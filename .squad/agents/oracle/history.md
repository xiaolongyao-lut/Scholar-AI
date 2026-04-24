# Oracle History

## Project Context

- Project: my-project
- Owner: xiao
- Preferred role: data generation, label work, and benchmark support

## Recent Milestones

- **2026-04-24: Goldset 100 Final Approval — Tank APPROVED** (Tank issued final verdict on regenerated canonical 100-query goldset; former 64 scaffold entries fully adjudicated; schema/qrels/provenance validated; hard-goldset acceptance gate closed)
- **2026-04-24: Goldset Re-Review Input — 100-Query Artifact Set (Tank CONDITIONAL APPROVE)** (Tank's re-review confirms first-pass 100-query artifact set ready for adjudication workflow; schema/provenance validated; 64 review-needed entries require human judgment; next gate = regenerate canonical set post-adjudication)
- **2026-04-24: Goldset Rejection Audit — Oracle Build Unblocked** (Morpheus audit confirms Tank's rejection applies only to 36/40 artifacts; fresh 100-query build can continue unblocked; entry conditions for next review = 100-query scope + Zotero provenance + schema validation + no synthetic root)
- **2026-04-24: Persistence Lane Bottleneck Analysis — Complete** (Router import instability = HIGH; async I/O bloat = MEDIUM; health checks = MEDIUM; Phase 1: create `routers/__init__.py` → 0.5s speedup)
- **2026-04-24: Gate B Phase B Sign-Off — PASS** (36-query goldset schema-valid; annotation-ready; path hygiene issue flagged)

## Learnings

- User explicitly wants a dedicated data specialist for tasks like generating structured batches or evaluation datasets.
- Data work should be routed early instead of being treated as cleanup after implementation.

### 2026-04-24: Router Import Stability Audit

- **Scope:** Root cause analysis of Tank's pytest collection failure on `tests/test_runtime_router_contract.py`
- **Verdict:** ✅ Root cause identified and minimal fix proposed
- **Key findings:**
  - `routers/` directory lacks `__init__.py` → Python treats as namespace package
  - Bare `from models import (...)` in routers becomes ambiguous import path
  - PEP 420 resolver searches `routers.models` first, fails, never reaches top-level `models`
  - Works in server context (root path setup) but fails in pytest (submodule import context)
- **Fix:** Create `routers/__init__.py` (empty file)
  - Converts namespace package → regular package
  - Eliminates import ambiguity
  - One file, zero code changes
  - No runtime impact
- **Verification:** Pre/post collection and full test run commands documented
- **Decision ref:** `.squad/decisions.md` (Router Import Path Stability entry)

### 2026-04-22: Gate B Review-Chain Milestone — Oracle Review Pass

- **Scope:** Annotation artifact review (gateb_goldset.jsonl + gateb_qrels.tsv)
- **Verdict:** ✅ PASS (36 queries, 343 candidates verified, schema-valid, no data-side blockers)
- **Key findings:**
  - All 36 queries retain consistent field structure and provenance chain
  - 343 total candidates verified across S1/S2/S3 strata
  - gateb_goldset.jsonl passes validator; qrels.tsv header-ready structure correct
  - Only seeded from trusted `gateb_initial_candidates.jsonl` (40 entries); 4 S4 placeholders properly excluded
- **Next:** Trinity preflight + Morpheus final gate → Ralph canonical merge authorization
- **Decision ref:** `.squad/decisions/inbox/oracle-annotation-review.md`

### Phase 4: Real-Record Validation (2026-04-20)
- **Key discovery:** "Record" in extraction pipeline context means a single chunk, not a full paper. Each chunk retains source PDF and paper title as metadata.
- **Sampling insight:** Introduction chunks are meta-heavy (journal headers, conference markers). Full-paper validation would need chunks from body and methods sections for complete keyword coverage.
- **Filter confidence:** `keyword_prefilter.py` correctly implements OR semantics, case-insensitive substring matching, and Unicode normalization. Tested against 10 real samples across 3 scenarios; zero false positives, appropriate recall rate (70% on high-relevance keywords, 10% on specific parameters, 0% on rare technologies).
- **Unicode handling:** Mixed English/Chinese titles, chunk text, and PDFs processed without encoding errors. NFKC normalization is working as intended.
- **Next-phase readiness:** Function is production-ready for retrieval pipeline. Recommend chunk-level granularity for search (not full-paper aggregation) to maximize precision.

### Phase 5: Real-Data Extraction Validation (2026-04-21)
- **Scope:** Validated `extract_literature_context()` on 109 laser-processing papers (13,926 chunks total)
- **High-relevance keywords test:** ["laser", "nitriding", "surface"] → 3,584 items from 282 files (25.7% of baseline). Content distribution: 95% chunks, 3% focus_points, 2% titles.
- **Technical parameters test:** ["temperature", "hardness", "scanning speed"] → 1,317 items from 97 files (9.5% of baseline). Higher precision due to parameter-specific matching.
- **Irrelevant keyword test:** ["PTFE"] → 0 items extracted. Confirmed files without matches are NOT expanded (efficiency goal met).
- **Provenance preservation:** 100% of 2,835+ sampled items retain full provenance (source_file, relative_path, chunk_id, section_title). All items conform to output schema.
- **Unicode coverage:** Zero encoding failures on mixed English/Chinese text; NFKC normalization working correctly across all 109 papers.
- **Content type distribution:** full_extract (94%), hybrid_retrieval (5%), writing_material_pack (1%) across entire dataset.
- **Item schema:** All extracted items include content, content_type, provenance (source_root, path, record_type), and metadata (chunk_id, chunk_index where applicable).
- **Production readiness:** Function is PASS for retrieval pipeline. Recommend adding ranking layer in next phase for result ordering.

### Phase U1: Eval Audit + Full-Run Kickoff (2026-04-20)
- **Canonical query count:** `eval_queries_v2.1.jsonl` currently contains 3,269 queries, not the stale `414q` wording in `docs/superpowers/plans/2026-04-20-latest-unified-plan.md`.
- **Audit result:** Reproduced `output/eval_query_audit_v21.json` and `output/eval_query_audit_v21_template_flags.jsonl`; both are non-empty and report `matched=3269`, `missing=0`.
- **Validation command:** `pytest tests\test_eval_dataset_audit.py tests\test_eval_runtime.py -q` passed `17/17`, confirming audit + template-bucket eval wiring before the long run.
- **Execution pattern:** Full eval should be launched with explicit metrics output plus heartbeat logging: `python eval_retrieval_runtime.py --queries eval_queries_v2.1.jsonl --template-flags output/eval_query_audit_v21_template_flags.jsonl --output output/v21_full_eval_canonical.json --progress output/v21_full_eval_canonical.progress.jsonl --progress-every 25`.
- **Operational caveat:** For persistence, the first attached run was replaced by a detached run; the shared progress file now contains both stopped-run and live-run heartbeats, so future monitoring must read the newest timestamps only.

### U1 Step 2 & 3 Checkpoint (2026-04-20)
- **U1 Step 2 COMPLETE:** Canonical audit artifacts finalized and validated; all wiring tests pass.
- **U1 Step 3 IN PROGRESS:** Full eval launched as detached background job with `--progress` and `--progress-every 25` flags for observability.
- **Oracle responsibilities:** Monitor `output/v21_full_eval_canonical.progress.jsonl` for heartbeat freshness; validate metrics JSON when written; extract Recall@5, MRR, per_template_bucket for Tank approval.
- **Tank approval gate:** 11-point checklist (A1–A11) including artifact presence, query count match (3269), Tier 2 gate pass (Recall@5 ≥ 0.45, MRR ≥ 0.30), and run integrity verification.
- **Critical path:** Awaiting metrics file completion; 60-min hard timeout enforced; single-process ownership required per supervision rule.

### U1 Step 3 Revision Lockout (2026-04-20)
- **Event:** Tank formal reviewer gate verdict issued: REJECTED
- **Blocker analysis:** (1) Missing canonical metrics `output/v21_full_eval_canonical.json`, (2) Tier 2 quality gate failure (Recall@5=0.0281 vs ≥0.45), (3) progress coherence gap (template-flags vs canonical-named)
- **Lockout enforcement:** Oracle locked out from immediate revision cycle per strict rejection protocol
- **Revision owner:** Transferred to Trinity

### Rerank Pipeline Alignment (2026-04-21)
- **Chunk-rerank trace:** Verified raw_content prioritization in reranker; embedding uses content (post-context); no mismatch detected.
- **Key finding:** Embedding cache independent of reranker model; remains valid across model updates.
- **Multimodal ready:** Pipeline extensible to image+text when needed; no current image extraction in chunking pipeline.
- **Final decision:** Text-only qwen3-rerank confirmed stable; Morpheus audit + Tank regressions + final config alignment complete.
- **Orchestration:** Decisions consolidated to `.squad/decisions/decisions.md` with full evidence trail.
- **Oracle next steps:** Wait for Trinity remediation; available for data support tasks outside U1 revision scope

### Pipeline Architecture Verification (2026-04-21)
- **Task:** Trace chunk-embedding-rerank pipeline end-to-end; verify qwen3-vl-rerank integration
- **Scope:** chunk_models.py → contextual_chunker.py → chunk_vector_store.py → eval_retrieval_runtime.py → reranker_client.py
- **Key finding:** Pipeline correctly handles text-only input. `_extract_document()` prioritizes `raw_content` (undecorated) over `content` (context-decorated). Reranker receives clean chunk text as intended.
- **Chunk data structure:** EnrichedChunk carries both `content` (post-context) for embedding and `raw_content` (original) for reranking—no mismatch.
- **Multimodal readiness:** qwen3-vl-rerank capable of image+text but currently pipeline extracts text only; extensible when Phase 6+ requires visual reranking.
- **Decision:** No code changes needed. Pipeline production-ready for text reranking. Future multimodal support requires figure/table extraction in chunk phase and request format update.
- **Evidence:** reranker_client.py:83–95, contextual_chunker.py:164–220, test_reranker.py:261–309 all validate correct behavior.
- **Formal decision:** `.squad/decisions/inbox/oracle-chunk-trace.md` written; team coordination complete.

### Gate B Phase A Trusted Input Production (2026-04-22)
- **Task:** Build canonical Gate B goldset and qrels from repo-local trusted sources
- **Input:** `artifacts/eval_audit/gateb_initial_candidates.jsonl` (40 candidates, trusted)
- **Output:** `artifacts/eval_audit/gateb_goldset.jsonl` (36 schema-valid queries) + `artifacts/eval_audit/gateb_qrels.tsv` (TREC format)
- **Scope limitation:** S4 placeholders (query_text=null) excluded as user-authored; 36/40 candidates converted to reviewer-ready scaffolds
- **Constraints honored:** Root `gateb_goldset.jsonl` NOT used as input (forbidden); no fabricated provenance or judgments; schema validation passes
- **Artifact quality:** All records have `no_gold=true`, empty `qrels` arrays (honest about annotation blocker); strata S1=16, S2=10, S3=10
- **Precise blocker:** Human annotation requires (1) pooling tool to build candidate pools, (2) relevance judgments (0/1/2) for 20-40 docs per query, (3) Cohen's κ ≥ 0.6 validation
- **What unblocked:** Reviewers can inspect queries and provenance; pooling tool can proceed; schema-valid structure ready for annotation data
- **What remains blocked:** Evaluation cannot run (empty qrels); Gate B pass criteria unchecked; Gate C trigger decision blocked
- **Script:** `scripts/build_gateb_phase_a_trusted.py` (reproducible, no manual edits)
- **Decision:** `.squad/decisions/inbox/oracle-gateb-phase-a-scaffold.md` documents completion of first legal trusted-input production slice

### Gate B Phase B Reviewed Annotation Audit (2026-04-22)
- **Task:** Data-side audit of user-reviewed in-place annotations in `artifacts/eval_audit/gateb_phase_b_annotation_input.jsonl`
- **Scope lock result:** PASS — current file hash changed from frozen baseline to `cee338e774f11c5af0ccdf8982bdf55f0c2f9cde1d628ceb4f14fa4bc1914802`, but all 36 locked query IDs remain present in canonical order and exactly match `artifacts/eval_audit/gateb_phase_b_pools.jsonl`
- **Coverage result:** 36 queries, 343 judged candidates total; per-query candidate coverage matches pool export exactly with no missing or extra `(doc_id, chunk_id)` identities
- **Schema result:** All candidate judgments contain valid `relevance` in {0,1,2} and valid `judged_at` ISO-Z timestamps; no missing candidate arrays, no duplicate query IDs, no duplicate candidate identities, no conflicting duplicate judgments
- **Operational note:** All 343 candidates share the same `judged_at` timestamp (`2026-04-22T14:32:13Z`), which is acceptable as a batch-reviewed artifact but should be preserved verbatim in audit-side outputs
- **Downstream contract:** Working transforms should now treat this annotated JSONL as the authoritative reviewed source, flattening `(query_id, doc_id, relevance)` for review-stage qrels generation while retaining `chunk_id`, `judged_at`, and provenance metadata in sidecar audit outputs until canonical writes are approved

### Phase 6 Contextual Chunks Eval Attempt (2026-04-22)
- **Task:** Execute `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md` §3.3 E1-E4 contextual-vs-non-contextual evaluation and emit `eval_reports/2026-04-*` artifacts.
- **Prep completed:** Read plan/context files, verified cache-separation logic in `chunk_vector_store.py`, and ran targeted baseline checks: `pytest tests\test_eval_runtime.py tests\test_dense_rrf_retrieval.py tests\test_contextual_chunker.py -q` → **43 passed**.
- **Blocker:** First E1 run failed before any progress/per-query artifact was written. `eval_retrieval_runtime.py` attempted to build non-contextual embeddings and raised `chunk_vector_store.EmbeddingAPIError` with `last_status=401, body='"Api key is invalid"'`.
- **Evidence:** Only contextual cache exists at `output/embedding_cache/corpus_embeddings_contextual.npy` + manifest (`chunk_count=6293`, `is_contextual=true`), while `output/chunk_store/laser_welding_109_chunks.json` currently has 2911 chunks and no embedded vectors. No reusable non-contextual cache (`corpus_embeddings.npy`) exists.
- **Decision:** Hold Phase 6 default-switch decision until a valid embedding credential is restored or a matching non-contextual cache is prebuilt. Do **not** fake results with polluted contextual cache or dense-disabled fallback.
- **Artifacts written:** `eval_reports/2026-04-phase6-comparison.md` blocker report; decision note `\.squad\decisions\inbox\oracle-phase6-eval.md`.

### 2026-04-24: Fallback Contract Analysis + Router Import Audit — Complete

**Scope 1: Fallback Contract Analysis**
- **Task:** Verify backend/frontend chat contract supports Gemini → Copilot fallback detection
- **Verdict:** ✅ No backend changes required; contract already complete and safe
- **Key findings:**
  - Frontend tracks attempted + active provider in fallback metadata
  - Backend returns actual model in `ChatResponse.model` field
  - UI displays both when fallback occurs; no conflicts
  - `model` field correctly extracted from LLM provider response via `_extract_chat_response()`
- **Evidence:** Full audit documented in `.squad/decisions.md` (Fallback Contract Analysis section)

**Scope 2: Router Import Audit**
- **Task:** Root cause analysis of Tank's pytest collection failure on `tests/test_runtime_router_contract.py`
- **Verdict:** ✅ Root cause identified and minimal fix proposed
- **Root Cause:** `routers/` directory lacks `__init__.py` → Python treats as namespace package; bare `from models import (...)` becomes ambiguous
- **PEP 420 Issue:** Resolver searches `routers.models` first (fails), never reaches top-level `models`
- **Fix:** Create `routers/__init__.py` (empty file)
  - Converts namespace package → regular package
  - Eliminates import ambiguity
  - One file, zero code changes, no runtime impact
- **Verification:** Pre/post collection and full test run commands documented
- **Evidence:** Full diagnostic in `.squad/decisions.md` (Router Import Fix section)

**Orchestration Log:** `.squad/orchestration-log/2026-04-24T10-21-09Z-oracle.md`

### 2026-04-24: Step 3 Parameter Sweep Completion + U1A Full Eval Launch

**Task:** Execute 24-candidate parametric optimization sweep on isolated 109-paper corpus; select winner configuration; launch full U1A closure evaluation

**Scope:** Complete Step 3 of U1 retrieval closure (per ralph-u1-closure-prep plan)

**Execution Results:**

**Sweep Details:**
- Corpus: Isolated 109-paper derived contextual cache from laser_welding_109 dataset
- Test set: 100 frozen queries from gateb_firstpass_100_eval_queries.jsonl
- Parameter space: recall_top_n in [50,100,150,200], rerank_top_n in [20,40], use_rerank in [true,false]
- Control config: top_k=10, recall_top_n=100, rerank_top_n=40, use_rerank=true
- Candidates tested: 24 configurations

**Winner Identified:**
- Configuration: top_k=10, recall_top_n=200, rerank_top_n=40, use_rerank=true, use_expansion=false
- Recall@5: 0.8700 (+6% vs control 0.82)
- MRR: 0.6798 (+2.7% vs control 0.6616)
- Avg latency: 3337.54ms (warm-cache measurement)
- P95 latency: 4084.47ms (warm-cache measurement)
- Quality tier: 2 (defensible improvement)

**Critical Caveat:**
- Latency measurements are warm-cache optimistic due to prefix embeddings cached from control run
- Per-query rows show rerank_attempts=0 / rerank_api_ms=0.0
- Full eval latency (cold corpus) expected higher; use full-eval as production expectation
- No reranker auth failures observed in Step 3 sweep

**Artifacts Generated:**
- output\109papers_step3_sweep.jsonl — Full candidate result set
- output\109papers_step3_best.json — Frozen winner config
- output\109papers_step3_report.md — Human-readable sweep analysis

**U1A Full Eval Launch:**
- Configuration: Winner config from Step 3 (recall_top_n=200, rerank_top_n=40, use_rerank=true)
- Query set: eval_queries_v2.1_u1a.jsonl (3269 queries expected)
- Expected artifacts: u1_closure_full_eval.metrics.json, progress.jsonl, per_query.jsonl
- Quality gates: Recall@5 >= 0.45, MRR >= 0.30 (Tier 2 thresholds)

**Status:**
- Step 3 sweep: ✅ COMPLETE with winner identified
- U1A full eval: 🔵 LAUNCHED (running)
- Quality assurance: Tank QA checklist prepared and ready to apply upon completion

**Evidence:**
- Orchestration logs: .squad/orchestration-log/20260424-222522-oracle-step3-sweep-run.md, oracle-u1-full-eval.md
- Session log: .squad/log/20260424-222522-step3-to-u1-full-eval.md
- Decisions merged: oracle-step3-sweep-run.md, ralph-u1-closure-prep.md, tank-u1-review-prep.md all moved to decisions.md

**Next:** Monitor U1A full eval completion; hand metrics/progress/per-query artifacts to Tank for A1-A11 acceptance checklist validation. Target completion ~2h from launch.

