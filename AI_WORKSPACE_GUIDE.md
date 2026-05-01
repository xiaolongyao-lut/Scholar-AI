# AI Workspace Guide

This repository has been reorganized around a stable literature-assistant
workspace. Follow this guide before changing code, running tests, or giving
commands to the user.

## Required Preflight

- Create a rollback snapshot before nontrivial edits, moves, deletes, config changes, path changes, API changes, or long-running automation.
- Search official or mature references before changing architecture, packaging, import behavior, test discovery, shell/process cleanup, or deployment commands.
- Preserve unrelated user/agent changes. Inspect `git status --short` and target files before editing.
- Do not touch `github/` reference repositories unless the user explicitly asks.
- Prefer active project records over stale historical plans. Historical `.kilo/`, `.squad/`, and worktree snapshots may mention old root files; treat them as audit trail unless a current task says otherwise.

Safe rollback snapshot pattern:

```powershell
$repo = "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$snapshot = Join-Path $repo ".rollback_snapshots\manual-$stamp"
New-Item -ItemType Directory -Force -Path $snapshot | Out-Null
Copy-Item -LiteralPath "$repo\path\to\target" -Destination $snapshot -Recurse -Force
```

Mature references already used for this layout:

- PyPA / Python packaging guidance favors isolating importable code from repo clutter.
- Python `site` / `.pth` is the standard compatibility mechanism for adding import roots.
- pytest import behavior can prepend/append paths during collection; keep import precedence explicit.
- Uvicorn ASGI apps should be started with the `module:attribute` import string.

## Current Layout

- `literature_assistant/core/`: backend and core Python implementation.
- `literature_assistant/bootstrap.py`: runtime path bootstrap for commands and compatibility.
- `literature_assistant/core/project_paths.py`: canonical filesystem anchors. New code should use these helpers instead of hardcoded repo-relative output paths.
- `run_literature_assistant.py`: stable wrapper for workspace diagnostics.
- `sitecustomize.py`: root-run compatibility hook.
- `.venv-1/Lib/site-packages/literature_assistant_core.pth`: local environment path registration for repo root and core.
- `frontend/`: React/Vite frontend.
- `workspace_artifacts/generated/output/`: generated output and eval/runtime artifacts.
- `workspace_artifacts/runtime_state/`: runtime state, browser/app profiles, transient state.
- `workspace_artifacts/backups/`: local backups for cleanup/encoding/path fixes.
- `docs/plans/`: canonical location for active plans, specs, and AI execution plans.
- `workspace_tests/`: evaluation scripts, diagnostics, and migrated non-product test helpers.
- `workspace_references/`: experiments and references kept outside product code.
- `github/`: external RAG/reference repositories. Read-only by default.
- `my-project/`: removed root residue. Do not recreate it for active work.

## Import Rules

- New backend code should prefer package-style imports such as `literature_assistant.core.<module>` where practical.
- Existing flat imports such as `from routers.resources_router import ...` and `import python_adapter_server` remain supported for legacy tests and scripts. Do not mass-rewrite them unless a task specifically scopes that migration.
- `tests/conftest.py` intentionally puts `literature_assistant/core` before evaluation and experiment paths. Preserve that precedence so `routers` resolves to the active backend, not old experiments.
- Do not remove `sitecustomize.py` or the local `.pth` without replacing all legacy import paths and proving external-cwd imports still work.

## Canonical Commands

Use the repo root as working directory unless noted.

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script

# Path diagnostic
& .\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths

# Backend import / ASGI entry
& .\.venv-1\Scripts\python.exe -m uvicorn literature_assistant.core.python_adapter_server:app --host 127.0.0.1 --port 8000

# Python compile smoke
& .\.venv-1\Scripts\python.exe -m compileall -q literature_assistant run_literature_assistant.py sitecustomize.py tests\conftest.py workspace_tests\evaluation_scripts

# Test collection smoke
& .\.venv-1\Scripts\python.exe -m pytest tests --collect-only -q

# Workspace verification
& .\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\system_verification.py --json
```

Frontend commands run from `frontend/`:

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend
npm run build
npm run test -- --run
```

## Deprecated Command Patterns

Do not suggest or add these as active commands:

- `python python_adapter_server.py`
- `python -m uvicorn python_adapter_server:app`
- `python batch_controller.py`
- `python pipeline_core.py`
- root-level `output/` for new runtime artifacts
- root-level `my-project/`

Use the canonical commands and paths above instead.

## Path And Output Rules

- New runtime/generated files go under `workspace_artifacts/`, not beside source files.
- New evaluation/diagnostic scripts go under `workspace_tests/` unless they are product runtime modules.
- New plan/spec/execution-plan files go under `docs/plans/`.
- New experiments or imported reference snippets go under `workspace_references/`.
- Product backend code goes under `literature_assistant/core/`.
- Frontend code stays under `frontend/src/`.
- If a user asks to organize or clean "my project", operate inside `Modular-Pipeline-Script` and the active literature assistant layout, not the external `github/` reference repositories.

## Verification Expectations

For path/import/layout changes, the minimum closure set is:

- Rollback snapshot path recorded.
- Official/mature references considered.
- `python -m compileall ...` passes.
- `python -m pytest tests --collect-only -q` passes.
- `run_literature_assistant.py paths` passes.
- External-cwd import of `python_adapter_server`, `routers.resources_router`, and `HybridSearchRuntime` passes if compatibility imports are touched.
- Any stale process cleanup is evidence-backed with PID/path/lock information.

## Records

- Current path hardening record: `literature_assistant/00-index/path-hardening-record.md`.
- Current master plan: `docs/plans/active/2026-04-27-full-project-build-master-plan.md`.
- Rollbacks live under `.rollback_snapshots/`.
- Durable shared decisions should use `.squad/decisions/inbox/` with Facts / Decision / Evidence / Rollback.
