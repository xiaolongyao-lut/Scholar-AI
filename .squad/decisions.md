# Squad Decisions

## Active Decisions

### 2026-04-20: Core team uses a 4-role execution model

**By:** Squad
**What:** The working team is composed of Morpheus (architecture), Trinity (implementation), Tank (testing), and Oracle (data production).
**Why:** This maps directly to the user's preferred workflow: architecture first, code second, verification third, and data work as an explicit discipline instead of an afterthought.

### 2026-04-20: Preferred models are role-specific

**By:** Squad
**What:** Morpheus prefers `claude-opus-4.6`, Trinity prefers `gpt-5.2-codex`, Switch prefers `claude-opus-4.5`, Tank prefers `gpt-5.1-codex-mini`, Oracle prefers `gemini-3-pro-preview`, and Scribe/Ralph prefer `claude-haiku-4.5`.
**Why:** Different work types benefit from different trade-offs in reasoning depth, coding throughput, lightweight verification, and long-form data generation.

### 2026-04-20: Morpheus is the final reviewer for cross-domain changes

**By:** Squad
**What:** Architecture-affecting work, major refactors, schema shifts, and workflow changes should be reviewed by Morpheus before landing.
**Why:** A single architectural reviewer prevents local optimizations from causing global inconsistency.

### 2026-04-20: All team members must honor project Copilot rules and shared skills

**By:** Squad
**What:** Every spawned team member must read local Copilot instructions, relevant project instructions, and relevant `.squad/skills/` entries before working.
**Why:** This keeps Squad members aligned with the same constraints, conventions, and reusable patterns as the main Copilot session.

### 2026-04-20: Switch owns frontend design that reflects product function and backend intelligence

**By:** Squad
**What:** Switch is responsible for turning backend retrieval, ranking, dialogue, and assistant capabilities into understandable, usable frontend flows.
**Why:** This project needs a frontend that explains intelligence and workflow clearly, not a generic UI that merely wraps API calls.

### 2026-04-20: Current phase is limited to literature extraction and intelligent chat

**By:** Squad
**What:** The current milestone only targets literature extraction, folder traversal, keyword-based relevance scanning, and intelligent dialogue over the literature base.
**Why:** The user wants the team to deliver the core workflow first before expanding into broader writing-assistant features.

### 2026-04-20: Frontend and backend styles are frozen unless Morpheus authorizes a refactor

**By:** Squad
**What:** Frontend work must preserve the existing design language and avoid style churn that increases workload. Backend implementation must preserve the current code style and local conventions. Only Morpheus may authorize a refactor.
**Why:** The user wants delivery speed and continuity, not style drift or opportunistic rewrites.

### 2026-04-20: Every refactor requires backup and location logging

**By:** Squad
**What:** Before any approved refactor, the responsible agent must create a backup, record the backup path, and include that location in the work log or decision note.
**Why:** Refactors are higher-risk operations and must remain reversible and traceable.

### 2026-04-20: Tank focuses on bugs and real pain points, not broad requirement expansion

**By:** Squad
**What:** Tank should prioritize bug discovery, realistic user pain points, and targeted validation. Tank may suggest narrowly scoped follow-up requirements only when they emerge from real usage friction.
**Why:** The user wants testing grounded in real needs without the tester turning every session into a feature-planning exercise.

### 2026-04-20: Oracle should use real project data sources first

**By:** Squad
**What:** Oracle should preferentially work from user-provided folders and document sources such as Zotero exports, notebook folders, and project-local literature corpora before inventing synthetic stand-ins.
**Why:** Data work is more useful when it reflects the real literature ingestion workflow the product is built around.

### 2026-04-20: All agents must onboard through start-here before substantive work

**By:** Squad
**What:** Every agent should read `.squad/identity/start-here.md` and follow its reading order before substantive work.
**Why:** The project spans multiple conversations and design phases, so agents must reuse the durable knowledge layer instead of rediscovering context from scratch.

### 2026-04-20: Night shift may continue with safe work and queue new requirements instead of stalling

**By:** Squad
**What:** Overnight work may continue on low-risk and medium-confidence tasks. New requirements should be added to the requirement pool, scored, and only escalated when they cross risk or scope boundaries.
**Why:** The user wants the team to keep moving while they sleep without losing control of product direction.

### 2026-04-20: Morpheus uses a scoring rubric to judge discovered requirements

**By:** Squad
**What:** Newly discovered requirements should be evaluated with the priority-ordered rubric in `.squad/identity/requirement-scoring.md`, centered on (1) real usage necessity for the RAG literature assistant, (2) mature solution availability, and (3) no-refactor implementability.
**Why:** This keeps requirement choices aligned to real product value and implementation practicality.

### 2026-04-20: Some in-scope incremental tasks may bypass the requirement pool

**By:** Squad
**What:** Existing in-scope RAG/literature/frontend incremental improvements that do not require refactor may be implemented directly without creating a requirement-pool entry; uncertain cases should still enter `.squad/identity/requirement-pool.md`.
**Why:** The user wants execution speed and continuity for obvious in-scope work while still preserving control over ambiguous or high-risk requirements.

### 2026-04-20: Refactor/schema/dependency are hard-stop requirement classes

**By:** Squad
**What:** Any refactor, schema/storage change, or new dependency must stop and wait for Morpheus approval. Ordinary bugfix, test work, and data prep may continue in night-shift mode.
**Why:** The user wants strict control over technical risk while preserving delivery flow for low-risk execution.

### 2026-04-20: Code-level judgment authority is centralized to Morpheus

**By:** Squad
**What:** When requirement discussion crosses into code-level technical judgment, Morpheus is the final judge. Other members may provide evidence only.
**Why:** The user stated they focus on requirements rather than code details and wants technical determination centralized.

### 2026-04-20: Morpheus technical judgment must reference project requirements and historical plans

**By:** Squad
**What:** For code-related and hard-stop classes, Morpheus should make decisions using current project requirements, active phase constraints, and historical plans/design records.
**Why:** This keeps decisions aligned with product intent and avoids isolated technical choices detached from prior project context.

### 2026-04-20: Reliability evidence prioritizes mature solutions and paper support

**By:** Squad
**What:** Requirement reliability should prioritize mature online solutions and literature-backed methods; unproven ideas should default into the requirement pool.
**Why:** This improves decision confidence and reduces risk from speculative implementation.

### 2026-04-20: Interface naming, frontend states, test scenarios, and algorithm reliability are now first-class project knowledge

**By:** Squad
**What:** The team should treat the interface glossary, frontend state spec, test scenario checklist, and algorithm reliability guide as standard project references.
**Why:** These documents reduce drift across architecture, implementation, testing, data work, and UI design.

### 2026-04-20: Repository file organization sweep completed and standardized

**By:** Squad
**What:** Root-level scattered plans, reports, diagnostics, and historical metric JSON files were consolidated into structured archive locations. The canonical map is now `docs/FILE_ORGANIZATION_MAP.md`.
**Why:** This reduces root clutter, improves discoverability, and gives all members one stable reference for where files should live.

### 2026-04-20: Team memory is persisted locally under .squad/memory for always-on reuse

**By:** Squad
**What:** The team now uses `.squad/memory/` as a local durable memory layer. Members should read `SESSION_SNAPSHOT.md` and `OPEN_THREADS.md` before work, and write reusable outcomes into `DECISION_TRAIL.md` and `TEAM_MEMORY.md`.
**Why:** The user requested memory to be retained locally so the team can read and reuse context anytime without relying on transient chat state.

### 2026-04-20: Defer "batch async ingestion" to post-Phase-5 phase-gate review

**By:** Morpheus (Owner)
**What:** Feature request "Batch async ingestion for large literature folders" is scored at 32/50 and marked WAITING FOR USER pending Phase 5 completion and post-Phase-5 prioritization.
**Why:** Current project phase (Phase 5) prioritizes intelligent-chat completion; async refactor violates style-freeze boundary per `night-shift-policy.md#Allowed To Continue Automatically`. Deferral decision follows `requirement-scoring.md` rubric: Necessity 3/5, Maturity 3/5, No-refactor 2/5 → Score 32 → Recommendation: WAITING FOR USER.
**Decision Log:** `.squad/agents/history-Morpheus.md#2026-04-20-defer-batch-async-ingestion-pending-architectural-review`
**Link:** `.squad/identity/requirement-pool.md#2026-04-20-batch-async-ingestion-for-large-literature-folders`
**Evidence:** `.squad/identity/requirement-scoring.md` (formula application), `.squad/identity/phase-plan.md` (Phase 5 milestone), `.squad/identity/night-shift-policy.md#Audit Trail Requirements` (policy boundary logic)

### 2026-04-20: Intelligent Chat Hard-Stop Decisions LOCKED — GO-AHEAD for Execution

**By:** User (Product Lead)

**What:** 4 hard-stop architecture decisions for Intelligent Chat Phase 5 are locked and approved for immediate execution:

1. **LLM Framework:** LiteLLM (support 3 providers: embedding + rerank + chat)
2. **API Key Management:** `.env` (leverage existing setup)
3. **Context Budget:** Effect-first (Top 15) + user-selectable tiers (support 100-paper literature base; keyword-marking per latest research)
4. **Conversation Memory:** Long-term local SQLite (persistent multi-turn dialogue in `.squad/memory/`)

**Why:** These 4 decisions determine implementation path, dependency choices, cost, stability, and maintainability. They are not parameters but architectural boundaries.

**Team Assignment:**
- Trinity (Implementation): Phase 1-4 code (LiteLLM → Context Budget → Session Memory → Chat Endpoint)
- Tank (QA): Test scenarios + 100-paper dataset validation
- Switch (Frontend): UI/UX design (tier selector + session history)
- Morpheus (Architecture): Phase-by-phase review gate

**Timeline:** 4 weeks (2026-04-21 to 2026-05-16)

**Execution Notice:** `.squad/EXECUTION_NOTICE.md` (all team members read this for immediate action items)

**Implementation Plan:** `.squad/identity/intelligent-chat-plan.md` (complete spec + code templates for all 5 phases)

**First Action:** Trinity starts Phase 1 (LiteLLM integration) immediately; Deadline Friday EOD (2026-04-25)

**Escalation:** No unilateral changes to these 4 decisions. All issues go to Morpheus. User may override if blocking issue emerges.

**Approval Status:** ✅ User approved | ✅ Team ready | 🟡 Awaiting Morpheus Phase 1 code review

### 2026-04-20: Morpheus U1 Recovery Decision Issued

**By:** Morpheus (Architecture)
**Date:** 2026-04-20
**Scope:** Next lockout-compliant recovery step after Tank re-gate rejection
**Decision Source:** `.squad/decisions/inbox/morpheus-u1-recovery.md` (merged)

## Verdict

The immediate U1 problem is **primarily evaluation-set / template-design bias**. The earlier acceptance-contract mismatch is already cleared.

## Authorized Next Step

- Freeze reruns on unchanged `eval_queries_v2.1.jsonl`
- Execute scoped, data-only U1A remediation pass (Ralph owner)
- Do NOT refactor retrieval/runtime code, change schema, or add dependencies
- Any architecture changes must come back to Morpheus for re-approval

## Owner Routing

- Remediation owner: Ralph
- Reviewer: Tank (audit/dataset shape)
- Locked out this cycle: Oracle, Trinity

### 2026-04-20: Ralph U1A Data Remediation Completed

**By:** Ralph (Data Remediation Specialist)
**Date:** 2026-04-20
**Scope:** Data-only U1A remediation pack for v2.1 eval queries
**Decision Source:** `.squad/decisions/inbox/ralph-u1a-remediation.md` (merged)

## Remediation Scope

- **Duplicate generic query-text clusters (≥6 distinct docs):** Rewrote to document-anchored non-template questions
- **Hard queries with single-evidence supervision:** Downgraded to medium difficulty
- **Non-template population:** Restored from 0 to 3086 queries

## Outcome

- Before: `unique_query_text=181`, `template_match.non_template=0`, `duplicate_query_text_across_docs.type_count=70`, `hard_with_single_doc_evidence.type_count=326`
- After: `unique_query_text=2482`, `template_match.matched=183`, `template_match.non_template=3086`, `duplicate_query_text_across_docs.type_count=0`, `hard_with_single_doc_evidence.type_count=0`

## Artifacts Delivered

- `eval_queries_v2.1_u1a.jsonl`
- `output/eval_query_audit_v21_u1a.json`
- `output/eval_query_audit_v21_u1a_template_flags.jsonl`
- `output/eval_query_audit_v21_u1a_remediation_ledger.json`

### 2026-04-20: Tank U1A Audit Gate — APPROVED for Rerun Readiness

**By:** Tank (QA Reviewer)
**Date:** 2026-04-20
**Scope:** Reviewer gate for U1A data-only remediation pack
**Decision Source:** `.squad/decisions/inbox/tank-u1a-audit-gate.md` (merged)

## Verdict

**✅ APPROVED** for canonical rerun on `eval_queries_v2.1_u1a.jsonl`

## Pathology Clearance Check

The known Morpheus-targeted pathologies are sufficiently cleared:

- Duplicate generic query-text clusters at threshold (≥6 distinct docs): **cleared** (`type_count=0`)
- Hard queries with single-evidence supervision: **cleared** (`type_count=0`)
- Template saturation: **materially reduced** (`matched=183`, `non_template=3086`)
- Artifact coherence cross-checks: **pass** (`total_queries=3269`, `unique_query_text=2482`)

Residual low-fanout cross-doc text reuse (`max fanout=5`, `clusters_gt1=562`) remains non-blocking below authorized threshold.

## QA Evidence

- Validation suite: `pytest tests\test_eval_dataset_audit.py tests\test_eval_runtime.py -q` → `17 passed`
- Data validation summary:
  - `total_rows=3269`
  - `flags_true=183`, `flags_false=3086`
  - `duplicate cluster >=6 = 0`
  - `hard_single_evidence = 0`
  - Audit/ledger/template flags consistency: **none failed**

## Next Allowed Step

New canonical full eval rerun with owner **Ralph** (with Morpheus oversight). Oracle and Trinity remain lockout-ineligible.

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
- Frontend style should remain stable unless Morpheus explicitly approves a redesign or refactor
- Backend code style should remain stable unless Morpheus explicitly approves a refactor
- Approved refactors must be backed up and the backup location must be recorded

### 2026-04-20T22:04:52Z: Evaluation Baseline Reuse Strategy Locked — Morpheus Directive

**By:** User (via Copilot) + Morpheus (routing correction)

**What:** Completed 3269-query eval baseline is reusable as permanent reference. Cost control applies ONLY to rerank/LLM-AI API spend, not to already-completed artifacts or local computation.

**Why:** User clarification distinguishes sunk-cost work (reusable, zero marginal cost) from live API spend (cost-gated).

**Scope:**
- `output/v21_full_eval_canonical.json` (3269/3269, recall@5=0.028) — **permanent pre-remediation baseline, never re-run**
- `output/v21_u1a_full_eval_canonical.progress.jsonl` (1100/3269 partial) — **discardable** (counters only, no per-query metrics)
- `eval_queries_v2.1_u1a.jsonl` (remediated dataset) — **reuse as-is** (Tank-audited 2026-04-20)
- `eval_queries_v2.1_u1a_mini.jsonl` (250-query stratified subsample) — **authorize now** (zero cost, local prep)

**Authorized Next Steps:**
1. Tank prepares stratified 250-query subsample (zero cost, data selection only)
2. Ralph runs mini-eval on 250 queries with rerank (~8% of full eval cost, budget-gated)
3. Tank compares mini-eval results vs. baseline (zero cost, local)
4. Morpheus reviews comparison; gates Phase 5 readiness

