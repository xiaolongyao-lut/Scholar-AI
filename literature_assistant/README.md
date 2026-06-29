# RAG 文献助手工作区

这个目录是文献助手本体入口。核心后端、算法、路由、配置和能力代码已集中到 `core/`。

## 目录边界

|路径|用途|
|---|---|
|`core/`|文献助手核心代码：后端服务、RAG/检索/重排/写作运行时、skills、配置模板|
|`../frontend/`|前端工程，保持原位，避免 Vite/构建脚本路径漂移|
|`../tests/`|公开回归测试|
|`../agent_mcp_server/`|Claude / Codex 本地 MCP 工具箱|

## 兼容策略

- 根目录 `sitecustomize.py` 会把 `literature_assistant/core` 加入 `sys.path`。
- 旧代码里的 `import chunk_vector_store`、`import python_adapter_server` 等顶层导入仍可工作。
- 新代码优先放入 `literature_assistant/core`，公开回归测试放入 `tests/`。

## 用户入口

- 双击或运行根目录 `start.bat`，由 `start.py` 启动前端和后端。
- 路径诊断：`python run_literature_assistant.py paths`（等价 `python -m literature_assistant paths`）。
- Wiki 状态诊断：`python run_literature_assistant.py wiki status`。
- Wiki doctor dry-run：`python run_literature_assistant.py wiki doctor`。
- 后端开发启动：在仓库根目录执行 `python -m uvicorn literature_assistant.core.python_adapter_server:app --host 127.0.0.1 --port 8000`。

## 路径工程约定

- 代码入口统一先执行 `literature_assistant.bootstrap.configure_runtime_paths()`，不要依赖用户当前工作目录。
- 运行输出统一写入 `../workspace_artifacts/generated/output/`，可用 `LITERATURE_ASSISTANT_OUTPUT_ROOT` 覆盖。
- 运行态数据库、浏览器 profile、锁和本机状态优先写入 `../workspace_artifacts/runtime_state/`，避免污染核心代码区。
