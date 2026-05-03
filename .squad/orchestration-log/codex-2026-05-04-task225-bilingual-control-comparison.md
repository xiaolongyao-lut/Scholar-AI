# TASK-225 Bilingual Default Control Comparison

## Facts

- Scope: extend the zero-cost TOLF comparison report with a bilingual default-control arm.
- No model-provider calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- The raw default-control arm remains unchanged. The bilingual arm appends deterministic bridge terms only inside the comparison tool.
- Runtime search, TOLF selection, ranking, qrels, and release gates are not changed.

## Mature-Solution Check

- Azure AI Search synonym maps, Elastic search synonyms, and Vespa hybrid/query rewriting guidance all support query-time expansion as a controlled diagnostic or ranking-assist mechanism.
- Local reference evidence from OmegaWiki synonym canonicalization and PaperQA expansion controls supports using a separate expanded control instead of mutating the raw query baseline.

## Decisions

- Keep `schema_version` at `tolf-context-selector-comparison/v1` and add additive fields only.
- Add `bilingual_query_terms`, `bilingual_default_top_ids`, `bilingual_control_overlap_ids`, and `bilingual_control_overlap_at_top_k` per query.
- Add summary counters for `queries_with_empty_bilingual_default`, `queries_where_bilingual_default_recovers_empty_default`, and `mean_bilingual_control_overlap_at_top_k`.
- Treat bilingual-control recovery as evidence of language mismatch in the raw lexical baseline, not as a relevance label or default-chain approval.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q` -> `11 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py tests\test_compare_tolf_context_selector.py literature_assistant\core\tolf_text_selector.py` -> pass
- Regenerated local report:
  - command: `.\.venv-1\Scripts\python.exe tools\eval\compare_tolf_context_selector.py --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl --chunks workspace_artifacts\generated\tolf_context_selector\laser_welding_30_chunks.jsonl --output workspace_artifacts\generated\tolf_context_selector\laser_welding_30_comparison.json --top-k 5 --max-queries 30 --embedding-dim 64 --max-candidates 45`
  - summary: `mean_overlap_at_top_k=0.2`, `queries_with_empty_default=24`, `queries_with_empty_bilingual_default=0`, `queries_where_bilingual_default_recovers_empty_default=24`, `mean_bilingual_control_overlap_at_top_k=0.0`, `queries_where_all_tolf_hits_lack_query_or_bridge_overlap=7`, `tolf_hits_with_query_bridge_overlap=81`

## Judgment

- Raw default empty results are mostly a bilingual lexical-control problem: all `24/24` raw-empty queries recover at least one bilingual-control hit.
- Bilingual-control top-k has zero overlap with TOLF top-k in the current `laser_welding_30` report, so TOLF and the recovered lexical control are selecting different evidence.
- This makes default-chain switching inappropriate. The next useful step is manual or qrels-oriented inspection that compares raw default, bilingual default-control, and TOLF per query.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-001712-task225-bilingual-control-comparison`
- Do not restore unless the user explicitly requests rollback.

## Next

- Add a zero-cost per-query inspection packet/export that surfaces raw default hits, bilingual-control hits, TOLF hits, bridge terms, and snippets side by side for manual or goldset-aligned review.
- Keep corpus/goldset/qrels/eval criteria unchanged.
