---
mode: agent
description: Inject this when starting a long-running task (multi-step refactor, Squad fan-out, evaluation run, batch ingest) on a flaky third-party LLM connection. Forces durable checkpoints so a session crash or proxy drop is recoverable.
---

# Long-Task Checkpoint Discipline

You are about to execute a task that is expected to take more than ~10 minutes wall-clock or more than ~5 substantive steps. The transport (third-party Claude / Copilot proxy) is known to drop connections. Without checkpoints, a single drop forces a full restart and wastes user budget.

## Hard rules

1. **Every checkpoint is a file write.** Chat scrollback is not memory. If it is not on disk, it does not survive a reconnect.
2. **Checkpoint path:** `.squad/orchestration-log/<task-slug>-<UTC-timestamp>.md` (or `.squad/decisions/inbox/copilot-<task-slug>.md` if it represents a decision needing team visibility).
3. **Cadence:** write a checkpoint after each completed step, or at most every ~5 minutes of work — whichever comes first.
4. **No two-step "I'll save it later" promises.** Save first, then move on.

## Checkpoint template (Facts / Decisions / Open / Next)

```markdown
# <task slug> — checkpoint <UTC ISO>

## Facts
- Concrete observed state: file paths touched, commands run, exit codes, test counts.
- Each fact has a citation: a file:line, a command output excerpt, or a tool result ID.

## Decisions
- Choices made this slice. Include the rejected alternatives in one line each.
- Mark each decision as `self-decided` (within authorized envelope) or `pending-user`.

## Open
- Blockers, ambiguities, unverified assumptions.
- Anything that would force a stop if it cannot be self-decided.

## Next
- The single safe next action. Must be concrete enough that a fresh agent could resume from this file alone.
- Include the exact next command or file edit.
```

## Resume protocol

When a session resumes (new chat, after a crash, or after the user says "continue"):

1. List the most recent 3 files under `.squad/orchestration-log/` matching the task slug.
2. Read the latest one fully.
3. Re-state the `Next` action and execute it. Do not re-derive the plan.

## Anti-patterns

- ❌ Holding a 10-step plan only in chat history.
- ❌ Writing a single end-of-run summary instead of incremental checkpoints.
- ❌ Vague checkpoints ("worked on retries") — cite file:line and outcome.
- ❌ Marking the task complete before the checkpoint trail shows the last `Next` was actually executed and verified.

## Related

- `.github/skills/third-party-llm-resilience/SKILL.md` — why the transport drops in the first place.
- `.github/skills/memory-palace-lite/SKILL.md` — multi-session decision retention.
- Repo HR1–HR6 long-run hard rules in `CLAUDE.md` — same spirit, broader scope.
