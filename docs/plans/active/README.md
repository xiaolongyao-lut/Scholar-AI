# LLM-Wiki 执行计划文档索引

## 文档用途

本目录包含 LLM-Wiki + RAG 文献助手优化项目的完整执行计划和补充文档，供所有 AI agent（Claude、Copilot、Squad 等）公用。

---

## 核心执行计划

### 主计划
- **文件**：`2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md`
- **内容**：240 个任务（LMWR-224 ~ LMWR-473）的完整执行计划
- **包含**：
  - 执行硬规则
  - 权限管理与执行治理
  - 项目构建完整性
  - 15 个 Wave 的任务分解
  - 成熟方案对标
  - 验证命令基线

### 执行决策
- **文件**：`2026-05-03-llmwiki-execution-decisions.md`
- **内容**：核心决策记录（D1-D15）
- **包含**：
  - 执行范围决策
  - Wiki-first retrieval 决策
  - Frontmatter 格式决策
  - 外部资料源集成决策
  - Graph 存储格式决策
  - API Router 权限模型决策
  - 测试失败修复状态
  - 分块参数调整与回滚
  - TOLF 功能定位
  - 前端 UI 测试覆盖
  - 外部知识库写回策略
  - Wiki 编译成本控制
  - longrun 模式边界

---

## 权限管理与执行治理

### Wave 任务权限与 DoD 补充
- **文件**：`wave-permission-dod-supplement.md`
- **内容**：所有 Wave 的权限层级和标准化 DoD
- **包含**：
  - 每个 Wave 的权限层级（L0/L1/L2/L3）
  - 自动批准标识
  - 红线项标识
  - 回档点命名
  - 标准化 DoD（主产物落盘 ∧ 状态同步 ∧ 门禁通过 ∧ 环境收尾）

### 红线重新定义（2026-05-04 更新）
- **文件**：`redline-relaxation-analysis.md`
- **内容**：基于实际执行经验重新定义红线
- **包含**：
  - 原红线问题分析（过度保守）
  - 新红线定义（硬红线/绿灯操作）
  - 计划任务豁免规则（LMWR-XXX 任务自动放行）
  - 权限层级调整（L1 扩大范围）
  - 请示模板更新
  - 对比表（原红线 vs 新红线）
- **核心原则**：
  - 数据安全第一（数据丢失、不可逆操作必须请示）
  - 基线保护第二（评测基线、主链不能随意破坏）
  - 计划任务放行（已规划任务触碰红线自动豁免）
  - 小事情放行（文档、测试、小修复、只读操作、成本控制无需请示）

### LLM-Wiki 自决策授权补充（2026-05-04 更新）
- **文件**：`llmwiki-autonomy-authorization.md`
- **内容**：用户对剩余计划任务的一次性授权和边界补充
- **包含**：
  - 最终界面为独立窗口，浏览器仅用于开发期最小预览和 E2E 验收
  - 查询集、qrels、goldset、canary30 可在备份和对照证据充分后自决策演进
  - 安全审计定义为本地轻量门禁，不做外部攻击扫描
  - AI 可联网搜索背景和成熟方案，但正式回答必须基于本地知识库证据链
  - 删除、修改、远程历史和外部数据操作必须先有可验证备份

### 用户画像 v4（外部引用）
- **文件**：`C:\Users\xiao\Desktop\tools\用户画像_v4_AI协作治理型工程主理人.md`
- **内容**：权限模型、完成定义、多 agent 协作、红线、事故索引
- **关键章节**：
  - §5 权限模型（L0/L1/L2/L3）
  - §6 完成定义（主产物落盘 ∧ 状态同步 ∧ 门禁通过 ∧ 环境收尾）
  - §8 红线（20+ 红线项，已根据实际经验放宽）
  - §11 多 agent / Squad 协作协议
  - §11.5 已知事故索引（4 个事故）

---

## 项目构建完整性

### TOLF-Wiki 集成设计
- **文件**：`../specs/tolf-wiki-integration.md`
- **内容**：TOLF 与 Wiki 的集成设计
- **包含**：
  - 当前状态（TOLF 已实现，Wiki 已完成 Wave 0-14）
  - 集成目标（3 个 Phase）
  - 集成点设计（3 个集成点）
  - 数据流设计（并行、集成、替换模式）
  - 实现计划（Phase 1-3）
  - 风险与缓解（4 个风险）

