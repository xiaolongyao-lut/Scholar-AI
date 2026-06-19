# RAG 文献助手工作区

这个目录是文献助手本体入口。核心后端、算法、路由、配置和能力代码已集中到 `core/`。

## 目录边界

|路径|用途|
|---|---|
|`core/`|文献助手核心代码：后端服务、RAG/检索/重排/写作运行时、skills、配置模板|
|`../frontend/`|前端工程，保持原位，避免 Vite/构建脚本路径漂移|
|`../workspace_ai/`|AI/模型/本机状态，不属于核心源码|
|`../workspace_references/`|参考资料、历史设计、外部实验项目|
|`../workspace_tests/`|测试、评估脚本、评估数据、诊断输出|
|`../workspace_artifacts/`|生成物、运行态、备份、连通性结果|
|`../github/`|外部 GitHub 参考仓库，继续保留原位|

## 兼容策略

- 根目录 `sitecustomize.py` 会把 `literature_assistant/core` 加入 `sys.path`。
- 旧代码里的 `import chunk_vector_store`、`import python_adapter_server` 等顶层导入仍可工作。
- 新代码优先放入 `literature_assistant/core`，测试放入 `tests/` 或 `workspace_tests/`。

## 用户入口

- 双击或运行根目录 `start.bat`，由 `start.py` 启动前端和后端。
- 路径诊断：`python run_literature_assistant.py paths`（等价 `python -m literature_assistant paths`）。
- Wiki 状态诊断：`python run_literature_assistant.py wiki status`。
- Wiki doctor dry-run：`python run_literature_assistant.py wiki doctor`。
- 后端开发启动：在仓库根目录执行 `python -m uvicorn literature_assistant.core.python_adapter_server:app --host 127.0.0.1 --port 8000`。

## Agent 源码入口

- 文献写作、综述、引言、证据包、embedding/rerank、analysis chain、图表公式引用和 DOCX/LaTeX 导出任务，先读 `AGENT_SOURCE_MAP.md`。
- MCP 工具超时或缺工具时，先按 `AGENT_SOURCE_MAP.md` 用源码入口核验能力；不要直接自建 hash embedding、临时 rerank 或旁路写作流水线。

## 路径工程约定

- 代码入口统一先执行 `literature_assistant.bootstrap.configure_runtime_paths()`，不要依赖用户当前工作目录。
- 运行输出统一写入 `../workspace_artifacts/generated/output/`，可用 `LITERATURE_ASSISTANT_OUTPUT_ROOT` 覆盖。
- 运行态数据库、浏览器 profile、锁和本机状态优先写入 `../workspace_artifacts/runtime_state/`，避免污染核心代码区。
- 外部参考仓库继续保留在 `../github/`，核心代码不得把它当作可修改工作区。
- 本次路径硬化记录见 `00-index/path-hardening-record.md`。

## 回档

主回档脚本：

```powershell
powershell -ExecutionPolicy Bypass -File "<REPO_ROOT>\.rollback_snapshots\internal-literature-workspace-20260501_020742\rollback.ps1"
```

## 待处理

- `my-project/` 是嵌套 Git 实验仓库，移动时有文件被进程占用；当前源目录仍保留 `src/`、`tests/`，目标侧保留已迁入部分：`workspace_references/experiments/my-project/`。
- `.app-profile/` 是旧浏览器运行态目录；新启动器默认使用 `workspace_artifacts/runtime_state/app-profile/`，旧目录可在确认浏览器关闭后归档。
