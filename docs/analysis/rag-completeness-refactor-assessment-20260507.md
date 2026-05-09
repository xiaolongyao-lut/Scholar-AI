# RAG 项目完整度 + 重构机会评估 — 2026-05-07

> 触发: 计划.txt step 4 — 评估 RAG 工作流、健壮性、重构级优化机会
> 参考: docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md
> 参考: docs/plans/runbooks/local-app-engineering-release-checklist.md
> 历史重构基线: 浏览器→嵌入式前端 (✅ §9.1)、嵌入→重排路由 (✅ rerank_logic_cache + reranker_client)

## 1. 当前完整度快照

### 1.1 测试与门禁状态

| 维度 | 数值 | 来源 |
| --- | --- | --- |
| 后端 pytest | 1840 passed / 4 skipped | gap-fix-status §release-gate-truth-refresh |
| Wiki 子集 | 457 passed / 1 skipped | 同上 |
| 前端 Vitest | 通过 | LMWR-466 record |
| Playwright E2E | 29 passed | LMWR-466 + release-gate |
| canary30 v2.1 (frozen) | R@5=0.50 / MRR=0.32 / nDCG@10=待补 | SCORING_POLICY §7.2 |
| 第一篇 P0 paper-level | R@5=0.83 / MRR=0.65 (post-refine) | v2.3-workflow-quality-20260507.md |

**结论**: 测试基础设施稳定，发布门禁已就位。

### 1.2 §9 产品化路线进展

| 节 | 功能 | DoD 状态 | 备注 |
| --- | --- | --- | --- |
| 9.1 | pywebview 嵌入式 + in-process uvicorn | ✅ 全绿 | start_desktop.py + start.bat 已上线 |
| 9.2 | TipTap + docx 导出 | ✅ 代码入口已存在 | `frontend/src/components/TipTapEditor/TipTapEditor.tsx` + `literature_assistant/core/routers/export_router.py`；发布前仍需专项 smoke |
| 9.3 | PDF.js + 选段 AI | ✅ 代码入口已存在 | `frontend/src/components/PdfViewer/PdfViewer.tsx` + `literature_assistant/core/routers/annotation_router.py`；发布前仍需专项 smoke |
| 9.4 | Skill → LLM 调用链 | ✅ 全绿 | skill_executor + intelligent_chat_router |
| 9.5 | 多 Agent 讨论 (CCB) | ✅ 全绿 | discussion_router + WebSocket |
| §8 | 用户研究方向记忆 | ⚠️ 6/9 | profile_updater 写入未完成；手动验证未做 |

**结论**: §9 主体能力已具备代码入口；写作 (9.2) 和阅读 (9.3) 不再按“未开始”处理，但在打包 / release 前仍需按 `local-app-engineering-release-checklist.md` 做专项 smoke 和端到端验收。

### 1.3 §11 重构机会进展

| 节 | 机会 | DoD 状态 | 复杂度 |
| --- | --- | --- | --- |
| 11.1 | 可插拔记忆提供者 (Hermes) | ❌ 未开始 | 低 |
| 11.2 | Compiled Truth + Timeline (GBrain) | ❌ 未开始 | 低 |
| 11.3 | Skill 精准路由 (GBrain Resolver) | ❌ 未开始 | 中 |
| 11.4 | Curator 自动保鲜 | ❌ 未开始 | 中 |
| 11.5 | 确定性任务队列 (GBrain Minions) | ❌ 未开始 | 中高 |
| 11.6 | 凭证池故障切换 (Hermes) | ❌ 未开始 | 低 |

**结论**: 6 项重构机会均在档，全未启动。

## 2. 紧凑性 / 健壮性 体检

### 2.1 代码紧凑性 (按行数排查 god-module)

| 模块 | 行数 | 评级 |
| --- | --- | --- |
| `routers/resources_router.py` | **3008** | 🔴 god-router; 强烈建议拆分 |
| `routers/intelligent_chat_router.py` | 1024 | 🟡 偏大；§11.3 + §11.4 后可能再涨 |
| `routers/wiki_router.py` | 564 | 🟢 可接受 |
| `python_adapter_server.py` | 508 | 🟢 ASGI 注册中心，行数合理 |
| `extractor_full.py` | 552 | 🟢 单层职责 |
| `layers/r_layer_hybrid_retriever.py` | 447 | 🟢 |
| `integrated_pipeline.py` | 68 | 🟢 |

**核心痛点**: `resources_router.py` 3008 行是当前最大紧凑性赤字。其他模块体量基本合理。

### 2.2 路径与配置纪律

| 检查项 | 状态 | 证据 |
| --- | --- | --- |
| `.env` 不进打包产物 | ✅ | release checklist §6.1 |
| `project_paths.py` 统一路径 | ✅ | 已是规范层 |
| 后端绑定 127.0.0.1 | ✅ | start_desktop / start.py |
| canary30 v2.1 frozen 不被覆盖 | ✅ | SCORING_POLICY §7.5 + 今日 v2.3 工作未触动 |
| paper-level 与 retrieval 边界 | ✅ | v2.3 README 显式声明 release_gate=false |

### 2.3 健壮性盲点

