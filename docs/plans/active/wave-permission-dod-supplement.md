# Wave 任务权限与 DoD 补充

## 使用说明

本文档为主执行计划的补充，为每个 Wave 添加权限层级和标准化 DoD。

---

## Wave 0：治理、回档、调研固化

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave0-governance-start`

**标准化 DoD**：
- 主产物落盘：文档已写入 `docs/plans/runbooks/` 或 `docs/plans/specs/`
- 状态同步：更新主计划
- 门禁通过：文档可读、模板可复用
- 环境收尾：无临时文件

---

## Wave 1：数据模型与 schema

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave1-data-model-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/models.py` 已创建
- 状态同步：更新主计划、更新 Wave 1 runbook
- 门禁通过：
  - `pytest tests/wiki/test_models.py -q` 通过（23 tests）
  - `compileall literature_assistant/core/wiki/models.py` 通过
- 环境收尾：无临时文件

---

## Wave 2：source registry 与 stable chunk registry

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave2-registry-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/source_registry.py` 已创建（含 source + chunk registry）
- 状态同步：更新主计划、更新 Wave 2 runbook
- 门禁通过：
  - `pytest tests/wiki/test_source_registry.py -q` 通过（27 tests）
  - `compileall literature_assistant/core/wiki` 通过
- 环境收尾：无 stale registry lock

---

## Wave 3：Markdown/frontmatter page store

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave3-page-store-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/page_store.py` 已创建
- 状态同步：更新主计划、更新 Wave 3 runbook
- 门禁通过：
  - `pytest tests/wiki/test_page_store.py -q` 通过（39 tests）
  - `compileall literature_assistant/core/wiki` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
- 环境收尾：无 orphan wiki pages in tmp

---

## Wave 4：citation validator 与 finalize gate

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave4-citation-validator-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/citation_validator.py` 已创建
- 状态同步：更新主计划、更新 Wave 4 runbook
- 门禁通过：
  - `pytest tests/wiki/test_citation_validator.py -q` 通过（35 tests）
  - `compileall literature_assistant/core/wiki` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
- 环境收尾：无临时文件

---

## Wave 5：RAG evidence_refs 到 wiki evidence 映射

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave5-evidence-adapter-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/evidence_adapter.py` 已创建
- 状态同步：更新主计划、更新 Wave 5 runbook
- 门禁通过：
  - `pytest tests/wiki/test_evidence_adapter.py -q` 通过（26 tests）
  - `compileall literature_assistant/core/wiki` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
- 环境收尾：无临时文件

---

## Wave 6：wiki 编译器最小闭环

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：单次跑超过 30 分钟（需成本预估）
**回档点**：`wave6-compiler-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/compiler.py` 已创建
- 状态同步：更新主计划、更新 Wave 6 runbook
- 门禁通过：
  - `pytest tests/wiki/test_compiler.py -q` 通过（10 tests）
  - `compileall literature_assistant/core/wiki` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
- 环境收尾：无 orphan compile artifacts

---

## Wave 7：LLM 生成接入与 prompt 治理

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：替换主 LLM（需成本预估）
**回档点**：`wave7-llm-gateway-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/llm_gateway.py`, `prompt_templates/wiki_*.txt` 已创建
- 状态同步：更新主计划、更新 Wave 7 runbook
- 门禁通过：
  - `pytest tests/wiki/test_llm_gateway.py -q` 通过（15 tests, stub mode）
  - `compileall literature_assistant/core/wiki` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
  - 成本预估：dry-run 显示预估 token 和成本
- 环境收尾：无未解释 API 调用

---

## Wave 8：wiki-aware retrieval 与 query pipeline

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：修改评测口径、修改 qrels
**回档点**：`wave8-wiki-retrieval-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/query.py` 已创建
- 状态同步：更新主计划、更新 Wave 8 runbook
- 门禁通过：
  - `pytest tests/wiki/test_query.py -q` 通过（47 tests）
  - `compileall literature_assistant/core/wiki` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
  - 评测对照：wiki vs raw retrieval comparison（zero-cost）
- 环境收尾：无 stale index

---

