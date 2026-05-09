# Phase P4: Focused Observability Upgrade

You are working in `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`.

Today is April 11, 2026.

Your mission is to improve observability in the most valuable execution paths without turning this phase into a full-platform rewrite.

## Non-negotiable execution rules

1. Before editing any file, create a rollback snapshot under `.rollback_snapshots/` with a timestamped folder name and copy every file you plan to modify into it.
2. Before writing code, search official or mature sources for the relevant implementation patterns. At minimum, review:
   - OpenTelemetry Python instrumentation
   - FastAPI / Starlette middleware guidance
   - low-overhead metrics collection patterns
3. Start with the smallest useful observability surface.
4. Do not combine this phase with full async DB migration.
5. Do not add tracing everywhere just because it is possible.

## Preconditions

Only start this phase after P0 is green.

## Current repo-grounded facts

These are true in the current codebase:

- The repository already has recovery metrics and telemetry-related tests.
- `recovery_autopilot_router.py` exposes a metrics endpoint.
- The recovery and autopilot stack already has observability concepts, but instrumentation depth is uneven.

## Required outcome

Add targeted observability to the highest-value execution paths:

- recovery/autopilot control actions
- recovery recommendation generation
- canonical event store critical operations
- scoring pipeline entry point only if it fits naturally

## Required design

1. Add a small, reusable tracing setup module if needed.
2. Prefer explicit spans around critical operations over broad, noisy tracing.
3. Preserve graceful degradation when optional observability dependencies are absent.
4. Ensure metrics and trace additions do not change business behavior.

## Strong warning

Do not gate core execution on observability components. If tracing exporters are unavailable, the application must still run.

## Acceptance criteria

All of the following must be true:

1. Critical recovery/autopilot operations emit useful telemetry or spans.
2. Existing metrics behavior remains intact or improves truthfully.
3. No route or business contract changes are introduced.
4. Observability additions have test coverage where practical.
5. Completion reporting clearly distinguishes implemented instrumentation from future ideas.

## Verification commands

Run these after implementation:

```powershell
& '.\.venv-1\Scripts\python.exe' -m pytest test_recovery_observability.py test_integration_h41.py test_h41_final_hardening.py -q
& '.\.venv-1\Scripts\python.exe' -m pytest -q
```

If you add optional exporter setup, also run a local smoke test and report the exact command.

## Deliverables

1. Focused observability implementation
2. Supporting tests
3. A truthful completion report with:
   - exact instrumented paths
   - any optional dependency behavior
   - exact test counts
   - measured or estimated overhead if available

## Output expectations

At the end, report:

- rollback snapshot path
- files changed
- which paths are now instrumented
- exact passing test counts
- whether any remaining observability gaps were intentionally deferred
