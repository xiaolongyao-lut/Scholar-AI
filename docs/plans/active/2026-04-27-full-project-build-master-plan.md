# 2026-04-27 RAG/TOLF 全项目构建总排程（Master Build Plan）

## 目标

在不打断现有研发节奏的前提下，建立一套可重复、可审计、可回滚的全项目构建与验收流水线，覆盖：

- Squad/Copilot 治理层
- Python 后端与评测层
- Frontend 构建层
- 决策与执行记录层
- TOLF 上游评测与迁移层

标准 RAG 仅作为当前工程对照组，最终落点仍是 TOLF。

## 约束

- 优先小步快跑，先验证后扩面。
- 小决策自动推进；高影响决策先入记录、批量确认。
- 所有长期任务必须产出证据包（Facts/Decisions/Open/Next）。
- 禁止无证据“口头通过”。
- 非平凡架构、接口、权限、安全或数据流变更前必须先建立可回档点，并检索成熟方案或官方一手文档；计划、任务指令和交接提示中也必须显式包含“先回档、再对标成熟方案、再实施”的要求。
- 前端视觉与独立窗口形态参考优先来自 `github/` 参考库中的项目界面、截图与结构文档；当前本地 `localhost` 页面只用于运行态验证与交互 smoke，不作为最终视觉母版。
- 若页面已在 VS Code 中开启“与智能体共享”，可直接使用共享页面做自动元素交互与回归验证；长跑不得依赖用户手动“添加元素到聊天”作为必经步骤，该动作仅作为可选的精确定位增强。

## 当前进度快照（更新于 2026-05-02）

- **Wave 0~8 已全面收口**：Squad 控制面恢复（TASK-000）、reranker 矩阵完成 provisional verdict（TASK-010~014 Wave 4）、Gate B/Tier3 一致性验收通过（TASK-020）、会话持久化 API 契约 + SQLite 恢复闭环（TASK-030）、前端检索/扫描闭环（TASK-040）、主运行时 guard 对齐（TASK-050 Wave 5）、TOLF text-only pilot ablation 完成（TASK-060 Wave 6）、academic connector 设计 + Evidence/Citation/Review 前端最小实现 + shared-page 自动 UI 协议（Wave 7）、backend evidence export contract + OpenAPI schema 固化 + schema risk review（Wave 8）。
- **Wave 4 reranker provisional verdict 已出**：DashScope `qwen3-rerank` / `qwen3-vl-rerank` / `gte-rerank-v2` 三条 pinned c16 canary 全部显著劣于 no-rerank control（Recall@5=0.6667, MRR=0.6667）；短期基线保持 `--no-rerank`；reranker 作为一等能力保留在架构中，不删除。
- **Wave 9 前端产品化已完成 E2E gate 收口**：Workbench 会话恢复 UI、KnowledgeBase 扫描失败详情、academic export 前端消费、默认 Vitest 集、route-level lazy/bundle 优化、i18n 补齐和 Playwright smoke 均已有本地验证；2026-05-01 独立复核 `npm run test` -> `34 passed`、`npm run build` -> success、`npm run test:e2e -- --reporter=line` -> `16 passed`。
- **Wave 10 用户 Skill 扩展层前端 gate 已从 provisional 改为通过并完成 UX hardening**：用户 Skill 后端 contract / runtime / registry（TASK-183~188）、前端 Skill Manager MVP（TASK-189）、Skill 映射为 Actions 并接入 RAG 文献助手调用面（TASK-190）已有实现；2026-05-01 Skill Manager E2E 覆盖渲染、导入错误路径、启用/停用、测试运行、审批 decision、卸载确认、回滚入口、审计日志，Playwright runner 稳定 exit `0`。
- **2026-05-01 后端 hardening 切片已闭环**：TASK-193（Skill approval decision 持久化）与 TASK-194（Skill 卸载 / 回滚 API）已按"设计先行 + 契约测试 + 实现"推进完成；后端 now exposes persistent approval requests / decisions、user-skill uninstall、rollback latest / explicit snapshot，且 OpenAPI 命名 schema 已通过 smoke。
- **2026-05-01 Skill zip/import happy path 后端切片已完成**：TASK-197 已把用户 Skill 导入扩展为“目录或 `.zip` 包”双入口，补齐单根目录压缩包解析、坏包/路径穿越/重复条目/加密条目拦截，并保持原有启用审批、卸载/回滚与运行时安全边界不变；focused pytest `26 passed`、扩展 Skill 回归 `60 passed`、compileall pass。
- **2026-05-01 Skill import 错误契约前后端补位已完成**：TASK-199 已把 `/skills/import` 失败 detail 稳定为 `error_code + errors` 结构，前端改为基于错误码提示 zip/manifest/路径问题，并增加本地浅预检；后端 focused pytest `26 passed`、前端默认 Vitest `38 passed`、全量前端 E2E `23 passed`、build success、compileall pass。
- **2026-05-02 脚本型 Skill 安全策略合同已完成**：TASK-200 已新增机器可读 `SkillSecurityAssessment` 与 `/skills/{skill_id}/security`，把脚本/网络/文件写入风险统一为 runtime gate、审批原因、阻断原因和未来沙箱控制项；脚本/tool-wrapper 执行仍保持 blocked，不放开 shell/network/file-write；Skill 回归 `68 passed`、compileall pass、OpenAPI 生成成功、前端 `38 passed`、build success。
- **2026-05-02 Skill 安全策略前端可视化已完成**：TASK-201 已在 Skill Manager 中按需消费 `/skills/{skill_id}/security`，为每个 Skill 展示风险等级、运行门控、当前是否可执行、启用审批、被拦截操作、未来沙箱控制项和阻断/审批原因；Skill Manager E2E `13 passed`、前端默认 Vitest `39 passed`、build success。
- **2026-05-02 核心 RAG evidence/provenance hardening 已完成首刀**：TASK-202 已新增机器可读 `EvidenceReference` / `evidence_refs`，把 packed evidence 的 `chunk_id`、`material_id`、`text`、`compressed_text`、`quote`、`label`、`score`、`page`、`source_labels` 保留到 `last_answer.json` 与会话事件；prompt 继续保留 `SOURCE_ID` / `MATERIAL` / `QUOTE` / `BODY`，并新增 `SOURCE_LABELS`；focused pytest `19 passed`、compileall pass。
- **2026-05-02 检索来源 provenance 首刀已完成**：TASK-203 已把 hybrid / dense / graph / RRF / rerank / local fallback 的 `source_labels` 与 `source_hint` 补齐为机器可读链路，后续 answer packing 能看到候选来自 `bm25`、`dense`、`graph`、`rrf`、`rerank` 或 fallback；本切片不改排序、不改默认 rerank、不改 corpus/goldset/qrels；focused pytest `42 passed`、compileall pass。
- **2026-05-02 RAG result evidence_refs 契约已补齐**：TASK-204 已把 `evidence_refs` 从副产物/会话事件提升到 `RAGResult` 正式字段，并复用生成阶段同一 evidence packing helper，保证 API/CLI/后续 UI consumer 拿到的机器可读引用与实际 prompt 证据一致；本切片不改回答文本、不改检索排序、不改默认 rerank、不改评测口径；focused pytest `18 passed`、compileall pass。
- **2026-05-02 RAG CLI JSON 输出契约已补齐**：TASK-205 已为 `rag_integration_entry.py ask` 增加显式 `--json-output`，机器输出包含 `query/focused_points/memory_hits/rag_evidence/evidence_refs/generated_answer/confidence_score/trace/association_bundle`，默认人类可读输出保持不变；focused pytest `11 passed`、compileall pass。
- **2026-05-02 前端 evidence refs 展示字段已对齐后端 RAG**：TASK-206 已让 `frontend/src/lib/evidenceReferences.ts` 识别 `material_id/text/compressed_text/label/page/source/source_labels/source_hint`，证据正文优先显示压缩文本或全文，metadata 展示 material/source 与检索来源标签；focused Vitest `5 passed`、frontend build success。
- **2026-05-02 runtime RAG rerank 默认门禁已对齐**：TASK-207 已把主运行时 `HybridRetrieverWithRerank()` 默认改为 `RAG_RUNTIME_RERANK_ENABLED` 显式 opt-in，避免 `.env` 中存在 rerank key 时默认主链悄悄启用；显式 `use_reranker=True` 与 eval `use_rerank/--no-rerank` 仍保持原控制面；focused pytest `40 passed`、compileall pass。
- **2026-05-02 rerank canary dry-run guard 已补齐**：TASK-208 已为 `tools/eval/run_pinned_rerank_manifest.py` 增加 `--dry-run` 与 `--require-runtime-rerank-opt-in`，在不调用模型、不删除输出的前提下校验 manifest sections、queries/qrels 存在、`use_rerank=true`、pinned base_url/model、唯一输出路径和 runtime opt-in；focused pytest `3 passed`、compileall pass。
- **2026-05-02 rerank canary dry-run 样例与 runbook 已补齐**：TASK-209 已新增可版本化样例 manifest 与 `docs/plans/runbooks/rerank-canary-dry-run.md`，并把 dry-run preflight 复用于真实 runner 开头，防止重复输出路径或 query/qrels 行数错配在真实 canary 中才暴露；focused pytest `6 passed`、sample dry-run pass。
- **2026-05-02 IntelligentChat HTTP 兼容层已补齐**：TASK-210 已恢复前端实际调用的 `/api/chat`、`/api/chat/sessions`、`/api/chat/resume`、`/api/budget/status` typed FastAPI contract，并在 response 中暴露 `evidence_refs`；实现复用现有 `/chat/ask` LLM 代理，不改变 RAG/TOLF 默认主链；focused pytest `13 passed`、OpenAPI 生成成功、frontend build success。
- **2026-05-02 IntelligentChat 项目知识库接入已补齐**：TASK-211 已让 `/api/chat` 支持 `project_id`，优先复用项目 chunk store 的检索结果作为上下文，并保留 `chunk_id/material_id/title/section/page/source_labels/source_hint` 到 `context_metadata` 与 `evidence_refs`；前端从 `WritingContext.activeProjectId` 自动透传当前项目；本切片仍不替换默认 RAG/TOLF 主链、不启用 rerank、不改 corpus/goldset/qrels；focused pytest `6 passed`、OpenAPI 生成成功、frontend build success。
- 参考证据来源：`model_selection_summary_literature_rag_TOLF修订版.md`、`.copilot-tracking/plans/2026-04-21-cost-and-defaults.md`、`.squad/orchestration-log/*`、`.claude_squad/agents/{oracle,morpheus,tank,ralph}/history.md`。

## 2026-04-30 前端 Wave 9/10 核查回填

- **回档点**：本次计划回填前已建立 `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.rollback_snapshots\codex-plan-status-update-20260430_232323`；后续清理旧快照时只删除更早目录，保留该最新回档点用于本次文档修改回退。
- **成熟方案 / 官方文档对标**：Playwright API mocking / route：`https://playwright.dev/docs/mock`；Playwright locator 与 web-first assertion：`https://playwright.dev/docs/locators`、`https://playwright.dev/docs/test-assertions`；React route-level lazy / Suspense：`https://react.dev/reference/react/lazy`、`https://react.dev/reference/react/Suspense`。
- **已核查通过**：`node -e "JSON.parse(require('fs').readFileSync('src/locales/zh.json','utf8')); console.log('zh.json ok')"` 通过；`npm run test` 通过，当前默认集 `34 passed`；`npm run build` 通过，主 bundle 约 `405 kB` 且无 500 kB warning；DevTools 手动访问 `http://127.0.0.1:3100/settings?section=skills` 可见 `导入用户 Skill`、`我的 SKILL`、`基础能力`、`采样策略`。
- **不得误报为完成**：`npx playwright test tests/e2e/skill-manager.spec.ts --workers=1 --timeout=30000 --max-failures=1 --reporter=line` 在当前环境仍 timeout / blank-page 偶发，不能把 `TASK-179` 或 `TASK-191` 标记为 E2E gate pass；手动 DevTools 成功只能作为运行态佐证，不能替代 Playwright exit `0`。
- **后续验收口径**：只有当 `npm run test:e2e -- smoke.spec.ts skill-manager.spec.ts` 在隔离 Vite server、同源 mock API、清空 localStorage/sessionStorage 状态下稳定 exit `0`，才允许把 `TASK-179` 和 `TASK-191` 改回完成态。

## 2026-05-01 前端 Wave 9/10 E2E gate 复核收口

- **回档点**：本次计划回填前已建立 `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\.rollback_snapshots\codex-frontend-e2e-gate-20260501_010038`。
- **成熟方案 / 官方文档对标**：Playwright `webServer` 用于在测试前启动本地 dev server；Playwright `page.route()` 用于 mock API 请求；locator / web-first assertion 口径沿用 role/text locator 与 auto-retrying assertions。官方文档：`https://playwright.dev/docs/test-webserver`、`https://playwright.dev/docs/network`、`https://playwright.dev/docs/locators`、`https://playwright.dev/docs/test-assertions`。
- **根因核验**：`frontend/tests/e2e/mockApi.ts` 只 fulfill `fetch/xhr`，避免拦截 Vite `.ts/.tsx` 模块请求；`/chat/providers` mock 返回数组，匹配 `Settings.tsx` 的 `catalog.find()` 预期；`frontend/vite.config.e2e.ts` 去掉 backend proxy，使 Playwright route mock 可接管 API；`a-smoke.spec.ts` 使用 root warm-up + sidebar navigation 降低 Windows / Vite 直达路由 500 风险。
- **独立复跑结果**：`npm run test` -> `34 passed`；`npm run build` -> success，主 bundle `405.13 kB` 且无 500 kB warning；`npm run test:e2e -- --reporter=line` -> `16 passed (50.7s)`。
- **结论**：`TASK-179`、`TASK-191`、`TASK-192` 可从 `进行中 / provisional` 改为 `已完成`；后续不得再引用 2026-04-30 的 timeout 结果作为当前状态，只保留为历史根因背景。

## 当前推进原则

1. Wave 0~8 已完成收口，Wave 9/10 前端 gate 已收口；后续若继续前端，只能基于新增需求或真实回归，不再重复修已通过的 Playwright runner 稳定化切片。
2. reranker 仍是一等能力。后续是否在 RAG 完善中启用 rerank / reranker canary 属于 AI 自决策小/中决策：必须有回档点、成熟方案对标、唯一输出路径/trace/fallback 证据与可回滚配置；只有重构级默认链大切换、评测口径改变或最终 release gate 才上升为人工确认。
3. TOLF 仍默认不无证据替换主链，但允许 AI 在后续 RAG 完善中自决策做 default-off adapter、guarded canary 或可回滚主链试接；要求先保留标准 RAG 对照、产出证据包，并不得修改 corpus/goldset/qrels 或最终发布口径。
4. 2026-05-02 Skill 扩展层 hardening 已完成：TASK-193 approval decision 持久化、TASK-194 卸载/回滚 API、TASK-195 前端审批/卸载/回滚 UX、TASK-196 高风险启用审批门禁、TASK-197 真实 zip/import happy path 后端切片、TASK-198 前端 zip/import package validation UX、TASK-199 import 错误契约前后端补位、TASK-200 脚本型 Skill 安全策略合同、TASK-201 安全策略前端可视化均已有契约测试、实现与证据包；后续若继续 Skill 扩展层，应另开 sandbox runner 设计并独立审批，不再重复同一闭环。
5. 后续决策分级降噪：rerank/TOLF 试接、证据链字段补强、测试/文档/小范围配置 gate 属于 AI 自决策；只有重构级目录/接口/默认链大迁移、删除 legacy/用户资料、修改 secrets/env、修改评测口径、明显超预算长跑、最终 release gate 需要再问用户。

## 预先决策包（待用户批量确认）

> 本节用于把全项目推进中的关键分叉提前显式化。默认策略是：结构性缺失、治理空洞、可回滚的小步修复由 AI 自决策推进；会改变默认主链、评测口径、外部预算或高影响交付定义的事项，在本节集中预先确认。确认后，下游执行不再逐项打断。

### 预决策矩阵

