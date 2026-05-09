---
description: "Structured long-running self-decision workflow. Phase 0: global project scan. Phase 1: preflight envelope (9 fields). Phase 2: 10-step execution round loop. Phase 3: exit protocol with evidence package. Derived from Copilot long-run-prompt.md."
---

# Autonomous Execution Workflow

> Structured self-decision flow. Every long task follows this sequence.
> Derived from Copilot `.squad/identity/long-run-prompt.md` + `.squad/identity/start-here.md`
> + capability-reuse §12 reading order, adapted for Claude Code.

## Phase 0: Global Scan (第一步，每次长任务必做)

**原则：先看"总装图"，再看"加载链路"，最后才看局部实现。**

1. **读项目说明** — `AI_WORKSPACE_GUIDE.md` + `CLAUDE.md`：项目是什么、怎么分层、规范是什么。
2. **读当前状态** — `docs/plans/active/*.md` master plan + `.claude_squad/identity/claude-now.md`：当前在哪一步、什么已完成、什么 blocked。
3. **读决策上下文** — `.claude_squad/memory/claude-DECISION_TRAIL.md` tail + `.claude_squad/memory/OPEN_THREADS.md`：最近决策、未闭合线程。
4. **读 git 状态** — `git status --short` + `git log --oneline -10`：工作区脏不脏、最近做了什么。

完成后才能进入 Phase 1。跳过 Phase 0 直接写代码 = 违规。

## Phase 1: Preflight Envelope (进入长跑前)

记录以下 9 项，写入 DECISION_TRAIL checkpoint：

| # | 字段 | 说明 |
|---|---|---|
| 1 | Objective | 本轮要完成什么 |
| 2 | Allowed scope | 可以动什么 |
| 3 | Disallowed actions | 不能动什么 |
| 4 | Time/cost budget | 时间/成本上限 |
| 5 | Checkpoint cadence | 多久写一次 checkpoint |
| 6 | Stop conditions | 什么情况下停 |
| 7 | Expected artifacts | 预期产出文件 |
| 8 | Rollback path | 回滚方式 |
| 9 | Evidence sources | 证据来源 |

## Phase 2: Execution Round Loop (每轮执行)

每轮按顺序执行，不得跳步：

1. **Reload state** — 重读 goal-drift、now.md、open threads、最新 decisions。
2. **Check resume** — 是否有断点恢复上下文？是否有 ghost-running？
3. **Read latest artifact** — 读最新 eval/产物。用 mtime + config 口径判断是否过期，不用叙述。
4. **Classify failures** — 失败项归层：data / chunk / retrieval / rerank / generation / eval / state / cache / governance。
5. **Duplicate preflight** — 添加需求或派发前，grep 最近 50 个 H2 + inbox + log + task list，重复即拒。
6. **Pick top item** — 用 Morpheus 式判断：`DO NOW` / `LATER` / `BLOCKED`。
7. **Execute** — 只执行 `DO NOW` 项。产出必须是可验证的：代码 diff、测试结果、数据产物、决策记录。
8. **Write checkpoint** — 用 `checkpoint <UTC>` 格式（HR5），不写 Round N。
9. **Self-audit** — 每 10 个自主动作执行一次 `.claude_squad/kernel/self-audit.md` 清单。
10. **Loop breaker (HR4)** — 连续 2 轮无 artifact delta → 停，写 Facts/Stalled/Safe-next。

## Phase 3: Exit Protocol (停止时)

每次退出必须：

1. **写证据包 (HR6)** — Facts / Decisions / Open / Next 写入 DECISION_TRAIL。
2. **检查 completion gate** — 四项全满足才算完成：
   - 主产物已落盘且下游可读
   - 状态/决策/文档已同步
   - Gate 已报告（命令、exit code、口径、指标）
   - 清理已检查（stale locks、ghost-running、orphan tmp）
3. **决策级结果标记 provisional** — 除非独立复核，否则标 provisional。

## Hard Stops (红线，任何模式下不可自决)

- 删除性操作：force push、branch delete、`rm -rf`
- 密钥/env 编辑、付费预算变更、外部账号变更
- corpus / goldset / qrels / 评测口径变更
- 编辑 `.copilot/`、`.github/agents/`、`.claude/`（除非用户明确要求）

## Reference

- Copilot source: `.squad/identity/long-run-prompt.md`
- Copilot source: `.squad/identity/start-here.md`
- Reading order: `docs/plans/kilo/2026-04-27-squad-official-capability-reuse.md` §12
- Kernel: `.claude_squad/kernel/self-audit.md`
- Charter: `.claude_squad/charter.md`
