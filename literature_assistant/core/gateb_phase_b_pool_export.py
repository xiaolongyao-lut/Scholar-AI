from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from eval_retrieval_runtime import (
    ChunkVectorStore,
    _extract_candidate_doc_ids,
    _load_queries,
    _load_retrieval_corpus,
    _rrf_fuse,
    build_keyword_graph,
    graph_keyword_search,
    hybrid_search_async,
    rerank_async,
)
from project_paths import output_path


SOURCE_LABELS = ("bm25", "dense", "graph", "rrf", "rerank", "evidence_set")


def _get_git_commit_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _compute_file_hash(path: Path, algorithm: str = "sha256") -> str:
    """Compute stable hash of a file for reproducibility proof."""
    if not path.exists():
        return None
    hasher = hashlib.new(algorithm)
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _build_repro_metadata(
    goldset_path: Path,
    eval_queries_path: Path,
    pool_output_path: Path,
    annotation_output_path: Path,
    top_k: int,
    query_count: int,
) -> dict[str, Any]:
    """Build reproducibility metadata artifact (not persisted to outputs)."""
    return {
        "reproducibility_metadata": {
            "schema_version": "1.0",
            "export_timestamp": None,  # Set by caller if needed
            "git_commit_sha": _get_git_commit_sha(),
            "command_args": {
                "goldset": str(goldset_path),
                "eval_queries": str(eval_queries_path),
                "pool_output": str(pool_output_path),
                "annotation_output": str(annotation_output_path),
                "top_k": top_k,
            },
            "input_hashes": {
                "goldset": _compute_file_hash(goldset_path),
                "eval_queries": _compute_file_hash(eval_queries_path),
            },
            "output_hashes": {
                "pool_output": None,  # Set after file is written
                "annotation_output": None,  # Set after file is written
            },
            "query_count": query_count,
            "determinism_knobs": {
                "sort_candidates_by_source_index": True,
                "sort_candidates_by_best_rank": True,
                "sort_candidates_by_doc_id": True,
                "evidence_set_membership_stable": True,
            },
        }
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONL file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_original_query_index(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        query_id = str(record.get("query_id", "")).strip()
        if query_id:
            index[query_id] = record
    return index


def _normalize_doc_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, str(default))).strip())
    except (TypeError, ValueError):
        return int(default)


def resolve_doc_id(item: dict[str, Any], expected_doc_ids: set[str] | None = None) -> str | None:
    chunk_id = _normalize_doc_id(item.get("chunk_id"))
    chunk_doc_id = chunk_id.split("_chunk_")[0] if chunk_id and "_chunk_" in chunk_id else None
    ordered = [
        _normalize_doc_id(item.get("doc_id")),
        _normalize_doc_id(item.get("material_id")),
        _normalize_doc_id(item.get("id")),
        chunk_doc_id,
    ]
    expected = expected_doc_ids or set()
    for candidate in ordered:
        if candidate and candidate in expected:
            return candidate
    for candidate in ordered:
        if candidate:
            return candidate
    return None


def build_doc_lookup(chunks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        doc_id = resolve_doc_id(chunk)
        if not doc_id or doc_id in lookup:
            continue
        lookup[doc_id] = {
            "doc_id": doc_id,
            "title": str(chunk.get("title") or "").strip() or None,
            "chunk_id": str(chunk.get("chunk_id") or "").strip() or None,
            "content_preview": str(
                chunk.get("content") or chunk.get("claim") or chunk.get("text") or ""
            ).strip()[:400],
        }
    return lookup


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, str]:
    """Stable sort key for deterministic candidate ordering.
    
    Order:
    1. Source label index (bm25 < dense < graph < rrf < rerank < evidence_set)
    2. Best rank across sources (lower rank first)
    3. Doc ID (lexicographic for tie-breaking)
    
    This ensures identical ordering for same inputs/settings across reruns.
    """
    labels = candidate.get("source_labels", [])
    source_index = min(
        (SOURCE_LABELS.index(label) for label in labels if label in SOURCE_LABELS),
        default=len(SOURCE_LABELS),
    )
    source_ranks = candidate.get("source_ranks", {})
    best_rank = min(
        (
            int(rank)
            for label, rank in source_ranks.items()
            if label != "evidence_set" and isinstance(rank, int)
        ),
        default=9999,
    )
    doc_id = str(candidate.get("doc_id", ""))
    return (source_index, best_rank, doc_id)


