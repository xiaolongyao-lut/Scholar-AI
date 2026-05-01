# Harness V2 Implementation Prompt

```text
你现在是这个仓库的 Staff/Principal 级工程师，负责把现有系统升级到 Harness V2，并且必须把已经接入的 AI 记忆能力纳入主架构，而不是当作外挂功能。

你工作的仓库根目录：
C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

你必须先完整阅读以下文档，再开始任何代码改动：
1. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_V2_INTEGRATED_AI_MEMORY_PLAN.md
2. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\HARNESS_AI_MEMORY_UPGRADE_ROADMAP.md
3. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE3_IMPLEMENTATION.md
4. C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\PHASE4_IMPLEMENTATION.md

你必须把以下现有代码视为当前系统基线，不能推翻重做，只能增量演进：
- writing_runtime.py
- writing_resources.py
- python_adapter_server.py
- harness_protocols.py
- harness_adapters.py
- skills/service.py
- skills/audit.py
- skills/approval.py
- main_rag_workflow.py
- layers/m_layer_mempalace_memory.py
- bootstrap_mempalace_repo.py

当前 AI 记忆代码已经存在，必须纳入新 Harness 方案：
- MemPalace bootstrap 已完成
- runtime terminal job 会自动 sync 到长期记忆
- RAG 在回答前会读取 memory hits
- API 已暴露 /memory/status、/memory/search、/memory/wakeup、/memory/runtime/job/{job_id}/sync

你的目标不是“再补几个接口”，而是严格按 Harness V2 方案推进：
- Harness Kernel 管执行态
- Resource Truth Plane 管业务真相
- Capability Plane 管动作、审批、审计
- Memory Fabric 管 AI 短记忆、长期项目记忆、temporal facts
- API Gateway 管外部稳定接口

你必须遵守以下工作流程，顺序不可跳：

第一步：回档
- 在 .rollback_snapshots 下创建阶段快照
- 至少备份所有将修改的 runtime / adapter / config / test / docs 文件
- 没有创建快照前，不允许开始核心代码改动

第二步：搜索网上成熟方案
- 必须先搜索并参考官方/一手资料，不允许闭门造车
- 优先查：
  1. LangGraph 官方 memory 文档
  2. Zep / Graphiti 的 temporal memory / knowledge graph 设计
  3. Temporal 官方 workflow history / durable execution 文档
- 搜索后，把借鉴点映射到当前仓库，不允许生搬硬套

第三步：再开始实现
- 先补测试
- 再改协议和存储
- 再接 runtime
- 再接 memory policy
- 最后接 API 和 smoke path

你必须严格遵守以下设计边界：
- 不能破坏旧 action 流程
- 不能破坏现有 python_adapter_server 的兼容能力
- 不能让 AI 记忆覆盖业务 truth
- 不能把 audit log、session state、long-term memory 混成一个存储
- 不能直接把所有 artifact 全量塞进 MemPalace
- 不能省略防守逻辑、类型标注、测试和验证

你这次要执行的阶段目标：
【在这里填当前要做的 Harness V2 阶段，例如：V2-Phase A Durable Kernel】

如果本次做 V2-Phase A Durable Kernel，交付要求是：
- 新增 harness_store.py
- 用 SQLite 持久化 sessions/jobs/events/artifacts/approvals
- 把 writing_runtime.py 的 export_state/import_state 变成真实能力
- 增加 runtime rehydrate 能力
- 保持现有 API 兼容
- 不改变 MemPalace 对外契约

如果本次做 V2-Phase B Canonical Event Stream，交付要求是：
- 新增 harness_event_stream.py
- 合并 runtime events / audit events / resource mutation events
- 定义 canonical event envelope
- 让 memory sync 不再直接由 runtime 硬编码，而是基于 canonical events 触发

如果本次做 V2-Phase C Memory Policy Engine，交付要求是：
- 新增 memory_policy.py
- 明确哪些事件写 durable project memory
- 明确哪些事件写 temporal fact store
- 明确哪些事件只保留在 session memory / audit log

你在实施时必须优先阅读并理解这些现有实现，再下手：
- writing_runtime.py 中 complete_job / fail_job / sync_job_to_memory
- main_rag_workflow.py 中 memory_hits / _retrieve_memory_hits / _generate_answer
- layers/m_layer_mempalace_memory.py 中 load_mempalace_settings / build_wakeup_context / sync_runtime_job
- python_adapter_server.py 中 memory endpoints

你必须输出的交付物：
1. 完整代码改动
2. 对应测试
3. 回档快照路径
4. 搜索过的成熟方案与借鉴点
5. 运行过的验证命令与结果
6. 若未完成，明确剩余阻塞

你必须执行并汇报以下验证：
- py_compile
- 相关 unittest / pytest
- 至少一条真实 smoke path
- 若涉及 memory：至少一条真实写入 + 检索验证

你在实现过程中必须优先使用这些命令模板：

1. 回档命令模板
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$snapshot = Join-Path '.rollback_snapshots' ('harness-v2-phase-' + $ts)
New-Item -ItemType Directory -Path $snapshot -Force | Out-Null

2. 搜成熟方案
先查官方资料：
- https://docs.langchain.com/oss/python/langgraph/memory
- https://blog.getzep.com/content/files/2025/01/ZEP__USING_KNOWLEDGE_GRAPHS_TO_POWER_LLM_AGENT_MEMORY_2025011700.pdf
- https://docs.temporal.io/

3. 验证模板
python -X utf8 -m py_compile .\writing_runtime.py .\python_adapter_server.py
python -X utf8 -m unittest .\test_mempalace_integration.py .\test_mempalace_bootstrap.py -v

补充要求：
- 所有新增 Python 代码必须有完整类型标注
- 核心入口必须带 defensive guardrails
- 公共函数必须写 docstring
- 不允许删掉未要求改动的逻辑
- 不允许留 TODO 占位
- 必须兼顾当前 AI 记忆代码，而不是绕开它另起炉灶

最终目标：
把这个仓库升级成一个真正可恢复、可审计、可回放、带 AI 长期记忆与事实记忆分层的 Harness V2。
```

