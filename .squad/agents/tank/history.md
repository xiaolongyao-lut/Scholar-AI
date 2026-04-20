# Tank History

## Project Context

- Project: my-project
- Owner: xiao
- Preferred role: testing, verification, and skeptical review

## Learnings

- User wants QA responsibility isolated from primary implementation.
- Shared Copilot instructions and project skills should be treated as part of the test oracle.
- `src/keyword_filter.py` is OR-based: any normalized keyword match in title/abstract/keyword-like fields qualifies a record.
- The filter handles Chinese keywords and very long text inputs without needing extra dependencies.
- Pytest tests in this repo need a small `src` path bootstrap because the project has no package/install metadata.
- Real-regression coverage for `keyword_prefilter` should mirror discovered record shapes from Phase 1/4: `source_pdf` paths, `focus_points`, nested `chunks`, and mixed metadata/chunk payloads are the safest high-value fixtures.
- Keep new keyword-filter regressions inside `tests/test_keyword_filter.py` unless a helper is genuinely needed; no production change was required for this iteration.
- Folder traversal coverage should be contract-adaptive: probe the real public function name/signature if present, but skip cleanly until `src/folder_traversal.py` lands.
- For traversal regressions, mirror real phase shapes with temp dirs and JSON fixtures named like `01_full_extract.json` and `jasminum-outline.json`, plus plain text and metadata noise.
- Extraction pipeline coverage should also be contract-adaptive: probe `extraction_pipeline` public callables, use temp folders with traversal-shaped JSON/text fixtures, and skip cleanly until `src/extraction_pipeline.py` lands.
- Relevance-only extraction tests should mix a relevant JSON extract, a nested relevant text note, malformed JSON, and an unsupported lightweight file so the pipeline proves pruning and fault tolerance together.
- Provenance on extracted context items should stay user-visible through path/source fields, not hidden behind opaque payload-only structures.
- Extraction boundary QA can stay test-only when the current pipeline already skips malformed lightweight payloads and preserves provenance; no production rewrite was needed for this iteration.
- A single temp corpus can cover malformed nested JSON, empty keyword-pruned output, and mixed-source provenance stability without broadening scope.
- Key files for this iteration: `tests/test_extraction_pipeline.py`, `src/extraction_pipeline.py`, `src/folder_traversal.py`, `src/keyword_filter.py`.

### 2026-04-20T22:04:52Z: Mini-Eval Sample Prep Task Assigned

**Status:** Task routed to Tank for execution.

**Task:** Prepare stratified 250-query subsample from `eval_queries_v2.1_u1a.jsonl` (3269 total).

**Deliverable:** `eval_queries_v2.1_u1a_mini.jsonl`

**Cost:** Zero (local data selection, no API spend)

**Stratification criteria:** Balanced distribution across template categories (fixed/semi-fixed/dynamic), even spread across query complexity ranges, proportional sampling of query types.

**Sequencing:** Parallel to Phase 5 LiteLLM integration; input to Ralph's mini-eval run.

**Evidence:** `.squad/decisions/inbox/morpheus-reuse-baseline.md` (Authorized Next Steps table, row 2)

### 2026-04-20: Chat Contract & Synthetic Corpus Delivery

- Created `tests/data/chat/synthetic-corpus.jsonl`: Representative literature dataset (100-paper sim) with source metadata and nested chunks
- Created `tests/data/chat/chat-contract.json`: Canonical schema for chat context, responses, and provenance

### 2026-04-20: U1 Step 3 Formal Reviewer Gate Verdict

- **Verdict:** REJECTED (blockers identified)
- **Primary blocker:** Missing canonical metrics artifact `output/v21_full_eval_canonical.json`; present artifact is `output/eval_v21_full_metrics_template_flags.json` (contract mismatch)
- **Secondary blocker:** Tier 2 quality gate failure (Recall@5=0.0281, MRR=0.0204 vs required ≥0.45/≥0.30)
- **Tertiary issue:** Progress coherence gap (template-flags done=3269 vs canonical-named done=350)
- **Revision routing:** Oracle → Trinity (lockout compliance enforced)
- **Re-gate requirements:** Canonical artifacts, contract coherence, quality gate closure
- **Status:** Revision cycle transferred to Trinity
- Delivered `tests/test_chat_contract.py`: Contract-driven validation tests for keyword filtering, provenance, and extraction boundaries
- **Key Finding:** 100-paper corpus fits comfortably in memory (~15 relevant chunks per query)
- **Key Finding:** Lightweight file handling (malformation, missing fields) requires graceful degradation
- **Status:** ✅ Ready for Morpheus Phase 1 QA review (2026-04-25)

