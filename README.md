# Scholar AI

[English](README.en.md) · [科研工作流与 Skills](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) · [MCP 工具箱文档](agent_mcp_server/README.md) · [快速开始](#快速开始)

Scholar AI 是一个开源的本地科研工作台，用来管理 PDF 文献、构建可追溯证据、辅助综述写作，并把本地文献库变成 Claude、Codex 等 AI 客户端可调用的工具箱。

它适合需要反复阅读论文、整理证据、导出文档和复用本地研究资料的学生、研究者和开源实验者。你可以把它当成一个桌面文献库，也可以把它接到支持 MCP 的 AI 客户端，让外部智能体检索材料、读取上下文、检查证据和生成研究产物。

当前源码版本：[v0.1.8.4](CHANGELOG.md#0184---2026-06-17)

## 能做什么

- 管理本地 PDF 文献、项目、页码级 chunk、批注和阅读状态。
- 对文献库做关键词、向量、rerank 和证据融合检索。
- 把检索结果组织成带来源、页码和完整性检查的证据包。
- 辅助论文研读、文献综述、学术写作、图表候选提取和 Word 导出。
- 检查 OCR 配置和扫描型材料处理路径。
- 通过 MCP 工具箱让 Claude / Codex 调用本地文献能力，但不暴露原始 API key。
- 通过 Agent Workspace 查看工具调用、审计记录、工作流产物和交接信息。

## 相关仓库

| 仓库 | 内容 |
|---|---|
| [Scholar AI](https://github.com/xiaolongyao-lut/Scholar-AI) | 本仓库，包含桌面端、后端、MCP 工具箱、检索、写作、OCR 和测试。 |
| [scholar-ai-research-toolkit](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) | Scholar AI 沉淀出的科研工作流和技能卡片，覆盖论文阅读、翻译、写作、OCR、实验设计和证据流程。 |

## Claude / Codex 工具箱

`agent_mcp_server/` 提供一个本地 MCP server。Claude、Codex 或其他 MCP 客户端可以通过它调用 Scholar AI 的文献工具：

- 源码查看：`source.list_tree`, `source.search`, `source.read_file`, `source.read_symbols`, `source.inspect_routes`
- 文献项目：`literature.list_projects`, `literature.list_materials`, `literature.read_material`, `literature.get_material_chunks`
- 检索证据：`literature.search_refs`, `literature.evidence_pack_build`, `literature.evidence_integrity_gate`, `literature.knowledge_context_receipt`
- OCR 与材料处理：`literature.ocr_status`, `literature.ocr_engines`, `literature.ocr_health`, `literature.ocr_material`
- 图表与引用：`literature.figures_candidates`, `literature.figures_generate`, `literature.citations_sources`, `literature.citations_detect_overlap`
- 写作与导出：`literature.outline_generate`, `literature.academic_writing_lint`, `literature.export_docx`, `literature.export_project_pack`, `literature.translate_pack`
- Agent Workspace：`literature.agent_workspace_status`, `literature.agent_resource_read`, `literature.agent_handoff_card`, `literature.workflow_passport`
- 本地工作流：`workflow.create_plan`, `workflow.run_json_workflow`, `artifact.write_markdown`, `artifact.read_artifact`

## 已打通的工具链路

| 链路 | 工具调用顺序 | 产出 |
|---|---|---|
| 检索取证 | `literature.list_projects` -> `literature.search_refs` -> `literature.evidence_pack_build` -> `literature.evidence_integrity_gate` | 带 ref、页码、材料来源和完整性检查的证据包 |
| 上下文装载证明 | `literature.agent_resource_read` -> `literature.knowledge_context_receipt` -> provider tool-call transcript | 证明模型实际收到 bounded context 和 receipt hash |
| 单篇研读 | `literature.read_material` -> `literature.get_material_chunks` -> `literature.figures_candidates` -> `literature.agent_handoff_card` | 可交接的单篇阅读摘要、图表候选和后续任务卡 |
| 写作导出 | `literature.evidence_pack_build` -> `literature.outline_generate` -> `literature.academic_writing_lint` -> `literature.export_docx` | 带证据引用和格式检查的 Word 写作输出 |
| OCR 准备 | `literature.ocr_status` -> `literature.ocr_engines` -> `literature.ocr_health` -> `literature.ocr_material` | 扫描型 PDF 的引擎选择、健康检查和授权后 OCR 处理 |
| 源码修复 | `source.search` -> `source.read_symbols` -> `source.read_file` -> `literature.agent_workspace_status` | 结合源码和审计信息定位修复面 |
| 工作流复验 | `literature.workflow_passport` -> `literature.workflow_refresh_receipt` -> `literature.workflow_replay_lineage` | 将研究动作、证据、产物和交接记录串成可复验链路 |

工具箱验证不使用 `Hi`、`ok` 这类纯连通性探针；上下文装载证明要求模型真实请求 `literature.agent_resource_read` 与 `literature.knowledge_context_receipt`。原始 provider key 不写入 Git、日志或公开文档。

## 工作方式

```text
Claude / Codex / MCP client
        │
        │ stdio MCP
        ▼
agent_mcp_server/
本地文献 MCP 工具箱
        │
        │ HTTP + local token
        ▼
Scholar AI backend
FastAPI / retrieval / export / workflow APIs
        │
        ├─ literature workspace
        ├─ chunk store and indexes
        ├─ model and credential config
        └─ Agent Workspace audit artifacts
```

桌面端负责文献库、PDF 阅读、模型配置、凭证管理和审计查看。MCP 工具箱负责把这些本地能力暴露给用户授权的 AI 客户端。

## 快速开始

### 1. 准备环境

需要：

- Python 3.11
- Node.js 20+
- Windows PowerShell

### 2. 安装后端依赖

```powershell
py -3.11 -m venv .venv-1
.\.venv-1\Scripts\python.exe -m pip install --upgrade pip
.\.venv-1\Scripts\python.exe -m pip install -e ".[desktop,dev]"
.\.venv-1\Scripts\python.exe -m pip install -r requirements-ci.txt
```

### 3. 构建前端控制台

```powershell
cd frontend
npm ci
npm run build
cd ..
```

### 4. 启动文献助手

```powershell
.\.venv-1\Scripts\python.exe .\start_desktop.py
```

`start_desktop.py` 会在同一个 Python 进程里启动 FastAPI 后端线程和 pywebview 桌面窗口。关闭窗口后进程退出。

### 5. 自检 MCP 工具箱

```powershell
.\agent_mcp_server\bin\lit-assistant-mcp.ps1 -SelfTest
```

### 6. 配置 Claude / Codex

详细配置见 [agent_mcp_server/README.md](agent_mcp_server/README.md)。

常用入口：

```powershell
# Codex 配置预览
.\agent_mcp_server\packaging\codex\add-user.ps1 -PrintOnly

# Claude Code 配置预览
.\agent_mcp_server\packaging\claude-code\add-user.ps1 -PrintOnly
```

实验工具默认关闭。确认要让外部智能体使用 OCR、视觉审阅、翻译包、项目包和受限 Python sandbox 时，再设置：

```powershell
$env:LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS = "1"
```

## MCP 工具清单

`agent_mcp_server/` 当前基础工具包括：

| 工具 | 用途 |
|---|---|
| `source.list_tree` | 列出允许范围内的源码树 |
| `source.search` | 搜索允许范围内的源码文本 |
| `source.read_file` | 读取允许范围内的源码文件并自动脱敏 |
| `source.read_symbols` | 提取 Python 文件中的类、函数和导入符号 |
| `literature.config_status` | 查看后端连接和模型配置状态 |
| `literature.list_projects` | 列出文献项目 |
| `literature.list_materials` | 列出项目材料 |
| `literature.read_material` | 读取材料元数据 |
| `literature.get_material_chunks` | 读取材料切块 |
| `literature.search_refs` | 检索文献库并返回可读取 ref |
| `literature.evidence_pack_build` | 构建带来源的证据包 |
| `literature.evidence_integrity_gate` | 检查证据包完整性 |
| `literature.knowledge_context_receipt` | 为 bounded context 生成 receipt，证明上下文装载 |
| `literature.export_annotations_markdown` | 导出批注 Markdown |

启用实验工具后，外部智能体还可以请求 OCR/page-image、视觉审阅、翻译包、项目包和受限 Python sandbox。模型调用仍走文献助手后端，MCP server 不接收原始 provider key。

## 安全边界

- 源码工具只允许读取明确白名单内的目录。
- `PathPolicy` 使用真实路径和公共路径校验阻断 `..`、绝对路径绕过和大小写混淆。
- `SecretRedactor` 覆盖 OpenAI、Anthropic、中国大模型平台、Bearer、Basic Auth、JWT、URL 编码和上下文型 key。
- 所有工具结果返回前都会走统一脱敏和大小限制。
- 后端不可用时，MCP 客户端收到结构化错误；连续失败会触发熔断，避免智能体长时间等待。
- 每次工具调用写入 `workspace_artifacts/agent_mcp_workflows/.audit/`，包括工具名、参数摘要、触达路径和脱敏预览。
- 用户凭证、`.env`、运行时令牌、数据库、日志和本机 MCP 客户端配置不属于公开读取面。

## 桌面控制台

桌面端仍然是本地资料和配置的入口，但它服务于 MCP-first 工作流：

- 导入和管理 PDF 文献。
- 查看 PDF、页码、高亮、便签和阅读位置。
- 配置 embedding、rerank、LLM、OCR、视觉和翻译相关 API。
- 查看后端日志、任务状态和 Agent Workspace 审计。
- 在需要时使用内置智能研读、Wiki 和写作区。

## 界面预览

<table>
  <tr>
    <td width="50%"><strong>智能研读</strong><br><img width="520" alt="智能研读界面" src="frontend/public/readme/smart-read.png" /></td>
    <td width="50%"><strong>知识库</strong><br><img width="520" alt="知识库界面" src="frontend/public/readme/knowledge-base.png" /></td>
  </tr>
  <tr>
    <td width="50%"><strong>Wiki 工作台</strong><br><img width="520" alt="Wiki 工作台界面" src="frontend/public/readme/wiki.png" /></td>
    <td width="50%"><strong>设置与功能开关</strong><br><img width="520" alt="设置与功能开关界面" src="frontend/public/readme/settings-flags.png" /></td>
  </tr>
</table>

## 后端与数据

- ASGI 入口是 `literature_assistant.core.python_adapter_server:app`。
- 业务 API 位于 `literature_assistant/core/routers/`，覆盖资源入库、检索、聊天、Wiki、写作、MCP、凭证、设置、日志、模型配置和功能开关。
- 源码运行数据集中在 `workspace_artifacts/`，包括运行时端口、本机访问令牌、日志、审计和项目索引。
- PDF 默认用 PyMuPDF 抽取文本；marker 结构化解析保留为可选能力。
- 检索链路包括关键词检索、向量检索、重排序、目标导向检索和证据融合。
- embedding、rerank、LLM、OCR、视觉和翻译能力由文献助手后端配置，外部智能体通过 MCP 调用能力，不接收原始 provider key。

## 开发检查

```powershell
.\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py
.\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
.\.venv-1\Scripts\python.exe -m pytest agent_mcp_server\tests -q

cd frontend
npm run lint
npm run build
```

调试后端 API 时可以单独启动：

```powershell
.\.venv-1\Scripts\python.exe -m uvicorn literature_assistant.core.python_adapter_server:app --host 127.0.0.1 --port 8000
```

## 公开源码结构

| 路径 | 说明 |
|---|---|
| `agent_mcp_server/` | 面向 Claude / Codex 的本地文献 MCP 工具箱、配置模板和测试 |
| `literature_assistant/` | Python 后端、RAG、Wiki、写作、凭证、设置和本地 API |
| `frontend/` | React / Vite / pywebview 桌面控制台 |
| `scripts/` | OpenAPI、索引回填、发布校验和维护脚本 |
| `tests/` | 后端、检索、安全、MCP 和前端相关回归测试 |

根目录主要入口：

| 文件 | 用途 |
|---|---|
| `start_desktop.py` | 源码桌面启动器，单进程启动后端线程和 pywebview 窗口 |
| `start.bat` | Windows 双击启动入口 |
| `run_literature_assistant.py` | 路径诊断和命令行包装入口 |
| `sitecustomize.py` | 兼容从仓库根目录直接运行时的 Python 导入路径 |
| `requirements-ci.txt` | CI 和回归测试依赖锁定 |
| `requirements-pin.txt` | 依赖版本参考 |

## 许可

Scholar AI 项目代码使用 MIT License。第三方开源组件仍适用各自许可证。详见 [LICENSE](LICENSE)。

## 反馈

- [报告安全问题](SECURITY.md)
- [查看贡献说明](CONTRIBUTING.md)
