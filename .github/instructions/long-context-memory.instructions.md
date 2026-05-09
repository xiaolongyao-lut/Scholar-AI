---
description: 'Maintain durable long-task context by capturing facts, decisions, open questions, and next actions with evidence anchors, so future sessions can resume accurately.'
applyTo: '**/*.{md,py,ts,tsx,js,jsx,json,yaml,yml}'
---

# Long Context Memory Instruction

## Purpose

在多轮开发和长链路调试中，减少上下文丢失，避免重复分析。

本指令要求在关键节点沉淀“可续接上下文”，并优先记录**证据驱动**信息。

## Applicability Gate

优先在以下场景启用：

- 任务包含多个子步骤，且跨 1 轮以上对话
- 涉及调试、测试、回归、重构、迁移
- 需要交接或下一轮继续

以下场景可跳过：

- 单次微小修改（1~2 行）
- 纯解释型问答且无需后续衔接
- 用户明确要求“只要简答结果”

## What to Capture

每个中大型任务尽量提炼以下四类信息：

1. **Facts（事实）**
   - 仅记录可验证信息：文件路径、函数名、错误信息、命令结果、配置值
2. **Decisions（决策）**
   - 记录采取的方案 + 选择理由 + 放弃方案（若有）
3. **Open Questions（未决）**
   - 缺失信息、待确认前提、潜在阻塞
4. **Next Actions（下一步）**
   - 最小可执行任务，便于下一轮直接接续

## Evidence Anchors

所有非显然结论应附证据锚点，优先使用：

- 文件路径（例如 `src/service/foo.py`）
- 测试文件与用例名
- 构建/测试输出中的关键行
- 已执行命令的结果摘要

不要写“猜测型历史”；不确定时使用 `[TODO]` 或 `[ASK USER]`。

## Compression & Format

为减少 token 占用，推荐使用紧凑结构：

- 一条结论尽量 1~2 行
- 使用固定字段名（Facts/Decisions/Open/Next）
- 避免冗长复述
- 默认总长度控制在 12 行以内（复杂任务可放宽至 18 行）

推荐片段：

`[scope] DECISION: ... | WHY: ... | EVIDENCE: ... | NEXT: ...`

## Trigger Points

在以下场景应主动生成/更新上下文摘要：

- 完成一个子任务（例如修复一个根因、合并一组变更）
- 连续进行了 3~5 次工具调用后
- 运行测试或验证后结果有变化
- 准备切换任务或结束当前回合前

## Conflict Handling

当新结论与旧结论冲突时：

1. 明确标记 `Conflict:`
2. 给出新证据锚点
3. 指出旧结论为何失效（或证据不足）
4. 将 Next 指向复核动作（如回归测试/二次验证）

## Guardrails

- 禁止记录 secrets（API key、token、密码、隐私）
- 决策必须包含理由，不能只写“已改完”
- 发现与历史结论冲突时，优先标记冲突并说明新证据

## Completion Requirement

在多步骤任务结束前，提供一段“可续接上下文”，至少包含：

- `Facts`
- `Decisions`
- `Open`
- `Next`

确保下一轮可以在最少额外上下文下继续工作。

推荐最小模板：

`Facts: ...`
`Decisions: ...`
`Open: ...`
`Next: ...`
