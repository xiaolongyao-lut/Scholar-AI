# Night Shift Policy

## Purpose

Allow the squad to continue useful work while the user is asleep, without stalling on every ambiguity and without crossing high-risk boundaries.

## Default Night Shift Mode

Night shift is allowed to continue with low-risk and medium-confidence work. The squad should prefer momentum, but not uncontrolled structural change.

## Allowed To Continue Automatically

These task types may continue overnight:

- issue triage and routing
- requirement collection into the requirement pool
- requirement scoring and prioritization suggestions
- bug reproduction and test expansion
- test scenario authoring
- support data preparation
- documentation updates
- frontend flow refinement inside the current design style
- backend feature implementation that stays within the current code style and architecture
- retrieval / extraction / chat improvements that do not require refactor or product-direction change
- safe follow-up tasks unlocked by earlier completed work

## Must Pause For Morpheus Approval

These task types must stop or be parked for review:

- any refactor (must wait for Morpheus approval)
- redesigns that change the frontend style system
- backend structural rewrites or architecture shifts
- any new external dependency
- any schema or storage model change
- product direction changes beyond the current phase
- requirements with unclear value or scope that Morpheus cannot score confidently

## Continue Automatically (Explicitly Allowed)

These remain auto-continuable overnight:

- ordinary bugfix
- test writing / test expansion
- data preparation

## Requirement Pool Rule

If a new idea appears overnight, do not block progress immediately.

1. First check bypass eligibility using `.squad/identity/requirement-pool.md`.
2. If bypass-eligible, execute directly and include it in the morning report.
3. If not bypass-eligible, add it to `.squad/identity/requirement-pool.md`.
4. Score it using `.squad/identity/requirement-scoring.md`.
5. If Morpheus can judge it confidently, mark the recommendation.
6. If confidence is low or product intent is unclear, mark it as `WAITING FOR USER` and continue other work.

All code-related technical judgment belongs to Morpheus. Other members should not self-approve code-level uncertainty. Morpheus should judge by combining current project requirements and historical plans/documents.

## Ralph Night Patrol

During night shift, Ralph should:

1. check open issues, draft PRs, review feedback, and queued work
2. route low-risk work immediately
3. push new feature ideas into the requirement pool instead of stopping the whole queue
4. allow direct execution for bypass-eligible items
5. escalate only when a task crosses the pause boundary above
6. keep the board moving until no safe work remains

## Morning Report

When the user returns, the team should summarize:

- what was completed
- what was queued into the requirement pool
- what was scored high / medium / low
- what is waiting for user decision
- what was blocked and why
- when the team started and stopped overnight
- total team working window (duration)

## Stop-Time and Team Work Window

For every overnight run, include a clear stop-time record.

1. Prefer runtime/log event timestamps as primary evidence.
2. Use checkpoint naming time (for example `checkpoint-...-YYYYMMDD-HHMM`) as secondary evidence.
3. If only secondary evidence is available, mark the stop time as "estimated".
4. Always report both:
   - `Team Work Window` (start → stop)
   - `Team Working Time` (duration)

## Output Format

Use this shape for overnight summary:

- **Completed:** ...
- **Queued Requirements:** ...
- **High-Score Candidates:** ...
- **Waiting for User:** ...
- **Blocked / Escalated:** ...
- **Team Work Window:** {start_time} → {stop_time}
- **Team Working Time:** {duration}
- **Stop-Time Evidence:** {log/checkpoint/path}

## Escalation Conditions

Escalate immediately when:

- refactor is requested (requires Morpheus)
- schema change is requested
- new dependency is requested
- safe style boundary would be crossed
- algorithm reliability would be weakened for speed
- a requirement could cause major phase drift
- rollback path is unclear for a risky change

## Audit Trail Requirements

All overnight work must create an audit trail so that morning report and future audits can answer: **who did what, when, why, and with what result?**

Recording obligations:

1. **Every policy boundary crossing** (allowed → blocked)
   - Log the decision point: what was attempted, why it was rejected
   - Reference the specific rule in `night-shift-policy.md` that triggered the boundary
   - Example: "Attempted to execute async refactor; stopped at `night-shift-policy.md#Must Pause For Morpheus Approval` (no refactor overnight)"

2. **Every requirement pool decision**
   - Bypass-eligible item executed? Log it to `orchestration-log` with evidence
   - Item scored and queued? Log score, recommendation, reason
   - Item escalated to WAITING FOR MORPHEUS? Log reason + evidence

3. **Every major state change or checkpoint**
   - Checkpoint created (time, backup location, scope)
   - Work paused or resumed (why, what triggered it)
   - Issue discovered and escalated (what, severity, next steps)
   - Stale process cleanup executed (killed PIDs, protected canonical PID, verification output path)

4. **Stop-time evidence** (per `#Stop-Time and Team Work Window`)
   - Log timestamp of shift end (primary evidence: orchestration-log entry)
   - Link to checkpoint created at shift end
   - For morning report: "Team Work Window: {start} → {stop}, Duration: {total time}"

### Recording Format

- **Primary location:** `.squad/orchestration-log/` (one file per night: `{YYYYMMDD}_{run_id}.log`)
- **Primary format:** JSONL (machine-parseable) + Markdown sections (human-readable)
- **Schema reference:** `.squad/orchestration-log/SCHEMA.md`
- **Example:** `.squad/orchestration-log/SAMPLE_NIGHT_SHIFT_RUN.md`

See `.squad/orchestration-log/README.md` for full recording framework.

---

## Record Keeper Responsibility

Ralph and the night duty owner must maintain the orchestration-log entry for the shift.

### Before Shift Starts

1. Create session ID: `nightly_{YYYYMMDD}_{HHMM}` (e.g., `nightly_20260420_2200`)
2. Create opening checkpoint and log entry (timestamp shift start)
3. Prepare orchestration-log file for the night (header with session_id, start time, team members)

### During the Shift

Ralph (or rotating duty owner) records:
- Every decision to execute or escalate a requirement (with policy reference)
- Every checkpoint created (time, scope, backup path)
- Every major policy boundary crossing (with reason)
- Every block or escalation (with justification)

**Quick logging template:**
- Timestamp (ISO 8601)
- Action (what was decided/executed/blocked)
- Policy reference (which rule applied)
- Evidence (file/log path)
- Result (pass/fail/blocked/queued/completed)

Example quick entry:
```
2026-04-20T23:30:54Z | ralph | issue_escalated | night-shift-policy.md#Must Pause For Morpheus Approval | .squad/identity/requirement-pool.md#Entry-chunk-context-metadata | blocked
```

### At Shift End

1. Record final checkpoint and shift stop-time (with timestamp)
2. Summarize: completed count, queued count, escalated count, policy violations (should be 0)
3. Commit orchestration-log to `.squad/orchestration-log/{date}_{run_id}.log`
4. Prepare morning-report summary (citing orchestration-log entries as evidence)

### Audit Trail Integrity

- All entries must include a timestamp (precision: ±5 min tolerance for clock skew)
- All entries must include policy_ref (shows which rule was applied)
- No entries should be deleted; if a correction is needed, add a new entry with reference to original
- Morning report must cite orchestration-log paths as evidence for every claim
