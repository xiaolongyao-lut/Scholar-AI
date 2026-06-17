# 路径硬化记录

## 执行原则

- 风险操作前先创建 `.rollback_snapshots/` 快照，避免在多人 Agent 并行时不可逆移动。
- 参考成熟工程做法：代码包可导入、入口不依赖当前目录、运行态与生成物不混入源码目录。
- `github/` 保持外部参考仓库定位，不参与文献助手核心整理。

## 当前布局

- 核心代码：`literature_assistant/core/`
- 启动入口：`start.py`、`run_literature_assistant.py`
- 运行输出：`workspace_artifacts/generated/output/`
- 运行态：`workspace_artifacts/runtime_state/`
- 浏览器 profile：`workspace_artifacts/runtime_state/app-profile/`
- 参考/实验：`workspace_references/`
- 评估/诊断：`workspace_tests/`

## 路径入口

- `literature_assistant/bootstrap.py`：统一配置 `sys.path`、环境默认值和工作区目录。
- `literature_assistant/core/project_paths.py`：统一维护 repo/core/frontend/output/runtime/profile 等路径。
- `.venv-1/Lib/site-packages/literature_assistant_core.pth`：注册仓库根目录和 core 目录，兼容外部 cwd 直接导入。
- `sitecustomize.py`：从仓库根目录运行时自动补充兼容路径。

## 可回档位置

- `<REPO_ROOT>\.rollback_snapshots\internal-literature-workspace-20260501_020742`
- `<REPO_ROOT>\.rollback_snapshots\path-hardening-20260501_024551`
- `<REPO_ROOT>\.rollback_snapshots\my-project-code-move-20260501_030802`

## 残留说明

- `my-project/src` 和 `my-project/tests` 中的 30 个源码/测试文件已移动到 `workspace_references/experiments/my-project/`。
- 2026-05-01 清理时确认根目录 `my-project/` 仅剩 `.squad/memory` 运行态文件；释放旧 Python 进程 `PID 33444` 对 SQLite 的锁后已删除该空壳目录。
- 旧 UTF-16LE 调试脚本 `workspace_tests/evaluation_scripts/debug_simple.py` 已替换为 UTF-8 等价脚本，原文件备份到 `workspace_artifacts/backups/encoding-fixes-20260501_0334/debug_simple.py.utf16.bak`。

## 2026-05-01 收口验证

- 成熟方案对齐：pytest 官方文档确认默认导入模式会调整 `sys.path`；Python 官方 `site` 文档确认 `.pth` 是标准路径配置机制；Uvicorn 官方文档确认 ASGI 入口格式为 `"<module>:<attribute>"`。
- 测试导入兼容：`tests/conftest.py` 现在确保 `literature_assistant/core` 优先于实验目录，避免 `workspace_references/experiments/my-project/src/routers` 抢占正式 `routers` 包。
- 旧测试兼容：恢复 `_search_chunks_hybrid`、`bm25_rank`、`HybridSearchRuntime` 三个遗留接口，底层仍复用当前核心检索/资源路由逻辑。
- 活跃入口修复：`.github/copilot-instructions.md` 后端入口更新为 `literature_assistant.core.python_adapter_server:app`，并明确新代码优先包式导入；`.github/skills/ruff-recursive-fix/SKILL.md`、`workspace_tests/evaluation_scripts/system_verification.py`、`workspace_tests/evaluation_scripts/verify_production_readiness.py` 已对齐新路径。
- 活跃配置扫描：`.vscode`、`.github/workflows`、`.github/skills` 中不再存在旧 `python_adapter_server.py` / `uvicorn python_adapter_server` / `my-project/src` 启动残留；`.kilo`、`.squad` 中的旧文件名视为历史审计引用，不作为执行入口。
- 验证结果：`python -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests/conftest.py workspace_tests/evaluation_scripts` 通过。
- 验证结果：`python -m pytest tests --collect-only -q` 收集 `1226` 个测试，通过。
- 验证结果：`python run_literature_assistant.py paths` 输出 repo/core/frontend/output/runtime/reference 路径，通过。
- 验证结果：从外部 cwd 导入 `python_adapter_server`、`routers.resources_router`、`HybridSearchRuntime` 成功；临时目录没有 `.env` 的 embedding key 日志仅为配置告警，不影响导入。
- 验证结果：`workspace_tests/evaluation_scripts/system_verification.py --json` 返回 `passed=23, failed=0, warnings=0`。

## 2026-05-01 AI 工作规范

- 新增 `AI_WORKSPACE_GUIDE.md` 作为整理后仓库的 AI 主工作规范，覆盖当前布局、导入规则、入口命令、弃用命令、路径/输出规则、验证期望和回档纪律。
- `AGENTS.md`、`GEMINI.md`、`CLAUDE.md`、`.github/copilot-instructions.md`、`.squad/copilot-instructions.md` 已指向 `AI_WORKSPACE_GUIDE.md`，避免不同 AI 按旧根目录入口执行。
- 规范明确：`github/` 是外部 RAG/reference 仓库，默认只读；“整理我的项目”应限定在 `Modular-Pipeline-Script` 的 active literature-assistant layout 内。

## 2026-05-01 计划文件统一

- 新增 `docs/plans/` 作为项目计划、规格、AI 执行计划的唯一权威目录。
- 成熟方案对齐：The Turing Way 的项目文档/roadmap 思路、Diátaxis 的用途分层文档模型、Read the Docs 的 Diátaxis 实践说明，均支持把计划/规格作为可导航的项目文档集中管理，而不是散落到工具私有目录。
- 当前主计划迁移到 `docs/plans/active/2026-04-27-full-project-build-master-plan.md`。
- `.kilo/plans/`、`.copilot-tracking/plans/`、`docs/superpowers/specs/` 中的活跃计划/规格文件已迁移到 `docs/plans/` 对应子目录，旧路径仅保留同名 redirect stub。
- `AI_WORKSPACE_GUIDE.md`、`AGENTS.md`、`GEMINI.md`、`CLAUDE.md`、`.github/copilot-instructions.md`、`.squad/copilot-instructions.md` 已更新：新计划文件必须放在 `docs/plans/`，不要再分散写到工具私有目录。
- 活跃 Squad 路由表已从旧 `active .kilo master plan` 改为 `docs/plans/active/`，避免长跑收口继续读取旧计划目录。
