# Work Routing

How to decide who handles what.

## Routing Table

| Work Type                    | Route To | Examples                                           |
| ---------------------------- | -------- | -------------------------------------------------- |
| Architecture / System Design | Morpheus | module boundaries, interfaces, system trade-offs   |
| Code Implementation          | Trinity  | features, bug fixes, refactors, scaffolding        |
| Frontend / UX Design         | Switch   | flows, UI states, interaction design               |
| Frontend Implementation      | Dozer    | api adapter, interface sync, UI state wiring       |
| Testing / QA                 | Tank     | unit tests, regression checks, smoke tests         |
| Data Work                    | Oracle   | sample data, goldsets, labels, eval analysis       |
| Code Review                  | Morpheus | PRs, audits, post-rejection reassignment decisions |
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
17. **Disable generic peer peek by default.** Under heartbeat-first supervision, read-only peek is off for single-owner runs.
18. **Use co-work interface for shared tasks.** When 2+ agents are assigned to one task, Coordinator may open structured co-work exchange (`request`, `constraints`, `handoff_artifacts`, `done_criteria`) without ownership takeover.
19. **Clean superseded processes after rerun decision.** If a stale run is rejected and a rerun is active, Coordinator must terminate only superseded processes from the rejected run to prevent resource contention.
20. **Protect canonical runner.** Cleanup operations must preserve the designated canonical runner and verify by PID/command-line after cleanup.
21. **Ghost-running is hard-fail.** If an agent is marked `running` but no matching owner process exists and no artifact heartbeat updates for 2 patrol cycles (~10s), classify as `ghost-running` immediately.
22. **Ghost-running bypasses adaptive wait windows.** For ghost-running, skip long-goal L2/L3 waiting and jump directly to `stale-cleanup + relaunch decision`.
23. **Heartbeat SLA for long runs.** Owner agent must publish heartbeat every 25s with `task_id`, `owner`, `phase`, `last_checkpoint`, `next_milestone`, `updated_at`.
24. **Unified heartbeat schema is mandatory.** Heartbeat records must use the same keys and status vocabulary across all agents: `running`, `weak-heartbeat`, `heartbeat-miss`, `blocked`, `done`.
25. **Weak-heartbeat threshold.** If heartbeat gap exceeds 40s and artifact/log progress is flat for 2 patrol cycles, mark `weak-heartbeat` and trigger a single peer nudge.
26. **Heartbeat-miss threshold.** If heartbeat gap reaches 75s with no progress markers, mark `heartbeat-miss` and escalate to consult (or stale-cleanup if hard-fail signals coexist).
27. **Nudge throttle.** For the same run, allow at most one nudge per 60s window and at most two consecutive nudges before mandatory consult.
28. **Coordinator active heartbeat polling.** Heartbeat reporting is pull-based: Coordinator asks for heartbeat on patrol windows instead of waiting for ad-hoc agent broadcasts.
29. **Ordered heartbeat reporting.** For multi-agent shared tasks, emit one serialized heartbeat summary using order `owner -> Tank -> Oracle/Switch -> Trinity -> Ralph -> Morpheus -> Scribe`.
30. **No broadcast storm.** Agents should avoid unsolicited heartbeat chatter; unsolicited messages are reserved for `blocked`, `heartbeat-miss`, `done`, or hard-fail evidence.
31. **Quiet-window cadence control.** If no status/checkpoint change is observed for 3 consecutive poll windows, user-facing heartbeat summaries should be downshifted to 60s cadence.
32. **Wake-up on meaningful change.** Any checkpoint advance or state transition (`weak-heartbeat`, `heartbeat-miss`, `blocked`, `done`) must immediately restore 25s summary cadence.
33. **Collaboration visibility artifact (required).** For any multi-agent shared task, Coordinator/Scribe must append ordered summaries to `output/squad_collab_timeline.jsonl` so collaboration is observable outside chat.
34. **Usage Q&A is non-interruptive by default.** If active background work exists, Coordinator should answer user usage/how-to questions directly while keeping active tasks running.
35. **Stop requires explicit user intent.** Active task loops may stop only on explicit user commands such as `stop`, `pause`, `idle`, or equivalent clear instruction.
36. **Reviewer rejection reassignment is Morpheus-audited.** When Tank (or any reviewer) rejects an artifact, Morpheus audits lockout compliance and selects the revision owner; Coordinator then executes the reassignment per Morpheus decision.
37. **Non-Morpheus reassignment audit.** If a revision task is reassigned without Morpheus review, Morpheus must immediately audit the decision and either approve or cancel the task before execution continues.
38. **Backend change triggers frontend parallel lane.** If Trinity modifies or adds backend endpoints/contracts, spawn Dozer in parallel to update existing frontend service functions/interfaces, and spawn Switch for state/UX expression review.

### Unified Heartbeat Record (Required)

Every long-running task heartbeat should be emitted as one normalized record containing:

- `task_id`: stable task identifier
- `owner`: owner agent name
- `status`: one of `running|weak-heartbeat|heartbeat-miss|blocked|done`
- `phase`: current phase label
- `last_checkpoint`: latest concrete checkpoint marker
- `next_milestone`: next expected milestone
- `updated_at`: ISO8601 timestamp
- `artifact_ref`: primary artifact/log path (or `none`)

## Supervision Order (Serialized)

For the same long-running target task, supervision must be serialized:

1. **Nudge (single peer)** — one concise unblock suggestion from exactly one peer agent.
2. **Co-work-sync (multi-agent task only)** — one structured collaboration exchange using the co-work interface fields.
3. **Consult (multi-agent)** — only after failed nudge/co-work-sync, gather 2-agent verdict.
4. **Stale-cleanup + relaunch decision** — kill only superseded processes, protect canonical runner.

`weak-heartbeat` should enter step 1 directly (nudge) even if L2 time window is not yet reached.

`heartbeat-miss` should enter step 3 directly (consult), unless hard-fail signals require immediate step 4.

If `ghost-running` is detected, jump from current step directly to step 4.

Never run step 1-3 concurrently for the same target run.

Heartbeat check is performed as a serialized pre-step by Coordinator (poll owner first, then applicable peers), and then supervision steps proceed based on the ordered summary.

During quiet-window mode, supervision evaluation still runs on patrol cadence; only user-facing summary frequency is downshifted.

For multi-agent tasks, each ordered heartbeat summary should include: `task_id`, `window_id`, `participants`, `order`, `status`, `checkpoint`, `updated_at`, `decision`.

## Per-Agent Supervision Functions

- **Coordinator (Squad):** owns supervision token, enforces step order, announces state transitions.
- **Ralph:** watchdog/queue monitor; detects orphaned or ghost-running tasks and opens supervision tickets to Coordinator (no ownership takeover).
- **Tank:** first-line heartbeat plausibility check and retry acceptance line.
- **Oracle:** data/eval co-work sync for artifact heartbeat and metric append health.
- **Switch:** frontend-flow co-work sync for state transitions and UX heartbeat.
- **Trinity:** owner-runner diagnostics and minimal recovery command path.
- **Morpheus:** arbitration only when architecture/hard-stop boundary is crossed.
- **Scribe:** append supervision timeline and evidence (who/when/what verdict).
