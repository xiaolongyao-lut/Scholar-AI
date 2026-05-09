# Team 执行任务报告（停机前快照）

生成时间：2026-04-24
范围：任务盘点（12项核心目标 + 关联执行项）

## 1) 总览

- 已完成：11
- 进行中：3
- 未启动：2
- 过期：0
- 文档缺失：2

> 说明：状态按“文档声明 + 仓库证据（代码/产物/路由）”双重核验判定。

## 2) 核心任务状态（摘要）

| 任务 | 状态 | 关键证据 |
| --- | --- | --- |
| CJK Bigram 查询修复 | 已完成 | `inspiration_engine.py` |
| Rerank 缓存持久化 | 已完成 | `rerank_cache.py` |
| Rerank 成本埋点 | 已完成 | `reranker_client.py`, `output/rerank_cost.jsonl` |
| Chunk Store 重构 | 已完成 | `routers/resources_router.py` |
| Rerank 动态候选池上限 | 已完成 | `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md` |
| Rerank 日预算硬阀门 | 已完成 | `reranker_client.py`, `output/rerank_budget_state.json` |
| 模型调用网关（3.6） | 已完成 | `main_rag_workflow.py`, `.squad/decisions.md` |
| 证据打包器与预算（3.8） | 已完成 | `evidence_packer.py`, `tests/test_evidence_packer.py` |
| 会话持久化设计 | 进行中 | `CONVERSATION_PERSISTENCE_DESIGN.md`（设计完成） |
| 会话持久化 API 实现 | 未启动/缺口 | `python_adapter_server.py`（未见 `runtime/sessions\|resume\|rewind\|fork` 实现） |
| Tier3 全量评测（u1a3269） | 进行中 | `output/tier3_u1a3269.metrics.json/progress.jsonl/per_query.jsonl` |
| Gate B Phase B 规范化合并 | 进行中 | `.squad/decisions/inbox/ralph-canonical-normalization.md` |

## 3) 风险与阻塞

1. **Tier3 评测耗时高**：队列等待显著，推进速度慢。  
2. **会话持久化“设计-实现断层”**：有设计文档，但 API/行为尚未落地。  
3. **Gate B 合并单点执行风险**：当前主要依赖单执行链，需复核闭环。  
4. **4B 替换结论未闭合**：仓库 canary 与外部文档建议不一致，需可信集重测。  

## 4) 下一步（优先级）

- **P0**：完成 Tier3 全量评测，并做 `metrics/progress/per_query` 一致性验收。  
- **P0**：完成 Gate B Phase B 规范化合并后的 schema 校验并签核。  
- **P1**：补齐会话持久化 API（`resume/fork/rewind`）并加最小契约测试。  
- **P1**：在可信集上重跑 8B vs 4B vs BGE，对齐“效果/延迟/异常率”三指标。  

## 5) 结论

当前项目主线可继续推进；短期关键不是继续扩功能，而是**先把评测与持久化闭环打实**。完成 P0 后再推进模型替换与 TOLF 上游扩展，风险最小。

---

## 6) 本轮增量（2026-04-24）

- [x] 已对核心计划文件补齐“完成标注”与状态分层（完成/进行中/未启动/阻塞）。
- [x] 已把活跃计划补充为可勾选状态面板，便于停机前/续跑时快速对账。
- [x] 已同步统一计划中的 U1 已完成项勾选（脚本位置确认、审计产物生成）。