|ID|决策项|AI 自决策建议|需要用户确认的原因|默认回滚方式|状态|用户选择|证据回填|
|---|---|---|---|---|---|---|---|
|PD-001|短期默认检索链是否允许把 reranker 置为 evidence-gated 非默认|允许。若 aligned canary / Gate B pilot 继续证明当前 reranker 默认链路有害，则短期默认 `--no-rerank` 作为控制/降压路径；但 reranker 必须作为一等能力纳入架构与后续评测。后续可由 AI 在证据充分、可回滚且不改评测口径的前提下自决策启用 rerank canary 或局部主链试接。|会影响默认排序路径，但可回滚；同时必须避免把“默认非开启”误读成“架构移除 reranker”。|恢复 `DEFAULT_USE_RERANK` 或运行参数；reranker client、配置、评测任务不删除。|已确认|同意 AI 默认（2026-04-27）；用户随后明确“rerank必须加入”；2026-05-02 用户确认“后续可以走有rerank”，并要求此类小决策降级为 AI 自决策|`.squad/decisions/inbox/copilot-2026-04-27-full-project-predecisions.md`；`/memories/repo/reranker-first-class-but-gated.json`；当前计划 2026-05-02 决策回填|
|PD-002|reranker 对照矩阵优先级|先跑 `no-rerank` control，再跑 8B、4B、BGE；不先动 LLM。`no-rerank` 只作为控制组，不作为替代 reranker 的长期架构结论。|涉及付费/耗时评测顺序，但不改变最终模型。|保留所有 metrics/progress/per_query，按矩阵重跑。|已确认|同意 AI 默认（2026-04-27）|`.squad/decisions/inbox/copilot-2026-04-27-full-project-predecisions.md`|
|PD-003|Tier3 / Gate B 旧中间态处理|旧 full/canary 指标只作历史证据，不再用于模型选择；以 Gate B pilot / aligned canary 为准。|会改变后续讨论引用的主证据源。|在计划 Open 中保留旧指标引用，不删除原文件。|已确认|同意 AI 默认（2026-04-27）|`.squad/decisions/inbox/copilot-2026-04-27-full-project-predecisions.md`|
|PD-004|会话持久化最小范围|先做 `resume / fork / rewind / checkpoint` 最小 API + 契约测试；不做完整 UI。|新 API 契约会影响后续前端和状态存储。|API behind router/test；不接前端前可回滚。|已确认|同意 AI 默认（2026-04-27）|`.squad/decisions/inbox/copilot-2026-04-27-full-project-predecisions.md`|
|PD-005|前端本轮范围|只补 `retrievalTopK`、首问扫描边界、失败占位入库策略；不扩写新 UI 面。|会限定本轮前端工作范围。|保留现有页面结构，仅回退新增控件/配置。|已确认|同意 AI 默认（2026-04-27）|`.squad/decisions/inbox/copilot-2026-04-27-full-project-predecisions.md`|
|PD-006|TOLF 推进口径|先做专项评估原型，不无证据替换默认主链；后续 RAG 完善中允许 AI 自决策做 default-off adapter、guarded canary 或可回滚主链试接。|防止把长期目标误报成默认链路切换；但用户已确认 TOLF/rerank 试接属于可降级小决策，不应频繁打断。|TOLF 评测脚本/产物独立放置；主链试接必须保留开关与标准 RAG 对照。|已确认|同意 AI 默认（2026-04-27）；2026-05-02 用户补充“后续自决策可以考虑在 RAG 完善时候接入主链”，并要求此类决策降级|`.squad/decisions/inbox/copilot-2026-04-27-full-project-predecisions.md`；当前计划 2026-05-02 决策回填|
|PD-007|长跑执行方式|当 Squad 运行在 Copilot Chat / VS Code 中时，>10 分钟、付费 eval、批量处理默认优先在当前会话内按 checkpoint 分段推进并持续留证；仅在需要 detached/background 持续运行、会话/工具限制阻塞执行、或用户明确要求时，才交接到 Copilot CLI Sessions。|影响执行组织方式与等待方式。|回到会话内短任务切片或交接到 CLI；不恢复退役 wrapper。|已确认|已按治理更新为 chat-first（2026-04-28）|`.squad/decisions/inbox/copilot-2026-04-27-full-project-predecisions.md`、`.squad/decisions/inbox/copilot-chat-first-longrun.md`|
|PD-008|Go/No-Go 权限边界|AI 可给 provisional Go/No-Go；最终“门禁通过/发布可用”需要独立复核或用户确认。|防止同一自主链路自我终审。|标记为 provisional，等待独立 review。|已确认|同意 AI 默认（2026-04-27）|`.squad/decisions/inbox/copilot-2026-04-27-full-project-predecisions.md`|

### 自决策默认项（无需逐项确认）

|ID|默认项|执行规则|回填要求|
|---|---|---|---|
|AD-001|计划细化、任务拆分、证据列补齐|直接做，不问。|在本文件追加任务状态与证据路径。|
|AD-002|结构性缺失修复|不触红线时先修，再回主任务。|写明 Facts / Decision / Evidence / Rollback。|
|AD-003|小范围文档/测试/脚本修补|L1 surgical 范围内直接做。|grep/read/test 复核。|
|AD-004|失败或过期引用纠偏|发现历史路径迁移、报告位置变化、旧状态不可信时直接更正。|保留旧锚点，说明新权威锚点。|
|AD-005|证据包与状态同步|每个切片结束自动写回计划与决策 inbox。|`Facts / Decisions / Open / Next`。|

### 人工审批硬边界（仍必须单独确认）

|ID|边界|说明|
|---|---|---|
|HB-001|修改 `.env` / secrets / 外部账号配置|涉及密钥或账号安全。|
|HB-002|提高付费服务预算或启动明显超日常预算的长跑|涉及成本上限。|
|HB-003|修改 corpus / goldset / qrels / 评测口径|会影响历史可比性。|
|HB-004|删除兼容层、legacy 路径、用户工作文档、画像、记忆、plan|不可替代决策。|
|HB-005|将未独立复核结果宣布为最终 gate pass / release Go|需独立复核或用户确认。|

## 可回填执行矩阵

|Task ID|Lane|目标|主要文件 / 产物|依赖决策|验证命令 / 验收证据|状态|证据路径|Next|
|---|---|---|---|---|---|---|---|---|
|TASK-000|Governance|重跑 Squad 升级总检，确认控制面可用|`.kilo/plans/2026-04-27-squad-official-capability-reuse.md`、`tools/squad/*`|AD-001|2026-04-28 已修 PowerShell 5 兼容性缺口：`profile-version-check.ps1` 改为动态解析 canonical v4 profile，`smoke-test.ps1` 改为 ASCII-only runtime checks + `powershell -ExecutionPolicy Bypass` 嵌套调用；复跑后 `profile-version-check/check-ghost/smoke-test` 全部 exit `0`，`SMOKE: OK (5/5)`|已完成|`.squad/orchestration-log/copilot-2026-04-28-governance-selfcheck-and-canary-audit.md`、`tools/squad/profile-version-check.ps1`、`tools/squad/smoke-test.ps1`、`tools/squad/check-ghost.ps1`|治理控制面恢复可用；继续 `TASK-020` 与后续 long-run slice|
|TASK-010|Eval|清理/确认 reranker 评测输入与输出路径，防 mixed-run|`eval_queries_v2.1_canary30_ALIGNED.jsonl`、`artifacts/eval_audit/*`、`output/*`|PD-002、PD-003|blocked manifest 与 rerun manifest 均已创建；输入 hash 与唯一输出路径 precheck 完成|已完成|`.squad/orchestration-log/copilot-2026-04-27-no-rerank-control-blocked.md`、`.squad/orchestration-log/copilot-2026-04-28-no-rerank-control-rerun-success.md`、`artifacts/eval_audit/manifests/20260427-canary30-aligned-no_rerank.json`、`artifacts/eval_audit/manifests/20260427-canary30-aligned-no_rerank-rerun1.json`|沿用同一 discipline 继续矩阵 runs|
|TASK-011|Eval|跑 `--no-rerank` control|`eval_retrieval_runtime.py`、`output/*no_rerank*`|PD-001、PD-002|rerun 成功；metrics/progress/per_query/rerank_trace/resume_guard 全部产出；Recall@5=0.6667，MRR=0.6667，p95=844.1ms|已完成|`.squad/orchestration-log/copilot-2026-04-28-no-rerank-control-rerun-success.md`、`artifacts/eval_audit/manifests/20260427-canary30-aligned-no_rerank-rerun1.json`、`output/20260427-canary30-aligned-no_rerank-rerun1.metrics.json`|继续 TASK-012 8B reranker control|
|TASK-012|Eval|跑 env 现货 reranker control matrix|`reranker_client.py`、`output/*rerank*`|PD-002|fresh run 必须显式 pin `(api_key, base_url, model)` 并证明真实 rerank：`rerank_api_* > 0` 或 trace 明确 `rerank_fallback=true` 且 reason 已审阅；2026-04-28 已修复 DashScope probe payload，显式 live inventory 证明 DashScope `qwen3-vl-rerank` / `qwen3-rerank` / `gte-rerank-v2` 均 `probe_ok=true` 且 `request_ok=true`；随后又补上 DashScope embedding live 兼容（2560→1024 归一化 + multimodal batch cap=20），并完成三条 pinned c16 canary：`qwen3-rerank`=`Recall@5 0.0667 / MRR 0.0517 / avg_latency_ms 20801.14`，`gte-rerank-v2`=`0.0 / 0.05 / 17960.16`，`qwen3-vl-rerank`=`0.1 / 0.0682 / 20063.44`；三者 artifacts 均 `30/30/30` 对齐、`resume_guard` 模型匹配、trace 无 fallback/warning，但全部显著劣于当前 embedding 语义下的 no-rerank control（`Recall@5=0.6667`, `MRR=0.6667`, `avg_latency_ms=1148.37`）；SiliconFlow `BAAI/bge-reranker-v2-m3` / `netease-youdao/bce-reranker-base_v1` 仍为 403 insufficient balance|已完成|`.squad/orchestration-log/copilot-2026-04-28-rerank8b-control1-invalid.md`、`.squad/orchestration-log/copilot-2026-04-28-rerank-keypool-fix-credential-block.md`、`.squad/orchestration-log/copilot-2026-04-28-rerank-probe-fix-env-matrix.md`、`.squad/orchestration-log/copilot-2026-04-28-qwen3-rerank-c16-canary-rerun-success.md`、`.squad/orchestration-log/copilot-2026-04-28-no-rerank-current-embed-control.md`、`.squad/orchestration-log/copilot-2026-04-29-gte-rerank-c16-canary-result.md`、`.squad/orchestration-log/copilot-2026-04-29-qwen3-vl-rerank-c16-canary-result.md`、`.squad/orchestration-log/copilot-2026-04-29-dashscope-reranker-provisional-verdict.md`、`artifacts/eval_audit/manifests/20260428-canary30-aligned-qwen3-rerank-c16-canary1-rerun1.json`、`artifacts/eval_audit/manifests/20260428-canary30-aligned-no_rerank-c16-current-embed-control1.json`、`artifacts/eval_audit/manifests/20260428-canary30-aligned-gte-rerank-c16-canary1.json`、`artifacts/eval_audit/manifests/20260429-canary30-aligned-qwen3-vl-rerank-c16-canary1.json`、`output/20260428-canary30-aligned-qwen3-rerank-c16-canary1-rerun1.metrics.json`、`output/20260428-canary30-aligned-no_rerank-c16-current-embed-control1.metrics.json`、`output/20260428-canary30-aligned-gte-rerank-c16-canary1.metrics.json`、`output/20260429-canary30-aligned-qwen3-vl-rerank-c16-canary1.metrics.json`|保持 no-rerank 为当前短期默认基线；后续若继续 Wave 4，优先查 embedding candidate observability / runtime client reuse，而不是继续提升这批 DashScope rerankers为默认|
|TASK-013|Eval|跑 runtime 并发边界 smoke|`eval_retrieval_runtime.py`、`reranker_client.py`、`output/*concurrency*`|PD-002|在 pinned rerank model 下先比较 `16 / 32 / 48`；2026-04-28 smoke 已确认 provider-direct `qwen3-rerank` 在 fresh process 下 `16/32/48` 全成功，runtime-level 当时仅 `16` 可用，`32/48` 在 `20s` 外层限时下整批超时；2026-04-29 先修复 `model_call_gateway.py` 内部 `rerank=3` 硬编码并使其 honor 并发现有 env，再继续在 `reranker_client.py` 落地 shared `httpx.AsyncClient` + async-native miss path（移除 `to_thread -> gated_call -> run_coroutine_threadsafe` 线程回跳）；post-fix live runtime smoke（当前 env 解析到 DashScope `qwen3-vl-rerank`, `rerank_source=key-pool:unknown`, `fallback_count=0`）已完成 `16/32/48`：`c16=15 成功 / 1 timeout`，`c32=31 / 1`（hot rerun 仍 `31 / 1`），`c48=47 / 1` 且观测到 1 次真实 `429`；整批 cliff 已移除，残余问题收敛为单个 tail timeout|已完成|`.squad/orchestration-log/copilot-2026-04-28-qwen3-rerank-concurrency16-32-48-matrix.md`、`.squad/orchestration-log/copilot-2026-04-29-rerank-gateway-concurrency-fix.md`、`.squad/orchestration-log/copilot-2026-04-29-rerank-async-native-runtime-recovery.md`、`tests/test_model_call_gateway.py`、`tests/test_reranker.py`|转 `TASK-130`：针对 residual single-timeout 补 observability，并在需要时显式 pin live rerank candidate 重跑一轮|
|TASK-014|Eval|补齐其余 env DashScope reranker 候选|`reranker_client.py`、`output/*dashscope_rerank*`|PD-002|在同一 query/qrels slice 上补齐 `qwen3-vl-rerank`、`gte-rerank-v2` 与 `qwen3-rerank` 对照；2026-04-28/29 已用 reusable pinned runner `tools/eval/run_pinned_rerank_manifest.py` 完成全部 DashScope 可用候选的 c16 canary，形成可直接横向比较的对照矩阵|已完成|`.squad/orchestration-log/copilot-2026-04-28-gte-rerank-c16-canary-envelope.md`、`.squad/orchestration-log/copilot-2026-04-29-gte-rerank-c16-canary-result.md`、`.squad/orchestration-log/copilot-2026-04-29-qwen3-vl-rerank-c16-canary-envelope.md`、`.squad/orchestration-log/copilot-2026-04-29-qwen3-vl-rerank-c16-canary-result.md`、`.squad/orchestration-log/copilot-2026-04-29-dashscope-reranker-provisional-verdict.md`、`artifacts/eval_audit/manifests/20260428-canary30-aligned-gte-rerank-c16-canary1.json`、`artifacts/eval_audit/manifests/20260429-canary30-aligned-qwen3-vl-rerank-c16-canary1.json`、`tools/eval/run_pinned_rerank_manifest.py`、`output/20260428-canary30-aligned-gte-rerank-c16-canary1.run.log`、`output/20260429-canary30-aligned-qwen3-vl-rerank-c16-canary1.run.log`|DashScope matrix 已补齐；后续转入 provisional verdict / 观测性改进|
|TASK-020|GateB|Tier3 / Gate B 三件套一致性验收|`output/*metrics*.json`、`*.progress.jsonl`、`*.per_query.jsonl`|PD-003|2026-04-28 已对最新 aligned canary 双跑（`qwen3-rerank` rerun + current-embed `no-rerank` control）做只读一致性审计；2026-04-29 进一步结合 `gte-rerank-v2` / `qwen3-vl-rerank` 的同 slice metrics 与现有 provisional verdict 收口：当前 trusted 四向对照在相同 retrieval settings 下已具备一致 query source、完整 sidecars、`progress/per_query/trace=30/30/30`、匹配的 `resume_config`/pinned rerank model，可用于 GateB/Tier3 provisional judgment|已完成|`.squad/orchestration-log/copilot-2026-04-28-governance-selfcheck-and-canary-audit.md`、`.squad/orchestration-log/copilot-2026-04-29-dashscope-reranker-provisional-verdict.md`、`.squad/orchestration-log/copilot-2026-04-29-gateb-tier3-provisional-judgment.md`、`output/20260428-canary30-aligned-qwen3-rerank-c16-canary1-rerun1.metrics.json`、`output/20260428-canary30-aligned-gte-rerank-c16-canary1.metrics.json`、`output/20260429-canary30-aligned-qwen3-vl-rerank-c16-canary1.metrics.json`、`output/20260428-canary30-aligned-no_rerank-c16-current-embed-control1.metrics.json`、`output/20260428-canary30-aligned-qwen3-rerank-c16-canary1-rerun1.metrics.json.resume_config.json`、`output/20260428-canary30-aligned-no_rerank-c16-current-embed-control1.metrics.json.resume_config.json`、`eval_queries_v2.1_canary30_ALIGNED.jsonl`|继续 `TASK-130` / `TASK-013`：优先处理 runtime client reuse / embedding provenance observability，再决定是否需要新的高并发或 reranker follow-up slice|
|TASK-030|Backend|会话持久化 API 契约与 SQLite 恢复闭环|`routers/runtime_router.py`、`writing_runtime.py`、`repositories/writing_runtime_repository.py`、`tests/test_*session*.py`|PD-004|`tests/test_runtime_router_contract.py tests/test_writing_runtime_persistence.py -q` 成功，12 passed in 9.70s；OpenAPI 预检已导出|已完成|`.squad/orchestration-log/copilot-2026-04-27-session-runtime-tests.md`、`artifacts/preflight/modular-pipeline-openapi.json`|继续 TASK-112 前端类型闭环|
|TASK-040|Frontend|检索配置与扫描行为闭环|`frontend/src/pages/Workbench.tsx`、`frontend/src/pages/Settings.tsx`、`frontend/src/pages/KnowledgeBase.tsx`、`frontend/src/services/settingsStore.ts`|PD-005|TASK-112/120/121/122 均完成；`npm run generate:openapi` 成功；`npm run build` 成功（最新 Vite built in 7.45s）|已完成|`.squad/orchestration-log/copilot-2026-04-27-frontend-retrieval-scan.md`、`.squad/orchestration-log/copilot-2026-04-27-frontend-openapi.md`、`.squad/orchestration-log/copilot-2026-04-27-frontend-scan-params.md`|进入 TASK-100 eval manifest|
|TASK-050|Runtime|主运行时与成熟 guard 组件对齐|`layers/r_layer_hybrid_retriever.py`、`chunk_vector_store.py`、`reranker_client.py`、`token_utils.py`|PD-001、PD-002|2026-04-29 已完成三处高价值最小闭环切口：其一，`TASK-140` 已把共享 local retriever 接回 `reranker_client.rerank_async()`，并对齐 pre-top-n / hard-cap 与 rerank provenance；其二，`main_rag_workflow.py` 已恢复 `last_answer.json` 原子写入与 `last_answer_persisted` 事件记录，同时持久化实际路由后的 `current_model`，修复主问答链的可审计闭环；其三，`pipeline_core.py` 的 TOLF embedding 路径已切回 `chunk_vector_store.batch_embed_texts(...)`，不再使用 `urllib.request` + 固定 `64` batch + `[:512]` 字符截断，转而复用成熟 embedding config resolution、provider-aware batching、token guard 与 failover。Focused regression：`pytest tests/test_embedding_batch_chunking.py tests/test_pipeline_tolf_embedding_alignment.py tests/test_pipeline_observability.py tests/test_main_rag_workflow_citation.py tests/test_llm_provider_routing.py tests/test_reranker.py tests/test_eval_runtime.py -q` -> `77 passed in 35.07s`。当前仍保留的 query-embedding / strict-cache-guard 差异已降为低优先级结构性议题，不再阻塞本轮 runtime guard 收口|已完成|`.squad/orchestration-log/copilot-2026-04-29-task140-shared-retriever-rerank-alignment.md`、`.squad/orchestration-log/copilot-2026-04-29-task050-last-answer-persistence-fix.md`、`.squad/orchestration-log/copilot-2026-04-29-task050-tolf-embedding-guard-alignment.md`、`main_rag_workflow.py`、`layers/r_layer_hybrid_retriever.py`、`chunk_vector_store.py`、`pipeline_core.py`、`tests/test_main_rag_workflow_citation.py`、`tests/test_llm_provider_routing.py`、`tests/test_main_rag_workflow_generation.py`、`tests/test_pipeline_tolf_embedding_alignment.py`|Wave 5 当前高价值 guard 对齐已收口；若继续推进，应转入新的低优先级优化或后续 wave，而不是继续在本 slice 上扩刀|
|TASK-060|TOLF|TOLF 上游专项评估与 ablation 原型|`layers/tolf_engine.py`、`test_tolf_engine.py`、新增 `eval_tolf_*`|PD-006|已完成 text-only pilot 原型：`TASK-150/151/152` 形成固定/MAQ × evidence × richer mask 的本地零外部成本 ablation 面，并保留 default-off 的 representative rerank stage；focused regression `pytest tests/test_tolf_text_pilot.py test_tolf_engine.py -q` 最新 `33 passed in 24.27s`，sample report 已确认包含 `mask_summary` 与 `representative_rerank` 元数据|已完成|`.squad/orchestration-log/copilot-2026-04-27-tolf-text-pilot.md`、`.squad/orchestration-log/copilot-2026-04-29-tolf-mask-rerank-reservation.md`、`artifacts/tolf/text_pilot_sample_report.json`|不接默认主链；若未来需要 live reranker adapter，再开新切片|
|TASK-070|Evidence|写入决策 inbox 与日终证据包|`.squad/decisions/inbox/*`、`.squad/orchestration-log/*`|AD-005|文件存在 + Facts/Decisions/Open/Next 完整|每切片执行||同步本计划|
|TASK-080|Reference|把 `github/` 下载源码库固化为 RAG/TOLF 参考地图|`github/INDEX.md`、`github/RAG_TOLF_REFERENCE_MAP.md`、`github/project-notes/*.md`|AD-001、PD-006|Markdown 文件存在；重点项目有证据路径；reranker 一等能力表述一致|已完成|`github/INDEX.md`、`github/RAG_TOLF_REFERENCE_MAP.md`、`github/project-notes/`|后续按映射拆 TOLF prototype|

