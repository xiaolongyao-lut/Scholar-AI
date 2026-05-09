# LLM-Wiki 集成切片 Runbook

> LMWR-465 · TOLF/Wiki boundary design

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-465 |
| 简短描述 | 明确 TOLF text-only selector 与 Wiki registry/page/query/review 的边界、允许数据流和禁止数据流。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T21:35:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| 起点 checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-212129-llmwiki-lmwr465-tolf-wiki-design-start` |
| 本轮续跑 checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-212507-llmwiki-longrun-doc-align-resume` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| Azure AI Search hybrid search | `https://learn.microsoft.com/en-us/azure/search/hybrid-search-how-to-query` | hybrid search 用 RRF 融合多路检索；本项目保留 raw default / bilingual default / TOLF 三臂，不以单臂命中数做默认链判断。 |
| Azure AI Search synonym maps | `https://learn.microsoft.com/en-us/azure/search/search-synonyms` | synonym 属于 query-time 控制策略；本项目 bridge 只作诊断。 |
| Elasticsearch semantic hybrid search | `https://www.elastic.co/guide/en/elasticsearch/reference/8.19/semantic-text-hybrid-search.html` | semantic 与 lexical retriever 并存；TOLF 不替换 keyword/control path。 |
| Elasticsearch search with synonyms | `https://www.elastic.co/guide/en/elasticsearch/reference/current/search-with-synonyms.html` | search-time synonyms 便于迭代；本项目若扩展 bilingual control，先保持 eval/report 层。 |
| Vespa hybrid search tutorial | `https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html` | BM25 + vector nearestNeighbor 的 hybrid pattern 支持控制臂比较。 |
| 本地 TOLF comparison runbook | `docs/plans/runbooks/tolf-context-selector-comparison.md` | 已有 inspection、review Markdown、judgment JSONL 和 summary；继续作为 TOLF 质量证据来源。 |

---

## 3. Facts

- `literature_assistant/core/tolf_text_selector.py` 已输出 `tolf_activation_score`、`tolf_evidence_score`、`tolf_point_type`、`tolf_rank`、`query_overlap_tokens`，并追加 `tolf_text_selector` provenance。
- `literature_assistant/core/routers/intelligent_chat_router.py` 只在 `INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED=1` 时启用 TOLF；默认关闭；异常/空命中回退原项目 chunk search。
- `tools/eval/compare_tolf_context_selector.py` 已支持 raw default / bilingual default / TOLF 三臂、bridge diagnostics、inspection packet、review Markdown、judgment template、judgment summary。
- Wiki 侧已有 `migration-dry-run` 和 `save_exploration()`，均可通过 `evidence_refs` 接收 provenance-bearing evidence，但不会自动 final。

---

## 4. Decision

TOLF 定位为 default-off 的候选上下文选择与诊断臂：

- 不作为 Wiki 编译器。
- 不直接写 `WikiPageStore`。
- 不直接写 query index、review queue、qrels/goldset。
- 不替换默认 RAG/TOLF 主链。
- 只能通过 `evidence_refs` / `context_metadata` 进入 migration dry-run 或 draft exploration。

---

## 5. Evidence

| 文件 | 证据 |
| ---- | ---- |
| `docs/plans/specs/tolf-wiki-integration.md` | LMWR-465 设计规范。 |
| `docs/plans/runbooks/tolf-context-selector-comparison.md` | 既有 TOLF 对照命令和解释边界。 |
| `literature_assistant/core/tolf_text_selector.py` | TOLF 输出字段和 provenance。 |
| `literature_assistant/core/routers/intelligent_chat_router.py` | default-off runtime 接入点。 |
| `tools/eval/compare_tolf_context_selector.py` | 三臂对照、bridge、review、judgment summary。 |
| `literature_assistant/core/wiki/migration.py` | Evidence refs no-write migration dry-run。 |
| `literature_assistant/core/wiki/query.py` | `save_exploration()` draft-only 保存路径。 |

---

## 6. Verification

```powershell
& .\.venv-1\Scripts\python.exe -m compileall -q docs\plans
& .\.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py tests\wiki\test_migration.py tests\wiki\test_query_save_exploration.py -q
```

| 检查项 | 结果 |
| ------ | ---- |
| docs compileall | PASS |
| TOLF/Wiki focused pytest | PASS（38 passed） |

---

## 7. Open

- 是否给前端 evidence panel 增加 `tolf_text_selector` provenance 展示，另开 LMWR-465-A。
- 是否把 filled judgment summary 导出成 Markdown/CSV，另开 LMWR-465-B。
- 是否基于真实项目重新生成 review packet，需用户确认 project_id。

---

## 8. Next

- LMWR-468：补 Wiki compile cost estimate 在 dry-run/report 的显示，或
- LMWR-469：把 longrun 使用指南补成可执行 SOP，确保所有指令都包含回档和成熟方案搜索。
