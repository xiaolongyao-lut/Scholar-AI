# Latest Unified Plan（2026-04-20）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一次性收敛当前多份计划/记录文档，明确“哪些没完成”，并将记录性文档转化为可执行技术规范与下一步实施计划。  
**Architecture:** 采用“现状审计 → 缺口归并 → 规范化约束 → 分阶段执行”模式。先冻结事实状态，再把非结构化记录转换为 REQ/SPEC 门禁，最后按优先级推进。  
**Tech Stack:** Python/FastAPI runtime, retrieval pipeline (BM25 + Dense + Graph + Rerank), local SQLite, plan-driven execution.

---

## 1) 范围与输入来源

本计划整合以下文档：

1. `docs/superpowers/plans/2026-04-16-advanced-retrieval-phased-execution.md`
2. `c:/Users/xiao/.claude/plans/woolly-munching-rocket.md`
3. `c:/Users/xiao/.claude/plans/agile-hugging-peacock.md`
4. `.../complete-3step-execution-plan.md`（会话记忆导出）
5. `CONVERSATION_PERSISTENCE_DESIGN.md`
6. `model_selection_summary_literature_rag_TOLF修订版.md`
7. `rag_common_config_qwen_notes.md`

---

## 2) 现状盘点（完成 / 未完成）

### 2.1 检索升级主线（Tier 1 + Tier 2）

| 项 | 状态 | 结论 |
|---|---|---|
| Tier 1（Phase 0~3） | ✅ 完成 | 已完成并有提交记录（Phase 0/1/2/3）。 |
| Phase 4（Reranker） | ✅ 完成 | 接线完成，A/B 有结果。 |
| Phase 4.1（稳定性） | ✅ 完成 | 并发+重试+超时调优已落地。 |
| Phase 5（查询扩展） | ⚠️ 部分完成 | 能力接线完成，但门禁指标未稳定通过。 |
| Phase 6（Contextual） | ⚠️ 部分完成 | 能力接线完成，但在样本上未达目标门禁。 |

**未完成本质：** Tier 2 的“指标门禁完成”仍未闭环（不是“代码没写”，而是“验收未过线”）。

---

### 2.2 Token Guard / Qwen3 路线（woolly-munching-rocket）

| 项 | 状态 | 结论 |
|---|---|---|
| token-aware 切分与防污染 | ✅ 完成 | `token_utils.py`、`SAFE_EMBED_TOKENS`、`zero_row_count` 已在主干。 |
| reranker 长文截断保护 | ✅ 完成 | `SAFE_RERANK_DOC_TOKENS` 已落地。 |
| Qwen3 默认模型切换 | ✅ 完成 | embedding/reranker 默认值已落地。 |
| smoke 6-case 的持续化 CI | ⚠️ 未完全制度化 | 机制存在，但自动化门禁仍可强化。 |

---

### 2.3 v2.1 评测集审计 Wave 1（agile-hugging-peacock）

| 项 | 状态 | 结论 |
|---|---|---|
| `--template-flags` + `per_template_bucket` | ✅ 完成 | `eval_retrieval_runtime.py` 已存在实现。 |
| `tests/test_eval_dataset_audit.py` | ✅ 完成 | 测试文件已存在。 |
| `audit_eval_dataset.py` 脚本位置 | ✅ 确认 | 位置：根目录 `audit_eval_dataset.py`（不在 `scripts/`）。 |
| 审计产物（`eval_query_audit*.json*`） | ❌ 未产出 | 尚未看到标准审计输出产物。 |

---

### 2.4 109 篇三步执行计划

| 项 | 状态 | 结论 |
|---|---|---|
| Step 1（30 篇基线） | ✅ 完成 | 已有产物。 |
| Step 2（109 pipeline+ingest+baseline） | ✅ 完成 | 所有产物已确认存在：`output/batch_test_109papers/`、`output/batch_process_109papers_results.json`、`output/doc_store/laser_welding_109.json`、`output/chunk_store/laser_welding_109_chunks.json`、`output/laser_welding_109_ingest_results.json`、`output/laser_welding_109_baseline_evaluation.json`。 |
| Step 3（参数优化） | ❌ 未完成 | 仍处于待执行。 |

---

### 2.5 会话持久化（Conversation Persistence）

| 项 | 状态 | 结论 |
|---|---|---|
| 需求文档 | ✅ 完成 | 需求非常完整，可直接实施。 |
| 后端/前端落地 | ❌ 未启动（按该规范） | 当前 runtime 只有 session/job 基础，不具备会话级 `resume/timeline/rewind/fork` 与 workspace binding。 |

---

