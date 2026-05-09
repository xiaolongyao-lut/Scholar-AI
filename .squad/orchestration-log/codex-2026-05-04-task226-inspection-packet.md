# TASK-226 TOLF Comparison Inspection Packet

## Facts

- Scope: add an optional side-by-side inspection packet to the zero-cost TOLF comparison tool.
- No model-provider calls, no `.env` edits, no secret printing, no corpus/goldset/qrels/eval-criteria changes.
- The default report remains compact. Inspection snippets are emitted only when `--include-inspection` is explicitly set.

## Mature-Solution Check

- Retrieval evaluation patterns in LlamaIndex, LangChain, and RAGAS encourage inspecting retrieved contexts/source nodes before judging generation quality.
- This slice follows that pattern by exporting retrieved snippets from raw default, bilingual-control default, and TOLF arms side by side without changing ranking or runtime behavior.

## Decisions

- Add `--include-inspection` and `--inspection-snippet-chars`.
- Keep snippet export optional to avoid bloating normal comparison reports.
- Include stable provenance fields in each hit snapshot: `chunk_id`, `material_id`, `title`, `section_title`, `page`, `score`, `source_labels`, `query_overlap_tokens`, and `snippet`.
- Include `query_bridge_matches` only for TOLF hit snapshots where bridge diagnostics are relevant.

## Verification

- `.venv-1\Scripts\python.exe -m pytest tests\test_compare_tolf_context_selector.py tests\test_tolf_text_selector.py -q` -> `12 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\compare_tolf_context_selector.py tests\test_compare_tolf_context_selector.py literature_assistant\core\tolf_text_selector.py` -> pass
- Generated local inspection packet:
  - command: `.\.venv-1\Scripts\python.exe tools\eval\compare_tolf_context_selector.py --queries workspace_tests\evaluation_data\eval_queries_v2.1_canary30_ALIGNED.jsonl --chunks workspace_artifacts\generated\tolf_context_selector\laser_welding_30_chunks.jsonl --output workspace_artifacts\generated\tolf_context_selector\laser_welding_30_inspection.json --top-k 5 --max-queries 30 --embedding-dim 64 --max-candidates 45 --include-inspection --inspection-snippet-chars 360`
  - first query inspection counts: raw default `0`, bilingual default-control `5`, TOLF `5`
  - first bilingual chunk: `mat_8dd7f329cb28_chunk_48`
  - first TOLF chunk: `mat_0709176dfdcf_chunk_419`

## Judgment

- The inspection packet confirms the new bilingual-control arm recovers evidence for raw-empty Chinese queries, but it often recovers different chunks from TOLF.
- This makes manual/qrels-oriented review the next safe step before any tuning or default-chain change.

## Rollback

- Checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-001712-task225-bilingual-control-comparison`
- Do not restore unless the user explicitly requests rollback.

## Next

- Add a compact CSV or Markdown summary for manual scoring if reviewers need spreadsheet-friendly inspection.
- Keep corpus/goldset/qrels/eval criteria unchanged.
