# 计划漏洞修复影响分析

## 修复策略

### 原则
1. **依赖优先**：先修复被其他漏洞依赖的基础问题
2. **风险优先**：先修复高风险、高影响的漏洞
3. **验证闭环**：每个修复必须有验证方式
4. **文档同步**：修复后更新所有相关文档

---

## 漏洞依赖关系图

```
LMWR-464 (测试修复) ← 基础，影响所有后续验证
    ↓
LMWR-465 (TOLF设计) ← 影响 Wiki 集成边界
    ↓
LMWR-468 (成本预估) ← 影响 Wave 15 迁移安全性
    ↓
LMWR-472 (安全审计) ← 影响发布门禁
    ↓
LMWR-466 (E2E测试) ← 影响前端发布质量
LMWR-471 (性能基线) ← 影响优化决策
LMWR-473 (可观测性) ← 影响生产运维
    ↓
LMWR-470 (分块参数) ← 依赖性能基线
LMWR-469 (longrun指南) ← 依赖安全审计
LMWR-467 (写回策略) ← 低优先级，可独立
```

---

## 修复顺序与影响分析

### 第一批：基础设施修复（P0）

#### LMWR-464：修复剩余测试失败（4-6个）

**影响范围**：
- 直接影响：所有后续 Wave 的测试验证
- 间接影响：CI/CD 流程、回归检测、质量门禁

**修复前置条件**：
- 无

**修复步骤**：
1. 跑完整 pytest，确认当前失败数量和类型
2. 分类失败：Pipeline 可观测性 (2) + 编码 (1) + LLM Mock 残留 (1)
3. 逐个修复，每个修复后跑 focused tests
4. 全量回归验证

**验收标准**：
- `pytest tests -q` 失败数 < 5
- 所有 P0/P1 测试通过
- 无新增失败

**影响的文档**：
- `docs/analysis/legacy-test-triage-20260503.md`：更新修复状态
- `docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`：更新 D9
- 各 Wave runbook：更新验证结果

**风险**：
- 修复可能引入新的回归
- 某些失败可能需要架构调整

---

#### LMWR-465：补充 TOLF 设计文档

**影响范围**：
- 直接影响：TOLF 与 Wiki 的集成边界
- 间接影响：Wave 15 迁移策略、数据流设计

**修复前置条件**：
- 需要理解当前 TOLF 实现（最新 5 个 commit）
- 需要理解 Wiki page store 的输入契约

**修复步骤**：
1. 读取 TOLF 相关 commit 和代码
2. 分析 TOLF 输出格式和 Wiki 输入格式
3. 设计集成方案：独立工具 vs 前置步骤
4. 编写设计文档

**验收标准**：
- 明确 TOLF 定位（独立工具 or Wiki 前置）
- 明确集成点（TOLF 输出 → Wiki page store）
- 明确测试覆盖和质量门禁
- 设计文档评审通过

**影响的文档**：
- 新增：`docs/plans/specs/tolf-wiki-integration.md`
- 更新：`docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md`
- 更新：`docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`

**风险**：
- TOLF 和 Wiki 可能存在功能重叠
- 集成可能需要重构现有代码

---

### 第二批：安全与成本控制（P1）

#### LMWR-468：实现 Wiki 编译成本预估

**影响范围**：
- 直接影响：用户成本控制、LLM 调用预算
- 间接影响：Wave 15 迁移安全性、生产发布

**修复前置条件**：
- Wave 7 LLM gateway 已实现（当前为 stub 模式）
- Wave 14 cost guard 已实现（LMWR-439）

**修复步骤**：
1. 扩展 `CompileBudget` 支持成本预估
2. 实现 token-to-cost 转换（按模型定价）
3. 在 dry-run 中显示预估成本
4. 添加用户确认流程

**验收标准**：
- dry-run 显示预估 token 和成本
- 超预算时拒绝或警告
- 用户可配置预算上限
- focused tests 覆盖成本预估逻辑

**影响的文档**：
- 更新：`literature_assistant/core/wiki/compiler.py`
- 更新：`tests/wiki/test_compiler.py`
- 新增：`docs/plans/specs/wiki-cost-control.md`

**风险**：
- 不同模型定价差异大
- 预估可能不准确（prompt 优化、cache hit）

---

#### LMWR-472：补充 Wiki 安全审计

**影响范围**：
- 直接影响：生产安全、数据隐私
- 间接影响：发布门禁、用户信任

