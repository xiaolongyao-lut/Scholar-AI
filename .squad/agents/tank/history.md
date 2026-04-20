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
