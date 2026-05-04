# LLM-Wiki + RAG 文献助手优化执行计划

## 目标

把当前 RAG 文献助手从“每次查询即时检索、即时生成、事后遗忘”的工作流，升级为“RAG 证据层 + LLM-Wiki 编译层 + citation/graph/doctor 治理层”的可回档、可审计、可长期演化系统。

核心判断：不推倒现有 RAG，不替换 TOLF / hybrid retrieval / evidence_refs；先在现有证据链上增量加入 wiki 编译、结构化 claim、持久 synthesis、引用校验和图谱影响分析。

## 执行硬规则

- 每个非平凡代码切片开始前必须创建回档点。
- 每个架构、数据、接口、评测或治理切片开始前必须搜索成熟方案或官方/上游项目做对标。
- `github/` 和 `C:\Users\xiao\Downloads\llmwiki借鉴库` 只读参考，不复制外部代码，不改外部参考库。
- 产品代码优先放入 `literature_assistant/core/`。
- 计划、执行记录、交接提示放入 `docs/plans/`。
- 运行输出放入 `workspace_artifacts/`，不写回根目录 `output/`。
- 不改变默认 RAG/TOLF 主链、不默认启用 rerank；corpus/goldset/qrels/canary30 允许在备份、独立 gate、对照指标和回滚记录齐全后自决策演进。
- 对外部资料源 Zotero / EndNote / Obsidian 先只读索引，不做写回同步。
- 所有 claim 进入正式 wiki 前必须有可解析 evidence reference；无法溯源的内容只能进入 draft/review。
- 最新一次性授权边界见 `docs/plans/active/llmwiki-autonomy-authorization.md`；若本文旧规则与该授权冲突，以授权补充和用户最新消息为准。

## 补充文档索引

**权限管理与执行治理**：
- 权限层级、红线映射、自决策边界、DoD 模板、长跑 envelope、防自喂食、独立复核、事故索引、环境收尾：见本文档 §权限管理与执行治理
- Wave 任务权限与 DoD 补充：`docs/plans/active/wave-permission-dod-supplement.md`
- LLM-Wiki 自决策授权补充：`docs/plans/active/llmwiki-autonomy-authorization.md`

**项目构建完整性**：
- 六层功能边界、TOLF 集成路径、评测口径、前端构建流程、成熟方案对标流程：见本文档 §项目构建完整性
- TOLF-Wiki 集成设计：`docs/plans/specs/tolf-wiki-integration.md`

**漏洞分析与修复**：
- 计划漏洞分析（15 个缺失点）：`docs/plans/active/plan-missing-analysis.md`
- 漏洞修复影响分析：`docs/plans/active/gap-fix-impact-analysis.md`
- 漏洞修复执行状态：`docs/plans/active/gap-fix-status.md`

**用户画像与协作协议**：
- 用户画像 v4（权限模型、完成定义、多 agent 协作、红线、事故索引）：`C:\Users\xiao\Desktop\tools\用户画像_v4_AI协作治理型工程主理人.md`

## 本次回档点

- 回档 id：`llmwiki-rag-plan`
- 回档路径：`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260503-122353-llmwiki-rag-plan`
- 工作树状态：存在用户/历史改动，包含 `literature_assistant/core/query_expander.py`、多项 tests、eval scripts、`.claude/*`、`backups/` 等；本计划只新增本文档。

## 成熟方案与本地证据

### 已读本地借鉴库

|参考项目|本地路径|可借鉴点|
|---|---|---|
|PaperQA2|`C:\Users\xiao\Downloads\llmwiki借鉴库\paper-qa-main`|科学文献 RAG、metadata-aware retrieval、in-text citations、RCS、contradiction detection|
|OpenKB|`C:\Users\xiao\Downloads\llmwiki借鉴库\OpenKB-main`|short/long document split、PageIndex tree、wiki compilation、lint/watch/chat/save|
|llm-wiki-compiler|`C:\Users\xiao\Downloads\llmwiki借鉴库\llm-wiki-compiler-main`|two-phase compile、hash skip、query --save、chunk-aware query、paragraph source markers|
|obsidian-llm-wiki-local|`C:\Users\xiao\Downloads\llmwiki借鉴库\obsidian-llm-wiki-local-master`|draft approval/reject、hand-edit protection、git undo、local-first provider、inline citation toggle|
|TheKnowledge|`C:\Users\xiao\Downloads\llmwiki借鉴库\TheKnowledge-main`|source immutability、citation density、wiki validator、draft/finalize、MCP gateway|
|WikiLoom|`C:\Users\xiao\Downloads\llmwiki借鉴库\wikiloom-main`|stable chunk_id、chunk store、hybrid linking、duplicates、linked-page expansion|
|Keppi|`C:\Users\xiao\Downloads\llmwiki借鉴库\keppi-master`|graph build、blast radius、semantic search、MCP graph tools|
|OmegaWiki|`C:\Users\xiao\Downloads\llmwiki借鉴库\OmegaWiki-main`|research entity model、typed edges、papers/concepts/claims/experiments lifecycle|
|SwarmVault|`C:\Users\xiao\Downloads\llmwiki借鉴库\swarmvault-main`|context packs、doctor、retrieval manifest、review queues、graph share|

### 已读 `github/` RAG 参考库

|参考项目|本地路径|可借鉴点|
|---|---|---|
|LightRAG|`github/LightRAG-1.4.15`|graph RAG、entity/relation extraction、query modes、reranker as first-class capability、storage locks|
|RAG-Anything|`github/RAG-Anything-1.2.10`|multimodal document parsing、image/table/equation processors、context extractor|
|nano-graphrag|`github/nano-graphrag-0.0.8`|轻量 GraphRAG storage/query 边界|
|Knowledge-Base-Gateway|`github/Knowledge-Base-Gateway-1.2.2026.10009`|Zotero/EndNote/Obsidian 本地科研库接入、fast/deep 模式|
|WeKnora|`github/WeKnora-main`|Wiki Mode、knowledge graph UI、observability、agent orchestration|
|Quivr|`github/quivr-core-0.0.33`|文档知识库 API 与 retrieval 应用边界|
|open-webui|`github/open-webui-0.8.12`|知识库 UI、用户权限、模型/检索配置体验|

### 网上成熟方案

- Karpathy LLM-Wiki gist：`https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f`
- PaperQA2 upstream：`https://github.com/Future-House/paper-qa`
- OpenKB upstream：`https://github.com/VectifyAI/OpenKB`
- LightRAG upstream：`https://github.com/HKUDS/LightRAG`
- RAG-Anything upstream：`https://github.com/HKUDS/RAG-Anything`
- Microsoft GraphRAG upstream：`https://github.com/microsoft/graphrag`

## 当前项目证据锚点

|能力|当前文件|说明|
|---|---|---|
|RAG 主流程|`literature_assistant/core/main_rag_workflow.py`|已有 `RAGResult.evidence_refs`、SemanticRouter、RAGFlow/local fallback、generation|
|证据打包|`literature_assistant/core/evidence_packer.py`|已有 `EvidenceReference`、rank、source_labels、query_overlap_tokens|
|引用审计|`literature_assistant/core/citation_auditor.py`|已有 quote-in-source 检查，但需要扩展到 wiki claim/finalize|
|检索 provenance|`literature_assistant/core/retrieval_provenance.py`|已有 source_labels normalize/merge/attach|
|向量 store|`literature_assistant/core/chunk_vector_store.py`|已有 embedding manifest/cache guard，但缺 wiki/source registry contract|
|项目路径|`literature_assistant/core/project_paths.py`|后续 wiki/runtime 输出必须通过路径 helper 落入 workspace_artifacts|
|API 服务|`literature_assistant/core/python_adapter_server.py`、`routers/*`|后续 wiki/query/save/doctor UI contract 从这里接|
|前端|`frontend/src/*`|后续 Evidence/Wiki/Graph/Doctor 面板从现有页面增量接入|
|评测|`tools/eval/*`、`workspace_tests/evaluation_scripts/*`|后续加 wiki-aware retrieval/evidence/audit 对照；qrels/goldset/canary30 可在备份和指标证据充分后版本化演进|

## 项目构建完整性

### 六层功能边界映射

| 层级 | 功能 | 对应 Wave | 关键文件 | 当前状态 |
|------|------|-----------|----------|----------|
| 1. 基础设施 | 环境、配置、模型网关、成本日志、缓存、状态文件 | Wave 0 | `runtime_env.py`, `project_paths.py` | ✅ 已完成 |
| 2. 抽取 | PDF 文本、章节、参考文献、图/表/caption | 已完成 | `extractor_full.py` | ✅ 已完成 |
| 3. 入库 | material manifest、chunk、向量存储、项目索引 | Wave 1-2 | `source_registry.py`（含 source + chunk registry） | ✅ 已完成 |
| 4. 检索 | BM25/Hybrid/Graph/Dense/RRF/rerank/expansion | Wave 8 | `wiki/query.py` | ✅ 已完成 |
| 5. 生成 | 证据约束回答、写作素材、引用链 | Wave 5-7 | `wiki/compiler.py`, `wiki/evidence_adapter.py` | ✅ 已完成 |
| 6. 交付 | 前端 Workbench、报告、Word/料包 | Wave 11-12 | `frontend/`, `routers/wiki_router.py` | ✅ 已完成 |

### TOLF 集成路径

**当前状态**：
- TOLF 已实现：`layers/tolf_engine.py`, `test_tolf_engine.py`
- TOLF 为可选实验能力，未替换默认主链
- 最新 5 个 commit 全部是 TOLF 相关（judgment summary、template export、review packet、inspection packet、bilingual control、query bridge diagnostics）

**集成路径**：

| Phase | 目标 | 集成点 | 时间线 |
|-------|------|--------|--------|
| Phase 1（当前）| TOLF 与 RAG 并行 | 互不干扰，独立运行 | 已完成 |
| Phase 2（Wave 15）| TOLF 输出进入 Wiki | TOLF judgment → Wiki synthesis<br>TOLF review → Wiki review queue<br>TOLF inspection → Wiki doctor | 待执行 |
| Phase 3（未来）| TOLF 替换默认主链 | 主链切换、评测对照、回滚点 | 待规划 |

**集成边界**：
- TOLF 定位：独立工具 + Wiki 前置步骤
- TOLF 输出格式：必须兼容 Wiki page store 输入契约
- TOLF 测试覆盖：独立测试 + Wiki 集成测试

**设计文档**：`docs/plans/specs/tolf-wiki-integration.md`（✅ 已补充，LMWR-465）

### 评测口径明确说明

**当前评测口径**：

| 口径 | 规模 | 用途 | 修改规则 |
|------|------|------|----------|
| canary30 | 30 个查询 | 快速验证、回归检测 | 先新增/版本化；若效果证据充分，可备份后自决策修改 |
| full | 109 篇基线 | 完整验证、性能基线 | 先备份和记录旧指标，再做版本化演进 |
| qrels | 人工标注 | 相关性判断、评测金标 | 先备份、保留旧版本和恢复路径，再根据人工/对照证据修改 |

**Wiki 评测口径**：

| 口径 | 类型 | 用途 | 成本 |
|------|------|------|------|
| zero-cost | retrieval-only | 不调用模型，只比较检索结果 | 零成本 |
| wiki vs raw | 对比评测 | Wiki 检索 vs RAG 检索对比 | 零成本 |
| citation audit | 质量评测 | 引用密度、quote 匹配 | 零成本 |

**评测规则**：
- 默认优先新增查询集和独立评测，不直接覆盖旧评测。
- 修改 qrels/goldset/canary30 前必须创建 checkpoint、备份原文件、记录旧/新指标、样本数和恢复路径。
- 若新增查询集或对照实验显示新口径明显更好，可在备份后自决策修改旧查询集或 goldset。
- 评测结果必须记录口径、样本数、关键指标

### 前端构建流程

**终态说明**：
- 最终程序界面是独立窗口应用；浏览器页面只是开发期预览、smoke test 和最小 E2E 验收面。
- 测试期浏览器适配以关键流程可用为目标，不追求完整产品化视觉和响应式打磨。
- LMWR-466 优先复用现有 Playwright，不引入 Cypress；缺浏览器 runtime 时只补 Playwright browser 安装。

**开发流程**：
```bash
cd frontend
npm install
npm run dev  # 启动开发服务器 http://localhost:5173
npm run test  # 运行 Vitest 单元测试
npm run build  # 构建生产版本
```

**发布流程**：
1. 运行 `npm run test` 确保所有测试通过
2. 运行 `npm run build` 确保构建成功
3. 浏览器 smoke 测试（至少 5 个关键页面）：
   - `/` 首页
   - `/chat` 对话页
   - `/writing` 写作页
   - `/wiki` Wiki 工作台
   - `/wiki?page=sources/example.md` Wiki 页面预览
4. 提交代码并创建 PR
5. 等待 CI/CD 通过
6. 合并到 main

**回滚流程**：
1. 找到上一个稳定版本的 commit
2. `git revert <commit>` 或 `git reset --hard <commit>`
3. 重新构建：`npm run build`
4. 验证：`npm run test` + 浏览器 smoke

**前端门禁**：
- Vitest 单元测试通过（当前 54 个）
- 构建成功（无 TypeScript 错误）
- 浏览器 smoke 通过（5 个关键页面）
- 无 console error（除已知 warning）

### 成熟方案对标流程

**对标范围**：
1. 本地借鉴库：`C:\Users\xiao\Downloads\llmwiki借鉴库\`
2. github 参考库：`github/`
3. 官方上游文档

**对标流程**：
1. 搜索相关项目（grep 关键词）
2. 读取相关文件（Read 核心实现）
3. 记录可借鉴点（设计、参数、边界）
4. 记录不适用点（依赖、复杂度、维护成本）
5. 写入 Wave runbook

**对标记录格式**：
```markdown
## 成熟方案对标

| 来源 | 参考点 | 本轮借鉴 | 不适用点 |
|------|--------|----------|----------|
| PaperQA2 | citation validator | 引用密度检查 | 依赖 LangChain |
| OpenKB | page store | frontmatter 格式 | 不支持 JSON |
| LightRAG | graph RAG | entity extraction | 存储格式不兼容 |
```

## 总体架构落点

```text
raw/project docs + PDFs + Zotero/EndNote/Obsidian notes
  -> source registry + stable chunks + existing RAG evidence_refs
  -> LLM-Wiki compiler writes draft wiki pages
  -> citation validator + duplicate/graph/doctor gates
  -> finalized wiki pages
  -> query reads wiki first, then linked pages, then raw RAG fallback
  -> answer can be saved as synthesis/exploration page
```

## 推荐落地目录（已更新至实际实现）

```text
literature_assistant/core/wiki/
  models.py
  source_registry.py          # 含 source + chunk registry（原 chunk_registry.py 已合并）
  page_store.py               # 含 frontmatter render/parse（原 frontmatter.py 已合并）
  citation_validator.py
  evidence_adapter.py
  compiler.py
  query.py                    # 含 FTS index（原 index.py 已合并）
  graph.py
  doctor.py
  review_queue.py
  evaluation.py               # Wave 14 新增
  llm_gateway.py              # Wave 7 新增
  backup.py                   # Wave 15 新增
  migration.py                # Wave 15 新增
  observability.py            # LMWR-473 新增
  export.py                   # Wave 9 新增
  connectors/
    __init__.py
    base.py
    markdown.py
    pdf_folder.py
    zotero.py
    endnote.py

prompt_templates/
  generation.txt              # 现有 RAG 生成模板
  （wiki_*.txt 待 LMWR-333~336 实现）

workspace_artifacts/runtime_state/wiki/
  wiki.db
  graph.json
  graph.db
  retrieval_manifest.json
  review_queue.jsonl
  observability/              # LMWR-473 新增

workspace_artifacts/generated/wiki/
  index.md
  sources/
  papers/
  concepts/
  claims/
  synthesis/
  explorations/
  reports/
```

## 权限管理与执行治理

### 权限层级映射

| Wave | 任务范围 | 权限层级 | 自动批准 | 需用户授权 |
|------|----------|----------|----------|------------|
| Wave 0 | 治理文档 | L1 | ✓ | - |
| Wave 1-2 | 数据模型、注册表 | L1 | ✓ | - |
| Wave 3-6 | 页面存储、引用验证、编译器 | L1 | ✓ | - |
| Wave 7 | LLM 生成（stub 模式） | L1 | ✓ | - |
| Wave 8-10 | 检索、图谱、Doctor | L1 | ✓ | - |
| Wave 11-12 | API、前端 | L1 | ✓ | - |
| Wave 13 | 外部 connector（只读） | L1 | ✓ | - |
| Wave 14 | 评测（zero-cost） | L1 | ✓ | - |
| Wave 15 | 迁移、发布 | L3 | - | ✓（高权限） |

**权限层级说明**：
- **L1（surgical 写）**：小修改、新增测试、文档更新、只读操作
- **L2（局部重构）**：新增模块、局部重构（<15 文件）、schema 调整（保兼容层）
- **L3（高权限）**：大范围重构、主链调整、高 blast radius 操作

**实际执行经验**：
- Wave 0-14 全部在 L1 范围内完成
- 未触发任何硬红线
- 大部分操作都是绿灯操作（文档、测试、小修复）

### 红线映射表

**硬红线**（必须停下请示）：

| 类别 | 红线项 | 请示模板 |
|------|--------|----------|
| 数据丢失 | 全量 reindex（>100 篇）<br>删除兼容层<br>删除 `.bak`<br>rm -rf（>10 文件）<br>删除用户文档/画像/plan | 先 checkpoint + 目标备份；备份失败、无法恢复或影响外部不可逆数据时请示 |
| 不可逆操作 | force push<br>删分支<br>删表<br>删除外部知识库数据 | 先创建本地备份分支/tag或目标级导出；无法证明备份覆盖目标时请示 |
| 评测基线 | 修改 qrels<br>修改 goldset<br>修改 canary30 查询集 | 允许在备份、版本化、对照指标充分后自决策；证据不足时先新增独立评测 |
| 主链破坏 | 替换主 embedding<br>替换主 rerank<br>删除默认 RAG 链路 | 同上 |

**计划任务豁免**：本执行计划中的具体任务（LMWR-XXX）触碰硬红线时自动放行，无需请示。因为这些任务已经过人工审核和规划，属于已授权操作。

**绿灯操作**（无需请示）：
- 更新文档/状态/plan/runbook
- 新增/修复测试
- 修复 bug（<100 行）
- 修复 lint/type/缩进错误
- 新增 feature flag（默认关闭）
- 新增前端组件（只读）
- 新增 env 变量/budget guard/cost log

**详细分析**：见 `docs/plans/active/redline-relaxation-analysis.md`

### 自决策白名单

**允许自决策**（绿灯操作）：
- 缺失的 DoD 命令
- 缺失的回档点
- 缺失的验证脚本
- 缺失的状态同步
- 缺失的 compileall 检查
- 缺失的 pytest marker
- 缺失的 runbook 文档
- 新增/修复测试（<100 行）
- 修复 bug（<100 行）
- 新增 feature flag（默认关闭）
- 新增前端组件（只读）
- 新增小依赖（<10MB，无 C 扩展）
- 新增独立评测（不覆盖现有）
- 备份后演进 qrels/goldset/canary30
- 备份后删除、迁移、改名项目内 stale artifact 或旧实现

**需说明但可自决策**：
- 新增模块（不删除现有模块）
- 局部重构（<15 文件）
- 保兼容层的 schema 调整
- 新增 LLM 调用（有 budget guard）
- 新增 rerank/expansion（有 feature flag）
- 只读外部知识库/API
- 外部知识库写入方案的 spec/dry-run/diff/backup 设计

**禁止自决策**（硬红线）：
- 无法创建或验证备份的数据丢失风险操作
- 无法用备份覆盖目标的不可逆操作
- 未备份、未对照、未记录指标的评测基线破坏
- 主链破坏

**豁免规则**：本执行计划中的具体任务（LMWR-XXX）触碰硬红线时自动放行。

### 回滚点策略

**命名规范**：`{date}-{wave}-{task-id}-{slug}`

**创建时机**：
- 每个 Wave 开始前
- 每个红线任务开始前
- 每个 L2/L3 任务开始前

**恢复流程**：
```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" list --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```

