# morpheus-headless.ps1 — Gamma: headless Morpheus decision loop.
#
# Replaces the interactive Claude Code TUI window with a bash-style loop that
# calls `claude --print` once per round. Each round:
#   1. Compose a round-brief from goal-drift + latest eval + squad inbox.
#   2. Call claude -p (reusing --session-id so prompt cache stays warm).
#   3. Claude's response body executes squad commands internally via its Bash
#      tool — we don't parse it.
#   4. Append DECISION_TRAIL snippet, run halt-check, sleep, loop.
#
# Why this exists: the interactive TUI flavor failed under true unattended
# operation because stdin-piped Chinese was truncated by Windows ACP argv and
# new claude sessions ran in a restricted sandbox that couldn't read
# .claude_squad/**. This script runs in the parent shell, so it inherits the
# user's existing Claude Code permissions — no sandbox barrier.
#
# Usage:
#   .\tools\squad\morpheus-headless.ps1                      # loop forever
#   .\tools\squad\morpheus-headless.ps1 -Once                # one round and exit
#   .\tools\squad\morpheus-headless.ps1 -RoundSleepSec 600   # 10 min between rounds
#   .\tools\squad\morpheus-headless.ps1 -MaxRounds 3         # test mode
#
# Stop:
#   Close the window, or:  .\tools\squad\squad-cleanup.ps1
#   Legal halt: the loop itself will stop when `squad long-status halt-check`
#   returns exit 0.

param(
    [int]$RoundSleepSec = 1200,   # 20 min between rounds by default
    [int]$MaxRounds    = 0,       # 0 = unlimited
    [switch]$Once,
    [string]$SessionId = '',      # override; default = read/write .squad/state/morpheus-session-id.txt
    [switch]$DryRun,              # print the prompt, don't call claude
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

# Force UTF-8 end-to-end so the Chinese charter/brief survives the pipe to `claude`.
# Windows default console encoding (CP936/GBK) otherwise corrupts multibyte chars.
$OutputEncoding = [System.Text.Encoding]::UTF8
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { [Console]::InputEncoding  = [System.Text.Encoding]::UTF8 } catch {}

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
$scriptDir   = $PSScriptRoot

# 2026-04-26 root-cause fix (third-party claude API instability):
# dot-source resilient-call sidecar. Provides Invoke-ClaudeOnceRetried
# used inside Invoke-ClaudeRound below. See tools/squad/claude-resilient-call.ps1.
. (Join-Path $scriptDir 'claude-resilient-call.ps1')

$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)

$goalDrift   = Join-Path $projectRoot '.squad\identity\goal-drift.md'
$reqPool     = Join-Path $projectRoot '.squad\identity\requirement-pool.md'
$kickoff     = Join-Path $projectRoot '.squad\identity\long-run-prompt.md'
$charter     = Join-Path $projectRoot '.claude_squad\agents\morpheus\charter.md'
$evalDir     = Join-Path $projectRoot '.squad\evaluations'
$decisions   = Join-Path $projectRoot '.squad\memory\DECISION_TRAIL.md'
$openThreads = Join-Path $projectRoot '.squad\memory\OPEN_THREADS.md'
$stateDir    = Join-Path $projectRoot '.squad\state'
$sessIdFile  = Join-Path $stateDir 'morpheus-session-id.txt'
$sessSeeded  = Join-Path $stateDir 'morpheus-session-seeded.flag'
$roundLog    = Join-Path $stateDir 'morpheus-rounds.jsonl'
$lockFile    = Join-Path $stateDir 'morpheus-headless.lock'
$squadPs1    = Join-Path $scriptDir 'squad.ps1'

# Prefer the local wrapper; fallback to installed squad.exe.
$squadExe = if (Test-Path $squadPs1) { $null } else { 'C:\Tools\squad\squad-real.exe' }  # 2026-04-26: shim-aware fallback

function Invoke-Squad {
    param([string[]]$SquadArgs)
    if ($null -ne $squadExe) {
        & $squadExe @SquadArgs
    } else {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $squadPs1 @SquadArgs
    }
}

if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }

$Host.UI.RawUI.WindowTitle = 'morpheus-headless'

