---
description: "Anti-interruption discipline for long tasks. Prevents habitual segmentation — after answering a question, continue executing if the task is not closed. Defines stop gate, anti-pattern table, and self-check protocol."
---

# Long-Task Continuation

> Anti-interruption discipline. Prevents habitual segmentation during multi-step work.
> Canonical rule lives in CLAUDE.md §不中断规则（始终生效）。This skill provides
> the detailed protocol for explicit loading or self-reminder.

## Core Rule

After answering a status/interruption question, if the current task is NOT closed,
continue executing immediately. Do NOT wait for user input.

## Stop Gate (4 conditions — must hit at least one)

1. User explicitly says `stop`, `pause`, or `idle`
2. Red-line / hard-stop requires independent user authorization
3. Current slice fully closed: artifact written + verification run (or explicitly bypassed with reason) + concrete next action selected
4. Environment/tooling failed and smallest safe recovery action already reported

## What Does NOT Count as Completion

- Diagnostic explanation of why work paused
- Status summary of what was done so far
- Cause analysis of a failure or blocker

If you explain why work paused, you must resume execution in the same turn.

## Anti-Pattern Recognition

Watch for these habits that trigger unnecessary interruption:

| Anti-Pattern | Trigger | Fix |
|---|---|---|
| Tool error → pause | Write/Edit tool fails | Retry with alternative (Bash, different approach), then continue |
| Verification → pause | Ran a check, got result | Immediately proceed to next step based on result |
| "Phase complete" → pause | Finished creating files | Continue to reference fixes, verification, memory update |
| Multi-round task → pause | Completed one sub-step | Continue to next sub-step without stopping |
| Explaining what you did → pause | Gave a summary | Summary is output, not a stop signal — keep going |

## Self-Check Before Ending Turn

Before ending any turn, ask:

1. Is there a next action selected? → Continue
2. Is the current task fully closed (artifact + verification + next action)? → Only then stop
3. Did I just explain something? → Not a stop signal, continue

## Reference

- Copilot equivalent: `.squad/identity/long-run-prompt.md` §round loop
- Claude charter: `.claude_squad/charter.md` §Stop Gate
- Kernel protocol: `.claude_squad/kernel/long-running-protocol.md`
