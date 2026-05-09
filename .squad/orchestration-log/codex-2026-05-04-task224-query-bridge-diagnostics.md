# TASK-224 TOLF Query Bridge Diagnostics

## Facts

- Scope: extend the zero-cost TOLF comparison report with query bridge diagnostics.
- No model-provider calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- The bridge lexicon is intentionally local, additive, and report-only. It does not alter default project search, TOLF selection, ranking, or runtime behavior.

## Mature-Solution Check

- Azure AI Search, Elastic, and Vespa all treat hybrid retrieval and synonym/query expansion as complementary query-time signals, not as stand-alone relevance labels.
- Local reference check found OmegaWiki-style synonym canonicalization and PaperQA expansion controls; both support the same design direction: use bridge/canonicalization to explain retrieval gaps before changing the main chain.

## Decisions

- Keep `schema_version` at `tolf-context-selector-comparison/v1` and add additive fields only.
- Add `comparisons[].tolf_query_bridge_matches` as a per-hit diagnostic alongside `tolf_query_overlap_tokens`.
- Add `tolf_hits_without_query_or_bridge_overlap`, `queries_where_all_tolf_hits_lack_query_or_bridge_overlap`, and `tolf_hits_with_query_bridge_overlap`.
- Treat bridge matches as a reason to investigate bilingual query translation/control, not as evidence to enable TOLF by default.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q` -> `10 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py tests\test_compare_tolf_context_selector.py literature_assistant\core\tolf_text_selector.py` -> pass
- `git diff --check` -> no whitespace errors; Windows line-ending warnings only
- Regenerated local report:
  - command: `.\.venv-1\Scripts\python.exe tools\eval\compare_tolf_context_selector.py --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl --chunks workspace_artifacts\generated\tolf_context_selector\laser_welding_30_chunks.jsonl --output workspace_artifacts\generated\tolf_context_selector\laser_welding_30_comparison.json --top-k 5 --max-queries 30 --embedding-dim 64 --max-candidates 45`
  - summary: `mean_overlap_at_top_k=0.2`, `queries_with_tolf_hits=30`, `queries_with_empty_default=24`, `queries_where_all_tolf_hits_lack_query_overlap=30`, `queries_where_all_tolf_hits_lack_query_or_bridge_overlap=7`, `tolf_hits_without_query_overlap=150`, `tolf_hits_without_query_or_bridge_overlap=69`, `tolf_hits_with_query_bridge_overlap=81`

## Judgment

- The previous all-query literal-overlap risk was too coarse for Chinese queries over English technical literature.
- Bridge diagnostics show that `81/150` TOLF-selected hits have no literal query overlap but do match configured Chinese/English technical bridge terms.
- `7/30` queries still have all TOLF hits lacking both literal and bridge overlap, so TOLF remains default-off.
- The next high-value zero-cost slice is bilingual query control or query-translation-aware comparison, not default-chain switching.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260503-234324-task224-query-bridge-diagnostics`
- Do not restore unless the user explicitly requests rollback.

## Next

- Add a zero-cost bilingual query/control comparison layer so default project chunk search is not evaluated only with raw Chinese lexical queries against English-heavy chunks.
- Keep corpus/goldset/qrels/eval criteria unchanged.
