# LLM-Wiki RAG 执行决策记录

## 核心决策

### D1: 执行范围
- **决策**：完成全部 240 任务（LMWR-224~463）
- **理由**：用户要求"做完吧"，可以在执行过程中继续编写后续任务
- **影响**：不限于最小闭环，完整实现 Wiki 系统所有功能

### D2: Wiki-first Retrieval
- **默认状态**：可开可关，通过 `ENABLE_WIKI_FIRST_RETRIEVAL` 环境变量控制
- **查询顺序**：wiki FTS → wiki linked pages → wiki embeddings (optional) → raw RAG fallback
- **付费测试**：支持 env 控制的付费测试模式
- **影响**：需要在 `runtime_env.py` 和 `main_rag_workflow.py` 中实现开关逻辑

### D3: Frontmatter 格式
- **决策**：JSON frontmatter (`---json\n{...}\n---`)
- **理由**：严格、易解析、与现有 Python 生态兼容
- **不支持**：YAML frontmatter（暂不支持，后续可扩展）
- **影响**：`wiki/page_store.py` 中 `render_frontmatter` 使用 JSON

### D4: 外部资料源集成
- **是否做**：做（Wave 13）
- **优先级**：Zotero > Obsidian > EndNote（按用户建议）
- **写回策略**：先不做写回，只读索引
- **影响**：Wave 13 任务保留，实现只读 connector

### D5: Graph 存储格式
- **决策**：JSON + SQLite 双模式
  - `graph.json`：人类可读、易调试、版本控制友好
  - `graph.db`：SQLite 表，支持复杂查询（typed edges、blast radius）
- **理由**：兼顾可读性和查询性能
- **影响**：`wiki/graph.py` 需要实现双写逻辑

### D6: API Router 权限模型
- **决策**：用户级权限控制
- **实现**：前端界面用户可选择是否添加 API key
- **状态转换**：Draft → Review → Final 由用户控制（不需要审批流程）
- **影响**：
  - `routers/wiki_router.py` 需要实现用户权限检查
  - 前端需要 API key 管理界面
  - 状态转换 API 需要用户身份验证

### D7: 测试失败修复
- **决策**：先修复所有简单测试失败（包括 27 个 squad_cli）
- **执行顺序**：
  1. 修复 legacy_root 路径问题（13 个）
  2. 修复 squad_cli 命令测试（27 个）
  3. 修复 contextual/export/observability（9 个）
  4. 修复 reranker（3 个）
- **验收**：每个修复后运行 focused tests，确保不引入新失败
- **影响**：Task #15 优先级提升，在 Wave 3 之前完成

## 延续决策

### D8: Wave 执行顺序
按原计划顺序推进：
1. ✅ Wave 0: 治理文档
2. ✅ Wave 1: 数据模型 (23 tests)
3. ✅ Wave 2: Source/chunk registry (27 tests)
4. ✅ Wave 3: Markdown page store (39 tests)
5. ✅ Wave 4: Citation validator (35 tests)
6. ✅ Wave 5: Evidence adapter (26 tests)
7. ✅ Wave 6: Compiler dry-run (10 tests)
8. ✅ Wave 7: LLM gateway integration (15 tests, stub mode)
9. ✅ Wave 8: Wiki-aware retrieval (query pipeline closeout, 47 focused tests)
10. ✅ Wave 9: Graph (232 wiki tests + 54 Wave8/9 focused tests)
11. ✅ Wave 10: Doctor/review queue (247 wiki tests + 69 Wave8/9/10 focused tests)
12. ✅ Wave 11: API contract (15 focused tests)
13. ✅ Wave 12: Frontend Wiki 工作台（七块只读工作台面、citation warnings、evidence_refs deep link、focused UI tests、frontend gate 已收口）
14. ✅ Wave 13: 外部 connector（只读 connector interface、Markdown/PDF skeleton、Zotero/EndNote spec-only、focused 10 tests）
15. ✅ Wave 14: 评测和质量门禁（zero-cost manifest/comparison/citation audit、fixtures、no-secret、cost guard、marker、收口验证）
16. ⏸️ Wave 15: 迁移、MCP、长期维护

**进度**：Wave 11 API contract 已收口；Wave 12 前端 Wiki 工作台已收口；Wave 13 只读 connector 已收口；Wave 14 评测和质量门禁已收口。最新验证为 `pytest tests/wiki -q` → `287 passed`、`pytest tests --collect-only -q` → `1618 tests collected`、`pytest tests/wiki -m wiki_wave14 -q` → `11 passed / 276 deselected`、`system_verification.py --json` → `23 passed / 0 failed / 0 warnings`；前端上一轮验证为 focused `19 passed` + frontend full Vitest `54 passed` + frontend build PASS + `/wiki?page=...` 浏览器 smoke。
**核心能力**：数据模型、注册表、页面存储、引用验证、证据适配、编译器、LLM 网关（stub 模式）、FTS 检索（基础）、wiki API contract、前端 Wiki 只读工作台、外部知识库只读 connector skeleton/spec、zero-cost wiki eval manifest/comparison/citation audit

**Wave 8 收口结果（2026-05-04 Codex）**：
- `LITERATURE_ASSISTANT_WIKI_ENABLED` + `LITERATURE_ASSISTANT_WIKI_FIRST_RETRIEVAL` 已接入 `RAGWorkflow`，默认关闭，未开启时不构建 wiki index。
- Linked page expansion、raw RAG fallback bridge、token-bounded context pack、sanitized query debug trace、explicit saved exploration draft flow 已完成 focused 覆盖。
- 证据包：`.squad/orchestration-log/codex-2026-05-04-lmwr-347-358-wave8-closeout.md`。

**Wave 9 收口结果（2026-05-04 Codex）**：
- `wiki/graph.py` 已实现 typed edge ontology、JSON/SQLite graph store、wikilink parser、frontmatter edge extraction、backlinks、weighted blast radius。
- `wiki/export.py` 已提供 deterministic graph JSON export。
- `WikiGraphStore.default()` 使用 canonical `workspace_artifacts/runtime_state/wiki/graph.json` + `graph.db`。
- 验证：`compileall` 通过；`tests/wiki -q` -> `232 passed`；Wave 8/9 focused -> `54 passed`。
- 回档点：`20260504-172308-lmwr-359-368-wave9-graph-core`、`20260504-172524-lmwr-359-368-wave9-graph-continue`。