## GitHub 参考库吸收计划（2026-04-27 新增）

### 边界

|目录|定位|使用边界|
|---|---|---|
|`github/`|下载的外部源码/项目参考库|用于学习机制、产品形态、评测方式；不作为当前运行路径|
|`.github/`|Copilot/Squad/skills/workflows 配置资产|用于 agent 行为、技能和工作流；不与外部源码参考库混同|

### 已固化文档

|文档|用途|
|---|---|
|`github/INDEX.md`|按 RAG/TOLF、知识库/API、skill/写作、UI/产品、低相关/归档整理下载项目|
|`github/RAG_TOLF_REFERENCE_MAP.md`|按 TOLF 能力维度映射参考项目与吸收路线|
|`github/project-notes/*.md`|为重点项目建立项目卡片，记录路径、价值、TOLF 映射、风险和证据|

### 吸收优先级

|优先级|参考项目|先吸收的机制|对应任务|
|---|---|---|---|
|P0|`sa-rag-0.1.0`|spreading activation、query-edge mask、多跳传播 trace|TASK-060|
|P0|`Doris-Mae-Dataset-main`|multi-level aspect query、科学文献候选池、aspect relevance|TASK-060、后续 TOLF eval|
|P0|`LightRAG-1.4.15`|Graph RAG、实体关系抽取、图索引、reranker 配置|TASK-050、TASK-060|
|P0|`RAG-Anything-1.2.10`|多模态文献单元、表格/公式/图像 evidence unit|TASK-060 后续扩面|
|P0|`Knowledge-Base-Gateway-1.2.2026.10009`|Zotero/EndNote/Obsidian 本地科研资料接入|后续 connector design|
|P1|`nano-graphrag-0.0.8`|轻量 GraphRAG prototype 接口边界|TASK-060|
|P1|`WeKnora-main`、`open-webui-0.8.12`|知识库产品化、Wiki Mode、RAG UI、观测性|TASK-040 后续 UI/产品化|
|P1|`mempalace-3.0.0`|长期研究记忆、证据/决策沉淀|TASK-070 与长跑恢复|
|P1|`academic-research-skills-3.1`|学术研究/写作 pipeline skill 化|TOLF 结构化 generation 后续|

### Reranker 纠偏声明

reranker 必须加入 RAG/TOLF 架构，并保留为代表单元精排的一等能力。当前 aligned canary 中 reranker ON 有害，只能支持“默认启用需要证据门控”这一结论，不能支持“移除 reranker”这一结论。`--no-rerank` 是控制组、降压路径和短期安全默认候选，不是长期架构替代品。

### UI 参考与共享页面联调规则（2026-04-29 新增）

- **设计参考源**：前端视觉、窗口层级、工作台布局优先参考 `github/` 下载项目中的界面设计、截图与产品文档，尤其是知识库工作台、科研工具与独立窗口风格项目。
- **运行态验证源**：当前本地 `localhost` 页面只作为功能 smoke、状态检查、回归交互和封装前行为验证入口，不作为最终设计基线。
- **自动交互触发条件**：当页面已在 VS Code 中打开并处于“与智能体共享”状态时，AI 可直接对共享页面元素执行点击、输入、切换、滚动与状态读取，不要求用户先把元素添加到聊天。
- **元素附加到聊天的定位**：仅在复杂布局、元素歧义或需要人工精确指认时作为可选增强，不应成为长跑前置依赖。

|场景|何时使用共享页面直接交互|期望证据|
|---|---|---|
|新功能交互 smoke|新 UI 功能落地后，直接验证按钮、Tab、Drawer、表单与主路径是否可达|shared page 交互记录 + build/test|
|回归验证|修复 bug 或重构后复跑关键路径，确认交互无退化|shared page 读数/状态变化 + focused 验证|
|状态态验证|验证 empty/loading/error/disabled/permission 等非 happy path|状态截图/读数 + 说明|
|写作/证据工作流验证|验证 `DraftStudio`、`Evidence`、`Citation Chain`、`Review` 等面板间的同步、滚动与聚焦|shared page 交互笔记 + 相关 build/test|
|独立窗口封装前 smoke|在准备本地独立窗口壳之前，先验证侧栏、工作区、设置、导出、切换等工具型窗口行为|封装前 smoke 记录 + Open/Next|

## 下一阶段 AI 自决策与详细执行规划（2026-04-27）

本节是对“接下来的全项目完整详细规划”的可执行化更新。规则是：AI 先对低风险、可回滚、证据充分的事项自决策；会触及成本、默认主链、外部资料写入、最终门禁的事项，集中列为待用户确认。

### AI 已自决策项（可直接执行，不逐项打断）

|ID|自决策|理由|证据锚点|回滚/保护|
|---|---|---|---|---|
|AD-006|继续以本文件作为唯一 master plan，不新建并行主计划。|避免 `.kilo/plans/` 内出现多个互相竞争的全项目计划。|本文件；repo memory: planning location uses `.kilo/plans`。|如需拆分，只新增子计划并在本文件引用。|
|AD-007|下一步先跑零成本/低风险预检，不直接启动付费 reranker eval。|符合 HB-002 成本硬边界，也能先发现环境/契约问题。|`frontend/package.json`、`routers/runtime_router.py`、`test_tolf_engine.py`。|预检失败只更新 Open，不改变默认链。|
|AD-008|会话持久化任务改为“契约与恢复闭环”，不是从零实现 API。|`runtime_router.py` 已暴露 `/runtime/session/{id}/resume`、`/runtime/session/{id}/rewind`、`/runtime/session/{id}/fork` 与 checkpoints；`writing_runtime.py` 已有对应方法。|`routers/runtime_router.py`、`writing_runtime.py`、`frontend/src/services/sessionApi.ts`。|若现有实现不稳定，只在测试/契约层补洞，不重写 runtime。|
|AD-009|前端检索闭环先补 Settings 暴露与扫描反馈，不扩 UI 大面。|`settingsStore.ts` 已有 `retrievalTopK`；Workbench 已使用该值；KnowledgeBase 已有扫描入口与失败结果展示。|`frontend/src/services/settingsStore.ts`、`frontend/src/pages/Workbench.tsx`、`frontend/src/pages/KnowledgeBase.tsx`。|仅回退 Settings/scan 小改动，不影响页面结构。|
|AD-010|TOLF 下一步做 ablation/eval harness，不重造 engine。|`layers/tolf_engine.py` 已实现 MAQ、SpreadingActivation、EvidenceGate；`test_tolf_engine.py` 已覆盖核心行为。|`layers/tolf_engine.py`、`test_tolf_engine.py`、`github/RAG_TOLF_REFERENCE_MAP.md`。|TOLF eval 产物独立，不接默认主链。|
|AD-011|参考库只作为架构/机制来源，不复制外部项目代码。|多个外部项目存在许可证/再分发边界，且当前目标是规划与机制吸收。|`github/INDEX.md`、`github/project-notes/*.md`。|若未来需要代码复用，单独做 license review。|
|AD-012|所有 eval 输出必须先有 run manifest 或唯一输出路径，禁止混写旧 metrics/progress/per_query。|已有 repo memory 指出 eval runtime 会 append JSONL，混跑会污染决策。|`eval_retrieval_runtime.py` progress/per_query append 行为；repo memory: evaluation outputs。|发现混写立即作废该 run，只保留历史参考。|
|AD-013|reranker 评测必须同时输出模型身份、配置、trace 与 fallback 状态。|否则无法区分模型效果、候选池变化和 API fallback。|`eval_retrieval_runtime.py` 的 rerank model/config/trace 字段。|缺 trace 的 reranker run 不用于默认链路决策。|
|AD-014|每个执行切片结束必须写回本文件状态列与证据路径。|让下个 agent 能从计划直接恢复，不靠聊天记忆。|本文件 `可回填执行矩阵` 与 AD-005。|未写证据的任务保持 `待执行` 或 `进行中`，不标完成。|
|AD-015|只要页面已在 VS Code 中共享，就优先用共享页面做自动 UI 元素交互与验证。|避免长跑依赖人工点击“添加元素到聊天”；当前工具链已能直接对共享页面执行读/点/输。|本文件“UI 参考与共享页面联调规则（2026-04-29 新增）”；当前会话用户确认。|若页面未共享或不可访问，则回退到 build/test/代码审阅，必要时再由用户人工附加元素。|
|AD-016|前端视觉与独立窗口形态参考优先锚定 `github/` 参考库，而不是当前本地 `localhost` 实例。|防止把临时运行页误判成最终产品母版，保持窗口型产品方向稳定。|`github/INDEX.md`、`github/project-notes/*.md`、本次用户要求。|当前本地页面仅保留为运行态验证源；如参考项目变化，再更新本文件与 Squad 决策记录。|
|AD-017|接口设计和代码实施前强制先回档并检索成熟方案。|用户已明确要求以后干活必须“回档以及搜索网上成熟方案”；skill 接口属于安全/扩展性高影响设计，尤其需要先参考官方/成熟模式。|本文件约束；Dify plugin manifest、MCP tools/prompts/resources/roots、LangChain tools、VS Code extension manifest 官方文档。|缺少回档点或成熟方案对标记录的切片不得进入实现；只读调研可先做，写入前必须有 rollback snapshot。|

### 需要用户集中确认的高影响决策（已回填用户选择）

|ID|待确认决策|AI 推荐默认|状态|用户选择（2026-04-27）|执行约束|
|---|---|---|---|---|---|
|PD-009|是否允许进入“非付费预检 + focused tests”执行段|同意。先跑零成本预检、导入、focused tests、OpenAPI/前端 build。|已确认|同意 AI 默认：立即进入非付费预检。|AI 可自动跑 TASK-000、TASK-020 audit、TASK-030 focused tests、TASK-040 build。|
|PD-010|是否允许在预检通过后启动付费/耗时 reranker eval|原建议为每轮单独确认。|已确认|用户回复：“都同意，env里面的随便用”。|本轮授权使用现有 `.env` / 环境变量启动必要 eval；禁止打印密钥、禁止修改 `.env`，必须先生成 manifest 和唯一输出路径。|
|PD-011|reranker 矩阵跑完后，是否授权 AI 按阈值自动改短期默认链|原建议为只给 provisional 建议。|已确认|授权 AI 按阈值自动切默认。|只有在同一 trusted slice、manifest、metrics/progress/per_query/trace 一致且回滚方式明确时，才允许自动切短期默认；reranker 能力不得删除。|
|PD-012|TOLF 第一轮 prototype 是否限制为 text-only ablation|同意。先做 text chunk / graph / mask / evidence gate；多模态只做接口预留。|已确认|同意 AI 默认：text-only ablation 先行。|多模态/connector 本轮只预留接口或设计，不进入默认 runtime。|
|PD-013|本地科研知识库连接器是否只读设计，不写 Zotero/EndNote/Obsidian|同意。只读 connector design，禁止写用户资料源。|已确认|同意 AI 默认：只读 connector。|禁止写外部科研资料源；任何写回/同步能力需另行确认。|
|PD-014|最终 Gate Pass / Release Go 是否必须独立复核|原建议为必须独立复核或用户确认。|已确认|用户授权 AI 自主最终 Gate Pass。|按治理约束执行：AI 可自主推进最终结论，但同一执行链不能自评自批；最终 Gate 需独立 review pass、可审计证据包或后续显式用户确认。|

### 详细路线图（从当前状态到可交付）

|Wave|目标|入口任务|主要文件/产物|完成标准|并行性|
|---|---|---|---|---|---|
|Wave 0|控制面与环境预检|TASK-000、TASK-090、TASK-091|`tools/squad/*`、`python_adapter_server.py`、`frontend/package.json`|Squad smoke/profile/ghost 通过；后端 app import；前端 build 可执行|可与 Wave 1 的只读审计并行|
|Wave 1|评测资产与输出隔离|TASK-010、TASK-020、TASK-100、TASK-101|`eval_retrieval_runtime.py`、`eval_queries_*`、`output/*`、`artifacts/eval_audit/*`|生成 run manifest；确认 query/qrels/config/output 不混旧行|不启动 paid eval|
|Wave 2|会话持久化闭环|TASK-030、TASK-110、TASK-111、TASK-112|`routers/runtime_router.py`、`writing_runtime.py`、`repositories/writing_runtime_repository.py`、`frontend/src/services/sessionApi.ts`|resume/fork/rewind/checkpoints API 契约测试通过；SQLite reload 后可恢复 timeline|后端先行，前端客户端随后验证|
|Wave 3|前端检索/扫描闭环|TASK-040、TASK-120、TASK-121、TASK-122|`Settings.tsx`、`settingsStore.ts`、`Workbench.tsx`、`KnowledgeBase.tsx`|Settings 可配置 retrievalTopK；首问扫描边界明确；扫描失败占位稳定；`npm run build` 通过|可与 Wave 2 后半并行|
|Wave 4|Reranker 矩阵与默认门控决策|TASK-011、TASK-012、TASK-013、TASK-014、TASK-130|`reranker_client.py`、`eval_retrieval_runtime.py`、`output/*rerank*`|同一 trusted slice 上产出 no-rerank + env-available pinned reranker metrics/trace，并比较默认并发与 `50` 并发；当前 live inventory 已确认 3 个 DashScope 模型可用、2 个 SiliconFlow 模型余额阻塞；满足阈值和回滚条件后可自动切短期默认|PD-010 已授权使用现有 env；执行前仍需 manifest、唯一输出路径与显式 model pinning|
|Wave 5|主运行时对齐|TASK-050、TASK-140、TASK-141|`layers/r_layer_hybrid_retriever.py`、`chunk_vector_store.py`、`token_utils.py`|主链与评测链参数/guard 对齐；focused retrieval pytest 通过|依赖 Wave 4 provisional 结论|
|Wave 6|TOLF text-only ablation pilot|TASK-060、TASK-150、TASK-151、TASK-152|`layers/tolf_engine.py`、`test_tolf_engine.py`、`eval_tolf_*`、`github/RAG_TOLF_REFERENCE_MAP.md`|mask/weight/evidence ablation 报告；不接默认主链；`pytest test_tolf_engine.py` 通过|可在 Wave 1 后准备，最终对照依赖稳定评测资产|
|Wave 7|科研资料入口、产品输出与共享页面验证设计|TASK-160、TASK-161、TASK-162、TASK-163|`docs/*` 或 `.kilo/plans/*`、`github/project-notes/*`、`.squad/decisions/inbox/*`|只读 Zotero/EndNote/Obsidian connector 设计；论文输出/引用 UI 草图；共享页面自动交互协议固定；独立窗口终态约束明确；不写外部资料源|可与 Wave 6 并行做设计，不写代码|
|Wave 8|总验收与交接|TASK-070、TASK-170、TASK-171|`.squad/decisions/inbox/*`、`.squad/orchestration-log/*`、本文件|证据包完整；Open/Next 清晰；Go/No-Go 为 provisional 或已独立确认|所有 wave 收口后执行|
|Wave 9|前端产品化补齐与真实体验闭环|TASK-176、TASK-177、TASK-178、TASK-179、TASK-180、TASK-181、TASK-182、TASK-192|`frontend/src/pages/*`、`frontend/src/components/writing/*`、`frontend/src/services/*`、`frontend/src/types/*`、`frontend/playwright.config.*`、`frontend/tests/e2e/*`、`frontend/src/locales/*`|会话恢复不再停留在 console-only；扫描失败可操作；academic export 有前端消费入口；默认测试集覆盖前端核心参数链；bundle warning 有处理或明确豁免；新增文案完成 i18n/a11y 基线；Playwright smoke 只有在隔离 server + deterministic mocks + runner exit 0 后才算 gate pass|依赖 Wave 8 schema lane；已完成多数 UI/build/unit 切片，当前优先收口 Playwright runner 稳定性，不用手动 DevTools 替代 E2E|
|Wave 10|用户自定义 Skill 扩展层|TASK-183、TASK-184、TASK-185、TASK-186、TASK-187、TASK-188、TASK-189、TASK-190、TASK-191、TASK-192|`skills/*`、`routers/*skill*`、`models/*skill*`、`frontend/src/pages/Settings.tsx`、`frontend/src/components/skills/*`、`frontend/src/services/*skill*`、`tests/test_skill_*`、`frontend/tests/e2e/*skill*`|基础 RAG/AI/写作能力保留为 builtin/base capability；用户 Skill 通过 manifest-driven package 接入；支持导入/启用/禁用/测试/审计；权限、root 边界、脚本策略、模型调用、网络/文件访问均可见可控；后端 contract、前端 UI 和单元/build/manual smoke 已通过；E2E gate 仍需 Playwright exit 0 后补齐|先只读设计与 threat model，再做 manifest/import，不触 Claude 正在处理的 API 连通性；写入前必须有回档点和成熟方案对标证据；当前不得改 `.env`、API key、provider routing、connectivity scripts|