### 标准化 DoD 模板

**完成定义**：`完成 = 主产物落盘 ∧ 状态同步 ∧ 门禁通过 ∧ 环境收尾`

**主产物落盘**：
- [ ] 代码文件已写入目标目录
- [ ] 测试文件已写入 `tests/wiki/`
- [ ] grep 可验证落盘

**状态同步**：
- [ ] 更新 `docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`
- [ ] 更新 Wave runbook
- [ ] 更新 `docs/analysis/` 相关分析文档

**门禁通过**：
- [ ] focused tests 通过（报告 exit code、样本数）
- [ ] compileall 通过
- [ ] 全量 wiki tests 通过（无回归）
- [ ] 关键指标记录（Recall/MRR/latency）

**环境收尾**：
- [ ] 无 stale lock（检查 `workspace_artifacts/runtime_state/`）
- [ ] 无 orphan tmp（检查 `/tmp/` 或 `%TEMP%`）
- [ ] 无混跑 artifact（检查 `output/` vs `workspace_artifacts/`）
- [ ] 无未解释非零 exit

### 长跑 envelope 模板

**每次长跑前必须声明**：

```markdown
## Long-run Envelope

**Objective**: [一句话目标]

**Allowed Scope**:
- [允许改动的文件/目录]
- [允许的操作类型]

**Disallowed Actions**:
- [禁止的操作]
- [红线项]

**Budget**:
- Time: [预估时间]
- Cost: [预估成本]
- Token: [预估 token]

**Checkpoint Cadence**: [每 N 个任务 or 每 N 分钟]

**Stop Conditions**:
- [触发停止的条件]
- [红线触发]
- [预算超限]

**Expected Artifacts**:
- [主产物列表]
- [状态文件列表]

**Rollback Path**: [回档点 ID]

**Evidence Sources**: [验证命令列表]
```

### 防自喂食机制

**触发条件**：连续两轮没有以下任何一项
- code diff
- test artifact
- data artifact
- task transition
- eval delta

**停止动作**：
1. 停止执行
2. 报告 Facts / Stalled evidence / Safe next action
3. 禁止继续写 meta-observation

**判定标准**：按外部可验证 checkpoint 计算，不按 agent 自报 round 编号

### 独立复核机制

**复核对象**：
- L2/L3 任务的最终产物
- 红线任务的执行结果
- 长跑任务的阶段产物

**复核方式**：
- 独立 reviewer（另一个 agent）
- 或标记 provisional（等用户确认）
- 或用户最终确认

**复核标准**：
- 主产物落盘验证
- 门禁通过验证
- 无回归验证

### 事故索引引用

**已知事故**（来源：用户画像 v4 §11.5）：
1. **2026-04-25 09:11~09:20**：`requirement-pool.md` 从 1.5MB 缩到 9KB，历史条目丢失
   - 对应规则：单一 append helper、shrink guard、非零退出 hard stop
2. **2026-04-25 11:43~11:55**：同一条目 12 分钟内出现 4 份字节级重复
   - 对应规则：最近 50 块 SHA-256 dedup、派发前查重
3. **2026-04-25 09:35~10:09**：34 分钟内产出 6 条元观察，0 个净产出
   - 对应规则：防自喂食、两轮无 artifact delta 就停
4. **2026-04-25 08:39**：派发前发现重复任务、重复 spec
   - 对应规则：pre-flight 查重和队列冷却

**本计划应用**：
- 所有写操作必须验证落盘（防事故 1）
- 所有任务派发前查重（防事故 2、4）
- 所有长跑必须有 artifact delta 检查（防事故 3）

### 环境收尾检查清单

**每个任务完成后必须检查**：

```powershell
# 检查 stale lock
Get-ChildItem -Path "workspace_artifacts/runtime_state/" -Filter "*.lock" -Recurse

# 检查 orphan tmp
Get-ChildItem -Path $env:TEMP -Filter "*literature*" -Recurse | Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-1) }

# 检查混跑 artifact
Get-ChildItem -Path "output/" -Recurse | Select-Object FullName, LastWriteTime | Sort-Object LastWriteTime -Descending | Select-Object -First 10

# 检查未解释非零 exit
# 查看最近的命令历史和 exit code
```

