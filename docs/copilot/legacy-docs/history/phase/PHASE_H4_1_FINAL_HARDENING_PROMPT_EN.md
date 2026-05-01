# Phase H4.1 Final Hardening Prompt: Merge Autopilot Into Main FastAPI Adapter

You are working in the `Modular-Pipeline-Script` repository on **April 11, 2026**.

## Non-Negotiable First Steps

1. **Create a rollback snapshot before changing anything.**
   - Create a timestamped snapshot under:
     - `.rollback_snapshots/phase-h4-1-final-hardening-<timestamp>/`
   - Copy every file you plan to edit into that snapshot first.
   - Include API files, CLI files, autopilot files, tests, and docs.

2. **Search mature, official solutions on the web before implementation.**
   - Use official docs and mature upstream patterns only.
   - At minimum, benchmark:
     - FastAPI docs for `APIRouter` / bigger applications / router inclusion
     - FastAPI docs for middleware
     - Starlette docs for ASGI middleware and request/response middleware layering
     - FastAPI docs for `TestClient`
     - pytest docs for API / CLI integration testing
   - Record the exact sources used in the completion report.

3. **Inspect repository truth before coding.**
   - Do not trust stale summaries.
   - Confirm the current real state from code and tests:
     - main CLI already includes `autopilot` subcommands
     - `recovery_api.py` exists as a separate FastAPI app
     - `python_adapter_server.py` does **not** yet expose the autopilot endpoints
     - current directed H4.1 slice:
       - `46 passed`
     - current full repository baseline:
       - `474 tests collected`
       - `471 passed, 3 skipped, 32 warnings`

## Verified Current Gaps

This phase is **not** fully hardened yet, even though the new files exist.

The remaining gaps are:

1. `recovery_api.py` is a **parallel FastAPI app**, not integrated into the main adapter `python_adapter_server.py`.
2. `python_adapter_server.py` still does not expose autopilot control endpoints.
3. `recovery_api.py` claims HTTP endpoints are tracked in metrics, but it still has a simplified placeholder note instead of real request metrics middleware.
4. The API integration is partially duplicated across two FastAPI entrypoints, which is not the desired final architecture.
5. Documentation and reports should reflect the final integrated architecture, not the temporary split-app state.

## Goal

Complete **H4.1 final hardening** by:

- folding the autopilot API surface into the **existing main FastAPI adapter** (`python_adapter_server.py`)
- replacing the temporary split-app design with a truthfully integrated architecture
- adding **real HTTP request metrics / middleware**
- preserving canonical events and existing CLI behavior

Do **not** expand into H5.
Do **not** create more parallel entrypoints.

## Required Scope

### 1. Merge autopilot API into the main adapter

Refactor so autopilot endpoints live in or are mounted into `python_adapter_server.py`.

Use a mature structure:

- either define an `APIRouter` in a dedicated module and include it in `python_adapter_server.py`
- or move the route definitions directly into `python_adapter_server.py`

Preferred direction:

- keep logic modular
- keep only **one authoritative FastAPI recovery app**
- avoid duplicate route ownership

The final architecture should make `recovery_api.py` either:

- deleted, if fully superseded
- or reduced to a thin router module / compatibility wrapper with no duplicated app ownership

### 2. Add real HTTP metrics middleware

Implement actual request metrics for the recovery/autopilot API paths.

At minimum track:

- route/path
- method
- status code
- duration

Integrate with the existing recovery metrics collector.

Do not leave placeholder comments like “simplified middleware” once the work is complete.

### 3. Preserve canonical event audit trail

Ensure the integrated autopilot control endpoints still emit canonical events for:

- enable
- disable
- emergency-stop
- emergency-resume
- policy change

Do not regress the current control-plane event behavior.

### 4. Preserve CLI integration

The main CLI integration in `recovery_cli.py` must continue to work exactly as before.

Do not break:

- `autopilot status`
- `autopilot enable`
- `autopilot disable`
- `autopilot emergency-stop`
- `autopilot emergency-resume`
- `autopilot policy show`
- `autopilot policy set`

### 5. Unify tests around the final architecture

Update or add tests so they validate the final integrated shape, not the temporary parallel-app shape.

At minimum cover:

- main adapter exposes autopilot routes
- request metrics middleware records requests
- canonical events still emit on autopilot control actions
- CLI still works
- health and metrics endpoints still work

If `recovery_api.py` remains as a compatibility layer, tests must clearly distinguish:

- authoritative production entrypoint
- compatibility-only entrypoint

### 6. Truthful docs

Create or update a completion report, for example:

- `PHASE_H4_1_FINAL_HARDENING_REPORT.md`

It must include:

- exact architectural change made
- whether `recovery_api.py` still exists and why
- rollback snapshot path
- official sources consulted
- validation commands run
- exact counts
- residual warnings labeled as pre-existing or newly introduced

No inflated “production-ready” claim unless the final integrated architecture is what was actually validated.

## Hard Constraints

- Preserve unrelated user changes.
- Keep strict typing throughout.
- Do not fork the API surface into more entrypoints.
- Prefer `APIRouter` / `include_router()` style composition over ad hoc duplication.
- Use real metrics middleware, not placeholder comments.
- Keep canonical events authoritative for audit.
- Keep existing CLI behavior stable.
- Do not expand scope to H5.

## Acceptance Criteria

- autopilot endpoints are exposed from the main FastAPI adapter
- duplicate split-app architecture is removed or truthfully minimized
- HTTP request metrics are recorded via real middleware
- canonical event audit trail still works
- CLI autopilot commands still pass
- integrated API tests pass
- repository-wide collection still succeeds
- repository-wide tests still pass

## Mandatory Validation Checklist

Run all of the following after implementation:

```powershell
# 1. Compile changed files
& .\.venv-1\Scripts\python.exe -m py_compile python_adapter_server.py recovery_cli.py recovery_autopilot_cli.py recovery_autopilot_control_plane.py

# 2. Focused autopilot/API/CLI tests
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_autopilot_cli.py test_integration_h41.py -q

# 3. Main adapter regression guard
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_api_routes_real.py test_recovery_observability.py test_adapter_import.py -q

# 4. Repository collection
& .\.venv-1\Scripts\python.exe -m pytest --collect-only -q

# 5. Full suite
& .\.venv-1\Scripts\python.exe -m pytest -q
```

## Output Requirements

When finished, provide:

1. a short implementation summary
2. exact files created / modified / deleted
3. the rollback snapshot path
4. the official sources consulted
5. final validation results with exact counts
6. any remaining warnings or limitations, clearly labeled as pre-existing or newly introduced

Do not stop at analysis. Implement the final hardening end-to-end.
