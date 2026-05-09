# TASK-229 TOLF Comparison Judgment Summary

## Facts

- Scope: add a read-only summary path for filled judgment JSONL files.
- No model-provider calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- The summary path does not rerun retrieval. It only reads a filled judgment JSONL and aggregates counts.

## Mature-Solution Check

- TREC-style workflows separate candidate pooling, manual relevance judgments, and evaluation summary.
- This slice follows that pattern by allowing a manual judgment file to be summarized without mutating qrels or rerunning the retrieval chain.

## Decisions

- Add `--judgment-input` and `--judgment-summary-output`.
- Require both flags together and fail fast if only one is provided.
- Emit `schema_version=tolf-comparison-judgment-summary/v1` with `row_count`, `reviewed_count`, `unknown_count`, `invalid_count`, `by_arm`, and `by_query`.
- Treat the summary as a review artifact only, not as a qrels or goldset mutation path.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q` -> `18 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py tests\test_compare_tolf_context_selector.py literature_assistant\core\tolf_text_selector.py` -> pass
- Generated local summary:
  - command: `.\.venv-1\Scripts\python.exe tools\eval\compare_tolf_context_selector.py --queries unused.jsonl --chunks unused.json --output unused.json --judgment-input workspace_artifacts\generated\tolf_context_selector\comparison_judgments_filled.jsonl --judgment-summary-output workspace_artifacts\generated\tolf_context_selector\comparison_judgment_summary.json`
  - output: `row_count=3`, `reviewed_count=2`, `unknown_count=1`, `invalid_count=0`

## Judgment

- The project now has a complete zero-cost loop from comparison to inspection packet to review packet to judgment template to judgment summary.
- The next useful step is only to add a tiny human-review convenience export if needed, not to change the runtime chain or qrels.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-010759-task229-judgment-summary`
- Do not restore unless the user explicitly requests rollback.

## Next

- Optionally add a CSV export for the judgment summary if spreadsheet review is desired.
- Keep corpus/goldset/qrels unchanged unless a separate review gate explicitly approves promotion.