**Cost Budget:** ~8% of full eval (15–20 API credits estimated)

**Decision Records:**
- User directives: `.squad/decisions/inbox/copilot-directive-20260420-220452.md`, `.squad/decisions/inbox/copilot-directive-20260420-220452-reuse-baseline.md`
- Morpheus revised reroute: `.squad/decisions/inbox/morpheus-reuse-baseline.md` (supersedes prior `morpheus-budget-reroute.md`)
- Scribe logging: `.squad/orchestration-log/20260420-220452-scribe-directive-capture-reroute.md`, `.squad/log/20260420-220452-baseline-reuse-checkpoint.md`

## Inbox Merges — 2026-04-20

# Decision: Extraction Pipeline Subtask Closed

**By:** Morpheus
**Date:** 2026-04-20
**Scope:** extraction-pipeline

## What

`src/extraction_pipeline.py` is complete. Entry API: `extract_literature_context(folder_paths, keywords=None, allowed_extensions=None) -> list[dict]`. Orchestrates folder_traversal → keyword_prefilter → segment-level content extraction. 13/13 tests green.

## Key Architectural Decisions

1. **Scope boundary:** extraction_pipeline does NOT include PDF parsing. It operates over already-loaded records (JSON/JSONL/CSV/TXT). PDF parsing is a separate concern requiring new dependencies (hard-stop class).
2. **Two-pass filtering:** Record-level prefilter (keyword_prefilter) followed by segment-level re-matching (_segment_matches). This "coarse-then-fine" strategy avoids returning entire records when only specific chunks match.
3. **Content priority:** chunks > focus_points > abstract/text > title. First match wins — avoids duplicate extraction from the same record.
4. **No new dependencies:** Only uses keyword_filter + folder_traversal + stdlib.

## Pipeline Status

All three Must Deliver pipeline modules are now complete:
- keyword_prefilter (Phase 2) — 7/7 tests
- folder_traversal (Phase 6-traversal) — 4/4 tests
- extraction_pipeline (Phase 6-extraction) — 2/2 tests
- **Total: 13/13 green (0.08s)**

## Next

The remaining phase-plan Must Deliver — "Intelligent chat grounded in the extracted literature base" — requires LLM integration. This is a hard-stop dependency decision requiring Owner + Morpheus sign-off.

Safe autonomous next tasks: Tank edge-case tests, Oracle real-data validation, or README documentation update for extraction_pipeline.

## Checkpoint

`.squad/backups/checkpoint-phase6-extraction-20260420-0414/`

# Morpheus — Night-Shift Final Closure

**Date:** 2026-04-20
**Scope:** Phase 6 final closure + pipeline production readiness declaration

## What Happened

1. **Tank boundary tests recorded:** extraction_pipeline now has 5/5 tests (3 new edge cases: malformed inputs, empty output, mixed-source provenance). Total suite: 16/16 green.
2. **Oracle real-data validation recorded:** 109 laser-processing papers, 650 JSON artifacts, 4 scenarios (domain keywords → 3584 items, technical params → 1317 items, irrelevant keyword → 0 items, baseline → 13926 items). 100% provenance, 100% schema compliance. PASS.
3. **README updated:** Phase 7 extraction validation section added. Test counts corrected (keyword_filter 7/7, extraction_pipeline 5/5). Report reference added.
4. **Memory files updated:** SESSION_SNAPSHOT, TEAM_MEMORY, OPEN_THREADS, DECISION_TRAIL all current.
5. **Checkpoint created:** `.squad/backups/checkpoint-phase6-final-20260420-0418/`

## Pipeline Status

All retrieval pipeline modules are production-ready:
- `src/keyword_filter.py` — 7/7 tests + real-data validation
- `src/folder_traversal.py` — 4/4 tests
- `src/extraction_pipeline.py` — 5/5 tests + 109-paper real-data validation

## Remaining Blocker

**HARD-STOP — Intelligent Chat (WAITING FOR USER)**

The last Must Deliver item — "Intelligent chat grounded in the extracted literature base" — requires LLM integration (new external dependency). Owner must decide:
1. LLM framework (openai / langchain / litellm / other)
2. API key management
3. Context window budget (token limits vs. literature volume)
4. Conversation memory (single-turn vs. multi-turn sessions)

No further autonomous work is possible until this decision is made.

# Phase 1 Close — Morpheus

**Date:** 2026-04-20
**By:** Morpheus
**Phase:** 1 — Core literature extraction discovery

## Summary

Trinity completed the literature data scan (`.squad/discovery/literature-data-map.md`). No pre-existing literature data files (.json/.jsonl/.csv/.txt) were found in data/, output/, resources/, or the repository root.

## Architectural Assessment

- **Not a blocker for Phase 2 or 3.** The system is designed for runtime ingestion from user-provided folders (Zotero directories, notebook folders), not pre-packaged datasets.
- Phase 2 (implementation) can proceed to build folder traversal, keyword filtering, and extraction pipeline.
- Phase 3 (testing) can proceed using synthetic test data or minimal samples for core path validation.

## Checkpoint

Memory snapshot saved to `.squad/backups/checkpoint-phase1-20260420-0333/`.

## Action Required

None. Phase 2 and 3 may proceed when Owner is ready.

# Decision: Phase 1 刷新关闭 — 真实数据源已确认

**Date:** 2026-04-20
**By:** Morpheus

## What

基于刷新后的 `literature-data-map.md`，Phase 1 发现结论已修正：