**Wave 10 收口结果（2026-05-04 Codex）**：
- `wiki/doctor.py` 已实现机器可读 doctor report、workspace/source/retrieval/citation/graph/review checks、duplicate/orphan/broken-link 检查、safe repair subset。
- `wiki/review_queue.py` 已实现 JSONL review queue、append/list/get/filter、approve/reject 决策记录。
- Safe repair 只创建目录、初始化 registry、重建 retrieval index、重建 graph JSON/SQLite，不修改页面正文，不自动 finalize。
- 验证：`compileall` 通过；`tests/wiki -q` -> `247 passed`；Wave 8/9/10 focused -> `69 passed`。
- 回档点：`20260504-173149-lmwr-374-379-wave10-doctor-core`、`20260504-173456-lmwr-380-382-wave10-review-queue`。

**Wave 11 收口结果（2026-05-04 Copilot）**：

- `WikiStatusResponse` 已补齐 `stale` 字段，status contract 覆盖 `enabled/page_count/stale/paths`。
- compile/query request surface 已锁定 `source_id`、`project_id`、`wiki_first`、`save`、`debug`；`save=true` 明确返回 service integration 边界错误。
- pages list/read/filter、doctor、review、OpenAPI named schema、CLI dry-run wrapper 已完成 focused 合同覆盖。
- focused 验证：`pytest tests/wiki/test_wiki_router.py tests/wiki/test_wiki_cli.py -q` → `15 passed`；CLI smoke 返回 disabled status JSON；相关文件 `compileall` 通过。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-397-wave11-cli-openapi.md`。

**Wave 12 首刀结果（2026-05-04 Copilot）**：

- `/wiki` 页面、侧边栏 `Wiki` 导航与 `Wiki 工作台` header 已落地，前端状态面从零变成可见入口。
- 已执行 `npm run generate:openapi`，前端生成类型纳入 `/api/wiki/status` 与 `WikiStatusResponse` 等 schema。
- `frontend/src/types/wiki.ts` + `frontend/src/services/wikiApi.ts` 提供 generated alias 与 strict runtime parser；`frontend/src/services/wikiApi.test.ts` 锁定 unknown payload 防守。
- `WikiStatusCard` 现已显示 `enabled/stale/page_count`、artifact existence、canonical paths、warnings；后端离线时显示中文错误诊断而非白屏。
- focused 验证：`npx vitest run src/services/wikiApi.test.ts` → `2 passed`；`npm run build` → PASS；浏览器 smoke 通过。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-405-wave12-status-workbench.md`。

**Wave 12 第二刀结果（2026-05-04 Copilot）**：

- `/wiki` 页面现在已接入 `Pages`、`Doctor`、`Review`、`Graph` 四块只读 panel，不再只是状态页。
- `wikiApi.ts` 已扩展到 status/pages/doctor/review/graph 五类 parser，并补齐对应 normalized model。
- `WikiPageListPanel`、`DoctorReportPanel`、`ReviewQueuePanel`、`GraphDebugPanel` 已落地；都遵守“只读优先”的安全边界。
- focused 验证：`npx vitest run src/services/wikiApi.test.ts` → `6 passed`；`npm run build` → PASS；浏览器 smoke 证明五块 panel 可见，且后端离线时显示中文错误诊断。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-408-wave12-readonly-panels.md`。

**Wave 12 第三刀结果（2026-05-04 Copilot）**：

- `WikiPagePreviewPanel` 与 `WikiCompileDryRunPanel` 已落地，`/wiki` 页面现扩展到七块工作台面。
- `WikiPageListPanel` 已支持选中态；`frontend/src/services/wikiApi.ts` 已补 `parseWikiPageDetail` / `parseWikiCompileDryRun` 与对应 loader。
- focused 验证：`npx vitest run src/services/wikiApi.test.ts` → `8 passed`；`npm run build` → PASS；浏览器 smoke 证明 `Wiki 页面预览` 与 `Wiki Compile Dry-Run` 两块新面板可见，且后端异常时仍显示中文错误/空态提示。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-407-wave12-compile-preview.md`。

**Wave 12 第四刀结果（2026-05-04 Copilot + Gemini frontend subagent）**：

- `WikiPagePreviewPanel` 已新增 `文内引用与证据预警` 卡片，先以 read-only 方式展示 citation/evidence 风险，不执行 mutate。
- `extractCitationWarnings` 已从粗略 bracket 判断收紧为 evidence-aware heuristic：识别 `evidence_refs/references`，区分 `[[wikilink]]` 和 `@cite(...)` / `[来源]`，并检查 evidence ref 是否具备可跳转 id 与 quote/text。
- focused tests 先红后绿：新增用例复现旧逻辑的 3 个失败，修正后 `npx vitest run src/services/wikiApi.test.ts` → `11 passed`。
- frontend build PASS；Vite preview `/wiki` 浏览器 smoke PASS，后端离线时仍显示中文 500 诊断而非白屏。
- `LMWR-414` 只完成 evidence_refs readiness 检查；existing Evidence UI 到 wiki citation/page preview 的真实跳转仍是下一步。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-412-wave12-citation-warnings.md`。

**Wave 12 第五刀结果（2026-05-04 Copilot）**：

- Existing Evidence UI 已支持只读 Wiki preview deep link：Writing Canvas 和 Chat Bubble 在 evidence ref 带显式 wiki page path 时显示跳转入口。
- `evidenceReferences.ts` 新增安全 helper，只从 `page_store_path` / `wiki_page_path` / `page_path` 生成 `/wiki?page=...`，不从 `source_id` / `material_id` 猜 slug。
- `WikiWorkbench` 支持 `?page=` query-param deep link，并在后端离线时保留 preview target 和中文错误态。
- TDD 红灯：新增 helper 测试先失败；修正后 focused tests `17 passed`，frontend build PASS，`/wiki?page=sources%2Fpaper-a.md` 浏览器 smoke PASS。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-414-wave12-evidence-wiki-links.md`。

