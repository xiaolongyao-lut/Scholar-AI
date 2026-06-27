# Scholar AI Reference-Derived Code Plan

Date: 2026-06-19

Rollback checkpoint:

- `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260619-212929-reference-to-code-plan`
- Optimization checkpoint:
  `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260619-220807-reference-plan-records-optimization`

## Current Objective

Use the completed local reference-learning records to compare the learned ideas
and technology stacks against all Scholar AI / 文献助手 function areas, then
produce a code plan that can guide optimization and refactoring.

This document is a planning artifact. It is not a product-code implementation
claim.

## Current Identity

- Current product name: `Scholar AI`.
- Chinese desktop/window name: `文献助手`.
- Internal package path: `literature_assistant/`.
- Historical names appear in older plans and package paths; they are not the
  current product name.

## Source Records Used

Primary local learning records:

- `docs/plans/supplemental-reference-learning-index-2026-06-19.md`
- `docs/plans/supplemental-reference-learning-notes-2026-06-19.md`
- `docs/plans/github-reference-learning-index-2026-06-19.md`
- `docs/plans/github-reference-learning-notes-2026-06-19.md`

Current product records and code evidence:

- `README.md`
- `AI_WORKSPACE_GUIDE.md`
- `docs/plans/autonomous-execution-framework.md`
- `docs/plans/autonomous-execution-planning-playbook.md`
- `docs/plans/literature-assistant-product-architecture-brief-2026-06-03.md`
- `docs/plans/mcp-task-control-layer.md`
- `docs/plans/mcp-task-control-layer-api-chat-tool-loop-validation-audit-2026-06-19.md`
- Router inventory from `literature_assistant/core/python_adapter_server.py`.
- Frontend surface inventory from `frontend/src/pages`, `frontend/src/components`,
  `frontend/src/services`, and `frontend/src/types`.

Reference-learning closure:

- `C:\Users\xiao\Downloads\第一次补充参考`: local inventory recorded as complete
  for 12 unique downloaded projects.
- `workspace_references/github_mcp_agent_research_20260619/repos`,
  `C:\Users\xiao\Downloads\文章写作过程`, and
  `C:\Users\xiao\Downloads\文献检索`: local inventory recorded as complete
  enough for planning across 16 unique project identities plus duplicates.
- This closure supersedes the older `Recommended next downloads` tail in
  `github-reference-learning-notes-2026-06-19.md` for Vercel AI SDK, LiteLLM,
  LangGraph, Cline, Goose, OpenHands, ToolHive, Docker MCP Gateway, MCP
  Inspector, official MCP servers, mcp-proxy, and MCP Filesystem Server.

Coverage boundary:

- The records are targeted engineering learning, not literal whole-repository
  line-by-line audit. They record project identity, stack, important entrypoints,
  files/modules actually read, transferable patterns, product application, and
  limits.
- Vendor/generated/static assets, broad UI examples, deployment examples, and
  provider-specific adapters are excluded unless a project note names them.
- The records are design evidence, not proof that Scholar AI already implements
  the target behavior.
- Current dirty product code may contain partial implementations of formatter
  payload separation, provider probing, runtime attach, source guards, writing
  lint/export, and Agent Workspace features. Those are not accepted by this
  plan until Phase 0 audits ownership and focused tests pass.

## Optimization Audit, 2026-06-19

This plan was optimized after a follow-up audit. The audit tightened four
records:

- Product identity: new conclusions use `Scholar AI` / `文献助手`; historical
  `Literature Assistant` wording may remain only in old paths or quoted records.
- Learning status: `Read` means targeted engineering learning with recorded
  coverage and limits, not a literal guarantee that every line in every
  reference checkout was read.
- Download status: the earlier GitHub notes' recommended-download tail is
  superseded by the later `第一次补充参考` pass for most listed projects.
- Implementation boundary: this plan is a queue and acceptance contract for
  future product-code slices. It is not evidence that dirty working-tree code is
  complete, tested, staged, or safe to continue without Phase 0.

## Design Thesis

The references converge on a single durable direction:

Scholar AI should own typed local state below provider adapters and above UI,
audit, and export renderers. Provider messages, chat text, and audit previews
are lossy projections, not the source of truth.

The main internal contracts should therefore become:

- Tool result envelope: raw content blocks, structured content, tool-level
  error status, metadata, audit preview, and provider-facing payload.
- Provider capability record: model/provider endpoint support, native tool
  calling, forced tool choice, streaming, context limits, media support, and
  fallback status.
- Run state machine: phase, stop reason, terminal state, per-tool call ids,
  progress, context/cost usage, and artifacts.
- Evidence object model: low-token refs first, bounded full-content reads second,
  and claim/citation/export artifacts third.
- Source authority: project-scoped roots, realpath containment, sensitive-path
  denial, and unified ingest/source-tool/archive safety.
- Workflow state: writing, retrieval, export, wiki, graph, and longrun actions
  should be recoverable from explicit state records, not only chat history.

## Full Function Comparison

| Scholar AI area | Current evidence | Reference lesson | Code-plan direction |
|---|---|---|---|
| Product identity and longrun execution | Current README and workspace guide define Scholar AI / 文献助手; longrun playbook now requires goal-state records. | LangGraph threads/runs, Cline explicit completion, OpenHands event catalog. | Keep current identity in all new docs; add schema validation for generic longrun goal-state records later. |
| MCP toolbox and external-agent bridge | `agent_mcp_server/`, local tool bridge, runtime attach, Agent Workspace, `agent_bridge_router.py`, and `mcp_runtime/*` exist; A1 formatter correction is recorded. | MCP SDK/FastMCP/LangChain adapters preserve envelopes; Vercel AI SDK and LiteLLM split raw result, model output, and UI event. | Make `ToolResultRecord` the stable internal envelope and add typed tool-loop states/stop reasons through `/api/chat`, MCP stdio, runtime artifacts, and Agent Workspace. |
| Provider probing and routing | `provider_probe.py` has reachability and tool-call capability probe code; current records warn that fake/free proxies can chat while swallowing tools. | LiteLLM and Goose use provider/model capability metadata rather than one `works` flag. | Persist provider capability records and make chat/tool-loop dispatch fail closed or degrade explicitly when tool calling is not proven. |
| SmartRead and `/api/chat` | `/api/chat` and `/chat/ask` have deterministic local literature tool-use tests; `context_chunks_used` can be misleading for tool-first paths. | OpenAI Agents, FastMCP, and Pydantic AI expose bounded loops and failure states. | Add `tool_payloads_used`, `tool_payload_chars`, `context_budget_used`, `stop_reason`, and `terminal_state` diagnostics. |
| Materials, source folders, scan, chunks | `resources_router` provides project/source/material/chunk/search; `path_guard.py` and scan/search contracts exist in the dirty worktree. | MCP filesystem, Docker Gateway, Cline ignore/env guards, gpt_academic archive handling. | Extend one shared source policy across picker binding, scan, upload extraction, MCP `source.*`, resource reads, and export/write paths. |
| Retrieval and evidence packs | `search_refs` is low-token and ref-first; evidence pack exists but retrieval quality and qrels remain guarded. | paperscraper normalized JSONL refs, ChatPaper/gpt_academic staged search plans, LangGraph conformance style. | Build a source-specific query planner, keep refs/content split, and add qrels/promotion workflow before semantic quality claims. |
| PDF reader and parsing | Direct PDF reading remains product core; PyMuPDF and optional marker/PDF backend paths exist. | gpt_academic PDF splitting, paper-writing workflow evidence layers, Hugo page bundles. | Keep visible PDF as source of truth; add explicit parse-budget/truncation diagnostics and page-bundle export metadata. |
| Writing, citation, export | `writing_router.py`, `writing_runtime.py`, `evidence_router.py`, `export_router.py`, `academic_writing_linter.py`, and frontend writing pages exist; current records say writing quality evidence is still limited. | scipilot, PaperSpine, chinese-thesis-workbench, ChineseResearchLaTeX stage intake, citation banks, deterministic gates, DOCX guards, and artifact manifests. | Introduce durable `writing_workflow_state`, citation support bank, evidence/claim register, lint report, change log, export manifest, and medium-specific validators. |
| Wiki, graph, knowledge workbench | `wiki_router.py`, `knowledge_router.py`, graph components, source vault, evolution capture, and wiki review/doctor surfaces exist. | Hugo page bundles, LangGraph projections, OpenHands typed event/reducer patterns. | Treat wiki/export objects as page bundles with front matter, evidence refs, artifacts, and search metadata; route agent results into wiki/graph/evolution consumers explicitly. |
| Runtime jobs and Agent Workspace | `runtime_router.py` exposes sessions/jobs/events/artifacts/checkpoints; `AgentWorkspace.tsx` and bridge APIs exist in the dirty worktree. | AgentControlPlane Task/ToolCall phases, Goose event replay, LangGraph stream projections, OpenHands dedupe reducers. | Normalize all long operations as `session/thread + run/job + typed events + artifacts`; frontends should render projections, not parse log text. |
| Skills and MCP installation | Skill import, approvals, runtime actions, MCP installer, scan, preview, install, pending calls, and security policy exist. | ToolHive/Docker Gateway registry/profile/policy, Pydantic AI toolsets, mcp-use client/session split. | Add tool annotations and capability/profile records: read-only, destructive, idempotent, network/open-world, project-scoped, source-read, export-write, experimental. |
| Settings, credentials, costs | Credentials, settings, model config, rerank config, cost router, and dynamic API config exist. | Goose model catalog, LiteLLM endpoint capability matrix, OpenHands immutable secrets. | Store immutable per-request credential/provider snapshots; expose provider capability and auth status without leaking secrets. |
| Evaluation and quality gates | Chunk package quality and qrels promotion tools exist; tests guard candidate vs canonical qrels. | paperscraper mocked external retrieval tests, PaperSpine guard scripts, scipilot lint exit codes. | Expand acceptance around natural prompts, content backflow, qrels status, export validators, and state-machine stop reasons. |
| Frontend data layer and UI | Generated OpenAPI, service modules, pages, contexts, Agent Workspace, writing, wiki, knowledge, settings, PDF viewer exist. | Vercel UI message parts, OpenHands event stores, Goose status notifications. | Prefer typed event reducers and generated API types; render lifecycle states with stable ids and in-place updates. |
| Local analytics and audit | MCP audit JSONL, runtime events, evolution capture, diagnostics, logs, and linter reports exist. | OpenHands event catalog and analytics isolation, Goose custom notifications. | Add a local-only event catalog for run/tool/provider/retrieval/writing/export terminal states; never let audit failure break the product path. |

## Priority Order

### High ROI And Already Needed

1. Typed tool-loop state and stop reasons.
   - Why: fixes overclaiming, makes test failures actionable, and improves Agent
     Workspace immediately.
   - Reference evidence: Vercel stop conditions, OpenAI Agents max-turn errors,
     FastMCP sampling loop, AgentControlPlane Task/ToolCall phases, mcp-use max
     step handling.
   - First code slice: add backend enums/models and API diagnostics without
     changing provider behavior.

2. Provider capability registry drives tool dispatch.
   - Why: prevents fake provider success and stops native MCP claims when tools
     are swallowed.
   - Reference evidence: LiteLLM endpoint capability matrix, Goose canonical
     model metadata, FastMCP client capability checks.
   - First code slice: persist probe result and make local literature tool use
     require `tool_call_ok`, with a clear `provider_tool_probe_failed` state.

3. Total provider-bound context budget for tool results.
   - Why: A1 restored content backflow, but unbounded accumulated payloads can
     overflow context and hide the real failure.
   - Reference evidence: Cline compaction pipeline, gpt_academic PDF splitting,
     FastMCP response limiting.
   - First code slice: enforce per-run budget across tool payloads and report
     truncation/redaction/unsupported blocks.

4. Unified source and secret-read policy.
   - Why: content backflow makes source-read safety more important than preview
     redaction.
   - Reference evidence: MCP filesystem realpath checks, Docker Gateway local
     catalog containment, Cline env blocker, gpt_academic archive safety.
   - First code slice: connect `path_guard.py` or equivalent shared guard to
     MCP source tools, upload/archive extraction, source-folder scan, and
     resource-read paths.

5. Agent Workspace typed event projection.
   - Why: user and agent need to see whether a run is discovering tools,
     executing, denied, truncated, failed, or completed.
   - Reference evidence: Vercel UI message parts, LangGraph projections, Goose
     event replay, OpenHands dedupe reducer.
   - First code slice: backend event schema plus frontend reducer for tool/run
     lifecycle, keeping existing UI layout.

6. Writing workflow state and citation support bank.
   - Why: writing/export quality cannot be proven by tool count.
   - Reference evidence: scipilot staged lint, PaperSpine citation bank and
     rationale matrix, chinese-thesis verified facts layers, ChineseResearchLaTeX
     DOCX quality reports.
   - First code slice: add a `writing_workflow_state` record and deterministic
     lint/change-log/export-manifest artifacts around existing writing APIs.

7. Retrieval qrels and evidence-quality workflow.
   - Why: semantic retrieval claims remain noncanonical until human labels exist.
   - Reference evidence: chunk promotion validator, paperscraper normalized
     refs, LangGraph conformance testing pattern.
   - First code slice: surface qrels state in UI/API and prevent semantic
     quality badges while qrels are candidate-only.

8. Page-bundle export artifacts.
   - Why: writing/wiki/export outputs need portable, inspectable folders instead
     of isolated blobs.
   - Reference evidence: Hugo academic page bundles, ChatPaper auto-survey run
     directories, PaperSpine artifact manifests.
   - First code slice: export `index.md`, metadata JSON, citations, evidence
     refs, generated files, and verification reports under a controlled artifact
     directory.

### Missing But Needed

1. Natural-prompt real-provider acceptance harness.
   - Explicit tool-sequence smoke is useful as control, not autonomy evidence.
   - Need a harness where natural user intent causes provider-selected tool
     calls and final answer uses bounded tool content.

2. Provider/model inventory object.
   - Need model id, provider, base URL host, auth status, tool-call support,
     forced-tool support, context limit, media support, reasoning support,
     streaming support, and last probe result.

3. Source-specific retrieval planner.
   - Need natural query -> arXiv/Semantic Scholar/PubMed/Crossref/local project
     search plans where available, with per-source capability and fallback
     reasons.

4. Writing intake and motivation confirmation.
   - Need task type, target venue, output medium, language direction, discipline,
     conservatism, material scope, citation policy, and user-confirmed writing
     motivation before major draft generation.

5. Local event catalog.
   - Need stable event names for conversation/run/tool/retrieval/writing/export
     created, started, hidden, denied, truncated, failed, succeeded, cancelled,
     and completed.

6. Artifact manifest contract.
   - Need one manifest shape for run artifacts, writing exports, evidence packs,
     wiki pages, DOCX/PDF outputs, and verification reports.

### Can Optimize Later

1. Generic MCP proxy/gateway.
   - Useful for diagnostics, but increases local attack surface. Keep current
     source-checkout MCP server unless a specific workflow requires a proxy.

2. Multi-agent teams and delegated subagents.
   - References show value, but Scholar AI's core is evidence, retrieval,
     reading, writing, and export. Add only after typed run state is solid.

3. Hosted/cloud control plane.
   - Outside current local MCP-first direction.

4. Broad UI redesign.
   - Current need is typed state visibility and event rendering, not a new visual
     architecture.

5. Full provider-adapter rewrite.
   - Use branch-by-abstraction: capability records and stop states first,
     provider-specific adapters later.

## Code Plan

### Phase 0: Preflight And Ownership Audit

Goal:

- Create a safe implementation boundary before touching product code.
- Convert the broad dirty worktree from "many plausible partial slices" into an
  explicit ownership map before adding new behavior.

Actions:

- Run `git status --short --branch`.
- Create a rollback checkpoint for the next product-code slice.
- Inspect current dirty diffs for files touched by prior slices:
  `mcp_runtime/*`, `provider_probe.py`, `chat_mcp_integration.py`,
  `intelligent_chat_router.py`, `runtime_router.py`, `agent_bridge_router.py`,
  `path_guard.py`, frontend Agent Workspace, writing/export/linter files.
- Record which dirty files are in-scope and which are unrelated.
- Classify every dirty path touched by the next slice as one of:
  - already verified and in-scope
  - in-scope but unverified
  - unrelated user/agent work
  - generated/runtime output
  - unknown ownership, stop before editing
- Run focused baseline compile/collect-only if the worktree is not obviously
  broken.

Verification:

- `git diff --check` on in-scope files.
- `python -m compileall` for touched backend modules before code edits when
  feasible.
- Targeted `rg` checks proving actual call sites match the plan's file anchors.

Stop:

- Stop if the dirty worktree makes ownership impossible to separate.
- Stop if the next slice would overwrite unrelated user/agent changes.

### Phase 1: Typed Tool Loop State And Stop Reasons

Goal:

- Make every tool-loop exit machine-readable and testable.
- Make existing partial implementations falsifiable before extending them.

