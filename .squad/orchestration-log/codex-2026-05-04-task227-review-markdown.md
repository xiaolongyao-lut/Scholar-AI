# TASK-227 TOLF Comparison Markdown Review Packet

## Facts

- Scope: add an optional Markdown review packet generated from the inspection report.
- No model-provider calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- The Markdown packet is generated only when `--review-markdown-output` is set and requires `--include-inspection`.

## Mature-Solution Check

- TREC-style pooling/qrels workflows and modern RAG evaluation practices inspect retrieved contexts before judging generation.
- This slice converts the JSON inspection packet into a human-readable review artifact with blank manual judgment rows, while preserving the raw JSON as the machine-readable source.

## Decisions

- Add `--review-markdown-output` and `--review-max-queries`.
- Fail fast if Markdown output is requested without `--include-inspection`.
- Include summary metrics, a review rubric, per-query control metadata, blank `raw_default / bilingual_default / tolf` judgment rows, and candidate snippets.
- Treat the Markdown as manual review scaffolding only; it is not a relevance label, qrels file, or release gate.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q` -> `14 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py tests\test_compare_tolf_context_selector.py literature_assistant\core\tolf_text_selector.py` -> pass
- Generated local review packet:
  - command: `.\.venv-1\Scripts\python.exe tools\eval\compare_tolf_context_selector.py --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl --chunks workspace_artifacts\generated\tolf_context_selector\laser_welding_30_chunks.jsonl --output workspace_artifacts\generated\tolf_context_selector\laser_welding_30_inspection.json --top-k 5 --max-queries 30 --embedding-dim 64 --max-candidates 45 --include-inspection --inspection-snippet-chars 360 --review-markdown-output workspace_artifacts\generated\tolf_context_selector\laser_welding_30_review.md --review-max-queries 30`
  - summary table correctly includes zero values such as `queries_with_empty_bilingual_default=0` and `mean_bilingual_control_overlap_at_top_k=0.0`.

## Judgment

- The review packet is now practical for manual or separate-agent inspection because it presents the raw default, bilingual-control, and TOLF arms in one artifact.
- The current evidence still argues against default-chain switching: bilingual control recovers raw-empty queries, but TOLF and bilingual-control top-k overlap remains `0.0`.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-004948-task227-inspection-markdown-summary`
- Do not restore unless the user explicitly requests rollback.

## Next

- Either pause for human review of `laser_welding_30_review.md`, or add a JSONL scoring template that can collect manual judgments without touching qrels/goldset.