**Wave 12 第六刀 / frontend gate 结果（2026-05-04 Copilot）**：

- 新增 `ReviewQueuePanel.test.tsx`，覆盖 review item 渲染、状态、decision reason、status filter、refresh callback。
- 新增 `DoctorReportPanel.test.tsx`，覆盖 warnings、structured checks、metrics、safe/manual action hints、refresh callback。
- 验证：Review/Doctor focused UI tests `2 passed`；Wave 12 focused frontend tests `19 passed`；frontend full Vitest `54 passed`；frontend build PASS。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-416-418-wave12-ui-tests-gate.md`。

**Wave 13 / read-only connector 结果（2026-05-04 Codex）**：

- 修复 `tests/wiki/test_connectors.py` 中 PDF connector `pytest.raises` 缩进阻塞后，扩展 connector focused tests 到 10 项。
- `wiki/connectors/base.py` 已提供 ReadOnlyConnector protocol、ConnectorSource、ConnectorScanReport、ConnectorSpec/ConnectorFieldSpec、路径白名单、source_id namespace、dry-run no-write report、错误脱敏 helper。
- `MarkdownConnector` 已支持 Obsidian-like notes 只读扫描/读取/metadata，并排除 `.obsidian`、`.git`、`.trash`、`templates` 与 `*.excalidraw.md`。
- `PdfFolderConnector` 只列 PDF metadata/path/size，并明确拒绝 PDF text extraction。
- Zotero / EndNote 当前为 spec-only contract，不读取用户真实 `zotero.sqlite`、`.enl`、`.Data` 或附件目录。
- 验证：connector focused tests `10 passed`；connector 包与 focused test `compileall` PASS。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-419-433-wave13-connectors.md`。

**Wave 14 首刀 / zero-cost eval 结果（2026-05-04 Codex）**：

- `wiki/evaluation.py` 已新增 `WikiEvalManifest` / `WikiEvalCase`，支持 query、expected IDs、wiki/raw context IDs、answer_page_path、answer、ground_truth、contexts。
- `compare_wiki_vs_raw_retrieval()` 已实现 zero-cost hit_rate、MRR、precision、recall 对比，不调用模型、不改 qrels/goldset。
- `audit_wiki_page_text()` / `audit_wiki_pages()` 已实现 rendered wiki page citation audit，输出 citation/evidence_refs/claim density 的 pass/warn/fail 统计。
- 验证：evaluation focused tests `8 passed`；citation/page/evaluation focused group `82 passed`；wiki package/test compileall PASS。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-434-436-wave14-zero-cost-eval.md`。

**Wave 14 第二刀 / fixtures + no-secret trace 结果（2026-05-04 Codex）**：

- 新增 `workspace_tests/fixtures/wiki_eval_smoke/`，包含 zero-cost manifest 与 2 个 rendered wiki page fixtures。
- `wiki/evaluation.py` 已新增 no-secret scan：检测 Authorization/Bearer、`sk-` key、AWS-style key、named secret field、Windows 私有路径；finding 不回显 raw secret/path。
- `tests/wiki/test_evaluation.py` 扩展到 11 项，覆盖 fixture load/compare/audit/no-secret、危险文本脱敏、真实 query trace 输出扫描。
- 验证：evaluation focused tests `11 passed`；citation/page/query/evaluation focused group `108 passed`；wiki package/test/fixture compileall PASS。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-437-440-446-wave14-fixtures-no-secret.md`。

**Wave 14 第三刀 / doctor graph fixtures 结果（2026-05-04 Codex）**：

- 新增 `workspace_tests/fixtures/wiki_graph_doctor_smoke/`，用固定 rendered pages 锁定 broken-link、orphan、duplicate candidate 组合。
- `tests/wiki/test_doctor.py` 新增 fixture-based doctor graph 测试。
- 验证：doctor/graph/evaluation focused group `27 passed`；wiki package/test/fixture compileall PASS。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-438-wave14-doctor-graph-fixtures.md`。

**Wave 14 第四刀 / compile cost guard 结果（2026-05-04 Codex）**：

- `wiki/compiler.py` 新增 `CompileBudget` / `CompileBudgetCheck` / `check_compile_budget()`，并在 `compile_source()` 写页面前执行 hard guard。
- 超预算 source 在 real compile 和 dry-run 下都返回 skipped + error，不写 page store。
- 验证：compiler focused tests `13 passed`；compiler/llm/eval/doctor/graph focused group `55 passed`；wiki package/test/fixture compileall PASS。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-439-wave14-compile-cost-guard.md`。

**Wave 14 收口 / final gate 结果（2026-05-04 Codex）**：

