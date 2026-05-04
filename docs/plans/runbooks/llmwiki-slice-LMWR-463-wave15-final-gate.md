# LLM-Wiki 集成切片 Runbook

> LMWR-463 · Wave 15 final gate and evidence packet

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-463 |
| 简短描述 | Wave 15 final gate：证据路径、测试结果、残留风险、回滚路径收口。 |
| Wave | Wave 15 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T21:24:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| Wave 15 起点 | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-205313-llmwiki-wave15-longrun-resume` |
| Release checklist 前 | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-210800-llmwiki-wave15-release-checklists-start` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```

---

## 2. 成熟方案研究

Wave 15 已对标：

- SwarmVault README / CHANGELOG：doctor、migrate dry-run、retrieval manifest、MCP、context/task ledgers、backup/export。
- LLM Wiki Coordination README：多 agent consensus、async dialogue、typed relations、memory tiers。
- Alembic offline migration：迁移先 dry-run / offline plan。
- Python zipfile / sqlite3 backup / tempfile：本地 zip、热库备份、临时 E2E。
- MCP tool annotations：未来 read-only / destructive / idempotent 暴露边界。
- Vite / pytest / OWASP Secrets / OWASP Logging：发布、测试、隐私安全门禁。

---

## 3. Wave 15 产物

| LMWR | 产物 |
| ---- | ---- |
| 449 | `docs/plans/specs/llmwiki-wave15-migration-maintenance-spec.md` |
| 450 | `literature_assistant/core/wiki/migration.py`、`python -m literature_assistant wiki migration-dry-run` |
| 451 | `literature_assistant/core/wiki/backup.py`、`python -m literature_assistant wiki backup` |
| 452~455 | cleanup / human edit / multi-agent / MCP exposure plan 写入 Wave 15 spec |
| 456~459 | `docs/plans/runbooks/llmwiki-slice-LMWR-456-459-wave15-release-privacy-rollback.md` |
| 460 | `docs/plans/runbooks/llmwiki-user-facing-usage-guide-draft.md` |
| 461 | `docs/plans/active/2026-04-27-full-project-build-master-plan.md` 状态引用 |
| 462 | `tools/eval/wiki_wave15_end_to_end_dry_run.py`、`tests/wiki/test_wave15_end_to_end.py` |
| 463 | 本 runbook |

---

## 4. Verification

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki literature_assistant\__main__.py tools\eval tests\wiki docs\plans
& .\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
& .\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\system_verification.py --json
& .\.venv-1\Scripts\python.exe tools\eval\wiki_wave15_end_to_end_dry_run.py --pretty
```

| 检查项 | 结果 |
| ------ | ---- |
| `pytest tests/wiki -q` | PASS（299 passed） |
| compileall | PASS |
| `pytest tests --collect-only -q` | PASS（1630 tests collected） |
| `run_literature_assistant.py paths` | PASS |
| `system_verification.py --json` | PASS（23 passed / 0 failed / 0 warnings） |
| Wave 15 E2E dry-run | PASS（`doctor.counts.error=0`、`query_hit_count=1`、`backup_plan.file_count=4`、`would_write=false`） |

---

## 5. Residual Risk

- Frontend release checklist 已写入，但本 final gate 未重跑 `frontend/npm run build` 和 `npm run test -- --run`；本轮主要是 backend/wiki/docs gate。
- E2E doctor 仍有预期 warning：draft/review 页面待人工治理、graph artifacts 未在 dry-run 中落盘、页面路径型 wikilink 对 citation validator 是 warning。
- MCP/tool exposure 仍是计划，不注册真实 MCP server。
- migration 仍是 dry-run，不执行 registry import。
- backup 默认 dry-run；真实 zip 需要显式 `--write`。

---

## 6. Stop Conditions Still Active

- 不写回 Zotero / EndNote / Obsidian。
- 不自动 finalize。
- 不修改 `.env` / secrets。
- 不修改 qrels/goldset/eval queries。
- 不把 wiki-first retrieval 改成默认。
- 不复制或修改 `github/` 与 `C:\Users\xiao\Downloads\llmwiki借鉴库`。

---

## 7. Next

- 若继续长跑，优先从计划中的补充项选择低风险切片：LMWR-464 剩余测试失败复核、LMWR-465 TOLF/Wiki 边界文档、LMWR-468 compile 成本预估展示、LMWR-472 Wiki 安全审计、LMWR-473 Wiki 可观测性。
