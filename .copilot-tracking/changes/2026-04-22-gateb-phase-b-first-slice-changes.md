<!-- markdownlint-disable-file -->
# Release Changes: gateb phase b first slice

**Related Plan**: `2026-04-22-gateb-phase-b-first-slice.md`
**Implementation Date**: 2026-04-22

## Summary

This slice adds an offline Phase B pool export for the current 36 scaffold queries, preserves source labels and original evidence docs, emits a separate annotation input artifact, and leaves the canonical goldset/qrels pair unchanged.

## Changes

### Added

- `gateb_phase_b_pool_export.py` - Added the offline pool-export module and CLI that reads the 36-query scaffold, recovers original evidence docs, builds deduplicated per-query candidate pools, and writes separate pool plus annotation-input JSONL artifacts.
- `tests/test_gateb_phase_b_pool_export.py` - Added focused regressions for doc-level deduplication, source-label preservation, annotation-record shaping, and canonical goldset immutability during export.
- `artifacts/eval_audit/gateb_phase_b_pools.jsonl` - Added the generated detailed per-query pool export for the current 36 scaffold queries.
- `artifacts/eval_audit/gateb_phase_b_annotation_input.jsonl` - Added the generated annotation-ready input artifact derived from the exported Phase B pools.
- `.copilot-tracking/plans/2026-04-22-gateb-phase-b-first-slice.md` - Added the slice-local tracking plan for the Phase B first-pass export.
- `.copilot-tracking/changes/2026-04-22-gateb-phase-b-first-slice-changes.md` - Added the release-ready tracking file for this Phase B slice.
- `.squad/decisions/inbox/trinity-gateb-doc-level-pools.md` - Added the implementation decision note for doc-level pool deduplication with retained representative chunk previews.

### Modified

- `artifacts/eval_audit/GATEB_PHASE_B_GUIDE.md` - Updated the Phase B guide to point reviewers at the implemented pooling command and the two new export artifacts while keeping annotation work explicitly pending.

### Removed

- None.

## Release Summary

**Total Files Affected**: 8

### Files Created (7)

- `gateb_phase_b_pool_export.py` - Offline Phase B pool export entrypoint and helper logic.
- `tests/test_gateb_phase_b_pool_export.py` - Regression coverage for the new export path.
- `artifacts/eval_audit/gateb_phase_b_pools.jsonl` - Detailed per-query candidate pools for the 36 scaffold queries.
- `artifacts/eval_audit/gateb_phase_b_annotation_input.jsonl` - Annotation-input artifact derived from the pool export.
- `.copilot-tracking/plans/2026-04-22-gateb-phase-b-first-slice.md` - Slice-local implementation checklist.
- `.copilot-tracking/changes/2026-04-22-gateb-phase-b-first-slice-changes.md` - Slice-local release tracking log.
- `.squad/decisions/inbox/trinity-gateb-doc-level-pools.md` - Team decision note for doc-level pooling.

### Files Modified (1)

- `artifacts/eval_audit/GATEB_PHASE_B_GUIDE.md` - Documented the implemented pooling slice and artifact paths.

### Files Removed (0)

- None.

### Dependencies & Infrastructure

- **New Dependencies**: none
- **Updated Dependencies**: none
- **Infrastructure Changes**: none
- **Configuration Updates**: none

### Deployment Notes

Run `py -3 gateb_phase_b_pool_export.py` from the repo root to refresh the two Phase B export artifacts after scaffold or retrieval-path changes.

