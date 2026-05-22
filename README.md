# Scholar AI

> **面向学术研究的本地优先桌面工作台。多智能体协同讨论，回答带可追溯的页码级引用，所有数据默认留在本机。**
>
> 公开仓库：https://github.com/xiaolongyao-lut/Scholar-AI ·
> 最新版本：[v0.1.8-alpha](https://github.com/xiaolongyao-lut/Scholar-AI/releases/tag/v0.1.8-alpha)（2026-05-23）·
> [Windows 安装包下载](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/LiteratureAssistant-Setup-0.1.8-alpha-windows-x64.exe)

本仓库公开的是产品源码，方便下载、自用、学习和非商业研究。未经作者书面许可，不允许商业使用、盈利服务、转售或再授权。比赛 / 竞赛使用必须明确披露使用了 Scholar AI，不能把本项目或高度雷同版本当作原创提交。

> 当前版本为 alpha / dogfood 阶段。Windows 安装包未做代码签名，首次安装可能触发 SmartScreen 警告。

## 界面预览

<img width="1440" alt="Scholar AI 智能研读工作台" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-workbench.png" />

<img width="1440" alt="Wiki 工作台" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-wiki.png" />

<img width="1440" alt="多智能体讨论" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-discussion.png" />

<img width="1440" alt="MCP 设置" src="https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/scholar-ai-mcp-settings.png" />

## 这个程序是做什么的

Windows 桌面应用，双击安装包就能用。把研究里"读—问—讨论—写—沉淀"五个动作放在同一个界面里：

- **读**：内嵌 PDF 阅读器，高亮、便签、最后阅读页本地保存。
- **问**：围绕本地文献库做检索 + 重排 + 证据打包，回答里每段话都带 `[E:E<n>]` 引用标记，点击跳回 PDF 原文对应位置。
- **讨论**：可以同时摆 3–5 个 AI 角色（方法学审查员、数据分析师、领域专家、质疑者等），各自独立模型、独立提示词，围绕同一问题按轮次发言、互相质询、补充证据、收敛到带引用的回答。
- **写**：内嵌 TipTap 富文本编辑器，大纲 + 引用 + 图表 + 一键导出 DOCX。
- **沉淀**：Wiki 知识库 + Evolution 经验沉淀机制（候选 → 人工审核 → 提升为长期记忆，全流程有审计可回滚）。

底层不训练大模型，直接调你自己绑定的 LLM API。出厂内置 17 个 provider 适配层，覆盖多家 LLM 厂商（DeepSeek、通义千问、火山方舟、智谱、OpenAI、Anthropic、Google 等），用户配置自己的 API key 即可使用。应用本体跑在本机，仅 LLM 调用走用户配置的目的地。

## 为什么做这个

长期跟文献打交道的研究生每天都在卡同一些点：

1. **引用难以核对**。LLM 在长文档问答中有 well-documented 的 hallucination 风险——已发表的研究和各厂商自家文档都承认这一点。在文献问答场景里常见的失败模式包括：把图题或表题里的暗示性陈述强化为作者明确结论，把原文里的因果链条跳过中间环节。当前 ChatGPT / Claude / Gemini 网页版与 NotebookLM 都依赖模型自觉（NotebookLM 有 source citation 显示来源，但没有工程层面强制 reject 写入未在原文出现的引用），最终能否避免幻觉引用还是要靠用户自己逐条复核。学术写作里这种复核成本很高。
2. **Obsidian 本体不是 AI 研究 agent**。Obsidian 笔记和知识图谱很强，但本体没有 AI 能力，要让它"会查文献、能讨论、能引用证据"需要装第三方 AI 插件（Smart Connections、Copilot、Text Generator 等），每个插件单独配置 API key，模型层面各自独立运行。
3. **现有 LLM 缺少专门为研究流程定向的本地桌面客户端**。多家厂商的大模型（DeepSeek、通义千问、Kimi、OpenAI、Anthropic、Google 等）已经达到通用文献辅助可用水准。市面上有通用聊天桌面客户端（Chatbox、Cherry Studio 等）和一些 RAG 工具 demo，但产品化的、专门面向"读 + 问 + 多 agent 讨论 + 引用追溯 + 知识沉淀"完整研究流程的本地桌面客户端选项还较少。

Scholar AI 就是为这条路上的几个真实摩擦点写的。出发点是"先把自己每天踩到的坑磨平"，但磨完发现不同学科（材料、化学、机械、电子、生医等）的研究生踩的是同一批坑，所以做成了通用的桌面应用。

## 和 NotebookLM / Obsidian 比

| 能力 | Google NotebookLM | Obsidian | Scholar AI |
|---|---|---|---|
| 部署形态 | 100% 云端 | 本地软件 | 本地桌面应用，安装包一键安装 |
| 必须的账号 | Google 账号 | 无 | 无任何强制账号 |
| LLM 接入 | 仅谷歌自家模型 | 无内置，靠插件 | 任意 OpenAI 兼容 API，UI 直接配置切换 |
| PDF 阅读 | 简易内嵌 + 段落级页码引用 | 需插件 | 内嵌 PDF 阅读器 + 高亮 + 笔记 + chunk 级页面定位 |
| 证据问答 | 有，单 agent | 无 | 每条引用带页码，可点击跳回 PDF 原位 |
| 多智能体讨论 | 无 | 无 | 多角色协同：质询、补证、收敛 |
| 知识沉淀 | Notebook 持久 + 自动生成摘要 / FAQ / audio overview | 笔记 + 双链 + 图视图 | Wiki + Evolution 候选 / 审核 / 提升 |
| 写作 | study guide / FAQ / audio overview | Markdown 编辑 | TipTap 富文本 + 大纲 + 引用 + DOCX 导出 |
| 工具扩展 | 无 | Community plugins | MCP 标准接入，调用前必须人工审批 |
| 数据导出 | 受限 | 完全自由 | 完全自由（Markdown / DOCX / JSONL） |

## 和直接用 GPT / Claude / Gemini 网页版比

这个最容易问：既然 AI 模型本身是 OpenAI、Anthropic、Google 训练的，为什么不直接用它们的网页版？

事实是：**Scholar AI 不训练大模型，也调用同样的 API**——出厂内置 17 个 provider，含 GPT-4o / GPT-4.1 / o3-mini、Claude Opus 4 / Sonnet 4、Gemini 2.5 Pro / Flash、DeepSeek、通义千问 等。底层 AI 完全一样。差异在客户端工程对"研究流程"这一具体场景做了多少事。

下表每行对应实际代码，可在公开仓库源码里核验：

| 维度 | GPT / Claude / Gemini 网页版 | Scholar AI 客户端 | 对应实现 |
|---|---|---|---|
| 持久研究空间 | 持久层依赖各家自有的项目 / 记忆功能（Claude Projects、ChatGPT Custom GPTs + memory、Gemini Gems），颗粒度由产品决定 | 资料、对话、引用、Wiki 写本地 SQLite，跨会话保留，颗粒度可控 | `evolution_router.py` + `memory_router.py` + SQLite WAL |
| 文献量上限 | 单次对话上传数与单文件大小受各家产品限制（具体数值随产品演进） | 受硬盘容量限制，几百 PDF 无压力 | `extract_pdfs.py` + `extract_pdfs2.py` + `extractor_full.py` 三层解析管线 |
| PDF 解析颗粒度 | 模型通过 vision / 文档理解读 PDF，chunk 级位置与字符偏移不暴露给应用层 | 六模块联合：文本抽取 + 图片裁切 + 多模态层 + chunk 切片（默认 800 字 / 150 重叠）+ 页码 + 字符偏移 | `extract_pdfs.py` / `extractor_full.py` / `image_cropper.py` / `e_layer_multimodal.py` / `routers/resources_router/_document_extraction.py` / `_chunk_text.py:23` |
| 引用校验机制 | 无强制引用校验，依赖模型自觉与用户复核 | `citation_auditor` 在写答案前强制校验每条 `[E:E<n>]` 是否真在传给 LLM 的上下文中存在，否则拒绝写入 | `literature_assistant/core/citation_auditor.py` |
| 检索 / 重排 | 检索与重排细节不暴露给应用层，无法在客户端定制 | 五模块重排管线：客户端 + 预算控制 + 缓存 + 逻辑缓存 + 运行时配置 | `reranker_client.py` + `rerank_budget.py` + `rerank_cache.py` + `rerank_logic_cache.py` + `rerank_runtime_config.py` |
| 多智能体讨论 | 单 agent | 多 agent 协同：独立模型 / 提示词 / 工具权限，按轮次发言互相质询 | `discussion_router.py` + `discussion_advanced_router.py` |
| 上下文预算可见性 | 上下文管理由产品决定，前端通常看不到 token 使用情况 | Envelope guard 显式预算，超额即返回 422 告知具体超出位置；历史走动态预算 + 滚动窗口 | `chat_router.py` `MAX_CHAT_QUERY_LENGTH = 80_000` + FD-13 元数据通道 + FD-14 动态预算 |
| 成本结构 | 订阅制（具体月费随各家产品变化） | 按 token 计费，可按用量精细控制 | `llm_cost_router.py` + `rerank_budget.py` |
| 工具扩展 | 扩展走各家自有协议（GPT Actions、Claude MCP、Gemini Extensions），主要面向云端 hosted 工具 | MCP 标准接入第三方工具，包含本地 stdio 工具，每次调用前弹窗审批，审计可查 | `mcp_router.py` + `mcp_installer_router.py` |
| 写作工作台 | 无内嵌富文本写作工作台，常见做法是复制到外部编辑器 | 内嵌 TipTap + 大纲 + 引用 + 图表 + 一键 DOCX 导出 | `frontend/src/components/TipTapEditor/` + `services/exportApi.ts` |
| 知识沉淀 | 持久层依赖各家自有的项目 / 记忆 / Gem 功能 | Wiki + Evolution：候选 → 审核 → 提升 → 长期记忆 | `wiki_router.py` + `evolution_router.py` |
| 可定制与可审查 | 客户端实现不公开 | 10.2 万行 Python + 3.5 万行 TS 全公开 | 公开仓库 |

简单说：通用聊天产品偏向广泛对话场景，单次任务、跨平台都能用；Scholar AI 是专门为"研究流程"做了客户端工程，比如读几十到上百篇文献做综述、每个观点要可追溯到具体页码、多角色围绕同一问题讨论这类场景。

## 技术实现

### 架构

```
┌─────────────────────────────────────────────────────────┐
│  Frontend（React + Vite + TipTap + PDF.js）             │
│   · 35,227 行 TS/TSX                                    │
│   · 路由级 + 组件级两层 lazy 代码分割                     │
│   · 57 个测试文件 / 428 个 vitest 用例                    │
│   · TypeScript 类型完全从 OpenAPI 自动生成                │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP（OpenAPI 3，168 端点）
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Backend（Python + FastAPI + Pydantic v2）              │
│   · 102,156 行 Python                                   │
│   · 26 个 router 模块                                   │
│   · 271 个测试文件 / 2,297 个 pytest 用例                │
│   · SQLite 本地持久化（WAL 模式 + busy_timeout）          │
└────────────────────────┬────────────────────────────────┘
                         │
       ┌─────────────────┼──────────────────┐
       ▼                 ▼                  ▼
  17 provider     5 模块 rerank         MCP 工具运行时
  适配 + key 池    + 预算追踪          stdio/http/ws
  + failover                          + env_refs 凭证桥
                                      + 调用人工审批
```

### 关键工程决策

- **不静默失败**：引用追溯走 `citation_auditor` 强制校验，引用没真出现在传给 LLM 的上下文里就直接拒绝写入，而不是让 LLM 自觉。
- **不冒充完成**：envelope guard 在多 agent 历史 + 当前证据总长度超出预算时返回 422 告知具体超出位置，避免回答看起来完整但上下文已被截断的情况。
- **不绑死厂商**：17 provider 适配层 + key 池 + 自动 failover，用户随时切换多家厂商模型。
- **不留明文凭证**：API key 永不出现在前端 localStorage / 控制台日志 / 网络响应；后端走 `env_refs` 引用模式，凭证不写进配置文件。
- **不靠手动验收**：Release 流水线 9 步固定脚本——前端构建 → PyInstaller 分析 → forbidden-path 扫描 → onedir 构建 → secret 扫描 → Inno Setup 编译 → 首次启动冻结烟测，9 步全过才出安装包。
- **工具调用前人工审批**：MCP 工具每次调用前弹窗审批（可记住"本会话内同意"），审计面板可查所有历史调用。

### 工程现状

| 项 | 数值 |
|---|---|
| Backend Python | 102,156 行 |
| Frontend TS/TSX（不含测试 / 生成） | 35,227 行 |
| Router 模块 | 26 个 |
| OpenAPI 端点 | 168 个 |
| Backend 测试 | 271 文件 / 2,297 用例（提交前自律回归） |
| Frontend 测试 | 57 文件 / 428 用例（前端改动后跑 vitest + build） |
| 内置 LLM provider | 17 个 |
| 已发布版本 | 0.1.5-alpha（2026-05-19）、0.1.6-alpha、0.1.7-alpha、0.1.8-alpha（2026-05-23） |
| Windows 安装包 | 约 142 MB，SHA256 可校验 |

## 设计支持的场景（早期阶段，尚在积累实际用户案例）

| 场景 | 工作流 |
|---|---|
| 做文献综述 | 导入一批 PDF → 多 agent 讨论各文献方法论差异 → 证据问答抽取每篇核心论点 → 进入 Wiki 沉淀 → 写作工作台直接引用 |
| 准备开题 / 中期 / 答辩 | 已读文献喂入 → 让"质疑者 agent"故意挑刺 → 提前发现答辩薄弱点 → 一键导出 DOCX |
| 跟导师讨论某个研究方向 | 把方向相关 5–10 篇文献导入 → 多 agent 讨论生成带引用的方向调研 → 给导师看带页码可追溯的简报 |
| 投稿前自审 | 把草稿喂入 → 让多 agent 模拟审稿人、编辑、作者三方对话 → 提前发现可能被 reject 的薄弱论证 |
| 跨学科 / 跨模型对比 | 同时配置多个 LLM provider，让不同基座模型的 agent 互相讨论同一问题，对比判断差异 |

## 谁会用得上

当前是 alpha 阶段，以早期个人使用为主，尚未积累大规模公开用户案例。设计上面向以下几类潜在用户：

- **理工科研究生**：材料、化学、机械、电子、生医等需要持续读大量文献并写综述论文的方向。
- **课题组导师与博后**：需要把已读文献沉淀成可复查、可分享的研究知识库的人。
- **跨学科研究者**：需要同时调度多个 LLM 对比判断的人（不同基座模型对同一文献的解读差异本身就是研究信号）。
- **数据敏感的实验室**：在投稿、涉密、未公开数据有上传第三方云端限制的场景。
- **预算受限的学生**：相比订阅制月费，按 token 计费可根据实际用量更精细地控制成本。

## 下载和安装

普通用户请从 **Releases** 下载 Windows 安装包：

- [当前版本 0.1.8-alpha 发布页](https://github.com/xiaolongyao-lut/Scholar-AI/releases/tag/v0.1.8-alpha)
- [下载 0.1.8-alpha Windows 安装包](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/LiteratureAssistant-Setup-0.1.8-alpha-windows-x64.exe)
- [查看 0.1.8-alpha SHA256 校验文件](https://github.com/xiaolongyao-lut/Scholar-AI/releases/download/v0.1.8-alpha/SHA256SUMS.txt)

## 从源码运行

源码运行面向开发者。普通用户建议使用 Releases 中的 Windows 安装包。

环境要求：

- Python 3.10 或更新版本。
- Node.js 20 或更新版本。
- Windows PowerShell。

安装 Python 依赖：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements-ci.txt
```

安装前端依赖：

```powershell
cd frontend
npm ci
```

在仓库根目录启动后端：

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
| `literature_assistant/` | Python 后端、RAG 运行时、路由、持久化、MCP、Skills、Evolution、Wiki 和写作服务。 |
| `frontend/` | React/Vite 前端工作台。 |
| `extension_packages/skills/` | 可选的 Scholar AI Skill 安装包。只放应用能读取 `SKILL.md` 并安装的包。 |
| `extension_packages/mcp/` | 可选的 Scholar AI MCP 安装包。只放应用能扫描 `literature-mcp.json` 或 `lit-mcp.json` 的包。 |
| `packaging/` | PyInstaller spec + Inno Setup 脚本 + 品牌图标资产。 |
| `scripts/build_windows_exe.ps1` | 9 步 Windows 发布流水线（前端构建 → PyInstaller → forbidden-path 扫描 → secret 扫描 → Inno 编译 → 冻结烟测）。 |
| `run_literature_assistant.py` | 工作区路径诊断入口。 |
| `sitecustomize.py` | 本地源码运行兼容钩子。 |
| `requirements-ci.txt` / `requirements-pin.txt` | 当前 alpha 源码树使用的 Python 依赖快照。 |

## 可安装扩展包

Scholar AI 相关的第三方 Skill / MCP 资源包可以放在 `extension_packages/`，供用户下载后在应用内选择本地地址并安装。这个目录只承载可安装包本身和安装器需要的公开元数据：

- Skill 包必须是 Scholar AI Skill 规范，包根目录包含 `SKILL.md`。
- MCP 包必须包含 `literature-mcp.json` 或 `lit-mcp.json`，由后端扫描后生成安装向导。

普通用户的扩展安装流程是：下载资源包，打开 Scholar AI 的安装入口，选择本地包地址，按向导绑定凭证和配置项，然后启用。凭证只在本机凭证中心或运行时配置中保存，不随 Git 仓库公开。

API、MCP 和 Skill 的本地凭证配置方式见 [API_CONFIGURATION.md](API_CONFIGURATION.md)。

## 隐私与凭证

Scholar AI 默认本地优先。研究资料、运行配置和第三方服务凭证由用户在本机管理。API key 永不出现在前端 localStorage、控制台日志或网络响应；后端走 `env_refs` 引用模式，凭证不写进配置文件。MCP 工具调用前必须人工审批。

## 接下来想做什么

- **macOS / Linux 安装包**：当前只有 Windows，下一步打 macOS 安装包 + Linux Flatpak。
- **Inspiration P3 因果 DAG**：从论文里自动抽取命名实体 + 实体之间的因果关系图，把"文献网络"变成可视化的因果图（举例：材料类的"参数 → 过程 → 微观 → 性能"、生医类的"剂量 → 通路 → 表型 → 临床"等链条都能这样可视化）。
- **前端国际化**：中英双语切换。
- **移动端轻量阅读器**：安卓 / iOS 端只看 PDF + 引用，不跑 AI（重 AI 仍走桌面端）。
- **导师组 / 课题组协作模式**：在保留本地优先的前提下，提供"共享研究空间"。
- **学科插件市场**：围绕 MCP 协议建设学科特化工具包（材料数据库、专利检索、化学结构、生医文献等）。
- **高校实验室私有部署版**：给有数据安全要求的实验室提供私有部署。

## 当前限制（诚实陈述）

- **平台**：当前只有 Windows 安装包，macOS / Linux 还需手动从源码运行。
- **签名**：Windows 安装包未做代码签名，首次安装可能触发 SmartScreen 警告（在做签名预算评估）。
- **LLM 成本由用户承担**：默认不绑定任何 LLM 服务的代付，用户必须自备 API key。换言之 Scholar AI 不在 API 调用上抽成，但用户需自己核算成本。
- **多人协作**：当前是单机本地优先架构，多人协作模式还在路线图上。
- **学科覆盖**：当前默认的 chunk 策略与重点关注链条预设偏向工程类学科。其他学科（化学、医学、生物等）可以在"用户话术层"自行调整重点关注链条，举例：把"参数 → 过程 → 微观 → 性能"换成"剂量 → 通路 → 表型 → 临床"或"假设 → 实验设计 → 数据 → 结论"。
- **alpha 阶段**：版本号 0.1.8-alpha 反映现状——核心链路稳定（已通过 2,297 + 428 个自动化测试 + 9 步发布流水线），但桌面 GUI 安装包仍需手动烟测，仍可能遇到边界 case。

## 许可

本项目是 source-available 非商业许可。学生、个人研究者、非商业研究机构可以免费下载、阅读、运行、修改。商业使用、转售、再授权或付费托管服务，都必须先取得作者书面许可。比赛 / 竞赛中如果使用了本项目、修改版本或实质性代码，必须在提交材料里明确说明使用了 Scholar AI；参赛规则、成绩、资格、奖项等风险由参赛者自行承担。

代码可审查：产品运行时代码（`literature_assistant/` 后端约 10 万行 Python + `frontend/` 前端核心 TS/TSX）在公开仓库可审查。安装包提供 SHA256 校验，可证明用户下载的二进制确实从公开源码构建。数据可迁移：研究资料默认 SQLite 单文件 + Markdown / JSON 导出，可随时备份、迁移、二次加工，不被任何厂商锁定。

详见 [LICENSE](LICENSE)。

## 反馈

- [报告安全问题](SECURITY.md)
- [查看贡献说明](CONTRIBUTING.md)
