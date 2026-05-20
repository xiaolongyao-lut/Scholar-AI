# Scholar AI

Scholar AI 是本地优先的学术研究智能体工作台，面向论文阅读、证据分析、知识沉淀、多智能体讨论和研究写作。它不只是 RAG 工具，而是把文献处理、证据增强问答、Wiki 知识库、多智能体协作、写作工作台、MCP 工具接入和 Evolution 经验沉淀组织到同一个研究流程里。

本仓库公开的是产品源码，方便下载、自用、学习和非商业研究。未经作者书面许可，不允许商业使用、盈利服务、转售或再授权。比赛/竞赛使用必须明确披露使用了 Scholar AI，不能把本项目或高度雷同版本当作原创提交。

> 当前版本为 alpha / dogfood 阶段。Windows 安装包未签名，首次安装时可能触发 SmartScreen 提示。

## 界面预览

<img width="1440" height="1000" alt="Scholar AI workbench" src="https://github.com/user-attachments/assets/f0df43ac-5745-4de3-9e82-1f69c48b76d9" />

<img width="1440" height="1000" alt="Wiki 工作台" src="https://github.com/user-attachments/assets/fd6ca5c9-c204-4747-83b5-12f591bdd761" />

<img width="1440" height="1000" alt="多智能体讨论" src="https://github.com/user-attachments/assets/068fc8cb-0ae7-4f8b-b845-bfc22161cf1b" />

<img width="1440" height="1000" alt="MCP 设置" src="https://github.com/user-attachments/assets/b1d9e41e-5038-4049-8e5a-23f1cf261a52" />

## 下载和安装

普通用户请打开 GitHub 右侧或顶部的 **Releases** 页面，下载 Windows 安装包：

```text
LiteratureAssistant-Setup-<version>-windows-x64.exe
```

GitHub 每个 tag 页面都会自动显示：

```text
Source code (zip)
Source code (tar.gz)
```

这两个是 GitHub 自动生成的源码压缩包，不是安装包，也不是已经打包好的桌面应用。如果你只是想安装软件，请下载 Releases 里的 `.exe` 安装包。

## 核心能力

- **文献阅读与材料管理**：导入、阅读、整理研究材料、论文资产和本地证据。
- **证据增强问答**：围绕本地文献库进行检索、重排、证据打包和引用感知回答。
- **Wiki 知识库**：把论文、概念、断言、来源和研究线索沉淀为可复查的知识结构。
- **多智能体讨论**：让不同研究角色围绕同一问题讨论、质询、补证和收敛。
- **写作工作台**：组织综述、提纲、草稿、引用、图表和投稿材料。
- **MCP 工具接入**：扫描本地 MCP 包，配置启动方式，绑定凭证，并在工具调用前进行人工审批。
- **Evolution 经验沉淀**：把有价值的模型观察、人工判断和工作流经验保存为长期资产。
- **本地优先运行**：研究数据、运行时状态、凭证和已安装 MCP 配置默认保留在本机。

## 公开源码结构

| 路径 | 说明 |
|---|---|
| `literature_assistant/` | Python 后端、RAG 运行时、路由、持久化、MCP、Skills、Evolution、Wiki 和写作服务。 |
| `frontend/` | React/Vite 前端工作台。 |
| `extension_packages/skills/` | 可选的 Scholar AI Skill 安装包。只放应用能读取 `SKILL.md` 并安装的包。 |
| `extension_packages/mcp/` | 可选的 Scholar AI MCP 安装包。只放应用能扫描 `literature-mcp.json` 或 `lit-mcp.json` 的包。 |
| `run_literature_assistant.py` | 工作区路径诊断入口。 |
| `sitecustomize.py` | 本地源码运行兼容钩子。 |
| `requirements-ci.txt` / `requirements-pin.txt` | 当前 alpha 源码树使用的 Python 依赖快照。 |

内部计划、测试、构建脚本、打包脚本、CI、发布证据、运行时输出、缓存、外部参考仓库、agent 配置、插件包、本机 MCP 配置、API key、credential store 和本地状态不进入公开源码树。

## 可安装扩展包

Scholar AI 相关的第三方 Skill/MCP 资源包可以放在 `extension_packages/`，供用户下载后在应用内选择本地地址并安装。这个目录只承载可安装包本身和安装器需要的公开元数据：

- Skill 包必须是 Scholar AI Skill 规范，包根目录包含 `SKILL.md`。
- MCP 包必须包含 `literature-mcp.json` 或 `lit-mcp.json`，由后端扫描后生成安装向导。
- API key、token、用户已安装的 MCP server 配置、运行时数据库、工具登录态和本机 `.env` 不属于资源包，不能提交。

普通用户的扩展安装流程是：下载资源包，打开 Scholar AI 的安装入口，选择本地包地址，按向导绑定凭证和配置项，然后启用。凭证只在本机凭证中心或运行时配置中保存，不随 Git 仓库公开。

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

## 隐私与凭证

Scholar AI 默认本地优先。根据自己的机器创建本地环境文件，不要提交真实凭证、API key、浏览器配置、模型缓存、生成结果或运行时状态。

## 发布状态

当前公开安装包基线：`0.1.6-alpha`。

`Source code (zip)` 和 `Source code (tar.gz)` 是 GitHub 自动生成的源码包，不是安装包。真正的 Windows 安装包以 `LiteratureAssistant-Setup-...exe` 这类名称作为 Release asset 发布。

## 许可

本项目是 source-available 非商业许可。你可以在非商业目的下下载、阅读、运行、学习和修改本软件。

商业使用、转售、再授权或付费托管服务，都必须先取得作者书面许可。比赛/竞赛中如果使用了本项目、修改版本或实质性代码，必须在提交材料里明确说明使用了 Scholar AI；参赛规则、成绩、资格、奖项等风险由参赛者自行承担。

详见 [LICENSE](LICENSE)。