Likely backend files:

- `literature_assistant/core/mcp_runtime/tool_use_runner.py`
- `literature_assistant/core/mcp_runtime/tool_dispatcher.py`
- `literature_assistant/core/mcp_runtime/tool_result_formatter.py`
- `literature_assistant/core/mcp_runtime/audit.py`
- `literature_assistant/core/routers/chat_mcp_integration.py`
- `literature_assistant/core/routers/intelligent_chat_router.py`
- `literature_assistant/core/routers/chat_router.py`
- `literature_assistant/core/models/runtime.py`
- `literature_assistant/core/harness_protocols.py`

Likely frontend files:

- `frontend/src/services/chatApi.ts`
- `frontend/src/services/intelligentChatApi.ts`
- `frontend/src/services/agentWorkspaceApi.ts`
- `frontend/src/types/runtime.ts`
- `frontend/src/pages/AgentWorkspace.tsx`
- `frontend/src/components/chat/MessageRenderer.tsx`

Implementation direction:

- First add characterization tests for current runner behavior. These tests must
  distinguish at least `natural`, `no_tools`, max-round/timeout-like exits, tool
  execution error returned to the model, and provider call failure.
- Add enums or literal types for:
  - `tool_loop_not_started`
  - `mcp_disabled_by_policy`
  - `provider_tool_probe_failed`
  - `tool_loop_started`
  - `tool_discovery_failed`
  - `tools_hidden_by_policy`
  - `provider_no_tool_calls`
  - `tool_call_received`
  - `tool_call_denied`
  - `tool_execution_error_returned`
  - `tool_call_failed_no_model_payload`
  - `tool_result_rendered`
  - `follow_up_sent`
  - `tool_loop_completed`
  - `tool_loop_max_rounds`
  - `tool_loop_timeout`
  - `tool_loop_cancelled`
  - `adapter_conversion_error`
  - `context_budget_exceeded`
- Add a run-level `terminal_state` separate from natural-language answer text.
- Keep current response fields for compatibility; add new diagnostics in a
  nested object.
- Update tests so `partial_tool_chain` is not a success unless explicitly
  configured for exploratory smoke.
- Do not rename or remove existing public response fields in this phase.

Verification:

- Existing tool-loop tests plus new cases for each major stop reason.
- API test proving `/api/chat` returns distinct stop diagnostics.
- Frontend typecheck/build after generated/openapi changes if public schemas
  change.
- Negative smoke: fake provider returns normal text while tools were offered;
  diagnostics must report `provider_no_tool_calls` or equivalent, not success by
  tool-count expectation.

### Phase 2: Provider Capability Registry

Goal:

- Tool dispatch should be gated by proven provider capability, not by ordinary
  chat success.
- Separate "probe code exists" from "dispatch policy consumes probe result".

Likely backend files:

- `literature_assistant/core/provider_probe.py`
- `literature_assistant/core/model_config_store.py` or current provider settings
  store
- `literature_assistant/core/routers/model_config_router.py`
- `literature_assistant/core/routers/credentials_router.py`
- `literature_assistant/core/routers/chat_mcp_integration.py`
- `literature_assistant/core/mcp_runtime/provider_tool_adapter.py`

Implementation direction:

- Define `ProviderCapabilityRecord` with:
  - provider alias
  - base URL host
  - model
  - ordinary chat status
  - `/v1/models` status when applicable
  - forced tool-choice status
  - tool-result round-trip status when feasible
  - streaming tool-delta status when tested
  - context limit if known
  - last probe timestamp
  - failure class and masked error
- Store capability records in runtime state, not in public source.
- Make local literature tool loop require a successful tool capability record or
  run a bounded probe when the user explicitly requests testing.
- Surface `auth_required`, `not_probed`, `probe_failed`, `tool_call_ok`, and
  `unsupported` distinctly.
- Persist capability records in runtime/local state with timestamp and endpoint
  fingerprint; never infer capability from a successful ordinary chat alone.

Verification:

- Fake provider tests for:
  - chat OK, tools swallowed
  - forced tool rejected
  - model missing
  - 401/403 auth failure
  - tool call OK
- API tests proving tool loop is disabled with
  `provider_tool_probe_failed` rather than silently running a prompt-only path.

### Phase 3: Total Context Budget And Payload Accounting

Goal:

- Ensure MCP/tool content reaches providers within a bounded, auditable budget.

Likely backend files:

- `literature_assistant/core/mcp_runtime/tool_result_formatter.py`
- `literature_assistant/core/mcp_runtime/tool_use_runner.py`
- `literature_assistant/core/routers/local_literature_tool_bridge.py`
- `literature_assistant/core/routers/chat_mcp_integration.py`
- `literature_assistant/core/models/evidence.py`

Implementation direction:

- Keep `search_refs` ref-first and low-token.
- Make `agent_resource_read`, `source.read_file`, and content-bearing tools
  report:
  - payload chars
  - estimated tokens
  - truncated flag
  - redacted flag
  - unsupported block count
  - source provenance
  - budget class
- Add a per-run total budget across all tool payloads.
- When the budget is exceeded, return a model-visible summary plus explicit
  `context_budget_exceeded`, not a silent empty result.
- Avoid exposing stale `structuredContent` after truncation unless it remains
  schema-valid and explicitly marked partial.

Verification:

- Sentinel tests where useful text appears after the old preview limit.
- Tests for total budget exhaustion over multiple tool calls.
- Tests that audit logs do not persist raw `llm_payload`.

## Implementation Record, 2026-06-19 Phase 3a

Scope:

- First total provider-bound context budget slice for MCP/tool results.
- Add per-tool payload accounting, source provenance, and run-level budget
  diagnostics without changing existing preview fields.

Rollback:

- `20260619-233326-phase3-context-budget-preflight`

Mature / official references rechecked:

- OpenAI function calling documentation: tool outputs are structured protocol
  messages and must stay within the model's usable context.
- Vercel AI SDK tool-calling documentation: multi-step tool loops need explicit
  loop control and observable stop conditions.
- MCP schema: tool results are structured content records; provider-facing
  projections should be bounded and auditable rather than treated as the raw
  source of truth.

Changed files:

- `literature_assistant/core/mcp_runtime/tool_result_formatter.py`
  - Adds per-record `llm_payload_chars`, `estimated_tokens`, `redacted`,
    `unsupported_block_count`, `source_provenance`, and `budget_class`.
  - Keeps ref tools compact and body tools provider-visible beyond audit
    preview, while preserving the existing per-record payload cap.
- `literature_assistant/core/mcp_runtime/tool_use_runner.py`
  - Adds `RunCaps.max_tool_payload_chars` with env override
    `MCP_MAX_TOOL_PAYLOAD_CHARS`.
  - Applies a per-run total provider-bound tool payload budget across records.
  - Replaces over-budget tool bodies with a model-visible
    `context_budget_exceeded` summary instead of silently sending an empty
    result.
  - Adds run diagnostics for payload count, payload chars, estimated tokens,
    budget limit, remaining budget, and budget-exceeded state.
- `literature_assistant/core/routers/chat_mcp_integration.py`
  - Projects the new per-tool payload diagnostics into `mcp_run.tool_calls`
    additively while preserving legacy fields.
- Ignored local tests:
  - `tests/test_mcp_phase2_tool_loop.py`
    - Adds a red/green runner test for total payload budget exhaustion across
      multiple tool calls.
  - `tests/test_api_chat_local_literature_tool_use.py`
    - Adds API transcript assertions for budget class, payload chars,
      estimated tokens, and source provenance.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_phase2_tool_loop.py::test_runner_enforces_total_tool_payload_budget_across_records -q`
  failed before implementation because `RunCaps` lacked a run-level payload
  budget, then passed after implementation.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_phase2_tool_loop.py -q`
  passed: 55 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py::test_chat_ask_local_literature_tool_loop_executes_search_refs tests\test_api_chat_local_literature_tool_use.py::test_chat_ask_local_literature_tool_result_returns_body_beyond_preview -q`
  passed: 2 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py tests\test_api_probe_semantics.py tests\test_provider_probe.py tests\test_mcp_phase2_tool_loop.py -q`
  passed: 102 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\mcp_runtime literature_assistant\core\provider_capabilities.py literature_assistant\core\provider_probe.py literature_assistant\core\routers\chat_router.py literature_assistant\core\routers\chat_mcp_integration.py literature_assistant\core\routers\model_config_router.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py tests\test_provider_probe.py tests\test_api_probe_semantics.py`
  passed.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_phase2_tool_loop.py::test_audit_record_does_not_persist_llm_payload tests\test_mcp_phase5_hardening.py::test_audit_append_creates_jsonl -q`
  passed: 2 tests.
- `git diff --check -- literature_assistant\core\mcp_runtime\tool_result_formatter.py literature_assistant\core\mcp_runtime\tool_use_runner.py literature_assistant\core\routers\chat_mcp_integration.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py`
  passed.

Skipped / not claimed:

- No frontend reducer or generated OpenAPI update was done; the API transcript
  change is additive under existing dict-shaped `mcp_run`.
- No real provider smoke was run. This slice proves local budget mechanics and
  API projection with deterministic fake providers.
- No source safety changes were made; Phase 4 remains the next source-policy
  slice.

Residual risk:

- `estimated_tokens` is a deterministic local estimate based on character
  count, not tokenizer-specific accounting.
- The run-level budget is character-based and provider-agnostic. Provider/model
  context-limit-specific budgeting remains a later provider inventory concern.
- If many over-budget records appear, summary payloads themselves still consume
  budget; this is explicit in diagnostics but can be optimized later.

### Phase 3 Stop Audit, 2026-06-19

Active queue:

- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`, Phase 3.

Rollback:

- `20260619-235436-phase3-stop-audit-record`

Done:

- Provider-facing tool content is no longer limited to audit `preview`; content
  tools use bounded `llm_payload` while compact ref tools remain low-token.
- Per-tool payload diagnostics now include payload chars, estimated tokens,
  truncation/redaction flags, unsupported block count, source provenance, and
  budget class.
- The runner enforces a total provider-bound payload budget across records and
  returns model-visible `context_budget_exceeded` summaries when the budget is
  exhausted.
- Persistent MCP audit remains preview-only and does not persist raw content or
  provider-bound `llm_payload`.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_phase2_tool_loop.py::test_runner_enforces_total_tool_payload_budget_across_records tests\test_mcp_phase2_tool_loop.py::test_audit_record_does_not_persist_llm_payload tests\test_api_chat_local_literature_tool_use.py::test_chat_ask_local_literature_tool_result_returns_body_beyond_preview -q`
  passed: 3 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\mcp_runtime literature_assistant\core\provider_capabilities.py literature_assistant\core\provider_probe.py literature_assistant\core\routers\chat_router.py literature_assistant\core\routers\chat_mcp_integration.py literature_assistant\core\routers\model_config_router.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py tests\test_provider_probe.py tests\test_api_probe_semantics.py`
  passed.
- `git diff --check -- literature_assistant\core\mcp_runtime\tool_result_formatter.py literature_assistant\core\mcp_runtime\tool_use_runner.py literature_assistant\core\routers\chat_mcp_integration.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed before this record update.
- `rg -n "llm_payload|raw_content|audit|append" literature_assistant\core\mcp_runtime tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py`
  confirmed audit stripping and local tests cover the preview-only audit
  contract.

Deferred to later authorized slices:

- Frontend reducers/generated API types for these additive transcript fields
  remain part of the later Agent Workspace typed event projection slice.
- Real-provider natural-prompt smoke remains part of the acceptance harness
  slice, after provider capability and safety gates are stable.
- Provider/model-specific tokenizer accounting remains part of the later
  provider inventory object.

Authorized local work remaining:

- Phase 4 unified source safety is now the next central local slice.

Post-current-goal queue note:

- The user added `C:\Users\xiao\Downloads\文献检索\scansci-pdf-master` as a new
  reference project. Do not interrupt the active code-plan objective for it.
  After the current goal is complete, learn that project, record notes, then
  compare its lessons against Scholar AI / 文献助手 literature retrieval and PDF
  functions for optimization.

### Phase 4: Unified Source Safety

Goal:

- One source policy should guard all local file entry points.

Likely backend files:

- `literature_assistant/core/routers/resources_router/path_guard.py`
- `literature_assistant/core/routers/resources_router/endpoints_projects.py`
- `literature_assistant/core/routers/resources_router/endpoints_search_upload.py`
- `literature_assistant/core/routers/local_literature_tool_bridge.py`
- `agent_mcp_server/src/lit_assistant_mcp/tools/source.py` or current source
  tool modules
- Upload/archive extraction helpers if present.

Implementation direction:

- Define one `SourceAccessPolicy` or equivalent wrapper over existing guard:
  - project-scoped source root binding
  - realpath containment
  - Windows reparse point detection
  - sensitive directory/file denylist
  - archive traversal checks
  - output path allowlist for generated artifacts
  - absolute path privacy for external agents
- Use the policy in:
  - source-folder write
  - scan-folder execution
  - MCP `source.*`
  - resource read
  - upload/archive extraction
  - export/write output directories
- Return structured denial records to tools and runtime audit.

Verification:

- Shared allow/deny matrix reused across router and MCP source tests.
- Windows cases: drive root, UNC, AppData, `.codex`, `.env`, symlink,
  junction/reparse, archive traversal, allowed project subpath.

## Implementation Record, 2026-06-19 Phase 4a

Scope:

- First unified source-safety slice for MCP `source.*` directory roots.
- Fix source-tool directory listing/search roots so they cannot escape the repo
  before policy checks or leak denied runtime/artifact directories.

Rollback:

- `20260619-235751-phase4-source-safety-preflight`

Mature / official references rechecked:

- Python `pathlib.Path.resolve()` / `os.path.realpath()` documentation: resolve
  symlink/junction-like indirections before containment decisions.
- OWASP path traversal guidance: canonicalize paths and validate them against
  an allowlist before file access.
- Microsoft reparse-point/junction documentation: Windows links can redirect
  path access and must be handled as real target paths.

Changed files:

- `agent_mcp_server/src/lit_assistant_mcp/tools/source.py`
  - `_resolve_directory_root()` now resolves real paths, requires repo
    containment, rejects denylisted roots, and only accepts roots equal to,
    inside, or containing an allowed source root.
  - Directory traversal now uses a denylist-pruning walker rather than raw
    `rglob("*")`, preventing denied runtime directories from being enumerated
    or returned.
  - `list_tree`, `search`, `inspect_routes`, and reference/import helper
    scans now share the same pruned visible-path traversal.
- `agent_mcp_server/tests/test_source_tools.py`
  - Adds regression tests for `root=".."` escape and for hiding
    `workspace_artifacts` from root tree listings while preserving allowed
    source files.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests\test_source_tools.py::test_list_tree_blocks_parent_directory_root agent_mcp_server\tests\test_source_tools.py::test_list_tree_workspace_root_hides_denied_directories -q`
  failed before implementation with 2 failures, then passed after the fix.
- `.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests\test_source_tools.py -q`
  passed: 11 tests.
- `.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests\test_policy.py -q`
  passed: 7 tests, 1 skipped.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_source_folder_guard_contract.py tests\test_path_guard.py -q`
  passed: 27 tests, 2 skipped.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_resources_chunk_locator.py::test_resolve_material_source_path_rejects_traversal_source_reference tests\test_resources_chunk_locator.py::test_resolve_material_source_path_rejects_absolute_path_outside_allowed_roots tests\test_resources_chunk_locator.py::test_document_file_base64_rejects_source_path_traversal -q`
  passed: 3 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q agent_mcp_server\src\lit_assistant_mcp literature_assistant\core\routers\resources_router\path_guard.py literature_assistant\core\routers\resources_router\endpoints_projects.py literature_assistant\core\routers\resources_router\endpoints_search_upload.py`
  passed.
