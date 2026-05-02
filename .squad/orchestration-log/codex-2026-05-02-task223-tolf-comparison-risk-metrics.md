# TASK-223 TOLF Comparison Risk Metrics

## Facts

- Scope: extend the zero-cost TOLF comparison report so it distinguishes "returned hits" from "grounded hits".
- No model-provider calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- Existing comparison tool and runbook remained the only execution path.

## Decisions

- Keep the report schema on `tolf-context-selector-comparison/v1` and add additive risk fields instead of introducing a new report format.
- Add per-query flags for `default_empty`, `tolf_empty`, and `tolf_hits_without_query_overlap`.
- Add summary counters for empty-default / empty-TOLF queries and for cases where every TOLF hit lacks lexical overlap with the query.
- Treat these counters as interpretation guardrails only; they do not authorize a default-chain switch.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q` -> `8 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py tests\test_compare_tolf_context_selector.py literature_assistant\core\layers\tolf_engine.py literature_assistant\core\tolf_text_selector.py` -> pass
- `git diff --check` -> no whitespace errors; Windows line-ending warnings only
- Regenerated local report:
  - command: `.\.venv-1\Scripts\python.exe tools\eval\compare_tolf_context_selector.py --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl --chunks workspace_artifacts\generated\tolf_context_selector\laser_welding_30_chunks.jsonl --output workspace_artifacts\generated\tolf_context_selector\laser_welding_30_comparison.json --top-k 5 --max-queries 30 --embedding-dim 64 --max-candidates 45`
  - summary: `mean_overlap_at_top_k=0.2`, `queries_with_tolf_hits=30`, `queries_with_empty_default=24`, `queries_with_empty_tolf=0`, `queries_where_all_tolf_hits_lack_query_overlap=30`, `tolf_hits_without_query_overlap=150`

## Judgment

- The new metrics exposed a real grounding risk in the current `laser_welding_30` sample: TOLF consistently returns chunks, but every returned hit lacks lexical query overlap.
- This is useful as a semantic-fallback signal, not as evidence that TOLF should replace the current control path.
- `INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED` should remain default-off until we have either stronger query translation/control baselines or manual inspection proving these hits are genuinely relevant.

## Rollback

- Checkpoints: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-235943-task223-verify-and-close`, `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260503-010028-task223-final-verify`
- Do not restore unless the user explicitly requests rollback.

## Next

- Use the risk report to target the next zero-cost slice: stronger interpretation docs, better control queries, or query-translation-aware comparison.
- Do not switch the default chain based on hit-count alone.