- `tools/eval/wiki_wave14_performance_baseline.py` 已新增，零成本临时目录 baseline 输出 JSON：`compile_ms=4.929`、`index_ms=10.676`、`query_ms=0.224`。
- `pytest.ini` 已注册 `wiki_wave14` marker；`tests/wiki/test_evaluation.py` 已标记为 CI-friendly Wave 14 subset。
- 收口验证：`pytest tests/wiki -m wiki_wave14 -q` → `11 passed, 276 deselected`；`pytest tests/wiki -q` → `287 passed`；`pytest tests --collect-only -q` → `1618 tests collected`；`system_verification.py --json` → `23 passed / 0 failed / 0 warnings`。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-441-443-447-448-wave14-final-gate.md`。

### D9: 回档策略

- 每个 Wave 开始前创建回档点
- 回档命名：`wave{N}-{slug}-{timestamp}`
- 回档路径：`.rollback_snapshots/`

### D10: 测试覆盖率要求

- 每个新模块至少 80% 行覆盖率
- 关键路径（citation validator、compiler、doctor）要求 90%+
- 每个 Wave 完成后运行 `pytest tests/wiki/ -v --cov=literature_assistant/core/wiki`

### D11: 本地长跑监督

- **决策**：在 VS Codex 无法展示自动化确认卡片时，使用 Windows Task Scheduler + 项目内 runner 作为本地长跑监督机制。
- **任务名**：`LiteratureAssistantLongrunAutopilot`
- **周期**：30 分钟一次；单次最多 25 分钟；计划任务和 runner 均禁止并发。
- **实现文件**：
  - `tools/longrun/invoke-longrun-supervisor.ps1`
  - `tools/longrun/start-longrun-worker.ps1`
  - `tools/longrun/install-longrun-supervisor.ps1`
  - `tools/longrun/status-longrun-supervisor.ps1`
  - `tools/longrun/pause-longrun-supervisor.ps1`
  - `tools/longrun/resume-longrun-supervisor.ps1`
  - `tools/longrun/enter-interactive-longrun.ps1`
  - `tools/longrun/leave-interactive-longrun.ps1`
  - `tools/longrun/uninstall-longrun-supervisor.ps1`
  - `tools/longrun/longrun-prompt.md`
  - `docs/plans/runbooks/longrun-local-supervisor.md`
- **运行状态目录**：`workspace_artifacts/runtime_state/longrun-supervisor/`
- **停止方式**：创建 `workspace_artifacts/runtime_state/longrun-supervisor/STOP` 可暂停 runner；卸载使用 `tools/longrun/uninstall-longrun-supervisor.ps1`。
- **启动顺序**：监督和 worker 顺序无关；推荐先确认监督已安装，再用 `tools/longrun/start-longrun-worker.ps1` 启动一次即时 worker。两者共用 `run.lock`，任何一方正在运行时另一方会跳过。
- **监督语义**：计划任务不常驻占用；只在 30 分钟 tick 时短暂启动。无 worker 时启动新 worker；存在 `run.lock` 或交互标记 `interactive-session.json` 时静默跳过，等待下一次监督。
- **边界**：runner 只能继续当前 LLM-Wiki/RAG 长跑计划；仍必须回档、成熟方案对标、focused verification、回填计划；默认链变更、auto-finalize、`.env`/secret、无备份外部写回、无备份 qrels/goldset/canary30 修改或大重构必须停下询问用户。
- **2026-05-04 授权更新**：具体边界以 `docs/plans/active/llmwiki-autonomy-authorization.md` 为准；qrels/goldset/canary30 可在备份、版本化、对照指标和恢复路径齐全后自决策修改；浏览器 UI 只做独立窗口终态前的最小测试面。

## 决策影响矩阵

| 决策 | 影响模块 | 优先级 | 预计工作量 |
| ---- | -------- | ------ | ---------- |
| D1 | 全部 | P0 | 240 任务 |
| D2 | `runtime_env.py`, `main_rag_workflow.py`, `wiki/query.py` | P1 | Wave 8 |
| D3 | `wiki/page_store.py` | P0 | Wave 3 |
| D4 | `wiki/connectors/` | P2 | Wave 13 |
| D5 | `wiki/graph.py` | P1 | Wave 9 |
| D6 | `routers/wiki_router.py`, `frontend/` | P1 | Wave 11-12 |
| D7 | `tests/` | P0 | 立即执行 |
| D9 | `tests/` | P0 | LMWR-464 |
| D10 | `resources_router.py`, `chunking_pipeline.py` | P2 | LMWR-470 |
| D11 | `docs/plans/specs/`, TOLF 模块 | P1 | LMWR-465 |
| D12 | `frontend/tests/e2e/` | P2 | LMWR-466 |
| D13 | `wiki/connectors/` | P3 | LMWR-467 |
| D14 | `wiki/compiler.py` | P1 | LMWR-468 |
| D15 | `docs/plans/runbooks/` | P2 | LMWR-469 |

## 下一步行动

1. **立即**：进入 Wave 15 前创建回档并搜索/读取迁移、发布门禁、备份/回滚、MCP/tool exposure 的成熟方案。
2. **然后**：优先写 migration dry-run / backup-export / release checklist，不启用外部写回，不自动 finalize。
3. **最后**：需要用户产品判断或外部发布动作时暂停。

## Wave 15 执行记录（2026-05-04 Codex）

- 已创建回档：`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-205313-llmwiki-wave15-longrun-resume`。
- 已读取成熟方案：SwarmVault README/CHANGELOG、LLM Wiki Coordination README、Alembic offline migration、Python zipfile、MCP tool annotations。
- `LMWR-449` ~ `LMWR-455` 第一批已完成：
  - `literature_assistant/core/wiki/migration.py`：evidence_refs -> wiki registry no-write dry-run report。
  - `literature_assistant/core/wiki/backup.py`：wiki runtime/pages/graph backup plan and explicit local zip writer。
  - `literature_assistant/__main__.py`：新增 `wiki migration-dry-run` 和 `wiki backup` CLI。
  - `docs/plans/specs/llmwiki-wave15-migration-maintenance-spec.md`：迁移、cleanup、human edit、多 agent、MCP/tool exposure 策略。
  - `docs/plans/runbooks/llmwiki-slice-LMWR-449-451-wave15-migration-backup.md`：证据包与回滚命令。
- 验证：focused pytest `13 passed`；compileall PASS。
- 决策边界按最新授权补充执行：不自动 finalize，不启用默认 wiki-first，不改 `.env`、默认 RAG 链；外部写回或 qrels/goldset/canary30 修改必须先备份、dry-run/对照并记录恢复路径。
- 下一步：`LMWR-456` ~ `LMWR-459` release/privacy/rollback checklist，再执行 `LMWR-462` 端到端 dry-run。

### Release / Privacy / Rollback Checklist 补充

- 已创建回档：`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-210800-llmwiki-wave15-release-checklists-start`。
- 已新增 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-456-459-wave15-release-privacy-rollback.md`。
- 成熟方案：Vite production build、pytest good integration practices、OWASP Secrets Management、OWASP Logging、SwarmVault stable/migration/doctor 记录。
- 验证：`pytest tests/wiki -q` → `297 passed`；compileall PASS；paths PASS；system verification PASS；wiki backup dry-run smoke PASS。
- 下一步：用户使用指南、master plan 引用、端到端 dry-run、最终证据包。

