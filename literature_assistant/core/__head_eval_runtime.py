from __future__ import annotations

import asyncio
import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

try:
    from layers.r_layer_hybrid_retriever import hybrid_search as hybrid_search_async
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    hybrid_search_async = None

try:
    from graph_keyword_retriever import build_keyword_graph, graph_keyword_search
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    build_keyword_graph = None
    graph_keyword_search = None

try:
    from chunk_vector_store import ChunkVectorStore
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    ChunkVectorStore = None

try:
    from reranker_client import rerank_async
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    rerank_async = None

from project_paths import output_path


def _calculate_mrr(relevance_list: list[bool]) -> float:
    for idx, is_rel in enumerate(relevance_list):
        if is_rel:
            return 1.0 / (idx + 1)
    return 0.0


def _calculate_recall_at_k(relevance_list: list[bool], k: int) -> float:
    return 1.0 if any(relevance_list[:k]) else 0.0


def _extract_candidate_doc_ids(hit: dict[str, Any]) -> set[str]:
    candidates = {
        str(hit.get("material_id", "")).strip(),
        str(hit.get("doc_id", "")).strip(),
        str(hit.get("id", "")).strip(),
    }
    chunk_id = str(hit.get("chunk_id", "")).strip()
    if chunk_id and "_chunk_" in chunk_id:
        candidates.add(chunk_id.split("_chunk_")[0])
    return {x for x in candidates if x}


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "aggregated_metrics": {
                "recall_at_1": 0.0,
                "recall_at_3": 0.0,
                "recall_at_5": 0.0,
                "recall_at_10": 0.0,
                "mrr": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
            },
            "per_difficulty": {},
        }

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    latencies = sorted(float(r.get("latency_ms", 0.0)) for r in results)
    p95_idx = min(len(latencies) - 1, int(len(latencies) * 0.95))

    aggregated = {
        "recall_at_1": _avg([float(r.get("recall_at_1", 0.0)) for r in results]),
        "recall_at_3": _avg([float(r.get("recall_at_3", 0.0)) for r in results]),
        "recall_at_5": _avg([float(r.get("recall_at_5", 0.0)) for r in results]),
        "recall_at_10": _avg([float(r.get("recall_at_10", 0.0)) for r in results]),
        "mrr": _avg([float(r.get("mrr", 0.0)) for r in results]),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
        "p95_latency_ms": round(latencies[p95_idx], 2),
    }

    per_difficulty: dict[str, dict[str, Any]] = {}
    for diff in sorted({str(r.get("difficulty", "unknown")) for r in results}):
        subset = [r for r in results if str(r.get("difficulty", "unknown")) == diff]
        per_difficulty[diff] = {
            "count": len(subset),
            "recall_at_5": _avg([float(r.get("recall_at_5", 0.0)) for r in subset]),
            "mrr": _avg([float(r.get("mrr", 0.0)) for r in subset]),
        }

    return {
        "aggregated_metrics": aggregated,
        "per_difficulty": per_difficulty,
    }


def _load_queries(queries_path: Path) -> list[dict[str, Any]]:
    if not queries_path.exists():
        raise FileNotFoundError(f"Query file not found: {queries_path}")
    with queries_path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _load_retrieval_corpus() -> dict[str, Any]:
    """加载 chunk_store 目录下所有 JSON，支持多种格式：

    - list[dict]               → 直接展平
    - {"chunks": list[dict]}   → 取 chunks 字段
    - {material_id: list[dict]}→ 按 material 分组（resources_router 产出格式）
    """
    chunk_store_dir = output_path("chunk_store")
    if not chunk_store_dir.exists():
        return {"chunks": []}

    chunks: list[dict[str, Any]] = []
    for fp in chunk_store_dir.glob("*.json"):
        try:
            with fp.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, list):
                chunks.extend([x for x in payload if isinstance(x, dict)])
            elif isinstance(payload, dict):
                # 格式 1: {"chunks": [...]}
                raw = payload.get("chunks")
                if isinstance(raw, list):
                    chunks.extend([x for x in raw if isinstance(x, dict)])
                else:
                    # 格式 2: {material_id: [chunk, ...], ...}
                    for _key, val in payload.items():
                        if isinstance(val, list):
                            chunks.extend([x for x in val if isinstance(x, dict)])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return {"chunks": chunks}


