# Claude / Codex 工具箱

[English](claude-codex-toolbox.en.md) · [项目首页](../README.md) · [MCP server 说明](../agent_mcp_server/README.md)

Scholar AI 提供一个本地 MCP 工具箱，让 Claude、Codex 和其他 MCP 客户端调用本机文献库、证据检索、写作导出、OCR 状态、工作流产物和安全源码查看能力。

这个工具箱的重点是“把本地研究资料变成可调用工具”，不是把用户的 API key、数据库或私人材料交给外部智能体。模型供应商凭证仍由 Scholar AI 后端或桌面端配置管理。

## 适用场景

- 让 Claude / Codex 检索本地文献项目，而不是只依赖网页搜索。
- 让外部智能体读取页码级 chunk、证据包和 bounded context。
- 为综述、单篇研读、写作导出、OCR 准备和工作流复验提供固定工具链。
- 让代码智能体在白名单内查看源码，理解接口和工具实现。
- 用 Agent Workspace 查看工具调用、审计记录、产物和交接信息。

## 连接方式

Scholar AI 的 MCP server 位于 `agent_mcp_server/`，通过 stdio 接入 MCP 客户端：

```text
Claude / Codex / MCP client
        |
        | stdio MCP
        v
agent_mcp_server/
        |
        | HTTP + local token
        v
Scholar AI backend
        |
        +-- literature workspace
        +-- chunk store and indexes
        +-- model and credential config
        +-- Agent Workspace audit artifacts
```

自检命令：

```powershell
.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -SelfTest
```

配置预览：

```powershell
.\agent_mcp_server\packaging\codex\add-user.ps1 -PrintOnly
.\agent_mcp_server\packaging\claude-code\add-user.ps1 -PrintOnly
```

## 工具分组

| 分组 | 代表工具 | 用途 |
|---|---|---|
| 源码查看 | `source.list_tree`, `source.search`, `source.read_file`, `source.read_symbols`, `source.inspect_routes` | 在白名单内查看 Scholar AI 源码、符号、路由和入口。 |
| 文献项目 | `literature.list_projects`, `literature.list_materials`, `literature.read_material`, `literature.get_material_chunks` | 找到项目、材料、元数据和页码级 chunk。 |
| 检索证据 | `literature.search_refs`, `literature.evidence_pack_build`, `literature.evidence_integrity_gate`, `literature.knowledge_context_receipt` | 检索 refs，构建证据包，检查完整性，并生成上下文 receipt。 |
| OCR 与材料处理 | `literature.ocr_status`, `literature.ocr_engines`, `literature.ocr_health`, `literature.ocr_material` | 检查 OCR 策略、引擎状态和授权后的材料处理路径。 |
| 图表与引用 | `literature.figures_candidates`, `literature.figures_generate`, `literature.citations_sources`, `literature.citations_detect_overlap` | 抽取图表候选、生成图表材料、检查引用来源和重叠。 |
| 写作与导出 | `literature.outline_generate`, `literature.academic_writing_lint`, `literature.export_docx`, `literature.export_project_pack`, `literature.translate_pack` | 生成提纲、检查学术写作、导出 Word/项目包/翻译包。 |
| Agent Workspace | `literature.agent_workspace_status`, `literature.agent_resource_read`, `literature.agent_handoff_card`, `literature.workflow_passport` | 查看审计、读取资源、生成交接卡和复验工作流。 |
| 本地工作流 | `workflow.create_plan`, `workflow.run_json_workflow`, `artifact.write_markdown`, `artifact.read_artifact` | 写入、读取和复跑本地 JSON/Markdown 工作流产物。 |

完整实时工具注册表以 MCP `list_tools` 返回结果为准。工具到代码的映射见 [agent_mcp_server/CAPABILITY_MAP.md](../agent_mcp_server/CAPABILITY_MAP.md)。

## 已打通的工具链路

| 链路 | 工具调用顺序 | 产出 |
|---|---|---|
| 检索取证 | `literature.list_projects` -> `literature.search_refs` -> `literature.evidence_pack_build` -> `literature.evidence_integrity_gate` | 带 ref、页码、材料来源和完整性检查的证据包。 |
| 上下文装载证明 | `literature.agent_resource_read` -> `literature.knowledge_context_receipt` -> provider tool-call transcript | 证明模型实际收到 bounded context 和 receipt hash。 |
| 单篇研读 | `literature.read_material` -> `literature.get_material_chunks` -> `literature.figures_candidates` -> `literature.agent_handoff_card` | 可交接的单篇阅读摘要、图表候选和后续任务卡。 |
| 写作导出 | `literature.evidence_pack_build` -> `literature.outline_generate` -> `literature.academic_writing_lint` -> `literature.export_docx` | 带证据引用和格式检查的 Word 写作输出。 |
| OCR 准备 | `literature.ocr_status` -> `literature.ocr_engines` -> `literature.ocr_health` -> `literature.ocr_material` | 扫描型 PDF 的引擎选择、健康检查和授权后 OCR 处理。 |
| 源码修复 | `source.search` -> `source.read_symbols` -> `source.read_file` -> `literature.agent_workspace_status` | 结合源码和审计信息定位修复面。 |
| 工作流复验 | `literature.workflow_passport` -> `literature.workflow_refresh_receipt` -> `literature.workflow_replay_lineage` | 将研究动作、证据、产物和交接记录串成可复验链路。 |

## 依赖与前置条件

| 项目 | 要求 |
|---|---|
| Scholar AI 后端 | 使用 `literature_assistant.core.python_adapter_server:app` 运行。桌面端启动器会在同一进程中启动后端。 |
| Python 环境 | 推荐使用仓库内 `.venv-1`。 |
| MCP 客户端 | Claude、Codex 或任何支持 stdio MCP 的客户端。 |
| 本地文献库 | 已导入或可扫描的 Scholar AI 项目和材料。 |
| 模型与凭证 | 由 Scholar AI 桌面端或后端配置管理；MCP 工具不接收原始 provider key。 |
| 实验工具 | OCR/page-image、视觉审阅、翻译包、项目包和受限 Python sandbox 需要显式设置 `LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS=1`。 |

## 验证方式

基本自检：

```powershell
.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -SelfTest
```

MCP server 测试：

```powershell
.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests -q
```

上下文装载证明不使用 `Hi`、`ok` 或纯连通性探针。有效证明需要模型真实请求 `literature.agent_resource_read` 与 `literature.knowledge_context_receipt`，并在 provider tool-call transcript 中回流 receipt hash。

## 安全边界

- 源码工具只读取白名单路径。
- 工具输出返回前统一脱敏并限制大小。
- 原始 API key、`.env`、运行时 token、数据库、日志、本机 MCP 客户端配置不属于公开读取面。
- 后端不可用时返回结构化错误，连续失败会触发熔断。
- 工具调用审计写入 `workspace_artifacts/agent_mcp_workflows/.audit/`。
- 外部全文获取工具应与 Scholar AI 分离；论文全文来源、机构访问、开放获取和合规责任由用户自行确认。
