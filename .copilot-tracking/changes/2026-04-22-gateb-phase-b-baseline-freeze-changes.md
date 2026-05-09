<!-- markdownlint-disable-file -->
# Release Changes: Gate B Phase B Baseline Freeze

**Related Plan**: `morpheus-2026-04-22-gateb-next-slice-after-c6-pass.md`  
**Implementation Date**: 2026-04-22

## Summary

Froze the verified Phase B annotation baseline by recording exact artifact paths, SHA256 hashes, and 36-query scope lock. Created reviewer-ready baseline freeze documentation and decision note to hand off to Orchestration for annotator assignment. No code changes; data governance and artifact registry only.

## Changes

### Added

- `artifacts/eval_audit/GATEB_PHASE_B_BASELINE_FREEZE.md` - Baseline freeze artifact documenting canonical pair (pools + annotation_input), locked SHA256 hashes, 36-query scope, and workflow bindings for annotators.
- `.squad/decisions/inbox/oracle-gateb-phase-b-baseline-freeze.md` - Decision note recording rationale, facts, blockers, and human dependencies for baseline freeze handoff.

### Modified

- None (baseline freeze is read-only; no mutations to canonical artifacts or code).

### Removed

- None

## Locked Baseline

| Artifact | Path | SHA256 | Query Count |
|----------|------|--------|-------------|
| Pool Export | `artifacts/eval_audit/gateb_phase_b_pools.jsonl` | `a553d1e396d3fc380c430470d5b3405cacf2422ab3739ab25a93ddb255f48f59` | 36 |
| Annotation Input | `artifacts/eval_audit/gateb_phase_b_annotation_input.jsonl` | `f86ede18bbce875df9665d445c1aaa9c6b11c4ff9856282c0396d8a7dab5233f` | 36 |

## Canonical References (Unchanged)

| Artifact | Path | Purpose |
|----------|------|---------|
| Goldset | `artifacts/eval_audit/gateb_goldset.jsonl` | 36 trusted queries, all `no_gold=true`, empty qrels arrays |
| TREC Qrels | `artifacts/eval_audit/gateb_qrels.tsv` | Header-only, awaiting annotation |

## Verification

✅ 36 queries verified across all three artifacts (goldset, pools, annotation_input)  
✅ Query IDs identical and in same order  
✅ Canonical pair stable (no mutations)  
✅ Ralph C6 reproducibility fix applied (deterministic hashes)  
✅ Ready for annotator assignment

## Human Dependencies Remaining

1. **Annotator assignment** (primary domain expert: laser welding)
2. **Reviewer assignment** (secondary for κ overlap)
3. **Annotation scoring** (judgments: 0/1/2 relevance for ~1,080 query-doc pairs)
4. **κ validation** (Cohen's κ ≥ 0.6 on ≥10% overlap sample)

## Next Blocking Steps

- Morpheus announces annotator and reviewer identities
- Annotators begin scoring against frozen pool
- Upon completion: κ validation → qrels update → Gate B eval

## Release Summary

**Total Files Affected**: 2

### Files Created (2)
- `artifacts/eval_audit/GATEB_PHASE_B_BASELINE_FREEZE.md` - Baseline freeze registry with locked hashes, 36-query scope, annotation workflow bindings
- `.squad/decisions/inbox/oracle-gateb-phase-b-baseline-freeze.md` - Decision note documenting rationale, blockers, and handoff to Orchestration

### Files Modified (0)
- None

### Files Removed (0)
- None

### Dependencies & Infrastructure
- **New Dependencies**: None
- **Updated Dependencies**: None
- **Infrastructure Changes**: None (read-only governance artifacts)
- **Configuration Updates**: None

### Deployment Notes

This slice is **non-blocking and read-only**. It does not require code deployment or environment changes. The frozen hashes serve as a reference point for all downstream annotation and qa-gate phases. Any changes to the retrieval stack, corpus, or pooling logic require a new explicit gate decision before annotation can proceed.

---

**Status**: ✅ BASELINE FROZEN — Awaiting annotator assignment