async def _retrieve(
    query_text: str,
    corpus: dict[str, Any],
    top_k: int,
    *,
    keyword_graph: dict[str, Any] | None = None,
    vector_store: Any | None = None,
    query_vec: Any | None = None,
    use_rerank: bool = True,
    rerank_top_n: int = 20,
    rerank_semaphore: Any | None = None,
) -> list[dict[str, Any]]:
    hybrid_hits: list[dict[str, Any]] = []
    graph_hits: list[dict[str, Any]] = []
    dense_hits: list[dict[str, Any]] = []

    if hybrid_search_async:
        try:
            hits = await hybrid_search_async(corpus, query_text, top_k=top_k)
            hybrid_hits = hits if isinstance(hits, list) else []
        except (RuntimeError, TypeError, ValueError):
            hybrid_hits = []

    if keyword_graph and graph_keyword_search:
        try:
            chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
            graph_hits = graph_keyword_search(keyword_graph, chunks, query=query_text, top_k=top_k)
        except (RuntimeError, TypeError, ValueError):
            graph_hits = []

    if vector_store is not None:
        try:
            dense_hits = await _dense_retrieve_precomputed(vector_store, query_vec, top_k)
        except (RuntimeError, TypeError, ValueError):
            dense_hits = []

    merged_hits = _rrf_fuse([hybrid_hits, graph_hits, dense_hits], top_k=max(top_k, rerank_top_n))
    if use_rerank and rerank_async and merged_hits:
        try:
            return await rerank_async(
                query_text, merged_hits[:rerank_top_n], top_k=top_k, semaphore=rerank_semaphore
            )
        except (RuntimeError, TypeError, ValueError):
            pass
    return merged_hits[:top_k]


async def _dense_retrieve_precomputed(
    vector_store: Any, query_vec: Any, top_k: int
) -> list[dict[str, Any]]:
    """Dense retrieval with a pre-computed query vector (no API call)."""
    if query_vec is None:
        return []
    return vector_store.cosine_search(query_vec, top_k=top_k)


