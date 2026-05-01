# Rerank Canary Dry-Run Runbook

Use this runbook when preparing a guarded rerank canary from the current project layout.

## References Checked

- Python `argparse` documents `action="store_true"` for optional boolean CLI flags: https://docs.python.org/3/library/argparse.html
- pytest documents `tmp_path` as a per-test `pathlib.Path` temporary directory fixture: https://docs.pytest.org/en/stable/how-to/tmp_path.html
- JSON Lines keeps one valid JSON value per line for query/qrels-style data: https://jsonlines.org/
- MLflow Tracking documents runs as comparable units with params, metrics, tags, and artifacts; the local manifest mirrors that principle by requiring a paired no-rerank control before interpreting rerank canaries: https://mlflow.org/docs/latest/ml/tracking/

## Rollback First

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "before-rerank-canary"
```

## Dry-Run Only

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\.venv-1\Scripts\python.exe tools\eval\run_pinned_rerank_manifest.py workspace_tests\evaluation_manifests\rerank_canary_dry_run_sample.json --dry-run --require-runtime-rerank-opt-in
```

Expected behavior:

- Prints JSON with `"status": "ok"`.
- Does not call any model provider.
- Does not delete or create output files.
- Verifies `queries_path`, `qrels_path`, pinned rerank model identity, unique output paths, and `RAG_RUNTIME_RERANK_ENABLED=1`.
- Verifies `paired_control` uses the same `queries_path` and `qrels_path`, has unique output paths, and explicitly sets `retrieval_config.use_rerank=false`.

## Real Canary Guardrails

- Copy the sample manifest to a new dated filename before a real run.
- Keep secrets in the environment only; never write API keys to a manifest, plan, log, or test.
- Keep outputs under `workspace_artifacts/generated/eval/...` so runtime artifacts stay out of git.
- Keep `workspace_tests/evaluation_data/*` immutable unless the user explicitly approves corpus, goldset, qrels, or evaluation-criteria changes.
- Keep standard RAG/no-rerank control evidence available before interpreting rerank results.
- Treat rerank and no-rerank as a paired comparison. Do not interpret a rerank manifest unless its `paired_control` preflight is also green.
- Do not mark a final release gate or model-selection verdict without independent review or user confirmation.

## Restore Only On Explicit Rollback Request

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --id "<checkpoint-id>"
```
