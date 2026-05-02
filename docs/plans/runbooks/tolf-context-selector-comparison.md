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
- `comparisons[].only_default_ids`: chunks default search selected but TOLF did not.
- `comparisons[].only_tolf_ids`: chunks TOLF selected but default search did not.
- `comparisons[].tolf_source_labels`: provenance labels added by TOLF selector.
- `comparisons[].tolf_query_overlap_tokens`: query tokens found in TOLF-selected chunks.

## Rollback

Restore a checkpoint only when explicitly rolling back:

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --id "<checkpoint-id>"
```
