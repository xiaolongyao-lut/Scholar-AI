# Blocker Arbitration Rules

## Blocker Taxonomy

| Type          | Description                                                       |
|---------------|-------------------------------------------------------------------|
| env_mismatch  | Runtime environment differs from expected (wrong Python, missing venv, etc.) |
| missing_dep   | A required package or tool is not installed                       |
| constraint    | A hard rule or policy prevents the action (cost limit, approval gate, etc.) |
| ambiguity     | Insufficient information to proceed with confidence               |

## Decision Matrix

| Tier      | env_mismatch | missing_dep | constraint | ambiguity  |
|-----------|--------------|-------------|------------|------------|
| default   | self_heal    | queue       | escalate   | escalate   |
| autopilot | self_heal    | self_heal   | constraint | degrade    |

## Decision Definitions

- **self_heal**: Agent attempts to fix the issue autonomously (e.g., activates venv, installs package).
- **queue**: Record the blocker in `.squad/state/blockers.jsonl` and continue other tasks.
- **degrade**: Proceed with reduced scope or a safe fallback; document the compromise.
- **escalate**: Halt and surface the blocker to a human decision-maker immediately.

## Hard Rules

1. `constraint` blockers ALWAYS escalate regardless of tier.
2. Any action that would permanently delete data or spend budget beyond approved limits must escalate.
3. If self-heal fails after one attempt, fall back to `queue` (default) or `escalate` (constraint).
