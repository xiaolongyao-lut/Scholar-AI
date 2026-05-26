# 功能验收矩阵 (Functional Acceptance Matrix)

## 范围与说明

**数据源**: `docs/plans/active/` 全量 (70+ plans)  
**粒度**: 每个 task / slice 一行  
**状态**: 本轮已做静态代码对照；未启动后端、未跑测试、未做浏览器验收  
**状态口径**: ✅ 已实现（静态定位）= 当前代码能对上前端 + 后端/API 链路；⚠️ 部分实现/契约不一致 = 只有一侧、路径/字段不同、范围缩水或需要开关；❓ 未定位/待验证 = 未找到足够当前代码证据  
**优先级口径**: P0 = 文献助手核心闭环必须做；P1 = 对核心体验明显增益，应排入近期；P2 = 可延后，不阻塞主闭环；P3 = 暂缓或偏发布/运维  
**基础设施口径**: API 凭证、模型路由、MCP 协议兼容、工具审批、Agent 权限隔离、Skill 沙箱、Wiki 权限属于 AI 可用性/安全基础设施；即使看起来偏生态，也应按 P0/P1 优先考虑  
**执行方口径**: Claude 负责后端、数据模型、API 契约、OpenAPI/类型客户端、接口测试；Codex 负责前端 UI、交互逻辑、布局、浏览器验收；Claude→Codex 表示先由 Claude 补齐接口，再由 Codex 接 UI

---

## A. 检索内核 (RAG / TOLF / Rerank / 证据链)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| A1 | Rerank Stage0 验证 | BGE API ≈ Local (ρ=0.951)，material-dedup 白拿收益 | 无前端 UI | `test_rerank_stage0.py` 通过 | rerank-stage0-findings | 可延后/P2 | Claude(后端/接口) | ❓ 未定位：未找到 `tests/test_rerank_stage0.py` |
| A2 | 本地 Rerank 主线化 | 默认启用本地 rerank，Settings 可切换 | Settings → 语义路由 开关 | `feature_flags.py` ENABLE_LOCAL_RERANK=True | experimental-mainline-promotion E1 | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现：Settings 有 `/api/rerank/config` 配置；未定位 `ENABLE_LOCAL_RERANK` 默认主线 flag |
| A3 | TOLF 跨语言桥接修复 | hash-based embedding 改为语义 embedding，跨语言对齐 | 无前端 UI | 中英文检索 NDCG 提升 | tolf-bridge-expansion-fix (memory) | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现：`tolf_text_selector.py` 与相关测试存在；跨语言 NDCG 验收未静态证明 |
| A4 | Evidence refs 路由 | 证据引用支持 source_labels 过滤 | 无前端 UI (后端 API) | `/api/evidence_refs` 返回 filtered results | TASK-202~229 (master plan) | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现：`evidence_refs` 分布在 RAG/Chat/Wiki/Inspiration 返回体；未定位独立 `/api/evidence_refs` |
| A5 | Source labels 持久化 | 用户标注的 source 标签存入 DB | 无前端 UI | `source_labels` 表 CRUD | TASK-210 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现：`source_labels` 随 evidence/chunk payload 传播；未定位独立 `source_labels` 表 CRUD |
| A6 | Goldset v3.1 L1 Active | n=50 canary, R@5=0.86 NDCG@10=0.60, per_difficulty floors | 无前端 UI | `goldset_v3_promotion.md` 验收通过 | goldset-v3-promotion (memory) | 可延后/P2 | Claude(后端/接口) | ⚠️ 部分实现：有 `tests/wiki/test_canary_goldset_drift.py`；未定位该 promotion 文档/验收产物 |
| A7 | Chunk-page locator L0 | 前端传 chunk_id，后端返回 PDF page + bbox | 无前端调用 (API ready) | `/api/chunk_to_page` 200 OK | chunk-page-locator L0 | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现/契约不一致：实际为 `GET /resources/chunks/{chunk_id}/locator`，返回 page/chunk_index，无 bbox |
| A8 | Chunk-page locator L1 | PDF Reader 高亮定位到 chunk 位置 | PDF Reader 显示高亮框 | 前端调 `/api/chunk_to_page` + 渲染 | chunk-page-locator L1 | 是/P0 必做 | Codex(UI) | ⚠️ 部分实现：PDF Reader 有高亮 overlay；locator 无 bbox，不能证明 chunk 精确框选 |
| A9 | Chunk-page locator L2 | 智能研读引用点击跳转 PDF | 引用气泡点击 → PDF Reader 跳页 | 前端路由 + locator API | chunk-page-locator L2 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`EvidencePill` 通过 locator 跳 `/workbench/paper/:materialId?page=&chunk=`；Dialog/MessageRenderer 复用 |
| A10 | Chunk-page locator L3 | Workbench Inspector 引用跳转 | Inspector 引用 → PDF 跳页 | 同 L2 | chunk-page-locator L3 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：Workbench Inspector 复用 `Conversation`/`EvidencePill` 引用跳转链路 |
| A11 | Chunk-page locator L4 | 写作系统引用跳转 | Writing Citations → PDF 跳页 | 同 L2 | chunk-page-locator L4 | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现：写作画布/引用抽屉有 citation anchors；Sources 页未定位完整 PDF locator 点击链路 |

---

## B. 智能研读 (SmartRead / Chat / IntelligentChat)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| B1 | Dialog 合并 A0 | 三入口统一路由到 `/dialog` | 顶栏"智能研读"单一入口 | 路由表移除 `/chat` `/intelligent-chat` | dialog-merge A0 | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现：`/chat`、`/inspiration` 重定向 `/dialog`；未定位 `/intelligent-chat` 路由，旧页面文件仍存在 |
| B2 | Dialog 合并 A1 | `Conversation` 组件统一渲染 | Dialog 页用 `Conversation` | `MessageRenderer` 替代 `MessageBubble` | dialog-merge A1 | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现：Dialog 用 `Conversation`；`IntelligentChat.tsx` 仍用 `MessageBubble` 兼容页 |
| B3 | Dialog 合并 A2 | 后端 `/api/chat` 统一入口 | 前端只调 `/api/chat` | `/chat/ask` 标记 deprecated | dialog-merge A2 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`POST /api/chat` 存在；`/chat/ask` deprecated |
| B4 | SmartRead 流式输出 | SSE 流式返回，前端逐 token 渲染 | 输入框发送 → 逐字显示 | `/api/chat/stream` 200 OK | smart-read-streaming B4 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`POST /api/chat/stream` + Dialog/SmartReadContext 流式更新 |
| B5 | 成本档位统一 | low/medium/high/xhigh/max 五档 | Settings → API 凭证 → 默认档位 | `CredentialStrategyHint` enum 扩展 | settings-smartread-ui-followup tier slice | 是/P0 必做 | Claude | ✅ 已完成 (2026-05-26 commit b5b0ca3e + cc0da047)：`CredentialStrategyHint` 新增 LOW/MEDIUM/HIGH/XHIGH/MAX canonical 枚举 + DEFAULT/CHEAP/FAST/QUALITY legacy 枚举；`normalize_strategy_hint()` 映射 cheap→low, default→medium, fast→medium, quality→high, 未知→medium；`to_public()` 输出 canonical 值（存储保留原始，避免迁移）；13 测试覆盖 canonical/legacy/surface/defaults/case/whitespace/to_public 输出 (`tests/test_credentials_strategy_hint_mapping.py`)；代码：`literature_assistant/core/models/credentials.py:39-68` enum, `:173-217` normalize, `:356` to_public normalize；验证：`pytest tests/test_credentials_strategy_hint_mapping.py -v` 13/13 passed |
| B6 | 智能研读档位移除 | 提问界面不显示档位选择器 | Dialog 页无 `TierSelector` | 读取 Settings 默认档位 | settings-smartread-ui-followup tier slice | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：Dialog 未渲染 `TierSelector`，读取 `loadSmartReadCostTier()` 映射后端 tier |
| B7 | ChatPipeline 统一 M-Slice 2 | `chat/pipeline.py` 统一 session/evidence 逻辑 | 无前端变化 | `build_chat_pipeline()` 单一入口 | fullstack-deduplication M-Slice 2 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现/命名不一致：`chat/pipeline.py` 抽出 session/evidence helpers；未定位 `build_chat_pipeline()` 单一入口 |
| B8 | localStorage 迁移 M-Slice 5 | 会话历史迁移到后端 DB | 无前端 UI 变化 (透明迁移) | `session_store` 表持久化 | fullstack-deduplication M-Slice 5 | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现：后端 JSON session store + resume/list/delete；前端仍大量 localStorage scope/session/input 持久化 |