### 细化任务池（新增）

|Task ID|Wave|目标|主要文件 / 产物|验证 / 完成标准|状态|证据路径|Next|
|---|---|---|---|---|---|---|---|
|TASK-090|0|确认 Python/FastAPI 入口可导入且 router 注册完整|`python_adapter_server.py`、`routers/runtime_router.py`、`artifacts/preflight/modular-pipeline-openapi.json`|后端 app import 成功；route count=108；resume/fork/rewind route 存在；OpenAPI schema 导出成功|已完成|`.squad/orchestration-log/copilot-2026-04-27-preflight.md`、`artifacts/preflight/modular-pipeline-openapi.json`|进入 runtime contract tests|
|TASK-091|0|确认前端质量门命令存在并可构建|`frontend/package.json`、`frontend/dist/`|`npm run build` 成功，Vite build finished in 6.54s|已完成|`.squad/orchestration-log/copilot-2026-04-27-preflight.md`|后续前端改动后重跑 build|
|TASK-092|0|运行 focused baseline tests|`tests/test_session_memory_resume.py`、`test_tolf_engine.py`|`pytest tests/test_session_memory_resume.py test_tolf_engine.py -q` 成功，27 passed in 34.29s|已完成|`.squad/orchestration-log/copilot-2026-04-27-preflight.md`|继续 TASK-101/TASK-110|
|TASK-100|1|生成 eval run manifest 模板，防 mixed-run|`artifacts/eval_audit/*`、`output/*`|`artifacts/eval_audit/run_manifest_template.json` 与 `RUN_MANIFEST_GUIDE.md` 已创建；模板要求 run_id、输入 hash、唯一输出路径、command、trace、postrun checks|已完成|`.squad/orchestration-log/copilot-2026-04-27-eval-manifest-template.md`|再跑 control|
|TASK-101|1|只读审计历史 metrics/progress/per_query 是否混旧行|`output/*metrics*.json`、`*.progress.jsonl`、`*.per_query.jsonl`|最近 20 个 metrics 初审完成；未见明显 mixed-run；多数旧 metrics 缺 sidecar，标 WARN/历史证据|已完成|`.squad/orchestration-log/copilot-2026-04-27-eval-artifact-audit.md`|TASK-100 先补 manifest，再跑新 eval|
|TASK-110|2|补 runtime session API 契约测试|`tests/test_runtime_router_contract.py` 或 `tests/test_*session*.py`|已有测试覆盖 create/list/current/resume/timeline/checkpoints/rewind/fork；focused suite 通过|已完成|`.squad/orchestration-log/copilot-2026-04-27-session-runtime-tests.md`|接 TASK-112|
|TASK-111|2|验证 SQLite 持久化重载后 session/timeline/checkpoint 可恢复|`writing_runtime.py`、`repositories/writing_runtime_repository.py`|已有持久化测试覆盖 reload/resume/repair/blob spill；focused suite 通过|已完成|`.squad/orchestration-log/copilot-2026-04-27-session-runtime-tests.md`|失败只修持久化边界|
|TASK-112|2|前端 `SessionApiService` 与 OpenAPI 类型对齐|`frontend/src/services/sessionApi.ts`、`frontend/src/types/runtime.ts`、`frontend/src/generated/openapi.ts`|`npm run generate:openapi` 成功；`npm run build` 成功，Vite built in 6.05s|已完成|`.squad/orchestration-log/copilot-2026-04-27-frontend-openapi.md`|接 UI 使用点|
|TASK-120|3|在 Settings Workspace 区暴露 `retrievalTopK` 控件|`frontend/src/pages/Settings.tsx`、`frontend/src/services/settingsStore.ts`|Settings 增加 3-20 bounded number control；Workbench 已读取 settings top_k；build 通过|已完成|`.squad/orchestration-log/copilot-2026-04-27-frontend-retrieval-scan.md`|不新增复杂 UI|
|TASK-121|3|明确首问扫描边界与失败占位策略|`frontend/src/pages/Workbench.tsx`、`frontend/src/pages/KnowledgeBase.tsx`|扫描失败展示失败图标/文案，不再走成功文案；build 通过|已完成|`.squad/orchestration-log/copilot-2026-04-27-frontend-retrieval-scan.md`|build 验证已完成|
|TASK-122|3|保持扫描请求的限流参数可审计|`Workbench.tsx`、`KnowledgeBase.tsx`|Workbench 已用命名常量记录 top_k、ingest_limit、scan_mode/batch/workers 默认值；build 通过|已完成|`.squad/orchestration-log/copilot-2026-04-27-frontend-scan-params.md`|必要时文档化|
|TASK-130|4|准备并执行 env 现货 reranker matrix 与并发路径|`eval_retrieval_runtime.py`、`reranker_client.py`、`artifacts/eval_audit/*`|no-rerank control 已成功产出 baseline；首个 8B run 已归档为 invalid；fallback/trace observability 已补齐；`reranker_client` 已接入 key-pool grouped candidate resolution + request-time failover；2026-04-28 进一步修复 DashScope probe payload，并通过 explicit live inventory 确认 `qwen3-vl-rerank` / `qwen3-rerank` / `gte-rerank-v2` 可用；并发 smoke 已确认 provider-direct 健康到 `48/50`。2026-04-29 先后完成 gateway 并发修复、shared `httpx.AsyncClient` 复用，以及 async-native rerank miss path 改造；live runtime 已从 `32/32 TIMEOUT` / `48/48 TIMEOUT` 恢复到 `c16=15/1`、`c32=31/1`、`c48=47/1`（无 bulk fallback，sample live model=`qwen3-vl-rerank`）；随后 timeout phase probe 进一步确认 residual timeout 固定表现为 `query 0 / attempts=1 / last_phase=provider_wait / queue_wait≈0ms`。在用户批准 one-shot live warm-up 后，已于 batch fan-out 前接入 best-effort 预热，并新增 one-shot 回归测试；复跑 warm-up smoke 后 `c16=16/16`、`c32=32/32`、`c48=48/48` 全成功，`fallback_count=0`，`c48` 虽仍有真实 `429 Throttling.RateQuota` 日志，但不再放大为 timeout，说明当前 Wave 4 runtime cliff 已完成恢复|已完成|`.squad/orchestration-log/copilot-2026-04-27-no-rerank-control-blocked.md`、`.squad/orchestration-log/copilot-2026-04-28-no-rerank-control-rerun-success.md`、`.squad/orchestration-log/copilot-2026-04-28-rerank8b-control1-invalid.md`、`.squad/orchestration-log/copilot-2026-04-28-rerank-keypool-fix-credential-block.md`、`.squad/orchestration-log/copilot-2026-04-28-rerank-probe-fix-env-matrix.md`、`.squad/orchestration-log/copilot-2026-04-28-qwen3-rerank-concurrency16-32-48-matrix.md`、`.squad/orchestration-log/copilot-2026-04-29-rerank-gateway-concurrency-fix.md`、`.squad/orchestration-log/copilot-2026-04-29-rerank-async-native-runtime-recovery.md`、`.squad/orchestration-log/copilot-2026-04-29-rerank-timeout-phase-probe.md`、`.squad/orchestration-log/copilot-2026-04-29-rerank-warmup-runtime-recovery.md`、`artifacts/eval_audit/manifests/20260427-canary30-aligned-no_rerank-rerun1.json`|Wave 4 已收口；按 D11 continuation gate 转入 `TASK-140`，继续对齐主运行时与评测链参数，并保留 provider `429` observability|
|TASK-140|5|对齐主运行时与评测链参数|`layers/r_layer_hybrid_retriever.py`、`chunk_vector_store.py`、`reranker_client.py`|2026-04-29 已把共享 local retriever 从内嵌旧 rerank HTTP 路径切到 `reranker_client.rerank_async()`，使主链复用 shared async client、provider semaphore、request-time failover、warm-up、fallback/provenance；同时把主链 rerank candidate depth 对齐到 eval 的 `RERANK_PRE_TOPN / RERANK_PRE_TOPN_HARD_CAP` 语义（默认 `30 / 60`），不再把粗排 Top50 全量送去 rerank；`main_rag_workflow.py` 也已保留本地 fallback 的 `rerank_score / rerank_model / rerank_source / rerank_fallback / warning` 元数据，并用 rerank score 作为本地 evidence score。Focused regression：`pytest tests/test_llm_provider_routing.py tests/test_reranker.py tests/test_eval_runtime.py tests/test_main_rag_workflow_generation.py::test_rag_search_preserves_local_rerank_metadata -q` -> `58 passed in 34.39s`。当前不把 `strict_cache_guard` 直接搬进主链，因为主链与 eval 仍不是同一套 dense retrieval implementation，此差异保留为后续结构性议题|已完成|`.squad/orchestration-log/copilot-2026-04-29-task140-shared-retriever-rerank-alignment.md`、`layers/r_layer_hybrid_retriever.py`、`main_rag_workflow.py`、`tests/test_llm_provider_routing.py`、`tests/test_main_rag_workflow_generation.py`|转 `TASK-050`：继续检查主运行时与成熟 retrieval/guard 组件是否仍有剩余偏差，并选下一处最小闭环切口|
|TASK-141|5|把 reranker fallback/trace 写入运行时可审计输出|`reranker_client.py`、相关 retrieval output|`_apply_fallback()` 现已显式标记 `rerank_fallback`；eval trace 会提升内部 fallback 并序列化 warning；targeted pytest 40 passed|已完成|`.squad/orchestration-log/copilot-2026-04-28-rerank8b-control1-invalid.md`、`reranker_client.py`、`eval_retrieval_runtime.py`、`tests/test_rerank_short_circuit_and_budget.py`、`tests/test_eval_runtime.py`|用 fresh rerun 验证修复后的 trace 进入真实 8B control|
|TASK-150|6|建立 TOLF text-only pilot 输入/输出格式|新增 `eval_tolf_*`、`artifacts/tolf/*`|`eval_tolf_text_pilot.py`、sample input/report 已创建；本地 hash text embeddings；`pytest tests/test_tolf_text_pilot.py test_tolf_engine.py -q` 通过，最新 29 passed in 28.68s|已完成|`.squad/orchestration-log/copilot-2026-04-27-tolf-text-pilot.md`、`artifacts/tolf/text_pilot_sample_report.json`|跑 ablation|
|TASK-151|6|运行 TOLF mask/weight/evidence ablation|`layers/tolf_engine.py`、`eval_tolf_*`|在原 fixed/MAQ × evidence on/off 2×2 基础上，已扩展 `fixed_cosine_mask` / `maq_cosine_mask` / `fixed_relation_mask` / `maq_relation_mask` richer mask 变体；sample report 已写出每个 ablation 的 `mask_summary`（含 `mask_kind`、kept/masked counts、chunk ids、allowed_point_types）；focused regression `pytest tests/test_tolf_text_pilot.py test_tolf_engine.py -q` 最新 `33 passed in 24.27s`|已完成|`.squad/orchestration-log/copilot-2026-04-27-tolf-text-pilot.md`、`.squad/orchestration-log/copilot-2026-04-29-tolf-mask-rerank-reservation.md`、`artifacts/tolf/text_pilot_sample_report.json`|如需更复杂 edge schema（非当前 text-only heuristic），另开新任务|
|TASK-152|6|TOLF 代表单元精排接口预留 reranker|`layers/tolf_engine.py`、`reranker_client.py` 或 adapter|已在 `TOLFEngine` 预留 post-evidence-gate 的 representative rerank stage：默认关闭，仅在显式传入 callback 且 `enable_representative_rerank=True` 时生效；pilot report 现已记录 `representative_rerank.enabled=false`、`stage=post_evidence_gate`，对应 focused regression 通过|已完成|`.squad/orchestration-log/copilot-2026-04-29-tolf-mask-rerank-reservation.md`、`layers/tolf_engine.py`、`test_tolf_engine.py`、`tests/test_tolf_text_pilot.py`|保持 default-off，不接默认主链；未来若接 live adapter 再单独评估|
|TASK-160|7|只读 Zotero/EndNote/Obsidian connector 设计|设计文档；参考 `Knowledge-Base-Gateway-1.2.2026.10009`|已完成只读 connector 设计文档：明确 Zotero / EndNote / Obsidian 统一走 read-only adapter → project-local `.scholarai/connectors/...` staging snapshot → 现有 `source_folder` / `scan-folder` / `folder_traversal` / `extract_literature_context` 链；约束包括不写回外部资料源、不复制整个资料库、保留 provenance、支持 `fast/balanced/deep` 三档|已完成|`.squad/orchestration-log/copilot-2026-04-29-wave7-academic-design.md`、`docs/copilot/2026-04-29-readonly-academic-connectors-design.md`|后续若进入实现，建议从 Zotero export/snapshot 最小切片开始，仍保持只读|
|TASK-161|7|论文输出与引用 UI 设计切片|设计文档；参考 `academic-research-skills-3.1`、`AI_paper--`|已完成 academic output UI 设计：在现有 `DraftStudio` / `WritingCanvas` / `ReferenceDrawer` / `citation_anchors` 骨架上定义 `Evidence` / `Citation Chain` / `Review` 三个核心视图，目标输出包含 source anchors、证据表、引用链与 evidence-gap 审计|已完成|`.squad/orchestration-log/copilot-2026-04-29-wave7-academic-design.md`、`docs/copilot/2026-04-29-academic-output-citation-ui-design.md`|后续实现优先走 DraftStudio 增量扩展，不另起第二套编辑器|
|TASK-162|7|实现 academic output 最小 Evidence / Citation Chain / Review 视图|`frontend/src/components/DraftStudio.tsx`、`frontend/src/components/writing/WritingCanvas.tsx`、`frontend/src/components/writing/ReferenceDrawer.tsx`、`frontend/src/lib/citationAnchors.ts`|已在现有 `citation_anchors` spine 上完成最小实现：`ReferenceDrawer` 新增 `Evidence` / `Citation Chain` / `Review` 三视图，复用当前 draft、material、anchor 数据完成证据聚合、段落-引用链追踪与 evidence-gap 审计；独立复核后又补上实例级 anchor 聚焦与 dangling material 审计，`frontend/` 下 `npm run build` 两次成功（5.41s / 5.51s）|已完成|`.squad/orchestration-log/copilot-2026-04-29-task162-evidence-citation-review-implementation.md`、`frontend/src/components/DraftStudio.tsx`、`frontend/src/components/writing/WritingCanvas.tsx`、`frontend/src/components/writing/ReferenceDrawer.tsx`、`frontend/src/lib/citationAnchors.ts`、`frontend/src/types/writing.ts`|若继续扩面，优先补 backend evidence contract / export formatting，而不是另起第二套 citation system|
|TASK-163|7|固化共享页面自动 UI 验证与独立窗口约束|`.kilo/plans/2026-04-27-full-project-build-master-plan.md`、`.squad/decisions/inbox/copilot-2026-04-29-shared-ui-autotest-and-design-reference.md`、`.squad/orchestration-log/copilot-2026-04-29-shared-ui-autotest-plan-sync.md`|master plan 已明确：1）设计参考源优先 `github/` 参考库；2）共享页面可直接自动元素交互；3）“添加元素到聊天”仅为可选增强；4）适用场景覆盖新功能 smoke、回归、状态态验证、写作工作流验证与封装前 smoke|已完成|`.kilo/plans/2026-04-27-full-project-build-master-plan.md`、`.squad/decisions/inbox/copilot-2026-04-29-shared-ui-autotest-and-design-reference.md`、`.squad/orchestration-log/copilot-2026-04-29-shared-ui-autotest-plan-sync.md`|后续 UI 切片若页面已共享，优先直接纳入 shared-page validation，不额外引入人工定位前置|
|TASK-164|7|补 academic output focused frontend tests 护栏|`frontend/package.json`、`frontend/vite.config.ts`、`frontend/src/test/setup.ts`、`frontend/src/lib/citationAnchors.test.ts`、`frontend/src/components/writing/ReferenceDrawer.test.tsx`|已补最小 Vitest + jsdom + React Testing Library 测试基建，并新增 focused tests 覆盖 citation anchor parsing/range 与 ReferenceDrawer evidence/review heuristics；保持现有 `citation_anchors` spine，不扩到 backend evidence contract，也不引入 Jest|已完成|`.squad/orchestration-log/copilot-2026-04-29-task164-focused-frontend-tests.md`、`frontend/package.json`、`frontend/vite.config.ts`、`frontend/src/test/setup.ts`、`frontend/src/lib/citationAnchors.test.ts`、`frontend/src/components/writing/ReferenceDrawer.test.tsx`、`frontend/src/components/writing/sessionDrawerHelpers.test.mjs`|若继续 academic output，下一刀转 backend evidence contract / export formatting；helper `node:test` 入口统一仅作可选 hygiene|
|TASK-170|8|写阶段证据包与 Open/Next|`.squad/orchestration-log/*`、本文件|已补写 Wave 7 gate review evidence pack，明确 `Facts / Decisions / Open / Next`，并把当前非阻塞开放项收口为 backend evidence contract / focused tests 两个后续入口|已完成|`.squad/orchestration-log/copilot-2026-04-29-wave7-gate-review.md`|同步 `TASK-171` 的 provisional go 结论|
|TASK-171|8|形成 Gate Go/No-Go 结论|`.squad/decisions/inbox/*`、独立 review 证据包|PD-014 已确认；独立 gate review 对 `TASK-162` / Wave 7 slice 给出 `PASS WITH NOTES`，Blocking issues=`none`，允许将该切片视作“最小可交付且可继续推进下一任务”的 provisional go；该结论不等于全项目 release pass|已完成|`.squad/decisions/inbox/copilot-2026-04-29-wave7-task162-provisional-go.md`、`.squad/orchestration-log/copilot-2026-04-29-wave7-gate-review.md`|若继续 academic output，优先 formalize backend evidence contract / export formatting；focused frontend tests 已于 `TASK-164` 完成|
|TASK-172|8|formalize backend evidence contract / export formatting|`routers/resources_router.py`、`tests/test_resources_router_contract.py`、`docs/copilot/2026-04-29-academic-output-citation-ui-design.md`|已用 TDD 补齐 `/resources/project/{project_id}/export` 的 additive JSON `evidence_rows` / `citation_chain` / `review_findings` 与 Markdown `证据表` / `引用链` / `审计提示`；不改持久化 schema、不新增 endpoint、不触碰外部资料源；focused suite `.venv-1\Scripts\python.exe -m pytest tests\test_resources_router_contract.py tests\test_writing_resource_persistence.py -q` 通过，`7 passed in 22.43s`|已完成|`.squad/orchestration-log/copilot-2026-04-30-backend-evidence-export-contract.md`、`.squad/decisions/inbox/copilot-2026-04-30-backend-evidence-export-contract-implemented.md`、`output/20260430-backend-evidence-export-contract.md`|后续若前端要消费 export 新字段，再单独跑 OpenAPI/frontend 类型切片；当前无需扩大 UI 改动|
|TASK-173|8|OpenAPI / response model 固化 academic export appendix|`models/resources.py`、`routers/resources_router.py`、`frontend/src/generated/openapi.ts`、`frontend/src/types/resources.ts`、`tests/test_resources_export_contract.py`|已完成 response model / OpenAPI schema 固化：新增 `ProjectExportPayload` 及 evidence/citation/review 子模型，`export_project` 改为正式 `response_model`；先用 RED 证明 OpenAPI 仍是匿名 object，再 GREEN 到 `#/components/schemas/ProjectExportPayload`；Codex 先前已完成 contract tests + 前端本地类型同步；本轮复跑 focused pytest `10 passed in 23.03s`，`npm run generate:openapi` 成功，`npm run build` 成功（built in 2.55s）|已完成|`.squad/orchestration-log/codex-2026-04-30-academic-export-contract-verification.md`、`.squad/orchestration-log/codex-2026-04-30-post-task172-frontend-consumption-verification.md`、`.squad/orchestration-log/copilot-2026-04-30-task173-openapi-export-schema.md`、`.squad/decisions/inbox/copilot-2026-04-30-task173-openapi-export-schema-complete.md`、`output/20260430-task173-openapi-export-schema.md`|下一步回到 master plan continuation gate；若继续 academic output，优先做 schema 风险复盘/前端真实消费需求判断，不再重复改 export 基础合同|
|TASK-174|8|TASK-173 独立 schema 风险复盘与前端类型去重|`frontend/src/types/resources.ts`、`frontend/src/types/resources.test.ts`、`.squad/orchestration-log/*`、`output/*`|已完成 TASK-173 独立 review：code-review agent 未发现 Critical/Important 阻塞；唯一中等级建议是 `frontend/src/types/resources.ts` 手写 export appendix interfaces 与 generated OpenAPI schema 重复。已按 TDD 增加 type alias guard，先观察 RED，再把 `ProjectExportResult` / evidence / citation / review 类型改为 `components["schemas"][...]` aliases；fresh verification：backend focused pytest `10 passed in 12.24s`，frontend type test `1 passed`，`npm run build` 成功（built in 2.56s）|已完成|`.squad/orchestration-log/copilot-2026-04-30-task174-schema-risk-review.md`、`.squad/decisions/inbox/copilot-2026-04-30-task174-schema-risk-review-complete.md`、`output/20260430-task174-schema-risk-review.md`|当前 academic export schema lane 已完成独立复盘；下一步只能回到 master plan broader gate，若无新真实消费需求，不新增 UI|
|TASK-175|8|Wave 8 academic export gate review / provisional go|`.squad/orchestration-log/*`、`.squad/decisions/inbox/*`、`output/*`|已完成 Wave 8 academic export lane gate review：`TASK-172/173/174` 证据链完整，focused backend pytest、OpenAPI generation、frontend type guard/build 均有 fresh exit 0 证据；独立 code-review 未发现 blocking issues，唯一维护建议已在 `TASK-174` 处理。结论限定为 academic export schema lane `PASS WITH NOTES / provisional go`，不等同全项目 release pass|已完成|`.squad/orchestration-log/copilot-2026-04-30-wave8-academic-export-gate-review.md`、`.squad/decisions/inbox/copilot-2026-04-30-wave8-academic-export-provisional-go.md`、`output/20260430-wave8-academic-export-gate-review.md`|回到 broader master-plan gate；若无真实 frontend consumer / release-packaging 指令，停止扩展 academic export UI|
|TASK-176|9|Workbench 会话恢复 UI 实体化|`frontend/src/pages/Workbench.tsx`、`frontend/src/components/writing/SessionDrawer.tsx`、`frontend/src/hooks/useSessionPersistence.ts`、`frontend/src/services/sessionApi.ts`、`frontend/src/types/runtime.ts`|已实现会话恢复/fork/rewind 到聊天流映射与可见反馈，避免只停留在 `console.info`；本轮未重新审阅全部 UX 细节，但默认 Vitest 与 build 已覆盖当前前端集|基本完成|`frontend/src/hooks/useSessionPersistence.ts`、`frontend/src/components/writing/SessionDrawer.tsx`、`frontend/src/pages/Workbench.tsx`、`npm run test` -> `34 passed`、`npm run build` -> success|后续只在 Playwright 用户路径中验证恢复/fork/rewind 可达，不再扩大组件重写|
|TASK-177|9|KnowledgeBase 扫描失败可操作化|`frontend/src/pages/KnowledgeBase.tsx`、`frontend/src/services/*`、`frontend/src/locales/zh.json`|扫描面板已区分成功 / 部分失败 / 全失败，展示失败详情并提供重试；`zh.json` parse、Vitest 默认集、build 已通过|基本完成|`frontend/src/pages/KnowledgeBase.tsx`、`frontend/src/locales/zh.json`、`node -e "JSON.parse(require('fs').readFileSync('src/locales/zh.json','utf8')); console.log('zh.json ok')"`、`npm run test` -> `34 passed`、`npm run build` -> success|后续如后端返回更细粒度失败文件列表，再补字段兼容与 E2E 状态态|
|TASK-178|9|前端消费 academic export schema|`frontend/src/services/*`、`frontend/src/types/resources.ts`、`frontend/src/components/writing/ReferenceDrawer.tsx`、`frontend/src/components/writing/ExportPreviewModal.tsx`|已接入 academic export 前端预览/复制/下载入口，并修正 schema drift：导出 payload 使用 `content` 而非旧 `markdown` 字段；仍需在 Playwright smoke 中覆盖导出预览路径|基本完成|`frontend/src/components/writing/ExportPreviewModal.tsx`、`frontend/src/components/writing/ReferenceDrawer.tsx`、`frontend/src/types/resources.ts`、`npm run test` -> `34 passed`、`npm run build` -> success|后续只补 E2E mock payload 和用户可见断言，不新增后端 endpoint|
|TASK-179|9|前端 E2E / shared-page smoke 基线|`frontend/playwright.config.ts`、`frontend/vite.config.e2e.ts`、`frontend/tests/e2e/mockApi.ts`、`frontend/tests/e2e/a-smoke.spec.ts`、`frontend/tests/e2e/skill-manager.spec.ts`、`.squad/orchestration-log/*`|已完成 Windows 稳定化 E2E smoke：Playwright webServer 使用独立 `127.0.0.1:3100` Vite E2E config；mock API 只拦截 `fetch/xhr`，避免误拦 Vite 模块；`/chat/providers` 返回数组；route smoke 使用 root warm-up + sidebar navigation；官方口径仍采用 route mock、role/text locator 与 web-first assertions。Codex 2026-05-01 独立复跑 `npm run test:e2e -- --reporter=line` -> `16 passed (50.7s)`|已完成|`frontend/playwright.config.ts`、`frontend/vite.config.e2e.ts`、`frontend/tests/e2e/mockApi.ts`、`frontend/tests/e2e/a-smoke.spec.ts`、`frontend/tests/e2e/skill-manager.spec.ts`、`.squad/decisions/inbox/codex-2026-05-01-frontend-e2e-gate.md`、`.squad/orchestration-log/codex-2026-05-01-frontend-e2e-gate.md`|保持 E2E 作为后续前端变更 gate；若新增页面，再扩 `a-smoke.spec.ts`，不要恢复宽泛 catch-all mock|
|TASK-180|9|前端测试默认集补齐与 helper 统一|`frontend/package.json`、`frontend/src/**/*.test.*`、`frontend/src/components/writing/sessionDrawerHelpers.test.mjs`|默认 Vitest 集已覆盖当前核心前端 helper / 组件路径，本轮复核 `npm run test` 通过 `34 passed`；若仍保留少量 `node:test` helper，必须确保不会成为默认测试盲区|基本完成|`npm run test` -> `34 passed`|后续新增测试必须默认纳入 `npm run test`，不要只放孤立脚本|
|TASK-181|9|前端 bundle / route-level performance hardening|`frontend/src/App.tsx`、`frontend/src/pages/*`、`frontend/vite.config.ts`|已采用 route-level `React.lazy` / `Suspense` 拆分重页面，`npm run build` 成功，主 bundle 约 `405 kB`，无 500 kB warning；对标 React 官方 lazy/Suspense，不盲目调高 warning limit|已完成|`frontend/src/App.tsx`、`npm run build` -> success, main chunk around `405 kB`|后续只在新增重页面时延续 route-level lazy，不做无目标 chunk 微调|
|TASK-182|9|前端 i18n / a11y / keyboard polish|`frontend/src/locales/zh.json`、`frontend/src/pages/*`、`frontend/src/components/writing/*`|新增 Wave 9/10 文案已补齐到 `zh.json`，JSON parse 通过；基础用户可见 locator 已随 TASK-179/192 E2E smoke 覆盖核心导航、Settings、Skill Manager tab、按钮和审计面板；不再以“待 E2E 验证”阻塞 Wave 9|已完成|`frontend/src/locales/zh.json`、`npm run test` -> `34 passed`、`npm run build` -> success、`npm run test:e2e -- --reporter=line` -> `16 passed`|后续新增 drawer/modal/keyboard path 随具体功能增量补测试|
|TASK-183|10|用户 Skill 成熟方案对标与威胁模型|`docs/copilot/2026-04-30-user-skill-extension-design.md`、`.squad/orchestration-log/codex-2026-04-30-user-skill-backend-contract.md`、本文件|已按 AD-017 建立回档点并对标 Dify manifest/permission/privacy、MCP tools/prompts/resources/roots、LangChain typed tools/runtime context、VS Code manifest/contributes/activation；明确 prompt-only、workflow、tool-wrapper、scripted 四类 Skill 的风险分级、默认权限和回滚策略；不触碰 Claude 的 API/provider connectivity 工作|已完成|`.rollback_snapshots/skill-backend-20260430-191116`、`.rollback_snapshots/skill-backend-persistence-20260430-192609`、`docs/copilot/2026-04-30-user-skill-extension-design.md`、`.squad/orchestration-log/codex-2026-04-30-user-skill-backend-contract.md`|后续 runtime 执行仍需保持 scripted blocked，新增高风险权限前重新对标成熟方案|
|TASK-184|10|定义用户 Skill 包格式与验证器|`skills/SKILL.md.template`、`skills/models.py`、`skills/user_manifest.py` 或 `skills/validators.py`、`tests/test_skill_manifest*.py`|已实现 `SKILL.md` frontmatter validator：覆盖 `id/name/version/kind/entry_mode/ui_visibility/supported_scopes/permissions/input_schema/output_schema/root_policy/script_policy/model_policy/privacy_notes/rollback_hint`；校验 id、SemVer、相对路径、path traversal、权限默认 deny、script safe_to_execute 禁止由用户 manifest 自行开启；PyYAML 可用时支持嵌套 YAML，失败时回退轻量 parser|已完成|`skills/user_manifest.py`、`tests/test_skill_manifest.py`、`.venv-1\Scripts\python.exe -m pytest tests\test_skill_manifest.py tests\test_skill_import.py tests\test_skill_router_contract.py test_skill_registry.py -q` -> `47 passed`|后续如加入 zip/package signing，再扩 validator 合同|
|TASK-185|10|用户 Skill 存储与导入流水线|`skills/user/` 或 project-local managed skill root、`skills/importers/*`、`skills/service.py`、`tests/test_skill_import*.py`|已支持从本地目录导入到 managed root：导入前 manifest validation、文件数量/单文件/总大小限制、SHA-256 content hash；覆盖导入前自动备份到 managed root 内 `.rollback_snapshots`；导入后写 `.install_meta.json`，默认 disabled、untrusted、script blocked，并注册到统一 `WritingSkillService` registry；zip 导入未进 MVP|已完成|`skills/importers/user_skill_importer.py`、`skills/persistence.py`、`skills/service.py`、`tests/test_skill_import.py`、`tests/test_skill_router_contract.py`、focused pytest `47 passed`|卸载/恢复 UI 入口仍归后续任务；当前只允许托管根内可见与启停|
|TASK-186|10|Skill Registry / Approval / Audit 持久化与启停状态|`skills/registry.py`、`skills/approval.py`、`skills/audit.py`、`repositories/*skill*`、`tests/test_skill_registry*.py`|已完成最小持久化闭环：`WritingSkillService` 启动时自动扫描 managed root 的 user skills；enable/disable 写回 `.install_meta.json`，重启后恢复 enabled/disabled；test-run 后写回 `last_run_at/last_status/last_warnings`；`AuditLog` 支持 append-only JSONL 并可重载；builtin/base capability 仍不可通过用户 Skill 管理禁用；所有 import/enable/disable/test-run 继续写 audit event|已完成|`.rollback_snapshots/skill-run-state-20260430-195200`、`skills/persistence.py`、`skills/audit.py`、`skills/service.py`、`tests/test_skill_runtime.py`、`tests/test_skill_router_contract.py`、focused pytest `53 passed`|仍待补：卸载/回滚 API、approval decision 持久化；暂不扩大到账号体系或 SQLite|
|TASK-187|10|Skill 执行运行时与沙箱策略|`skills/runtime.py`、`skills/service.py`、`model_call_gateway.py` 或 adapter、`tests/test_skill_runtime*.py`|已实现 MVP 安全运行时：prompt-only 只做受控 template render，不执行表达式、不访问网络、不写文件、不调用模型；workflow kind 进入同一受控路径并标记 execution_mode；scripted skill、高风险 `network/files.write/script.execute` 权限默认 blocked；运行结果包含 `structured_output`、`evidence_refs`、`warnings`、`audit_id`；`/skills/{id}/test-run` 返回 `SkillTestRunResponse` 结构化 OpenAPI payload|已完成|`.rollback_snapshots/skill-runtime-20260430-194314`、`skills/runtime.py`、`skills/service.py`、`models/skills.py`、`routers/skills_router.py`、`tests/test_skill_runtime.py`、`tests/test_skill_router_contract.py`、`.squad/orchestration-log/codex-2026-04-30-user-skill-runtime.md`、focused pytest `53 passed`|后续如接真实 LLM/tool-wrapper，必须新增审批/预算/roots gate；scripted 仍不进默认执行路径|
|TASK-188|10|后端 Skill 管理 API 合同|`routers/skills_router.py` 或现有 router、`models/*skill*.py`、`frontend/openapi/modular-pipeline-openapi.json`、`tests/test_skill_router_contract.py`|已固化 `GET /skills`、`GET /skills/{id}`、`POST /skills/import`、`POST /skills/{id}/enable`、`POST /skills/{id}/disable`、`POST /skills/{id}/test-run`、`GET /skills/audit`；`/skills/audit` 已放在动态路由前防 shadow；新增 `ImportUserSkillRequest/Response`、`SkillToggleResponse` 等 Pydantic response model；OpenAPI schema 可生成且 router contract 覆盖 validation/not_found/legacy transform result|已完成|`routers/skills_router.py`、`models/skills.py`、`models/__init__.py`、`tests/test_skill_router_contract.py`、focused pytest `47 passed`|后续若前端生成 OpenAPI，需要再跑 frontend/openapi 同步；不触碰 provider connectivity|
|TASK-189|10|前端 Skill Manager UI|`frontend/src/pages/Settings.tsx`、`frontend/src/components/skills/*`、`frontend/src/services/skillApi.ts`、`frontend/src/types/skills.ts`、`frontend/src/locales/zh.json`|Skill Manager MVP 已接入 Settings：基础功能区 / 用户 Skill 区分展示，支持本地路径导入、启用/禁用、测试运行、审计列表、权限/脚本/高风险 badge 与 i18n；Codex 复核后新增 `evidenceReferences` helper 回归测试并确认 `npm run test` 默认集通过 34 tests、`npm run build` 成功|已完成|`frontend/src/components/skills/SkillManager.tsx`、`frontend/src/services/skillApi.ts`、`frontend/src/types/skills.ts`、`frontend/src/locales/zh.json`、`.squad/orchestration-log/codex-2026-04-30-wave10-gemini-skill-contract-fix.md`|MVP 可用；原计划中的”前端创建 prompt-only skill”和高风险启用二次确认仍需后续 UI hardening，不把 smoke 误报为完整 UX gate|
|TASK-190|10|用户 Skill 接入 RAG 文献助手调用面|`frontend/src/pages/Workbench.tsx`、`frontend/src/components/DraftStudio.tsx`、`frontend/src/components/writing/*`、`skills/service.py`、`tests/test_runtime_router_contract.py`|已完成用户 Skill 手动触发闭环：启用且安全的 imported prompt/workflow Skill 自动映射为 legacy action；`/runtime/job` 使用 `action_id` 时解析到真实 `skill_id` 执行，不再把 accepted envelope 当最终 artifact；runtime artifact 保留 `output_text`、`structured_output`、`evidence_refs`、`audit_id`；DraftStudio/WritingCanvas 解析并展示 evidence refs，结果继续走 diff/preview|已完成|`.rollback_snapshots/codex-wave10-verify-20260430-204107`、`skills/service.py`、`routers/runtime_router.py`、`writing_runtime.py`、`frontend/src/lib/evidenceReferences.ts`、`frontend/src/components/DraftStudio.tsx`、`frontend/src/components/writing/WritingCanvas.tsx`、`tests/test_runtime_router_contract.py`、`.squad/orchestration-log/codex-2026-04-30-wave10-gemini-skill-contract-fix.md`|不触碰默认 RAG 主链、回答提示词、检索默认链、评测口径或 Claude API/provider/connectivity 工作|
|TASK-191|10|用户 Skill E2E、文档与 gate review|`frontend/tests/e2e/skill-manager.spec.ts`、`docs/copilot/2026-04-30-user-skill-extension-design.md`、`.squad/orchestration-log/*`、`.squad/decisions/inbox/*`|Skill Manager E2E 已稳定通过：覆盖基础能力/我的 Skill 渲染、导入错误路径、启用/停用、测试运行结果、审计日志；Codex 2026-05-01 独立复跑 `npm run test:e2e -- --reporter=line` -> `16 passed`，其中 `skill-manager.spec.ts` 5 tests 全部通过。结论从 2026-04-30 provisional 升级为 frontend gate pass；后端卸载/回滚 API 与 approval decision 持久化仍属后续非 E2E hardening|已完成|`frontend/tests/e2e/skill-manager.spec.ts`、`frontend/tests/e2e/mockApi.ts`、`frontend/src/components/skills/SkillManager.tsx`、`.squad/decisions/inbox/codex-2026-05-01-frontend-e2e-gate.md`、`.squad/orchestration-log/codex-2026-05-01-frontend-e2e-gate.md`、`npm run test` -> `34 passed`、`npm run build` -> success、`npm run test:e2e -- --reporter=line` -> `16 passed`|后续如新增真实 zip/import happy path、高风险权限审批 UI、卸载/回滚 API，再新增专门 E2E，不复用本任务扩大范围|
|TASK-192|9/10|Playwright runner 稳定化与前端 gate 收口|`frontend/playwright.config.ts`、`frontend/vite.config.e2e.ts`、`frontend/tests/e2e/mockApi.ts`、`frontend/tests/e2e/a-smoke.spec.ts`、`frontend/tests/e2e/skill-manager.spec.ts`、`.squad/orchestration-log/*`|已完成 Windows / Vite / Playwright 稳定化：E2E 使用无 proxy 的 `vite.config.e2e.ts`；`page.route()` mock 限定 `fetch/xhr`，不拦截 document/script/style；`/chat/providers` mock 类型对齐数组；`a-smoke.spec.ts` 通过 root warm-up 与 sidebar navigation 避免直达路由 500；webServer 单 worker、复用 existing server。Codex 独立复跑 `npm run test:e2e -- --reporter=line` -> `16 passed (50.7s)`|已完成|`.rollback_snapshots/codex-frontend-e2e-gate-20260501_010038`、`frontend/playwright.config.ts`、`frontend/vite.config.e2e.ts`、`frontend/tests/e2e/mockApi.ts`、`frontend/tests/e2e/a-smoke.spec.ts`、`frontend/tests/e2e/skill-manager.spec.ts`、`.squad/decisions/inbox/codex-2026-05-01-frontend-e2e-gate.md`|继续把 E2E 作为前端回归 gate；若未来出现端口残留，只清理确认由 Playwright/Vite 生成的 Node 进程|
|TASK-193|10|Skill approval decision 持久化（设计先行）|`skills/approval.py`、`skills/persistence.py`、`skills/service.py`、`routers/skills_router.py`、`models/skills.py`、`tests/test_approval_persistence.py`|已完成 SQLite-backed `ApprovalStore` 持久化：`approval_requests` / `approval_decisions` 表、重启后保留 pending/decision history、`POST /skills/approvals/requests`、`GET /skills/approvals/pending`、`GET /skills/approvals/{id}`、`POST /skills/approvals/{id}/decide`，并为 submit/decide 写 AuditLog；OpenAPI 暴露 `SkillApproval*` 命名 schema；前端审批 UI 仍留后续切片|已完成|`.rollback_snapshots/task-193-approval-store-20260501_045958`、`.squad/decisions/inbox/codex-2026-05-01-longrun-default-approval.md`、`.squad/orchestration-log/codex-2026-05-01-task193-approval-persistence.md`、`tests/test_approval_persistence.py`、focused pytest `50 passed`、compileall pass、OpenAPI approval schema probe pass|TASK-194 已完成；下一步转前端审批 / 卸载 / 回滚 UX 或高风险权限审批 UI；不动 builtin approval；不触碰默认 RAG 主链、corpus/goldset/qrels、`.env` 内容|
|TASK-194|10|Skill 卸载 / 回滚 API（设计先行）|`skills/service.py`、`routers/skills_router.py`、`models/skills.py`、`models/__init__.py`、`skills/registry.py`、`tests/test_skill_uninstall.py`|已完成 `DELETE /skills/{id}`（仅 managed user skill；builtin 返回 403；支持 dry_run）与 `POST /skills/{id}/rollback`（latest 或 explicit backup_path）；卸载前复制到 managed root `.rollback_snapshots`，卸载后移除 registry entry；rollback 会校验 snapshot path 不逃逸 rollback root、manifest id 与 URL skill_id 一致，并排除 `*-broken-*` 快照；每步写 AuditLog；OpenAPI 暴露 `SkillUninstallResponse`、`SkillRollbackRequest`、`SkillRollbackResponse` 命名 schema；前端 UX 留后续切片|已完成|`.rollback_snapshots/task-194-skill-uninstall-rollback-20260501_051449`、`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260501-051814-task-194-skill-uninstall-continue`、`.squad/orchestration-log/codex-2026-05-01-task194-skill-uninstall-rollback.md`、`tests/test_skill_uninstall.py`、focused pytest `58 passed`、compileall pass、`run_literature_assistant.py paths` pass、OpenAPI skill hardening schema probe pass|不删除 `.install_meta.json` 历史；rollback 失败时保留 broken snapshot；下一步转前端审批 / 卸载 / 回滚 UX 或高风险权限审批 UI，仍不触默认 RAG 主链、corpus/goldset/qrels、`.env` 内容|
|TASK-195|10|Skill Manager 审批 / 卸载 / 回滚前端 UX hardening|`frontend/src/components/skills/SkillManager.tsx`、`frontend/src/services/skillApi.ts`、`frontend/src/types/skills.ts`、`frontend/src/components/ui/Modal.tsx`、`frontend/src/locales/zh.json`、`frontend/tests/e2e/skill-manager.spec.ts`、`frontend/tests/e2e/mockApi.ts`、`frontend/openapi/modular-pipeline-openapi.json`、`frontend/src/generated/openapi.ts`|已完成前端消费 TASK-193/194 后端契约：新增审批 tab 展示 pending approvals 并支持 approve / deny / defer；用户 Skill 卡片新增卸载与回滚入口；卸载使用 `alertdialog` 语义、默认焦点落取消按钮、先 dry-run 预览 backup/removed path，再执行 DELETE；回滚支持 latest snapshot 或 explicit backup_path；同步 OpenAPI schema/types；E2E 覆盖审批、卸载确认、回滚、既有启停/测试/审计路径|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260501-053331-frontend-skill-approval-uninstall-ux`、`.squad/orchestration-log/codex-2026-05-01-task195-skill-manager-hardening.md`、`npm run build` -> success、`npm run test` -> `34 passed`、`npm run test:e2e -- tests/e2e/skill-manager.spec.ts --reporter=line` -> `8 passed`、`npm run test:e2e -- --reporter=line` -> `19 passed`、backend focused pytest `58 passed`、`npm run generate:openapi` -> success|后续若继续 Skill 层，优先真实 zip/import happy path 或高风险权限审批 UI；不触默认 RAG 主链、corpus/goldset/qrels、`.env` 内容|
|TASK-196|10|高风险用户 Skill 启用审批门禁|`skills/service.py`、`skills/approval.py`、`routers/skills_router.py`、`tests/test_skill_router_contract.py`、`tests/test_skill_runtime.py`、`frontend/src/services/skillApi.ts`、`frontend/src/components/skills/SkillManager.tsx`、`frontend/tests/e2e/skill-manager.spec.ts`、`frontend/tests/e2e/mockApi.ts`|已完成服务器端强制审批：含 `network` / `files.write` / `script.execute` 或脚本声明的 imported Skill 在首次 enable 时返回 `409 approval_required` 并自动创建 pending approval；重复 enable 复用 pending request，不刷屏；批准后才能写入 enabled 状态；前端识别 409 后展示“启用前需要审批”并切到审批 tab；即使审批后启用，MVP runtime 仍阻断网络/脚本执行；OpenAPI schema/types 同步|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260501-054956-task-196-high-risk-skill-approval-gate`、`.squad/orchestration-log/codex-2026-05-01-task196-high-risk-skill-approval-gate.md`、backend focused pytest `59 passed`、`npm run build` -> success、`npm run test` -> `34 passed`、`npm run test:e2e -- tests/e2e/skill-manager.spec.ts --reporter=line` -> `9 passed`、`npm run test:e2e -- --reporter=line` -> `20 passed`、compileall pass、`npm run generate:openapi` -> success|后续 Skill 层剩余建议：真实 zip/import happy path、脚本型 Skill 单独安全设计、权限审计可视化；仍不触默认 RAG 主链、corpus/goldset/qrels、`.env` 内容|
|TASK-197|10|真实 zip/import happy path 后端切片|`literature_assistant/core/skills/importers/user_skill_importer.py`、`literature_assistant/core/skills/service.py`、`literature_assistant/core/routers/skills_router.py`、`literature_assistant/core/models/skills.py`、`tests/test_skill_import.py`、`tests/test_skill_router_contract.py`|已完成用户 Skill 导入双入口：`source_path` 现在接受目录或 `.zip` 包；zip 导入支持单顶层目录包根解析，并在解压前拦截坏包、绝对路径、路径穿越、重复归一化条目、加密条目以及超量文件/体积；目录导入原契约保持兼容；高风险权限审批、卸载/回滚、运行时网络/脚本阻断继续沿用 TASK-196 边界|已完成|`.rollback_snapshots/codex-task197-zip-import-\+\20260501_111234`、`.squad/orchestration-log/codex-2026-05-01-task197-skill-zip-import-happy-path.md`、`.squad/decisions/inbox/codex-2026-05-01-task197-skill-zip-import-happy-path.md`、focused pytest `26 passed`、扩展 Skill 回归 `60 passed`、compileall pass|后续若继续 Skill 层，优先前端 zip/import package validation UX、脚本型 Skill 独立安全设计或权限审计可视化；仍不触默认 RAG 主链、corpus/goldset/qrels、`.env` 内容|
|TASK-198|10|前端 zip/import package validation UX|`frontend/src/components/skills/SkillManager.tsx`、`frontend/src/locales/zh.json`、`frontend/tests/e2e/skill-manager.spec.ts`、`frontend/tests/e2e/mockApi.ts`|已完成前端导入体验补齐：明确“目录或 `.zip` 包”导入入口、运行边界提示、zip 导入成功回执，以及 invalid zip 机器错误到中文提示的首轮映射；保持脚本/网络执行仍 blocked|已完成|`.rollback_snapshots/copilot-task198-frontend-20260501_145959`、`.squad/orchestration-log/copilot-2026-05-01-task198-frontend-zip-import-ux-complete.md`、focused Skill Manager E2E `11 passed`、`npm run build` -> success、`npm run test` -> `34 passed`|后续继续把导入错误处理从字符串匹配收敛到稳定错误码，必要时由 Codex补前后端契约，不触默认 RAG 主链、corpus/goldset/qrels、`.env` 内容|
|TASK-199|10|Skill import 错误契约前后端补位|`literature_assistant/core/skills/importers/user_skill_importer.py`、`literature_assistant/core/routers/skills_router.py`、`tests/test_skill_import.py`、`tests/test_skill_router_contract.py`、`frontend/src/services/skillApi.ts`、`frontend/src/services/skillApi.test.ts`、`frontend/src/components/skills/SkillManager.tsx`、`frontend/src/locales/zh.json`、`frontend/tests/e2e/mockApi.ts`、`frontend/tests/e2e/skill-manager.spec.ts`|已完成 `/skills/import` 失败 detail 稳定化：后端返回机器可读 `error_code + errors`，覆盖 invalid zip、unsafe archive entry、invalid manifest、missing `SKILL.md`、package limit、source path 等失败态；前端改为基于错误码提示 zip/manifest/路径问题，并仅做“空输入/明显不支持后缀”浅预检，仍把 archive safety、manifest validity、路径存在性交给后端作为权威；无任何运行时权限放宽|已完成|`.rollback_snapshots/codex-task198-import-error-contract-\+\20260501_152915`、`.squad/orchestration-log/codex-2026-05-01-task199-skill-import-error-contract-fillin.md`、`.squad/decisions/inbox/codex-2026-05-01-task199-skill-import-error-contract-fillin.md`、backend focused pytest `26 passed`、compileall pass、frontend focused Vitest `4 passed`、frontend default Vitest `38 passed`、focused Skill Manager E2E `12 passed`、full frontend E2E `23 passed`、`npm run build` -> success|后续若继续 Skill 层，优先脚本型 Skill 独立安全设计或权限审计可视化；前端不自行判断本地路径存在性，仍由后端保持权威；不触默认 RAG 主链、corpus/goldset/qrels、`.env` 内容|
|TASK-200|10|脚本型 Skill 安全策略合同|`literature_assistant/core/skills/security_policy.py`、`literature_assistant/core/skills/service.py`、`literature_assistant/core/routers/skills_router.py`、`literature_assistant/core/models/skills.py`、`tests/test_skill_security_policy.py`、`tests/test_skill_runtime.py`、`tests/test_skill_router_contract.py`、`frontend/openapi/modular-pipeline-openapi.json`、`frontend/src/generated/openapi.ts`|已完成机器可读 Skill 安全策略：新增 `SkillSecurityAssessment` 与 `/skills/{skill_id}/security`，统一暴露 `risk_level`、`runtime_gate`、`runtime_executable`、`enable_requires_approval`、`denied_operations`、`required_sandbox_controls`、`approval_reason`、`block_reason`；`list_legacy_actions`、高风险 enable approval、approval profile metadata 与 runtime blocked result 均复用同一策略；非法权限形状 fail closed 为 `reference_only`；脚本/tool-wrapper、网络和文件写入仍 blocked，没有放开执行权限|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-010951-reload-longrun-continue-rag-skill-safety`、`.squad/orchestration-log/codex-2026-05-02-task200-skill-security-policy-contract.md`、focused backend `22 passed`、Skill 回归 `68 passed`、compileall pass、`npm run generate:openapi` success、frontend `npm run test` -> `38 passed`、frontend `npm run build` -> success|后续若继续 Skill 层，优先用 `/skills/{skill_id}/security` 做权限审计可视化；若要真正执行脚本/tool-wrapper，必须另开 sandbox runner 设计并独立审批；仍不触默认 RAG 主链、corpus/goldset/qrels、`.env` 内容|
|TASK-201|10|Skill 安全策略前端可视化|`frontend/src/components/skills/SkillManager.tsx`、`frontend/src/services/skillApi.ts`、`frontend/src/types/skills.ts`、`frontend/src/locales/zh.json`、`frontend/tests/e2e/mockApi.ts`、`frontend/tests/e2e/skill-manager.spec.ts`|已完成 Skill Manager 内联安全策略面板：每个 Skill 提供唯一可访问按钮 `查看安全策略：{name}`，按需调用 `/skills/{skill_id}/security`，展示风险等级、运行门控、当前可执行性、启用审批、被拦截操作、未来沙箱控制项和阻断/审批原因；保持只读展示，不放开任何脚本、网络或文件写入执行权限|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-012425-task201-skill-security-audit-ui`、`.squad/orchestration-log/codex-2026-05-02-task201-skill-security-audit-ui.md`、focused unit `5 passed`、frontend default `39 passed`、Skill Manager E2E `13 passed`、`npm run build` -> success|Skill 扩展层当前安全/UX闭环已够用；若继续该 lane，必须转 sandbox runner 设计 gate，不再做重复 UI polish；若转核心 RAG，优先 evidence/provenance 或 TOLF follow-up|
|TASK-202|11|核心 RAG evidence/provenance 机器可读引用首刀|`literature_assistant/core/evidence_packer.py`、`literature_assistant/core/main_rag_workflow.py`、`tests/test_evidence_packer.py`、`tests/test_main_rag_workflow_citation.py`|已完成 packed evidence provenance hardening：新增 `EvidenceReference`、`build_evidence_reference`、`build_evidence_references`，把 `chunk_id/material_id/text/compressed_text/quote/label/score/page/source/source_labels/source_hint` 标准化为 JSON-safe 结构；`format_evidence_item` 继续输出 SOURCE_ID/MATERIAL/SCORE/LABEL/QUOTE/BODY，并新增 SOURCE_LABELS；`_generate_answer` 的 assistant event 与 `_persist_last_answer` 统一写入 `evidence_refs`，让压缩上下文、quote 和真实 chunk provenance 不在回答后处理/持久化阶段丢失；本切片不改检索排序、不启用/禁用 rerank、不改 corpus/goldset/qrels、不触 `.env`|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-022454-rag-provenance-hardening-start`、`.squad/orchestration-log/codex-2026-05-02-task202-rag-evidence-provenance-hardening.md`、`.venv-1\Scripts\python.exe -m pytest tests\test_evidence_packer.py tests\test_main_rag_workflow_citation.py tests\test_main_rag_workflow_generation.py tests\test_citation_auditor.py -q` -> `19 passed`、`.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\evidence_packer.py literature_assistant\core\main_rag_workflow.py tests\test_evidence_packer.py tests\test_main_rag_workflow_citation.py` -> pass|下一刀优先检查 retrieval hits 到 packed evidence 的 source_labels/source_hint 覆盖率，或把 `evidence_refs` 接到写作/导出链路的统一 schema；TOLF/rerank 可在证据充分时由 AI 自决策做 guarded canary/adapter，不再逐项询问|
|TASK-203|11|检索来源 provenance 机器可读链路|`literature_assistant/core/retrieval_provenance.py`、`literature_assistant/core/layers/r_layer_hybrid_retriever.py`、`literature_assistant/core/chunk_vector_store.py`、`literature_assistant/core/graph_keyword_retriever.py`、`workspace_tests/evaluation_scripts/eval_retrieval_runtime.py`、`literature_assistant/core/reranker_client.py`、`literature_assistant/core/main_rag_workflow.py`、`tests/test_retrieval_provenance.py`、`tests/test_dense_rrf_retrieval.py`、`tests/test_graph_keyword_retriever.py`、`tests/test_main_rag_workflow_generation.py`|已完成检索生产端 provenance 补强：新增 `normalize_source_labels` / `merge_source_labels` / `attach_source_labels`；hybrid 命中标记 `bm25`、`dense` 或 `dense_fallback`、`context`；dense vector store 命中标记 `dense`；graph 命中标记 `graph`；RRF 融合时合并分支标签并追加 `rrf`；真实 rerank 追加 `rerank`，fallback 追加 `rerank_fallback`；RAG 本地兜底把 source labels/hint 复制到顶层与 metadata，避免 downstream answer/evidence refs 丢失检索来源；本切片只加机器可读字段，不改变排序、阈值、默认链路、评测口径或数据集|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-025728-rag-retrieval-source-provenance-continue`、`.squad/orchestration-log/codex-2026-05-02-task203-rag-retrieval-source-provenance.md`、`.venv-1\Scripts\python.exe -m pytest tests\test_retrieval_provenance.py tests\test_graph_keyword_retriever.py tests\test_dense_rrf_retrieval.py tests\test_main_rag_workflow_generation.py tests\test_evidence_packer.py -q` -> `42 passed`、`.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\retrieval_provenance.py literature_assistant\core\layers\r_layer_hybrid_retriever.py literature_assistant\core\chunk_vector_store.py literature_assistant\core\graph_keyword_retriever.py literature_assistant\core\main_rag_workflow.py literature_assistant\core\reranker_client.py workspace_tests\evaluation_scripts\eval_retrieval_runtime.py tests\test_retrieval_provenance.py tests\test_dense_rrf_retrieval.py tests\test_graph_keyword_retriever.py tests\test_main_rag_workflow_generation.py` -> pass|下一刀可做 answer/evidence refs 到前端/导出链路的统一展示，或做 default-off rerank/TOLF guarded canary；仍不改 corpus/goldset/qrels，不触 `.env`，不做最终 release gate 自签|
|TASK-204|11|RAG result evidence_refs 正式契约|`literature_assistant/core/main_rag_workflow.py`、`tests/test_main_rag_workflow_generation.py`、`.squad/orchestration-log/codex-2026-05-02-task204-rag-result-evidence-refs-contract.md`|已完成 `RAGResult.evidence_refs` 加法契约：字段位于 dataclass 末尾并带 `default_factory=list`，避免破坏旧的位置参数构造；`_pack_generation_evidence()` 统一生成 prompt/context 与 result evidence refs 使用的 packed evidence；`ask_my_literature()` 返回的 result 直接携带与生成 prompt 一致的机器可读引用，并在 trace 中记录 `evidence_ref_count`；cache/error 路径返回空 refs；本切片不改回答文本、不改检索排序、不启用/禁用 rerank、不改 corpus/goldset/qrels、不触 `.env`|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-033710-continue-rag-task204-evidence-api-contract`、`.squad/orchestration-log/codex-2026-05-02-task204-rag-result-evidence-refs-contract.md`、`.venv-1\Scripts\python.exe -m pytest tests\test_main_rag_workflow_generation.py tests\test_main_rag_workflow_citation.py tests\test_evidence_packer.py -q` -> `18 passed`、`.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\main_rag_workflow.py tests\test_main_rag_workflow_generation.py` -> pass|下一刀可检查 CLI/API/OpenAPI 是否需要显式暴露 `RAGResult.evidence_refs`，或做 default-off rerank/TOLF guarded canary；仍不改评测口径、不碰 secrets、不自签最终 release gate|
|TASK-205|11|RAG CLI evidence_refs JSON 输出契约|`literature_assistant/core/rag_integration_entry.py`、`tests/test_rag_integration_entry_cli.py`、`.squad/orchestration-log/codex-2026-05-02-task205-rag-cli-json-evidence-refs.md`|已完成 CLI 机器输出最小契约：新增 `_serialize_rag_result()` 与 `_json_safe()`，显式 `ask --json-output` 输出完整 JSON payload，保留 `evidence_refs`、`rag_evidence`、`trace` 和 `association_bundle`，并把非 JSON-safe 浮点/对象降级为字符串以防成功问答后输出失败；默认人类可读输出完全保留；本切片不改检索/生成/排序/默认 rerank/评测口径、不触 `.env`|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-035824-continue-rag-task205-cli-evidence-refs`、`.squad/orchestration-log/codex-2026-05-02-task205-rag-cli-json-evidence-refs.md`、`.venv-1\Scripts\python.exe -m pytest tests\test_rag_integration_entry_cli.py tests\test_text_utils.py -q` -> `11 passed`、`.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\rag_integration_entry.py tests\test_rag_integration_entry_cli.py` -> pass|下一刀优先评估是否已有 HTTP RAG result endpoint 需要 Pydantic/OpenAPI schema；若没有，就转 default-off rerank/TOLF guarded canary 准备，不做最终 release gate 自签|
|TASK-206|11|前端 evidence_refs 展示字段对齐后端 RAG|`frontend/src/lib/evidenceReferences.ts`、`frontend/src/lib/evidenceReferences.test.ts`、`frontend/src/types/writing.ts`、`.squad/orchestration-log/codex-2026-05-02-task206-frontend-evidence-fields.md`|已完成前端 evidence refs normalizer/display contract 补齐：类型与 parser 识别后端 RAG 的 `material_id/text/compressed_text/label/page/source/source_label/source_labels/source_hint`；证据正文优先 `content -> compressed_text -> text -> quote -> title -> chunk_id`，避免只显示 chunk id；metadata 在缺少 `source_id` 时展示 `material_id`，并展示 `source_labels/source_hint` 以保留检索来源；保持 WritingCanvas 结构不变，不做视觉重构|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-040542-continue-rag-task206-frontend-evidence-fields`、`.squad/orchestration-log/codex-2026-05-02-task206-frontend-evidence-fields.md`、`npm run test -- src/lib/evidenceReferences.test.ts` -> `5 passed`、`npm run build` -> success|下一刀可转 rerank/TOLF default-off canary 准备，或继续查 API/OpenAPI RAG result endpoint；仍不改默认链、不碰 corpus/goldset/qrels、不自签最终 release gate|
|TASK-207|11|runtime RAG rerank 默认门禁对齐|`literature_assistant/core/layers/r_layer_hybrid_retriever.py`、`tests/test_llm_provider_routing.py`、`.env.example`、`README.md`、`.squad/orchestration-log/codex-2026-05-02-task207-runtime-rerank-default-off.md`|已完成主运行时 rerank default-off 门禁：`HybridRetrieverWithRerank()` 默认读取 `RAG_RUNTIME_RERANK_ENABLED`，默认 `False`，避免仅因 provider key 存在就自动启用 rerank；`HybridRetrieverWithRerank(use_reranker=True/False)` 仍可显式覆盖，评测脚本的 `use_rerank` / `--no-rerank` 不变；`.env.example` 与 README 已标注该开关；本切片只改运行时默认门禁，不删除 reranker、不改 rerank client、不改评测口径、不触 `.env`|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-041221-continue-rag-task207-rerank-default-off-runtime`、`.squad/orchestration-log/codex-2026-05-02-task207-runtime-rerank-default-off.md`、`.venv-1\Scripts\python.exe -m pytest tests\test_llm_provider_routing.py tests\test_main_rag_workflow_generation.py tests\test_reranker.py -q` -> `40 passed`、`.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\layers\r_layer_hybrid_retriever.py tests\test_llm_provider_routing.py` -> pass|下一刀可做 default-off rerank canary runbook/manifest guard，或继续 TOLF adapter 准备；仍不改 corpus/goldset/qrels、不自签最终 release gate|
|TASK-208|11|rerank canary manifest dry-run guard|`tools/eval/run_pinned_rerank_manifest.py`、`tests/test_run_pinned_rerank_manifest.py`、`.squad/orchestration-log/codex-2026-05-02-task208-rerank-canary-dry-run-guard.md`|已完成 pinned rerank runner 的零成本 preflight：新增 `dry_run_manifest()`、CLI `--dry-run`、`--require-runtime-rerank-opt-in`；dry-run 校验 manifest root/sections、queries/qrels 路径存在、`retrieval_config.use_rerank=true`、pinned rerank `base_url/model`、输出路径唯一、runtime opt-in，并输出 JSON preflight report；不调用模型、不 probe key、不删除 stale outputs、不改真实 `.env`、不启动付费 eval|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-042046-continue-rag-task208-rerank-canary-guard`、`.squad/orchestration-log/codex-2026-05-02-task208-rerank-canary-dry-run-guard.md`、`.venv-1\Scripts\python.exe -m pytest tests\test_run_pinned_rerank_manifest.py -q` -> `3 passed`、`.venv-1\Scripts\python.exe -m compileall -q tools\eval\run_pinned_rerank_manifest.py tests\test_run_pinned_rerank_manifest.py` -> pass|下一刀若继续 rerank，可先补一个 current-layout sample manifest under `workspace_tests/` 或 `docs/plans/`，仍不直接跑付费 eval；若转 TOLF，必须保留 standard RAG control|
|TASK-209|11|rerank canary dry-run 样例与真实 runner 预检复用|`workspace_tests/evaluation_manifests/rerank_canary_dry_run_sample.json`、`docs/plans/runbooks/rerank-canary-dry-run.md`、`tools/eval/run_pinned_rerank_manifest.py`、`tests/test_run_pinned_rerank_manifest.py`、`.squad/orchestration-log/codex-2026-05-02-task209-rerank-dry-run-sample.md`|已完成 current-layout 样例 manifest 与 runbook：样例使用 `eval_queries_v2.1_canary30_ALIGNED.jsonl` + `gateb_goldset.jsonl`，输出路径固定到 ignored `workspace_artifacts/generated/eval/...`，不包含任何 secret；dry-run 新增 `inputs.queries_nonempty_lines` / `qrels_nonempty_lines` 校验，并在真实 `run_manifest()` 开头复用 preflight，防止重复输出路径、错配 query/qrels 数量或缺少 pinned model 的 manifest 进入付费执行；本切片仍不调用模型、不修改 `.env`、不改 corpus/goldset/qrels、不给最终 rerank verdict|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-043441-task209-rerank-dry-run-sample-manifest`、`.squad/orchestration-log/codex-2026-05-02-task209-rerank-dry-run-sample.md`、`.venv-1\Scripts\python.exe tools\eval\run_pinned_rerank_manifest.py workspace_tests\evaluation_manifests\rerank_canary_dry_run_sample.json --dry-run --require-runtime-rerank-opt-in` -> status ok、`.venv-1\Scripts\python.exe -m pytest tests\test_run_pinned_rerank_manifest.py -q` -> `6 passed`、compileall pass|下一刀可转 TOLF default-off adapter / HTTP RAG result endpoint schema 检查；若执行真实 rerank canary，必须复制样例为 dated manifest 并保留 no-rerank control，不得自签 release gate|
|TASK-210|11|IntelligentChat HTTP 兼容层与 evidence_refs schema|`literature_assistant/core/routers/intelligent_chat_router.py`、`literature_assistant/core/python_adapter_server.py`、`tests/test_intelligent_chat_router.py`、`frontend/src/services/intelligentChatApi.ts`、`frontend/src/pages/IntelligentChat.tsx`、`frontend/src/components/chat/MessageBubble.tsx`、`.env.example`、`.squad/orchestration-log/codex-2026-05-02-task210-intelligent-chat-http-compat.md`|已完成前端实际调用面的 typed 兼容层：新增 `/api/chat`、`/api/chat/sessions`、`/api/chat/resume`、`/api/budget/status`，`/api/chat` 从显式 `source_paths` 或 `LITERATURE_SOURCE_PATHS` 读取本地文本上下文，按 fast/balanced/thorough 做有限 chunk selection，复用现有 `/chat/ask` LLM proxy 生成回答，并返回 `context_metadata` + `evidence_refs`；sessions/resume 使用 runtime_state JSON 原子写入；frontend 类型与消息气泡展示 evidence references；本切片不接 TOLF 默认主链、不启用 rerank、不改 corpus/goldset/qrels、不触真实 `.env`|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-044748-task210-rag-http-schema-inspection`、`.squad/orchestration-log/codex-2026-05-02-task210-intelligent-chat-http-compat.md`、`.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py tests\test_chat_router_telemetry.py tests\test_runtime_router_contract.py -q` -> `13 passed`、compileall pass、`frontend/ npm run generate:openapi` -> success、`frontend/ npm run build` -> success|下一刀可补 `/api/chat` 对项目 chunks search 的 project_id 模式或做 TOLF default-off adapter；若要替换当前 local text selection 为正式 RAGWorkflow/TOLF 主链，属于更高影响重构，需保持开关和标准 RAG 对照|
|TASK-211|11|IntelligentChat project_id 项目知识库上下文|`literature_assistant/core/routers/intelligent_chat_router.py`、`literature_assistant/core/routers/resources_router.py`、`tests/test_intelligent_chat_router.py`、`frontend/src/services/intelligentChatApi.ts`、`frontend/src/pages/IntelligentChat.tsx`、`frontend/openapi/modular-pipeline-openapi.json`、`frontend/src/generated/openapi.ts`、`.squad/orchestration-log/codex-2026-05-02-task211-project-backed-intelligent-chat.md`|已完成 `/api/chat` 的项目级知识库模式：请求带 `project_id` 时先校验 writing project 存在，再复用 `resources_router` 的 chunk store 搜索 helper，按 tier 限制 chunk 数与上下文字符数，生成上下文字符串时带上 `chunk_id/material_id/section/page`，并把同一 provenance 写入 `context_metadata`、`evidence_refs` 与 session resume；前端 IntelligentChat 从 `WritingContext.activeProjectId` 自动传入当前项目，并在 header 显示 project context；保留旧 `source_paths/LITERATURE_SOURCE_PATHS` fallback；本切片不修改评测数据、不触真实 `.env`、不启用 rerank、不切默认 TOLF 主链|已完成|`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-051430-task211-project-backed-intelligent-chat`、`.squad/orchestration-log/codex-2026-05-02-task211-project-backed-intelligent-chat.md`、`.venv-1\Scripts\python.exe -m pytest tests\test_intelligent_chat_router.py -q` -> `6 passed`、`.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\routers\intelligent_chat_router.py literature_assistant\core\routers\resources_router.py tests\test_intelligent_chat_router.py` -> pass、`frontend/ npm run generate:openapi` -> success、`frontend/ npm run build` -> success；尝试 `npm run test -- src/pages/IntelligentChat.test.tsx` 因该测试文件不存在返回 no test files，不是代码失败|下一刀可继续把 IntelligentChat 的 answer path 升级为 default-off RAGWorkflow/TOLF adapter，或补项目级 chat UI smoke；仍需保持标准 RAG control、开关、trace 与可回滚，不自签 release gate|

### 用户自定义 Skill 接口设计规则（2026-04-30 新增）

- **产品边界**：RAG 文献助手已接入的 AI 检索、证据压缩、引用审计、写作导出等能力是基础功能或 builtin/base capability；用户自定义 Skill 是扩展层，只能补充工作流、提示词、工具包装和领域写作策略，不能覆盖默认检索主链、默认评测口径或安全门控。
- **成熟方案吸收**：参考 Dify 的 workspace-scoped plugin、manifest、权限和隐私声明；参考 MCP 的 tool input/output schema、resource link、roots、sampling/human-in-loop 和审计建议；参考 LangChain typed tool/schema/runtime context；参考 VS Code extension manifest、contributes、activation events，把 UI 注册与运行触发分开。
- **在线对标证据**：Dify manifest / permissions / privacy：`https://docs.dify.ai/en/develop-plugin/features-and-specs/plugin-types/plugin-info-by-manifest`、`https://docs.dify.ai/en/use-dify/workspace/plugins`；MCP tools/resources/prompts/roots：`https://modelcontextprotocol.io/specification/2025-06-18/server/tools`、`https://modelcontextprotocol.io/specification/2025-06-18/server/resources`、`https://modelcontextprotocol.io/specification/2025-06-18/server/prompts`、`https://modelcontextprotocol.io/specification/2025-06-18/client/roots`；LangChain tools/runtime context：`https://docs.langchain.com/oss/python/langchain/tools`；VS Code extension manifest/contribution points/activation events：`https://code.visualstudio.com/api/references/extension-manifest`、`https://code.visualstudio.com/api/references/contribution-points`、`https://code.visualstudio.com/api/references/activation-events`。
- **包结构建议**：用户 Skill 最小包为一个目录或 zip，根目录包含 `SKILL.md`，可选 `prompts/`、`references/`、`assets/`、`schemas/`、`scripts/`；MVP 只执行 prompt-only 与 workflow skill，`scripts/` 默认导入但 blocked。
- **Manifest 必填字段**：`id`、`name`、`version`、`kind`、`description`、`entry_mode`、`ui_visibility`、`supported_scopes`、`input_schema`、`output_schema`、`permissions`、`root_policy`、`script_policy`、`model_policy`、`privacy_notes`、`rollback_hint`。
- **权限模型**：默认 deny。`model.llm`、`model.embedding`、`retrieval.read`、`draft.read`、`draft.write`、`files.read`、`files.write`、`network`、`script.execute`、`storage` 必须逐项声明；高风险权限需要用户显式审批，脚本执行默认 blocked。
- **运行模型**：`prompt-only` 只能把受控上下文填入 prompt template；`workflow` 只能编排已经授权的 builtin/base capability；`tool-wrapper` 必须声明 JSON Schema 输入输出；`scripted` / network / file-write 当前通过 `SkillSecurityAssessment` 机器合同暴露风险并保持 runtime blocked，后续若要执行必须另开 sandbox runner 设计与独立审批。
- **审计与可回滚**：导入、启用、禁用、测试、执行、失败、审批和卸载都写 audit；每个 Skill 包记录 hash、origin、installed_at、enabled_by、last_run；覆盖或卸载前复制到 `.rollback_snapshots`。
- **UI 原则**：前端把“基础功能”和“我的 Skill”分区展示；每个 Skill 卡片显示来源、版本、权限、信任级别、脚本状态、最近运行和审计入口；危险权限 badge 不用颜色单独表达，必须有文本。
- **不得做的事**：不得把 `.claude/skills`、`.github/skills` 的 agent 工具生态直接暴露给普通用户；不得让用户 Skill 读取 `.env`、密钥文件、qrels/goldset、评测产物或项目外任意路径；不得让用户 Skill 静默调用外部网络或模型。

