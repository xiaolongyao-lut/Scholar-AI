---
name: "rerank-regression"
description: "Minimal QA gate for reranker model/payload changes with chunk+embedding chain sanity"
domain: "qa"
confidence: "high"
source: "tank rerank migration check"
---

## Context

Use this when reranker provider/model/payload is changed (for example SiliconFlow -> DashScope, qwen3-rerank -> qwen3-vl-rerank text mode).

## Minimal test gate

Run the narrowest chain-aware tests first:

1. `tests/test_reranker.py::test_rerank_async_reorders_using_api`  
   - verifies outgoing rerank request shape and model string.
2. `tests/test_llm_provider_routing.py::test_hybrid_retriever_uses_siliconflow_rerank`  
   - verifies hybrid retriever wiring and env-driven rerank model usage.
3. `tests/test_eval_runtime.py::test_retrieve_with_expansion_uses_translated_query_for_retrieval`  
   - verifies embedding path is active (`embed_query`) and rerank remains in retrieval chain.
4. `tests/test_contextual_chunker.py::test_contextual_preserves_original`  
   - verifies `raw_content` is preserved before rerank selection.

## Gap checklist

Flag a coverage gap if either is missing:
- direct assertion for DashScope text-mode payload (`input.query`, `input.documents`, `parameters.top_n`),
- direct assertion that reranker prefers `raw_content` over prefixed `content`.

## Live smoke interpretation rule

- If smoke metrics show `rerank_api_avg_ms=0.0` and `rerank_api_p95_ms=0.0`, do **not** treat "no 401 in log" as proof of active rerank.
- Always cross-check `output/rerank_budget_state.json` and recent `output/rerank_cost.jsonl` tail for `budget_capped` events before concluding runtime health.