---

## C. 学者工作台 (Scholar Workbench / Workbench Inspector)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| C1 | Workbench IA 重设计 | 三栏布局：文献列表 + PDF Reader + Inspector | Workbench 页显示三栏 | 无后端变化 | workbench-ia-redesign | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`WorkbenchShell` 三栏结构 + `ResearchWorkbenchInspector` |
| C2 | Inspector 智读页 | 右侧 Inspector 嵌入智能研读对话 | Inspector 显示 `Conversation` | 复用 `/api/chat` | workbench-inspector phases | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：Inspector 智读 tab 嵌入 `Conversation` |
| C3 | Inspector 多智能体页 | 右侧 Inspector 嵌入多智能体讨论 | Inspector 显示 Discussion 面板 | 复用 `/api/discussion` | workbench-inspector phases | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：Inspector 讨论 tab 嵌入 `DiscussionPanel` |
| C4 | Inspector 默认嵌入讨论 | 主线默认启用 Inspector 嵌入讨论 | Settings → 功能开关 默认 ON | `feature_flags.py` WORKBENCH_INSPECTOR_DEFAULT_EMBEDDED_DISCUSSION=True | experimental-mainline-promotion E2 | 是/P1 应做 | Claude→Codex | ⚠️ 部分实现/命名不一致：`inspector_embed_unified` 默认 true；不是矩阵里的 flag 名 |
| C5 | Inspector 窄栏布局优化 | 窄栏不挤压重叠，垂直滚动 | Inspector 宽度 < 400px 时布局正常 | 无后端变化 | settings-smartread-ui-followup discussion inspector slice | 是/P1 应做 | Codex(UI) | ⚠️ 部分实现：窄栏组件结构存在；未做本轮浏览器尺寸验收 |
| C6 | Inspector 保存默认设置 | "保存为知识库讨论默认" 按钮 | Inspector 显示保存按钮 | 保存到 localStorage defaults | settings-smartread-ui-followup discussion inspector slice | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`DiscussionPanel` 有保存默认按钮并持久化默认设置 |
| C7 | PDF Reader L2 F0 | 加载 PDF.js 3.x | PDF Reader 渲染 PDF | `pdfjs-dist` 3.x 加载 | pdf-reader-l2 F0 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`react-pdf` + `pdfjs-dist/build/pdf.worker.min.mjs` |
| C8 | PDF Reader L2 F1 | 页面导航 (上/下页) | PDF Reader 显示翻页按钮 | 前端状态管理 | pdf-reader-l2 F1 | 是/P1 应做 | Codex(UI) | ⚠️ 部分实现：连续滚动、outline/高亮跳页、页码输入存在；未见传统上下页按钮 |
| C9 | PDF Reader L2 F2 | 缩放控制 (放大/缩小) | PDF Reader 显示缩放按钮 | 前端 canvas 缩放 | pdf-reader-l2 F2 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`PdfViewer` scale/zoom 状态与工具栏 |
| C10 | PDF Reader L2 F3 | 页面跳转输入框 | PDF Reader 显示页码输入 | 前端跳转逻辑 | pdf-reader-l2 F3 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`PageJump` 输入 + `goToPage()` |
| C11 | PDF Reader L2 F4 | 高亮 chunk bbox | PDF Reader 渲染高亮框 | 前端 canvas overlay | pdf-reader-l2 F4 | 是/P0 必做 | Codex(UI) | ⚠️ 部分实现：PDF overlay 支持 rects；chunk locator 不返回 bbox |
| C12 | PDF Reader L2 F5 | 全屏模式 | PDF Reader 全屏按钮 | 前端全屏 API | pdf-reader-l2 F5 | 可延后/P2 | Codex(UI) | ❓ 未定位：未找到 fullscreen/requestFullscreen |
| C13 | PDF Reader L2 F6 | 打印/下载 | PDF Reader 打印/下载按钮 | 浏览器打印 API | pdf-reader-l2 F6 | 是/P1 应做 | Codex(UI) | ⚠️ 部分实现：`PdfReaderShell` 有笔记 Markdown 下载；未定位 PDF 打印/下载按钮 |
| C14 | PDF Reader L2 F7 | 搜索文本 | PDF Reader 搜索框 | PDF.js textContent API | pdf-reader-l2 F7 | 是/P1 应做 | Codex(UI) | ❓ 未定位：未找到 PDF Reader 内文本搜索框 |
| C15 | PDF Reader L2 F8 | 性能优化 (虚拟滚动) | 大 PDF 流畅滚动 | 前端虚拟列表 | pdf-reader-l2 F8 | 可延后/P2 | Codex(UI) | ❓ 未定位：未找到虚拟列表/virtual scrolling |
| C16 | KG-1 Step 5 嵌入 | Workbench 嵌入知识图谱查看器 | Workbench 显示 KG viewer | `/api/kg/graph` 返回图数据 | kg-1-step-5-embed | 可延后/P2 | Claude→Codex | ⚠️ 部分实现/契约不一致：有 `GraphPayloadViewer` 与 `/api/graph/payload`；未定位 `/api/kg/graph` |

---

