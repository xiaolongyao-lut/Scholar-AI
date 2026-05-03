# TOLF Context Selector Comparison

This runbook compares default project chunk search with the default-off text-only TOLF context selector without calling any model provider.

## Guardrails

- Create a rollback checkpoint before editing code or manifests.
- Use only local JSONL inputs and ignored `workspace_artifacts/` outputs.
- Do not edit `.env`.
- Do not change corpus, goldset, qrels, or evaluation criteria.
- This comparison is a context-selection probe only; it is not a release gate and does not justify switching the default chain by itself.

## Mature-Solution Reference

- GraphRAG-style evaluation separates query/retrieval modes and keeps a basic search/control path.
- Retrieval-first RAG evaluation should inspect selected chunks before judging generation quality.
- Azure AI Search hybrid search, Elastic hybrid search, and Vespa hybrid retrieval all treat lexical and semantic retrieval as complementary signals, commonly combining them through fusion/ranking rather than using semantic hit-count alone as a quality verdict.
- Query-time synonym and expansion systems should be treated as diagnostic or ranking-assist signals unless they are backed by a controlled analyzer/index contract.
- Bilingual controls are useful to test whether a weak raw lexical baseline is caused by language mismatch; they should not replace raw-query controls or qrels-based evaluation.
- Official references: `https://learn.microsoft.com/en-us/azure/search/hybrid-search-how-to-query`, `https://learn.microsoft.com/en-us/azure/search/search-synonyms`, `https://www.elastic.co/guide/en/elasticsearch/reference/8.19/semantic-text-hybrid-search.html`, `https://www.elastic.co/guide/en/elasticsearch/reference/current/search-with-synonyms.html`, `https://docs.vespa.ai/en/learn/tutorials/hybrid-search`.

## Input Shape

Queries JSONL:

```json
{"query_id":"q1","query_text":"laser power hardness"}
```

Chunks JSONL:

```json
{"chunk_id":"c1","material_id":"m1","title":"Paper","content":"Laser power increased hardness to 280 HV."}
```

## Command

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "tolf-context-selector-comparison"

# Mature-solution check: review GraphRAG/RAG retrieval evaluation docs before changing interpretation thresholds.

cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\.venv-1\Scripts\python.exe tools\eval\export_project_chunks_for_tolf_comparison.py `
  --project-id "<project_id>" `
  --output workspace_artifacts\generated\tolf_context_selector\project_chunks.jsonl

.\.venv-1\Scripts\python.exe tools\eval\compare_tolf_context_selector.py `
  --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl `
  --chunks workspace_artifacts\generated\tolf_context_selector\project_chunks.jsonl `
  --output workspace_artifacts\generated\tolf_context_selector\comparison.json `
  --top-k 5 `
  --max-queries 30 `
  --embedding-dim 64

.\.venv-1\Scripts\python.exe tools\eval\compare_tolf_context_selector.py `
  --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl `
  --chunks workspace_artifacts\generated\tolf_context_selector\project_chunks.jsonl `
  --output workspace_artifacts\generated\tolf_context_selector\comparison_inspection.json `
  --top-k 5 `
  --max-queries 30 `
  --embedding-dim 64 `
  --include-inspection `
  --inspection-snippet-chars 360
```

## Verification

```powershell
.\.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q
.\.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py tests\test_compare_tolf_context_selector.py
.\.venv-1\Scripts\python.exe -m pytest tests\test_export_project_chunks_for_tolf_comparison.py -q
```

## Output Fields

- `summary.mean_overlap_at_top_k`: overlap between default and TOLF selections.
- `summary.queries_with_tolf_hits`: number of queries where TOLF returned at least one chunk.
- `summary.queries_with_empty_default`: queries where default project chunk search returned no chunks.
- `summary.queries_with_empty_bilingual_default`: queries where the query-time bilingual control returned no chunks.
- `summary.queries_where_bilingual_default_recovers_empty_default`: raw-default empty queries that get at least one bilingual-control hit.
- `summary.queries_with_empty_tolf`: queries where TOLF returned no chunks.
- `summary.mean_bilingual_control_overlap_at_top_k`: overlap between bilingual-control default search and TOLF selections.
- `summary.queries_where_all_tolf_hits_lack_query_overlap`: risk signal for cross-lingual or weakly grounded TOLF hits.
- `summary.queries_where_all_tolf_hits_lack_query_or_bridge_overlap`: stricter risk signal after zero-cost query bridge diagnostics.
- `summary.tolf_hits_without_query_overlap`: total TOLF-selected chunks with no lexical query overlap.
- `summary.tolf_hits_without_query_or_bridge_overlap`: total TOLF-selected chunks with neither lexical overlap nor configured query bridge matches.
- `summary.tolf_hits_with_query_bridge_overlap`: TOLF-selected chunks that lack literal token overlap but match configured Chinese/English technical bridge terms.
- `comparisons[].only_default_ids`: chunks default search selected but TOLF did not.
- `comparisons[].bilingual_query_terms`: query-time bridge terms appended for the diagnostic bilingual-control arm.
- `comparisons[].bilingual_default_top_ids`: chunks selected by the bilingual-control default arm.
- `comparisons[].bilingual_control_overlap_ids`: overlap between bilingual-control default search and TOLF selections.
- `comparisons[].bilingual_control_overlap_at_top_k`: top-k overlap ratio between bilingual-control default search and TOLF.
- `comparisons[].only_tolf_ids`: chunks TOLF selected but default search did not.
- `comparisons[].tolf_source_labels`: provenance labels added by TOLF selector.
- `comparisons[].tolf_query_overlap_tokens`: query tokens found in TOLF-selected chunks.
- `comparisons[].tolf_query_bridge_matches`: diagnostic matches from query terms to configured bridge terms, for example `激光焊接 -> laser/welding`.
- `comparisons[].inspection.raw_default_hits`: optional side-by-side snippets for raw default hits when `--include-inspection` is set.
- `comparisons[].inspection.bilingual_default_hits`: optional side-by-side snippets for bilingual-control hits.
- `comparisons[].inspection.tolf_hits`: optional side-by-side snippets for TOLF hits, including bridge matches.

## Interpretation Guardrails

- If `queries_with_empty_default` is high, the current keyword-heavy default project chunk search is missing those queries and should be treated as a weak control for that slice.
- If `queries_where_bilingual_default_recovers_empty_default` is high, prioritize bilingual query rewrite/translation or controlled synonym maps before tuning TOLF/rerank.
- If bilingual-control overlap with TOLF rises materially while raw-default overlap stays low, inspect those shared chunks manually before changing the runtime chain.
- If bilingual-control overlap with TOLF stays low, use `--include-inspection` to compare snippets before deciding whether TOLF or bilingual-control hits are better grounded.
- If `queries_where_all_tolf_hits_lack_query_overlap` is high, TOLF is behaving more like a semantic fallback than a grounded retrieval win. Do not treat "TOLF returned something" as evidence that it is better.
- If `queries_where_all_tolf_hits_lack_query_or_bridge_overlap` remains high after bridge diagnostics, keep `INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED` default-off and prioritize query translation or stronger control retrieval before tuning TOLF.
- If bridge overlap is high but literal query overlap is low, treat the report as evidence that Chinese/English terminology bridging may be needed; do not treat bridge matches alone as relevance labels.
- If both default-empty and no-bridge risk signals are high at the same time, require manual chunk inspection, query rewrite/translation, or a stronger control path before any default-chain decision.
- Use this report to decide what to inspect next, not to grant a release verdict.

## Rollback

Restore a checkpoint only when explicitly rolling back:

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --id "<checkpoint-id>"
```
