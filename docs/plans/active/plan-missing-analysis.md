# LLM-Wiki 执行计划缺失点分析

## 分析维度

1. **权限管理与决策参考**：对照用户画像 v4 §5-§11
2. **项目构建完整性**：对照用户画像 v4 §1.3 六层功能边界
3. **执行治理**：对照用户画像 v4 §6 完成定义、§11 多 agent 协作

---

## 一、权限管理缺失

### 缺失 1：执行计划未明确权限层级

**问题**：
- 240 个任务（LMWR-224 ~ LMWR-473）未标注权限层级（L0/L1/L2/L3）
- 未明确哪些任务需要用户授权，哪些可自动批准
- 未明确红线触发条件

**影响**：
- AI 执行时可能越权操作
- 用户无法快速判断任务风险
- 缺少自动批准白名单

**补充方案**：
为每个 Wave 添加权限层级标注：
- Wave 0-2（数据模型、注册表）：L1（surgical 写）
- Wave 3-6（页面存储、引用验证、编译器）：L2（局部重构）
- Wave 7（LLM 生成）：L2（需成本预估）
- Wave 8-10（检索、图谱、Doctor）：L2（局部重构）
- Wave 11-12（API、前端）：L2（局部重构）
- Wave 13（外部 connector）：L2（需路径白名单）
- Wave 14（评测）：L1（surgical 写）
- Wave 15（迁移、发布）：L3（高权限，需明确授权）

---

### 缺失 2：红线清单未映射到执行计划

**问题**：
- 用户画像 v4 §8 定义了 20+ 红线项
- 执行计划未标注哪些任务触发红线
- 未提供红线请示模板

**影响**：
- AI 可能触发红线而不自知
- 用户需要手动判断每个任务是否触红线

**补充方案**：
为执行计划添加红线映射表：

| 任务 | 红线项 | 请示模板 |
|------|--------|----------|
| LMWR-224 ~ LMWR-240（source registry）| 无 | - |
| LMWR-314 ~ LMWR-328（compiler）| 单次跑超过 30 分钟 | 需成本预估 |
| LMWR-329 ~ LMWR-343（LLM 生成）| 替换主 LLM、单次跑超预算 | 需用户确认 |
| LMWR-344 ~ LMWR-358（wiki-aware retrieval）| 修改评测口径、修改 qrels | 需用户确认 |
| LMWR-419 ~ LMWR-433（外部 connector）| 引入新依赖、外部路径写回 | 需用户确认 |
| LMWR-449 ~ LMWR-463（迁移、发布）| 全量 reindex、删除兼容层 | 需用户确认 |

---

### 缺失 3：自决策边界未明确

**问题**：
- 用户画像 v4 §5.2A 定义了"结构性缺失优先自决"
- 执行计划未明确哪些属于结构性缺失
- 未明确自决策的证据要求

**影响**：
- AI 可能过度自决策，扩大改动范围
- 或过度保守，频繁停下询问

**补充方案**：
为执行计划添加自决策白名单：
- 缺失的 DoD 命令
- 缺失的回档点
- 缺失的验证脚本
- 缺失的状态同步
- 缺失的 compileall 检查
- 缺失的 pytest marker

禁止自决策：
- 架构调整
- 主链变更
- 评测口径变更
- 新增依赖
- 外部写回

---

## 二、决策参考缺失

### 缺失 4：完成定义（DoD）未标准化

**问题**：
- 240 个任务的验收标准不统一
- 部分任务只有"focused tests pass"，缺少完整 DoD
- 未明确"主产物落盘 ∧ 状态同步 ∧ 门禁通过 ∧ 环境收尾"

**影响**：
- AI 可能误报完成
- 用户需要手动补充验收标准

**补充方案**：
为每个 Wave 添加标准化 DoD 模板：

