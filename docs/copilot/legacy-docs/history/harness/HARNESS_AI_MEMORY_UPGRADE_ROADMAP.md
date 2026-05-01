# Harness Upgrade Roadmap with AI Memory

## Goal

在不打断当前主链的前提下，把现有仓库从“协议层 + 资源层 + 技能层 + API 层”升级成一个真正可持续运行的 Harness：

- 保留现有 `WritingRuntime` / `writing_resources` / `skills` / `python_adapter_server` 资产
- 把 AI 记忆纳入一等公民，而不是外挂工具
- 兼顾短期会话状态、长期项目记忆、审计、审批、回放与恢复
- 维持对旧 `run_action` / pipeline 入口的向后兼容

## Current Baseline

截至当前仓库状态，已经具备：

- Phase 1: typed protocol layer
- Phase 2: in-memory `WritingRuntime`
- Phase 3: backend-first `writing_resources`
- Phase 4: unified capability registry, approvals, audit logging
- MemPalace integration:
  - runtime 终态任务可自动沉淀到长期记忆
  - RAG 回答前可检索项目长期记忆
  - API 已暴露 memory status/search/wakeup/manual sync

当前缺口不在“有没有接口”，而在“有没有把这些接口收敛成稳定的 Harness 运行模型”。

## External Patterns to Borrow

升级过程建议持续参考以下成熟方案，但不要原样照抄：

- LangGraph Memory:
  - 会话内状态和跨会话长期记忆分离
  - 长期记忆支持 hot path 写入和 background 写入
- MemPalace:
  - 本地优先、结构化 wing/room 记忆空间
  - 适合做项目级长期语义回忆和 wake-up context
- Zep / Graphiti:
  - 时序知识图适合记录“事实何时开始生效、何时失效”
  - 适合把审批、指派、项目状态变化做成 temporal facts
- Temporal / Workflow engines:
  - 任务历史事件流是回放与恢复的核心
  - Harness 的 durable execution 应以 event history 为核心，而不是靠 scattered flags

## Non-Negotiables

- 不能推倒现有 API 契约
- 不能破坏旧 action 流程
- 不能让 AI 记忆直接污染核心业务真相源
- 不能把短期上下文、长期记忆、审计日志混成一个存储
- 每一阶段都必须先回档，再对照成熟方案，再落改动

## Operating Discipline

每次升级阶段都固定执行：

1. 回档
   - 在 `.rollback_snapshots/` 下创建阶段快照
   - 至少备份将修改的 runtime / adapter / config / tests / docs
2. 搜成熟方案
   - 先看 LangGraph 官方 memory 文档
   - 再看 Zep/Graphiti 的 temporal memory 设计
   - 涉及 durable execution 时补看 Temporal 官方 workflow history
3. 小步落地
   - 先加适配层，再切主链，再补兼容层
4. 强验证
   - `py_compile`
   - 单测
   - 至少一条真实 smoke path

## Target Architecture

### Layer A: Session Harness

职责：

- 持有 thread/session 级短期状态
- 驱动 job lifecycle
- 管理 pause/resume/cancel
- 收敛 UI/API 调用进入统一执行入口

现状：

- `writing_runtime.py` 已经是雏形

下一步：

- 补持久化 event log
- 从“内存状态”升级到“事件驱动状态恢复”

### Layer B: Resource Truth

职责：

- 维护 project / section / draft / revision 的事实真相
- 作为写作主链的 authoritative store

现状：

- `writing_resources.py` 已经把资源模型建立起来

下一步：

- 引入 durable persistence
- 给 revision / draft save / restore 建立事件映射

### Layer C: Capability Execution

职责：

- 统一技能、prompt、legacy action、pipeline run
- 审批、审计、风险分层

现状：

- `skills/service.py` + `approval.py` + `audit.py` 已具备基础能力

下一步：

- 将 execution record 与 runtime job/event 真正联通
- 不再维持两套近似但割裂的事件系统

### Layer D: Memory Fabric

职责：

- 会话短记忆: runtime/session state
- 项目长记忆: MemPalace drawers
- 事实记忆: temporal knowledge graph / state transitions
- 检索唤醒: wake-up context + scoped semantic search

现状：

- 已接入 MemPalace 作为长期项目记忆
- 仍缺 temporal fact layer 和明确的 write policy

下一步：

- 明确哪些事件写长期记忆
- 明确哪些事实写 temporal graph
- 避免把原始 artifact 全量塞进 memory

## Phase Roadmap

## Phase 5: Durable Harness State

目标：

- 把 `WritingRuntime` 从纯内存态升级成可恢复 Harness

建议改动：

- 新增 `harness_store.py`
- 存储：
  - sessions
  - jobs
  - events
  - artifacts
  - approvals
- 持久化方式优先级：
  - SQLite
  - 再考虑 Postgres
- `export_state/import_state` 从 placeholder 变成真实恢复逻辑

验收标准：

- 进程重启后可恢复 session/job/event/artifact
- `job_status` 与 `events` 能重建一致状态

和 AI 记忆的关系：

- 这是短期可恢复状态，不替代 MemPalace

## Phase 6: Event History Unification

目标：

