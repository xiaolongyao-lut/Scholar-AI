# Copilot Global Instructions

These instructions are always-on for this repository.

## Karpathy-inspired coding guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them; don't pick silently.
- If a simpler approach exists, say so.
- If something is unclear, stop and ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No flexibility/configurability that wasn't requested.
- No defensive error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't improve adjacent code/comments/formatting unless requested.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it; don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

Test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" -> "Write tests for invalid inputs, then make them pass"
- "Fix the bug" -> "Write a test that reproduces it, then make it pass"
- "Refactor X" -> "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Squad Mode Parity Hardening

These rules mirror the Claude-side Squad hardening lessons for Copilot-facing work. Use them when the user invokes `/squad`, mentions Squad/team mode, asks for long-running unattended work, or asks Copilot to repair Squad behavior.

## Scholar AI Project Conventions

These conventions replace the deprecated pseudo prompt file `.github/prompts/prompts.md.deprecated`. Keep durable repository-wide rules here, not in non-`.prompt.md` prompt files.

Before editing, moving files, running tests, or giving user-facing commands, read `AI_WORKSPACE_GUIDE.md`. It is the canonical map for the reorganized literature-assistant workspace.

### Project Structure

- Backend ASGI entry: `literature_assistant.core.python_adapter_server:app`; routers live under `literature_assistant/core/routers/`.
- New backend code should prefer package-style imports such as `literature_assistant.core.<module>`; legacy flat imports remain supported by the local `.pth`/`sitecustomize.py` compatibility layer.
- Core backend implementation lives under `literature_assistant/core/`; do not assume old root-level Python scripts are active entrypoints.
- Frontend entry: `frontend/src/`; pages live under `frontend/src/pages/`; services live under `frontend/src/services/`.
- Data models live under `literature_assistant/core/models/` and use Pydantic v2.
- Runtime/generated output belongs under `workspace_artifacts/`; use `project_paths.py` helpers instead of hardcoded root `output/` paths.
- Project plans, specs, and execution plans belong under `docs/plans/`; do not create new active plans under `.kilo/plans/`, `.copilot-tracking/plans/`, or `docs/superpowers/specs/`.
- Evaluation scripts and migrated diagnostics live under `workspace_tests/`.
- Experiments and imported references live under `workspace_references/`.
- `github/` contains external RAG/reference repositories and is read-only by default.
- Writing resource persistence uses `WritingResourceStore` with frozen dataclass + SQLite and JSON fallback.
- Datetime code should use `datetime_utils.utc_now_iso_z()` instead of direct `datetime.now()` for persisted timestamps.
- The primary local Python environment is `.venv-1`.

### Implementation Discipline

- Read the target files before editing and preserve unrelated user or agent changes.
- Before nontrivial interface, security, workflow, config, permission, or architecture changes, create a rollback snapshot and compare against official or mature solutions.
- Use strict typing: Python type hints for public functions and TypeScript without `any`; use `unknown` plus type guards when the shape is not known.
- Validate external input at system boundaries. Keep internal helpers simple once the boundary contract is enforced.
- Diagnose bugs with file/line evidence and concrete root cause; do not guess.
- Comments should explain why, not narrate how.
- When updating frozen dataclass state, convert to a dict, update the copy, and rebuild the dataclass.
- Backend API changes must be reflected in frontend types/services and OpenAPI-generated aliases when applicable.

### Prohibited Patterns

- Do not use placeholder edits such as `// ... existing code ...`, `# omitted`, or TODO stubs for required logic.
- Do not hardcode API keys or secrets.
- Do not swallow exceptions with bare `pass`.
- Do not create speculative abstraction layers.

### API and Error Handling

- Backend errors should use the `ErrorResponse` envelope from `literature_assistant/core/models/common.py` where the route family already uses that convention.
- Use the `ErrorCode` enum for categorized errors.
- HTTP exceptions should flow through the global exception handler where possible.
- Frontend error UI should extract user-friendly text from `error.message` or `detail`.
- Route prefixes are domain-based, for example `/chat`, `/resources`, and `/pipeline`.
- List endpoints should use `page` and `page_size` when pagination is needed.
- New endpoint groups must be registered in `OPENAPI_TAGS`.
- LLM configuration is provided from frontend settings per request; backend code must not persist user secrets.

