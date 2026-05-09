---
name: "project-conventions"
description: "Project-wide Copilot rules, instruction files, and shared working conventions for all squad members"
domain: "project-conventions"
confidence: "high"
source: "my-project bootstrap"
---

## Context

Use this skill for every substantive task in this project. It is the bridge between Squad members and the Copilot rules already active in the user's workspace.

## Patterns

### Always load project rules first

Before doing real work:
- Read `.squad/identity/start-here.md` if it exists, and follow its reading order.
- Read `.github/copilot-instructions.md` if it exists.
- Read task-relevant files under `.github/instructions/`.
- Read `.squad/decisions.md` and any relevant `.squad/skills/*/SKILL.md` files.

### Use project knowledge entry points

Treat these files as the project's durable knowledge layer:

- `.squad/identity/project-brief.md`
- `.squad/identity/phase-plan.md`
- `.squad/identity/data-sources.md`
- `.squad/identity/interface-glossary.md`
- `.squad/identity/night-shift-policy.md`
- `.squad/identity/requirement-scoring.md`
- `.squad/identity/requirement-pool.md`
- `.squad/identity/frontend-state-spec.md`
- `.squad/identity/test-scenarios.md`
- `.squad/identity/algorithm-reliability.md`
- `.squad/identity/refactor-policy.md`
- `.squad/identity/now.md`
- `.squad/identity/wisdom.md`
- `.squad/memory/SESSION_SNAPSHOT.md`
- `.squad/memory/OPEN_THREADS.md`
- `.squad/memory/TEAM_MEMORY.md`

Do not start substantive work without understanding the active phase and existing project constraints.

### Team memory persistence (local-first)

- Team memory is stored locally in `.squad/memory/` and must remain readable by all members.
- Before substantive work, read `SESSION_SNAPSHOT.md` and `OPEN_THREADS.md`.
- During/after meaningful work, append key decisions to `DECISION_TRAIL.md` with reasons and evidence.
- When a conclusion is stable and reusable, promote it into `TEAM_MEMORY.md`.
- For governance-level conclusions, sync a concise record into `.squad/decisions.md`.

### Follow the main Copilot session's behavior

All squad members should align with the same expectations as the main Copilot session:
- Think before coding.
- Prefer the minimum code that solves the problem.
- Make surgical changes.
- Define success criteria and verify them.

### Keep changes scoped

- Match existing style.
- Avoid speculative abstractions.
- Do not rewrite unrelated code.
- If instructions conflict, prefer `.github/copilot-instructions.md`, then task-relevant `.github/instructions/*`, then local habits.

### Keep src-only tests runnable

- If the repo is not packaged for installation, add a minimal `src` path bootstrap in pytest modules so tests run directly from the repo root.
- Prefer local `sys.path` handling in the test file over adding new dependencies or build steps.

### Make pending-module tests contract-adaptive

- When a target module is not implemented yet, keep the test file collected by skipping at the call site instead of skipping module import globally.
- Probe a small set of plausible public function names/signatures so the tests can adapt once the implementation lands.
- Use temp directories and fixture names that mirror real discovered artifacts, not abstract toy filenames.

### Mirror real record shapes in regressions

- For retrieval and keyword-filter tests, prefer fixtures shaped like discovered production records instead of abstract toy dicts.
- High-value fields in this project include `source_pdf`, `focus_points`, and nested `chunks`.
- Mixed metadata plus nested chunk content is a strong regression target because it exercises the same recursion paths used by the real pipeline.

### Make extraction pipeline tests contract-adaptive

- When `src/extraction_pipeline.py` is not present yet, keep the test collected and skip at the call site instead of failing on import.
- Probe a small set of plausible public callable names and accept folder-path plus keyword conventions before giving up.
- Use temp folders with traversal-shaped JSON/text fixtures, including malformed and unsupported lightweight inputs, to verify relevance pruning, provenance visibility, and graceful failure together.

### Prefer one corpus for extraction boundary QA

- For extraction boundary checks, a single temp corpus can usually cover malformed nested JSON, keyword-pruned empties, and mixed-source provenance stability.
- Seed the corpus with one relevant JSON extract, one noisy or malformed lightweight payload, and at least one plain-text source so the test can verify all three behaviors without expanding scope.
- Assert provenance fields remain visible on every emitted item; path stability matters more than payload shape.

### Preserve current frontend and backend style

- Frontend agents should preserve the current design language and interaction style unless Morpheus explicitly authorizes a redesign or refactor.
- Backend and implementation agents should preserve the existing code style, structure, and local conventions.
- Do not change style merely because a different aesthetic or architecture might also work.

### Refactor lock and backup rule

- Only Morpheus may authorize a refactor.
- If a refactor is approved, create a backup before changing the target files.
- Record the backup path or backup file location in the work log, decision note, or summary.
- Preferred ledger: `.squad/log/refactor-backups.md`.
- Preferred backup root: `.squad/backups/`.
- No silent refactors, no drive-by rewrites.

### Night shift requirement handling

- First apply requirement-pool bypass rules for clearly in-scope, no-refactor incremental work.
- If bypass-eligible, implement directly and report in the morning summary.
- If not bypass-eligible, queue in `.squad/identity/requirement-pool.md`.
- Score with `.squad/identity/requirement-scoring.md` using this priority order:
	1. real usage necessity for the RAG literature assistant
	2. availability of mature online solutions
	3. implementability without refactor
- If the score is clear, Morpheus can recommend `DO NOW` or `LATER`.
- If confidence is low on code-level decisions, mark `WAITING FOR MORPHEUS` and continue with safer work.
- Any refactor, schema change, or new dependency is a hard stop and must wait for Morpheus approval.
- Ordinary bugfix / test / data prep can continue under night-shift safe-mode.
- Code-level final judgment belongs to Morpheus.
- Morpheus should evaluate using current project requirements plus historical plans/design records.
- Existing design/code thinking in the `github` project may be reused directly when it fits current scope and does not trigger hard stops.

### Instruction file routing

Use these instruction files when relevant:
- `code-review-generic.instructions.md` for review and QA framing
- `context-engineering.instructions.md` for code organization and context quality
- `long-context-memory.instructions.md` for long-running context and handoff-sensitive tasks
- `performance-optimization.instructions.md` for runtime, rendering, or web performance work
- `security-and-owasp.instructions.md` for security-sensitive work
- `update-docs-on-code-change.instructions.md` when code changes imply docs changes

## Anti-Patterns

- Starting implementation before reading project rules
- Starting implementation before reading `.squad/identity/start-here.md`
- Treating `.squad/skills/` as optional trivia
- Ignoring user-specified constraints that were already captured in `decisions.md`
- Using broad refactors when the task only needs a focused change
- Changing frontend style casually and increasing UI rework cost
- Reformatting backend code into a new style without explicit authorization
- Performing refactors without backup and without recording where rollback artifacts live
