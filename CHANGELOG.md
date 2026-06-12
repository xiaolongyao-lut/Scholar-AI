# Changelog

## Unreleased

本版本核心是把 RAG 检索链做强、把"实验性功能"开关默认打开，并补上后端日志查看器和本地推理回退。

### 检索质量（RAG）

- **结构化兄弟块召回（A15 链）**：rerank 之前先按 chunk 类型加权（表 ×3 / 公式 ×2 / 段落 ×1 / 标题 ×0.5），让真正含数值和方程的块更容易进 cross-encoder 池。命中之后会把同一章节里相邻的表/公式作为"兄弟块"一起送进 LLM 上下文，保证答案里能引用真实表格数值而不是泛泛复述（例如 "0.4990→0.0357 h⁻¹ 降低 14 倍" 真表数据）。
- **段落标题缺失时的兜底**：旧的 PyMuPDF 入库结果里章节标题字段可能是空的，新增 `section_title` fallback 让兄弟块召回链对这部分老文献依然有效。
- **TOLF × RAG 融合（RRF）**：把"目标导向检索（TOLF）"和传统 hybrid_search 用 RRF（k=60）融合，替代原来的"TOLF 命中就用 TOLF、否则退回 RAG"二选一。两条检索路径互补、互不替代。
- **5 个 RAG 实验开关默认打开**：`hybrid_retrieval`、`rag_chunk_type_weighting`、`rag_structured_sibling_inclusion`、`tolf_context`、`tolf_fusion_mode` 出厂全部 ON，原有用户的 `feature_flags_override.json` 仍生效。设置 → 实验性功能里能看到产品语言文案（不暴露 BM25 / RRF 等内部术语）。

### 设置 → 后端日志

- **新增「后端日志」分区**：直接在设置里查看 `backend.log`，支持按级别（INFO / WARNING / ERROR / CRITICAL）阈值过滤、关键字搜索、行数选择、5 秒自动刷新、一键复制。终端配色，连续行（如堆栈）正确归到上一条日志。
- **凭据二次脱敏**：API key（`sk-*`）和 Bearer token 进入查看器前被强制脱敏一次，即使早期启动阶段日志过滤器漏挂也兜得住。
- **路径越权保护**：日志路径解析只允许读 `runtime_state/logs/` 下的 `backend.log` 系列文件，禁止任意路径读取。

### 本地推理回退

- **rerank 自动用 GPU**：如果本地装了 CUDA 版 PyTorch（例如 cu126 + RTX 系列），rerank 回退会自动选 cuda 设备，否则用 CPU。`LOCAL_RERANK_DEVICE` 环境变量可强制覆盖（`cpu` / `cuda` / `cuda:0`）。
- **embedding 加同款本地回退**：云端 embedding API 失败时（DNS 屏蔽 / 403 / 限流 / 完全离线），自动回退到本地 SentenceTransformer（默认 `BAAI/bge-m3`），在 cuda 或 cpu 上跑。env 变量与 rerank 同形态（`LOCAL_EMBEDDING_MODEL_NAME` / `DEVICE` / `BATCH_SIZE` / `DISABLED` / `ALLOW_DOWNLOAD`），不需要联网。
- **回退链**：远端 API → 本地 GPU/CPU 模型 → hybrid_score 兜底，任一环节失败都不会让对话或入库挂掉。
- **状态可视化**：设置 → Rerank 卡片 + Embedding 卡片头部各加 4 色 chip，显示当前回退链路状态（绿=本地可用 / 黄=需下载 / 灰=已禁用 / 红=不可用），hover 看完整说明。换模型操作手册见 `docs/local-rerank-fallback-models.md`。
- **参考服务器脚本**：`local_rerank_server.py` 和新加的 `local_embedding_server.py`，让用户能在另一台机器跑独立的本地推理服务，App 通过 OpenAI 兼容协议消费。

### 智能研读 → 引用链路标签

- **每条引用显示"怎么被召回的"**：MessageBubble 的证据 chip 上多了一个小标签，告诉用户这条引用是怎么进入答案上下文的：「上下文兄弟」=同章节相邻表/公式被一起拉进来，「语义匹配」=向量相似度，「关键词」=BM25 命中，「深度检索」=TOLF 多角度发散。鼠标 hover 可以看到完整召回链路。
- chat 默认显示，其他场景（Workbench、讨论面板等）保持不显，避免视觉过载。

### 工程基础设施