**修复前置条件**：
- Wave 13 connector 已实现（路径白名单）
- Wave 14 no-secret trace check 已实现

**修复步骤**：
1. 审计路径遍历风险（connector、page store）
2. 审计注入风险（query、compile prompt）
3. 审计权限提升风险（API router）
4. 编写安全审计文档和测试

**验收标准**：
- 路径遍历测试覆盖（`..`、绝对路径、符号链接）
- 注入测试覆盖（SQL、命令、prompt）
- 权限测试覆盖（未授权访问、越权操作）
- 安全审计文档评审通过

**影响的文档**：
- 新增：`docs/plans/specs/wiki-security-audit.md`
- 更新：`tests/wiki/test_connectors.py`
- 更新：`tests/wiki/test_page_store.py`
- 更新：`tests/wiki/test_query.py`

**风险**：
- 安全问题可能需要架构调整
- 修复可能影响功能可用性

---

### 第三批：质量与可观测性（P2）

#### LMWR-466：补充前端 E2E 测试框架

**影响范围**：
- 直接影响：前端发布质量、UI 回归检测
- 间接影响：用户体验、生产稳定性

**修复前置条件**：
- Wave 12 前端工作台已完成
- 前端 Vitest 单元测试已通过（54 个）

**修复步骤**：
1. 选择 E2E 框架（Playwright vs Cypress）
2. 搭建 E2E 测试环境
3. 编写最小测试集（登录、导航、Wiki 工作台、Evidence UI、错误态）
4. 集成到 CI/CD

**验收标准**：
- E2E 框架搭建完成
- 最小测试集通过（≥5 个场景）
- CI/CD 集成完成
- E2E 测试文档完成

**影响的文档**：
- 新增：`frontend/tests/e2e/` 目录
- 新增：`docs/plans/specs/frontend-e2e-testing.md`
- 更新：`frontend/package.json`（添加 E2E 脚本）

**风险**：
- E2E 测试可能不稳定（flaky）
- 需要额外的测试环境配置

---

#### LMWR-471：补充 Wiki 性能基线

**影响范围**：
- 直接影响：性能优化决策、回归检测
- 间接影响：用户体验、生产容量规划

**修复前置条件**：
- Wave 14 performance baseline 已实现（LMWR-441）

**修复步骤**：
1. 扩展 `wiki_wave14_performance_baseline.py`
2. 添加 compile/query/doctor 延迟和吞吐量测试
3. 记录基线数据
4. 建立性能回归检测

**验收标准**：
- 性能基线数据记录（P50/P95/P99）
- 性能回归检测脚本
- 性能基线文档

**影响的文档**：
- 更新：`tools/eval/wiki_wave14_performance_baseline.py`
- 新增：`docs/plans/specs/wiki-performance-baseline.md`
- 新增：`workspace_artifacts/performance_baselines/wiki_baseline.json`

**风险**：
- 性能基线可能受环境影响
- 需要定期更新基线

---

#### LMWR-473：补充 Wiki 可观测性

**影响范围**：
- 直接影响：生产问题定位、运维效率
- 间接影响：用户支持、系统稳定性

**修复前置条件**：
- 无

**修复步骤**：
1. 设计统一日志接口
2. 设计统一指标接口（compile/query/doctor 计数、延迟）
3. 设计统一追踪接口（query trace、compile trace）
4. 实现最小可观测性

**验收标准**：
- 统一日志接口实现
- 统一指标接口实现
- 统一追踪接口实现
- 可观测性文档完成

**影响的文档**：
- 新增：`literature_assistant/core/wiki/observability.py`
- 新增：`docs/plans/specs/wiki-observability.md`
- 更新：`literature_assistant/core/wiki/compiler.py`
- 更新：`literature_assistant/core/wiki/query.py`
- 更新：`literature_assistant/core/wiki/doctor.py`

**风险**：
- 可观测性可能影响性能
- 需要额外的存储和处理

---

### 第四批：优化与指南（P2-P3）

#### LMWR-470：重新评估分块参数 200/8

**影响范围**：
- 直接影响：检索质量、用户体验
- 间接影响：成本、延迟

**修复前置条件**：
- LMWR-471（性能基线）已完成
- canary30 回归根因已分析

**修复步骤**：
1. 分析 canary30 回归根因
2. 设计新的分块参数实验
3. 在 canary30 上评估
4. 决策是否采用