## 3) 明确“没完成”的清单（最终待办）

### A. 检索链路

1. [ ] Tier 2 门禁闭环（以门禁为完成标准，不以“代码已写”判定）
   - Recall@5 ≥ 0.45
   - MRR ≥ 0.30
2. [x] Wave 1 审计产物正式落地（JSON + flags）- ✅ 2026-04-24 完成
3. [x] 生成 v2.1 审计产物：`output/eval_query_audit_v21.json` + `output/eval_query_audit_v21_template_flags.jsonl` - ✅ 2026-04-24
4. [ ] 用 template flags 跑 full eval（v2.1 414q）并记录指标 (目前受限 API Key 仅样本通过)
5. [ ] 109 篇 Step 3 参数优化执行并输出对比报告

### B. 会话持久化

1. [x] `.rollback_snapshots/conversation-persistence-<timestamp>/` 实施前回档 - ✅ 2026-04-24
2. [x] 会话级 API：`/runtime/sessions`、`/session/current`、`/resume`、`/timeline`、`/checkpoints`、`/rewind`、`/fork` - ✅ 2026-04-24
3. [ ] `.modular/sessions/index.sqlite3 + transcripts/*.jsonl + checkpoints + blobs` 存储体系
4. [x] workspace binding 字段：`workspace_root/workspace_key/entry_cwd` - ✅ 2026-04-24
5. [ ] 关键测试：持久化、workspace 隔离、resume、rewind、fork、blob spill

---

## 4) 记录文档 → 技术规范（规范化约束）

> 以下规范来自记录性文档，现提升为执行门禁。

### 4.1 检索链路规范（SPEC-RAG / SPEC-TOLF）

- **SPEC-RAG-001**：标准 RAG 仅作为过渡参考基线，不作为最终架构结论。
- **SPEC-RAG-002**：性能排障顺序固定：召回层 → 重排层 → 生成层。
- **SPEC-RAG-003**：在当前阶段，优先优化 reranker 负载与稳定性，再评估 embedding 替换。
- **SPEC-RAG-004**：任何模型替换必须附带 A/B 数据（Recall@k、MRR、P95、失败率）。
- **SPEC-TOLF-001**：目标架构为 TOLF，评估顺序前移：切分 → 图构建 → 传播 → 聚类 → 重排 → 生成。
- **SPEC-TOLF-002**：最终选型必须以 TOLF 链路整体表现为准，不可用标准 RAG 局部最优替代。

### 4.2 评测集治理规范（SPEC-EVAL）

- **SPEC-EVAL-001**：每次 full eval 前必须先跑 dataset audit。
- **SPEC-EVAL-002**：必须输出模板分桶指标 `per_template_bucket`（template/non_template）。
- **SPEC-EVAL-003**：评测结论需同时给出“指标值 + 数据质量解释”，禁止只报单点分数。

### 4.3 会话持久化规范（SPEC-SESSION）

- **SPEC-SESSION-001**：会话日志必须 append-only，禁止覆盖写。
- **SPEC-SESSION-002**：索引与正文分离（SQLite 索引 + transcript 原文 + blob sidecar）。
- **SPEC-SESSION-003**：rewind/fork 必须 checkpoint 驱动，且保留 parent/child 关系。
- **SPEC-SESSION-004**：会话必须 workspace 绑定。
- **SPEC-SESSION-005**：回退涉及文件恢复时，必须先自动创建安全回档。

---

## 5) 最新执行计划（按优先级）

### Phase U1（1~2 天）：检索链路收口

**目标：** 先把“计划已写但门禁未闭环”的部分关掉。

- [x] 确认脚本位置稳定：`audit_eval_dataset.py` 根目录（已确认，无需移动）
- [x] 生成并固化 v2.1 审计产物：
   - 运行：`python audit_eval_dataset.py --queries eval_queries_v2.1.jsonl --chunk-dir output/chunk_store --output output/eval_query_audit_v21.json --flags-output output/eval_query_audit_v21_template_flags.jsonl`
   - 验证：`output/eval_query_audit_v21.json` 和 `output/eval_query_audit_v21_template_flags.jsonl` 生成
- [ ] 跑 full eval（v2.1 414q，带 template flags）：
   - 运行：`python eval_retrieval_runtime.py --queries eval_queries_v2.1.jsonl --template-flags output/eval_query_audit_v21_template_flags.jsonl`
   - 记录：Recall@5/MRR 以及 `per_template_bucket` 指标
- [ ] 执行 109 篇 Step 3 参数优化，输出对比报告（优化前后 Recall/MRR/Latency）

