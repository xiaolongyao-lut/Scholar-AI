---
name: memory-palace-lite
description: "Use when the user asks to retain long-term context, preserve decisions, build project memory, avoid repeating discoveries, summarize multi-session progress, create handoff summaries, or maintain decision trails. Trigger phrases include '长期记忆', '上下文沉淀', '别忘了', '延续上次结论', '会话续接', '交接摘要', 'project memory', 'decision log', 'handoff summary', and 'context snapshot'. Skip for one-shot tiny edits."
license: Internal workspace guidance
---

# Memory Palace Lite

轻量版长期记忆工作流（不依赖 MCP / 外部数据库）。

目标：在普通 Copilot 工作流中，把“会话里容易丢失的信息”沉淀为稳定、可复用、可追溯的上下文。

## When to Use (Must)

- 用户希望“延续上次讨论”或“避免重复踩坑”
- 多轮任务（重构、排障、迁移、性能优化）跨度较大
- 需要把临时结论沉淀为可执行的后续步骤
- 需要把“事实 / 决策 / 风险 / 未决项”结构化保存
- 需要生成可交接摘要（handoff summary / decision trail）

## When NOT to Use (Skip)

- 一次性小改动（例如单行文案、简单重命名）
- 纯问答且不涉及后续衔接
- 用户明确要求“只给结论，不要过程记录”

## Activation Checklist

满足以下任意 2 项即可启用：

- 涉及 2+ 文件或 2+ 子步骤
- 出现调试、测试、回归验证
- 有“下次继续 / 交给他人继续”的需求
- 结论依赖命令输出或具体文件证据

## Output Contract

执行本 skill 时，输出应尽量包含以下四层（可按任务裁剪）：

1. **Facts（事实）**：可验证信息（文件、命令、错误、接口、版本）
2. **Decisions（决策）**：做了什么选择，以及原因
3. **Open Questions（未决）**：缺什么信息、下一步要验证什么
4. **Next Actions（行动）**：最小可执行步骤

### Output Modes

- **Lite（默认）**：4~8 行，适合日常迭代
- **Deep（复杂任务）**：10~18 行，适合跨轮交接

## Palace-Lite Structure

使用“轻量宫殿”结构组织上下文（仅概念，不要求目录固定）：

- **Wing（领域）**：例如 `frontend`、`pipeline`、`recovery`、`db`
- **Room（主题）**：例如 `auth-migration`、`sqlite-wal-tuning`
- **Drawer（证据）**：命令输出、报错片段、关键配置、测试结果
- **Closet（摘要）**：对 drawer 的压缩总结（结论 + 影响 + 风险）

建议优先把高价值信息放入 closet：
- 为什么这样做（Why）
- 做完后影响什么（Impact）
- 下次继续时先看哪里（Entry points）

## Compression Rules (AAAK-inspired, Human-readable)

为了降低 token 占用，摘要遵循：

- 一条记忆尽量控制在 1~4 行
- 先写“结论”，再写“证据锚点”
- 用固定字段名，减少歧义
- 非必要不复述背景故事

推荐模板：

`[WING/ROOM] DECISION: ... | WHY: ... | EVIDENCE: file/path or command | NEXT: ...`

示例：

`[db/sqlite] DECISION: 保持 WAL + 定期 checkpoint | WHY: 已有工具链完善且迁移成本低 | EVIDENCE: db.py, sqlite_maintenance.py | NEXT: 加压测基线`

## Safety & Quality Rules

- 只记录可验证事实，不编造历史
- 不写入密钥、口令、令牌、隐私数据
- 决策记录必须包含“理由”，避免只记结论
- 如果不确定，用 `[TODO]` 或 `[ASK USER]` 明确标记

## Recommended Workflow

1. 先收集证据（代码/命令/报错）
2. 抽取事实与决策（不要混写）
3. 识别未决项与风险
4. 生成下一步最小行动列表
5. 在回复末尾附“可续接上下文块”

## Reusable Context Block

在长任务结束时，可附上：

`Context Snapshot:`
- `Facts:` ...
- `Decisions:` ...
- `Open:` ...
- `Next:` ...

该块应短小（通常 6~14 行），用于下一轮快速续接。

## Anti-Patterns

- 只记“做了什么”，不记“为什么”
- 写大量主观猜测且没有证据
- 用大段流水账替代结构化摘要
- 把敏感信息（token、密码、隐私）写进快照

## Completion Gate

在多步骤任务结束前，至少给出一个可续接块，并满足：

- 至少 2 条 Facts（含证据）
- 至少 1 条 Decision（含 WHY）
- 至少 1 条 Next（可直接执行）