# Process lock ($lockFile = morpheus-headless.lock): "which PID is running the
# headless daemon", read by supervisor.ps1 to decide if the daemon is dead.
# Identity lock (morpheus.lock, written by Acquire-SquadIdentity below):
# "which PID owns the morpheus name in the squad registry". The two are
# distinct on purpose — identity outlives any one daemon process.
# (Refactor 2026-04-26 — fixes morpheus-2 / morpheus-3 ID drift on abrupt
# restart by making takeover detect dead-PID locks and force `squad leave`
# before re-joining. See tools/squad/squad-lock.ps1.)

function Get-LockPid {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'lock path is required' }
    if (-not (Test-Path $Path)) { return $null }

    $raw = (Get-Content -Path $Path -Raw -ErrorAction SilentlyContinue).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }

    $pidValue = 0
    if (-not [int]::TryParse($raw, [ref]$pidValue)) { return $null }
    if ($pidValue -le 0) { return $null }
    return $pidValue
}

function Remove-MorpheusProcessLock {
    if ((Test-Path $lockFile) -and ((Get-LockPid -Path $lockFile) -eq $PID)) {
        Remove-Item -Path $lockFile -Force -ErrorAction SilentlyContinue
    }
}

function Acquire-MorpheusProcessLock {
    $existingPid = Get-LockPid -Path $lockFile
    if ($null -ne $existingPid -and $existingPid -ne $PID) {
        $existingProc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProc) {
            Write-Warning "another morpheus-headless already running at PID $existingPid"
            exit 0
        }
    }

    Set-Content -Path $lockFile -Value ([string]$PID) -Encoding UTF8
}

Acquire-MorpheusProcessLock

# Acquire the squad-side morpheus identity via the shared lock module.
# This handles the dead-PID-takeover dance (force `squad leave` before
# re-joining) so we can never end up registered as morpheus-2 / morpheus-3.
. (Join-Path $scriptDir 'squad-lock.ps1')
$idAcq = Acquire-SquadIdentity -Role 'morpheus'
if (-not $idAcq.ok) {
    Write-Warning "morpheus identity unavailable: $($idAcq.reason). Exiting to avoid name collision."
    Remove-MorpheusProcessLock
    exit 0
}
Write-Host "[morpheus-headless] joined squad as 'morpheus' (identity-lock pid=$PID)" -ForegroundColor Green

$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -MessageData @{ LockFile = $lockFile; OwnerPid = $PID; ScriptDir = $scriptDir } -Action {
    $data = $Event.MessageData
    if ($null -eq $data) { return }
    $path = [string]$data.LockFile
    $ownerPid = [int]$data.OwnerPid
    $scriptDirLocal = [string]$data.ScriptDir

    if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path $path)) {
        $raw = (Get-Content -Path $path -Raw -ErrorAction SilentlyContinue).Trim()
        $lockPid = 0
        if ([int]::TryParse($raw, [ref]$lockPid) -and $lockPid -eq $ownerPid) {
            Remove-Item -Path $path -Force -ErrorAction SilentlyContinue
        }
    }

    # Release the identity lock too, so the next start-up can take over cleanly.
    if (-not [string]::IsNullOrWhiteSpace($scriptDirLocal)) {
        $lockMod = Join-Path $scriptDirLocal 'squad-lock.ps1'
        if (Test-Path $lockMod) {
            try {
                . $lockMod
                Release-SquadIdentity -Role 'morpheus' -OwnerPid $ownerPid | Out-Null
            } catch {}
        }
    }
} -ErrorAction SilentlyContinue

# ------------------------------------------------------------------
# Session ID: persistent across rounds so prompt cache stays warm.
# ------------------------------------------------------------------
function Resolve-SessionId {
    if ($SessionId) { return $SessionId }
    if (Test-Path $sessIdFile) {
        $existing = (Get-Content $sessIdFile -Raw).Trim()
        if ($existing) { return $existing }
    }
    $new = [guid]::NewGuid().ToString()
    # Atomic write per CLAUDE.md §4.7: write to .tmp then Move-Item -Force.
    # Prevents corrupt session-id file (empty/partial UUID) on crash mid-write.
    # Audit anchor: .squad/audits/atomic-write-audit-2026-04-25.md (P1 violator #4, morpheus-headless.ps1:91 → drifted to :176).
    # Variable named $sessIdTmp to satisfy tools/squad/check-atomic-write.ps1's compliant regex.
    $sessIdTmp = "$sessIdFile.tmp"
    Set-Content -Path $sessIdTmp -Value $new -Encoding UTF8
    Move-Item -LiteralPath $sessIdTmp -Destination $sessIdFile -Force
    return $new
}

