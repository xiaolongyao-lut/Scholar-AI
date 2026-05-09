# LLM-Wiki 集成切片 Runbook

> LMWR-437 / LMWR-440 / LMWR-446 · Wave 14 fixtures and no-secret trace gate

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-437、LMWR-440、LMWR-446 |
| 简短描述 | 新增 wiki eval smoke fixture，并实现 eval/trace no-secret scan。 |
| Wave | Wave 14 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T20:43:00+08:00 |

---

## 1. 回档点

| 类型 | 路径 |
| ---- | ---- |
| Codex checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-203528-llmwiki-wave14-fixtures-no-secret` |

恢复只允许在用户明确要求“回滚/恢复/撤销本次改动”后执行。

---

## 2. 成熟方案 / 参考目录

| 来源 | 参考点 | 本轮借鉴 |
| ---- | ------ | -------- |
| `workspace_tests/evaluation_manifests/rerank_canary_dry_run_sample.json` | dry-run manifest、outputs/inputs 分离、secret_policy 明确写入 | 新 fixture 明确 no secret / no qrels edits / no model calls。 |
| `tests/wiki/test_query.py` | `write_query_trace()` 已验证不写 plain query | 新增通用 no-secret scan 后，直接扫描真实 query trace 文件。 |
| `tools/longrun/longrun-prompt.md` | 禁止 `.env`、secrets、qrels/goldset/eval query changes | Fixture 放入 `workspace_tests/fixtures/`，不改 goldset/query 数据。 |
| 成熟 secret scanning 思路 | 检测 token pattern、Authorization/Bearer、named secret field、私有路径，同时不回显 raw match | `SecretScanFinding` 只输出 kind/line/message，不输出 secret snippet。 |

---

## 3. 核心代码与 fixture 落点

| 文件 | 任务覆盖 |
| ---- | -------- |
| `literature_assistant/core/wiki/evaluation.py` | LMWR-440、LMWR-446：`SecretScanFinding`、`SecretScanReport`、`scan_text_for_secrets()`、`scan_paths_for_secrets()`。 |
| `workspace_tests/fixtures/wiki_eval_smoke/manifest.json` | LMWR-437：zero-cost eval smoke manifest，不含 secret/qrels/model call。 |
| `workspace_tests/fixtures/wiki_eval_smoke/pages/synthesis/paper-a.md` | LMWR-437：final page with wikilink citation + evidence_refs。 |
| `workspace_tests/fixtures/wiki_eval_smoke/pages/synthesis/baseline-contrast.md` | LMWR-437：final page with chunk-id citation + evidence_refs。 |
| `tests/wiki/test_evaluation.py` | Fixture load/compare/audit/no-secret scan、dangerous text redaction、real query trace scan。 |

---

## 4. 实现事实

- Fixture manifest 支持 2 个 zero-cost cases：一个 source_id case，一个 chunk_id case。
- Fixture pages 使用当前 `---json` page format，能被 `audit_wiki_pages()` 直接读取。
- No-secret scanner 检测 Authorization/Bearer、OpenAI-style `sk-` key、AWS-style access key、named secret value、Windows `C:\Users\...` 私有路径。
- Scan report 不回显命中的 secret/path 原文，只返回 source、line、kind、message。
- `write_query_trace()` 生成的真实 trace 文件已被 no-secret scanner 覆盖，确认 secret query 文本不会落盘。

---

## 5. 验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_evaluation.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki\evaluation.py tests\wiki\test_evaluation.py workspace_tests\fixtures\wiki_eval_smoke
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_citation_validator.py tests\wiki\test_page_store.py tests\wiki\test_query.py tests\wiki\test_evaluation.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki tests\wiki workspace_tests\fixtures\wiki_eval_smoke
```

| 检查项 | 结果 |
| ------ | ---- |
| evaluation focused tests | PASS（11 tests） |
| fixture/no-secret compileall | PASS |
| citation/page/query/evaluation focused group | PASS（108 tests） |
| wiki package/test/fixture compileall | PASS |

---

## 6. Open / 后续

- `LMWR-438` duplicate/orphan/broken-link fixtures 仍未做，建议下一刀接 `wiki/graph.py` + `wiki/doctor.py` 的 fixture gate。
- `LMWR-439` compile cost guard 仍未做。
- `LMWR-443` CI-friendly test subset marker 仍未做。
- `LMWR-447` / `LMWR-448` 收口前仍需 collect-only / workspace verification。

---

## 7. 下一步命令模板

```powershell
# 1. 回档
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "llmwiki-wave14-doctor-graph-fixtures"

# 2. 搜索/读取成熟方案
Get-Content "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\github\LightRAG-1.4.15\lightrag\evaluation\sample_dataset.json" -TotalCount 220
Get-Content "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\literature_assistant\core\wiki\doctor.py" -TotalCount 260
Get-Content "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\literature_assistant\core\wiki\graph.py" -TotalCount 260

# 3. 实现
# 补 LMWR-438 duplicate/orphan/broken-link fixtures，不改 qrels/goldset。

# 4. 验证
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_doctor.py tests\wiki\test_graph.py tests\wiki\test_evaluation.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki tests\wiki workspace_tests\fixtures

# 5. 回滚，仅用户明确要求时
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```
