# Changelog

## 0.1.8.1 - 2026-05-23

PDF 阅读器报错更易读、数据和日志集中到一个地方。

亮点：

- **PDF 加载失败现在能看到原因**：以前不管什么原因都只显示一句"PDF 加载失败"，现在会显示具体出错原因（比如"文件不存在: foo.pdf"或"无原始文件路径记录"），下方有"重试"按钮。
- **所有数据集中到一个文件夹**：安装版的所有日志、所有项目的切块和索引数据，现在都放在同一个根目录下 —— Windows 上是 `%APPDATA%\LiteratureAssistant\`。每个知识库放在 `projects\{项目ID}\` 子文件夹里，互不干扰。同一个项目下做多次卷次分析时，切块是共享的，相关性排序和回答 AI 都能看到全部切块。
- **统一日志文件**：在 `%APPDATA%\LiteratureAssistant\runtime_state\logs\backend.log`。文件超过 10MB 自动切分，保留最近 5 份。后端任何报错、卷次分析的去重统计、前端崩溃都写在这里，遇到问题时直接打开看就行。

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
