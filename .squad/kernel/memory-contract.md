# Memory Contract

## Purpose

Defines what agent memory is authoritative, how conflicts are resolved, and
when memory must be audited before acting.

## Memory Sources (priority order)

1. `.squad/kernel/` — Immutable kernel rules. Never overwritten by agents.
2. `.squad/state/` — Live runtime state (blockers.jsonl, pool.jsonl). Agents may append.
3. `.squad/config.json` — User-controlled configuration. Agents may write via `squad tier`.
4. Agent working memory — Ephemeral; not persisted between sessions.

## Write Rules

- Agents MUST NOT modify files under `.squad/kernel/`.
- State appends to JSONL files are the only permitted writes under `.squad/state/`.
- Config writes go through `Set-SquadConfig` only; no direct file manipulation.

## Audit Trigger

Run `squad memory audit` before any multi-step destructive operation
(mass delete, schema migration, bulk API calls).

## Conflict Resolution

When agent working memory conflicts with `.squad/kernel/` rules, the kernel wins.
When `.squad/state/` and user intent conflict, surface the conflict and wait for
explicit resolution (do not silently override state).