## 验证命令基线

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py workspace_tests\evaluation_scripts
& .\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
& .\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\system_verification.py --json
```

## 任务编号说明

本计划从现有 master plan 的 TASK-223 后续接续，使用 `LMWR-224` 到 `LMWR-463`，共 240 个细分任务。每个任务默认执行顺序：

1. 回档。
2. 搜索成熟方案或读取本地参考项目对应实现。
3. 小范围实现。
4. focused tests / compileall / contract smoke。
5. 写回执行记录与证据路径。

## 高难任务核心代码蓝图

本节给后续执行者一份“先建骨架”的代码蓝图。实现时不要把这些片段机械粘贴后放任不管；每个切片仍必须先回档、再读取参考文件、再按现有项目 import/path/test 约束落地。蓝图的价值是先固定难点接口、数据边界和防守逻辑，避免每个 agent 重新发明一套不兼容的模型。

### 蓝图参考目录索引

|蓝图|对应任务|优先参考本项目文件|优先参考借鉴库文件|
|---|---|---|---|
|Wiki domain models|LMWR-239~253|`literature_assistant/core/evidence_packer.py`、`literature_assistant/core/chunk_models.py`、`literature_assistant/core/models/common.py`|`OmegaWiki-main/tools/research_wiki.py`、`wikiloom-main/wikiloom/frontmatter.py`、`llm-wiki-compiler-main/src/utils/types.ts`|
|Source/chunk registry|LMWR-254~268|`literature_assistant/core/chunk_vector_store.py`、`literature_assistant/core/project_paths.py`、`literature_assistant/core/db.py`|`wikiloom-main/wikiloom/chunk_store.py`、`TheKnowledge-main/src/gateway/validator.py`、`LightRAG-1.4.15/lightrag/lightrag.py`|
|Markdown page store|LMWR-269~283|`literature_assistant/core/project_paths.py`、`literature_assistant/core/manifest_builder.py`|`llm-wiki-compiler-main/src/utils/markdown.ts`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/vault.py`、`wikiloom-main/wikiloom/frontmatter.py`|
|Citation validator|LMWR-284~298|`literature_assistant/core/citation_auditor.py`、`literature_assistant/core/evidence_packer.py`|`TheKnowledge-main/src/gateway/citations.py`、`TheKnowledge-main/src/gateway/validator.py`|
|Evidence adapter|LMWR-299~313|`literature_assistant/core/evidence_packer.py`、`literature_assistant/core/retrieval_provenance.py`、`literature_assistant/core/main_rag_workflow.py`|`llm-wiki-compiler-main/src/commands/query.ts`、`PaperQA2 paperqa/types.py`|
|Compiler dry-run|LMWR-314~328|`literature_assistant/core/main_rag_workflow.py`、`literature_assistant/core/model_call_gateway.py`、`literature_assistant/core/prompt_templates/`|`llm-wiki-compiler-main/src/compiler/`、`OpenKB-main/openkb/cli.py`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/cli.py`|
|Wiki-aware retrieval|LMWR-344~358|`literature_assistant/core/hybrid_search_runtime.py`、`literature_assistant/core/layers/r_layer_hybrid_retriever.py`、`literature_assistant/core/chunk_vector_store.py`|`wikiloom-main/wikiloom/query.py`、`llm-wiki-compiler-main/src/commands/query.ts`、`keppi-master/keppi/search/semantic.py`|
|Graph/doctor/review|LMWR-359~388|`literature_assistant/core/recovery_*`、`literature_assistant/core/harness_store.py`、`literature_assistant/core/routers/*`|`keppi-master/keppi/analysis/blast_radius.py`、`swarmvault-main/packages/engine/src/doctor.ts`、`wikiloom-main/wikiloom/duplicates.py`|
|API router|LMWR-389~403|`literature_assistant/core/python_adapter_server.py`、`literature_assistant/core/routers/intelligent_chat_router.py`、`literature_assistant/core/routers/resources_router.py`|`swarmvault-main/packages/engine/src/mcp.ts`、`OpenKB-main/openkb/cli.py`|
|Frontend Wiki 工作台|LMWR-404~418|`frontend/src/lib/evidenceReferences.ts`、`frontend/src/pages/KnowledgeBase.tsx`、`frontend/src/pages/Workbench.tsx`|`swarmvault-desktop-main/src/renderer/`、`WeKnora-main/frontend/`、`LightRAG-1.4.15/lightrag_webui/`|

### 蓝图 A：`wiki/models.py`

对应任务：`LMWR-239` 到 `LMWR-253`。

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence


class WikiPageStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    FINAL = "final"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class WikiPageKind(StrEnum):
    SOURCE = "source"
    PAPER = "paper"
    CONCEPT = "concept"
    CLAIM = "claim"
    SYNTHESIS = "synthesis"
    EXPLORATION = "exploration"
    REPORT = "report"


class WikiEdgeType(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    EXTENDS = "extends"
    DEPENDS_ON = "depends_on"
    RELATED_TO = "related_to"
    DERIVED_FROM = "derived_from"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


@dataclass(frozen=True)
class WikiEvidenceRef:
    chunk_id: str
    material_id: str
    text: str
    compressed_text: str = ""
    quote: str = ""
    label: str = ""
    source: str = ""
    source_labels: tuple[str, ...] = ()
    page: int | str | None = None
    rank: int | None = None
    score: float | str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "WikiEvidenceRef":
        if not isinstance(raw, Mapping):
            raise TypeError("raw evidence reference must be a mapping")
        chunk_id = require_non_empty(str(raw.get("chunk_id") or ""), "chunk_id")
        material_id = require_non_empty(str(raw.get("material_id") or chunk_id), "material_id")
        text = str(raw.get("text") or raw.get("compressed_text") or raw.get("quote") or "").strip()
        if not text:
            raise ValueError("evidence reference must include text, compressed_text, or quote")
        labels = raw.get("source_labels") or ()
        if isinstance(labels, str):
            source_labels = (labels.strip(),) if labels.strip() else ()
        elif isinstance(labels, Sequence):
            source_labels = tuple(str(label).strip() for label in labels if str(label).strip())
        else:
            raise TypeError("source_labels must be a string or sequence of strings")
        return cls(
            chunk_id=chunk_id,
            material_id=material_id,
            text=text,
            compressed_text=str(raw.get("compressed_text") or "").strip(),
            quote=str(raw.get("quote") or "").strip(),
            label=str(raw.get("label") or "").strip(),
            source=str(raw.get("source") or "").strip(),
            source_labels=source_labels,
            page=raw.get("page"),
            rank=int(raw["rank"]) if raw.get("rank") is not None else None,
            score=raw.get("score"),
        )

    def to_citation_target(self) -> str:
        target = f"sources/{self.material_id}#{self.chunk_id}"
        if self.page is not None:
            target = f"{target};p={self.page}"
        return target


@dataclass(frozen=True)
class WikiPage:
    kind: WikiPageKind
    page_id: str
    title: str
    status: WikiPageStatus
    body: str
    evidence_refs: tuple[WikiEvidenceRef, ...] = ()
    source_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        require_non_empty(self.page_id, "page_id")
        require_non_empty(self.title, "title")
        if not isinstance(self.kind, WikiPageKind):
            raise TypeError("kind must be WikiPageKind")
        if not isinstance(self.status, WikiPageStatus):
            raise TypeError("status must be WikiPageStatus")
        if self.status is WikiPageStatus.FINAL and not self.evidence_refs and self.kind in {
            WikiPageKind.CLAIM,
            WikiPageKind.SYNTHESIS,
            WikiPageKind.PAPER,
        }:
            raise ValueError("final evidence-bearing pages require evidence_refs")

    def frontmatter(self) -> dict[str, Any]:
        return {
            "id": self.page_id,
            "kind": self.kind.value,
            "title": self.title,
            "status": self.status.value,
            "source_ids": list(self.source_ids),
            "aliases": list(self.aliases),
            "evidence_refs": [ref.__dict__ for ref in self.evidence_refs],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class WikiWritePlan:
    page: WikiPage
    relative_path: Path
    old_hash: str | None
    new_hash: str
    reason: str
```

### 蓝图 B：`wiki/source_registry.py`

对应任务：`LMWR-254` 到 `LMWR-268`。

```python
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wiki_sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    source_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wiki_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    page TEXT,
    section TEXT,
    span_start INTEGER,
    span_end INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES wiki_sources(source_id)
);
CREATE INDEX IF NOT EXISTS idx_wiki_chunks_source_id ON wiki_chunks(source_id);
"""


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    source_type: str
    title: str
    source_hash: str
    source_path: Path


@dataclass(frozen=True)
class ChunkInput:
    text: str
    chunk_index: int
    page: str | None = None
    section: str | None = None
    span_start: int | None = None
    span_end: int | None = None


def sha256_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if not value:
        raise ValueError("value cannot be empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def derive_source_id(source_type: str, title: str, source_hash: str) -> str:
    source_type = source_type.strip().lower()
    title = title.strip()
    if not source_type or not title or not source_hash:
        raise ValueError("source_type, title, and source_hash are required")
    readable = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
    readable = "-".join(part for part in readable.split("-") if part)[:64] or "source"
    return f"{source_type}-{readable}-{source_hash[:12]}"


def derive_chunk_id(source_hash: str, chunk_index: int) -> str:
    if not source_hash:
        raise ValueError("source_hash is required")
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    return hashlib.sha256(f"{source_hash}:{chunk_index}".encode("utf-8")).hexdigest()[:16]


class WikiRegistry:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_source(self, record: SourceRecord, *, now_iso: str) -> bool:
        if not record.source_id or not record.source_hash:
            raise ValueError("source_id and source_hash are required")
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT source_hash FROM wiki_sources WHERE source_id = ?",
                (record.source_id,),
            ).fetchone()
            if existing and existing["source_hash"] != record.source_hash:
                raise ValueError(
                    f"source immutability violation for {record.source_id}: "
                    f"{existing['source_hash']} != {record.source_hash}"
                )
            conn.execute(
                """
                INSERT INTO wiki_sources (
                    source_id, source_type, title, source_hash, source_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title = excluded.title,
                    source_path = excluded.source_path,
                    updated_at = excluded.updated_at
                """,
                (
                    record.source_id,
                    record.source_type,
                    record.title,
                    record.source_hash,
                    str(record.source_path),
                    now_iso,
                    now_iso,
                ),
            )
            return existing is None

    def replace_chunks(self, source: SourceRecord, chunks: Iterable[ChunkInput], *, now_iso: str) -> list[str]:
        chunk_list = list(chunks)
        if not chunk_list:
            raise ValueError("chunks cannot be empty")
        for chunk in chunk_list:
            if not chunk.text.strip():
                raise ValueError("chunk text cannot be empty")
            if chunk.chunk_index < 0:
                raise ValueError("chunk_index must be non-negative")
        with self.connect() as conn:
            conn.execute("DELETE FROM wiki_chunks WHERE source_id = ?", (source.source_id,))
            ids: list[str] = []
            for chunk in chunk_list:
                chunk_id = derive_chunk_id(source.source_hash, chunk.chunk_index)
                ids.append(chunk_id)
                conn.execute(
                    """
                    INSERT INTO wiki_chunks (
                        chunk_id, source_id, source_hash, chunk_index, text_hash, text,
                        page, section, span_start, span_end, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        source.source_id,
                        source.source_hash,
                        chunk.chunk_index,
                        sha256_text(chunk.text),
                        chunk.text,
                        chunk.page,
                        chunk.section,
                        chunk.span_start,
                        chunk.span_end,
                        now_iso,
                    ),
                )
            return ids
```

### 蓝图 C：`wiki/page_store.py`

对应任务：`LMWR-269` 到 `LMWR-283`。

```python
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


AUTO_START = "<!-- literature-assistant:auto:start -->"
AUTO_END = "<!-- literature-assistant:auto:end -->"


@dataclass(frozen=True)
class RenderedPage:
    relative_path: Path
    text: str
    content_hash: str


def stable_slug(title: str) -> str:
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    value = title.strip().lower()
    if not value:
        raise ValueError("title cannot be empty")
    chars: list[str] = []
    for ch in value:
        if ch.isalnum():
            chars.append(ch)
        elif ch in {" ", "-", "_", ".", "/"}:
            chars.append("-")
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug[:96] or hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]


def render_frontmatter(frontmatter: Mapping[str, Any]) -> str:
    if not isinstance(frontmatter, Mapping):
        raise TypeError("frontmatter must be a mapping")
    if "id" not in frontmatter or "kind" not in frontmatter or "title" not in frontmatter:
        raise ValueError("frontmatter requires id, kind, and title")
    payload = json.dumps(dict(sorted(frontmatter.items())), ensure_ascii=False, indent=2)
    return f"---json\n{payload}\n---\n"


def render_page(relative_path: Path, frontmatter: Mapping[str, Any], body: str) -> RenderedPage:
    if not isinstance(relative_path, Path):
        relative_path = Path(relative_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("relative_path must stay inside the wiki root")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("body cannot be empty")
    text = f"{render_frontmatter(frontmatter)}\n{AUTO_START}\n{body.strip()}\n{AUTO_END}\n"
    return RenderedPage(
        relative_path=relative_path,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def atomic_write_text(path: Path, text: str) -> None:
    if not isinstance(path, Path):
        path = Path(path)
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


class WikiPageStore:
    def __init__(self, wiki_root: Path) -> None:
        self.wiki_root = Path(wiki_root)
        self.wiki_root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: Path) -> Path:
        candidate = (self.wiki_root / relative_path).resolve()
        root = self.wiki_root.resolve()
        if root not in {candidate, *candidate.parents}:
            raise ValueError(f"path escapes wiki root: {relative_path}")
        return candidate

    def write_rendered(self, rendered: RenderedPage, *, allow_overwrite: bool = True) -> None:
        target = self.resolve(rendered.relative_path)
        if target.exists() and not allow_overwrite:
            raise FileExistsError(target)
        old_text = target.read_text(encoding="utf-8") if target.exists() else ""
        if old_text and AUTO_START not in old_text:
            raise ValueError(f"manual page lacks auto marker and will not be overwritten: {target}")
        atomic_write_text(target, rendered.text)

    def list_pages(self, kind_dir: str | None = None) -> list[Path]:
        base = self.wiki_root / kind_dir if kind_dir else self.wiki_root
        if not base.exists():
            return []
        return sorted(path.relative_to(self.wiki_root) for path in base.rglob("*.md"))
```

### 蓝图 D：`wiki/citation_validator.py`

对应任务：`LMWR-284` 到 `LMWR-298`。

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol


SOURCE_LINK_RE = re.compile(r"\[\[sources/(?P<source>[^#\];]+)(?:#(?P<chunk>[^;\]]+))?(?:;p=(?P<page>[^\]]+))?\]\]")
FENCE_RE = re.compile(r"```")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")


class ChunkLookup(Protocol):
    def get_chunk_text(self, chunk_id: str) -> str | None:
        ...


@dataclass(frozen=True)
class CitationIssue:
    rule: str
    message: str
    line_no: int | None = None
    severity: str = "error"


@dataclass(frozen=True)
class CitationReport:
    ok: bool
    cited_claims: int
    total_claims: int
    citation_density: float
    issues: tuple[CitationIssue, ...] = field(default_factory=tuple)


def strip_code_fence_lines(text: str) -> list[tuple[int, str]]:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    in_fence = False
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.search(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((idx, line))
    return out


def claim_lines(body: str) -> list[tuple[int, str]]:
    claims: list[tuple[int, str]] = []
    for line_no, line in strip_code_fence_lines(body):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("-", "*", "+")) and stripped.count("[[") == stripped.count("]]") and len(stripped) < 160:
            continue
        for sentence in SENTENCE_SPLIT_RE.split(stripped):
            sentence = sentence.strip()
            if len(sentence.split()) >= 5 or len(sentence) >= 24:
                if sentence.endswith((".", "!", "?", "。", "！", "？")):
                    claims.append((line_no, sentence))
    return claims


def validate_citations(
    body: str,
    *,
    lookup: ChunkLookup,
    final_mode: bool,
    min_density: float = 0.95,
) -> CitationReport:
    if not 0.0 <= min_density <= 1.0:
        raise ValueError("min_density must be between 0 and 1")
    claims = claim_lines(body)
    issues: list[CitationIssue] = []
    cited = 0
    for line_no, claim in claims:
        links = list(SOURCE_LINK_RE.finditer(claim))
        if not links:
            issues.append(CitationIssue("missing-citation", "claim has no source citation", line_no))
            continue
        cited += 1
        for link in links:
            chunk_id = link.group("chunk")
            if not chunk_id:
                issues.append(CitationIssue("missing-chunk", "citation lacks chunk id", line_no))
                continue
            chunk_text = lookup.get_chunk_text(chunk_id)
            if chunk_text is None:
                issues.append(CitationIssue("unknown-chunk", f"chunk not found: {chunk_id}", line_no))
    total = len(claims)
    density = 1.0 if total == 0 else cited / total
    if final_mode and density < min_density:
        issues.append(CitationIssue("citation-density", f"citation density {density:.3f} below {min_density:.3f}"))
    errors = [issue for issue in issues if issue.severity == "error"]
    return CitationReport(
        ok=not errors if final_mode else True,
        cited_claims=cited,
        total_claims=total,
        citation_density=density,
        issues=tuple(issues),
    )
```

### 蓝图 E：`wiki/evidence_adapter.py`

对应任务：`LMWR-299` 到 `LMWR-313`。

```python
from __future__ import annotations

from typing import Any, Iterable

from wiki.models import WikiEvidenceRef


def coerce_evidence_refs(raw_refs: Iterable[dict[str, Any]]) -> tuple[WikiEvidenceRef, ...]:
    if raw_refs is None:
        raise ValueError("raw_refs cannot be None")
    refs: list[WikiEvidenceRef] = []
    for raw in raw_refs:
        refs.append(WikiEvidenceRef.from_mapping(raw))
    if not refs:
        raise ValueError("at least one evidence reference is required")
    return tuple(refs)


def evidence_ref_to_markdown(ref: WikiEvidenceRef) -> str:
    quote = ref.quote or ref.compressed_text or ref.text
    if not quote.strip():
        raise ValueError("evidence reference has no quotable text")
    return f"{quote.strip()} [[{ref.to_citation_target()}]]"


def build_synthesis_body(question: str, answer: str, refs: Iterable[WikiEvidenceRef]) -> str:
    question = question.strip()
    answer = answer.strip()
    if not question:
        raise ValueError("question cannot be empty")
    if not answer:
        raise ValueError("answer cannot be empty")
    ref_tuple = tuple(refs)
    if not ref_tuple:
        raise ValueError("synthesis requires evidence references")
    evidence_lines = "\n".join(f"- {evidence_ref_to_markdown(ref)}" for ref in ref_tuple)
    return f"# {question}\n\n{answer}\n\n## Evidence\n\n{evidence_lines}\n"
```

### 蓝图 F：`wiki/compiler.py`

对应任务：`LMWR-314` 到 `LMWR-343`。

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from wiki.evidence_adapter import build_synthesis_body, coerce_evidence_refs
from wiki.models import WikiPage, WikiPageKind, WikiPageStatus, WikiWritePlan
from wiki.page_store import WikiPageStore, render_page, stable_slug


@dataclass(frozen=True)
class CompileInput:
    question: str
    answer: str
    evidence_refs: tuple[dict, ...]
    source_ids: tuple[str, ...] = ()
    save_kind: WikiPageKind = WikiPageKind.SYNTHESIS


@dataclass(frozen=True)
class CompileResult:
    dry_run: bool
    plans: tuple[WikiWritePlan, ...]
    written_paths: tuple[Path, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


class WikiCompiler:
    def __init__(self, store: WikiPageStore) -> None:
        self.store = store

    def plan_synthesis(self, item: CompileInput) -> WikiWritePlan:
        if item.save_kind not in {WikiPageKind.SYNTHESIS, WikiPageKind.EXPLORATION}:
            raise ValueError("plan_synthesis only supports synthesis or exploration pages")
        refs = coerce_evidence_refs(item.evidence_refs)
        body = build_synthesis_body(item.question, item.answer, refs)
        slug = stable_slug(item.question)
        page_id = f"{item.save_kind.value}/{slug}"
        page = WikiPage(
            kind=item.save_kind,
            page_id=page_id,
            title=item.question.strip(),
            status=WikiPageStatus.DRAFT,
            body=body,
            evidence_refs=refs,
            source_ids=item.source_ids,
        )
        relative_path = Path(item.save_kind.value) / f"{slug}.md"
        rendered = render_page(relative_path, page.frontmatter(), body)
        return WikiWritePlan(
            page=page,
            relative_path=relative_path,
            old_hash=None,
            new_hash=hashlib.sha256(rendered.text.encode("utf-8")).hexdigest(),
            reason="query-save",
        )

    def compile(self, items: Iterable[CompileInput], *, dry_run: bool) -> CompileResult:
        plans = tuple(self.plan_synthesis(item) for item in items)
        if dry_run:
            return CompileResult(dry_run=True, plans=plans)
        written: list[Path] = []
        for plan in plans:
            rendered = render_page(plan.relative_path, plan.page.frontmatter(), plan.page.body)
            self.store.write_rendered(rendered)
            written.append(plan.relative_path)
        return CompileResult(dry_run=False, plans=plans, written_paths=tuple(written))
```

### 蓝图 G：`wiki/query.py`

对应任务：`LMWR-344` 到 `LMWR-358`。

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WikiHit:
    page_id: str
    title: str
    path: Path
    score: float
    reason: str


@dataclass(frozen=True)
class WikiContextPack:
    query: str
    primary_hits: tuple[WikiHit, ...]
    linked_hits: tuple[WikiHit, ...] = field(default_factory=tuple)
    omitted: tuple[str, ...] = field(default_factory=tuple)


class WikiQueryEngine:
    def __init__(self, db_path: Path, wiki_root: Path) -> None:
        self.db_path = Path(db_path)
        self.wiki_root = Path(wiki_root)

    def search_pages(self, query: str, *, limit: int = 8) -> tuple[WikiHit, ...]:
        if not query.strip():
            raise ValueError("query cannot be empty")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if not self.db_path.exists():
            return ()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT page_id, title, path, bm25(wiki_pages_fts) AS score
                FROM wiki_pages_fts
                WHERE wiki_pages_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return tuple(
            WikiHit(
                page_id=str(row["page_id"]),
                title=str(row["title"]),
                path=Path(str(row["path"])),
                score=float(row["score"]),
                reason="wiki_fts",
            )
            for row in rows
        )

    def build_context_pack(self, query: str, *, max_pages: int = 8) -> WikiContextPack:
        primary = self.search_pages(query, limit=max_pages)
        return WikiContextPack(query=query, primary_hits=primary)
```

### 蓝图 H：`wiki/doctor.py` 与 `wiki/review_queue.py`

对应任务：`LMWR-374` 到 `LMWR-388`。

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DoctorAction:
    command: str
    description: str
    safe_auto_repair: bool = False


@dataclass(frozen=True)
class DoctorCheck:
    id: str
    label: str
    status: str
    summary: str
    detail: str = ""
    actions: tuple[DoctorAction, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    checks: tuple[DoctorCheck, ...]


class WikiDoctor:
    def __init__(self, wiki_root: Path, db_path: Path) -> None:
        self.wiki_root = Path(wiki_root)
        self.db_path = Path(db_path)

    def run(self) -> DoctorReport:
        checks = [
            self._check_workspace(),
            self._check_registry(),
        ]
        return DoctorReport(ok=all(check.status == "ok" for check in checks), checks=tuple(checks))

    def _check_workspace(self) -> DoctorCheck:
        if self.wiki_root.exists():
            return DoctorCheck("workspace", "Workspace", "ok", "Wiki workspace exists.")
        return DoctorCheck(
            "workspace",
            "Workspace",
            "error",
            "Wiki workspace is missing.",
            actions=(DoctorAction("wiki init", "Create wiki workspace.", safe_auto_repair=True),),
        )

    def _check_registry(self) -> DoctorCheck:
        if self.db_path.exists():
            return DoctorCheck("registry", "Registry", "ok", "Wiki registry database exists.")
        return DoctorCheck(
            "registry",
            "Registry",
            "warning",
            "Wiki registry database is missing.",
            actions=(DoctorAction("wiki doctor --repair", "Initialize registry schema.", safe_auto_repair=True),),
        )
```

### 蓝图 I：`routers/wiki_router.py`

对应任务：`LMWR-389` 到 `LMWR-403`。

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/wiki", tags=["wiki"])


class WikiStatusResponse(BaseModel):
    enabled: bool
    page_count: int = 0
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)


class WikiCompileRequest(BaseModel):
    dry_run: bool = True
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    evidence_refs: list[dict[str, Any]]


class WikiCompileResponse(BaseModel):
    dry_run: bool
    planned_paths: list[str]
    written_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def wiki_enabled() -> bool:
    import os
    return os.getenv("LITERATURE_ASSISTANT_WIKI_ENABLED", "0").strip() in {"1", "true", "yes", "on"}


@router.get("/status", response_model=WikiStatusResponse)
def wiki_status() -> WikiStatusResponse:
    if not wiki_enabled():
        return WikiStatusResponse(enabled=False, warnings=["wiki integration is disabled"])
    return WikiStatusResponse(enabled=True)


@router.post("/compile", response_model=WikiCompileResponse)
def wiki_compile(request: WikiCompileRequest) -> WikiCompileResponse:
    if not wiki_enabled():
        raise HTTPException(status_code=409, detail={"error_code": "wiki_disabled"})
    if not request.evidence_refs:
        raise HTTPException(status_code=422, detail={"error_code": "missing_evidence_refs"})
    return WikiCompileResponse(dry_run=request.dry_run, planned_paths=["synthesis/example.md"])
```

### 蓝图 J：首批测试文件布局

对应任务：`LMWR-250`、`LMWR-266`、`LMWR-280`、`LMWR-295`、`LMWR-309`、`LMWR-325`、`LMWR-399`。

```text
tests/wiki/
  test_wiki_models.py          # 原 test_models.py
  test_source_registry.py
  test_page_store.py
  test_citation_validator.py
  test_evidence_adapter.py
  test_compiler.py             # 原 test_compiler_dry_run.py
  test_wiki_router.py          # 原 test_wiki_router_contract.py
  test_llm_gateway.py
  test_query.py
  test_query_save_exploration.py
  test_graph.py
  test_doctor.py
  test_review_queue.py
  test_evaluation.py
  test_connectors.py
  test_backup.py
  test_migration.py
  test_wiki_cli.py
  test_observability.py
  test_cache_corpus_preflight.py
  test_performance_baseline.py
  test_lmwr470_chunk_param_review.py
  test_expansion_optimizations.py
  test_wave15_end_to_end.py
```

首批 focused 命令：

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant tests\wiki
```

## Wave 执行前必读文件清单

每个 Wave 开始前，执行者先读本表对应文件，再做回档和实现。读取时只摘取与本任务相关的接口/约束，不要批量复制参考项目代码。

|Wave|本项目必读|借鉴库必读|备注|
|---|---|---|---|
|Wave 0|`AGENTS.md`、`AI_WORKSPACE_GUIDE.md`、`docs/plans/README.md`、本文件|`longrun-autopilot/references/mature-solution-research.md`|先统一执行纪律和文档落点|
|Wave 1|`evidence_packer.py`、`chunk_models.py`、`models/common.py`、`retrieval_provenance.py`|`OmegaWiki-main/tools/research_wiki.py`、`wikiloom-main/wikiloom/frontmatter.py`|先定类型，不接 runtime|
|Wave 2|`chunk_vector_store.py`、`db.py`、`project_paths.py`、`sqlite_maintenance.py`|`wikiloom-main/wikiloom/chunk_store.py`、`TheKnowledge-main/src/gateway/validator.py`|关键是 stable id、hash guard、不可变 source|
|Wave 3|`project_paths.py`、`manifest_builder.py`、`material_bundler.py`|`llm-wiki-compiler-main/src/utils/markdown.ts`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/vault.py`|重点看 atomic write 和手工编辑保护|
|Wave 4|`citation_auditor.py`、`evidence_packer.py`、`prompt_templates/generation.txt`|`TheKnowledge-main/src/gateway/citations.py`、`TheKnowledge-main/src/gateway/validator.py`|不要让无引用 claim 进入 final|
|Wave 5|`main_rag_workflow.py`、`evidence_packer.py`、`retrieval_provenance.py`|`llm-wiki-compiler-main/src/commands/query.ts`、`paper-qa-main/README.md`|保持现有 evidence_refs 向后兼容|
|Wave 6|`main_rag_workflow.py`、`model_call_gateway.py`、`runtime_env.py`、`prompt_templates/`|`llm-wiki-compiler-main/src/commands/compile.ts`、`OpenKB-main/openkb/cli.py`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/cli.py`|先 dry-run，再写 draft|
|Wave 7|`model_call_gateway.py`、`runtime_env.py`、`llm_defaults.py`、`.github/skills/env-test-discipline/SKILL.md`|`paper-qa-main/README.md`、`OpenKB-main/openkb/agent/` 如存在|所有 LLM 调用必须走 env/test discipline|
|Wave 8|`hybrid_search_runtime.py`、`layers/r_layer_hybrid_retriever.py`、`chunk_vector_store.py`、`tolf_text_selector.py`|`wikiloom-main/wikiloom/query.py`、`keppi-master/keppi/search/semantic.py`|wiki-first 必须 default-off|
|Wave 9|`graph_keyword_retriever.py`、`layers/p2_conflict_detector.py`、`layers/p3_consistency_validator.py`|`keppi-master/keppi/graph/builder.py`、`keppi-master/keppi/analysis/blast_radius.py`、`OmegaWiki-main/tools/_schemas.py`|先图索引和影响分析，后自动推理|
|Wave 10|`recovery_api.py`、`recovery_store_provider.py`、`harness_store.py`、`routers/recovery_router.py`|`swarmvault-main/packages/engine/src/doctor.ts`、`wikiloom-main/wikiloom/lint.py`、`obsidian-llm-wiki-local-master/src/obsidian_llm_wiki/cli.py`|doctor repair 只能做安全子集|
|Wave 11|`python_adapter_server.py`、`routers/intelligent_chat_router.py`、`routers/resources_router.py`、`models/runtime.py`|`OpenKB-main/openkb/cli.py`、`swarmvault-main/packages/engine/src/mcp.ts`|API 默认 disabled contract 先行|
|Wave 12|`frontend/src/lib/evidenceReferences.ts`、`frontend/src/pages/KnowledgeBase.tsx`、`frontend/src/pages/Workbench.tsx`、`frontend/src/services/*`|`swarmvault-desktop-main/src/renderer/`、`WeKnora-main/frontend/`、`LightRAG-1.4.15/lightrag_webui/`|先工作台信息密度，不做营销页|
|Wave 13|`project_paths.py`、`runtime_env.py`、`routers/resources_router.py`|`Knowledge-Base-Gateway-1.2.2026.10009/README.md`、`keppi-master/keppi/parser/`|只读 connector，绝不写用户 Zotero/EndNote/Obsidian|
|Wave 14|`tools/eval/compare_tolf_context_selector.py`、`workspace_tests/evaluation_scripts/eval_retrieval_runtime.py`、`tests/test_eval_runtime.py`|`LightRAG-1.4.15/lightrag/evaluation/`、`paper-qa-main/README.md`|新增独立 eval，不改现有 qrels|
|Wave 15|`README.md`、`AI_WORKSPACE_GUIDE.md`、`docs/plans/runbooks/`|`llm-wiki-coordination-main/README.md`、`swarmvault-main/README.md`|迁移/发布/协作策略，不急于实现 MCP|

## 难点切片的执行备注

### Registry 切片备注

- 不要把现有 `ChunkVectorStore` 直接替换掉；先做 `WikiRegistry`，再通过 adapter 从现有 chunks/evidence_refs 注册 source/chunk。
- `chunk_id` 必须可复现，不依赖当前时间、数据库自增 id 或随机数。
- `source_hash` 变化时不要静默覆盖；进入 review 或报 immutability violation。
- 参考 `wikiloom-main/wikiloom/chunk_store.py` 的 deterministic chunk id，参考 `TheKnowledge-main/src/gateway/validator.py` 的 source immutability。

### Citation 切片备注

- `citation_auditor.py` 现在只做 response evidence quote 检查；新 validator 要能处理 markdown 页面、claim sentence、wiki citation target。
- final mode 要 fail-closed；draft mode 可以 warning-open。
- 引用密度只是一层指标，不能替代 quote/chunk existence。
- 参考 `TheKnowledge-main/src/gateway/citations.py` 的 claim detection 和 citation density。

### Compiler 切片备注

- 第一版编译器不要直接调用 LLM；先 deterministic stub + dry-run + draft writer。
- LLM 接入必须等 schema validator、citation validator、review queue 都有最小实现后再开。
- 写入必须先生成 `WikiWritePlan`，dry-run 和真实写入共用同一个 plan。
- 参考 `llm-wiki-compiler-main/src/commands/compile.ts` 的 two-phase 思路，参考 OpenKB `add_single_file` 的 short/long doc 分流。

### Wiki-aware retrieval 切片备注

- 不要把 wiki-first 直接变默认；必须 env/config gate。
- 查询顺序建议：wiki FTS -> wiki linked pages -> wiki embeddings optional -> raw RAG fallback。
- 每次 fallback 都要写 trace：为什么 fallback、wiki hits 几个、raw hits 几个。
- 参考 `wikiloom-main/wikiloom/query.py` 的 primary/secondary context，参考 `llm-wiki-compiler-main/src/commands/query.ts` 的 chunk-aware page selection。

### Doctor/review 切片备注

- doctor 的 `repair` 只能自动做安全动作：建目录、建 schema、重建 index/log/manifest。
- 修改正文、删除页面、finalize draft、resolve duplicates 都必须进入 review queue。
- review queue 的 approve/reject 要记录 reason、actor、time、old status、new status。
- 参考 SwarmVault `doctor.ts` 的 check/action 结构，参考 OLW 的 approve/reject/undo 工作流。

### API/frontend 切片备注

- API 默认返回 `wiki_disabled`，不能在无配置时偷偷创建大目录或运行编译。
- 前端 first screen 应该是工作台式状态与任务队列，不做落地页。
- UI 中不要用大段解释文字替代真实控件；以 status、doctor、review、pages、graph tabs 为主。
- Evidence UI 已经能展示 `evidence_refs`，新增 wiki 功能应从这些引用跳转到 page/citation，而不是重复造一套证据对象。

## Wave 0：治理、回档、调研固化

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-224|为 LLM-Wiki 集成建立专用 rollback/runbook 模板|`docs/plans/runbooks/`|模板包含回档、成熟方案搜索、实现、验证、显式恢复命令|
|LMWR-225|建立参考项目对照索引|`docs/plans/specs/`|列出 PaperQA/OpenKB/llmwiki/OLW/TheKnowledge/WikiLoom/Keppi/LightRAG/RAG-Anything 对照|
|LMWR-226|冻结现有 RAG evidence contract 快照|`docs/plans/specs/`、`tests/`|记录 `EvidenceReference` 当前字段和兼容边界|
|LMWR-227|补全 dirty worktree 风险记录|`.squad/decisions/inbox/` 或本文档追加|列出不得覆盖的已改文件|
|LMWR-228|定义 wiki 集成 feature flag 命名|`runtime_env.py`、spec|所有新能力默认关闭，有 env/config gate|
|LMWR-229|定义 wiki 输出路径策略|`project_paths.py`、spec|所有 wiki 产物落入 `workspace_artifacts/`|
|LMWR-230|定义只读外部参考库规则|`docs/plans/runbooks/`|明确 `github/` 与下载库不得被改|
|LMWR-231|定义任务完成证据包格式|`docs/plans/runbooks/`|Facts/Decision/Evidence/Rollback/Open/Next 模板可复用|
|LMWR-232|定义 wiki 页面状态枚举|spec|`draft/review/final/deprecated/archived` 语义清晰|
|LMWR-233|定义 claim 审计分级|spec|`passed/warning/failed/draft_only` 可机器解析|
|LMWR-234|建立 LLM-Wiki 集成风险登记表|spec|覆盖 hallucination、stale source、duplicate、license、cost、privacy|
|LMWR-235|建立 LLM-Wiki task dependency graph|spec|每个 wave 依赖和阻塞条件可追踪|
|LMWR-236|补充 Copilot/Agent 执行提示模板|`docs/plans/runbooks/`|提示强制包含回档和成熟方案搜索|
|LMWR-237|建立 wiki integration stop conditions|spec|涉及评测口径、外部写回、默认链替换必须停下确认或独立 gate|
|LMWR-238|创建 Wave 0 focused verification|tests/docs|只验证新增文档路径和无代码行为变更|

## Wave 1：数据模型与 schema

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-239|新增 wiki domain model spec|`docs/plans/specs/`|定义 Source/Paper/Concept/Claim/Synthesis/Exploration/Edge|
|LMWR-240|实现 `WikiSource` 类型草案|`literature_assistant/core/wiki/models.py`|包含 source_id/source_hash/path/title/source_type/created_at|
|LMWR-241|实现 `WikiChunk` 类型草案|`wiki/models.py`|包含 stable chunk_id/material_id/page/span/text_hash|
|LMWR-242|实现 `WikiEvidenceRef` 兼容映射|`wiki/models.py`|可从现有 `EvidenceReference` 无损转换|
|LMWR-243|实现 `WikiPaperPage` 类型草案|`wiki/models.py`|包含 metadata、summary、claims、concepts、source_ids|
|LMWR-244|实现 `WikiConceptPage` 类型草案|`wiki/models.py`|包含 aliases、sources、related_concepts、open_questions|
|LMWR-245|实现 `WikiClaimPage` 类型草案|`wiki/models.py`|包含 claim_text、evidence_refs、confidence、status|
|LMWR-246|实现 `WikiSynthesisPage` 类型草案|`wiki/models.py`|包含 question、answer、evidence_refs、derived_from_pages|
|LMWR-247|实现 `WikiEdge` 类型草案|`wiki/models.py`|支持 `supports/contradicts/extends/depends_on/related_to`|
|LMWR-248|定义 frontmatter JSON/YAML schema|`docs/plans/specs/`|每类页面必填字段和可选字段清晰|
|LMWR-249|实现 schema validation helper 草案|`wiki/models.py`|非法类型/空 id/坏状态 fail fast（已合并入 models.py）|
|LMWR-250|补充 model serialization 测试|`tests/`|模型可 JSON roundtrip|
|LMWR-251|补充 EvidenceReference backward compatibility 测试|`tests/`|旧 evidence refs 不丢字段|
|LMWR-252|补充 page status transition 测试|`tests/`|非法 transition 被拒绝|
|LMWR-253|Wave 1 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 2：source registry 与 stable chunk registry

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-254|设计 source registry SQLite schema|`docs/plans/specs/`|sources/chunks/source_aliases/source_events 表结构明确|
|LMWR-255|实现 registry path resolver|`wiki/source_registry.py`|通过 `project_paths.py` 定位 runtime db|
|LMWR-256|实现 source_hash 计算|`wiki/source_registry.py`|同内容 hash 稳定，空文件拒绝|
|LMWR-257|实现 source_id 生成规则|`wiki/source_registry.py`|paper/pdf/web/note/other 有确定性 id|
|LMWR-258|实现 source upsert|`wiki/source_registry.py`|同 hash skip，变更写 event|
|LMWR-259|实现 source immutability guard|`wiki/source_registry.py`|raw source 变更不静默覆盖旧记录|
|LMWR-260|实现 chunk_id 派生规则|`wiki/source_registry.py`|参考 WikiLoom：source_hash + chunk_index（已合并入 source_registry.py）|
|LMWR-261|实现 chunk upsert|`wiki/source_registry.py`|同 source reingest 不产生重复 chunk（已合并入 source_registry.py）|
|LMWR-262|实现 page/span 元数据保存|`wiki/source_registry.py`|page、section、start/end 可保存（已合并入 source_registry.py）|
|LMWR-263|实现 chunk text_hash|`wiki/source_registry.py`|chunk 内容变化可检测（已合并入 source_registry.py）|
|LMWR-264|实现 chunk lookup by evidence_ref|`wiki/source_registry.py`|现有 evidence_ref 可回源（已合并入 source_registry.py）|
|LMWR-265|迁移现有 local project chunks 到 registry 只读 adapter|`wiki/source_registry.py`|不改现有 chunk store，只提供 adapter（已合并入 source_registry.py）|
|LMWR-266|测试 source/chunk registry roundtrip|`tests/`|SQLite 临时库插入/读取通过|
|LMWR-267|测试 source immutability 失败路径|`tests/`|同 source_id 不同 hash 进入 review/warning|
|LMWR-268|Wave 2 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 3：Markdown/frontmatter page store

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-269|设计 wiki markdown output layout|spec|`sources/papers/concepts/claims/synthesis/explorations/reports` 明确|
|LMWR-270|实现 safe slugify|`wiki/page_store.py`|中英文标题稳定转路径，非法字符处理|
|LMWR-271|实现 frontmatter parser|`wiki/page_store.py`|YAML/JSON frontmatter 解析失败有清晰错误（已合并入 page_store.py）|
|LMWR-272|实现 frontmatter renderer|`wiki/page_store.py`|字段排序稳定，日期格式 ISO（已合并入 page_store.py）|
|LMWR-273|实现 atomic markdown write|`wiki/page_store.py`|写入使用临时文件替换，失败不留半文件|
|LMWR-274|实现 markdown read_page|`wiki/page_store.py`|返回 frontmatter/body/path/hash|
|LMWR-275|实现 page_exists/list_pages|`wiki/page_store.py`|支持按 kind 过滤|
|LMWR-276|实现 generated section markers|`wiki/page_store.py`|保护人工编辑区，自动区可替换|
|LMWR-277|实现 hand-edit detection|`wiki/page_store.py`|参考 OLW，用户改动后进入 review/skip|
|LMWR-278|实现 index.md rebuild|`wiki/page_store.py`|按 kind/title/source 排序稳定|
|LMWR-279|实现 log.md append|`wiki/page_store.py`|所有 compile/query/save 写入 timeline|
|LMWR-280|测试 frontmatter roundtrip|`tests/`|多语言标题、list、dict 字段不丢|
|LMWR-281|测试 atomic write failure path|`tests/`|模拟异常不破坏旧页|
|LMWR-282|测试 hand-edit protection|`tests/`|人工区保留，自动区更新|
|LMWR-283|Wave 3 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 4：citation validator 与 finalize gate

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-284|定义 citation syntax|spec|支持 `[[sources/id#chunk]]`、`[chunk_id]`、page/span|
|LMWR-285|扩展 `CitationAuditor` 输入模型|`citation_auditor.py` 或 `wiki/citation_validator.py`|支持 evidence_refs + wiki claim|
|LMWR-286|实现 citation parser|`wiki/citation_validator.py`|能提取 source_id/chunk_id/page/span|
|LMWR-287|实现 claim sentence detector|`wiki/citation_validator.py`|参考 TheKnowledge，跳过代码块/header/list-only links|
|LMWR-288|实现 citation density metric|`wiki/citation_validator.py`|返回 cited_claims/total/ratio|
|LMWR-289|实现 quote exact match|`wiki/citation_validator.py`|quote 必须存在于 source/chunk text|
|LMWR-290|实现 quote fuzzy fallback metric|`wiki/citation_validator.py`|只作为 warning，不自动通过|
|LMWR-291|实现 source existence validation|`wiki/citation_validator.py`|引用不存在 source/chunk 时 fail|
|LMWR-292|实现 draft vs final validation mode|`wiki/citation_validator.py`|draft 可 warning，final 缺引用 fail|
|LMWR-293|实现 finalize command/service 草案|`wiki/review_queue.py`|finalize 前必须过 citation gate|
|LMWR-294|实现 validation report JSON|`wiki/citation_validator.py`|机器可读 errors/warnings/metrics|
|LMWR-295|测试无引用 claim 被拒绝|`tests/`|final mode fail|
|LMWR-296|测试 quote hallucination warning/fail|`tests/`|不存在 quote 被标记|
|LMWR-297|测试 draft finalize 成功路径|`tests/`|补齐 citation 后 status final|
|LMWR-298|Wave 4 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 5：RAG evidence_refs 到 wiki evidence 映射

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-299|设计 evidence_refs -> wiki citation mapping|spec|字段无损映射表|
|LMWR-300|实现 EvidenceReference coercer|`wiki/evidence_adapter.py`|旧 dict/TypedDict 均支持|
|LMWR-301|实现 evidence_ref source lookup|`wiki/evidence_adapter.py`|按 chunk_id/material_id 查 registry|
|LMWR-302|实现 evidence_ref normalized citation string|`wiki/evidence_adapter.py`|生成稳定 markdown citation|
|LMWR-303|实现 prompt evidence to wiki evidence conversion|`wiki/evidence_adapter.py`|`SOURCE_ID/MATERIAL/QUOTE/BODY` 可解析|
|LMWR-304|扩展 `RAGResult` 保存 wiki-ready evidence|`main_rag_workflow.py`|默认不改变输出，只增加可选字段或 helper|
|LMWR-305|实现 last_answer 到 synthesis draft adapter|`wiki/compiler.py`|可从 `last_answer.json` 生成 draft synthesis|
|LMWR-306|实现 missing evidence_ref fallback policy|`wiki/evidence_adapter.py`|缺 chunk_id 时进入 review，不伪造 final|
|LMWR-307|实现 source_labels 到 retrieval trail 保存|`wiki/evidence_adapter.py`|bm25/dense/graph/rrf/rerank 标签不丢|
|LMWR-308|实现 query_overlap_tokens 到 evidence note|`wiki/evidence_adapter.py`|方便 UI 解释证据命中|
|LMWR-309|测试 evidence_refs 无损转换|`tests/`|text/compressed/quote/page/rank/source_labels 都保留|
|LMWR-310|测试缺 chunk_id fallback|`tests/`|进入 draft/review|
|LMWR-311|测试 last_answer -> synthesis draft|`tests/`|生成 markdown + frontmatter|
|LMWR-312|测试 citation validator 接受 evidence adapter 输出|`tests/`|draft/final 两模式通过|
|LMWR-313|Wave 5 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 6：wiki 编译器最小闭环

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-314|设计 compile input contract|spec|输入 source/chunks/evidence_refs/config 清晰|
|LMWR-315|实现 compiler service skeleton|`wiki/compiler.py`|`compile_source`、`compile_project` 接口存在|
|LMWR-316|实现 dry-run compile plan|`wiki/compiler.py`|不写文件只返回将创建/更新页面|
|LMWR-317|实现 source summary page writer|`wiki/compiler.py`|从 source/chunks 写 `sources/*.md`|
|LMWR-318|实现 paper page draft writer|`wiki/compiler.py`|写 `papers/*.md`，不调用外部 LLM 的模板路径先通|
|LMWR-319|实现 concept page draft writer|`wiki/compiler.py`|从 focus/concepts/claims 初步聚合|
|LMWR-320|实现 claim page draft writer|`wiki/compiler.py`|每个 claim 有 evidence_refs|
|LMWR-321|实现 synthesis draft writer|`wiki/compiler.py`|从 query result 保存|
|LMWR-322|实现 compile skip by source_hash|`wiki/compiler.py`|无变更不重复写|
|LMWR-323|实现 compile transaction manifest|`wiki/compiler.py`|记录 touched pages / old hash / new hash|
|LMWR-324|实现 compile rollback metadata|`wiki/compiler.py`|为手动回滚提供 page manifest|
|LMWR-325|测试 dry-run 不写磁盘|`tests/`|临时目录无新增 wiki 文件|
|LMWR-326|测试 first compile 生成 index/log/pages|`tests/`|最小 source 生成完整目录|
|LMWR-327|测试 unchanged source skip|`tests/`|第二次 compile 无多余写入|
|LMWR-328|Wave 6 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 7：LLM 生成接入与 prompt 治理

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-329|设计 wiki compiler prompt templates|`prompt_templates/`、spec|summary/concept/claim/synthesis 模板分离|
|LMWR-330|对标 PaperQA RCS 和 OpenKB compile prompt|spec|记录取舍，不直接复制|
|LMWR-331|实现 provider-gated wiki LLM client wrapper|`wiki/compiler.py` 或 `model_call_gateway.py`|复用现有 env/test discipline|
|LMWR-332|实现 no-LLM deterministic stub mode|`wiki/compiler.py`|测试不需要外部 API|
|LMWR-333|实现 paper summary prompt|`prompt_templates/wiki_paper_summary.txt`|要求输出 JSON schema|
|LMWR-334|实现 concept extraction prompt|`prompt_templates/wiki_concept_extract.txt`|要求概念、aliases、evidence_refs|
|LMWR-335|实现 claim extraction prompt|`prompt_templates/wiki_claim_extract.txt`|要求每 claim 绑定证据|
|LMWR-336|实现 synthesis save prompt|`prompt_templates/wiki_synthesis.txt`|保存 query answer 时带 citation|
|LMWR-337|实现 LLM JSON repair/validation path|`wiki/compiler.py`|无效 JSON 进入 review，不写 final|
|LMWR-338|实现 token budget planner|`wiki/compiler.py`|长 source 按 chunk/evidence budget 裁剪|
|LMWR-339|实现 prompt audit trace|`workspace_artifacts/runtime_state/wiki/`|保存 masked prompt hash/model/cost，不泄露 key|
|LMWR-340|测试 stub mode compile|`tests/`|无 API key 也能跑|
|LMWR-341|测试 invalid LLM response 进入 review|`tests/`|不写 final|
|LMWR-342|测试 token budget guard|`tests/`|超长输入不爆 context|
|LMWR-343|Wave 7 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 8：wiki-aware retrieval 与 query pipeline

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-344|设计 wiki retrieval status manifest|`wiki/query.py`、spec|记录 index hash、page count、stale|
|LMWR-345|实现 wiki page FTS index|`wiki/query.py`|SQLite FTS 可搜 page/title/body（已合并入 query.py）|
|LMWR-346|实现 wiki page embedding adapter|`wiki/query.py`|复用 `ChunkVectorStore`，默认可关闭|
|LMWR-347|实现 wiki-first retrieval flag|`main_rag_workflow.py`|默认关闭，开启后先读 wiki|
|LMWR-348|实现 primary wiki page retrieval|`wiki/query.py`|top-k pages + scores|
|LMWR-349|实现 linked page expansion|`wiki/query.py`|参考 WikiLoom，primary -> outbound/inbound|
|LMWR-350|实现 raw RAG fallback bridge|`wiki/query.py`|wiki 无命中时回现有 RAG|
|LMWR-351|实现 wiki context pack renderer|`wiki/query.py`|token bounded, cited context|
|LMWR-352|实现 query debug trace|`wiki/query.py`|wiki_hits/raw_hits/fallback_reason|
|LMWR-353|实现 saved exploration page flow|`wiki/query.py`|query answer 可保存到 `explorations/`|
|LMWR-354|测试 wiki-first no-hit fallback|`tests/`|不影响现有 RAG answer|
|LMWR-355|测试 linked expansion ranking|`tests/`|被多个 primary 引用的 page 排名前|
|LMWR-356|测试 context pack token budget|`tests/`|超预算截断且记录 omitted|
|LMWR-357|测试 saved exploration citation|`tests/`|保存页过 citation validator|
|LMWR-358|Wave 8 compileall/pytest 收口|verification|focused tests + compileall pass|

## Wave 9：graph 与 typed relations

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-359|设计 typed edge ontology|spec|参考 OmegaWiki/Coordination/Keppi|
|LMWR-360|实现 graph store JSON/SQLite schema|`wiki/graph.py`|nodes/edges/status/hash|
|LMWR-361|实现 wikilink parser|`wiki/graph.py`|解析 `[[kind/slug]]`|
|LMWR-362|实现 edge extraction from frontmatter|`wiki/graph.py`|sources/claims/concepts 关系入图|
|LMWR-363|实现 inbound/outbound backlinks|`wiki/graph.py`|页面可查双向链接|
|LMWR-364|实现 orphan detection|`wiki/doctor.py`|孤立页报告|
|LMWR-365|实现 duplicate concept candidates|`wiki/doctor.py`|slug/fuzzy/embedding 候选|
|LMWR-366|实现 blast radius|`wiki/graph.py`|参考 Keppi，按 edge weight BFS|
|LMWR-367|实现 claim contradiction edge stub|`wiki/graph.py`|先存人工/LLM 标记，不自动判 final|
|LMWR-368|实现 graph export JSON|`wiki/export.py`|前端/Obsidian 可用|
|LMWR-369|测试 backlinks|`tests/`|in/out 关系正确|
|LMWR-370|测试 orphan report|`tests/`|孤立 concept 被标记|
|LMWR-371|测试 duplicate candidates|`tests/`|近似 slug 被发现|
|LMWR-372|测试 blast radius|`tests/`|深度/阈值正确|
|LMWR-373|Wave 9 compileall/pytest 收口|verification|focused tests + compileall pass|

### Wave 9 执行证据（2026-05-04 Codex）

- ✅ `LMWR-359`：typed edge ontology 已落到 `literature_assistant/core/wiki/graph.py`，采用保守白名单，覆盖 wikilink、related/derived/supports/contradicts/depends_on 以及论文-概念/论文-论文语义边 stub。
- ✅ `LMWR-360`：`WikiGraphStore` 支持 deterministic `graph.json` + SQLite `graph.db` 双写，并新增 `WikiGraphStore.default()` 使用 canonical `workspace_artifacts/runtime_state/wiki/` 路径。
- ✅ `LMWR-361`：wikilink parser 支持 `[[target]]` / `[[target|display]]`，并跳过 fenced/inline code。
- ✅ `LMWR-362`：frontmatter relation extraction 支持 `supports`、`contradicts`、`derived_from`、`depends_on`、`related` 等字段。
- ✅ `LMWR-363`：`WikiGraphStore.backlinks()` 可查 inbound/outbound typed edges。
- ⏸️ `LMWR-364` / `LMWR-365`：orphan/duplicate doctor 仍留到 Wave 10 doctor/review queue 统一实现。
- ✅ `LMWR-366`：`compute_blast_radius()` 实现 weighted BFS，支持 `in/out/both`、depth、threshold。
- ✅ `LMWR-367`：contradiction edge 作为显式 frontmatter/人工标记入图，不自动判定 final。
- ✅ `LMWR-368`：`literature_assistant/core/wiki/export.py` 提供 deterministic graph JSON export。
- ✅ `LMWR-369` / `LMWR-372`：新增 `tests/wiki/test_graph.py` 覆盖 backlinks、SQLite/JSON persistence、weighted blast radius、export。
- ✅ `LMWR-373`：验证通过：
  - `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki literature_assistant\core\project_paths.py`
  - `.\.venv-1\Scripts\python.exe -m pytest tests\wiki -q` -> `232 passed`
  - `.\.venv-1\Scripts\python.exe -m pytest tests\test_main_rag_workflow_generation.py tests\wiki\test_query.py tests\wiki\test_query_save_exploration.py tests\wiki\test_graph.py -q` -> `54 passed`
- 回档点：
  - `20260504-172308-lmwr-359-368-wave9-graph-core`
  - `20260504-172524-lmwr-359-368-wave9-graph-continue`

## Wave 10：doctor、review queue、治理面

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-374|设计 wiki doctor report schema|spec|workspace/source/retrieval/citation/graph/review|
|LMWR-375|实现 workspace doctor|`wiki/doctor.py`|检查目录、db、config|
|LMWR-376|实现 source doctor|`wiki/doctor.py`|stale hash、missing source、orphan source|
|LMWR-377|实现 retrieval doctor|`wiki/doctor.py`|index stale/missing|
|LMWR-378|实现 citation doctor|`wiki/doctor.py`|uncited claims、broken citations|
|LMWR-379|实现 graph doctor|`wiki/doctor.py`|broken links、orphans、duplicates|
|LMWR-380|实现 review queue schema|`wiki/review_queue.py`|draft/fail/warning/manual_edit queue|
|LMWR-381|实现 review list/read|`wiki/review_queue.py`|可查看待处理项|
|LMWR-382|实现 review approve/reject|`wiki/review_queue.py`|approve finalize，reject 记录 reason|
|LMWR-383|实现 auto-repair safe subset|`wiki/doctor.py`|只允许 rebuild index/log，禁止改内容|
|LMWR-384|实现 doctor CLI/API service boundary|`routers/` or service|返回机器可读 report|
|LMWR-385|测试 doctor empty workspace|`tests/`|缺目录报 error|
|LMWR-386|测试 review approve/reject|`tests/`|状态转移正确|
|LMWR-387|测试 doctor repair safe subset|`tests/`|只重建索引，不改页面正文|
|LMWR-388|Wave 10 compileall/pytest 收口|verification|focused tests + compileall pass|

### Wave 10 执行证据（2026-05-04 Codex）

- ✅ `LMWR-374`：`wiki/doctor.py` 定义机器可读 `DoctorAction` / `DoctorCheck` / `DoctorReport` / `RepairResult`。
- ✅ `LMWR-375`：workspace doctor 检查 generated wiki root 和 page count。
- ✅ `LMWR-376`：registry/source doctor 检查 registry DB、source count、orphan source。
- ✅ `LMWR-377`：retrieval doctor 检查 FTS DB、page count/indexed count drift，并给出 safe rebuild action。
- ✅ `LMWR-378`：citation doctor 复用 `citation_validator`，final 页缺引用/坏引用进入 error，draft 警告进入 review。
- ✅ `LMWR-379`：graph doctor 复用 `wiki/graph.py`，报告 broken links、orphans、duplicate concept candidates、graph artifact presence。
- ✅ `LMWR-380`：`wiki/review_queue.py` 实现 JSONL review queue schema，覆盖 draft/fail/warning/manual_edit。
- ✅ `LMWR-381`：review queue 支持 append/list/get/filter。
- ✅ `LMWR-382`：review queue 支持 approve/reject 决策记录；不自动 finalize，不修改页面正文。
- ✅ `LMWR-383`：`WikiDoctor.repair_safe_subset()` 仅允许创建目录、初始化 registry、重建 retrieval index、重建 graph JSON/SQLite。
- ⏸️ `LMWR-384`：doctor CLI/API service boundary 留到 Wave 11 API contract 一并接入。
- ✅ `LMWR-385` / `LMWR-386` / `LMWR-387`：新增 `tests/wiki/test_doctor.py`、`tests/wiki/test_review_queue.py` 覆盖 empty workspace、review approve/reject、safe repair。
- ✅ `LMWR-388`：验证通过：
  - `.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki literature_assistant\core\project_paths.py literature_assistant\core\main_rag_workflow.py literature_assistant\core\runtime_env.py`
  - `.\.venv-1\Scripts\python.exe -m pytest tests\wiki -q` -> `247 passed`
  - `.\.venv-1\Scripts\python.exe -m pytest tests\test_main_rag_workflow_generation.py tests\wiki\test_query.py tests\wiki\test_query_save_exploration.py tests\wiki\test_graph.py tests\wiki\test_doctor.py tests\wiki\test_review_queue.py -q` -> `69 passed`
- 回档点：
  - `20260504-173149-lmwr-374-379-wave10-doctor-core`
  - `20260504-173456-lmwr-380-382-wave10-review-queue`

## Wave 11：API contract 与 CLI/服务入口

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-389|设计 `/api/wiki/status` contract|`routers/wiki_router.py`|返回 status/paths/counts/stale|
|LMWR-390|设计 `/api/wiki/compile` contract|`routers/wiki_router.py`|支持 dry_run、source_id、project_id|
|LMWR-391|设计 `/api/wiki/query` contract|`routers/wiki_router.py`|支持 wiki_first、save、debug|
|LMWR-392|设计 `/api/wiki/pages` contract|`routers/wiki_router.py`|list/read/filter|
|LMWR-393|设计 `/api/wiki/review` contract|`routers/wiki_router.py`|list/approve/reject|
|LMWR-394|设计 `/api/wiki/doctor` contract|`routers/wiki_router.py`|report/repair=false|
|LMWR-395|实现 router skeleton default-off|`routers/wiki_router.py`|未开启时返回 disabled status|
|LMWR-396|接入 FastAPI app|`python_adapter_server.py`|OpenAPI 可见 wiki routes|
|LMWR-397|实现 CLI runbook wrapper|`run_literature_assistant.py` 或 new tool|支持 status/doctor dry-run|
|LMWR-398|补充 OpenAPI schema snapshot|`workspace_artifacts` or tests|schema 生成成功|
|LMWR-399|测试 status disabled|`tests/`|默认关闭不破坏服务|
|LMWR-400|测试 compile dry-run API|`tests/`|不写磁盘|
|LMWR-401|测试 doctor API|`tests/`|返回机器可读 report|
|LMWR-402|测试 review API contract|`tests/`|approve/reject 状态正确|
|LMWR-403|Wave 11 compileall/pytest 收口|verification|focused tests + OpenAPI pass|

### Wave 11 收口结果（2026-05-04 Copilot）

- `LMWR-389`：`WikiStatusResponse` 已补齐 `stale` 字段；status contract 现在覆盖 `enabled/page_count/stale/paths`，并锁定“有页面但缺 query index => stale=true；索引对齐 => stale=false”。
- `LMWR-390` / `LMWR-391`：compile/query request surface 已通过 focused contract tests 锁定，覆盖 `source_id`、`project_id`、`wiki_first`、`save`、`debug`；`save=true` 时明确返回 service-integration 边界错误而非静默写盘。
- `LMWR-392` / `LMWR-393` / `LMWR-394`：pages list/read/filter、review list/approve/reject、doctor report contract 已在 `tests/wiki/test_wiki_router.py` 覆盖。
- `LMWR-395` / `LMWR-396` / `LMWR-397`：router default-off、full app OpenAPI 接入、CLI wrapper `wiki status|doctor` 已落地。
- `LMWR-398` / `LMWR-399` / `LMWR-400` / `LMWR-401` / `LMWR-402` / `LMWR-403`：focused 验证 `pytest tests/wiki/test_wiki_router.py tests/wiki/test_wiki_cli.py -q` → `15 passed`；CLI smoke 返回机器可读 disabled status JSON；相关文件 `compileall` 通过。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-397-wave11-cli-openapi.md`。
- 下一步：继续 Wave 12，优先把 `WikiPageList` / `DoctorReportPanel` 的只读骨架接到已落地的 `/wiki` 状态面上。

## Wave 12：前端 Wiki 工作台最小产品面

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-404|设计 Wiki 面板信息架构|`frontend/src/`、spec|Status/Pages/Review/Graph/Doctor 分区|
|LMWR-405|新增 wiki API client types|`frontend/src/lib`|TypeScript strict，无 `any`|
|LMWR-406|新增 WikiStatusCard|`frontend/src/components`|显示 enabled/stale/page counts|
|LMWR-407|新增 WikiCompileDryRunPanel|frontend|展示将写入页面，不直接执行写入|
|LMWR-408|新增 WikiPageList|frontend|按 kind/status/filter|
|LMWR-409|新增 WikiPagePreview|frontend|frontmatter + body preview|
|LMWR-410|新增 ReviewQueuePanel|frontend|approve/reject UI，带 reason|
|LMWR-411|新增 DoctorReportPanel|frontend|errors/warnings/actions|
|LMWR-412|新增 CitationWarnings view|frontend|uncited/broken quote 可读|
|LMWR-413|新增 GraphJson debug view|frontend|先 JSON/列表，后续再图可视化|
|LMWR-414|接入 existing Evidence UI|frontend|evidence_refs 可跳转 wiki citation|
|LMWR-415|测试 API client parsing|frontend tests|unknown payload 防守|
|LMWR-416|测试 ReviewQueuePanel|frontend tests|approve/reject 状态|
|LMWR-417|测试 DoctorReportPanel|frontend tests|error/warning/action 渲染|
|LMWR-418|Wave 12 frontend test/build 收口|verification|Vitest focused + build pass|

### Wave 12 首刀结果（2026-05-04 Copilot）

- `LMWR-404`：`/wiki` 页面信息架构已落地为 `Status / Pages / Review / Graph / Doctor` 五分区，后四项先以工作台占位卡形式显式摆出下一刀方向。
- `LMWR-405`：已执行 `frontend/npm run generate:openapi`，刷新 `frontend/openapi/modular-pipeline-openapi.json` 与 `frontend/src/generated/openapi.ts`；新增 `frontend/src/types/wiki.ts` + `frontend/src/services/wikiApi.ts`，用 generated schema alias + strict parser 构成 wiki client types。
- `LMWR-406`：新增 `frontend/src/components/wiki/WikiStatusCard.tsx`，显示 `enabled/stale/page_count`、graph/index/review existence、canonical paths 与 warnings。
- `LMWR-415`：新增 `frontend/src/services/wikiApi.test.ts`，锁定 backend wiki status payload parsing 与 malformed warnings 防守。
- Wave 12 页面入口已接入 `frontend/src/App.tsx` 与 `frontend/src/layouts/MainLayout.tsx`，现在侧边栏可直接进入 `/wiki`。
- focused 验证：`npx vitest run src/services/wikiApi.test.ts` → `2 passed`；`npm run build` → PASS；浏览器 smoke 证明 `/wiki` 页面可渲染，后端离线时显示中文错误诊断而非白屏。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-405-wave12-status-workbench.md`。

### Wave 12 第二刀结果（2026-05-04 Copilot）

- `LMWR-408`：新增 `WikiPageListPanel`，在 `/wiki` 页面中以只读方式展示 page list，并支持 `kind/status` 本地筛选。
- `LMWR-410` / `LMWR-411`：新增 `ReviewQueuePanel` 与 `DoctorReportPanel`，分别显示 review queue 与 doctor report 的机器可读结果；本轮坚持只读，不接 mutate。
- `LMWR-413`：新增 `GraphDebugPanel`，展示 `node_count/edge_count` 与 node/edge preview，先满足 debug 可读性，不提前做图可视化。
- `frontend/src/services/wikiApi.ts` 已扩展到 status/pages/doctor/review/graph 五类 parser；`frontend/src/services/wikiApi.test.ts` 现覆盖 6 项 focused parsing tests。
- focused 验证：`npx vitest run src/services/wikiApi.test.ts` → `6 passed`；`npm run build` → PASS；浏览器 smoke 证明 `/wiki` 已显示五块只读工作台面，并在后端离线时统一展示中文错误诊断。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-408-wave12-readonly-panels.md`。

### Wave 12 第三刀结果（2026-05-04 Copilot）

- `LMWR-407`：新增 `frontend/src/components/wiki/WikiCompileDryRunPanel.tsx`，把 `/api/wiki/compile` 的 safe-mode dry-run contract 接进工作台，展示 optional scope、warnings、planned paths 与只读安全边界。
- `LMWR-409`：新增 `frontend/src/components/wiki/WikiPagePreviewPanel.tsx`，并让 `WikiPageListPanel` 支持选中态，把 `/api/wiki/pages/{page_path}` 的 page read contract 接成主从 preview 结构。
- `LMWR-415`：`frontend/src/services/wikiApi.ts` 已扩展到 `parseWikiPageDetail` / `parseWikiCompileDryRun` 与对应 loader；`frontend/src/services/wikiApi.test.ts` 现覆盖 8 项 focused parsing tests。
- `frontend/src/pages/WikiWorkbench.tsx` 已升级为三排布局：`Pages + Preview`、`Doctor + Compile`、`Review + Graph`，而且在后端返回 500/不可用时仍保持中文错误提示与空态，不白屏。
- focused 验证：`npx vitest run src/services/wikiApi.test.ts` → `8 passed`；`npm run build` → PASS；浏览器 smoke 证明 `/wiki` 已显示 `Wiki 页面预览` 与 `Wiki Compile Dry-Run` 两块新面板。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-407-wave12-compile-preview.md`。

### Wave 12 第四刀结果（2026-05-04 Copilot + Gemini frontend subagent）

- `LMWR-412`：`WikiPagePreviewPanel` 已新增 `文内引用与证据预警` 卡片，页面 preview 可读出 empty body、缺 citation/evidence、缺 evidence_refs、malformed evidence_refs、claim 缺 quote/Evidence 上下文等风险。
- `LMWR-415`：`frontend/src/services/wikiApi.test.ts` 已从 8 项扩展到 11 项 focused tests；先用新增用例复现旧启发式的 3 个失败，再修正 `extractCitationWarnings` 后全部转绿。
- `frontend/src/services/wikiApi.ts` 的 `extractCitationWarnings` 已收紧为 evidence-aware 版本：识别 `evidence_refs/references`，区分 `[[wikilink]]` 与 `[来源]` / `@cite(...)`，并避免对合格 evidence_refs 的 claim/final 页面误报。
- `LMWR-414`：本刀只完成 evidence_refs 跳转 readiness 的前置检查；existing Evidence UI 到 wiki citation/page preview 的实际跳转仍保留为下一刀。
- focused 验证：`npx vitest run src/services/wikiApi.test.ts` → `11 passed`；`npm run build` → PASS；浏览器 smoke 证明 `/wiki` 页面完整渲染，后端离线时各 panel 显示中文 500 诊断而非白屏。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-412-wave12-citation-warnings.md`。

### Wave 12 第五刀结果（2026-05-04 Copilot）

- `LMWR-414`：existing Evidence UI 已接到 Wiki read-only preview deep link；Chat `Evidence References` 与 Writing Canvas `evidence_refs` 卡片在存在显式 wiki page path 时显示 `Wiki preview` / `Wiki` 入口。
- `frontend/src/lib/evidenceReferences.ts` 新增 `getEvidenceReferenceWikiPagePath` / `getEvidenceReferenceWikiUrl`，只接受 `page_store_path`、`wiki_page_path`、`page_path`，并拒绝 source-only、绝对路径、Windows drive path 与 `..` 路径。
- `frontend/src/pages/WikiWorkbench.tsx` 支持 `/wiki?page=...` 自动加载 preview；即使 pages list 为空或后端离线，也保留 deep-linked target 并展示中文错误。
- `LMWR-415`：`frontend/src/lib/evidenceReferences.test.ts` 新增 TDD helper 用例；先红灯验证缺失 helper，再转绿。
- focused 验证：`npm --prefix frontend exec vitest -- run src/lib/evidenceReferences.test.ts src/services/wikiApi.test.ts` → `17 passed`；`npm --prefix frontend run build` → PASS；浏览器 smoke 证明 `/wiki?page=sources%2Fpaper-a.md` 可渲染并显示 page preview 中文错误态。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-414-wave12-evidence-wiki-links.md`。

### Wave 12 第六刀结果（2026-05-04 Copilot）

- `LMWR-416`：新增 `frontend/src/components/wiki/ReviewQueuePanel.test.tsx`，覆盖 review item 渲染、pending/approved 状态、decision reason、本地 status filter 与 refresh callback。
- `LMWR-417`：新增 `frontend/src/components/wiki/DoctorReportPanel.test.tsx`，覆盖 doctor warnings、overall status、structured checks、metrics、safe auto repair / manual only action hints 与 refresh callback。
- `LMWR-418`：Wave 12 frontend gate 已跑通；focused UI tests、Wave 12 focused tests、full Vitest 与 build 均通过。
- 验证：Review/Doctor focused UI tests → `2 passed`；Wave 12 focused frontend tests → `19 passed`；frontend full Vitest → `54 passed`；`npm --prefix frontend run build` → PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-416-418-wave12-ui-tests-gate.md`。
- 暂停/交接记录：`docs/plans/runbooks/llmwiki-handoff-2026-05-04-wave12-closeout-wave13-partial.md`。
- 下一步：Wave 12 最小前端面已可收口；继续前先做一次状态核对，然后按计划进入 Wave 13 connector 设计/只读接口。

## Wave 13：Zotero/EndNote/Obsidian 只读 connector 设计与最小接入

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-419|设计 connector interface|spec / `wiki/connectors/`|list_sources/read_source/extract_metadata|
|LMWR-420|对标 Knowledge-Base-Gateway source model|spec|记录 Zotero/EndNote/Obsidian 可读字段|
|LMWR-421|实现 filesystem markdown connector|`wiki/connectors/markdown.py`|只读扫描 Obsidian-like notes|
|LMWR-422|实现 PDF folder connector skeleton|`wiki/connectors/pdf_folder.py`|只读列出 PDF metadata/path|
|LMWR-423|实现 Zotero connector spec only|spec|不读用户真实库，先定义接口|
|LMWR-424|实现 EndNote connector spec only|spec|不读用户真实库，先定义接口|
|LMWR-425|实现 connector permission guard|`wiki/connectors/base.py`|外部路径必须显式配置|
|LMWR-426|实现 connector source_id namespace|`wiki/connectors/base.py`|`zotero:`, `endnote:`, `obsidian:`|
|LMWR-427|实现 connector dry-run scan report|`wiki/connectors/base.py`|不写 registry，只返回 counts|
|LMWR-428|实现 connector errors sanitization|`wiki/connectors/base.py`|不泄露本地隐私路径到公开日志|
|LMWR-429|测试 markdown connector|`tests/`|临时目录 notes 扫描正确|
|LMWR-430|测试 external path guard|`tests/`|未配置路径拒绝|
|LMWR-431|测试 source_id namespace|`tests/`|不同 connector 不冲突|
|LMWR-432|测试 dry-run no writes|`tests/`|registry/page store 无变化|
|LMWR-433|Wave 13 compileall/pytest 收口|verification|focused tests pass|

### Wave 13 结果（2026-05-04 Codex）

- `LMWR-419` / `LMWR-425` / `LMWR-426` / `LMWR-427` / `LMWR-428`：`wiki/connectors/base.py` 已补 ReadOnlyConnector protocol、ConnectorSpec/ConnectorFieldSpec、外部路径白名单、namespaced source_id、dry-run no-write report、错误脱敏 helper。
- `LMWR-420`：已对齐 `github/Knowledge-Base-Gateway-1.2.2026.10009/README.md` 的只读边界，以及 `keppi-master/keppi/parser/` 的 Markdown vault 扫描/排除目录思路。
- `LMWR-421`：`MarkdownConnector` 已支持 Obsidian-like notes 只读扫描、读取、metadata、`.obsidian/.git/.trash/templates` 与 `*.excalidraw.md` 排除、slug collision 后缀。
- `LMWR-422`：`PdfFolderConnector` 已支持 PDF metadata/path/size 列表，明确拒绝 text extraction。
- `LMWR-423` / `LMWR-424`：新增 Zotero / EndNote spec-only connector contract，不读取用户真实数据库或附件目录。
- `LMWR-429` ~ `LMWR-433`：`tests/wiki/test_connectors.py` 已扩展到 10 项 focused tests，覆盖 path guard、markdown scan/read、private/template 排除、source_id collision、PDF skeleton、dry-run no writes、error sanitization、Zotero/EndNote spec-only。
- 验证：`pytest tests/wiki/test_connectors.py -q` → `10 passed`；connector 包与 focused test `compileall` PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-419-433-wave13-connectors.md`。
- 下一步：进入 Wave 14 前先做回档与成熟方案搜索，优先评测/质量门禁的最小独立 manifest 和 collect-only/compileall gate。

## Wave 14：评测、回归、质量门禁

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-434|设计 wiki-aware retrieval eval manifest|`tools/eval/` spec|不改现有 qrels，只新增独立 manifest|
|LMWR-435|实现 wiki vs raw RAG zero-cost comparison|`tools/eval/`|比较 top-k overlap/empty/fallback|
|LMWR-436|实现 citation audit eval report|`tools/eval/`|统计 citation pass/warn/fail|
|LMWR-437|实现 compile quality smoke dataset|`workspace_tests/fixtures`|小型论文/notes fixture|
|LMWR-438|实现 duplicate/graph doctor fixtures|fixtures|覆盖 broken link/orphan/duplicate|
|LMWR-439|实现 cost guard for wiki LLM compile|`wiki/compiler.py`|预算超限拒绝或 dry-run|
|LMWR-440|实现 no-secret trace check|tests|trace 不包含 API key|
|LMWR-441|实现 performance baseline|`tools/eval/`|compile/query 时间记录|
|LMWR-442|实现 rollback restore rehearsal runbook|runbook|只列命令，不自动恢复|
|LMWR-443|实现 CI-friendly test subset marker|tests|wiki tests 可 focused 跑|
|LMWR-444|测试 wiki eval manifest dry-run|tests|不调用模型|
|LMWR-445|测试 citation audit metrics|tests|pass/warn/fail 统计正确|
|LMWR-446|测试 no-secret trace|tests|密钥 mask|
|LMWR-447|跑 workspace verification|verification|system_verification JSON pass 或记录 blocker|
|LMWR-448|Wave 14 compileall/pytest 收口|verification|focused + collect-only pass|

### Wave 14 首刀结果（2026-05-04 Codex）

- `LMWR-434`：新增 `literature_assistant/core/wiki/evaluation.py`，定义 `WikiEvalManifest` / `WikiEvalCase`，manifest 支持 query、expected source/chunk IDs、wiki/raw context IDs、answer_page_path、answer、ground_truth、contexts。
- `LMWR-435`：新增 `compare_wiki_vs_raw_retrieval()`，零成本计算 wiki/raw hit_rate、MRR、precision、recall，不调用模型，不改 qrels。
- `LMWR-436`：新增 `audit_wiki_page_text()` / `audit_wiki_pages()`，读取当前 `---json` wiki page frontmatter，输出 citation/evidence_refs/claim density 的 pass/warn/fail 统计。
- `tests/wiki/test_evaluation.py` 新增 8 项 focused tests，覆盖 manifest validation、retrieval metrics、wiki/raw comparison、citation audit、aggregate counts、page path escape guard。
- 验证：`pytest tests/wiki/test_evaluation.py -q` → `8 passed`；`pytest tests/wiki/test_citation_validator.py tests/wiki/test_page_store.py tests/wiki/test_evaluation.py -q` → `82 passed`；`compileall literature_assistant/core/wiki tests/wiki` PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-434-436-wave14-zero-cost-eval.md`。
- 下一步：继续 `LMWR-437` / `LMWR-438` fixtures 与 `LMWR-440` / `LMWR-446` no-secret trace check；仍禁止模型调用和无备份外部写回；qrels/goldset/canary30 改写按最新授权补充执行。

### Wave 14 第二刀结果（2026-05-04 Codex）

- `LMWR-437`：新增 `workspace_tests/fixtures/wiki_eval_smoke/`，包含 zero-cost eval manifest 与 2 个 rendered wiki page smoke fixtures，覆盖 source_id 和 16-hex chunk_id citation。
- `LMWR-440` / `LMWR-446`：`wiki/evaluation.py` 新增 no-secret scan，检测 Authorization/Bearer、`sk-` key、AWS-style key、named secret field、Windows `C:\Users\...` 私有路径，并且 finding 不回显 raw secret/path。
- `tests/wiki/test_evaluation.py` 扩展到 11 项 focused tests，新增 fixture load/compare/audit/no-secret scan、危险文本脱敏、真实 `write_query_trace()` 输出扫描。
- 验证：`pytest tests/wiki/test_evaluation.py -q` → `11 passed`；`pytest tests/wiki/test_citation_validator.py tests/wiki/test_page_store.py tests/wiki/test_query.py tests/wiki/test_evaluation.py -q` → `108 passed`；`compileall literature_assistant/core/wiki tests/wiki workspace_tests/fixtures/wiki_eval_smoke` PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-437-440-446-wave14-fixtures-no-secret.md`。
- 下一步：`LMWR-438` duplicate/orphan/broken-link fixtures、`LMWR-439` cost guard、`LMWR-443` CI subset marker、`LMWR-447` / `LMWR-448` collect-only/workspace verification 收口。

### Wave 14 第三刀结果（2026-05-04 Codex）

- `LMWR-438`：新增 `workspace_tests/fixtures/wiki_graph_doctor_smoke/`，使用 `alpha-model` / `alpha-models` 两个 rendered wiki pages 锁定 broken-link、orphan、duplicate candidate 组合。
- `tests/wiki/test_doctor.py` 新增 fixture-based doctor graph 测试，确保 workspace fixture 与临时目录测试得到一致 metrics。
- 验证：`pytest tests/wiki/test_doctor.py tests/wiki/test_graph.py tests/wiki/test_evaluation.py -q` → `27 passed`；`compileall literature_assistant/core/wiki tests/wiki workspace_tests/fixtures` PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-438-wave14-doctor-graph-fixtures.md`。
- 下一步：`LMWR-439` cost guard、`LMWR-443` CI subset marker、`LMWR-447` / `LMWR-448` collect-only/workspace verification 收口。

### Wave 14 第四刀结果（2026-05-04 Codex）

- `LMWR-439`：`wiki/compiler.py` 新增 `CompileBudget` / `CompileBudgetCheck` / `check_compile_budget()`；`WikiCompiler` 支持 optional budget，并在 `compile_source()` 写页面前执行 hard guard。
- 超预算 source 在 real compile 和 dry-run 下都返回 `skipped=1` 与机器可读 error，不写 page store；正常小输入旧行为保持不变。
- `tests/wiki/test_compiler.py` 扩展到 13 项 focused tests，覆盖超 chunks、超 chars、budget estimate。
- 验证：`pytest tests/wiki/test_compiler.py -q` → `13 passed`；`pytest tests/wiki/test_compiler.py tests/wiki/test_llm_gateway.py tests/wiki/test_evaluation.py tests/wiki/test_doctor.py tests/wiki/test_graph.py -q` → `55 passed`；`compileall literature_assistant/core/wiki tests/wiki workspace_tests/fixtures` PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-439-wave14-compile-cost-guard.md`。
- 下一步：`LMWR-441` performance baseline、`LMWR-443` CI subset marker、`LMWR-447` / `LMWR-448` collect-only/workspace verification 收口。

### Wave 14 收口结果（2026-05-04 Codex）

- `LMWR-441`：新增 `tools/eval/wiki_wave14_performance_baseline.py`，在临时目录内运行 source compile -> query index -> query search，stdout 输出 JSON，不调用模型、不写 qrels/goldset、不写 runtime artifacts。
- `LMWR-443`：`pytest.ini` 注册 `wiki_wave14` marker，`tests/wiki/test_evaluation.py` 使用模块级 marker，可用 `pytest tests/wiki -m wiki_wave14 -q` 跑 CI-friendly subset。
- `LMWR-447` / `LMWR-448`：Wave 14 收口验证通过：
  - `pytest tests/wiki -m wiki_wave14 -q` → `11 passed, 276 deselected`
  - `pytest tests/wiki/test_evaluation.py -q` → `11 passed`
  - `pytest tests --collect-only -q` → `1618 tests collected`
  - `compileall literature_assistant/core/wiki tests/wiki workspace_tests/fixtures` PASS
  - `pytest tests/wiki -q` → `287 passed`
  - `run_literature_assistant.py paths` PASS
  - `system_verification.py --json` → `23 passed / 0 failed / 0 warnings`
- Performance baseline sample：`compile_ms=4.929`、`index_ms=10.676`、`query_ms=0.224`、`created_pages=2`、`query_hit_count=1`。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-441-443-447-448-wave14-final-gate.md`。
- 下一步：Wave 15 迁移、发布门禁、长期维护；进入前仍必须回档并搜索/读取成熟方案。

## Wave 15：迁移、发布门禁、长期维护

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-449|✅ 编写 migration plan：evidence_refs 到 wiki registry|`docs/plans/specs/llmwiki-wave15-migration-maintenance-spec.md`|说明现有数据如何只读导入|
|LMWR-450|✅ 编写 migration dry-run command|`literature_assistant/core/wiki/migration.py`、CLI、runbook|不写入时输出 would-import|
|LMWR-451|✅ 编写 backup/export plan|`literature_assistant/core/wiki/backup.py`、CLI、runbook|wiki db/pages/graph 一键打包|
|LMWR-452|✅ 编写 wiki cleanup policy|`docs/plans/specs/llmwiki-wave15-migration-maintenance-spec.md`|stale/deprecated/archived 处理|
|LMWR-453|✅ 编写 human edit policy|`docs/plans/specs/llmwiki-wave15-migration-maintenance-spec.md`|自动区/人工区/冲突处理|
|LMWR-454|✅ 编写 multi-agent coordination policy|`docs/plans/specs/llmwiki-wave15-migration-maintenance-spec.md`|参考 llm-wiki-coordination，不强制引入|
|LMWR-455|✅ 编写 wiki MCP/tool exposure plan|`docs/plans/specs/llmwiki-wave15-migration-maintenance-spec.md`|后续给 Codex/Claude 使用，先不实现|
|LMWR-456|✅ 编写 frontend release checklist|`docs/plans/runbooks/llmwiki-slice-LMWR-456-459-wave15-release-privacy-rollback.md`|build/test/e2e/manual smoke|
|LMWR-457|✅ 编写 backend release checklist|`docs/plans/runbooks/llmwiki-slice-LMWR-456-459-wave15-release-privacy-rollback.md`|compileall/pytest/OpenAPI/system verification|
|LMWR-458|✅ 编写 privacy/security checklist|`docs/plans/runbooks/llmwiki-slice-LMWR-456-459-wave15-release-privacy-rollback.md`|外部路径、secret、source text、export|
|LMWR-459|✅ 编写 rollback checklist|`docs/plans/runbooks/llmwiki-slice-LMWR-456-459-wave15-release-privacy-rollback.md`|恢复 checkpoint + 恢复 wiki db/pages|
|LMWR-460|✅ 编写 user-facing usage guide draft|`docs/plans/runbooks/llmwiki-user-facing-usage-guide-draft.md`|说明 wiki-first/query-save/review/doctor|
|LMWR-461|✅ 更新 master plan 状态引用|`docs/plans/active/2026-04-27-full-project-build-master-plan.md`|只追加链接，不复制 240 项|
|LMWR-462|✅ 做一次端到端 dry-run 验收|`tools/eval/wiki_wave15_end_to_end_dry_run.py`、`tests/wiki/test_wave15_end_to_end.py`|source -> compile dry-run -> doctor -> query-save draft|
|LMWR-463|✅ 最终 gate：独立复核和证据包|`docs/plans/runbooks/llmwiki-slice-LMWR-463-wave15-final-gate.md`|证据路径、测试结果、残留风险写清|

### Wave 15 第一刀结果（2026-05-04 Codex）

- `LMWR-449`：新增 `docs/plans/specs/llmwiki-wave15-migration-maintenance-spec.md`，定义 evidence_refs -> wiki registry 的 no-write migration plan；迁移输入为 EvidenceReference-shaped JSONL 或包含 `evidence_refs` 的 JSONL 行。
- `LMWR-450`：新增 `literature_assistant/core/wiki/migration.py` 与 CLI `python -m literature_assistant wiki migration-dry-run --input <jsonl>`；输出 `would_write=false`、`candidates[]`、`skipped[]`、`already_registered_count`，不写 registry/page store。
- `LMWR-451`：新增 `literature_assistant/core/wiki/backup.py` 与 CLI `python -m literature_assistant wiki backup [--archive <zip>] [--write]`；默认 dry-run，仅显式 `--write` 才写本地 zip；SQLite 文件使用在线 backup API 快照后归档。
- `LMWR-452` ~ `LMWR-455`：在同一 Wave 15 spec 中固化 cleanup、human edit、multi-agent coordination、MCP/tool exposure plan；仅规划，不注册 MCP、不启用写入类 tool。
- 验证：`pytest tests/wiki/test_migration.py tests/wiki/test_backup.py tests/wiki/test_wiki_cli.py -q` → `13 passed`；`compileall literature_assistant/core/wiki literature_assistant/__main__.py tests/wiki/test_migration.py tests/wiki/test_backup.py tests/wiki/test_wiki_cli.py` PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-449-451-wave15-migration-backup.md`。
- 下一步：`LMWR-456` ~ `LMWR-459` release / privacy / rollback checklists，然后执行 `LMWR-462` 端到端 dry-run。

### Wave 15 第二刀结果（2026-05-04 Codex）

- `LMWR-456`：新增 frontend release checklist，要求 rollback + Vite production build 对标 + `npm run build` / `npm run test -- --run` / manual smoke。
- `LMWR-457`：新增 backend release checklist，要求 compileall、`tests/wiki`、collect-only、paths、system verification、wiki CLI smoke。
- `LMWR-458`：新增 privacy/security checklist，参考 OWASP Secrets/Logging，要求 secret scan、manifest 不含全文 source body、connector error sanitization。
- `LMWR-459`：新增 rollback checklist，明确代码 checkpoint restore 与 wiki artifact zip restore 分离，恢复动作必须用户显式要求。
- 验证：`pytest tests/wiki -q` → `297 passed`；compileall PASS；`run_literature_assistant.py paths` PASS；`system_verification.py --json` → `23 passed / 0 failed / 0 warnings`；`wiki backup` dry-run JSON PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-456-459-wave15-release-privacy-rollback.md`。
- 下一步：`LMWR-460` 用户使用指南草稿、`LMWR-461` master plan 状态引用、`LMWR-462` 端到端 dry-run。

### Wave 15 第三刀结果（2026-05-04 Codex）

- `LMWR-460`：新增 `docs/plans/runbooks/llmwiki-user-facing-usage-guide-draft.md`，覆盖 rollback + 成熟方案搜索、status/doctor、migration dry-run、backup、query-save/review/doctor 安全顺序、禁止事项与恢复命令。
- `LMWR-461`：在 `docs/plans/active/2026-04-27-full-project-build-master-plan.md` 追加 LLM-Wiki/RAG 集成计划状态引用，不复制本计划几百项任务。
- 下一步：`LMWR-462` 端到端 dry-run 验收与 `LMWR-463` final gate。

### Wave 15 第四刀结果（2026-05-04 Codex）

- `LMWR-462`：新增 `tools/eval/wiki_wave15_end_to_end_dry_run.py`，在临时目录执行 source registry -> compile dry-run -> 临时 compile write -> query index -> query search -> exploration draft save -> doctor -> backup plan，全程不写真实 runtime artifacts。
- 新增 `tests/wiki/test_wave15_end_to_end.py`，确认 migration `would_write=false`、query 命中、exploration draft 成功、doctor `error=0`、backup plan `would_write=false` 且选中文件。
- 顺手修复 `wiki/query.py`：`build_wiki_index()` rebuild 前清空 FTS 表，避免 deleted/stale pages 留在 query index；`tests/wiki/test_query.py` 增加回归。
- 验证：`pytest tests/wiki/test_wave15_end_to_end.py tests/wiki/test_query.py tests/wiki/test_migration.py tests/wiki/test_backup.py tests/wiki/test_wiki_cli.py -q` → `38 passed`；E2E dry-run script PASS；compileall PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-462-wave15-e2e-dry-run.md`。
- 下一步：`LMWR-463` final gate。

### Wave 15 收口结果（2026-05-04 Codex）

- `LMWR-463`：新增 `docs/plans/runbooks/llmwiki-slice-LMWR-463-wave15-final-gate.md`，汇总 Wave 15 证据路径、验证结果、残留风险、回滚点和 stop conditions。
- 最终验证：
  - `pytest tests/wiki -q` → `299 passed`
  - `compileall literature_assistant/core/wiki literature_assistant/__main__.py tools/eval tests/wiki docs/plans` PASS
  - `pytest tests --collect-only -q` → `1630 tests collected`
  - `run_literature_assistant.py paths` PASS
  - `system_verification.py --json` → `23 passed / 0 failed / 0 warnings`
  - `tools/eval/wiki_wave15_end_to_end_dry_run.py --pretty` PASS
- Wave 15 planned tasks `LMWR-449` ~ `LMWR-463` 已收口；补充任务 `LMWR-464` 起仍可继续长跑。

### Wave 15 补充任务

|ID|任务|主要落点|验收|
|---|---|---|---|
|LMWR-464|✅ 修复剩余测试失败|`gateb_phase_b_pool_export.py`、`literature_assistant/core/gateb_phase_b_pool_export.py`、`scripts/validate_contextual_miss.py`、`tests/legacy_root/test_gateb_c6_repro.py`、`tests/test_validate_contextual_miss.py`|`pytest tests -q` → 1632 passed, 3 skipped|
|LMWR-465|✅ 补充 TOLF 设计文档|`docs/plans/specs/tolf-wiki-integration.md`、`docs/plans/runbooks/llmwiki-slice-LMWR-465-tolf-wiki-boundary.md`|明确 TOLF 与 Wiki 的边界和集成点|
|LMWR-466|✅ 补充前端 E2E 测试框架|`frontend/tests/e2e/`|复用现有 Playwright；浏览器仅作独立窗口终态前的最小工作流验收|
|LMWR-467|✅ 补充外部知识库写回设计|`docs/plans/specs/external-knowledge-writeback-policy.md`、`docs/plans/runbooks/llmwiki-slice-LMWR-467-external-writeback-policy.md`|明确写回触发条件、边界、回滚机制|
|LMWR-468|✅ 实现 Wiki 编译成本预估|`wiki/compiler.py`、`routers/wiki_router.py`、`frontend/src/components/wiki/WikiCompileDryRunPanel.tsx`|dry-run 显示预估 token 和成本|
|LMWR-469|✅ 补充 longrun 模式使用指南|`docs/plans/runbooks/longrun-local-supervisor.md`、`docs/plans/runbooks/llmwiki-slice-LMWR-469-longrun-mode-guide.md`|启动条件、停止条件、监督策略|
|LMWR-470|✅ 重新评估分块参数 200/8|`tools/eval/wiki_lmwr470_chunk_param_review.py`、`tests/wiki/test_lmwr470_chunk_param_review.py`、`workspace_artifacts/evaluations/lmwr-470-chunk-param-review-20260505.json`|只读复盘确认 200/8 不提升，150/5 继续默认，下一 gate 为 cache/corpus 对齐后重跑 canary30 control|
|LMWR-471|✅ 补充 Wiki 性能基线|`tools/eval/wiki_wave14_performance_baseline.py`、`tests/wiki/test_performance_baseline.py`、`docs/plans/runbooks/llmwiki-slice-LMWR-471-performance-baseline.md`|compile/query/doctor 延迟和吞吐量|
|LMWR-472|✅ 补充 Wiki 安全审计|`docs/plans/specs/`、`literature_assistant/core/routers/wiki_router.py`、`literature_assistant/core/wiki/backup.py`|路径遍历、输入校验、路径脱敏、只读/备份边界|
|LMWR-473|✅ 补充 Wiki 可观测性|`wiki/`|日志、指标、追踪的统一接口|

## 推荐优先级

### 图片决策执行包（2026-05-03 固化）

- 决策 P-IMG-01（参考源约束）
  - 参数与模型策略优先参考：`github/` 内 RAG 参考库 + `C:\Users\xiao\Downloads\llmwiki借鉴库` + 官方上游文档。
  - 仅“借鉴设计与参数语义”，不复制外部实现，不改外部仓库。
- 决策 P-IMG-02（执行顺序）
  - 当前批次严格按图片给定顺序推进：`B -> C -> D -> A`（保持原标签命名，不在本计划内重命名）。
- 决策 P-IMG-03（失败处置）
  - 先记录失败（含测试名/报错/归因/证据路径），再进入修复。
  - 修复策略：先简单项（低风险、低耦合、可快速回归），后复杂项（跨模块、需架构变更或新增 gate）。
  - 每个修复切片必须带 focused 回归结果，不允许“只改不验”。

### P0：必须先做

- Wave 0：治理和回档模板。
- Wave 1：数据模型。
- Wave 2：source/chunk registry。
- Wave 4：citation validator。
- Wave 5：evidence_refs 映射。
- Wave 6：compiler dry-run 和最小 markdown 写入。

### P1：有 P0 后再做

- Wave 8：wiki-aware retrieval。
- Wave 10：doctor/review queue。
- Wave 11：API contract。
- Wave 14：评测和质量门禁。

### P2：可延后

- Wave 3：page store（可先用临时目录）。
- Wave 7：LLM 生成（可先用 stub 模式）。
- Wave 9：graph（可先用简单 dict）。
- Wave 12：前端工作台（可先用 API 测试）。
- Wave 13：外部 connector（可先用本地文件）。

### P3：长期优化

- Wave 15：迁移、发布门禁、长期维护。
- LMWR-464 ~ LMWR-473：补充任务已收口；后续进入发布准备和 post-cache retrieval gate。

## 执行节奏建议

### 第一阶段（已完成）：基础设施
- ✅ Wave 0-7：数据模型、注册表、页面存储、引用验证、证据适配、编译器、LLM 网关（stub）
- ✅ Wave 8-10：检索集成、图谱、Doctor/Review
- ✅ Wave 11：API contract
- ✅ Wave 12：前端工作台
- ✅ Wave 13：外部 connector
- ✅ Wave 14：评测和质量门禁

### 第二阶段（当前）：漏洞修复与补充
- ✅ LMWR-464：修复剩余测试失败
- ✅ LMWR-465：补充 TOLF 设计文档
- ✅ LMWR-466：补充前端 E2E 测试框架
- ✅ LMWR-467：补充外部知识库写回设计
- ✅ LMWR-468：实现 Wiki 编译成本预估
- ✅ LMWR-469：补充 longrun 模式使用指南
- ✅ LMWR-470：重新评估分块参数 200/8（已生成只读复盘 artifact；不改常量、不改 qrels/goldset/canary30）
- ✅ LMWR-471：补充 Wiki 性能基线
- ✅ LMWR-472：补充 Wiki 安全审计（本地轻量门禁）
- ✅ LMWR-473：补充 Wiki 可观测性（本地 JSONL 事件/指标/span，默认无网络导出）

### 第三阶段（待启动）：发布准备 / post-cache retrieval gate
- ⏸️ LMWR-449 ~ LMWR-463：迁移、发布门禁、长期维护
- ✅ Post-LMWR-470 cache/corpus preflight：已新增 `tools/eval/wiki_cache_corpus_preflight.py` 与 artifact `workspace_artifacts/evaluations/post-lmwr-470-cache-corpus-preflight-laser-welding-109-20260505.json`；当前 `laser_welding_109` v2 chunk-store 与 canonical/legacy manifests 均未对齐，FAIL 前不提升 200/8。
- ✅ Post-LMWR-470 canary corpus source locator/root hygiene：已新增 `tools/eval/wiki_canary_corpus_source_locator.py` 与 artifact `workspace_artifacts/evaluations/post-lmwr-470-canary-corpus-source-locator-20260505.json`；`eval_retrieval_runtime` 默认 root 为 `output/chunk_store`，该路径是指向 `workspace_artifacts/generated/output/chunk_store` 的 junction。初始聚合 root 为 `11471` chunks/hash `76f661a741bbc5b7cc69dfab34b3cdd99cba8744691111403874b9fee162bc6a`；定位到 1-chunk 测试残留 `proj_f9adfb165de1`，备份到 `workspace_artifacts/backups/post-lmwr-470-root-hygiene-20260505/` 后清理，当前 runtime corpus 为 `11470` chunks/hash `58c76986fdfa125d9e690ad00dfa990b72b2a6b41a564405280d8613a012ddf0`，已匹配 canonical contextual manifest。
- ⏸️ Post-LMWR-470 next：cache/corpus gate 已 PASS；继续 rerun canary30 no-rerank/raw/default control，可使用现有 env / provider 配置；仍不修改 `.env`、不打印密钥、不自动提升 200/8、不改 qrels/goldset/canary30。

## 风险与缓解

### 风险 1：测试失败未完全修复
**影响**：可能影响后续 Wave 的稳定性。
**缓解**：LMWR-464 已收口；`pytest tests -q` → `1632 passed, 3 skipped`，证据见 `docs/plans/runbooks/llmwiki-slice-LMWR-464-test-failure-closeout.md`。

### 风险 2：TOLF 功能与 Wiki 脱节
**影响**：可能重复实现类似能力，或集成困难。
**缓解**：补充 TOLF 设计文档，明确与 Wiki 的边界和集成点。

### 风险 3：前端 UI 测试覆盖不足
**影响**：前端改动可能引入未被发现的回归。
**缓解**：补充前端 E2E 测试框架和最小测试集。

### 风险 4：外部知识库写回策略未明确
**影响**：后续如需写回功能，可能需要大幅重构 connector 接口。
**缓解**：已补充 `docs/plans/specs/external-knowledge-writeback-policy.md`，明确当前默认不写回；未来 direct write 必须另开任务、先 dry-run diff、备份/导出、operation journal，并由用户显式确认。

### 风险 5：Wiki 编译成本控制缺失实际测试
**影响**：用户可能在不知情的情况下触发大量 LLM 调用，导致高额费用。
**缓解**：实现 compile cost guard，并在 dry-run 中显示预估成本。

### 风险 6：分块参数回滚未记录根因
**影响**：后续优化可能重复踩坑。
**缓解**：记录 canary30 回归的具体指标和回滚决策依据。

### 风险 7：longrun 模式与主计划脱节
**影响**：longrun 模式可能与主计划的 Wave 推进节奏冲突。
**缓解**：已补充 `docs/plans/runbooks/longrun-local-supervisor.md` 和 `docs/plans/runbooks/llmwiki-slice-LMWR-469-longrun-mode-guide.md`，明确启动 envelope、停止条件、监督策略、命令模板和验证梯度。

### 风险 8：Wiki 性能未基线化
**影响**：无法评估优化效果，或发现性能回归。
**缓解**：已扩展 `tools/eval/wiki_wave14_performance_baseline.py`，输出 compile/index/query/doctor/total 的 P50/P95/P99 与 throughput；证据见 `docs/plans/runbooks/llmwiki-slice-LMWR-471-performance-baseline.md`。

### 风险 9：Wiki 安全审计缺失
**影响**：可能存在路径遍历、注入、权限提升等安全风险。
**缓解**：已补充 Wiki 安全门禁、focused tests 和执行记录，覆盖路径越界、输入校验、路径脱敏、backup allowed-root 边界。

### 风险 10：Wiki 可观测性不足
**影响**：生产环境问题难以定位和排查。
**缓解**：补充 Wiki 可观测性（日志、指标、追踪的统一接口）。

### P2：产品化与扩展

- Wave 9：graph。
- Wave 12：前端 Wiki 工作台。
- Wave 13：Zotero/EndNote/Obsidian 只读 connector。
- Wave 15：迁移、MCP、长期维护。

## 最小可交付闭环

最小闭环不需要 240 项全部完成。第一个可用版本建议只做到：

1. 稳定 source/chunk registry。
2. 从现有 `RAGResult.evidence_refs` 生成 `synthesis` draft。
3. citation validator 能拒绝无引用 final。
4. page store 能写 `workspace_artifacts/generated/wiki/`。
5. doctor 能报告 broken citation / stale index。
6. API 能返回 disabled/status/dry-run。

对应任务范围：`LMWR-224` 到 `LMWR-328`，再加 `LMWR-374` 到 `LMWR-388` 的最小 doctor。

## 计划漏洞与补充

### 漏洞 1：Wave 15 迁移与发布门禁缺失具体任务分解

**问题**：Wave 15 只有高层描述，缺少可执行的任务 ID 和验收标准。
**影响**：无法按现有 Wave 1-14 的节奏推进，容易遗漏关键步骤。
**补充**：见下方 Wave 15 任务分解。

### 漏洞 2：测试失败修复状态与计划不同步

**问题**：
- `legacy-test-triage-20260503.md` 显示从 59 降至 22 失败，再降至约 4-6 个。
- 但主计划未记录这些修复的具体 commit、覆盖范围、剩余风险。
- P0 Contextual Chunker / Reranker / legacy_root 已修复，但计划未更新状态。

**影响**：后续 Wave 可能重复修复或遗漏残留失败。
**补充**：
- ✅ P0 Contextual Chunker (2)：已修复（commit ed386e4f）
- ✅ P0 Reranker (3)：实际未失败（exit code 49 是 squad guard 误报）
- ✅ P1 legacy_root (9)：已修复（commit 24d5ba6f）
- ✅ P2 Precompute/Migration (4)：已修复（commit 672a73ac）
- ✅ 剩余失败已收口：legacy C6 reproducibility 与 contextual miss validation 已修复。
- **当前门禁**：`pytest tests -q` → `1632 passed, 3 skipped`。
- **证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-464-test-failure-closeout.md`。

### 漏洞 3：分块参数调整未记录回滚触发条件

**问题**：
- `chunk-strategy-review-20260503.md` 显示 CHUNK_OVERLAP 从 150 增至 200，MAX_CHUNKS_PER_MATERIAL 从 5 增至 8。
- 但最新 commit `b8839cc5` 显示"revert to 150/5 due to canary30 regression"。
- 计划未记录：(1) canary30 回归的具体指标；(2) 回滚决策依据；(3) 下一步优化方向。

**影响**：后续优化可能重复踩坑，或不知道何时重新尝试 200/8 配置。
**补充**：
- **历史误判修正**：初始报告显示 200/8 run 相对 2026-04-27 aligned baseline Recall@5 从 `0.6667` 降至 `0.5`、MRR 从 `0.6667` 降至 `0.3181`；但随后 150/5 revert run 得到完全相同 Recall/MRR，因此参数因果未证明。
- **当前配置**：CHUNK_OVERLAP=150，MAX_CHUNKS_PER_MATERIAL=5（已回滚）。
- **cache evidence**：旧 embedding manifest `11445` / `11436` chunks，对比当前 corpus `11457` chunks，stale cache/corpus state 是更强解释。
- **本轮结论**：`workspace_artifacts/evaluations/lmwr-470-chunk-param-review-20260505.json` 已固化不提升 200/8、不改 qrels/goldset/canary30。
- **Post-gate 工具**：`tools/eval/wiki_cache_corpus_preflight.py` 已能只读对比 corpus/chunk-store 与 embedding manifest；`laser_welding_109` 当前预检 FAIL（corpus `7225` chunks/hash 不匹配 canonical `11470` 或 legacy `11457` manifests）。
- **下一步**：先定位 canary30 control 的真实 corpus source，并让 cache/corpus preflight PASS；之后才允许重跑 aligned canary30 no-rerank/raw/default control 和重新比较 200/8。

### 漏洞 4：TOLF 相关功能未纳入主计划

**问题**：
- 最新 5 个 commit 全部是 TOLF 相关（judgment summary、template export、review packet、inspection packet、bilingual control、query bridge diagnostics）。
- 但主计划未提及 TOLF 功能的设计目标、验收标准、与 Wiki 的集成点。

**影响**：TOLF 功能可能与 Wiki 系统脱节，或重复实现类似能力。
**补充**：
- **TOLF 定位**：已明确为 default-off 候选上下文选择与诊断臂，不是 Wiki 编译器，也不是默认链替代。
- **集成点**：TOLF 输出只能通过 provenance-bearing `evidence_refs` / `context_metadata` 进入 migration dry-run 或 `save_exploration()` draft；不得直接写 page store final 或 query index；qrels/goldset/canary30 只能按最新授权补充先备份、后对照、再演进。
- **验收**：保留 raw default / bilingual default / TOLF 三臂对照、inspection、review Markdown、judgment JSONL 和 summary；任何默认链切换需另建 gate。
- **证据**：`docs/plans/specs/tolf-wiki-integration.md`、`docs/plans/runbooks/llmwiki-slice-LMWR-465-tolf-wiki-boundary.md`。

### 漏洞 5：前端 UI 测试覆盖不足

**问题**：
- Wave 12 前端工作台已收口，但只有 54 个 Vitest 测试。
- 缺少端到端测试（E2E）、浏览器兼容性测试、性能测试。
- 缺少 UI 回归测试的自动化流程。

**影响**：前端改动可能引入未被发现的回归。
**补充**：
- **当前覆盖**：54 个 Vitest 单元测试 + 浏览器 smoke 测试。
- **缺失**：Wiki 关键工作流 E2E；视觉回归和完整浏览器响应式适配不作为当前测试期目标。
- **现状**：LMWR-466 已复用现有 Playwright 补齐 Wiki Workbench 最小 E2E；浏览器仍仅作为独立窗口终态前的开发期验收面。

### Wave 15 Supplement / LMWR-466（2026-05-04 Codex）

- 已新增 `frontend/tests/e2e/wiki-workbench.spec.ts`，覆盖 `/wiki` sidebar route、`?page=` deep link preview、page list select、compile dry-run、doctor/review/graph 只读治理面。
- 已修复 `frontend/tests/e2e/mockApi.ts` 中 `**/api/**` catch-all 抢占 Wiki mock 的问题：对 `/api/wiki/`、`/api/budget`、`/api/chat` 使用 `route.fallback()`，避免专用 mock 被兜底 handler 吃掉。
- 聚焦验证：`npm run test:e2e -- tests/e2e/wiki-workbench.spec.ts --reporter=line` → `5 passed`；`npm run test -- --run src/services/wikiApi.test.ts` → `11 passed`；`npm run build` → PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-466-frontend-e2e.md`。

### 漏洞 6：外部知识库写回策略未明确

**问题**：
- Wave 13 connector 设计为只读，但未明确：
  - 何时启用写回（如果需要）？
  - 写回的安全边界和用户授权流程？
  - 写回失败的回滚机制？

**影响**：后续如需写回功能，可能需要大幅重构 connector 接口。
**补充**：
- **当前决策**：Wave 13 只读优先，LMWR-467 已明确当前默认不做写回；外部 Zotero/EndNote/Obsidian 仍保持 `read_only=true` / `writes_user_library=false` / `would_write=false`。
- **写回触发条件**：只能由用户显式指定目标、字段、范围和回滚计划；必须先读取官方写 API、生成 dry-run diff、验证 backup/export 和 operation journal。
- **写回边界**：未来如另行批准，第一阶段只允许低风险 metadata；禁止删除/重命名/覆盖外部资料、直接写 Zotero SQLite、直接改 EndNote `.enl/.Data`、静默改 Obsidian vault。
- **证据**：`docs/plans/specs/external-knowledge-writeback-policy.md`、`docs/plans/runbooks/llmwiki-slice-LMWR-467-external-writeback-policy.md`。

### 漏洞 7：Wiki 编译成本控制缺失实际测试

**问题**：
- Wave 14 `LMWR-439` 已实现 compile budget hard guard，但 active plan 未同步 dry-run 可见的 token/cost estimate。
- 实际 LLM 调用仍为 stub/default-off，不能把估算误写成真实账单。

**影响**：用户可能在不知情的情况下触发大量 LLM 调用，导致高额费用。
**补充**：
- **当前状态**：已新增 `CompilePricing` / `CompileCostEstimate`，`CompileResult`、`/api/wiki/compile` 和前端 Dry-run console 均显示 token/cost estimate。
- **价格边界**：不硬编码任何线上模型价格；默认 `pricing_configured=false`、`estimated_cost_usd=0.0`，真实费率必须按当日官方 pricing 或 provider config 显式传入。
- **验收**：compiler/router focused pytest、frontend wikiApi test、frontend build、OpenAPI regenerate、Wave15 E2E focused group 已通过。
- **证据**：`docs/plans/runbooks/llmwiki-slice-LMWR-468-compile-cost-estimate.md`。

### 漏洞 8：长跑监督脚本与主计划脱节

**问题**：
- `llmwiki-execution-decisions.md` 提到 longrun supervisor 脚本，但主计划未提及。
- 缺少 longrun 模式的启动条件、停止条件、监督策略。

**影响**：longrun 模式可能与主计划的 Wave 推进节奏冲突。
**补充**：
- **longrun 边界**：只能继续当前 LLM-Wiki/RAG 长跑计划，不能自动启用外部写回、auto-finalize、大重构。
- **停止条件**：存在 `workspace_artifacts/runtime_state/longrun-supervisor/STOP` 或交互标记。
- **当前状态**：已完成 LMWR-469；长跑指南和 worker prompt 已强制包含回档、成熟方案搜索、focused verification 和 handoff 记录。
- **证据**：`docs/plans/runbooks/longrun-local-supervisor.md`、`docs/plans/runbooks/llmwiki-slice-LMWR-469-longrun-mode-guide.md`。

### Wave 15 Supplement / LMWR-469 执行结果（2026-05-04 Codex）

- 已更新 `docs/plans/runbooks/longrun-local-supervisor.md`，补充 LMWR-469 scope、成熟方案对标、启动 envelope、任务选择、命令模板、验证梯度和 handoff 记录。
- 已新增 `docs/plans/runbooks/llmwiki-slice-LMWR-469-longrun-mode-guide.md`，记录 checkpoint、成熟方案、Longrun SOP、验证和后续边界。
- 已更新 `tools/longrun/longrun-prompt.md`，要求 scheduled worker 读取 longrun SOP，并把“回档 + 成熟方案搜索”写入所有给用户或其他 agent 的执行指令。
- 成熟方案：OpenAI Codex `AGENTS.md` / non-interactive mode、Microsoft ScheduledTasks、Git worktree。

### Wave 15 Supplement / 用户授权补充（2026-05-04）

- 已新增 `docs/plans/active/llmwiki-autonomy-authorization.md`，固化用户对剩余计划的一次性授权。
- 产品界面：终态为独立窗口；浏览器仅用于开发期预览和最小 E2E，不要求测试页面做完整产品化适配。
- 评测：qrels/goldset/canary30 允许在 checkpoint、备份、版本化、对照指标和恢复路径齐全后自决策修改；默认优先新增查询集做对比。
- 安全：LMWR-472 定义为本地轻量安全审计，覆盖路径越界、输入校验、只读权限、日志脱敏和 RAG/LLM evidence 边界，不做外部攻击扫描。
- 联网：程序本体除 AI provider 外默认不联网；AI 可联网搜索背景/成熟方案，但正式回答必须基于本地知识库和 evidence_refs，网络结果不能静默成为知识库证据。
- 删除/修改：允许备份后删除或修改项目内目标；外部系统、远程历史、账号、凭据、付费或无法证明可恢复的操作仍需停下。

### Wave 15 Supplement / LMWR-472（2026-05-05 Codex）

- `wiki_router.py` 已新增三类本地安全门禁：filter token 校验、identifier/page_path 校验、review 非法筛选值 400 化。
- `/api/wiki/status` 不再向前端回传真实绝对路径；repo 内路径显示为相对路径，repo 外路径脱敏为 `<external>/<name>`。
- `wiki/backup.py` 现在只收集仍位于声明 allowed root 内的真实文件；越界文件报告为 `outside_allowed_root`，不进入 zip。
- focused 验证：`pytest tests/wiki/test_wiki_router.py tests/wiki/test_backup.py -q` → `19 passed, 1 skipped`；`compileall` PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-472-security-audit.md`。

### Wave 15 Supplement / LMWR-473（2026-05-05 Codex）

- `wiki/observability.py` 已新增本地 `WikiObservabilitySink`，统一事件、指标、span 三类 JSONL 输出，默认无网络 exporter。
- `project_paths.py` 新增 `wiki_observability_path()`，观测产物统一落在 `workspace_artifacts/runtime_state/wiki/observability/`。
- `WikiQueryIndex`、`WikiCompiler`、`WikiDoctor` 已支持可注入 observability sink；不传 sink 时保持原有离线/测试路径无观测写入。
- 观测 payload 对 query/prompt/answer/text/path/api_key/token 等敏感字段做 hash + length + reason 脱敏，不写原始 query、私有路径、正文或密钥。
- focused 验证：`pytest tests/wiki/test_observability.py tests/wiki/test_query.py tests/wiki/test_compiler.py tests/wiki/test_doctor.py -q` → `61 passed`；`compileall` PASS。
- 证据 runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-473-observability.md`。

## Copilot/Agent 单任务指令模板

```text
任务：执行 LMWR-<ID>：<任务名>。

必须先做：
1. 创建回档：
   py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-<ID>-<slug>"
2. 搜索/读取成熟方案：
   - 优先读本文列出的本地参考库对应文件。
   - 如涉及架构或库选择，再搜索官方/上游项目文档。
3. 只改本任务范围内文件，不碰 `github/` 和下载参考库。
4. 实现后运行 focused tests 和 compileall。
5. 把执行证据写回 docs/plans 或 .squad/decisions/inbox。

验收：<复制本任务验收列>。
```

## 回滚说明

不得自动恢复回档。只有用户明确要求”回滚/恢复/撤销本次改动”时，才执行：

```powershell
py “$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py” list --workspace “C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script”
py “$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py” restore --workspace “C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script” --checkpoint “<checkpoint-id>” --confirm-restore
```

## 计划与实现对齐审计（2026-05-05）

### 已修复的对齐问题

| # | 问题 | 修复 |
|---|------|------|
| 1 | 目录布局列出 `chunk_registry.py`、`frontmatter.py`，但实际已合并入 `source_registry.py`、`page_store.py` | 更新目录布局，标注合并关系 |
| 2 | TOLF 集成设计标注”待补充”，但 LMWR-465 已创建 | 更新为”✅ 已补充” |
| 3 | 蓝图 J 测试文件名与实际不一致（`test_models.py` → `test_wiki_models.py` 等） | 更新为实际文件名，补全所有 24 个测试文件 |
| 4 | 六层边界映射 Layer 3 引用不存在的 `chunk_registry.py` | 更新为 `source_registry.py（含 source + chunk registry）` |
| 5 | LMWR-260~265 落点列为 `wiki/chunk_registry.py` | 更新为 `wiki/source_registry.py` 并标注”已合并” |
| 6 | LMWR-271~272 落点列为 `wiki/frontmatter.py` | 更新为 `wiki/page_store.py` 并标注”已合并” |
| 7 | LMWR-249 落点列为 `wiki/schema.py` | 更新为 `wiki/models.py` 并标注”已合并” |
| 8 | LMWR-345 落点列为 `wiki/query.py 或 wiki/index.py` | 更新为 `wiki/query.py` 并标注”已合并” |
| 9 | Wave 14 DoD 测试数 287 与实际 342 不符 | 更新为实际 342 |

### 待修复/关注的残留问题

| # | 问题 | 状态 | 影响 | 建议 |
|---|------|------|------|------|
| 1 | `prompt_templates/wiki_*.txt` 未创建（LMWR-333~336） | ⏸️ | LLM 生成仍为 stub 模式，prompt 模板缺失 | 启用真实 LLM 调用前必须补齐 |
| 2 | Wave 9 graph 测试仅 7 个 vs DoD 目标 54 个 | ⏸️ | graph 功能测试覆盖偏低 | 后续补充 graph edge cases |
| 3 | Wave 10 doctor+review 测试仅 16 个 vs DoD 目标 69 个 | ⏸️ | doctor/review 功能测试覆盖偏低 | 后续补充 doctor repair/review lifecycle |
| 4 | Wave 8 query 测试实际 39 个 vs DoD 目标 47 个 | ⏸️ | query 功能测试覆盖偏低 | 后续补充 fallback/linked expansion |
| 5 | Post-LMWR-470 eval 工具未被任务编号覆盖 | ⚠️ | `wiki_cache_corpus_preflight.py`、`wiki_canary_corpus_source_locator.py`、`wiki_lmwr470_chunk_param_review.py` 在 `tools/eval/` 但无 LMWR 编号 | 已记录在第三阶段，不分配新编号 |
| 6 | `wiki/page_store.py` 中 `frontmatter.py` 功能是否完整合并 | ✅ | 已验证：`page_store.py` 含 `render_frontmatter`、`stable_slug`、`render_page` | 无需额外操作 |
| 7 | `wiki/models.py` 中 `schema.py` 功能是否完整合并 | ✅ | 已验证：`models.py` 含 `require_non_empty`、类型校验、`__post_init__` | 无需额外操作 |

### 实际文件与计划文件对照

| 计划文件 | 实际文件 | 状态 |
|----------|----------|------|
| `wiki/models.py` | `wiki/models.py` (11,155 bytes) | ✅ 一致 |
| `wiki/source_registry.py` | `wiki/source_registry.py` (8,786 bytes) | ✅ 一致 |
| `wiki/chunk_registry.py` | → 合并入 `wiki/source_registry.py` | ✅ 已更新计划 |
| `wiki/page_store.py` | `wiki/page_store.py` (4,359 bytes) | ✅ 一致 |
| `wiki/frontmatter.py` | → 合并入 `wiki/page_store.py` | ✅ 已更新计划 |
| `wiki/citation_validator.py` | `wiki/citation_validator.py` (5,927 bytes) | ✅ 一致 |
| `wiki/evidence_adapter.py` | `wiki/evidence_adapter.py` (6,943 bytes) | ✅ 一致 |
| `wiki/compiler.py` | `wiki/compiler.py` (20,858 bytes) | ✅ 一致 |
| `wiki/llm_gateway.py` | `wiki/llm_gateway.py` (2,988 bytes) | ✅ 一致 |
| `wiki/query.py` | `wiki/query.py` (22,461 bytes) | ✅ 一致 |
| `wiki/graph.py` | `wiki/graph.py` (30,132 bytes) | ✅ 一致 |
| `wiki/doctor.py` | `wiki/doctor.py` (22,466 bytes) | ✅ 一致 |
| `wiki/review_queue.py` | `wiki/review_queue.py` (9,836 bytes) | ✅ 一致 |
| `wiki/export.py` | `wiki/export.py` (1,015 bytes) | ✅ 计划外新增 |
| `wiki/evaluation.py` | `wiki/evaluation.py` (23,471 bytes) | ✅ 计划外新增 |
| `wiki/backup.py` | `wiki/backup.py` (10,218 bytes) | ✅ 计划外新增 |
| `wiki/migration.py` | `wiki/migration.py` (10,458 bytes) | ✅ 计划外新增 |
| `wiki/observability.py` | `wiki/observability.py` (19,491 bytes) | ✅ 计划外新增 |
| `wiki/connectors/` | `wiki/connectors/` (6 files) | ✅ 一致 |
| `routers/wiki_router.py` | `routers/wiki_router.py` | ✅ 一致 |
| `prompt_templates/wiki_*.txt` | 不存在 | ⏸️ 待实现 |
| `tools/eval/wiki_wave14_performance_baseline.py` | ✅ 存在 | ✅ 一致 |
| `tools/eval/wiki_wave15_end_to_end_dry_run.py` | ✅ 存在 | ✅ 计划外新增 |
| `tools/eval/wiki_cache_corpus_preflight.py` | ✅ 存在 | ✅ 计划外新增 |
| `tools/eval/wiki_canary_corpus_source_locator.py` | ✅ 存在 | ✅ 计划外新增 |
| `tools/eval/wiki_lmwr470_chunk_param_review.py` | ✅ 存在 | ✅ 计划外新增 |

## Post-LMWR-470 / canary30 goldset 漂移诊断补充（2026-05-05）

- 已创建回档：`20260505-022115-post-lmwr-470-goldset-drift-diagnostic-start`。
- 已新增 `tools/eval/wiki_canary_goldset_drift.py`，只读消费 canary query JSONL、已有 `rerank_trace.jsonl` 和 chunk-store，输出 gold rank、top hits、same-title alternate、top competitor 与 drift labels。
- 已新增 `tests/wiki/test_canary_goldset_drift.py`，覆盖 v2 chunk-store catalog、duplicate title groups、gold buried、same-title alternate、path escape guard 和 deterministic writer。
- 成熟方案：LlamaIndex Retriever Evaluation、Ragas Context Precision/Recall、LangChain Indexing/RecordManager；共同结论是 retrieval eval 必须显式记录 gold/reference、retrieved contexts/material identity 与排名，不应只看 aggregate metric。
- full-root artifact：`workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-drift-20260505.json`。
- laser109 artifact：`workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-drift-laser109-20260505.json`。
- no-write proposal artifacts：`workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-proposal-20260505.json` 与 `workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-proposal-laser109-20260505.json`。
- full-root 结果：30 条 top5 命中 `15`、miss `15`；其中 `10` 条 gold 在 trace window 内完全找不到，`5` 条 gold 被埋到 top5 后；duplicate title groups `29`，material/chunk `194/11470`。
- laser109 单项目对照：top5 命中 `13`、miss `17`；gold missing `10`、buried `7`；duplicate title groups `3`，material/chunk `108/7225`。
- proposal 结果：full-root `15` 个 action、laser109 `17` 个 action；simulated Recall@5 均可到 `1.0`，但仅是接受 trace top-k candidates 后的上界估算，不作为 release gate。
- 结论：当前 canary30 回归更像 goldset 过窄/陈旧和 material identity 漂移，不是 200/8 chunk 参数因果；下一步优先新增版本化 query/qrels/goldset 对照，旧 canary30 暂不直接覆盖。
- 验证：`pytest tests/wiki/test_canary_goldset_drift.py tests/wiki/test_cache_corpus_preflight.py tests/test_eval_runtime.py -q` → `51 passed`；compileall PASS。
- 证据 runbook：`docs/plans/runbooks/post-lmwr-470-cache-corpus-preflight.md` 第 8-9 节。

### 测试文件实际对照

| 测试文件 | 测试数 | 计划 DoD 目标 | 差异 |
|----------|--------|---------------|------|
| `test_wiki_models.py` | 23 | 23 | ✅ 达标 |
| `test_source_registry.py` | 27 | 27 | ✅ 达标 |
| `test_page_store.py` | 39 | 39 | ✅ 达标 |
| `test_citation_validator.py` | 35 | 35 | ✅ 达标 |
| `test_evidence_adapter.py` | 26 | 26 | ✅ 达标 |
| `test_compiler.py` | 16 | 10 | ✅ 超额 |
| `test_llm_gateway.py` | 15 | 15 | ✅ 达标 |
| `test_query.py` | 24 | 47 | ⚠️ 不足 |
| `test_query_save_exploration.py` | 15 | — | ✅ 计划外新增 |
| `test_graph.py` | 7 | 54 | ⚠️ 不足 |
| `test_doctor.py` | 9 | 69 | ⚠️ 不足 |
| `test_review_queue.py` | 7 | — | ⚠️ 不足 |
| `test_wiki_router.py` | 16 | 15 | ✅ 达标 |
| `test_evaluation.py` | 11 | 11 | ✅ 达标 |
| `test_connectors.py` | 10 | 10 | ✅ 达标 |
| `test_backup.py` | 4 | — | ✅ 计划外新增 |
| `test_migration.py` | 5 | — | ✅ 计划外新增 |
| `test_wiki_cli.py` | 5 | — | ✅ 计划外新增 |
| `test_observability.py` | 12 | — | ✅ 计划外新增 |
| `test_cache_corpus_preflight.py` | 16 | — | ✅ 计划外新增 |
| `test_expansion_optimizations.py` | 12 | — | ✅ 计划外新增 |
| `test_lmwr470_chunk_param_review.py` | 5 | — | ✅ 计划外新增 |
| `test_performance_baseline.py` | 2 | — | ✅ 计划外新增 |
| `test_wave15_end_to_end.py` | 1 | — | ✅ 计划外新增 |
| **合计** | **342** | — | — |