### User Guide / Master Plan Link 补充

- 已新增 `docs/plans/runbooks/llmwiki-user-facing-usage-guide-draft.md`，作为 LMWR-460 草稿。
- 已在 `docs/plans/active/2026-04-27-full-project-build-master-plan.md` 追加 LLM-Wiki/RAG 集成计划链接和当前状态，作为 LMWR-461。
- 下一步只剩 Wave 15 端到端 dry-run 与 final gate；仍保持 default-off 和 no external write-back 边界。

### End-to-End Dry-Run 补充

- 已新增 `tools/eval/wiki_wave15_end_to_end_dry_run.py` 与 `tests/wiki/test_wave15_end_to_end.py`，完成 LMWR-462。
- E2E 只使用临时目录，不写真实 `workspace_artifacts/runtime_state/wiki`。
- 发现并修复 `build_wiki_index()` rebuild stale row bug；新增测试覆盖删除页面后重建索引。
- 验证：focused pytest `38 passed`；E2E script PASS；compileall PASS。
- 下一步：LMWR-463 final gate。

### Wave 15 Final Gate

- 已新增 `docs/plans/runbooks/llmwiki-slice-LMWR-463-wave15-final-gate.md`。
- 最终验证：
  - `pytest tests/wiki -q` → `299 passed`
  - compileall PASS
  - `pytest tests --collect-only -q` → `1630 tests collected`
  - paths PASS
  - system verification PASS（23/0/0）
  - Wave 15 E2E dry-run PASS
- Wave 15 planned tasks `LMWR-449` ~ `LMWR-463` 已收口。后续若继续长跑，优先从 `LMWR-464` ~ `LMWR-473` 的补充任务中选低风险项。

### Wave 15 Supplement / LMWR-465

- 已新增 `docs/plans/specs/tolf-wiki-integration.md` 与 `docs/plans/runbooks/llmwiki-slice-LMWR-465-tolf-wiki-boundary.md`。
- 决策：TOLF 是 default-off context-selection / diagnostics arm，不是 Wiki compiler，不直接写 page store，不改 qrels/goldset，不替换默认 RAG 链。
- 允许路径：TOLF provenance 随 `evidence_refs` / `context_metadata` 进入 migration dry-run 或 `save_exploration()` draft，再由 doctor/review/citation validator 处理。
- 成熟方案：Azure AI Search hybrid/RRF + synonym maps、Elasticsearch semantic hybrid + search-time synonyms、Vespa hybrid search；共同结论是保留 lexical/control arm 和审阅证据，不靠单个 semantic arm 自动切默认链。

### Wave 15 Supplement / LMWR-467

- 已新增 `docs/plans/specs/external-knowledge-writeback-policy.md` 与 `docs/plans/runbooks/llmwiki-slice-LMWR-467-external-writeback-policy.md`。
- 决策：当前外部知识库 connector 继续只读；不写 Zotero / EndNote / Obsidian / PDF folders，不引入 API 凭据或外部同步。
- 未来 direct write 必须另开任务，先做 checkpoint、官方写 API 对标、dry-run diff、backup/export、operation journal，并由用户显式确认。
- 成熟方案：Zotero Web API write/version contract、Obsidian Vault modify API、Wave 13 read-only connector contract。

### Wave 15 Supplement / LMWR-468

- 已新增 `docs/plans/runbooks/llmwiki-slice-LMWR-468-compile-cost-estimate.md`。
- `wiki/compiler.py` 新增 `CompilePricing` / `CompileCostEstimate`，`CompileResult` 现在携带 `budget_checks` 和 `cost_estimate`。
- `/api/wiki/compile` 在 registry 存在时执行 read-only dry-run，返回 `created/updated/skipped`、`budget_summary`、`budget_checks`、`errors`；缺 registry 时不创建 DB。
- 前端 Wiki Compile Dry-Run panel 已展示 total tokens、estimated cost、pricing source、configured 状态；OpenAPI schema/types 已重新生成。
- 成熟方案：参考 OpenAI 官方 pricing 页但不硬编码价格；真实费率必须由显式 env/provider config 注入。

### Wave 15 Supplement / LMWR-469

- 已更新 `docs/plans/runbooks/longrun-local-supervisor.md`，补充启动 envelope、任务选择、命令模板、验证梯度和 handoff 记录。
- 已新增 `docs/plans/runbooks/llmwiki-slice-LMWR-469-longrun-mode-guide.md`，记录回档点、成熟方案、Longrun SOP、验证和后续边界。
- 已更新 `tools/longrun/longrun-prompt.md`，要求 scheduled worker 读取 longrun SOP，并在给用户或其他 agent 的命令里包含回档和成熟方案搜索。
- 成熟方案：OpenAI Codex `AGENTS.md` / non-interactive mode、Microsoft ScheduledTasks、Git worktree；共同结论是长跑必须由明确 instruction scope、周期监督、锁/停止条件、回档和 focused verification 约束。

### Wave 15 Supplement / LMWR-470

