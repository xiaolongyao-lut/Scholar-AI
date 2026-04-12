# Harness V2 Integrated AI Memory Plan

## Intent

这不是一份“以后再考虑 AI 记忆”的泛路线图，而是基于当前仓库已经存在的代码，重新定义一个 **Harness V2**：

- 现有 Harness 资产继续保留
- 现有 AI 记忆代码直接纳入主架构
- 现有 RAG / skills / runtime / resources / adapter server 全部有位置
- 后续升级以此文档为主，不再把 MemPalace 当成外挂

## What Already Exists

当前仓库实际上已经有一个 Harness 雏形，只是还没有被完整收敛成统一架构。

### Protocol Layer

- `harness_protocols.py`
- `harness_adapters.py`

作用：

- 提供 session / job / event / artifact / approval 的 typed contract
- 给 legacy action 和新协议之间做翻译

### Runtime Layer

- `writing_runtime.py`

作用：

- 管理 session lifecycle
- 管理 job queue / start / pause / resume / cancel / complete / fail
- 管理 artifacts / events / approvals

### Resource Truth Layer

- `writing_resources.py`

作用：

- 维护 project / section / draft / revision 这些真实资源
- 是写作主链的事实源

### Capability Layer

- `skills/service.py`
- `skills/registry.py`
- `skills/runtime.py`
- `skills/approval.py`
- `skills/audit.py`

作用：

- 管理 skill / action / imported capability
- 审批与审计
- skill execution 结果生成

### API Layer

- `python_adapter_server.py`

作用：

- 对外暴露 runtime / resources / skills / pipeline / memory 入口

### AI Memory Layer

已经落地的代码：

- `layers/m_layer_mempalace_memory.py`
- `bootstrap_mempalace_repo.py`
- `output/mempalace/identity.txt`
- `mempalace.yaml`

已经接上的能力：

- runtime 终态 job 自动沉淀长期记忆
- RAG 生成前读取 MemPalace memory hits
- API 提供 memory status/search/wakeup/manual sync
- repo bootstrap 已完成，可做本地长期记忆基线

## Why The Old Harness Plan Was Not Enough

旧方案的问题不是方向错，而是不够“收口”。

当前仍存在这些结构性问题：

1. `WritingRuntime` 是运行时中心，但不是 durable center
2. `skills/audit.py` 和 `writing_runtime.py` 都有事件，但不是同一条 canonical history
3. `writing_resources.py` 是事实源，但资源变化还没有系统性投射到 memory/facts
4. `MemPalace` 已经接入，但它还只是部分路径可见：
   - RAG 路径可读
   - runtime 终态可写
   - skill execution / resource mutation 还没统一纳入
5. AI 记忆、审计日志、短期状态还没被明确定义边界

所以新方案必须回答三件事：

- 哪个层才是 Harness 的中心
- 哪个层才是业务事实真相
- 哪个层才是 AI 记忆

## Harness V2 Core Principle

Harness V2 采用三分离原则：

### 1. Execution State != Business Truth

- `writing_runtime.py` 负责执行态
- `writing_resources.py` 负责资源真相

### 2. Business Truth != AI Memory

- 业务当前真相永远来自 resources / canonical facts
- AI 记忆只做 recall / wake-up / historical context

### 3. Audit Log != Short-Term Memory != Long-Term Memory

- Audit: 合规与回放
- Short-term memory: 当前 session / thread / active job context
- Long-term memory: 跨 session 的 durable recall

## Harness V2 Architecture

## Layer 1: Harness Kernel

文件归属：

- `writing_runtime.py`
- `harness_protocols.py`
- 后续新增 `harness_store.py`
- 后续新增 `harness_event_stream.py`

职责：

- 统一 job/session 执行入口
- 产生 canonical lifecycle events
- 持有短期 execution state
- 对外暴露恢复与回放能力

设计要求：

- 所有执行状态都能从 event history 重建
- pause/resume/cancel 不能只靠进程内变量
- terminal state 必须可追溯

## Layer 2: Resource Truth Plane

文件归属：

- `writing_resources.py`

职责：

- 维护业务对象 current truth
- 保存 draft / revision / section / project 的 authoritative state

设计要求：

- 资源是当前事实
- revision 是业务级历史
- 资源变更必须投射到 canonical event stream

## Layer 3: Capability Plane

文件归属：

- `skills/service.py`
- `skills/runtime.py`
- `skills/audit.py`
- `skills/approval.py`

职责：

- 统一 action / skill / imported capability / pipeline execution
- 执行前审批
- 执行过程审计
- 执行结果转换为 canonical artifact

设计要求：

- `skills/audit.py` 不再只是旁路日志
- execution record 要能回挂到 runtime job_id
- capability invocation 必须发 canonical events

## Layer 4: Memory Fabric

文件归属：

- `layers/m_layer_mempalace_memory.py`
- `bootstrap_mempalace_repo.py`
- 后续新增 `memory_policy.py`
- 后续新增 `memory_fact_store.py`

