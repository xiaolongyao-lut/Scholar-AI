# Scholar AI

[English](README.en.md) · [Releases](https://github.com/xiaolongyao-lut/Scholar-AI/releases) · [Claude / Codex 工具箱](docs/claude-codex-toolbox.md) · [科研工作流与 Skills](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) · [快速开始](#快速开始)

Scholar AI 是一个本地科研工作台：放论文、读 PDF、整理证据、写综述，也把这套本地资料交给 Claude / Codex 这类工具来查。

它想解决的不是“再做一个聊天框”，而是科研里更日常的麻烦：PDF 放散了，笔记找不到，引用页码对不上，写综述时还要来回翻原文。Scholar AI 把材料、页码、chunk、笔记、证据包和导出结果放在同一个本地工作流里；人负责判断和写作，工具负责查找、整理、复验和跑重复任务。

当前源码版本：[v0.1.8.4](CHANGELOG.md#0184---2026-06-17)

## 能做什么

- 管理本地 PDF、项目、批注、阅读位置和页码级切块。
- 在本地文献库里做关键词、向量、rerank 和证据融合检索。
- 把候选材料整理成带来源、页码、locator 和完整性检查的证据包。
- 支持智能研读、Wiki 沉淀、综述写作、图表候选提取和 Word 导出。
- 检查 OCR 配置，处理扫描型材料的入库路径。
- 通过 [MCP 工具箱](docs/claude-codex-toolbox.md) 让 Claude / Codex 调用本地文献能力，原始 API key 仍留在本机配置里。
- 在任务中心查看长任务、工具调用结果和可回放的研究产物。

## 相关仓库

| 仓库 | 内容 |
|---|---|
| [Scholar AI](https://github.com/xiaolongyao-lut/Scholar-AI) | 本仓库，包含桌面端、后端、[MCP 工具箱](docs/claude-codex-toolbox.md)、检索、写作、OCR 和测试。 |
| [scholar-ai-research-toolkit](https://github.com/xiaolongyao-lut/scholar-ai-research-toolkit) | Scholar AI 沉淀出的科研工作流和技能卡片，覆盖论文阅读、翻译、写作、OCR、实验设计和证据流程。 |

## Claude / Codex 工具箱

[`agent_mcp_server/`](agent_mcp_server/README.md) 是 Scholar AI 给 Claude / Codex 用的本地 MCP server。它把文献检索、证据包、OCR、写作导出、工作流产物和安全源码查看这些能力整理成可调用工具。

详细工具分组、已打通链路、依赖、验证方式和安全边界见 [Claude / Codex 工具箱说明](docs/claude-codex-toolbox.md)。

## 工作方式

```text
Claude / Codex / MCP client
        │
        │ 1. stdio MCP: list_tools / call_tool
        ▼
agent_mcp_server/
        │
        ├─ source.*       只读源码树、符号、路由和文件片段
        ├─ literature.*   通过后端调用文献、证据、OCR、写作和知识库 API
        ├─ workflow.*     本地 JSON workflow 计划、执行和回放
        └─ artifact.*     Markdown / JSON 产物读写和索引
        │
        │ HTTP + local token
        ▼
Scholar AI backend
        │
        ├─ FastAPI routers and typed response models
        ├─ project / material / chunk stores
        ├─ retrieval, evidence, OCR, writing, export services
        ├─ model and credential settings
        └─ task, audit, and workflow artifacts
```

桌面端负责文献库、PDF 阅读、模型配置、凭证管理和任务查看。MCP 工具箱负责把本机能力交给用户授权的 Claude / Codex：`source.*` 只读白名单源码；`literature.*` 调用后端文献 API；`workflow.*` 和 `artifact.*` 保存可回放的研究动作与产物。工具结果返回前会统一脱敏、限长，并保留 refs、locator 和 integrity 状态。

## RAG 与证据架构

Scholar AI 的 RAG 不是只把文本丢进向量库。入库后，每篇材料都会变成可定位的 chunk；后面无论是智能研读、Wiki 合成、综述写作，还是 Claude / Codex 调工具，都尽量带着项目、材料、页码、chunk 和完整性状态往前走。详细模块、代码入口和降级边界见 [RAG 与证据架构](docs/rag-evidence-architecture.md)。

```text
PDF / Markdown / OCR 材料
        │
        ▼
入库与结构化切块
        │  doc_store / chunk_store / page locator / section_path
        ▼
基础候选召回
        │  lexical refs / BM25 / dense embedding / optional rerank
        ▼
受控扩展
        │  TOLF 多面查询扩散
        │  bridge lexicon 查询扩展
        │  Wiki linked-page expansion
        │  project + wiki weighted RRF
        │  same-section table / formula / figure siblings
        ▼
证据整理
        │  search_refs / evidence_pack_build / locator coverage
        ▼
完整性门控
        │  evidence_integrity_gate / qrels status / context receipt
        ▼
智能研读 / 综述写作 / Word 导出 / MCP 工具调用
```

这条链路的目标很简单：回答里每个重要说法，最好都能追到“哪个项目、哪篇材料、哪一页、哪个 chunk”。轻量检索走 `search_refs`；智能研读可以组合 TOLF、RRF、结构化邻居和混合检索；证据包会把项目 chunk、Wiki refs 和知识 refs 收束成可复查结果。Claude / Codex 通过 MCP 读到的也是这些受控结果。

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

自检前后的工具分组、链路和依赖说明见 [Claude / Codex 工具箱说明](docs/claude-codex-toolbox.md)。

### 6. 配置 Claude / Codex

详细配置见 [agent_mcp_server/README.md](agent_mcp_server/README.md)，完整工具链路见 [Claude / Codex 工具箱说明](docs/claude-codex-toolbox.md)。

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

完整工具分组、已打通链路、实验工具开关和安全边界见 [Claude / Codex 工具箱说明](docs/claude-codex-toolbox.md)。

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

桌面端仍然是本地资料和配置的入口，也负责把必要的信息留给人看：

- 导入和管理 PDF 文献。
- 查看 PDF、页码、高亮、便签和阅读位置。
- 配置 embedding、rerank、LLM、OCR、视觉和翻译相关 API。
- 查看任务状态、工具调用结果和必要的审计信息。
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
| [`agent_mcp_server/`](agent_mcp_server/README.md) | 面向 Claude / Codex 的本地文献 [MCP 工具箱](docs/claude-codex-toolbox.md)、配置模板和测试 |
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
