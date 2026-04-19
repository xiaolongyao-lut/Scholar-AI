# Phase 5.1: Translated-First Retrieval

## What changed
- Modified `_retrieve_with_expansion()` in `eval_retrieval_runtime.py` (lines ~217-280)
- Old: bilingual parallel retrieve (Chinese + English queries → RRF → rerank)
- New: translated-first (translate to English → single retrieval → rerank with original Chinese query)
- This halves retrieval work

## Test update needed
- File: `tests/test_eval_runtime.py`
- Function: `test_retrieve_with_expansion_merges_translated_results` (line 81)
- Old test expects: both Chinese and English queries to be run via `_retrieve`, then merged
- New behavior: only translated English query goes to `_retrieve`, rerank uses original Chinese
- Need to update fake `_fake_retrieve` to only expect the translated query
- Need to update `_fake_rerank` assertion: candidates come from single English retrieval only

## Old test structure (needs rewriting):
```python
async def _fake_retrieve(query_text, _corpus, top_k, **_kwargs):
    if query_text == "海洋碳循环":
        return [{"chunk_id": "cn1", ...}]
    return [{"chunk_id": "en1", ...}]  # English path

async def _fake_rerank(query, candidates, ...):
    assert query == "海洋碳循环"
    assert {item["chunk_id"] for item in candidates} == {"cn1", "en1"}  # expects both
```

## New test should:
- `_fake_retrieve` should expect "ocean carbon cycle" (translated), return mixed results
- `_fake_rerank` should get query="海洋碳循环" (original Chinese for reranking)
- Verify single retrieval path, not dual

## Quick eval command (30-sample):
```powershell
$env:SILICONFLOW_API_KEY = "sk-umfivdejifggzmmahnoqpqezvvzpmhrjwbvktmhnaksqnywj"
$env:ARK_API_KEY = "d27da208-78e6-4f93-9bea-f352dc29cad7"
$env:ARK_EXPANSION_CONCURRENCY = "2"
```

## A/B Comparison (30-sample, same queries)

| Metric | Old (bilingual parallel) | New (translated-first) | Delta |
|--------|--------------------------|------------------------|-------|
| recall_at_1 | 0.1667 | **0.2667** | +0.10 ↑ |
| recall_at_3 | 0.4333 | **0.4667** | +0.03 ↑ |
| recall_at_5 | 0.4333 | **0.5000** | +0.07 ↑ |
| recall_at_10 | 0.5667 | 0.5000 | -0.07 ↓ |
| mrr | 0.2906 | **0.3456** | +0.06 ↑ |
| avg_latency_ms | 31138.29 | **28235.54** | -2903 ↓ |
| p95_latency_ms | 51428.42 | **48184.29** | -3244 ↓ |

### Per-difficulty
| Difficulty | Old R@5 / MRR | New R@5 / MRR |
|------------|---------------|---------------|
| hard | 0.3 / 0.131 | **0.4 / 0.15** |
| medium | 0.6 / 0.4333 | 0.6 / **0.4667** |
| simple | 0.4 / 0.3076 | **0.5 / 0.42** |

### Verdict
Translated-first wins on Recall@1/3/5, MRR, and latency.
Recall@10 dropped slightly (0.57→0.50) - acceptable tradeoff.
Tests: 12/12 passed.

## Files changed
- eval_retrieval_runtime.py: _retrieve_with_expansion() rewritten
- tests/test_eval_runtime.py: test renamed and updated

## Env
- Python: .venv-1\Scripts\python.exe
- OS: Windows, PowerShell
