# Longrun Local Supervisor

This runbook documents the local fallback used when Codex UI automation cards are
not available in VS Codex.

## LMWR-469 Scope

This guide is the operating contract for LLM-Wiki/RAG longrun mode. It covers
startup conditions, stop conditions, supervisor behavior, required checkpoints,
mature-solution research, verification, and handoff records.

Longrun mode may continue only the active LLM-Wiki/RAG literature assistant
plan. It must not enable external write-back, auto-finalize wiki pages, change
the default RAG/TOLF chain, edit `.env` or secrets, write into `github/` or
downloaded reference repositories, or perform a broad refactor without explicit
user approval. qrels/goldset/canary30 may be changed only under the
2026-05-04 authorization rule: checkpoint, backup, versioned metrics, and a
documented restore path first.

Latest user authorization is recorded in:
`docs/plans/active/llmwiki-autonomy-authorization.md`.

## Mature Solution Notes

| Source | Borrowed rule |
| --- | --- |
| OpenAI Codex `AGENTS.md` docs: `https://developers.openai.com/codex/guides/agents-md` | Load global and project instructions before work; keep project-specific guidance close to the repo. |
| OpenAI Codex non-interactive mode docs: `https://developers.openai.com/codex/noninteractive` | Scheduled jobs should use explicit sandbox/approval settings, narrow prompts, structured output when useful, and verification after edits. |
| Microsoft ScheduledTasks `New-ScheduledTaskTrigger`: `https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasktrigger` | Use a time-based repeating trigger for local supervision, with a separate worker process per tick. |
| Git worktree docs: `https://git-scm.com/docs/git-worktree` | Avoid disturbing a dirty working tree; for high-risk parallel work prefer an isolated worktree or stop for user direction. |
| Project guide: `AI_WORKSPACE_GUIDE.md` | Put plans in `docs/plans/`, runtime state in `workspace_artifacts/`, and preserve rollback before non-trivial edits. |

## Design

- Scheduler: Windows Task Scheduler via PowerShell ScheduledTasks.
- Runner: `tools/longrun/invoke-longrun-supervisor.ps1`.
- Manual worker: `tools/longrun/start-longrun-worker.ps1`.
- Cadence: default 30 minutes.
- Runtime state: `workspace_artifacts/runtime_state/longrun-supervisor/`.
- Logs: `workspace_artifacts/runtime_state/longrun-supervisor/logs/`.
- Stop file: `workspace_artifacts/runtime_state/longrun-supervisor/STOP`.
- Interactive marker:
  `workspace_artifacts/runtime_state/longrun-supervisor/interactive-session.json`.
- Prompt: `tools/longrun/longrun-prompt.md`.

The runner uses a lock file to avoid overlapping Codex runs. The scheduled task
also uses `MultipleInstances IgnoreNew`, so a long run does not start a second
agent in parallel.

## Required Startup Envelope

Every longrun worker must begin with this envelope:

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "llmwiki-longrun-<slice-or-purpose>"
git status --short
rg -n "LMWR-|下一步|待|⏸️|D[0-9]+|longrun|回档|成熟方案" docs\plans\active docs\plans\runbooks
```

Then read the current control files before deciding:

```powershell
Get-Content docs\plans\active\2026-05-03-llmwiki-rag-literature-assistant-execution-plan.md
Get-Content docs\plans\active\2026-05-03-llmwiki-execution-decisions.md
Get-Content docs\plans\active\llmwiki-autonomy-authorization.md
Get-Content docs\plans\runbooks\longrun-local-supervisor.md
Get-Content AI_WORKSPACE_GUIDE.md
```

For every non-trivial architecture, data, retrieval, graph, prompt, scheduler,
UI, API, evaluation, or release decision, search official or mature references
before editing. Prefer official docs and maintained upstream examples. If the
task is only a small documentation sync based on already-read project records,
local references are sufficient, but the runbook must say so.

## Task Selection

Select the next slice from active docs, not from memory. Prefer a task when it
is:

- already listed in the active plan
- low risk and independently verifiable
- inside the LLM-Wiki/RAG scope
- reversible with the current checkpoint
- small enough to finish and verify in one worker window

When the next useful operation requires product judgment, and that judgment is not included in the authorization supplement, stop the operation instead of selecting work.
Changes to qrels/goldset/canary30 without backup, external write-back without target-level backup,When backup exists, all operations can make their own decisions.

## Command-Giving Rule

Any instruction or command block written for a user or another agent must
include these phases:

```powershell
# 1. Create rollback checkpoint.
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" create --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --label "<task-label>"

