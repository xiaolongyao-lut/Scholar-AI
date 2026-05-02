# Modular Pipeline Script Guidance

## 核心回答规则（最高优先级）

1. 极致精简：接近三句话法，杜绝冗长背景和铺垫。
2. 提炼第一性原理：直接给结论、证据、下一步。
3. 用户时间极其宝贵，啰嗦信息会影响判断。超过3句的段落必须重写。

## 不中断规则（始终生效，非 Squad 专属）

**禁止习惯性分段。** 回答状态/问题后，若当前任务未闭合，必须立即继续执行，不得等待用户输入"继续"。

允许停止的条件（必须命中至少一条）：
1. 用户明确说 `stop`、`pause`、`idle`
2. 红线/硬阻塞需要用户独立授权
3. 当前切片完全闭合：artifact 已写、验证已跑或已显式跳过并附理由、下一步已选
4. 工具/环境失败且已报告最小安全恢复动作

以下不算完成：诊断解释、状态总结、原因分析。如果解释了暂停原因，必须在同一 turn 内恢复执行。

This file mirrors the repository's Copilot-wide instructions for Claude Code.

## Required Workspace Guide

Before editing, moving files, running tests, or giving commands, read `AI_WORKSPACE_GUIDE.md`.

The guide is the canonical map for the reorganized literature-assistant workspace:
active backend code lives under `literature_assistant/core/`, frontend code under
`frontend/`, generated/runtime files under `workspace_artifacts/`, evaluation
helpers under `workspace_tests/`, plans/specs under `docs/plans/`, experiments
under `workspace_references/`, and external RAG reference repositories under
read-only `github/`.

## Available Project Skills

Claude should prefer the project-local skills under `.claude/skills/` when a task matches a specialized workflow. Those skills were migrated from:

- `.github/skills/*`
- `.github/instructions/*.instructions.md`

Use the matching skill instead of re-deriving the same checklist or playbook in the main conversation.

## Repository-Wide Working Style

### 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them; don't pick silently.
- If a simpler approach exists, say so.
- If something is unclear, stop and ask.

### 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No flexibility or configurability that was not requested.
- No defensive error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

- Do not improve adjacent code, comments, or formatting unless requested.
- Do not refactor things that are not broken.
- Match existing style, even if you would do it differently.
- If you notice unrelated dead code, mention it; do not delete it.

When your changes create orphans:

- Remove imports, variables, and functions that your changes made unused.
- Do not remove pre-existing dead code unless asked.

Every changed line should trace directly to the user's request.

## Squad 模式与长跑模式 (Sprint 4)

### 0. Stop Gate（停止门禁）

The assistant must NOT end the turn just because it answered a status or interruption question.

It may stop only if one of the following is true:
1. The user explicitly says `stop`, `pause`, or `idle`
2. A red-line / hard-stop requires independent user authorization
3. The current slice is fully closed with: artifact written, verification run or explicitly bypassed with reason, and a concrete next action selected
4. The environment or tooling failed and the assistant has already reported the smallest safe recovery action

Otherwise, after answering the user's question, the assistant must immediately continue the current next_action in the same turn.

A diagnostic explanation is not completion. A status summary is not completion. A cause analysis is not completion.

If the assistant explains why work paused, it must resume execution in the same turn unless a true stop gate condition is met.

### 1. 激活 Squad
当用户输入 `/squad` 或提到”开启团队模式”时：
- **强制参考目录**：立即加载 `.claude_squad/` 下的配置、Agent 席位与私有技能。
- **Agent 本身属性**：转变为 **Squad 4.7 核心专家团** 视角。全员采用 Opus 4.7 级推理深度。
- **决策依据**：必须参考 `C:\Users\xiao\Desktop\tools\用户画像_v4_AI协作治理型工程主理人.md`（canonical v4，含 §5 权限模型、§8 红线、§11 多 agent / Squad 协议、§11.5 事故索引）进行所有工业化决策。v1（`用户画像_AI协作工程画像.md`）仅供原句证据回溯；v2（`用户画像_AI编码参考_v2.md`）为本仓库操作手册；v3（`用户画像_v3.md`）已 archival。

### 2. 长跑规范 (Long-Running Logic)
- **多终端并发**：支持在多个终端同时运行 `/squad` 实例。所有实例共享 `.modular/sessions/` 的分布式状态与 `Semantic Cache`。
- **断点恢复 (Resume)**：新对话开启时，检查 `RAG_SESSION_ID` 环境变量，自动执行历史 Turn 回填。
- **写保护**：禁止修改 `.copilot/` 原始目录，所有 Claude 专属改动仅限 `.claude_squad/`。

### 3. 工程硬化准则 (Spec §4.7)
- **拒绝静默失败**：所有核心链路（持久化、API 调用）必须经过 `citation_auditor` 与 `model_call_gateway`。
- **原子化写入**：缓存文件写入必须使用 `.tmp` + `replace` 模式。

### 4. Long-run hard rules（强制）

进入长跑 / `/squad` / Morpheus 自决策模式时，**必读** `.claude_squad/charter.md` §Long-run hard rules（HR1–HR6）。要点（关键词锚点供 grep）：

- **HR1 Requirement-pool write gate**：`requirement-pool.md` 唯一写入口是 `python .squad/tools/pool_append.py`。禁止 `Edit` / `Write` / heredoc / `Add-Content` 直写。非零退出 / `rc=49` = `hard stop` + diag dump 落 `.squad/audits/`。
- **HR2 Pool duplicate guard**：写新条目前先 grep 最近 50 个 H2 + inbox + orchestration-log + log + `squad task list`；重复即拒。
- **HR3 Dispatch pre-flight**：`squad task create` / `squad spawn` / fan-out / 派发 spec 前必须查目标产物是否已存在、同 lane 任务是否在飞。
- **HR4 Observation-loop breaker**：连续 2 轮无 artifact delta 的 observation-only，必须停，按三行 Facts/Stalled/Safe-next 收尾；禁止再写元观察。
- **HR5 Round authority**：禁止自填 `Round N`，用 `checkpoint <UTC>` 或 `checkpoint <uuid>`。
- **HR6 Evidence package**：长跑每次 exit 必落 Facts / Decisions / Open / Next（v4 §17 模板）到 `.squad/orchestration-log/` 或 `.squad/audits/`。

代码侧的实现锚点：`.squad/tools/pool_append.py`（含锁、原子 replace、SHA-256 last-50 dedup、G1 size-must-grow、G3 safe-floor 100KB、rc=49 diag dump）。配套测试：`test_pool_append_dup_noop.py`、`test_pool_append_n_writer_stress.py`。

## Squad Collaboration

This project uses squad for multi-agent collaboration. Run `squad help` for all commands and usage guide.

