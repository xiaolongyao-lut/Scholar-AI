# Copilot Coding Agent — Squad Instructions

You are working on a project that uses **Squad**, an AI team framework. When picking up issues autonomously, follow these guidelines.

## Required Workspace Guide

Before editing, moving files, running tests, or giving commands, read `AI_WORKSPACE_GUIDE.md`.

The active literature-assistant workspace is organized as:

- Backend/core Python: `literature_assistant/core/`
- ASGI app: `literature_assistant.core.python_adapter_server:app`
- Frontend: `frontend/`
- Runtime/generated artifacts: `workspace_artifacts/`
- Plans/specs/execution plans: `docs/plans/`
- Evaluation/diagnostic scripts: `workspace_tests/`
- Experiments/references: `workspace_references/`
- External RAG reference repositories: read-only `github/`

Do not recreate old root-level entrypoints such as `python_adapter_server.py`, `batch_controller.py`, or `my-project/`. Use the canonical commands in `AI_WORKSPACE_GUIDE.md`.

## Team Context

Before starting work on any issue:

1. Read `C:\Users\xiao\Desktop\tools\用户画像_v4_AI协作治理型工程主理人.md` for the canonical owner profile.
2. Read `.squad/identity/owner-profile-v4.md` for the Squad adapter rules.
3. Read `.squad/team.md` for the team roster, member roles, and your capability profile.
4. Read `.squad/routing.md` for work routing rules.
5. If the issue has a `squad:{member}` label, read that member's charter at `.squad/agents/{member}/charter.md` to understand their domain expertise and coding style — work in their voice.

Owner-profile v4 supersedes older user-profile v3 references. Use v3 only as archival evidence, not as the active behavior source.

## Capability Self-Check

Before starting work, check your capability profile in `.squad/team.md` under the **Coding Agent → Capabilities** section.

- **🟢 Good fit** — proceed autonomously.
- **🟡 Needs review** — proceed, but note in the PR description that a squad member should review.
- **🔴 Not suitable** — do NOT start work. Instead, comment on the issue:
  ```
  🤖 This issue doesn't match my capability profile (reason: {why}). Suggesting reassignment to a squad member.
  ```

## Branch Naming

Use the squad branch convention:
```
squad/{issue-number}-{kebab-case-slug}
```
Example: `squad/42-fix-login-validation`

## PR Guidelines

When opening a PR:
- Reference the issue: `Closes #{issue-number}`
- If the issue had a `squad:{member}` label, mention the member: `Working as {member} ({role})`
- If this is a 🟡 needs-review task, add to the PR description: `⚠️ This task was flagged as "needs review" — please have a squad member review before merging.`
- Follow any project conventions in `.squad/decisions.md`

## Decisions

If you make a decision that affects other team members, write it to:
```
.squad/decisions/inbox/copilot-{brief-slug}.md
```
The Scribe will merge it into the shared decisions file.

## Long-Running & Self-Decision

For any task that runs across multiple turns, terminals, or sessions, you MUST conform to the kernel-grade protocols:

- **Long-running protocol** — `.squad/kernel/long-running-protocol.md`
  - Atomic writes (`*.tmp` + replace) for shared/persistent state
  - Session resume via `RAG_SESSION_ID` (or task-equivalent ID) with checkpoints under `.squad/sessions/`
  - Multi-terminal lock files under `.squad/locks/` before touching shared state
  - All LLM/API calls go through `model_call_gateway`; citations through `citation_auditor`
  - No silent failure — degraded paths must be logged
  - Cross-stack write protection (Copilot must not write under `.claude_squad/`)

- **Self-audit protocol** — `.squad/kernel/self-audit.md`
  - Run the 7-item audit checklist on the cadence defined in
    `.squad/casting-policy.json` → `execution_profile.discipline`
  - Every irreversible action (delete / push / publish / pay / schema) goes through the double-confirm gate
  - Every autonomous decision writes a provenance record with `kernel_rule_ref`
  - Failed audit = `constraint` blocker → escalate per `.squad/kernel/blocker-arbitration.md`

These rules apply to every agent in the squad regardless of profile, but the
aggressive profile additionally enforces the safety guardrails defined in
`.squad/charter.md` (Aggressive Safety Guardrails).

## Owner Profile v4 Closure Rule

Do not claim completion until all four are true:

1. primary artifact is on disk and downstream-readable;
2. state/decision/docs are synchronized where applicable;
3. smoke/canary/full gate is reported with actual command and exit code;
4. environment cleanup is checked for stale locks, ghost-running, orphan tmp, mixed-run artifacts, and duplicate append pollution.

If you dispatch another agent, include the owner-profile packet from the canonical v4 profile plus `.squad/identity/owner-profile-v4.md` in the brief. Missing propagation is a coordinator failure.
