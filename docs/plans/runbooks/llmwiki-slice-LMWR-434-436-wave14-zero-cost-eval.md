# LLM-Wiki 集成切片 Runbook

> LMWR-434 / LMWR-435 / LMWR-436 · Wave 14 zero-cost evaluation

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-434、LMWR-435、LMWR-436 |
| 简短描述 | 新增 wiki-aware eval manifest、wiki vs raw zero-cost retrieval comparison、citation audit report。 |
| Wave | Wave 14 |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T20:38:00+08:00 |

---

## 1. 回档点

| 类型 | 路径 |
| ---- | ---- |
| Codex checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-202846-llmwiki-wave14-eval-gates-start` |

恢复只允许在用户明确要求“回滚/恢复/撤销本次改动”后执行。

---

## 2. 成熟方案 / 参考目录

| 来源 | 参考点 | 本轮借鉴 |
| ---- | ------ | -------- |
| `github/LightRAG-1.4.15/lightrag/evaluation/README_EVALUASTION_RAGAS.md` | RAGAS 常见指标：faithfulness、answer relevance、context recall、context precision；结果 JSON/CSV；dataset + results 目录分离 | 本轮不引 RAGAS 依赖，先实现 zero-cost retrieval/citation 指标和 JSON serializable report。 |
| `github/LightRAG-1.4.15/lightrag/evaluation/eval_rag_quality.py` | evaluation dataset、endpoint、results_dir、per-case + aggregate result shape | `WikiEvalManifest` + `RetrievalComparisonReport` 明确 case/report 分层。 |
| 本地 `eval_retrieval_runtime.py` / `tests/test_eval_runtime.py` | 现有 retrieval metrics：recall、MRR、latency、per-difficulty | Wave 14 首刀选择 hit_rate/MRR/precision/recall，保持纯本地可测。 |
| 本地 `wiki/citation_validator.py` | citation parsing、claim detection、citation density | `audit_wiki_page_text()` 复用 citation parser 与 claim detector，输出 page-level audit。 |
| RAGAS / LlamaIndex / LangSmith 官方评测思路 | retrieval 与 generation 分开评估，manifest 中保留 query/context/reference 字段 | Manifest 支持 query、expected IDs、wiki/raw context IDs、answer_page_path、answer、ground_truth、contexts。 |

---

## 3. 核心代码落点

| 文件 | 任务覆盖 |
| ---- | -------- |
| `literature_assistant/core/wiki/evaluation.py` | LMWR-434、LMWR-435、LMWR-436：manifest loader、retrieval metric rows、wiki/raw comparison、rendered page citation audit、JSON report。 |
| `tests/wiki/test_evaluation.py` | focused tests：manifest validation、metrics、comparison、citation audit pass/fail、aggregate report、path escape guard。 |

---

## 4. 实现事实

- `WikiEvalManifest` 使用 `schema_version` + `cases`，case 支持 `expected_source_ids` / `expected_chunk_ids`、`wiki_context_*`、`raw_context_*`、`answer_page_path`、`answer`、`ground_truth`、`contexts`。
- `compare_wiki_vs_raw_retrieval()` 不调用模型，只根据 expected IDs 与 retrieved IDs 计算 hit_rate、MRR、precision、recall。
- `audit_wiki_page_text()` 可读取当前 `---json` wiki page frontmatter，审计 citations、evidence_refs、claim citation density。
- `audit_wiki_pages()` 只读 page root，支持传入 relative page paths，并阻止 `..` / absolute path escape。
- 本轮不改现有 qrels/goldset，不写 eval output，不引入 RAGAS/LlamaIndex/LangSmith 依赖。

---

## 5. 验证

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_evaluation.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki\evaluation.py tests\wiki\test_evaluation.py
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_citation_validator.py tests\wiki\test_page_store.py tests\wiki\test_evaluation.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki tests\wiki
```

| 检查项 | 结果 |
| ------ | ---- |
| evaluation focused tests | PASS（8 tests） |
| evaluation compileall | PASS |
| citation/page/evaluation focused group | PASS（82 tests） |
| wiki package/test compileall | PASS |

---

## 6. Open / 后续

- `LMWR-437` / `LMWR-438`：还需要补小型 wiki eval fixtures，覆盖 duplicate/orphan/broken-link 与 compile quality smoke dataset。
- `LMWR-439`：compile cost guard 仍未处理，不能在本轮引入模型调用。
- `LMWR-440` / `LMWR-446`：no-secret trace check 仍需单独实现，优先检查 `wiki_trace_path()` 与 query debug trace。
- `LMWR-443`：可考虑给 wiki tests 增加 CI-friendly marker 或 runbook subset。
- `LMWR-447` / `LMWR-448`：Wave 14 最终收口前再跑 workspace verification / collect-only。

---

## 7. 下一步命令模板

```powershell
# 1. 回档
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "llmwiki-wave14-fixtures-no-secret"

# 2. 搜索/读取成熟方案
Get-Content "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\github\LightRAG-1.4.15\lightrag\evaluation\README_EVALUASTION_RAGAS.md" -TotalCount 220
Get-Content "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\literature_assistant\core\wiki\evaluation.py" -TotalCount 260

# 3. 实现
# 只改 Wave 14 fixtures / no-secret trace / focused tests，不触碰 qrels/goldset。

# 4. 验证
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_evaluation.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki tests\wiki

# 5. 回滚，仅用户明确要求时
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```
