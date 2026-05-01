# Phase P0: Baseline Recovery and Truth Sync

You are working in `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`.

Today is April 11, 2026.

Your mission is to restore the repository to a truthful, green baseline before any new feature work begins.

## Non-negotiable execution rules

1. Before editing any file, create a rollback snapshot under `.rollback_snapshots/` with a timestamped folder name and copy every file you plan to modify into it.
2. Before writing code, search official or mature sources for the relevant implementation patterns. At minimum, review:
   - FastAPI routing and request validation
   - FastAPI / Starlette route conflict behavior
   - pytest patterns for API route tests and validation status codes
3. Do not expand scope beyond baseline recovery.
4. Do not introduce new dependencies unless absolutely necessary.
5. After implementation, truth-sync all reported test counts and status claims to the real repository state.

## Current truthful repository state

As of April 11, 2026, the current baseline is:

- `python -m pytest --collect-only -q` -> `561 tests collected`
- `python -m pytest -q` -> `553 passed, 3 skipped, 5 failed, 42 warnings`

The 5 failing tests are all in `test_recovery_api_routes_real.py`:

- `TestRecoveryAPIRoutes::test_recovery_events_success`
- `TestRecoveryAPIRoutes::test_recovery_facts_invalidate_success`
- `TestRecoveryAPIRoutes::test_recovery_facts_invalidate_missing_fact_id`
- `TestRecoveryAPIRoutes::test_recovery_events_inspection_context`
- `TestRecoveryAPIRoutes::test_recovery_empty_timeline`

## Known repo-grounded failure signals

These are not guesses. They are grounded in the current code:

1. `python_adapter_server.py` defines `GET /recovery/events` as an `EventTimelinePayload`, but `recovery_autopilot_router.py` also defines `GET /recovery/events` and returns `List[EventLogEntry]`. This duplicate route ownership is likely causing route resolution/schema mismatch in the failing tests.
2. `python_adapter_server.py` uses `InvalidFactRequest` in `/recovery/facts/invalidate`, but the handler accesses `request.fact_id`. The current request model does not match the handler contract, causing `AttributeError` and a `500` where the tests expect `200` or `422`.
3. The event inspection tests expect `get_recovery_console().inspect_event_timeline(...)` to be called, but the current request path appears to bypass that handler.

## Required outcome

Restore a truthful green baseline for the recovery API stack without breaking the rest of the repository.

## Scope

You may modify only what is necessary in:

- `python_adapter_server.py`
- `recovery_autopilot_router.py`
- request/response model definitions that are directly involved
- `test_recovery_api_routes_real.py` only if a test is objectively stale after the contract is made internally consistent
- truthful status documents only after code and tests are green

## Concrete tasks

1. Resolve duplicate ownership of `/recovery/events`, `/recovery/metrics`, and any other overlapping `/recovery/*` routes so the main app has one authoritative contract per path.
2. Fix the invalidation request contract so `/recovery/facts/invalidate` correctly accepts:
   - `fact_id`
   - `namespace`
   - `reason`
   - `invalidated_by`
3. Preserve correct FastAPI validation behavior:
   - missing required request fields should return `422`
   - domain validation errors should return `400` only when appropriate
4. Ensure the event timeline endpoint returns the schema expected by the recovery console contract:
   - `events`
   - `event_count`
   - `start_time`
   - `end_time`
   - `session_filter`
   - `job_filter`
5. Keep H4.1 autopilot behavior intact. Do not regress:
   - autopilot control routes
   - recovery metrics
   - canonical event emission

## Acceptance criteria

All of the following must be true:

1. `python -m pytest test_recovery_api_routes_real.py -q` passes fully.
2. `python -m pytest test_recovery_autopilot_cli.py test_integration_h41.py test_h41_final_hardening.py test_recovery_api_routes_real.py -q` passes fully.
3. `python -m pytest -q` returns a green baseline with no new failures.
4. No duplicate or contradictory `/recovery/events` contract remains in the main application.
5. Any documentation updated in this phase reports real counts only.

## Deliverables

1. Code fixes
2. A truthful completion report describing:
   - what was changed
   - what the previous failures were
   - exact final test results
   - any remaining warnings, clearly labeled as pre-existing or new

## Verification commands

Run these after implementation:

```powershell
& '.\.venv-1\Scripts\python.exe' -m pytest test_recovery_api_routes_real.py -q
& '.\.venv-1\Scripts\python.exe' -m pytest test_recovery_autopilot_cli.py test_integration_h41.py test_h41_final_hardening.py test_recovery_api_routes_real.py -q
& '.\.venv-1\Scripts\python.exe' -m pytest --collect-only -q
& '.\.venv-1\Scripts\python.exe' -m pytest -q
```

## Output expectations

At the end, report:

- rollback snapshot path
- files changed
- exact passing test counts
- whether the repository is back to a truthful green baseline
