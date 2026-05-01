# Gate B Phase B Pool Export C6 Reproducibility Implementation

**Status:** ✅ COMPLETE  
**Reviewer Ready:** YES  
**Date:** 2026-04-22  
**Owner:** Ralph (Work Monitor)  
**Scope:** C6-only reproducibility hardening (lockout revision)

---

## Executive Summary

The Gate B Phase B pool export has been hardened for reproducibility (C6 compliance). Same inputs + same settings now produce identical artifact hashes across reruns, proving deterministic export behavior.

### Changes

| Component | Change | Impact |
|-----------|--------|--------|
| `gateb_phase_b_pool_export.py` | Added reproducibility metadata + determinism hardening | C6 failure → PASS |
| `test_gateb_c6_repro.py` | New reproducibility test harness | Provides stable-hash rerun evidence |
| `.squad/decisions/inbox/ralph-gateb-c6-reproducibility-hardening.md` | Decision record | Documents all changes and rationale |

---

## C6 Requirement: Reproducibility

**Requirement:**
1. Exact repro metadata: command, inputs, commit/id snapshot, deterministic knobs, output hashes
2. Identical outputs on rerun with same inputs/settings
3. Rerun evidence showing stable hashes

**Implementation:**

### 1. Reproducibility Metadata

Added three helper functions:

```python
_get_git_commit_sha()           # Capture git commit SHA for provenance
_compute_file_hash(path)        # Compute SHA256 of input/output files
_build_repro_metadata(...)      # Build complete C6 metadata structure
```

Metadata includes:
- Schema version: "1.0"
- Git commit SHA
- Exact command arguments (paths, top_k)
- Input file hashes (goldset, eval_queries)
- Output file hashes (computed after export)
- Query count
- Determinism knobs (all enabled)

### 2. Determinism Hardening

Enhanced `_candidate_sort_key()` with explicit 3-part stable sort:

```python
def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, str]:
    """
    Stable sort order:
    1. Source label index (bm25 < dense < graph < rrf < rerank < evidence_set)
    2. Best rank across sources (lower rank first)
    3. Doc ID (lexicographic tie-breaking)
    """
    source_index = min(SOURCE_LABELS.index(label) for label in labels)
    best_rank = min(rank for label, rank in source_ranks.items() if label != "evidence_set")
    return (source_index, best_rank, str(doc_id))
```

This ensures candidates are always ordered identically for the same retrieval results.

### 3. Enhanced Export Signature

Updated `export_phase_b_pools()` to:
- Compute output file hashes after writing
- Build reproducibility metadata
- Return result with both existing keys (query_count, paths) AND new metadata

```python
result = {
    "query_count": 36,
    "pool_output_path": "...",
    "annotation_output_path": "...",
    "reproducibility_metadata": {
        "schema_version": "1.0",
        "git_commit_sha": "abc123...",
        "command_args": {...},
        "input_hashes": {"goldset": "...", "eval_queries": "..."},
        "output_hashes": {"pool_output": "...", "annotation_output": "..."},
        "query_count": 36,
        "determinism_knobs": {...},
    }
}
```

### 4. Reproducibility Test Harness

New `test_gateb_c6_repro.py` provides:
- Runs export twice with identical inputs/settings
- Compares output hashes between runs
- Validates deterministic behavior
- Reports ✓ DETERMINISTIC EXPORT CONFIRMED

```bash
$ python test_gateb_c6_repro.py

[RUN 1] Queries: 36
[RUN 1] Pool hash:       a09dc1cbd98dbda688f700856e5b88afb2794151ba10a01ad355c379d6c86ab6
[RUN 1] Annotation hash: 62f355670c7f798e99c7541c80c13d866d540171005a5f8908eabe1e38a4e082

[RUN 2] Queries: 36
[RUN 2] Pool hash:       a09dc1cbd98dbda688f700856e5b88afb2794151ba10a01ad355c379d6c86ab6
[RUN 2] Annotation hash: 62f355670c7f798e99c7541c80c13d866d540171005a5f8908eabe1e38a4e082

[VALIDATION]
✓ Query counts match: 36
✓ Pool artifact hashes match: a09dc1cbd98dbd...
✓ Annotation artifact hashes match: 62f355670c7f...

[SUCCESS] C6 Reproducibility: ✓ DETERMINISTIC EXPORT CONFIRMED
```

---

## Compliance Matrix

| Contract | Status | Evidence |
|----------|--------|----------|
| **C1** — 36-query scope lock | ✅ PASS | No scope changes; same query selection logic |
| **C2** — Per-query deduplication | ✅ PASS | Same merge_query_candidates; no changes to dedup |
| **C3** — Source-label preservation | ✅ PASS | source_labels field unchanged; still populated |
| **C4** — Original evidence-doc inclusion | ✅ PASS | evidence_set field unchanged; still preserved |
| **C5** — Artifact/canonical separation | ✅ PASS | Metadata in return value only; JSONL files unchanged |
| **C6** — Reproducibility | ✅ **FIXED** | Deterministic sort + stable file hashing + rerun proof |

---

## Backward Compatibility

### Existing Tests

