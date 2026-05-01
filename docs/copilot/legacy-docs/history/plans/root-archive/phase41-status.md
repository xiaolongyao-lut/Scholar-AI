# Phase 4.1 Status

## Commit
- `b6ccdd2` on `main` — "feat(reranker): Phase 4.1 — retry + semaphore concurrency + gather eval loop"

## Key Files Modified
- `reranker_client.py`: 3x retry (exponential backoff 0.5s/1.0s), timeout 45→15s, semaphore param, nullcontext fallback
- `eval_retrieval_runtime.py`: asyncio.gather + Semaphore(8), rerank_top_n default 30→20, import os added
- `tests/test_reranker.py`: monkeypatch.delenv for env-independent fallback tests

## Eval Results (414 queries, rerank_top_n=20, semaphore=8)
- Recall@5 = 0.2995 ✅ (gate ≥ 0.28)
- MRR = 0.1719 ❌ (gate ≥ 0.20, gap = 0.028)
- Throughput: ~23min → ~3min (-87%)

## Phase 4 (prior) Results for comparison
- Recall@5 = 0.3019, MRR = 0.1762

## Note
- avg_latency_ms=104137 is inflated by semaphore queuing in concurrent gather mode
- MRR gap to be addressed by Phase 5 (query expansion)

## Next Steps
- Phase 5: Query expansion + cross-lingual enhancement
  - Create: `query_expander.py` (translate_query, expand_multi_query, generate_hyde)
  - Create: `tests/test_query_expander.py`
  - Modify: `eval_retrieval_runtime.py` (parallel bilingual retrieve + RRF merge)
  - Target: Recall@5 ≥ 0.40, hard R@5 ≥ 0.35
  - Volcano endpoint for translation

## Key Constants
- SiliconFlow API key: [REDACTED]
- Reranker: Qwen/Qwen3-Reranker-8B at https://api.siliconflow.cn/v1/rerank
- Embedding: BAAI/bge-m3 (1024-dim) via SiliconFlow
- Volcano dialog: d27da208-78e6-4f93-9bea-f352dc29cad7
- Volcano endpoint: https://ark.cn-beijing.volces.com/api/v3/responses, model ep-20260414011719-8x7s4
- Eval file: eval_queries_v2.0.jsonl (414 queries)
- Plan doc: docs/superpowers/plans/2026-04-16-advanced-retrieval-phased-execution.md


## Phase 5 Progress (2026-04-16)
- Implemented `query_expander.py` with translate/multi-query/HyDE async + sync wrappers (ARK Responses API, graceful fallback without key)
- Integrated `_retrieve_with_expansion()` in `eval_retrieval_runtime.py`: translate -> parallel retrieve -> RRF merge -> single rerank
- Added `--no-expansion` CLI switch and tests in `tests/test_query_expander.py`; extended `tests/test_eval_runtime.py`
- Verification: `pytest tests/test_query_expander.py tests/test_eval_runtime.py tests/test_reranker.py -q` => 11 passed
- Full eval outputs:
  - `BASELINE_METRICS_phase5_no_expansion.json`: Recall@5=0.3043, hard R@5=0.2857, MRR=0.1753
  - `BASELINE_METRICS_phase5_with_expansion.json`: Recall@5=0.2899, hard R@5=0.2619, MRR=0.1753
- Gate status: Phase 5 gates not met (Recall@5>=0.40 and hard R@5>=0.35 both failed)
- Root cause observed: `ARK_API_KEY` and `VOLCANO_API_KEY` are not set in runtime environment, so expansion path degrades to original-query behavior
- Next action: set ARK/Volcano key, rerun phase5 A/B eval, then tune `rerank_top_n` and expansion variants if needed