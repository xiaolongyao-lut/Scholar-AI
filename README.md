# Scholar AI

本地优先的学术研究智能体工作台。多智能体协同讨论，回答带可追溯的页码级引用，所有数据默认留在本机。

最新版本 [v0.1.8-alpha](https://github.com/xiaolongyao-lut/Scholar-AI/releases/tag/v0.1.8-alpha)（2026-05-23）·
[Windows 安装包](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/LiteratureAssistant-Setup-0.1.8-alpha-windows-x64.exe) ·
[SHA256](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/SHA256SUMS.txt)

本仓库公开的是产品源码，方便下载、自用、学习和非商业研究。未经作者书面许可，不允许商业使用、盈利服务、转售或再授权。比赛 / 竞赛使用必须明确披露使用了 Scholar AI，不能把本项目或高度雷同版本当作原创提交。当前是 alpha / dogfood 阶段，Windows 安装包未做代码签名，首次安装可能触发 SmartScreen 警告。

## 界面预览

<img width="1440" alt="智能研读工作台" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-workbench.png" />

<img width="1440" alt="Wiki 工作台" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-wiki.png" />

<img width="1440" alt="多智能体讨论" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-discussion.png" />

<img width="1440" alt="MCP 设置" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-mcp-settings.png" />

浅色模式：

<img width="1440" alt="智能研读工作台（浅色）" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-workbench-light.png" />

<img width="1440" alt="多智能体讨论（浅色）" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-discussion-light.png" />

## 下载和安装

普通用户从 Releases 下载 Windows 安装包：

- [v0.1.8-alpha 发布页](https://github.com/xiaolongyao-lut/Scholar-AI/releases/tag/v0.1.8-alpha)
- [下载 Windows 安装包](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/LiteratureAssistant-Setup-0.1.8-alpha-windows-x64.exe)
- [SHA256 校验文件](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/SHA256SUMS.txt)

## 这个程序是做什么的

Windows 桌面应用，双击安装包就能用。把研究里"读—问—讨论—写—沉淀"五个动作放在同一个界面：

- **读**：内嵌 PDF 阅读器，高亮、便签、最后阅读页本地保存。
- **问**：本地文献库做检索 + 重排 + 证据打包，回答里每段话都带 `[E:E<n>]` 引用标记，点击跳回 PDF 原文位置。
- **讨论**：同时摆 3–5 个 AI 角色（方法学审查员、数据分析师、领域专家、质疑者等），各自独立模型与提示词，围绕同一问题按轮次发言、互相质询、补证据、收敛到带引用的回答。
- **写**：内嵌 TipTap 富文本编辑器，大纲 + 引用 + 图表 + 一键导出 DOCX。
- **沉淀**：Wiki 知识库 + Evolution 经验沉淀（候选 → 人工审核 → 提升为长期记忆，全流程审计可回滚）。

底层不训练大模型，调用户自己绑定的 LLM API。出厂内置 17 个 provider 适配层，覆盖 DeepSeek、通义千问、火山方舟、智谱、OpenAI、Anthropic、Google 等。应用本体跑在本机，仅 LLM 调用走用户配置的目的地。

## 为什么不直接用 NotebookLM、Obsidian 或 GPT 网页版

LLM 在长文档问答中的幻觉引用问题是公开的——NotebookLM 有 source citation 但没有工程层面强制 reject 写入未在原文出现的引用，ChatGPT / Claude / Gemini 网页版更是依赖模型自觉。学术写作里这种逐条复核成本很高。

Obsidian 本体没有 AI 能力，要"会查文献、能讨论、能引用证据"得装第三方插件，每个插件单独配置 API key。

而 Chatbox、Cherry Studio 这类通用聊天桌面客户端没有专门为研究流程做客户端工程。Scholar AI 就是为这条路上的几个真实摩擦点写的。

简短对比：

| 能力 | NotebookLM | Obsidian | Scholar AI |
|---|---|---|---|
| 部署形态 | 100% 云端 | 本地软件 | 本地桌面应用 |
| 必须的账号 | Google 账号 | 无 | 无 |
| LLM 接入 | 仅谷歌 | 无内置，靠插件 | 任意 OpenAI 兼容 API |
| PDF 阅读 | 简易内嵌 + 段落级引用 | 需插件 | 内嵌阅读器 + chunk 级页面定位 |
| 多智能体讨论 | 无 | 无 | 多角色协同：质询、补证、收敛 |
| 知识沉淀 | Notebook 持久 + 摘要 / FAQ / audio | 笔记 + 双链 | Wiki + Evolution 候选审核机制 |
| 写作 | study guide / FAQ / audio | Markdown | TipTap + 大纲 + 引用 + DOCX |
| 工具扩展 | 无 | Community plugins | MCP 标准接入，调用前人工审批 |
| 数据导出 | 受限 | 完全自由 | Markdown / DOCX / JSONL |

Scholar AI 不训练大模型，调的就是 OpenAI、Anthropic、Google、DeepSeek 等 API。底层 AI 完全一样。差异在客户端工程：

| 维度 | 网页版 GPT / Claude / Gemini | Scholar AI |
|---|---|---|
| 持久研究空间 | 各家自有的项目 / 记忆 / Gem 功能 | 资料、对话、引用、Wiki 写本地 SQLite，跨会话保留 |
| 文献量上限 | 受各家产品限制 | 受硬盘限制，几百 PDF 无压力 |
| PDF 解析颗粒度 | chunk 级位置不暴露给应用层 | 文本抽取 + 图片裁切 + 多模态层 + chunk 切片 + 页码 + 字符偏移 |
| 引用校验 | 依赖模型自觉与用户复核 | 引用没真出现在传给 LLM 的上下文里就拒绝写入 |
| 多智能体 | 单 agent | 多 agent：独立模型 / 提示词 / 工具权限，按轮次互相质询 |
| 上下文预算 | 由产品决定，前端通常不可见 | 显式预算 envelope，超额返回 422 告知超出位置 |
| 成本结构 | 订阅制 | 按 token 计费，按用量精细控制 |
| 工具扩展 | 各家自有协议，主要面向云端 | MCP 标准接入本地 stdio 工具，每次调用弹窗审批 |
| 写作工作台 | 复制到外部编辑器 | 内嵌 TipTap + DOCX 导出 |
| 可定制与可审查 | 客户端实现不公开 | 公开仓库可审查 |

通用聊天产品偏向广泛对话场景；Scholar AI 是专门为"读几十到上百篇文献做综述、每个观点要可追溯到具体页码、多角色围绕同一问题讨论"这类研究流程做了客户端工程。

## 架构

```
┌─────────────────────────────────────────────────────────┐
│  Frontend（React + Vite + TipTap + PDF.js）             │
│   · 路由级 + 组件级两层 lazy 代码分割                     │
│   · TypeScript 类型从 OpenAPI 自动生成                    │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP（OpenAPI 3）
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Backend（Python + FastAPI + Pydantic v2）              │
│   · 26 个 router 模块                                   │
│   · SQLite 本地持久化（WAL 模式 + busy_timeout）          │
└────────────────────────┬────────────────────────────────┘
                         │
       ┌─────────────────┼──────────────────┐
       ▼                 ▼                  ▼
  17 provider     5 模块 rerank         MCP 工具运行时
  适配 + key 池    + 预算追踪          stdio / http / ws
  + failover                          + env_refs 凭证桥
                                      + 调用人工审批
```

几个关键工程选择：

- 引用追溯走 `citation_auditor` 强制校验，引用没真出现在传给 LLM 的上下文里就拒绝写入，不是让 LLM 自觉。
- envelope guard 在多 agent 历史 + 当前证据总长度超出预算时返回 422 告知超出位置，避免回答看起来完整但上下文已被截断。
- 17 provider + key 池 + 自动 failover，随时切换厂商模型。
- API key 永不出现在前端 localStorage / 控制台日志 / 网络响应；后端走 `env_refs` 引用模式，凭证不写进配置文件。
- Release 流水线 9 步固定脚本：前端构建 → PyInstaller 分析 → forbidden-path 扫描 → onedir 构建 → secret 扫描 → Inno Setup 编译 → 首次启动冻结烟测，9 步全过才出安装包。
- MCP 工具每次调用前弹窗审批（可记住"本会话内同意"），审计面板可查所有历史调用。

## 从源码运行

源码运行面向开发者。普通用户建议用 Releases 中的 Windows 安装包。

环境要求：Python 3.10+、Node.js 20+、Windows PowerShell。

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

打开 Vite 输出的本地地址即可。

## 公开源码结构

| 路径 | 说明 |
|---|---|
| `literature_assistant/` | Python 后端、RAG 运行时、路由、持久化、MCP、Skills、Evolution、Wiki、写作服务 |
| `frontend/` | React / Vite 前端工作台 |
| `extension_packages/skills/` | 可选 Scholar AI Skill 安装包（含 `SKILL.md`） |
| `extension_packages/mcp/` | 可选 Scholar AI MCP 安装包（含 `literature-mcp.json` 或 `lit-mcp.json`） |
| `packaging/` | PyInstaller spec + Inno Setup 脚本 + 品牌图标 |
| `scripts/build_windows_exe.ps1` | 9 步 Windows 发布流水线 |
| `requirements-ci.txt` / `requirements-pin.txt` | 当前 alpha 源码树的 Python 依赖快照 |

Scholar AI 相关的第三方 Skill / MCP 资源包可以放在 `extension_packages/`，供用户下载后在应用内选择本地地址安装。Skill 包根目录需有 `SKILL.md`；MCP 包需有 `literature-mcp.json` 或 `lit-mcp.json`。安装流程是：下载资源包 → 应用内选择本地包地址 → 向导绑定凭证 → 启用。凭证只在本机凭证中心保存，不进 Git。

API、MCP、Skill 的本地凭证配置见 [API_CONFIGURATION.md](API_CONFIGURATION.md)。

## 隐私与凭证

研究资料、运行配置、第三方服务凭证由用户在本机管理。API key 永不出现在前端 localStorage、控制台日志或网络响应；后端走 `env_refs` 引用，凭证不写进配置文件。MCP 工具调用前必须人工审批。

## 路线图

- macOS / Linux 安装包
- 论文实体抽取 + 实体间因果关系图（"参数 → 过程 → 微观 → 性能"、"剂量 → 通路 → 表型 → 临床"这类链条可视化）
- 前端中英双语
- 安卓 / iOS 端轻量 PDF 阅读器（不跑 AI）
- 导师组 / 课题组协作模式（在保留本地优先的前提下）
- 围绕 MCP 协议的学科插件市场
- 高校实验室私有部署版

## 许可

source-available 非商业许可。学生、个人研究者、非商业研究机构可免费下载、阅读、运行、修改。商业使用、转售、再授权、付费托管服务需作者书面授权。比赛 / 竞赛使用必须明确披露使用了 Scholar AI。详见 [LICENSE](LICENSE)。

安装包提供 SHA256 校验，可证明用户下载的二进制确实从公开源码构建。研究资料默认 SQLite 单文件 + Markdown / JSON 导出，可随时备份迁移，不被任何厂商锁定。

## 反馈

- [报告安全问题](SECURITY.md)
- [查看贡献说明](CONTRIBUTING.md)