### 首轮执行顺序（AI 默认，不触成本边界）

1. `TASK-090`：确认后端 app/router/OpenAPI 入口。
2. `TASK-101`：只读审计已有 eval 输出一致性，不运行新 paid eval。
3. `TASK-110` / `TASK-111`：补会话 API 契约与 SQLite 恢复测试。
4. `TASK-120` / `TASK-121`：补前端 Settings `retrievalTopK` 与扫描失败占位。
5. `TASK-150`：准备 TOLF text-only pilot 输入/输出格式。
6. 每完成一个切片，更新本文件状态与 `.squad/orchestration-log/` 证据包。

### 暂不执行的事项

- 不在缺少 manifest、唯一输出路径、预算/模型身份记录时启动 8B/4B/BGE reranker eval；PD-010 已授权使用现有 env，但 secrets 不得打印，`.env` 不得修改。
- 不把 TOLF 接入默认 runtime，除非后续有独立评估通过。
- 不写入 Zotero/EndNote/Obsidian/外部科研资料源，只做只读设计。
- 不复制 `github/` 外部项目源码到主链，只吸收架构和机制。

## 项目级 Close 条件

本计划在满足以下全部条件后视为关停：

1. **Wave 9 前端产品化补齐全部完成**（TASK-176~182），`npm run build` 与 `npm run test -- --run` 通过，且 `TASK-179/TASK-192` 的 Playwright smoke 以 runner exit `0` 覆盖关键路径；2026-05-01 当前证据为 `npm run test` -> `34 passed`、`npm run build` -> success、`npm run test:e2e -- --reporter=line` -> `16 passed`。
2. **Wave 10 用户 Skill 扩展层**后端合同、运行时、前端 MVP、完整 Skill E2E smoke、approval persistence、uninstall / rollback API、前端 UX hardening、高风险启用审批门禁、真实 zip/import happy path 后端合同、zip/import 前端 UX 与 import 错误契约前后端补位均为 `PASS WITH NOTES` 或更高；2026-05-01 `TASK-191` 已由 `skill-manager.spec.ts` 纳入 16/16 E2E gate，`TASK-193` / `TASK-194` 后端 hardening 已通过 focused pytest、compileall 与 OpenAPI smoke，`TASK-195` / `TASK-196` 已把 Skill E2E 扩到 `9 passed`、全量前端 E2E 扩到 `20 passed`，`TASK-197` 已通过 focused pytest `26 passed`、扩展 Skill 回归 `60 passed` 与 compileall，`TASK-198` 已通过 focused Skill Manager E2E `11 passed`，`TASK-199` 已把全量前端 E2E 扩到 `23 passed`、默认 Vitest 扩到 `38 passed`。
3. **证据包完整**：`.squad/orchestration-log/*` 与 `.squad/decisions/inbox/*` 覆盖以上所有完成切片。
4. **Open/Next 清晰**：剩余 open items（如 reranker follow-up、TOLF live adapter）有明确的后续入口，不悬空。