---

## 漏洞分析与修复

### 计划漏洞分析
- **文件**：`plan-missing-analysis.md`
- **内容**：15 个缺失点的详细分析
- **包含**：
  - 权限管理缺失（5 个）
  - 决策参考缺失（1 个）
  - 项目构建缺失（4 个）
  - 执行治理缺失（5 个）
  - 每个缺失点的补充方案

### 漏洞修复影响分析
- **文件**：`gap-fix-impact-analysis.md`
- **内容**：漏洞修复的依赖关系和影响分析
- **包含**：
  - 漏洞依赖关系图
  - 修复顺序（4 批次）
  - 每个漏洞的影响范围、前置条件、修复步骤、验收标准、影响文档、风险
  - 修复时间线（3 周）
  - 修复验证矩阵

### 漏洞修复执行状态
- **文件**：`gap-fix-status.md`
- **内容**：当前修复状态和下一步行动
- **包含**：
  - 测试失败数（从 22 降至 0，-100%）
  - LMWR-464 收口证据
  - 后续 L2 任务授权边界
  - 修复优先级调整
  - 验证结果

---

## 使用指南

### 对于新接手的 AI

1. **必读文档**（按顺序）：
   - `2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md`（主计划）
   - `wave-permission-dod-supplement.md`（权限和 DoD）
   - `llmwiki-autonomy-authorization.md`（最新自决策授权补充）
   - `C:\Users\xiao\Desktop\tools\用户画像_v4_AI协作治理型工程主理人.md`（权限模型和红线）

2. **执行任务前**：
   - 检查权限层级（L0/L1/L2/L3）
   - 检查是否触发红线
   - 创建回档点（L2/L3 任务）
   - 搜索成熟方案（架构/数据/接口/评测任务）

3. **执行任务后**：
   - 验证主产物落盘
   - 更新状态同步
   - 运行门禁验证
   - 检查环境收尾

### 对于长跑 / Squad 模式

1. **必读文档**（额外）：
   - `2026-05-03-llmwiki-execution-decisions.md`（决策记录）
   - `gap-fix-status.md`（当前状态）
   - 用户画像 v4 §11（多 agent 协作协议）

2. **长跑前**：
   - 声明 envelope（objective/scope/budget/checkpoint/stop conditions）
   - 检查防自喂食机制
   - 检查独立复核机制

3. **长跑中**：
   - 每个 checkpoint 更新状态
   - 检查 artifact delta（连续两轮无 delta 必须停）
   - 检查环境收尾（stale lock/orphan tmp/混跑 artifact）

---

## 文档维护

### 更新规则

1. **主计划更新**：
   - 每个 Wave 完成后更新进度
   - 每个决策后更新决策记录
   - 每个漏洞修复后更新修复状态

2. **补充文档更新**：
   - 权限模型变更时更新 `wave-permission-dod-supplement.md`
   - TOLF 集成进展时更新 `tolf-wiki-integration.md`
   - 漏洞修复进展时更新 `gap-fix-status.md`

3. **文档索引更新**：
   - 新增文档时更新本索引
   - 文档移动时更新本索引

### 文档命名规范

- 主计划：`{date}-{project}-{type}.md`
- 补充文档：`{topic}-{type}.md`
- 规范文档：`{topic}-{version}.md`

---

## 相关资源

### 成熟方案参考

- 本地借鉴库：`C:\Users\xiao\Downloads\llmwiki借鉴库\`
- github 参考库：`github/`
- 官方上游文档：见主计划 §成熟方案与本地证据

### 验证命令

```powershell
# 基础验证
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py workspace_tests\evaluation_scripts

# Wiki 测试
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -q
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -m wiki_wave14 -q

# 前端测试
npm --prefix frontend run test
npm --prefix frontend run build

# 系统验证
& .\.venv-1\Scripts\python.exe workspace_tests\system_verification.py --json
```

---

## 联系与反馈

- 主理人：小龙 姚
- 执行者：Claude (Kiro) / Copilot / Squad
- 文档版本：v1.0
- 最后更新：2026-05-04
