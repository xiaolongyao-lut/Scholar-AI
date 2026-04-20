# Refactor Policy

## Authority

Only Morpheus may authorize a refactor.

## What Counts as a Refactor

Treat these as refactors:

- Structural reorganization across modules or directories
- Rewriting major logic without preserving the local implementation pattern
- Broad style rewrites in frontend or backend
- Replacing a stable implementation approach with a new pattern

## Required Steps Before Refactor

1. Confirm explicit authorization from Morpheus.
2. Create a backup before editing target files.
3. Record the backup location in `.squad/log/refactor-backups.md`.
4. Only then begin the refactor.

## Backup Convention

Suggested backup path pattern:

- `.squad/backups/YYYY-MM-DD/<task-slug>/`

Include:

- files backed up
- reason for refactor
- who authorized it
- who executed it

## Normal Work Is Not Refactor

These do not automatically count as refactors:

- small feature additions
- bug fixes
- narrow test additions
- local UI wording adjustments inside the current style system

When unsure, escalate to Morpheus before proceeding.
