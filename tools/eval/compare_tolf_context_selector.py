from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "literature_assistant" / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tolf_text_selector import select_tolf_context_chunks


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"JSONL file not found: {path}")

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise TypeError(f"JSONL row {line_number} must be an object")
            rows.append(payload)
    return rows


def _chunk_content(chunk: Mapping[str, Any]) -> str:
    return str(
        chunk.get("content")
        or chunk.get("raw_content")
        or chunk.get("text")
        or chunk.get("source_text")
        or ""
    ).strip()


def _chunk_key(chunk: Mapping[str, Any], index: int) -> str:
    chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
    if chunk_id:
        return chunk_id
    material_id = str(chunk.get("material_id") or "").strip()
    return f"{material_id or 'chunk'}:{index}"


def _normalize_chunk_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        content = _chunk_content(row)
        if not content:
            continue
        chunk = dict(row)
        chunk_id = _chunk_key(chunk, index)
        chunk["chunk_id"] = chunk_id
        chunk.setdefault("id", chunk_id)
        chunk["content"] = content
        chunks.append(chunk)
    return chunks


def _query_text(row: Mapping[str, Any], index: int) -> tuple[str, str]:
    query_id = str(row.get("query_id") or row.get("id") or f"q_{index + 1:04d}").strip()
    query = str(row.get("query_text") or row.get("query") or "").strip()
    if not query:
        raise ValueError(f"query row {index + 1} has no query_text/query")
    return query_id, query


def _score_default_chunks(query: str, chunks: Sequence[Mapping[str, Any]], top_k: int) -> list[dict[str, Any]]:
    from routers.resources_router import _score_chunks_for_query, _select_diverse_top_chunks

    scored = _score_chunks_for_query([dict(chunk) for chunk in chunks], query)
    selected = _select_diverse_top_chunks(scored, top_k=top_k)
    return [
        {"score": round(float(score), 4), **dict(chunk)}
        for score, chunk in selected
        if float(score) > 0
    ]


def _ids(chunks: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(chunk.get("chunk_id") or chunk.get("id") or "").strip() for chunk in chunks]


def compare_context_selectors(
    queries: Sequence[Mapping[str, Any]],
    chunks: Sequence[Mapping[str, Any]],
    *,
    top_k: int = 5,
    max_queries: int | None = None,
    embedding_dim: int = 64,
    max_candidates: int = 45,
) -> dict[str, Any]:
    """Compare default project chunk search with text-only TOLF selection.

    Args:
        queries: Query rows containing ``query_text`` or ``query``.
        chunks: Chunk rows containing content/text and optional provenance.
        top_k: Positive number of chunks selected by each method.
        max_queries: Optional positive query cap.
        embedding_dim: Positive local hashing embedding dimension.
        max_candidates: Positive prefilter cap before TOLF.

    Returns:
        JSON-serializable comparison report.

    Raises:
        ValueError: If numeric arguments are invalid or query rows are malformed.
        TypeError: If queries/chunks are not sequences.
    """
    if isinstance(queries, (str, bytes)) or not isinstance(queries, Sequence):
        raise TypeError("queries must be a sequence of mapping objects")
    if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
        raise TypeError("chunks must be a sequence of mapping objects")
    if not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    if max_queries is not None and (not isinstance(max_queries, int) or max_queries <= 0):
        raise ValueError("max_queries must be a positive integer when provided")
    if not isinstance(embedding_dim, int) or embedding_dim <= 0:
        raise ValueError("embedding_dim must be a positive integer")
    if not isinstance(max_candidates, int) or max_candidates <= 0:
        raise ValueError("max_candidates must be a positive integer")

    normalized_chunks = _normalize_chunk_rows(chunks)
    query_rows = list(queries[:max_queries] if max_queries is not None else queries)
    comparisons: list[dict[str, Any]] = []

    for index, row in enumerate(query_rows):
        if not isinstance(row, Mapping):
            continue
        query_id, query = _query_text(row, index)
        default_hits = _score_default_chunks(query, normalized_chunks, top_k)
        try:
            tolf_hits = select_tolf_context_chunks(
                query,
                default_hits or normalized_chunks,
                top_k=top_k,
                embedding_dim=embedding_dim,
                max_candidates=max_candidates,
            )
        except (RuntimeError, TypeError, ValueError):
            tolf_hits = []

        default_ids = _ids(default_hits)
        tolf_ids = _ids(tolf_hits)
        overlap = [chunk_id for chunk_id in default_ids if chunk_id in set(tolf_ids)]
        comparisons.append(
            {
                "query_id": query_id,
                "query_text": query,
                "default_top_ids": default_ids,
                "tolf_top_ids": tolf_ids,
                "overlap_ids": overlap,
                "only_default_ids": [chunk_id for chunk_id in default_ids if chunk_id not in set(tolf_ids)],
                "only_tolf_ids": [chunk_id for chunk_id in tolf_ids if chunk_id not in set(default_ids)],
                "overlap_at_top_k": round(len(overlap) / max(1, top_k), 4),
                "tolf_source_labels": [
                    list(hit.get("source_labels") or [])
                    for hit in tolf_hits
                ],
                "tolf_query_overlap_tokens": [
                    list(hit.get("query_overlap_tokens") or [])
                    for hit in tolf_hits
                ],
            }
        )

    mean_overlap = (
        round(sum(float(item["overlap_at_top_k"]) for item in comparisons) / len(comparisons), 4)
        if comparisons
        else 0.0
    )
    return {
        "schema_version": "tolf-context-selector-comparison/v1",
        "input": {
            "query_count": len(comparisons),
            "chunk_count": len(normalized_chunks),
            "top_k": top_k,
            "embedding_backend": "local_hashing_text_only",
            "embedding_dim": embedding_dim,
            "external_api_calls": 0,
        },
        "summary": {
            "mean_overlap_at_top_k": mean_overlap,
            "queries_with_tolf_hits": sum(1 for item in comparisons if item["tolf_top_ids"]),
        },
        "comparisons": comparisons,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare default project chunk search with text-only TOLF context selection.")
    parser.add_argument("--queries", required=True, help="JSONL file with query_id/query_text rows.")
    parser.add_argument("--chunks", required=True, help="JSONL file with project-like chunk rows.")
    parser.add_argument("--output", required=True, help="Output JSON report path.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-queries", type=int, default=None)
    parser.add_argument("--embedding-dim", type=int, default=64)
    parser.add_argument("--max-candidates", type=int, default=45)
    args = parser.parse_args()

    report = compare_context_selectors(
        _load_jsonl(Path(args.queries)),
        _load_jsonl(Path(args.chunks)),
        top_k=args.top_k,
        max_queries=args.max_queries,
        embedding_dim=args.embedding_dim,
        max_candidates=args.max_candidates,
    )
    _write_json(Path(args.output), report)
    print(json.dumps({"status": "ok", "output": args.output, "query_count": report["input"]["query_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