- 已新增 `tools/eval/wiki_lmwr470_chunk_param_review.py`，只读解析 canary30 历史 artifacts 与当前 `resources_router.py` 常量，输出 deterministic JSON decision artifact。
- 已新增 `tests/wiki/test_lmwr470_chunk_param_review.py`，覆盖 AST 常量提取、200/8 vs 150/5 指标相同、stale cache evidence 和 deterministic writer。
- 已生成 `workspace_artifacts/evaluations/lmwr-470-chunk-param-review-20260505.json`；备份路径为 `workspace_artifacts/backups/lmwr-470-20260505/evaluation-inputs`。
- 决策：当前不提升 200/8，不修改 qrels/goldset/canary30，不修改 `CHUNK_OVERLAP=150` / `MAX_CHUNKS_PER_MATERIAL=5` 默认值。
- 成熟方案：LangChain text splitters、LlamaIndex retrieval evaluation、Pinecone chunking strategies；共同结论是 chunk 参数必须用代表性 retrieval metrics 对照验证。
- 验证：focused pytest `5 passed`；related eval pytest `7 passed`；compileall PASS。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-470-chunk-params-reevaluation.md`。

### Post-LMWR-470 / cache-corpus preflight

- 已新增 `tools/eval/wiki_cache_corpus_preflight.py`，只读计算 corpus/chunk-store 的 `chunk_count`、`chunks_hash`、`is_contextual`，并对比 embedding manifest 的 count/hash/shape/dim/contextual/zero rows。
- 已新增 `tests/wiki/test_cache_corpus_preflight.py`，覆盖 PASS/FAIL、v2 chunk-store manifest、路径逃逸拒绝、无 manifest、多 cache dir、deterministic writer。
- 当前真实 artifact：`workspace_artifacts/evaluations/post-lmwr-470-cache-corpus-preflight-laser-welding-109-20260505.json`。
- 决策：`laser_welding_109` v2 chunk-store 预检 FAIL（`7225` chunks/hash 不匹配 canonical `11470` 或 legacy `11457` manifests），因此不能直接 rerun canary30，也不能提升 200/8。
- 下一步：先定位 canary30 control 实际 corpus source，并让 preflight PASS；需要 rebuild cache 或 provider eval 时可使用现有 env / provider 配置继续执行，必须记录 no-secret 输出和 old-new metrics。
- 验证：focused pytest `8 passed`；related bundle `15 passed`；compileall PASS。
- 证据：`docs/plans/runbooks/post-lmwr-470-cache-corpus-preflight.md`。

### Post-LMWR-470 / canary corpus source locator and root hygiene

- 已新增 `tools/eval/wiki_canary_corpus_source_locator.py`，按 `workspace_tests/evaluation_scripts/eval_retrieval_runtime.py::_load_retrieval_corpus()` 的真实语义定位 canary30 runtime corpus source。
- 关键修正：canary runtime 加载的是 `output/chunk_store` root 下所有 v2 project manifest 加 root legacy JSON，不是单个 `laser_welding_109` project；并且 loader 顺序不排序 chunk_id、不去重，manifest 比较必须使用 runtime 原顺序 hash。
- 当前真实 artifact：`workspace_artifacts/evaluations/post-lmwr-470-canary-corpus-source-locator-20260505.json`。
- 初始结果：`output/chunk_store` 是 junction，解析到 `workspace_artifacts/generated/output/chunk_store`；runtime corpus 为 `11471` chunks，hash `76f661a741bbc5b7cc69dfab34b3cdd99cba8744691111403874b9fee162bc6a`。
- Root hygiene 结论：1-chunk v2 project `proj_f9adfb165de1` 是测试残留（`valid.txt` / `This is valid extractable content.`）；排除该 group 后 projected corpus 精确匹配 canonical contextual manifest `11470` / `58c76986fdfa125d9e690ad00dfa990b72b2a6b41a564405280d8613a012ddf0`。
- 已按授权 checkpoint + 目标级备份后清理；备份和 cleanup journal 位于 `workspace_artifacts/backups/post-lmwr-470-root-hygiene-20260505/`。
- 当前结果：locator status `PASS`，runtime corpus 已匹配 `workspace_artifacts/generated/output/embedding_cache/corpus_embeddings_contextual_m571cef40de3d.manifest.json`。
- 决策：cache/corpus gate 已 PASS；后续 canary30 no-rerank/raw/default control 可使用现有 env / provider 配置继续执行。仍不修改 `.env`、不打印密钥、不自动提升 200/8、不修改 qrels/goldset/canary30。
- 验证：`pytest tests/wiki/test_cache_corpus_preflight.py -q` → `14 passed`；`pytest tests/wiki/test_cache_corpus_preflight.py tests/wiki/test_lmwr470_chunk_param_review.py -q` → `19 passed`；compileall PASS。
- 证据：`docs/plans/runbooks/post-lmwr-470-cache-corpus-preflight.md`。

### Wave 15 Supplement / LMWR-471

- 已扩展 `tools/eval/wiki_wave14_performance_baseline.py`，schema v2 输出 compile/index/query/doctor/total latency P50/P95/P99 和 throughput_per_second。
- 已新增 `tests/wiki/test_performance_baseline.py`，覆盖 percentile/throughput payload 和 invalid iteration guard。
- 基线命令：`python tools/eval/wiki_wave14_performance_baseline.py --iterations 5 --pretty`；本轮结果 `compile p50=4.979ms`、`index p50=10.562ms`、`query p50=0.204ms`、`doctor p50=5.558ms`、`error_count=0`。
- 成熟方案：Python `perf_counter` / `timeit` / `statistics` 官方文档；继续保持 zero-cost temp workspace，不调用模型、不写 runtime artifacts。

### Wave 15 Supplement / LMWR-473

- 已新增 `literature_assistant/core/wiki/observability.py`，统一 Wiki 本地事件、指标、span JSONL 接口，输出到 `workspace_artifacts/runtime_state/wiki/observability/`。
- 决策：本轮不引入 OpenTelemetry SDK/exporter；只借鉴 traces/metrics/logs 三信号模型，保持本地默认、无网络导出、fail-open。
- `WikiQueryIndex`、`WikiCompiler`、`WikiDoctor` 支持可注入 observability sink；默认不传 sink 时不污染离线测试与批处理产物。
- 脱敏边界：query/prompt/answer/text/body/path/api_key/token 等字段只保留 hash、length、reason，不回显用户原文、私有路径或密钥。
- 验证：focused pytest `61 passed`；wiki package/test compileall PASS。
- 证据：`docs/plans/runbooks/llmwiki-slice-LMWR-473-observability.md`。

## 决策补充

### D9: 测试失败修复状态
- **当前状态**：LMWR-464 已收口；`pytest tests -q` → `1632 passed, 3 skipped`。
- **已修复**：
  - ✅ P0 Contextual Chunker (2)：commit ed386e4f
  - ✅ P0 Reranker (3)：实际未失败（exit code 49 是 squad guard 误报）
  - ✅ P1 legacy_root (9)：commit 24d5ba6f
  - ✅ P2 Precompute/Migration (4)：commit 672a73ac
  - ✅ legacy C6 reproducibility：root shim 转发 core CLI，测试改为 temp deterministic corpus。
  - ✅ contextual miss validation：validation-only contextual coverage 恢复 missing summary log。
- **剩余**：0 个。
- **证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-464-test-failure-closeout.md`。

