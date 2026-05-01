#!/usr/bin/env python3
"""
C6 Reproducibility Test Harness

Validates that the pool export produces identical artifacts on consecutive reruns
with the same inputs, demonstrating deterministic export behavior required for C6.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_export(
    goldset_path: str,
    eval_queries_path: str,
    pool_output: str,
    annotation_output: str,
    top_k: int = 10,
) -> dict[str, str]:
    """Run the pool export and return the result including output hashes."""
    cmd = [
        sys.executable,
        "gateb_phase_b_pool_export.py",
        "--goldset", goldset_path,
        "--eval-queries", eval_queries_path,
        "--pool-output", pool_output,
        "--annotation-output", annotation_output,
        "--top-k", str(top_k),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout.strip())


def test_c6_reproducible_export_identical_hashes_across_reruns() -> None:
    """
    C6 Reproducibility Proof:
    Verify that running the same export twice with identical inputs produces
    identical output artifacts (matching hashes).
    """
    goldset = "artifacts/eval_audit/gateb_goldset.jsonl"
    eval_queries = "eval_queries_v2.1.jsonl"
    
    # First run
    run1_pool = "artifacts/eval_audit/.test_c6_pools_run1.jsonl"
    run1_annot = "artifacts/eval_audit/.test_c6_annot_run1.jsonl"
    
    result1 = run_export(goldset, eval_queries, run1_pool, run1_annot, top_k=10)
    hash1_pools = result1.get("reproducibility_metadata", {}).get("output_hashes", {}).get("pool_output")
    hash1_annot = result1.get("reproducibility_metadata", {}).get("output_hashes", {}).get("annotation_output")
    query_count1 = result1.get("query_count")
    
    print(f"\n[RUN 1] Queries: {query_count1}")
    print(f"[RUN 1] Pool hash:       {hash1_pools}")
    print(f"[RUN 1] Annotation hash: {hash1_annot}")
    
    # Second run (identical inputs and settings)
    run2_pool = "artifacts/eval_audit/.test_c6_pools_run2.jsonl"
    run2_annot = "artifacts/eval_audit/.test_c6_annot_run2.jsonl"
    
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
    
    # Cleanup test artifacts
    for path in [Path(run1_pool), Path(run1_annot), Path(run2_pool), Path(run2_annot)]:
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    test_c6_reproducible_export_identical_hashes_across_reruns()
