# Morpheus History

> **Scope:** agent-internal working log.
> **Team-facing approval record:** see `.squad/agents/history-Morpheus.md` — the two are complementary, not duplicates. Audit 2026-04-24.

## Core Context

**Project:** my-project | **Owner:** xiao  
**Team Pattern:** architecture → implementation → testing → data  
**Responsibility:** Review cross-domain changes before landing  

**Key Checkpoints:**
- **2026-04-26: R5 Option B audit — COMPLETED** (Audited minimal formal `retrieve_then_rerank(...)` seam; identified best module (eval_retrieval_runtime.py), minimal signature (13 params, all env-resolved), blast radius (2 files); no parameter-based credential fallback; decision inbox note merged to decisions.md)
- **2026-04-24: Goldset Rejection Audit — Scope Clarification** (Tank's rejection binds only pre-existing 36/40-query artifacts; Oracle's fresh 100-query build unblocked; lockout is artifact-specific, not builder-specific)
- **2026-04-24: Persistence Turnaround Diagnosis** (Backend already passes 31/31 runtime+persistence tests; collection failure root-cause isolated to import path collision; shortest turnaround: add import guard + negative-path assertions + round-trip regression)
- Phase 6 extraction/pipeline complete (13/13 tests): `.squad/backups/checkpoint-phase6-final-20260420-0418/`
- U1A query dataset remediation approved: all pathologies cleared (duplicates/hard-queries/template-saturation)
- Tier 2 eval validation: Recall@5=0.70, MRR=0.599 (12.8× gate threshold, statistically sound)
- 2.1.2 sampling persistence approved: precedence wiring confirmed both `/chat/ask` and `/chat/stream`
- 2.1.3 cycle close: backend (Ralph) + frontend (Trinity) both approved, phase ready for deployment

## Learnings

