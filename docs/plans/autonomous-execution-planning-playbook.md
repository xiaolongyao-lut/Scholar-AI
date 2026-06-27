# Autonomous Execution Planning Playbook

> This document records the planning method, not a history of one plan. Use it when preparing Claude, Codex, or another coding agent to keep working while the user is away.

Read `docs/plans/autonomous-execution-framework.md` before this playbook. The framework defines the stable execution state machine and boundary rules. This playbook explains how to write a concrete plan, but the concrete queue, slice list, target files, verification commands, and completion records must stay in the active plan, functional matrix, or runbook.

## Goal

The goal of an unattended engineering plan is to maximize useful code completed during idle time without turning the agent into an unbounded rewrite machine. A good plan lets the agent continue through multiple safe slices, test each slice seriously, and stop only at real risk boundaries.

The plan should answer:

- What may the agent do without asking again?
- What should it do next after each slice passes?
- What tests prove the work is good enough?
- What must never be done without explicit user approval?
- What should the agent do when the plan is incomplete?

## Core Principle

Do not write a plan that says "finish this and wait." Write a plan that says "finish this, verify it, record the result, then continue to the next authorized slice."

The agent should stop only when continuing would require an irreversible external action, new secrets, production or paid access, destructive file or git operations, or a product decision that cannot be narrowed into a safe mini-plan. Codex / Claude review feedback is not a stop condition by itself: convert each finding into a local fix slice, add or update regression tests, verify, commit locally when appropriate, update the runbook, and continue unless the finding crosses one of the explicit approval boundaries below.

## Global / Local Alternation

Long-running execution must alternate between product-level judgment and code-level focus. Do not treat the next listed queue item as automatically worth doing.

Before starting each slice, run a global fit check:

- Product center: does this slice directly strengthen the current product's core user workflow?
- Locality: can it be completed as local code/docs/tests without credentials, publishing, deployment, or production access?
- Dependency: is it a real prerequisite for a later core workflow, or only a possible future surface?
- Opportunity cost: would doing it delay a more central local slice?
- Stop boundary: is it better recorded as deferred, optional, or explicit-approval-only?

Then switch to local execution only if the global fit check passes. After verification, zoom out again before selecting the next slice.

Use these queue categories:

- Core path: authorized local work that directly improves the main product workflow.
- Enabler: local infrastructure required by one or more core-path slices.
- Maintenance: small local fixes discovered while verifying the active slice.
- Parking lot: optional future surfaces, external integrations, deployment, publishing, remote control, notifications, or broad product directions. Parking-lot items are not next steps unless the user explicitly asks.

## Living Memory Rule

Treat this playbook as canonical project memory for unattended planning and execution. It must improve when repeated failures, better verification patterns, safer rollback methods, or mature external practices reveal an upgrade.

Required behavior:

- Before long-running, unattended, multi-slice, or handoff work, read this playbook and apply it explicitly in the active plan.
- If a reusable lesson is discovered while planning or executing, update this playbook in the same slice when the improvement is clear and low risk.
- If the improvement is real but not safe to edit immediately, record an exact proposed playbook upgrade in the active plan or runbook under a "Playbook upgrade proposal" note.
- Keep one canonical plan under `docs/plans/`. Remove stale duplicate plan copies after the canonical file is updated, with a rollback snapshot first.
- Do not let project-specific one-off details accumulate here. Put one-off facts in the active plan or runbook; put durable process rules here.
- After context compaction, interruption, or a new agent handoff, recover from
  authoritative project records before acting. Read the active plan/index,
  latest handoff or continuation packet, latest matching
  `docs/plans/longrun-goal-state-*.json` file, changed files, and current git
  status; then compare the recovered state to the original user goal before
  selecting work.
- Treat compacted summaries, continuation packets, and goal-state files as
  recovery evidence, not as a replacement for the current conversation turn.
  If a recovered `newest_user_request`, next action, or objective conflicts
  with a visible user message in the active thread, the visible user message
  wins. Before stopping or producing a handoff-only answer after resume, state
  the active user objective in one sentence and verify it still asks for a
  handoff rather than continued execution.

## Preflight Discipline

Every nontrivial plan must start with local evidence and a rollback path.

Required preflight:

- Read `AI_WORKSPACE_GUIDE.md`.
- Inspect `git status --short`.
- Create a rollback checkpoint or targeted snapshot.
- Identify the current workspace identity from the most current local records
  before naming the project/product in plans or reports. Prefer current
  `README.md`, active runbooks, and launcher/window metadata when applicable
  over package names, stale plans, or historical release artifacts. If they
  differ, record the distinction explicitly, such as `current name`, `UI name`,
  `internal paths`, and `historical names`.
- Read the current active plan, relevant code, and tests.
- Verify every plan-specific code anchor against the current tree; rewrite stale helper names to the real call site or call chain before handing the plan off.
- Check official or mature references before security, packaging, API, UI framework, storage, or architecture decisions.

Useful reference types:

- Official docs for the framework or API.
- Maintained upstream examples.
- ADR-style decision records for non-obvious choices.
- SRE-style rollout, smoke, and rollback patterns.
- Mature refactoring patterns such as branch-by-abstraction, strangler-style replacement, and characterization tests.

## Knowledge Runtime Integration Gate

Use this gate when a slice adds, edits, or relies on durable Scholar AI
knowledge assets, including discourse habits, move/frame rules, official
examples, prompt corpora, translation rules, citation heuristics, ontology
notes, or agent-facing reference material.

Do not count "a document exists" as "knowledge is integrated." The completion
claim must prove the full chain:

```text
authoritative source -> builder/loader -> structured runtime artifact ->
manifest/provenance record -> runtime/retrieval caller -> focused tests
```

Requirements:

- Identify the authoritative source file before editing runtime constants,
  generated artifacts, JSON databases, prompts, or skill references.
- Prefer the authoritative source as the single source of truth. If legacy
  hardcoded data remains, wrap it as a compatibility adapter and test that it
  cannot drift silently from the source schema.
- Generated artifacts and manifests should record provenance such as
  `source_path`, `loaded`, `content_hash`, and build/update time when practical.
- Tests must verify that representative source content appears in the runtime
  artifact and that changing the source changes the artifact or content hash.
- Missing, unreadable, or schema-invalid source files must leave an observable
  warning, manifest status, integrity-gate failure, or blocked action. Silent
  fallback to stale hardcoded knowledge is not acceptable.
- Completion evidence must inspect the builder or loader path that runtime
  callers actually use. A `SKILL.md`, README, or plan reference is only
  human/agent discoverability evidence.
- Align parallel concept collections such as `MOVE_RULES`, discourse frames,
  Markdown sections, JSON schemas, database rows, and prompt snippets through
  one source schema or an explicitly tested migration/compatibility layer.
- For user-visible or agent-critical knowledge, add or preserve a debug/UI/API
  surface that shows loaded packages, source path, updated time, hash, and load
  status.

Mature reference boundary:

- W3C PROV-style provenance separates entities, activities, and agents; use
  that principle to distinguish source files, build/load steps, and runtime
  consumers. Reference: https://www.w3.org/TR/prov-overview/
- RO-Crate-style research object packaging keeps data and metadata together;
  use that principle for source-to-artifact manifests without copying any
  external implementation. Reference:
  https://www.researchobject.org/ro-crate/specification/1.1/introduction.html
- FAIR-style reuse depends on rich metadata and provenance; use that principle
  to reject undocumented or untraceable runtime knowledge. Reference:
  https://www.go-fair.org/fair-principles/

## Authorization Model

Separate "safe to do locally" from "requires user approval."

Allowed by default:

- Local code implementation.
- Local refactoring needed for the authorized goal.
- Test additions and test fixes.
- Local build, typecheck, smoke, and release-gate verification.
- Local commits with explicit staging.
- Documentation and plan updates.
- Real AI/API smoke tests using already configured credentials.
- Follow-up fixes from local code review, Codex review, Claude review, failed deterministic tests, failed build/typecheck, or failed local smoke tests.
- Mini-plan creation for any newly discovered local bug or test gap that fits the current slice's product surface.

Requires explicit approval:

- `git push`, tag creation, GitHub Release, artifact upload, or public publishing.
- Adding, editing, or pasting real credentials.
- Production, paid, or unconfigured external service access.
- Destructive git or filesystem operations.
- Deleting existing product behavior without a compatibility path.
- Starting a new product direction that is not a dependency or cleanup of the active slice and cannot be reduced to a local mini-plan.