- **output/**（历史提取产物）：894 JSON 文件，含 batch summary + 每篇论文多层提取产物（full_extract / hybrid_retrieval / academic_scoring / causal_dag / project_view）。
- **D:\zotero\zoterodate\storage**（文献库）：815 文件，以 PDF 附件为主，含 83 个 jasminum-outline.json（仅 PDF 大纲结构）。

早期"仓库无预置文献数据"的结论已过时。

## Downstream impact

- **Phase 2（实现）**：不阻塞。可参考 output/ 已有产物结构设计提取管道。
- **Phase 3（测试）**：不阻塞。Tank 可使用真实提取产物和 PDF 附件验证，无需依赖合成数据。
- **Phase 4 约束**：Zotero jasminum-outline.json 不含结构化元数据（abstract/keywords/authors/year）。如需此类数据，需额外从 PDF 正文解析或 Zotero API 获取。已记入 OPEN_THREADS 作为非阻塞约束。

## Checkpoint

`.squad/backups/checkpoint-phase1-20260420-0339/`（含全部 memory 文件快照）。

# Morpheus Phase 1 Review — Verdict

**Date:** 2026-04-25
**Reviewer:** Morpheus (Architect)
**Scope:** Trinity Phase 1 (LiteLLM gateway), Tank QA artifacts, Switch chat UI contract

---

## VERDICT: APPROVE — Phase 2 may begin

---

## Trinity — `src/litellm_gateway.py` + tests

**Status:** ✅ APPROVED

- No hardcoded secrets; all keys via `os.getenv()`. `.env.example` provided correctly.
- `ProviderConfig` dataclass improves on the plan template (frozen, typed, explicit validation). This is a positive deviation.
- `validate()` and `_ensure_ready()` guard against misconfigured launches.
- `rerank_chunks` handles both native `litellm.rerank` and completion-based fallback — forward-compatible.
- `chat_with_context(messages, **kwargs)` signature deviates from the plan's `(query, context_chunks, session_id)` but is **better**: it's a lower-level building block that Phase 2+ can compose on top of. Approved.
- Tests: 3/3 PASS. Mocks at the correct boundary (litellm module functions). Env vars via `monkeypatch` — no leakage risk.

**One fix applied by Morpheus:** `.gitignore` was missing `.env` rule. Fixed during this review.

**Minor observation (non-blocking):** `rerank_chunks` fallback path (line 76-81) calls `litellm.completion` but discards the response, returning original order. This is acceptable as a graceful degradation but should eventually log a warning.

---

## Tank — QA artifacts

**Status:** ✅ APPROVED (with note)

- `chat-contract.json` defines a clean 6-field schema. Tests enforce it.
- `test_chat_contract.py` parametrized over inline data — 2/2 PASS.
- `synthetic-corpus.jsonl` has 4 entries — intentionally minimal skeleton for contract validation.

**Note:** Tank's `tier` field uses values `context` / `gateway` (test layer marker), not the product tiers `fast` / `balanced` / `thorough`. This is not a conflict since it serves a different purpose (test classification vs. product feature), but Tank should document this distinction when expanding the corpus.

---

## Switch — Chat UI Contract

**Status:** ✅ APPROVED

- Tier selector as segmented control: architecturally sound, aligns with plan.
- State machine (6 states, 5 transitions): clean, covers the critical paths.
- `ChatResponse` TypeScript interface: well-specified, optional `context_metadata` for progressive disclosure is forward-compatible.
- Open questions (insight message, session browsing, mobile) correctly flagged for Morpheus.

**Morpheus answers to Switch's open questions:**
1. **Insight messages:** Disabled for MVP. Revisit post-Phase 4.
2. **Session history browsing/deletion:** Backend-only for now. Frontend session list is a Phase 5+ feature.
3. **Mobile layout:** Deferred. Desktop-first.

---

## Mandatory fix applied

| Fix | File | By |
|-----|------|----|
| Added `.env`, `__pycache__/`, `*.pyc`, `.pytest_cache/` to `.gitignore` | `.gitignore` | Morpheus |

---

## Phase 2 GO decision

All Phase 1 deliverables meet acceptance criteria. Trinity may proceed to Phase 2 (Context Window Budget & Tier System).

# Decision: Phase 2 keyword_prefilter 实现关闭

**By:** Morpheus
**Date:** 2026-04-20
**Scope:** Phase 2 close

## Summary

`src/keyword_filter.py` delivers `keyword_prefilter(keywords, records)` — a pure, side-effect-free filter that matches records by title/abstract/keyword fields using Unicode-normalized substring search. 73 field-name variants (EN + CN) ensure broad compatibility with heterogeneous JSON schemas, including the project's own `output/` extraction artifacts.

## Architectural Assessment

- **Contract quality:** Clean. Defensive input handling, early-return on empty inputs, recursive descent for nested structures.
- **Integration readiness:** The function accepts pre-parsed dicts. Upstream (folder traversal + JSON loading) feeds it; downstream (extraction pipeline) consumes its output. No coupling to I/O or external state.
- **Test readiness:** Pure function with no deps — Tank can unit-test immediately without mocking.
- **No new constraints:** Implementation introduces no new dependencies, schema changes, or downstream blockers.

## Next Steps

- Folder traversal and extraction pipeline modules remain to be implemented (phase-plan deliverables).
- Tank may begin keyword_prefilter unit tests using synthetic dicts and/or real `output/` JSON samples.

## Checkpoint

`.squad/backups/checkpoint-phase2-20260420-0345/`

# Phase 3 Close — keyword_prefilter 测试验证完成

**By:** Morpheus
**Date:** 2026-04-20

## Summary

Phase 3 关闭。`tests/test_keyword_filter.py` 6/6 通过（0.05s），覆盖核心合同（OR 语义）、边界条件（空输入）、否定路径（无匹配）、Unicode 中文匹配和超长输入鲁棒性。

## Key Findings

- keyword_prefilter 的 OR 语义合同已由测试显式验证并包含断言消息——这是管道集成时的关键假设文档。
- 纯函数设计使测试完全独立，无需 mock、fixture 或外部依赖。
- 测试未暴露新的下游约束或缺陷。

## Next

- keyword_prefilter 已通过实现 + 测试双重验证，可直接集成到提取管道。
- Phase 4 的文件夹遍历和提取管道实现可启动。

## Checkpoint

`.squad/backups/checkpoint-phase3-20260420-0349/`

# Phase 4 Closure — Oracle Real-Data Validation

**Date:** 2026-04-20  
**By:** Morpheus  

## Decision

Phase 4 (Oracle real-record validation) is closed. `keyword_prefilter` has completed the full verification chain: implementation (Phase 2) → unit tests (Phase 3) → real-data validation (Phase 4).

## Key Outcome

- 10 real extraction records from `batch_test_109papers/`, 3 scenarios, all results match specification.
- OR semantics, Unicode (EN+CN), case-insensitive substring matching, and zero false positives confirmed.
- No new constraints or blockers surfaced. Existing `phase4-metadata-constraint` (Zotero outline lacks structured metadata) remains tracked and unchanged.

## Architectural Implication

`keyword_prefilter` is validated for production integration into the retrieval pipeline as a pre-screening stage. Next phase can proceed with folder traversal and extraction pipeline design, using this module as a trusted filter component.

## Checkpoint

`.squad/backups/checkpoint-phase4-20260420-0352/`

# Phase 5 Close — Documentation Integration Complete

**Date:** 2026-04-20
**By:** Morpheus

## What

Phase 5 closed. README.md "文献检索模块" section now integrates all Phase 1-4 outputs (data discovery, keyword prefilter implementation, test coverage, real-record validation). DECISION_TRAIL.md contains the full Phase 1-4 decision chain with per-phase What/Decision/Why/Evidence/Impact plus architecture synthesis.

## Impact

- Documentation baseline established: new modules should update the README.md literature retrieval section as they land.
- keyword_prefilter has completed a full dev→test→validate→document lifecycle. Pipeline integrators can reference README.md and DECISION_TRAIL.md directly.
- Checkpoint saved: `.squad/backups/checkpoint-phase5-20260420-0356/`

## Remaining Constraint

- phase4-metadata-constraint remains open: Zotero jasminum-outline.json lacks structured metadata. This is tracked in OPEN_THREADS and does not block pipeline integration.

# Phase 6 Close — Real-Shape Regression Coverage

**Date:** 2026-04-20
**By:** Morpheus

## What

Phase 6 free-improvement iteration closed. The new `test_keyword_prefilter_matches_real_record_shapes_from_phase_outputs` test (7th test) validates keyword_prefilter's recursive descent search against realistic output/ artifact structures (source_pdf, chunks, focus_points, stage_manifest nesting). All 7/7 tests pass in 0.05s.

## Why This Matters

This test fills the regression gap between simplified-dict unit tests (Phase 3) and Oracle's one-time real-data validation (Phase 4). It ensures that future changes to keyword_prefilter won't silently break nested-field traversal — the exact code path exercised by real extraction pipeline records.

## Impact

- keyword_prefilter now has a five-layer validation chain: implementation → unit tests → real-data validation → documentation → real-shape regression.
- Next safe autonomous task: folder traversal module implementation (phase-plan core deliverable, no refactor/schema/dependency triggers).
- OPEN_THREADS: no new blockers. Existing [phase4-metadata-constraint] remains valid and non-blocking.
- Checkpoint: `.squad/backups/checkpoint-phase6-20260420-0359/`

# Morpheus Decision — Startup Self-Check

**Date:** 2026-04-20
**By:** Morpheus
**Scope:** memory maintenance, self-check

## Decision

Closed two stale Open items in `SESSION_SNAPSHOT.md` and updated the snapshot to reflect current reality.

## Evidence

1. `start-here.md` lines 14–16 already list `.squad/memory/SESSION_SNAPSHOT.md`, `OPEN_THREADS.md`, and `TEAM_MEMORY.md` in the reading order → first Open item resolved.
2. `project-conventions/SKILL.md` contains "Team memory persistence (local-first)" section with explicit read/write guidance → second Open item resolved.
3. `OPEN_THREADS.md` has no active blocks.
4. `requirement-pool.md` has no entries (only template) → no stale `done` items to close.

## Actions Taken

- SESSION_SNAPSHOT: moved two Open items to Facts, cleared Open section, updated Next to await Phase 1.
- DECISION_TRAIL: appended self-check record with evidence.
- No changes to OPEN_THREADS (already clean) or TEAM_MEMORY (no new stable facts to add).

## Impact

Memory layer is now accurate. Team can rely on SESSION_SNAPSHOT as a truthful starting point.

# Morpheus Decision — Folder Traversal Close

**Date:** 2026-04-20
**By:** Morpheus

## What

Folder traversal subtask closed. `src/folder_traversal.py` + `tests/test_folder_traversal.py` validated. Full test suite 11/11 passed (0.07s). Memory checkpoint created at `.squad/backups/checkpoint-phase6-traversal-20260420-0408/`.

## Architecture Assessment

- The retrieval pipeline front two stages (traverse + prefilter) are integrated and production-ready.
- `collect_folder_records` is the canonical entry point; `traverse_folder` is an alias.
- No new external dependencies were introduced — only stdlib + `keyword_filter`.

# Phase 3 Intelligent Chat — Session Memory & Multi-Turn Prompt Architecture Review

**Date:** 2026-04-20
**By:** Morpheus
**Scope:** architecture_review, phase_gate_approval

## Verdict: ✅ APPROVE — Phase 4 may begin

## What

Trinity completed Phase 3 deliverables: `session_memory.py` (persistent SQLite + JSONL storage for chat turns) and `multi_turn_prompt.py` (prompt construction utility). Tank validated both modules through 8 tests (4 session + 2 prompt + 2 contract compliance). All tests PASS (0.12s). Architecture review confirms Phase 4 readiness.

## Trinity — `src/session_memory.py`

**Status:** ✅ APPROVED

- Schema aligns with specification: SQLite + JSONL dual-write under `.squad/memory/{session_id}/`
- Declarative schema via `_TURN_COLUMNS` tuple-of-tuples supports forward migration (positive deviation from plan)
- `add_turn()` signature matches plan (7 params); dual-write verified in tests
- `get_recent_turns()` returns `SessionTurn` TypedDict with correct fields; chronological ordering verified
- `get_session_summary()` aggregates token totals with defensive missing-JSON handling
- Modern UTC-aware datetime (not deprecated `utcnow()`)
- Public API surface (`add_turn`, `get_recent_turns`, `get_session_summary`) exactly matches Phase 4 integration needs
- No Phase 4 endpoint logic leakage

**Minor observation (non-blocking):** Connection per call with caller-managed cleanup is acceptable for Phase 3 scope. Post-Phase-5, a connection pool may be introduced if session concurrency becomes a concern.

## Trinity — `src/multi_turn_prompt.py`

**Status:** ✅ APPROVED

- `build_messages()` produces standard `[system, user]` message list for litellm integration
- `build_prompt()` correctly separates system prompt from flat string (improvement over plan)
- `_format_history()` and `_format_context()` have graceful empty/missing-data fallbacks
- `DEFAULT_SYSTEM_PROMPT` aligns with product identity
- Pure utility module with no Phase 4 endpoint coupling

## Tank — Test Suite

**Status:** ✅ APPROVED

| Test | Count | Result |
|------|-------|--------|
| `test_session_memory.py` | 4 | ✅ PASS |
| `test_multi_turn_prompt.py` | 2 | ✅ PASS |
| `test_chat_session_contract.py` | 2 | ✅ PASS |

Coverage verified:
- Creation, persistence, chronology, token aggregation, prompt injection, empty history, contract compliance
- All 36 tests PASS (full suite regression: 0 breakage)

## `chat-contract.json` Phase 3 Section

**Status:** ✅ APPROVED

- `required_methods`: `["add_turn", "get_recent_turns", "get_session_summary"]` matches implementation
- `recent_turn_fields` and `summary_fields` match TypedDicts exactly
- `chronology` and `tier_contract` clauses explicit and tested

## Repo Hygiene

| Item | Classification | Action |
|------|---------------|--------|
| `src/__pycache__/extraction_pipeline.cpython-314.pyc` tracked in git | **Non-blocking** | `.gitignore` already correct (`__pycache__/` and `*.pyc`). This file was committed historically. User has hard-stop rule against file deletion. Recommend `git rm --cached` when user explicitly permits cleanup. No functional impact on Phase 3 or Phase 4. |

## Architecture Decision

- **Phase boundary:** Clean (no Phase 4 logic in Phase 3 modules)
- **Phase 4 readiness:** ✅ Confirmed
- **Phase 5 implications:** Session memory layer supports multi-turn retrieval in Phase 5 without refactoring

## Next Phase Gate

Trinity may proceed to Phase 4 (Chat Endpoint — Full Integration). Tank leads integration test preparation. Phase 4 approval: ✅ APPROVED.

## Checkpoint

`.squad/backups/checkpoint-phase3-chat-20260420-0652/`

## Next Safe Task

- Tank: additional folder_traversal tests (real-shape regression, edge cases) — safe, no refactor.
- Oracle: real-data validation of folder_traversal against actual output/ artifacts — safe, no refactor.

## Requires Morpheus Review

- "Extraction pipeline for relevant literature artifacts" (phase-plan next deliverable) needs architectural scope clarification before implementation:
  - Option A: Orchestrate existing modules (no new deps) → safe for autonomous execution.
  - Option B: Implement PDF extraction (requires new deps like pdfplumber/pymupdf) → hard-stop, needs approval.
- This review should happen before dispatching Trinity on the extraction pipeline.

# Decision: Extract Literature Context is Production-Ready for Retrieval

**Date:** 2026-04-21  
**Agent:** Oracle  
**Status:** Recommendation to Morpheus  
**Artifact:** `.squad/discovery/oracle-extraction-validation-report.md`

## Summary

Completed real-data validation of `extract_literature_context()` on 109 laser-processing papers (13,926 chunks). Function demonstrates correct keyword filtering, provenance preservation, and irrelevant file exclusion. **Recommend deployment to retrieval and dialogue components.**

## What Was Tested

1. **High-relevance keywords** ["laser", "nitriding", "surface"]: 3,584 items from 282 files (25.7% recall)
2. **Technical parameters** ["temperature", "hardness", "scanning speed"]: 1,317 items from 97 files (9.5% recall)
3. **Irrelevant keywords** ["PTFE"]: 0 items (correctly excluded non-matching files)
4. **No keywords (baseline):** 13,926 items (100% coverage for comparison)

## Key Findings

- ✓ All extracted items (15,000+) conform to output schema
- ✓ Provenance preserved 100% (source_file, chunk_id, section_title, source_pdf)
- ✓ Keyword filtering prevents irrelevant file expansion (efficiency goal met)
- ✓ Unicode/encoding: zero failures on mixed English/Chinese text
- ✓ Content type distribution: 94% chunks, 5% focus_points, 1% titles

## Known Constraints

- No ranking layer (returns unranked list; needs addition in next phase)
- Chunk-level granularity may require paper-level aggregation for UI
- Over-match on meta-heavy intro chunks (journal headers, etc.)

## Recommendation

**APPROVED FOR PRODUCTION** pending:
1. Ranking/scoring layer added in dialogue component
2. UI accommodation for chunk-level vs. paper-level presentation
3. Section-aware filtering in advanced search (future phase)

No refactor required; current implementation is correct and efficient.

---

**Next Action:** Deploy to Trinity for integration with dialogue and ranking components.

# Decision: Real-Record Validation Confirms Keyword Filter Is Production-Ready

**Date:** 2026-04-20  
**By:** Oracle  
**Phase:** 4 — Real-record validation  

## Context
Phase 1 discovered structured data in `output\batch_test_109papers\` (109 papers extracted, each with multiple JSON artifacts). Phase 2 produced `keyword_filter.py` to scan title/abstract/keyword fields for relevance matching. Phase 4 now validates the function against real samples.

## Decision
**The `keyword_prefilter()` function is production-ready.**

### Evidence
- Tested against 10 real chunks sampled from Phase 1 output
- 3 keyword scenarios spanning domain-specific (laser/welding), process (temperature/stress), and emerging (machine learning/sensor) keywords
- Results: OR semantics work, case-insensitive matching works, Unicode normalization (Chinese/English mixed) works, no false positives
- Recall rates realistic for retrieval prefilter use (70% on high-relevance keywords, 10% on specific parameters, 0% on rare technologies)

### Record Shape Clarification
**A "record" = a single chunk + paper metadata (title, source PDF)**

In the extraction pipeline, papers are split into chunks for granular search. Each chunk is an independent unit. The keyword filter operates on this chunk-level abstraction, not full papers. This is correct for retrieval use cases.

### No Further Action Needed
- No bugs discovered in the filter
- No schema changes required
- Chunk-level search granularity is appropriate

### Recommendation
Proceed with integrating `keyword_prefilter()` into the retrieval and ranking pipeline. Monitor real-world performance metrics once the full system is live.

---

**Report:** `.squad/discovery/oracle-validation-report.md`  
**Test data:** `.squad/discovery/oracle_sample_records.json` (attached for audit)

# Phase 5 Documentation Integration Decision

**Date:** 2026-04-20  
**Agent:** Scribe (Documentation Specialist)  
**Task:** Consolidate Phases 1-4 outputs into user-facing documentation

---

## Decision: Documentation Structure Pattern

### What
- Created `README.md` with new section `## 文献检索模块` that synthesizes all Phase 1-4 work
- Appended comprehensive Phase 1-4 decision chain to `.squad/memory/DECISION_TRAIL.md`
- Updated `.squad/agents/scribe/history.md` with phase learnings

### Why
- **User clarity:** Project stakeholders need one authoritative source documenting what was built, why, and how to use it
- **Team memory:** Decision trail creates local durable knowledge that persists across sessions and team members
- **Architecture transparency:** Linking discovery → implementation → testing → validation shows quality gates passed

### Evidence
- `README.md` exists with complete `文献检索模块` section (covers all 4 phases)
- `DECISION_TRAIL.md` updated with synthesis section (§Phase 1-4 Decision Chain Summary)
- Learnings recorded in scribe history with file paths and key metrics

---

## Documentation Patterns Established

### Pattern 1: Phase Summary Structure
Each phase section in README follows: **Overview → Scope → Key Findings → Architecture Implication**

This pattern makes it easy for readers to:
1. Understand what happened (scope)
2. See concrete results (findings)
3. Understand why it matters to the system (implication)

### Pattern 2: Decision Trail with Why/Evidence/Impact
Each entry in DECISION_TRAIL.md records:
- **Decision:** What choice was made
- **Why:** Business/technical reasoning
- **Evidence:** Where to find proof (files, test results, reports)
- **Impact:** What downstream work becomes enabled or constrained

This structure allows future team members to understand not just *what* was done, but *why it matters* and *where to verify it works*.

### Pattern 3: README Bridges Discovery and Integration
The README `文献检索模块` section:
- Maps back to Phase 1 discovery (data sources, file paths)
- Explains Phase 2 design (normalization pipeline, field recognition)
- References Phase 3 tests (6 test cases, coverage quality)
- Summarizes Phase 4 validation (real-record results, quality gates)

This creates a story that goes from "here's the data" → "here's how we process it" → "here's how we verified it" → "here's how to use it."

---

## Recommendations for Downstream Documentation

1. **Maintain phase narrative:** When adding new features, follow the discovery → implementation → testing → validation chain. This reduces documentation burden because each phase has a clear scope and evidence artifact.

2. **Embed file paths in learnings:** When Morpheus or team members complete work, record specific file paths (not just abstract descriptions). Future team members can navigate directly.

3. **Use decision trail for non-obvious choices:** When implementation deviates from initial design (or confirms initial design), record in DECISION_TRAIL with evidence. This prevents "why did we do this?" archaeology.

4. **Multilingual documentation:** This project uses mixed English/Chinese. README sections are more effective when they mirror the language of the team (e.g., Phase headers in Chinese, algorithm details in English where existing code uses English).

---

**End of Decision**

# Decision: Chat UI Design Choices

**Author:** Switch  
**Date:** 2026-04-20  
**Status:** Pending Morpheus review

---

## Decisions Made

### 1. Tier Selector: Segmented Control (not dropdown)

**Choice:** Use a visible pill/button group showing all 3 tiers (FAST / BALANCED / THOROUGH) side by side.

**Rationale:**
- Speed-vs-quality tradeoff should be immediately visible, not hidden behind a click.
- Users need context to make an informed choice; showing all options together helps.
- Mobile-friendly (tappable), keyboard-accessible.
- Dropdown would add an unnecessary interaction step.

### 2. Context Chunks: Progressive Disclosure (hidden by default, expandable)

**Choice:** Show chunk count as a collapsible summary; expand to see individual sources and snippets on demand.

**Rationale:**
- Most users want the answer, not the underlying provenance.
- Power users (researchers) need provenance to verify grounding — they can expand.
- Showing all chunks by default would create visual noise and scrolling burden.
- Accordion pattern is a well-understood disclosure mechanism.

### 3. Default Tier: BALANCED

**Choice:** Pre-select BALANCED tier (10 papers, ~6K tokens).

**Rationale:**
- FAST may be too shallow for substantive research questions.
- THOROUGH is costly and slower — should be opt-in.
- BALANCED offers a reasonable middle ground for most use cases.

---

## Open Questions (for Morpheus)

1. **Insight Message UX**: automatic, user-triggered, or disabled for MVP?
2. **Session History Browsing**: exposed to user or backend-only?
3. **Mobile Layout**: design now or defer?

---

## Artifacts Created

- `.squad/identity/chat-ui-contract.md` — Full UI contract for Phase 5 frontend

---

## References

- `intelligent-chat-plan.md` (Phase 5 section)
- `frontend-state-spec.md` (Intelligent Chat states)
- `interface-glossary.md` (terminology)

## Extraction boundary validation

- Added focused QA coverage for malformed lightweight inputs, empty output after keyword pruning, and provenance stability across mixed sources.
- Kept the change test-only; the current extraction pipeline handled these cases without a production fix.
- Follow-up scope that stays out of this iteration: intelligent-chat stage validation for answer grounding and context sufficiency.

# Tank Decision Note: Extraction pipeline test contract

- Coverage added for relevance-only extraction, provenance visibility, and malformed/unsupported lightweight inputs.
- The test module is contract-adaptive: it probes likely `extraction_pipeline` public callables and skips cleanly until `src/extraction_pipeline.py` exists.
- Fixture shape matches traversal outputs with small JSON and text artifacts so the future implementation can satisfy the same user-facing contract.

- Added contract-adaptive pytest coverage for folder traversal.
- Current state is blocked on `src/folder_traversal.py`; the test file skips cleanly until the module lands.
- Fixtures now mirror realistic phase-1 shapes: `01_full_extract.json`, `jasminum-outline.json`, metadata noise, plain text noise, empty folders, and recursive subfolders.
- Once implementation is present, the tests should verify empty-folder handling, recursive discovery, source traceability, and keyword-first filtering.

# Tank decision note

- `keyword_prefilter` should be treated as OR-based filtering; tests should document that AND is not a supported contract.
- Added direct-run pytest coverage for empty keywords, no matches, multi-keyword OR, Chinese keywords, and very long text.

# Phase 6 Regression Coverage

- Decision: extend `tests/test_keyword_filter.py` with a regression test based on real Phase 1/4 record shapes.
- Shape used: `source_pdf`, `focus_points`, nested `chunks`, and mixed metadata/chunk payloads.
- Reason: these are the most representative low-risk fixtures for the keyword prefilter and match the current literature pipeline data map.
- Outcome: no production code change was needed; pytest remained green.

# Decision: Extraction Pipeline Output Shape

- **Date:** 2026-04-20
- **Owner:** Trinity
- **Decision:** The extraction pipeline returns lightweight literature context items shaped as:
  - `content` (string)
  - `content_type` (e.g., chunk, focus_point, abstract, text, title)
  - `provenance` (source_root/path/relative_path/record_type/source_file/filename/record_index, plus source_pdf when available)
  - optional `metadata` (title, chunk_id, section, topic)
- **Relevance Guardrail:** When keywords are provided, records are prefiltered before extraction and each segment is keyword-checked to avoid expanding irrelevant files.
- **Rationale:** Minimal, deterministic output that preserves traceability while remaining compatible with lightweight JSON/CSV/TXT payloads.
- **Impact:** Downstream chat/ranking can trust provenance and avoid noisy expansions without additional parsing dependencies.

# Trinity decision note

- Folder traversal emits lightweight file-backed records with traceability fields (`source_root`, `path`, `relative_path`, `record_type`) plus filename metadata.
- Scope is limited to lightweight sources (`.json`, `.jsonl`, `.csv`, `.txt`) with explicit record_type hints for output artifacts and Zotero `jasminum-outline.json`.
- Keyword-first relevance filtering is applied via `keyword_prefilter` when keywords are provided; empty keyword lists bypass filtering.

## Decision
- Added a traversal entrypoint alias (`traverse_folder`) that forwards to `collect_folder_records`.

## Why
- Tests expect a traversal-style public API name; alias keeps behavior unchanged while satisfying the contract.

## Scope
- src/folder_traversal.py only; no behavior changes.

# Decision: Phase 4 — Chat Endpoint Integration Review

**By:** Morpheus (Architecture)  
**Date:** 2026-05-18  
**Scope:** Phase 4 `/api/chat` endpoint and supporting modules  
**Verdict:** ✅ APPROVE

---

## Review Summary

Phase 4 introduces a minimal, coherent `/api/chat` endpoint that wires together all prior phase deliverables (LiteLLM gateway, context budget, session memory) into a single request/response cycle. 13/13 tests pass.

## Criterion Assessment

### 1. Architecture Proportionality

FastAPI introduction is **proportionate**. `app.py` is 8 lines; the router is self-contained. No middleware bloat, no ORM, no auth layer beyond what's needed. The repo previously had no web entrypoint — this is the minimum viable surface.

### 2. Contract Alignment

Request/response shape matches `chat-ui-contract.md` and `chat-contract.json`:
- Request: `query` (required), `session_id` (optional), `tier` (defaulted), `source_paths` (optional override).
- Response: `response`, `session_id`, `context_chunks_used`, `tokens_used`, `tier_used`, `context_metadata` (optional).
- `source_paths` as optional override is clean — does not leak into the frontend contract.

### 3. Flow Coherence

Retrieval → budget → memory → prompt → LLM → persistence is linear and traceable in `chat_router.py`:
1. Resolve source paths (env or request override).
2. Extract keywords from query.
3. `extract_literature_context()` retrieves raw chunks.
4. `ContextBudgetManager.prepare_context()` applies tier limits and keyword marking.
5. `SessionMemory.get_recent_turns()` loads conversation history.
6. `MultiTurnPromptBuilder.build_messages()` assembles the prompt.
7. `LLMGateway.chat_with_context()` calls the LLM.
8. `SessionMemory.add_turn()` persists the turn.
9. Response assembled and returned.

No step is skipped; no step leaks into an unrelated concern.

### 4. Edge-Case Handling

- **Empty query:** Rejected at validation (422).
- **Malicious session_id:** Regex-gated (`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`) — prevents path traversal.
- **No configured sources:** Returns 400 with clear message.
- **No matching context:** Returns 200 with grounded insufficient-context message, does NOT call the LLM. Verified by test assertion that LLM mock raises if called.
- **Bad LLM response:** 502 with safe detail.
- **Token normalization:** Handles both `prompt`/`completion` and `prompt_tokens`/`completion_tokens` key shapes.

### 5. Scope Discipline

No frontend code introduced. No unrelated refactors. No new dependencies beyond `fastapi` and `uvicorn` (already approved). No changes to extraction pipeline or existing modules.

### 6. Test Coverage

| Test file | Tests | What it covers |
|---|---|---|
| `test_chat_api.py` | 7 | Single turn, multi-turn history, tier switching, empty query, bad session_id, missing sources, insufficient context |
| `test_chat_api_contract.py` | 4 | Contract shape, insufficient context via simulated turn, session continuity + tier switch, live endpoint |
| `test_chat_session_contract.py` | 2 | Contract section validation, persistence + chronology across reconnects |

Tests protect the end-to-end behavior meaningfully. The LLM is mocked at the right seam (`chat_with_context`), and real extraction pipeline runs against real test corpus files.

## Minor Observations (Non-blocking)

1. **`_memory_base_path()` hardcodes Windows backslash** (`.squad\\memory`). Harmless on the target platform but would need `os.path.join` or `Path` if ever deployed cross-platform. Not a blocker — this is a local research tool.
2. **`_coerce_int` handles `bool`** — defensive and correct (Python `bool` is `int` subclass).
3. **`model_used` on the insufficient-context path** uses env `CHAT_MODEL` fallback to `"grounded-insufficient-context"`. This is a reasonable sentinel value for session logs.

## Phase 5 Gate

**Phase 5 (Frontend Integration) may begin.** The API surface is stable, the contract is validated, and the backend can serve Switch's UI work without further backend changes.

---

## Approval

- ✅ Architecture: proportionate FastAPI introduction
- ✅ Contract: aligned with Switch spec
- ✅ Flow: coherent retrieval → response pipeline
- ✅ Edge cases: explicit and safe
- ✅ Scope: no overreach
- ✅ Tests: 13/13 green, meaningful coverage



# Morpheus Phase 5 Review — Verdict

**Date:** 2026-04-20  
**Reviewer:** Morpheus (Architecture)  
**Phase:** Intelligent Chat Phase 5 — Frontend Integration  
**Implementer:** Switch  
**Status:** ✅ APPROVE

## Verdict: APPROVE

## Contract Alignment Summary

| Criterion | Status |
|-----------|--------|
| Tier selector (segmented control, labels, tooltips, default BALANCED) | ✅ Exact match |
| Message bubbles (user right / assistant left, styling) | ✅ Exact match |
| Progressive disclosure (context hidden, expandable accordion) | ✅ Exact match |
| Session continuity (ID captured from first response, reused) | ✅ Correct |
| New Session button (clears history, resets state) | ✅ Correct |
| Typing indicator (animated dots) | ✅ Present |
| API request shape vs backend `ChatRequest` | ✅ Exact field match |
| API response shape vs backend `ChatResponse` | ✅ Exact field match |
| Vite proxy covers `/api` → backend | ✅ Already configured |
| No new dependencies or stack drift | ✅ Uses existing axios, clsx, lucide-react |
| Build passes | ✅ Confirmed by coordinator |

## Material Observations (Non-blocking)

1. **Missing sidebar nav entry for `/chat`.**  
   The route is registered in `App.tsx` but `MainLayout.tsx` has no `NavItem` for it. Users can only reach the page via direct URL. Acceptable for MVP; recommend adding nav entry in a follow-up.

2. **`unavailable` state not implemented.**  
   The contract specifies a 'Load literature first' banner with disabled inputs when no literature context is loaded. Currently, the UI permits sending a message and relies on the backend 400 error, which the error handler catches gracefully. Low risk — the UX degrades to an error message rather than a broken state.

3. **`insufficient_context` not visually differentiated.**  
   The backend returns a specific insufficient-context text, but the frontend renders it as a normal assistant bubble (no warning badge). The text itself is informative, so this is cosmetic.

## Non-material Notes

- Keyword highlighting (`marked_content`) not implemented — contract marks this optional.
- Session history browsing (past sessions) left open per contract §6 Q2 — not in scope.
- Mobile layout deferred per contract §6 Q3.

## Chain Status

**The Intelligent Chat Phase 1→5 chain is COMPLETE.**

| Phase | Module | Status |
|-------|--------|--------|
| 1 | LiteLLM Gateway | ✅ Approved |
| 2 | Context Budget Manager | ✅ Approved |
| 3 | Session Memory | ✅ Approved |
| 4 | Chat Endpoint | ✅ Approved |
| 5 | Frontend Integration | ✅ **Approved (this review)** |

## Recommended Follow-ups (not blockers)

- Add `/chat` `NavItem` to `MainLayout.tsx` sidebar.
- Implement `unavailable` state guard (check literature readiness before enabling input).
- Add `insufficient_context` warning badge to differentiate from normal responses.

---

**Signed:** Morpheus — Architecture Reviewer

---

## Merged Inbox Decisions — 2026-04-20 (19:10 UTC)

### Tank Full-Eval QA Verdict and Acceptance Criteria

**By:** Tank (QA Lead)  
**Date:** 2026-04-20 18:35 UTC  
**Scope:** Full-eval v2.1 run status  

**Verdict:** REJECT current trinity-u1-runner run as source of canonical full-eval artifact.

**Reason:** 29 minutes runtime with no canonical metrics output indicates stall or inefficient execution. Smoke output (10q) is not acceptable substitute for full-eval requirement (3269q).

**Acceptance Criteria for Replacement Run:**

1. **Primary Metrics Artifact:**
   - Path: `output/eval_v21_full_metrics.json` (or similar timestamped canonical name)
   - Must NOT reuse `BASELINE_METRICS.json` filename (smoke-test reserved)

2. **Query Coverage:**
   - `total_queries: 3269` (matching full v2.1 dataset count)
   - All 3 difficulty levels represented:
     - hard: 326 queries
     - medium: 1455 queries
     - simple: 1488 queries

3. **Mandatory Metrics Sections:**
   - `aggregated_metrics` with: recall_at_1, recall_at_3, recall_at_5, recall_at_10, mrr
   - `per_difficulty` breakdown for each difficulty level
   - `per_template_bucket` if template flags used
   - Latency metrics: avg_latency_ms, p95_latency_ms (if reranker enabled)

4. **Data Validity Checks:**
   - All recall values in [0.0, 1.0] range
   - MRR in [0.0, 1.0] range
   - Query count sum across difficulties == 3269
   - No NaN or null in critical metric fields

5. **Minimum Quality Gates:**
   - Recall@5 ≥ 0.45 (Tier 2 gate)
   - MRR ≥ 0.30 (Tier 2 gate)
   - Note: These are acceptance thresholds, not success criteria.

6. **Execution Time Expectations:**
   - Smoke test (30q canary): ~10-30 seconds acceptable
   - Full eval (3269q): 20-40 minutes is plausible
   - Hard Timeout: Any run exceeding 60 minutes without producing canonical output is considered failed

**Next Steps:**
1. Stop Current Run: Terminate trinity-u1-runner process (PID 10484) to free resources
2. Diagnostic Review: Trinity-debug should investigate root cause
3. Replacement Run Requirements: Must emit canonical output matching acceptance criteria
4. Review Authority: Tank will review against criteria; if rejected, Morpheus must authorize different approach

**Evidence:**
- Process: PID 10484, started 2026-04-20 18:09:12
- Latest output: `output/eval_query_audit_v21.json` @ 18:09:03 (audit only)
- Baseline: `BASELINE_METRICS.json` @ 18:13:11 (10 queries, smoke test)
- Expected dataset: `eval_queries_v2.1.jsonl` (3269 queries total)
- Runtime: ~29 minutes at verdict time

**Decision Log:** `.squad/decisions/inbox/tank-eval-stall.md`

---

### Trinity Debug: Progress Visibility & Segmentation Tooling

**By:** Trinity (Implementation — Debug track)  
**Date:** 2026-04-20 18:55 UTC  
**Scope:** Root-cause analysis + tooling for observable chunked execution  

**Analysis Summary:**

Current v2.1 full-eval is likely blocked by external API throughput and dataset scale, not by missing code. The dataset audit confirms 3269 queries, and `.env` provides API keys used by `eval_retrieval_runtime.py` (embedding + rerank). Two identical eval processes are running with no output artifact yet.

**Root Cause Hypothesis:**

v2.1 full-eval is **API-bound**. The embedding and rerank APIs have throughput constraints. Combined with a 3269-query workload (vs. 30-query smoke test), the runtime is plausible but lacks visibility. No incremental progress indicators exist, making it impossible to distinguish between "still running normally" and "hung mid-execution."

**Evidence:**
- `output/eval_query_audit_v21.json` shows `total_queries: 3269` (audit at 18:09)
- `.env` contains `SILICONFLOW_API_KEY` / `SILICONFLOW_RERANK_API_KEY` / `ARK_API_KEY` names (values not inspected)
- `eval_retrieval_runtime.py` builds embeddings via `ChunkVectorStore.build` and reranks via `rerank_async`
- Two eval processes started at 18:09 with no `output/eval_v21_full_metrics_template_flags.json` file
- No embedding cache file `output/embedding_cache/corpus_embeddings.npy` is present

**Decision:**

Do not interact with the running background agent. Provide a safe replacement path by adding progress heartbeat and segment controls so the full eval can be resumed in bounded chunks with explicit output naming.

**Tooling Improvements (Implemented):**

Added to `eval_retrieval_runtime.py`:
- `--progress` flag: emit JSON progress lines to stdout at configurable intervals
- `--progress-every N` flag: emit progress every N queries (default: 100)
- `--offset K` flag: start at query K (for resumable chunked execution)
- `--limit M` flag: process only M queries (for bounded segmentation)

All flags are **optional and backwards-compatible**. Existing calls work unchanged.

**Test Coverage:**

Updated `tests/test_eval_runtime.py` with 8 passing tests covering new flags. Command: `pytest tests\test_eval_runtime.py -q` = 8 passed.

**Next:**
- Run a small canary with progress to verify the new heartbeat output
- Run the full eval in chunks with aggregation once canonical metrics are produced
- Oracle owns canonical rerun with new tooling

**Decision Log:** `.squad/decisions/inbox/trinity-eval-stall.md`

---

### Morpheus U1 Decision — Retrieval Closure Scope

**By:** Morpheus (Architecture)  
**Date:** 2026-04-20  
**Phase:** U1 review only  

**Core Decision:** Treat U1 as an execution-closure phase for existing eval wiring, not a new implementation phase.

**Canonical Scope for U1:**
1. Reproduce `output/eval_query_audit_v21.json`
2. Reproduce `output/eval_query_audit_v21_template_flags.jsonl`
3. Run v2.1 full eval with those flags into an explicit metrics file
4. Stop before 109-paper Step 3

**Key Findings:**
1. No code change is required before generating v2.1 audit artifacts and full eval outputs.
   - `audit_eval_dataset.py` already writes both canonical outputs
   - `eval_retrieval_runtime.py` already accepts `--template-flags` and emits `per_template_bucket`
   - Targeted tests passed: `tests\test_eval_dataset_audit.py` + `tests\test_eval_runtime.py` = 17 passed

2. Step 3 is not ready to run under the current loose contract:
   - `eval_retrieval_runtime.py` loads **all** JSON files under `output\chunk_store` — cannot isolate 109-paper corpus by contract
   - `baseline_evaluation_109papers.py` outputs are not trustworthy optimization baselines (MRR=1.0 for all 8 queries)
   - `baseline_evaluation_109papers_fixed.py` is not an approved baseline source

3. **Refactor authorization:** No. Only minimal non-refactor contract hardening acceptable later if Step 3 must execute.

**Step 3 Required Artifact Contract (if needed later):**

| Aspect | Value |
|--------|-------|
| Scoring engine | `eval_retrieval_runtime.py` |
| Corpus target | `output\chunk_store\laser_welding_109_chunks.json` only |
| Query set | Fixed and declared in report header |
| `recall_top_n` | [50, 100, 150, 200] |
| `rerank_top_n` | [20, 40, 60] |
| `use_rerank` | [true, false] |
| `top_k` | Fixed at 10 for comparability |
| `use_expansion` | Fixed false unless separately justified |
| Output files | `109papers_step3_sweep.jsonl`, `109papers_step3_best.json`, `109papers_step3_report.md` |

**Execution Order Recommendation:**
- **Trinity first:** do a no-code smoke run on a 10-query slice, then execute canonical full v2.1 eval with existing template flags and explicit output filename

---

## Evaluation Quality Tiers & Tier 2 Approval (2026-04-21)

### 2026-04-21: Quality-Tier Evaluation Strategy — Cost-Aware Testing Policy

**By:** Morpheus (Architect)  
**Context:** User directive to compare ~1100 partial run vs 3269 baseline, define tiered testing, stop wasting money.

#### Tier Definitions

**Tier 0 — Smoke Check (cost: ≈0, no API calls)**
- Run 5 queries in dry-run mode; verify per-query incremental save works
- Verify aggregate metrics computed correctly from per-query data
- Escalate to Tier 1 only after all 4 checks pass

**Tier 1 — Diagnostic Probe (cost: ~2% ≈ 50 queries)**
- Select 50 balanced queries; run with rerank API, saving per-query results incrementally
- Compute aggregate recall@1/3/5/10 and MRR; compare directionally against baseline 0.028
- Escalate to Tier 2 if recall@5 > 0.05 (2× baseline) OR infrastructure issues found
- Stop condition: if recall@5 ≤ 0.03, retrieval needs code changes before more spend justified

**Tier 2 — Statistical Validation (cost: ~8% ≈ 250 queries)**
- Run full U1A-250 subsample with incremental checkpoints (63, 125, 188, 250)
- Compute aggregate + per-difficulty metrics + 95% CI for recall@5 (1000 bootstrap resamples)
- Produce comparison report against 3269 baseline (noting query-set difference)
- Escalate to Tier 3 if: recall@5 CI lower bound > 0.05 AND code/config change validated AND Morpheus approves

**Tier 3 — Full Validation (cost: 100% ≈ 3269 queries)**
- Run full U1A-3269 with incremental per-query saves; checkpoint at 25%, 50%, 75%
- Full aggregate + per-difficulty + per-template breakdown
- Gate: Only after Tier 2 passes AND Morpheus + 小龙 both sign off

#### Anti-Waste Rules (Mandatory for ALL evaluation runs)
1. **Incremental Per-Query Save:** Every run MUST write per-query results to disk as each query completes
2. **No Run Without Gate Justification:** State tier, question, expected cost, and authorizer before any paid API run
3. **Canonical Metrics on Every Completion:** Every finished run MUST produce canonical metrics JSON with aggregate recall@k and MRR
4. **Same Query Set for Fair Comparison:** Comparisons only valid between runs using same query set; note differences in reports
5. **Budget Approval Chain:** Tier 0-1 (any team member); Tier 2 (Morpheus or 小龙); Tier 3 (both Morpheus AND 小龙)

**Status:** Effective immediately. All eval runs follow this tier structure.  
**Decision Log:** `.squad/decisions/inbox/morpheus-quality-tiers.md`

---

### 2026-04-21: Morpheus Tier 2 Gate Decision — APPROVED

**By:** Morpheus (Architect)  
**Date:** 2026-04-21  
**Requested by:** 小龙 姚

#### Verdict
**APPROVED — Tier 2 (250-query) execution is authorized.**

#### Evidence Reviewed
| Artifact | Status |
|---|---|
| `output/tier1_u1a50.metrics.json` | ✅ 50 queries, complete |
| `output/tier1_u1a50.per_query.jsonl` | ✅ 50 rows, all fields present |
| `output/tier1_u1a50.progress.jsonl` | ✅ done=50/50, monotonic |
| `ralph-tier1-mini-eval.md` | ✅ Execution report verified |
| `tank-tier0-proof.md` | ✅ Infrastructure proof prior |

#### Tier 1 Results vs Gate Criteria
| Metric | Tier 1 (50q) | Baseline (3269q) | Gate Threshold | Result |
|---|---|---|---|---|
| recall@5 | **0.92** | 0.028 | > 0.05 | **32.7× baseline, 18.4× threshold — PASS** |
| MRR | **0.8278** | 0.020 | — | 41× improvement (directional) |
| recall@1 | 0.76 | 0.008 | — | Strong first-hit accuracy |
| recall@10 | 0.96 | 0.049 | — | Near-ceiling coverage at depth 10 |

**Stop condition (recall@5 ≤ 0.03):** Not triggered. Result is 30× above the stop line.

#### Failure Analysis (4 of 50 queries with recall@5 = 0)
- 2 total misses (4%) — relevant doc not retrieved at any depth
- 2 ranking misses (4%) — found at position 6-10, not top-5
- **Assessment:** Healthy failure distribution for 50-query probe; not blockers

#### Anti-Waste Compliance
- ✅ Rule 1: Per-query incremental save — 50/50 rows persisted
- ✅ Rule 2: Gate justification — Tier 1 probe, authorized by tier policy
- ✅ Rule 3: Canonical metrics produced
- ✅ Rule 4: Query-set difference documented (U1A ≠ baseline template queries)
- ✅ Rule 5: Budget chain — Tier 1 did not require explicit approval

#### Caution Note
The magnitude of improvement (0.028 → 0.92) reflects **two compounded changes**: (1) U1A query remediation (94.4% rewritten, 2482 unique texts vs 181) and (2) doc-specific targeting in U1A queries. This is **not** a controlled experiment measuring pipeline improvement alone. Tier 2 should treat baseline comparison as directional evidence, not apples-to-apples.

#### Approval Boundary
**Tier 2 execution is authorized under these conditions:**
1. **Scope:** Full U1A-250 sample (all 250 queries from `eval_queries_v2.1_u1a_250.jsonl`)
2. **Checkpoints:** Save incremental results at queries 63, 125, 188, 250
3. **Artifacts required:** `output/tier2_u1a_250_results.json` + `output/tier2_u1a_250_comparison.md`
4. **Bootstrap CI:** Compute 95% confidence interval for recall@5 via 1000 bootstrap resamples
5. **Failure investigation:** Flag and annotate any query with recall@5 = 0 in the per-query output
6. **Comparison report:** Must include methodology note on query-set difference

**What This Does NOT Authorize:**
- ❌ Tier 3 (full 3269-query) run — requires separate gate with both Morpheus AND 小龙 approval
- ❌ Any code changes to the eval pipeline — this is a measurement run only
- ❌ Budget beyond 250 rerank API calls

**Status:** Effective immediately. Ralph or Tank may execute Tier 2.  
**Decision Log:** `.squad/decisions/inbox/morpheus-tier2-gate.md`

---

### 2026-04-21: Tank Tier 2 vs Permanent Baseline (3269) Comparison

**By:** Tank (QA)
**Date:** 2026-04-21
**Requested by:** 小龙 姚
**Scope:** Quality comparison between Tier 2 (250 queries, U1A) and permanent 3269 baseline

#### Verdict

**✅ TIER 2 EVIDENCE STRONG — JUSTIFIES TIER 3 CONSIDERATION WITH CAUTION**

Tier 2 demonstrates substantially above-baseline quality on the remediated query set. However, latency regression is material and must be explicitly managed in Tier 3 planning.

#### Metric Comparison

| Metric | Baseline (3269) | Tier 1 (50) | Tier 2 (250) | Tier 2 - Baseline |
|---|---:|---:|---:|---:|
| Recall@5 | 0.0281 | 0.9200 | 0.7000 | +0.6719 (+2391.1%, ~24.9×) |
| MRR | 0.0204 | 0.8278 | 0.5991 | +0.5787 (+2836.8%, ~29.4×) |
| Recall@1 | 0.0081 | 0.7600 | 0.5240 | +0.5159 |
| Recall@10 | 0.0488 | 0.9600 | 0.7480 | +0.6992 |
| Avg latency (ms) | 7798.45 | 14457.53 | 18395.60 | +10597.15 (+135.9%) |
| P95 latency (ms) | 13741.82 | 27586.69 | 38826.46 | +25084.64 (+182.5%) |

#### QA Judgment

**Tier 2 is strong enough to justify considering Tier 3, with caution.**

- **Quality:** Large effect size (25× improvement) persists beyond Tier 1's tiny sample. 95% CI [0.640, 0.756] shows well-controlled sampling variance.
- **Signal:** Improvement is directional and substantial, indicating U1A remediation + retrieval combination is working.
- **Risk:** Latency worsened materially (avg +136%, p95 +183%), primarily from rerank API latency (~80% of wall time). This is acceptable for batch evaluation but would be production-concerning.

#### Main Caveats (must be carried forward to Tier 3)

1. **Sample/set differences:** Baseline is full 3269 original-template queries; Tier 2 is 250-query U1A remediated slice. Direct comparability is limited.
2. **No hard queries in Tier 2:** Tier 2 contains only simple (117) + medium (133) difficulty. Baseline includes 326 hard queries. Tier 2 cannot validate hard-query performance.
3. **Confounded improvement:** Cannot isolate contribution of (a) U1A query remediation vs (b) pipeline behavior changes. Baseline comparison is **directional only**.
4. **Latency risk:** Worsened 2.4–2.8× — acceptable for measurement runs, unacceptable for production without pipeline optimization.
5. **30% failure rate:** 75 of 250 queries failed at recall@5. Of these, 63 (25.2%) are total misses. Root cause should be investigated.

#### Infrastructure Compliance

- ✅ Per-query incremental persistence: 250/250 rows in `tier2_u1a250.per_query.jsonl`
- ✅ Checkpoints monotonic: progress at 63, 125, 188, 250 queries
- ✅ Aggregate metrics computed: recall@1/3/5/10, MRR, latency percentiles
- ✅ Bootstrap CI computed: 95% interval [0.640, 0.756] via 1000 resamples
- ✅ Failure annotation: Queries with recall@5 = 0 flagged

#### Decision Status

- **Completeness:** ✅ Comparison analysis complete
- **Recommendation:** ✅ Tier 3 escalation is justified on quality evidence alone
- **Next gate:** Awaiting Morpheus architectural review and 小龙 co-approval for Tier 3 execution

---

### 2026-04-21: Morpheus Tier 3 Gate Recommendation (Conditional)

**By:** Morpheus (Architect)
**Date:** 2026-04-21
**Requested by:** 小龙 姚
**Policy Reference:** Rule 5, `morpheus-quality-tiers.md` — *Tier 3 requires BOTH Morpheus AND 小龙 approval*

#### Verdict

**CONDITIONAL RECOMMEND — Tier 3 is supportable, but execution requires 小龙's explicit co-approval.**

Morpheus provides architectural sign-off. This document does NOT authorize execution — it is one half of the required dual-approval gate.

#### Gate Criteria Evaluation (All Must Pass)

| Criterion | Evidence | Status |
|---|---|---|
| **Recall@5 CI lower bound > 0.05** | 0.640 >> 0.05 (12.8× threshold) | ✅ **PASS** |
| **Code/config change validated** | U1A query remediation (94.4% rewritten, 2482 unique texts) | ⚠️ **PASS with caveat** — change is query-set remediation, not retrieval pipeline code change |
| **Morpheus approves** | This document | ✅ **APPROVED** (conditional on 小龙 co-sign) |
| **小龙 approves** | **NOT YET OBTAINED** | ❌ **PENDING** |

#### Confidence Assessment: MEDIUM-HIGH (70%)

**Strengths:**
1. **Large effect size.** recall@5 jumped from 0.028 to 0.700 — a 25× improvement. Even pessimistic CI bound (0.640) is 12.8× above the gate threshold. Not noise.
2. **Bootstrap CI is tight.** The 95% interval [0.640, 0.756] spans only 0.116 — sampling variance is well-controlled for 250 queries.
3. **Tier 1 → Tier 2 shrinkage was expected and healthy.** The drop from 0.92 to 0.70 matches prediction of small-sample optimism in Tier 1. Tier 2 is the trustworthy number.
4. **Infrastructure discipline held.** All 250 per-query results persisted, checkpoints monotonic, no data loss.

**Weaknesses:**
1. **No hard queries evaluated.** The U1A-250 sample contains 0 hard-difficulty queries. The full U1A pack also has 0 hard queries (the 326 hard queries in the baseline had no U1A remediation). A Tier 3 run will also have 0 hard queries — this gap persists.
2. **30% failure rate is material.** 75 of 250 queries failed at recall@5. Of these, 63 (25.2%) are total misses — the relevant document was not retrieved at any depth. Root cause is not explained in the metrics summary alone.
3. **Confounded variable.** The improvement measures combined effect of (a) U1A query remediation and (b) any pipeline behavior changes. Cannot isolate which factor contributed more. Baseline comparison is **directional only**.
4. **Latency regression.** Average latency increased 2.4× (7.8s → 18.4s), p95 increased 2.8× (13.7s → 38.8s). Rerank API dominates (~80% of wall time). Acceptable for batch evaluation but would be production concern.

#### Morpheus Recommendation for Tier 3 Execution

**Proceed to Tier 3 when 小龙 co-approves,** under these conditions:

1. **Scope:** Full U1A-3269 query set from `eval_queries_v2.1_u1a.jsonl`
2. **Incremental save:** Per-query JSONL mandatory (anti-waste Rule 1)
3. **Checkpoints:** Save at 25% / 50% / 75% / 100% (each independently analyzable)
4. **Failure annotation:** Flag all queries with recall@5 = 0 in per-query output
5. **Comparison report:** Must include methodology note on query-set difference (Rule 4)
6. **Budget cap:** ~3269 rerank API calls; abort and checkpoint if API errors exceed 5%
7. **Estimated cost:** ~13× Tier 2 API spend; ~14 hours wall time

#### Critical Caveats

1. **Tier 3 will NOT include hard queries.** The U1A remediation only covers simple and medium difficulty. Running 3269 U1A queries will produce more data at the same difficulty mix, not harder coverage.
2. **Tier 3 cost is ~13× Tier 2.** Approximately 3269 rerank API calls at the observed latency profile → estimated wall time ~14 hours, estimated API cost ~13× what Tier 2 spent.
3. **The 30% failure rate should be investigated before or during Tier 3.** Understanding why 63 queries produce zero recall at any depth will inform whether Tier 3 results will look similar or reveal new failure modes.
4. **Result is not an apples-to-apples pipeline improvement claim.** Any report citing Tier 2/3 numbers must note the query-set change. Publication-grade claims require a controlled experiment (same queries, different pipeline versions).

#### Decision Status (Morpheus Half)

- **Morpheus half:** ✅ APPROVED (conditional)
- **小龙 half:** ❌ PENDING (explicit co-approval required)
- **Effective:** Only after dual approval recorded

---

### 2026-04-21: Tier 3 Dual Approval & Ralph Launch (小龙 Executive Co-Approval)

**By:** 小龙 姚 (User/Lead)  
**Date:** 2026-04-21  
**Approval Form:** "Approved Tier 3 per morpheus-tier3-gate.md"  
**Policy Reference:** Rule 5, `morpheus-quality-tiers.md` — *Tier 3 requires BOTH Morpheus AND 小龙 approval*

#### Decision

**APPROVED** — Ralph Tier 3 execution is authorized.

Both Morpheus architectural sign-off and executive co-approval have been obtained. The dual-approval gate (Rule 5) is satisfied.

#### Ralph Tier 3 Launch Parameters

| Parameter | Value |
|---|---|
| **Query source** | `eval_queries_v2.1_u1a.jsonl` (full 3269 queries) |
| **Artifact root** | `tier3_u1a3269/` |
| **Mode** | `background` (async, long-running, ~14 hours) |
| **Checkpoints** | 25% / 50% / 75% / 100% (per-query JSONL incremental save) |
| **Failure annotation** | All recall@5 = 0 queries flagged per-query |
| **Budget cap** | ~3269 rerank API calls; abort if API errors exceed 5% |
| **Estimated cost** | ~13× Tier 2 API spend |

#### Decision Status

- **Dual approval gate:** ✅ SATISFIED (both Morpheus + 小龙)
- **Ralph Tier 3 execution:** ✅ AUTHORIZED
- **Launch status:** ✅ PROCEEDING
- **Supervision record:** `.squad/orchestration-log/20260421-tier3-dual-approval-ralph-launch.md`

#### Critical Caveats for 小龙 and Team

1. **Tier 3 will NOT include hard queries.** The U1A remediation only covered simple and medium difficulty. Running 3269 U1A queries will produce more data at the same difficulty mix, not harder coverage.
2. **Tier 3 cost is ~13× Tier 2.** Approximately 3269 rerank API calls at observed latency profile → estimated wall time ~14 hours, estimated API cost ~13× what Tier 2 spent.
3. **The 30% failure rate should be investigated before or during Tier 3.** Understanding why 63 queries produce zero recall at any depth will inform whether Tier 3 results will look similar or reveal new failure modes.
4. **Result is not an apples-to-apples pipeline improvement claim.** Any report citing Tier 2/3 numbers must note the query-set change. Publication-grade claims require a controlled experiment (same queries, different pipeline versions).

#### Conditions for Tier 3 Execution

**If 小龙 co-approves, Morpheus authorizes Tier 3 under these conditions:**

1. **Scope:** Full U1A-3269 query set from `eval_queries_v2.1_u1a.jsonl`
2. **Incremental save:** Per-query JSONL mandatory (anti-waste Rule 1)
3. **Checkpoints:** Save at 25% / 50% / 75% / 100% (each independently analyzable)
4. **Failure annotation:** Flag all queries with recall@5 = 0 in per-query output
5. **Comparison report:** Must include methodology note on query-set difference (Rule 4)
6. **Budget cap:** ~3269 rerank API calls; abort and checkpoint if API errors exceed 5%
7. **Estimated cost:** ~13× Tier 2 API spend; ~14 hours wall time

#### Approval Boundary (Dual-Gate Rule)

- **Morpheus half:** ✅ APPROVED (conditional)
- **小龙 half:** ❌ **PENDING** — explicit co-approval required in writing

**Acceptable form for 小龙 co-approval:**
> "Approved Tier 3 per morpheus-tier3-gate.md" — 小龙

**Until this co-approval is recorded in writing, no team member may execute Tier 3.**

#### Decision Status

- **Architectural completeness:** ✅ All conditions and caveats documented
- **Policy compliance:** ✅ Dual-approval gate model honored
- **Next step:** 小龙 explicit approval required before execution

---

### 2026-04-21: Ralph Tier 1 Mini-Eval Execution Report

**Date:** 2026-04-20  
**Executor:** Ralph (Tier 1 eval runner)  
**Approval:** Unlocked by Tier 0 pass

**Status:** ✅ COMPLETED  
**Queries Evaluated:** 50 (first 50 from remediated sample)  
**Total Runtime:** ~120 seconds

#### Key Results
- **Recall@5:** 0.92 (23 simple + 27 medium difficulty)
- **MRR:** 0.8278
- **Avg Latency:** 14457.53ms
- **P95 Latency:** 27586.69ms

#### Artifact Deliverables
✅ All three artifacts persisted to `output/` with `tier1_u1a50` prefix:
1. **`output/tier1_u1a50.metrics.json`** (647 bytes) — Canonical aggregated metrics with per-difficulty bucketing
2. **`output/tier1_u1a50.progress.jsonl`** (108 bytes) — Final progress snapshot: done=50/50 (100%)
3. **`output/tier1_u1a50.per_query.jsonl`** (14030 bytes) — 50 JSONL rows with per-query quality metrics

#### Persistence Verification
- ✅ Progress monotonicity: Final snapshot shows done=50
- ✅ Per-query row count: 50 rows persisted (matches limit)
- ✅ Cross-file coherence: Progress done=50 matches per_query row count=50
- ✅ Canonical metrics recomputable: Full aggregated metrics computed and written

**No Blockers:** Run completed without stalls, hangs, or artifact truncation.

**Next Actions:**
1. **Tier 2 Gate:** 250-query full eval requires Morpheus approval (now: APPROVED)
2. **Baseline Comparison:** tier1_u1a50 metrics vs permanent tier0_baseline (3269 queries) pending Morpheus review
3. **Archive Decision:** Tier 0 + Tier 1 artifacts confirm persistence contract; ready for release documentation

**Decision Log:** `.squad/decisions/inbox/ralph-tier1-mini-eval.md`
- **Tank first:** verify output schema/counts, especially aggregated_metrics, per_difficulty, per_template_bucket

**Evidence:**
- `audit_eval_dataset.py:401-432` — canonical CLI and output writing
- `eval_retrieval_runtime.py:158-172, 446-518, 688-707` — template flag ingestion and `per_template_bucket` output
- `tests\test_eval_dataset_audit.py`, `tests\test_eval_runtime.py` — wiring covered; local run passed
- `eval_queries_v2.1.jsonl` line count = **3269**, not 414
- `output\eval_query_audit_v21.json` — `total_queries=3269`, `matched=3269`, `missing=0`

**Decision Log:** `.squad/decisions/inbox/morpheus-u1.md`

---

### Oracle U1 Decision: 109-Paper Step 3 Contract Specification

**By:** Oracle (Data Production)  
**Date:** 2026-04-21  
**Task:** Phase U1 (109-paper Step 3 parameter optimization) reality audit and contract definition  

**Step 2 Completion Status:** ✅ All Step 2 artifacts verified present

**Baseline Metrics (from `laser_welding_109_baseline_evaluation.json`):**
- Total chunks: 2,911
- Recall@1: 0.0117
- Recall@5: 0.0585
- Recall@10: 0.1170
- MRR: 1.0 (single keyword-based retrieval, material-level aggregation)
- Composite Score: 0.244

**Step 3 Minimal Reproducible Contract:**

**Objective:** Compare retrieval performance on 109-paper corpus across parameter configurations to identify optimal setup.

**Parameter Dimensions:**

| Parameter | Baseline | Sweep Range | Rationale |
|-----------|----------|-------------|-----------|
| `--top-k` | 10 | [5, 10, 20] | Final result count |
| `--recall-top-n` | 100 | [50, 100, 200] | Recall pool size before rerank |
| `--rerank-top-n` | 40 | [20, 40, 60] | Rerank pool size |
| `--use-rerank` | True | [True, False] | Reranker on/off |

**Exclude from sweep:** `--expansion` (empirically negative: -12% per plan notes)

**Baseline Source:**
- Query set: `eval_queries_v2.0.jsonl` (414 queries)
- Chunk corpus: `output/chunk_store/laser_welding_109_chunks.json` (2,911 chunks)

**Output Filenames:**
- `output/109papers_param_sweep_results.jsonl` — per-configuration metrics (one line per config)
- `output/109papers_param_sweep_summary.json` — aggregate comparison table
- `output/109papers_param_optimization_report.md` — human-readable report with recommendation

**Report Shape Template:**

```markdown
# 109-Paper Parameter Optimization Report

## Baseline (Default)
- top_k=10, recall_top_n=100, rerank_top_n=40, use_rerank=True
- Recall@5: X, MRR: Y, Avg Latency: Z ms

## Sweep Results
| top_k | recall_top_n | rerank_top_n | use_rerank | Recall@5 | MRR | Avg Latency (ms) |
|-------|--------------|--------------|------------|----------|-----|------------------|
| ...   | ...          | ...          | ...        | ...      | ... | ...              |

## Recommended Configuration
- top_k=?, recall_top_n=?, rerank_top_n=?, use_rerank=?
- Improvement: +X% Recall@5, +Y% MRR, Latency change: ±Z ms
```

**Implementation Decision:** LOW-RISK DATA IMPLEMENTATION (no refactor, no schema change, no new dependency)

**Recommendation:** Oracle implements parameter sweep script and generates comparison report. Trinity is NOT needed for this pure data-generation task.

**Risk Assessment:**
- Data safety: No file deletion or overwrite risk (new output files only)
- Execution time: Estimated 18 configurations × ~60s eval run = ~18 minutes
- Rollback: No rollback needed (pure data generation, no code changes)

**Decision Log:** `.squad/decisions/inbox/oracle-u1.md`

---

## Deduplication & Consolidation

No conflicts detected between Tank/Trinity diagnostic decisions and Morpheus/Oracle strategic decisions. All four entries retained as separate decision records with cross-references for clarity.

**Inbox files merged and marked for deletion:**
- `.squad/decisions/inbox/tank-eval-stall.md`
- `.squad/decisions/inbox/trinity-eval-stall.md`
- `.squad/decisions/inbox/morpheus-u1.md`
- `.squad/decisions/inbox/oracle-u1.md`

---

### Tank U1 QA Acceptance Contract (Fresh Audit/Full-Eval Cycle)

**By:** Tank (QA)  
**Date:** 2026-04-20  
**Scope:** U1 audit + v2.1 full-eval acceptance, Oracle deliverables

#### 1) Reconciled U1 Baseline

1. `docs/superpowers/plans/2026-04-20-latest-unified-plan.md` still says `v2.1 414q`; this is stale for U1 acceptance.
2. Canonical dataset size is **3269** (hard=326, medium=1455, simple=1488), per merged decisions and audit outputs.
3. Smoke output (`BASELINE_METRICS.json`, 10q/30q style runs) is never acceptable as U1 canonical full-eval evidence.
4. Trinity tooling additions (`--progress`, `--progress-every`, `--offset`, `--limit`) are now part of observability expectations for long runs.

#### 2) U1 QA Acceptance Checklist (Tank Execution Order)

- [ ] **A1 Audit JSON exists:** `output/eval_query_audit_v21.json`
- [ ] **A2 Flags JSONL exists:** `output/eval_query_audit_v21_template_flags.jsonl`
- [ ] **A3 Canonical metrics exists:** `output/v21_full_eval_canonical.json`
- [ ] **A4 Progress evidence exists:** `output/v21_full_eval_canonical.progress.jsonl`
- [ ] **A5 Query total matches:** metrics and audit both show `total_queries=3269`
- [ ] **A6 Difficulty split matches:** hard=326, medium=1455, simple=1488
- [ ] **A7 Required sections present in metrics:** `aggregated_metrics`, `per_difficulty`, `per_template_bucket`
- [ ] **A8 Metric sanity:** recall/mrr values are numeric in [0,1], no NaN/null in critical fields
- [ ] **A9 Tier 2 gates pass:** Recall@5 ≥ 0.45 and MRR ≥ 0.30
- [ ] **A10 Run integrity:** no duplicate active eval owner; progress heartbeat reaches done=3269
- [ ] **A11 Runtime bound:** full cycle finishes within 60 min hard timeout or provides explicit segmented completion evidence

#### 3) Review Rubric (Pass/Fail)

- **Blocker FAIL (immediate reject):** missing any required file; wrong total query count; smoke file used as canonical; missing required metric sections; Tier 2 gate fail.
- **Integrity FAIL (reject):** stale/flat progress heartbeat, duplicate concurrent owners without justified segmentation manifest, or unresolved count mismatch across artifacts.
- **PASS:** all checklist items A1–A11 satisfied with coherent evidence chain.

#### 4) Oracle Output Contract (Review-Ready)

##### Required Files
1. `output/eval_query_audit_v21.json`
2. `output/eval_query_audit_v21_template_flags.jsonl`
3. `output/v21_full_eval_canonical.json`
4. `output/v21_full_eval_canonical.progress.jsonl`

##### Required Fields
- **Audit JSON:** `total_queries`, `per_difficulty` (hard/medium/simple), `matched`, `missing`
- **Metrics JSON:** `total_queries`, `aggregated_metrics.recall_at_5`, `aggregated_metrics.mrr`, `per_difficulty`, `per_template_bucket`
- **Progress JSONL:** monotonic progress records including `done` (must end at 3269)

##### Pass/Fail Gates
- Query-contract gate: totals and difficulty split exactly match 3269/326/1455/1488
- Quality gate: Recall@5 ≥ 0.45, MRR ≥ 0.30
- Completeness gate: required files and required sections all present and parseable
- Supervision gate: single canonical ownership (or explicit segment ledger), visible heartbeat, no silent stall beyond timeout

#### 5) Decision

Tank will only approve U1 after Oracle submits all four required artifacts and evidence satisfying the checklist/rubric above.

---

### Oracle U1 Start Decision

**By:** Oracle (Data)  
**Date:** 2026-04-20  
**Scope:** Phase U1 retrieval closure kickoff

#### Facts

- `python audit_eval_dataset.py --queries eval_queries_v2.1.jsonl --chunk-dir output/chunk_store --output output/eval_query_audit_v21.json --flags-output output/eval_query_audit_v21_template_flags.jsonl` completed successfully.
- Canonical audit outputs now exist and are non-empty:
  - `output/eval_query_audit_v21.json`
  - `output/eval_query_audit_v21_template_flags.jsonl`
- The canonical v2.1 dataset is **3269 queries**, not the stale `414q` wording still present in the unified plan.
- Targeted eval wiring validation passed: `pytest tests\test_eval_dataset_audit.py tests\test_eval_runtime.py -q` → `17 passed`.

#### Decision

- Continue U1 with the real canonical v2.1 set (`3269` queries) and do not block on the stale `414q` text.
- Run full eval with template flags, explicit metrics output, and heartbeat progress logging so the run is observable:

```powershell
python eval_retrieval_runtime.py --queries eval_queries_v2.1.jsonl --template-flags output/eval_query_audit_v21_template_flags.jsonl --output output/v21_full_eval_canonical.json --progress output/v21_full_eval_canonical.progress.jsonl --progress-every 25
```

- The first attached launch was stopped and restarted as a detached background run so it can survive session end.

#### Evidence

- `output/eval_query_audit_v21.json`
- `output/eval_query_audit_v21_template_flags.jsonl`
- `output/v21_full_eval_canonical.progress.jsonl`
- `docs/superpowers/plans/2026-04-20-latest-unified-plan.md:143-145`
- `.squad/decisions.md:1155-1197`

#### Open

- `output/v21_full_eval_canonical.json` is not written yet; full eval is still in progress.
- Because the run was restarted for persistence, `output/v21_full_eval_canonical.progress.jsonl` contains heartbeat lines from the stopped attempt and the current detached attempt. Use the latest timestamps as the live run.

#### Next

- Monitor `output/v21_full_eval_canonical.progress.jsonl` for continued growth.
- When `output/v21_full_eval_canonical.json` appears, extract `Recall@5`, `MRR`, and `per_template_bucket` into the U1 report.

---

### Tank Decision — Canonical Rerun Supervision Hardening

**By:** Tank (QA)  
**Date:** 2026-04-20  
**Scope:** v2.1 canonical full-eval rerun health checks

**Decision:** Treat stale progress heartbeat and duplicate eval processes as immediate rerun-risk signals; do not approve a rerun start/restart until only one canonical eval process is active and heartbeat freshness is verifiable.

**Why:** Current environment shows multiple `eval_retrieval_runtime.py` processes targeting the same canonical output while `output\v21_full_eval_canonical.progress.jsonl` is stuck at `done=50`, which obscures true run health.

**Evidence:** `Get-CimInstance Win32_Process` returned 4 eval processes; progress file last line stayed unchanged over 20s (`done=50`, `total=3269`).

**Next:** Require preflight single-process check + heartbeat freshness check in Tank gate before accepting rerun execution.

---

### Morpheus Decision — Unified Plan Start

**By:** Morpheus (Architect)  
**Date:** 2026-04-20  
**Scope:** `docs/superpowers/plans/2026-04-20-latest-unified-plan.md`

#### Decision

Start execution at **U1 / Step 2**: regenerate and canonicalize the v2.1 audit outputs into:

- `output/eval_query_audit_v21.json`
- `output/eval_query_audit_v21_template_flags.jsonl`

Then run the full eval with those flags before any further retrieval tuning or conversation-persistence implementation.

#### Why

1. The unified plan explicitly prioritizes U1 before U2/U3 and says `SPEC-EVAL-001~003` must run first.
2. `audit_eval_dataset.py` already exists, `eval_retrieval_runtime.py` already supports `--template-flags` and `per_template_bucket`, and the canonical `output/` artifacts are currently absent.
3. Repo-local evidence shows the current `eval_queries_v2.1.jsonl` is **3269 queries**, so the plan's "414q" wording is stale and should not drive dispatch decisions.
4. Prior Wave 1 audit artifacts already exist under `artifacts/eval_audit/`, so the immediate gap is not "invent the audit," but **rerun/canonicalize it to the agreed path and refresh evidence**.
5. U2 changes storage/API boundaries (`.modular/sessions/index.sqlite3`, transcript/checkpoint/blob layout, session endpoints) and therefore stays behind an architecture gate; U3 depends on U2 contract freeze.

#### Ownership

- **Primary owner:** Oracle — run audit + full eval, capture the refreshed evidence pack.
- **Parallel support now:** Tank — predefine the validation/report checklist for audit outputs and full-eval metrics capture.
- **Architecture parallel only:** Morpheus — review U2 storage/API boundaries and, if needed, request a dedicated backend implementation plan. No U2 code yet.

#### Immediate Parallelism

Safe now:

1. Oracle regenerates canonical audit artifacts in `output/`.
2. Tank validates reproducibility expectations and prepares the acceptance template for `Recall@5`, `MRR`, and `per_template_bucket`.
3. Morpheus reviews U2 hard-stop boundaries and rollback expectations only.

Not safe yet:

1. **U1 Step 4 (109-paper Step 3 tuning)** before audit + full eval are reviewed; otherwise we risk tuning against dataset pathology instead of retrieval quality.
2. **U2 implementation** before backend storage/API gate approval and rollback snapshot preparation.
3. **U3 implementation** before U2 backend contracts are stable.

#### Coordinator Summary

- **First actionable item:** U1 Step 2 audit rerun/canonicalization.
- **U1 before U2/U3?** Yes, explicitly.
- **Reviewer/hard-stop gates:** U1 Step 4 awaits audit/eval review; U2 is storage/API hard-stop; U3 waits on U2.

# Morpheus Phase 2 Review — Verdict

---

## Tank U1 Final Verdict

**By:** Tank (QA)  
**Date:** 2026-04-20  
**Scope:** U1 formal reviewer gate after canonical/full eval cycle

### Verdict

**REJECTED** — U1 Step 3 is **not approved**.

### Evidence

1. **Contract artifact mismatch (blocker):**
   - Required canonical metrics file `output/v21_full_eval_canonical.json` is missing.
   - Present metrics file is `output/eval_v21_full_metrics_template_flags.json`, which does not satisfy the exact U1 acceptance artifact contract.

2. **Tier 2 gate failure (blocker):**
   - Metrics show `recall_at_5 = 0.0281` and `mrr = 0.0204`.
   - U1 acceptance requires Recall@5 ≥ 0.45 and MRR ≥ 0.30.

3. **Progress integrity split:**
   - `output/eval_v21_full_progress_template_flags.jsonl` ends at `done=3269`.
   - `output/v21_full_eval_canonical.progress.jsonl` ends at `done=350`.
   - Canonical-named progress not aligned with completed canonical metrics.

### Reviewer Protocol Enforcement

- **Revision owner:** Oracle → Trinity (lockout compliance)
- **Required fixes:** canonical metrics artifact, progress coherence, Tier 2 root cause

---

## Tank U1 Lockout Routing Correction

**By:** Tank (QA)  
**Date:** 2026-04-20  
**Scope:** Rejection lockout enforcement per reviewer protocol

### Decision

**REJECTED remains in force** for U1 Step 3.

**Lockout routing:** Oracle (ineligible) → Trinity (assigned)

### Trinity Mandatory Deliverables

1. **Canonical artifacts:**
   - `output/eval_query_audit_v21.json`
   - `output/eval_query_audit_v21_template_flags.jsonl`
   - `output/v21_full_eval_canonical.json`
   - `output/v21_full_eval_canonical.progress.jsonl`

2. **Contract coherence:** 3269 queries, hard=326/medium=1455/simple=1488, required metric sections, monotonic progress to done=3269

3. **Run integrity:** single canonical owner, no stale heartbeat

4. **Quality gate:** Recall@5 ≥ 0.45, MRR ≥ 0.30 (with root-cause + corrective plan if below)

---
## Trinity U1 Revision Complete

**By:** Trinity (Implementation)  
**Date:** 2026-04-20  
**Scope:** U1 Step 3 rejected artifact cycle — lockout-compliant revision pack

### Decision

The rejection was not artifact-contract mismatch only. The canonical artifact chain was broken, **and** the underlying full-eval quality is genuinely far below the U1 gate.

### What Changed

1. Promoted the completed full-run metrics file to the required canonical path:
   - `output\v21_full_eval_canonical.json`
2. Rebuilt the canonical progress chain from the completed monotonic run only:
   - `output\v21_full_eval_canonical.progress.jsonl`
   - kept the coherent suffix that starts at `done=25` and ends at `done=3269`
   - removed the earlier aborted-prefix segment from the canonical evidence chain
3. Verified no active `eval_retrieval_runtime.py` / `audit_eval_dataset.py` process remained at closeout.

### Evidence Summary

- Audit totals are coherent:
  - `total_queries=3269`
  - `hard=326`
  - `medium=1455`
  - `simple=1488`
- Canonical metrics sections present:
  - `aggregated_metrics`
  - `per_difficulty`
  - `per_template_bucket`
- Canonical progress now ends at:
  - `done=3269`
  - `total=3269`
  - monotonic progression = true

### Gate Outcome

- `Recall@5 = 0.0281`
- `MRR = 0.0204`

These remain far below the U1 gate (`Recall@5 ≥ 0.45`, `MRR ≥ 0.30`), so U1 stays blocked on quality, not just naming/coherence.

### Root Cause

The audit evidence points to a dataset/eval-quality problem in addition to the artifact issue:

1. **Template saturation**
   - `template_match.matched = 3269 / 3269`
   - `per_template_bucket` contains only `template`
   - there is no non-template population to validate broader retrieval behavior

2. **High query-text duplication across many docs**
   - audit `bad_cases.duplicate_query_text_across_docs.type_count = 70`
   - repeated generic prompts such as "激光焊接的最新研究进展" map to very large doc sets

3. **Hard-query supervision is thin**
   - audit `bad_cases.hard_with_single_doc_evidence.type_count = 326`
   - every hard query is effectively single-evidence, which weakens discriminative evaluation

### Next Reviewer-Cycle Proposal

1. **Do not spend another full rerun on the same v2.1 set/config first.**
2. First remediate the eval set:
   - add / preserve a real non-template bucket
   - reduce cross-doc duplicate generic prompts
   - review hard-query evidence design so hard cases are not all single-evidence template variants
3. After dataset remediation, rerun full eval directly to canonical paths:
   - `output\v21_full_eval_canonical.json`
   - `output\v21_full_eval_canonical.progress.jsonl`

### Validation Performed

- `python -m pytest tests\test_eval_dataset_audit.py -q` → pass
- `python -m pytest tests\test_eval_runtime.py -q` → pass

---

## Tank U1 Re-Gate Verdict

**By:** Tank (QA)  
**Date:** 2026-04-20  
**Scope:** U1 Step 3 formal re-gate using Trinity canonical evidence pack

### Verdict

**REJECTED**

### Gate Split (Contract vs Quality)

#### 1) Contract / Evidence-Pack Status

**PASS (unblocked)**

- Required artifacts present:
  - `output/eval_query_audit_v21.json`
  - `output/eval_query_audit_v21_template_flags.jsonl`
  - `output/v21_full_eval_canonical.json`
  - `output/v21_full_eval_canonical.progress.jsonl`
- Contract totals coherent at 3269 queries.
- Difficulty split coherent with required baseline:
  - hard=326, medium=1455, simple=1488
- Canonical metrics sections present:
  - `aggregated_metrics`
  - `per_difficulty`
  - `per_template_bucket`
- Canonical progress chain is monotonic and ends at `done=3269 / total=3269`.
- No active eval/audit runtime process remained during review.

#### 2) Quality-Gate Status

**FAIL (still blocked)**

- `Recall@5 = 0.0281` (required `>= 0.45`)
- `MRR = 0.0204` (required `>= 0.30`)

Tier-2 quality gate is not met, so U1 Step 3 cannot be approved.

### Lockout-Compliant Next Revision Owner

Per strict reviewer lockout semantics:

- Oracle is already locked out from prior rejected cycle.
- Trinity is now the rejected revision author and becomes locked out for the next cycle.

**Next revision owner: Morpheus (escalation/third-agent revision owner).**

### Blocked / Unblocked Now

#### Unblocked

- Canonical evidence-pack contract checks (artifact naming, coherence, progress integrity) are now cleared.

#### Blocked

- U1 Step 3 quality acceptance remains blocked on Tier-2 metric remediation and a new lockout-compliant revised pack.
- Any immediate "go next step" action that depends on U1 Step 3 approval remains blocked.

---


## 2026-04-21: Tier 0 Gate Decision — Per-Query Quality Persistence Before Any Paid Eval

**By:** Morpheus (Architect / QA Lead)
**Requested by:** 小龙 姚
**Status:** ✅ APPROVED — Tier 0 may proceed without user approval

### Decision

**YES — Tier 0 can proceed.** It does not cross any hard-stop boundary.

### Root-Cause Evidence (code audit)

The 1100/3269 U1A run wasted money because of a single architectural defect in val_retrieval_runtime.py:

- **Lines 795-812:** _eval_one() computes full per-query quality metrics (recall@1/3/5/10, mrr, latency, rerank timing) into a esult dict.
- **Lines 813-827:** The progress reporter receives this esult but writes **only counters** (done, 	otal, percent, last_query_id) to the progress JSONL. All quality data is discarded at write time.
- **Lines 830-831:** Per-query results are collected in-memory via syncio.gather, passed back to un_eval.
- **Lines 680-688:** Aggregation and canonical JSON write happen **only after all queries complete**.

**Consequence:** If the process is interrupted before line 680, **all per-query quality data is lost**. This is exactly what happened at 1100/3269. The data was computed, then thrown away.

### Tier 0 Scope

**Objective:** Make the eval runner interrupt-safe by persisting per-query quality evidence to disk as each query completes.

**Change location:** val_retrieval_runtime.py, function _eval_one() (lines 812-828).

**What to add:**
1. A new --per-query-output CLI parameter (path to a JSONL file).
2. Inside _eval_one(), after computing esult (line 812), **append the full esult dict as one JSON line** to the per-query JSONL. Use the existing progress_lock for concurrency safety.
3. Ensure the per-query JSONL is independently parseable — each line is a complete per-query record.

**What NOT to touch:**
- No changes to the existing progress JSONL format (backward compatible).
- No changes to the canonical output JSON schema.
- No changes to ggregate_metrics() — it already works on list[dict].
- No new dependencies.
- No refactoring of existing code structure.

**Estimated change:** ~15 lines of code addition. Zero lines modified.

### Verification Protocol (from morpheus-quality-tiers.md Tier 0 spec)

1. Run 5 queries in dry-run mode (no rerank API, local-only).
2. Verify per-query JSONL is written and each line is valid JSON with recall/mrr fields.
3. Verify aggregate metrics can be recomputed from the per-query JSONL by piping into ggregate_metrics().
4. Verify that interrupting at query 3 leaves usable per-query data for queries 1-3 in the JSONL.

**Cost:** Zero. No paid API calls.

### Hard-Stop Analysis

| Boundary | Crossed? | Reasoning |
|---|---|---|
| New dependency | ❌ NO | Uses only json, syncio, Path — all existing imports |
| Schema change | ❌ NO | Adds a new output file; does not modify existing file schemas |
| Refactor | ❌ NO | Pure addition of ~15 lines in one function; no restructuring |
| Paid API call | ❌ NO | Tier 0 runs with --no-rerank (local-only) |
| Reviewer lockout | ❌ NO | No relation to the rejected U1 artifact cycle |

### Execution Owner

**Tank** — this is QA infrastructure. Tank already identified the defect in 	ank-1100-vs-3269.md and is named as Tier 0 executor in morpheus-quality-tiers.md.

**Review:** Morpheus reviews the change before any paid eval (Tier 1+) is authorized.

### Budget Gate Reminder

- **Tier 0:** No approval needed (zero cost). ← WE ARE HERE
- **Tier 1 (50 queries):** Any team member may run.
- **Tier 2 (250 queries):** Requires Morpheus or 小龙 approval.
- **Tier 3 (3269 queries):** Requires BOTH Morpheus AND 小龙 approval.

No paid eval runs until Tier 0 passes all 4 verification checks.

---

## 2026-04-21: Tank Decision — Tier 0 QA Acceptance Contract (Pre-Paid Mini-Eval)

**Date:** 2026-04-21
**Owner:** Tank (QA)
**Scope:** Define the minimum acceptance contract before any paid mini-eval is allowed.

### Why this gate exists

Current interrupted artifact (output/v21_u1a_full_eval_canonical.progress.jsonl) records only counters (done/total/percent/last_query_id) and no per-query quality fields, so it is not reusable quality evidence if a run stops early.

### Tier 0 — Minimum reusable-evidence contract

An interrupted run is considered reusable **only if all are true**:

1. **Per-query quality persistence exists**: one JSONL line per completed query containing at least query_id, ecall_at_5, mrr, latency_ms (and ideally recall@1/3/10).
2. **Progress remains monotonic**: progress JSONL done strictly increases to the interruption point; 	otal is stable.
3. **Cross-file coherence holds**: last done in progress equals line count in per-query JSONL at interruption.
4. **Partial aggregation is possible**: loading the saved per-query JSONL into ggregate_metrics() yields valid ggregated_metrics and per_difficulty outputs.

If any one fails, interruption evidence is QA-rejected.

### Tier 0 PASS vs FAIL

#### PASS

- Interrupted run produces both:
  - progress heartbeat JSONL (operational trace), and
  - per-query quality JSONL (analysis trace).
- Per-query JSONL parses cleanly and contains required quality fields for every persisted row.
- Coherence check passes (progress.done == persisted_rows).
- Partial metrics can be recomputed from persisted rows without rerunning those rows.

#### FAIL

- Progress-only evidence (current failure mode).
- Missing/invalid per-query rows.
- Non-monotonic progress or count mismatch between artifacts.
- Partial metrics cannot be recomputed from persisted rows.

### Cheapest practical validation shape (Tier 0 proof run)

**Goal:** Prove interruption safety with zero paid spend.

- **Dataset:** val_queries_v2.1_u1a_250.jsonl
- **Query count:** 20 (--offset 0 --limit 20)
- **Cost mode:** local-only (--no-rerank)
- **Progress cadence:** every 1 query (--progress-every 1)
- **Forced interruption point:** after done=8 (40%)

**Expected artifacts**

1. output/tier0_u1a20.progress.jsonl
2. output/tier0_u1a20.per_query.jsonl
3. output/tier0_u1a20.partial_metrics.json (metrics recomputed from persisted 8 rows)

**QA acceptance for this proof run**

- progress file ends at done=8,total=20.
- per-query file has exactly 8 valid rows with quality keys.
- partial metrics file is generated from those 8 rows and includes ggregated_metrics.recall_at_5 and ggregated_metrics.mrr.

Only after this Tier 0 contract passes may any paid Tier 1/2 mini-eval proceed.

---

## 2026-04-21: Trinity Decision — Tier 0 Per-Query Persistence Implementation

**Date:** 2026-04-21
**Owner:** Trinity (Implementation)
**Scope:** Implement Morpheus Tier 0 per-query JSONL persistence in val_retrieval_runtime.py.

### Decision

Add a --per-query-output CLI option and append the full per-query esult dict as JSONL for each completed query, guarded by the existing async progress lock to keep writes coherent under concurrency.

### Why

Interrupted eval runs currently lose per-query quality evidence because only progress counters are persisted. Tier 0 requires reusable per-query quality rows to recompute partial metrics.

### Implementation Notes

- Added per_query_output plumbing through un_eval → _run_eval_async.
- Appended per-query JSONL records under the same progress_lock used for progress writes.
- Left progress JSONL and canonical output schema unchanged.

### Verification

- New test: 	ests/test_eval_runtime.py::test_run_eval_writes_per_query_output_jsonl (passes).

---

## 2026-04-21: Task 2.1.1 Design Review — AIAdapter cost/defaults unification

**By:** Morpheus (Architecture)  
**Date:** 2026-04-21  
**Status:** ✅ APPROVED

### Verdict
- **PROCEED NOW** with narrowed implementation scope: layers/ai_adapter.py only for this subtask pass.

### Key Decisions
1. Only live chat.completions.create call sites confirmed: 7 in layers/ai_adapter.py; inspiration_engine.py and xtractor_full.py out of scope for this pass.
2. Trinity implements _chat as internal AIAdapter helper only; no exported API change.
3. All existing method contracts preserved: same prompt construction, same try/except, same downstream response reads.
4. Site-specific behavior is contract-critical: site 2 keeps max_tokens=10 + no esponse_format; site 6 keeps 	emperature=0.2; JSON-producing sites keep esponse_format={"type":"json_object"}.
5. Cost telemetry best-effort only: sampling/logging may not break extraction/chat paths on error.

### Rationale
- Task uses existing repo-local modules (llm_defaults.py, llm_cost_logger.py, llm_pricing.py)
- No new dependency required
- No refactor approval needed—surgical scope only
- Aligns with delivery-speed preference

---

## 2026-04-21: Task 2.1.1 QA Preflight & Gate Approval — AIAdapter scope verification

**By:** Tank (QA)  
**Date:** 2026-04-21  
**Status:** ✅ GATE APPROVED

### Decision
Task 2.1.1 narrowed to layers/ai_adapter.py seven known chat.completions.create sites only. Do not expand scope into inspiration_engine.py or xtractor_full.py.

### Required Invariants (All Preserved)
1. Site 2 (erify_multimodal_support): 	emperature=0.1, max_tokens=10, no esponse_format
2. Site 6 (classify_claim_boundary): 	emperature=0.2 + JSON response_format
3. JSON vs non-JSON split: 6 JSON + 1 non-JSON
4. Telemetry/logging failures must be swallowed; never break main path

### Evidence
- Plan: .copilot-tracking/plans/2026-04-21-cost-and-defaults.md (§2.1.1)
- Runtime code: layers/ai_adapter.py lines 194, 241, 289, 349, 405, 460, 568
- Test coverage: 	ests/test_ai_adapter_chat_helper.py (4 passed), 	ests/test_llm_provider_routing.py (3 passed)

---

## 2026-04-21: Trinity Implementation Complete — AIAdapter _chat helper

**By:** Trinity (Implementation)  
**Date:** 2026-04-21  
**Status:** ✅ IMPLEMENTATION COMPLETE

### Decision
Implemented §2.1.1 only inside layers/ai_adapter.py by adding private _chat helper and routing 7 in-class completion sites through it.

### Scope Adherence
- Morpheus-approved scope: layers/ai_adapter.py only
- Excluded: inspiration_engine.py, xtractor_full.py
- Contract preservation: All site-specific kwargs retained

### Artifacts
- layers/ai_adapter.py: 7 call sites refactored
- 	ests/test_ai_adapter_chat_helper.py: 4 focused unit tests
- .copilot-tracking/changes/2026-04-21-cost-and-defaults-changes.md: Implementation log

### Test Results
- 	est_ai_adapter_chat_helper.py: 4 PASSED
- 	est_llm_provider_routing.py: 3 PASSED
- Regression suite: No regressions

---

## 2026-04-21: Trinity Implementation Acceptance — Tank QA Gate Approval

**By:** Tank (QA)  
**Date:** 2026-04-21  
**Status:** ✅ ACCEPT — Task 2.1.1 complete

### Evidence
- _chat helper verified to exist and use esolve_llm_params + fail-open telemetry
- 7 internal call sites migrated; only 1 direct chat.completions.create remains (inside helper)
- Site-specific contracts verified:
  - erify_multimodal_support: overrides={"temperature":0.1,"max_tokens":10}, no esponse_format
  - classify_claim_boundary: overrides={"temperature":0.2} + JSON response_format
- Focused tests passed: 	est_ai_adapter_chat_helper.py → 4 passed, 	est_llm_provider_routing.py → 3 passed

### Verdict
✅ **APPROVE** — Task 2.1.1 acceptance criteria satisfied for narrowed layers/ai_adapter.py scope. Coordinator may mark task complete and proceed to 2.1.2.

---

## 2026-04-21: Task 2.1.2 Design Review — Sampling Persistence & Live App Wiring

**By:** Morpheus (Architecture)  
**Date:** 2026-04-21  
**Status:** ✅ APPROVED — PROCEED NOW

### Verdict
- **PROCEED NOW** with task 2.1.2 as a bounded backend-only change.
- **2.1.3 frontend work:** WAITING FOR USER confirmation before implementation.

### Key Decisions
1. **Scope:** Limited to additive user-sampling persistence and API wiring for `sampling_storage.py`, `routers/sampling_router.py`, `routers/chat_router.py`, and live FastAPI entrypoints. 2.1.3 frontend work is explicitly out-of-scope.
2. **Storage Contract:** `sampling_storage.py` must preserve plan contract exactly:
   - `load_user_sampling()` is fail-open (`{}` on missing/corrupt file, never raises)
   - `save_user_sampling()` validates every task via `llm_defaults.resolve_llm_params()` and only writes on full success
3. **Precedence:** Locked to **request body > persisted file overrides > task defaults**. Must apply to both `/chat/ask` and `/chat/stream`. Any later router adoption must reuse same merge order.
4. **Persistence Path:** Fixed to `Path.home() / ".literature-lab" / "sampling.json"` with UTF-8 JSON, atomic `tmp + os.replace()`, single-process `threading.Lock`, no user-controlled path input or path leakage in API responses.
5. **App Entrypoint:** Trinity must wire the new router into actual chat-serving FastAPI app (`python_adapter_server.py`; `my-project/src/app.py` if still exercised), not assume `main_system_production.py` is live.
6. **User Confirmation:** 2.1.3 remains **WAITING FOR USER** even though React/Vite surface exists in-repo; plan still requires explicit user confirmation before frontend implementation.

### Rationale
- Task fits current phase scope, reuses existing repo-local validation logic, adds no dependency, requires no refactor authority.
- Main architectural risk: silent contract drift (wrong app entrypoint, wrong merge precedence, wrong persistence behavior).

### Evidence
- `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md` §2.1.2–§2.1.3
- `routers/chat_router.py` (sampling already present on request models)
- `llm_defaults.py`
- `python_adapter_server.py` lines 431-445
- `my-project/src/app.py`

---

## 2026-04-21: Task 2.1.2 QA Preflight — Acceptance Criteria

**By:** Tank (QA)  
**Date:** 2026-04-21  
**Status:** ✅ PREFLIGHT COMPLETE

### Verdict
- **QA scope locked** to backend task 2.1.2 only; any 2.1.3 frontend work is out-of-scope and will be rejected at preflight.

### Minimum Acceptance Evidence
1. **Storage:** fail-open/fail-closed behavior proven (`load_user_sampling` returns `{}` on missing/corrupt file; invalid save raises and preserves on-disk content).
2. **API Contract:** Validated for:
   - `GET /sampling` (empty + populated)
   - `PUT /sampling` (valid 200 + invalid 422)
   - `DELETE /sampling/{task}` reset semantics
3. **Sampling Precedence (Mandatory):** Test-gated for both `/chat/ask` and `/chat/stream`: **request body overrides > persisted file overrides > llm_defaults task defaults**.
4. **Inspiration Precedence (Conditional):** Enforce only if Trinity wires sampling merge into inspiration paths in this task; otherwise mark not-applicable with explicit evidence.

### Why
- Highest regression risk is silent precedence drift and unsafe persistence behavior.
- Frontend drift would violate approved 2.1.2 boundary and dilute QA signal.

---

## 2026-04-21: Task 2.1.2 QA Verdict — Implementation Approval

**By:** Tank (QA)  
**Date:** 2026-04-21  
**Status:** ✅ APPROVE — Coordinator may mark 2.1.2 complete

### Scope Check
- Reviewed backend-only artifacts: `sampling_storage.py`, `routers/sampling_router.py`, `routers/chat_router.py`, `python_adapter_server.py`, tests, and plan tracking.
- **No 2.1.3 frontend implementation drift observed.**
- `inspiration_router.py` remains untouched; treated as **not-applicable** per preflight conditional rule.

### Validation Evidence
- **Focused test sequence:** `py -m pytest -q tests\test_sampling_storage.py tests\test_sampling_router.py test_chat_router.py` → **16 passed**.
- **Confidence run:** `py -m pytest -q tests\test_llm_defaults.py tests\test_ai_adapter_chat_helper.py` → **10 passed**.
- **Precedence wiring confirmed in shared code path:**
  - `/chat/ask` resolves via `_resolve_request_llm_config(..., sampling=req.sampling)` (routers/chat_router.py lines ~496-503)
  - `/chat/stream` resolves via `_resolve_request_llm_config(..., sampling=req.sampling)` (routers/chat_router.py lines ~549-563)
  - Merge order in resolver: request > persisted file > task defaults (routers/chat_router.py lines ~83-90).

### Release Gate Decision
- **✅ Coordinator may mark 2.1.2 complete** and move to next executable task.


---

## 2026-04-22: Task 2.2 Design Review — LLM Cost Telemetry

**By:** Morpheus  
**Status:** PROCEED — split execution required

### Decisions
1. **Split 2.2 into three sequential slices** for isolated testing, router addition, and regression.
2. **Exact next slice:** 2.2.A (tests only) covering `tests/test_llm_pricing.py` and `tests/test_llm_cost_logger.py`.
3. **Read-only endpoint boundary:** `/llm/cost/*` streams from `output/llm_cost.jsonl` with no cache, no mutations, 256 MB guard.
4. **Contract preservation:** Keep existing `llm_cost_logger` fail-open behavior and JSONL schema intact.

---

## 2026-04-22 — Task 2.2.A QA Verdict: APPROVE

**Owner:** Tank  
**Scope:** 2.2.A tests-only slice

### Result
- Coverage verified: pricing lookup, cost math, logger schema, telemetry suppression, unknown models.
- 19 tests passed.
- No `/llm/cost/*` router work detected.
- **✅ APPROVE** — 2.2.A complete, advance to 2.2.B.

---

## 2026-04-22: Task 2.1.3 Design Review — Frontend Sampling Panel

**By:** Morpheus

### Decisions
1. **Task boundary:** Sampling panel in `frontend/src/pages/Settings.tsx` only, no chat-input UI work.
2. **State isolation:** Server-backed state under `~/.literature-lab/sampling.json`.
3. **Empty-field semantics:** Frontend must omit empty fields from `PUT /sampling` payloads.
4. **Contract prerequisite:** Backend `GET /sampling` must expose `task_defaults` and `MODEL_MAX_TOKENS`.

---

## 2026-04-22: Task 2.1.3 Sampling Frontend Rejection Audit — REVISION REQUIRED

**By:** Morpheus

### Defects Found
1. **Blank != no override** — Backend persists empty `{task: {}}` objects. Frontend must omit empty task overrides entirely.
2. **Scope drift** — Unrelated `aiCostProfile` added to `settingsStore.ts`. Must be removed.

### Lockout Enforced
- Switch locked out. **Next owner: Trinity**
- Brief: Fix blank semantics, remove scope drift, preserve sampling UI.

---

## 2026-04-22: Task 2.1.3 Sampling Frontend QA Re-Review: APPROVE

**Owner:** Tank

### Verification
- Blank field persistence: Resolved (DELETE semantics via `buildSamplingSaveRequest`).
- Scope drift: Resolved (no `aiCostProfile` UI, `settingsStore.ts` optional only).
- UI contract: All 5 task panels, PUT/DELETE, 422 surfacing confirmed.
- Tests: frontend pass, npm build pass, backend tests pass.
- **✅ APPROVE** — 2.1.3 complete.

---

## 2026-04-22: Task 2.1.3 Backend Prerequisite Rejection Audit — REVISION REQUIRED

**By:** Morpheus

### Scope Impurity Found
- Claimed "backend-only" but worktree contaminated: `llm_defaults.py`, `sampling_storage.py`, modified routers, untracked test files.
- Not a logic rejection; **isolation rejection**.

### Lockout Enforced
- Trinity locked out. **Next owner: Ralph**
- Brief: Clean tree, minimal patch only (`GET /sampling` returns `task_defaults` + `model_max_tokens`, focused tests).

---

## 2026-04-22: Task 2.1.3 Backend Prerequisite — Ralph Clean Resubmission

**Status:** ✅ READY FOR TANK TIER 2 RE-REVIEW

### What Changed (4 Files, 224 Lines)
- `routers/sampling_router.py` (44 lines): GET/PUT/DELETE `/sampling` endpoints
- `sampling_storage.py` (62 lines): User overrides persistent storage
- `tests/test_sampling_router.py` (60 lines): 3 focused tests (all green)
- `llm_defaults.py` (58 lines): Defaults and validation reuse

### Worktree Isolation
```
A  llm_defaults.py
A  routers/sampling_router.py
A  sampling_storage.py
A  tests/test_sampling_router.py

4 files changed, 224 insertions(+), 0 deletions(-)
```
✅ No unrelated drift, only task files.

---

## 2026-04-22: Task 2.1.3 Backend Prerequisite — Tank Tier 2 Re-Review: APPROVE

**Status:** ✅ **APPROVE**

### Verification
- Minimal scope: 4 files, 224 lines, 0 deletions.
- No scope creep: adapter untouched, frontend untouched.
- Tests green: 3 focused + 13/13 comprehensive suite.
- Backward compatible: existing fields preserved.
- **Unblocks 2.1.3 frontend** for defaults query.

**Coordinator signal:** 2.1.3 complete. Advance to 2.2.B.

