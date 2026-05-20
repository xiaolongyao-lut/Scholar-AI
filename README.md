# Scholar AI Workbench

本地优先的学术文献工作台，用来阅读论文、整理知识库、基于证据提问、组织多智能体讨论，并把文献材料沉淀为笔记、综述草稿和可追溯的研究资产。

本仓库公开的是产品源码，方便下载、自用、学习和非商业研究。未经作者书面许可，不允许商业使用、盈利服务、比赛/竞赛提交、转售、再授权或影响作者所有权。

## 下载和安装

普通用户请优先打开 GitHub 右侧或顶部的 **Releases** 页面，下载正式安装包。Windows 安装包名称通常类似：

```text
LiteratureAssistant-Setup-<version>-windows-x64.exe
```

GitHub 每个 tag 页面都会自动显示：

```text
Source code (zip)
Source code (tar.gz)
```

这两个是 GitHub 自动生成的源码压缩包，不是安装包，也不是已经打包好的桌面应用。如果你只是想安装软件，请下载 Releases 里的 `.exe` 安装包。

## 功能概览

- 文献导入与处理：面向 PDF 和研究文档的本地处理流程。
- 私有知识库：在本机维护文献索引、检索状态和研究材料。
- 证据增强问答：混合检索、重排、证据打包和引用感知回答。
- 研究工作台 UI：阅读、讨论、知识库导航、写作、设置和审核入口集中在一个前端界面。
- MCP 工具审批：模型调用外部工具前可以进入人工审批流程。
- Evolution 记忆通道：把有价值的模型观察或人工经验保存、忽略或提升为可复用资产。

## 公开源码结构

| 路径 | 说明 |
|---|---|
| `literature_assistant/` | Python 后端、RAG 运行时、路由、持久化、MCP、Skills、Evolution、Wiki 和写作服务。 |
| `frontend/` | React/Vite 前端工作台。 |
| `extension_packages/skills/` | 可选的文献助手 Skill 安装包。只放文献助手能读取 `SKILL.md` 并一键安装的包。 |
| `extension_packages/mcp/` | 可选的文献助手 MCP 安装包。只放文献助手能扫描 `literature-mcp.json` 或 `lit-mcp.json` 的包。 |
| `start.py` / `start_desktop.py` / `start.bat` | 本地启动入口。 |
| `run_literature_assistant.py` | 工作区路径诊断入口。 |
| `sitecustomize.py` | 本地源码运行兼容钩子。 |
| `requirements-ci.txt` / `requirements-pin.txt` | 当前 alpha 源码树使用的 Python 依赖快照。 |

内部计划、测试、构建脚本、打包脚本、CI、发布证据、运行时输出、缓存、外部参考仓库、agent 配置、插件包、本机 MCP 配置、API key、credential store 和本地状态不进入公开源码树。

## 可安装扩展包

文献助手相关的第三方 Skill/MCP 资源包可以放在 `extension_packages/`，供用户下载后在应用内选择本地地址并一键安装。这个目录只承载可安装包本身和安装器需要的公开元数据：

- Skill 包必须是文献助手 Skill 规范，包根目录包含 `SKILL.md`。
- MCP 包必须包含 `literature-mcp.json` 或 `lit-mcp.json`，由后端扫描后生成安装向导。
- API key、token、用户已安装的 MCP server 配置、运行时数据库、工具登录态和本机 `.env` 不属于资源包，不能提交。

普通用户的流程是：下载资源包，打开文献助手的安装入口，选择本地包地址，按向导绑定凭证和配置项，然后启用。凭证只在本机凭证中心或运行时配置中保存，不随 Git 仓库公开。

## 从源码运行

源码运行面向开发者。普通用户建议等待或使用 Releases 中的安装包。

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

## 配置

根据自己的机器创建本地环境文件。不要提交真实凭证、API key、浏览器配置、模型缓存、生成结果或运行时状态。

## 发布状态

当前公开源码基线：`0.1.5-alpha`。

之前的 `0.1.5-alpha-release-evidence.zip` 是发布验证证据包，不是安装包。真正的安装包会以 `LiteratureAssistant-Setup-...exe` 这类名称作为 Release asset 发布。

## 许可

本项目是 source-available 非商业许可。你可以在非商业目的下下载、阅读、运行、学习和修改本软件。

商业使用、比赛/竞赛使用、转售、再授权、付费托管服务，或任何影响作者所有权的使用，都必须先取得作者书面许可。

详见 [LICENSE](LICENSE)。
