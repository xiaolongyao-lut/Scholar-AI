# squad-pro 项目脚手架规范

**目的**:在不修改上游 `mco-org/squad` 0.7.6 源码的前提下,把 `tools/squad/*.ps1` 的自决策 + 长跑能力包成一个独立 Rust exe `squad-pro.exe`。

**给谁看**:让 GPT/Codex 按这份规范一次性生成完整项目,生成完直接 `cargo build --release` 即可。

---

## 1. 项目布局

```
C:\Users\xiao\Desktop\tools\squad-pro\
├── Cargo.toml
├── README.md
├── build.rs                          ← 构建期校验嵌入的 ps1 存在
├── src/
│   ├── main.rs                       ← clap 子命令分发
│   ├── embed.rs                      ← include_bytes! 嵌入 ps1,首次运行解压到 %LOCALAPPDATA%\squad-pro\
│   ├── lock.rs                       ← JSON 锁协议(owner_pid/started_at/purpose),stale 回收
│   ├── daemon.rs                     ← supervisor 等价物:看门狗 + 熔断 + 持久化重启历史
│   ├── reaper.rs                     ← kill-stuck-agent 等价物:心跳过期 + CPU idle 双门
│   ├── identity.rs                   ← PID 名字白名单 + StartTime 5s 容差(anti-recycling)
│   ├── proc_win.rs                   ← Windows 专属:Get-CimInstance 等价(用 windows-rs 或 sysinfo)
│   ├── policy.rs                     ← 读 .squad\casting-policy.json
│   └── cli.rs                        ← clap 定义
└── ps1/                              ← 这 4 个文件 build.rs 检查存在性,src/embed.rs 用 include_bytes! 嵌入
    ├── morpheus-headless.ps1         ← 从 tools/squad/ 拷贝
    ├── supervisor.ps1                ← (运行时由 squad-pro daemon 子命令替代,但保留以备 fallback)
    ├── kill-stuck-agent.ps1          ← (同上,被 squad-pro reaper 替代)
    └── squad-cleanup.ps1             ← 这个保留,squad-pro cleanup 直接调它
```

## 2. Cargo.toml

```toml
[package]
name = "squad-pro"
version = "0.1.0"
edition = "2021"
license = "MIT"
description = "Self-decision and long-run wrapper around mco-org/squad"

[dependencies]
clap = { version = "4", features = ["derive"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
anyhow = "1"
chrono = { version = "0.4", features = ["serde"] }
fs2 = "0.4"
sysinfo = "0.30"          # 跨平台进程查询(Get-Process 等价)
dirs = "5"                # 拿 %LOCALAPPDATA%
uuid = { version = "1", features = ["v4"] }

[target.'cfg(windows)'.dependencies]
windows = { version = "0.54", features = [
    "Win32_System_Threading",
    "Win32_System_ProcessStatus",
    "Win32_Foundation",
] }

[profile.release]
strip = true              # exe 体积 <2MB
lto = true
```

**注意**:`squad-pro` 不依赖 `squad` 作为库——上游 0.7.6 是 binary crate(`main.rs`),不导出 lib。它通过 `Command::new("squad.exe")` 调用上游 squad,假设 `squad.exe` 在 `PATH` 或 `C:\Tools\squad\squad.exe`。

## 3. CLI 子命令

```
squad-pro long-run [--supervised] [--max-rounds N] [--round-sleep-sec 1200]
squad-pro daemon start --name <name> --script <path> [--restart-window-min 5] [--restart-limit 3]
squad-pro daemon stop --name <name>
squad-pro daemon list
squad-pro lock acquire <key> [--timeout-sec 30] [--purpose "<text>"]
squad-pro lock release <key>
squad-pro lock list
squad-pro heartbeat <agent_id>
squad-pro reaper [--once] [--stale-min 10] [--idle-min 30]
squad-pro cleanup [--nuke] [--dry-run]
squad-pro spawn <role> "<reason>"
squad-pro doctor                           ← 自检:squad.exe 在不在 PATH、Rust 工具链版本、ps1 解压目录权限
```

## 4. 各模块行为规范

### 4.1 `src/embed.rs`