职责：

- 统一短记忆、长记忆、事实记忆
- 负责 memory write/read policy
- 为 execution 和 RAG 提供 memory augmentation

### Memory Fabric 内部分层

#### L0 Identity Memory

当前文件：

- `output/mempalace/identity.txt`

用途：

- 固定项目身份
- 固定 agent/harness 行为边界
- 提供 wake-up 的最小人格与任务上下文

#### L1 Project Wake-Up Memory

当前文件：

- `layers/m_layer_mempalace_memory.py`

用途：

- 由 MemPalace Layer0 + Layer1 生成
- 提供项目级关键上下文

#### L2 Session Memory

当前归属：

- `writing_runtime.py`

用途：

- thread/session 级短期状态
- 当前 job 的活动上下文

注意：

- 这是 short-term memory，不写进 MemPalace 作为当前事实

#### L3 Durable Project Memory

当前归属：

- `layers/m_layer_mempalace_memory.py`
- `main_rag_workflow.py`

用途：

- 跨 session 的项目历史回忆
- 决策、失败原因、重复问题、稳定偏好

当前已实现：

- runtime terminal sync
- memory search
- wake-up context
- bootstrap history

#### L4 Temporal Fact Memory

当前状态：

- 还没正式接入

目标：

- 保存“当前生效事实”和“历史上何时失效”
- 类似 Zep/Graphiti 的 temporal fact layer，但本地优先

应该记录：

- 当前启用的 pipeline 配置
- 某个 project 当前状态
- 某个 skill 是否被禁用
- 某个 approval 在何时被批准/拒绝
- 某个 memory/fact 在何时被替换

## Layer 5: API & UX Gateway

文件归属：

- `python_adapter_server.py`

职责：

- 对前端和外部调用暴露稳定接口
- 统一读写 runtime/resources/memory
- 提供 recovery / audit / memory inspection 面板能力

当前 memory 相关接口已经存在：

- `/memory/status`
- `/memory/search`
- `/memory/wakeup`
- `/memory/runtime/job/{job_id}/sync`

下一步：

- 增加 replay / memory inspection / fact invalidation / rehydrate 接口

## Concrete Data Flow

## Flow A: Job Execution

1. API 接收请求
2. `WritingRuntime` 创建 session/job
3. `skills/service.py` 或 pipeline 执行 capability
4. 生成 artifact + audit
5. runtime 完成 terminal transition
6. terminal event 写入 canonical event stream
7. `memory_policy.py` 判断是否写入 long-term memory
8. 符合条件则写 MemPalace 或 fact store

## Flow B: Resource Mutation

1. draft save / revision restore / project status update
2. `writing_resources.py` 更新资源 truth
3. 同步发出 resource mutation event
4. memory policy 决定：
   - 是否更新 fact store
   - 是否写一条 durable project memory

## Flow C: AI Retrieval

1. 创建 job 或执行 RAG/skill 前
2. 先读取 L0/L1 wake-up
3. 按 job kind 做 scoped memory search
4. 注入 execution context
5. 输出时保留 evidence / memory trace

## What Current AI Memory Code Should Become

现有代码不是临时补丁，应该这样定位：

### `layers/m_layer_mempalace_memory.py`

当前身份：

- MemPalace integration adapter

在 Harness V2 的正式身份：

- Memory Fabric gateway

未来职责：

- load settings
- wake-up context
- long-term memory search
- terminal sync
- memory dedupe
- memory invalidation hook
- bridge to fact store

### `bootstrap_mempalace_repo.py`

当前身份：

- 一次性初始化脚本

在 Harness V2 的正式身份：

- Memory bootstrap / reindex tool

未来职责：

- 项目初始化
- reindex
- conversation import
- repo identity rebuild
- selective rebuild by wing/room

### `main_rag_workflow.py`

当前身份：

- 读 memory hits 参与回答

在 Harness V2 的正式身份：

- retrieval consumer

未来职责：

- 所有 retrieval class 统一走 memory-aware retrieval policy
- 不只 RAG 路径能读 memory

### `writing_runtime.py`

当前身份：

- terminal 自动 sync memory

在 Harness V2 的正式身份：

- short-term execution memory owner
- long-term memory event publisher

未来职责：

- 不直接决定写什么记忆
- 只负责发 canonical events + 调 memory policy

## Memory Write Policy

这是新方案最关键的补足点。

## Never Write Directly to Long-Term Memory

以下内容不能直接无差别进 MemPalace：

- 全量 artifact 内容
- 临时报错堆栈
- 每一次普通工具调用
- 未确认的中间推理

## Always Eligible for Long-Term Memory

- 稳定项目决策
- 已经验证的修复结论
- 多次重复的 bug pattern
- 用户稳定偏好
- 流程级规则变更

## Write to Temporal Fact Store Instead

- 当前默认模型
- 当前启用/禁用的 skill
- 当前项目状态
- 当前 approval decision
- 当前 pipeline strategy

