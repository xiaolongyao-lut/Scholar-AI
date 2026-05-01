# Phase H3 Prompt: Operator Workflow CLI + Roadmap Truth Sync

You are working in the `Modular-Pipeline-Script` repository on **April 10, 2026**.

## Non-Negotiable First Steps

1. **Create a rollback snapshot before changing anything.**
   - Create a timestamped snapshot under:
     - `.rollback_snapshots/phase-h3-operator-workflow-<timestamp>/`
   - Copy every file you plan to edit into that snapshot first.
   - Include any new test files, docs, and touched runtime files in the snapshot set.

2. **Search mature, official solutions on the web before implementation.**
   - Use official documentation and mature upstream patterns, not blogspam.
   - At minimum, benchmark:
     - official `pytest` docs for CLI testing patterns
     - official `Typer` or `Click` docs if you choose a framework
     - official `argparse` docs if you keep the dependency surface minimal
     - official `Rich` docs only if you introduce formatted terminal UX
   - Record the exact sources you used in the implementation report.

3. **Inspect the repository truthfully before coding.**
   - Do not assume the roadmap is current.
   - Confirm the current real state from code and tests:
     - Phase H1.1 memory evidence is already implemented
     - H2 observability is already present in code (`recovery_metrics_exporter.py`, `recovery_telemetry.py`, `/recovery/metrics`, `test_recovery_observability.py`)
     - Current verified baseline after the latest repo hardening is:
       - `372 passed, 3 skipped`
       - `375 tests collected`

## Goal

Implement **Phase H3: Safe Operator Workflow and CLI** for Harness Recovery, and truth-sync the roadmap so it matches the repository as it actually exists now.

This phase must stay **operator-safe**:

- no autonomous recovery execution
- no hidden side effects
- no silent fact mutation beyond already-supported explicit invalidation flows
- recommendations and workflows must remain inspectable, explainable, and approval-aware

## Required Scope

### 1. Truth-sync the roadmap first

Update `PHASE_H_ROADMAP.md` so it no longer falsely says:

- H1 is merely "in progress"
- H2 is only "planned"

The roadmap must reflect the real state as of **April 10, 2026**, grounded in repository files and passing tests.

### 2. Add an operator-facing recovery CLI

Implement a production-grade CLI entrypoint, for example:

- `recovery_cli.py`

The CLI must wrap the existing recovery stack rather than reimplementing it.
Reuse real stores, engines, and adapters already present in the repository.
Do **not** create fresh empty in-memory stores for normal runtime flows.

At minimum, support commands in these categories:

- inspect event timeline
- inspect current memory/facts
- fetch recovery recommendations
- explain recommendation evidence
- show observability metrics
- run dry-run workflow previews
- invalidate a fact only through explicit guarded command flow

If you choose `argparse`, keep it clean and typed.
If you choose `Typer` or `Click`, justify it from maturity, compatibility, and current repo constraints.
Do not add a flashy dependency unless it materially improves maintainability.

### 3. Add guided operator workflows

Implement a separate module, for example:

- `recovery_workflows.py`

This layer should provide safe, guided flows such as:

- recommendation review flow
- dry-run replay preview
- state rehydration preview
- fact invalidation confirmation path
- evidence summary generation for incident operators

These workflows must consume the existing:

- canonical event store
- temporal fact store
- recovery recommendation engine
- observability hooks

### 4. Make the CLI output understandable under pressure

Borrow mature UX ideas from robust operator tools:

- concise summaries first
- evidence counts and confidence clearly surfaced
- clear warning text for destructive or high-risk actions
- dry-run output separated from actual execution

You may borrow inspiration from the local `openhanako-0.91.9` benchmark work for capability surfacing and operator readability, but **do not** port Electron packaging or Node-specific architecture into this Python CLI phase.

### 5. Add comprehensive tests

Create or update tests for:

- CLI argument parsing
- happy-path CLI commands
- seeded recommendation inspection
- dry-run workflow behavior
- guarded invalidation flow
- observability integration for CLI-triggered paths
- regression safety for existing H1.1 and H2 features

Prefer real seeded integration tests over shallow mocks where feasible.
If you introduce a CLI framework, use its official testing utility.

### 6. Deliver truthful documentation

Create a completion report, for example:

- `PHASE_H3_OPERATOR_WORKFLOW_REPORT.md`

The report must include:

- what was actually implemented
- what remains out of scope
- official sources consulted
- exact validation commands run
- real pass counts
- known residual warnings or limitations

No inflated claims. No fake files. No stale counts.

## Hard Constraints

- Preserve existing behavior unless a change is required for correctness.
- Do not revert unrelated user changes.
- Keep strict typing throughout.
- Add defensive guardrails for all CLI inputs.
- Keep compatibility with the current FastAPI recovery surface.
- Do not introduce autonomous recovery.
- Do not fake persistence or telemetry integrations.

## Acceptance Criteria

- `PHASE_H_ROADMAP.md` truthfully reflects real H1.1 and H2 completion state
- operator CLI is implemented and usable
- guided workflows exist as reusable code, not only inline CLI logic
- recommendations, facts, metrics, and evidence are inspectable from the CLI
- dry-run behavior is explicit and safe
- tests cover both unit and seeded integration paths
- existing recovery and memory functionality remains green
- repository-wide collection still succeeds

## Mandatory Validation Checklist

Run all of the following after implementation:

```powershell
# 1. Compile changed runtime files
& .\.venv-1\Scripts\python.exe -m py_compile recovery_cli.py recovery_workflows.py python_adapter_server.py recovery_recommendation_engine.py

# 2. Focused tests for the new phase
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_observability.py test_recovery_api_routes_real.py test_recovery_recommendation_engine.py -q

# 3. New CLI/workflow tests
& .\.venv-1\Scripts\python.exe -m pytest test_recovery_cli.py test_recovery_workflows.py -q

# 4. Regression guard
& .\.venv-1\Scripts\python.exe -m pytest test_memory_fact_store.py test_memory_policy.py test_writing_runtime.py test_skill_registry.py -q

# 5. Repository collection
& .\.venv-1\Scripts\python.exe -m pytest --collect-only -q

# 6. Full suite
& .\.venv-1\Scripts\python.exe -m pytest -q
```

## Output Requirements

When finished, provide:

1. a short implementation summary
2. the exact files created and modified
3. the rollback snapshot path
4. the official/mature sources consulted
5. the final validation results with exact counts
6. any residual warnings that still remain and whether they are pre-existing or newly introduced

Do not stop at analysis. Implement the phase end-to-end.
