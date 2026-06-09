# Scholar AI

Scholar AI 是面向文献综述、课题调研和论文写作的本地优先研究工作台。它适合“读几十到上百篇文献、围绕同一问题反复追问、每个观点都要能追溯到具体页码”的场景：把 PDF 阅读、证据检索、多智能体讨论、引用校验、写作和知识沉淀放在同一个桌面应用里。

最新版本 [v0.1.8.1](https://github.com/xiaolongyao-lut/Scholar-AI/releases/tag/v0.1.8.1)（2026-05-23）·
[Windows 安装包](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.1/Scholar-AI-Setup-0.1.8.1-windows-x64.exe) ·
[SHA256](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.1/SHA256SUMS.txt)

当前是 alpha / dogfood 阶段，Windows 安装包未做代码签名，首次安装可能触发 SmartScreen 警告。

## 它能做什么

把研究里“读、问、讨论、写、沉淀”几个动作串成一个闭环：

- **读文献**：内嵌 PDF 阅读器，支持高亮、便签、阅读位置保存。
- **问问题**：从本地文献库检索证据，回答带页码级引用，点击引用能回到原文位置。
- **多角色讨论**：方法学审查员、领域专家、数据分析师、质疑者等角色围绕同一问题按轮次讨论，互相质询、补证据、收敛结论。
- **写作整理**：内嵌 TipTap 富文本编辑器，支持大纲、引用、图表和 DOCX 导出。
- **知识沉淀**：Wiki + Evolution 经验沉淀，把临时发现审核后沉淀为长期知识。
- **本地优先**：资料、对话、引用、Wiki 默认写入本机 SQLite；LLM 调用走用户自己配置的 API。

## 文献入库与本地语义路由

项目内上传的文献会在上传时完成切块和索引；工作台里的“入库模式”只处理项目绑定源文件夹中尚未入库的文件：

- **无入库**：只检索已经切块入库的内容。
- **按需入库**：根据当前问题筛选源文件夹里的待索引文件，先切块再检索，适合刚接入大量文献或卷次分析前的首次提问。
- **全量入库**：先处理源文件夹里所有待索引文件，再开始检索。

语义路由由 embedding 和 rerank 两段组成。Embedding 把文本转成向量，通常填写 OpenAI 兼容 `/v1` 地址和模型 ID；rerank 对候选证据重排，通常填写 Cohere 兼容 `/rerank` 完整端点和模型 ID。本地服务如果没有鉴权，访问密钥可以留空。

## 下载

普通用户建议直接下载 Windows 安装包：

- [v0.1.8.1 发布页](https://github.com/xiaolongyao-lut/Scholar-AI/releases/tag/v0.1.8.1)
- [下载 Windows 安装包](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.1/Scholar-AI-Setup-0.1.8.1-windows-x64.exe)
- [SHA256 校验文件](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8.1/SHA256SUMS.txt)

## 界面预览

深色模式：
多智能体讨论
<img width="2162" height="1407" alt="scholar-ai-discussion" src="https://github.com/user-attachments/assets/7f173a14-a800-4fd9-ba96-fea84ce4e435" />
系统设置
<img width="2162" height="1407" alt="scholar-ai-mcp-settings" src="https://github.com/user-attachments/assets/96386a5a-d5be-4e7e-a27f-14c3c966596d" />
wiki界面
<img width="2162" height="1407" alt="scholar-ai-wiki" src="https://github.com/user-attachments/assets/b9117dea-8dde-40b9-9f29-fdc8f88cfb8c" />
智能研读
<img width="2162" height="1407" alt="scholar-ai-workbench" src="https://github.com/user-attachments/assets/4b12189b-b6af-4d62-bdf1-b28dd62afbd3" />

浅色模式
多智能体讨论
<img width="2162" height="1407" alt="scholar-ai-discussion-light" src="https://github.com/user-attachments/assets/b91d4828-a769-4949-865c-91f49e06dbe0" />
智能研读
<img width="2162" height="1407" alt="scholar-ai-workbench-light" src="https://github.com/user-attachments/assets/8dd46fe0-58f8-443c-ba18-9f19f196a5cf" />

## 为什么不直接用 NotebookLM、Obsidian 或 GPT 网页版

LLM 在长文档问答里容易生成看似可信、但无法回到原文核验的引用。NotebookLM 有 source citation，但不会在工程层面强制拦截未出现在原文中的引用；ChatGPT / Claude / Gemini 网页版也主要依赖模型自己保持准确。学术写作里，这类引用逐条复核成本很高。

Obsidian 本体没有 AI 能力，要"会查文献、能讨论、能引用证据"得装第三方插件，每个插件单独配置访问密钥。

Chatbox、Cherry Studio 这类通用聊天桌面客户端更适合日常对话和模型调试。Scholar AI 重点服务学术研究流程：从读文献、查证据、组织讨论，到整理结论和写作导出，尽量减少在多个工具之间来回复制、核对和整理。

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

Scholar AI 不训练大模型，调的就是 OpenAI、Anthropic、Google、DeepSeek 等 API。底层 AI 完全一样。区别在于 Scholar AI 把这些模型接进了一个完整的研究工作流：

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

换句话说，Scholar AI 的重点不在“换一个模型聊天”，而在把研究过程里反复发生的证据整理、引用复核、多人视角讨论和写作交付做成一个连贯的本地工作流。

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
  适配 + 凭证池    + 预算追踪          stdio / http / ws
  + failover                          + 本地凭证绑定
                                      + 调用人工审批
```

为了让结果更容易复核，应用里做了几层约束：

- 回答里的引用必须来自本次传给模型的证据上下文；如果引用对不上原文，就不会写入结果。
- 多智能体讨论会检查上下文长度；证据或历史记录太长时会直接提示超出位置，而不是悄悄截断后继续回答。
- 内置多家模型服务商适配和凭证池，可以按需要切换模型，也能在单个服务不可用时自动换路。
- 第三方服务密钥不放在浏览器存储、控制台日志或网络响应里；配置文件只保存本地凭证引用。
- 发布安装包前会自动做构建、路径检查、敏感信息扫描和首次启动检查，通过后才生成安装包。
- MCP 工具调用前需要用户确认，历史调用可以在审计面板里查看。

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

`--port` 后面的数字可以按本机空闲端口调整。Uvicorn 也支持 `UVICORN_PORT` 环境变量；命令行里的 `--port` 优先级更高。

启动前端：

```powershell
cd frontend
npm run dev
```

前端开发端口默认由 `frontend/vite.config.ts` 管理，也可以启动时临时指定，例如 `npm run dev -- --port 3500`，或在 PowerShell 中先设置 `$env:VITE_DEV_PORT=3500` 再运行 `npm run dev`。如果端口被占用，Vite 会自动尝试下一个可用端口，实际地址以终端输出为准。

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

研究资料、运行配置、第三方服务凭证由用户在本机管理。第三方服务密钥不会出现在前端 localStorage、控制台日志或网络响应；配置文件只保存本地凭证引用。MCP 工具调用前必须人工审批。

## 数据和日志放在哪

**安装版（Windows）**：所有数据集中在 `%APPDATA%\LiteratureAssistant\`，可直接在文件资源管理器地址栏粘贴这串地址回车打开。

- 知识库切块和索引：`projects\{项目ID}\`（每个项目一个子文件夹）
- 应用日志：`runtime_state\logs\backend.log`（自动轮转，保留最近 5 份）
- 浏览器配置 / 临时状态：`runtime_state\app-profile\`

遇到问题时，把 `backend.log` 拷一份发我或附在反馈里就行 —— 后端报错、PDF 加载失败原因、卷次分析的去重统计、前端崩溃都会写在这一个文件里。

**从源码运行**：上面这些路径对应到仓库内的 `workspace_artifacts\`。

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

## 反馈

- [报告安全问题](SECURITY.md)
- [查看贡献说明](CONTRIBUTING.md)