## D. 多 Agent 讨论 (Discussion + Auto-stop + Citation)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| D1 | Runtime 凭证 Phase 6 | 讨论时动态选择 API 凭证 | Discussion 面板显示凭证选择器 | `runtime_credentials_store` 表 | runtime-credentials Phase 6 | 是/P0 必做 | Claude→Codex | ✅ 已完成 (2026-05-26)：后端支持 `credential_id`、`strategy_hint`+`category` 动态采样；`DiscussionAgentConfig` 新增 `strategy_hint`/`category` 字段（与 `credential_id`/`llm` 互斥）；`_resolve_agent_endpoint` 优先级：llm > credential_id > strategy_hint > default；采样逻辑复用 `/api/credentials/sample`（精确匹配 strategy_hint 优先，回退到最高 priority）；禁用凭证返回 `DiscussionCredentialMissingError` (404)；`DiscussionAgentTrace` 不含 `api_key` 字段（仅记录 `credential_id` 用于审计）；11 测试覆盖 credential_id 解析/禁用检查/strategy_hint 采样/category 默认/无匹配错误/字段互斥验证/优先级顺序 (`tests/test_discussion_runtime_credentials.py`)；代码：`models/discussion.py:93-148` DiscussionAgentConfig 字段+验证，`discussion_orchestrator.py:142-168` 禁用检查，`:172-237` strategy_hint 采样；验证：`pytest tests/test_discussion_runtime_credentials.py -v` 11/11 passed；前端 Discussion 面板运行时选择器待 Codex 实现 |
| D2 | Runtime 凭证 Phase 7 | 凭证采样端点 `/api/credentials/sample` | 无前端 UI (后端 API) | `/api/credentials/sample` 200 OK | runtime-credentials Phase 7 | 是/P1 应做 | Claude | ✅ 已完成 (2026-05-26 commit b5b0ca3e + cc0da047)：`POST /api/credentials/sample?category={generation|embedding|rerank}&strategy_hint={tier}` 按 category + strategy_hint 选择凭证；精确匹配 strategy_hint 优先（双向 normalize：查询参数和候选凭证都 normalize 后比较，确保 legacy stored credential 能被 canonical query 命中），回退到最高 priority (数值越小优先级越高)；返回 `RuntimeCredentialPublic` (masked api_key, canonical strategy_hint)；11 测试覆盖精确匹配/legacy 映射/priority 回退/category 过滤/无可用凭证 404/默认 category=generation/默认 strategy_hint=medium/api_key 掩码/legacy stored 匹配/legacy query 匹配/list 输出 canonical (`tests/test_credentials_sampling.py`)；代码：`literature_assistant/core/routers/credentials_router.py:208-261` sample_credential endpoint, `:252-256` 双向 normalize 匹配；验证：`pytest tests/test_credentials_sampling.py -v` 11/11 passed；依赖注入修复：router 所有端点使用 `Depends(get_credential_store)` 支持测试隔离 |
| D3 | Autostop 基础逻辑 | 讨论自动停止 (收敛/超时) | Discussion 面板显示停止原因 | `autostop_detector.py` 触发 | autostop-logic | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`auto_stop`、收敛 judge、`stop_reason`、前端展示存在 |
| D4 | Evidence trace G1 | 讨论生成证据包 | Discussion 显示证据引用 | `evidence_builder.py` 输出 | evidence-trace G1 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`evidence_pack.build_evidence_pack` + `DiscussionEvidencePackPayload` + 前端 evidence pack |
| D5 | Evidence trace G2 | 证据包持久化到 DB | 无前端 UI | `evidence_pack` 表 CRUD | evidence-trace G2 | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现：run payload/store 保留 evidence；未定位独立 `evidence_pack` 表 CRUD |
| D6 | Evidence trace G3 | 前端渲染证据引用气泡 | Discussion 消息显示引用标记 | 前端解析 evidence refs | evidence-trace G3 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`cited_evidence_ids` pills 和 evidence cards |
| D7 | Evidence trace G4 | 引用点击跳转源文献 | 引用气泡点击 → PDF Reader | 前端路由 + locator API | evidence-trace G4 | 是/P0 必做 | Codex(UI) | ⚠️ 部分实现：通用 `EvidencePill` 支持跳转；Discussion 引用 pill 是否全量复用需浏览器验收 |
| D8 | Evidence trace G5 | 证据重叠检测 | 后端检测重复引用 | `citation_overlap_detector.py` | evidence-trace G5 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现/命名不一致：有 `citation_overlap_converged` 测试与收敛逻辑；未定位该文件名 |
| D9 | Evidence trace G6 | 前端显示重叠警告 | Discussion 显示"引用重叠"提示 | 前端接收 overlap 字段 | evidence-trace G6 | 是/P1 应做 | Codex(UI) | ❓ 未定位：未找到前端 overlap 警告字段展示 |
| D10 | History cap H0 | 讨论历史上限 100 轮 | 无前端 UI | `discussion_store` 限制 100 条 | history-cap H0 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现：历史预算/截断逻辑和测试存在；未定位“100 轮” store hard cap |
| D11 | History cap H1 | 超限自动归档 | 无前端 UI | 旧记录移到 `archived_discussions` | history-cap H1 | 是/P1 应做 | Claude(后端/接口) | ❓ 未定位：未找到 archived_discussions |
| D12 | History cap H2 | 前端分页加载历史 | Discussion 历史列表分页 | `/api/discussion/history?page=N` | history-cap H2 | 是/P1 应做 | Claude→Codex | ❓ 未定位：未找到该 history API |
| D13 | History cap H3 | 归档历史只读查看 | Discussion 显示"归档"标签 | `/api/discussion/archived` | history-cap H3 | 是/P1 应做 | Claude→Codex | ❓ 未定位 |
| D14 | History cap H4 | 归档搜索 | Discussion 历史搜索框 | 后端全文搜索 archived | history-cap H4 | 是/P1 应做 | Claude→Codex | ❓ 未定位 |
| D15 | History cap H5 | 归档导出 | Discussion 导出按钮 | `/api/discussion/export` JSON | history-cap H5 | 是/P1 应做 | Claude→Codex | ❓ 未定位 |
| D16 | History cap H6 | 归档删除 (用户确认) | Discussion 删除按钮 + 确认弹窗 | `/api/discussion/delete` | history-cap H6 | 是/P1 应做 | Claude→Codex | ❓ 未定位 |
| D17 | Discussion 持久化 B1 | 讨论记录存入 DB | 无前端 UI 变化 | `discussion_store` 表持久化 | 0182-release B1 | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现：run register/get/resume store 存在；未定位 DB 表而非运行态 store |
| D18 | Discussion 流式 DSE-1 | SSE 流式返回讨论消息 | Discussion 逐 token 显示 | `/api/discussion/stream` 200 OK | 0182-release DSE-1 | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现/契约不一致：实际 `POST /api/discussion/runs/stream` |
| D19 | Discussion 流式 DSE-2 | 前端 EventSource 接收 | Discussion 组件订阅 SSE | 前端 EventSource 连接 | 0182-release DSE-2 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`discussionApi.ts` 与 `DiscussionPanel` 流式/恢复链路存在 |
| D20 | Discussion 流式 DSE-3 | 多 Agent 并发流 | Discussion 显示多个 Agent 同时输出 | 后端 asyncio 并发 | 0182-release DSE-3 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`arun_parallel_round` + stream run task |
| D21 | Discussion 流式 DSE-4 | 流式错误处理 | Discussion 显示错误提示 | SSE error event | 0182-release DSE-4 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：router SSE error events + 前端错误状态 |
| D22 | Analysis Chain ACR-2 | Discussion 集成思维链 | Discussion 显示推理步骤 | `analysis_chain_rag_builder.py` | 0182-release ACR-2 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`analysis_chain_discussion` flag + `build_analysis_chain` |
| D23 | Analysis Chain ACR-3 | 前端渲染思维链 UI | Discussion 显示折叠/展开推理 | 前端解析 chain steps | 0182-release ACR-3 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`AnalysisChainPanel` 在 DiscussionPanel 渲染 |

---

## E. 灵感工坊 (Inspiration / Evidence-refs / Causal-DAG)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| E1 | Inspiration 重写 B1 | 新架构：IRAC/FinCoT 框架 | 无前端 UI 变化 | `inspiration_generator.py` 重构 | inspiration-rewrite B1 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现/命名不一致：`inspiration_router.py` 有 IRAC/FinCoT frame 与模板；未定位 `inspiration_generator.py` |
| E2 | Inspiration 重写 B2 | 证据引用集成 | Inspiration 显示引用标记 | `evidence_refs` 字段输出 | inspiration-rewrite B2 | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`SparkEvidenceRef`、`SparkResponse.evidence_refs`、前端 `SparkEvidencePills` |
| E3 | Inspiration 重写 B3 | 前端渲染 IRAC 结构 | Inspiration 显示 Issue/Rule/Application/Conclusion | 前端解析 IRAC 字段 | inspiration-rewrite B3 | 可延后/P2 | Codex(UI) | ⚠️ 部分实现：IRAC prompt/template 存在；未定位结构化 IRAC 字段 UI |
| E4 | Inspiration 重写 B4 | FinCoT 推理链 | Inspiration 显示推理步骤 | `fincot_chain` 字段输出 | inspiration-rewrite B4 | 可延后/P2 | Claude→Codex | ⚠️ 部分实现：FinCoT prompt/template 与 causal summary 存在；未定位 `fincot_chain` 字段 UI |
| E5 | Inspiration 重写 B5 | 持久化到 DB | 无前端 UI 变化 | `inspiration_store` 表 CRUD | inspiration-rewrite B5 | 可延后/P2 | Claude(后端/接口) | ❓ 未定位：未找到 inspiration_store 表 CRUD |
| E6 | Evidence refs E0 | 后端 API `/api/evidence_refs` | 无前端 UI (后端 API) | `/api/evidence_refs` 200 OK | evidence-refs E0 | 是/P1 应做 | Claude(后端/接口) | ❓ 未定位：没有独立 `/api/evidence_refs` |
| E7 | Evidence refs E1 | 前端调用 evidence refs | Inspiration 加载引用数据 | 前端调 `/api/evidence_refs` | evidence-refs E1 | 是/P1 应做 | Codex(UI) | ⚠️ 部分实现：Inspiration 从 `/inspiration/generate` 返回 `evidence_refs`，不是独立 API |
| E8 | Evidence refs E2 | 引用气泡渲染 | Inspiration 显示引用标记 | 前端渲染 refs | evidence-refs E2 | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`SparkEvidencePills` 复用 `EvidencePill` |
| E9 | Evidence refs E3 | 引用点击跳转 | 引用气泡点击 → PDF Reader | 前端路由 + locator API | evidence-refs E3 | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`SparkEvidencePills` -> `EvidencePill` locator 跳转 |
| E10 | Evidence refs E4 | 引用过滤 (by source_labels) | Inspiration 显示过滤器 | 后端 source_labels 过滤 | evidence-refs E4 | 是/P1 应做 | Claude(后端/接口) | ❓ 未定位：未找到 Inspiration evidence source_labels 过滤器/API |
| E11 | Evidence refs E5 | 引用排序 (by relevance) | Inspiration 引用按相关性排序 | 后端 relevance score | evidence-refs E5 | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`build_spark_evidence_refs` 按 score 降序排序并有测试 |
| E12 | Evidence refs E6 | 引用导出 | Inspiration 导出按钮 | `/api/evidence_refs/export` | evidence-refs E6 | 可延后/P2 | Claude(后端/接口) | ❓ 未定位：未找到 `/api/evidence_refs/export` |
| E13 | Causal DAG P3 | 因果图生成 | Inspiration 显示因果图 | `causal_dag_builder.py` | causal-dag P3 | 可延后/P2 | Claude→Codex | ⚠️ 部分实现：`inspiration_engine.load_causal_dags_from_output` + causal context；未定位该文件名/完整 DAG builder |
| E14 | Causal DAG P3 前端 | 前端渲染 DAG (D3.js / Cytoscape) | Inspiration 显示交互式图 | 前端图渲染库 | causal-dag P3 | 可延后/P2 | Codex(UI) | ⚠️ 部分实现：`InspirationGraphSection` 基于 evidence refs 渲染图；不是完整因果 DAG |
| E15 | IRAC P0 | IRAC 框架生成 | Inspiration 显示 IRAC 结构 | `irac_generator.py` | irac P0 | 可延后/P2 | Claude→Codex | ⚠️ 部分实现/命名不一致：IRAC 模板与 frame 选择存在；未定位 `irac_generator.py` |
| E16 | FinCoT P1 | FinCoT 推理链生成 | Inspiration 显示推理步骤 | `fincot_generator.py` | fincot P1 | 可延后/P2 | Claude→Codex | ⚠️ 部分实现/命名不一致：FinCoT 模板与 helper 测试存在；未定位 `fincot_generator.py` |

