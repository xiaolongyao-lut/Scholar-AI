# LLM-Wiki 集成切片 Runbook

> LMWR-449 / LMWR-450 / LMWR-451 · Wave 15 migration dry-run and backup/export

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-449、LMWR-450、LMWR-451 |
| 简短描述 | Evidence refs -> wiki registry dry-run 报告；wiki runtime/pages/graph 本地 zip 备份计划与显式写入命令。 |
| Wave | Wave 15 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T21:05:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| Codex checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-205313-llmwiki-wave15-longrun-resume` |
| 恢复命令 | `py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-205313-llmwiki-wave15-longrun-resume" --confirm-restore` |

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 关键借鉴点 |
| ---- | ---- | ---- |
| SwarmVault README | `C:\Users\xiao\Downloads\llmwiki借鉴库\swarmvault-main\README.md` | local-first vault、doctor、review queue、migrate、MCP、graph/export、task/context ledgers。 |
| SwarmVault CHANGELOG | `C:\Users\xiao\Downloads\llmwiki借鉴库\swarmvault-main\CHANGELOG.md` | `migrate --dry-run`、structured doctor、retrieval manifest、stable surface、MCP doctor/retrieval 分层。 |
| LLM Wiki Coordination README | `C:\Users\xiao\Downloads\llmwiki借鉴库\llm-wiki-coordination-main\README.md` | 多 agent consensus、async thread、typed relations、memory tiers；本项目只借鉴协议。 |
| Alembic offline migration | `https://alembic.sqlalchemy.org/en/latest/offline.html` | 迁移先离线生成/预演 SQL 或计划，再显式 apply。 |
| Python zipfile | `https://docs.python.org/3/library/zipfile.html` | 标准库 zip 归档；manifest 放 zip 内和旁路 JSON。 |
| MCP tool annotations | `https://modelcontextprotocol.io/specification/2025-06-18/server/tools` | 未来 tool exposure 需标注 read-only / destructive / idempotent。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `literature_assistant/core/wiki/migration.py` | `EvidenceMigrationDryRunReport`、`evidence_refs_migration_dry_run()`、`evidence_refs_migration_dry_run_from_jsonl()`；只读、去重、统计 already-registered。 |
| `literature_assistant/core/wiki/backup.py` | `WikiBackupPlan`、`build_wiki_backup_plan()`；默认 dry-run，显式写 zip；SQLite 文件使用 `sqlite3.Connection.backup()` 临时快照再归档。 |
| `literature_assistant/__main__.py` | 新增 `python -m literature_assistant wiki migration-dry-run` 与 `wiki backup` CLI。 |
| `tests/wiki/test_migration.py` | 覆盖 would-import、dedupe、registered count、JSONL nested refs、invalid lines、bad inputs。 |
| `tests/wiki/test_backup.py` | 覆盖 dry-run 文件选择、zip + manifest 写入、archive path guard。 |
| `tests/wiki/test_wiki_cli.py` | 覆盖 CLI JSON contract。 |

---

## 4. CLI

Dry-run migration:

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki migration-dry-run --input path\to\evidence_refs.jsonl
```

Backup plan only:

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki backup --archive workspace_artifacts\backups\wiki-backup.zip
```

Create local backup zip:

```powershell
& .\.venv-1\Scripts\python.exe -m literature_assistant wiki backup --archive workspace_artifacts\backups\wiki-backup.zip --write
```

---

## 5. 验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_migration.py tests\wiki\test_backup.py tests\wiki\test_wiki_cli.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki literature_assistant\__main__.py tests\wiki\test_migration.py tests\wiki\test_backup.py tests\wiki\test_wiki_cli.py
```

| 检查项 | 结果 |
| ------ | ---- |
| focused pytest | PASS（13 passed） |
| compileall | PASS |

备注：首轮备份测试暴露 Windows 上 SQLite 临时快照连接未显式 close 导致目录清理失败；已改为显式 close，并把测试输入改为真实 SQLite fixture。

---

## 6. 证据包

### Facts

- 已新增 no-write evidence_refs migration dry-run 模块和 CLI。
- 已新增 wiki backup plan/create 模块和 CLI，默认不写 zip，显式 `--write` 才创建本地 archive。
- 备份覆盖 registry db、retrieval manifest、graph json/db、query index、review queue、generated wiki markdown pages；缺失项进入 report。
- SQLite 归档使用在线 backup API 生成临时快照后压缩，避免直接复制热库。

### Decision

- Wave 15 先做只读计划和本地备份，不实现外部系统写回、不注册 MCP、不自动 finalize。
- migration dry-run 仅输出结构化 would-import，不输出全文 source text。
- backup create 只写 `workspace_artifacts/backups` 或用户显式传入的 `.zip` 路径，不触碰参考库。

### Evidence

- `tests/wiki/test_migration.py`
- `tests/wiki/test_backup.py`
- `tests/wiki/test_wiki_cli.py`
- `docs/plans/specs/llmwiki-wave15-migration-maintenance-spec.md`

### Rollback

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-205313-llmwiki-wave15-longrun-resume" --confirm-restore
```

### Open

- LMWR-452~455 的策略已写 spec，尚未新增清理/人工编辑/MCP 的 runtime API。
- LMWR-456~459 release/privacy/rollback checklist 仍待拆分为 runbook。
- 端到端 dry-run LMWR-462 尚未执行。

### Next

- LMWR-456~459：补 frontend/backend/privacy/rollback release checklist。
- LMWR-460：用户使用指南草稿。
- LMWR-462：source -> compile dry-run -> doctor -> query-save draft 端到端 dry-run。