| 项 | 现状 | 风险 |
| --- | --- | --- |
| `resources_router.py` 测试覆盖 | 部分（路径未审计） | 3008 行单文件难定位回归 |
| 大语料同步处理 | §11.5 未做：嵌入/提取在请求线程跑 | 200 篇导入卡 5-10 分钟 |
| API key 故障切换 | §11.6 未做：单 key 限速即停 | 长跑 / 评测时手动换 key |
| Reranker 默认开启 | SCORING_POLICY §7.7 release_blocker | 已固化为禁止默认 |
| frozen exe 路径 | 未验证 | release checklist §5.4 待补 |

## 3. 推荐重构顺序（紧凑+健壮维度）

按”代码紧凑性收益 / 健壮性收益 / 阻塞下游条目数量”排序：

### 3.1 优先级 A — 立即收益高，风险低

#### A1. `resources_router.py` 3008 行拆分（独立任务）

- 把 router 按职责切成 ≤500 行的子 router 文件，统一通过 APIRouter include 挂回。
- 候选切分轴: pdf-import / chunk-store-admin / metadata-edit / search / annotation。
- 收益: 紧凑性 +40%，单文件回归定位时间显著降低。
- 风险: 路由 path 不能改; 用 git mv + 引用集中替换。
- 测试: 既有 pytest tests/ 全部维持通过即可。
- DoD: 单文件 ≤ 500 行；既有 1840 pytest 全绿；OpenAPI schema 字节稳定。

#### A2. §11.6 凭证池故障切换 (低复杂度)

- gateway 注入 CredentialPool；同 provider 多 key 配置；STATUS_EXHAUSTED 标记 + 恢复探针。
- 收益: 长跑 / 评测稳定性提升; 用户不再手动换 key。
- 风险: env_config.py schema 变化需向后兼容（单 key 仍能跑）。
- 参考: `github/download/hermes-agent-main/agent/credential_pool.py`。

### 3.2 优先级 B — 中复杂度，与已有产品化能力联动

#### B1. §11.5 确定性任务队列

- SQLite 任务队列；chunk 嵌入/提取异步化；前端轮询任务状态。
- 阻塞: 批量导入 UX。
- 风险: 幂等键设计；进程崩溃后任务恢复。
- 参考: `github/download/gbrain-master/src/core/minions/`。

#### B2. §11.3 Skill 精准路由（与 §9.4 联动）

- 路由表 + MECE 检查 + check-resolvable 审计；skill 注册脚手架 + 10 项清单门禁。
- 阻塞: 当前 skill 选择由 LLM 自由路由，未来 skill 数量增长后会出现误选。
- 风险: 现有 skill 需补 triggers schema；可分批上线。

### 3.3 优先级 C — 长期价值，可延后

#### C1. §11.1 + §11.2 + §11.4 记忆层演进链

- §8 user_research_profile 已有基础但未完全落地。等 §8 DoD 全绿后再推 §11.1 → §11.2 → §11.4。

#### C2. §9.2 TipTap + §9.3 PDF.js（核心写作 / 阅读能力）

- 这两条不是“紧凑性”重构；代码入口已经存在，后续归 release 前专项 smoke / 端到端验收。
- 它们是 §9.5 多 Agent 讨论的能力基础，打包前建议按 `local-app-engineering-release-checklist.md` 单独验收。

## 4. 不建议的“重构”

| 想法 | 不做的理由 |
| --- | --- |
| Electron / Tauri 替换 pywebview | §9.6 已论证：体积/学习成本高，pywebview 单体方案已经够用 |
| Express / Node 替换 FastAPI | 同 provider 锁定，后端 pytest 1840 已稳定，迁移成本远超收益 |
| 重写 chunk_vector_store | 现有缓存语义稳定，rerank cache v2 已分层；先做 §11.5 任务队列再考虑 |
| 把 frontend dist 内置到 PyInstaller onefile | release checklist §5.3 明确建议先 onedir；onefile 路径混淆风险高 |
| TOLF 替换默认主链 | plan-missing §8.3 phase 3 设计已存在，但需要更多 P1 sample 验证后才能安排 |

## 5. 落地建议（最小 next-step set）

如果只能挑 3 条立即推进，建议：

1. **A1 拆分 resources_router.py** — 紧凑性最直接收益；独立任务，无外部依赖。
2. **A2 凭证池** — 长跑稳定性硬需求；本地实现简单，对外接口不变。
3. **B1 任务队列** — 大语料 UX 阻塞；做完后 §11.4 Curator / §11.5 大批量重嵌入 都解锁。

完成这 3 条后再回到 §9.2 / §9.3 做核心写作 + 阅读能力的专项 smoke、端到端验收和打包发布硬化。

## 6. 不属于本次评估的

- 重新评估 chunk size / overlap / max_chunks_per_material — LMWR-470 已闭环，结论 `promote_200_8=false`；除非新一轮 canary30 全量回归出现退化，不需重新评估。
- 重新评估 reranker — SCORING_POLICY §7.7 已固化为 release_blocker；待 LMWR-470 RERANK-FIX-01 ticket 处理。
- 重新调整 v2.1 / v2.2 / v2.3 边界 — 今日 v2.3 已落地，下一步是扩到 P1 (≥10 paper)，不是改边界。

## 7. 回滚边界

本评估文件只是诊断报告，不修改代码、不动 baseline、不影响任何路由。删除本文件即回滚。