### D10: 分块参数调整与回滚
- **初始调整**：CHUNK_OVERLAP 150→200，MAX_CHUNKS_PER_MATERIAL 5→8（commit ed386e4f、0f5dcfd4）
- **回滚**：commit b8839cc5 "revert to 150/5 due to canary30 regression"
- **历史指标**：aligned baseline 2026-04-27 Recall@5/MRR 为 `0.6667/0.6667`；200/8 run 为 `0.5/0.3181`；150/5 revert run 仍为 `0.5/0.3181`。
- **因果结论**：200/8 与 150/5 的 Recall/MRR 完全相同，参数导致回归未被证明；旧报告标题不可作为参数因果依据。
- **cache/corpus 证据**：旧 embedding manifest `11445` / `11436` chunks，对比当前 corpus `11457` chunks，stale cache/corpus state 是更强解释。
- **当前配置**：CHUNK_OVERLAP=150，MAX_CHUNKS_PER_MATERIAL=5
- **当前决策**：不提升 200/8，不修改 qrels/goldset/canary30；先做 cache/corpus manifest 对齐，再重跑 aligned canary30 no-rerank/raw/default control。
- **Post-gate 状态**：已新增只读 preflight；当前 `laser_welding_109` v2 chunk-store 与现有 canonical/legacy manifests 不对齐，必须先定位真实 canary corpus source。
- **证据**：`workspace_artifacts/evaluations/lmwr-470-chunk-param-review-20260505.json`、`docs/plans/runbooks/llmwiki-slice-LMWR-470-chunk-params-reevaluation.md`。

### D11: TOLF 功能定位
- **当前状态**：最新 5 个 commit 全部是 TOLF 相关（judgment summary、template export、review packet、inspection packet、bilingual control、query bridge diagnostics）
- **当前决策**：TOLF 是 default-off 候选上下文选择与诊断臂，不是 Wiki 前置强依赖，不是 Wiki 编译器。
- **集成点**：TOLF 输出只可通过 `evidence_refs` / `context_metadata` 进入 migration dry-run 或 draft exploration；不得直接写 final page 或 query index；qrels/goldset/canary30 只能按最新授权补充先备份、后对照、再演进。
- **验收**：继续保留 raw default / bilingual default / TOLF 三臂、inspection、review Markdown、judgment JSONL 和 summary；默认链切换必须另建 gate 并停下问用户。
- **证据**：`docs/plans/specs/tolf-wiki-integration.md`、`docs/plans/runbooks/llmwiki-slice-LMWR-465-tolf-wiki-boundary.md`。

### D12: 前端 UI 测试覆盖
- **当前覆盖**：54 个 Vitest 单元测试 + 浏览器 smoke 测试
- **产品终态**：最终程序界面是独立窗口；浏览器只作为开发期预览、smoke 和最小 E2E 验收面。
- **已补齐**：LMWR-466 已复用现有 Playwright 增加 Wiki Workbench 最小 E2E，覆盖 route、deep-link preview、page select、compile dry-run、doctor/review/graph。
- **实现细节**：修复 `frontend/tests/e2e/mockApi.ts` catch-all API route，用 `route.fallback()` 让 `/api/wiki/*` 专用 mock 生效，避免被兜底 `{}` 响应打成 500。
- **验证**：focused Playwright `5 passed`；`wikiApi` focused Vitest `11 passed`；frontend build PASS。
- **边界**：视觉回归和完整响应式适配仍不作为当前测试期目标。
- **证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-466-frontend-e2e.md`。

### D13: 外部知识库写回策略
- **当前决策**：LMWR-467 已完成；当前 runtime 对 Zotero / EndNote / Obsidian / PDF folders 保持 read-only，不引入外部写回代码。
- **硬边界**：当前默认仍保持 `ConnectorSpec.read_only=true`、`ConnectorSpec.writes_user_library=false`、`ConnectorScanReport.would_write=false`；禁止无 dry-run diff、无目标级备份、无 operation journal 的 Zotero SQLite、EndNote `.enl/.Data`、Obsidian vault、附件/PDF、外部参考仓库、qrels/goldset/eval query 写入。
- **未来触发条件**：只有用户显式指定目标、字段、范围和回滚计划后，才能另开写回任务；任务必须先读官方写 API，输出 dry-run diff、backup/export、operation journal，并由用户确认。
- **回滚边界**：Codex checkpoint 只能回滚项目文件，不能自动撤销已同步到外部工具的数据；任何外部写入都必须有单独的 target-level backup/restore runbook。
- **证据**：`docs/plans/specs/external-knowledge-writeback-policy.md`、`docs/plans/runbooks/llmwiki-slice-LMWR-467-external-writeback-policy.md`。

### D14: Wiki 编译成本控制
- **当前状态**：Wave 14 已实现 compile budget hard guard；Wave 15 supplement 已实现 dry-run token/cost estimate 并显示到 API + 前端。
- **价格边界**：不硬编码模型价格；默认不配置费率时 `estimated_cost_usd=0.0` 且 `pricing_configured=false`，真实费率需按当日官方 pricing 或 provider config 显式注入。
- **验收**：compiler/router focused pytest、frontend wikiApi test、frontend build、OpenAPI regenerate、Wave15 E2E focused group 已通过。
- **证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-468-compile-cost-estimate.md`。

