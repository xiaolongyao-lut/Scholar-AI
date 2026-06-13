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
| 检索链路 | BM25 + dense embedding + rerank；TOLF 与 RAG 通过 RRF 融合，不再互相替代 |
| 结构化证据补全 | 表格、公式、同章节相邻证据可作为 sibling 一起进入上下文，减少“提到表格但没给真数据”的情况 |
| 多角色讨论 | 多个角色围绕同一问题讨论、质询、补证据并形成综合结论 |
| Wiki 知识沉淀 | 可把材料、观点和复审后的发现沉淀为本地 Wiki 页面 |
| 写作 | TipTap 富文本编辑器，大纲、引用、图表资料和 DOCX 导出链路 |
| MCP / Skill | 本地扫描安装包，绑定凭证后启用；工具调用前需要人工审批 |
| 设置与日志 | API、模型、凭证、实验功能、本地回退状态和后端日志查看器集中在设置页 |

## 0.1.8.3 重点

- RAG 主链路默认启用 hybrid retrieval、chunk 类型加权、同章节结构化邻居补全、TOLF 目标导向检索和 TOLF×RAG 融合。
- 云端 embedding / rerank 仍是默认路线；用户本机安装模型后，可在 API 不可用时回退到本地 SentenceTransformer / reranker。
- 设置页新增本地回退状态提示和后端日志查看器。
- README 图片已替换为当前 UI 的真实截图，并以缩略图表格展示。
- 默认 Windows 安装包不内置 torch / sentence-transformers / marker 大模型，避免安装包膨胀到数 GB。

## 下载

普通用户建议直接下载 Windows 安装包：

- [v0.1.8.3 发布页](https://github.com/xiaolongyao-lut/Scholar-AI/releases/tag/v0.1.8.3)
- [下载 Windows 安装包](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.3/Scholar-AI-Setup-0.1.8.3-windows-x64.exe)
- [SHA256 校验文件](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.3/SHA256SUMS.txt)
- 安装包 SHA256：`77FBA03CE894B95D186261ED7D4ED32AFE43FCD08F5B8689F91B5A71B7D06235`

## 为什么不直接用 NotebookLM、Obsidian 或 GPT 网页版

NotebookLM、GPT / Claude / Gemini 网页版适合快速问答，但研究写作里更难控制证据链、长期项目空间、引用复核和本地工具调用。Obsidian 很适合笔记，但 AI 文献检索、讨论、引用和写作链路通常依赖多个插件拼装。

Scholar AI 的重点不是换一个模型聊天，而是把研究流程中反复发生的动作串起来：读 PDF → 入库 → 检索证据 → 多视角讨论 → 复核引用 → 沉淀 Wiki → 写作导出。

| 维度 | NotebookLM | Obsidian | Scholar AI |
|---|---|---|---|
| 部署形态 | 云端 | 本地笔记软件 | 本地桌面应用 |
| LLM 接入 | Google 产品内置 | 依赖插件 | 用户自己的 OpenAI 兼容 API |
| PDF 阅读 | 简易阅读与引用 | 依赖插件 | 内嵌阅读器 + 页码定位 |
| 多文献检索 | 有 | 依赖插件 | 项目级 RAG / TOLF / rerank |
| 多角色讨论 | 无 | 无 | 有 |
| 知识沉淀 | Notebook 内部 | Markdown / 双链 | Wiki + Evolution 复审 |
| 写作交付 | 轻量辅助 | Markdown | 富文本编辑 + DOCX 导出 |
| 工具扩展 | 产品内置 | 插件 | MCP / Skill，本地审批 |
| 数据位置 | 云端 | 本地 | 本地优先 |

## 架构

```text
Frontend
  React + Vite + TipTap + PDF.js
  route-level lazy loading
  OpenAPI-generated TypeScript types

Backend
  Python + FastAPI + Pydantic v2
  project/resource/chat/wiki/writing/MCP routers
  SQLite / JSONL / local runtime state

Retrieval
  PDF extraction -> chunk store -> embedding/BM25 -> rerank
  TOLF target-oriented retrieval -> RRF fusion with RAG
  structured sibling inclusion for tables/formulas/figure captions

Extensions
  MCP servers and Scholar AI Skills
  local package scan, credential binding, manual approval before tool calls
```

## 从源码运行

源码运行面向开发者。普通用户建议使用 Windows 安装包。

环境要求：Python 3.11+、Node.js 20+、Windows PowerShell。

```powershell
# 后端依赖
python -m pip install --upgrade pip
python -m pip install -r requirements-ci.txt

# 前端依赖
cd frontend
npm ci
```

启动后端：

```powershell
.\.venv-1\Scripts\python.exe -m uvicorn literature_assistant.core.python_adapter_server:app --host 127.0.0.1 --port 8000
```

启动前端：

```powershell
cd frontend
npm run dev
```

打开 Vite 输出的本地地址即可。安装版的数据目录在 `%APPDATA%\LiteratureAssistant\`；源码运行的数据目录在仓库内 `workspace_artifacts\`。

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
- 第三方 API key 不写入前端 localStorage，不在日志和 API 响应中明文展示。
- MCP 工具调用前需要用户确认；高风险能力会被阻断或进入审批流。
- 默认安装包不捆绑本地大模型。需要本地 embedding / rerank 时，由用户自行安装模型权重。

## 路线图

- macOS / Linux 安装包。
- 更稳定的本地 embedding / rerank 启动器。
- 论文实体抽取与参数-过程-结构-性能关系图。
- 前端中英双语。
- 团队 / 课题组协作模式。

## 许可

source-available 非商业许可。学生、个人研究者、非商业研究机构可免费下载、阅读、运行、修改。商业使用、转售、再授权、付费托管服务需作者书面授权。比赛 / 竞赛使用必须明确披露使用了 Scholar AI。详见 [LICENSE](LICENSE)。

## 反馈

- [报告安全问题](SECURITY.md)
- [查看贡献说明](CONTRIBUTING.md)