```
DoD = 主产物落盘 ∧ 状态同步 ∧ 门禁通过 ∧ 环境收尾

主产物落盘：
- [ ] 代码文件已写入 `literature_assistant/core/wiki/`
- [ ] 测试文件已写入 `tests/wiki/`
- [ ] grep 可验证落盘

状态同步：
- [ ] 更新 `docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`
- [ ] 更新 Wave runbook
- [ ] 更新 `docs/analysis/` 相关分析文档

门禁通过：
- [ ] `pytest tests/wiki/<wave>_tests.py -q` 通过
- [ ] `compileall literature_assistant/core/wiki tests/wiki` 通过
- [ ] `pytest tests/wiki -q` 全量通过（无回归）
- [ ] 报告 exit code、样本数、关键指标

环境收尾：
- [ ] 无 stale lock
- [ ] 无 orphan tmp
- [ ] 无混跑 artifact
- [ ] 无未解释非零 exit
```

---

### 缺失 5：回滚点策略未明确

**问题**：
- 执行计划提到"每个非平凡代码切片开始前必须创建回档点"
- 但未明确回档点的命名规范、存储位置、恢复流程
- 未明确哪些情况需要回滚

**影响**：
- 回档点可能命名混乱
- 恢复流程不清晰
- 用户难以快速回滚

**补充方案**：
添加回档点策略：

**命名规范**：
- `{date}-{wave}-{task-id}-{slug}`
- 例如：`20260504-wave15-lmwr-449-migration-plan`

**存储位置**：
- `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-{hash}\`

**创建时机**：
- 每个 Wave 开始前
- 每个红线任务开始前
- 每个 L2/L3 任务开始前

**恢复流程**：
```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" list --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```

---

### 缺失 6：成熟方案对标流程未标准化

**问题**：
- 执行计划提到"每个架构、数据、接口、评测或治理切片开始前必须搜索成熟方案"
- 但未明确对标流程、对标范围、对标记录格式

**影响**：
- AI 可能跳过对标
- 对标记录不完整
- 无法追溯设计决策