## Execution Queue

Write a prioritized queue, not a single task.

Each queue item should include:

- Category: core path, enabler, maintenance, or parking lot.
- Purpose.
- Scope.
- Non-goals.
- Files or modules likely touched.
- Verification commands.
- Fallback if blocked.
- What to record after completion.

After a queue item passes, the agent should continue to the next item. If it is blocked, it should record the blocker and move to the next independent safe item.

## Default-Continue Rule

Unattended plans should bias toward execution, not confirmation loops.

When a plan contains proposed decisions, defaults, review questions, or "codex may challenge" notes:

- Treat documented defaults as pre-approved for local execution.
- Treat review questions as prompts for the next reviewer, not as mandatory user questions.
- If review feedback identifies a bug, implement the smallest local fix that preserves the active plan's intent.
- If review feedback identifies a test gap, add the regression test locally and continue.
- If review feedback identifies a design concern with two reasonable local options, choose the lower-risk option that preserves public compatibility and record the choice in the runbook.
- If a trigger condition is already satisfied by current evidence, execute the slice rather than asking for the trigger again.

Only pause when the next action needs explicit approval under the Authorization Model, or when all remaining independent local work is blocked.

## Stop Conditions

Stop conditions should be narrow. Broad stop conditions waste unattended time.

### Plan-Level Stop Audit

Before stopping after a slice passes, audit the active plan at the plan level,
not only the completed slice.

Required audit:

- List the remaining plan items or queue entries.
- Mark each remaining item as done, blocked, deferred, parking lot, approval-only, or authorized local work.
- If any authorized local work remains, select the next slice with the global fit check and continue.
- If the current slice is complete but the total plan still has authorized local work, do not write a stop boundary; write a slice completion record and a next-slice handoff.
- A valid stop reason must explain why every remaining independent item is blocked, deferred, parking lot, approval-only, or outside the current product boundary.

Do not infer total plan completion from local workflow coverage. A core-path
slice can be locally complete while the master plan still contains other
authorized local slices. The agent must switch back to the global queue before
stopping.

### Goal Completion Audit

For long user-provided goals, completion is a claim that must be proven against
the original request, not against the work that happened to be done.

Before declaring a long goal complete:

- Restate the original requirements without narrowing them.
- Write a one-sentence `current objective` from the latest user instruction and
  a separate `not the objective` line for tempting but narrower interpretations.
  If naming changed, include the current workspace identity before any status
  claim.
- Build a requirement-to-evidence matrix covering every explicit path, project,
  numbered goal, named artifact, command, test, boundary condition, and
  deliverable.
- Inspect authoritative current state for each row: files, command output,
  generated artifacts, runtime behavior, test results, or downloaded reference
  inventories.
- Classify each row as `proved`, `contradicted`, `incomplete`,
  `weak/indirect evidence`, or `missing evidence`.
- Treat weak or indirect evidence as incomplete unless a stronger check is
  impossible and the limitation is recorded.
- Record the exact row that justifies any request for more user input,
  downloads, credentials, or product judgment. Do not ask for new downloads when
  local requested material remains unread or unclassified.
- Only mark the goal complete when all rows are proved or explicitly out of
  scope by the user's latest instruction.
- For goals that span more than one slice, write or update a machine-readable
  goal-state record under `docs/plans/longrun-goal-state-YYYY-MM-DD.json`.
  Markdown tables are still useful for humans, but the JSON record is the
  recovery source for context compaction and handoff.

When using persistent goal tooling, do not call the goal complete until this
audit has been done. A partial slice, broad summary, green smoke, or
well-written report is not enough by itself.

### Machine-Readable Goal State

Use a goal-state JSON file when a user goal is long enough to cross context
compaction, multiple slices, reference-learning phases, or agent handoff.

Required top-level fields:

- `schema_version`: use `codex_longrun_goal_state_v1` until a newer schema is
  recorded.
- `updated_at`: ISO-like date or timestamp for choosing the newest matching
  record.
- `current_objective`: the latest full user goal, not the narrower active
  slice.
- `not_the_objective`: tempting but forbidden or already-rejected narrower
  interpretations.