---

## F. 演化层 (Evolution / Memory Palace / Curator)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| F1 | Evolution S0 | 候选池初始化 | 无前端 UI | `candidate_store` 表创建 | evolution S0 | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`evolution/store.py` 创建 `candidates` SQLite 表 |
| F2 | Evolution S1 | 候选生成逻辑 | 无前端 UI | `evolution_agent.py` 生成候选 | evolution S1 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现/命名不一致：capture extractors + `EvolutionService.capture()` 存在；未定位 `evolution_agent.py` |
| F3 | Evolution S2 | 候选评分 | 无前端 UI | `candidate_scorer.py` | evolution S2 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现/命名不一致：candidate `confidence`、risk、curator judge 存在；未定位 `candidate_scorer.py` |
| F4 | Evolution S3 | 候选排序 | 无前端 UI | 按 score 排序 | evolution S3 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现：候选列表按 `updated_at DESC`；不是明确 score 排序 |
| F5 | Evolution S4 | 候选持久化 | 无前端 UI | `candidate_store` 表写入 | evolution S4 | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`EvolutionCandidateStore.upsert_candidate()` |
| F6 | Evolution S5 | Review UI | Evolution 页显示候选列表 | `/api/evolution/candidates` | evolution S5 | 是/P1 应做 | Claude→Codex | ⚠️ 部分实现/契约不一致：UI 与 `GET /evolution/candidates` 存在；不是 `/api/evolution/candidates` |
| F7 | Evolution S6 | 用户审核 (批准/拒绝) | Evolution 页显示批准/拒绝按钮 | `/api/evolution/approve` | evolution S6 | 是/P1 应做 | Claude→Codex | ⚠️ 部分实现/契约不一致：实际 `/evolution/candidates/{id}/accept`、`reject`、`snooze`、`rollback` |
| F8 | Evolution S7 | 批准后晋升到 MemPalace | 无前端 UI | 候选 → `memory_palace` 表 | evolution S7 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现：`EvolutionPromoter` 调 MemPalace adapter；未定位 `memory_palace` 表 |
| F9 | Evolution S8 | Curator 定期清理 | 无前端 UI | `curator.py` 定时任务 | evolution S8 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现：`POST /evolution/curate/run` 手动运行；未定位定时任务 |
| F10 | Evolution S8.1 优先级队列 | 高优先级候选优先展示 | Evolution 页按优先级排序 | `priority_queue` 字段 | post-s8.1-priority-queue | 可延后/P2 | Claude(后端/接口) | ❓ 未定位：未找到 `priority_queue` 字段 |
| F11 | MemPalace 存储 | 长期记忆存储 | 无前端 UI | `memory_palace` 表 CRUD | memory-palace | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现：MemPalace adapter `add_memory` 存在；表结构属于外部 adapter，未在本仓定位 |
| F12 | MemPalace 检索 | 记忆检索 API | 无前端 UI (后端 API) | `/api/memory_palace/search` | memory-palace | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现/契约不一致：实际 `POST /memory/search` |
| F13 | MemPalace 前端展示 | Evolution 页显示 MemPalace 内容 | Evolution 页显示记忆列表 | 前端调 `/api/memory_palace` | memory-palace | 可延后/P2 | Codex(UI) | ❓ 未定位：Evolution 页未找到 MemPalace 列表展示 |

---