def _rrf_fuse(rank_lists: list[list[dict[str, Any]]], top_k: int, rrf_k: int = 60) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion for multiple ranked lists."""
    score_map: dict[str, float] = {}
    item_map: dict[str, dict[str, Any]] = {}

    def _item_key(item: dict[str, Any]) -> str:
        chunk_id = str(item.get("chunk_id", "")).strip()
        if chunk_id:
            return f"chunk::{chunk_id}"
        material_id = str(item.get("material_id", "")).strip()
        text = str(item.get("content") or item.get("claim") or item.get("text") or "").strip()
        return f"mat::{material_id}::{hash(text)}"

    for rank_list in rank_lists:
        for rank, item in enumerate(rank_list):
            if not isinstance(item, dict):
                continue
            key = _item_key(item)
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in item_map:
                item_map[key] = dict(item)

    ranked = sorted(score_map.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    fused: list[dict[str, Any]] = []
    for key, score in ranked:
        item = dict(item_map[key])
        item["rrf_score"] = round(score, 6)
        fused.append(item)
    return fused


def run_eval(
    queries_path: str = "eval_queries_v1.0.jsonl",
    output_path: str = "BASELINE_METRICS.json",
    top_k: int = 10,
    use_rerank: bool = True,
    rerank_top_n: int = 30,
) -> dict[str, Any]:
    queries = _load_queries(Path(queries_path))
    corpus = _load_retrieval_corpus()

    # Pre-build keyword graph once.
    keyword_graph: dict[str, Any] | None = None
    if build_keyword_graph:
        chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
        if chunks:
            keyword_graph = build_keyword_graph(chunks)

    # Run async portion (build vector store + batch embed queries + retrieve) in one event loop
    results = asyncio.run(
        _run_eval_async(
            queries,
            corpus,
            keyword_graph,
            top_k,
            use_rerank=use_rerank,
            rerank_top_n=rerank_top_n,
        )
    )

    summary = aggregate_metrics(results)
    payload = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_queries": len(queries),
        **summary,
    }

    with Path(output_path).open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return payload


async def _run_eval_async(
    queries: list[dict[str, Any]],
    corpus: dict[str, Any],
    keyword_graph: dict[str, Any] | None,
    top_k: int,
    *,
    use_rerank: bool,
    rerank_top_n: int,
) -> list[dict[str, Any]]:
    """Async eval loop — single event-loop, batch query embedding."""

    # Pre-build vector store for dense retrieval.
    vector_store = None
    if ChunkVectorStore is not None:
        chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
        if chunks:
            cache_path = output_path("embedding_cache", "corpus_embeddings.npy")
            vector_store = await ChunkVectorStore.build(chunks, cache_path=cache_path)

    # Pre-embed all query texts in batch (avoids 414 individual API calls)
    query_texts = [str(q.get("query_text", "")) for q in queries]
    query_vecs: list[Any] = [None] * len(queries)
    if vector_store is not None and vector_store.has_embeddings:
        try:
            query_vecs = await vector_store.batch_embed_queries(query_texts)
        except (RuntimeError, TypeError, ValueError):
            pass

    rerank_semaphore = asyncio.Semaphore(
        int(os.getenv("SILICONFLOW_RERANK_CONCURRENCY", "8"))
    ) if use_rerank else None

    async def _eval_one(i: int, q: dict[str, Any]) -> dict[str, Any]:
        query_text = query_texts[i]
        difficulty = str(q.get("difficulty_level", "unknown"))
        evidence = q.get("evidence_set", []) if isinstance(q.get("evidence_set", []), list) else []
        expected_doc_ids = {
            str(item.get("doc_id", "")).strip() for item in evidence if isinstance(item, dict)
        }
        expected_doc_ids = {x for x in expected_doc_ids if x}

        t0 = time.perf_counter()
        hits = await _retrieve(
            query_text, corpus, top_k=top_k,
            keyword_graph=keyword_graph,
            vector_store=vector_store,
            query_vec=query_vecs[i],
            use_rerank=use_rerank,
            rerank_top_n=rerank_top_n,
            rerank_semaphore=rerank_semaphore,
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        relevance_list: list[bool] = []
        for hit in hits:
            if not isinstance(hit, dict):
                relevance_list.append(False)
                continue
            candidate_ids = _extract_candidate_doc_ids(hit)
            relevance_list.append(bool(candidate_ids.intersection(expected_doc_ids)))

        return {
            "query_id": q.get("query_id"),
            "difficulty": difficulty,
            "latency_ms": latency_ms,
            "recall_at_1": _calculate_recall_at_k(relevance_list, 1),
            "recall_at_3": _calculate_recall_at_k(relevance_list, 3),
            "recall_at_5": _calculate_recall_at_k(relevance_list, 5),
            "recall_at_10": _calculate_recall_at_k(relevance_list, 10),
            "mrr": _calculate_mrr(relevance_list),
        }

    results: list[dict[str, Any]] = list(
        await asyncio.gather(*[_eval_one(i, q) for i, q in enumerate(queries)])
    )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run retrieval evaluation.")
    parser.add_argument("--queries", default="eval_queries_v1.0.jsonl")
    parser.add_argument("--output", default="BASELINE_METRICS.json")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--rerank-top-n", type=int, default=20)
    parser.add_argument("--no-rerank", action="store_true")
    args = parser.parse_args()

    final_metrics = run_eval(
        queries_path=args.queries,
        output_path=args.output,
        top_k=args.top_k,
        use_rerank=not args.no_rerank,
        rerank_top_n=args.rerank_top_n,
    )
    agg = final_metrics.get("aggregated_metrics", {})
    print("Evaluation completed.")
    print(
        f"Recall@5={agg.get('recall_at_5', 0.0)} | "
        f"MRR={agg.get('mrr', 0.0)} | "
        f"P95={agg.get('p95_latency_ms', 0.0)}ms"
    )