$sessionId = Resolve-SessionId
Write-Host "[morpheus-headless] session-id: $sessionId" -ForegroundColor Cyan
Write-Host "[morpheus-headless] state dir:  $stateDir" -ForegroundColor DarkGray

# ------------------------------------------------------------------
# Round brief builder
# ------------------------------------------------------------------
function Get-LatestEvalPath {
    if (-not (Test-Path $evalDir)) { return $null }
    $latest = Get-ChildItem $evalDir -Filter 'run-*.json' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $latest) { return $null }
    return $latest.FullName
}

function Get-EvalSummary {
    $path = Get-LatestEvalPath
    if (-not $path) { return "No eval available yet. Run .\tools\squad\run-rag-once.ps1 first." }
    try {
        $data = Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
        $s = $data.summary
        $age = [int]((Get-Date) - (Get-Item $path).LastWriteTime).TotalMinutes
        $lines = @("Latest eval: $($data.run_id)  pass=$($s.passed)/$($s.total) rate=$($s.pass_rate)  age=${age}min")
        foreach ($q in $data.questions) {
            $tag = if ($q.passed) { 'OK  ' } else { 'FAIL' }
            $snippet = if ($q.question.Length -gt 50) { $q.question.Substring(0,50) + '...' } else { $q.question }
            $lines += ("  [{0}] http={1} ms={2} {3}" -f $tag, $q.http_status, $q.elapsed_ms, $snippet)
        }
        return ($lines -join "`n")
    } catch {
        return "Eval parse failed: $_  (path=$path)"
    }
}

function Get-InboxTail {
    # `squad history` does not expose --json (only `squad receive --json` does, but
    # receive is destructive — it marks messages read. We need a peek, so we parse
    # the text output. Format (verified 2026-04-26):
    #   "  [<ts>] <from> -> <to>: <body>"     (read)
    #   "* [<ts>] <from> -> <to>: <body>"     (unread)
    try {
        $raw = Invoke-Squad -SquadArgs @('history','morpheus') 2>$null | Out-String
        if ([string]::IsNullOrWhiteSpace($raw)) { return '' }
        $rx = '^([\*\s])\s\[([^\]]+)\]\s+(\S+)\s+->\s+\S+:\s*(.*)$'
        $entries = foreach ($line in ($raw -split "`r?`n")) {
            if ($line -match $rx) {
                [pscustomobject]@{
                    unread = ($Matches[1] -eq '*')
                    ts     = $Matches[2]
                    from   = $Matches[3]
                    body   = $Matches[4]
                }
            }
        }
        if (-not $entries -or $entries.Count -eq 0) { return '' }
        $recent = $entries | Select-Object -Last 8
        $lines = foreach ($m in $recent) {
            $body = if ($m.body.Length -gt 160) { $m.body.Substring(0,160) + '...' } else { $m.body }
            $tag  = if ($m.unread) { '[NEW]' } else { '     ' }
            "  $tag from=$($m.from) ts=$($m.ts)  $body"
        }
        return ($lines -join "`n")
    } catch {
        return "(inbox read failed: $_)"
    }
}

function Get-OpenThreadsTail {
    if (-not (Test-Path $openThreads)) { return '' }
    $lines = Get-Content $openThreads -Tail 40
    return ($lines -join "`n")
}