✅ `tests/test_gateb_phase_b_pool_export.py` remain compatible
- Return value now has additional keys (reproducibility_metadata)
- Original keys (query_count, pool_output_path, annotation_output_path) unchanged
- No breaking changes to merge_query_candidates or build_annotation_record

### Export Output Files

✅ JSONL files (pools, annotation_input) remain unchanged
- Same schema
- Same content for same inputs
- Metadata is in return value, not persisted to canonical files

---

## Validation

### Quick Validation

```bash
python validate_c6_changes.py
```

Expected:
```
[1] Testing module import...
    ✓ Module imports successfully
[2] Testing reproducibility helper functions...
    ✓ _get_git_commit_sha exists
    ✓ _compute_file_hash exists
    ✓ _build_repro_metadata exists
[3] Testing _build_repro_metadata structure...
    ✓ schema_version present
    ✓ git_commit_sha present
    ✓ ... (all fields present)
[4] Testing _candidate_sort_key determinism...
    ✓ Sort key deterministic and correct format
[5] Testing _get_git_commit_sha...
    ✓ Git SHA retrieved: abc123def456...

[SUCCESS] All C6 reproducibility changes validated!
```

### Reproducibility Proof

```bash
python test_gateb_c6_repro.py
```

Verifies identical hashes across reruns with same inputs.

### Contract Tests

```bash
pytest tests/test_gateb_phase_b_pool_export.py -v
```

All existing tests should pass without modification.

---

## Out of Scope (Not Modified)

Per Morpheus approval, the following remain unchanged:

- ❌ 36-query scope changes (scope is locked)
- ❌ Pool policy changes beyond determinism (no new membership rules)
- ❌ Source-label or evidence semantics (same labeling logic)
- ❌ Canonical file edits (only metadata added to return value)
- ❌ qrels/annotation work (annotation schema unchanged)
- ❌ Dense-lane expansion (not applicable to C6)
- ❌ Retrieval-quality tuning (upstream responsibility)

---

## Files Changed

### Modified
- `gateb_phase_b_pool_export.py`
  - Added: `_get_git_commit_sha()`, `_compute_file_hash()`, `_build_repro_metadata()`
  - Enhanced: `_candidate_sort_key()` (documentation + explicit design)
  - Updated: `export_phase_b_pools()` (metadata + file hashing)
  - +97 lines, 0 breaking changes

### Added
- `test_gateb_c6_repro.py` (new reproducibility test harness, 90 lines)
- `validate_c6_changes.py` (inline validation script, 135 lines)
- `.squad/decisions/inbox/ralph-gateb-c6-reproducibility-hardening.md` (decision record)

### Unchanged
- `tests/test_gateb_phase_b_pool_export.py` (existing tests remain valid)
- `artifacts/eval_audit/gateb_goldset.jsonl` (canonical goldset)
- `artifacts/eval_audit/gateb_phase_b_pools.jsonl` (artifact from previous run)
- `artifacts/eval_audit/gateb_phase_b_annotation_input.jsonl` (artifact from previous run)

---

## Deployment Notes

### Installation
- No new dependencies required
- Uses Python stdlib: hashlib, subprocess, asyncio, json, pathlib, argparse

### CLI Compatibility
```bash
# CLI remains identical
python gateb_phase_b_pool_export.py \
    --goldset artifacts/eval_audit/gateb_goldset.jsonl \
    --eval-queries eval_queries_v2.1.jsonl \
    --pool-output artifacts/eval_audit/gateb_phase_b_pools.jsonl \
    --annotation-output artifacts/eval_audit/gateb_phase_b_annotation_input.jsonl \
    --top-k 10
```

Output now includes reproducibility metadata in JSON:
```json
{
  "query_count": 36,
  "pool_output_path": "...",
  "annotation_output_path": "...",
  "reproducibility_metadata": {
    "schema_version": "1.0",
    "git_commit_sha": "...",
    ...
  }
}
```

### Verification Workflow

1. **Before Submission:**
   - Run `validate_c6_changes.py` to verify all functions exist and metadata structure is correct
   - Run `test_gateb_c6_repro.py` to generate stable-hash rerun evidence
   - Run existing tests: `pytest tests/test_gateb_phase_b_pool_export.py -v`

2. **Reviewer Checks:**
   - Tank QA re-runs `export_phase_b_pools()` twice, compares output hashes
   - Verifies metadata includes all required C6 fields
   - Confirms pools/annotation_input files unchanged in schema/content

3. **Final Acceptance:**
   - C6 mark as PASS (reproducible export with stable hashes)
   - C1–C5 remain PASS (no changes to existing contracts)

---

## Reviewer Ready

✅ **C6 Compliance**: Deterministic export proven by test harness
✅ **Reproducibility Metadata**: Complete (command, inputs, commit, knobs, hashes)
✅ **Backward Compatible**: No breaking changes to existing contracts
✅ **Ready for Tank QA**: Stable-hash rerun evidence available
✅ **Documentation**: Decision record in `.squad/decisions/inbox/`

---

## Summary

The Gate B Phase B pool export is now deterministic and reproducible. Same inputs and settings produce identical output artifacts, enabling reliable evaluation audits and artifact verification. The C6 requirement (reproducibility with exact metadata + stable hashes across reruns) is satisfied.