## G. LLM-Wiki (知识库 / Compiler / Doctor / Graph)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| G1 | Wave 0 基础架构 | Wiki 页面存储 | 无前端 UI | `wiki_pages` 表创建 | llm-wiki Wave 0 | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现/存储形态不同：`WikiPageStore` 文件页 + registry/source DB；未定位 `wiki_pages` 表 |
| G2 | Wave 1 页面 CRUD | 创建/读取/更新/删除页面 | Wiki 页显示页面列表 | `/api/wiki/pages` CRUD | llm-wiki Wave 1 | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现：`GET /api/wiki/pages` 和 page read；无 create/update/delete router |
| G3 | Wave 2 Markdown 渲染 | 页面内容 Markdown 渲染 | Wiki 页渲染 Markdown | 前端 Markdown 库 | llm-wiki Wave 2 | 是/P0 必做 | Codex(UI) | ⚠️ 部分实现：`WikiPagePreviewPanel` 展示 frontmatter/body；未定位完整 Markdown 渲染库 |
| G4 | Wave 3 页面链接 | Wiki 内部链接 `[[page]]` | Wiki 页显示可点击链接 | 前端解析 `[[]]` 语法 | llm-wiki Wave 3 | 是/P0 必做 | Codex(UI) | ⚠️ 部分实现：后端 graph 支持 wikilink；前端 page body 未定位 `[[...]]` 可点击解析 |
| G5 | Wave 4 搜索 | Wiki 全文搜索 | Wiki 页显示搜索框 | `/api/wiki/search` | llm-wiki Wave 4 | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现/契约不一致：后端是 `POST /api/wiki/query`；页面列表是本地过滤 |
| G6 | Wave 5 版本历史 | 页面版本控制 | Wiki 页显示历史按钮 | `wiki_versions` 表 | llm-wiki Wave 5 | 是/P1 应做 | Claude(后端/接口) | ❓ 未定位：未找到版本历史 UI/API/table |
| G7 | Wave 6 Compiler | 自动生成 Wiki 页面 | 无前端 UI | `wiki_compiler.py` | llm-wiki Wave 6 | 是/P0 必做 | Claude(后端/接口) | ⚠️ 部分实现：`/api/wiki/compile` dry-run + `compiler.py`；非 dry-run 默认拒绝 |
| G8 | Wave 7 Doctor | Wiki 一致性检查 | Wiki 页显示检查报告 | `wiki_doctor.py` | llm-wiki Wave 7 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`GET /api/wiki/doctor` + `DoctorReportPanel` |
| G9 | Wave 8 Graph 基础 | 页面关系图数据 | 无前端 UI | `/api/wiki/graph` 返回图数据 | llm-wiki Wave 8 | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`GET /api/wiki/graph` + `wiki/graph.py` |
| G10 | Wave 9 Graph 前端 | 前端渲染知识图谱 | Wiki 页显示交互式图 | 前端图渲染库 | llm-wiki Wave 9 | 是/P0 必做 | Codex(UI) | ⚠️ 部分实现：`GraphDebugPanel` 展示 graph payload；不是完整交互式知识图谱验收 |
| G11 | Wave 10 标签系统 | 页面标签 | Wiki 页显示标签 | `wiki_tags` 表 | llm-wiki Wave 10 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现：page frontmatter/status/kind 可展示；未定位 `wiki_tags` 表 |
| G12 | Wave 11 分类 | 页面分类/目录 | Wiki 页显示目录树 | `wiki_categories` 表 | llm-wiki Wave 11 | 是/P1 应做 | Claude(后端/接口) | ❓ 未定位：未找到目录树/API/table |
| G13 | Wave 12 模板 | Wiki 页面模板 | Wiki 页显示模板选择器 | `wiki_templates` 表 | llm-wiki Wave 12 | 可延后/P2 | Claude(后端/接口) | ❓ 未定位 |
| G14 | Wave 13 权限 | 页面访问控制 | Wiki 页显示权限设置 | `wiki_permissions` 表 | llm-wiki Wave 13 | 是/P1 应做 | Claude(后端/接口) | ✅ 已完成：`wiki/permissions.py` (WikiPageVisibility enum, WikiPagePermissions dataclass, can_read/can_write helpers)；`wiki/service.py` (WikiService.get_page/update_page_extra)；`GET/PUT /api/wiki/pages/{slug}/permissions` 端点；权限存储在 WikiPage.extra["permissions"] 避免 schema migration；15 个测试全通过 (tests/test_wiki_permissions.py) |
| G15 | Wave 14 导出 | Wiki 导出 (Markdown/PDF) | Wiki 页显示导出按钮 | `/api/wiki/export` | llm-wiki Wave 14 | 是/P1 应做 | Claude(后端/接口) | ⚠️ 部分实现：`wiki/export.py` 存在；未定位 `/api/wiki/export` 和 UI 按钮 |
| G16 | Wave 15 导入 | Wiki 导入 (Markdown/Notion) | Wiki 页显示导入按钮 | `/api/wiki/import` | llm-wiki Wave 15 | 可延后/P2 | Claude(后端/接口) | ⚠️ 部分实现：`wiki/migration.py` 支持 evidence refs/jsonl dry-run；未定位 `/api/wiki/import`/Notion UI |

---

## H. 写作系统 (Writing Project / Outline / Citations / Figures)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| H1 | Writing Overview 页 | 写作项目总览 | Writing 页显示项目列表 | `/api/writing/projects` | git status (WritingOverview.tsx) | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现/契约不一致：页面存在；后端实际 `/resources/projects` |
| H2 | Outline Manager 页 | 大纲管理 | Writing 页显示大纲编辑器 | `/api/writing/outline` CRUD | git status (OutlineManager.tsx) | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现/契约不一致：Outline 页和 `/resources/section(s)` 存在；不是 `/api/writing/outline` |
| H3 | Sources Citations 页 | 文献引用管理 | Writing 页显示引用列表 | `/api/writing/citations` CRUD | git status (SourcesCitations.tsx) | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现/范围偏窄：Sources 页列材料/切块数，Draft/ReferenceDrawer 管 citation anchors；不是 Word 式交叉引用/参考文献目录，也不是 `/api/writing/citations` |
| H4 | Figures Tables 页 | 图表管理 | Writing 页显示图表列表 | `/api/writing/figures` CRUD | git status (FiguresTables.tsx) | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现/范围偏窄：`FiguresTables` 只管理文本派生候选和手动项；后端 `/resources/figure-table-candidates` 非图表 CRUD/真实资产提取 |
| H5 | Reviewer Submission 页 | 审稿人提交 | Writing 页显示提交表单 | `/api/writing/submit` | git status (ReviewerSubmission.tsx) | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现：页面存在；未定位 `/api/writing/submit` |
| H6 | 引用跳转 PDF | Citations 点击 → PDF Reader | Citations 列表项点击跳转 | 前端路由 + locator API | chunk-page-locator L4 | 是/P0 必做 | Codex(UI) | ⚠️ 部分实现：通用 evidence/citation anchor 跳转能力存在；SourcesCitations 页点击跳 PDF 未静态定位完整 |
| H7 | 大纲自动生成 | AI 生成大纲 | Outline 页显示"生成"按钮 | `/api/writing/outline/generate` | writing-outline-generation | 是/P1 应做 | Claude→Codex | ❓ 未定位 |
| H8 | 引用自动补全 | AI 推荐引用 | Citations 页显示推荐列表 | `/api/writing/citations/suggest` | writing-citation-suggest | 是/P1 应做 | Claude→Codex | ❓ 未定位 |
| H9 | 图表自动生成 | AI 生成图表 | Figures 页显示"生成"按钮 | `/api/writing/figures/generate` | writing-figure-generation | 可延后/P2 | Claude→Codex | ❓ 未定位 |
| H10 | 写作项目导出 | 导出 Word/LaTeX/PDF | Writing 页显示导出按钮 | `/api/writing/export` | writing-export | 是/P1 应做 | Claude→Codex | ⚠️ 部分实现/契约不一致：`/resources/project/{project_id}/export` 支持 JSON/Markdown academic export；未定位 Word/LaTeX/PDF |

---

## I. 设置与凭证 (Settings / Credentials / Sampling)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| I1 | Settings 统一 API 配置 | 单一入口配置所有 API | Settings 页显示 API 配置区 | `/api/settings` CRUD | settings-unified-api-config | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现：Settings 有 Chat/Embedding/Rerank/Credentials 等分区；未定位统一 `/api/settings` CRUD |
| I2 | Settings 清理 | 移除废弃配置项 | Settings 页无废弃项 | 后端移除废弃字段 | settings-cleanup | 是/P1 应做 | Codex(UI) | ⚠️ 部分实现：语义路由合并 embedding/rerank；仍需浏览器审查确认无废弃项 |
| I3 | Credentials 统一 | 凭证管理统一入口 | Settings → API 凭证 | `/api/credentials` CRUD | credentials-unification | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`CredentialsSection` + `/api/credentials` CRUD/test |
| I4 | Credentials 列表/详情 | 列表进入详情子界面 | Credentials 列表 → 详情页 | 前端组件内状态 | settings-smartread-ui-followup credentials slice | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`CredentialsSection` 列表/选中详情状态 |
| I5 | Credentials 采样 B8 | 采样端点 `/api/credentials/sample` | 无前端 UI (后端 API) | `/api/credentials/sample` 200 OK | 0182-release B8 | 是/P0 必做 | Claude | ✅ 已完成 (2026-05-26 commit b5b0ca3e + cc0da047)：与 D2 同一实现。`POST /api/credentials/sample?category={generation|embedding|rerank}&strategy_hint={tier}` 按 category + strategy_hint 选择凭证；精确匹配优先（双向 normalize 确保 legacy stored credential 能被 canonical query 命中），回退到最高 priority；返回 `RuntimeCredentialPublic` (masked api_key, canonical strategy_hint)；11 测试覆盖精确匹配/legacy 映射/priority 回退/category 过滤/无可用凭证 404/默认值/掩码/legacy 兼容 (`tests/test_credentials_sampling.py`)；代码：`literature_assistant/core/routers/credentials_router.py:208-261` sample_credential endpoint；验证：`pytest tests/test_credentials_sampling.py -v` 11/11 passed |
| I6 | Credentials 档位配置 | 默认成本档位配置 | Credentials 详情显示档位选择器 | `default_cost_tier` 字段 | settings-smartread-ui-followup tier slice | 是/P0 必做 | Claude→Codex | ⚠️ 部分实现/字段不一致：有 `strategy_hint`；未定位 `default_cost_tier` |
| I7 | Credentials 模型路由偏好 | Claude Max / Codex XHigh / Codex Fast | Credentials 详情显示路由说明 | `CredentialStrategyHint` enum | settings-smartread-ui-followup tier slice | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`CredentialStrategyHint` 包含 fast/quality/xhigh/max/discussion/embedding/rerank |
| I8 | Settings 语义路由说明 | 同时覆盖 embedding + rerank | Settings → 语义路由 说明文案 | 无后端变化 | settings-smartread-ui-followup copy slice | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`SectionSemanticRouting` 说明 embedding + rerank |
| I9 | Settings 功能开关说明 | 不暴露实现路径 | Settings → 功能开关 用户友好文案 | 无后端变化 | settings-smartread-ui-followup copy slice | 是/P1 应做 | Codex(UI) | ⚠️ 部分实现：功能开关 UI 与 copy 存在；仍需浏览器验收文案是否泄露实现路径 |
| I10 | Settings 输出路径 | 默认安装目录内输出 | Settings → 输出路径 显示默认值 | `project_paths.py` 默认路径 | settings-smartread-ui-followup copy slice | 是/P1 应做 | Codex(UI) | ⚠️ 部分实现：`project_paths.py` 规范存在；Settings 输出路径展示需浏览器核验 |