满足以上条件时，本计划可标记为 `CLOSED`，后续工作转新计划或 follow-up slices。

## 执行阶段（历史参考）

> 以下 Phase 0~5 是以 Day 0~3 短跑节奏编写的早期框架。当前实际进度已进入 Wave 8~10，Phase 框架已不再作为主执行节奏，仅保留为横向参考。当前执行节奏以本文"详细路线图"与"可回填执行矩阵"中的 Wave/Task 状态为准。

### Phase 0：环境预检（Day 0）

**目标**：保证所有后续构建任务在可复现环境运行。

- Python 环境激活与依赖校验（`requirements-ci.txt`）
- Node 环境与 `frontend/package.json` 脚本可用性校验
- 验证 Squad 自检链路（`tools/squad/smoke-test.ps1`）

**完成标准**：

- smoke-test 5/5 通过
- Python/Node 入口命令均可启动

---

### Phase 1：治理层构建（Day 1）

**目标**：确保协作与自动化流程稳定。

- 校验 `.github/agents/squad.agent.md`、`.squad/routing.md`、`.github/copilot-instructions.md` 一致性
- 校验 `tools/squad/check-ghost.ps1` 与 `tools/squad/profile-version-check.ps1`
- 运行一次“最小真实任务” smoke（选择 Squad -> 计划 -> 执行 -> 证据留存）