- 把 runtime event、audit event、resource revision event 收敛成统一事件主线

建议改动：

- 建立 canonical event envelope
- 统一字段：
  - event_id
  - aggregate_type
  - aggregate_id
  - session_id
  - job_id
  - actor
  - timestamp
  - payload
  - correlation_id
- `skills/audit.py` 不再只是旁路日志，而是可映射到 Harness history

验收标准：

- 同一个 job 的执行、审批、artifact 生成和资源写入可以串成一条时间线

和 AI 记忆的关系：

- 统一事件流是长期记忆提炼的上游
- memory writer 以后只订阅 canonical events

## Phase 7: AI Memory Policy Engine

目标：

- 明确什么写入 AI 记忆、什么时候写、写到哪一层

建议改动：

- 新增 `memory_policy.py`
- 把事件分成四类：
  - session-only
  - resource-only
  - audit-only
  - memory-worthy
- memory-worthy 示例：
  - 关键决策
  - 稳定偏好
  - 失败原因与修复结论
  - 项目阶段切换
  - 重复出现的 bug pattern

建议输出层：

- MemPalace drawer:
  - 保存项目级语义记忆与 verbatim 片段
- Temporal fact store:
  - 保存状态变化、审批结果、角色关系、当前激活配置
- Wake-up context:
  - 只保留高价值摘要，不直接拼全量 artifact

验收标准：

- 新任务完成后不会无脑把所有输出塞进 memory
- memory search 命中率上升，噪声下降

## Phase 8: Memory-Aware Execution Planning

目标：

- 让 Harness 在执行前、执行中、执行后都能用 memory

建议改动：

- 执行前：
  - session create / job create 时注入 wake-up context
  - 对 skill/pipeline 进行 memory-aware prompt enrichment
- 执行中：
  - 根据 job kind 决定是否触发 scoped memory search
- 执行后：
  - terminal event 交给 memory policy engine 决定是否沉淀

验收标准：

- 同类任务重复执行时能引用上次决策或失败原因
- 但不会把历史记忆覆盖当前事实真相

## Phase 9: Human Review + Recovery Console

目标：

- 给 Harness 一个可操作的调试和恢复面板

建议改动：

- 增加 API：
  - replay job timeline
  - inspect memory syncs
  - compare artifact vs memory drawer
  - invalidate wrong fact
  - requeue failed job
- 前端侧增加：
  - job timeline
  - approval queue
  - memory hits panel
  - recovery actions

验收标准：

- 用户可以看见“为什么这次执行这么做”
- 用户可以修正错误记忆，而不是手改底层库

## Phase 10: Multi-Agent Harness

目标：

- 在现有单执行流之上增加多代理/多角色协作，但不破坏主链

建议改动：

- 每个 agent 保持独立 memory wing
- 共享 canonical event stream
- shared truth 只来自 resources / facts，不来自 agent 私有 diary

验收标准：

- reviewer / planner / writer / retriever 各自有长期记忆
- 不会互相污染最终业务状态

## Priority Order

建议按下面顺序推进，不要跳：

1. Phase 5 Durable Harness State
2. Phase 6 Event History Unification
3. Phase 7 AI Memory Policy Engine
4. Phase 8 Memory-Aware Execution Planning
5. Phase 9 Human Review + Recovery Console
6. Phase 10 Multi-Agent Harness

原因：

- 没有 durable state，就没有稳定 Harness
- 没有 unified history，就没有可信 memory source
- 没有 memory policy，就会把 AI 记忆写脏

## Files to Touch First

第一批建议优先改这些文件：

- `writing_runtime.py`
- `harness_protocols.py`
- `harness_adapters.py`
- `skills/audit.py`
- `skills/service.py`
- `writing_resources.py`
- `python_adapter_server.py`
- `layers/m_layer_mempalace_memory.py`

新增建议文件：

- `harness_store.py`
- `harness_event_stream.py`
- `memory_policy.py`
- `memory_fact_store.py`
- `test_harness_persistence.py`
- `test_harness_memory_policy.py`

## Immediate Next Implementation Slice

如果直接进入下一轮开发，建议先做这一小段：

1. 把 `WritingRuntime` 的 sessions/jobs/events/artifacts 落 SQLite
2. 让 `export_state/import_state` 变成真实能力
3. 给 runtime 增加 `rehydrate_from_store()`
4. 把 terminal job memory sync 改成基于 canonical event 触发
5. 为 memory sync 加幂等键和 invalidation hook

## Command Template

每次进入新阶段都先执行：

```powershell
# 1. 回档
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('phase-next-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

# 2. 搜成熟方案
# 先查 LangGraph memory / Zep Graphiti / Temporal workflow history 官方文档

# 3. 验证
python -X utf8 -m py_compile .\writing_runtime.py .\python_adapter_server.py
python -X utf8 -m unittest .\test_mempalace_integration.py -v
```

## Bottom Line

这条路线不是“再堆几个 endpoint”，而是把当前仓库升级成：

- 可恢复的 Harness
- 有统一事件流的 Harness
- 有 AI 长期记忆但不被 AI 记忆绑架的 Harness
- 能兼顾短期状态、长期记忆、审批、审计和回放的 Harness