### ML / Research Changes

- For tensor or model-shape changes, verify dimensions with a small deterministic probe before full runs.
- For training logic, first overfit a tiny sample before scaling.
- Isolate preprocessing mutations with `.copy()` / `.clone()` where applicable.
- Prefer framework-native vectorized operations over Python loops.

### 1. Activation and Source Boundaries

- Treat `.github/agents/squad.agent.md` as the Copilot Squad coordinator contract.
- For Squad runtime startup, first resolve `TEAM_ROOT`, then read `.squad/identity/start-here.md` and follow its mandatory read order before routing, dispatch, catch-up, or long-run work. Then load `.squad/INDEX.md` when present, `.squad/team.md`, `.squad/routing.md`, `.squad/decisions.md`, `.squad/identity/now.md`, and task-relevant instructions/skills.
- Treat `CLAUDE.md` and `.claude_squad/` as reference/evidence when comparing Claude fixes, not as Copilot write targets.
- Do not modify `.claude/`, `.claude_squad/`, or raw `.copilot/` configuration for Copilot-specific fixes unless the user explicitly asks. Prefer `.github/` for Copilot customization and `.squad/decisions/inbox/` for shared team decisions.
- Resolve the canonical owner profile from `.squad/identity/start-here.md`, `.squad/identity/owner-profile-v4.md`, `.claude_squad/config.json`, or another explicit config reference before self-decision/dispatch; do not copy private profile content into committed files, logs, or downstream prompts.

### 2. Long-Running and Resume Safety

- Before long-running Squad work, load `.squad/identity/long-run-prompt.md`, then check for resume context: `RAG_SESSION_ID` when available, `.modular/sessions/`, `.squad/identity/now.md`, recent `.squad/log/`, and recent `.squad/orchestration-log/`.
- Assume multiple terminals may operate concurrently. Use drop-box writes (`.squad/decisions/inbox/*`) and append-only logs instead of direct ledger rewrites.
- Treat "running" without fresh heartbeat, progress, or output artifacts as ghost-running. Inspect owner PID, lock file, command line, and timestamps before cleanup or relaunch; never mark it healthy without evidence.
- In this repository most `.squad/` paths are git-ignored runtime/team state; only a small canonical governance whitelist is intended to be tracked. Use ignored `.squad/` files for local coordination, but mirror durable Copilot governance changes into tracked `.github/` files, tracked `.squad` governance files, or repository memory.

### 3. Autonomous Long-Run Guardrails

- Before starting or continuing a self-directed long task, produce a preflight envelope: objective, allowed scope, disallowed actions, time/cost budget, checkpoint cadence, stop conditions, expected artifacts, rollback path, and current evidence sources.
- Include a startup packet in the preflight: team root, current user, loaded owner-profile boundaries, active focus, routing/decision context, resume state, task-relevant env/capability rules, and loaded evidence sources. Capability checks may be redacted; never print or persist secret values.
- Continue automatically only inside that approved envelope. If the task drifts, lacks fresh evidence, exceeds budget, changes risk class, or needs a new authority decision, stop and report `Facts / Decision needed / Evidence / Safe next action`.
- Before declaring long-run work complete, performing final cleanup, killing terminals, or calling `task_complete`, apply the continuation gate: the active master plan under `docs/plans/active/` is the first truth source for whether the run is actually done. Slice-local todo lists or checklists may track substeps but cannot declare overall completion. If same-scope tasks remain `待执行` / `进行中` / `open` / `in-progress`, and no hard boundary or explicit user stop applies, keep going or stop with `Facts / Decision needed / Evidence / Safe next action`. Even when the active plan is clear, do not stop if the current slice's latest `Facts / Decisions / Open / Next` still contains an already-authorized safe next action. `provisional go`, `PASS WITH NOTES`, build success, or test success are never sufficient stop reasons by themselves. Autonomous completion also requires a self-decision floor: `task_complete` must carry `[SELF_DECISIONS:<n>]`, and the count must satisfy the current session minimum (default `2`, configurable via `SQUAD_MIN_SELF_DECISIONS`) unless the stop reason is a user/hard-boundary exemption.
- Default to **decision-bundling mode** for autonomous/project work: do not give the user a step-by-step execution plan by default. At the start, ask only the currently necessary high-impact decisions in one bundled prompt; if there are none, say so briefly and proceed. During execution, self-decide within the envelope instead of repeatedly interrupting for small choices. Collect blockers, authorization gaps, or things the agent cannot do and ask once in a consolidated batch at the end of the run or at a hard stop.
- Structural blockers or governance gaps that materially extend the current run must be self-decided and repaired first inside the envelope. Do not stop to ask whether to fix them unless the repair crosses an existing human-approval hard boundary.
- Human approval is required before destructive or high-impact actions: editing `.env` or secrets, changing external/paid-service budgets, killing/relaunching non-owned processes, modifying corpus/goldset scope, changing tracked governance policy, or promoting an unverified result to a gate/pass decision.
- For unattended runs, require fresh checkpoints with artifact paths and timestamps. A run is not complete until its output artifacts, logs, exit status, and residual cleanup have been checked.
- Never let the same autonomous agent both create and final-approve a decision-grade result. Use an independent review pass or explicitly mark the result as provisional.
- Prevent self-feeding long-run loops: after two consecutive observation-only checkpoints with no code/test/data artifact, task transition, or eval delta, stop and report `Facts / Stalled evidence / Safe next action` instead of writing more meta-observations.