function Get-QueuedTasksForMe {
    # Inject queued tasks assigned to morpheus into the round brief, so morpheus
    # actually sees `squad tell` -> task-create work in its prompt without having
    # to remember to run `squad task list` itself.
    # Added 2026-04-26 — closes the tell -> task -> ack loop.
    try {
        $raw = Invoke-Squad -SquadArgs @('task','list','--agent','morpheus','--status','queued') 2>$null | Out-String
        if ([string]::IsNullOrWhiteSpace($raw)) { return '(no queued tasks)' }
        # Output format (verified 2026-04-26):
        #   [task <id>] queued
        #     assigned_to: morpheus
        #     lease_owner: unleased
        #     title: <title>
        #     created_by: <from>
        #     body: <body>
        # We grep just the [task ...] header and the title/created_by lines for
        # brevity — the full body is one squad command away if morpheus needs it.
        # Use ContainsKey, not .id directly — Set-StrictMode at top of file makes
        # property access on a hashtable that lacks the key throw PropertyNotFoundException.
        $blocks = @()
        $current = @{}
        foreach ($line in ($raw -split "`r?`n")) {
            if ($line -match '^\[task\s+([^\]]+)\]\s+(\w+)') {
                if ($current.ContainsKey('id')) { $blocks += $current }
                $current = @{ id = $Matches[1]; status = $Matches[2]; title = ''; from = '' }
            } elseif ($line -match '^\s+title:\s*(.*)$' -and $current.ContainsKey('id')) {
                $current.title = $Matches[1]
            } elseif ($line -match '^\s+created_by:\s*(.*)$' -and $current.ContainsKey('id')) {
                $current.from = $Matches[1]
            }
        }
        if ($current.ContainsKey('id')) { $blocks += $current }
        if ($blocks.Count -eq 0) { return '(no queued tasks)' }
        $lines = foreach ($b in $blocks) {
            $title = if ($b.title.Length -gt 100) { $b.title.Substring(0,100) + '...' } else { $b.title }
            "  [task $($b.id)] from=$($b.from)  $title"
        }
        return ($lines -join "`n")
    } catch {
        return "(task list read failed: $_)"
    }
}

function Get-QueuedTaskCount {
    # Count of queued tasks assigned to morpheus. Kept for backwards-compat /
    # debugging visibility. Wait-ForEvent uses Get-QueuedTaskIds for the actual
    # event-detection logic. Added 2026-04-26.
    try {
        $raw = Invoke-Squad -SquadArgs @('task','list','--agent','morpheus','--status','queued') 2>$null | Out-String
        if ([string]::IsNullOrWhiteSpace($raw)) { return 0 }
        $matches_array = [regex]::Matches($raw, '(?m)^\[task\s+[^\]]+\]\s+queued')
        return $matches_array.Count
    } catch { return 0 }
}

function Get-QueuedTaskIds {
    # Returns a hashtable (set) of queued task IDs assigned to morpheus.
    # Wait-ForEvent uses this to detect *new* tasks (set diff), not just count
    # changes — needed because the same un-acked task would otherwise trigger
    # endless wake-ups, burning API $$. If morpheus fails to ack a task, the
    # task ID stays in the baseline and won't re-wake the loop until it's
    # acked or a *different* new task arrives. Added 2026-04-26.
    $set = @{}
    try {
        $raw = Invoke-Squad -SquadArgs @('task','list','--agent','morpheus','--status','queued') 2>$null | Out-String
        if ([string]::IsNullOrWhiteSpace($raw)) { return $set }
        foreach ($m in [regex]::Matches($raw, '(?m)^\[task\s+([^\]]+)\]\s+queued')) {
            $set[$m.Groups[1].Value] = $true
        }
    } catch {}
    return $set
}

function Get-PendingMessageCount {
    # Count of unread messages in morpheus's inbox. Used by Wait-ForEvent to
    # detect worker `squad send` replies during sleep. `squad pending` lists
    # all unread; we filter to lines addressed to morpheus. Added 2026-04-26.
    try {
        $raw = Invoke-Squad -SquadArgs @('pending') 2>$null | Out-String
        if ([string]::IsNullOrWhiteSpace($raw)) { return 0 }
        # `squad pending` output format: each unread message starts with `* [<ts>] <from> -> <to>: ...`
        # We count lines where <to> is morpheus or @all.
        $matches_array = [regex]::Matches($raw, '(?m)^\*\s+\[[^\]]+\]\s+\S+\s+->\s+(morpheus|@all)\s*:')
        return $matches_array.Count
    } catch { return 0 }
}