**补充方案**：
添加成熟方案对标流程：

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
```

---

## 三、项目构建缺失

### 缺失 7：六层功能边界未映射到执行计划

**问题**：
- 用户画像 v4 §1.3 定义了六层功能边界
- 执行计划未明确每个 Wave 对应哪一层
- 未明确层间依赖关系

**影响**：
- AI 可能跨层修改
- 层间接口不清晰
- 难以定位问题

**补充方案**：
添加六层功能边界映射：

| 层级 | 功能 | 对应 Wave | 关键文件 |
|------|------|-----------|----------|
| 1. 基础设施 | 环境、配置、模型网关、成本日志、缓存、状态文件 | Wave 0 | `runtime_env.py`, `project_paths.py` |
| 2. 抽取 | PDF 文本、章节、参考文献、图/表/caption | 已完成 | `extractor_full.py` |
| 3. 入库 | material manifest、chunk、向量存储、项目索引 | Wave 1-2 | `source_registry.py`, `chunk_registry.py` |
| 4. 检索 | BM25/Hybrid/Graph/Dense/RRF/rerank/expansion | Wave 8 | `wiki/query.py` |
| 5. 生成 | 证据约束回答、写作素材、引用链 | Wave 5-7 | `wiki/compiler.py`, `wiki/evidence_adapter.py` |
| 6. 交付 | 前端 Workbench、报告、Word/料包 | Wave 11-12 | `frontend/`, `routers/wiki_router.py` |

---

### 缺失 8：TOLF 集成路径未明确

**问题**：
- 用户画像 v4 §1.3 强调"TOLF 是最终目标，RAG 是过渡"
- 执行计划未明确 TOLF 集成路径
- 未明确 TOLF 与 Wiki 的关系

**影响**：
- TOLF 功能可能与 Wiki 脱节
- 重复实现类似能力
- 最终目标不清晰

**补充方案**：
添加 TOLF 集成路径：

**当前状态**：
- TOLF 已实现：`layers/tolf_engine.py`, `test_tolf_engine.py`
- TOLF 为可选实验能力，未替换默认主链
- 最新 5 个 commit 全部是 TOLF 相关

**集成路径**：
1. **Phase 1（当前）**：TOLF 与 RAG 并行，互不干扰
2. **Phase 2（Wave 15）**：TOLF 输出进入 Wiki page store
3. **Phase 3（未来）**：TOLF 替换默认主链

**集成点**：
- TOLF judgment summary → Wiki synthesis page
- TOLF review packet → Wiki review queue
- TOLF inspection packet → Wiki doctor report

---

### 缺失 9：评测口径未明确

**问题**：
- 执行计划提到"不改变 corpus/goldset/qrels"
- 但未明确当前评测口径：canary30、full、109 篇基线
- 未明确 Wiki 评测与 RAG 评测的关系

**影响**：
- AI 可能误改评测口径
- 评测结果不可比较
- 回归检测失效

**补充方案**：
添加评测口径明确说明：

**当前评测口径**：
- **canary30**：30 个查询，快速验证
- **full**：109 篇基线，完整验证
- **qrels**：人工标注的相关性判断

**Wiki 评测口径**：
- **zero-cost**：不调用模型，只比较 retrieval
- **wiki vs raw**：Wiki 检索 vs RAG 检索对比
- **citation audit**：引用密度、quote 匹配

**禁止改动**：
- 不改 qrels
- 不改 goldset
- 不改 canary30 查询集
- 新增评测必须独立，不覆盖现有评测

---

### 缺失 10：前端构建流程未明确

**问题**：
- Wave 12 前端工作台已完成
- 但未明确前端构建流程、发布流程、回滚流程

**影响**：
- 前端改动可能破坏构建
- 发布流程不清晰
- 回滚困难

**补充方案**：
添加前端构建流程：

**开发流程**：
```bash
cd frontend
npm install
npm run dev  # 启动开发服务器
npm run test  # 运行 Vitest 单元测试
npm run build  # 构建生产版本
```

**发布流程**：
1. 运行 `npm run test` 确保所有测试通过
2. 运行 `npm run build` 确保构建成功
3. 浏览器 smoke 测试（至少 5 个关键页面）
4. 提交代码并创建 PR
5. 等待 CI/CD 通过
6. 合并到 main

**回滚流程**：
1. 找到上一个稳定版本的 commit
2. `git revert <commit>` 或 `git reset --hard <commit>`
3. 重新构建和发布

---

## 四、执行治理缺失

### 缺失 11：长跑 envelope 未标准化

**问题**：
- 用户画像 v4 §11.2 要求长跑必须有 envelope
- 执行计划未提供 envelope 模板
- 未明确 longrun 模式的启动条件、停止条件

**影响**：
- longrun 模式可能失控
- 缺少预算控制
- 缺少停止机制

**补充方案**：
添加长跑 envelope 模板：

```markdown
## 长跑 Envelope

**Objective**：完成 Wave X 的 Y 功能

**Allowed Scope**：
- 修改 `literature_assistant/core/wiki/` 下的文件
- 新增 `tests/wiki/` 下的测试
- 更新 Wave runbook

**Disallowed Actions**：
- 不改 qrels/goldset
- 不改主链默认值
- 不引入新依赖
- 不外部写回
- 不 auto-finalize

**Budget**：
- 时间：< 2 小时
- Token：< 100K tokens
- 成本：< $5

**Checkpoint Cadence**：
- 每完成一个任务创建回档点
- 每 30 分钟报告进度

**Stop Conditions**：
- 触发红线
- 超预算
- 连续 2 轮无 artifact delta
- 用户创建 STOP 文件

**Expected Artifacts**：
- 代码文件：`literature_assistant/core/wiki/*.py`
- 测试文件：`tests/wiki/*.py`
- Wave runbook：`docs/plans/runbooks/llmwiki-slice-LMWR-*.md`

**Rollback Path**：
- 回档点：`{checkpoint-id}`
- 恢复命令：`py checkpoint.py restore --checkpoint {checkpoint-id}`