### 4. No Silent Failure

- Persistence, API calls, model calls, citation checks, and cleanup operations must either produce verifiable artifacts or surface a clear failure.
- When the codebase has `model_call_gateway` or `citation_auditor`, route core model/citation paths through them. If they are missing for a requested path, record the gap instead of bypassing it silently.
- Cleanup success must be evidence-backed: after cleanup, scan for stale locks, dead live-agent markers, and orphaned owned processes where practical.

### 5. Atomic Writes and Evidence

- Write cache/state/session artifacts with same-directory temp files plus atomic replace (`os.replace` in Python, `.tmp` + replace/move semantics in PowerShell/Rust). Use unique temp names for concurrent writers.
- Before consolidating or rewriting Squad canonical files, make a backup or use inbox/prepend-only patterns with clear rollback notes.
- Team-relevant Copilot decisions should be written to `.squad/decisions/inbox/copilot-{brief-slug}.md` with `Facts`, `Decision`, `Evidence`, and `Rollback` sections.
- For `.squad/identity/requirement-pool.md`, do not use direct edits, heredocs, or whole-file rewrites. Use `.squad/tools/pool_append.py` and treat any non-zero exit as a hard failure that must be diagnosed rather than bypassed.
- Before Copilot Squad dispatches duplicate-prone work, check task list/local artifacts first (`.squad/decisions/inbox/`, `.squad/orchestration-log/`, `.squad/log/`, and relevant `tools/squad/` files) and record evidence when suppressing a duplicate.

### 6. Self-Development Restart Notice

- If `.github/agents/squad.agent.md` changes, tell the user to restart the Squad/Copilot session so the new coordinator behavior is loaded.


## Squad 0.9.3-modular Decision Map (2026-04-27)

本节记录 2026-04-27 与 Squad `0.9.3-modular` 相关的关键决策映射。详细执行记录见 `docs/plans/kilo/2026-04-27-squad-official-capability-reuse.md` 第 15 节，以及 `.github/agents/squad.agent.md` 头部中文摘要。

