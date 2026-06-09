# MCP Stdio 安全隔离声明

## ⚠️ 安全警告

**MCP stdio 子进程不是 OS 沙箱**。当前实现仅提供软约束，不能限制：
- **系统调用**
- **文件系统访问**（子进程继承用户权限）
- **网络连接**（可连接任意地址）

## 当前安全措施（软约束）

### ✅ 已实现的防护

1. **命令验证**
   - argv-only（禁止 shell 字符串）
   - 危险命令检测（rm、format、sudo 等）
   - 危险参数模式（rm -rf、物理磁盘路径等）

2. **环境变量隔离**
   - 仅传递显式允许的环境变量
   - PATH/SYSTEMROOT 等最小集合
   - 敏感值自动脱敏（日志）

3. **工作目录隔离**
   - 子进程 cwd 设置到 runtime_state 目录

4. **资源限制**
   - 启动超时：10 秒
   - 单次调用超时：20 秒
   - stdout 限制：1 MB
   - stderr 限制：256 KB

### ❌ 未实现的防护

**关键缺陷**：
- 子进程可读写用户所有文件
- 子进程可建立任意网络连接
- 子进程可执行任意系统调用

## 风险等级

| 场景 | 风险等级 | 说明 |
|------|---------|------|
| 官方 MCP 服务器 | 低 | 受信任的第一方代码 |
| 社区 MCP 服务器 | **高** | 不受控的第三方代码 |
| 用户自定义 MCP | **严重** | 完全不受信任的代码 |

## 用户确认要求

### 高风险 MCP 安装时必须显示

```
⚠️ 安全警告

您正在安装一个 MCP 服务器：{name}

当前隔离级别：仅软约束
- ❌ 无系统调用限制
- ❌ 无文件系统隔离
- ❌ 无网络访问限制

风险：
- 可读写您的所有文件
- 可访问任意网络地址
- 可执行系统命令

建议：
- 仅安装您完全信任的 MCP 服务器
- 审查源代码后再安装

确认安装？[是(Y)/否(N)]
```

## 强隔离选项（未实现）

### 选项 A: Windows Job Object
```python
import win32job

job = win32job.CreateJobObject(None, "")
limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
limits['ProcessMemoryLimit'] = 512 * 1024 * 1024  # 512 MB
limits['BasicLimitInformation']['LimitFlags'] = (
    win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY |
    win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
)
win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
win32job.AssignProcessToJobObject(job, process_handle)
```

### 选项 B: AppContainer (Windows)
```python
import subprocess
subprocess.Popen(
    cmd,
    creationflags=subprocess.CREATE_NO_WINDOW,
    # 需要额外的 AppContainer API 调用
)
```

### 选项 C: 低权限用户 (跨平台)
```bash
# 创建专用低权限用户
useradd -r -s /bin/false mcp-runner

# 在该用户下运行
sudo -u mcp-runner python mcp_server.py
```

### 选项 D: 容器隔离
```python
import docker
client = docker.from_env()
container = client.containers.run(
    "mcp-server-image",
    detach=True,
    network_mode="none",  # 禁止网络
    read_only=True,
    security_opt=["no-new-privileges"],
)
```

## 实施建议

### 短期（1 周内）

1. ✅ **文档警告** - 本文档
2. ⏳ **前端确认对话框** - MCP 安装时显示风险
3. ⏳ **MCP 信任级别** - 标记官方/社区/自定义

### 中期（1 个月内）

4. ⏳ **Windows Job Object** - 内存限制
5. ⏳ **网络访问日志** - 记录所有连接

### 长期（3 个月内）

6. ⏳ **AppContainer 支持** - Windows 强隔离
7. ⏳ **容器模式** - 可选的容器运行

## 相关文件

- 安全策略: `literature_assistant/core/mcp_runtime/security_policy.py`
- 客户端管理: `literature_assistant/core/mcp_runtime/client_manager.py`
- 安装路由: `literature_assistant/core/routers/mcp_installer_router.py`
- 本文档: `MCP_SECURITY_ISOLATION.md`

## 参考资料

- Windows Job Objects: https://docs.microsoft.com/en-us/windows/win32/procthread/job-objects
- AppContainer: https://docs.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation
- Linux seccomp: https://www.kernel.org/doc/Documentation/prctl/seccomp_filter.txt

---

**创建时间**: 2026-06-09
**基于审查**: 独立代码审查报告 - 高风险问题 #4
**状态**: 当前仅软约束，强隔离待实现
