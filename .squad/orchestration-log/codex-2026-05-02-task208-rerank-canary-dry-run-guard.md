# TASK-208 Rerank Canary Dry-Run Guard

## Facts

- Rollback checkpoint created before resume edits: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-042639-continue-rag-task208-resume`.
- Prior checkpoint for the TASK-208 slice: `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260502-042046-continue-rag-task208-rerank-canary-guard`.
- Mature solution pattern checked before implementation:
  - Python `argparse` supports optional boolean flags through `action="store_true"`, matching the existing runner CLI style.
  - pytest `tmp_path` provides isolated `pathlib.Path` temp directories, matching the dry-run tests' no-mutation contract.
- Local risk: pinned rerank manifests can trigger paid/provider calls and output cleanup if executed directly, while current rerank/TOLF work still requires guarded canary behavior.

## Decision

- Add `dry_run_manifest()` to validate pinned rerank manifests without invoking providers or mutating outputs.
- Add CLI flags:
  - `--dry-run` to emit a JSON preflight report.
  - `--require-runtime-rerank-opt-in` to require `runtime_env_overrides.RAG_RUNTIME_RERANK_ENABLED=1` before runtime canary use.
- Validate manifest root/sections, queries/qrels existence, `retrieval_config.use_rerank=true`, pinned rerank base URL/model, output path uniqueness, and runtime opt-in when requested.
- Do not probe credentials, call models, delete stale outputs, modify `.env`, change goldset/qrels, or run paid eval in this slice.

## Evidence

- Changed files:
  - `tools/eval/run_pinned_rerank_manifest.py`
  - `tests/test_run_pinned_rerank_manifest.py`
  - `docs/plans/active/2026-04-27-full-project-build-master-plan.md`
  - `.squad/orchestration-log/codex-2026-05-02-task208-rerank-canary-dry-run-guard.md`
- Verification:
  - `.venv-1\Scripts\python.exe -m pytest tests\test_run_pinned_rerank_manifest.py -q` -> `3 passed`
  - `.venv-1\Scripts\python.exe -m compileall -q tools\eval\run_pinned_rerank_manifest.py tests\test_run_pinned_rerank_manifest.py` -> pass
  - `git diff --check` -> pass with line-ending warnings only
  - diff secret scan for API keys/secrets/tokens -> no matches

## Open

- A real rerank canary still needs explicit output paths, budget-aware runtime settings, and the user's release-gate approval before promoting any verdict.
- A sample current-layout manifest can be added later, but should remain non-secret and default-off.

## Next

- Run focused verification, diff hygiene, and secret scan.
- Commit TASK-208 if the worktree contains only this slice.
- Continue to the next low-risk RAG build task from the active plan after the commit.