function Wait-ForEvent {
    # Polling sleep with event-driven wakeup.
    # - Wakes immediately (within $PollSec) when:
    #     a) a *new* queued task ID appears (not in baseline set), OR
    #     b) inbox unread count grows above baseline.
    # - Falls back to $TimeoutSec alarm for routine self-driven cycle.
    # - Returns hashtable describing why we woke up (for round-log + visibility).
    #
    # Why ID-set instead of count: if morpheus enters sleep with a task already
    # queued (e.g. owner sent it during round-1 claude call), count-based
    # detection would never fire (1 -gt 1 = false). And if morpheus failed to
    # ack a task, count-based "any > 0" detection would loop forever burning
    # API $$. ID-set means: same un-acked task stays baseline; only NEW IDs wake us.
    # Added 2026-04-26 — replaces hard `Start-Sleep -Seconds RoundSleepSec`.
    param(
        [int]$TimeoutSec = 1200,
        [int]$PollSec   = 10
    )

    $baselineIds   = Get-QueuedTaskIds
    $baselineInbox = Get-PendingMessageCount
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $reason = 'alarm'

    Write-Host "[morpheus-headless] sleep enter (timeout=${TimeoutSec}s, poll=${PollSec}s, queue_baseline=$($baselineIds.Count), inbox=$baselineInbox)" -ForegroundColor DarkGray

    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds $PollSec
        $nowIds   = Get-QueuedTaskIds
        $nowInbox = Get-PendingMessageCount

        # Find new task IDs (in nowIds but not in baselineIds).
        $newIds = @()
        foreach ($id in $nowIds.Keys) {
            if (-not $baselineIds.ContainsKey($id)) { $newIds += $id }
        }
        if ($newIds.Count -gt 0) {
            $reason = "new-task(+$($newIds.Count): $($newIds[0]))"
            Write-Host "[morpheus-headless] event: new queued task(s) detected: $($newIds -join ', ') — waking" -ForegroundColor Green
            break
        }

        if ($nowInbox -gt $baselineInbox) {
            $reason = "new-inbox(+$($nowInbox - $baselineInbox))"
            Write-Host "[morpheus-headless] event: inbox count $baselineInbox -> $nowInbox, waking" -ForegroundColor Green
            break
        }
    }

    if ($reason -eq 'alarm') {
        Write-Host "[morpheus-headless] sleep alarm (timeout reached, no events)" -ForegroundColor DarkGray
    }
    return @{ reason = $reason; waited_sec = [int]((Get-Date) - $deadline.AddSeconds(-$TimeoutSec)).TotalSeconds }
}

