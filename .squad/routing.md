# Work Routing

How to decide who handles what.

## Routing Table

| Work Type                    | Route To | Examples                                           |
| ---------------------------- | -------- | -------------------------------------------------- |
| Architecture / System Design | Morpheus | module boundaries, interfaces, system trade-offs   |
| Code Implementation          | Trinity  | features, bug fixes, refactors, scaffolding        |
| Frontend / UX Design         | Switch   | flows, UI states, interaction design               |
| Testing / QA                 | Tank     | unit tests, regression checks, smoke tests         |
| Data Work                    | Oracle   | sample data, goldsets, labels, eval analysis       |
| Code Review                  | Morpheus | review PRs, quality checks, design consistency     |
| Frontend State Mapping       | Switch   | retrieval states, filters, chat surfaces           |
| Testing                      | Tank     | edge cases, test coverage, verification            |
| Scope & Priorities           | Morpheus | planning, sequencing, trade-offs                   |
| Session Logging              | Scribe   | automatic logging only                             |

## Issue Routing

| Label          | Action                                               | Who          |
| -------------- | ---------------------------------------------------- | ------------ |
| `squad`        | Triage issue and assign `squad:{member}`             | Morpheus     |
| `squad:{name}` | Pick up issue and complete the work                  | Named member |

### How Issue Assignment Works

1. When a GitHub issue gets the `squad` label, **Morpheus** triages it — analyzing content, assigning the right `squad:{member}` label, and commenting with triage notes.
2. When a `squad:{member}` label is applied, that member picks up the issue in their next session.
3. Members can reassign by removing their label and adding another member's label.
4. The `squad` label is the "inbox" — untriaged issues waiting for Morpheus review.

## Rules

1. **Eager by default** — spawn all agents who could usefully start work, including anticipatory downstream work.
2. **Scribe always runs** after substantial work, always as `mode: "background"`. Never blocks.
3. **Quick facts → coordinator answers directly.** Don't spawn an agent for "what port does the server run on?"
4. **When two agents could handle it**, pick the one whose domain is the primary concern.
5. **"Team, ..." → fan-out.** Spawn all relevant agents in parallel as `mode: "background"`.
6. **Anticipate downstream work.** If a feature is being built, spawn the tester to write test cases from requirements simultaneously.
7. **Issue-labeled work** — when a `squad:{member}` label is applied to an issue, route to that member. Morpheus handles all `squad` (base label) triage.
8. **Architecture-first review.** Cross-module work, schema changes, and tooling changes should be reviewed by Morpheus before merge.
9. **Data tasks route to Oracle early.** When a task needs synthetic data, goldsets, labels, or evaluation baselines, involve Oracle at the start instead of after coding is done.
10. **Feature-driven UI.** UI work should route to Switch when the task depends on expressing backend retrieval logic, algorithm outputs, confidence, ranking, or multi-step user flows.
11. **Coordinator patrol is mandatory.** While background agents are active, inspect task activity every 5 seconds; if no real artifact/log progress appears, start immediate review and escalate via L1/L2/L3 stale ladder.
12. **Long-goal tasks use adaptive windows.** For canonical full eval / large-batch sweeps, widen stale thresholds (L2: 3-5 min, L3: 8-12 min) and judge by heartbeat + partial progress, not short silence alone.
13. **Stall requires multi-agent consult before kill.** If a run crosses L2 without progress, Coordinator should ask at least two relevant agents whether to continue, co-work, or handoff before terminating the runner.
14. **Coordinator is not architecture authority.** When a block crosses hard-stop boundaries (refactor/schema/new dependency), escalate to Morpheus and mark `WAITING FOR MORPHEUS`.
15. **Requirement-pool gate before dispatch.** For non-bypass requirements, Coordinator must auto-route to Morpheus for requirement judgment before assigning implementation.
16. **Execution only after judgment.** Only Morpheus-judged `DO NOW` items can be fanned out to Trinity/Tank/Oracle/Switch; all other recommendations stay queued or waiting.
17. **Enable peer peek on long runs.** Coordinator may assign read-only "peek" checks to non-owner agents to verify milestone progress and heartbeat.
18. **Enable peer nudge before takeover.** Coordinator should try at least one peer "nudge" (concise unblock suggestion) before hard reroute/kill, unless explicit crash/fatal error is present.
19. **Clean superseded processes after rerun decision.** If a stale run is rejected and a rerun is active, Coordinator must terminate only superseded processes from the rejected run to prevent resource contention.
20. **Protect canonical runner.** Cleanup operations must preserve the designated canonical runner and verify by PID/command-line after cleanup.
21. **Ghost-running is hard-fail.** If an agent is marked `running` but no matching owner process exists and no artifact heartbeat updates for 2 patrol cycles (~10s), classify as `ghost-running` immediately.
22. **Ghost-running bypasses adaptive wait windows.** For ghost-running, skip long-goal L2/L3 waiting and jump directly to `stale-cleanup + relaunch decision`.

## Supervision Order (Serialized)

For the same long-running target task, supervision must be serialized:

1. **Peek (Tank first)** — verify checkpoint/heartbeat plausibility and test-risk surface.
2. **Peek (Oracle second, for data/eval tasks; Switch second, for UI tasks)** — verify artifact/metrics/state progression.
3. **Nudge (single peer)** — one concise unblock suggestion from exactly one peer agent.
4. **Consult (multi-agent)** — only after failed nudge, gather 2-agent verdict.
5. **Stale-cleanup + relaunch decision** — kill only superseded processes, protect canonical runner.

If `ghost-running` is detected, jump from current step directly to step 5.

Never run step 1-4 concurrently for the same target run.

## Per-Agent Supervision Functions

- **Coordinator (Squad):** owns supervision token, enforces step order, announces state transitions.
- **Ralph:** watchdog/queue monitor; detects orphaned or ghost-running tasks and opens supervision tickets to Coordinator (no ownership takeover).
- **Tank:** first-line peek for stale suspicion, defines retry acceptance line.
- **Oracle:** second-line peek for data/eval artifact heartbeat and metric append health.
- **Switch:** second-line peek for frontend-flow tasks (state transitions, UX heartbeat).
- **Trinity:** owner-runner diagnostics and minimal recovery command path.
- **Morpheus:** arbitration only when architecture/hard-stop boundary is crossed.
- **Scribe:** append supervision timeline and evidence (who/when/what verdict).