- `workspace_identity`: current project/product name, UI name when relevant,
  internal paths, and historical names when relevant.
- `authoritative_records`: files the next agent must read before selecting
  work.
- `rollback`: checkpoint id/path and restore command, with restore gated behind
  explicit user intent.
- `mature_references_checked`: official or mature references used for process
  or implementation decisions.
- `requirements`: requirement-to-evidence rows. Each row must include `id`,
  `requirement`, `source`, `status`, `evidence`, and `residual_risk`.
- `changed_files_for_this_slice`: changed files and why they belong to the
  current slice.
- `next_authorized_local_actions`: ordered next safe local actions.
- `stop_boundary`: external-risk, approval, worktree, or product-decision
  boundaries.
- `completion_claim`: separates this slice's status from the full product goal.

Allowed requirement statuses:

- `proved`
- `contradicted`
- `incomplete`
- `weak_indirect_evidence`
- `missing_evidence`
- `out_of_scope`

Update timing:

- Create or update the state before stopping, handing off, or asking the user
  for more input.
- Update it after reference inventory changes, implementation verification,
  new rollback checkpoints, or a changed latest user objective.
- Do not let a prose final answer be the only durable state for a long goal.
- On resume, verify the newest relevant state file against current files and
  `git status --short --branch`; current files and latest user instruction win
  over stale JSON.

### Continuation Packet

Long-running goals must leave a recovery packet whenever stopping, handing off,
or approaching context limits. A useful packet is short enough to survive
compaction and specific enough to resume without redoing all discovery.

Required fields:

- `current objective`: latest full user goal, not the narrower slice.
- `non-goals`: tempting actions that are currently forbidden or already rejected.
- `workspace identity`: current project/product name, UI name when relevant,
  internal paths, and historical names if relevant.
- `authoritative records`: active plan/index/runbook paths to read first.
- `completed evidence`: rows proved with file paths, command outputs, or artifact
  paths.
- `incomplete evidence`: rows still incomplete or weakly evidenced.
- `local inventory`: downloaded/reference roots already inventoried and remaining
  unread local projects.
- `changed files`: files this slice changed and whether they are ignored,
  tracked, staged, committed, or intentionally unstaged.
- `rollback`: checkpoint id/path and restore command, with restore gated behind
  explicit user intent.
- `next action`: the next authorized local slice, plus the stop boundary that
  would require user input.
- `goal state`: path to the latest matching `longrun-goal-state-*.json` file
  when one exists.

On resume, the next agent must verify this packet against current files and git
state before trusting it. If the packet conflicts with current evidence, current
files and latest user instructions win.

### Worktree Delegation Packet

When creating or steering a separate worktree thread, the delegation prompt must
be self-contained. Do not assume the child thread can infer the real checkout,
current state, or narrow objective from the parent conversation.

Required delegation fields:

- `work paths`: name the source project path, the requested worktree mode, and
  require the child thread to confirm its actual worktree root with
  `pwd`/`git rev-parse --show-toplevel` plus `git status --short --branch`
  before editing. If the worktree tool returns only a pending id, say that the
  actual path is unknown until setup completes and must be recorded by the child
  thread.
- `must-read files`: list `AI_WORKSPACE_GUIDE.md`, `AGENTS.md`, this playbook,
  `docs/plans/autonomous-execution-framework.md`, the active plan/audit/state
  files, and the exact code/test files likely touched by the slice.
- `current state`: summarize branch/status, known dirty-worktree ownership,
  completed evidence, unresolved audit findings, local-only/generated files,
  and any files the child must not overwrite.
- `objective`: state the one narrow slice, completion criteria, non-goals, and
  whether the slice is a quick fix, design slice, verification slice, or
  documentation/record slice.
- `execution discipline`: require `git status --short --branch`, a rollback
  checkpoint, dirty-worktree ownership audit, and official/mature reference
  review before nontrivial edits.
- `verification`: name focused tests/builds/checks, JSON validation, diff
  checks, and final status checks required for the slice.
- `record updates`: name the plan/audit/goal-state files to update with
  rollback, mature references, changed files, tests, and residual risk.
- `stop boundaries`: explicitly forbid destructive cleanup, `clean_test_data`,
  deleting runtime state, staging/committing/pushing/tags/releases/restores,
  credential changes, and product-direction decisions unless the user gave
  explicit authorization.

