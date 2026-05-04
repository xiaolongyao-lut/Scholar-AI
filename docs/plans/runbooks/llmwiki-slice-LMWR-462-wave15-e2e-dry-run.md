# LLM-Wiki 集成切片 Runbook

> LMWR-462 · Wave 15 end-to-end dry-run acceptance

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-462 |
| 简短描述 | source -> compile dry-run -> doctor -> query-save draft -> backup plan 的临时工作区端到端验收。 |
| Wave | Wave 15 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T21:20:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| Codex checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-210800-llmwiki-wave15-release-checklists-start` |
| 恢复命令 | `py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-210800-llmwiki-wave15-release-checklists-start" --confirm-restore` |

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 关键借鉴点 |
| ---- | ---- | ---- |
| SwarmVault README / CHANGELOG | `C:\Users\xiao\Downloads\llmwiki借鉴库\swarmvault-main\README.md`、`CHANGELOG.md` | doctor、retrieval manifest、migrate dry-run、context/save-first query、backup/export。 |
| Python sqlite3 backup API | `https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup` | 热库备份使用 SQLite backup API，避免直接复制锁定文件。 |
| Python tempfile | `https://docs.python.org/3/library/tempfile.html` | E2E 在临时目录运行，结束后不留下 runtime artifacts。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `tools/eval/wiki_wave15_end_to_end_dry_run.py` | 临时 workspace 内构造 registry/source/chunks，执行 compile dry-run、临时写页、build index、query、save exploration、doctor、backup plan。 |
| `tests/wiki/test_wave15_end_to_end.py` | 验证 E2E staying temp、migration no-write、query 命中、draft save、doctor error=0、backup plan no-write 且 file_count>=3。 |
| `literature_assistant/core/wiki/query.py` | 修复 `build_wiki_index()` 重建前不清空 FTS 的 stale row bug。 |
| `tests/wiki/test_query.py` | 新增 rebuild removes deleted pages 回归测试。 |

---

## 4. 发现与修复

- 首轮 E2E 暴露 Windows 临时 SQLite 句柄清理问题：脚本现在在 finally 中关闭 `WikiQueryIndex` 并 `gc.collect()`。
- E2E 暴露 `build_wiki_index()` 重建不清空 FTS，导致保存 exploration 后 indexed pages 大于 page store。已修复为 rebuild 前 `DELETE FROM wiki_pages_fts`。
- E2E 暴露 registry source ID 与 page graph node ID 不应混用。脚本中 migration refs 保持 registry ID，exploration refs 使用页面路径 ID，避免 graph broken edge。

---

## 5. 验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_wave15_end_to_end.py tests\wiki\test_query.py tests\wiki\test_migration.py tests\wiki\test_backup.py tests\wiki\test_wiki_cli.py -q
& .\.venv-1\Scripts\python.exe tools\eval\wiki_wave15_end_to_end_dry_run.py --pretty
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki literature_assistant\__main__.py tools\eval\wiki_wave15_end_to_end_dry_run.py tests\wiki
```

| 检查项 | 结果 |
| ------ | ---- |
| focused pytest | PASS（38 passed） |
| E2E dry-run script | PASS（JSON 输出；`doctor.counts.error=0`、`query_hit_count=1`、`backup_plan.file_count=4`、`would_write=false`） |
| compileall | PASS |

---

## 6. Open

- Doctor 仍有预期 warning：draft/review 页面需要人工治理、graph JSON/SQLite 派生产物未在 E2E dry-run 中落盘、页面路径型 wikilink 对 citation validator 只是 warning。
- LMWR-463 需要最终 gate，把 Wave 15 全部证据路径、测试结果、残留 warning 和停机条件收口。

---

## 7. Next

- LMWR-463：最终 gate 和证据包。
