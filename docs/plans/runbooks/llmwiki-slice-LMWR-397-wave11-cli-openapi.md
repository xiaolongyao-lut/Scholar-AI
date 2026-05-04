# LLM-Wiki 集成切片 Runbook

> LMWR-397（关联 LMWR-389~403）· Wave 11 API contract 收口

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-397 |
| 简短描述 | 为 Wave 11 收口 wiki status/compile/query/pages/review/doctor 的 API contract、CLI dry-run 入口与 full app OpenAPI named schema。 |
| Wave | Wave 11 |
| 执行者 | Copilot |
| 开始时间 | 2026-05-04T09:59:32Z |

---

## 1. 回档点

> **每个非平凡代码切片开始前必须创建。**

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-wave11-cli-openapi-slice"
```

| 字段 | 值 |
| ---- | ---- |
| 回档命令 | `py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-wave11-cli-openapi-slice"` |
| 恢复命令 | `git restore --source=HEAD --worktree literature_assistant/__main__.py literature_assistant/core/python_adapter_server.py literature_assistant/README.md docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md docs/plans/active/2026-05-03-llmwiki-execution-decisions.md ; Copy-Item "C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-175932-lmwr-wave11-cli-openapi-slice\untracked\tests\wiki\test_wiki_router.py" "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\tests\wiki\test_wiki_router.py" -Force ; Remove-Item tests/wiki/test_wiki_cli.py, docs/plans/runbooks/llmwiki-slice-LMWR-397-wave11-cli-openapi.md -ErrorAction SilentlyContinue` |
| 快照文件/stash ref | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-175932-lmwr-wave11-cli-openapi-slice` |

---

## 2. 成熟方案研究

| 参考来源 | 路径 | 关键借鉴点 |
| ---------- | ------ | ----------- |
| 本项目 API contract smoke | `tests/test_intelligent_chat_router.py` | full app `openapi.json` contract 验证模式：既查 path，又查 named schema。 |
| 本项目 OpenAPI named schema contract | `tests/test_resources_export_contract.py` | 用 `$ref` 锁定稳定 response/request schema，避免接口漂移。 |
| 现有 wiki router contract | `tests/wiki/test_wiki_router.py` | 复用已落地的 router skeleton，CLI 不重复实现 status/doctor 逻辑。 |

---

## 3. 实现记录

### 新增文件

| 文件 | 目的 |
| ---- | ---- |
| `tests/wiki/test_wiki_cli.py` | 锁定 `python -m literature_assistant wiki status\|doctor` 与 wrapper 输出合同。 |

### 修改文件

| 文件 | 改动摘要 |
| ---- | -------- |
| `literature_assistant/__main__.py` | 新增 `wiki status`、`wiki doctor` dry-run 诊断入口；保持 `paths` 兼容。 |
| `literature_assistant/core/python_adapter_server.py` | 显式注册 `Wiki` OpenAPI tag，保证 full app schema 可发现。 |
| `tests/wiki/test_wiki_router.py` | 新增 full app OpenAPI contract、status stale、compile/query request surface、pages filter 等测试，锁定 `/api/wiki/*` 合同。 |
| `literature_assistant/README.md` | 补充 `run_literature_assistant.py wiki status\|doctor` 用户入口说明。 |
| `docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md` | 回填 Wave 11 首刀进展与下一步 open item。 |
| `docs/plans/active/2026-05-03-llmwiki-execution-decisions.md` | 同步 Wave 11 首刀结果与当前下一步行动。 |

---

## 4. 验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_wiki_router.py tests\wiki\test_wiki_cli.py -q
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py wiki status
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py wiki doctor
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\__main__.py literature_assistant\core\python_adapter_server.py tests\wiki\test_wiki_router.py tests\wiki\test_wiki_cli.py
```

| 检查项 | 结果 |
| ------ | ---- |
| compileall | PASS |
| focused pytest | PASS（最终 `15 passed in 1.81s`） |
| CLI wrapper smoke | PASS（status/doctor 均返回机器可读 JSON） |
| 全量 pytest（可选） | SKIP（本切片未触达更大面，先保持 focused gate） |

---

## 5. 证据包

### Facts

- `python -m literature_assistant wiki status|doctor` 已可用，且 `run_literature_assistant.py` wrapper 可直接复用。
- full app OpenAPI 现在显式包含 `Wiki` tag，并对 `/api/wiki/status`、`/api/wiki/compile`、`/api/wiki/query`、`/api/wiki/pages`、`/api/wiki/doctor` 暴露稳定 schema 引用。
- `WikiStatusResponse` 已覆盖 `stale` 字段；有页面但缺 query index 时标记 stale，对齐索引后恢复 `false`。
- focused 验证 `pytest tests/wiki/test_wiki_router.py tests/wiki/test_wiki_cli.py -q` 通过，最终结果为 `15 passed`。

### Decision

- CLI 层不重复实现 wiki 诊断逻辑，而是直接复用 `wiki_router` 的 status/doctor contract 作为单一事实源，减少 API/CLI 双轨漂移风险。
- OpenAPI snapshot 先以稳定 contract tests 落地，不额外引入新的 schema 产物写盘流程。
- status 的 `stale` 语义保持保守：仅对“页面存在但检索索引缺失或页数失配”告警，不把更激进的健康判定混入首版 API contract。

### Evidence

- 回档点：`C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-175932-lmwr-wave11-cli-openapi-slice`
- focused tests：`tests/wiki/test_wiki_router.py`、`tests/wiki/test_wiki_cli.py`
- CLI 代码：`literature_assistant/__main__.py`
- OpenAPI 注册：`literature_assistant/core/python_adapter_server.py`
- 关键 contract 输出：`run_literature_assistant.py wiki status` 返回 disabled JSON，含 `stale: false`。
- 文档同步：`literature_assistant/README.md`、`docs/plans/active/2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md`、`docs/plans/active/2026-05-03-llmwiki-execution-decisions.md`

### Rollback

- 若只回滚本切片，优先使用上面的 touched-file restore + checkpoint 中 `untracked/tests/wiki/test_wiki_router.py` 的恢复副本。
- 若需要完整回到切片开始前状态，以 checkpoint 目录中的 `metadata.json`、`worktree.diff`、`staged.diff` 为准执行人工恢复。

### Open

- None（Wave 11 API contract 当前按 focused gate 收口）。

### Next

- Wave 12：进入前端 Wiki 工作台最小产品面，先补 `WikiStatusCard` / client types / 只读状态面板。

---

## 执行硬规则（copy from plan）

- `github/` 和 `C:\Users\xiao\Downloads\llmwiki借鉴库` 只读参考，不复制外部代码。
- 产品代码优先放入 `literature_assistant/core/`。
- 运行输出放入 `workspace_artifacts/`，不写回根目录 `output/`。
- 不改变默认 RAG/TOLF 主链，不默认启用 rerank，不改变 corpus/goldset/qrels。
- 对外部资料源 Zotero/EndNote/Obsidian 先只读索引，不做写回同步。
- 所有 claim 进入正式 wiki 前必须有可解析 evidence reference。
