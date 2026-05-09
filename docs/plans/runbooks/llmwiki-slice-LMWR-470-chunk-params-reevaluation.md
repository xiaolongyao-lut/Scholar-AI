# LLM-Wiki 集成切片 Runbook

> LMWR-470 · chunk params 200/8 reevaluation

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-470 |
| 简短描述 | 复盘 200/8 分块参数与 canary30 回归证据，生成只读决策 artifact。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-05T00:40:00+08:00 |

---

## 1. 回档点与备份

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260505-002707-lmwr-470-chunk-params-eval-start` |
| eval input backup | `workspace_artifacts/backups/lmwr-470-20260505/evaluation-inputs` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260505-002707-lmwr-470-chunk-params-eval-start" --confirm-restore
```

本轮未修改 `qrels` / `goldset` / `canary30`，未修改 runtime 分块常量，未触发 embedding/model 调用。

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| LangChain text splitters | `https://docs.langchain.com/oss/python/integrations/splitters/index` | splitter 参数需要按应用和检索质量调优；不能把 chunk 参数直觉当默认发布依据。 |
| LlamaIndex evaluation | `https://developers.llamaindex.ai/python/framework/module_guides/evaluating/` | retriever 变更用 MRR、hit-rate、precision、recall 等 ranking metrics 评估。 |
| Pinecone chunking strategies | `https://www.pinecone.io/learn/chunking-strategies/` | chunk 太小或太大都可能伤害检索；有效 chunking 需要基于代表性 query 评估。 |
| 本地 canary artifacts | `workspace_artifacts/evaluations/canary30-*.json` | 现有证据显示 200/8 与 150/5 指标相同，cache/corpus mismatch 是更强解释。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `tools/eval/wiki_lmwr470_chunk_param_review.py` | 新增只读复盘 CLI：解析历史 canary JSON、AST 读取当前 `resources_router.py` 常量、输出 deterministic JSON artifact。 |
| `tests/wiki/test_lmwr470_chunk_param_review.py` | 覆盖 AST 常量提取、metric equality、cache stale evidence、review writer deterministic JSON。 |
| `workspace_artifacts/evaluations/lmwr-470-chunk-param-review-20260505.json` | 本轮机器可读结论和证据 hash。 |

---

## 4. 复盘结论

| 证据 | 结果 |
| ---- | ---- |
| 当前 runtime constants | `CHUNK_SIZE=800`、`CHUNK_OVERLAP=150`、`MAX_CHUNKS_PER_MATERIAL=5` |
| aligned baseline 2026-04-27 | Recall@5 `0.6667`、MRR `0.6667` |
| regression run 200/8 | Recall@5 `0.5`、MRR `0.3181` |
| revert run 150/5 | Recall@5 `0.5`、MRR `0.3181` |
| 200/8 vs 150/5 | Recall/MRR delta 全部 `0.0`，参数因果未证明 |
| cache evidence | 旧 manifest `11445` / `11436` chunks，当前 corpus `11457` chunks，存在 stale cache 证据 |

决策：

- 不提升 200/8。
- 不修改 `resources_router.py` 常量。
- 不修改 `qrels` / `goldset` / `canary30`。
- 150/5 继续作为当前默认。
- 下一道 gate 是 cache/corpus manifest 对齐后，重跑 aligned canary30 no-rerank/raw/default control。

---

## 5. Verification

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_lmwr470_chunk_param_review.py -q
& .\.venv-1\Scripts\python.exe tools\eval\wiki_lmwr470_chunk_param_review.py --pretty
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_lmwr470_chunk_param_review.py tests\wiki\test_performance_baseline.py -q
& .\.venv-1\Scripts\python.exe -m compileall -q tools\eval tests\wiki\test_lmwr470_chunk_param_review.py docs\plans
```

| 检查项 | 结果 |
| ------ | ---- |
| focused LMWR-470 pytest | PASS（5 passed） |
| review CLI | PASS，生成 `workspace_artifacts/evaluations/lmwr-470-chunk-param-review-20260505.json` |
| related eval focused pytest | PASS（7 passed） |
| compileall | PASS |

---

## 6. Open / 后续

- 后续如要重试 200/8，必须先验证 rebuilt cache manifest 的 chunk_count 和 corpus hash。
- 真实 canary30 评测若需要 embedding/provider 调用，需自决策确认环境和 no-secret 输出，再运行。
- 修改旧查询集前仍优先新增 versioned query set；若确需覆盖旧文件，按授权补充先备份、记录旧/新指标、样本数和恢复路径。