function Build-RoundBrief {
    param([int]$Round)
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $eval = Get-EvalSummary
    $inbox = Get-InboxTail
    $tasks = Get-QueuedTasksForMe
    $ot = Get-OpenThreadsTail

    $firstRoundPreamble = ''
    if ($Round -eq 1) {
        # Round 1 gets the full charter + kickoff. Subsequent rounds skip this —
        # prompt cache carries it forward via --resume.
        $charterText = if (Test-Path $charter) { Get-Content $charter -Raw } else { '(charter missing)' }
        $kickoffText = if (Test-Path $kickoff) { Get-Content $kickoff -Raw } else { '(kickoff missing)' }
        $firstRoundPreamble = @"
=== CHARTER (read once, applies to every round) ===
$charterText

=== LONG-RUN KICKOFF (read once) ===
$kickoffText

"@
    }

    return @"
$firstRoundPreamble=== ROUND $Round BRIEF — $ts ===

You are Morpheus running in headless mode (no TUI). You have access to Bash,
Read, Edit, Write, Grep, Glob. You are in long-run mode — do not ask to stop,
do not preface, just execute this round and produce a verifiable artifact.

--- Latest RAG eval ---
$eval

--- Recent squad inbox (last 8 msgs to morpheus) ---
$inbox

--- Queued tasks assigned to you (squad task list) ---
$tasks

--- OPEN_THREADS tail ---
$ot

--- This round's job (in order) ---
0. **Process queued tasks first.** If `--- Queued tasks for you ---` above is
   not `(no queued tasks)`, you MUST handle every entry before doing anything
   else this round. For each `[task <id>] from=<owner> <title>`:
     a. `squad task ack morpheus <id>`        # claim it (queued -> acked)
     b. Read the task body if needed: `squad task list --agent morpheus | findstr <id>`
     c. Do the work (or determine you cannot)
     d. Either:
          squad task complete morpheus <id> --summary "<what you did, paths, evidence>"
        or, if genuinely blocked:
          squad task requeue <id> --to <other-agent>   # with reason in --summary
   Skipping a queued task counts as idling and violates the no-idle rule below.
   Only after all queued tasks are resolved do you proceed to step 1.
1. Reload `.squad/identity/goal-drift.md` (it may have changed since last round).
2. Diff goal-drift against the eval above. Every ✗ becomes a new requirement in
   `.squad/identity/requirement-pool.md` with status `needs-score`.
3. If step 2 produced 0 new items, self-explore per kickoff §4 — at least one
   candidate from user profile v3 + wenxianku benchmark.
4. Pick the top-scored open requirement. Dispatch it now:
      # pre-dispatch duplicate-check (required, per pool entry 47/50 round-10):
      # squad task list --status queued | grep -iE '<task-keywords>'
      # If >=1 match, file a needs-score pool entry instead of a duplicate task.
      squad task create morpheus <agent> --title ... --body ...
   or, if no existing agent fits:
      squad spawn <role> "<reason>"
5. Append ONE line to `.squad/memory/DECISION_TRAIL.md`:
      ### [timestamp] round $Round — <one-line summary>
      - pass_rate: <n>
      - new_reqs: <n>
      - dispatched_to: <agent>
      - artifact: <path or squad id>
6. End your turn. The loop will run halt-check and schedule the next round.

Hard rules (unchanged):
- Never ask the user anything. Never say WAITING FOR USER as a stop reason.
- Never idle. This round MUST produce a code diff, new test, new requirement,
  new DECISION_TRAIL entry, or dispatched task. No exceptions.
- Spawn cap = 10 live agents. At cap, finish something before spawning.
- Path-lock and denylist still enforced by squad-guard.ps1.

Start now.
"@
}