For parallel work, prefer separate worktrees and make the boundaries
non-overlapping. If two delegated threads might touch the same source file,
either split the file ownership before dispatch or make one thread design-only
until the other finishes. Small fix threads and larger design threads should
state their interaction boundary in both prompts.

### Reference-Learning Goals

For long goals whose output is research, reference learning, or repository
study:

- First inventory the requested roots and classify duplicate checkouts,
  generated/vendor/static assets, partial checkouts, and unique project
  identities.
- Give each unique project comparable treatment: source, local path, type,
  technical stack, important entrypoints, files or modules actually read,
  transferable patterns, product application, and limits.
- Keep a live project table with `pending`, `reading`, `read`, `duplicate`,
  `partial`, or `skipped-with-reason` status. Do not mark the whole learning goal
  complete while any unique local project remains `pending` or `reading`.
- Record coverage boundaries while reading. Do not wait until the end to admit
  that generated files, external services, provider implementations, or UI
  examples were skipped.
- Separate `local learning complete` from `product implementation verified`.
  Reference notes can justify a design direction; they do not prove the product
  already satisfies it.
- If additional downloads are needed, stop only after the local inventory is
  complete enough to name the precise blind spots and recommended repositories.
- When the user offers to download more repositories, answer with exact links
  only after the current local inventory is complete or after recording why a
  specific local gap cannot be filled from existing files.

Stop only when:

- Continuing needs new credentials, paid access, production access, push, tag, release, or upload.
- A failure cannot be diagnosed and there is no independent safe task to continue.
- Continuing would overwrite user or other-agent work.
- The next choice is a broad product judgment that cannot be reduced into a mini-plan.
- The only remaining work is a forbidden phase, such as unplanned full rewrite, large dependency migration, or external service integration.

Do not stop just because:

- A slice completed.
- The plan is imperfect.
- A local refactor is needed.
- A test needs real AI/API access.
- A packaging smoke may take time.
- Codex or Claude has not reviewed the latest local fix yet.
- A reviewer may have a preference among already documented defaults.
- A runbook says "waiting for next slice signal" but the active plan already contains an authorized next slice and no approval boundary is crossed.

## Refactoring Policy

Plans and code are never perfect. Allow refactoring, including large refactoring, when it is necessary to finish an authorized goal.

Allowed refactoring must have:

- A clear goal: unblock a slice, remove duplicate contracts, make tests possible, isolate risk, or preserve compatibility.
- A staged path: adapter, wrapper, compatibility layer, migration, cleanup.
- A rollback checkpoint before the broad change.
- Characterization tests or focused tests before and after.
- Compatibility for existing routes, payloads, imports, and UI entry points unless the slice explicitly authorizes a breaking change.
- Separate local commits for each phase where practical.

Disallowed refactoring:

- Cross-module rewrites just because code looks untidy.
- Big-bang replacement with no adapter and no tests.
- Mixing multiple product surfaces in one commit so failures cannot be traced.
- Copying external reference project code into the product path.

If the plan is incomplete, the agent should add a mini-plan before editing:

```markdown
### Mini-plan: <slice name>

- Goal:
- Current evidence:
- Files likely touched:
- Refactor needed:
- Compatibility plan:
- Verification:
- Rollback checkpoint:
- Stop conditions:
```

## AI-backed Verification

Use mock tests for deterministic behavior. Use real AI/API smoke tests to prove provider wiring, fallback, runtime config, and user-like flows.

Allowed real AI/API testing:

- Chat/generation smoke.
- Embedding smoke.
- Rerank smoke.
- Gateway or runtime credential fallback smoke.
- End-to-end flow that depends on a model response.

Rules:

- Use only existing `.env`, runtime credential store, key pool, or model config store.
- Resolve credentials through repository code, not agent memory.
- Never log raw keys or Authorization headers.
- Use short prompts, low token budgets, low concurrency, and minimal turns.
- Do not assert exact model wording; assert status, schema, non-empty content, trace fields, fallback behavior, and no secret leakage.
- Treat auth, rate, provider, and network failures as environment signals first; retry through configured fallback only within the budget.

Default budget:

- Up to three real AI/API calls per slice.
- Up to six calls only for provider/auth/rate/network diagnosis.
- More coverage should use mocks.

