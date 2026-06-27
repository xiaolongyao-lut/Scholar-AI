# Autonomous Execution Framework

Date: 2026-06-04

Rollback checkpoint for this framework file:

- `.rollback_snapshots/execution-framework-20260604-234200`

## Purpose

This framework defines how an agent decides what to do, how it proves the work, and when it must stop.

It does not contain the execution plan.

Concrete execution plans, queues, task slices, target files, test commands, mature-reference notes, and completion records belong in the active plan, functional matrix, or slice runbook under `docs/plans/`.

## What The Framework Does

The framework answers only stable operating questions:

- Which document is the queue entry point?
- Is a candidate task authorized local work?
- What preflight must happen before edits?
- How does the agent alternate between global product judgment and local code work?
- What evidence is required before a slice is done?
- What must be recorded after each slice?
- When is stopping valid?

The framework must not store:

- A concrete implementation queue.
- Per-slice target files.
- Per-slice test commands.
- Reference-project code-path notes.
- Temporary status summaries.
- "Next slice" decisions that belong to a plan-level audit.

## Source Order

When documents disagree, use this order:

1. Latest explicit user instruction.
2. `AI_WORKSPACE_GUIDE.md`.
3. This execution framework.
4. `docs/plans/autonomous-execution-planning-playbook.md`.
5. Current active plan, functional matrix, or slice runbook.
6. Current code and test evidence.
7. Historical plans and reference notes.

Historical plans are audit trail unless the current active plan explicitly re-authorizes them.

## Queue Entry Rule

Before implementation, identify the active queue entry:

- If the user names a plan, use that plan as the active queue.
- If the user names the functional matrix, use `docs/plans/2026-05-26-functional-acceptance-matrix.md`.
- If the user asks to continue without naming a plan, inspect `docs/plans/active/`, the functional matrix, and the latest relevant runbook, then record which one is active before editing.
- If multiple plans conflict, perform a Plan-Level Queue Audit and record the boundary judgment in the active plan or matrix before implementing.

Do not treat a completed overlay plan as completion of the whole product.

Do not treat P2/P3, parking-lot, approval-only, deployment, publishing, notification, IM, remote-control, or release tasks as automatic authorized local work.

## Authorization Test

A task is authorized local work only if all conditions are true:

- It is named by the active plan or queue.
- It is not already done by row-level or slice-level evidence.
- It directly supports the current product workflow or is a necessary enabler.
- It can be completed locally without production access, paid access, publishing, push, tags, release upload, destructive filesystem work, or new credentials.
- It does not overwrite unrelated dirty worktree changes.
- It has a feasible rollback point and verification path.

If any condition fails, classify it as one of:

- `done`
- `blocked`
- `deferred`
- `parking lot`
- `approval-only`
- `outside current plan boundary`

Only `authorized local work` can proceed to implementation.

## Operating Loop

Every slice follows the same state machine:

1. **Audit**
   - Read `AI_WORKSPACE_GUIDE.md`.
   - Read this framework.
   - Read `docs/plans/autonomous-execution-planning-playbook.md`.
   - Read the active plan, matrix, or runbook.
   - Run `git status --short --branch`.
   - Classify remaining tasks at plan level.

2. **Select**
   - Pick the highest-value authorized local slice.
   - Run a global fit check: product center, locality, dependency value, opportunity cost, approval boundary.
   - If no authorized local slice remains, write a stop audit and stop.

3. **Plan**
   - Write or update the execution plan in `docs/plans/`.
   - The plan records the concrete goal, target files, non-goals, tests, rollback, mature references, and next audit point.
   - Do not expand this framework with per-slice details.

4. **Prepare**
   - Create a rollback checkpoint for target files and plan files.
   - Search official or mature references for the selected slice.
   - Deep-read only the most relevant reference project paths needed for design evidence.
   - Inspect target-file diffs before editing.

5. **Implement**
   - Change only files needed for the selected slice.
   - Preserve compatibility unless the active plan explicitly authorizes a breaking change.
   - Do not modify `github/`.
   - Do not stage, commit, push, tag, release, deploy, package, or publish unless explicitly authorized.

6. **Verify**
   - Run the smallest meaningful checks first.
   - Escalate to build, browser smoke, or real AI/API smoke only when the slice needs it and the active plan allows it.
   - Record skipped verification with the exact reason.

7. **Record**
   - Update the active plan, matrix, or runbook with:
     - rollback checkpoint
     - mature/official references checked
     - reference-project evidence
     - changed files
     - verification commands and results
     - residual risk
     - next Plan-Level Stop Audit

8. **Continue Or Stop**
   - Run a Plan-Level Stop Audit.
   - If authorized local work remains, continue with the next slice.
   - If none remains, stop with a stop reason that classifies all remaining work.

## Plan-Level Stop Audit

Stopping is valid only after the active queue is audited.

The audit must answer:

- What active queue was used?
- Which rows or slices remain?
- Which are done?
- Which are blocked?
- Which are deferred?
- Which are parking lot?
- Which are approval-only?
- Which are outside the current plan boundary?
- Is any authorized local work still present?

If authorized local work remains, stopping is invalid.

If only P2/P3 or parking-lot work remains, do not invent a new local slice. Record that the next implementation needs explicit reprioritization or a new active plan.

## Mature Reference Rule

Mature references are checked per slice, not once for the entire project.

Use the smallest relevant set:

- Official framework/API documentation for the changed surface.
- Maintained upstream examples when behavior is framework-specific.
- ADR-style decision structure for durable architecture choices.
- SRE-style canary, smoke, rollback, and observability patterns for risky runtime changes.
- Requirements traceability and MoSCoW-style prioritization for queue and matrix decisions.

Reference studies go under `docs/plans/reference-*-study-YYYY-MM-DD.md` or the slice runbook. This framework only records the reference rule.

## Command Handoff Rule

When giving another agent or user execution instructions, include:

- Read `AI_WORKSPACE_GUIDE.md`.
- Read this framework.
- Read `docs/plans/autonomous-execution-planning-playbook.md`.
- Read the active plan or matrix.
- Run `git status --short --branch`.
- Create a rollback checkpoint before nontrivial edits.
- Search official or mature references for the selected slice.
- Record implementation, verification, residual risk, and next stop audit in `docs/plans/`.

Do not give a command prompt that starts directly with implementation.

## Stop Boundaries

Stop instead of implementing when the next action requires:

- Production access.
- Paid access not already authorized by the active plan.
- New credentials or editing real credentials.
- Git push, tag, release, upload, deployment, packaging, or publishing.
- Notification, IM, remote-control, or external automation unless explicitly authorized.
- Destructive filesystem operations without a verified rollback path.
- A product direction decision that is not already reducible to a local mini-plan.
- Work in `github/` reference repositories.

## Framework Maintenance

Update this framework only when the operating model changes.

Do not update this framework for:

- Completing a slice.
- Choosing the next slice.
- Recording test output.
- Listing changed files.
- Capturing temporary risks.

Those belong in the active plan, matrix, or runbook.

## Mature References Checked For This Framework

- Google SRE release and rollback practices: canary, monitoring, rollback, and small-batch verification.
- Architecture Decision Records: context, decision, and consequence separation.
- Requirements traceability matrix practice: requirements, implementation evidence, and verification remain linked.
- Agile Business Consortium MoSCoW prioritization: must/should/could/won't distinctions map to authorized, deferred, and parking-lot categories.
- DACI / decision-rights style frameworks: distinguish decision owner, contributors, and execution responsibility.