**完成标准**：

- 路由、画像校验、ghost 清理、doctor/smoke 全通过
- 生成一条可复用样例记录到 `.squad/orchestration-log/`

---

### Phase 2：Python 核心构建（Day 1-2）

**目标**：建立后端与检索评测的 CI 级基础通过线。

- 运行关键回归测试（focus registry / resources router / retrieval 相关）
- 运行 `pytest` 主测试集（分层：快速集 -> 全量集）
- 对关键入口做命令级冒烟：
  - `batch_controller.py --help`
  - `integrated_pipeline.py --help`
  - `rag_integration_entry.py --help`

**完成标准**：

- 快速测试集全绿
- 全量测试集可重复通过（允许记录已知 flaky，并入 Open）

---

### Phase 3：Frontend 构建（Day 2）

**目标**：前端可构建、可生成类型、可发布预览。

- 在 `frontend/` 执行：
  - `npm run generate:openapi`（若本轮涉及接口变化）
  - `npm run lint`
  - `npm run build`

**完成标准**：

- lint 无阻塞错误
- build 成功并产出静态构建

---

### Phase 4：评测与性能门禁（Day 2-3）

**目标**：保证检索评测结果可比较、可追溯。

- 固化评测输入（query 集与 qrels）
- 跑 control（当前主配置）+ 对照（候选配置）
- 输出 `metrics/progress/per_query` 三件套并做一致性检查