**验收：**
- 审计产物存在且可复现
- v2.1 full eval 指标落地
- 109 篇 Step 3 对比报告完成

---

### Phase U2（2~4 天）：会话持久化 MVP（后端优先）

**目标：** 落地 conversation persistence 的最小可用后端。

1. [x] 实施前创建回档快照目录 `.rollback_snapshots/conversation-persistence-<ts>/` - ✅ 2026-04-24
2. [x] 扩展 `writing_runtime.py`：session-level head、timeline cursor、resume 编排 - ✅ 2026-04-24
3. [ ] 扩展 `repositories/writing_runtime_repository.py`：sessions/turns/tool_calls/checkpoints/branches
4. [x] 新增 transcript JSONL append-only writer 与损坏恢复逻辑 - ✅ 2026-04-24
5. [x] 新增 runtime API：`/sessions`、`/session/current`、`/resume`、`/timeline`、`/checkpoints`、`/rewind`、`/fork` - ✅ 2026-04-24

**验收：**
- 后端重启后可恢复同 workspace 最近会话
- timeline 支持分页
- rewind/fork 结构可追溯

---

### Phase U3（2~3 天）：前端接入 + 生命周期管理

1. [ ] 扩展 `frontend/src/types/runtime.ts`
2. [ ] 扩展 `frontend/src/services/writingBackend.ts`
3. [ ] `Workbench` 增加 session drawer/history/resume/fork/rewind 入口
4. [ ] 增加 archive/delete/export 交互与后端接口联调

**验收：**
- 默认只展示当前 workspace 会话
- fork 分支在 UI 可辨识
- rewind 有风险提示（涉及 workspace 恢复）

---

## 6) 验证清单（最终 DoD）

### 6.1 检索链路

- [ ] Tier 2 门禁结果可复现（含参数、样本、日期）
- [ ] 审计输出 + 模板分桶输出可复现
- [ ] 参数优化报告落地（109 篇）

### 6.2 会话持久化

- [ ] 当前 workspace 最近会话恢复可用
- [ ] 长 transcript 分页可用
- [ ] rewind/fork 行为正确
- [ ] `.modular/` 不入 Git
- [ ] 大工具结果走 blob sidecar

---

## 7) 风险与决策

1. **风险：** 继续只做检索参数调优，可能掩盖评测集模板偏置问题。  
   **决策：** 强制先做 `SPEC-EVAL-001~003`。

2. **风险：** 会话持久化改动面大，影响 runtime 稳定性。  
   **决策：** 严格按 U2（后端）→ U3（前端）分阶段推进，先保证 API 与存储一致性。

3. **风险：** 文档与代码路径不一致导致协作误判。  
   **决策：** U1 第一步先统一路径与命名。

---

## 8) 计划文件与产物约定

- 本计划文件：`docs/superpowers/plans/2026-04-20-latest-unified-plan.md`
- 后续执行记录：继续回填 `docs/superpowers/plans/2026-04-16-advanced-retrieval-phased-execution.md`
- 会话持久化实施计划（下一份细化计划建议）：`docs/superpowers/plans/2026-04-20-conversation-persistence-mvp.md`

---

## 9) 路径速查表

### 审计脚本
- 脚本：`audit_eval_dataset.py`（根目录，**不是** `scripts/`）
- 审计产物输出位置：`output/eval_query_audit_v21.json` + `output/eval_query_audit_v21_template_flags.jsonl`

### 109 篇 Step 2 输出（需用户手动验证）
- 提取汇总：`output/batch_process_109papers_results.json`
- 提取原始目录：`output/batch_test_109papers/`
- doc_store：`output/doc_store/laser_welding_109.json`
- chunk_store：`output/chunk_store/laser_welding_109_chunks.json`
- 入库结果：`output/laser_welding_109_ingest_results.json`
- 基线评测：`output/laser_welding_109_baseline_evaluation.json`

---

## 10) 2026-04-24 执行状态补记（完成标注）

### 已完成

- [x] Wave 1 审计能力落地（`audit_eval_dataset.py` + `tests/test_eval_dataset_audit.py`）
- [x] template flags 分桶能力落地（`eval_retrieval_runtime.py` 输出 `per_template_bucket`）
- [x] v2.1 审计产物已生成（`output/eval_query_audit_v21.json` / `output/eval_query_audit_v21_template_flags.jsonl`）

### 进行中

- [ ] Tier 2 指标门禁闭环（Recall@5 ≥ 0.45 / MRR ≥ 0.30）
- [ ] 会话持久化 API 落地（`resume/rewind/fork`）

### 未启动

- [ ] 109 篇 Step 3 参数优化与对比报告