---

## J. 扩展生态 (MCP / Skill 安装与运行)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| J1 | MCP v0.3 支持 | 支持 MCP v0.3 协议 | 无前端 UI | `mcp_client.py` v0.3 | mcp-v0.3-support | 是/P1 应做 | Claude(后端/接口) | ✅ 已完成：mcp SDK 1.27.0 (protocol 2025-11-25) > v0.3；ClientSession/StdioServerParameters/stdio_client 已集成 |
| J2 | MCP v0.4 支持 | 支持 MCP v0.4 协议 | 无前端 UI | `mcp_client.py` v0.4 | mcp-v0.4-support | 是/P0 必做 | 维护 | ✅ 已实现（静态定位）：`STREAMABLE_HTTP`、pending tool approval、audit/routes 存在 |
| J3 | MCP Vision 辅助 | Vision 模型辅助 MCP 工具 | 无前端 UI | `mcp_vision_aux.py` | mcp-vision-aux | 可延后/P2 | Claude(后端/接口) | ❓ 未定位 |
| J4 | MCP Tool-use UX | 工具使用体验优化 | 前端显示工具调用状态 | 后端返回工具调用详情 | mcp-tool-use-ux | 是/P1 应做 | Claude→Codex | ✅ 后端完成：`GET /api/mcp/pending-calls` + `POST /api/mcp/pending-calls/{id}/decide` + audit；前端 modal 需 Codex 浏览器验证 |
| J5 | MCP 本地安装器 A | 扫描本地 MCP 包 | 无前端 UI | `mcp_scanner.py` | mcp-local-installer A | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`POST /api/mcp/installations/scan` + package scanner |
| J6 | MCP 本地安装器 B | 前端配置 UI | Settings → MCP 安装 | 前端 MCP 配置表单 | mcp-local-installer B | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`McpInstallWizard` local install/config/credential binding |
| J7 | MCP 本地安装器 C | 安装/探测/信任确认 | Settings → MCP 显示信任确认弹窗 | `/api/mcp/install` | mcp-local-installer C | 是/P1 应做 | Claude(后端/接口) | ✅ 已完成：实际端点 `POST /api/mcp/installations/install` (scan/preview/install 三阶段)；McpTemplateInstaller stdio 安装 + 信任确认 |
| J8 | MCP Per-agent scope | 每个 Agent 独立 MCP 配置 | 无前端 UI | `mcp_config` 按 agent_id 隔离 | mcp-per-agent-scope | 是/P1 应做 | Claude(后端/接口) | ✅ 已完成：`McpScopeType` (surface/agent) + `DiscussionMcpOverrides.per_agent/per_role` + discussion_advanced_router agent_id 隔离逻辑；5 tests passed |
| J9 | Skill 安全评估 | Skill 安装前安全检查 | Settings → Skill 显示安全评分 | `skill_security_assessor.py` | skill-security-assessment | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`GET /skills/{skill_id}/security` + SkillManager/security policy |
| J10 | Skill 沙箱 | Skill 运行沙箱隔离 | 无前端 UI | `skill_sandbox.py` | skill-sandbox | 是/P1 应做 | Claude(后端/接口) | ✅ 已完成：skill_executor.py `_execute_scripted` subprocess 隔离 + timeout + SKILL_SANDBOX=1 env + 输出截断；safe_to_execute 安全策略阻断 |
| J11 | Skill 导入/导出 | Skill 包导入导出 | Settings → Skill 导入/导出按钮 | `/api/skill/import` `/api/skill/export` | skill-import-export | 是/P1 应做 | Claude→Codex | ✅ 已完成 (2026-05-26)：`POST /skills/import` 已存在；新增 `POST /skills/{skill_id}/export` 端点；`WritingSkillService.export_user_skill` 方法将 skill 目录打包为 zip（从 `default_parameters.installed_path` 读取路径）；默认输出到 `workspace_artifacts/skill_exports/{skill_id}.zip`，支持自定义 output_path；拒绝导出 builtin skill (400)；`SkillExportResponse` 模型返回 success/export_path/errors；9 测试覆盖端点成功/自定义路径/skill 不存在 404/builtin 拒绝/服务失败 500/zip 创建验证/默认路径/builtin 错误/不存在错误 (`tests/test_skill_export.py`)；代码：`skills/service.py:559-626` export_user_skill 方法，`models/skills.py:254-264` SkillExportResponse，`routers/skills_router.py:303-355` export 端点；验证：`pytest tests/test_skill_export.py -v` 9/9 passed；前端 Settings 导出按钮待 Codex 实现 |
| J12 | Skill 审批流程 | Skill 安装需审批 | Settings → Skill 显示审批按钮 | `skill_approval_workflow.py` | skill-approval | 是/P1 应做 | 维护 | ✅ 已实现（静态定位）：`/skills/approvals/*` 申请/待审/决策链路 |

---

## K. 发布与运维 (Release Gate / Soak / Runbooks)

| ID | 功能 | 期望效果 | 前端验收点 (界面是否齐) | 后端验收点 (链路是否通) | 来源 plan | 文献助手必要性/优先级 | 执行方 | 状态 |
|----|------|----------|------------------------|------------------------|-----------|----------------------|--------|------|
| K1 | Release Gate | 发布前检查清单 | 无前端 UI | `release_gate.py` 通过 | release-gate | 暂缓/P3 | 暂缓 | ⚠️ 部分实现/命名不一致：有 release secret/forbidden/frozen smoke/build 脚本；未定位 `release_gate.py` |
| K2 | Public Push 边界检查 | 推送前检查敏感文件 | 无前端 UI | `git diff --cached --check` + forbidden-path | git-branch-hygiene (memory) | 暂缓/P3 | 维护 | ✅ 已实现（静态定位）：工作区规则 + `release_forbidden_path_scan.py`/secret scan 脚本 |
| K3 | Bundle Split | 前端 bundle 拆分优化 | 前端 bundle 体积 < 阈值 | `npm run build` 输出分析 | bundle-split | 可延后/P2 | Claude(后端/接口) | ⚠️ 部分实现：bundle split plan 与 lazy routes 存在；本轮未跑 build/体积验收 |
| K4 | God-module Split | 后端大模块拆分 | 无前端 UI | 模块行数 < 阈值 | god-module-split | 可延后/P2 | Claude(后端/接口) | ⚠️ 部分实现：resources router 已拆 endpoints；未做全仓模块行数验收 |
| K5 | Router Prefix | API 路由前缀统一 | 无前端 UI | 所有路由 `/api/*` | router-prefix | 暂缓/P3 | 暂缓 | ⚠️ 部分实现/决策为混合保留：`docs/architecture/router-prefix-convention.md`，当前仍有 `/resources`、`/evolution`、`/memory` |
| K6 | Audit Fixes (9 commits) | 0.1.8.2 bug 修复 | 各页面 bug 修复验证 | 9 个 commit 验证通过 | 0182-release 9-commit list | 暂缓/P3 | 暂缓 | ❓ 未定位：本轮未核 git commit list/验证 |
| K7 | Identity Injection | 身份注入修复 | 无前端 UI | `identity_injector.py` | identity-injection | 暂缓/P3 | 暂缓 | ❓ 未定位 |
| K8 | Baseline Anchor | 基线锚点建立 | 无前端 UI | `baseline_anchor.py` | baseline-anchor | 暂缓/P3 | 暂缓 | ⚠️ 部分实现：`docs/plans/active/2026-05-24-0182-baseline-anchor.md` 存在；未定位脚本 |
| K9 | Soak Gate | 发布后浸泡测试 | 无前端 UI | `soak_gate.py` 通过 | soak-gate | 暂缓/P3 | 暂缓 | ⚠️ 部分实现/命名不一致：`scripts/soak_dispatch_path.py` 存在；未定位 `soak_gate.py` |
| K10 | Runbooks | 运维手册 | 无前端 UI | `docs/plans/runbooks/` 文档齐全 | docs/plans/README.md | 暂缓/P3 | 维护 | ✅ 已实现（静态定位）：`docs/plans/runbooks/` 存在多项执行/发布/功能 runbook |