**Evidence Sources**：
- 本地借鉴库：`C:\Users\xiao\Downloads\llmwiki借鉴库\`
- github 参考库：`github/`
```

---

### 缺失 12：防自喂食机制未明确

**问题**：
- 用户画像 v4 §11.3 要求"连续两轮没有 artifact delta 就必须停"
- 执行计划未明确如何检测 artifact delta
- 未明确停止后的报告格式

**影响**：
- AI 可能陷入元观察循环
- 浪费时间和成本
- 用户需要手动中断

**补充方案**：
添加防自喂食机制：

**Artifact Delta 检测**：
- code diff（git diff）
- test artifact（pytest 输出）
- data artifact（新增文件）
- task transition（任务状态变更）
- eval delta（评测指标变化）

**停止报告格式**：
```markdown
## 停止报告

**Facts**：
- 已完成任务：LMWR-X, LMWR-Y
- 未完成任务：LMWR-Z
- 最后一次 artifact delta：{timestamp}

**Stalled Evidence**：
- 连续 2 轮无 code diff
- 连续 2 轮无 test artifact
- 连续 2 轮无 task transition

**Safe Next Action**：
- 选项 1：修复 LMWR-Z 的阻塞问题
- 选项 2：跳过 LMWR-Z，继续下一个任务
- 选项 3：停止长跑，等待用户指示
```

---

### 缺失 13：独立复核机制未明确

**问题**：
- 用户画像 v4 §11.4 要求"决策级结果必须独立复核"
- 执行计划未明确哪些属于决策级结果
- 未明确复核流程

**影响**：
- AI 可能自己批准自己的结果
- 缺少质量保证
- 用户需要手动复核所有结果

**补充方案**：
添加独立复核机制：

**决策级结果**：
- 架构调整
- 主链变更
- 评测口径变更
- 新增依赖
- 外部写回
- 发布门禁

**复核流程**：
1. AI 产出候选结果，标记为 `provisional`
2. 独立 reviewer（另一个 AI 或用户）复核
3. 复核通过后标记为 `approved`
4. 复核不通过时回滚并重新设计

**复核清单**：
- [ ] 是否符合用户画像 v4 的规则？
- [ ] 是否触发红线？
- [ ] 是否有回滚点？
- [ ] 是否有完整 DoD？
- [ ] 是否有证据支持？

---

## 五、补充建议

### 建议 1：创建执行计划权限矩阵

在主计划中添加一个权限矩阵表，明确每个 Wave 的权限层级、红线项、自决策边界。

### 建议 2：创建执行计划 DoD 模板库

为每种类型的任务（数据模型、API、前端、评测）创建标准化 DoD 模板。

### 建议 3：创建执行计划回滚手册

详细说明回档点的创建、命名、存储、恢复流程，以及常见回滚场景。

### 建议 4：创建执行计划成熟方案索引

为每个 Wave 预先索引相关的成熟方案，减少对标时间。

### 建议 5：创建执行计划长跑监督指南

详细说明 longrun 模式的启动、监督、停止、恢复流程。

---

## 总结

执行计划在以下方面存在缺失：

**权限管理（5 个缺失）**：
1. 未明确权限层级
2. 红线清单未映射
3. 自决策边界未明确
4. 完成定义未标准化
5. 回滚点策略未明确

**决策参考（2 个缺失）**：
6. 成熟方案对标流程未标准化
7. 评测口径未明确

**项目构建（4 个缺失）**：
8. 六层功能边界未映射
9. TOLF 集成路径未明确
10. 前端构建流程未明确
11. 评测口径未明确（重复）

**执行治理（3 个缺失）**：
12. 长跑 envelope 未标准化
13. 防自喂食机制未明确
14. 独立复核机制未明确

**优先级**：
- P0：缺失 1, 2, 4, 12, 13（影响执行安全和质量）
- P1：缺失 3, 5, 6, 8, 11（影响执行效率）
- P2：缺失 7, 9, 10（影响可维护性）