- `git diff --check -- agent_mcp_server\src\lit_assistant_mcp\tools\source.py agent_mcp_server\tests\test_source_tools.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed before this record update.

Skipped / not claimed:

- This slice does not claim full Phase 4 completion. Upload/archive extraction,
  export/write output paths, and any remaining resource-read paths still need
  a Phase 4 stop audit.
- No frontend work, desktop smoke, or real provider smoke was run.
- No commit/stage/push was performed.

Residual risk:

- `PathPolicy` and `path_guard.py` are still separate implementations. This
  slice makes MCP source directory roots obey the same containment/denylist
  intent but does not yet replace both with one shared backend package.
- The default MCP source allowlist is still repo-source oriented; project
  source-folder reads remain backend-managed through resource APIs.

Authorized local work remaining:

- Continue Phase 4 by auditing upload/archive extraction, export/write output
  directories, delete-material source-file cleanup, and resource-read paths for
  the same canonical containment policy.

## Implementation Record, 2026-06-20 Phase 4b

Scope:

- Material deletion path containment for managed uploaded source files.
- Treat `doc_store[*].source_relative_path` as untrusted durable metadata before
  unlinking files.

Rollback:

- `20260619-235751-phase4-source-safety-preflight`

Changed files:

- `literature_assistant/core/routers/resources_router/endpoints_materials_drafts.py`
  - Adds `_resolve_project_source_file_for_unlink()` to resolve a candidate
    source file and require it to be inside the project's managed
    `source_files` directory before deletion.
  - `delete_material()` now skips unsafe or missing paths while preserving the
    best-effort deletion contract for valid uploaded originals.
- Ignored local tests:
  - `tests/test_resources_chunk_locator.py`
    - Adds a red/green regression proving `source_relative_path="../secret.pdf"`
      does not unlink a file outside `source_files`.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_resources_chunk_locator.py::test_delete_material_does_not_unlink_source_path_traversal -q`
  failed before implementation because the outside file was deleted, then
  passed after the fix.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_resources_chunk_locator.py::test_delete_material_does_not_unlink_source_path_traversal tests\test_resources_chunk_locator.py::test_resolve_material_source_path_rejects_traversal_source_reference tests\test_resources_chunk_locator.py::test_document_file_base64_rejects_source_path_traversal -q`
  passed: 3 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\routers\resources_router\endpoints_materials_drafts.py tests\test_resources_chunk_locator.py`
  passed.
- `git diff --check -- agent_mcp_server\src\lit_assistant_mcp\tools\source.py agent_mcp_server\tests\test_source_tools.py literature_assistant\core\routers\resources_router\endpoints_materials_drafts.py tests\test_resources_chunk_locator.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed with only a CRLF normalization warning for
  `endpoints_materials_drafts.py`.

## Phase 4 Stop Audit, 2026-06-20

Active queue:

- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`, Phase 4.

Done in this phase:

- Source-folder create/update, scan-folder, and query-ingest paths already
  enforce `path_guard.py` safety plus project-scoped `source_folder_ref`
  binding; focused tests passed.
- MCP `source.*` directory roots now reject repo escape and hide denied runtime
  directories before traversal.
- Resource document serving for `source_relative_path` already rejects relative
  traversal and absolute outside paths; focused tests passed.
- Material deletion now rejects `source_relative_path` traversal before unlink.
- Skill zip import and artifact workspace paths were audited and already have
  traversal/symlink/absolute-path guards in their local surfaces.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests\test_source_tools.py -q`
  passed: 11 tests.
- `.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests\test_policy.py -q`
  passed: 7 tests, 1 skipped.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_source_folder_guard_contract.py tests\test_path_guard.py -q`
  passed: 27 tests, 2 skipped.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_resources_chunk_locator.py::test_resolve_material_source_path_rejects_traversal_source_reference tests\test_resources_chunk_locator.py::test_resolve_material_source_path_rejects_absolute_path_outside_allowed_roots tests\test_resources_chunk_locator.py::test_document_file_base64_rejects_source_path_traversal tests\test_resources_chunk_locator.py::test_delete_material_does_not_unlink_source_path_traversal -q`
  passed: 4 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q agent_mcp_server\src\lit_assistant_mcp literature_assistant\core\routers\resources_router\path_guard.py literature_assistant\core\routers\resources_router\endpoints_projects.py literature_assistant\core\routers\resources_router\endpoints_search_upload.py literature_assistant\core\routers\resources_router\endpoints_materials_drafts.py tests\test_resources_chunk_locator.py`
  passed.

Deferred to later authorized slices:

- A single shared `SourceAccessPolicy` abstraction replacing both
  `path_guard.py` and MCP `PathPolicy` remains a future refactor. This phase
  aligns behavior and tests at the current entry points without a broad module
  move.
- Full Windows junction coverage still depends on platform capability; existing
  tests skip cases when the OS cannot create the relevant link type.
- Export/wiki/page-bundle write policies should be revisited when Phase 8 page
  bundle export is implemented.

Authorized local work remaining:

- Phase 5 retrieval and evidence workflow is the next central local slice.

### Phase 5: Retrieval And Evidence Workflow

Goal:

- Turn retrieval into a staged, inspectable flow from natural query to refs to
  bounded content to cited answer.

Likely backend files:

- `literature_assistant/core/routers/evidence_router.py`
- `literature_assistant/core/routers/resources_router/endpoints_search_upload.py`
- `literature_assistant/core/routers/resources_router/_search_helpers.py`
- `literature_assistant/core/chunk_package_quality.py`
- `literature_assistant/core/models/evidence.py`
- `workspace_tests/evaluation_scripts/*`

Implementation direction:

- Keep `search_refs` as identity/metadata only.
- Add or harden an evidence build pipeline:
  - query intent
  - source-specific plans when external sources are available
  - local project search
  - hybrid/rerank status
  - normalized refs
  - bounded `agent_resource_read`
  - evidence pack artifact
  - answer/citation linkage
- Add `candidate_qrels`, `reviewed_qrels`, and `canonical_qrels` state to API/UI.
- Do not show semantic quality claims unless qrels are canonical.

Verification:

- Deterministic tests with mixed project/wiki refs.
- Candidate qrels cannot be promoted with `unknown`.
- Natural-prompt harness proves selected evidence text reaches final answer.

## Implementation Record, 2026-06-20 Phase 5a

Scope:

- First retrieval/evidence workflow slice: expose qrels review state and gate
  semantic retrieval-quality claims in the evidence-pack API.

Rollback:

- `20260620-004727-phase5-retrieval-evidence-slice`

Mature / official references checked:

- NIST TREC relevance-judgement guidance defines qrels as
  `TOPIC ITERATION DOCUMENT# RELEVANCY`; retrieval evaluation depends on judged
  relevance rows, not on a retrieval method label.
- `trec_eval` is the standard TREC community tool for evaluating runs against a
  judged results file.
- BEIR custom dataset guidance keeps `corpus`, `queries`, and `qrels` as
  separate inputs, with qrels carrying query-id, corpus-id, and score.

Changed files:

- `literature_assistant/core/models/evidence.py`
  - Adds `RetrievalQrelsStatusPayload` with defensive validation: semantic
    quality claims are allowed only for `status=canonical` with canonical qrels
    rows.
  - Adds `qrels_status` to `EvidenceRetrievalDiagnosticsPayload`.
- `literature_assistant/core/models/__init__.py`
  - Exports `RetrievalQrelsStatusPayload` through the centralized model module.
- `literature_assistant/core/routers/evidence_router.py`
  - Adds read-only project qrels status detection for direct known files under
    per-project `qrels/`.
  - Counts candidate TREC rows, reviewed JSONL judgment rows, and canonical
    TREC rows without creating, promoting, deleting, or recursively scanning
    qrels artifacts.
  - Attaches the qrels status to every evidence-pack build response.
- `tests/test_evidence_pack_build_contract.py`
  - Adds regressions proving hybrid/rerank retrieval without canonical qrels
    cannot claim semantic quality.
  - Adds regressions proving candidate qrels remain visible but still require
    review.
  - Adds canonical qrels coverage proving the quality gate opens only when
    canonical rows exist.
- `frontend/openapi/modular-pipeline-openapi.json`
- `frontend/src/generated/openapi.ts`
  - Regenerated OpenAPI schema/types so frontend callers can consume
    `retrieval_diagnostics.qrels_status`.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_evidence_pack_build_contract.py::test_evidence_pack_build_reports_hybrid_rerank_when_retriever_returns_dense_hits tests\test_evidence_pack_build_contract.py::test_evidence_pack_build_reports_canonical_qrels_quality_gate tests\test_evidence_pack_build_contract.py::test_evidence_pack_build_reports_candidate_qrels_without_quality_claim -q`
  failed before implementation on missing `qrels_status`, then passed after
  implementation: 3 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_evidence_pack_build_contract.py tests\test_chunk_package_quality.py tests\test_search_refs_contract.py -q`
  passed: 25 tests.
- `.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests\test_runtime_tools.py::test_evidence_pack_build_posts_bounded_query_payload agent_mcp_server\tests\test_runtime_tools.py::test_academic_writing_lint_posts_quality_payload -q`
  passed: 2 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py -q`
  passed: 9 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\models\evidence.py literature_assistant\core\models\__init__.py literature_assistant\core\routers\evidence_router.py tests\test_evidence_pack_build_contract.py tests\test_chunk_package_quality.py tests\test_search_refs_contract.py`
  passed.
- `npm run generate:openapi` in `frontend/` passed.
- `npm run build` in `frontend/` passed.
- `git diff --check -- literature_assistant\core\models\evidence.py literature_assistant\core\models\__init__.py literature_assistant\core\routers\evidence_router.py tests\test_evidence_pack_build_contract.py frontend\openapi\modular-pipeline-openapi.json frontend\src\generated\openapi.ts`
  passed with CRLF warning only for generated OpenAPI JSON.

Skipped / not claimed:

- Frontend UI has not yet rendered qrels status badges or hidden semantic
  quality copy based on `semantic_quality_claim_allowed`.
- Natural-prompt real-provider harness was not run.
- No qrels generation, qrels promotion, retrieval ranking, or source-specific
  external retrieval planning changed in this slice.
- No commit/stage/push was performed.

Residual risk:

- Qrels discovery is intentionally conservative and only checks direct known
  filenames under the per-project `qrels/` directory. Future review-bundle UI
  work can add a first-class manifest/index instead of expanding filesystem
  heuristics.
- Reviewed JSONL row detection counts non-`unknown` judgment rows but does not
  itself prove they have been promoted; that is why `reviewed` still blocks
  semantic quality claims.

Authorized local work remaining:

- Phase 5b should wire qrels status into frontend/chat diagnostics so candidate
  or missing qrels cannot be displayed as semantic retrieval quality.
- Phase 5c can add the natural-prompt harness proving selected evidence text
  reaches the final answer, after the UI/API state gate is visible.

## Implementation Record, 2026-06-20 Phase 5b

Scope:

- Frontend/chat diagnostics projection for Phase 5 qrels status.

Rollback:

- `20260620-005922-phase5b-qrels-ui-diagnostics`

Mature / official references checked:

- Same Phase 5 retrieval-evaluation references as Phase 5a: NIST TREC qrels,
  `trec_eval`, and BEIR dataset separation of corpus/query/qrels.
- Frontend-quality local guidance: keep the UI change narrow, scannable,
  accessible through existing chat diagnostics, and verified with focused tests
  plus build.

Changed files:

- `frontend/src/components/chat/MessageRenderer.tsx`
  - Adds `ChatRetrievalQrelsStatus` to chat retrieval diagnostics.
  - Renders compact qrels status in the existing diagnostics row:
    `qrels 未建立`, `qrels 待复核`, `qrels 待提升`, or
    `语义质量已验证`.
  - Shows candidate/reviewed/canonical counts without raw ids, paths, or JSON.
  - Only renders `语义质量已验证` when `status=canonical`,
    `semantic_quality_claim_allowed=true`, and canonical qrels count is positive.
- `frontend/src/pages/Dialog.tsx`
  - Coerces backend `retrieval_diagnostics.qrels_status` into the typed chat
    diagnostics object without trusting unknown strings.
- Ignored local tests:
  - `frontend/src/components/chat/MessageRenderer.test.tsx`
    - Adds regressions that candidate qrels render as review-needed and do not
      show semantic quality proof.
    - Adds regression that canonical qrels render as the only verified quality
      state.

Verification:

- `npm run test -- MessageRenderer.test.tsx --run` failed before implementation
  because qrels status was not rendered, then passed after implementation:
  5 tests.
- `npm run test -- Dialog.test.tsx MessageRenderer.test.tsx --run` passed:
  25 tests.
- `npm run build` passed.
- `git diff --check -- frontend\src\components\chat\MessageRenderer.tsx frontend\src\components\chat\MessageRenderer.test.tsx frontend\src\pages\Dialog.tsx`
  passed.

Skipped / not claimed:

- No screenshot/browser smoke was run because this is a compact diagnostics row
  covered by component tests and full frontend build.
- Natural-prompt real-provider harness was not run.
- No qrels creation/review/promotion UI was added.
- No commit/stage/push was performed.

Residual risk:

- The UI now consumes qrels status where chat diagnostics use
  `MessageRenderer`; other future retrieval-quality surfaces must use the same
  field instead of inventing their own badges.
- `MessageRenderer.test.tsx` is currently under ignored test paths; this is
  recorded as local test evidence but will need explicit staging policy if the
  test suite is later published.

Authorized local work remaining:

- Phase 5c natural-prompt harness proving selected evidence text reaches the
  final answer without claiming provider autonomy from scripted tool calls.

## Implementation Record, 2026-06-20 Phase 5c

Scope:

- Natural-prompt evidence-backflow harness for `/api/chat` and the live API
  writing-chain smoke script.

Rollback:

- `20260620-010721-phase5c-natural-prompt-evidence-backflow`

Mature / official references checked:

- Vercel AI SDK tool-calling docs: multi-step calls should pass tool results
  back into the next generation until no more tool calls or a stop condition is
  reached.
- MCP tool-result specification: tool results carry structured or unstructured
  content that must stay distinct from provider transcript projection.
- Anthropic tool-use docs: the model decides when to call tools from the user
  request and tool descriptions; applications execute the call and return
  results into the agent loop.

Changed files:

- `tests/test_api_chat_local_literature_tool_use.py`
  - Adds fixture evidence markers and natural-prompt guards so full writing
    chain tests assert the initial user prompt did not enumerate internal tool
    names.
  - Snapshots provider payloads before later runner mutations so each tool-loop
    round can be audited independently.
  - Makes the deterministic fake provider extract an evidence phrase from the
    `agent_resource_read` tool payload and require that phrase in the final
    answer.
- `tests/test_live_api_chat_full_writing_chain_smoke_harness.py`
  - Adds harness tests proving a complete tool chain is not `ok` unless the
    final answer contains a fixture evidence marker.
  - Verifies the smoke summary records `answerEvidenceMarkers` and
    `evidenceBackflowVerified`.
- `workspace_artifacts/generated/output/run_live_api_chat_full_writing_chain_smoke.py`
  - Adds required writing-tool and evidence-marker constants.
  - Adds `_verdict_for_summary()` so `missing_final_evidence_backflow` is a
    failing verdict distinct from `partial_tool_chain`.
  - Records tool-preview markers, answer markers, and evidence-backflow status
    in the generated smoke summary.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_live_api_chat_full_writing_chain_smoke_harness.py tests\test_api_chat_local_literature_tool_use.py::test_chat_ask_local_literature_tools_execute_full_writing_chain_when_allowed tests\test_api_chat_local_literature_tool_use.py::test_api_chat_local_literature_tools_surface_full_writing_chain_transcript -q`
  failed once before payload snapshotting because captured provider payloads
  were mutable and could not prove per-round evidence backflow, then passed
  after the fix: 6 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py tests\test_live_api_chat_full_writing_chain_smoke_harness.py -q`
  passed: 13 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q tests\test_live_api_chat_full_writing_chain_smoke_harness.py tests\test_api_chat_local_literature_tool_use.py workspace_artifacts\generated\output\run_live_api_chat_full_writing_chain_smoke.py`
  passed.
- `git diff --check -- tests\test_api_chat_local_literature_tool_use.py tests\test_live_api_chat_full_writing_chain_smoke_harness.py workspace_artifacts\generated\output\run_live_api_chat_full_writing_chain_smoke.py`
  passed.

Skipped / not claimed:

- No real provider smoke was run in this slice; deterministic fake-provider
  tests are the acceptance evidence.
- The harness proves natural prompt shape plus provider-loop evidence backflow;
  it does not prove every real provider will autonomously choose the same full
  seven-tool writing chain.
- No commit/stage/push was performed.

Residual risk:

- The live smoke script lives under ignored `workspace_artifacts/`; it is
  suitable as local acceptance harness evidence but needs a separate promotion
  decision if it becomes a public test utility.
- The evidence markers are fixture phrases, not semantic citation validation.
  Canonical citation/evidence correctness remains part of writing workflow
  state and later export/lint phases.

### Phase 5 Stop Audit, 2026-06-20

Active queue:

- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`, Phase 5.

Done:

- Phase 5a exposes missing/candidate/reviewed/canonical qrels status through
  the evidence-pack API and blocks semantic quality claims unless canonical
  qrels exist.
- Phase 5b projects qrels status into chat/frontend diagnostics without showing
  candidate or missing qrels as verified semantic quality.
- Phase 5c proves natural-prompt local literature tool loops send selected
  evidence text back to the provider and require final-answer use of that
  evidence marker.

Deferred within retrieval/evidence:

- Source-specific external retrieval planners, ranking improvements, qrels
  review/promotion UI, real-provider autonomous smoke, and semantic citation
  validation remain future slices.

Authorized local work remaining:

- Phase 6 writing workflow state is now the next central local slice. It should
  begin with a fresh rollback checkpoint, dirty-worktree audit, mature reference
  recheck, and a narrow state/artifact contract test before changing writing
  runtime behavior.

### Phase 6: Writing Workflow State

Goal:

- Upgrade writing from tool calls to evidence-backed workflow runs.

