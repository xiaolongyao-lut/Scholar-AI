# Scholar AI

Scholar AI 是一个本地优先的学术研究工作台，面向需要长期阅读 PDF、围绕同一课题反复追问、整理证据并写成文稿的研究流程。它把文献库、PDF 阅读、RAG 问答、多角色讨论、Wiki 知识沉淀、写作编辑器和 MCP 工具调用放在同一个桌面应用里。

最新版本 [v0.1.8.3](https://github.com/xiaolongyao-lut/Scholar-AI/releases/tag/v0.1.8.3) ·
[Windows 安装包](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.3/Scholar-AI-Setup-0.1.8.3-windows-x64.exe) ·
[SHA256](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.3/SHA256SUMS.txt)

> 当前仍是 alpha / dogfood 阶段。Windows 安装包未做代码签名，首次安装可能触发 SmartScreen 警告。

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

## 适合什么场景

- 读几十到上百篇 PDF，并持续围绕同一课题追问。
- 需要答案带页码级引用，能回到原文核验。
- 需要把临时问答、讨论结论和证据沉淀成长期知识库。
- 需要从证据检索走到论文写作，而不是在多个工具间复制粘贴。
- 希望研究资料、日志、对话和索引默认留在本机。

## 核心能力

| 能力 | 当前实现 |
|---|---|
| PDF 阅读 | 内嵌 PDF.js 阅读器，多标签页、连续滚动、页码跳转、高亮、便签和阅读位置保存 |
| 文献库 | 项目级文献管理，上传 PDF 后切块、去重、索引，支持绑定源文件夹后按需或全量入库 |
| 智能研读 | 统一问答入口，结合 RAG、目标导向检索和 rerank，回答带证据引用 |
| 检索链路 | 关键词检索、向量检索、重排序和目标导向检索共同工作，提升长文献问答的召回质量 |
| 结构化证据补全 | 表格、公式、图注和同章节相邻证据会一起进入上下文，减少“提到表格但没给真数据”的情况 |
| 多角色讨论 | 多个角色围绕同一问题讨论、质询、补证据并形成综合结论 |
| Wiki 知识沉淀 | 可把材料、观点和复审后的发现沉淀为本地 Wiki 页面 |
| 写作 | TipTap 富文本编辑器，大纲、引用、图表资料和 DOCX 导出链路 |
| MCP / Skill | 本地扫描安装包，绑定凭证后启用；工具调用前需要人工审批 |
| 设置与日志 | API、模型、凭证、实验功能和后端日志查看器集中在设置页 |

## 0.1.8.3 重点

- 检索链路默认启用混合检索、结构化证据补全、目标导向检索和结果融合，回答更容易带到表格、公式和同章节证据。
- Windows 安装包采用 API-first 方案，默认依赖已配置的云端 embedding / rerank / chat 服务，不捆绑本地推理代码。
- 源码运行支持可选本地加速能力，适合需要 marker-pdf 结构化解析、本地 rerank 或本地 embedding 的开发者。
- 设置页新增后端日志查看器，便于排查 API、模型、文献入库和检索问题。
- README 图片已替换为当前 UI 的真实截图，并以缩略图表格展示。

## 下载

普通用户建议直接下载 Windows 安装包：

- [v0.1.8.3 发布页](https://github.com/xiaolongyao-lut/Scholar-AI/releases/tag/v0.1.8.3)
- [下载 Windows 安装包](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.3/Scholar-AI-Setup-0.1.8.3-windows-x64.exe)
- [SHA256 校验文件](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.3/SHA256SUMS.txt)
- 安装包 SHA256：`77FBA03CE894B95D186261ED7D4ED32AFE43FCD08F5B8689F91B5A71B7D06235`

Windows 安装包面向普通用户，体积约 466MB，默认使用你在设置页配置的云端模型服务。安装包不包含本地推理代码；需要本地 GPU/CPU 加速或 marker-pdf 结构化解析的开发者，请使用源码运行方式。

## 架构

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Frontend                                                             │
│ React + Vite + TypeScript + TipTap + PDF.js                          │
│ 桌面工作台、PDF 阅读、写作编辑器和设置页面                              │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP / SSE / OpenAPI
┌───────────────────────────────▼──────────────────────────────────────┐
│ Backend                                                              │
│ FastAPI + Pydantic v2                                                │
│ 文献入库、聊天问答、Wiki、写作、MCP、设置、日志和模型配置 API            │
└───────┬───────────────────────┬──────────────────────┬───────────────┘
        │                       │                      │
        ▼                       ▼                      ▼
  Project storage          Retrieval engine        Extension system
  SQLite / JSONL           PyMuPDF extraction       MCP / Skill scanner
  chunk store              chunking + embedding     credential binding
  runtime state            keyword/vector search    approval gate
  backend logs             rerank + evidence merge  audit records
        │                       │                      │
        └───────────────┬───────┴──────────────┬───────┘
                        ▼                      ▼
                  Research workflow        Writing workflow
                  SmartRead / discussion   TipTap editor
                  evidence references      citation resources
                  Wiki / Evolution         DOCX export
```

### 前端

- `frontend/src/App.tsx` 定义桌面工作台路由，主要页面包括智能研读、知识库、项目、Wiki、写作、任务和设置。
- `frontend/vite.config.ts` 在开发模式下代理后端 API，并从 `workspace_artifacts/runtime_state/api-port.json` 读取实际后端端口。
- 同一个代理还会读取本地访问令牌，并在开发请求中自动附加，匹配后端本地 API 保护机制。
- OpenAPI schema 由 `scripts/export_openapi_schema.py` 导出，前端通过 `openapi-typescript` 生成 `frontend/src/generated/openapi.ts`。

### 后端

- ASGI 入口是 `literature_assistant.core.python_adapter_server:app`。
- `literature_assistant/bootstrap.py` 负责启动时路径注册，保证从源码运行和打包后运行都能加载同一套后端代码。
- 业务 API 位于 `literature_assistant/core/routers/`，覆盖资源入库、聊天、Wiki、写作、MCP、凭证、设置、日志、模型配置和功能开关。
- 本地 API 默认启用访问令牌。健康检查可以直接访问，真实业务请求需要携带运行时生成的本机令牌。

### 数据与运行时状态

- 安装版数据集中在 `%APPDATA%\LiteratureAssistant\`。
- 源码运行数据集中在 `workspace_artifacts/`，其中 `runtime_state/` 放端口、能力令牌、日志和运行时配置，项目资料和切块索引按项目分目录保存。
- 文献切块使用 JSONL / SQLite 等本地文件结构；日志写入 `backend.log` 并在设置页可查看。

### 检索与问答链路

- PDF 默认用 PyMuPDF 抽取文本；marker 结构化解析保留为实验能力，默认关闭。
- 入库后形成 chunk store，并按项目维护文献、页码、chunk 类型、章节和证据引用信息。
- 召回链路包括关键词检索、向量检索、重排序、目标导向检索和结果融合。
- 表格、公式、图注和同章节相邻证据会被优先补入最终上下文，减少只引用段落、不引用真实数据的问题。
- 云端 embedding / rerank 是默认路线。

### 写作、Wiki 与扩展

- 写作区使用 TipTap 富文本编辑器，引用、图表资料和导出能力由后端 writing router 支持。
- Wiki / Evolution 用于把问答、讨论和写作中出现的可复用发现沉淀为本地知识。
- MCP / Skill 包从本地路径扫描，不自动执行包内代码；绑定凭证和启用后，工具调用仍经过审批和审计。

### 打包发布

- Windows 发布脚本是 `scripts/build_windows_exe.ps1`。
- 打包链路会先构建前端，再跑 PyInstaller、路径扫描、敏感信息扫描、Inno Setup 和首次启动 smoke。
- 默认发布的是 API-first 轻量安装包，PyInstaller 配置会排除本地推理相关模块，避免安装包膨胀到数 GB。
- 自行构建包含本地推理模块的完整版时，可在构建前设置 `LITASSIST_BUNDLE_RAG=1`；该形态体积约 3GB，本仓库不提供预构建安装包。

## 从源码运行

源码运行面向开发者。普通用户建议使用 Windows 安装包。

环境要求：Python 3.11、Node.js 20+、Windows PowerShell。

创建虚拟环境并安装后端依赖：

```powershell
py -3.11 -m venv .venv-1
.\.venv-1\Scripts\python.exe -m pip install --upgrade pip
.\.venv-1\Scripts\python.exe -m pip install -e ".[desktop,packaging,dev]"
.\.venv-1\Scripts\python.exe -m pip install -r requirements-ci.txt
```

安装前端依赖：

```powershell
cd frontend
npm ci
```

构建前端：

```powershell
cd frontend
npm run build
```

推荐启动方式是一体桌面模式：

```powershell
cd ..
.\.venv-1\Scripts\python.exe .\start_desktop.py
```

`start_desktop.py` 会在同一个 Python 进程里启动本地 FastAPI 后端线程，并打开 pywebview 桌面窗口；关闭窗口后进程退出，不需要用户手动分别管理前后端。

需要调试后端 API 时，可以只启动后端：

```powershell
.\.venv-1\Scripts\python.exe -m uvicorn literature_assistant.core.python_adapter_server:app --host 127.0.0.1 --port 8000
```

开发前端界面时，可以另开一个 PowerShell 启动 Vite 开发服务器：

```powershell
cd frontend
npm run dev
```

这种开发模式会同时运行两个进程：后端由 `start_desktop.py` 或 uvicorn 提供，Vite 只负责前端开发服务器。Vite 代理会读取 `workspace_artifacts/runtime_state/api-port.json` 中的后端端口，并自动附加本地 API 访问令牌。

常用检查命令：

```powershell
.\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py
.\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q

cd frontend
npm run lint
npm run build
```

Windows 安装包构建属于发布流程，不是源码运行的必要步骤。公开发布前需要完成打包、签名、哈希校验和安装烟测。

## 公开源码结构

| 路径 | 说明 |
|---|---|
| `literature_assistant/` | Python 后端、RAG、Wiki、写作、MCP、Skill、Evolution 运行时 |
| `frontend/` | React / Vite 桌面工作台 |
| `extension_packages/skills/` | 可选 Scholar AI Skill 包，包根目录需有 `SKILL.md` |
| `extension_packages/mcp/` | 可选 MCP 包，包根目录需有 `literature-mcp.json` 或 `lit-mcp.json` |
| `packaging/` | PyInstaller spec、Inno Setup 脚本和品牌资源 |
| `scripts/` | 构建、发布校验、回填和运维脚本 |
| `tests/` | 后端、检索、安全、打包和前端相关回归测试 |

## 隐私与凭证

- 研究资料、对话、索引、Wiki、日志默认写在本机。
- 第三方 API key 不写入前端 localStorage，不在日志和 API 响应中明文显示。
- MCP 工具调用前需要用户确认；高风险能力会被阻断或进入审批流。
- 默认安装包保持轻量，研究资料、对话、索引和日志默认留在本机。

## 可选扩展

Windows 安装包默认不包含本地推理模块，适合直接配置 API 后使用。

从源码运行时，可以按需启用 marker-pdf 结构化解析、本地 rerank 和本地 embedding。相关依赖不会随默认安装包分发，需要开发者自行安装。详见 [OPTIONAL_ADDONS.md](OPTIONAL_ADDONS.md)。

## 许可

source-available 非商业许可。学生、个人研究者、非商业研究机构可免费下载、阅读、运行、修改。商业使用、转售、再授权、付费托管服务需作者书面授权。比赛 / 竞赛使用必须明确披露使用了 Scholar AI。详见 [LICENSE](LICENSE)。

## 反馈

- [报告安全问题](SECURITY.md)
- [查看贡献说明](CONTRIBUTING.md)
