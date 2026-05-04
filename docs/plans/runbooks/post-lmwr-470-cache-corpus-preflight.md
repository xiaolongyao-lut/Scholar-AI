# LLM-Wiki 后续 Gate Runbook

> Post-LMWR-470 · cache/corpus manifest preflight

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | Post-LMWR-470 |
| 简短描述 | 给 200/8 后续重试增加只读 cache/corpus manifest 预检，避免未对齐缓存直接跑 canary control。 |
| 执行者 | Codex |
| 完成时间 | 2026-05-05T00:55:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260505-004142-post-lmwr-470-cache-corpus-preflight-start` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260505-004142-post-lmwr-470-cache-corpus-preflight-start" --confirm-restore
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| LlamaIndex ingestion pipeline | `https://docs.llamaindex.ai/en/stable/module_guides/loading/ingestion_pipeline/` | 用 source/chunk hash 判断节点是否需要 upsert/delete，先验证再复用缓存。 |
| LangChain indexing API | `https://python.langchain.com/docs/how_to/indexing/` | indexing 需要 record/hash 管理，避免重复写入和 stale retrieval state。 |
| FAISS Index IO guidance | `https://github.com/facebookresearch/faiss/wiki/Index-IO%2C-cloning-and-hyper-parameter-tuning` | 持久化向量索引/缓存加载前必须显式校验，不能盲目信任磁盘状态。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `tools/eval/wiki_cache_corpus_preflight.py` | 新增只读 CLI；从 corpus JSON/JSONL 或 v2 chunk-store manifest 计算 `chunk_count`、`chunks_hash`、`is_contextual`，对比 embedding manifest 的 count/hash/shape/dim/contextual/zero rows。 |
| `tests/wiki/test_cache_corpus_preflight.py` | 覆盖 manifest PASS/FAIL、v2 chunk-store 读取、路径逃逸拒绝、无 manifest、多 cache dir、deterministic JSON writer。 |
| `workspace_artifacts/evaluations/post-lmwr-470-cache-corpus-preflight-laser-welding-109-20260505.json` | 当前真实只读预检 artifact。 |

---

## 4. 真实预检结果

命令：

```powershell
& .\.venv-1\Scripts\python.exe tools\eval\wiki_cache_corpus_preflight.py `
  --chunk-store-dir workspace_artifacts\generated\output\chunk_store\laser_welding_109 `
  --include-legacy-cache `
  --output workspace_artifacts\evaluations\post-lmwr-470-cache-corpus-preflight-laser-welding-109-20260505.json `
  --pretty
```

结果：

| 项 | 值 |
| ---- | ---- |
| status | FAIL |
| corpus | `workspace_artifacts/generated/output/chunk_store/laser_welding_109` |
| corpus chunk_count | `7225` |
| corpus chunks_hash | `55b055d47e2bc65746523f29d855bdcc9bf65cb255c4ad773f36b725daf40b46` |
| checked manifests | canonical `11470` chunks、canonical non-contextual `2` chunks、legacy `11457` chunks |
| failure reasons | `chunk_count_match`、`chunks_hash_match`、`shape_row_match`，非 contextual manifest 额外 `contextual_match` |

解释：

- 工具证明当前可见 canonical/legacy embedding manifests 均不能直接代表 `laser_welding_109` v2 chunk-store。
- legacy `output/embedding_cache` 中的 `11457` manifest 与 LMWR-470 历史记录吻合，但它仍不匹配当前 `laser_welding_109` v2 chunk-store 的 `7225` chunks/hash。
- 因此现在不应直接 rerun canary30，也不应提升 200/8；需要先明确 canary eval 实际 corpus source，再做 cache rebuild/verification。

---

