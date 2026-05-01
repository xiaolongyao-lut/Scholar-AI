# TASK-214 Rerank Paired-Control Preflight

## Facts

- Scope: zero-cost manifest preflight for guarded rerank canaries.
- No model calls, no output writes, no `.env` edits, no corpus/goldset/qrels/eval-criteria changes.
- `rerank_canary_dry_run_sample.json` now carries a `paired_control` no-rerank arm.
- Dry-run report includes `paired_control.status=ok` when the control is valid.

## Mature-Solution Check

- MLflow Tracking treats runs as comparable units with params, metrics, tags, and artifacts; the local manifest mirrors this by validating rerank and no-rerank as a paired comparison before interpretation.
- JSON Lines remains the line-count basis for query/qrels and per-query artifacts.
- Sources checked: `https://mlflow.org/docs/latest/ml/tracking/` and `https://jsonlines.org/`.

## Decisions

- Keep this as preflight only; do not run paid rerank canaries in this slice.
- Require paired control to use the same `queries_path`, `qrels_path`, expected line counts, and comparable retrieval parameters.
- Require paired control output paths to be unique within the control and non-overlapping with rerank output paths.
- Require explicit `paired_control.retrieval_config.use_rerank=false`; omission is rejected.
- Fix bool parsing so string `"false"` is not treated as truthy.
- If `safety.requires_paired_no_rerank_control=true`, missing `paired_control` fails preflight.

## Verification

- `.venv-1\Scripts\python.exe tools\eval\run_pinned_rerank_manifest.py workspace_tests\evaluation_manifests\rerank_canary_dry_run_sample.json --dry-run --require-runtime-rerank-opt-in` -> `status: ok`, `paired_control.status: ok`
- `.venv-1\Scripts\python.exe -m pytest tests\test_run_pinned_rerank_manifest.py -q` -> `14 passed`
- `.venv-1\Scripts\python.exe -m compileall -q tools\eval\run_pinned_rerank_manifest.py tests\test_run_pinned_rerank_manifest.py` -> pass

## Rollback

- `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-061054-task214-rerank-control-manifest-preflight`

## Next

- Optional zero-cost next slice: add a manifest copy/helper command that materializes dated rerank + paired-control manifests without secrets.
- Real canary remains gated: dated manifest, dry-run first, paired no-rerank control, unique outputs, no final release verdict self-sign.