- **PyInstaller 打包修复**：补 `routers.diagnostics_router`、`local_rerank_adapter`、`local_embedding_adapter` 到 hiddenimports；这几个模块是新加的日志查看器和本地回退入口，缺失会让 onedir 安装版启动时 ImportError。已用真跑 PyInstaller onedir 验证 onedir 里 import 路径正确。
- **前端代码质量**：ESLint `--max-warnings 0` 现在零错零警告通过，CI 流水线打通。`@typescript-eslint/no-unused-vars` 跨 22 个文件清理（lucide 未用图标真删、业务 WIP 占位变量加 `_` 前缀保留）。`no-console` 允许 `error`/`warn`/`info`，仍禁 `console.log`。`@typescript-eslint/no-explicit-any` 收紧到产品代码，测试文件的 mock fixture 在 lint 层归 ignore。
- **测试覆盖**：后端 3883 单元 + 集成测试全过；新增端到端 redact 回归测试覆盖"日志过滤器漏挂时日志查看器二层兜底"场景；新增本地 embedding adapter 11 个 case 覆盖禁用 / 无权重 / 状态契约 / cuda 探测等。前端 vitest 119 测试文件 / 730 个 case 全过。

## 0.1.8.3 - 2026-06-10

发布加固补丁：

- 默认关闭生产环境 OpenAPI schema 暴露，只有 `LITASSIST_ENABLE_DOCS=1` 时才返回 `/openapi.json`。
- PyInstaller 打包前过滤运行时目录、日志、审批/审计/回档目录、私钥和凭证类文件，降低从开发工作区误带敏感数据的风险。
- Windows 发布脚本改用 .NET SHA256 计算发布件哈希，避免依赖当前 PowerShell 环境中不可用的 `Get-FileHash`。
- 发布门禁测试加入显式源码白名单，避免回归测试被 `/tests/*` ignore 规则静默排除。
- Windows 主程序文件名统一为 `Scholar-AI.exe`，和安装包、快捷方式品牌名保持一致。

## 0.1.8.2 - 2026-05-23

新增「实验性功能」设置分区，把后端实验能力的开关搬到 UI。本版本第一个加入的是 TOLF 检索切换。

### 新增

- **设置 → 实验性功能**：左侧 sidebar 新增一个分区，专门放尚未默认开启的实验能力。开关写到 `runtime_state/feature_flags_override.json`，改完立即生效，不需要重启。
- **TOLF 目标导向检索（默认关闭）**：在「实验性功能」里开启。把问题拆成 4 个角度（背景 / 方法 / 结果 / 贡献）、在文献关系图上扩散 3 跳、按硬证据（带数值的内容）筛选。比默认 RAG 更慢，但能找到间接证据、归因清晰、抗弱化措辞。适合综述、找数据、深度调研。同一问题分别开 / 关跑一次即可直观对比效果。
- **Feature flags REST API**：`GET /api/feature-flags` 列出全部开关；`POST /api/feature-flags/{name}` 修改并持久化。后续实验能力按同样模式登记即可，不需要新建文件。

### 兼容

- 原 `INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED` 环境变量仍然有效，作为 UI 开关的兜底。优先级：UI 开关 > 环境变量 > 默认。

## 0.1.8.1 - 2026-05-23

PDF 阅读体验大改 + 数据/日志集中化 + 批量上传去重。原版 0.1.8.1（仅 PDF 错误提示 + 数据合并）发布后追加的内容统一收口到本版本。

### PDF 阅读器（重做）

- **多 PDF 标签页**：可以同时打开多篇文献，顶部横向标签条无数量上限，超出可滑动。同一篇 PDF 重复打开会自动复用已有标签页，不再产生重复加载。后台只保留少量最近 PDF 字节在内存，切换瞬间恢复；其他标签页只占一个 UI 行，不占内存。
- **上下连续滚动**：删除「‹ ›」翻页按钮，PDF 渲染成一长条，鼠标滚轮 / 触控板自然滚动。可视区域占比最大的页自动成为「当前页」。
- **页码可点输入跳转**：顶部页码点一下变输入框，回车即跳到任意页。
- **PDF 内部链接同窗口跳转**：正文里蓝色 `[14]`、`Fig. 3`、章节目录等内部引用，点一下直接平滑滚动到目标页，并短暂蓝色高亮提示落点。外部 http 链接仍新开标签页。
- **PDF 加载失败现在能看到原因**：以前只显示"PDF 加载失败"，现在会显示具体出错原因，下方有"重试"按钮。
- **PDF 高亮**：选中文本→标记会显示半透明黄色覆盖层，按页面归一化坐标，缩放不失真，重新打开仍在原位。
- **PDF 文本选中"重影"修复**：某些字体在选中时会因为浏览器默认行为出现描边，看起来像重影。新版 CSS 强制文本层完全透明，选区用半透明蓝色。
- **深色模式对比度**：PDF 工具栏图标、页码、侧栏开关在深色模式下文字颜色加深，不再灰得看不清。

