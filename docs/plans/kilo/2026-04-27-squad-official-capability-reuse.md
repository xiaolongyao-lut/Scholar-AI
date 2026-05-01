# Squad 升级总检与官方能力复用主计划

> **定位**：本文件是每次升级 `Squad` 的前置总检门禁。  
> 任何涉及 `Squad` 控制面、`.github/agents/squad.agent.md`、`.squad/routing.md`、`.github/prompts/*.prompt.md`、`.github/skills/*`、`.github/hooks/*`、`.squad/identity/*`、Copilot CLI handoff、`Claude Squad` 适配层，或 `D4/D7/DD2/DD4/DD5/DD6` 决策变更的工作，**必须先跑完本文件的六段检查**，再进入实施。  
> 它的地位高于单次功能计划；若它与下游构建计划冲突，以本文件为升级前门禁，先修门禁，再跑交付计划。

## 0. 生效规则与使用方式

- 任何 Squad 升级前，先读本文件，再读当前活跃计划（例如 `.kilo/plans/2026-04-27-full-project-build-master-plan.md`）。
- 本文件适用于：控制面升级、治理策略升级、入口迁移、worker 体系调整、hooks/prompt/skills 变更、`Claude Squad` 适配层收口。
- 通过标准不是“写了文档”，而是“六段都通过 + 有证据 + 能复盘”。
- 启动前的最小全量预检包是：`tools/squad/smoke-test.ps1`、`tools/squad/profile-version-check.ps1`、`tools/squad/check-ghost.ps1`、`squad-doctor`、routing / chatmodes / HR1-6 文档链接检查。
- 若任一段失败：停止升级、写入 `.squad/decisions/inbox/`，并在 `.squad/orchestration-log/` 留痕。
- 若总检或执行中发现结构性缺失、治理空洞或明显拖长单次运行时长的阻塞项，默认先自决策修复并留证；除非触及人工审批硬边界，不再单独询问“是否愿意继续修”。
- 输出格式遵循 `Facts / Decisions / Open / Next`。

## 1. 为什么要这么做

- `Squad` 的角色是**控制面**，不是交付面；本文件负责控制面健康。
- 之前的 Squad 设计记忆已经证明：应复用官方 `custom agents / Plan / subagents / Copilot CLI / prompt files / skills / hooks`，而不是再造一套并行系统。
- `Claude Squad` 的经验提醒我们：
  - adapter 与 runtime 必须分离，不能让适配层成为第二个主入口
  - 入口只能有一个主线，不能让用户在多个“Squad”之间选择
  - 长跑、清理、自检必须显式留证，不能 silent success
  - wrapper 只能是 fallback，不能抢主路径
- 本文件就是把这些经验收口成每次升级都要跑的**六段总检**，并把交付计划放到它之后执行。

---

## 2. 已确认可直接复用的官方能力

### 2.1 Custom Agents（官方主入口能力）

官方文档确认：VS Code 支持 `.github/agents/*.agent.md` 作为 workspace custom agents。

已确认可直接利用：

- 聊天下拉选择自定义 agent
- `tools` 前置声明
- `agents` 白名单（限制可调用的 subagents）
- `handoffs`（阶段切换按钮）
- `user-invocable` / `disable-model-invocation`
- `Chat: Open Chat Customizations`
- `/agents`
- Diagnostics 视图检查加载来源与错误

对 `Squad` 的意义：

- **不需要自写 agent 注册 / picker / discoverability 逻辑**
- **不需要自写“模式切换 UI”**
- `Squad` 只需要成为一个正确配置的官方 custom agent

参考：

- [VS Code Custom Agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents)

### 2.2 Built-in Plan Agent（官方规划能力）

官方文档确认：VS Code 内置 `Plan` agent，并支持：

- 直接从下拉选择 `Plan`
- `/plan`
- 将计划保存到 session memory：`/memories/session/plan.md`
- `chat.planAgent.defaultModel`
- `github.copilot.chat.planAgent.additionalTools`

对 `Squad` 的意义：

- **不需要自写一个新的 planner agent 才能得到官方规划体验**
- `Squad` 可以：
  - 直接提示/触发 built-in `Plan`
  - 或将复杂任务先交给 `Plan` 作为 subagent
- durable 计划仍落库到 `.kilo/plans/`；官方 `plan.md` 用作**会话内草稿**

参考：