## Wave 9：graph 与 typed relations

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave9-graph-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/graph.py` 已创建
- 状态同步：更新主计划、更新 Wave 9 runbook
- 门禁通过：
  - `pytest tests/wiki/test_graph.py -q` 通过（54 tests）
  - `compileall literature_assistant/core/wiki` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
- 环境收尾：无 stale graph.db lock

---

## Wave 10：doctor、review queue、治理面

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave10-doctor-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/doctor.py`, `review_queue.py` 已创建
- 状态同步：更新主计划、更新 Wave 10 runbook
- 门禁通过：
  - `pytest tests/wiki/test_doctor.py tests/wiki/test_review_queue.py -q` 通过（69 tests）
  - `compileall literature_assistant/core/wiki` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
- 环境收尾：无 stale review queue lock

---

## Wave 11：API contract 与 CLI/服务入口

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave11-api-contract-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/routers/wiki_router.py` 已创建
- 状态同步：更新主计划、更新 Wave 11 runbook、更新 OpenAPI spec
- 门禁通过：
  - `pytest tests/wiki/test_wiki_router.py -q` 通过（15 tests）
  - `compileall literature_assistant/core/routers` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
  - OpenAPI 生成：`npm --prefix frontend run generate:openapi` 成功
- 环境收尾：无 stale API server

---

## Wave 12：前端 Wiki 工作台最小产品面

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：无
**回档点**：`wave12-frontend-workbench-start`

**标准化 DoD**：
- 主产物落盘：`frontend/src/pages/WikiWorkbench.tsx`, `frontend/src/components/wiki/` 已创建
- 状态同步：更新主计划、更新 Wave 12 runbook
- 门禁通过：
  - `npm --prefix frontend run test` 通过（54 tests）
  - `npm --prefix frontend run build` 成功
  - 浏览器 smoke：5 个关键页面可访问
  - 无回归：前端全量测试通过
- 环境收尾：无 orphan node_modules

---

## Wave 13：Zotero/EndNote/Obsidian 只读 connector

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：引入新依赖、外部路径写回
**回档点**：`wave13-connector-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/connectors/` 已创建
- 状态同步：更新主计划、更新 Wave 13 runbook
- 门禁通过：
  - `pytest tests/wiki/test_connectors.py -q` 通过（10 tests）
  - `compileall literature_assistant/core/wiki/connectors` 通过
  - 无回归：`pytest tests/wiki -q` 全量通过
  - 路径白名单：明确允许的外部路径
- 环境收尾：无外部路径写入

---

## Wave 14：评测、回归、质量门禁

**权限层级**：L1（surgical 写）
**自动批准**：✓
**红线项**：修改 qrels、修改 goldset
**回档点**：`wave14-eval-gates-start`

**标准化 DoD**：
- 主产物落盘：`literature_assistant/core/wiki/evaluation.py`, `tools/eval/wiki_wave14_performance_baseline.py` 已创建
- 状态同步：更新主计划、更新 Wave 14 runbook
- 门禁通过：
  - `pytest tests/wiki -m wiki_wave14 -q` 通过（11 tests）
  - `pytest tests/wiki -q` 全量通过（342 tests）
  - `pytest tests --collect-only -q` 收集成功（1618+ tests）
  - `compileall literature_assistant/core/wiki tests/wiki workspace_tests/fixtures` 通过
  - `system_verification.py --json` 通过（23 passed / 0 failed）
  - 性能基线：compile/query/doctor 延迟记录
- 环境收尾：无 eval artifacts in wrong location

---

## Wave 15：迁移、发布门禁、长期维护

**权限层级**：L3（高权限）
**自动批准**：-
**需用户授权**：✓（高权限，需明确授权）
**红线项**：全量 reindex、删除兼容层、force push、删分支
**回档点**：`wave15-migration-start`

**标准化 DoD**：
- 主产物落盘：迁移脚本、备份脚本、发布 checklist 已创建
- 状态同步：更新主计划、更新 Wave 15 runbook、更新 master plan
- 门禁通过：
  - 端到端 dry-run 验收：source → compile → doctor → query-save
  - 独立复核：另一个 agent 或用户确认
  - 证据包：Facts / Decisions / Open / Next 完整
  - 残留风险：明确记录
- 环境收尾：
  - 无 stale lock
  - 无 ghost-running
  - 无 orphan tmp
  - 无混跑 artifact
  - 无未解释非零 exit

---

## 补充任务（LMWR-464 ~ LMWR-473）

### LMWR-464：修复剩余测试失败

**状态**：✅ 已完成（2026-05-04）
**权限层级**：L1
**自动批准**：✓
**红线项**：无
**DoD**：
- 主产物：修复代码已提交
- 状态同步：更新 `docs/analysis/legacy-test-triage-20260503.md`
- 门禁：`pytest tests -q` 失败数 < 5
- 环境：无临时文件

### LMWR-465：补充 TOLF 设计文档

**权限层级**：L1
**自动批准**：✓
**红线项**：无
**DoD**：
- 主产物：`docs/plans/specs/tolf-wiki-integration.md` 已创建
- 状态同步：更新主计划、更新决策记录
- 门禁：设计文档评审通过
- 环境：无临时文件

### LMWR-466：补充前端 E2E 测试框架

**权限层级**：L2
**自动批准**：✓（2026-05-04 用户授权补充）
**需用户授权**：-
**红线项**：无；优先复用现有 Playwright，仅缺 browser runtime 时补安装
**DoD**：
- 主产物：`frontend/tests/e2e/` 下 Wiki 最小 E2E 场景通过
- 状态同步：更新主计划、更新执行记录；如未改依赖则不改 `frontend/package.json`
- 门禁：E2E 测试通过（关键工作流优先，浏览器仅作独立窗口终态前的开发期验收）
- 环境：无 orphan browser processes

### LMWR-467：补充外部知识库写回设计

**状态**：✅ 已完成（2026-05-04）
**权限层级**：L1
**自动批准**：✓
**红线项**：无（仅设计文档）
**DoD**：
- 主产物：`docs/plans/specs/external-knowledge-writeback-policy.md` 已创建
- 状态同步：更新主计划、更新决策记录
- 门禁：设计文档评审通过
- 环境：无临时文件

### LMWR-468：实现 Wiki 编译成本预估

**权限层级**：L2
**自动批准**：-
**需用户授权**：✓
**红线项**：无
**DoD**：
- 主产物：`literature_assistant/core/wiki/compiler.py` 已扩展
- 状态同步：更新主计划
- 门禁：dry-run 显示预估成本，focused tests 通过
- 环境：无临时文件

### LMWR-469：补充 longrun 模式使用指南

**状态**：✅ 已完成（2026-05-04）
**权限层级**：L1
**自动批准**：✓
**红线项**：无
**DoD**：
- 主产物：`docs/plans/runbooks/longrun-local-supervisor.md` 已更新
- 状态同步：更新主计划、更新决策记录
- 门禁：使用指南可执行
- 环境：无临时文件

### LMWR-470：重新评估分块参数 200/8

**权限层级**：L2
**自动批准**：✓（2026-05-04 用户授权补充）
**需用户授权**：-
**红线项**：无备份修改 qrels/goldset/canary30
**DoD**：
- 主产物：实验结果记录、决策文档
- 状态同步：更新 `docs/analysis/chunk-strategy-review-20260503.md`
- 门禁：canary30 或新增查询集对照通过；若修改旧查询集/qrels/goldset，必须先备份并记录旧/新指标和恢复路径
- 环境：无临时文件

### LMWR-471：补充 Wiki 性能基线

**状态**：✅ 已完成（2026-05-04）
**权限层级**：L1
**自动批准**：✓
**红线项**：无
**DoD**：
- 主产物：`tools/eval/wiki_wave14_performance_baseline.py` 已扩展
- 状态同步：更新主计划
- 门禁：性能基线数据记录（P50/P95/P99）
- 环境：无临时文件

### LMWR-472：补充 Wiki 安全审计

**权限层级**：L2
**自动批准**：✓（2026-05-04 用户授权补充）
**需用户授权**：-
**红线项**：无
**DoD**：
- 主产物：`docs/plans/specs/wiki-security-audit.md` 已创建，路径越界、输入校验、只读权限、日志脱敏、RAG/LLM evidence 边界测试已补充
- 状态同步：更新主计划
- 门禁：本地安全测试通过；不做外部攻击扫描
- 环境：无临时文件

### LMWR-473：补充 Wiki 可观测性

**权限层级**：L2
**自动批准**：✓（2026-05-04 用户授权补充）
**需用户授权**：-
**红线项**：无
**DoD**：
- 主产物：`literature_assistant/core/wiki/observability.py` 已创建
- 状态同步：更新主计划
- 门禁：统一日志/指标/追踪接口实现，focused tests 通过；默认本地、无网络导出、敏感字段脱敏
- 环境：无临时文件