**验收标准**：
- 回归根因分析文档
- 实验结果记录
- 决策文档（采用 or 放弃）

**影响的文档**：
- 更新：`docs/analysis/chunk-strategy-review-20260503.md`
- 更新：`docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`

**风险**：
- 可能仍然导致回归
- 需要多次实验

---

#### LMWR-469：补充 longrun 模式使用指南

**影响范围**：
- 直接影响：longrun 模式使用、自动化流程
- 间接影响：开发效率、错误率

**修复前置条件**：
- LMWR-472（安全审计）已完成

**修复步骤**：
1. 整理 longrun 模式的启动条件、停止条件、监督策略
2. 编写使用指南
3. 补充安全边界说明

**验收标准**：
- longrun 使用指南完成
- 安全边界说明完成
- 示例脚本完成

**影响的文档**：
- 更新：`docs/plans/runbooks/longrun-local-supervisor.md`
- 更新：`docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`

**风险**：
- longrun 模式可能误操作
- 需要明确的停止机制

---

#### LMWR-467：补充外部知识库写回设计

**影响范围**：
- 直接影响：外部知识库集成
- 间接影响：用户工作流

**修复前置条件**：
- Wave 13 connector 已实现（只读）

**修复步骤**：
1. 分析写回需求
2. 设计写回触发条件、边界、回滚机制
3. 或明确"永不写回"决策

**验收标准**：
- 写回设计文档完成
- 或"永不写回"决策文档完成

**影响的文档**：
- 新增：`docs/plans/specs/connector-write-back.md`
- 更新：`docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`

**风险**：
- 写回可能破坏用户数据
- 需要非常谨慎的设计

---

## 修复时间线

### Week 1（立即执行）
- Day 1-2：LMWR-464（测试修复）
- Day 3：LMWR-465（TOLF 设计）
- Day 4-5：LMWR-468（成本预估）

### Week 2（本周）
- Day 1-2：LMWR-472（安全审计）
- Day 3-4：LMWR-466（E2E 测试）
- Day 5：LMWR-471（性能基线）

### Week 3（下周）
- Day 1-2：LMWR-473（可观测性）
- Day 3：LMWR-470（分块参数）
- Day 4：LMWR-469（longrun 指南）
- Day 5：LMWR-467（写回策略）

---

## 修复验证矩阵

| 任务 | 单元测试 | 集成测试 | E2E 测试 | 文档 | 评审 |
|------|---------|---------|---------|------|------|
| LMWR-464 | ✅ | ✅ | - | ✅ | - |
| LMWR-465 | - | - | - | ✅ | ✅ |
| LMWR-468 | ✅ | ✅ | - | ✅ | - |
| LMWR-472 | ✅ | ✅ | - | ✅ | ✅ |
| LMWR-466 | - | - | ✅ | ✅ | - |
| LMWR-471 | ✅ | ✅ | - | ✅ | - |
| LMWR-473 | ✅ | ✅ | - | ✅ | - |
| LMWR-470 | ✅ | ✅ | - | ✅ | - |
| LMWR-469 | - | - | - | ✅ | - |
| LMWR-467 | - | - | - | ✅ | ✅ |

---

## 风险缓解

### 高风险任务
- LMWR-464：测试修复可能引入回归 → 每个修复后跑 focused + 全量测试
- LMWR-465：TOLF 集成可能需要重构 → 先设计后实现，评审通过再动手
- LMWR-472：安全修复可能影响功能 → 先测试后修复，保留回滚路径

### 中风险任务
- LMWR-468：成本预估可能不准确 → 保守预估，添加用户确认
- LMWR-466：E2E 测试可能不稳定 → 选择稳定的框架，添加重试机制
- LMWR-473：可观测性可能影响性能 → 异步记录，采样策略

### 低风险任务
- LMWR-471：性能基线受环境影响 → 多次测量，记录环境信息
- LMWR-470：分块参数可能回归 → 在 canary30 上充分测试
- LMWR-469：longrun 指南可能不清晰 → 添加示例和常见问题
- LMWR-467：写回策略可能争议 → 先讨论后决策

---

## 下一步行动

1. **立即**：开始 LMWR-464（测试修复），跑完整 pytest 确认当前状态
2. **今天**：完成 LMWR-465（TOLF 设计）的需求分析和设计草稿
3. **明天**：开始 LMWR-468（成本预估）的实现
4. **本周末**：完成第一批修复，进入第二批
