# Phase P2: FastAPI Modularization Without Contract Drift

You are working in `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`.

Today is April 11, 2026.

Your mission is to continue modularizing the FastAPI adapter into maintainable routers and model modules while preserving one authoritative application entry point and zero API behavior drift.

## Non-negotiable execution rules

1. Before editing any file, create a rollback snapshot under `.rollback_snapshots/` with a timestamped folder name and copy every file you plan to modify into it.
2. Before writing code, search official or mature sources for the relevant implementation patterns. At minimum, review:
   - FastAPI "Bigger Applications"
   - Starlette routing behavior
   - Pydantic / FastAPI response model organization
3. Do not create a second FastAPI app.
4. Do not create duplicate route ownership for the same path.
5. Do not combine this phase with async DB migration or observability expansion.

## Preconditions

Only start this phase after P0 is green. Prefer P1 to be completed first if its changes touch shared request or service wiring.

## Current repo-grounded architecture facts

These are true in the current codebase:

- `python_adapter_server.py` is still the main FastAPI application entry point.
- `python_adapter_server.py` already includes `recovery_autopilot_router`.
- `python_adapter_server.py` still owns a large number of non-autopilot routes directly.
- `models/` and `routers/` directories already exist, so this is a continuation, not a greenfield structure.

## Required outcome

Move the remaining route surface into coherent APIRouter modules and centralize reusable models where it reduces duplication, while preserving current API behavior.

## Scope

Likely route groupings:

- `routers/pipeline_router.py`
- `routers/skills_router.py`
- `routers/memory_router.py`
- `routers/runtime_router.py`
- `routers/resources_router.py`
- optionally a dedicated non-autopilot `routers/recovery_router.py` if it improves clarity

Likely model groupings:

- pipeline payloads
- skills payloads
- memory payloads
- runtime payloads
- resources payloads

## Required design constraints

1. `python_adapter_server.py` must remain the single authoritative app entry point.
2. Routers must be imported and included from the main app rather than creating standalone apps.
3. Existing route paths, response shapes, and status code behavior must not change.
4. Do not duplicate the already modularized autopilot router logic.
5. If you extract models, do it incrementally and only when import cycles remain manageable.

## Strong warning

Do not pursue a cosmetic refactor that silently changes import-time side effects, singleton initialization, or route registration order. The goal is maintainability without contract drift.

## Acceptance criteria

All of the following must be true:

1. The main application still starts from `python_adapter_server:app`.
2. No route collisions are introduced.
3. Existing H4.1 tests continue to pass.
4. Recovery routes remain stable.
5. The modularization is truthful: completion reporting must state exactly what was extracted and what remains in `python_adapter_server.py`.

## Verification commands

Run these after implementation:

```powershell
& '.\.venv-1\Scripts\python.exe' -m pytest test_recovery_autopilot_cli.py test_integration_h41.py test_h41_final_hardening.py test_recovery_api_routes_real.py -q
& '.\.venv-1\Scripts\python.exe' -m pytest -q
```

## Deliverables

1. Router extraction for the selected route groups
2. Any supporting model extraction that reduces duplication
3. A truthful completion report documenting:
   - which routes moved
   - which routes intentionally stayed in the main adapter
   - exact test results

## Output expectations

At the end, report:

- rollback snapshot path
- files changed
- whether `python_adapter_server:app` remains the sole app entry point
- exact passing test counts
