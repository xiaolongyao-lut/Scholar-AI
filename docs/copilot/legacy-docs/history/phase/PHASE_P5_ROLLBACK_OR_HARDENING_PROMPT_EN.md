# Phase P5: Async Store Rollback or Hardening

You are working in `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`.

Today is April 11, 2026.

Your mission is to recover the repository from a broken async-store migration. Do not assume the migration should be kept. Your job is to choose the safest truthful path: either roll back to the last stable synchronous contracts, or harden the async migration end-to-end if and only if that is lower risk and can be completed cleanly.

## Non-negotiable execution rules

1. Before editing any file, create a rollback snapshot under `.rollback_snapshots/` with a timestamped folder name and copy every file you plan to modify into it.
2. Before writing code, search official or mature sources for the relevant implementation patterns. At minimum, review:
   - `aiosqlite` official documentation
   - pytest guidance on import side effects and collection stability
   - FastAPI / Starlette async handler patterns
3. Do not expand scope into unrelated P2-P4 work.
4. Do not leave the repository in a partially migrated sync/async state.
5. Do not use import-time `sys.exit(...)` in modules that tests import.
6. Prefer restoring a truthful green baseline over preserving the async migration.

## Current truthful repository state

As of April 11, 2026, the repository is not in a green state.

Observed facts:

- `pytest --collect-only -q` currently aborts during collection.
- Collection only reaches `211 tests collected` before failing with `6 errors`.
- The import chain fails because:
  - `recovery_store_provider.py` imports `HarnessStore` and `create_integrated_store` from `canonical_event_store.py`
  - the current `canonical_event_store.py` no longer exports those synchronous contracts
  - `recovery_autopilot_cli.py` catches the import failure and calls `sys.exit(1)` at import time

## Repo-grounded breakpoints you must account for

These are real breakpoints in the current codebase:

1. `recovery_autopilot_cli.py` contains import-time failure handling that calls `sys.exit(1)`, which breaks pytest collection.
2. `recovery_store_provider.py` still expects the old synchronous store surface:
   - `HarnessStore`
   - `create_integrated_store(...)`
3. `canonical_event_store.py` has been rewritten as an async `aiosqlite` implementation and now exposes async methods such as:
   - `append_event(...)`
   - `get_job_timeline(...)`
4. `memory_fact_store.py` has also been rewritten as an async `aiosqlite` implementation.
5. Multiple call sites still use the old synchronous contract, including:
   - `recovery_autopilot_control_plane.py`
   - `recovery_console.py`
   - `recovery_execution_engine.py`
   - provider and CLI layers

## Required decision framework

You must explicitly evaluate two options before implementing:

### Option A: Roll back to stable synchronous contracts

Choose this if it is the lowest-risk path to restore a green baseline.

This means:

- restore compatibility with the existing synchronous store API surface
- restore or reintroduce the synchronous integrated-store factory if needed
- remove import-time failure exits
- preserve current recovery/autopilot behavior and tests

### Option B: Complete async hardening end-to-end

Choose this only if you can complete the migration safely in this phase.

This means:

- every affected caller must be updated coherently
- no synchronous caller may keep treating coroutines as immediate values
- CLI paths must have safe async wrappers
- FastAPI handlers, recovery console, execution engine, control plane, provider layer, and tests must all become internally consistent

If you cannot complete Option B cleanly, you must choose Option A.

## Strong preference

Unless the async hardening path is clearly smaller and safer after inspection, prefer rolling back to the last stable synchronous contracts and produce a dedicated follow-up recommendation for a future async migration phase.

## Required tasks

1. Inspect the current async migration breakpoints and decide whether rollback or hardening is safer.
2. Remove import-time `sys.exit(...)` behavior from `recovery_autopilot_cli.py`.
3. Restore a stable store contract surface across:
   - `canonical_event_store.py`
   - `memory_fact_store.py`
   - `recovery_store_provider.py`
   - `recovery_autopilot_control_plane.py`
   - `recovery_console.py`
   - `recovery_execution_engine.py`
4. Fix pytest collection so test discovery completes normally.
5. Truth-sync any documentation you update with the real final test counts and the real chosen path:
   - rollback completed
   - or async hardening completed

## Acceptance criteria

All of the following must be true:

1. `pytest --collect-only -q` completes without internal errors.
2. `pytest -q` runs normally instead of aborting during import/collection.
3. No module imported by tests exits the interpreter at import time.
4. The recovery/autopilot store contract is internally consistent.
5. The final report clearly states which path was chosen:
   - rollback to sync contracts
   - or end-to-end async hardening

## Verification commands

Run these after implementation:

```powershell
& '.\.venv-1\Scripts\python.exe' -m pytest --collect-only -q
& '.\.venv-1\Scripts\python.exe' -m pytest test_recovery_autopilot_cli.py test_integration_h41.py test_h41_final_hardening.py test_recovery_api_routes_real.py -q
& '.\.venv-1\Scripts\python.exe' -m pytest -q
```

If you keep async stores, also run focused smoke verification for the updated async call paths and report the exact commands.

## Deliverables

1. Code changes that restore a stable repository state
2. A truthful completion report describing:
   - the chosen path and why
   - files changed
   - exact test results
   - any remaining warnings
   - whether async migration was rolled back, deferred, or fully hardened

## Output expectations

At the end, report:

- rollback snapshot path
- chosen path: `rollback` or `hardening`
- files changed
- exact collect-only result
- exact full pytest result
- whether the repository is back to a truthful green baseline