Likely backend files:

- `literature_assistant/core/writing_runtime.py`
- `literature_assistant/core/writing_resources.py`
- `literature_assistant/core/routers/writing_router.py`
- `literature_assistant/core/routers/export_router.py`
- `literature_assistant/core/routers/evidence_router.py`
- `literature_assistant/core/academic_writing_linter.py`
- `literature_assistant/core/routers/resources_router/_export_helpers.py`

Likely frontend files:

- `frontend/src/contexts/WritingContext.tsx`
- `frontend/src/components/writing/*`
- `frontend/src/pages/writing/*`
- `frontend/src/types/resources.ts`
- `frontend/src/services/writingBackend.ts`

Implementation direction:

- Add `writing_workflow_state`:
  - intake
  - material scope
  - target venue/style profile
  - language/medium
  - citation policy
  - motivation confirmation
  - source index
  - citation support bank
  - evidence/claim register
  - outline/section plan
  - lint report
  - reviewer read-back findings
  - change log
  - export manifest
- Keep deterministic linter and model-based reviewer separate.
- Allow "no change recommended" as a valid result.
- Make citation support bank required for generated scholarly claims.

Verification:

- Unit tests for workflow-state schema.
- Linter issue schema tests.
- Export manifest tests.
- DOCX/Markdown/CSL export tests with missing citation and figure/table cases.

## Implementation Record, 2026-06-20 Phase 6a

Scope:

- First writing workflow-state slice: durable runtime state snapshot for
  evidence-backed writing jobs.

Rollback:

- `20260620-011858-phase6-writing-workflow-state-preflight`

Mature / official references checked:

- Pandoc manual / CSL workflow separates document body, citation data, and
  citation style so export output does not become the only state source.
- JATS article structure keeps article metadata, body, back matter, and
  references as inspectable structure rather than one generated blob.
- W3C Web Annotation body/target/motivation model maps cleanly to
  claim/evidence/purpose rows for citation support banks.

Changed files:

- `literature_assistant/core/writing_runtime.py`
  - Adds JSON-safe workflow-state helpers.
  - Adds `update_writing_workflow_state()` to persist intake,
    evidence refs, citation bank, lint report, export manifest, change log,
    readiness flags, and schema metadata.
  - Stores workflow state in job metadata, writes a `METADATA` artifact, and
    emits a `JOB_PROGRESS` event with readiness flags.
  - Adds `get_writing_workflow_state()` so resume/import paths can read the
    state without parsing assistant prose or export files.
- Ignored local tests:
  - `tests/test_writing_runtime_persistence.py`
    - Adds a red/green persistence regression proving workflow state survives
      SQLite reload as job metadata, event data, and metadata artifact.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_writing_runtime_persistence.py::test_writing_workflow_state_persists_as_job_metadata_event_and_artifact -q`
  failed before implementation with missing `update_writing_workflow_state`,
  then passed after implementation.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_writing_runtime_persistence.py::test_writing_workflow_state_persists_as_job_metadata_event_and_artifact tests\test_writing_runtime_persistence.py::test_runtime_persists_sessions_jobs_events_and_artifacts_across_instances tests\test_writing_runtime_persistence.py::test_runtime_import_preserves_resource_ingest_and_tolerates_unknown_kind -q`
  passed: 3 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\writing_runtime.py tests\test_writing_runtime_persistence.py`
  passed.
- `git diff --check -- literature_assistant\core\writing_runtime.py tests\test_writing_runtime_persistence.py`
  passed.

Skipped / not claimed:

- No writing/export API endpoint has been wired to create workflow state yet.
- No frontend writing UI state projection, DOCX export validator change, or real
  provider writing run was executed in this narrow runtime-state slice.
- No commit/stage/push was performed.

Residual risk:

- Workflow state currently stores only caller-supplied JSON-safe objects. Later
  slices must connect evidence-pack, linter, export, and writing-router calls
  so the state is populated automatically instead of only by direct runtime API.
- The first state schema is intentionally additive and metadata-backed; a
  dedicated repository table may be useful only after the lifecycle stabilizes.

Authorized local work remaining:

- Phase 6b should first expose `writing_workflow_state` through a typed runtime
  API contract so writing/export callers and Agent Workspace can update/read it
  without parsing job metadata or artifact internals. A later Phase 6c should
  wire existing writing/export operations into that contract while preserving
  current response contracts.

## Implementation Record, 2026-06-20 Phase 6b

Scope:

- First runtime/API wiring slice for writing workflow state.
- Expose a stable read/write API for a job's `writing_workflow_state` without
  changing existing writing/export response contracts.

Rollback:

- Code/API checkpoint: `20260620-012739-phase6b-writing-workflow-state-wiring`
- Record-sync checkpoint: `20260620-013528-phase6b-record-sync`

Mature / official references checked:

- FastAPI response-model documentation: path operations can use Pydantic
  response models to validate, serialize, and document OpenAPI responses.
- FastAPI OpenAPI response documentation: response models are projected into
  generated OpenAPI schemas for typed clients.
- Pydantic schema practice: keep request and response models explicit at API
  boundaries instead of returning untyped metadata bags.
- Pandoc citation workflow, JATS article structure, and W3C Web Annotation
  remain the writing/export state references for keeping citation/evidence
  structure separate from rendered output.

Changed files:

- `literature_assistant/core/models/runtime.py`
  - Adds `WritingWorkflowStateRequest` and `WritingWorkflowStatePayload`.
  - Keeps the API shape additive and JSON-object/list based so the underlying
    runtime validation remains the defensive schema gate.
- `literature_assistant/core/models/__init__.py`
  - Exports the workflow-state request and response models through the central
    model registry.
- `literature_assistant/core/routers/runtime_router.py`
  - Adds `POST /runtime/job/{job_id}/writing-workflow-state`.
  - Adds `GET /runtime/job/{job_id}/writing-workflow-state`.
  - Maps missing jobs or missing workflow state to HTTP 404 and validation
    failures to HTTP 400 through existing runtime exceptions.
- Ignored local tests:
  - `tests/test_runtime_router_contract.py`
    - Adds router coverage proving state update returns typed payload fields
      and the runtime snapshot exposes metadata, event, and artifact evidence.
- Generated API clients:
  - `frontend/openapi/modular-pipeline-openapi.json`
  - `frontend/src/generated/openapi.ts`

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_runtime_router_contract.py::test_runtime_router_updates_writing_workflow_state -q`
  failed before implementation with HTTP 404, then passed after adding the
  runtime endpoints and models.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_runtime_router_contract.py::test_runtime_router_updates_writing_workflow_state tests\test_writing_runtime_persistence.py::test_writing_workflow_state_persists_as_job_metadata_event_and_artifact -q`
  passed: 2 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_runtime_router_contract.py::test_runtime_router_updates_writing_workflow_state tests\test_writing_runtime_persistence.py::test_writing_workflow_state_persists_as_job_metadata_event_and_artifact tests\test_writing_runtime_persistence.py::test_runtime_persists_sessions_jobs_events_and_artifacts_across_instances tests\test_writing_runtime_persistence.py::test_runtime_import_preserves_resource_ingest_and_tolerates_unknown_kind -q`
  passed: 4 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\writing_runtime.py literature_assistant\core\models\runtime.py literature_assistant\core\models\__init__.py literature_assistant\core\routers\runtime_router.py tests\test_writing_runtime_persistence.py tests\test_runtime_router_contract.py`
  passed.
- `npm run generate:openapi` from `frontend/` passed and regenerated the
  schema/client files.
- `npm run build` from `frontend/` passed.
- `git diff --check -- literature_assistant\core\writing_runtime.py literature_assistant\core\models\runtime.py literature_assistant\core\models\__init__.py literature_assistant\core\routers\runtime_router.py tests\test_writing_runtime_persistence.py tests\test_runtime_router_contract.py frontend\openapi\modular-pipeline-openapi.json frontend\src\generated\openapi.ts`
  passed with only the expected CRLF warning for the generated OpenAPI JSON.

Skipped / not claimed:

- Existing writing/export routers and local literature tools are not yet
  automatically populating workflow state.
- No real provider writing run, DOCX export validator, desktop pywebview smoke,
  or full backend test suite was run in this API-contract slice.
- No commit/stage/push was performed.

Residual risk:

- The API currently exposes the workflow-state contract, but caller integration
  remains Phase 6c. Existing writing/export actions will not populate state
  unless they explicitly call the new runtime method or endpoint.
- The frontend has typed generated access to the endpoint, but no visible UI
  projection was implemented in this slice.

Authorized local work remaining:

- Phase 6c should wire one existing writing/export path into
  `update_writing_workflow_state()` with a focused test that preserves that
  path's current response contract.

## Implementation Record, 2026-06-20 Phase 6c

Scope:

- First caller-integration slice for writing workflow state.
- Wire `/api/writing/export` into `WritingRuntime.update_writing_workflow_state()`
  after a successful project export, without adding fields to
  `ProjectExportPayload`.

Rollback:

- `20260620-014024-phase6c-writing-export-state-caller`

Mature / official references checked:

- FastAPI response-model and OpenAPI documentation: preserve the public
  response model while adding internal runtime bookkeeping as a side effect.
- Pandoc citation metadata, JATS article structure, and W3C Web Annotation:
  export state should keep manifest, audit, citation, and evidence summaries
  separate from rendered content.

Changed files:

- `literature_assistant/core/routers/writing_router.py`
  - Imports the existing writing runtime and runtime protocol enums.
  - Adds `_record_project_export_workflow_state()` for successful project
    exports.
  - Creates an `ARTIFACT_EXPORT` runtime job, persists `phase=export_ready`,
    stores intake, evidence summary, citation summary, lint presence, export
    manifest, and change log, then completes the job.
  - Keeps runtime-recording failures non-fatal for the export response by
    logging a warning and returning the original export payload.
- Ignored local tests:
  - `tests/test_writing_submission_export.py`
    - Adds a red/green regression proving `/api/writing/export` records
      workflow state while the response body does not expose `runtime_job_id` or
      `workflow_state`.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_writing_submission_export.py::TestProjectExport::test_export_project_records_runtime_workflow_state -q`
  failed before implementation because `writing_router` had no runtime hook,
  then passed after the caller integration.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_writing_submission_export.py -q`
  passed: 9 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_runtime_router_contract.py::test_runtime_router_updates_writing_workflow_state tests\test_writing_runtime_persistence.py::test_writing_workflow_state_persists_as_job_metadata_event_and_artifact -q`
  passed: 2 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_writing_submission_export.py tests\test_runtime_router_contract.py::test_runtime_router_updates_writing_workflow_state tests\test_writing_runtime_persistence.py::test_writing_workflow_state_persists_as_job_metadata_event_and_artifact tests\test_writing_runtime_persistence.py::test_runtime_persists_sessions_jobs_events_and_artifacts_across_instances -q`
  passed: 12 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\routers\writing_router.py tests\test_writing_submission_export.py`
  passed.
- `git diff --check -- literature_assistant\core\routers\writing_router.py tests\test_writing_submission_export.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed before this record update.

Skipped / not claimed:

- `/api/export/docx`, writing linter direct calls, outline generation, local
  literature tools, and frontend/Agent Workspace projection are not yet wired
  to workflow state.
- No real provider writing run, desktop pywebview smoke, full backend suite, or
  frontend build was run for this narrow caller slice.
- No commit/stage/push was performed.

Residual risk:

- The helper creates one runtime session/job per successful writing export.
  Later event projection should decide how these jobs appear in Agent Workspace.
- Runtime-recording failure is intentionally non-fatal to preserve export
  behavior; a future observability slice can surface those warnings in local
  audit records.

Authorized local work remaining:

- Phase 6 stop audit should classify remaining writing/export work. A next
  local slice can add deterministic export/lint manifest validation or wire the
  direct DOCX export path, but only after a fresh checkpoint and dirty-worktree
  audit.

### Phase 6 Stop Audit, 2026-06-20

Active queue:

- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`, Phase 6.

Rollback:

- `20260620-014950-phase6-stop-audit-record`

Done:

- Phase 6a added durable `writing_workflow_state` persistence in
  `WritingRuntime` with metadata, event, and artifact evidence.
- Phase 6b exposed typed runtime API read/write endpoints for workflow state and
  regenerated frontend OpenAPI types.
- Phase 6c wired `/api/writing/export` into runtime workflow state while
  preserving `ProjectExportPayload`.

Deferred within writing/export:

- Direct `/api/export/docx` workflow-state recording remains a future narrow
  caller slice because it returns a file response and needs a separate response
  preservation test.
- Direct linter/local-literature-tool workflow-state recording remains future
  work; current lint evidence is already included in project export state when
  export calls the deterministic linter.
- Frontend writing UI and Agent Workspace projection of workflow-state jobs
  belong to Phase 7 event projection, not more Phase 6 persistence work.
- Real-provider writing acceptance remains skipped until a later acceptance
  harness explicitly needs configured credentials.

Residual risk:

- Phase 6 now has a stable state contract and one JSON export caller, but not
  every writing/export surface populates it.
- Runtime-export jobs may need UI grouping/dedupe decisions in Phase 7 to avoid
  noisy Agent Workspace projections.

Authorized local work remaining:

- Phase 7 runtime jobs/artifacts and Agent Workspace typed event projection is
  now the next central local slice. It should start with a backend event/schema
  audit and a focused test before touching frontend reducers.

### Phase 7: Runtime Jobs, Artifacts, And Agent Workspace

Goal:

- Render real run state across scan, retrieval, writing, export, MCP calls, and
  agent bridge tasks.

Likely backend files:

- `literature_assistant/core/writing_runtime.py`
- `literature_assistant/core/routers/runtime_router.py`
- `literature_assistant/core/routers/agent_bridge_router.py`
- `literature_assistant/core/runtime_descriptor.py`
- `literature_assistant/core/harness_protocols.py`

Likely frontend files:

- `frontend/src/pages/AgentWorkspace.tsx`
- `frontend/src/services/agentWorkspaceApi.ts`
- `frontend/src/services/runtimeClient.ts`
- `frontend/src/types/runtime.ts`
- `frontend/src/pages/Jobs.tsx`
- `frontend/src/pages/jobsDisplay.ts`

Implementation direction:

- Normalize `Session`, `Run`, `Job`, `ToolCall`, `Artifact`, and `Event`.
- Add stable event ids and in-place update keys.
- Deduplicate progressive updates by tool call id or job id.
- Render:
  - requested
  - discovered
  - hidden by policy
  - awaiting approval
  - running
  - progress
  - result ready
  - truncated
  - denied
  - failed
  - cancelled
  - completed
- Keep runtime job artifacts separate from project materials/chunks/figure assets
  and export artifacts.

Verification:

- Backend event sequence tests.
- Frontend reducer tests for duplicate progress and action/result replacement.
- Desktop pywebview smoke for Agent Workspace only after backend tests pass.

## Implementation Record, 2026-06-20 Phase 7a

Scope:

- First backend/API event projection slice for Agent Workspace and runtime job
  lists.
- Add a compact `writing_workflow_state_summary` to `JobPayload` so frontends
  can render writing/export workflow status without parsing raw job metadata or
  large evidence/citation arrays.

Rollback:

- `20260620-015113-phase7-runtime-event-projection-preflight`

Mature / official references checked:

- Vercel AI SDK UI message parts: frontends should consume typed parts/state,
  not infer tool/runtime state from prose logs.
- LangGraph persistence/streaming records: long-running workflows should expose
  resumable, structured state projections.
- Existing Scholar AI runtime snapshot endpoints: job lists and snapshots are
  the local typed projection surface for Agent Workspace.

Changed files:

- `literature_assistant/core/models/runtime.py`
  - Adds additive `writing_workflow_state_summary` to `JobPayload`.
- `literature_assistant/core/routers/runtime_router.py`
  - Adds `_writing_workflow_state_summary()` to project compact workflow state
    from job metadata.
  - Adds `_job_payload()` and uses it for job create/list/detail/snapshot
    responses.
  - Summary includes phase, updated_at, readiness flags, project/task hints,
    export format/filename/media type, and lint status only; it intentionally
    omits full evidence refs and citation bank rows.
- Ignored local tests:
  - `tests/test_runtime_router_contract.py`
    - Adds a red/green regression proving `/runtime/jobs` exposes compact
      workflow summary without leaking full citation/evidence arrays.
