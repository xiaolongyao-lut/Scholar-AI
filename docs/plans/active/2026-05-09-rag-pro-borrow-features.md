# RAG-Pro 可借鉴功能落地计划 (2026-05-09)

## 背景

`D:\BaiduNetdiskDownload\基于AI智能体的RAG知识库管理及问答系统\RAG-Pro` 是一个 Vue 3 + FastAPI + Milvus + BGE-M3 的通用 RAG 知识库问答系统。和我们（literature_assistant 文献综述长跑）定位不同，但有 3 个可直接借鉴的产品级功能 —— 都已验证可行、对我们用户痛点直接命中。

参考源：

- 架构文档 `D:\...\RAG-Pro\docs\architecture.md`
- 功能对比 `D:\...\RAG-Pro\docs\feature-comparison.md`
- MCP 设计 `D:\...\RAG-Pro\docs\mcp-api-design.md`
- 后端 `D:\...\RAG-Pro\backend\app\agents\` + `backend\app\mcp\`

### Copilot 直接评审意见（2026-05-09 修订）

- **保留 3 个借鉴项，但实现路线要贴合本仓现状。** 本仓对外主聊天面是 `POST /api/chat`（`literature_assistant/core/routers/intelligent_chat_router.py`），低层 LLM 代理是 `/chat/ask`（`chat_router.py`）。所以 P1/P2/P3 都不应机械照搬 RAG-Pro 的 `/api/v1/kb/{kb_id}/...` 或 Vue 组件结构。
- **P1 仍是最高优先级，但第一刀应是“可观测 trace schema + 共享 retrieval trace helper”。** 当前 `intelligent_chat_router.py` 已有 context chunk / evidence refs / session persistence；debug 接口应复用这些证据链，并额外暴露“候选、淘汰、选中、prompt、metrics”，而不是另起一套独立检索逻辑。
- **P2 不建议直接套 RAG-Pro 阈值。** RAG-Pro README/架构文档写过 `0.7/0.5/0.3`，实际 `ConfidenceBadge.vue` 使用 `0.8/0.5/0.3`。本仓 `evidence_refs.score` 与 TOLF/RAGWorkflow 的分布不同，应先以后端返回 `confidence_label` 为准，P1 落地后再用真实 trace 校准阈值。
- **P3 可做，但必须默认关闭、只允许安全 ECharts option 子集。** RAG-Pro 的 `chart_agent.py` 只是从 LLM 文本中抽 JSON，校验失败返回空 series；本仓不能把未验证 spec 直接给前端渲染，应加 JSON schema / allowlist / fallback。
- **不借鉴清单基本正确。** 其中 MCP、Milvus、LiteLLM 三项尤其不应迁移：本仓已经有官方 MCP SDK、`model_call_gateway`、provider/cost/retry/keypool 体系，替换成本高且会破坏现有长跑稳定性。

### 本轮核验到的 RAG-Pro 真实实现锚点

- Test Chat：`D:\...\RAG-Pro\backend\app\api\v1\document.py` 的 `@router.post("/kb/{kb_id}/test-chat")`。
- 普通聊天：`D:\...\RAG-Pro\backend\app\api\v1\chat.py` 调用 `core/generator.py::generate_answer()`。
- Agent 路由：`D:\...\RAG-Pro\backend\app\agents\base_agent.py::detect_intent()` + `core/generator.py` 的 `route_and_generate()`。
- ChartAgent：`D:\...\RAG-Pro\backend\app\agents\chart_agent.py`，只做 JSON 抽取，未做强 schema 校验。
- ConfidenceBadge：`D:\...\RAG-Pro\frontend\src\components\ConfidenceBadge.vue`，实际阈值为 high `>=0.8`、medium `>=0.5`、low `>=0.3`。
- ChartRenderer：`D:\...\RAG-Pro\frontend\src\components\ChartRenderer.vue`，Vue ECharts 组件，React 侧只能借设计，不借代码。

### 决策锁定（2026-05-09）

采用组合：**1A + 2B + 3 使用 RAG-Pro 种子词 + 4 使用 `LITERATURE_DEV_MODE` + 5B + 6A**。

| 决策点 | 拍板 | 理由 |
| --- | --- | --- |
| P2 confidence 路径 | **1A：后端新增 `confidence_score/confidence_label`** | 语义更干净，session resume 可恢复，避免前端把 `evidence_refs.score` 临时解释成答案可信度。 |
| P1 debug 入口 | **2B：在 `IntelligentChat.tsx` 内加“调试模式” toggle** | 复用当前聊天上下文和页面心智，不新增独立页面/路由，入口更轻。 |
| P3 intent 种子 | **使用 RAG-Pro 种子词表**：`["图表", "折线图", "柱状图", "饼图", "可视化", "趋势", "分布", "对比", "统计"]` | 先保持确定性规则简单可回滚，避免本仓领域词过早扩张导致误判。 |
| 完整 prompt feature flag | **使用通用 `LITERATURE_DEV_MODE`** | 统一 dev-only 调试响应开关，避免为单一 debug 能力制造碎片化 flag。 |
| P3 错判率查询集 | **5B：P1 上线后从真实 chat trace 抽 50 条** | 真实分布优先，避免手写样本过拟合；抽样结果再固化为验收集。 |
| 启动时机 | **6A：等 PR #3 merge 后再从 `main` 开新分支** | 保持 `main` 和 MCP 集成线干净，避免从 `integration/mcp-current-20260509` 叠分支带来回滚/冲突成本。 |

---

## 🔴 P1 — Test Chat 调试接口（最高价值）

### P1 - 现状 vs 目标

| 维度 | 现状 | 目标 |
| --- | --- | --- |
| 检索 trace | logs 里有，API 不暴露 | `POST /api/chat/debug` 返回完整链路 |
| Query 改写 | `query_expander.py` 已实现 | trace 里包含 before/after |
| 多阶段评分 | `r_layer_hybrid_retriever.py` 已算 | 每个 chunk 暴露 dense/sparse/hybrid/rerank |
| Prompt 模板 | 内嵌不可见 | trace 里返回实际下发文本 |
| 性能指标 | 无 | retrieval_ms / rerank_ms / generation_ms / tokens |
| 前端 | 无 debug UI | `IntelligentChat.tsx` 内加“调试模式” toggle 和 trace 面板 |

### P1 - Copilot 修订意见

- **接口入参从 `kb_id` 改为本仓的 `project_id/source_paths/tier` 语义。** 本仓 `IntelligentChatRequest` 当前没有知识库 ID，只有 `project_id`、`source_paths`、`tier`；计划里的 `kb_id` 是 RAG-Pro 语义，不应进入本仓接口契约。
- **不要复制 RAG-Pro `document.py` 的实现方式。** RAG-Pro 的 debug 接口内联了 embed/search/rerank/prompt/generation；本仓应先抽出共享 trace helper，避免 `/api/chat` 与 `/api/chat/debug` 出现两套检索路径。
- **debug 默认不持久化会话。** Test Chat 是调试面，不应污染 `intelligent_chat_sessions.json`；如需保存 trace，应显式 `persist_trace=true` 并写入 `workspace_artifacts/runtime_state/` 的有界文件。
- **Prompt 返回必须有脱敏策略。** `prompt_template` 可能包含用户 API、私有路径或完整原文；默认返回 `prompt_preview`，完整 prompt 仅在 `LITERATURE_DEV_MODE` 开启时返回。
- **trace payload 要限流。** `content_preview` 最多 300 字符，默认候选最多 20 个；否则大文献项目会撑爆前端和日志。

### P1 - 关键文件

**后端**：

- 新增 `literature_assistant/core/routers/chat_debug_router.py`
- 修改 `literature_assistant/core/python_adapter_server.py` 注册新 router，并在 `OPENAPI_TAGS` 增加/复用 `Chat` 标签
- 修改/抽取 `literature_assistant/core/routers/intelligent_chat_router.py` 中的 context 构建逻辑，形成 debug 可复用 helper（避免复制私有函数拼接逻辑）
- 复用 `query_expander.py` / `r_layer_hybrid_retriever.py` / `rerank_cache.py` / `model_call_gateway.py`，但不得绕过现有 provider/cost/retry 体系
- 在每个阶段加 `time.perf_counter()` instrumentation
- 测试：新增独立 `tests/test_chat_debug_router.py`（debug router 专属，不再"或"扩展旧文件）；同时扩展 `tests/test_intelligent_chat_router.py` 验证 `/api/chat`、`/api/chat/sessions`、`/api/chat/resume` 行为未受影响
- Feature flag 落点：新增 `literature_assistant/core/dev_flags.py` 集中读取 `LITERATURE_DEV_MODE`（默认 off）；由 `chat_debug_router.py` 调用判断是否返回 `prompt_template` 完整版

**前端**：

- 新增 `frontend/src/components/debug/{RetrievalTrace,PromptViewer,MetricsPanel}.tsx`
- 新增 `frontend/src/services/chatDebugApi.ts`
- 修改 `frontend/src/pages/IntelligentChat.tsx`：增加“调试模式” toggle，复用同一页面发送 debug 请求并展示 trace 面板
- 不新增 `/chat/debug` 前端路由，也不新增独立 `ChatDebug.tsx` 页面

### 接口契约

```typescript
POST /api/chat/debug
Request: {
  query: string,
  project_id?: string,
  source_paths?: string[],
  tier?: 'fast' | 'balanced' | 'thorough',
  top_k?: number,
  include_generation?: boolean,      // 默认 true；false 只跑检索 trace
  include_full_prompt?: boolean,     // 默认 false；需 LITERATURE_DEV_MODE 允许
  persist_trace?: boolean            // 默认 false，不污染聊天会话
}
Response: {
  trace_id: string,
  query: string,
  rewritten_query: string | null,
  retrieval_results: Array<{
    chunk_id: string,
    material_id?: string | null,
    content_preview: string,
    dense_score?: number | null,
    sparse_score?: number | null,
    hybrid_score?: number | null,
    rerank_score?: number | null,
    final_score?: number | null,
    source: string,
    page?: string | number | null,
    section?: string | null,
    source_labels?: string[]
  }>,
  selected_chunks: Array<...>,
  rejected_chunks: Array<{ chunk_id: string, reason: 'rank' | 'budget' | 'filter' }>,
  prompt_preview: string,
  prompt_template?: string,           // 仅 include_full_prompt 且本地 flag 允许
  answer?: string,
  confidence_score?: number | null,
  confidence_label?: 'high' | 'medium' | 'low' | 'very_low',
  metrics: {
    query_rewrite_time_ms?: number,
    retrieval_time_ms: number,
    rerank_time_ms?: number,
    prompt_build_time_ms: number,
    generation_time_ms?: number,
    total_time_ms: number,
    input_tokens?: number,
    output_tokens?: number,
    total_tokens?: number
  }
}
```

### P1 - 验收

- [ ] 单测：trace 各字段非空、metrics 单调递增
- [ ] 集成测：1 个 happy path + 1 个 retrieval-fail edge case
- [ ] 手测：用一个查询失败的场景，能从 trace 定位到是 retrieval 没召回还是 rerank 把对的踢掉
- [ ] OpenAPI：`/api/chat/debug` 出现在 `/openapi.json`，且 schema 不含 RAG-Pro 风格 `kb_id` 必填字段
- [ ] 安全：默认响应不返回完整 prompt；`content_preview` 被截断；不写入普通 chat session
- [ ] 回归：原 `/api/chat`、`/api/chat/sessions`、`/api/chat/resume` 行为不变

### P1 - 建议验收命令

```powershell
.\.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py tests\test_chat_debug_router.py -q
cd frontend ; npm run test -- --run ; npm run build
```

---

## 🟡 P2 — ConfidenceBadge 前端可视化

### P2 - 现状 vs 目标

- 现状：`citation_auditor.py` 已算 confidence，但前端只展示纯文本答案
- 目标：每条 assistant 回答顶部显示 `ConfidenceBadge`（绿/黄/红/灰），hover 显示分级阈值和实际分数

### 关键设计

```typescript
// 1A 已拍板：后端产出，前端只展示，不重新解释 evidence_refs.score
confidenceScore = response.confidence_score
confidenceLabel = response.confidence_label
```

### P2 - Copilot 修订意见

- RAG-Pro 文档中的公式可借鉴，但实际 `ConfidenceBadge.vue` 使用 high `>=0.8`；本仓不要在前端硬编码两个来源都不完全适配的阈值。
- 当前 `IntelligentChatResponse` 没有 `confidence` 字段，但已有 `context_metadata.chunks[].relevance_score` 与 `evidence_refs[].score`。本次已锁定 **1A**：后端新增 `confidence_score/confidence_label`，前端只展示后端结论。
- 不采用前端临时计算方案：直接用 `evidence_refs.score` 算 badge 容易被误解为答案事实正确率，且 session resume 语义不稳定。
- Badge 文案必须区分“检索证据强度”与“答案可信度”。我们做文献助手，低分时应提示“证据覆盖不足/建议补充来源”，不要暗示模型自信度。

### P2 - 关键文件

- 新增 `frontend/src/components/chat/ConfidenceBadge.tsx`
- 修改 `frontend/src/components/chat/MessageBubble.tsx`（本仓实际文件名，不是 `ChatMessage.tsx`）
- 修改 `frontend/src/services/intelligentChatApi.ts` 增加响应类型字段
- 修改 `literature_assistant/core/routers/intelligent_chat_router.py` 的 `IntelligentChatResponse`，新增可选 `confidence_score/confidence_label`
- 修改 `literature_assistant/core/routers/intelligent_chat_router.py` 的 `_persist_turns()`（L826）与 `ChatResumeMessagePayload`（L164）：将 `confidence_score/confidence_label` 持久化并在 resume 时回填，否则 P2 验收"session resume 后 badge 仍能恢复"会失败
- 测试：新增/扩展 `frontend/src/components/chat/ConfidenceBadge.test.tsx` 与 `tests/test_intelligent_chat_router.py`

### P2 - 验收

- [ ] 4 种分级颜色显示正确
- [ ] hover tooltip 显示数值
- [ ] very_low 时附加 "答案可信度低，建议查证" 提示
- [ ] tooltip 文案明确为“检索证据强度”，避免过度承诺答案正确率
- [ ] session resume 后 badge 仍能恢复显示（需要把 confidence 字段持久化）

---

## 🟡 P3 — LLM Intent Detection + ChartAgent

### P3 - 现状 vs 目标

- 现状：`writing_resources.py` 只产 Word 文档；用户问"统计一下年份分布"只能拿到文字答案
- 目标：在 `intelligent_chat_router.py` 的 `/api/chat` 流程中接入 intent detector，识别 chart/table 意图时路由到 ChartAgent，前端用 ECharts 渲染

### P3 - Copilot 修订意见

- 本仓实际聊天入口是 `intelligent_chat_router.py`，不是普通 `chat_router.py`。ChartAgent 应接在 `/api/chat` 项目上下文构建之后、LLM 文本生成之前，而不是接在低层 `/chat/ask` 代理里。
- intent detection 不应一上来每次都调用 LLM。确定性规则首版锁定 RAG-Pro 种子词表：`["图表", "折线图", "柱状图", "饼图", "可视化", "趋势", "分布", "对比", "统计"]`；低置信度时再走 LLM intent，且单独 feature flag 控制。
- ChartAgent 输出必须是**结构化响应**，这会影响前端消息类型、session persistence、resume API。不能只在 `MessageBubble` 里临时塞一个 chart。
- React 技术栈要用 `echarts` + `echarts-for-react` 或直接 `echarts` 封装；不要借 Vue 的 `vue-echarts`。
- ECharts option 必须 allowlist：只允许 `title/tooltip/legend/grid/xAxis/yAxis/radar/series/dataset` 等安全字段，禁止函数、HTML、事件 handler、任意 JS 字符串。

### 范围裁剪

**只做 ChartAgent 一个**。RAG-Pro 还有 ReportAgent / WebpageAgent / DataAgent，但：

- ReportAgent (HTML 报表) 与我们 writing_resources Word 输出重复
- WebpageAgent (HTML+CSS+JS) 安全面太大
- DataAgent (composite) 价值低于单一 chart

### P3 - 关键文件

**后端**：

- 新增 `literature_assistant/core/agents/__init__.py`
- 新增 `literature_assistant/core/agents/intent_detector.py`（确定性关键词优先，LLM intent 仅在 `LITERATURE_ENABLE_CHART_AGENT_LLM_INTENT` 开启时使用）
- 新增 `literature_assistant/core/agents/chart_agent.py`（产 ECharts JSON spec）
- 修改 `literature_assistant/core/routers/intelligent_chat_router.py`（在 context/evidence 构建之后 detect intent，chart 时分支到 chart_agent）
- 扩展 `IntelligentChatResponse`：支持 `response_type: 'text' | 'chart'` 与 `chart_spec?: object`
- 扩展 `_persist_turns()` / `ChatResumeMessagePayload`：保存并恢复 chart 消息结构
- 新增 `tests/test_chart_agent.py` 与 `tests/test_intelligent_chat_router.py` chart 分支测试

**前端**：

- 新增依赖：`echarts` + `echarts-for-react`
- 新增 `frontend/src/components/chat/ChartRenderer.tsx`
- 修改 `frontend/src/components/chat/MessageBubble.tsx`：根据 `responseType === 'chart'` 切换渲染器
- 修改 `frontend/src/services/intelligentChatApi.ts`：新增 `response_type/chart_spec` 类型
- 修改 `frontend/src/pages/IntelligentChat.tsx`：消息 state、send/resume 都携带结构化 chart 字段

### Feature Flag

`LITERATURE_ENABLE_CHART_AGENT`（默认 off，与 MCP feature flag 风格一致）

建议再拆一个成本开关：`LITERATURE_ENABLE_CHART_AGENT_LLM_INTENT`（默认 off）。默认只跑确定性 intent；开启后才允许 LLM intent 判定。

### P3 - 验收

- [ ] 5 个常见图表类型都能生成（折线/柱状/饼/散点/雷达）
- [ ] LLM 产出的 JSON spec 用 ECharts schema 校验
- [ ] 校验失败时回退到 text 输出，不报错给用户
- [ ] 文本意图被错判为 chart 的比例 < 5%（人评 50 个查询）
- [ ] `LITERATURE_ENABLE_CHART_AGENT` 关闭时 `/api/chat` 行为完全不变
- [ ] chart 消息能被 session resume 正确恢复
- [ ] 前端不使用 `dangerouslySetInnerHTML`，ECharts option 不允许函数/HTML/事件 handler

---

## 不借鉴清单（已评估）

| 功能 | 不借鉴原因 |
| --- | --- |
| Milvus Lite 向量库 | 我们 ChromaDB 稳定，迁移成本远超收益 |
| Vue 3 + Element Plus | 我们 React 栈成熟，重写无意义 |
| Parent-Child Chunking | 我们 `contextual_chunker` 已实现类似策略 |
| OCR / 表格识别（PaddleOCR） | RAG-Pro docs 也只是建议未实现；我们 `image_cropper + extractor_full` 路线不同 |
| PostgreSQL 生产部署 | 我们 SQLite + atomic write 已满足本地优先定位 |
| 自实现 MCP JSON-RPC over SSE | 我们用官方 mcp 1.27.0 SDK + stdio/streamable_http，已大幅领先 |
| ReportAgent / WebpageAgent | 与 writing_resources Word 输出重复；HTML 安全面大 |
| LiteLLM 替换 model_call_gateway | 我们已有完整 provider 适配 + cost profile + retry，迁移收益有限 |

### 不借鉴清单 - Copilot 补充意见

- `Parent-Child Chunking` 不借鉴是合理的，但可以把 RAG-Pro 的“分块详情可视化”作为 P1 debug 面板的一个子能力，而不是单独做分块系统重构。
- `OCR / 表格识别` 不借鉴理由建议再加一个验收口径：除非后续有扫描 PDF goldset/表格抽取 goldset 证明收益，否则不要引入 PaddleOCR 这种重依赖。
- `他们的 MCP` 不借鉴理由应保留：本仓已有 `mcp_router` 与官方 SDK 路线，不要为了 RAG-Pro 的 SSE JSON-RPC 设计倒退。

---

## 推进顺序

```text
P1 (Test Chat)  ──▶  P2 (ConfidenceBadge)  ──▶  P3 (ChartAgent)
   debug 价值最高        纯前端，顺手做             需要 P1 的 intent 框架