```rust
// 伪代码,GPT 生成时按这个意图实现
const MORPHEUS_HEADLESS_PS1: &[u8] = include_bytes!("../ps1/morpheus-headless.ps1");
const SQUAD_CLEANUP_PS1: &[u8] = include_bytes!("../ps1/squad-cleanup.ps1");
// ... 其他 ps1

pub fn extract_to_appdata() -> anyhow::Result<PathBuf> {
    let dir = dirs::data_local_dir()
        .ok_or_else(|| anyhow!("no LOCALAPPDATA"))?
        .join("squad-pro").join("ps1");
    std::fs::create_dir_all(&dir)?;
    // 原子写入:tmp + rename
    write_atomic(dir.join("morpheus-headless.ps1"), MORPHEUS_HEADLESS_PS1)?;
    write_atomic(dir.join("squad-cleanup.ps1"), SQUAD_CLEANUP_PS1)?;
    // ...
    Ok(dir)
}
```

每次启动校验 hash;如果嵌入版本比磁盘新则覆盖,旧则保留(便于用户本地热修)。

### 4.2 `src/lock.rs`

锁文件位置:`<project_root>\.squad\locks\<key>.lock`(JSON):

```json
{
  "owner_pid": 12345,
  "started_at": "2026-04-26T10:00:00Z",
  "purpose": "morpheus-headless main loop",
  "host": "DESKTOP-XYZ"
}
```

**acquire 行为**:
1. 用 `fs2::FileExt::try_lock_exclusive` 在 `<key>.lock` 上拿独占锁
2. 拿到后写 JSON 内容,文件描述符保留在 `acquire` 进程内,直到 `release` 或进程退出
3. 如果 `try_lock_exclusive` 失败,读 JSON 内容,检查 `owner_pid` 是否存活:
   - 不存活 → 这是 stale lock,强制删除文件后重试一次
   - 存活但 `started_at` 距今超过 `policy.execution_profile.auto_close_idle_seconds`(默认 120s)→ 同样视为 stale
   - 否则 → 返回 `LockBusy`
4. 注册 `ctrlc::set_handler` + Drop trait 确保进程异常退出时清理

### 4.3 `src/daemon.rs`

`squad-pro daemon start --name X --script Y`:
1. 创建 `<project_root>\.squad\state\X.lock`(普通 PID 锁,plain int 格式,与 supervisor.ps1 兼容)
2. spawn 子进程:`powershell.exe -NoExit -ExecutionPolicy Bypass -Command "$Host.UI.RawUI.WindowTitle = 'X'; & 'Y' <args>"`,WindowStyle Minimized
3. 把子进程 PID 写入 lockfile
4. 进入 watch loop(每 60s):
   - 三重 AND 检测:lockfile 存在 + PID 中的进程存活 + `MainWindowTitle == X`(用 windows-rs `EnumWindows` 查)
   - 任一失败 → 重启
5. 熔断:重启历史持久化到 `.squad\state\daemon-restart-history.jsonl`,5 分钟滑窗 ≥3 次 → 暂停 30 分钟,日志 WARN

`squad-pro daemon list` 扫描 `.squad\state\*.lock`,输出表格:name / pid / alive / window-title-match / 最近一次重启时间。

### 4.4 `src/reaper.rs`

`squad-pro reaper --once`:
1. 扫 `<project_root>\.squad\autopilot-logs\live-agents\*.json` marker
2. 对每个 marker 做四步检查(与 kill-stuck-agent.ps1 同语义):
   - PID 不存活 → 删 marker
   - marker mtime > `idle-min` **且** CPU idle(用 sysinfo 取 8 秒采样,delta<0.3 秒判定 idle)→ kill
   - 调 `squad.exe history <id> --json` 取最新消息时间,< `stale-min` → 跳过
   - marker `spawned_at` < `stale-min` → grace 期,跳过
   - 否则 → kill + `squad.exe task list --agent <id> --status in_progress` → `squad.exe task requeue <task_id> --to morpheus`
3. kill 前做 identity check:进程名 ∈ {powershell, pwsh, WindowsTerminal, wt, claude},`StartTime` 与 `marker.wrapper_start_time` 误差 ≤5s

