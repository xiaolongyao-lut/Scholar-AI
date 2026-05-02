---
name: squad-cli-handoff
description: Prepare a safe Copilot CLI Sessions handoff packet for Squad long-running or detached work. Use when chat tools, context limits, or runtime duration make in-session execution unsafe, or when the user explicitly asks to continue in Copilot CLI.
---

# Squad CLI Handoff

Use this skill only when Squad work must move from the current chat session to Copilot CLI Sessions.

## Handoff Preconditions

- Prefer chat-first execution when the task can proceed in bounded checkpoints with fresh evidence.
- Use CLI handoff only for detached/background persistence, chat/tool/session limits, or explicit user request.
- Do not invoke `tools/squad/squad.ps1`; it is retired.
- Do not hand off tasks that require new human approval until the approval is recorded.

## Handoff Packet

Create a Markdown packet under `.squad/orchestration-log/` or `.squad/decisions/inbox/` with:

- `Objective`: one sentence.
- `Repo`: absolute path, branch, dirty-worktree warning, and files already touched.
- `Rollback`: snapshot path created before handoff and restore instructions.
- `Allowed scope`: exact files, directories, commands, and budgets.
- `Disallowed scope`: `.env`, secrets, provider routing, corpus/goldset, non-owned process cleanup, final gate promotion, and any user-specific boundary.
- `Startup packet`: required files to read before continuing.
- `Mature references`: official or mature solution links already checked.
- `Current evidence`: commands run, exit codes, logs, artifacts, and remaining gaps.
- `Execution steps`: ordered, checkpoint-sized steps.
- `Stop conditions`: `user-stop`, `approval-boundary`, `external-blocker`, `session-limit`, `cli-handoff`, or `plan-clear-no-safe-next`.
- `Return contract`: files to update when the CLI session finishes, including `.squad/orchestration-log/`, `.squad/decisions/inbox/`, and active `.kilo` plan status.

## Validation

Before declaring the handoff ready:

1. Confirm the active `.kilo` plan still has an in-scope open task or explicit safe next action.
2. Confirm no secret value is present in the packet.
3. Confirm the rollback snapshot exists.
4. Confirm all command examples are non-destructive by default.
5. End with `Facts / Decisions / Open / Next`.
