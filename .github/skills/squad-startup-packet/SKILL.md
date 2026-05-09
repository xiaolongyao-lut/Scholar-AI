---
name: squad-startup-packet
description: Load and summarize the Squad startup packet before routing, dispatch, long-run work, or governance repair. Use when a task invokes Squad mode, asks for autonomous project execution, resumes a long run, or modifies Squad governance/customization files.
---

# Squad Startup Packet

Use this skill before Squad routing, dispatch, long-run execution, or governance changes.

## Workflow

1. Resolve `TEAM_ROOT` from the current repository root. Refuse to continue if the resolved root does not contain `.github/agents/squad.agent.md`.
2. Create or verify a rollback snapshot before any non-read-only change. Use `.rollback_snapshots/<slug>-<YYYYMMDD_HHMMSS>/` inside `TEAM_ROOT`.
3. Read `.github/copilot-instructions.md` and `.github/agents/squad.agent.md` for the active coordinator contract.
4. Read `.squad/identity/start-here.md` if present, then follow its mandatory read order. If it is absent, record the absence and continue only with enough evidence from `.squad/team.md`, `.squad/routing.md`, `.squad/decisions.md`, and `.squad/identity/now.md`.
5. Read the active `docs/plans/active/*.md` file for current scope and continuation gate state. Follow legacy redirect stubs only when an old conversation names `.kilo/plans/` or `.copilot-tracking/plans/`.
6. For interface, security, config, permission, or workflow changes, consult official or mature references before implementation and record the source in the evidence package.
7. Run these checks when the task involves Squad governance, long-run startup, or handoff readiness:
   - `powershell -NoProfile -ExecutionPolicy Bypass -File tools/squad/smoke-test.ps1`
   - `powershell -NoProfile -ExecutionPolicy Bypass -File tools/squad/profile-version-check.ps1`
   - `powershell -NoProfile -ExecutionPolicy Bypass -File tools/squad/check-ghost.ps1`

## Output Contract

Return a startup packet with:

- `Team root`: resolved absolute path.
- `User / owner context`: source path only; never copy private profile content.
- `Active plan`: path and open-task summary.
- `Loaded governance`: agent, instructions, routing, decision files, and skill/prompt files used.
- `Allowed scope`: files and actions permitted by the request.
- `Disallowed scope`: secrets, provider routing, corpus/goldset, destructive cleanup, final gate promotion, or any additional local boundary.
- `Rollback`: snapshot path and restore scope.
- `Mature references`: official URLs or local mature-solution paths checked.
- `Evidence`: commands run and artifact paths.
- `Safe next action`: one executable next step or a hard stop reason.

## Guardrails

- Never print or persist secret values.
- Never mark a run healthy without fresh artifacts, command output, or timestamped evidence.
- Never use `tools/squad/squad.ps1`; it is retired and kept only as `.deprecated` history.
- If any check fails, stop with `Facts / Decision needed / Evidence / Safe next action` instead of dispatching work.
