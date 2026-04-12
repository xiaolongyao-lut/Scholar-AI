# Phase H4 Prompt: Guarded Autopilot Recovery

You are working in the `Modular-Pipeline-Script` repository on **April 10, 2026**.

## Non-Negotiable First Steps

1. **Create a rollback snapshot before changing anything.**
   - Create a timestamped snapshot under:
     - `.rollback_snapshots/phase-h4-guarded-autopilot-<timestamp>/`
   - Copy every file you plan to edit into that snapshot first.
   - Include runtime files, tests, docs, and any API/CLI files in the snapshot set.

2. **Search mature, official solutions on the web before implementation.**
   - Use official docs and mature production patterns, not blogspam.
   - At minimum, benchmark:
     - Python `argparse` docs if you extend the CLI
     - pytest docs for CLI / integration testing patterns
     - Kubernetes docs for `dry-run`, `warn`, and `audit` safety patterns
     - GitHub docs for required-reviewer / environment protection style gates
     - Open Policy Agent docs for policy-as-code design ideas
   - You do **not** need to import those systems as dependencies. Use them as design references for safety gates, approvals, and auditability.
   - Record the exact sources you used in the completion report.

3. **Inspect repository truth before coding.**
   - Do not trust stale summaries.
   - Confirm the current real state from code and tests:
     - Phase H1 / H1.1 implemented
     - Phase H2 implemented
     - Phase H3.1 integration hardening implemented
     - current repository baseline:
       - `399 tests collected`
       - `396 passed, 3 skipped, 32 warnings`
     - focused H3.1 validation:
       - `99 passed, 5 pre-existing warnings`

## Goal

Implement **Phase H4: Guarded Autopilot Recovery** as a safe, policy-gated recovery layer on top of the existing recommendation, workflow, audit, and observability stack.

This phase must remain **strictly bounded**:

- autopilot is **disabled by default**
- only explicitly allowed actions may execute
- every action must pass policy evaluation first
- every action must be auditable and reversible where possible
- an emergency stop / kill switch must exist
- no hidden autonomy

Do **not** build speculative, free-running autonomous recovery.
Build a production-defensible, policy-constrained autopilot foundation.

## Required Scope

### 1. Implement policy definitions and evaluation

Add a module such as:

- `recovery_autopilot_policy.py`

It should define typed policy models and evaluation logic, including at minimum:

- global enable / disable state
- confidence threshold
- allowed action types
- scope limits
- approval requirements by action/risk
- emergency stop state
- optional per-job or per-session exclusions

Policy evaluation must produce a typed result explaining:

- allowed vs blocked
- blocking reason(s)
- applied thresholds
- matched allowlist/denylist rules
- whether operator approval is still required

### 2. Implement guarded executor

Add a module such as:

- `recovery_autopilot_executor.py`

It must:

- consume real recovery recommendations
- evaluate policy before execution
- support dry-run and real execution modes
- persist audit events for every decision path
- emit observability metrics / telemetry hooks
- refuse execution if autopilot is disabled or emergency stop is active

Start with a **small allowed action surface**.
Do not enable every recovery action type at once.
A narrow, defensible initial scope is preferred.

### 3. Integrate with existing recovery infrastructure

Reuse existing repository components instead of duplicating logic:

- `recovery_recommendation_engine.py`
- `recovery_execution_engine.py`
- `recovery_workflows.py`
- `recovery_cli.py`
- `python_adapter_server.py`
- `recovery_metrics_exporter.py`
- `recovery_telemetry.py`
- `recovery_store_provider.py`

Normal autopilot flows must use the same shared persistent stores already introduced in H3.1.

### 4. Add operator controls

Extend CLI and/or API surface with safe operator controls for:

- viewing autopilot policy
- enabling autopilot explicitly
- disabling autopilot explicitly
- emergency stop
- dry-run autopilot evaluation for a recommendation/job
- reviewing the latest autopilot execution decisions

These controls must be explicit and understandable under incident pressure.

### 5. Make auditability first-class

Every autopilot decision path must be captured, including:

- recommendation received
- policy evaluation result
- approval path
- execution attempted or blocked
- outcome and rollback hint
- emergency stop trigger if used

Use canonical events and existing observability mechanisms where possible.

### 6. Add comprehensive tests

Add focused tests for:

- policy parsing / validation
- blocked vs allowed decisions
- emergency stop behavior
- disabled-by-default behavior
- dry-run evaluation path
- real execution path for the initial allowed action surface
- audit event emission
- metrics / telemetry accounting
- CLI/API operator control paths

Prefer seeded integration tests where feasible.

### 7. Deliver truthful documentation

Create a report, for example:

- `PHASE_H4_GUARDED_AUTOPILOT_REPORT.md`

It must include:

- exact scope implemented
- action types actually enabled
- what remains intentionally out of scope
- official references consulted
- validation commands run
- exact test counts
- residual warnings and whether they are pre-existing

No inflated claims. No fake files. No “full autonomy” language unless you actually built and verified it.

## Hard Constraints

- Preserve unrelated user changes.
- Keep strict typing throughout.
- Default autopilot state must be OFF.
- Require explicit operator action to enable autopilot.
- Include emergency stop.
- Do not bypass policy evaluation.
- Do not create hidden execution paths.
- Use shared persistent stores, not ephemeral `:memory:` stores.
- Keep observability and audit paths truthful.
- Prefer a smaller safe initial scope over a large risky one.

## Acceptance Criteria

- typed autopilot policy and evaluation models exist
- guarded autopilot executor exists
- autopilot is disabled by default
- emergency stop works
- only explicitly allowed action types can execute
- blocked decisions are explainable and auditable
- CLI/API operator controls exist
- observability hooks track autopilot decisions
- tests prove both blocked and allowed paths
- existing H1/H2/H3.1 functionality remains green
- repository-wide collection still succeeds

## Mandatory Validation Checklist

Run all of the following after implementation:

```powershell
# 1. Compile changed files
& .\.venv-1\Scripts\python.exe -m py_compile recovery_autopilot_policy.py recovery_autopilot_executor.py recovery_cli.py python_adapter_server.py

# 2. New H4 tests
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_autopilot_policy.py test_recovery_autopilot_executor.py -q

# 3. CLI / API integration checks
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_cli_hardened.py test_recovery_api_routes_real.py test_recovery_observability.py -q

# 4. Recovery regression guard
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_recommendation_engine.py test_recovery_execution_engine.py test_recovery_console.py test_memory_fact_store.py test_memory_policy.py -q

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

Do not stop at analysis. Implement the phase end-to-end.