- [VS Code Plan Agent](https://code.visualstudio.com/docs/copilot/agents/planning)

### 2.3 Subagents（官方多 agent 编排能力）

官方文档确认：VS Code 支持主 agent 拉起 subagent，并给出了 coordinator / worker 编排模式。

已确认可直接利用：

- `runSubagent`
- 自定义 agent 作为 subagent
- `user-invocable: false` 隐藏 worker
- `agents:` 白名单控制
- 并行视角审查 / coordinator-worker pattern

对 `Squad` 的意义：

- **不需要自写第二套“子 agent 调度协议”**
- `Squad` 可以成为 coordinator，worker 只做最窄职责
- 对于某些短任务，甚至不需要新建 worker 文件，直接通过 subagent prompt 做隔离研究/评审即可

参考：

- [VS Code Subagents](https://code.visualstudio.com/docs/copilot/agents/subagents)

### 2.4 Copilot CLI Sessions（官方后台执行能力）

官方文档确认：VS Code Chat 可直接创建/监控 Copilot CLI session，并支持：

- Chat 中创建 Copilot CLI session
- Workspace / Worktree isolation
- 并行多个 CLI sessions
- local session handoff 到 Copilot CLI
- `Continue in Copilot CLI`
- 在 CLI session 中选择 workspace custom agent（实验性）

对 `Squad` 的意义：

- **不需要自写后台任务 UI、长跑 session 列表、worktree 控制面**
- 长任务可优先交给官方 Copilot CLI
- `tools/squad/squad.ps1` 只保留为**repo-local parity fallback / compatibility bridge**

参考：

- [VS Code Copilot CLI Sessions](https://code.visualstudio.com/docs/copilot/agents/copilot-cli)

### 2.5 Prompt Files（官方 slash command 能力）

官方文档确认：`.github/prompts/*.prompt.md` 是正式 prompt file 位置，并支持：

- `/prompts`
- `Chat: New Prompt File`
- frontmatter `agent`, `tools`, `model`
- `agent: plan | ask | agent | <custom-agent>`

对 `Squad` 的意义：

- **不需要把所有一次性 workflow 都塞进 `squad.agent.md` 正文**
- repo-specific 的高频动作可做成 prompt files
- prompt file 可直接引用 `Squad` 或内置 `Plan`

当前现状：

- 仓库有 `.github/prompts/prompts.md`，但它**不是官方 `.prompt.md` 格式文件名**，不应假设它会被 prompt system 正常发现

参考：

- [VS Code Prompt Files](https://code.visualstudio.com/docs/copilot/customization/prompt-files)

### 2.6 Agent Skills（官方可复用工作流能力）

官方文档确认：skills 是可移植的 workflow 封装，支持：

- `.github/skills/`
- `/skills`
- `Chat: New Skill`
- 自动按需加载
- VS Code / Copilot CLI / cloud agent 共享

对 `Squad` 的意义：

- **不需要把所有通用流程硬编码在 `Squad` 正文中**
- 启动包读取、证据打包、CLI handoff 准则、决策入 inbox 等都更适合抽成 skill

参考：

- [VS Code Agent Skills](https://code.visualstudio.com/docs/copilot/customization/agent-skills)

### 2.7 Hooks（官方治理/自动化能力）

官方文档确认：hooks 支持：

- `.github/hooks/*.json`
- agent-scoped hooks（preview）
- `SessionStart` / `PreToolUse` / `PostToolUse` / `SubagentStart` / `SubagentStop` / `PreCompact` / `Stop`
- `/hooks`
- `Chat: Configure Hooks`
- `/create-hook`

对 `Squad` 的意义：

- **不需要自写一套“命令拦截器 / 自动格式化器 / 简单审计器”**
- 可以用 hooks 做：
  - SessionStart 注入 startup packet
  - PreToolUse 限制危险动作
  - PostToolUse 自动附加验证上下文
  - SubagentStart / Stop 记录编排痕迹

参考：

- [VS Code Hooks](https://code.visualstudio.com/docs/copilot/customization/hooks)

### 2.8 从 Claude Squad 经验里抽出的优化

- `Claude Squad` 只保留为 Copilot 适配层，不能与 `Squad` 并列成两个主入口。
- 不把 `.claude_squad/` 或旧 wrapper 当成新的控制面；控制面仍然归 `Squad`。
- 长跑、kill、recovery、ghost cleanup 都要有留痕，不能靠“看起来成功”判断。
- 任何能力缺失先记录 gap，再选 fallback；不要把 fallback 伪装成主实现。
- 启动前必须有统一 doctor / smoke / profile / ghost 检查，否则不进入升级。

---

## 3. 当前仓库状态与上下文地图

### 3.1 已存在且应继续复用

| 路径 | 作用 | 结论 |
| --- | --- | --- |
| `.github/agents/squad.agent.md` | 当前原生 `Squad` 总控 agent | 主改造入口 |
| `.squad/team.md` | 团队成员与职责 | 保留并继续复用 |
| `.squad/identity/start-here.md` | startup packet 读取顺序 | 保留并继续复用 |
| `.squad/decisions.md` / `decisions/` | 团队决策状态 | 保留并继续复用 |
| `tools/squad/squad.ps1` | repo-local squad wrapper | 保留为 parity fallback / bridge |
| `.github/agents/frontend-orchestrator.agent.md` | 现成前端协调 agent | 可作为 `Squad` 允许调用的 domain worker |
| `.github/agents/expert-react-frontend-engineer.agent.md` | 现成 React worker | 可直接复用 |
| `.github/agents/frontend-performance-investigator.agent.md` | 现成性能 worker | 可直接复用 |
| `.github/agents/gem-designer.agent.md` | 现成设计 worker | 可直接复用 |

### 3.2 当前存在的问题

| 路径 | 问题 |
| --- | --- |
| `.github/agents/squad.agent.md` | 已写入大量自定义编排规则，但还没有系统性接入官方 `agents`/`handoffs`/prompt files/hooks 复用路径 |
| `.github/agents/claude-squad.agent.md` | 仅保留为 Copilot 适配层；不得与 `Squad` 并列主入口 |
| `.github/prompts/prompts.md` | 命名不符合官方 `.prompt.md` 规则，不能视作正式可发现 prompt file |
| `.github/hooks/` | 当前没有 hook 配置，说明治理/自动化尚未接上官方 hook 体系 |

### 3.3 计划涉及的文件

#### 优先修改

- `.github/agents/squad.agent.md`
- `.github/agents/claude-squad.agent.md`
- `.github/prompts/prompts.md`

#### 候选新增

- `.github/prompts/squad-plan.prompt.md`
- `.github/prompts/squad-status.prompt.md`
- `.github/hooks/squad-governance.json`
- `.github/skills/squad-startup-packet/SKILL.md`
- `.github/skills/squad-cli-handoff/SKILL.md`

#### 只引用不改动

- `.squad/team.md`
- `.squad/identity/start-here.md`
- `.squad/routing.md`
- `.squad/decisions.md`
- `tools/squad/squad.ps1`

---

## 4. 六段总检：每次 Squad 升级必跑

> 这 6 段不是普通工作拆解，而是升级前的强制 gate。顺序不可乱，任何一段失败都不能进入下一段；如果这一段失败，就先修这一段，再重跑前面的预检包。

### **核心任务 1：把原生 `Squad` 收敛成唯一可见入口**

#### 任务 1 效果

- 聊天界面只保留一个主入口：`Squad`
- 用户不再承担 `Squad` vs `Claude Squad` 的选择成本
- `Squad` 成为官方 custom agent 语义下的总控入口

#### 任务 1 升级前确认

- `Squad` 是唯一的主入口；`Claude Squad` 只作为 adapter，不承担主线调度。
- diagnostics / customizations editor 能清楚显示 `Squad` 的加载来源与错误。
- 如果出现两个“看上去都能用”的入口，立即停止升级，先收口。

#### 任务 1 动作

- 修改 `.github/agents/squad.agent.md`：明确它是官方 custom agent + official features orchestrator
- 将 `.github/agents/claude-squad.agent.md` 标记为待归档或删除
- 不新增第二个主入口模式

#### 任务 1 优先复用的官方能力

- custom agents
- agents dropdown
- diagnostics / customizations editor

#### 任务 1 验证方式

- Chat 下拉仅保留 `Squad` 作为主工作流入口
- Diagnostics 能清楚显示 `Squad` 来源与加载状态
- 若 `Claude Squad` 仍可见，也必须明确标注为适配层，不得作为主路径。

### **核心任务 2：把规划交给官方 Plan agent，而不是自写 planner**

#### 任务 2 效果

- `Squad` 不再承担完整规划器职责
- 复杂任务先走官方 `Plan`
- 会话草稿由官方 `/memories/session/plan.md` 承接，durable 计划再镜像到 `.kilo/plans/`

#### 任务 2 升级前确认

- 复杂任务能够从 `Squad` 顺利进入 `Plan`，而不是先写自定义 planner。
- `Plan` 只负责方案草稿与分解，不直接替代 durable 计划落盘。
- 如果规划路径还依赖本地自写 planner，先拆掉再升级。

#### 任务 2 动作

- 在 `Squad` 正文中明确：复杂任务优先使用 built-in `Plan`
- 优先尝试两种路径：
  1. `Squad` 通过 subagent 调用 `Plan`
  2. 通过 prompt file `agent: plan` 提供 repo-specific 包装
- 不新建 `squad-planner.agent.md`，除非官方 `Plan` 无法满足需求

#### 任务 2 优先复用的官方能力

- `Plan` agent
- `/plan`
- `chat.planAgent.defaultModel`
- `github.copilot.chat.planAgent.additionalTools`

#### 任务 2 验证方式

- 复杂任务可从 `Squad` 路径顺利进入 `Plan`
- `plan.md` 能在 session memory 中生成
- `.kilo/plans/` 仅保存确认后的 durable 计划
- `Plan` 的可用性如果不成立，说明升级还没过门禁。

### **核心任务 3：用官方 subagents 组织 worker，而不是自写第二套子代理协议**

#### 任务 3 效果

- `Squad` 负责总控
- 窄职责 worker 通过官方 subagent 机制执行
- 能直接复用已有前端 agents，而不是重写一套并行角色体系

#### 任务 3 升级前确认

- `agents` 白名单已经明确，能直接复用现有 workers。
- 对通用研究/审查任务，优先 prompt-shaped subagent；不要一上来造 hidden worker。
- 子代理轨迹可在 chat 中观察到，不能黑盒运行。

#### 任务 3 动作

- 给 `Squad` 增加明确的 `agents` 白名单策略
- 第一批直接复用现有 agents：
  - `Frontend Orchestrator`
  - `Expert React Frontend Engineer`
  - `Frontend Performance Investigator`
  - `gem-designer`
- 对通用研究/审查类任务，先用 prompt-shaped subagent；只有稳定性不够时再补 hidden worker agents

#### 任务 3 优先复用的官方能力

- `runSubagent`
- `user-invocable: false`
- `disable-model-invocation`
- `agents:` 白名单

#### 任务 3 验证方式

- `Squad` 能并行触发 subagents
- 非主入口 worker 不出现在 picker（若设为 hidden）
- Chat 中可见 collapsible subagent 轨迹
- 如果 subagent 轨迹不可见，说明编排层还不够可审计。

### **核心任务 4：把长跑/后台执行交给官方 Copilot CLI，repo wrapper 只做 fallback**

#### 任务 4 效果

- 长任务由官方后台 session 执行
- VS Code 原生支持 worktree / workspace isolation
- `tools/squad/squad.ps1` 继续保留，但不再承包所有后台能力

#### 任务 4 升级前确认

- Copilot CLI session 可以接管长跑，不需要把所有后台能力塞进 wrapper。
- `tools/squad/squad.ps1` 只是兼容 fallback，不是主控制面。
- 长跑任务在切换前必须准备 `Facts / Decisions / Open / Next` 交接包。

#### 任务 4 动作

- 在 `Squad` 中重新排序优先级：
  1. 官方 Copilot CLI session（能用时优先）
  2. repo-local `tools/squad/squad.ps1` 作为兼容 fallback
  3. 再退回 local subagent orchestration
- 验证 `github.copilot.chat.cli.customAgents.enabled` 路径
- 使用 `Continue in Copilot CLI` 承接明确任务

#### 任务 4 优先复用的官方能力

- Copilot CLI sessions
- worktree isolation
- Continue in Copilot CLI
- custom agent in CLI session（experimental）

#### 任务 4 验证方式

- 可从本地 chat handoff 到 Copilot CLI
- CLI session 能在 Chat 里持续观测
- 并行 session 可正常存在
- 任何长跑升级如果不能 handoff，就先修 handoff，再谈扩面。

### **核心任务 5：把重复流程抽到 prompt files / skills，不把所有内容继续塞进 `squad.agent.md`**

#### 任务 5 效果

- `squad.agent.md` 变薄，职责更清楚
- 高复用动作走 slash commands / skills
- 避免再把大量固定模板硬编码进总控 agent 正文

#### 任务 5 升级前确认

- 高频流程已经拆到 `.github/prompts/*.prompt.md` 或 `.github/skills/*/SKILL.md`。
- `squad.agent.md` 只保留协调与门禁，不塞重复模板。
- `.github/prompts/prompts.md` 这类伪 prompt file 不再承担正式发现职责。

#### 任务 5 动作

- 将 repo-specific 高频动作区分为两类：
  - 一次性/轻量动作 → `.github/prompts/*.prompt.md`
  - 可复用多步骤能力 → `.github/skills/*/SKILL.md`
- 第一批候选：
  - `squad-plan.prompt.md`（若 direct `/plan` 需要 repo 包装）
  - `squad-startup-packet` skill
  - `squad-cli-handoff` skill
- 处理 `.github/prompts/prompts.md`：迁移、重命名或下线，避免伪 prompt file 继续误导

#### 任务 5 优先复用的官方能力

- prompt files
- `/prompts`
- skills
- `/skills`

#### 任务 5 验证方式

- `/` 菜单中可看到正式 prompt / skill
- 相关 workflow 不再需要 `Squad` 正文重复解释
- 如果 workflow 还要回到正文找模板，说明拆分还不够彻底。

### **核心任务 6：用 hooks 和 diagnostics 做治理与观测，避免自写简单自动化脚本**

#### 任务 6 效果

- 危险动作、startup context、subagent 生命周期、验证提醒有官方挂点
- 不再优先新增私有 shell glue 解决本可由 hooks 完成的问题

#### 任务 6 升级前确认

- `.github/hooks/squad-governance.json` 这类治理挂点有最小实现或明确 gap 记录。
- `squad-doctor` / `smoke-test` / profile / ghost 检查是升级前的固定动作，不是临时补丁。
- cleanup / kill / recovery 的结果必须可追溯，不能只靠口头说明。

#### 任务 6 动作

- 先落一个最小 `.github/hooks/squad-governance.json`
- 仅做最小必要自动化：
  - `SessionStart`：注入 startup packet 摘要
  - `PreToolUse`：对危险操作统一 ask/deny
  - `SubagentStart` / `SubagentStop`：注入编排上下文或结果校验提醒
- 使用官方 Diagnostics / Hooks Output 做排错，不新增定制 debug 面板

#### 任务 6 优先复用的官方能力

- hooks
- `/hooks`
- `Chat: Configure Hooks`
- Diagnostics

#### 任务 6 验证方式

- hook 在指定事件触发
- Diagnostics 可见加载来源
- 不出现“改了 hook 但无法观测”的黑盒状态
- 升级过程中任何一次静默失败，都会让这段失去通过资格。

---

## 5. 实施顺序

### Phase A：官方能力映射与最小收口（先过门禁）

- [ ] 运行 `tools/squad/smoke-test.ps1`，确认 5/5 检查通过或明确记录失败项
- [ ] 运行 `tools/squad/profile-version-check.ps1`，确认画像版本与当前协调者版本兼容
- [ ] 运行 `tools/squad/check-ghost.ps1`，清掉 stale ghost 并留记录
- [ ] 记录官方 feature → `Squad` 职责映射矩阵
- [ ] 确认 `Squad` 是唯一主入口
- [ ] 将 `Claude Squad` 固定为“Copilot 适配层”候选，不能回到主入口位置
- [ ] 明确 `.squad/` 为继续复用的运行时层

### Phase B：规划与后台执行改走官方主路径

- [ ] 验证 `Plan` 是否能作为 `Squad` 的 planning path
- [ ] 验证 Copilot CLI custom agent 选择与 handoff 能力
- [ ] 仅在官方路径不满足时，才保留 `tools/squad/squad.ps1` 作为主要执行面

### Phase C：把重复内容拆到官方 customization primitives

- [ ] 迁移/清理 `.github/prompts/prompts.md`
- [ ] 设计最小 prompt files
- [ ] 设计最小 skills
- [ ] 控制 `squad.agent.md` 文本膨胀

### Phase D：治理与验证

- [ ] 增加最小 hooks
- [ ] 使用 Diagnostics 检查 agents / prompts / skills / hooks 全部可见
- [ ] 用 2~3 条真实任务 smoke test `Squad`

### Phase E：升级后回写与留痕

- [ ] 把本次升级结论写入 `.squad/decisions/inbox/`
- [ ] 把升级过程摘要写入 `.squad/orchestration-log/`
- [ ] 如有必要，回写 `.github/copilot-instructions.md` 或 `squad.agent.md` 的引用锚点
- [ ] 更新 `README` / docs 中关于 Squad 升级前门禁的入口说明

---

## 6. 不选的方案

- **ALT-001：继续扩写 `Claude Squad`**
  - 原因：平行入口，不符合“只选 `Squad` 就有团队效果”的目标；它最多只能是适配层。

- **ALT-002：自写新的 planner / background runner / diagnostics UI**
  - 原因：官方已有 `Plan`、Copilot CLI session、Diagnostics、Hooks。

- **ALT-003：一上来创建大量 hidden worker agents**
  - 原因：官方 subagent prompt-shaped delegation 足以覆盖第一阶段，先避免过度建模。

- **ALT-004：把本文件降级成一次性项目计划**
  - 原因：这份文档现在承担的是 Squad 升级前门禁；如果降级，后续升级会再次出现重复入口和重复治理问题。

---

## 7. 风险与假设

- **RISK-001**：某些官方能力仍处于 preview / experimental（尤其 hooks、CLI custom agents）。
- **RISK-002**：`agents:` 白名单对 built-in `Plan` 的行为边界可能需要实测确认。
- **RISK-003**：若 `Squad` 同时保留过重正文与过多 wrapper，会出现“双层路由”混乱。
- **RISK-004**：如果 `Claude Squad` 的 adapter 边界不被严格执行，容易重新长出第二个主入口。
- **RISK-005**：如果升级只改文档不跑 `squad-doctor` / `smoke-test`，门禁会失真。

- **ASSUMPTION-001**：当前 VS Code / Copilot 版本已具备 custom agents、subagents、Plan、Copilot CLI session 相关功能。
- **ASSUMPTION-002**：`.squad/` 继续作为 repo-specific runtime state 与 durable memory，不另起第二套状态目录。
- **ASSUMPTION-003**：`Claude Squad` 保持 adapter-only 的前提下，`Squad` 仍是唯一主入口。

---

## 8. 通过标准

满足以下条件时，视为该方案落地成功：

1. 在聊天界面选择 `Squad` 即可进入主工作流，且不出现第二个主入口错觉。
2. 复杂任务能先通过官方 `Plan` 生成方案，而不是 `Squad` 自写 planner。
3. 长任务能 handoff 到官方 Copilot CLI session，fallback wrapper 只在官方路径不可用时出现。
4. 现有 `.squad/` 状态继续被利用，而非被绕开或另起一套 state。
5. 高频 workflow 通过官方 prompt files / skills 承载，不再写回 agent 正文。
6. 治理/自动化优先复用 hooks，且诊断链路可观测。
7. `Claude Squad` 仅承担 adapter 职责，不再承担主路径职责。
8. 升级前的六段总检已成为固定门禁；未通过不得进入 `.kilo/plans/2026-04-27-full-project-build-master-plan.md`。

---

## 9. 本计划对应的下一步

下一轮实施应从以下最小 slice 开始：

1. 先修改 `.github/agents/squad.agent.md` 的 frontmatter 和正文，明确官方优先级：`Plan` / subagents / Copilot CLI / hooks / wrapper fallback。
2. 保持 `.github/agents/claude-squad.agent.md` 为 adapter-only，若要归档也先保留可追溯说明。
3. 迁移 `.github/prompts/prompts.md`，改成真正的 `.prompt.md` 文件或拆进 skill / instructions。
4. 做一次真实 smoke test：
   - 选 `Squad`
   - 让其进入 planning path
   - 再 handoff 到 Copilot CLI 或 subagent
5. 通过后再进入 `.kilo/plans/2026-04-27-full-project-build-master-plan.md` 的 Day 0/Day 1 执行。

---

## 10. 参考资料

- [VS Code Custom Agents](https://code.visualstudio.com/docs/copilot/customization/custom-agents)
- [VS Code Plan Agent](https://code.visualstudio.com/docs/copilot/agents/planning)
- [VS Code Subagents](https://code.visualstudio.com/docs/copilot/agents/subagents)
- [VS Code Copilot CLI Sessions](https://code.visualstudio.com/docs/copilot/agents/copilot-cli)
- [VS Code Prompt Files](https://code.visualstudio.com/docs/copilot/customization/prompt-files)
- [VS Code Agent Skills](https://code.visualstudio.com/docs/copilot/customization/agent-skills)
- [VS Code Hooks](https://code.visualstudio.com/docs/copilot/customization/hooks)

---

## 11. 外部参考项目矩阵（已下载到本地）

本轮新增了本地参考源码集合目录：

- `C:\Users\xiao\Downloads\squad`

该目录不是单个仓库，而是一个**参考项目合集目录**。当前与本计划最相关的项目矩阵如下：

| 本地目录 | 上游项目 | 用途定位 | 与本计划的关系 |
| --- | --- | --- | --- |
| `squad-0.9.4/` | `bradygaster/squad` | **主参考**：Copilot / VS Code 原生 Squad | 直接回答“原生 `Squad` 怎样复用官方 custom agent、subagent、CLI、SDK、docs 体系” |
| `squad-0.7.6 (1)/squad-0.7.6/` | `mco-org/squad` | **底层桥接参考**：多 terminal + SQLite + slash command | 解释当前 `tools/squad/squad.ps1` 背后的 CLI / terminal 协作血缘；更适合做底层 bridge 参考，不是主交互层 |
| `claude-squad-1.0.17/` | `smtg-ai/claude-squad` | **会话监管 / TUI 参考** | 适合借鉴 worktree、tmux、多会话监督，不应替代 Copilot 官方主路径 |
| `Proma-0.9.8/` | `ErlichLiu/Proma` | **产品层 / Agent Teams 参考** | 适合借鉴产品化交互、记忆与团队呈现，不是官方能力接入主线 |
| `run-agent-2.0.0/` | `jonnyzzz/run-agent` | **强流程编排参考** | 适合理解 runner + prompt brain + message bus 的强流程风格 |
| `spec-to-agents-main/` | `microsoft/spec-to-agents` | **官方多 agent 样例** | 适合理解 coordinator-centric orchestration 与工具接入样式 |
| `Roo-Code-3.53.0/` | `Roo Code` | 模式 / MCP / 扩展生态参考 | 适合看 mode、custom mode、checkpoint、扩展产品形态 |
| `Roo-Code-cli-v0.1.17/` | Roo Code 相关 monorepo 发行包 | CLI / monorepo 参考 | 适合看 `.roo/`、`apps/`、`packages/` 的拆分方式 |
| `RooFlow-0.5.6/` | `RooFlow` | Prompt / Memory Bank 参考 | 适合借鉴 YAML prompt 与 memory bank 组织方式 |
| `Custom-Modes-Roo-Code-3.0.0/` | `Custom-Modes-Roo-Code` | 模式库参考 | 适合看大量 modes/agents 如何配置化组织 |
| `awesome-copilot-chatmodes-main/` | `awesome-copilot-chatmodes` | chat mode 样例库 | 适合参考 mode 命名、安装和轻量 persona 组织 |
| `continue-1.3.38-vscode/` | `Continue` | AI checks / CI 流参考 | 更适合看 markdown 驱动检查，而不是 `Squad` 主架构 |

当前结论：

- **第一优先深读**：`squad-0.9.4/`
- **第二优先对照**：`squad-0.7.6 (1)/squad-0.7.6/`
- **第三优先补视角**：`claude-squad-1.0.17/` 或 `Proma-0.9.8/`

项目关系补充：

- `squad-0.9.4/` 与 `squad-0.7.6 (1)/squad-0.7.6/` 构成纵向对照：前者回答 Copilot / VS Code 主入口，后者回答本地 SQLite / slash command 最小通信内核。
- `run-agent-2.0.0/` 是编排可观测性与工件留痕参考，优先级提升为中高，适合对照 `.squad/orchestration-log/` 证据包规范。
- `RooFlow-0.5.6/` 是 Roo Code prompt/memory 的实验替代路径；`Custom-Modes-Roo-Code-3.0.0/` 是模式资产库；二者均不能替代官方 Copilot custom agent 主线。
- `awesome-copilot-chatmodes-main/` 是 chat mode 样例库，用于区分 `.github/chatmodes/*.chatmode.md` 与 `.github/agents/*.agent.md` 的职责边界。

另：`C:\Users\xiao\Downloads\squad\00-参考项目目录索引.md` 已创建，用于记录本地目录映射与阅读顺序。

---

## 12. 参考源码阅读顺序与方法

用户额外要求已经明确：

- 可以先看项目说明，再找自己感兴趣的，最后一起看
- 相关功能的实现代码**不能只看局部**，要看总体上是怎么完成的、怎么加载的

因此，后续阅读参考源码时应遵循固定顺序，而不是先 grep 某个功能点。

### 12.1 统一阅读顺序

1. **先看 README / docs**

- 回答：项目是什么、解决什么问题、目标用户是谁。

1. **再看 workspace / package / manifest**

- 回答：项目怎么分层、CLI / extension / SDK / app 分别在哪里。

1. **再看 entrypoint / bootstrap / agent 定义**

- 回答：程序从哪里启动、agent/mode/prompt 怎样被发现和加载。

1. **最后才看 feature-specific implementation**

- 回答：某个功能点是在整体链路中的哪一层完成的。

一句话方法：

> **先看“总装图”，再看“加载链路”，最后才看局部实现。**

### 12.2 对 `squad-0.9.4/` 的推荐入口

为了服务本计划，后续应优先沿这条路径深读：

1. `README.md`
2. `docs/src/content/docs/get-started/choose-your-interface.md`
3. `docs/src/content/docs/scenarios/client-compatibility.md`
4. `package.json`
5. `squad.config.ts`
6. `packages/squad-cli/package.json`
7. `packages/squad-sdk/package.json`
8. `cli.js`
9. `.github/agents/squad.agent.md`
10. 再进入 `packages/squad-cli/src/` 与 `packages/squad-sdk/src/`

原因：

- 前 3 步先建立产品/平台心智模型。
- `package.json` + `packages/*` 解释 monorepo 分层：**CLI 是壳，SDK 是 runtime**。
- `cli.js` 说明顶层命令怎样转发到真正 CLI 入口。
- `.github/agents/squad.agent.md` 说明 Copilot / VS Code custom agent 层怎样组织。
- 最后再看具体源代码，避免一上来陷入局部函数。

### 12.3 对 `mco-org/squad` 的使用原则

对 `squad-0.7.6 (1)/squad-0.7.6/`，后续重点不应是抄它的终端交互层，而应回答：

- 多 terminal / slash command / SQLite 总线的最小内核是什么
- 哪些能力适合继续留在 repo-local bridge
- 哪些能力应该让位给 Copilot / VS Code 官方已有机制

也就是说：

- `bradygaster/squad` 负责回答“主入口怎么在 Copilot / VS Code 里成立”
- `mco-org/squad` 负责回答“底层多 terminal 协作最小内核怎么成立”

二者不能混为一谈。

---

## 12.5 代码复用矩阵（执行前对照表）

> 目的：在动 `.github/agents/squad.agent.md` 前，先把"任务 → 外部参考源 → 仓库落点 → 复用方式"一次钉死，避免 Phase A 边写边推翻。
>
> 复用方式说明：
>
> - **直接迁移**：把外部文件按本仓约定改名/路径直接落地，仅做最小适配。
> - **借鉴模式**：仅借鉴结构/写法，不拷贝原文，重新表达为本仓语境。
> - **选择性拷贝**：从一组样本中挑出适配项，逐条评审后纳入。
> - **仅参考边界**：只用来确认能力边界，不引入任何外部代码或文本。

| 核心任务 | 复用源（外部项目 + 锚点） | 仓库落点 | 复用方式 | 备注 |
| --- | --- | --- | --- | --- |
| 1 唯一入口 | `squad-0.9.4/.github/agents/squad.agent.md`、`squad-0.9.4/docs/choose-your-interface.md` | `.github/agents/squad.agent.md` | 直接迁移 + 适配 | 必须保留本仓 §Long-run hard rules / 长跑硬规则段落 |
| 2 Plan 协同 | `spec-to-agents-main/` coordinator 路由段；官方 Plan agent 文档 | `.github/agents/squad.agent.md` "路由到 /plan" 段 | 借鉴模式 | 只描述协同协议，不引入 spec-to-agents 的运行时 |
| 3 subagents | `spec-to-agents-main/` coordinator-centric pattern；`squad-0.9.4/` 派发段 | `.github/agents/squad.agent.md` 派发段 + `.squad/routing.md` | 借鉴模式 | 用官方 `runSubagent`，不复活私有派发协议 |
| 4 CLI handoff | `squad-0.9.4/docs/client-compatibility.md`；现有 `tools/squad/squad.ps1` | `tools/squad/squad.ps1` 边界封装 + 计划文档 | 仅参考边界 | 长跑优先 Copilot CLI Sessions，wrapper 仅 fallback |
| 5 prompts/skills | `awesome-copilot-chatmodes-main/`；`RooFlow-0.5.6/` memory bank | `.github/prompts/`、`.github/skills/` | 选择性拷贝 | 每条都需对照本仓 charter / hard rules 评审 |
| 6 hooks/治理 | `continue-1.3.38-vscode/` source-controlled checks；`run-agent-2.0.0/` Message Bus | `.github/copilot-instructions.md` 治理段 + `.squad/log/`、`.squad/orchestration-log/` 现有约定 | 借鉴模式 | 不引入外部运行时，只把"长跑硬规则"映射到官方 hooks 概念 |

附加边界：

- `claude-squad-1.0.17/`、`Proma-0.9.8/`、`Roo-Code-3.53.0/`、`Roo-Code-cli-v0.1.17/`、`Custom-Modes-Roo-Code-3.0.0/` 一律按"仅参考边界"对待——只用于产品/模式启发，不进入仓库代码或 agent 文本。
- `squad-0.7.6 (1)/` 内核读法：仅用于理解多 terminal/SQLite 总线的能力边界；任务 1/3/4 一律以 `squad-0.9.4` 的 Copilot SDK 取向为准。

---

## 13. 本计划的近期下一步（补充）

在真正修改仓库内 `Squad` 相关文件前，先完成以下阅读闭环：

1. 深读 `C:\Users\xiao\Downloads\squad\squad-0.9.4\` 的入口链路。
2. 对照 `C:\Users\xiao\Downloads\squad\squad-0.7.6 (1)\squad-0.7.6\`，明确哪些能力属于 bridge，哪些应被官方能力替代。
3. 视需要补读 `claude-squad-1.0.17/` 或 `Proma-0.9.8/`，只提取监督视图 / 产品交互层启发，不改变主架构判断。
4. 在此基础上，再回到本仓库修改 `.github/agents/squad.agent.md`，避免边看边改导致架构判断漂移。

---

## 14. 功能性识别标注索引（按项目）

本轮已完成“逐项目功能识别标注”，每个项目均有对应 `功能性识别.md` 文件。

| 项目 | 标注文件路径 | 用途摘要 | 优先级 |
| --- | --- | --- | --- |
| squad-0.9.4 | `C:\Users\xiao\Downloads\squad\squad-0.9.4\功能性识别.md` | 原生 Squad 官方接入主参考（custom agent / subagent / CLI / SDK） | 高 |
| squad-0.7.6 (outer) | `C:\Users\xiao\Downloads\squad\squad-0.7.6 (1)\功能性识别.md` | 外层目录说明与内层项目跳转索引 | 中 |
| squad-0.7.6 (inner) | `C:\Users\xiao\Downloads\squad\squad-0.7.6 (1)\squad-0.7.6\功能性识别.md` | 多 terminal/SQLite 协作内核与 bridge 边界参考 | 中高 |
| claude-squad-1.0.17 | `C:\Users\xiao\Downloads\squad\claude-squad-1.0.17\功能性识别.md` | 会话监管、worktree 隔离、长跑管理视角参考 | 中 |
| Proma-0.9.8 | `C:\Users\xiao\Downloads\squad\Proma-0.9.8\功能性识别.md` | 产品化 Agent Teams 交互与记忆可视化参考 | 中 |
| run-agent-2.0.0 | `C:\Users\xiao\Downloads\squad\run-agent-2.0.0\功能性识别.md` | runner/message bus/工件留痕编排参考 | 中高 |
| spec-to-agents-main | `C:\Users\xiao\Downloads\squad\spec-to-agents-main\功能性识别.md` | 官方 coordinator-centric 编排与工具接入样例参考 | 中高 |
| continue-1.3.38-vscode | `C:\Users\xiao\Downloads\squad\continue-1.3.38-vscode\功能性识别.md` | source-controlled checks 治理侧参考 | 中 |
| Roo-Code-3.53.0 | `C:\Users\xiao\Downloads\squad\Roo-Code-3.53.0\功能性识别.md` | mode/MCP/扩展工程化参考 | 中 |
| Roo-Code-cli-v0.1.17 | `C:\Users\xiao\Downloads\squad\Roo-Code-cli-v0.1.17\功能性识别.md` | monorepo CLI + 扩展共存结构对照 | 中低 |
| RooFlow-0.5.6 | `C:\Users\xiao\Downloads\squad\RooFlow-0.5.6\功能性识别.md` | YAML prompt + memory bank + 模式协作参考 | 中 |
| Custom-Modes-Roo-Code-3.0.0 | `C:\Users\xiao\Downloads\squad\Custom-Modes-Roo-Code-3.0.0\功能性识别.md` | 大规模模式资产组织方法参考 | 中 |
| awesome-copilot-chatmodes-main | `C:\Users\xiao\Downloads\squad\awesome-copilot-chatmodes-main\功能性识别.md` | chatmode 文件范式与轻量分发参考 | 中 |

复核记录：`C:\Users\xiao\Downloads\squad\01-功能性识别复核记录.md`

维护规则：新增或移除参考项目时，同步更新本索引、复核记录与对应项目下的 `功能性识别.md`。

## 15. 执行记录（2026-04-27，Squad 0.9.3-modular）

本节记录本计划在 2026-04-27 的实际执行结果。所有改动均在本文件第 1—14 节批准范围内完成，未新增需要用户单独确认的大决策。

### Phase A（`squad.agent.md` 改写与静态收口）— 已完成

- **A-1** 将 `.github/agents/squad.agent.md` 从 `v0.9.2` 升级为 `v0.9.3-modular`，完成 6 处关键改动：
  1. 在文件头部加入“协调者职责（中文摘要 · 通用模板）”摘要段，落入 `DE1 + DD2 + DD5 + D4 + D7 + DE2` 的总入口说明。
  2. 将旧的 CLI parity 规则替换为 `LONG-RUN HANDOFF RULE`，明确 `D7=B`：长跑统一改走 Copilot CLI Sessions。
  3. 将 `Repo-Local Hardening Overlay` 重写为可跨工程复用的模板版，纳入 `DD6=B + DE2 占位符 + DC5/DC5a + DD4 + DD5 + HR1-HR6 + DE3`。
  4. 在 routing 相关段落补入 `D4=B`（Plan 自动路由）与 `D7=B`（长跑 handoff）规则。
  5. 将 dispatch parity 相关说明改为 long-run handoff note，避免继续把本地 wrapper 当主路径。
  6. 在 MCP Integration 中补入 `DD2-revised`：GitHub MCP 写操作必须逐次征求用户确认。
  备份文件已保存为 `.github/agents/squad.agent.md.bak.20260427`。
- **A-2** `/plan` 自动路由已在 `squad.agent.md` 头部与 routing 语义中落地。
- **A-3** 在 `.squad/routing.md` 末尾追加 `Coordinator Auto-Routing Rules (D4=B + D7=B + DD2)`。
- **A-4** 将 `tools/squad/squad.ps1` 退役为 `.deprecated`，并新增 `tools/squad/README-DEPRECATED.md` 说明 `D7=B` 下的退役原因与替代路径。
- **A-5** 从 `C:\Users\xiao\Downloads\squad\awesome-copilot-chatmodes-main\chatmodes\` 全量吸收 17 个 `*.chatmode.md` 到 `.github/chatmodes/`（即 `DB1=B` 的落地结果）。
- **A-6** 在 `.github/copilot-instructions.md` 末尾追加 `Squad 0.9.3-modular Decision Map (2026-04-27)`，覆盖 `D4 / D7 / DD2 / DD4 / DD5 / DD6 / DE1 / DE3 / DE4` 的映射关系。
- **A-7** 本计划文件完成首轮执行记录落盘。

### Phase B（chat mode 静态吸收）— 已完成

- **DB1=B**：17 个 chatmodes 已全量吸收入 `.github/chatmodes/`，对应 Phase A 的 A-5。
- **DB2—DB7=A***：相关约束已并入 `squad.agent.md` 的协调者表达与路由规则中，无需另起脚本层。

### Phase C（ghost detection）— 已完成

- **DC5**：新增 `tools/squad/check-ghost.ps1`，用于检查 owner PID、lock、cmdline、heartbeat 的 ghost-running 情况。
- **DC5a=B**：支持发现 ghost 后自动清理，并强制写入 `.squad/orchestration-log/{ts}-ghost-cleanup.md` 留痕。
- `DC1—DC4 / DC6 = A*` 的治理语义已吸收入 `squad.agent.md` 的 `Repo-Local Hardening Overlay`。

### Phase D（治理 / profile / MCP）— 已完成

- **DD2-revised**：已在 A-1 / A-3 / A-6 的改动中完成落地。
- **DD4**：新增 `tools/squad/profile-version-check.ps1`，用于校验 `{{OWNER_PROFILE}}` 的版本兼容性；不通过时 hard stop。
- **DD5**：新增 `.github/prompts/squad-doctor.prompt.md`，作为协调者启动自检入口，覆盖 routing / agent / chatmodes / profile / HR1-HR6。
- **DD6=B**：已通过 `squad.agent.md` 与 `.squad/routing.md` 的占位符模板化完成通用化改造。
- `DD1 / DD3 = A*` 的主体要求已纳入 `squad.agent.md`。

### Phase E（验证）— 已完成

- **DE1 / DE2 / DE3**：已在 A-1 中落入 `squad.agent.md` 的启动与长跑规则。
- **DE4**：已通过 A-6 写入 `.github/copilot-instructions.md`。
- **DE5**：新增 `tools/squad/smoke-test.ps1`，用于自动检查 routing / agent / chatmodes / squad-doctor 等链路是否可用。

### 首轮修复收口

首轮新增的 4 个关键工件：

- `tools/squad/check-ghost.ps1`
- `tools/squad/profile-version-check.ps1`
- `.github/prompts/squad-doctor.prompt.md`
- `tools/squad/smoke-test.ps1`

这 4 个文件均已创建并纳入后续总检流程，作为 `D17 / D14` 相关自检与治理的基础工件。

## 16. 2026-04-27 总检结果（门禁复核增补）

### 16.1 启动包预检结果

- `tools/squad/smoke-test.ps1`：**PASS**（5/5）
- `tools/squad/profile-version-check.ps1`：**PASS**（画像版本 `v4`）
- `tools/squad/check-ghost.ps1`：初检发现 1 个 stale lock，已按 DC5a 自动清理并留痕；复检 **PASS**
- `squad-doctor.prompt.md`：**存在**

对应证据：

- `.squad/orchestration-log/20260427T124457Z-ghost-cleanup.md`
- `tools/squad/smoke-test.ps1`
- `tools/squad/profile-version-check.ps1`
- `.github/prompts/squad-doctor.prompt.md`

### 16.2 六段总检结论

| 段 | 结果 | 结论 |
| --- | --- | --- |
| 1 唯一主入口 | **未通过** | `Claude Squad` 仍作为独立 custom agent 存在，且适配层文案仍会制造第二入口感知 |
| 2 Plan 主路径 | **通过** | `Squad` 已声明 D4=B 自动 `/plan` 路由 |
| 3 subagent 组织 | **部分通过** | `runSubagent` 规则存在，但未见明确 `agents:` 白名单落地 |
| 4 CLI handoff | **部分通过** | `Squad` 已声明 D7=B；但 `Claude Squad` 仍优先引用已退役 `tools/squad/squad.ps1` |
| 5 prompts / skills 收口 | **部分通过** | skills 与 chatmodes 已具备，但 `.github/prompts/prompts.md` 仍是伪 prompt file |
| 6 hooks / diagnostics 治理 | **未通过** | `.github/hooks/` 目录与最小 hook 配置尚未落地 |

### 16.3 当前判断

本次总检结论是：**可启动，但未通过完整升级门禁**。

含义：

- 启动包级别自检已经可用，可以安全进入下一轮修复。
- 但 `Squad` 控制面仍有 3 个结构性阻塞，不应宣称“升级门禁全绿”：
  1. `Claude Squad` 适配层仍残留旧 wrapper 路径，并继续形成第二入口感知
  2. `.github/prompts/prompts.md` 尚未迁移为正式 `.prompt.md`
  3. `.github/hooks/` 的最小治理配置尚未建立

### 16.4 下一步最小修复切片

以下 3 项属于结构性阻塞修复，默认由协调者自决推进；只要不触及人工审批硬边界，不再额外征求“是否继续”。

1. 修 `claude-squad.agent.md`：去掉对退役 `tools/squad/squad.ps1` 的优先依赖，收紧为 adapter-only
2. 迁移 `.github/prompts/prompts.md`：拆成正式 `.prompt.md` 文件或并入 skill / instructions
3. 建最小 `.github/hooks/squad-governance.json`：先把 SessionStart / PreToolUse / SubagentStop 三个事件接上
4. 完成后重跑本文件总检，再决定是否进入下游项目构建计划

## 17. 2026-05-01 T5 修补与 Phase A 验收回填

### 17.1 本轮执行边界

- 本轮只修补用户指出的 gap：`T5 prompts / skills 拆分不彻底` 与 `Phase A 验收未落 inbox`。
- 未触碰 `.env`、secrets、provider routing、corpus/goldset、外部账号配置或产品运行链路。
- 写入前已建立回档点：`.rollback_snapshots/codex-squad-t5-fix-20260501_002824`。
- 对标官方 / 成熟方案：VS Code Prompt Files、VS Code Agent Skills、仓库常驻 `.github/copilot-instructions.md` 规则，以及本仓既有 `.github/skills/*/SKILL.md` 结构。

### 17.2 T5 prompts / skills 拆分结果

| 项 | 状态 | 证据 |
| --- | --- | --- |
| 下线伪 prompt file | **完成** | `.github/prompts/prompts.md` 已重命名为 `.github/prompts/prompts.md.deprecated`，并写明不得继续追加新指令 |
| 迁移常驻项目规范 | **完成** | `.github/copilot-instructions.md` 新增 `Scholar AI Project Conventions`，承接原 `prompts.md` 的项目结构、编码纪律、API / error handling、ML 变更约束 |
| 新增 Plan prompt | **完成** | `.github/prompts/squad-plan.prompt.md`，使用 `agent: plan`，规定 rollback、成熟方案对标、任务表和 open decision 输出 |
| 新增 startup skill | **完成** | `.github/skills/squad-startup-packet/SKILL.md`，负责 TEAM_ROOT、startup packet、rollback、成熟方案、三脚本自检和 safe next action |
| 新增 CLI handoff skill | **完成** | `.github/skills/squad-cli-handoff/SKILL.md`，负责 Copilot CLI Sessions handoff packet，不复活 `squad.ps1` |
| 更新 squad-doctor | **完成** | `.github/prompts/squad-doctor.prompt.md` 从 5 checks 扩为 6 checks，新增 prompt/skill split 检查 |
| 更新 smoke-test | **完成** | `tools/squad/smoke-test.ps1` 从 5 checks 扩为 6 checks，新增 `prompt-skill-split` 检查 |

### 17.3 Phase A 验收结果

本轮已执行脚本验收，并把结果落入 `.squad/decisions/inbox/codex-2026-05-01-squad-t5-phasea-signoff.md`。这里的“签字”是执行验收记录，不伪造最终人工 gate pass；若后续需要 release 级确认，仍由用户或独立 reviewer 显式确认。

| 验收项 | 命令 | 结果 |
| --- | --- | --- |
| smoke / squad-doctor scripted check | `powershell -NoProfile -ExecutionPolicy Bypass -File tools\squad\smoke-test.ps1` | **PASS**：`SMOKE: OK (6/6)` |
| owner profile version | `powershell -NoProfile -ExecutionPolicy Bypass -File tools\squad\profile-version-check.ps1` | **PASS**：`version=v4` |
| ghost detection | `powershell -NoProfile -ExecutionPolicy Bypass -File tools\squad\check-ghost.ps1` | **PASS**：`OK: no ghosts detected.` |
| startup skill validation | `.venv-1\Scripts\python.exe C:\Users\xiao\.codex\skills\.system\skill-creator\scripts\quick_validate.py .github\skills\squad-startup-packet` | **PASS**：`Skill is valid!` |
| CLI handoff skill validation | `.venv-1\Scripts\python.exe C:\Users\xiao\.codex\skills\.system\skill-creator\scripts\quick_validate.py .github\skills\squad-cli-handoff` | **PASS**：`Skill is valid!` |

### 17.4 更新后的门禁判断

| 段 | 更新后结果 | 说明 |
| --- | --- | --- |
| 1 唯一主入口 | **通过** | `claude-squad.agent.md` 已是 adapter-only，且不再引用退役 `tools/squad/squad.ps1` |
| 2 Plan 主路径 | **通过** | D4=B 已固化；新增 `.github/prompts/squad-plan.prompt.md` 作为 repo-specific Plan 包装 |
| 3 subagent 组织 | **部分通过** | 既有专业 agents 可用；是否需要更严格 `agents:` 白名单仍待真实 VS Code custom agent diagnostics 验证 |
| 4 CLI handoff | **通过** | D7=B 已固化；新增 `.github/skills/squad-cli-handoff/SKILL.md`；`squad.ps1` 保持 `.deprecated` |
| 5 prompts / skills 收口 | **通过** | `prompts.md` 已下线；`squad-plan`、`squad-doctor`、`squad-round`、startup skill、handoff skill 已齐 |
| 6 hooks / diagnostics 治理 | **部分通过** | `.github/hooks/squad-governance.json` 存在；真实 VS Code hook 触发仍需宿主 Diagnostics 或实际事件验证 |

### 17.5 Open / Next

- **Closed**：用户已在 2026-05-01 chat 中以“能跑就能签收”确认 Phase A 五段验收可签收；`.squad/decisions/inbox/copilot-2026-05-01-phasea-user-signoff.md` 已将 Plan B 标记为 `gate-passed (signed off)`。
- **Closed**：`copilot-smoke-test-2026-05-01.md` 已修正 HR1 假阴性，确认 `.squad/tools/pool_append.py` 实际存在并具备 lock / SHA-256 dedup last-50 / G1 size-must-grow / G3 safe-floor / atomic replace。
- **Residual observation**：`.github/hooks/squad-governance.json` 已存在；SessionStart / PreToolUse / SubagentStart-Stop 的宿主级真实触发仍留作未来长跑时观察，不阻塞 Plan B gate-passed。
- **Next**：Plan B 不再阻塞下游主线。后续优先回到 `.kilo/plans/2026-04-27-full-project-build-master-plan.md` 的 TASK-192 / 前端 E2E runner 稳定化，或回到 `.copilot-tracking/plans/2026-04-21-cost-and-defaults.md` 的剩余手动闭环项。