## 5. Verification

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_cache_corpus_preflight.py -q
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_cache_corpus_preflight.py tests\wiki\test_lmwr470_chunk_param_review.py tests\wiki\test_performance_baseline.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q tools\eval tests\wiki\test_cache_corpus_preflight.py tests\wiki\test_lmwr470_chunk_param_review.py docs\plans
```

| 检查项 | 结果 |
| ------ | ---- |
| cache/corpus preflight focused pytest | PASS（8 passed） |
| related LMWR-470/eval focused pytest | PASS（15 passed） |
| compileall | PASS |

---

## 6. Open / 后续

- 找到 canary30 control 的真实 corpus source 后，用本工具对该 corpus 与目标 manifest 做 PASS 预检。
- PASS 之前不要 rerun canary30 provider eval，也不要修改 qrels/goldset/canary30 或提升 200/8。
- 如果需要 rebuild embedding cache，可使用现有 env / provider 配置自决策执行；必须保留 no-secret 输出，并记录 manifest chunk_count、chunks_hash 和 eval old/new metrics。

---

## 7. Canary Corpus Source Locator 补充

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `20260505-005234-post-lmwr-470-canary-corpus-locator-start` |
| 工具 | `tools/eval/wiki_canary_corpus_source_locator.py` |
| 测试 | `tests/wiki/test_cache_corpus_preflight.py` |
| artifact | `workspace_artifacts/evaluations/post-lmwr-470-canary-corpus-source-locator-20260505.json` |
| cleanup checkpoint | `20260505-010851-post-lmwr-470-root-hygiene-start` |
| cleanup backup | `workspace_artifacts/backups/post-lmwr-470-root-hygiene-20260505/` |

成熟方案沿用本 runbook 第 2 节：LlamaIndex ingestion pipeline 的 node/transformation hash cache、LangChain indexing API 的 RecordManager/source id/hash 管理、FAISS Index IO 对持久化索引加载前显式校验的要求。

命令：

```powershell
& .\.venv-1\Scripts\python.exe tools\eval\wiki_canary_corpus_source_locator.py `
  --include-legacy-cache `
  --output workspace_artifacts\evaluations\post-lmwr-470-canary-corpus-source-locator-20260505.json
```

初始真实结果：

| 项 | 值 |
| ---- | ---- |
| status | `REPAIR_CANDIDATE` |
| CLI exit code | `2`（预期门禁信号，表示已定位 corpus 但禁止继续 canary/eval promotion） |
| runtime requested root | `output/chunk_store` |
| resolved root | `workspace_artifacts/generated/output/chunk_store` |
| root alias | `output/chunk_store` 是 junction，canonical root 是同一物理目录 |
| loader semantics | `eval_retrieval_runtime._load_retrieval_corpus()` 默认加载 root 下所有 v2 project manifest，再加载 root `*.json` legacy files；不按单项目加载 |
| runtime chunk_count | `11471` |
| runtime chunks_hash | `76f661a741bbc5b7cc69dfab34b3cdd99cba8744691111403874b9fee162bc6a` |
| v2 projects | `77` |
| root legacy JSON | `4` |
| manifest checks | canonical contextual `11470` / canonical non-contextual `2` / legacy contextual `11457` 均 FAIL |
| exact repair candidate | 排除 `output/chunk_store/proj_f9adfb165de1` 后 projected corpus 为 `11470` / `58c76986fdfa125d9e690ad00dfa990b72b2a6b41a564405280d8613a012ddf0`，精确匹配 canonical contextual manifest |

清理执行：

- 目标：`workspace_artifacts/generated/output/chunk_store/proj_f9adfb165de1`（alias：`output/chunk_store/proj_f9adfb165de1`）。
- 证据：该 project 只含 `valid.txt` 的 1 个测试 chunk：`This is valid extractable content.`；除 locator artifact 外，`rg` 未发现项目引用。
- 备份：复制到 `workspace_artifacts/backups/post-lmwr-470-root-hygiene-20260505/chunk_store_removed_projects/proj_f9adfb165de1`。
- 校验：`manifest.json` 和 `valid_2d147b6e.jsonl` 的 source/backup SHA256 完全一致。
- journal：`workspace_artifacts/backups/post-lmwr-470-root-hygiene-20260505/cleanup-journal.json`。

清理后结果：

| 项 | 值 |
| ---- | ---- |
| status | `PASS` |
| runtime chunk_count | `11470` |
| runtime chunks_hash | `58c76986fdfa125d9e690ad00dfa990b72b2a6b41a564405280d8613a012ddf0` |
| matching manifest | `workspace_artifacts/generated/output/embedding_cache/corpus_embeddings_contextual_m571cef40de3d.manifest.json` |
| cleanup restore path | 将 backup 目录 `proj_f9adfb165de1` 复制回 `workspace_artifacts/generated/output/chunk_store/proj_f9adfb165de1` |

结论：

- canary30 control 的默认运行时 corpus source 已定位为 `output/chunk_store`，但该路径实际解析到 `workspace_artifacts/generated/output/chunk_store`。
- canary runtime 加载的是聚合 root，不是单个 `laser_welding_109` 项目；此前 `7225` 单项目预检只能说明 109 project 自身不匹配，不能代表 canary runtime corpus。
- 清理测试残留 project 后，runtime corpus 与 canonical contextual embedding manifest 已 PASS。
- 后续 rerun canary30 / no-rerank/raw/default control 可使用现有 env / provider 配置继续执行；仍不得修改 `.env` 或打印密钥，不改 qrels/goldset/canary30，不自动提升 200/8。

补充验证：

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_cache_corpus_preflight.py -q
& .\.venv-1\Scripts\python.exe tools\eval\wiki_canary_corpus_source_locator.py --include-legacy-cache --output workspace_artifacts\evaluations\post-lmwr-470-canary-corpus-source-locator-20260505.json
```