- User prefers a model-specialized team rather than generic role rotation.
- Team members should honor the same Copilot rules, skills, and shared conventions as the main session.
- Startup self-check pattern: read SESSION_SNAPSHOT → OPEN_THREADS → requirement-pool; close drift items with file evidence; update DECISION_TRAIL before any implementation begins.
- SESSION_SNAPSHOT Open section had two items that were already resolved in prior sessions but never closed — always verify Open items against actual file state before trusting them.
- Key file paths for self-check: `.squad/memory/SESSION_SNAPSHOT.md`, `.squad/memory/OPEN_THREADS.md`, `.squad/identity/requirement-pool.md`, `.squad/memory/DECISION_TRAIL.md`.
- Phase close procedure: DECISION_TRAIL append → SESSION_SNAPSHOT Next update → OPEN_THREADS review → checkpoint copy `.squad/memory/` → `.squad/backups/checkpoint-phaseX-<timestamp>/`. Decision inbox note if team-relevant.
- **Gate B Contract Conflict Discovery (2026-04-22):** Ralph's canonical merge blocker reveals that validator code and guide documentation can drift without explicit reconciliation. Validator enforces `no_gold=true → ALL relevance = 0`, but guide implies `no_gold=true` when no `rel=2` (allowing `rel=1`). Contract ownership decision required. Evidence: `.squad/orchestration-log/2026-04-22T22-30Z-ralph-blocker-completion.md`, `.squad/orchestration-log/2026-04-22T22-35Z-morpheus-blocker-resolution-launch.md`, `.squad/session-log-blocker-milestone-2026-04-22.md`.
- **Phase 1 refreshed conclusion (2026-04-20):** Real data sources confirmed externally. `output/` = 894 JSON historical extraction artifacts (multi-stage pipeline outputs). `D:\zotero\zoterodate\storage` = 815 files (PDFs + 83 jasminum-outline.json outlines). User clarified: output/ is historical extraction product, Zotero storage is the literature library.
- **Data structure insight:** output/ per-paper artifacts follow a numbered stage pattern (01_full_extract → 02_hybrid_retrieval → 03_academic_scoring → 04_causal_dag → project_view). This is a strong design reference for Phase 2 pipeline architecture.
- **Metadata gap:** jasminum-outline.json only contains PDF TOC structure (level/title/page), not structured metadata (abstract/keywords/authors/year). This is a genuine constraint for any phase requiring structured bibliographic metadata.
- **Phase close refresh pattern:** When discovery data is corrected, update all four memory files, create a new timestamped checkpoint, and record the correction explicitly in DECISION_TRAIL. Old checkpoints are preserved for audit trail.
- **Phase 3 test quality observation:** Tests that include explicit assertion messages documenting contract assumptions (e.g., "Contract is OR-based; AND is not required.") serve double duty as executable specification and integration-readiness documentation. Worth encouraging in future test reviews.
- **Pure function testing advantage:** keyword_prefilter's pure function design (no I/O, no deps, no state) allowed 6 tests to run in 0.05s with zero setup. This validates the Phase 2 design decision to keep the module stateless.
- **Phase 3 checkpoint:** `.squad/backups/checkpoint-phase3-20260420-0349/`
- **Phase 4 validation outcome:** Oracle validated keyword_prefilter against 10 real extraction records (3 scenarios). All PASS. No new constraints. The module is triple-confirmed (impl → unit test → real data) and ready for pipeline integration.
- **Validation report quality:** Oracle's report includes clear scenario hypotheses, match counts, per-record analysis, and explicit strength/edge-case sections. This format is worth reusing for future validation tasks.
- **Phase 4 checkpoint:** `.squad/backups/checkpoint-phase4-20260420-0352/`
- **Phase 5 close procedure:** Verified that README.md and DECISION_TRAIL.md already contained integrated Phase 1-4 content before marking Phase 5 complete. Phase close = confirm deliverables → update memory files → checkpoint → inbox note. No implementation work needed when documentation was already done by the executing agent.
- **Documentation baseline pattern:** When a documentation phase closes, record in SESSION_SNAPSHOT Next that future modules should update the same README section as they land. This prevents documentation drift from accumulating across phases.
- **Phase 5 checkpoint:** `.squad/backups/checkpoint-phase5-20260420-0356/`
- **Phase 6 close observation:** The real-shape regression test bridges the gap between simplified dict unit tests and Oracle's real-data validation. It exercises recursive descent on nested structures (chunks, focus_points, stage_manifest) using shapes that mirror actual output/ artifacts. This is the pattern documented in `project-conventions/SKILL.md` under "Mirror real record shapes in regressions."
- **Phase 6 checkpoint:** `.squad/backups/checkpoint-phase6-20260420-0359/`
- **Five-layer validation chain:** keyword_prefilter now has implementation → unit tests → real-data validation → documentation integration → real-shape regression. This chain pattern is worth reusing for future pipeline modules.
- **Phase close loop discipline:** After Phase 6, the Next pointer in SESSION_SNAPSHOT should direct to the next phase-plan deliverable that is safe for autonomous execution. Folder traversal is the clear next candidate — it's within phase scope, requires no refactor, and has no new dependencies.
- **Folder traversal close (2026-04-20):** `src/folder_traversal.py` implements `collect_folder_records` (alias `traverse_folder`). Recognizes 7 real artifact types. Integrates keyword_prefilter when keywords supplied. 4/4 tests pass; joint with keyword_filter = 11/11 green (0.07s). Checkpoint: `.squad/backups/checkpoint-phase6-traversal-20260420-0408/`.
- **Pipeline front-end complete:** keyword_prefilter + folder_traversal = the first two stages of the retrieval pipeline are integrated, tested, and documented. No new dependencies needed.
- **Next task routing:** "Extraction pipeline" from phase-plan needs scope clarification before dispatch — if it requires PDF parsing libs, it's a hard-stop dependency decision. Safe alternatives: Tank tests or Oracle real-data validation for folder_traversal.
- **Extraction pipeline close (2026-04-20):** `src/extraction_pipeline.py` implements `extract_literature_context(folder_paths, keywords=None, allowed_extensions=None)`. Three-layer orchestration: folder_traversal → keyword_prefilter → segment-level extraction. Content priority: chunks > focus_points > abstract > title. Segment-level keyword re-matching via `_segment_matches`. 2/2 tests pass; joint suite = 13/13 green (0.08s). No new dependencies. Checkpoint: `.squad/backups/checkpoint-phase6-extraction-20260420-0414/`.
- **Extraction scope decision:** extraction_pipeline does NOT include PDF parsing. Scope is limited to orchestrating existing modules over already-loaded records (JSON/JSONL/CSV/TXT). PDF parsing would require new dependencies (hard-stop class).
- **Pipeline completion:** All three Must Deliver pipeline modules done: keyword_prefilter + folder_traversal + extraction_pipeline = 13/13 green. The remaining Must Deliver ("Intelligent chat") requires LLM integration — hard-stop decision domain.
- **Next safe tasks after extraction:** (1) Tank edge-case tests for extraction_pipeline (2) Oracle real-data validation for extraction_pipeline (3) README update with extraction pipeline section. All three are dependency-free and non-refactor.
- **Night-shift final closure (2026-04-20):** All safe autonomous work completed. Tank added 3 boundary tests (16/16 total). Oracle validated on 109 real papers (4 scenarios, PASS). README updated with extraction validation chapter + corrected test counts. HARD-STOP escalated: "Intelligent chat" requires LLM dependency — WAITING FOR USER.
- **Production readiness chain:** The full validation chain for the retrieval pipeline is: implementation → unit tests → boundary tests → real-data validation (109 papers) → documentation integration. This five-layer pattern should be the standard for future modules.
- **2026-04-24: Conversation Persistence MVP — Blocker Review Completed** (Block-and-reassign verdict rendered; Trinity locked out; Ralph assigned revision owner; MVP scope affirmed; router-contract bootstrap + negative-path coverage + export/import round-trip regression required; detailed scope in `.squad/decisions.md`)
- **Final checkpoint:** `.squad/backups/checkpoint-phase6-final-20260420-0418/`
- **Oracle validation report format:** The extraction validation report is significantly more detailed than the prefilter validation report (4 scenarios, provenance analysis, schema validation, item shape contract, limitations section). This format is the new gold standard for module validation reports.
- **Unified-plan dispatch rule (2026-04-20):** Before dispatching from a merged plan, reconcile plan wording against repo-local artifacts. For U1, `eval_queries_v2.1.jsonl` is 3269 lines, prior Wave 1 audit artifacts already exist under `artifacts/eval_audit\`, and the real missing step is canonicalizing/rerunning outputs into `output\` plus refreshed full-eval evidence.
- **Unified-plan gate rule (2026-04-20):** Treat conversation persistence U2 as a storage/API hard-stop even when the design doc is complete. `.modular/sessions/index.sqlite3`, transcript/checkpoint/blob layout, and new session endpoints must be gated before any frontend U3 work starts.

### 2026-04-22: Gate B Review-Chain Milestone — Final Gate Pass (With Conditions)

- **Scope:** Final architectural gate for annotation artifact canonical merge
- **Verdict:** ✅ PASS WITH CONDITIONS (canonical merge authorized as narrow normalization only)
- **Reasons:**
  - Oracle review: PASS (annotation artifact scope intact, 343 candidates verified, no data blockers)
  - Trinity preflight: READY WITH CONDITIONS (annotator_id + source_hint isolation required)
  - Canonical merge scope authorized: narrow normalization only (schema alignment, provenance population, no behavioral changes)
- **Merge safety:** Update slice constraints prevent scope creep or unintended field leaks
- **Binding conditions:** 5-point merge constraint checklist (annotator_id, source_hint exclusion, provenance preservation, schema validation, no behavioral changes)
- **Merge authorization:** Ralph may proceed with canonical normalization merge
- **Decision ref:** `.squad/decisions/inbox/morpheus-final-annotation-gate.md`

### 2026-04-22: Task 2.1.3 Cycle Close

**Cycle:** Cost Defaults & Frontend UI (2.1.3)  
**Participation:** Design review → backend rejection audit → UI rejection audit

**Key Decisions:**
1. Backend prerequisite required before frontend work proceeds
2. Trinity's backend metadata patch rejected (isolation failure) → Ralph assigned as revision owner
3. Ralph's clean resubmission approved by Tank
4. Switch's UI implementation rejected → Trinity assigned as UI revision owner
5. Trinity's UI revision approved by Tank (blank-field behavior fixed, constraints restored)

**Outcomes:**
- ✅ Backend: Ralph's isolated patch approved
- ✅ Frontend: Trinity's UI revision approved
- ✅ Phase ready for deployment

### 2026-04-22: Gate B Blocker Resolution — `no_gold` Canonical Semantics

**Event:** Contract conflict escalation from Ralph's canonical merge blocker  
**Scope:** Resolve semantic mismatch between Phase B guide and canonical validator  
**Resolution Authority:** Morpheus (architectural gate keeper)  
**Verdict:** ✅ RESOLVED

**The Decision:**

Canonical validator contract is authoritative. `no_gold=true` semantics:
- Queries with ≥1 `rel=2` → canonical qrels populated, `no_gold=false`
- Queries with 0 `rel=2` → canonical qrels empty, `no_gold=true`
- rel1-only judgments → audit sidecar (not canonical qrels)
- No validator/schema code changes required

**Rationale:** Smallest durable fix that preserves reviewed source, avoids schema widening, and keeps canonical outputs deterministic.

**Authority:** Binding to Ralph's canonical merge retry. Precedence: validator > guide for this conflict.

**Reference:**
- Blocker notes: `.squad/decisions/inbox/ralph-canonical-normalization.md`, `.squad/decisions/inbox/morpheus-no-gold-canonical-semantics.md`
- Orchestration: `.squad/orchestration-log/2026-04-22T22-40Z-morpheus-blocker-resolution.md`
- Session log: `.squad/session-log-blocker-milestone-2026-04-22.md`
- Ralph retry authorization: `.squad/orchestration-log/2026-04-22T22-42Z-ralph-canonical-merge-retry.md`

**Checkpoint:** `.squad/orchestration-log/2026-04-22T06-55-33Z-Morpheus.md`

### Rerank Pipeline Alignment (2026-04-21)
- **Cross-agent audit outcome:** Morpheus audit + Oracle trace + Tank regressions confirmed qwen3-rerank text-only pipeline is stable and production-ready.
- **Superseded direction:** Trinity's earlier VL-direction (qwen3-vl-rerank) was corrected per user guidance; final default is qwen3-rerank.
- **Decision consolidated:** All inbox decisions merged to `.squad/decisions/decisions.md` with full evidence trail and cross-references.
- **Next review scope:** Multimodal extension remains available if future phases require image+text reranking; no immediate action needed.
- **Evaluation baseline reuse decision (2026-04-20T22:04:52Z):** User clarified: completed 3269-query baseline (recall@5=0.028, mrr=0.020) is reusable permanent reference; cost control applies ONLY to rerank/LLM-AI API spend. Partial U1A progress file (1100/3269, counters only) is discardable. Authorized mini-eval: 250-query stratified subsample (~8% of full cost). Routing: Tank subsample prep (zero cost, parallel) → Ralph mini-eval (budget-gated) → Tank comparison (zero cost) → Morpheus gate. Decision records: `.squad/decisions/inbox/morpheus-reuse-baseline.md` (supersedes prior budget-reroute), user directives in `.squad/decisions/inbox/copilot-directive-*.md`.
- **Tier 0 per-query persistence gap (2026-04-21):** Code audit of `eval_retrieval_runtime.py` confirmed the root cause of the 1100-query waste: `_eval_one()` (L795-812) computes full per-query quality metrics but the progress writer (L813-827) discards them, writing only counters. Quality data exists only in memory and is lost on interrupt. The fix is purely additive (~15 lines): append the full `result` dict as JSONL alongside progress. No schema change, no dependency, no refactor. This pattern — "audit code before authorizing spend" — should be mandatory for every eval infrastructure change.
- **Pre-spend infrastructure gate pattern (2026-04-21):** Before any paid eval run, verify that the eval harness can persist usable quality evidence under all exit conditions (normal completion, interrupt, crash). The 1100-query incident proves that running eval without this check converts API spend to sunk cost. Tier 0 (zero-cost infra verification) must gate all subsequent tiers.
- **Tier 2 gate decision (2026-04-21):** Tier 1 (50-query) probe returned recall@5=0.92, MRR=0.828 — 32.7× baseline (0.028). Gate threshold was recall@5 > 0.05. Approved Tier 2 (250-query) execution. Key caveat: improvement magnitude reflects compounded effect of U1A query remediation + doc-specific targeting, not pipeline change alone. Comparison is directional, not controlled. 4/50 queries failed at recall@5 (2 total misses, 2 ranking misses) — healthy failure rate, worth investigating in Tier 2 but not blocking.
- **Compounded variable caution pattern:** When evaluating a system change that simultaneously modifies both the input (query set) and the pipeline, the measured improvement conflates both factors. Always note this in gate decisions and comparison reports. Controlled experiments require holding one variable constant.
- **Tier 3 gate decision (2026-04-21):** Tier 2 (250-query) completed: recall@5=0.700, 95% CI [0.640, 0.756]; MRR=0.599, CI [0.540, 0.654]. CI lower bound (0.640) is 12.8× the gate threshold (0.05) — comfortably passes. Morpheus conditionally approved Tier 3; execution blocked pending 小龙 co-approval per Rule 5. Key findings: (1) Tier 1→Tier 2 shrinkage from 0.92→0.70 was expected and healthy — Tier 2 is the trustworthy number; (2) 30% failure rate (75/250 queries, 63 total misses) is material and warrants root-cause investigation; (3) zero hard queries in U1A sample — Tier 3 will not close this gap; (4) latency regressed 2.4× avg. Decision recorded in `.squad/decisions/inbox/morpheus-tier3-gate.md`.
- **Tier escalation shrinkage pattern:** Expect 20-25% metric shrinkage when moving from small probe (50q) to statistical validation (250q). Tier 1 numbers should be treated as directional upper bounds, not commitments. Always quote Tier 2 numbers as the reliable estimate.
- **Dual-approval gate discipline:** For Tier 3 (high-cost) evaluation, the gate recommendation and the execution authorization are separate artifacts. The architect writes the recommendation; execution is blocked until the second approver (小龙) explicitly co-signs. This prevents accidental spend escalation.
- **Reranker model upgrade audit (2026-04-21):** Qwen3-VL-Reranker is backward-compatible for text-only reranking; multimodal capability is optional and not triggered by the current pipeline. Chunking is properly decoupled: `raw_content` (no prefix) used for rerank, `content` (with summary) used for embedding context enrichment. Switch is one-liner (env var or default model constant). No embedding recomputation needed; embeddings and reranking are independent. Decision: APPROVED for trivial implementation. Chunking gap alleged by user is not real—the separation of raw_content/content is intentional and correct.
- **Gate B Phase B reviewed-artifact rule (2026-04-22):** A reviewed annotation JSONL may become the authoritative working source even after it diverges from the frozen baseline hash, but the frozen hash remains the scope-lock reference and must not be silently replaced.
- **Canonical merge safety rule (2026-04-22):** If reviewed `source_hint` values exceed `gateb_schema_validator.py`'s closed vocabulary, normalize them into validator-safe canonical values (or `unexpected_unknown_source`) and preserve the original combos plus `chunk_id`/provenance in an audit sidecar instead of widening schema or validator.

### 2026-04-22: Gate B Canonical Merge — Blocker Resolution Dispatch

**Status:** 🔄 DECISION REQUIRED  
**Scope:** Contract ownership dispute: `no_gold` semantics between guide and validator  

**Blocker Context:**
Ralph's canonical merge attempt failed `gateb_schema_validator.py` validation. Conflict discovered:
- **Phase B Guide semantics:** `no_gold=true` when query has no `rel=2` candidates (implies `rel=1` acceptable)
- **Schema Validator enforcement:** `no_gold=true` → ALL relevance must be 0 (strict invariant)
- **Affected:** 6/36 queries (16.7%) with only `rel=1` candidates

**Decision Required:**
1. Which rule is authoritative: guide or validator?
2. Does contract need validator code change, guide clarification, or both?
3. How to classify the 6 affected queries: valid (guide-correct) or invalid (validator-correct)?

**Evidence to Examine:**
- `gateb_schema_validator.py` implementation and documentation
- `GATEB_PHASE_B_GUIDE.md` context and intent
- Oracle's prior annotation review criteria
- Related decisions in `.squad/decisions/decisions.md` (prior gate contexts)

**Morpheus Action:**
- Read validator code + guide documentation + prior decisions
- Determine binding semantics for `no_gold`
- Authorize Ralph merge retry with updated constraints (if needed)
- Log decision with binding authority notation in `.squad/orchestration-log/2026-04-22T22-35Z-morpheus-blocker-resolution.md`

**Orchestration refs:**
- Ralph blocker completion: `.squad/orchestration-log/2026-04-22T22-30Z-ralph-blocker-completion.md`
- Morpheus dispatch: `.squad/orchestration-log/2026-04-22T22-35Z-morpheus-blocker-resolution-launch.md`
- Session log: `.squad/session-log-blocker-milestone-2026-04-22.md`

**Binding authority:** Morpheus decision will authorize Ralph retry (no Scribe re-route needed)

**Timeline:** Within current session (no rush); other work streams can continue in parallel

---

### 2026-04-21: Task 2.1.2 Design Review — Sampling Persistence & Live App Wiring
- **Role:** Architecture review and cross-domain design gates.
- **Verdict:** APPROVED. PROCEED with backend-only scope (sampling_storage.py, routing, precedence wiring, live app binding). 2.1.3 frontend explicitly WAITING FOR USER.
- **Key constraints:** Sampling precedence (request > file > defaults) locked for both chat endpoints. Storage must be fail-open on read, fail-closed on write. Persistence path: `~/.literature-lab/sampling.json` with atomic writes and threading.Lock. Trinity must wire into actual chat-serving entrypoint (python_adapter_server.py or my-project/src/app.py), not assume main_system_production.py is live.
- **Architectural risk:** Silent contract drift (entrypoint binding, wrong precedence order, broken persistence semantics).
- **Evidence basis:** `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md`, live app sources, llm_defaults.py.
- **Decision trail:** Consolidated to `.squad/decisions/decisions.md` § 2026-04-21 Task 2.1.2 Design Review.
### 2026-04-26: Rerank Isolation Decision Tree

- **Decision:** Import-time dotenv loading in `eval_retrieval_runtime.py` is a valid surgical defect because it ignores `RUNTIME_ENV_DISABLE_DOTENV` and contaminates reranker tests; patch authorized only for dotenv guard plus focused regression.
- **Boundary:** Clean paired 30q rerank-ON run remains blocked until local env leak is fixed, exact 5-test bundle passes, and budget/credential approval is explicit.
- **Evidence:** `.squad\decisions\inbox\tank-rerank-layer-audit.md`, `.squad\decisions\inbox\oracle-ranking-evidence.md`, `.squad\decisions\inbox\trinity-rerank-diagnostics.md`, `eval_retrieval_runtime.py:13-25`, `runtime_env.py:18-67`.
- **Next:** Coordinator dispatches surgical env-loading guard; independent validation precedes any paid rerank smoke.

### 2026-04-26: Autonomy/Profile/.env Calibration

- **Decision:** Current free/public-interest rerank-on validation may continue using existing `.env` capability; paid-budget language is superseded for this slice.
- **Hard stop:** Do not expose secret values, edit `.env`, change external resources, mutate goldset/corpus scope, or duplicate the already-running `trinity-paired-rerank-on` task.
- **Coordinator phrasing:** Use capability/secret-safety/goldset-scope language: capability present, secret-safe, no scope mutation, continue.
- **Evidence:** `.squad/decisions/inbox/morpheus-autonomy-profile-env-calibration.md`; directives `copilot-directive-2026-04-26T16-18-03Z-external-rerank-testing.md` and `copilot-directive-2026-04-26T16-20-13Z-autonomy-profile-env.md`.


### 2026-04-26: Copilot Squad Startup Loading Root Cause

- **Finding:** Copilot Squad startup contract loads a minimal/as-needed source set and does not force `.squad/identity/start-here.md` mandatory read order; this explains missing profile/project/phase/memory context on entry.
- **Decision:** Durable repair requires a narrow `.github/agents/squad.agent.md` Team Mode startup patch; restart notice is mandatory after that file changes.
- **Evidence:** `.squad/decisions/inbox/morpheus-startup-loading-audit.md`; anchors include `.github/agents/squad.agent.md:100-108`, `.squad/identity/start-here.md:3-28`, `.github/copilot-instructions.md:71-75` and `:107-109`.
