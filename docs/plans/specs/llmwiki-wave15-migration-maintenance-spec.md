# LLM-Wiki Wave 15 迁移与长期维护规范

> LMWR-449 / LMWR-452 / LMWR-453 / LMWR-454 / LMWR-455

## 目标

Wave 15 的目标是把前面已完成的 wiki registry、page store、doctor、graph、review queue、connector 和 evaluation 能力整理成可迁移、可备份、可发布、可被未来 agent/MCP 安全调用的维护面。

## 成熟方案对标

| 来源 | 参考路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| SwarmVault | `C:\Users\xiao\Downloads\llmwiki借鉴库\swarmvault-main\README.md` | local-first vault、doctor、review queue、migrate dry-run、context/task/MCP 暴露、zip/export 思路。 |
| SwarmVault changelog | `C:\Users\xiao\Downloads\llmwiki借鉴库\swarmvault-main\CHANGELOG.md` | migrate target、stable surface、doctor structured JSON、MCP doctor/retrieval 工具分层。 |
| LLM Wiki Coordination | `C:\Users\xiao\Downloads\llmwiki借鉴库\llm-wiki-coordination-main\README.md` | 多 agent consensus、async dialogue、memory tiers、typed relations；本项目只借鉴协议，不强制引入目录。 |
| Alembic offline migration | `https://alembic.sqlalchemy.org/en/latest/offline.html` | 迁移先生成/预演计划，写入动作显式化。 |
| Python zipfile | `https://docs.python.org/3/library/zipfile.html` | 使用标准库生成便携 zip 归档；manifest 写入归档内部和旁路 JSON。 |
| MCP tool annotations | `https://modelcontextprotocol.io/specification/2025-06-18/server/tools` | 未来 tool exposure 必须标注只读/破坏性/幂等语义，默认暴露只读工具。 |

## LMWR-449：Evidence Refs 到 Wiki Registry 迁移计划

### 输入

- RAG 运行结果中的 `evidence_refs`。
- JSONL 离线导出，每行允许是单条 EvidenceReference，也允许是包含 `evidence_refs` 数组的对象。
- 可选 wiki registry，仅用于 dry-run 统计 `already_registered_count`。

### 输出

- `would_write=false` 的 dry-run JSON。
- `candidates[]` 仅包含 source/chunk/material/title/type/text length 等结构信息，不输出全文 source body。
- `skipped[]` 记录 invalid JSON、非 mapping、重复引用、缺少 chunk/material id。

### 不做

- 不注册 source/chunk。
- 不写 wiki pages。
- 不读取外部 Zotero/EndNote/Obsidian。
- 不自动 finalize。

## LMWR-452：Wiki Cleanup Policy

| 状态 | 语义 | 默认处理 |
| ---- | ---- | ---- |
| `draft` | 机器或 query-save 生成，引用可能不足 | 参与 review/doctor，不参与 final gate。 |
| `review` | 需要人类判断的冲突、stale、citation warning | 保留，doctor 提示，不自动修复。 |
| `final` | 人工确认、引用密度满足要求 | 参与检索，禁止自动覆盖无 marker 页面。 |
| `deprecated` | 被新版替代但仍保留引用历史 | 保留 backlink，默认降低检索权重。 |
| `archived` | 不再参与检索 | 保留文件和历史，除非用户显式删除。 |

清理命令未来必须先提供 dry-run，列出 `would_deprecate` / `would_archive` / `would_reindex`，再由用户显式 apply。

## LMWR-453：Human Edit Policy

- 自动区以 `<!-- literature-assistant:auto:start -->` 和 `<!-- literature-assistant:auto:end -->` 包裹。
- 缺少自动 marker 的页面视为人工页，不允许机器覆盖。
- 未来若支持混合页，只能替换自动区，人工区保持原样。
- 冲突处理优先进入 review queue，不做 silent merge。
- 手工 `final` 仍需 citation validator 可解析，否则 final gate 失败。

## LMWR-454：Multi-Agent Coordination Policy

- 当前项目不复制 `llm-wiki-coordination-main` 模板目录。
- 采用轻量协议：每个 agent 切片必须写 runbook Facts / Decision / Evidence / Rollback / Open / Next。
- 多 agent 同时工作时，以任务 ID 和文件 ownership 切分，参考库只读。
- 冲突由最新 active plan + runbook 证据裁决；不可推断时暂停问用户。
- 长跑 supervisor 只能继续 LLM-Wiki/RAG 计划；不得修改 `.env`、外部参考库、默认 RAG 链。qrels/goldset/canary30 仅可按 `docs/plans/active/llmwiki-autonomy-authorization.md` 先备份、后对照、再版本化演进。

## LMWR-455：Wiki MCP / Tool Exposure Plan

第一阶段只规划，不注册 MCP server：

| Tool | 语义 | 默认注解 |
| ---- | ---- | ---- |
| `wiki_status` | 读取 feature flag、page count、warnings | read-only, idempotent |
| `wiki_doctor` | 读取 doctor structured JSON | read-only, idempotent |
| `wiki_migration_dry_run` | 读取 JSONL 并返回 would-import | read-only, idempotent |
| `wiki_backup_plan` | 返回备份选中文件，不写 zip | read-only, idempotent |
| `wiki_query` | wiki-only 检索 | read-only, idempotent |

第二阶段才考虑写入类工具，且必须 default-off：

| Tool | 前置条件 |
| ---- | ---- |
| `wiki_backup_create` | 用户显式请求本地 zip；不写外部系统。 |
| `wiki_rebuild_index` | 仅重建 derived artifact；先 dry-run/doctor 提示。 |
| `wiki_compile_source` | `LITERATURE_ASSISTANT_WIKI_COMPILE_ENABLED=1` 且 budget guard 通过。 |

## 验收命令

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "lmwr-wave15-before-next"
Start-Process "https://alembic.sqlalchemy.org/en/latest/offline.html"
Start-Process "https://docs.python.org/3/library/zipfile.html"

& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_migration.py tests\wiki\test_backup.py tests\wiki\test_wiki_cli.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki literature_assistant\__main__.py tests\wiki
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki backup --archive workspace_artifacts\backups\wiki-wave15-smoke.zip
```

## 回滚

仅用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" list --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```