```

### Spike 基线固化（2026-05-09）

P1 + P2 + P3 spike 已落地并跑出绿灯，作为 P3.1 的回滚基线。

**分支**：`feature/rag-pro-borrow-spike`（从 `origin/main` @ `abe56dcd` 起，独立 git worktree）

**绿灯证据**：
- 后端：`pytest tests/test_intelligent_chat_router.py tests/test_chat_debug_router.py tests/test_chart_agent.py -q` → 30 passed
- 前端：`npx tsc --noEmit` 无错误；`npm run build` 成功；`IntelligentChat` chunk 25.59 kB（echarts 通过 `React.lazy` 拆分到独立 1.14 MB chunk，按需加载）

**默认安全态**：
- `LITERATURE_ENABLE_CHART_AGENT` 默认关 → `/api/chat` 行为完全等同当前稳定版
- `/api/chat/debug` 始终不调用 `_persist_turns`，不更新 `user_research_profile`，不污染 `intelligent_chat_sessions.json`
- `prompt_template` 完整版仅在 `LITERATURE_DEV_MODE=1` 且请求 `include_full_prompt=true` 时返回；默认只给 `prompt_preview`（≤1000 字符）
- ECharts spec sanitizer（`agents/chart_agent.py::sanitize_echarts_option`）阻断 `formatter` / `renderer` / `rich` / `html` 等键，丢弃 `function(...)` / `<...>` 等危险字符串；`series.type` 必须命中 `{bar,line,pie,scatter,radar,candlestick}` allowlist
- 候选 chunk content_preview 截断到 300 字符，默认 `top_k=20`

**额外固化的 main-branch hotfix**：spike 的第一个 commit（`fix(adapter): drop dangling semantic_causal_router reference`）是必要的 unblock：origin/main 自带 broken import（PR #3 squash 漏带 `semantic_causal_router.py`，`git log --all --diff-filter=A` 返回空）。spike 仅删除 dangling 引用以恢复 app import，不带未跟踪的 router 文件进入 spike scope；semantic causal 功能需要后续单独 hotfix 把缺失的 router + store 文件正式 commit。

**P3 spike 与 P3.1 的边界**：
- ✅ 已完成：seed-word intent detector（RAG-Pro 词表 + 英文 seeds 含 word-boundary 防误触）、ECharts spec sanitizer、feature flag、前端 lazy `ChartRenderer`、session persist + resume 携带 `response_type/chart_spec`
- ✅ **P3.1a 完成**（2026-05-09 同日）：真实 LLM 生成 ECharts JSON。`generate_chart_spec` 改为 async，注入 `chat_caller` 走本仓 `chat_ask`（同 provider/cost/retry 链路，不绕过 `model_call_gateway`）。失败语义：LLM 异常 / 非法 JSON / sanitizer 拒绝 → 返回 `None`，路由层降级为 text，不抛错给用户。
- ❌ 未完成（属于 P3.1b/c）：seed regex 漏掉时的 LLM intent fallback、误触率 / 失败率度量（jsonl atomic write 到 `workspace_artifacts/runtime_state/`）

**Smoke 基线修复（2026-05-09 同日）**：
- `_compute_confidence` 引入 `s/(s+5)` 饱和归一化：BM25 6.5–9.5 不再全 high，区分度恢复
- `_truncate_preview` 修截断 +301 字符 bug（导致 `/api/chat/debug` 500）
- 英文 seed 加入：`chart/plot/graph/histogram/...`（word-boundary 不会误匹配 `discharge`/`uncharted`）

如果 P3.1b/c 引入回归，回滚到本 spike 的 HEAD 即可恢复全绿状态。

### 第一步（已锁定决策 6A）

等 PR #3（`integration/mcp-current-20260509` → `main`）合并后，从 `main` 新开 RAG-Pro 借鉴分支。先做一个 P1.0 spike，不直接写完整页面：

1. 在 `intelligent_chat_router.py` 梳理当前 context/evidence 构建路径，确认哪些字段可稳定进入 trace。
2. 定义 `ChatDebugRequest/ChatDebugResponse` Pydantic 模型与前端 TypeScript 类型。
3. 加一个无 generation 的最小 `POST /api/chat/debug`，只返回 query、候选/选中 chunks、metrics、trace_id。
4. 跑通单测与 OpenAPI，再进入前端页面。

这个顺序能避免一开始就把检索、生成、UI 三条线耦在一起。

---

## 风险 & 回滚

- P1：`time.perf_counter()` 多余开销 < 1ms，但 trace 字段大可能撑大 response payload —— 限制 `content_preview` 截断到 **300 字符**（与 L65 限流意见同步），默认候选最多 20 个
- P2：后端 `confidence_label` 阈值可能与本仓 `evidence_refs.score` 分布不匹配（RAG-Pro 用 BGE-M3 reranker，我们用 BGE + ChromaDB）—— 等 P1 trace 落地后用真实分布校准**后端**阈值，前端只读 `confidence_label` 不参与公式
- P3：LLM 产出非合法 ECharts spec 是高频问题 —— Schema 校验 + 回退到 text 答案；不让用户看到错误
- 全部走 feature flag，rollback 策略：env 关掉即可，无需回滚代码

### Copilot 补充风险

- **隐私风险**：debug prompt 可能包含完整文献原文、用户私有路径、provider 配置痕迹。默认只返回 preview，完整 prompt 必须 `LITERATURE_DEV_MODE` + UI 明示。
- **会话污染风险**：Test Chat 如果复用 `/api/chat` persistence，会污染历史会话与用户研究画像；debug endpoint 默认不得调用 `_persist_turns()`，也不得更新 `user_research_profile`。
- **接口漂移风险**：前端类型、OpenAPI schema、后端 Pydantic 模型必须同步；每个 P 都要包含 schema/export 或类型测试。
- **评估缺口**：P3 的“错判率 < 5%”必须有固定查询集，不能只靠手感。P1 上线后从真实 chat trace 抽 50 条，固化到 `workspace_artifacts/validation/2026-05-09-rag-pro-borrow/chart-intent-queries.jsonl` 或同类 dated artifact。

---

## 全局验收门禁（建议加入每个 PR）

```powershell
.\.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py -q
.\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
cd frontend ; npm run test -- --run ; npm run build
```

若改 OpenAPI / 前端类型，再额外跑：

```powershell
cd frontend ; npm run generate:openapi
```

注意：本仓当前有大量未提交变更；实施时每个 PR/切片只允许改本计划列出的文件，避免顺手整理无关历史改动。

---

## 参考材料定位

如需查阅 RAG-Pro 原代码（D 盘只读快照）：

| 借鉴项 | RAG-Pro 文件 |
| --- | --- |
| Test Chat 后端 | `backend/app/api/v1/document.py` 中 `test_chat` 接口（feature-comparison.md 第 286-417 行有完整代码） |
| ChartAgent | `backend/app/agents/chart_agent.py` + `base_agent.py` |
| ConfidenceBadge | `frontend/src/components/ConfidenceBadge.vue` |
| Intent Detection prompt | `backend/app/utils/prompt_templates.py` 中 `INTENT_DETECTION_PROMPT` |
| ECharts 渲染 | `frontend/src/components/ChartRenderer.vue` |

本仓对应落点：

| 借鉴项 | 本仓文件 |
| --- | --- |
| 主聊天 API | `literature_assistant/core/routers/intelligent_chat_router.py` (`POST /api/chat`) |
| 低层 LLM 代理 | `literature_assistant/core/routers/chat_router.py` (`POST /chat/ask`) |
| FastAPI 注册 | `literature_assistant/core/python_adapter_server.py` |
| 当前聊天 UI | `frontend/src/pages/IntelligentChat.tsx` |
| 消息渲染 | `frontend/src/components/chat/MessageBubble.tsx` |
| 前端 API 类型 | `frontend/src/services/intelligentChatApi.ts` |
| 路由注册 | `frontend/src/App.tsx` |
| 当前后端测试 | `tests/test_intelligent_chat_router.py` |
