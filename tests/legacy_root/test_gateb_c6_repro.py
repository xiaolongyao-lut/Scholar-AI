#!/usr/bin/env python3
"""
C6 Reproducibility Test Harness

Validates that the pool export produces identical artifacts on consecutive reruns
with the same inputs, demonstrating deterministic export behavior required for C6.
"""

from __future__ import annotations

import json
from pathlib import Path

from literature_assistant.core.gateb_phase_b_pool_export import export_phase_b_pools


async def _deterministic_retrieval_collector(
    query_text: str,
    *,
    top_k: int,
    corpus: dict[str, object],
    keyword_graph: dict[str, object] | None = None,
    vector_store: object | None = None,
    query_vec: object | None = None,
    rerank_semaphore: object | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Return a stable tiny candidate set for reproducibility-only testing."""

    if not query_text.strip():
        raise ValueError("query_text cannot be empty")
    del corpus, keyword_graph, vector_store, query_vec, rerank_semaphore
    hits = [
        {
            "doc_id": "doc-1",
            "chunk_id": "doc-1_chunk_0",
            "title": "Deterministic Paper",
            "content": "alpha",
        },
        {
            "doc_id": "doc-2",
            "chunk_id": "doc-2_chunk_0",
            "title": "Secondary Paper",
            "content": "beta",
        },
    ]
    return {
        "bm25": hits[:top_k],
        "dense": list(reversed(hits[:top_k])),
        "graph": [],
        "rrf": hits[:top_k],
        "rerank": [],
    }


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def run_export(
    goldset_path: Path,
    eval_queries_path: Path,
    pool_output: Path,
    annotation_output: Path,
    top_k: int = 10,
) -> dict[str, object]:
    """Run the pool export and return the result including output hashes."""

    return export_phase_b_pools(
        goldset_path=goldset_path,
        eval_queries_path=eval_queries_path,
        pool_output_path=pool_output,
        annotation_output_path=annotation_output,
        corpus={
            "chunks": [
                {"doc_id": "doc-1", "chunk_id": "doc-1_chunk_0", "title": "Deterministic Paper", "content": "alpha"},
                {"doc_id": "doc-2", "chunk_id": "doc-2_chunk_0", "title": "Secondary Paper", "content": "beta"},
            ]
        },
        retrieval_collector=_deterministic_retrieval_collector,
        top_k=top_k,
    )


def test_c6_reproducible_export_identical_hashes_across_reruns(tmp_path: Path) -> None:
    """
    C6 Reproducibility Proof:
    Verify that running the same export twice with identical inputs produces
    identical output artifacts (matching hashes).
    """
    goldset = tmp_path / "gateb_goldset.jsonl"
    eval_queries = tmp_path / "eval_queries_v2.1.jsonl"
    _write_jsonl(
        goldset,
        [
            {
                "query_id": "q_gateb_0001",
                "query_text": "deterministic reproducibility",
                "original_query_id": "q_original_0001",
                "source_stratum": "synthetic",
                "source_template_id": "template-c6",
            }
        ],
    )
    _write_jsonl(
        eval_queries,
        [
            {
                "query_id": "q_original_0001",
                "query_text": "deterministic reproducibility",
                "evidence_set": [{"doc_id": "doc-1"}],
            }
        ],
    )
    
    # First run
    run1_pool = tmp_path / ".test_c6_pools_run1.jsonl"
    run1_annot = tmp_path / ".test_c6_annot_run1.jsonl"
    
    result1 = run_export(goldset, eval_queries, run1_pool, run1_annot, top_k=10)
    hash1_pools = result1.get("reproducibility_metadata", {}).get("output_hashes", {}).get("pool_output")
    hash1_annot = result1.get("reproducibility_metadata", {}).get("output_hashes", {}).get("annotation_output")
    query_count1 = result1.get("query_count")
    
    print(f"\n[RUN 1] Queries: {query_count1}")
    print(f"[RUN 1] Pool hash:       {hash1_pools}")
    print(f"[RUN 1] Annotation hash: {hash1_annot}")
    
    # Second run (identical inputs and settings)
    run2_pool = tmp_path / ".test_c6_pools_run2.jsonl"
    run2_annot = tmp_path / ".test_c6_annot_run2.jsonl"
    
    result2 = run_export(goldset, eval_queries, run2_pool, run2_annot, top_k=10)
    hash2_pools = result2.get("reproducibility_metadata", {}).get("output_hashes", {}).get("pool_output")
    hash2_annot = result2.get("reproducibility_metadata", {}).get("output_hashes", {}).get("annotation_output")
    query_count2 = result2.get("query_count")
    
    print(f"\n[RUN 2] Queries: {query_count2}")
    print(f"[RUN 2] Pool hash:       {hash2_pools}")
    print(f"[RUN 2] Annotation hash: {hash2_annot}")
    
    # Verify reproducibility
    print("\n[VALIDATION]")
    assert query_count1 == query_count2, "Query count mismatch between runs"
    print(f"✓ Query counts match: {query_count1}")
    
    assert hash1_pools == hash2_pools, f"Pool hash mismatch: {hash1_pools} != {hash2_pools}"
    print(f"✓ Pool artifact hashes match: {hash1_pools[:16]}...")
    
    assert hash1_annot == hash2_annot, f"Annotation hash mismatch: {hash1_annot} != {hash2_annot}"
    print(f"✓ Annotation artifact hashes match: {hash1_annot[:16]}...")
    
    print("\n[SUCCESS] C6 Reproducibility: ✓ DETERMINISTIC EXPORT CONFIRMED")
    print(f"Identical inputs/settings produce identical artifact hashes across reruns.")
    

if __name__ == "__main__":
    raise SystemExit("Run this test with pytest.")
