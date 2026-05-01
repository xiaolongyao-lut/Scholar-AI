# Phase H3.1 Prompt: Operator Workflow CLI Integration Hardening

You are working in the `Modular-Pipeline-Script` repository on **April 10, 2026**.

## Non-Negotiable First Steps

1. **Create a rollback snapshot before changing anything.**
   - Create a timestamped snapshot under:
     - `.rollback_snapshots/phase-h3-integration-hardening-<timestamp>/`
   - Copy every file you will edit into the snapshot first.
   - Include runtime files, tests, and docs in the snapshot set.

2. **Search mature, official solutions on the web before implementation.**
   - Use official docs and mature upstream patterns only.
   - At minimum, benchmark:
     - Python `argparse` official docs for subcommands and validation
     - `pytest` official docs for CLI/output testing and capture
     - Python `unittest.mock` official docs for controlled seams where real integration is not feasible
   - If you introduce any new dependency, justify it against the current repo constraint of keeping the CLI dependency-light.
   - Record exact sources used in the completion report.

3. **Inspect repository truth before coding.**
   - Do not trust phase summaries blindly.
   - Confirm the current real H3 state from code and tests.

## Verified Current State

The repository already contains:

- `recovery_cli.py`
- `recovery_workflows.py`
- `test_recovery_cli.py`
- updated `PHASE_H_ROADMAP.md`

Current verified facts:

- `test_recovery_cli.py` passes (`8 passed`)
- `recovery_cli.py` and `recovery_workflows.py` compile cleanly
- `PHASE_H_ROADMAP.md` truth-syncs H1 complete, H2 complete, H3 in progress

However, **H3 is not production-complete yet**. Key integration gaps remain:

1. `recovery_cli.py` still creates fresh empty stores like `CanonicalEventStore(":memory:")` and `MemoryFactStore()` in command handlers.
2. Multiple CLI commands still return placeholder output such as:
   - `"coming in H3.2"`
   - `"Evidence tracing coming in H3.2"`
   - `"Dry-run simulation coming in H3.2"`
3. `recovery_workflows.py` still contains placeholder behavior such as:
   - empty `simulated_effects`
   - empty `rollback_plan`
   - comment-only invalidation path instead of real guarded integration
4. `test_recovery_cli.py` is too forgiving in places, e.g. accepts either success or failure (`assertIn(result, [0, 1])`) instead of proving correct real behavior.
5. There is no separate seeded integration test coverage proving the CLI reads real events, facts, recommendations, and metrics from repository-backed stores.

## Goal

Complete **Phase H3.1 Integration Hardening** so the operator CLI and guided workflows become genuinely repository-integrated, evidence-backed, and safely usable under incident pressure.

Do **not** jump to H4 autopilot yet.
The next task is to harden H3 until it is truthfully ready.

## Required Scope

### 1. Replace fresh empty stores with real shared stores

Update `recovery_cli.py` so normal commands use the repository's actual store/provider getters or equivalent shared runtime wiring.

Do not use new empty instances like:

- `CanonicalEventStore(":memory:")`
- `MemoryFactStore()`

for normal operator flows unless the command is explicitly a test-only path.

The CLI should reflect real repository state, not blank process-local state.

### 2. Remove placeholder command behavior

Fully implement these CLI surfaces with real data:

- `events`
- `memory`
- `facts`
- `recommendations`
- `explain`
- `metrics`
- `invalidate-fact`
- `dry-run`

Each command must return deterministic, useful operator output.
No `"coming later"` placeholders.
No fake success messages.

### 3. Harden workflow implementations

Update `recovery_workflows.py` so workflows consume real recovery components and provide real structured outputs:

- recommendation review should expose actual recommendation payload and evidence summary
- dry-run preview should produce real effect summaries and rollback hints from existing recovery machinery
- fact invalidation should use the real guarded invalidation path and persist audit context
- state rehydration preview should inspect actual recoverable state and impacted resources

These workflows must remain operator-safe:

- preview first
- explicit confirmation for sensitive actions
- clear auditability
- no autonomous recovery execution

### 4. Upgrade tests from permissive to proof-oriented

Strengthen the tests so they prove behavior instead of tolerating failure.

Required test changes:

- remove `assertIn(result, [0, 1])` style assertions
- add seeded CLI integration tests
- validate actual stdout/stderr content
- validate real evidence-backed recommendation output
- validate fact invalidation confirmation behavior
- validate dry-run preview structure against seeded data
- validate metrics command returns non-empty Prometheus text when seeded

If useful, split tests into:

- `test_recovery_cli.py` for command behavior
- `test_recovery_workflows.py` for workflow logic

### 5. Keep roadmap truthful

Update `PHASE_H_ROADMAP.md` only if needed, but keep it honest:

- H3 should remain `IN PROGRESS` unless the code and validation really justify completion
- do not mark H3 complete unless placeholders are removed and real integration is proven

### 6. Deliver truthful documentation

Create a report, for example:

- `PHASE_H3_INTEGRATION_HARDENING_REPORT.md`

It must include:

- exact gaps fixed
- files changed
- rollback snapshot path
- official sources consulted
- validation commands run
- exact pass counts
- residual warnings and whether they were pre-existing

No inflated claims. No fake files. No stale numbers.

## Hard Constraints

- Preserve existing user changes unrelated to this task.
- Keep strict typing.
- Add defensive input validation for all CLI entrypoints.
- Prefer minimal dependency surface.
- Reuse existing recovery/memory/event infrastructure.
- No autonomous execution.
- No fake telemetry.
- No in-memory-only happy path for normal CLI commands.

## Acceptance Criteria

- CLI commands read from real repository-backed recovery state
- placeholder text is fully removed from user-facing command outputs
- workflows produce real, inspectable structured outputs
- fact invalidation is guarded and auditable
- dry-run preview is evidence-backed
- tests prove success paths and seeded integration paths
- H1.1 and H2 regressions stay green
- repository-wide collection still succeeds

## Mandatory Validation Checklist

Run all of the following after implementation:

```powershell
# 1. Compile changed files
& .\.venv-1\Scripts\python.exe -m py_compile recovery_cli.py recovery_workflows.py test_recovery_cli.py

# 2. H3-focused tests
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_cli.py test_recovery_workflows.py -q

# 3. Recovery regression guard
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_api_routes_real.py test_recovery_recommendation_engine.py test_recovery_observability.py -q

# 4. Memory/runtime regression guard
& .\.venv-1\Scripts\python.exe -m pytest test_memory_fact_store.py test_memory_policy.py test_writing_runtime.py test_skill_registry.py -q

# 5. Repository collection
& .\.venv-1\Scripts\python.exe -m pytest --collect-only -q

# 6. Full suite
& .\.venv-1\Scripts\python.exe -m pytest -q
```

## Output Requirements

When finished, provide:

1. a short implementation summary
2. exact files created and modified
3. the rollback snapshot path
4. the official sources consulted
5. final validation results with exact counts
6. remaining warnings or limitations, explicitly labeled as pre-existing or newly introduced

Do not stop at analysis. Implement the hardening end-to-end.
