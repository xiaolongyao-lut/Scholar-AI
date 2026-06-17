# Scholar AI

Scholar AI 把本地文献库变成 Claude、Codex 和其他 MCP 客户端可调用的文献工具箱。

它让成熟的外部智能体通过 MCP 直接使用文献助手的检索、材料读取、导出、工作流产物和安全源码查看能力。桌面端继续负责文献库、PDF 阅读、模型与凭证配置、运行状态和审计查看。

当前源码版本 [v0.1.8.4](CHANGELOG.md#0184---2026-06-17) ·
[MCP 工具箱文档](agent_mcp_server/README.md) ·
[快速开始](#快速开始)

## MCP 优先方向

Scholar AI 当前主线是源码工作区 + 本地 MCP 工具箱：

- Claude / Codex 通过 `agent_mcp_server/` 调用文献助手能力。
- 文献助手后端通过本机 HTTP API 提供检索、材料、切块、批注导出和实验工作流能力。
- 外部智能体可以读取允许范围内的源码，用于理解接口、抽取已有功能、修复工具问题和编排自己的工作流。
- API key、运行时令牌、数据库、日志和用户私有状态不通过 MCP 明文暴露。
- Agent Workspace 记录 MCP 调用审计、工作流产物和临时输出，避免外部智能体任务污染文献助手自己的任务中心。

## 给 Claude / Codex 的能力

| 能力 | MCP 工具箱提供什么 |
|---|---|
| 文献检索 | 查询项目、材料、chunk、关键词/向量/rerank 检索结果 |
| 材料读取 | 读取文献元数据、页码级 chunk、上下文片段和批注导出 |
| 源码查看 | 在白名单内列目录、搜索、读文件、提取 Python 符号 |
| 工作流产物 | 生成 OCR/page-image、视觉审阅包、翻译包、项目包和临时 JSON 工作流产物 |
| 安全边界 | 路径白名单、密钥脱敏、输出大小限制、HTTP 熔断和 JSONL 审计 |
| 本地配置 | 凭证、embedding、rerank、LLM、功能开关仍由文献助手桌面端和后端管理 |

当前重点是把文献助手做成外部智能体可靠可用的本地文献工具层。

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
Literature Assistant backend
FastAPI / retrieval / export / workflow APIs
        │
        ├─ literature workspace
        ├─ chunk store and indexes
        ├─ model and credential config
        └─ Agent Workspace audit artifacts
```

桌面端在这个架构里是控制台和本地资料库：上传 PDF、查看材料、配置模型、管理凭证、检查日志、查看审计与工作流输出。Claude / Codex 是主要的智能体入口。

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

`agent_mcp_server/` 当前提供：

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
| `literature.search_literature` | 检索文献库 |
| `literature.ingest_then_search` | 需要时入库后再检索 |
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