## Verification Ladder

Match verification strength to blast radius.

Use focused checks first:

- Unit tests for pure logic.
- Router/TestClient tests for API contracts.
- Typecheck for TypeScript changes.
- Compile smoke for Python import changes.
- Browser or Playwright smoke for UI workflows.

For browser smoke tests that mock network traffic, register the most specific
`page.route()` handlers before broad catch-all routes such as `**/api/**`.
If a catch-all is needed, explicitly `fallback()` the endpoints covered by
specific fixtures. This prevents fixtures from being replaced by generic `{}` or
empty-list responses and turns real UI regressions into debuggable failures.

On Windows, when a browser smoke starts a temporary frontend server through
`npm run dev` / Vite, cleanup must account for the child Vite `node.exe`
process, not only the parent `npm.cmd` process returned by `Start-Process`.
Prefer a process-tree cleanup or a command-line/port-filtered cleanup that
only stops the exact temporary port used by the smoke.

When using PowerShell `Start-Process` with redirected logs, do not point
`-RedirectStandardOutput` and `-RedirectStandardError` at the same file. Use
separate stdout/stderr log paths, or the process will not start and the smoke
will fail before product code is exercised.

For PDF text-selection browser smokes, first try a real mouse drag over the
rendered text layer. If headless Chromium over-selects because the PDF page is
clipped or scaled, use a deterministic DOM `Selection` / `Range` fallback
anchored inside `.react-pdf__Page` so the test still proves the product
selection handler, bbox extraction, and payload contract.

For React components that guard async completion with a mounted ref, set the
ref to `true` inside the mount effect and set it to `false` in cleanup. Do not
only initialize the ref before an effect cleanup; React StrictMode development
checks can run setup/cleanup more than once and expose stale false mounted
guards.

Escalate when the slice crosses boundaries:

- Backend + frontend: API contract test plus frontend build.
- Runtime config: masked connectivity probe plus fallback test.
- Security: malicious input tests plus regression for allowed local cases.
- Packaging: focused script tests, then local release gate or installer smoke.

A slice is not done until verification is run or the reason for skipping it is recorded.

## Root-Cause Abstraction Pattern

Use this pattern whenever the user says "抽象一下", "找根源", "不要只做针对性修复", "排查根本原因", or reports a bug whose visible symptom could be caused by hidden state coupling.

Mature references to keep in mind:

- SRE-style postmortems: separate symptom, trigger, contributing causes, root causes, and prevention actions.
- React-style UI debugging: an Effect that updates state used by its own dependency chain can create a cycle; event handlers read a render-time state snapshot, so same-tick duplicate events need an immediate guard such as a ref, not only a later disabled state.
- Characterization tests: lock the observed behavior at the call chain that reproduces the real failure before changing the boundary contract.

Default method:

1. Define the invariant, not only the symptom.
   - Bad: "button flickers."
   - Good: "after resuming a history session, there must be one active project authority, one conversation scope, one right-panel mode, and no repeating network/DOM loop."
2. Build an observable feedback loop before editing.
   - Prefer browser smoke, network count, DOM mutation count, URL changes, console messages, and focused unit/integration tests.
   - Capture enough data to distinguish "one slow refresh" from "state oscillation."
3. Draw the ownership map.
   - List each state/resource involved.
   - For each item, record who reads it, who writes it, and what event/effect writes it.
   - Mark duplicate writers and fallback/default writers; these often cause loops.
4. Generate falsifiable hypotheses before patching.
   - Example: "If global project fallback is the root cause, network requests will alternate between route project and default project."
   - Test one variable at a time with targeted instrumentation.
5. Fix the authority boundary, then add local guards.
   - First decide the canonical owner or precedence rule.
   - Remove feedback loops between URL, global context, local view state, storage, and async recovery.
   - Add idempotency guards for same-tick duplicate actions only as a secondary protection.
6. Add regression coverage at the root contract.
   - One test should protect the authority rule.
   - One test should protect the duplicate-action/idempotency rule when relevant.
   - Browser smoke should replay the original workflow and report counts, not only visual success.
7. Record the lesson.
   - Include symptom, invariant, ownership conflict, correct fix level, tests, smoke evidence, residual risks, and rollback.

