# TASK-222 Project Chunk Export For TOLF Comparison

## Facts

- Scope: read-only project chunk JSONL export for the TOLF context selector comparison runbook.
- No real API calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- New tool: `tools/eval/export_project_chunks_for_tolf_comparison.py`.
- Runbook updated to export project chunks before running `compare_tolf_context_selector.py`.

## Decisions

- Use existing `load_project_chunks_for_rag(project_id)` as the only data source.
- Export JSONL with stable provenance fields: `project_id`, `chunk_id`, `material_id`, `title`, `section_title`, `page`, `content`, `source_labels`, and `source_hint`.
- Skip empty chunk content instead of writing unusable rows.
- Keep output path caller-controlled, with runbook examples under `workspace_artifacts/generated`.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_export_project_chunks_for_tolf_comparison.py tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q` -> `9 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\export_project_chunks_for_tolf_comparison.py tools\eval\compare_tolf_context_selector.py tests\test_export_project_chunks_for_tolf_comparison.py tests\test_compare_tolf_context_selector.py` -> pass
- `git diff --check` -> no whitespace errors; Windows line-ending conversion warnings only.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-234545-task222-project-chunk-export-for-tolf-comparison`
- Do not restore unless the user explicitly requests rollback.

## Next

- With a real `project_id`, export chunks to `workspace_artifacts/generated/tolf_context_selector/project_chunks.jsonl` and run the comparison report.
- Keep any default-chain decision gated by comparison evidence, standard RAG control, and independent review.