---

## 统计摘要

- **总计**: 145 功能点
- **模块分布**: A(11) + B(8) + C(16) + D(23) + E(16) + F(13) + G(16) + H(10) + I(10) + J(12) + K(10) = 145 行
- **状态**: 已按静态代码证据更新为 ✅ / ⚠️ / ❓；这不是 E2E 验收结果
- **下一步**: 先修正“已部分实现但用户可见不达标”的 H3/H4/G，再补 D/J/K 的契约缺口

---

## 使用说明

1. **验收流程**: 实现功能后，先验证前端界面是否齐全，再验证后端链路是否联通
2. **状态更新**: ✅ = 静态定位支持或前端+后端验收通过 | ⚠️ = 部分完成/契约不一致 | ❌ = 明确未实现 | ❓ = 待验证/未定位
3. **来源追溯**: "来源 plan" 列可追溯到 `docs/plans/active/` 具体计划文件
4. **功能统计优先级**: 本文件是 145 项功能的当前验收入口，优先级高于零散历史计划；后续每次执行前先对照本文件选 slice，每次执行后必须回到本文件更新状态、代码定位、验证结果和下一步判断
5. **持续更新**: 每次 slice / sprint 结束后更新本矩阵，保持与实现同步；如果实现发现某项不是文献助手当前需要的功能，改优先级而不是直接删除
6. **证据要求**: 不能只因代码存在就改 ✅；✅ 必须写清前端入口、后端/API 链路、关键代码定位和至少一个验证方式。未跑浏览器或后端测试时，状态说明里必须保留“静态定位”或“待验收”
7. **回档要求**: 修改本文件前要按 `AI_WORKSPACE_GUIDE.md` 建立回档点；`docs/` 当前被忽略，除 git checkpoint 外还应保留目标文件实体快照到 `.rollback_snapshots/`

---

## 本轮代码定位索引（2026-05-26 静态对照）

- 路由注册：`literature_assistant/core/python_adapter_server.py:674`-`702` 注册 resources、wiki、discussion、credentials、MCP、evolution、feature flags。
- SmartRead：`literature_assistant/core/routers/intelligent_chat_router.py:1410` `/api/chat`，`:1427` `/api/chat/stream`，`:1928` sessions，`:1958` resume；`literature_assistant/core/routers/chat_router.py:862` deprecated `/chat/ask`；`literature_assistant/core/chat/pipeline.py:534`、`:688` session/evidence helpers；`frontend/src/pages/Dialog.tsx:709` `Conversation`。
- Chunk locator / evidence jump：`literature_assistant/core/routers/resources_router/endpoints_search_upload.py:363` `/resources/chunks/{chunk_id}/locator`；`frontend/src/components/evidence/EvidencePill.tsx:107` locator upgrade，`:122` 跳 `/workbench/paper/:materialId`。
- Workbench / PDF：`frontend/src/components/workbench/ResearchWorkbenchInspector.tsx:52` Inspector；`frontend/src/components/PdfViewer/PdfViewer.tsx:2` react-pdf/pdfjs，`:453` selection rects，`:572` continuous pages；`frontend/src/components/PdfViewer/PdfReaderShell.tsx:94` highlights/notes/outline shell。
- Discussion：`literature_assistant/core/routers/discussion_advanced_router.py:304` run，`:334` stream，`:558` get run，`:576` resume stream；`literature_assistant/core/discussion_orchestrator.py:654` evidence pack，`:721` auto-stop，`:783` parallel round，`:1083` analysis chain；`frontend/src/components/DiscussionPanel/DiscussionPanel.tsx:914` evidence pack UI，`:968` cited evidence pills。
- Inspiration：`literature_assistant/core/routers/inspiration_router.py:123` `SparkEvidenceRef`，`:155` evidence refs builder，`:753` generate，`:876` context；`frontend/src/components/inspiration/SparkEvidencePills.tsx:33` evidence refs UI；`frontend/src/components/inspiration/InspirationGraphSection.tsx:31` graph section。
- Evolution / Memory：`literature_assistant/core/routers/evolution_router.py:80` candidates，`:158` accept，`:167` reject，`:185` rollback，`:194` promote，`:236` curate，`:327` manual capture；`literature_assistant/core/evolution/store.py:101` candidates table；`literature_assistant/core/evolution/promotion.py:161` MemPalace add_memory；`literature_assistant/core/routers/memory_router.py:33` `/memory/search`。
- Wiki：`literature_assistant/core/runtime_env.py:103` wiki 默认关闭；`literature_assistant/core/routers/wiki_router.py:311` status，`:338` compile，`:387` query，`:456` pages，`:494` doctor，`:501` graph，`:509` review；`frontend/src/pages/WikiWorkbench.tsx:272` 当前 `WikiKnowledgeFlowCard`；`frontend/src/components/wiki/*` 对应 status/pages/doctor/graph/review panels。
- Writing：`literature_assistant/core/routers/resources_router/endpoints_projects.py:30` projects，`:293` sections；`endpoints_materials_drafts.py:31` materials，`:151` draft citation anchors；`endpoints_search_upload.py:307` figure/table candidates；`endpoints_export_stats.py:19` project export；`frontend/src/pages/writing/SourcesCitations.tsx:24`，`FiguresTables.tsx:25`，`frontend/src/components/writing/ReferenceDrawer.tsx:99` export/citation chain，`WritingCanvas.tsx:111` insert citation token。
- Settings/Credentials：`literature_assistant/core/routers/credentials_router.py:44` `/api/credentials`，`:69` list，`:84` create，`:200` test；`literature_assistant/core/models/credentials.py:39` strategy enum；`frontend/src/pages/Settings.tsx:452` smart read cost tier，`:992` rerank config，`:1704` discussion defaults；`frontend/src/components/settings/CredentialsSection.tsx` credentials UI。
- MCP/Skill：`literature_assistant/core/models/mcp.py:35` `STREAMABLE_HTTP`；`literature_assistant/core/routers/mcp_router.py:91` servers，`:497` pending calls，`:509` decide；`mcp_installer_router.py:151` scan，`:216` install；`skills_router.py:74` approvals，`:112` security，`:209` import，`:263` uninstall/rollback snapshot path。
- Release/Ops：`scripts/release_forbidden_path_scan.py:1`，`scripts/release_secret_scan.py:47`，`scripts/build_windows_exe.ps1:1`，`scripts/smoke_frozen_first_launch.py:95`，`scripts/soak_dispatch_path.py:195`，`docs/architecture/router-prefix-convention.md`。

---

## 结论与下一步