- Generated API clients:
  - `frontend/openapi/modular-pipeline-openapi.json`
  - `frontend/src/generated/openapi.ts`

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_runtime_router_contract.py::test_runtime_jobs_project_writing_workflow_state_summary -q`
  failed before implementation with missing `writing_workflow_state_summary`,
  then passed after the model/router projection.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_runtime_router_contract.py::test_runtime_jobs_project_writing_workflow_state_summary tests\test_runtime_router_contract.py::test_runtime_router_updates_writing_workflow_state -q`
  passed: 2 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_runtime_router_contract.py::test_runtime_jobs_project_writing_workflow_state_summary tests\test_runtime_router_contract.py::test_runtime_router_updates_writing_workflow_state tests\test_writing_runtime_persistence.py::test_writing_workflow_state_persists_as_job_metadata_event_and_artifact tests\test_writing_submission_export.py::TestProjectExport::test_export_project_records_runtime_workflow_state -q`
  passed: 4 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_runtime_router_contract.py tests\test_writing_runtime_persistence.py::test_writing_workflow_state_persists_as_job_metadata_event_and_artifact tests\test_writing_submission_export.py::TestProjectExport::test_export_project_records_runtime_workflow_state -q`
  passed: 14 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\models\runtime.py literature_assistant\core\routers\runtime_router.py tests\test_runtime_router_contract.py`
  passed.
- `npm run generate:openapi` from `frontend/` passed.
- `npm run build` from `frontend/` passed.
- `git diff --check -- literature_assistant\core\models\runtime.py literature_assistant\core\routers\runtime_router.py tests\test_runtime_router_contract.py frontend\openapi\modular-pipeline-openapi.json frontend\src\generated\openapi.ts literature_assistant\core\routers\writing_router.py tests\test_writing_submission_export.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed with only the expected CRLF warning for generated OpenAPI JSON.

Skipped / not claimed:

- Agent Workspace UI has not yet rendered `artifact_export` jobs or workflow
  summary badges; the typed backend projection now enables that as the next
  narrow frontend slice.
- No desktop pywebview smoke was run because the visible UI did not change in
  this slice.
- No full backend suite, full frontend test suite, real provider run, commit,
  stage, or push was performed.

Residual risk:

- The summary is deliberately compact. Future UI may still need job-specific
  detail fetches for full evidence/citation rows.
- Existing Agent Workspace filters still hide non-`resource_ingest` runtime jobs
  until the frontend slice includes `artifact_export`/workflow jobs.

Authorized local work remaining:

- Phase 7b should render writing/export runtime jobs in Agent Workspace using
  the generated `writing_workflow_state_summary` field, with a focused
  component test and frontend build.

## Implementation Record, 2026-06-20 Phase 7b

Scope:

- Frontend Agent Workspace projection for writing/export runtime jobs.
- Include `artifact_export` and runtime jobs with
  `writing_workflow_state_summary` in the existing job list without changing the
  page layout architecture.
- Render compact workflow badges for writing export status, phase, export
  format, and filename.

Rollback:

- `20260620-015914-phase7b-agent-workspace-writing-jobs`
- Follow-up checkpoint before test assertion fix:
  `20260620-020540-phase7b-agent-workspace-test-fix`

Mature / official references checked:

- Vercel AI SDK UI message/data-part documentation: frontends should consume
  typed state projections instead of parsing prose logs.
- Testing Library async query documentation: when duplicate UI projections are
  intentional, tests should use `findAllByText` or a scoped query rather than a
  singular async query.
- Existing Scholar AI generated OpenAPI types: Agent Workspace should consume
  the additive `writing_workflow_state_summary` field from `JobPayload`.

Changed files:

- `frontend/src/pages/AgentWorkspace.tsx`
  - Adds runtime-job visibility logic for `artifact_export` and jobs carrying a
    workflow summary.
  - Renders writing export, phase, export format, and export filename badges in
    the existing job row.
  - Updates the summary stat from resource-ingest-only to visible runtime jobs.
- Ignored local tests:
  - `frontend/src/pages/AgentWorkspace.test.tsx`
    - Adds a component regression for an `artifact_export` job with
      `writing_workflow_state_summary`.
    - Uses `findAllByText` because the selected job appears in both the list row
      and the detail panel.

Verification:

- `npm run test -- AgentWorkspace.test.tsx --run` from `frontend/` first failed
  before implementation because the `artifact_export` runtime job was hidden.
- After the Agent Workspace change, the focused test failed once because the
  job title was intentionally projected twice. The test was corrected to assert
  both projections.
- `npm run test -- AgentWorkspace.test.tsx --run` from `frontend/` passed:
  1 test.
- `npm run build` from `frontend/` passed.

Skipped / not claimed:

- No desktop pywebview smoke was run in this narrow component/build slice.
- No full frontend suite, full backend suite, real provider smoke, commit,
  stage, push, release, or publish was performed.
- This slice does not add full workflow detail polling, event replay, or
  artifact download actions.

Residual risk:

- Agent Workspace now shows writing/export runtime jobs, but still renders only
  compact summary fields. Detail views may need follow-up fetches for full
  evidence/citation state.
- `frontend/src/pages/AgentWorkspace.test.tsx` is ignored by `.gitignore`, so
  ordinary visible `git status` will not show the new regression.

Phase 7 Stop Audit, 2026-06-20:

- Done:
  - Runtime job payloads expose compact writing workflow summaries.
  - Agent Workspace includes writing/export runtime jobs and displays their
    summary badges.
  - Focused component regression and frontend build passed.
- Deferred:
  - Full event replay/dedup reducers and detail polling are not needed for the
    current writing/export summary projection.
  - Desktop pywebview smoke remains a later UI acceptance gate when the active
    slice needs native-window validation.
- Authorized local work remaining:
  - Phase 8 page-bundle/export artifact work is the next central local slice.

### Phase 8: Wiki, Graph, Knowledge, And Export Bundles

Goal:

- Make generated knowledge portable and evidence-linked.

Likely backend files:

- `literature_assistant/core/routers/wiki_router.py`
- `literature_assistant/core/wiki/*`
- `literature_assistant/core/routers/knowledge_router.py`
- `literature_assistant/core/knowledge_graph/*`
- `literature_assistant/core/evolution/*`

Likely frontend files:

- `frontend/src/pages/WikiWorkbench.tsx`
- `frontend/src/components/wiki/*`
- `frontend/src/components/knowledge/*`
- `frontend/src/components/graph/*`

Implementation direction:

- Treat wiki pages, publication drafts, evidence packs, and export outputs as
  page-bundle-like artifacts:
  - `index.md`
  - metadata/front matter JSON
  - evidence refs
  - citations/BibTeX/CSL
  - figures/assets
  - generated DOCX/PDF/HTML when applicable
  - verification report
- Route `agent_bridge` result flags into real wiki/graph/evolution consumers
  instead of only tagging results.

Verification:

- Export bundle contract tests.
- Wiki import/export round-trip tests.
- Evidence ref and citation metadata remain linked after export.

## Implementation Record, 2026-06-20 Phase 8a

Scope:

- First page-bundle/export artifact contract slice for the existing
  `/api/writing/export` path.
- Add a machine-readable bundle manifest artifact to the runtime export job
  without changing the stable `ProjectExportPayload` response body.
- Keep this as a manifest contract only; it does not yet create a full on-disk
  page-bundle directory with `index.md` and copied resources.

Rollback:

- `20260620-021122-phase8a-writing-export-bundle-manifest`

Mature / official references checked:

- Hugo page bundles: portable knowledge outputs should have an entry document
  plus associated resources.
- RO-Crate metadata guidance: artifact groups should carry machine-readable
  metadata about resources and provenance.
- JATS article structure: scholarly output metadata, body/support objects, and
  references should remain inspectable rather than only embedded in a rendered
  document.

Changed files:

- `literature_assistant/core/writing_runtime.py`
  - Adds public `add_job_artifact()` with defensive validation for job id,
    artifact type, content shape, metadata shape, and MIME type.
  - Persists artifacts through the existing runtime artifact path instead of
    requiring routers to call private storage helpers.
- `literature_assistant/core/routers/writing_router.py`
  - Adds `_build_project_export_bundle_manifest()` for one writing export.
  - Stores a `writing_export_bundle_manifest` metadata artifact on the export
    runtime job.
  - Links the bundle manifest artifact id and schema version into
    `writing_workflow_state.export_manifest`.
- Ignored local tests:
  - `tests/test_writing_submission_export.py`
    - Extends the existing `/api/writing/export` workflow-state regression to
      assert a bundle manifest artifact exists and response shape stays stable.
  - `tests/test_writing_runtime_persistence.py`
    - Adds a runtime regression for public metadata artifact creation and
      persistence reload.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_writing_submission_export.py::TestProjectExport::test_export_project_records_runtime_workflow_state -q`
  failed before implementation because no `writing_export_bundle_manifest`
  artifact existed, then passed after implementation.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_writing_runtime_persistence.py::test_add_job_artifact_attaches_metadata_artifact tests\test_writing_submission_export.py::TestProjectExport::test_export_project_records_runtime_workflow_state -q`
  passed: 2 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_writing_submission_export.py tests\test_runtime_router_contract.py::test_runtime_jobs_project_writing_workflow_state_summary tests\test_runtime_router_contract.py::test_runtime_router_updates_writing_workflow_state tests\test_writing_runtime_persistence.py::test_add_job_artifact_attaches_metadata_artifact tests\test_writing_runtime_persistence.py::test_writing_workflow_state_persists_as_job_metadata_event_and_artifact -q`
  passed: 13 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\routers\writing_router.py literature_assistant\core\writing_runtime.py tests\test_writing_submission_export.py tests\test_writing_runtime_persistence.py`
  passed.
- `git diff --check -- literature_assistant\core\routers\writing_router.py literature_assistant\core\writing_runtime.py tests\test_writing_submission_export.py tests\test_writing_runtime_persistence.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed.

Skipped / not claimed:

- No frontend bundle view/download action was added.
- No full on-disk page-bundle directory is written yet.
- No full backend suite, frontend suite, desktop pywebview smoke, real provider
  smoke, commit, stage, push, release, or publish was performed.

Residual risk:

- The manifest currently lives as a runtime metadata artifact; a later slice
  should materialize a controlled on-disk bundle when the file layout and
  download/cleanup policy are chosen.
- Existing `/api/export/docx`, wiki export, graph export, and direct local
  literature tools do not yet emit the same bundle manifest contract.

Authorized local work remaining:

- Phase 8b can either materialize the writing export bundle under controlled
  `workspace_artifacts/` output or extend the manifest contract to one wiki
  export path, after a fresh dirty-worktree audit and mature-reference check.

## Implementation Record, 2026-06-20 Phase 8b

Scope:

- Extend the page-bundle manifest contract to one existing wiki export path.
- Keep `/api/wiki/export` response shape stable while adding `manifest.json`
  inside the generated Markdown zip archive.
- Preserve wiki permission filtering: only readable pages are included in the
  archive and manifest.

Rollback:

- `20260620-022101-phase8b-wiki-export-bundle-manifest`

Mature / official references checked:

- Hugo page bundles: exported knowledge should be inspectable as page resources
  plus a discoverable manifest.
- RO-Crate metadata guidance: archive contents should describe resources and
  provenance in machine-readable metadata.
- Existing Scholar AI wiki permissions tests: export manifests must not leak
  private/unreadable pages.

Changed files:

- `literature_assistant/core/wiki/export.py`
  - Adds `_build_wiki_export_bundle_manifest()` and writes
    `manifest.json` into wiki Markdown export zips.
  - Manifest records schema version, bundle kind, archive filename, page count,
    resource count, page paths, and byte counts.
- Ignored/local tests:
  - `tests/test_wiki_export.py`
    - Asserts `manifest.json` exists in the archive and records exported page
      resources.
  - `tests/test_wiki_permissions.py`
    - Updates export permission regression to require `manifest.json` while
      proving private pages remain excluded.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_wiki_export.py::TestWikiExportFunction::test_export_creates_zip_with_pages -q`
  failed before implementation because `manifest.json` was absent, then passed
  after implementation and order-stable assertion correction.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_wiki_export.py -q`
  passed: 9 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_wiki_capture_review_flow.py tests\test_wiki_permissions.py -k "pending_capture_draft_is_hidden_from_default_wiki_surfaces or export_filters_unreadable_pages" -q`
  passed: 2 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_wiki_export.py tests\wiki\test_wiki_capture_review_flow.py tests\test_wiki_permissions.py -k "wiki_export or export or pending_capture_draft_is_hidden_from_default_wiki_surfaces" -q`
  passed: 11 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki\export.py tests\test_wiki_export.py tests\test_wiki_permissions.py tests\wiki\test_wiki_capture_review_flow.py`
  passed.
- `git diff --check -- literature_assistant\core\wiki\export.py tests\test_wiki_export.py tests\test_wiki_permissions.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed.

Skipped / not claimed:

- No frontend wiki export view/download changes were made.
- No graph export bundle manifest was added.
- No full backend suite, frontend suite, desktop pywebview smoke, real provider
  smoke, commit, stage, push, release, or publish was performed.

Residual risk:

- Wiki `manifest.json` records exported Markdown resources but not evidence refs,
  graph nodes, citation metadata, or import provenance yet.
- Existing archives now include an extra `manifest.json`; tests that assumed
  exact namelist equality were updated for the new contract.

Phase 8 Stop Audit, 2026-06-20:

- Done:
  - Writing export runtime jobs now carry a bundle manifest metadata artifact.
  - Wiki Markdown export zips now include a machine-readable manifest.
  - Focused writing/runtime and wiki export/permission tests passed.
- Deferred:
  - Full on-disk writing export bundle materialization, graph export manifests,
    frontend bundle projection, and download/open UX remain later work.
- Authorized local work remaining:
  - Phase 9 natural-prompt acceptance harness is the next central local slice,
    because the high-risk state/provenance/export evidence contracts now have
    initial backend coverage.

### Phase 9: Acceptance Harness

Goal:

- Replace overclaiming smokes with layered acceptance.

Implementation direction:

- Keep explicit-tool-sequence harness as a control test.
- Add natural-prompt acceptance:
  - provider capability must be `tool_call_ok`
  - prompt does not enumerate tool sequence
  - provider selects at least one relevant tool
  - bounded content reaches the provider
  - final answer cites or uses that content
  - artifacts record raw envelope, provider payload, audit preview, final answer,
    and verification status
- Add fake-provider negative cases:
  - tools swallowed
  - max rounds
  - partial chain
  - timeout
  - tool error returned to model
  - context budget exceeded

Verification:

- Deterministic tests are mandatory.
- Real provider smokes are low-budget, masked, and optional per slice.
- `partial_tool_chain` is failure unless the test name says partial is expected.

## Implementation Record, 2026-06-20 Phase 9a

Scope:

- Harden the deterministic live `/api/chat` writing-chain smoke harness so
  natural-prompt acceptance claims expose explicit machine-readable criteria.
- Preserve existing explicit-tool-sequence control mode and real-provider
  execution path; this slice does not run a real provider smoke.

Rollback:

- `20260620-022707-phase9a-natural-prompt-harness-contract`

Mature / official references checked:

- Vercel AI SDK tool-calling guidance: applications should distinguish
  provider-selected tool calls from ordinary text completion.
- Anthropic tool-use guidance: tool execution and returned tool results are
  structured evidence separate from final prose.
- Existing Scholar AI longrun playbook: partial chains and missing final-answer
  evidence backflow must not be counted as successful acceptance.

Changed files:

- Ignored local harness:
  - `workspace_artifacts/generated/output/run_live_api_chat_full_writing_chain_smoke.py`
    - Adds `acceptanceCriteria` to the smoke summary with natural/explicit
      prompt mode, provider-selected tool calls, required-tool coverage,
      bounded tool-content backflow, final-answer evidence backflow, and fixture
      leak status.
    - Keeps existing verdict and exit-code behavior.
- Ignored local tests:
  - `tests/test_live_api_chat_full_writing_chain_smoke_harness.py`
    - Adds a regression proving natural-prompt summaries expose acceptance
      criteria separately from prose claims.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_live_api_chat_full_writing_chain_smoke_harness.py::test_harness_natural_prompt_summary_exposes_acceptance_contract -q`
  failed before implementation with missing `acceptanceCriteria`, then passed
  after implementation.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_live_api_chat_full_writing_chain_smoke_harness.py -q`
  passed: 5 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q workspace_artifacts\generated\output\run_live_api_chat_full_writing_chain_smoke.py tests\test_live_api_chat_full_writing_chain_smoke_harness.py`
  passed.