Practical example from 2026-06-08:

- Symptom: double-clicking a left-rail SmartRead history item made the right QA panel flicker.
- Observed evidence: browser probe showed 600+ right-panel DOM mutations in about 3 seconds and repeated network requests alternating between two `project_id` values.
- Ownership map:
  - `Dialog` restored the archived/invisible history session into its original project.
  - `MainLayout` treated any project not in the visible project list as invalid and fell back to the first visible project.
  - `Dialog` then synced back from URL `project_id`, producing a loop.
- Root cause: conflicting project authority between route project id and global visible-project fallback, amplified by same-tick duplicate resume clicks.
- Fix level:
  - `MainLayout` now treats explicit route `project_id` as authoritative even if not visible.
  - `Dialog` uses an immediate restoring ref to reject duplicate restore events.
  - PDF read mode keeps the document in the center while only the right rail switches to chat/discussion.
- Regression:
  - Test invisible route `project_id` is not overwritten by default project.
  - Test duplicate same-tick history clicks call resume once.
  - Browser smoke verified one `/api/chat/resume`, stable URL/tab, stable center PDF, and no project-id request loop.

When this pattern applies, do not start by patching the visible component. Start by proving which boundary owns the state, then patch the ownership boundary and protect it with focused tests.

## Commit Strategy

Local commits are allowed when they improve recovery and review.

Commit rules:

- Inspect diff before staging.
- Stage only files belonging to the current slice.
- Do not include unrelated dirty files.
- Use commit messages that name the slice and verification result.
- Keep docs/plan changes separate when they are not part of the code slice.
- Leave user-local settings and generated audit files unstaged unless explicitly requested.

## Reference Repository Usage

External repositories under `github/` are reference material unless the user explicitly asks to modify them.

Use them to learn:

- Data model shape.
- UI interaction pattern.
- Testing strategy.
- Deployment or packaging technique.
- Failure modes and edge cases.

Do not copy reference code into product code without a license and architecture review.

## Plan Update Contract

After each slice, update the active plan or handoff note with:

- Status: done, blocked, skipped, or deferred.
- Changed files.
- Tests and commands run.
- Real AI/API calls used, with provider/model only and masked key identity if relevant.
- Residual risk.
- Next authorized slice.
- Rollback checkpoint.
- Latest goal-state JSON path when the active goal is long-running.

## Mature References To Reuse

- ADR style: context, decision, consequences.
- SRE style: canary/smoke, rollback, observable failure.
- Branch by abstraction: introduce a compatibility abstraction, migrate callers, remove old path later.
- Strangler-style replacement: wrap old behavior and replace incrementally.
- Characterization tests: lock current behavior before broad refactoring.
- Test pyramid: many deterministic unit tests, fewer integration tests, a small number of high-value end-to-end smokes.
- Requirements traceability: every original goal row links to implementation,
  command, artifact, runtime, or inventory evidence.
- Checkpointed agent state: long-running work resumes from explicit persisted
  state, not only from transcript memory.

## Anti-patterns

Avoid these patterns:

- Mechanical next-step execution that follows the queue order without checking product fit.
- Treating optional, external, or approval-gated items as local implementation work because they appear after the current slice.
- "Finish one slice and wait" when safe work remains.
- Unbounded "improve architecture" tasks.
- Testing only happy-path mocks when the real bug is provider wiring.
- Real AI tests that assert exact prose.
- Broad commits that combine feature work, formatting, docs, and unrelated local files.
- Big-bang rewrites with no compatibility layer.
- Plans that forbid necessary refactoring.
- Plans that allow publishing or credential changes without explicit approval.

## Minimal Template

```markdown
## Unattended Execution Decisions

### Automatic Authorization

- Allowed:
- Requires explicit approval:

### Execution Queue

1. <slice>
   - Scope:
   - Non-goals:
   - Verification:
   - Fallback:

### Refactor Policy

- Allowed when:
- Must preserve:
- Stop when:

### AI-backed Verification

- Allowed roles:
- Budget:
- Assertions:
- Logging:

### Stop Conditions

- Stop only for:
- Continue through:

### Completion Record

- Changed files:
- Tests:
- AI/API calls:
- Residual risk:
- Next slice:
- Rollback:
```