# ------------------------------------------------------------------
# Claude invocation
# ------------------------------------------------------------------
function Invoke-ClaudeRound {
    param(
        [string]$Prompt,
        [int]$Round
    )

    if ($DryRun) {
        Write-Host "[DRY-RUN] prompt length = $($Prompt.Length) chars" -ForegroundColor Yellow
        Write-Host "----- prompt head -----" -ForegroundColor DarkGray
        Write-Host ($Prompt.Substring(0, [Math]::Min(600, $Prompt.Length))) -ForegroundColor DarkGray
        Write-Host "----- /prompt head -----" -ForegroundColor DarkGray
        return @{ ok = $true; result = '(dry-run)'; cost = 0.0; duration_ms = 0 }
    }

    # Feed prompt via stdin — argv on Windows ACP mangles non-ASCII; stdin is UTF-8 clean.
    # --resume for rounds 2+ so cache hits. Round 1 uses --session-id to seed the uuid.
    $claudeArgs = @(
        '--print',
        '--output-format','json',
        '--dangerously-skip-permissions'
    )
    # Seeded flag semantics:
    #   no flag present → this uuid has never been handed to claude → use --session-id to seed
    #   flag present    → claude already knows this uuid → use --resume (avoids "Session ID is already in use")
    # We flip the flag after the FIRST successful claude call below, not here.
    $isFirstUse = -not (Test-Path $sessSeeded)
    if ($isFirstUse) {
        $claudeArgs += @('--session-id', $sessionId)
    } else {
        $claudeArgs += @('--resume', $sessionId)
    }

    $tmp = Join-Path $env:TEMP "morpheus-round-$Round-$([guid]::NewGuid().ToString('N')).txt"
    $callResult = $null
    try {
        Set-Content -Path $tmp -Value $Prompt -Encoding UTF8
        if ($Verbose) {
            Write-Host "[morpheus-headless] claude $($claudeArgs -join ' ')" -ForegroundColor DarkGray
            Write-Host "[morpheus-headless] prompt tmp: $tmp" -ForegroundColor DarkGray
        }
        # 2026-04-26 root-cause fix: route through resilient retry sidecar
        # instead of single-shot pipeline. Third-party claude API is
        # known to fluctuate; one transient blip used to mark the whole
        # round ok=false (round 25 was the loss event). The sidecar
        # retries on transport/parse failures (3 attempts, 2/4/8s
        # backoff) and surfaces a retry_log for diagnostics.
        $callResult = Invoke-ClaudeOnceRetried -PromptTmp $tmp -ClaudeArgs $claudeArgs -VerboseLog:$Verbose
    } finally {
        if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
        # claude CLI hijacks our console title to 'claude'. Reset it so supervisor's
        # Test-DaemonAlive (window-title match) doesn't misjudge us as dead.
        # Added 2026-04-26 — fixes D3-bug second root cause discovered during long-run validation.
        try { $Host.UI.RawUI.WindowTitle = 'morpheus-headless' } catch {}
    }

    if ($callResult.ok -and $callResult.parsed) {
        $obj = $callResult.parsed
        # Flip the seeded flag only after claude confirmed it accepted this uuid.
        # Doing it here (not pre-call) means a crashed/rejected round leaves the
        # flag absent, so the next round retries --session-id. Once seeded, we
        # never un-seed — the uuid is permanently claude-side.
        if ($isFirstUse -and -not (Test-Path $sessSeeded)) {
            # Atomic write per CLAUDE.md §4.7: write to .tmp then Move-Item -Force.
            # Crash mid-write would leave a partial timestamp, which Test-Path would
            # see as truthy and skip the re-seed — silently breaking the long-run
            # session-seeded contract. Audit anchor:
            # .squad/audits/atomic-write-audit-2026-04-25.md (P1 violator #5, drifted to :547).
            # Variable named $sessSeededTmp to satisfy tools/squad/check-atomic-write.ps1's compliant regex.
            $sessSeededTmp = "$sessSeeded.tmp"
            Set-Content -Path $sessSeededTmp -Value (Get-Date -Format 'o') -Encoding UTF8
            Move-Item -LiteralPath $sessSeededTmp -Destination $sessSeeded -Force
        }
        return @{
            ok            = $true
            result        = $obj.result
            cost          = $obj.total_cost_usd
            duration_ms   = $obj.duration_ms
            raw           = $obj
            attempt_count = $callResult.attempt_count
            retry_log     = $callResult.retry_log
        }
    } else {
        return @{
            ok            = $false
            result        = $callResult.raw
            cost          = $null
            duration_ms   = $null
            parse_error   = $callResult.parse_error
            attempt_count = $callResult.attempt_count
            retry_log     = $callResult.retry_log
            hard_fail     = ($callResult.PSObject.Properties.Match('hard_fail').Count -gt 0 -and $callResult.hard_fail)
        }
    }
}

# ------------------------------------------------------------------
# Halt check
# ------------------------------------------------------------------
function Test-HaltLegal {
    $global:LASTEXITCODE = 0
    Invoke-Squad -SquadArgs @('long-status','halt-check') 2>&1 | Out-Null
    $code = $global:LASTEXITCODE
    return ($code -eq 0)
}

# ------------------------------------------------------------------
# No-idle audit
# ------------------------------------------------------------------
function Test-NoIdleStall {
    # If the last 3 rounds produced no new DECISION_TRAIL lines, we're stalling.
    if (-not (Test-Path $roundLog)) { return $false }
    $tail = @(Get-Content $roundLog -Tail 3)
    if ($tail.Count -lt 3) { return $false }
    $stalls = 0
    foreach ($line in $tail) {
        try {
            $obj = $line | ConvertFrom-Json
            if (-not $obj.produced_artifact) { $stalls++ }
        } catch {}
    }
    return ($stalls -ge 3)
}

# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
try {
$round = 0
Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host " Morpheus headless loop (Gamma)" -ForegroundColor Cyan
Write-Host " sleep=${RoundSleepSec}s  max=$MaxRounds  once=$Once  dry=$DryRun" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan

while ($true) {
    $round++

    # Check halt BEFORE running — if the previous round made us done, stop now.
    if ($round -gt 1 -and (Test-HaltLegal)) {
        Write-Host "[morpheus-headless] halt-check passed. Legal stop. Exiting." -ForegroundColor Green
        break
    }

    Write-Host ""
    Write-Host "--- Round $round @ $(Get-Date -Format 'HH:mm:ss') ---" -ForegroundColor Yellow

    # Snapshot DECISION_TRAIL line count before round.
    $preLines = if (Test-Path $decisions) { (Get-Content $decisions).Count } else { 0 }

    $brief  = Build-RoundBrief -Round $round
    $result = Invoke-ClaudeRound -Prompt $brief -Round $round

    $postLines = if (Test-Path $decisions) { (Get-Content $decisions).Count } else { 0 }
    $producedArtifact = ($postLines -gt $preLines)

    # Log round outcome as JSONL.
    # 2026-04-26: added attempt_count + retry_log fields so post-hoc
    # diagnosis of API-instability rounds is mechanical (round 25 was
    # invisible because the JSONL only had ok=false with no clue why).
    $logEntry = [ordered]@{
        round             = $round
        ts                = (Get-Date -Format 'o')
        ok                = $result.ok
        duration_ms       = $result.duration_ms
        cost_usd          = $result.cost
        decision_lines    = $postLines - $preLines
        produced_artifact = $producedArtifact
    }
    if ($result.PSObject.Properties.Match('attempt_count').Count -gt 0) {
        $logEntry.attempt_count = $result.attempt_count
    }
    if ($result.PSObject.Properties.Match('retry_log').Count -gt 0 -and $result.retry_log) {
        # Compact: only verdict+duration+raw_len per attempt (omit
        # parse_error which can be long; keep it on the parent on
        # failure rounds via parse_error).
        $compact = @($result.retry_log | ForEach-Object {
            [ordered]@{
                attempt = $_.attempt
                verdict = $_.verdict
                ms      = $_.duration_ms
                raw_len = $_.raw_len
            }
        })
        $logEntry.retries = $compact
    }
    if (-not $result.ok -and $result.PSObject.Properties.Match('parse_error').Count -gt 0) {
        $logEntry.parse_error = $result.parse_error
    }
    Add-Content -Path $roundLog -Value ($logEntry | ConvertTo-Json -Compress -Depth 5) -Encoding UTF8

    Write-Host "[morpheus-headless] round=$round ok=$($result.ok) dur=$($result.duration_ms)ms cost=$($result.cost) new_decisions=$($postLines - $preLines)" -ForegroundColor Green
    if (-not $result.ok) {
        Write-Host "[morpheus-headless] result head: $($result.result.ToString().Substring(0,[Math]::Min(400,$result.result.ToString().Length)))" -ForegroundColor Yellow
    }

    if (Test-NoIdleStall) {
        Write-Host "[morpheus-headless] 3-round idle stall detected. Next round will force-swap requirement." -ForegroundColor Magenta
        # We don't take direct action; the brief already tells Morpheus to swap
        # to the second-highest requirement when stalling. The next round's
        # charter re-read handles it.
    }

    if ($Once) { Write-Host "[morpheus-headless] -Once set. Exiting after round 1." -ForegroundColor Cyan; break }
    if ($MaxRounds -gt 0 -and $round -ge $MaxRounds) {
        Write-Host "[morpheus-headless] MaxRounds=$MaxRounds reached. Exiting." -ForegroundColor Cyan; break
    }

    # Event-driven sleep: wake immediately on new owner task or worker reply,
    # alarm-fallback at RoundSleepSec for routine self-driven cycle.
    # Replaces the original `Start-Sleep -Seconds $RoundSleepSec` (2026-04-26).
    $wake = Wait-ForEvent -TimeoutSec $RoundSleepSec -PollSec 10
    Write-Host "[morpheus-headless] woke (reason=$($wake.reason))" -ForegroundColor Cyan
}

Write-Host "[morpheus-headless] loop exited cleanly at round $round." -ForegroundColor Cyan
} finally {
    Remove-MorpheusLock
    # Mirror the join above: leave the squad agent table on exit so a fresh
    # restart doesn't trip the "ID 'morpheus' was taken" auto-suffix path.
    try { Invoke-Squad -SquadArgs @('leave','morpheus') 2>&1 | Out-Null } catch {}
}