**完成标准**：

- 无 mixed-run 污染
- 评测结论可复现
- 成本/延迟/召回指标齐全

---

### Phase 5：发布前总验收（Day 3）

**目标**：形成可提交、可审阅、可交接的构建结果。

- 汇总所有证据到执行记录
- 输出发布候选结论（Go / Conditional Go / No-Go）
- 列出 rollback 方案

**完成标准**：

- 证据包完整（Facts/Decisions/Open/Next）
- 明确下一迭代入口

## 推荐任务编排（并行策略）

- Lane A（治理）：Squad/doctor/smoke/ghost/profile
- Lane B（Python）：pytest + 入口冒烟 + 评测
- Lane C（Frontend）：OpenAPI types + lint + build
- Lane D（审计）：orchestration-log + decisions/inbox + 指标归档

并行原则：

- 同一 lane 内串行，lane 间并行。
- 任一 lane 出现高风险失败，立即写入 Open 并冻结跨 lane 扩散。

## 每日节奏（建议）

- 09:00 预检与任务拆分
- 11:30 首轮验收（快速集）
- 15:00 全量回归与对照评测
- 18:00 日终收口（证据包 + 次日入口）

## 风险与防漂移规则

- 禁止在未完成评测一致性前做模型胜负结论。
- 禁止在无日志证据下执行“已完成”判定。
- 禁止长跑任务连续 2 轮仅观察无工件增量（触发停机汇报）。

## 交付物清单

- 构建日志（Python/Frontend）
- 测试报告（快速 + 全量）
- 评测三件套（metrics/progress/per_query）
- 决策记录（`.squad/decisions/inbox/*.md`）
- 编排记录（`.squad/orchestration-log/*.md`）

## 当前首个执行切片（基于 2026-04-27 进度）

1. 先在 aligned canary / Gate B pilot 上以 pinned explicit `(api_key, base_url, model)` 重跑 env 现货 reranker 结论，优先 `qwen3-rerank`；当前 runtime 并发先收敛到 `16`，不要直接上 `32+`。provider-direct `48/50` 已证实可用，但 runtime-level 高并发仍需连接复用修补后再冲。随后扩到 `qwen3-vl-rerank` 与 `gte-rerank-v2`。8B invalid 仅保留为历史审计，不再作为当前 Wave 4 前置阻塞。
2. 完成 Tier3 / Gate B 的 `metrics / progress / per_query` 一致性验收，确保旧的中间态不再影响当前主结论。
3. 补齐会话持久化 API 的最小可用实现：`resume / fork / rewind / checkpoint`，并把相关契约测试接上。
4. 收口前端检索配置与扫描行为：`retrievalTopK`、首问扫描边界、失败占位入库策略。
5. 在前四步稳定后，再按 `github/RAG_TOLF_REFERENCE_MAP.md` 启动 TOLF 上游评估切片：单元切分 → 图构建 → 传播/激活 → 鱼群聚类 → 代表单元精排。

## 执行记录（2026-04-29 Wave 6）

- 完成 `TASK-151`：`eval_tolf_text_pilot.py` 扩展 richer mask ablation surface，在保留既有 2×2 基线的同时新增 cosine-topk 与 relation-type heuristic 两组变体；`artifacts/tolf/text_pilot_sample_report.json` 已刷新并验证包含 `mask_summary`。
- 完成 `TASK-152`：`layers/tolf_engine.py` 预留 representative rerank stage，位置固定为 evidence gate 之后，默认关闭；`eval_tolf_text_pilot.py` 与对应测试已记录该 stage 的 default-off 元数据。
- 本轮验证：`.venv-1\\Scripts\\python.exe -m pytest tests\\test_tolf_text_pilot.py test_tolf_engine.py -q` → `33 passed in 24.27s`。
- 本轮静态收口：`layers/tolf_engine.py` / `test_tolf_engine.py` 已消除本轮改动相关静态告警；`get_errors` 对 `layers/tolf_engine.py`、`test_tolf_engine.py`、`eval_tolf_text_pilot.py`、`tests/test_tolf_text_pilot.py` 返回无错误。

## 执行记录（2026-04-29 Wave 7）

- 完成 `TASK-160`：新增 `docs/copilot/2026-04-29-readonly-academic-connectors-design.md`，把 Zotero / EndNote / Obsidian 入口收敛为只读 connector 设计，明确采用 project-local staging snapshot，并复用现有 `source_folder` / `scan-folder` / `folder_traversal` / `extract_literature_context`，不直接引入新的主入库链。
- 完成 `TASK-161`：新增 `docs/copilot/2026-04-29-academic-output-citation-ui-design.md`，将学术输出 UI 设计锚定到现有 `DraftStudio` / `WritingCanvas` / `ReferenceDrawer` / `citation_anchors`，补齐 `Evidence` / `Citation Chain` / `Review` 三个核心视图。
- 修补并完成 `TASK-162`：Wave 7 总表最初存在 `TASK-162` 悬空引用但任务池缺定义，先补 placeholder 后继续推进到最小前端实现；当前已在 `ReferenceDrawer` 上落地 `Evidence` / `Citation Chain` / `Review` 三视图，并由 `DraftStudio` 透传当前 draft / section context，确保实现复用现有 `citation_anchors` 脊柱而不是再发明第二套引用系统。独立复核返回 `PASS WITH NOTES` 后，又顺手补上实例级 anchor 聚焦与 dangling material 审计。
- 完成 `TASK-163`：将“共享页面自动 UI 验证 + GitHub 参考设计源 + 独立窗口终态约束”写回 master plan 并同步到 Squad。明确后续前端设计参考以 `github/` 参考库中的项目界面/截图/文档为准，当前本地 `localhost` 页面仅作运行态验证；当页面在 VS Code 中已共享时，AI 可直接对界面元素自动交互，用于新功能 smoke、回归验证、状态态验证、写作工作流验证与封装前 smoke，不依赖用户手动“添加元素到聊天”。
- 完成 `TASK-164`：在 `frontend/` 补最小 Vitest + jsdom + React Testing Library 测试基建，并新增 `citationAnchors.test.ts` 与 `ReferenceDrawer.test.tsx`，优先防守 anchor parsing / range 定位以及 `Evidence` / `Review` heuristics；保持切片收敛，不扩到 backend evidence contract，也不引入 Jest。已有 `sessionDrawerHelpers.test.mjs` 继续保留为轻量 helper 覆盖。
- 本轮证据包：`.squad/orchestration-log/copilot-2026-04-29-wave7-academic-design.md`、`.squad/orchestration-log/copilot-2026-04-29-task162-evidence-citation-review-implementation.md`、`.squad/orchestration-log/copilot-2026-04-29-shared-ui-autotest-plan-sync.md`、`.squad/orchestration-log/copilot-2026-04-29-task164-focused-frontend-tests.md`。
- 本轮验证：`frontend/` 下 `npm run build` 两次成功，分别为初版 5.41s 与复核修补后 5.51s；随后 `TASK-164` 又补跑 `npm run test -- src/lib/citationAnchors.test.ts src/components/writing/ReferenceDrawer.test.tsx`（2 files / 6 tests 通过）、`node --test src/components/writing/sessionDrawerHelpers.test.mjs`（11 tests 通过）与 `npm run build`（再次通过）。独立 QA 复核对该测试切片给出 `PASS WITH NOTES`，唯一 note 是 helper `node:test` 尚未并入默认 `npm run test`。

## 执行记录（2026-04-29 Wave 8）

- 完成 `TASK-170`：新增 `.squad/orchestration-log/copilot-2026-04-29-wave7-gate-review.md`，将 Wave 7 当前切片的 `Facts / Decisions / Open / Next` 单独收口，明确当前开放项不是 blocking defects，而是下一轮扩面的两个安全入口：backend evidence contract 与 focused frontend tests。
- 完成 `TASK-171`：基于独立 gate review 形成 `.squad/decisions/inbox/copilot-2026-04-29-wave7-task162-provisional-go.md`，将 `TASK-162` / Wave 7 slice 标记为 `PASS WITH NOTES` 的 provisional go；结论边界限定为“最小可交付且可继续推进下一任务”，不扩大解释为全项目 release pass。
- 本轮独立复核再次确认：`TASK-162` 的计划、设计、实现与证据保持一致；未发现 blocking issues；`frontend/` 下只读复跑 `npm run build` 成功，用时 5.97s。

## 执行记录（2026-04-30 Wave 8 continuation）

- 完成 `TASK-172`：将 backend evidence contract / export formatting 作为 `TASK-164` 后续安全入口落地；`export_project` 现在从现有 `materials`、`drafts`、`citation_anchors` 派生 `evidence_rows`、`citation_chain`、`review_findings`，JSON 导出走 additive fields，Markdown 导出追加 `证据表`、`引用链` 与必要的 `审计提示`。
- 本轮边界：不改 `writing_resources.py` 持久化 schema，不新增 endpoint，不写 Zotero/EndNote/Obsidian，不改 qrels/goldset，不触发 paid eval；`chunk_id/page/score/confidence` 在本切片保持 nullable，等待未来 chunk/page provenance 稳定后再升级。
- 本轮验证：先观察两条 RED（JSON 缺 `evidence_rows`、Markdown 缺 `## 证据表`），再实施；focused suite `.venv-1\Scripts\python.exe -m pytest tests\test_resources_router_contract.py tests\test_writing_resource_persistence.py -q` 通过，`7 passed in 22.43s`。
- 本轮证据包：`.squad/orchestration-log/copilot-2026-04-30-backend-evidence-export-contract.md`、`.squad/decisions/inbox/copilot-2026-04-30-backend-evidence-export-contract-implemented.md`、`output/20260430-backend-evidence-export-contract.md`。
- 完成 `TASK-173`：在 Codex 已补 focused export tests 与前端本地类型的基础上，Copilot 接手 response model / OpenAPI schema 固化；新增 `ProjectExportPayload`、`ProjectExportEvidenceRowPayload`、`ProjectExportCitationChainPayload`、`ProjectExportReviewFindingPayload` 等正式模型，并把 `/resources/project/{project_id}/export` 200 response 从匿名 object 收敛为 `ProjectExportPayload`。
- `TASK-173` 验证：先观察 OpenAPI RED（endpoint 200 schema 为匿名 object，不是 `#/components/schemas/ProjectExportPayload`），实现后 focused suite `.venv-1\Scripts\python.exe -m pytest tests\test_resources_export_contract.py tests\test_resources_router_contract.py tests\test_writing_resource_persistence.py -q` 通过，`10 passed in 23.03s`；`frontend/` 下 `npm run generate:openapi` 成功并刷新 `frontend/openapi/modular-pipeline-openapi.json` / `frontend/src/generated/openapi.ts`，随后 `npm run build` 成功（built in 2.55s）。
- `TASK-173` 证据包：`.squad/orchestration-log/copilot-2026-04-30-task173-openapi-export-schema.md`、`.squad/decisions/inbox/copilot-2026-04-30-task173-openapi-export-schema-complete.md`、`output/20260430-task173-openapi-export-schema.md`。
- 完成 `TASK-174`：对 `TASK-173` 做独立 schema/code risk review；review 结论为可合入但建议去除前端手写 export appendix 类型。Copilot 核对后采纳该建议，新增 `frontend/src/types/resources.test.ts` 防止回退为手写接口，并将 `frontend/src/types/resources.ts` 中 `ProjectExportResult`、`ProjectExportEvidenceRow`、`ProjectExportCitationChainRow`、`ProjectExportReviewFinding` 等改为 generated OpenAPI schema aliases。
- `TASK-174` 验证：RED 先失败于缺少 alias 合同；修正后 fresh verification `.venv-1\Scripts\python.exe -m pytest tests\test_resources_export_contract.py tests\test_resources_router_contract.py tests\test_writing_resource_persistence.py -q` 通过，`10 passed in 12.24s`；`frontend/ npm run test -- src\types\resources.test.ts` 通过（1 test），`frontend/ npm run build` 成功（built in 2.56s）。
- `TASK-174` 证据包：`.squad/orchestration-log/copilot-2026-04-30-task174-schema-risk-review.md`、`.squad/decisions/inbox/copilot-2026-04-30-task174-schema-risk-review-complete.md`、`output/20260430-task174-schema-risk-review.md`。
- 完成 `TASK-175`：对 Wave 8 academic export lane 做 gate review，覆盖 `TASK-172` backend evidence contract、`TASK-173` response model/OpenAPI schema、`TASK-174` independent schema review + frontend generated-type de-dup。结论为 `PASS WITH NOTES / provisional go`，边界限定为 academic export schema lane，不能外推为全项目 release pass。
- `TASK-175` 证据包：`.squad/orchestration-log/copilot-2026-04-30-wave8-academic-export-gate-review.md`、`.squad/decisions/inbox/copilot-2026-04-30-wave8-academic-export-provisional-go.md`、`output/20260430-wave8-academic-export-gate-review.md`。
