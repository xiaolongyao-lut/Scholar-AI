# 工作区地图

## 文献助手本体

- `literature_assistant/core/`：核心 Python 代码和核心包目录。
- `literature_assistant/core/config/`：运行配置。
- `literature_assistant/core/prompt_templates/`：提示词模板。
- `literature_assistant/core/skills/`：内置和导入的能力实现。

## 文献助手外侧支撑区

- `workspace_ai/local_state/`：本机模型/API/AI 状态文件，已在 `.gitignore` 中忽略。
- `workspace_references/project_notes/`：历史设计、模型选择、RAG 演化说明等参考文档。
- `workspace_tests/evaluation_scripts/`：评估、批处理、验证脚本。
- `workspace_tests/evaluation_data/`：评估集、goldset、metrics。
- `workspace_tests/legacy_root/`：原根目录测试迁入 `tests/legacy_root/`。
- `workspace_artifacts/generated/`：运行生成物和报告，已忽略。
- `workspace_artifacts/generated/output/`：默认 RAG 输出、chunk/doc store、重排缓存、LLM 成本日志和 gateway metrics。
- `workspace_artifacts/backups/`：本机备份和旧副本，已忽略。
- `workspace_artifacts/runtime_state/`：运行态数据库和缓存，已忽略。
- `workspace_artifacts/runtime_state/app-profile/`：桌面启动器的 Edge/Chrome 用户 profile。

## 外部参考

- `github/`：下载的外部项目和参考仓库，保持原位，不纳入文献助手核心包。