结果：`14 passed`；locator CLI 返回 `0` 且 artifact status 为 `PASS`。

---

## 8. Canary30 Goldset Drift Diagnostic 补充

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `20260505-022115-post-lmwr-470-goldset-drift-diagnostic-start` |
| 工具 | `tools/eval/wiki_canary_goldset_drift.py` |
| 测试 | `tests/wiki/test_canary_goldset_drift.py` |
| full-root artifact | `workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-drift-20260505.json` |
| laser109 artifact | `workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-drift-laser109-20260505.json` |

成熟方案补充：

| 参考来源 | 链接 | 借鉴点 |
| ---- | ---- | ---- |
| LlamaIndex Retriever Evaluation | `https://docs.llamaindex.ai/en/stable/examples/evaluation/retrieval/retriever_eval/` | retrieval eval 需要保留 query、expected doc、retrieved hits 和 metrics 的可解释链路。 |
| Ragas Context Precision / Recall | `https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/` | 只看 aggregated recall 不够，需要定位 retrieved contexts 与 reference/gold 的相对排序。 |
| LangChain Indexing API | `https://python.langchain.com/docs/how_to/indexing/` | source identity/hash 与重复索引会影响 retrieval state；diagnostic 需要显式暴露 material identity 与重复 title group。 |

新增工具行为：

- 只读读取 `eval_queries_v2.1_canary30_ALIGNED.jsonl`、已有 `rerank_trace.jsonl` 和 chunk-store。
- 不调用 provider，不修改 `.env`、embedding cache、qrels、goldset 或 canary30。
- 输出每条 query 的 expected doc、first gold rank、top-k hits、top1 material/title、same-title alternate、drift labels。
- 聚合输出 expected doc frequency、top1 competitor frequency、duplicate title groups 和 gold missing/buried counts。

命令：

```powershell
& .\.venv-1\Scripts\python.exe tools\eval\wiki_canary_goldset_drift.py `
  --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl `
  --trace workspace_artifacts\evaluations\canary30-post-cache-no-rerank-effective-dense-20260505.rerank_trace.jsonl `
  --chunk-store-dir workspace_artifacts\generated\output\chunk_store `
  --output workspace_artifacts\evaluations\post-lmwr-470-canary30-goldset-drift-20260505.json
```

full-root 结果：

| 项 | 值 |
| ---- | ---- |
| status | `DRIFT_DETECTED` |
| total queries | `30` |
| hit top5 | `15` |
| miss top5 | `15` |
| gold missing in trace window | `10` |
| gold buried after top5 | `5` |
| duplicate title groups | `29` |
| material count / chunk count | `194` / `11470` |
| expected doc frequency | `mat_1f5242e1034f=20`、`mat_f76878df9d8d=10` |

主要 competing top1 materials：

| material_id | top1 count | title |
| ---- | ---- | ---- |
| `mat_2f98d33813ce` | `7` | `Wang 等 - 2025 - Planetary laser welding of medium-thickness aluminum alloys...` |
| `mat_6844f200248a` | `7` | `Liu 等 - 2024 - Determination of beam oscillating pattern...` |
| `mat_bf26f6f7038f` | `6` | `刘浩东和戴京涛 - 2022 - 激光焊接技术的应用研究进展与分析.pdf` |
| `mat_29a909d77df0` | `2` | `刘浩东和戴京涛 - 2022 - 激光焊接技术的应用研究进展与分析.pdf` |

laser_welding_109 单项目对照：

| 项 | full root | laser109 |
| ---- | ---- | ---- |
| hit top5 | `15` | `13` |
| miss top5 | `15` | `17` |
| gold missing in trace window | `10` | `10` |
| gold buried after top5 | `5` | `7` |
| duplicate title groups | `29` | `3` |
| material count / chunk count | `194` / `11470` | `108` / `7225` |