1. **先补 AI 基础设施**：凭证采样/档位、模型路由、MCP 协议兼容、工具审批、Agent 权限隔离、Skill 沙箱、Wiki 权限是 AI 可用性与安全边界，不再按边缘生态延后。
2. **再修 Wiki 边界与后端能力**：Wiki 不是 Evolution 入口。当前 `WikiKnowledgeFlowCard` 容易把 Wiki 解释成“沉淀/演化流”，应改成“证据支撑的编译知识层”：状态、页面、Doctor、Graph、Review、dry-run compiler。后端默认关闭 `LITERATURE_ASSISTANT_WIKI_ENABLED` 是导致“Wiki 集成尚未启用”的直接原因；要么在设置/状态页明确启用方法，要么做可控启用入口。
3. **再修写作 H4 图表管理**：当前只显示题注和文献名，本质是“从切块文本里识别出的候选”，不是图表资产管理。下一步应隐藏 raw context/chunk ID，显示候选类型、页码、来源、是否有 `bbox`/`asset_path`、定位到 PDF 的动作；真实图表裁剪、CRUD、编号、引用绑定另开后端 slice。
4. **同步澄清 H3 来源与引用**：现在的引用功能是 draft 内 citation anchor/source 管理与 export preview，不等于 Word 的“交叉引用”。Word 式交叉引用通常指向标题、题注、书签等文档内部对象；参考文献目录来自 citation source 元数据和 bibliography 生成。当前项目还没有自动参考文献目录；文献显示优先来自 material title/metadata，缺失时才会退到文件名。
5. **随后补 Discussion/Task Center**：D12-D16 历史归档、分页、搜索、导出、删除未定位；D1 运行时凭证选择需要把 Settings profile 的能力接到 Discussion 面板用户流。
6. **最后做契约清理**：矩阵里大量 `⚠️` 来自路径不一致，例如 `/api/evolution/*` vs `/evolution/*`、`/api/writing/*` vs `/resources/*`、`/api/wiki/search` vs `/api/wiki/query`。要么更新矩阵为现行契约，要么实现兼容 alias，避免后续验收反复误判。

---

## Claude 长跑提示词（后端与接口）

把下面整段复制给 Claude。它的范围是后端、数据模型、API 契约、OpenAPI/类型客户端和接口测试；前端 UI、交互逻辑、布局、浏览器验收由 Codex 接续完成。

```text
你在 C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script 工作。请进入自决策长跑模式，但只做本提示授权的本地代码工作。

硬性前置：
1. 先读 AI_WORKSPACE_GUIDE.md、docs/plans/autonomous-execution-planning-playbook.md、docs/plans/2026-05-26-functional-acceptance-matrix.md。
2. 执行 git status --short --branch，确认 dirty worktree。不要回滚、覆盖、格式化或删除你没改的文件。
3. 每个非平凡 slice 开始前建立回档：优先用本地 checkpoint；涉及 docs/plans/2026-05-26-functional-acceptance-matrix.md 时，还要复制实体快照到 .rollback_snapshots/。
4. 每个 slice 设计前搜索官方或成熟方案。按 slice 选择 FastAPI/Pydantic/Starlette SSE、MCP 官方协议、凭证/权限/沙箱安全实践、引用/参考文献管理、需求追踪矩阵等主来源。记录你参考了什么，不要复制外部代码。

工作入口：
- 以 docs/plans/2026-05-26-functional-acceptance-matrix.md 为唯一功能队列入口。
- 只处理“状态不是 ✅”且“文献助手必要性/优先级”为 是/P0 必做 或 是/P1 应做 的行。
- 你优先处理“执行方”为 Claude(后端/接口) 或 Claude→Codex 的行；Codex(UI) 行只允许补后端契约、OpenAPI schema、类型客户端，不做页面布局和视觉。
- 每个 slice 结束必须回写该矩阵：状态、代码定位、验证命令、剩余缺口、下一步。不要写“矩阵已闭合”。

最高优先级顺序：
1. AI 基础设施与权限协议：
   - B5、I5、I6：凭证采样、默认成本档位、后端枚举/前端类型契约统一。
   - D1、D2：Discussion 运行时凭证选择与采样接口契约。
   - J1、J4、J7、J8、J10、J11：MCP v0.3/v0.4 兼容证据、工具审批/状态、安装探测、per-agent scope、Skill 沙箱、导入导出。
   - G14：Wiki 页面访问控制的后端模型与 API，先做可本地验证的最小权限层，不接生产身份系统。
2. Wiki 后端与接口：
   - G1、G2、G5、G6、G7、G11、G12、G15：页面存储/CRUD、query/search alias、版本历史、compiler 非破坏性提交路径、标签/分类、导出。
   - 保持 Wiki 为“证据支撑的编译知识层”，不要把它收窄成 Evolution 入口。
3. 写作后端与接口：
   - H1-H5、H7、H8、H10：/api/writing/* 兼容 alias 或矩阵契约修正，项目/大纲/引用/图表/审稿提交/大纲生成/引用建议/导出。
   - H3 当前不是 Word 交叉引用和自动参考文献目录；若实现，先补 source metadata、citation anchor、bibliography export 的后端数据模型和 API。
   - H4 当前是文本派生候选；若实现图表管理，先补 figure/table asset CRUD、编号、source/bbox/asset_path、PDF locator 契约。
4. 证据链与定位：
   - A4、A5、A7、D5、D8、E6、E10：独立 evidence refs/source_labels、chunk locator bbox、evidence pack 持久化、引用重叠检测、source_labels 过滤。
5. Discussion 历史与任务中心能力：
   - D10-D18：历史上限、归档、分页、只读查看、搜索、导出、删除、持久化、stream path 兼容。

实现规则：
- Active backend 只在 literature_assistant/core/ 下改。
- API 路由优先兼容现有调用；新增 alias 时保留旧路由，不做破坏性改名。
- Pydantic 模型要有明确类型、边界校验和向后兼容默认值。
- OpenAPI 或前端服务/类型客户端如果受影响，可以更新；但不要改 UI 页面、布局、视觉、浏览器交互。
- 真实凭证、真实 token、runtime credential store 内容、.env 不得打印或写入文档。
- 需要外部服务、生产权限、付费调用、push/tag/release/upload、破坏性删除或产品方向判断时停止并记录 blocker。

验证梯度：
- 每个后端 slice 至少运行 Python compile 或 focused pytest。
- 路由/API slice 用 TestClient 或现有 router tests 验证 schema、错误边界、兼容 alias。
- 影响 OpenAPI/前端类型时运行前端 build 或最小 typecheck/build。
- 建议默认命令：
  - .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py
  - .\.venv-1\Scripts\python.exe -m pytest <focused tests> -q
  - npm run build（在 frontend/ 下，仅当改到前端类型、service、generated client 时）
  - git diff --check -- <changed files>

每个 slice 的完成记录：
- 变更文件。
- 对应矩阵 ID。
- 代码定位：文件:行。
- 验证命令与结果。
- 是否改了 docs/plans/2026-05-26-functional-acceptance-matrix.md。
- 回档 checkpoint/snapshot 路径。
- 下一批可继续的矩阵 ID。

继续规则：
- 完成一个 slice 且验证通过后，直接进入下一项 P0/P1 Claude 后端/API slice。
- 如果某项被阻塞，写清 blocker 并转入下一项独立安全任务。
- 不因为一个 slice 完成就停；只在所有授权项完成或触及停止条件时停。
```

### 给 Codex 的接续边界

- Claude 完成后端/API/类型客户端后，Codex 负责 UI、交互、布局和浏览器验收。
- Codex 接手优先顺序：Wiki UI 边界与启用状态、H4 图表管理界面、H3 来源与引用说明和交互、Discussion 历史/凭证选择 UI、Settings 权限与协议可见状态。
- Codex 每次接手前也必须先对照本矩阵，执行后回写状态、代码定位和浏览器验收结果。

### 本轮参考依据

- Claude Code 官方 common workflows：用于长任务、代码库探索、测试、文档和计划式执行提示词结构。
- Agile Business Consortium MoSCoW prioritisation：用于 P0/P1/P2/P3 的需求优先级口径。
- Requirements traceability matrix 成熟实践：用于把功能、验收、状态、代码定位和验证记录绑定到同一矩阵。