**注意 C1 修正**:CPU idle 采样窗口 **8 秒**(不是 ps1 里的 2 秒),阈值 **<0.3 秒**(不是 1.0 秒),避免误杀等 LLM 响应的 agent。

### 4.5 `src/identity.rs`

```rust
pub struct ProcessIdentity {
    pub pid: u32,
    pub name: String,
    pub start_time: DateTime<Utc>,
}

const ALLOWED_NAMES: &[&str] = &[
    "powershell", "pwsh", "WindowsTerminal", "wt", "claude",
    "powershell.exe", "pwsh.exe", "WindowsTerminal.exe", "wt.exe", "claude.exe",
];

pub fn verify_identity(pid: u32, expected_start: Option<DateTime<Utc>>) -> Result<bool> {
    let actual = get_process_identity(pid)?;
    if !ALLOWED_NAMES.iter().any(|n| n.eq_ignore_ascii_case(&actual.name)) {
        return Ok(false);
    }
    if let Some(expected) = expected_start {
        let delta = (actual.start_time - expected).num_seconds().abs();
        if delta > 5 { return Ok(false); }
    }
    Ok(true)
}
```

### 4.6 `src/main.rs::long_run`

`squad-pro long-run --supervised`:
1. 解压 ps1 到 LOCALAPPDATA(embed::extract_to_appdata)
2. 自检:`squad-pro doctor` 内联调用,失败则 exit 2
3. spawn 4 个 daemon(用本进程的 daemon 模块,不再 fork ps1):
   - `spawn-watcher`(目前 .ps1,后续也可以改成 Rust)
   - `reaper`(直接调本进程的 reaper 模块,带 --loop)
   - `rag-eval-daemon`(项目独有,保留 ps1)
   - `morpheus-headless`(保留 ps1,因为它构造 round brief 的逻辑是项目独有)
4. 主进程不退,Ctrl+C 时调 cleanup 逻辑

## 5. 构建 & 安装

```powershell
cd C:\Users\xiao\Desktop\tools\squad-pro
cargo build --release
copy target\release\squad-pro.exe C:\Tools\squad\squad-pro.exe

# 加到 PATH(如果 C:\Tools\squad 已经在 PATH 就跳过):
[Environment]::SetEnvironmentVariable('PATH', $env:PATH + ';C:\Tools\squad', 'User')

# 启动
squad-pro long-run --supervised
```

## 6. 给 GPT 的执行指令

**复制下面这段**,贴给 GPT-4 / Claude(在能改 ps1 的会话里)/ Codex CLI:

> 我有一份《squad-pro 项目脚手架规范》在 `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\docs\squad-pro-scaffold-spec.md`。
> 请你按这份规范在 `C:\Users\xiao\Desktop\tools\squad-pro\` 创建完整 Rust 项目,要求:
> 1. 严格按规范的项目布局生成所有文件
> 2. ps1 文件从 `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\tools\squad\` 拷贝
> 3. `cargo build --release` 必须能直接通过,不要留 TODO
> 4. 跨模块的 anyhow::Result / sysinfo 用法保持一致
> 5. 完成后给我贴 `cargo build --release` 的输出和 `target/release/squad-pro.exe doctor` 的运行结果
> 完成后我会让另一个 Claude 审查你的代码。

## 7. 后续审查

GPT 写完后,把 diff 贴回 Claude Code 这边,我可以做 review(只读分析,不算 augment):
- 检查 lock.rs 的 stale recovery 是否真的 race-free
- 检查 reaper.rs 的 CPU 采样窗口是不是真的 8 秒(防止照抄 ps1 的 2 秒)
- 检查 identity.rs 的 ALLOWED_NAMES 是否完整
- 检查 daemon.rs 的熔断状态是否落盘

## 8. 已知风险 / 不在本规范范围

- **MainWindowTitle 检测仍然有竞态**:Windows 上窗口标题写入和进程启动有 100ms 级延迟。Rust 版应给 1.5 秒的 grace 期(daemon 首次检测延迟启动)。
- **squad.exe 必须在 PATH**:doctor 子命令负责检查,失败给明确报错。
- **不打算上游 PR**:这个 wrapper 不进 mco-org/squad。如要上游化,见 `squad-upstream-pr-proposal.md`(A2 输出)。