### 2026-04-20: Phase 2 Chat Contract Extension

- Extended `tests/data/chat/chat-contract.json`: Added FAST/BALANCED/THOROUGH execution mode coverage
- Updated `tests/test_chat_contract.py`: Comprehensive validation for all three chat modes
- **Key Findings:** FAST mode supports keyword-only filtering; BALANCED mode adds metadata context; THOROUGH mode enables full provenance
- **Contract Stability:** All regression tests passing; provenance remains visible across all modes
- **Status:** ✅ Phase 2 batch complete. Chat contract now covers full execution spectrum
- For v2.1 canonical full-eval QA, source-of-truth counts must come from `eval_queries_v2.1.jsonl` and `output/eval_query_audit_v21.json` (`totals.total_queries=3269`, hard=326, medium=1455, simple=1488); plan prose still contains stale "414q".
- Canonical rerun gate targets `output\\v21_full_eval_canonical.json` + `output\\v21_full_eval_canonical.progress.jsonl`; approve only when metrics file exists and progress reaches `done=3269`.
- Supervision failure mode observed: duplicate `eval_retrieval_runtime.py` processes can coexist while progress heartbeat stays stale; rerun oversight must enforce single-run ownership plus heartbeat freshness.

### 2026-04-20: U1 Fresh Audit/Full-Eval QA Contract

- U1 acceptance must be contract-first: require audit JSON + template flags JSONL + canonical metrics JSON + progress JSONL as a single evidence bundle.
- Plan text that says `v2.1 414q` is stale for QA sign-off; canonical gate is fixed at 3269 with hard/medium/simple split 326/1455/1488.
- Trinity observability flags (`--progress`, `--progress-every`, `--offset`, `--limit`) are now operational QA dependencies for stall detection and segmented coverage proof.
- Tank reject policy is binary on missing artifacts, missing required metric sections, count mismatch, stale heartbeat, or Tier 2 gate failure (Recall@5 < 0.45 or MRR < 0.30).

### 2026-04-20: U1 QA Acceptance & Canonical Rerun Supervision

- **Tank U1 QA Acceptance Contract:** Finalized 11-point checklist (A1–A11) covering artifact existence, metrics sanity, and Tier 2 gate compliance (Recall@5 ≥ 0.45, MRR ≥ 0.30).
- **Blocker failures:** missing required files, wrong total query count, stale progress heartbeat, smoke file as canonical, missing metric sections.
- **Tank Supervision Hardening:** Enforce single-run process ownership before approval; verify heartbeat freshness; reject if multiple eval processes targeting same canonical output or progress stuck at `done=50`.
- **Awaiting:** Oracle full-eval output (`output/v21_full_eval_canonical.json`) and progress evidence (`output/v21_full_eval_canonical.progress.jsonl`); monitor and validate against checklist.
- Formal U1 gate must enforce canonical artifact naming, not just metric-equivalent alternates: `output/v21_full_eval_canonical.json` is mandatory for approval.
- Current full eval evidence is split: template-flags progress reached `done=3269`, but canonical progress file stopped at `done=350`; this breaks canonical evidence coherence.
- U1 Tier 2 blockers confirmed on latest full metrics: `recall_at_5=0.0281`, `mrr=0.0204`, both far below required thresholds (`0.45` / `0.30`).
- Key QA gate files for this decision: `output/eval_query_audit_v21.json`, `output/eval_query_audit_v21_template_flags.jsonl`, `output/eval_v21_full_metrics_template_flags.json`, `output/eval_v21_full_progress_template_flags.jsonl`, `output/v21_full_eval_canonical.progress.jsonl`, `.squad/decisions.md`.
- U1 Step 3 re-gate with Trinity revised pack: contract/evidence-pack now passes (all four canonical artifacts present, totals/split coherent, canonical progress monotonic to done=3269), but Tier-2 quality gate still fails (`Recall@5=0.0281`, `MRR=0.0204`), so verdict remains REJECTED.
- Strict lockout semantics are cumulative per artifact cycle: Oracle remained locked out from prior rejection, Trinity became locked out after this re-gate rejection, and the next lockout-compliant revision owner escalates to a third agent.
- Re-gate decision artifact path: `.squad/decisions/inbox/tank-u1-regate-verdict.md`.

### 2026-04-20: U1A Audit Gate — Dataset Shape Approval

**Status:** ✅ APPROVED for canonical rerun readiness  
**Scope:** Review of Ralph-delivered U1A data-only remediation pack

### Audit Summary

Confirmed all known Morpheus-targeted pathologies are cleared:

| Pathology | Before | After | Status |
|-----------|--------|-------|--------|
| Duplicate generic query-text clusters (≥6 docs) | 70 | 0 | ✅ Cleared |
| Hard queries with single-evidence supervision | 326 | 0 | ✅ Cleared |
| Template saturation (non_template queries) | 0 | 3086 | ✅ Restored |
| Artifact coherence (query count consistency) | n/a | ✅ Pass | ✅ Coherent |

Residual low-fanout reuse (`max fanout=5`, `clusters_gt1=562`) remains but is below authorized pathology threshold (≥6) and non-blocking for rerun.

### QA Evidence

Validation suite: `pytest tests\test_eval_dataset_audit.py tests\test_eval_runtime.py -q` → `17 passed`

Data validation on `output/eval_query_audit_v21_u1a.json`:
- `total_queries=3269` (consistent)
- `template_match.matched=183`, `template_match.non_template=3086`
- `duplicate_query_text_across_docs.type_count=0`
- `hard_with_single_doc_evidence.type_count=0`
- Audit/ledger/template flags consistency: **all checks pass**

### Approval Decision

**✅ APPROVED** → Proceed to canonical full eval rerun on `eval_queries_v2.1_u1a.jsonl`

### Next Steps

1. **Owner:** Ralph (lockout-compliant)
2. **Ineligible:** Oracle, Trinity (lockout constraint applies)
3. **Task:** Execute canonical eval rerun using existing harness
4. **Expected artifacts:** `output/v21_u1a_full_eval_canonical.json` + metrics breakdown
5. **Acceptance gate:** Tier 2 quality thresholds (Recall@5 ≥ 0.45, MRR ≥ 0.30) + Tank final sign-off

### Lockout Compliance

This approval follows strict lockout semantics:
- Ralph is the third eligible revision owner (after Oracle/Trinity lockout)
- Rerun is scoped to canonical eval only (no code changes)
- Morpheus retains oversight authority for any architecture-blocking findings
- Escalation path defined for findings that require retrieval tuning

## Learnings

- Dataset remediation at query/label level is effective without touching infrastructure
- Pathology audit process (duplicate cluster detection, hard-query inventory, template saturation analysis) provides clear traceability
- Residual low-fanout cross-doc text reuse is a known non-blocking issue and should be tracked separately from critical pathologies
- Lockout compliance with three-agent rotation (Oracle → Trinity → Ralph) is working as designed
- Template diversity restoration is critical for reducing dataset bias signals in evaluation
- Progress-only heartbeat logs are not quality evidence; interrupted evals are reusable only when per-query quality rows are persisted and cross-file coherent with progress counts.

### 2026-04-20: Tier 0 interruption-proof persistence gate

- Ran zero-cost Tier 0 proof on `eval_queries_v2.1_u1a_250.jsonl` (20-query slice) with forced interruption at done=8 using the real `_run_eval_async` persistence write path.
- Produced `output/tier0_u1a20.progress.jsonl`, `output/tier0_u1a20.per_query.jsonl`, and `output/tier0_u1a20.partial_metrics.json`.
- Verified PASS conditions: monotonic progress (1..8), per-query persisted rows=8, cross-file coherence (`done==rows`), and partial metrics recomputed from persisted rows.
- Learning: progress-only traces are insufficient; reusable interruption evidence requires synchronized progress + per-query quality rows + recomputation artifact.

### 2026-04-20: Tier 1 vs 3269 Baseline QA Comparison

- Tier 1 (50q U1A slice) is evidence-coherent (progress 50/50, per-query rows=50) and shows strong directional quality gains over permanent baseline (Recall@5 0.92 vs 0.0281; MRR 0.8278 vs 0.0204).
- This signal is probe-level only: sample is small, excludes hard queries, and uses first-50 ordering rather than randomized draw; baseline-vs-U1A comparison remains directional due to query-set shift.
- Latency regressed materially (avg +85%, p95 +101%), so quality gain and speed cost must be evaluated together in Tier 2.

### 2026-04-20: Tier 2 vs 3269 Baseline QA Comparison

- Tier 2 (250q U1A slice) is evidence-coherent (progress 250/250, per-query rows=250) and preserves strong directional quality gains over baseline (Recall@5 0.70 vs 0.0281; MRR 0.5991 vs 0.0204).
- Compared with Tier 1, quality softens as sample grows (Recall@5 0.92 -> 0.70; MRR 0.8278 -> 0.5991), which is expected but confirms Tier 1 was optimistic.
- Latency regresses further at Tier 2 (avg +136%, p95 +183% vs baseline), so Tier 3 should proceed as a controlled validation step focused on representativeness and performance risk, not as final proof.