# 2. Search mature or official solutions.
# Example: site:developers.openai.com/codex <feature>
# Example: site:learn.microsoft.com PowerShell ScheduledTasks <feature>
# Example: site:git-scm.com/docs git worktree <feature>

# 3. Implement the narrow task.
# Keep generated/runtime files under workspace_artifacts and plans under docs/plans.

# 4. Verify with focused tests/build/compileall.
# Use the smallest command set that proves the slice.

# 5. Restore only after explicit user rollback intent.
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" list --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script"
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "<checkpoint-id>" --confirm-restore
```

Never run the restore command unless the user explicitly asks to roll back,
restore, or undo a specific change.

## Verification Ladder

Use the narrowest reliable verification first:

```powershell
.\.venv-1\Scripts\python.exe -m compileall -q docs\plans
.\.venv-1\Scripts\python.exe -m compileall -q literature_assistant\core\wiki literature_assistant\core\routers
.\.venv-1\Scripts\python.exe -m pytest tests\wiki -q
```

For frontend changes:

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script\frontend
npm run test -- --run
npm run build
```

For path/import or release-facing changes:

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\.venv-1\Scripts\python.exe .\run_literature_assistant.py paths
.\.venv-1\Scripts\python.exe workspace_tests\evaluation_scripts\system_verification.py --json
```

Record the exact verification commands and results in the relevant runbook or
decision log before moving to another slice.

## Handoff Record

Each worker must leave a compact handoff when it stops:

- checkpoint id and path
- selected task and reason
- files changed
- verification commands and results
- plan/decision files updated
- residual risks and blocked items
- next recommended slice

## Startup Semantics

There are two roles:

- **Supervisor**: the Windows scheduled task. It wakes up every 30 minutes and
  tries to start one non-interactive Codex run. It does not stay resident
  between ticks.
- **Worker**: one actual Codex run. It can be started by the scheduler or
  manually with `start-longrun-worker.ps1`.

Startup order is intentionally order-independent:

- If a manual worker is already running, the scheduled supervisor sees
  `run.lock` and skips that tick.
- If the scheduled worker is already running, a manual worker sees `run.lock`
  and exits without starting another Codex process.
- If a VS Codex interactive longrun is active and marked with
  `enter-interactive-longrun.ps1`, the scheduled supervisor skips that tick and
  waits for the next 30-minute cycle.
- If `STOP` exists, both scheduled and manual workers exit before starting
  Codex.

Expected behavior:

- No longrun active: the scheduled supervisor starts one worker at the next tick.
- Script-started worker active: the scheduled supervisor skips silently.
- VS Codex interactive longrun active and marked: the scheduled supervisor skips
  silently until the marker expires or is removed.
- Paused with `STOP`: all workers skip until resumed.

Recommended daily flow:

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\status-longrun-supervisor.ps1
.\tools\longrun\install-longrun-supervisor.ps1 -IntervalMinutes 30 -MaxRunMinutes 25
.\tools\longrun\start-longrun-worker.ps1 -MaxRunMinutes 25
```

The first two commands ensure supervision is active. The third command starts an
immediate worker instead of waiting for the next 30-minute tick. It is safe to
skip the third command if you only want scheduled execution.

For a VS Codex interactive longrun, mark the session first:

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\enter-interactive-longrun.ps1 -TtlMinutes 180
```

When the interactive longrun finishes, clear the marker:

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\leave-interactive-longrun.ps1
```

## Install

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\install-longrun-supervisor.ps1 -IntervalMinutes 30 -MaxRunMinutes 25
```

## Check Status

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\status-longrun-supervisor.ps1
```

## Pause Without Removing The Task

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\pause-longrun-supervisor.ps1 -Reason "manual pause"
```

## Resume

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\resume-longrun-supervisor.ps1
```

## Uninstall

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\uninstall-longrun-supervisor.ps1
```

## Manual Dry Run

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\invoke-longrun-supervisor.ps1 -DryRun
```

## Immediate Worker Run

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\start-longrun-worker.ps1 -MaxRunMinutes 25
```

## Interactive VS Codex Marker

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\enter-interactive-longrun.ps1 -TtlMinutes 180
```

```powershell
cd C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script
.\tools\longrun\leave-interactive-longrun.ps1
```
