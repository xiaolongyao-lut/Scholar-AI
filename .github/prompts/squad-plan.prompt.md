---
name: squad-plan
agent: plan
description: Create or refresh a Squad execution plan using the repo startup packet, active docs/plans plan, rollback requirement, and official Copilot customization boundaries.
argument-hint: "[objective or active plan path]"
---

# Squad Plan

Create or refresh a Squad-compatible execution plan for `${input:objective:the requested objective}`.

## Required Inputs

Read these sources before producing the plan:

- `.github/copilot-instructions.md`
- `.github/agents/squad.agent.md`
- `docs/plans/kilo/2026-04-27-squad-official-capability-reuse.md`
- The active project plan if the user names one, otherwise the most relevant `docs/plans/**/*.md`
- `.squad/identity/start-here.md` when present
- `.squad/routing.md` and `.squad/decisions.md` when present

## Planning Rules

- Do not edit product code from this prompt. Produce a plan or plan patch only.
- Start every nontrivial implementation slice with an explicit rollback snapshot requirement.
- For interface, security, config, permission, or workflow changes, include an official or mature-solution comparison step before implementation.
- Route multi-file implementation back to Squad after the plan is accepted; do not create a second coordinator entry point.
- Do not use `tools/squad/squad.ps1`; it is retired. Long-running detached work must use Copilot CLI Sessions or a documented handoff packet.
- Do not touch `.env`, secrets, provider routing, corpus/goldset scope, or final gate-pass decisions unless the active plan or user explicitly authorizes it.

## Output Format

Return Markdown with these sections:

1. `Facts`: current files, state, gaps, and evidence paths.
2. `Decisions`: low-risk self-decisions already covered by the plan envelope.
3. `Rollback`: exact snapshot location and restore scope required before edits.
4. `Mature References`: official or mature patterns to consult, with URLs or local reference paths.
5. `Tasks`: task table with owner, files, verification command, status, and stop condition.
6. `Open`: unresolved decisions that require user confirmation.
7. `Next`: the single safest executable next action for Squad.
