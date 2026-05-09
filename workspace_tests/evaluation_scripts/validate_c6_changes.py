#!/usr/bin/env python3
"""Quick inline validation of C6 reproducibility changes."""

import sys
import tempfile
from pathlib import Path

# Add repo to path
repo_root = Path(__file__).resolve().parent
sys.path.insert(0, str(repo_root))

# Test 1: Module imports without error
print("[1] Testing module import...")
try:
    import gateb_phase_b_pool_export as exporter
    print("    ✓ Module imports successfully")
except Exception as e:
    print(f"    ✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Helper functions exist
print("\n[2] Testing reproducibility helper functions...")
required_funcs = [
    "_get_git_commit_sha",
    "_compute_file_hash",
    "_build_repro_metadata",
]
for func_name in required_funcs:
    if hasattr(exporter, func_name):
        print(f"    ✓ {func_name} exists")
    else:
        print(f"    ✗ {func_name} missing")
        sys.exit(1)

# Test 3: _build_repro_metadata structure
print("\n[3] Testing _build_repro_metadata structure...")
try:
    # Create dummy paths in temp dir
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        goldset = test_dir / "goldset.jsonl"
        queries = test_dir / "queries.jsonl"
        pools = test_dir / "pools.jsonl"
        annot = test_dir / "annot.jsonl"
        
        # Write dummy files
        for p in [goldset, queries]:
            p.write_text("test content\n")
        
        meta = exporter._build_repro_metadata(goldset, queries, pools, annot, top_k=10, query_count=5)
        
        # Check structure
        assert "reproducibility_metadata" in meta, "Missing reproducibility_metadata key"
        rm = meta["reproducibility_metadata"]
        
        required_keys = [
            "schema_version",
            "git_commit_sha",
            "command_args",
            "input_hashes",
            "output_hashes",
            "query_count",
            "determinism_knobs",
        ]
        
        for key in required_keys:
            assert key in rm, f"Missing key in metadata: {key}"
            print(f"    ✓ {key} present")
        
        # Verify nested structures
        assert rm["query_count"] == 5, "query_count not set"
        assert rm["output_hashes"]["pool_output"] is None, "pool_output hash should be None initially"
        assert rm["determinism_knobs"]["sort_candidates_by_source_index"] is True
        print("    ✓ All metadata fields correct")
    
except Exception as e:
    print(f"    ✗ Metadata test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Candidate sort key function
print("\n[4] Testing _candidate_sort_key determinism...")
try:
    candidate1 = {
        "doc_id": "doc-1",
        "source_labels": ["bm25", "rerank"],
        "source_ranks": {"bm25": 1, "rerank": 3},
    }
    
    key1 = exporter._candidate_sort_key(candidate1)
    key2 = exporter._candidate_sort_key(candidate1)
    
    assert key1 == key2, f"Sort key not deterministic: {key1} != {key2}"
    assert isinstance(key1, tuple) and len(key1) == 3, "Sort key should be 3-tuple"
    print(f"    ✓ Sort key deterministic and correct format: {key1}")
    
except Exception as e:
    print(f"    ✗ Sort key test failed: {e}")
    sys.exit(1)

# Test 5: Git SHA retrieval
print("\n[5] Testing _get_git_commit_sha...")
try:
    sha = exporter._get_git_commit_sha()
    if sha == "unknown":
        print(f"    ⚠ Git not available, got: {sha}")
    else:
        assert len(sha) >= 7, f"Git SHA too short: {sha}"
        print(f"    ✓ Git SHA retrieved: {sha[:12]}...")
except Exception as e:
    print(f"    ✗ Git SHA test failed: {e}")
    sys.exit(1)

print("\n" + "="*60)
print("[SUCCESS] All C6 reproducibility changes validated!")
print("="*60)