## Keep Session-Only

- 当前线程的工作缓存
- 当前 job 中间状态
- 未完成任务的 scratch notes

## New Harness V2 Phases

## V2-Phase A: Durable Kernel

目标：

- 把 runtime 从内存对象升级成 durable kernel

改动：

- 新增 `harness_store.py`
- 用 SQLite 持久化:
  - sessions
  - jobs
  - events
  - artifacts
  - approvals
- `export_state/import_state` 变成真实实现

验收：

- 进程重启后能恢复 session/job/event

## V2-Phase B: Canonical Event Stream

目标：

- 合并 runtime events / audit events / resource events

改动：

- 新增 `harness_event_stream.py`
- 建 canonical envelope:
  - event_id
  - event_type
  - aggregate_type
  - aggregate_id
  - session_id
  - job_id
  - actor
  - payload
  - timestamp
  - correlation_id

验收：

- 单个 job 的全部行为能串成 timeline

## V2-Phase C: Memory Policy Engine

目标：

- 把 memory write/read 的规则代码化

改动：

- 新增 `memory_policy.py`
- 输入：
  - canonical events
  - resource diffs
  - terminal artifacts
- 输出：
  - skip
  - write durable memory
  - update fact store
  - refresh wake-up cache

验收：

- 不再由 runtime 直接决定怎么写 MemPalace

## V2-Phase D: Fact Store

目标：

- 增加本地 temporal memory

改动：

- 新增 `memory_fact_store.py`
- 建 SQLite temporal facts:
  - fact_id
  - namespace
  - subject
  - predicate
  - object
  - valid_from
  - valid_to
  - source_event_id

验收：

- 当前事实与历史事实都能查

## V2-Phase E: Memory-Aware Planner

目标：

- 让 job create / execution / retrieval 全部有 memory hook

改动：

- session create 时可选注入 wake-up
- job create 时根据 kind 绑定 memory namespace
- RAG / skill / pipeline 统一调用 memory retrieval policy

验收：

- 不只是 `main_rag_workflow.py` 能读 memory

## V2-Phase F: Recovery Console

目标：

- 让你能看见、验证、修正 Harness 和记忆行为

改动：

- API:
  - replay
  - inspect canonical events
  - inspect memory syncs
  - invalidate fact
  - rebuild wake-up
  - rehydrate runtime

验收：

- 错误记忆和错误事实都能被修

## Immediate Implementation Order

下一轮正确顺序应该是：

1. `harness_store.py`
2. `harness_event_stream.py`
3. `memory_policy.py`
4. `memory_fact_store.py`
5. `python_adapter_server.py` 增补 replay / inspect API
6. 再扩展 `main_rag_workflow.py` 和 `skills/service.py`

## File Mapping for Next Round

优先改：

- `writing_runtime.py`
- `harness_protocols.py`
- `harness_adapters.py`
- `skills/audit.py`
- `skills/service.py`
- `writing_resources.py`
- `layers/m_layer_mempalace_memory.py`
- `python_adapter_server.py`

新增：

- `harness_store.py`
- `harness_event_stream.py`
- `memory_policy.py`
- `memory_fact_store.py`
- `test_harness_store.py`
- `test_harness_event_stream.py`
- `test_memory_policy.py`

## Execution Rule

从现在开始，所有 Harness 升级都按这个固定流程执行：

1. 回档
2. 搜成熟方案
3. 先补测试
4. 再改核心层
5. 再接 AI 记忆
6. 最后做 smoke path

## Command Block

```powershell
Set-Location C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

# 1. 回档
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('harness-v2-phase-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

# 2. 搜成熟方案
Start-Process "https://docs.langchain.com/oss/python/langgraph/memory"
Start-Process "https://blog.getzep.com/content/files/2025/01/ZEP__USING_KNOWLEDGE_GRAPHS_TO_POWER_LLM_AGENT_MEMORY_2025011700.pdf"
Start-Process "https://docs.temporal.io/"

# 3. 验证当前 memory 基线
.\.venv\Scripts\python.exe -X utf8 -m unittest .\test_mempalace_integration.py .\test_mempalace_bootstrap.py -v
.\.venv\Scripts\python.exe -X utf8 -c "from layers.m_layer_mempalace_memory import MempalaceMemoryAdapter, load_mempalace_settings; import json; a=MempalaceMemoryAdapter(load_mempalace_settings()); print(json.dumps(a.describe(), ensure_ascii=False, indent=2))"
```

## Final Definition

新的 Harness 方案不是：

- 一个 runtime
- 一套 resources
- 再外挂一个 memory adapter

而是：

- **Harness Kernel** 管执行
- **Resource Truth Plane** 管业务真相
- **Capability Plane** 管动作与审批
- **Memory Fabric** 管 AI 记忆与事实回忆
- **API Gateway** 管外部可见接口

现有 AI 记忆代码已经是这个新方案的一部分，不再是旁路补丁。
