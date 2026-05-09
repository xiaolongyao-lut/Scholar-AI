# Upstream PR Proposal: Long-Run / Self-Supervision Primitives for `mco-org/squad`

**Target**:https://github.com/mco-org/squad(目前 0.7.6)
**Status**:Draft proposal,未提交
**Why upstream**:这些是"任何多 agent 协作工具都会需要"的内核能力,目前 squad 缺,各家私有方案重复造轮子。

---

## TL;DR

加 4 个新子命令到 squad:`daemon` / `lock` / `heartbeat` / `reaper`。它们是底层 primitive,不绑定任何 LLM 厂商或具体业务逻辑。Windows-first,Linux/macOS 用现成的 fork+setsid 实现。

## 动机

当前 `squad` 0.7.6 的能力:
- ✅ 任务队列(`task create/list/requeue`)
- ✅ 消息库(`history`)
- ✅ 角色组装(`teams`)
- ❌ **没有进程编排**:多 agent 启动后谁守护它们?谁 detect 卡死?谁防 PID recycle?
- ❌ **没有锁原语**:多终端并发用 squad 时容易写坏 messages.db / pool 文件
- ❌ **没有心跳协议**:agent "活着" 的判定只能看进程在不在,但等 LLM 响应的 agent CPU=0,看起来像死了

社区里(包括我们)都在用 shell/PowerShell 脚本外挂这些能力,导致:
- 无法跨平台(我们的 PowerShell 实现在 Linux 上跑不了)
- 升级 squad 时外挂逻辑容易 break
- 行为不一致(各家锁协议、心跳频率、熔断阈值都不同)

把这些做进 squad 内核,fs2 已经在依赖里了,加四个子命令成本很低。

## 提议的子命令

### 1. `squad daemon`

**用途**:把任意命令做成"守护进程",带自动重启 + 熔断 + 状态落盘。

```
squad daemon start --name <name> --cmd "<command>" \
    [--restart-window-min 5] \
    [--restart-limit 3] \
    [--circuit-cooldown-min 30]
squad daemon stop --name <name>
squad daemon list                              # 表格输出
squad daemon logs --name <name> --tail 200
```

**状态文件**:`.squad/state/daemons.json`(serde_json),记录每个 daemon 的 pid/started_at/restart_history。

**熔断**:5 分钟内重启 ≥3 次 → 暂停 30 分钟,exit 9 表明熔断触发。

### 2. `squad lock`

**用途**:跨进程互斥锁原语,JSON 元数据,带 stale 回收。

```
squad lock acquire <key> [--timeout-sec 30] [--purpose "<text>"] \
    [--exec "<command>"]                       # 拿到锁后执行,执行完自动释放
squad lock release <key>
squad lock list                                # 输出当前所有锁的 owner / 持锁时长
```

**锁文件**:`.squad/locks/<key>.lock`,内容 JSON:

```json
{
  "owner_pid": 12345,
  "started_at": "2026-04-26T10:00:00Z",
  "purpose": "morpheus-headless main loop",
  "host": "DESKTOP-XYZ"
}
```

**stale 回收**:owner 进程不存活,**或者** 持锁超过 `policy.execution_profile.auto_close_idle_seconds`(从 `casting-policy.json` 读,默认 120 秒)→ 强制释放。

**实现**:fs2::FileExt::try_lock_exclusive。

### 3. `squad heartbeat`

**用途**:agent 显式声明"我还活着",更新 marker 文件 mtime。

```
squad heartbeat <agent_id> [--metadata '{"phase": "querying"}']
```

**位置**:`.squad/autopilot-logs/live-agents/<agent_id>.json` 的 mtime 被 touch。

**为什么重要**:CPU idle 不能判断 agent 是否活着(等 LLM 响应时 CPU=0)。让 agent 自己每 20 秒打卡一次,reaper 用心跳过期判定,比 CPU idle 准。

### 4. `squad reaper`

**用途**:扫描所有 marker,kill 心跳过期的 agent,可选 requeue 它们的任务。

```
squad reaper [--once | --loop] \
    [--stale-min 10] \
    [--idle-min 30] \
    [--reassign-to <agent_id>]
```

**双门限**(都满足才 kill):
1. marker mtime > `stale-min`(心跳过期)
2. 进程 CPU 在 8 秒内消耗 < 0.3 秒(真的没在干活)
3. **或者** 跳过双门:marker mtime > `idle-min` 直接 kill(纯空闲超时)

**identity check**:kill 前验证 PID 名字 ∈ 白名单(可配置)+ 进程 StartTime 与 marker 记录的 wrapper_start_time 误差 ≤5 秒。防 PID recycle。

**requeue**:kill 后调 `squad task list --agent <id> --status in_progress` → `squad task requeue <task> --to <reassign>`。

## 不在本 PR 范围

- LLM 客户端调用(claude / openai / gemini)→ 用户应用层
- 角色 prompt(charter.md)→ 用户应用层(已有 `roles/*.md` 模板机制)
- RAG / 向量库 / eval 框架 → 完全是用户的事
- Windows GUI 窗口管理 → 选择性实现,Linux 用 nohup+setsid

## 兼容性

- 4 个新子命令,**不动现有命令的行为**
- 状态文件全部在 `.squad/`(已有目录),不污染用户项目
- 默认参数保守,不开 daemon/reaper 时行为与 0.7.6 完全一致

## 实现工作量估计

- `daemon`:~400 行 Rust,sysinfo 跨平台进程查询
- `lock`:~150 行,fs2 已经在依赖里
- `heartbeat`:~50 行,touch 文件 mtime
- `reaper`:~300 行,sysinfo CPU 采样

总计 ~900 行,2-3 天工作量(包括测试)。

## 参考实现

我们的 PowerShell overlay 在以下位置(可作为行为参考,不能直接照抄因为 Windows-only):

- `tools/squad/supervisor.ps1` ← daemon 等价
- `tools/squad/squad-cleanup.ps1` ← lock 回收逻辑
- `tools/squad/spawn-agent.ps1` ← heartbeat 写入端
- `tools/squad/kill-stuck-agent.ps1` ← reaper 等价

## 提交流程建议

1. 先开 issue 描述需求,不直接 PR
2. 等维护者表态(同意方向 / 拒绝 / 要求拆分)
3. 同意后分 4 个 PR 提:lock → heartbeat → daemon → reaper(依赖顺序)
4. 每个 PR 自带集成测试

## 风险

- 维护者可能认为 daemon 编排"不属于 squad 职责",要求剥到独立 binary。如此则我们的 squad-pro 方案反而更合适。
- Windows 进程查询 sysinfo 在某些版本有 bug,可能要 fallback 到 windows-rs 直接 syscall。
- 心跳频率/熔断阈值的"合理默认值"会有 bikeshed,提案里全部允许 CLI 覆盖。