### 文献库

- **批量上传自动去重**：拖入同一篇 PDF（同名或改名都算）只会入库一份。Summary 区会显示"跳过重复 N"。
- **删除文献会清磁盘**：以前点删除只清索引，留下的源 PDF 文件还在 `source_files/`；现在一起清理。
- **新建/打开项目落地知识库**：以前新建项目直接跳到「写作 - 草稿」页，现在先打开文献库。

### 界面 / 导航

- **侧栏 tab 高亮跟随业务**：在 `/workbench/paper/...` 时「知识库」tab 保持高亮，在 `/dialog` 时「智能研读」保持高亮，wiki / 多 agent 讨论同样处理。之前打开 PDF 后侧栏看起来像离开了知识库区。
- **顶部"当前项目"选择器视觉强化**：项目切换会同时切换文献库、对话历史、写作内容，旧版选择器太低调；新版加 primary 色背景 + 显式"当前项目"前缀 + tooltip 提示。

### 工程基础设施

- **数据 / 日志集中**：安装版的所有数据和日志放在 `%APPDATA%\LiteratureAssistant\`，每个知识库放在 `projects\{项目ID}\` 子文件夹。日志在 `runtime_state\logs\backend.log`（10MB 自动切分，保留 5 份）。
- **dev 端口桥**（开发者向）：后端启动时写 `workspace_artifacts/runtime_state/api-port.json`，vite proxy 逐请求读取，后端换端口或重启时 frontend dev server 不需要重启。Vite dev 端口支持 `VITE_DEV_PORT` 或 `--port` 覆盖。

### 升级提示（只有 0.1.8-alpha 或更早版本的老用户需要操作）

旧版本会把每个项目的索引和切块文件放在 **文献库文件夹里的一个 `.scholarai` 隐藏子目录**中。新版改成 **统一放到 `%APPDATA%\LiteratureAssistant\projects\{项目ID}\` 下**。

如果你想保留旧数据：

1. 在文件资源管理器的地址栏粘贴 `%APPDATA%\LiteratureAssistant\projects\` 回车，确认这个目录存在
2. 找到旧的文献库文件夹，打开里面的 `.scholarai` 子目录
3. 把里面的 `{项目ID}.json` 文件剪切到 `%APPDATA%\LiteratureAssistant\projects\{项目ID}\doc_store\`
4. 把剩下的（`{项目ID}_chunks.json` 或 `{项目ID}` 这个子文件夹）剪切到 `%APPDATA%\LiteratureAssistant\projects\{项目ID}\chunk_store\`
5. 多个项目就重复一遍

**不剪切也没关系**：下次在新版里打开项目，会重新读取一次文献并切块（耗时几分钟到几十分钟，看文献库大小）。新装的用户什么也不用做。

仍想用旧的"索引放在文献库旁边"行为的：启动应用前设置环境变量 `LITASSIST_USE_SOURCE_FOLDER_INDEX=1`。



## 0.1.8-alpha - 2026-05-23

Visual identity refresh on top of 0.1.7-alpha. Packaging-and-brand-only iteration — no backend/frontend behavior change, no OpenAPI contract change vs 0.1.7-alpha.

Highlights:

- **App icon set**: replaced the placeholder emoji favicon with a transparent-corner brand mark. New assets under `frontend/public/`: `favicon.ico` plus multi-size PNGs (16/32/48/64/128/180/192/256/512/1024) and a 1024 master. `frontend/index.html` now references `/favicon.ico` (with `sizes="any"`) + `/app-icon-180.png` (Apple touch).
- **Sidebar brand mark**: left sidebar in `frontend/src/layouts/MainLayout.tsx` shows the new icon in both collapsed (centered) and expanded (icon + title) states; preserves existing motion/`AnimatePresence` behavior.
- **Installer + .exe icon embedding**: `packaging/inno-setup/literature-assistant.iss` now sets `SetupIconFile=..\assets\icon.ico`; PyInstaller spec already referenced `packaging/assets/icon.ico` so the frozen `.exe` carries the same brand mark from this build forward.

Verification recorded locally:

- Frontend build: passed.
- PNG transparency verified: all four corners alpha=0 on `frontend/public/app-icon.png` (512×512 RGBA).
- 9-step release pipeline: forbidden-path scan, secret scan, Inno installer build, frozen first-launch smoke — all passed.
- Rollback snapshot: `.rollback_snapshots/icon-update-20260522_224149/`.

## 0.1.7-alpha - 2026-05-22

Discussion robustness + frontend initial-load split + API contract housekeeping.

Note: this release supersedes the earlier 0.1.6-alpha (created 2026-05-20 with installer base commit `89078ef6`) by adding the Inspiration P3 prep scaffold, the OpenAPI schema rebaseline, and the Workbench / ResearchWorkbench lazy-load split. 0.1.6-alpha's release page is preserved as historical record.

Highlights:

- **Discussion evidence transport (FD-13)**: refactored multi-agent discussion to carry evidence via `ChatRequest.context[]` metadata channel instead of inlining it into `query`. Added discussion-scope budget validator with 422 mapping. Envelope guard now covers `context_items` and the env-supplied `CHAT_SYSTEM_PROMPT`, with `_context_items` private-marker redaction + `dump_metadata_safe_to_log` helper for safe diagnostics.
- **Discussion history cap (FD-14)**: dynamic history budget bounded by the chat envelope; rolling-window cap + write-only answer cap so long sessions cannot silently overflow. Fail-fast on oversized assembled prompts.
- **Chat first-turn envelope (TG-1)**: widened `ChatRequest.query` / `ChatStreamRequest.query` cap to the documented Discussion envelope (80_000) so evidence-laden first-turn prompts no longer fail at the wire; clarifying docstring locked the contract.
- **Pydantic v2 + FastAPI lifespan**: removed `min_items`/`max_items` Pydantic V1 syntax and `@app.on_event("startup")` deprecations; replaced with V2-native equivalents + lifespan context.
- **Frontend initial-load split (Order 3)**: ResearchWorkbench lazy-loads PdfReaderShell (484 KB now on-demand); Workbench lazy-loads TipTapEditor (435 KB now on-demand). Both routes drop well below the Vite 500 kB warning threshold. Each lazy boundary wrapped in a local ErrorBoundary so a chunk fetch failure surfaces as a panel-level fallback instead of full-page crash.
- **OpenAPI schema rebaseline**: single regen of `frontend/openapi/modular-pipeline-openapi.json` + `frontend/src/generated/openapi.ts` to absorb several months of accumulated backend endpoint additions. No API behavior change — purely a generated-artifact refresh so future regens produce small incremental diffs.
- **Inspiration P3 prep scaffold (FD-10 Order 6a)**: shipped `literature_assistant/core/inspiration_p3.py` (288 LOC) with `INSPIRATION_P3_ENABLED` feature flag (default off), Pydantic goldset schema, sha256 cache-key helper, and deterministic precision/recall/F1 metric function. No production wiring; no LLM call; no user-authored goldset required. Cross-field validator rejects goldset entries whose edges reference unknown node ids.

Verification recorded locally per commit:

- Backend active suite: 2297 passed, 43 skipped, 1 xfailed (excludes `tests/legacy_root` which requires `umap-learn`; see local AI workspace guide).
- Frontend build: passed (Vite 6.21 s — 7.43 s across the split slices).
- Frontend unit/integration: 428 tests passed.

## 0.1.5-alpha - 2026-05-19

Public source readiness line for the Scholar AI Workbench.

Highlights:

- MCP pending-call approval flow with backend suspend/resume, frontend approval modal, per-run remember behavior, timeout handling, and audit records.
- Evolution memory pipeline with candidate capture, review queue, promotion path, curator hooks, audit endpoint, and operator UI.
- Evolution visual regression baselines and E2E smoke coverage.
- Discussion evidence tracing and citation overlap helpers.
- Settings API cleanup and provider/model configuration hardening.
- Wiki, retrieval, rerank, and writing runtime path hardening around `literature_assistant/core/`.

Verification recorded locally:

- Frontend unit/integration: 424 tests passed.
- Frontend build: passed.
- Evolution Playwright E2E: 10/10 passed.
- Backend active suite: 2659 passed, 43 skipped, 1 xfailed.
