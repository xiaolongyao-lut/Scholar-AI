# Phase P5: Async Database Evaluation and Safe PoC

You are working in `C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script`.

Today is April 11, 2026.

Your mission is not to force a full async database migration. Your mission is to evaluate whether such a migration is justified, and only build a narrowly scoped proof of concept if the evidence supports it.

## Non-negotiable execution rules

1. Before editing any file, create a rollback snapshot under `.rollback_snapshots/` with a timestamped folder name and copy every file you plan to modify into it.
2. Before writing code, search official or mature sources for the relevant implementation patterns. At minimum, review:
   - `aiosqlite` official documentation
   - FastAPI async persistence patterns
   - migration risk patterns for synchronous to asynchronous store APIs
3. Do not convert the full repository to async by default in this phase.
4. Start with analysis and risk accounting before code changes.
5. A proof of concept is allowed only if it remains isolated and reversible.

## Preconditions

Only start this phase after P0 is green. It is strongly preferred that P2 and P4 are completed first so current API and observability behavior are stable.

## Current repo-grounded facts

These are true in the current codebase:

- `canonical_event_store.py` is currently synchronous.
- `memory_fact_store.py` is currently synchronous.
- Recovery CLI and recovery/API paths depend on these stores.
- A naive async conversion would cascade into handler contracts, CLI wrappers, tests, and singleton lifecycle management.

## Required outcome

Produce a decision-quality evaluation of async DB migration risk and value. If justified, implement only a narrow PoC that does not force a repository-wide async contract migration.

## Required work sequence

1. Analyze current sync store usage:
   - entry points
   - hot paths
   - blocking behavior
   - likely contention points
2. Identify the real motivation:
   - throughput
   - latency
   - connection lifecycle
   - architectural consistency
3. Compare the migration cost against likely benefit.
4. Only if the benefit is credible, build an isolated PoC.

## PoC guardrails

If you choose to build a PoC:

1. Keep it isolated behind a separate implementation path, adapter, or experiment file.
2. Do not switch the main app or CLI to async store contracts by default.
3. Do not require a massive test rewrite.
4. Clearly label the PoC as experimental.

## Strong warning

If the evidence does not support migration, the correct output is a truthful recommendation not to migrate yet.

## Acceptance criteria

All of the following must be true:

1. There is a clear written assessment of async migration value and cost.
2. The report distinguishes:
   - what is proven
   - what is inferred
   - what remains unknown
3. If a PoC is built, it is isolated and reversible.
4. No mainline contract is silently changed.
5. Completion reporting makes it clear whether the result is:
   - no-go
   - defer
   - proceed later with a larger migration plan

## Verification commands

If no PoC is implemented:

```powershell
& '.\.venv-1\Scripts\python.exe' -m pytest -q
```

If a PoC is implemented, also run the smallest focused verification commands that exercise it and report them exactly.

## Deliverables

1. Async migration assessment report
2. Optional isolated PoC, only if justified
3. Truthful recommendation:
   - do not migrate yet
   - migrate later with a dedicated phase
   - proceed to a larger migration plan

## Output expectations

At the end, report:

- rollback snapshot path
- files changed
- whether a PoC was created
- exact verification commands run
- final recommendation on async DB migration