### D15: longrun 模式边界
- **当前状态**：LMWR-469 已完成；`longrun-local-supervisor.md` 已补充启动 envelope、任务选择、命令模板、验证梯度、handoff 记录和成熟方案来源，`tools/longrun/longrun-prompt.md` 已同步给 scheduled worker。
- **longrun 边界**：只能继续当前 LLM-Wiki/RAG 长跑计划；必须遵守 `docs/plans/active/llmwiki-autonomy-authorization.md`，包括先备份再删除/修改、先对照再演进评测基线、联网信息不能替代知识库 evidence。
- **停止条件**：存在 `workspace_artifacts/runtime_state/longrun-supervisor/STOP`、交互标记，或下一步需要新增/修改账号凭据或 `.env` secret、生产访问、默认 RAG/TOLF 主链替换、auto-finalize、无法备份的外部写回、无法证明可恢复的删除/远程历史操作。使用现有 env / provider 配置运行评测不属于停止条件。
- **命令规则**：给用户或其他 agent 的执行指令必须包含回档 checkpoint、成熟/官方方案搜索、实现、验证，以及“仅用户明确要求时恢复 checkpoint”的恢复命令。
- **证据**：`docs/plans/runbooks/longrun-local-supervisor.md`、`docs/plans/runbooks/llmwiki-slice-LMWR-469-longrun-mode-guide.md`。

### D16: 2026-05-04 自决策授权补充
- **记录文件**：`docs/plans/active/llmwiki-autonomy-authorization.md`
- **产品界面**：终态是独立窗口；浏览器只用于当前开发期看效果和最小 E2E。
- **评测基线**：qrels/goldset/canary30 不再一律停下；在 checkpoint、备份、版本化、旧/新指标、样本数和恢复路径齐全时可自决策修改。
- **安全审计**：LMWR-472 是本地轻量安全门禁，覆盖路径越界、输入校验、权限边界、日志脱敏、RAG/LLM evidence 边界；不做外部攻击扫描。
- **联网边界**：程序除 AI provider 外默认不联网；AI 可搜索背景和成熟方案，但正式回答必须基于本地知识库 evidence，网络内容不能静默成为知识库引用。
- **删除/修改**：项目内删除、迁移、改名和清理旧实现可在备份后自决策；外部系统、远程历史、账号、凭据、付费或无法证明可恢复的操作仍停下。

### D17: LMWR-472 本地安全门禁收口
- **当前状态**：LMWR-472 已完成第一轮本地轻量安全门禁，不做外部攻击扫描。
- **输入边界**：`wiki_router.py` 现在对 `kind/status`、`source_id/project_id`、`page_path` 做显式形状校验；非法值返回 400，而不是让底层路径/枚举逻辑抛成 500。
- **路径泄露边界**：`/api/wiki/status` 不再把真实绝对路径直接暴露给前端；仓库外路径统一脱敏为 `<external>/<name>`。
- **备份边界**：`wiki/backup.py` 现在只收集仍位于声明 allowed root 内的真实文件；越界 symlink/junction 目标不会被打进 archive。
- **验证**：`pytest tests/wiki/test_wiki_router.py tests/wiki/test_backup.py -q` → `19 passed, 1 skipped`；compileall PASS。
- **证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-472-security-audit.md`。

### D18: LMWR-473 本地可观测性收口
- **当前状态**：LMWR-473 已完成第一轮本地观测门禁。
- **事件/指标/span 边界**：统一通过 `WikiObservabilitySink` 输出 `events.jsonl`、`metrics.jsonl`、`spans.jsonl`；不接外部 exporter，不联网。
- **隐私边界**：观测行不保存原始 query、prompt、answer、正文、quote、私有路径、API key 或 token；敏感值只保存 hash/length/reason。
- **接入边界**：query/compiler/doctor 只在显式注入 sink 时写观测；默认业务路径保持无副作用。
- **验证**：`pytest tests/wiki/test_observability.py tests/wiki/test_query.py tests/wiki/test_compiler.py tests/wiki/test_doctor.py -q` → `61 passed`；compileall PASS。
- **证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-473-observability.md`。

### D19: Post-LMWR-470 canary30 goldset 漂移诊断
- **当前状态**：cache/corpus manifest 已 PASS，但 aligned canary30 no-rerank 仍为 Recall@5 `0.5`、MRR `0.3181`；default rerank 更差，不启用。
- **新增工具**：`tools/eval/wiki_canary_goldset_drift.py` 只读消费已有 query JSONL、rerank trace 和 chunk-store，输出每条 query 的 gold rank、top hits、competing material、same-title alternate 和 drift label。
- **full-root artifact**：`workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-drift-20260505.json`。
- **laser109 artifact**：`workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-drift-laser109-20260505.json`。
- **关键证据**：full root 30 条中 top5 命中 `15`、miss `15`；其中 `10` 条在 trace window 内找不到 gold，`5` 条 gold 被埋到 top5 后；aligned gold 只覆盖 `mat_1f5242e1034f=20` 与 `mat_f76878df9d8d=10`。
- **competing top1**：`mat_2f98d33813ce` 和 `mat_6844f200248a` 各 `7` 次，`mat_bf26f6f7038f` `6` 次，`mat_29a909d77df0` `2` 次；这些多为更新或更贴近 generic laser-welding query 的材料。
- **proposal artifact**：`workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-proposal-20260505.json` 与 `post-lmwr-470-canary30-goldset-proposal-laser109-20260505.json` 已生成；均为 no-write 草案，要求 review + checkpoint + 文件备份后才能物化。
- **proposal 摘要**：full-root 有 `15` 个 action，laser109 有 `17` 个 action；simulated Recall@5 均为 `1.0`，但这是接受 trace top-k candidates 后的上界估算，不是 release gate。
- **结论**：当前回归更像 canary30 goldset 过窄/陈旧与 material identity 漂移，不是 200/8 chunk 参数因果；后续优先新增版本化 query/qrels/goldset 对照，不直接覆盖旧 canary30。
- **验证**：`pytest tests/wiki/test_canary_goldset_drift.py tests/wiki/test_cache_corpus_preflight.py tests/test_eval_runtime.py -q` → `51 passed`；compileall PASS。
- **证据**：`docs/plans/runbooks/post-lmwr-470-cache-corpus-preflight.md` 第 8-9 节。

## 决策人

- 用户：小龙 姚
- 执行者：Claude (Kiro)
