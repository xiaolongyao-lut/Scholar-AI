# MCP 安全边界说明

Scholar AI 现在有两个不同的 MCP 面：

| MCP 面 | 主要用途 | 入口 |
|---|---|---|
| 外部智能体文献工具箱 | Claude / Codex 调用文献检索、材料读取、导出、工作流和安全源码查看 | `agent_mcp_server/` |
| 文献助手内部可选 MCP 包 | 文献助手桌面控制台扫描和启用本地扩展包 | `extension_packages/mcp/` |

## 外部智能体文献工具箱

`agent_mcp_server/` 是当前主方向。它通过 stdio MCP 接入 Claude / Codex，
再通过本机 HTTP API 调用文献助手后端。

安全边界：

- 不直接导入文献助手核心模块。
- 不接收原始 provider API key。
- 源码工具只允许读取白名单目录。
- 工具输出统一经过密钥脱敏和大小限制。
- 每次工具调用写入 `workspace_artifacts/agent_mcp_workflows/.audit/`。
- 后端不可用时返回结构化错误，并通过熔断避免外部智能体长时间等待。

外部智能体本身的文件读写、命令执行和联网权限由 Claude / Codex 等宿主客户端管理。
Scholar AI 的 MCP 工具箱只负责自己暴露的工具边界。

## 内部 MCP 包与用户技能

文献助手仍保留内部 MCP 包和 Skill 扫描能力。这类扩展运行在本机用户权限下，
不是系统级沙箱。

当前保护：

- 命令行参数校验。
- 危险命令检测。
- 环境变量白名单。
- 工作目录约束。
- 输出大小限制。
- 执行超时。
- 高风险权限审批。

无法提供的系统级隔离：

- syscall 限制。
- 完整文件系统沙箱。
- 网络隔离。
- CPU / 内存硬配额。

## 使用建议

- Claude / Codex 优先使用 `agent_mcp_server/`。
- 只启用自己信任并审查过的内部 MCP 包或 Skill。
- API key 通过文献助手设置页或本地环境配置，不写入 Git、manifest 或公开文档。
- 查看 Agent Workspace 和后端日志来复盘工具调用。
