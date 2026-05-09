# Phase H4.1 Prompt: Guarded Autopilot Integration Hardening

You are working in the `Modular-Pipeline-Script` repository on **April 11, 2026**.

## Non-Negotiable First Steps

1. **Create a rollback snapshot before changing anything.**
   - Create a timestamped snapshot under:
     - `.rollback_snapshots/phase-h4-1-integration-hardening-<timestamp>/`
   - Copy every file you plan to edit into that snapshot first.
   - Include runtime files, tests, API files, CLI files, and docs.

2. **Search mature, official solutions on the web before implementation.**
   - Use official docs and mature production patterns only.
   - At minimum, benchmark:
     - Kubernetes API concepts for `dry-run` and safety-first mutation patterns
     - GitHub environment protection / required reviewer patterns for explicit operator gates
     - Open Policy Agent policy-language docs for policy-as-code evaluation design
     - Python `argparse` docs if you extend the CLI
     - pytest docs for CLI/API integration testing
   - You do **not** need to import those systems as dependencies. Use them as design references for safe gating, approval, and auditability.
   - Record the exact sources used in the completion report.

3. **Inspect repository truth before coding.**
   - Do not trust stale summaries.
   - Confirm the current real state from code and tests:
     - H1 / H1.1 implemented
     - H2 implemented
     - H3.1 implemented
     - H4 core primitives implemented
     - current repository baseline:
       - `415 tests collected`
       - `412 passed, 3 skipped, 32 warnings`
     - focused H4/H3.1/API/observability slice:
       - `54 passed, 5 pre-existing warnings`

## Verified Current H4 Gaps

The repository already contains:

- `recovery_autopilot_policy.py`
- `recovery_autopilot_executor.py`
- `test_recovery_autopilot.py`

However, H4 is **not yet end-to-end complete**. These gaps remain:

1. Autopilot is not wired into `recovery_cli.py`.
2. Autopilot is not wired into `python_adapter_server.py`.
3. `AutopilotExecutor` keeps only in-memory execution logs; it does not persist canonical audit events.
4. `AutopilotExecutor` does not emit recovery metrics / telemetry hooks.
5. `execute_autonomous()` still contains simplified execution behavior instead of a real typed delegated path through the recovery execution stack.
6. Policy templates are enabled-on-create; there is not yet an explicit default-off operator control plane.

## Goal

Complete **Phase H4.1 Integration Hardening** so guarded autopilot becomes an actually integrated recovery capability rather than a standalone core module.

The result must remain:

- disabled by default
- explicitly operator-controlled
- policy-gated
- auditable
- observable
- easy to stop

Do **not** broaden scope into H5 multi-tenancy.
Do **not** create free-running autonomy.

## Required Scope

### 1. Add explicit default-off autopilot control plane

Implement a real control layer for autopilot state:

- disabled by default on startup
- explicit enable action required
- explicit disable action required
- emergency stop support
- clear status inspection

The control plane should be reusable from both CLI and API.

### 2. Integrate autopilot into CLI

Extend `recovery_cli.py` with safe operator commands such as:

- autopilot status
- autopilot enable
- autopilot disable
- autopilot emergency-stop
- autopilot policy show/set
- autopilot history
- autopilot evaluate <job/recommendation>
- autopilot execute <job/recommendation> --dry-run / --confirm
- autopilot rollback <execution_id>

Keep the CLI dependency-light.
Use strong argument validation.
Make unsafe actions require explicit confirmation semantics.

### 3. Integrate autopilot into API

Add safe FastAPI endpoints in `python_adapter_server.py` for:

- status
- enable / disable
- emergency stop
- policy inspection / update
- dry-run evaluation
- execution history

These endpoints must use the same shared stores and autopilot control state as the CLI.

### 4. Persist canonical audit trail

Update autopilot execution paths to emit real canonical events for:

- policy evaluated
- execution blocked
- execution authorized
- dry-run requested
- execution started
- execution completed
- execution failed
- rollback requested
- rollback completed / failed
- emergency stop toggled

Use the existing canonical event infrastructure instead of inventing a parallel audit mechanism.

### 5. Emit observability metrics and telemetry

Hook autopilot into:

- `recovery_metrics_exporter.py`
- `recovery_telemetry.py`

Track at minimum:

- autopilot evaluations total
- autopilot blocked decisions total
- autopilot executed decisions total
- autopilot rollbacks total
- autopilot emergency stop toggles total
- autopilot execution duration

### 6. Replace simplified execution path

Harden `AutopilotExecutor.execute_autonomous()` so the initial allowed action surface delegates through real recovery execution machinery.

Start with a **small safe scope**.
If only one action type is truly ready, keep it to that one.

The implementation must be truthful about what is actually executable.

### 7. Add comprehensive tests

Add or split tests as needed, for example:

- `test_recovery_autopilot.py`
- `test_recovery_autopilot_api.py`
- `test_recovery_autopilot_cli.py`

Cover:

- disabled-by-default behavior
- enable / disable transitions
- emergency stop
- policy update / inspection
- CLI integration
- API integration
- canonical audit event emission
- metrics / telemetry emission
- dry-run evaluation
- real execution for the initial allowed action type
- rollback behavior

Prefer seeded integration tests where feasible.

### 8. Deliver truthful documentation

Create a report, for example:

- `PHASE_H4_1_INTEGRATION_HARDENING_REPORT.md`

It must include:

- exact gaps fixed
- exact scope still intentionally limited
- files changed
- rollback snapshot path
- official sources consulted
- validation commands run
- exact pass counts
- residual warnings labeled as pre-existing or newly introduced

No inflated claims. No “fully autonomous” language.

## Hard Constraints

- Preserve unrelated user changes.
- Keep strict typing throughout.
- Default autopilot state must be OFF.
- No hidden execution paths.
- No bypass around policy evaluation.
- Use shared persistent stores, not `:memory:`.
- Use canonical events for audit.
- Use observability hooks truthfully.
- Prefer a smaller safe initial action surface over a larger risky one.

## Acceptance Criteria

- autopilot is disabled by default
- CLI operator controls exist
- API operator controls exist
- autopilot state is shared consistently across control surfaces
- canonical audit events are emitted for autopilot decision paths
- metrics / telemetry reflect autopilot decisions
- at least one low-risk action type executes through a real delegated path
- dry-run and rollback are exposed safely
- tests prove both blocked and allowed paths
- existing H1/H2/H3.1/H4 core functionality remains green
- repository-wide collection still succeeds

## Mandatory Validation Checklist

Run all of the following after implementation:

```powershell
# 1. Compile changed files
& .\.venv-1\Scripts\python.exe -m py_compile recovery_autopilot_policy.py recovery_autopilot_executor.py recovery_cli.py python_adapter_server.py

# 2. New / updated autopilot tests
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_autopilot.py test_recovery_autopilot_cli.py test_recovery_autopilot_api.py -q

# 3. Recovery integration regression guard
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_cli_hardened.py test_recovery_api_routes_real.py test_recovery_observability.py test_recovery_recommendation_engine.py -q

# 4. Recovery core regression guard
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_execution_engine.py test_recovery_console.py test_memory_fact_store.py test_memory_policy.py -q

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
4. the official / mature references consulted
5. final validation results with exact counts
6. remaining warnings or limitations, clearly labeled as pre-existing or newly introduced

Do not stop at analysis. Implement the hardening end-to-end.