- `git diff --check -- workspace_artifacts\generated\output\run_live_api_chat_full_writing_chain_smoke.py tests\test_live_api_chat_full_writing_chain_smoke_harness.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed.

Skipped / not claimed:

- No real provider/API smoke was run in this deterministic harness contract
  slice.
- No full backend suite, frontend suite, desktop pywebview smoke, commit,
  stage, push, release, or publish was performed.

Residual risk:

- The harness now records acceptance criteria, but real provider behavior still
  depends on configured credentials, provider tool-call support, and external
  network/rate limits.
- `workspace_artifacts/generated/output/run_live_api_chat_full_writing_chain_smoke.py`
  and the harness tests are ignored/local-only, so ordinary visible
  `git status` will not show these updates.

Phase 9 Stop Audit, 2026-06-20:

- Done:
  - Natural-prompt harness summaries distinguish prompt mode,
    provider-selected tool calls, required-tool coverage, bounded content
    backflow, final-answer evidence backflow, and fixture leak status.
  - Existing partial-chain and missing-final-evidence verdict failures remain
    covered by deterministic tests.
- Deferred:
  - Low-budget real provider smoke is environment-dependent and should run only
    when existing configured credentials and provider capability records are
    available.
  - Broader acceptance around desktop UI remains outside this backend harness
    slice.
- Authorized local work remaining:
  - The active code plan's core phases now have local implementation records.
    Next step is a final requirement-to-evidence audit across the plan before
    claiming completion or choosing any new plan beyond this queue.

## Suggested Slice Order

1. Worktree ownership audit and baseline verification.
2. Typed tool-loop state/stop reasons.
3. Provider capability registry gates tool dispatch.
4. Total context budget and payload accounting.
5. Unified source safety across scan/source/upload/resource/export.
6. Agent Workspace typed event projection.
7. Writing workflow state and citation support bank.
8. Retrieval qrels visibility and evidence quality workflow.
9. Page-bundle artifact export contract.
10. Natural-prompt acceptance harness.

This order keeps the highest-risk truthfulness and safety contracts first. It
also avoids building UI and writing workflows on top of ambiguous provider/tool
states.

## Current Plan Status

- Reference-learning record optimization: complete for this document set.
- Phase 0 ownership audit: complete for the 2026-06-19 code-continuation
  slice.
  - `git status --short --branch` showed `main...origin/main [ahead 1]` and no
    uncommitted visible paths before edits.
  - The local ahead commit is `2e1aa8e8 feat(mcp): expand scholarly runtime
    bridge`; its wide 75-file diff is the current baseline and must not be
    confused with this slice's new edits.
  - `tests/*` and `docs/plans/*` are ignored/local-only; use
    `git status --short --ignored -- <path>` when auditing test and plan
    records.
- Rollback checkpoint for the first product-code slice:
  `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260619-223623-phase0-tool-loop-preflight`.
- Phase 1 typed tool-loop diagnostics: first two narrow slices implemented.
  - Added typed stop reasons, terminal states, ordered lifecycle events, and a
    JSON-ready diagnostics payload in
    `literature_assistant/core/mcp_runtime/tool_use_runner.py`.
  - Provider-call failures and malformed provider/adapter payloads now return
    failed `ToolUseRunResult` diagnostics instead of escaping as untyped runner
    exceptions.
  - `/chat/ask` and `/api/chat` MCP transcript dumps now include
    `mcp_run.diagnostics` while preserving legacy `stopped_reason` and
    `tool_calls`.
  - Local ignored characterization tests now assert no-tool, completed,
    max-round, total-timeout, per-tool-error, provider-call failure,
    adapter-conversion failure, and API transcript diagnostics.
- Product-code verification for this slice: focused checks passed; see
  "Implementation Record, 2026-06-19 Phase 0 + Phase 1a" and
  "Implementation Record, 2026-06-19 Phase 1b".
- Full product implementation: incomplete. Provider capability gating, total
  context budget accounting, unified source safety, frontend reducers, writing
  state, retrieval qrels, bundle export, and natural-prompt acceptance remain
  future phases.
- Next code action: run a Phase 1 stop audit for disabled/non-started policy
  paths and schema exposure, then move to Phase 2 only if no remaining Phase 1
  authorized local backend diagnostics work remains.

## Implementation Record, 2026-06-19 Phase 0 + Phase 1a

Scope:

- Phase 0 preflight and ownership audit.
- Phase 1a typed diagnostics for the existing bounded MCP tool-use loop.

Rollback:

- `20260619-223623-phase0-tool-loop-preflight`

Mature / official references checked:

- Vercel AI SDK Core tool calling documents multi-step tool loops controlled by
  `stopWhen` / `stepCountIs`; this supports explicit loop-stop diagnostics
  rather than relying on answer text.
- Vercel AI SDK Agents loop-control docs separate loop continuation rules from
  per-step tool execution.
- MCP tools specification defines tool calls as structured external-system
  interactions with content-bearing results; this supports preserving tool
  result records separately from provider transcript projection.
- Anthropic stop-reason docs state that provider responses include a
  machine-readable `stop_reason`; this supports exposing typed terminal reasons
  for Scholar AI's local loop too.

Changed files:

- `literature_assistant/core/mcp_runtime/tool_use_runner.py`
  - Adds `ToolLoopStopReason`, `ToolLoopTerminalState`,
    `ToolLoopEventType`, `ToolLoopEvent`, and `ToolLoopDiagnostics`.
  - Emits `tool_loop_started`, `provider_no_tool_calls`,
    `tool_call_received`, `tool_result_rendered`,
    `tool_execution_error_returned`, `tool_call_denied`, `follow_up_sent`,
    `tool_loop_completed`, `tool_loop_max_rounds`, and
    `tool_loop_timeout` where current behavior already exposes those paths.
- `literature_assistant/core/routers/chat_mcp_integration.py`
  - Adds `diagnostics` to transcript dumps without removing existing fields.
- Ignored local tests:
  - `tests/test_mcp_phase2_tool_loop.py`
  - `tests/test_api_chat_local_literature_tool_use.py`

Verification:

- `git diff --check -- literature_assistant\core\mcp_runtime\tool_use_runner.py literature_assistant\core\routers\chat_mcp_integration.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py`
  passed.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\mcp_runtime literature_assistant\core\routers\chat_mcp_integration.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py`
  passed.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_phase2_tool_loop.py -q`
  passed: 51 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py -q`
  passed: 7 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_pending_calls.py::test_pending_call_approve_resumes_runner_and_audits tests\test_mcp_pending_calls.py::test_pending_call_reject_returns_user_rejected_record tests\test_mcp_pending_calls.py::test_pending_call_timeout_audits_and_returns_timeout_record -q`
  passed: 3 tests.

Skipped / not claimed:

- Full backend test suite, frontend build, desktop pywebview smoke, real
  provider smoke, and provider capability gate verification were not run in
  this narrow backend diagnostics slice.
- No commit/stage/push was performed.
- This slice does not prove provider autonomy, provider tool support, writing
  quality, total context-budget behavior, or frontend event rendering.

Residual risk:

- `tests/*` is ignored by `.gitignore`; ordinary `git status` will not show the
  new characterization assertions.
- The typed enum includes future stop reasons that are not yet emitted by all
  call sites. Remaining Phase 1 work should cover provider-call failure,
  adapter conversion errors, and non-started/disabled policy paths before
  Phase 2.
- Public schema/openapi generation was not updated; current response model uses
  an additive `dict[str, Any]` transcript, so this was intentionally deferred.

## Implementation Record, 2026-06-19 Phase 1b

Scope:

- Phase 1b typed diagnostics for provider-call failure and adapter-conversion
  failure paths in the bounded MCP tool-use loop.

Rollback:

- `20260619-225957-phase1b-provider-failure-diagnostics`

Mature / official references checked:

- Vercel AI SDK Core tool calling docs treat multi-step tool execution as a
  bounded loop with explicit stop conditions.
- MCP tool-result schema separates tool-result content and error state from
  provider transcript projection.
- Anthropic stop-reason docs expose provider termination as machine-readable
  protocol state.
- OpenAI function-calling docs treat tool calls and tool responses as
  structured messages, not prose-only evidence.

Changed files:

- `literature_assistant/core/mcp_runtime/tool_use_runner.py`
  - Adds bounded failure-envelope helpers for provider-call and adapter
    conversion failures.
  - Converts `chat_call` exceptions into failed diagnostics with
    `tool_call_failed_no_model_payload`.
  - Converts non-dict or malformed provider payloads into failed diagnostics
    with `adapter_conversion_error`.
  - Preserves legacy `stopped_reason` strings as `provider_error` and
    `adapter_error` for compatibility and later router/API decisions.
- Ignored local tests:
  - `tests/test_mcp_phase2_tool_loop.py`
    - Adds failing-then-passing characterization for provider exceptions,
      non-dict provider payloads, and malformed OpenAI-compatible payloads.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_phase2_tool_loop.py::test_runner_returns_provider_failure_diagnostics_when_chat_call_raises tests\test_mcp_phase2_tool_loop.py::test_runner_returns_adapter_diagnostics_for_non_dict_provider_payload tests\test_mcp_phase2_tool_loop.py::test_runner_returns_adapter_diagnostics_for_malformed_tool_call_payload -q`
  failed before implementation with raw `RuntimeError` / `AttributeError`,
  then passed after implementation: 3 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_phase2_tool_loop.py -q`
  passed: 54 tests.
- `git diff --check -- literature_assistant\core\mcp_runtime\tool_use_runner.py literature_assistant\core\routers\chat_mcp_integration.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py`
  passed.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\mcp_runtime literature_assistant\core\routers\chat_mcp_integration.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py`
  passed.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py -q`
  passed: 7 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_pending_calls.py::test_pending_call_approve_resumes_runner_and_audits tests\test_mcp_pending_calls.py::test_pending_call_reject_returns_user_rejected_record tests\test_mcp_pending_calls.py::test_pending_call_timeout_audits_and_returns_timeout_record -q`
  passed: 3 tests.

Skipped / not claimed:

- Full backend test suite, frontend build, desktop pywebview smoke, real
  provider smoke, and provider capability gate verification were not run.
- No commit/stage/push was performed.
- This slice does not prove provider native tool-call support or final
  end-to-end answer quality.

Residual risk:

- Router-level HTTP 502 payloads still do not expose `mcp_run.diagnostics` for
  failed tool-loop runs; the runner now has typed data for a later API contract
  slice, but this slice did not change the public error response.
- Disabled/non-started policy paths remain represented by enum values but are
  not emitted in ordinary successful responses because those paths currently do
  not enter `McpToolUseRunner`.

### Phase 1 Stop Audit, 2026-06-19

Active queue:

- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`, Phase 1.

Done:

- Runner exits now expose typed stop reason, terminal state, event sequence,
  rounds, tool-call counts, tool-error counts, and truncation counts.
- No-tool, completed loop, max-round, total-timeout, per-tool error,
  provider-call failure, and adapter-conversion failure paths are covered by
  focused characterization tests.
- `/chat/ask` and `/api/chat` successful MCP/local-tool responses include
  additive `mcp_run.diagnostics` while preserving legacy transcript fields.

Deferred to later authorized slices:

- Public error responses for failed MCP tool-loop runs still return HTTP 502
  through existing router parsing. A later API-contract slice can decide
  whether to surface `mcp_run.diagnostics` in error payloads; this was not
  changed here to avoid widening the Phase 1 backend runner slice.
- `tool_loop_not_started`, `mcp_disabled_by_policy`,
  `provider_tool_probe_failed`, and `tools_hidden_by_policy` remain enum values
  for future projections. The first two are mostly route/gate states, and
  `provider_tool_probe_failed` belongs to Phase 2 provider capability gating.

Authorized local work remaining:

- Phase 2 provider capability registry is now the next central local slice.
  It should start with fake-provider tests and must not infer tool support from
  ordinary chat success.

## Implementation Record, 2026-06-19 Phase 2a

Scope:

- First provider capability registry slice: runtime capability records and chat
  tool-dispatch gate.

Rollback:

- `20260619-230823-phase2-provider-capability-registry`

Mature / official references checked:

- OpenAI function-calling docs define tool use through structured `tools` and
  `tool_choice`; ordinary text chat success does not prove function calling.
- Vercel AI SDK tool-calling docs model tool loops as explicit multi-step
  provider/tool protocol, supporting a distinct gate before tools are offered.
- MCP tool-result schema keeps tool execution and tool errors in structured
  records, supporting a separate provider-capability state.
- LiteLLM / Goose reference learning records showed provider/model capability
  should be metadata-driven rather than inferred from one generic success flag.

Changed files:

- `literature_assistant/core/provider_capabilities.py`
  - Adds `ProviderCapabilityRecord`, `ProviderCapabilityStore`, endpoint/model
    fingerprinting, runtime-state JSON persistence, and
    `ensure_tool_call_capability()`.
  - Stores host, provider, model, status, ordinary-chat status,
    forced-tool-choice status, last probe time, failure class, and masked error.
- `literature_assistant/core/routers/chat_router.py`
  - Before MCP/local literature tool dispatch, requires a stored
    `tool_call_ok` capability record for the resolved provider/base/model.
  - If not proven, returns a successful chat response with empty answer and
    `mcp_run.diagnostics.stop_reason=provider_tool_probe_failed`, without
    calling the provider or pretending prompt-only chat is tool success.
- `literature_assistant/core/mcp_runtime/tool_use_runner.py`
  - Adds `failed_tool_use_run_result()` so route-level gates can reuse the same
    diagnostics envelope as runner failures.
- Ignored local tests:
  - `tests/test_api_chat_local_literature_tool_use.py`
    - Existing fake-provider happy paths now explicitly seed a temporary
      `tool_call_ok` capability record.
    - New negative test proves unproven provider capability blocks local tool
      dispatch and does not call the fake provider.

Generated/runtime output:

- `workspace_artifacts/runtime_state/provider-capabilities.json` was created
  during an early unisolated test run with a fake `chat.example` record. It is
  ignored runtime state and was not deleted in this slice. Tests now use
  temporary per-test capability stores.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py -q`
  passed: 8 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_mcp_phase2_tool_loop.py tests\test_provider_probe.py -q`
  passed: 82 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\mcp_runtime literature_assistant\core\provider_capabilities.py literature_assistant\core\provider_probe.py literature_assistant\core\routers\chat_router.py literature_assistant\core\routers\chat_mcp_integration.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py tests\test_provider_probe.py`
  passed.
- `git diff --check -- literature_assistant\core\mcp_runtime\tool_use_runner.py literature_assistant\core\provider_capabilities.py literature_assistant\core\routers\chat_router.py literature_assistant\core\routers\chat_mcp_integration.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py tests\test_provider_probe.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed.

Skipped / not claimed:

- The settings/model-config UI and endpoint do not yet persist
  `probe_openai_tool_calling_capability()` results into the capability store.
- Auth failure and model-missing probe outcomes are still covered at the probe
  layer only indirectly; the capability-store mapping slice remains.
- Full backend test suite, frontend build, desktop pywebview smoke, and real
  provider smoke were not run.
- No commit/stage/push was performed.

Residual risk:

- Until a probe endpoint writes capability records, existing real users must
  explicitly run the future probe path before MCP/local tool dispatch will be
  enabled for a provider/model.
- The dispatch gate currently treats missing capability as a 200 response with
  failed MCP diagnostics and empty answer. Frontend rendering of that state is
  deferred to later typed event/UI slices.

## Implementation Record, 2026-06-19 Phase 2b

Scope:

- Persist tool-call capability probe outcomes into the provider capability
  store through a settings/model-config API surface.

Rollback:

- `20260619-231920-phase2b-provider-probe-persistence`

Changed files:

- `literature_assistant/core/routers/model_config_router.py`
  - Adds `POST /api/chat/tool-capability/test`.
  - Runs `probe_openai_tool_calling_capability()` off the event loop with
    `asyncio.to_thread`.
  - Maps probe outcomes into `ProviderCapabilityStore` statuses:
    `tool_call_ok`, `probe_failed`, and `auth_required`.
  - Returns a public `ToolCapabilityProbeResult` with no raw credential or full
    URL exposure.
- Ignored local tests:
  - `tests/test_api_probe_semantics.py`
    - Adds fake-probe tests for persisted `tool_call_ok`,
      tools-swallowed `probe_failed`, and 401 `auth_required`.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_probe_semantics.py -q`
  passed: 10 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py tests\test_provider_probe.py tests\test_mcp_phase2_tool_loop.py -q`
  passed: 90 tests.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py tests\test_api_probe_semantics.py tests\test_provider_probe.py tests\test_mcp_phase2_tool_loop.py -q`
  passed earlier in the same slice: 100 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\mcp_runtime literature_assistant\core\provider_capabilities.py literature_assistant\core\provider_probe.py literature_assistant\core\routers\chat_router.py literature_assistant\core\routers\chat_mcp_integration.py literature_assistant\core\routers\model_config_router.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py tests\test_provider_probe.py tests\test_api_probe_semantics.py`
  passed.
- `git diff --check -- ...` passed before the final `asyncio.to_thread`
  refinement and should be rerun before handoff or the next code edit.

Skipped / not claimed:

- No frontend Settings button was wired to the new endpoint in this slice.
- No real provider smoke was run; fake-provider and fake-probe tests are the
  evidence here.
- Unsupported-protocol persistence remains a future small case if non-OpenAI
  tool-capability probes are added.
- No commit/stage/push was performed.

### Phase 2 Stop Audit, 2026-06-19

Active queue:

- `docs/plans/scholar-ai-reference-derived-code-plan-2026-06-19.md`, Phase 2.

Rollback:

- `20260619-232936-phase2-stop-audit-status-gates`

Done:

- Provider capability dispatch now fails closed unless the stored provider/model
  endpoint record has `status=tool_call_ok` and `forced_tool_choice_ok=true`.
- `/api/chat/tool-capability/test` persists forced-tool probe outcomes as
  `tool_call_ok`, `probe_failed`, or `auth_required`.
- Focused stop-audit coverage now proves that already persisted
  `probe_failed`, `auth_required`, and `unsupported` statuses all return
  `mcp_run.diagnostics.stop_reason=provider_tool_probe_failed` before any
  provider call is made.
- Missing capability state is still covered separately and also does not call
  the provider.

Mature / official references rechecked:

- OpenAI function calling documentation: tool calls and `tool_choice` are
  structured protocol features, so ordinary chat success is not enough.
- Vercel AI SDK tool-calling documentation: provider/tool loops are explicit
  multi-step protocol paths with stop conditions.
- MCP schema: tool results are structured content records; provider-facing
  transcript projection should not be the source of truth.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py::test_chat_ask_local_literature_tool_loop_blocks_failed_probe_statuses -q`
  passed: 1 test.
- `.\.venv-1\Scripts\python.exe -m pytest tests\test_api_chat_local_literature_tool_use.py tests\test_api_probe_semantics.py tests\test_provider_probe.py tests\test_mcp_phase2_tool_loop.py -q`
  passed: 101 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\mcp_runtime literature_assistant\core\provider_capabilities.py literature_assistant\core\provider_probe.py literature_assistant\core\routers\chat_router.py literature_assistant\core\routers\chat_mcp_integration.py literature_assistant\core\routers\model_config_router.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py tests\test_provider_probe.py tests\test_api_probe_semantics.py`
  passed.
- `git diff --check -- literature_assistant\core\mcp_runtime\tool_use_runner.py literature_assistant\core\provider_capabilities.py literature_assistant\core\routers\chat_router.py literature_assistant\core\routers\chat_mcp_integration.py literature_assistant\core\routers\model_config_router.py tests\test_mcp_phase2_tool_loop.py tests\test_api_chat_local_literature_tool_use.py tests\test_provider_probe.py tests\test_api_probe_semantics.py docs\plans\scholar-ai-reference-derived-code-plan-2026-06-19.md docs\plans\longrun-goal-state-2026-06-19.json`
  passed before this record update.

Deferred to later authorized slices:

- Frontend Settings has not yet been wired to call the new tool-capability
  endpoint. This is UI projection work, not a central Phase 2 backend gate.
- Real-provider smoke remains skipped; deterministic fake-probe coverage is
  the evidence for this local slice.
- Non-OpenAI tool-capability protocols remain future work.

Authorized local work remaining:

- Phase 3 total provider-bound context budget and payload accounting is now the
  next central local slice.

## Verification Ladder

For each slice:

1. Create rollback checkpoint.
2. Re-check official/mature references for the exact changed surface.
3. Inspect current dirty diffs for target files.
4. Add or update characterization tests before broad refactors.
5. Run focused unit/API tests.
6. Run compile/typecheck/build for touched stack.
7. Run desktop pywebview smoke only for UI/runtime acceptance.
8. Update the active plan and goal-state record with changed files, tests,
   residual risk, and next slice.

Baseline commands:

```powershell
.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant agent_mcp_server tests\conftest.py
.\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests -q
cd frontend
npm run build
npm run test -- --run
```

Use narrower commands first when a slice touches fewer files.

## Requirement-To-Plan Audit

| Requirement | Evidence in this plan | Status |
|---|---|---|
| Use completed `第一次补充参考` learning. | Source records include `supplemental-reference-*`; comparison uses Vercel AI SDK, LiteLLM, LangGraph, Cline, Goose, OpenHands, MCP gateways, and filesystem references. | Covered. |
| Do not repeat learning when unnecessary. | This plan cites existing learning records and records the closure boundary instead of rereading `ai-main`. | Covered. |
| Use `github_mcp_agent_research_20260619/repos`. | Source records include `github-reference-*`; plan uses MCP SDK, FastMCP, OpenAI Agents, Pydantic AI, mcp-agent, mcp-use, and AgentControlPlane lessons. | Covered. |
| Use `文章写作过程`. | Writing workflow phase uses scipilot, PaperSpine, chinese-thesis-workbench, and ChineseResearchLaTeX lessons. | Covered. |
| Use `文献检索`. | Retrieval/evidence phase uses paperscraper, ChatPaper, gpt_academic, and Hugo academic bundle lessons. | Covered. |
| Compare against all Scholar AI function areas, not only MCP. | Full Function Comparison covers product identity, MCP, provider, chat, materials, retrieval, PDF, writing, wiki/graph, runtime, skills, settings, evaluation, frontend, audit. | Covered. |
| Rank by high ROI, missing-needed, then later optimization. | Priority Order has three sections in that order. | Covered. |
| Produce code plan that may refactor/optimize. | Code Plan phases define target files, implementation direction, verification, and ordering. | Covered as planning, not implementation. |
| Avoid stale download requests. | Source closure records that most older recommended downloads were later covered by `第一次补充参考`; remaining gaps are optional and exact. | Covered. |
| Preserve implementation boundary. | Optimization audit and current status state that dirty working-tree code is unverified until Phase 0 and focused tests. | Covered. |

## Non-Goals For This Document

- Do not claim product-code implementation is complete.
- Do not stage, commit, push, tag, release, publish, or delete downloaded
  references.
- Do not ask for more downloads while this plan can proceed from existing
  records.
- Do not restart standalone installer/package direction.
- Do not rename `literature_assistant/` internal package paths.

## Next Authorized Local Action

Evidence-hardening follow-up after the 2026-06-20 verification audit:

- Highest priority: make the core deterministic/fake-provider verification
  evidence auditable without unignoring all `tests/` or `workspace_artifacts/`.
- Completion-boundary priority: keep Phase 0-9 as implementation slices
  completed under local focused verification, not as full-suite, desktop,
  real-provider, release, or public-source completion.
- Runtime-state priority: clean only the targeted stale fake provider
  capability record; do not run destructive `scripts/clean_test_data.ps1`.

Final Requirement-To-Evidence Audit, 2026-06-20:

- Rollback and worktree discipline:
  - Each implementation slice recorded a rollback checkpoint.
  - `git status --short --branch` was rerun before later phases and before this
    final audit.
  - The broad dirty worktree remains intentionally unstaged; unrelated or
    earlier-slice dirty files were not reverted.
- Mature references:
  - Provider/tool-loop slices used OpenAI, Anthropic, Vercel AI SDK, MCP, and
    capability-metadata references.
  - Source safety used Python path, OWASP path traversal, and Windows reparse
    point references.
  - Retrieval/qrels used TREC, trec_eval, and BEIR references.
  - Writing/export/page-bundle slices used Pandoc, JATS, W3C Web Annotation,
    Hugo page bundles, RO-Crate, and Testing Library/UI-state references.
  - Final audit used requirements traceability and small-batch verification
    references.
- Phase evidence:
  - Phase 0 through Phase 4 are recorded complete in this plan and the
    goal-state JSON, with source safety and tool/provider/runtime tests.
  - Phase 5 is recorded complete for qrels visibility and deterministic
    natural-prompt evidence-backflow harness behavior.
  - Phase 6 is recorded complete for writing workflow-state persistence,
    runtime API wiring, `/api/writing/export` caller integration, and Phase 6
    stop audit.
  - Phase 7 is recorded complete for runtime workflow summary projection,
    Agent Workspace writing/export runtime job rendering, and Phase 7 stop
    audit.
  - Phase 8 is recorded complete for writing export bundle-manifest runtime
    artifacts, wiki export zip `manifest.json`, and Phase 8 stop audit.
  - Phase 9 is recorded complete for deterministic natural-prompt acceptance
    criteria and Phase 9 stop audit.
- Verification boundary:
  - Focused Python tests, frontend component test/build, compileall, JSON
    validation, and diff checks passed for the slices recorded above.
  - Full backend suite and full frontend suite were later run in the
    2026-06-20 residual-closure slice and passed.
  - Desktop pywebview smoke and real provider/API smoke were not run. They
    remain residual release/acceptance risks, not uncompleted local
    implementation within this plan.
- Completion boundary:
  - The active `scholar-ai-reference-derived-code-plan-2026-06-19.md` local
    implementation queue is complete through its authorized phases only inside
    the local deterministic/fake-provider verification boundary.
  - `completion_claim.full_product_code_goal` is downgraded to
    `implementation_slices_complete_verification_gated`; fake providers,
    partial smokes, ignored local tests, and focused deterministic tests do not
    prove product-level completion.
  - No commit, push, tag, release, destructive cleanup, credential change, or
    production/paid access was performed.
  - Future work such as full on-disk bundle materialization, graph export
    manifests, frontend bundle projection, desktop acceptance, and
    real-provider smokes requires a new active slice/plan or explicit
    reprioritization.

## Evidence-Hardening Follow-Up, 2026-06-20

Rollback:

- `20260620-125558-evidence-hardening-audit-response`

Mature / official references rechecked:

- Git `.gitignore` documentation: use path-explicit negation allowlists; do not
  broadly unignore runtime/private trees.
- pytest usage/discovery documentation: run focused test files directly and use
  `-p no:cacheprovider` to avoid cache writes.
- Vitest configuration documentation: keep frontend component coverage as
  ordinary `*.test.tsx` tests discoverable by Vitest.
- Testing Library async query documentation: multi-projection UI tests should
  use `findAllByText` or scoped queries where duplicate text is intentional.

Dirty-worktree ownership:

- In-scope product/code-plan work: the existing 23 visible modified/untracked
  files plus reviewed characterization tests tied to Phases 1/2/3/5/6/7/8/9.
- Generated/local-only: `frontend/dist/`,
  `workspace_artifacts/runtime_state/provider-capabilities.json`, and
  `workspace_artifacts/generated/output/run_live_api_chat_full_writing_chain_smoke.py`.
- Unrelated or unknown ownership: none edited in this follow-up slice.

Verification evidence classification:

- Safe public/auditable and path-allowlisted:
  `tests/test_mcp_phase2_tool_loop.py`,
  `tests/test_api_chat_local_literature_tool_use.py`,
  `tests/test_api_probe_semantics.py`,
  `tests/test_evidence_pack_build_contract.py`,
  `tests/test_runtime_router_contract.py`,
  `tests/test_writing_runtime_persistence.py`,
  `tests/test_writing_submission_export.py`,
  `frontend/src/components/chat/MessageRenderer.test.tsx`, and
  `frontend/src/pages/AgentWorkspace.test.tsx`.
- Already auditable before this follow-up:
  `agent_mcp_server/tests/test_source_tools.py`,
  `tests/test_wiki_export.py`, and `tests/test_wiki_permissions.py`.
- Local-only/runtime-sensitive:
  `tests/test_live_api_chat_full_writing_chain_smoke_harness.py`, because it
  imports a generated harness under `workspace_artifacts/`.
- Generated harness/runtime artifact:
  `workspace_artifacts/generated/output/run_live_api_chat_full_writing_chain_smoke.py`;
  it embeds this machine's workspace path and resolves runtime provider
  configuration, so it remains ignored.

Provider capability runtime-state audit:

- `workspace_artifacts/runtime_state/provider-capabilities.json` previously
  contained a fake `chat.example` / `tool-loop-model` / `tool_call_ok` record
  from an early unisolated test run.
- The default `ProviderCapabilityStore()` reads
  `runtime_state_path("provider-capabilities.json")`, and
  `chat_router` checks the store before local MCP/literature tool dispatch.
  Therefore the fake record could authorize dispatch only when the runtime
  request/config used the same provider, endpoint host, and model.
- The targeted runtime JSON was later cleaned to `{"records": {}}` without
  running `scripts/clean_test_data.ps1` and without deleting chat/evolution
  runtime stores.

Residual risks:

- The live-smoke harness evidence is now represented by a source-safe harness
  file, but real provider/API smoke itself remains unrun.
- Desktop pywebview smoke and real-provider/API smoke remain unrun.
- The `chat_router.py` private `_snapshot` diagnostic fragility was fixed later
  by the offered-tool-count accessor cleanup slice.

Verification:

- `git check-ignore -v -- <reviewed tests and harness paths>` confirmed the
  nine reviewed tests are allowlisted and the live-smoke harness/runtime
  artifact remains ignored.
- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider
  tests\test_mcp_phase2_tool_loop.py
  tests\test_api_chat_local_literature_tool_use.py
  tests\test_api_probe_semantics.py
  tests\test_evidence_pack_build_contract.py
  tests\test_runtime_router_contract.py
  tests\test_writing_runtime_persistence.py
  tests\test_writing_submission_export.py -q` passed: 113 tests.
- `npm run test -- --run src/components/chat/MessageRenderer.test.tsx
  src/pages/AgentWorkspace.test.tsx` passed: 2 files / 6 tests.
- `npm run build` passed.
- `git diff --check -- .gitignore <visible product files>` passed, and
  ignored plan docs were covered separately with `git diff --no-index --check`.
- Untracked reviewed-test whitespace check passed; Git reported CRLF-to-LF
  normalization warnings for `tests/test_runtime_router_contract.py` and
  `tests/test_writing_runtime_persistence.py`, with no whitespace errors.
- Ignored-doc whitespace check passed; Git reported a CRLF-to-LF normalization
  warning for `docs/plans/longrun-goal-state-2026-06-19.json`, with no
  whitespace errors.

## Delegated Audit-Follow-Up Merge, 2026-06-20

Scope:

- Merge two completed delegated worktree slices into the main worktree:
  P2 `structured_content` first-class tool-result envelope, and P3 provider
  payload / context-budget deterministic-stop cleanup.
- Do not merge whole worktree diffs; both delegated worktrees were based on the
  broad longrun dirty state, so only the line-level P2/P3 deltas were applied.

Rollback:

- `20260620-134242-merge-delegated-p2-p3-tool-result-slices`

Mature / official references rechecked:

- MCP `CallToolResult` schema for `content`, `structuredContent`, `isError`,
  and metadata separation.
- OpenAI function calling docs for provider-visible tool-response messages.
- Anthropic tool-use docs for Claude `tool_result` blocks.
- LangChain MCP adapters for preserving `structuredContent` as an application
  artifact separate from model-visible content.

Changed files:

- `literature_assistant/core/mcp_runtime/tool_result_formatter.py`
  - Adds redacted JSON-safe `ToolResultRecord.structured_content` and
    `structured_metadata`.
  - Filters provider/raw/token/secret-like metadata keys out of structured
    metadata projection.
  - Adds a provider payload helper so Claude/OpenAI/XML renderers use
    `llm_payload` or an explicit `provider_payload_empty` JSON placeholder,
    never audit `preview`.
- `literature_assistant/core/mcp_runtime/audit.py`
  - Excludes structured content/metadata from persistent MCP audit dumps.
- `literature_assistant/core/routers/chat_mcp_integration.py`
  - Adds bounded structured projections in `mcp_run.tool_calls[]`.
- `literature_assistant/core/mcp_runtime/tool_use_runner.py`
  - Stops deterministically when the provider asks for more tools after the
    one-time context-budget summary.
- `tests/test_mcp_phase2_tool_loop.py`
  - Adds characterization for structured preservation, audit omission, API
    diagnostic projection, no preview fallback, and one-summary budget stop.
- `docs/plans/longrun-goal-state-2026-06-19.json` and this plan/audit record
  - Updated rollback, references, verification, changed files, residual risk,
    and next actions.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider
  tests\test_mcp_phase2_tool_loop.py -q` passed: 59 tests.
- `$env:LITASSIST_API_CAPABILITY_AUTH='0'; .\.venv-1\Scripts\python.exe -m
  pytest -p no:cacheprovider tests\test_api_chat_local_literature_tool_use.py
  -q` passed: 9 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q
  literature_assistant\core\mcp_runtime
  literature_assistant\core\routers\chat_mcp_integration.py
  tests\test_mcp_phase2_tool_loop.py` passed.
- `git diff --check --` over delegated merge touched files passed.

Residual risks:

- Full backend/frontend suites were not run in this delegated merge slice
  itself; later residual-closure evidence supersedes that full-suite gap.
- Desktop pywebview smoke and real provider/API smoke remain unrun.

## Offered-Tool-Count Accessor Cleanup, 2026-06-20

Scope:

- Close the remaining Claude audit implementation fragility where
  `chat_router.py` computed `offered_tool_count` by reading
  `_provider_runner._snapshot`.

Rollback:

- `20260620-135327-chat-router-offered-tool-count-accessor`

Mature / official reference:

- Python PEP 8 public/internal interface guidance: module/class users should
  depend on public attributes or methods rather than underscore-private
  implementation details.

Changed files:

- `literature_assistant/core/mcp_runtime/tool_use_runner.py`
  - Adds public `offered_tool_count` property.
- `literature_assistant/core/routers/local_literature_tool_bridge.py`
  - Forwards `offered_tool_count` from the wrapped provider runner.
- `literature_assistant/core/routers/chat_router.py`
  - Uses the public count for provider-capability fail-closed diagnostics.
- `tests/test_mcp_phase2_tool_loop.py`
  - Adds characterization that the runner exposes offered tool count without
    private snapshot access.

Verification:

- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider
  tests\test_mcp_phase2_tool_loop.py -q` passed: 60 tests.
- `$env:LITASSIST_API_CAPABILITY_AUTH='0'; .\.venv-1\Scripts\python.exe -m
  pytest -p no:cacheprovider tests\test_api_chat_local_literature_tool_use.py
  -q` passed: 9 tests.
- `.\.venv-1\Scripts\python.exe -m compileall -q
  literature_assistant\core\mcp_runtime\tool_use_runner.py
  literature_assistant\core\routers\local_literature_tool_bridge.py
  literature_assistant\core\routers\chat_router.py
  tests\test_mcp_phase2_tool_loop.py` passed.

Residual risks:

- Full backend/frontend suites and provider-capability cleanup were completed
  later in the residual-closure slice.
- Desktop pywebview smoke and real provider/API smoke remain unrun.

## Residual-Closure Verification, 2026-06-20

Scope:

- Close safe structural and verification residuals from the Claude audit:
  source-visible evidence records/tests, stale provider capability runtime
  state, full backend suite, and full frontend suite.
- Keep desktop pywebview and real provider/API smokes out of scope because
  they require explicit environment/credential prioritization.

Rollback:

- `20260620-141652-audit-structural-verification-fixes`
- `20260620-143050-full-suite-failure-triage-fixes`
- `20260620-144220-audit-residual-fullsuite-fix-continuation`
- `20260620-145246-fullsuite-eight-failure-targeted-fix`
- `20260620-151541-record-fullsuite-audit-residual-fixes`
- `20260620-151808-frontend-fullsuite-dimensiongraph-fix`

Mature / official references rechecked:

- Git `.gitignore` documentation for path-explicit negation allowlists.
- pytest usage/monkeypatch documentation for focused/full suite execution and
  isolated env/runtime-state tests.
- Vitest configuration/CLI documentation for focused and full frontend suites.
- Testing Library ByRole/accessibility guidance for frontend control tests.
- OWASP SSRF guidance for DNS/IP validation before provider endpoint probes.

Changed files:

- `.gitignore`
  - Path-allowlists the core plan/audit/goal-state records, longrun prompt,
    selected backend/frontend tests, source-safe live harness, and selected
    `workspace_tests` fixtures/manifests while keeping `workspace_artifacts/`
    ignored.
- `workspace_artifacts/runtime_state/provider-capabilities.json`
  - Local runtime state cleaned to `{"records": {}}`.
- `literature_assistant/core/routers/credentials_router.py`
  - Restores DNS/IP validation before credential-bearing endpoint probes.
- `literature_assistant/core/discussion_task_store.py`
  - Allows tests to reset the task store against a temporary persistence path.
- `literature_assistant/core/reranker_client.py`
  - Preserves runtime override precedence and isolates dotenv-disabled defaults.
- `literature_assistant/core/services/abstract_extractor.py`
  - Handles spaced headings, fallback extraction before keywords, stop-heading
    trimming, metadata trimming, and max-length validation.
- `literature_assistant/core/services/smart_filter_engine.py`
  - Reuses the shared abstract extractor through `extract_abstract()`.
- `literature_assistant/core/routers/chat_router.py`
  - Skips chat telemetry for internal analysis-chain LLM subcalls.
- `frontend/src/components/graph/DimensionGraphViewer.tsx`
  - Restores graph edge interaction controls and projections for
    evidence-weight, route filtering, node hover, and edge hover.
- `frontend/src/pages/Jobs.test.tsx`
  - Asserts the linter task endpoint path independent of configured API base.
- `tests/live_api_chat_full_writing_chain_smoke.py`
  - Adds a source-safe live writing-chain smoke harness that computes `ROOT`
    from the tests directory.
- Targeted test fixtures under `tests/` and `workspace_tests/`
  - Isolate runtime state, update stale contracts, and make full-suite
    characterization evidence reproducible.

Verification:

- Provider capability runtime JSON check: `{"records": {}}`.
- `git check-ignore -v` confirmed selected docs/plans records, longrun prompt,
  tests, source-safe harness, and workspace_tests fixtures are allowlisted while
  `workspace_artifacts/runtime_state/provider-capabilities.json` remains
  ignored.
- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider tests --collect-only -q`
  passed: `4228 tests collected`.
- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider tests -q`
  passed: `4175 passed, 52 skipped, 1 xfailed in 338.16s`.
- `npm run test -- --run src/components/graph/DimensionGraphViewer.test.tsx`
  passed: 11 tests.
- `npm run test -- --run src/pages/Jobs.test.tsx` passed: 4 tests.
- `npm run test -- --run` passed: 130 files / 804 tests.
- `npm run build` passed after the frontend fixes.

Residual risks:

- Desktop pywebview smoke was later run in a delegated acceptance thread and
  initially reached `blocked_clean_exit`: startup, native `文献助手` window
  visibility, non-browser verification, selected process exit, no same-title
  window, and no selected-port listener passed, but close emitted a
  pythonnet/.NET exception and exit code `-532462766`. The parent main
  worktree then reran the same source desktop smoke four times; all four reruns
  opened the native window, closed with `WM_CLOSE`, exited with code `0`, left
  no same-title window, and produced empty stderr. Current gate status:
  `passed_after_main_rerun` with one recorded intermittent close-path flake.
- Real provider/API smoke has not been run.
- The worktree remains intentionally unstaged and broadly dirty; no commit,
  push, tag, release, destructive cleanup, restore, credential change,
  production access, or paid external access was performed.

## Delegated Desktop And Source-Boundary Follow-Up, 2026-06-20

Scope:

- Merge records from two worktree follow-up threads after residual closure.
- Do not change product code, stage, commit, push, tag, release, restore, run
  real provider/API smoke, or run destructive cleanup.

Rollback:

- Main-worktree merge checkpoint:
  `20260620-191720-merge-delegated-desktop-source-readiness-records`
- Desktop-smoke delegated checkpoint:
  `20260620-191022-desktop-pywebview-smoke-20260620`
- Source-boundary delegated checkpoint:
  `20260620-191234-source-boundary-staging-readiness-20260620`

Mature / official references rechecked:

- pywebview usage/API documentation for `webview.start()`,
  `create_window()`, and `window.destroy()` behavior.
- Microsoft Win32 `EnumWindows`, `GetWindowTextW`, and `IsWindowVisible`
  documentation for native-window title/visibility evidence.
- Git `gitignore` and `git add` documentation for path-explicit allowlists and
  explicit path staging.
- GitHub source-archive/release documentation for the source tree as the public
  archive boundary.
- OWASP Secrets Management and GitHub secret scanning guidance for
  pre-publication scrub expectations.

Changed records:

- `docs/plans/scholar-ai-desktop-pywebview-smoke-2026-06-20.md`
  - Imported the delegated desktop smoke record.
- `docs/plans/scholar-ai-source-boundary-staging-readiness-2026-06-20.md`
  - Imported the delegated source-boundary/staging-readiness audit.
- `.gitignore`
  - Adds path-explicit allowlists for the two new records so they remain
    review-visible without broadly unignoring `docs/plans/`.
- This plan, the verification audit, and the goal-state JSON
  - Record the delegated outcomes and updated residual gates.

Desktop smoke result:

- Source command was run from the source project root because the delegated
  worktree did not contain `.venv-1`.
- Native top-level window titled `文献助手` appeared, was visible, and was
  verified through Win32 window enumeration rather than a browser tab.
- `WM_CLOSE` was posted; the selected launcher process exited; no same-title
  top-level window remained; and the selected backend port had no listener
  after close.
- Delegated first-run gate judgment was `blocked_clean_exit` because stderr
  contained a pythonnet/.NET exception and the launcher exit code was
  `-532462766`.
- Parent clean-exit diagnosis reran `start_desktop.py` once directly and three
  more times in a loop; all four reruns opened `文献助手`, closed through
  `WM_CLOSE`, exited with code `0`, left no same-title window, and produced
  empty stderr.
- Current desktop gate judgment is `passed_after_main_rerun`, with the
  delegated first-run exception retained as an intermittent close-path flake
  risk.

Source-boundary result:

- Product code, generated API contracts, PyInstaller spec, selected
  deterministic tests, selected frontend tests, source-safe live harness, and
  selected `workspace_tests` fixtures were classified as explicit staging
  candidates after final scrub.
- `docs/plans/*` evidence, longrun runbook/prompt, and internal agent records
  remain local-only or require an explicit publishing/scrub decision.
- `workspace_artifacts/`, `.env*`, credential/runtime stores, DB/log/profile
  output, root agent instruction files, `github/`, `workspace_references/`, and
  `frontend/dist/` remain forbidden for staging.

Verification:

- `git diff --check` passed for both delegated records in their worktrees.
- The source-boundary thread recorded check-ignore, scrub grep, JSON/JSONL
  validation, candidate diff whitespace checks, and
  `git ls-files -ci --exclude-standard` = empty.

Residual risks:

- Desktop startup/window visibility and clean shutdown passed on four
  main-worktree reruns; the delegated first-run pythonnet/.NET exception remains
  an intermittent close-path flake risk.
- Real provider/API smoke remains unrun and credential/network/cost-gated.
- No staging, commit, push, tag, release, restore, destructive cleanup,
  credential change, production access, or paid external access was performed.

## Delegated Provider Smoke And Pre-Stage Dry-Run, 2026-06-20

Scope:

- Merge two additional worktree verification records.
- Run a low-budget real provider/API smoke through existing runtime config.
- Validate the source-boundary explicit staging plan without executing
  `git add`, commit, push, tag, release, restore, or destructive cleanup.

Rollback:

- Main-worktree merge checkpoint:
  `20260620-194911-merge-provider-prestage-records-20260620`
- Real-provider delegated checkpoint:
  `20260620-193948-real-provider-api-smoke-20260620`
- Pre-stage dry-run delegated checkpoint:
  `20260620-193944-pre-stage-dry-run-20260620`

Mature / official references rechecked:

- OpenAI function/tool-calling documentation and API authentication
  documentation for structured tool calls and secret handling.
- Project `.github/skills/env-test-discipline/SKILL.md` for dynamic `.env`
  catalog resolution, masked probes, and low-budget provider testing.
- Git `gitignore`, Git `git add`, GitHub release/source-archive, GitHub secret
  scanning, and OWASP Secrets Management guidance for source-boundary and
  pre-stage checks.
- Vitest CLI and Vite production build documentation for parent source-root
  frontend verification after the delegated dry-run worktree lacked
  `frontend/node_modules`.

Changed records:

- `docs/plans/scholar-ai-real-provider-api-smoke-2026-06-20.md`
  - Imported the delegated real provider/API smoke record.
- `docs/plans/scholar-ai-pre-stage-dry-run-2026-06-20.md`
  - Imported the delegated pre-stage dry-run verification report.
- `.gitignore`
  - Adds path-explicit allowlists for the two new records.
- This plan, the verification audit, and the goal-state JSON
  - Record the updated provider and pre-stage gates.
- `docs/plans/scholar-ai-pre-stage-dry-run-2026-06-20.md`
  - Parent thread appended source-root frontend test/build verification.

Real provider/API smoke result:

- Actual execution used the source project root because the delegated worktree
  lacked `.venv-1`.
- Existing runtime configuration resolved generation/chat provider `hhl`,
  model `gpt-5.5`, host `free.hanhanapi.top`, and masked key `sk-k...VoL6`.
- External API calls used: 3.
- Probe path: existing OpenAI-compatible provider capability probe
  (`GET /models`, ordinary low-token chat, forced `tool_choice` function-call
  probe).
- Verdict: `passed_provider_tool_capability_probe`; `/models`, ordinary chat,
  and native forced tool call all passed, with `tool_call_ok=true` and duration
  `7490ms`.
- Runtime output remains under
  `workspace_artifacts/generated/output/real_provider_api_smoke/` and must not
  be staged.

Pre-stage dry-run result:

- 53 explicit candidate paths existed.
- Candidate `git diff --check` passed.
- `git ls-files -ci --exclude-standard` returned empty output.
- JSON/JSONL fixtures parsed successfully.
- High-risk secret regex found no real secret; hits were classified as fake
  fixtures, redaction tests, field names, or safety code paths.
- Forbidden paths such as `.env`, `workspace_artifacts/runtime_state/provider-capabilities.json`,
  `AGENTS.md`, and `AI_WORKSPACE_GUIDE.md` remain ignored.
- Backend focused deterministic suite passed with
  `134 passed, 15 warnings`.
- Frontend focused tests could not run in the dry-run worktree because it lacked
  `frontend/node_modules`; parent/staging environment should rerun frontend
  tests/build before commit.

Parent source-root frontend closure:

- `npm run test -- --run` from `frontend/` passed:
  `130 passed` test files and `804 passed` tests.
- `npm run build` from `frontend/` passed TypeScript and Vite production build.
- The Vitest run retained the known non-fatal jsdom `AggregateError` stderr in
  `PdfReaderShell.test.tsx`; exit code was still 0 and all tests passed.
- `frontend/dist/` was refreshed by build output and remains ignored/not a
  staging candidate.

Updated residual risks:

- Real provider tool capability is now proved for the configured
  OpenAI-compatible endpoint, but natural-prompt full writing-chain/tool-content
  backflow remains unverified.
- Explicit staging is ready as a dry-run, but no staging/commit has been
  executed.
- Frontend tests/build have now been rerun in the source dependency-complete
  environment; rerun again only if frontend files change before commit.

## Seventh-Review Gate Closure, 2026-06-20

Scope:

- Address the seventh-round adversarial review findings without staging,
  committing, pushing, tagging, releasing, restoring, or destructive cleanup.
- Fix/verify the desktop pywebview pythonnet close-path risk.
- Attempt a stronger real-provider natural-prompt writing-chain validation and
  record the exact blocker if it does not pass.
- Verify the `63b2` detached-worktree staging consistency concern before any
  staging decision.

Rollback:

- `20260620-205506-seventh-review-gate-closure-20260620`

Mature / official references rechecked:

- pywebview API docs and local pywebview 6.2.1 source for event threading and
  `webview.start(func=...)`.
- Python import system docs for direct-script `sys.path` shadowing.
- Git worktree docs for detached/missing worktree boundaries.
- Project `.github/skills/env-test-discipline/SKILL.md` for same-runtime,
  masked provider probes.

Changed files:

- `start_desktop.py`
  - Moved Windows titlebar native handling from async `shown` to synchronous
    `before_show`.
  - Moved reload hotkey installation to `webview.start(func=...)` after
    `window.events.loaded`.
- `literature_assistant/core/evolution/secret_scan.py`
  - Replaced shadowable `from wiki.evaluation` with package-qualified
    `from literature_assistant.core.wiki.evaluation`.
- `tests/live_api_chat_full_writing_chain_smoke.py`
  - Added `--probe-tool-capability` to run the product
    `/api/chat/tool-capability/test` gate in the same isolated runtime before
    writing-chain dispatch.
- `tests/test_live_api_chat_full_writing_chain_smoke_harness.py`
  - Added regressions for direct-script `tests/wiki` shadowing and local
    capability-header preflight behavior.
- This plan, the verification audit, desktop smoke record, and goal-state JSON
  - Record updated gate names and residual risks.

Verification:

- `.\.venv-1\Scripts\python.exe -m compileall -q start_desktop.py
  tests\live_api_chat_full_writing_chain_smoke.py` passed.
- `.\.venv-1\Scripts\python.exe -m pytest -p no:cacheprovider
  tests\test_live_api_chat_full_writing_chain_smoke_harness.py
  tests\test_api_probe_semantics.py
  tests\test_api_chat_local_literature_tool_use.py -q`
  passed: `26 passed`.
- Desktop close-path stress: 8/8 native `文献助手` close runs exited `0`,
  produced empty stderr, left no same-title window, and left no selected-port
  listener.
- Source-root product capability probe with local capability auth passed for
  `hhl` / `gpt-5.5` / `free.hanhanapi.top` with masked key `sk-k...VoL6`.
- Live writing-chain smoke with same-runtime `--probe-tool-capability` failed
  before the writing-chain request: `tool_capability_probe_failed`,
  `stage=models`, `error=timeout`.
- Current source-root candidate consistency fallback found 53/53 explicit
  candidate paths and wrote SHA-256 hashes under ignored runtime artifacts.

Updated gates:

- Desktop pywebview close-path:
  `passed_closepath_mitigated_stress_verified`.
- Real provider natural-prompt writing-chain:
  `attempted_blocked_by_same_runtime_tool_capability_probe_timeout`.
- `63b2` staging consistency:
  `blocked_old_63b2_missing_current_root_candidates_hashed`.

Residual risks:

- Full natural-prompt Scholar AI writing-chain/tool-content backflow remains
  unproved because the same-runtime provider capability preflight timed out.
- `63b2` no longer exists; future staging must use the current source root,
  explicit pathspecs, and a final scrub/diff pass.
- No staging/commit/push/tag/release was performed.
