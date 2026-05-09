# TASK-209 Rerank Dry-Run Sample Manifest

## Facts

- Rollback checkpoint: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-043441-task209-rerank-dry-run-sample-manifest`.
- Mature solution pattern checked before implementation:
  - Python `argparse` `store_true` is the appropriate official pattern for dry-run flags.
  - pytest `tmp_path` is the official isolated temp-path fixture for no-mutation tests.
  - JSON Lines is the established one-record-per-line shape used by the existing query/qrels files.
- Current repo has tracked query/goldset files under `workspace_tests/evaluation_data/`, but no tracked reusable current-layout rerank manifest under `artifacts/eval_audit/manifests`.
- Real rerank canaries are cost-bearing and can mutate/delete output files, so a copyable dry-run sample and runner-side preflight are safer than relying on agent memory.

## Decision

- Add a versioned dry-run sample manifest at `workspace_tests/evaluation_manifests/rerank_canary_dry_run_sample.json`.
- Keep sample outputs under ignored `workspace_artifacts/generated/eval/rerank_canary_sample/`.
- Keep all secrets out of the manifest; credentials remain ambient-env-only.
- Add `docs/plans/runbooks/rerank-canary-dry-run.md` as the canonical runbook for rollback, mature-source references, dry-run command, real canary guardrails, and explicit restore instructions.
- Extend `dry_run_manifest()` to validate optional `inputs.queries_nonempty_lines` and `inputs.qrels_nonempty_lines`.
- Reuse `dry_run_manifest()` at the start of real `run_manifest()` so unsafe manifests fail before log deletion, output cleanup, provider probing, or eval execution.

## Evidence

- Changed files:
  - `workspace_tests/evaluation_manifests/rerank_canary_dry_run_sample.json`
  - `docs/plans/runbooks/rerank-canary-dry-run.md`
  - `docs/plans/README.md`
  - `docs/plans/active/2026-04-27-full-project-build-master-plan.md`
  - `tools/eval/run_pinned_rerank_manifest.py`
  - `tests/test_run_pinned_rerank_manifest.py`
  - `.squad/orchestration-log/codex-2026-05-02-task209-rerank-dry-run-sample.md`
- Verification:
  - `.venv-1\Scripts\python.exe tools\eval\run_pinned_rerank_manifest.py workspace_tests\evaluation_manifests\rerank_canary_dry_run_sample.json --dry-run --require-runtime-rerank-opt-in` -> JSON `"status": "ok"`, 30 query lines, 40 qrels lines, no stale outputs.
  - `.venv-1\Scripts\python.exe -m pytest tests\test_run_pinned_rerank_manifest.py -q` -> `6 passed`
  - `.venv-1\Scripts\python.exe -m compileall -q tools\eval\run_pinned_rerank_manifest.py tests\test_run_pinned_rerank_manifest.py` -> pass
  - `git diff --check` -> pass with line-ending warnings only

## Open

- This slice does not run a paid rerank canary and does not produce any new model verdict.
- A real canary must copy the sample manifest to a dated file, preserve standard RAG/no-rerank control evidence, and keep final gate decisions out of the same autonomous chain.

## Next

- Continue with either TOLF default-off adapter preparation or HTTP RAG result schema inspection.
- If running a real rerank canary later, run the dry-run command first and keep output paths unique under `workspace_artifacts/generated/eval/`.
