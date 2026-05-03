# TASK-228 TOLF Comparison Judgment Template

## Facts

- Scope: add a machine-readable JSONL template for manual relevance judgments from the inspection report.
- No model-provider calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- The template is generated only when `--judgment-template-output` is set and requires `--include-inspection`.

## Mature-Solution Check

- TREC/qrels and RAG evaluation workflows separate candidate pooling from relevance judgment.
- This slice creates a candidate-pool judgment template only. It does not update qrels or treat generated rows as gold labels.

## Decisions

- Add `--judgment-template-output` and `--judgment-max-queries`.
- Fail fast if JSONL output is requested without `--include-inspection`.
- Emit one row per candidate hit with `schema_version=tolf-comparison-judgment/v1`.
- Default every row to `judgment="unknown"` with allowed values `relevant`, `partial`, `offtopic`, and `unknown`.
- Preserve provenance fields needed for later aggregation: query id/text, arm, rank, chunk id, material id, title, source labels, query overlap tokens, and bridge matches.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q` -> `16 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py tests\test_compare_tolf_context_selector.py literature_assistant\core\tolf_text_selector.py` -> pass
- Generated local template:
  - command: `.\.venv-1\Scripts\python.exe tools\eval\compare_tolf_context_selector.py --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl --chunks workspace_artifacts\generated\tolf_context_selector\laser_welding_30_chunks.jsonl --output workspace_artifacts\generated\tolf_context_selector\laser_welding_30_inspection.json --top-k 5 --max-queries 30 --embedding-dim 64 --max-candidates 45 --include-inspection --inspection-snippet-chars 360 --review-markdown-output workspace_artifacts\generated\tolf_context_selector\laser_welding_30_review.md --review-max-queries 30 --judgment-template-output workspace_artifacts\generated\tolf_context_selector\laser_welding_30_judgments_template.jsonl --judgment-max-queries 30`
  - output: `330` JSONL rows, arms `raw_default`, `bilingual_default`, and `tolf`

## Judgment

- The project now has a safe path from zero-cost comparison to human review without mutating gold data.
- The next useful step is an aggregator that summarizes filled judgment templates by arm and query after manual review.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-005523-task228-review-jsonl-template`
- Do not restore unless the user explicitly requests rollback.

## Next

- Add a JSONL judgment aggregator for manually reviewed files.
- Keep qrels/goldset unchanged unless a separate review gate explicitly approves promotion.