结论：

- cache/corpus 已经对齐后，canary30 回归仍复现；主要问题不是 200/8 参数，也不是单纯 root cache mismatch。
- 当前 aligned canary30 的 goldset 过窄：30 条 query 只允许两个 material id，其中 `mat_f76878df9d8d` 的 10 条在当前 trace window 内全部找不到 gold。
- 多个 generic query（如“激光焊接的最新研究进展”“文献综述”“基本原理和方法”）会自然召回更新、更主题匹配的 laser-welding review/materials，而旧 gold 仍指向 Man 2011 或 2003 cavitation paper。
- 后续优先新增版本化 query/qrels/goldset 对照，不直接覆盖旧 canary30；如要修改旧集，仍按授权执行 checkpoint、备份、旧/新指标和恢复路径。

验证：

```powershell
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_canary_goldset_drift.py tests\wiki\test_cache_corpus_preflight.py tests\test_eval_runtime.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q tools\eval\wiki_canary_goldset_drift.py tools\eval\wiki_canary_corpus_source_locator.py tools\eval\wiki_cache_corpus_preflight.py tests\wiki\test_canary_goldset_drift.py tests\wiki\test_cache_corpus_preflight.py workspace_tests\evaluation_scripts\eval_retrieval_runtime.py
```

结果：`51 passed`；compileall PASS。

---

## 9. Goldset Proposal 草案补充

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `20260505-023147-post-lmwr-470-goldset-proposal-start` |
| full-root proposal | `workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-proposal-20260505.json` |
| laser109 proposal | `workspace_artifacts/evaluations/post-lmwr-470-canary30-goldset-proposal-laser109-20260505.json` |

新增行为：

- `wiki_canary_goldset_drift.py` 支持 `--proposal-output`，从同一份 drift report 生成 no-write goldset evolution proposal。
- proposal 不写 query/qrels/goldset/canary30，只列出每个 miss query 的候选 alternate material、proposal type、review_required 和 mutation guard。
- proposal 内的 simulated recall 是基于现有 trace top-k 接受候选后的上界估算，不能作为 release gate，不能替代人工/版本化 goldset 审核。

命令：

```powershell
& .\.venv-1\Scripts\python.exe tools\eval\wiki_canary_goldset_drift.py `
  --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl `
  --trace workspace_artifacts\evaluations\canary30-post-cache-no-rerank-effective-dense-20260505.rerank_trace.jsonl `
  --chunk-store-dir workspace_artifacts\generated\output\chunk_store `
  --output workspace_artifacts\evaluations\post-lmwr-470-canary30-goldset-drift-20260505.json `
  --proposal-output workspace_artifacts\evaluations\post-lmwr-470-canary30-goldset-proposal-20260505.json
```

full-root proposal 摘要：

| 项 | 值 |
| ---- | ---- |
| status | `DRAFT_REVIEW_REQUIRED` |
| proposed actions | `15` |
| current trace Recall@5 | `0.5` |
| simulated Recall@5 if all candidates accepted | `1.0`（trace-only upper bound） |
| proposal types | `review_generic_query_scope=4`、`review_gold_buried_after_top_k=2`、`review_missing_gold_or_query_rewrite=7`、`review_non_gold_top_k_dominance=2` |

laser109 proposal 摘要：

| 项 | 值 |
| ---- | ---- |
| proposed actions | `17` |
| current trace Recall@5 | `0.4333` |
| simulated Recall@5 if all candidates accepted | `1.0`（trace-only upper bound） |
| proposal types | `review_generic_query_scope=4`、`review_gold_buried_after_top_k=5`、`review_missing_gold_or_query_rewrite=5`、`review_non_gold_top_k_dominance=3` |

下一步建议：

1. 先保留 proposal 为审计包，不改旧 canary30。
2. 若要落地 v2.2，先备份 `eval_queries_v2.1_canary30_ALIGNED.jsonl`、`eval_queries_v2.1_canary30.jsonl`、`gateb_goldset.jsonl` 和相关 artifacts。
3. 新增 `eval_queries_v2.2_canary30_DRAFT.jsonl` / `canary30_goldset_v2.2_DRAFT.jsonl` 后，用旧 aligned、v2.2 draft、full-root no-rerank、laser109 no-rerank 做并排指标；旧集只有在对照优于旧基线且恢复路径完整时才允许覆盖。