def merge_query_candidates(
    *,
    goldset_record: dict[str, Any],
    original_query: dict[str, Any] | None,
    source_hits: dict[str, list[dict[str, Any]]],
    doc_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    original_evidence = (
        original_query.get("evidence_set", [])
        if isinstance(original_query, dict) and isinstance(original_query.get("evidence_set"), list)
        else []
    )
    expected_doc_ids = {
        _normalize_doc_id(item.get("doc_id"))
        for item in original_evidence
        if isinstance(item, dict) and _normalize_doc_id(item.get("doc_id"))
    }
    expected_doc_ids = {doc_id for doc_id in expected_doc_ids if doc_id}

    candidates_by_doc: dict[str, dict[str, Any]] = {}
    source_doc_ids: dict[str, list[str]] = {}

    for label in SOURCE_LABELS[:-1]:
        doc_ids_for_source: list[str] = []
        for rank, hit in enumerate(source_hits.get(label, []), start=1):
            if not isinstance(hit, dict):
                continue
            doc_id = resolve_doc_id(hit, expected_doc_ids=expected_doc_ids)
            if not doc_id:
                continue
            if doc_id not in doc_ids_for_source:
                doc_ids_for_source.append(doc_id)

            existing = candidates_by_doc.get(doc_id)
            if existing is None:
                fallback = doc_lookup.get(doc_id, {})
                existing = {
                    "doc_id": doc_id,
                    "title": str(hit.get("title") or fallback.get("title") or "").strip() or None,
                    "chunk_id": str(hit.get("chunk_id") or fallback.get("chunk_id") or "").strip()
                    or None,
                    "content_preview": str(
                        hit.get("content")
                        or hit.get("claim")
                        or hit.get("text")
                        or fallback.get("content_preview")
                        or ""
                    ).strip()[:400],
                    "source_labels": [],
                    "source_ranks": {},
                    "from_original_evidence": False,
                }
                candidates_by_doc[doc_id] = existing

            if label not in existing["source_labels"]:
                existing["source_labels"].append(label)
            existing["source_ranks"][label] = rank
            existing["source_hint"] = "+".join(existing["source_labels"])

        source_doc_ids[label] = doc_ids_for_source

    evidence_doc_ids: list[str] = []
    for evidence_item in original_evidence:
        if not isinstance(evidence_item, dict):
            continue
        doc_id = _normalize_doc_id(evidence_item.get("doc_id"))
        if not doc_id:
            continue
        if doc_id not in evidence_doc_ids:
            evidence_doc_ids.append(doc_id)
        existing = candidates_by_doc.get(doc_id)
        if existing is None:
            fallback = doc_lookup.get(doc_id, {})
            existing = {
                "doc_id": doc_id,
                "title": fallback.get("title"),
                "chunk_id": fallback.get("chunk_id"),
                "content_preview": fallback.get("content_preview") or "",
                "source_labels": [],
                "source_ranks": {},
                "from_original_evidence": False,
            }
            candidates_by_doc[doc_id] = existing
        if "evidence_set" not in existing["source_labels"]:
            existing["source_labels"].append("evidence_set")
        existing["from_original_evidence"] = True
        fallback = doc_lookup.get(doc_id, {})
        if fallback.get("title"):
            existing["title"] = fallback["title"]
        if fallback.get("chunk_id"):
            existing["chunk_id"] = fallback["chunk_id"]
        if fallback.get("content_preview"):
            existing["content_preview"] = fallback["content_preview"]
        existing["source_hint"] = "+".join(existing["source_labels"])

    source_doc_ids["evidence_set"] = evidence_doc_ids

    candidates = sorted(candidates_by_doc.values(), key=_candidate_sort_key)
    for candidate in candidates:
        candidate["source_hint"] = "+".join(candidate["source_labels"])

    return {
        "query_id": goldset_record.get("query_id"),
        "query_text": goldset_record.get("query_text"),
        "original_query_id": goldset_record.get("original_query_id"),
        "source_stratum": goldset_record.get("source_stratum"),
        "source_template_id": goldset_record.get("source_template_id"),
        "source_doc_ids": source_doc_ids,
        "pool_stats": {"candidate_count": len(candidates)},
        "candidates": candidates,
    }


def build_annotation_record(pool_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_id": pool_record.get("query_id"),
        "query_text": pool_record.get("query_text"),
        "original_query_id": pool_record.get("original_query_id"),
        "source_stratum": pool_record.get("source_stratum"),
        "source_template_id": pool_record.get("source_template_id"),
        "pool_size": int(pool_record.get("pool_stats", {}).get("candidate_count", 0)),
        "candidates": [
            {
                "doc_id": candidate.get("doc_id"),
                "title": candidate.get("title"),
                "chunk_id": candidate.get("chunk_id"),
                "content_preview": candidate.get("content_preview"),
                "source_labels": candidate.get("source_labels", []),
                "source_hint": candidate.get("source_hint"),
                "from_original_evidence": bool(candidate.get("from_original_evidence", False)),
            }
            for candidate in pool_record.get("candidates", [])
        ],
    }


async def collect_query_source_hits(
    query_text: str,
    *,
    top_k: int,
    corpus: dict[str, Any],
    keyword_graph: dict[str, Any] | None = None,
    vector_store: Any | None = None,
    query_vec: Any | None = None,
    rerank_semaphore: asyncio.Semaphore | None = None,
) -> dict[str, list[dict[str, Any]]]:
    hybrid_hits: list[dict[str, Any]] = []
    graph_hits: list[dict[str, Any]] = []
    dense_hits: list[dict[str, Any]] = []

    if hybrid_search_async is not None:
        try:
            hits = await hybrid_search_async(corpus, query_text, top_k=top_k)
            hybrid_hits = hits if isinstance(hits, list) else []
        except (RuntimeError, TypeError, ValueError):
            hybrid_hits = []

    if keyword_graph and graph_keyword_search is not None:
        try:
            chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
            graph_hits = graph_keyword_search(keyword_graph, chunks, query=query_text, top_k=top_k)
        except (RuntimeError, TypeError, ValueError):
            graph_hits = []

    if vector_store is not None and getattr(vector_store, "has_embeddings", False) and query_vec is not None:
        try:
            dense_hits = vector_store.cosine_search(query_vec, top_k=top_k)
        except (RuntimeError, TypeError, ValueError):
            dense_hits = []

    rrf_hits = _rrf_fuse([hybrid_hits, graph_hits, dense_hits], top_k=top_k)
    rerank_hits: list[dict[str, Any]] = []
    if rerank_async is not None and rrf_hits:
        try:
            rerank_hits = await rerank_async(
                query_text,
                rrf_hits,
                top_k=top_k,
                semaphore=rerank_semaphore,
            )
        except (RuntimeError, TypeError, ValueError):
            rerank_hits = []

    return {
        "bm25": hybrid_hits[:top_k],
        "dense": dense_hits[:top_k],
        "graph": graph_hits[:top_k],
        "rrf": rrf_hits[:top_k],
        "rerank": rerank_hits[:top_k],
    }


async def _export_phase_b_pools_async(
    *,
    goldset_records: list[dict[str, Any]],
    original_query_index: dict[str, dict[str, Any]],
    pool_output_path: Path,
    annotation_output_path: Path,
    corpus: dict[str, Any],
    retrieval_collector,
    top_k: int,
) -> dict[str, Any]:
    chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
    doc_lookup = build_doc_lookup(chunks)
    keyword_graph = build_keyword_graph(chunks) if build_keyword_graph and chunks else None

    vector_store = None
    query_vecs: list[Any] = [None] * len(goldset_records)
    if ChunkVectorStore is not None and chunks:
        cache_path = output_path("embedding_cache", "corpus_embeddings.npy")
        vector_store = await ChunkVectorStore.build(
            chunks,
            cache_path=cache_path,
            strict_cache_guard=True,
        )
        if vector_store.has_embeddings:
            query_texts = [str(record.get("query_text", "")) for record in goldset_records]
            try:
                query_vecs = await vector_store.batch_embed_queries(query_texts)
            except (RuntimeError, TypeError, ValueError):
                query_vecs = [None] * len(goldset_records)

    rerank_semaphore = asyncio.Semaphore(_env_int("SILICONFLOW_RERANK_CONCURRENCY", 3))

    pool_records: list[dict[str, Any]] = []
    annotation_records: list[dict[str, Any]] = []

    for index, goldset_record in enumerate(goldset_records):
        source_hits = await retrieval_collector(
            str(goldset_record.get("query_text", "")),
            top_k=top_k,
            corpus=corpus,
            keyword_graph=keyword_graph,
            vector_store=vector_store,
            query_vec=query_vecs[index] if index < len(query_vecs) else None,
            rerank_semaphore=rerank_semaphore,
        )
        pool_record = merge_query_candidates(
            goldset_record=goldset_record,
            original_query=original_query_index.get(str(goldset_record.get("original_query_id", "")).strip()),
            source_hits=source_hits,
            doc_lookup=doc_lookup,
        )
        pool_records.append(pool_record)
        annotation_records.append(build_annotation_record(pool_record))

    write_jsonl(pool_output_path, pool_records)
    write_jsonl(annotation_output_path, annotation_records)

    return {
        "query_count": len(pool_records),
        "pool_output_path": str(pool_output_path),
        "annotation_output_path": str(annotation_output_path),
    }


def export_phase_b_pools(
    *,
    goldset_path: Path,
    eval_queries_path: Path,
    pool_output_path: Path,
    annotation_output_path: Path,
    corpus: dict[str, Any] | None = None,
    retrieval_collector=None,
    top_k: int = 10,
) -> dict[str, Any]:
    goldset_records = load_jsonl(goldset_path)
    original_query_index = build_original_query_index(_load_queries(eval_queries_path))
    active_corpus = corpus if corpus is not None else _load_retrieval_corpus()
    collector = retrieval_collector or collect_query_source_hits
    
    result = asyncio.run(
        _export_phase_b_pools_async(
            goldset_records=goldset_records,
            original_query_index=original_query_index,
            pool_output_path=pool_output_path,
            annotation_output_path=annotation_output_path,
            corpus=active_corpus,
            retrieval_collector=collector,
            top_k=top_k,
        )
    )
    
    # Compute output file hashes for reproducibility proof
    pool_hash = _compute_file_hash(pool_output_path)
    annotation_hash = _compute_file_hash(annotation_output_path)
    
    # Build reproducibility metadata
    repro_meta = _build_repro_metadata(
        goldset_path,
        eval_queries_path,
        pool_output_path,
        annotation_output_path,
        top_k,
        len(goldset_records),
    )
    
    # Update output hashes in metadata
    repro_meta["reproducibility_metadata"]["output_hashes"]["pool_output"] = pool_hash
    repro_meta["reproducibility_metadata"]["output_hashes"]["annotation_output"] = annotation_hash
    
    # Merge repro metadata into result for visibility
    result.update(repro_meta)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Gate B Phase B deduplicated candidate pools for scaffold queries."
    )
    parser.add_argument(
        "--goldset",
        default="artifacts\\eval_audit\\gateb_goldset.jsonl",
        help="Canonical scaffold goldset JSONL.",
    )
    parser.add_argument(
        "--eval-queries",
        default="eval_queries_v2.1.jsonl",
        help="Original eval query JSONL used to recover evidence_set.",
    )
    parser.add_argument(
        "--pool-output",
        default="artifacts\\eval_audit\\gateb_phase_b_pools.jsonl",
        help="Detailed per-query pool export JSONL.",
    )
    parser.add_argument(
        "--annotation-output",
        default="artifacts\\eval_audit\\gateb_phase_b_annotation_input.jsonl",
        help="Annotation-ready JSONL derived from the pool export.",
    )
    parser.add_argument("--top-k", type=int, default=10, help="Per-source retrieval depth.")
    args = parser.parse_args()

    result = export_phase_b_pools(
        goldset_path=Path(args.goldset),
        eval_queries_path=Path(args.eval_queries),
        pool_output_path=Path(args.pool_output),
        annotation_output_path=Path(args.annotation_output),
        top_k=args.top_k,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