- **D4=B Plan 自动路由**：协调者遇到多步任务 / 重构 / 跨文件改动 / 方案不明时，直接 `switch_agent('Plan')`，不再先询问用户；Plan 产出方案后再回到 Squad 派发执行。
- **D7=B 长跑执行**：当 Squad 运行在 Copilot Chat / VS Code 中时，长跑（>10 分钟、付费 eval、批量处理）默认优先在当前会话内继续推进，只要能够按 checkpoint 分段执行并持续留证。仅在需要 detached/background 持续运行、聊天面工具/会话限制阻塞执行、或用户明确要求时，才交接到 **Copilot CLI Sessions**；`tools/squad/squad.ps1` 已退役，仅保留 `.deprecated` 与 `tools/squad/README-DEPRECATED.md` 作为历史说明。
- **D8=B 结构性缺失优先自决**：发现结构性缺失 / 治理空洞 / 会明显拉长单次运行时长的阻塞项时，默认先自决策修复并留证，不再先问用户“愿不愿意继续修”；只有触及人工审批硬边界时才暂停请示。
- **D9=B 全项目推进预先决策**：进入全项目推进前，先由 AI 自决策把计划细化到可回填状态（决策 ID、任务 ID、状态、证据路径、回滚方式、硬边界），再一次性向用户收口少数高影响预决策；用户确认后写入计划文件与 `.squad/decisions/inbox/`，后续执行按该预决策包推进，不再逐项重复询问。
- **D10=B 决策收口模式**：默认不要给用户一步步计划；只在执行开始前一次性询问“当前必须拍板”的少数高影响决策。执行过程中在已批准 envelope 内自决策推进，不为小决策反复打断；把 AI 出力不了的事项、授权缺口、外部阻塞统一收集到结束后一次性询问，除非触发人工审批硬边界。
- **D11=B 长跑收口闸门**：active master plan under `docs/plans/active/` 是整轮长跑完工的第一真源。局部 todo / 切片 checklist 只能跟踪阶段进度，不能替代总 plan。若同 scope 仍有 `待执行` / `进行中` / `open` / `in-progress` 的 `TASK-*`，且未触发硬边界或用户明确 `stop` / `idle`，则禁止 `task_complete` 与最终 terminal cleanup，必须继续推进下一项或以 `Facts / Decision needed / Evidence / Safe next action` 收口。即使 active plan 已清空，也必须继续检查当前切片最近一次 `Next` 是否还有已授权安全入口；若有，则自动进入下一轮，不得结束。合法 stop reason 仅限 `user-stop`、`approval-boundary`、`external-blocker`、`session-limit`、`cli-handoff`、`plan-clear-no-safe-next`，并且每次 `task_complete` 前都必须在 summary 中显式包含 `[STOP_REASON:<reason>]` 与 `[SELF_DECISIONS:<n>]`。其中自决策数量以本会话新增的唯一 `.squad/decisions/inbox/copilot-*.md` 文件数为准，默认最低门槛为 `2`；仅 `user-stop`、`approval-boundary`、`external-blocker`、`cli-handoff` 可豁免该门槛。
- **DD2 GitHub MCP 写权限**：GitHub MCP 的只读能力（如搜索代码、读取 issue / PR / commit）可自动使用；写操作（如 create / update / delete / push / merge / comment / request review）每次执行前都必须征求用户确认。长跑结束或关键里程碑达成时，提醒用户执行 git → GitHub 同步。Pylance MCP 可自动使用；GitKraken / WorkIQ 默认不用。
- **DD4 画像版本校验**：协调者启动时必须运行 `tools/squad/profile-version-check.ps1` 校验 `{{OWNER_PROFILE}}` 版本；不一致即 hard stop。
- **DD5 squad-doctor 启动自检**：每次进入 Squad 模式都要通过 `.github/prompts/squad-doctor.prompt.md` 完成 routing / agent / chatmodes / profile / HR1–HR6 / prompt-skill 链路检查。
- **DD6=B 通用模板化**：Squad 文本使用 `{{TEAM_ROOT}}`、`{{OWNER_PROFILE}}`、`{{POOL_APPEND_TOOL}}` 占位符，避免把本仓私有路径硬编码进可复用模板。
- **DE1 中文摘要层**：协调者保留中文摘要 + 英文骨架双层表达，关键约束以中文为先，英文作为原始结构对照。
- **DE3=B 子代理失败自动重试 1 次**：`runSubagent` 失败时自动重试 1 次；仍失败则停下并回报 `Facts / Decisions / Open / Next`。
- **DE4 编排记录强制留痕**：所有 fan-out 与长跑交接都必须写入 `.squad/orchestration-log/`。
- **T5 prompts / skills 拆分完成口径**：`.github/prompts/prompts.md` 必须保持下线状态；计划、启动包、CLI handoff 分别由 `.github/prompts/squad-plan.prompt.md`、`.github/skills/squad-startup-packet/SKILL.md`、`.github/skills/squad-cli-handoff/SKILL.md` 承载。
