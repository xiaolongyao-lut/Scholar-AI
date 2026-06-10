# MCP 与用户技能安全隔离说明

## 关键安全声明

**⚠️ 当前版本 MCP 服务器和用户技能运行在软隔离环境，不提供系统级沙箱。**

### 软隔离 vs 真正沙箱

#### 当前保护（软隔离）
- ✅ 命令行参数校验（禁止 shell 注入）
- ✅ 危险命令检测（rm/format/sudo 等）
- ✅ 环境变量白名单
- ✅ 工作目录隔离
- ✅ 输出大小限制
- ✅ 执行超时限制

#### 无法防护（关键缺失）
- ❌ **无 syscall 限制**：进程继承完整用户权限
- ❌ **无文件系统隔离**：可读写用户有权限的所有文件
- ❌ **无网络隔离**：可访问任何网络地址
- ❌ **无资源限制**：无内存/CPU 配额

---

## 风险评估

| MCP 来源 | 风险等级 | 说明 |
|---------|---------|------|
| 官方 MCP（Anthropic） | 低 | 第一方可信代码 |
| 社区 MCP（GitHub） | 高 | 第三方代码，需审查 |
| 用户自定义 MCP/技能 | **关键** | 完全不可信，可执行任意代码 |

---

## 用户确认流程

### MCP 安装确认（已实现）

安装社区/自定义 MCP 前，后端 `mcp_runtime/security_policy.py:1-57` 已明确说明风险。

前端安装 UI 应显示（待实现）：

```
⚠️ 安全警告

您即将安装：{mcp_name}

当前隔离级别：软约束（无沙箱）
- ❌ 无系统调用限制
- ❌ 无文件系统隔离
- ❌ 无网络阻断

此 MCP 服务器可以：
- 读写您的所有文件
- 访问任何网络地址
- 执行系统命令

仅当您完全信任此 MCP 服务器时继续。
安装前请审查源代码。

继续？ [是/否]
```

### 用户技能安装确认（已实现）

`skills/user_manifest.py:59` 定义高风险权限：
- `script.execute`
- `network`
- `files.write`

`skills/service.py:546-570` 要求用户审批高风险权限。

---

## 未来加固路径

### 选项 1: 操作系统级隔离

**Windows**:
- Job Objects（资源限制）
- AppContainer（文件/网络隔离）

**Linux**:
- seccomp（syscall 过滤）
- landlock（文件系统限制）
- network namespaces（网络隔离）

**跨平台**:
- Docker/Podman 容器运行时

### 选项 2: WebAssembly 运行时

使用 WASI（WebAssembly System Interface）运行第三方代码：
- 默认无文件/网络权限
- 显式授权访问
- 跨平台一致性

工程量：需要 MCP 协议适配层

---

## 当前建议

1. **默认禁止未审查的第三方 MCP/技能**
2. **官方 MCP 优先**：Anthropic 维护的服务器
3. **审查代码**：安装社区 MCP 前检查源码
4. **最小权限**：用户技能只授予必要权限
5. **监控日志**：跟踪 MCP 子进程行为

---

**文档路径**：`literature_assistant/core/mcp_runtime/security_policy.py`  
**相关技能权限**：`literature_assistant/core/skills/user_manifest.py`  
**审批实现**：`literature_assistant/core/skills/service.py:546-570`

---

**生成时间**：2026-06-10  
**状态**：H2 已文档化，前端警告 UI 待实现
