# 微信 → Codex → RAG 项目自动执行 架构记录

- 日期：2026-04-30
- 状态：可用态（手动），已固化项目 cwd + 三 CLI 权限；待验证自然语言派活/署名
- 范围：本机 Windows，单用户

## 1. 现状链路（已跑通）

```text
微信 (a8afe90eb6b1-im-bot)
  └─► weixin-agent-gateway 1.0.6  (~/.openclaw/extensions/weixin-agent-gateway)
        └─► OpenClaw Gateway  ws://127.0.0.1:18789
              └─► ACP subprocess backend  (cwd: C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script)
                    ├─► codex-acp  → codex CLI 0.123.0
                    ├─► claude-agent-acp → Claude Code 2.1.121
                    └─► copilot --acp --stdio --allow-all → Copilot CLI 1.0.36
```

证据：

- 微信发 `/codex` + `1+1` 收到 `2`（用户截图，2026-04-30）。
- `openclaw gateway run --force` 日志：`[gateway] ready`、`starting weixin provider` for account `a8afe90eb6b1-im-bot`。
- `codex --version` → `codex-cli 0.123.0`。

## 2. 关键路径与配置

| 项 | 值 |
| --- | --- |
| OpenClaw 主配置 | `C:\Users\xiao\.openclaw\openclaw.json` |
| 插件 state dir（账号凭证） | `C:\Users\xiao\.openclaw\openclaw-weixin\accounts\` |
| 后端选择持久化 | `C:\Users\xiao\.openclaw\openclaw-weixin\backend-selection.json` |
| Backend cwd（启动脚本设置） | `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script` |
| Gateway 端口 | `127.0.0.1:18789` |
| 项目根（plan 真正所在） | `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script` |
| 现有 plan 目录 | `.kilo\plans\` |
| 手动启动脚本 | `tools\openclaw\start-wechat-gateway.ps1` |

## 3. 让三个 backend 看到项目 plan 的方案

已采用：在 `tools\openclaw\start-wechat-gateway.ps1` 启动 OpenClaw Gateway 前设置 weixin-agent-gateway 支持的 ACP 环境变量，而不是直接改 OpenClaw 全局 workspace。

脚本设置：

| 变量 | 值 |
| --- | --- |
| `WEIXIN_CODEX_ACP_CWD` / `CODEX_ACP_CWD` | 项目根 |
| `WEIXIN_CLAUDE_ACP_CWD` / `CLAUDE_ACP_CWD` | 项目根 |
| `WEIXIN_COPILOT_ACP_CWD` / `COPILOT_ACP_CWD` | 项目根 |
| `WEIXIN_COPILOT_ACP_ARGS` / `COPILOT_ACP_ARGS` | `--acp --stdio --allow-all` |
| `WEIXIN_ANTIGRAVITY_CWD` / `ANTIGRAVITY_CWD` | 项目根 |
| `WEIXIN_ANTIGRAVITY_BIN` | `C:\Users\xiao\AppData\Local\Programs\Antigravity\Antigravity.exe` |
| `WEIXIN_*_ACP_PERMISSION_MODE` | `auto` |

这样微信中 `/codex`、`/claude`、`/copilot` 都能以项目根为工作目录，直接看到 `.kilo\plans\`、`.squad\`、`output\` 等项目内约定路径。`/antigravity` 是实验性本机窗口后端：它会把微信任务投递到 Antigravity chat 窗口，不承诺把 Antigravity 的回答自动回写微信群。

风险：三个 CLI 都会在该目录下读写文件、执行命令；当前用户已明确要求“权限都打开”。执行长跑前仍建议确认 git 分支/工作树状态，避免误改难回滚。

## 3.1 三 CLI 权限状态

| CLI | 已落地设置 | 证据/位置 |
| --- | --- | --- |
| Codex（微信 isolated） | `approval_policy = "never"` + `sandbox_mode = "danger-full-access"` + Windows elevated + 项目 trusted | `C:\Users\xiao\.openclaw\acpx\codex-home\config.toml` |
| Codex（用户级） | 同上，同时保留现有 custom provider/model | `C:\Users\xiao\.codex\config.toml` |
| Claude Code | 项目 local 已是 `permissions.defaultMode = "bypassPermissions"`；用户级也补了同配置 | `.claude\settings.local.json`、`C:\Users\xiao\.claude\settings.json` |
| Copilot CLI | 项目根加入 trustedFolders；微信 ACP 启动参数加 `--allow-all` | `C:\Users\xiao\.copilot\config.json`、启动脚本 env |

## 3.2 CLI 模型选择状态

用户反馈“第一句返回像是不是 5.5 / 我没设置模型”。排查与处理结果：

- 曾确认当前 VS Code/Copilot Chat 调试日志 `main.jsonl` 中最近请求是 `llm_request name=chat:gpt-5.5`，`attrs.model="gpt-5.5"`。
- 曾确认用户级 Codex 配置 `C:\Users\xiao\.codex\config.toml` 含 `model = "gpt-5.5"` 与 `model_provider = "custom"`。
- 2026-04-30 已移除 Codex 用户级 `model = "gpt-5.5"`，保留 `model_provider = "custom"` 与 ccswitch/本地代理 `base_url = "http://127.0.0.1:15970/v1"`。
- 2026-04-30 已移除 Claude 用户级 `"model": "opus[1m]"`，保留 `ANTHROPIC_BASE_URL = "http://127.0.0.1:15970"`、`ANTHROPIC_API_KEY = "PROXY_MANAGED"` 与权限配置。
- OpenClaw Codex ACP isolated config 当前没有固定 `model` 字段；Copilot CLI 配置也没有固定 `model` 字段。

因此现在 CLI 层面不再硬编码具体模型；模型由 CLI 交互参数、ccswitch/本地代理路由、或 VS Code/Copilot Chat 当前选择决定。ccswitch 第三方 API 登录不受影响，因为本次没有改 provider/base_url/API key 占位，只删除固定模型名。

## 4. 让网关常驻（开机自启）

当前 `openclaw gateway run --force` 是前台进程，关终端就停。需要做一次：

```powershell
# 必须管理员 PowerShell
openclaw gateway install
```

之前失败原因：`schtasks create failed: 拒绝访问`（非管理员）。

兜底方案：保留前台终端不关；或用 `nssm` 把 `openclaw gateway run` 注册成 Windows 服务。

## 4.1 手动启动（当前最稳）

若暂时不用开机自启，建议直接在仓库根目录执行：

```powershell
.\tools\openclaw\start-wechat-gateway.ps1
```

若只想先看脚本会做什么，不真正启动：

```powershell
.\tools\openclaw\start-wechat-gateway.ps1 -DryRun
```

脚本内部实际执行的仍是以下顺序：

```powershell
openclaw config set gateway.mode local
openclaw config set gateway.bind loopback
openclaw gateway run --force
```

说明：

- 第 1、2 行是幂等自愈（重复执行安全），用于规避偶发的 `missing gateway.mode` 阻断。
- 第 3 行成功后应出现 `[gateway] ready`，并继续看到 weixin provider 启动日志。
- 启动前会把 Codex/Claude/Copilot 三个 ACP backend 的 cwd 固定到项目根，并为 Copilot ACP 加 `--allow-all`。
- 脚本会检查 `C:\Users\xiao\.openclaw\openclaw-weixin\accounts\` 下是否已有持久化账号痕迹；若已存在，通常**不需要每次重新扫码**，除非微信会话本身过期。

## 4.2 手动关闭（当前已验证）

`18789` 是 OpenClaw gateway 的默认端口。若 `netstat` 显示 `LISTENING`，先取 PID，再按 PID 关闭：

```powershell
netstat -ano | findstr :18789
Stop-Process -Id <PID> -Force
```

本机已验证：监听进程曾为 `PID 5572`、`node.exe`；`Stop-Process -Id 5572 -Force` 后，`netstat` 不再显示 `18789`。

验证是否关闭：

```powershell
netstat -ano | findstr :18789
```

如果没有 `LISTENING`，gateway 已关闭；如果完全没有输出，说明端口也没有残留连接行。

注意：本机 `Get-NetTCPConnection` / `taskkill` 曾出现卡住或 `关键错误`，排障时优先使用 `netstat` + `Stop-Process`。

## 5. 自动按 plan 执行的微信触发协议

### 5.1 自然语言一键唤醒（本机已加本地路由补丁）

现在可以在微信里直接发送：

```text
copilot进入squad
```

本地 `weixin-agent-gateway` 补丁会把它识别为自然语言路由：

1. 自动把当前微信会话 backend 切到 `copilot`。
2. 自动把触发语重写为 RAG 项目构建启动提示词。
3. 要求 Copilot 以 `【Copilot-Squad】` 身份回复，并进入协作沟通 + 自决策模式。
4. 要求启动后先读 `.kilo/plans/` 与最近执行记录，再继续执行。

同类自然语言入口：

```text
codex进入squad
claude进入squad
antigravity进入squad
codex进入项目构建
claude进入项目构建
antigravity进入项目构建
```

也支持“像聊天一样点名派活”，不必先发 `/backend`：

```text
copilot把计划再构建一下，需要决策现在问
copilot：继续读 master plan，执行下一项安全任务
让codex检查为什么评测失败
claude复盘最近执行记录并给我阻塞简报
antigravity检查当前方案
```

路由规则：

| 说法 | 路由到 |
| --- | --- |
| `copilot...` / `让copilot...` / `github copilot...` | Copilot backend |
| `codex...` / `让codex...` | Codex backend |
| `claude...` / `让claude...` / `claude code...` | Claude Code backend |
| `antigravity...` / `让antigravity...` / `google antigravity...` | Antigravity 本机 chat 后端 |
| 不点名 | 沿用当前微信会话已选 backend |

模型/思考模式说明：

```text
copilot使用Claude4.7最大思考模式
```

这句话会被路由到 Copilot，并作为“模型/推理偏好”写进提示词；AI 必须先判断当前 CLI / 网关 / ccswitch 是否真的支持该模型或思考级别，不允许假装已经切换。

当前已确认 Copilot CLI 有 `--model <model>` 与 `--reasoning-effort <low|medium|high|xhigh>` 参数；但微信 ACP backend 的启动参数是在 gateway 启动时固定的，所以**单条微信消息不能保证热切换模型**。若要强制默认模型/最大思考，需要在启动脚本的 `WEIXIN_COPILOT_ACP_ARGS` / `COPILOT_ACP_ARGS` 中加入对应参数并重启 gateway；否则它只是本轮任务偏好。

### 5.2 `@所有人` 广播启动

如果要让 Copilot、Codex、Claude、Antigravity 四个 backend 都收到同一条开场任务，直接发：

```text
@所有人 开场启动，读取主计划和最近执行记录，按 RAG 项目构建目标协作推进；需要决策现在问，需要外部方案时先联网检索。
```

也支持英文/简写：

```text
@all review the current build plan and start from the next safe task
@ai 开场启动，先读计划，再读最近执行记录
```

广播会并发 fan-out 给四个后端：

| 后端 | 默认角色 |
| --- | --- |
| Copilot | 协调者/执行入口：整合计划与最近记录，选下一项安全任务，需要决策立刻问用户 |
| Codex | 实现/验证顾问：检查代码、测试、命令可行性，避免和其他 AI 并发改同一文件 |
| Claude Code | 架构/风险复盘顾问：审查计划一致性、遗漏决策、风险和执行记录完整性 |
| Antigravity | 实验席位：通过本机 Antigravity chat 窗口接收任务；若不能直接回群，应在窗口内产出可复制结果或共享文件记录 |

`@所有人` 广播提示词会自动带上以下路径：

| 项 | 路径 |
| --- | --- |
| 项目根 | `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script` |
| 主计划 | `.kilo\plans\2026-04-27-full-project-build-master-plan.md` |
| 计划目录 | `.kilo\plans\` |
| 执行记录 | `.squad\orchestration-log\` |
| 决策收件箱 | `.squad\decisions\inbox\` |
| 审计/异常 | `.squad\audits\` |
| 运行产物 | `output\` |
| 团队参考 | `.squad\identity\start-here.md`、`.squad\routing.md`、`.squad\team.md`、`.github\agents\squad.agent.md` |
| 微信网关记录 | `docs\superpowers\specs\2026-04-30-wechat-codex-rag-design.md` |

联网规则也会写进提示词：需要外部方案/API/依赖信息时，优先使用当前 CLI 可用的 web/search/browser/fetch 工具；若该 CLI 没有联网工具，可用安全的 shell/curl/python 请求公开网页；仍不可用时必须在简报中说明限制。

注意：`@所有人` 不是“AI 之间直接聊天”。当前实现是**网关 fan-out**：同一条微信消息会并发发给 Copilot、Codex、Claude、Antigravity；它们通过 `.squad/` 共享文件协作，不假设 CLI 之间有直接通信能力。Antigravity 当前是本机窗口投递，不是 ACP/stdio 自动回群后端。

补充：为避免重启后把聊天群里的历史消息重新喂给 AI，网关现在会默认忽略**群聊中超过 10 分钟的旧消息**；私聊消息不受这个过滤影响。如需调整阈值，可设置环境变量 `WEIXIN_STALE_GROUP_MESSAGE_MAX_AGE_MS`（单位毫秒）。

### 5.3 微信可复制启动提示词（不依赖本地补丁时使用）

如果网关被升级导致本地补丁丢失，先发 `/copilot`，再发下面这段：

```text
你现在通过微信进入【Copilot-Squad】自决策协作模式。
目标：按本仓库现有计划推进 RAG 项目构建，不做脱离计划的发散开发。
启动必读：先读取 .kilo/plans/，再读取最近的 .squad/orchestration-log/、.squad/decisions/inbox/、.squad/audits/ 与 output/ 记录。
执行记录：阶段简报写入 .squad/orchestration-log/；自决策写入 .squad/decisions/inbox/；审计/异常写入 .squad/audits/；运行产物写入 output/。
沟通规则：每条微信回复首行必须以【Copilot-Squad】开头；启动、阶段完成、阻塞、风险、最终结果都发微信简报。
自决策规则：在已授权范围内自动推进，跑完一步自动下一步；仅在破坏性操作、外部付费/预算、密钥/账号、不可逆删除、或计划冲突时停下请示。
微信简报必须固定为 3~6 行，首行身份前缀，后续用 Facts / Decisions / Open / Next，不要刷屏。
启动简报模板：【Copilot-Squad】启动｜Facts: 已读计划/记录；Decisions: 本轮目标；Open: 当前风险；Next: 下一步。
进展简报模板：【Copilot-Squad】进展｜Facts: 完成项+证据路径；Decisions: 自决策；Open: 未决/风险；Next: 下一步。
阻塞简报模板：【Copilot-Squad】阻塞｜Facts: 阻塞事实；Decision needed: 需要用户拍板项；Evidence: 证据路径；Safe next action: 安全下一步。
完成简报模板：【Copilot-Squad】完成｜Facts: 结果；Artifacts: 产物路径；Verification: 验证结果；Next: 后续建议。
现在开始：读取 active plan 和最近执行记录，给我第一条启动简报，然后执行下一步安全任务。
```

### 5.4 微信简报固定格式

所有通过微信返回的工作介绍/进展都使用短简报，不写长报告。固定四类：

```text
【Copilot-Squad】启动
Facts: 已读取 <plan路径>；最近记录 <log路径>。
Decisions: 本轮按 <任务/阶段> 推进。
Open: 当前风险/缺口；没有则写“无”。
Next: 立即执行的下一步。
```

```text
【Copilot-Squad】进展
Facts: 已完成 <动作>；证据 <文件/命令结果>。
Decisions: 已自决策 <决策>；原因 <一句话>。
Open: 未决/风险；没有则写“无”。
Next: 下一步动作。
```

```text
【Copilot-Squad】阻塞
Facts: 阻塞事实 <一句话>。
Decision needed: 需要你拍板 <选项/问题>。
Evidence: 证据路径/错误摘要。
Safe next action: 不越权时能做的安全下一步。
```

```text
【Copilot-Squad】完成
Facts: 完成结果 <一句话>。
Artifacts: 产物路径 <文件/目录>。
Verification: 验证命令/结果；未跑则说明原因。
Next: 后续建议/下一入口。
```

### 5.5 回答者署名

本机 `weixin-agent-gateway` 出站层已加本地前缀补丁：

| Backend | 微信回复前缀 |
| --- | --- |
| Copilot | `【Copilot-Squad】` |
| Codex | `【Codex】` |
| Claude | `【Claude-Code】` |
| OpenClaw | `【OpenClaw】` |

注意：这是安装目录下的本地 OSS 插件补丁，后续执行 `npx -y @bytepioneer-ai/weixin-agent-gateway install` 或插件升级可能覆盖；如覆盖，需要重放本节对应改动。

一条消息搞定（方案 A 配置后）：

```text
/codex
读取并严格执行 .kilo/plans/2026-04-27-full-project-build-master-plan.md。
执行规则：
1. 按 plan 顺序推进，每完成一个 TASK 就把状态写回该文件。
2. 遇到需要长跑/付费/破坏性操作时停下，按 Facts/Decision needed/Evidence/Safe next action 回报。
3. 跑完一阶段不要等我确认，自动进入下一阶段（与 repo memory workflow 偏好一致）。
4. 所有产物写到 output/ 或 .squad/orchestration-log/，不要污染源代码。
```

多后端切换：

```text
/backend codex
/backend claude
/backend copilot
```

或直接：

```text
/codex
/claude
/copilot
```

注意：`weixin-agent-gateway` 当前 README 原生只列出 slash/backend 命令；“copilot进入squad”这类自然语言 alias 是本机安装目录里的本地补丁能力，插件升级后需要复核。

## 6. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| codex 误改源码 | 切到独立分支后再开 backend；或方案 B + symlink + 只读策略 |
| Gateway 宕机无感 | `gateway install` + Windows 计划任务监控；定期 `curl ws://127.0.0.1:18789` |
| 微信号被风控 | 不发刷屏指令；保留 `openclaw channels logout` 为 kill switch |
| `gpt-5.5` 与预期不一致 | CLI 配置中已移除 Codex/Claude 固定模型字段；若仍出现 `gpt-5.5`，优先检查 VS Code Copilot 模型选择器、启动命令参数、或 ccswitch/本地代理路由规则。 |

## 7. 待办（按优先级）

1. 微信验证：发 `@所有人 开场启动，读取主计划和最近执行记录，按 RAG 项目构建目标协作推进`，确认三后端都回复。
2. 微信验证：发 `copilot进入squad`，确认自然语言路由、署名、启动简报是否符合预期。
3. 微信验证：分别发 `/codex`、`/claude`、`/copilot`，确认 cwd、权限、署名是否符合预期。
4. 如需强制 Copilot 默认模型/最大思考，在启动脚本中追加 `--model` / `--reasoning-effort xhigh` 后重启 gateway。
5. 管理员重跑 `openclaw gateway install` 实现开机自启。
6. 如需多账号/路由（不同前缀打到不同 backend），后续再扩 `channels.weixin-agent-gateway.routes`。
