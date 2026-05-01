# commands/long.ps1 — `squad long-run / long-stop / long-status` subcommands.
#
# Thin dispatcher. Heavy lifting stays in:
#   - start-long-run.ps1   (already written, unmodified)
#   - squad-cleanup.ps1    (already written, unmodified)
#   - supervisor.ps1       (new, process self-heal — hardening #1)
#   - long-status-check.ps1 (new, stop-condition auditor — hardening #3)
#
# Usage:
#   squad long-run               # full stack (watcher + sweeper + eval daemon + morpheus)
#   squad long-run --supervised  # same + supervisor that restarts dead daemons
#   squad long-run --no-morpheus # only daemons, no claude window
#   squad long-stop              # kill agent windows + live-agent markers
#   squad long-status            # dashboard: are daemons up? last eval? stop-ready?
#   squad long-status --halt-check  # machine-readable: can we legally halt?

function Invoke-SquadLong {
    param(
        [Parameter(Mandatory)] [string]$SubCmd,   # 'run' | 'stop' | 'status'
        [Parameter(Mandatory)] [string]$RepoRoot,
        [string[]]$CmdArgs = @()
    )

    $squadDir     = Join-Path $RepoRoot 'tools\squad'
    $startScript  = Join-Path $squadDir 'start-long-run.ps1'
    $stopScript   = Join-Path $squadDir 'squad-cleanup.ps1'
    $statusScript = Join-Path $squadDir 'long-status-check.ps1'
    $supervisor   = Join-Path $squadDir 'supervisor.ps1'

    switch ($SubCmd) {

        'run' {
            $startArgs = @{}
            # Default supervised=ON (2026-04-26): user wants `squad long-run` to
            # be one-button — supervisor + dispatcher onboarding included by default.
            # Use --no-supervised to opt out (e.g. CI / automated tests that don't
            # want a supervisor window).
            $supervised = $true

            # Normalize $CmdArgs: under Set-StrictMode -Latest, accessing .Count
            # on $null throws PropertyNotFoundStrict. Zero-arg `squad long-run`
            # passes $null through, so wrap it. (Bug surfaced 2026-04-26 once
            # default-supervised made zero-arg the common path.)
            $CmdArgs = @($CmdArgs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

            $i = 0
            while ($i -lt $CmdArgs.Count) {
                $a = $CmdArgs[$i]
                switch -Regex ($a) {
                    '^--supervised$'        { $supervised = $true }
                    '^--no-supervised$'     { $supervised = $false }
                    '^--no-morpheus$'       { $startArgs.SkipMorpheus   = $true }
                    '^--no-autopilot$'      { $startArgs.SkipAutopilot  = $true }
                    '^--no-eval-daemon$'    { $startArgs.SkipEvalDaemon = $true }
                    '^--interactive$'       { $startArgs.Interactive    = $true }
                    '^--eval-every$'        { $i++; $startArgs.EvalEveryMinutes = [int]$CmdArgs[$i] }
                    '^--round-sleep$'       { $i++; $startArgs.RoundSleepSec    = [int]$CmdArgs[$i] }
                    '^-h$|^--help$' {
                        Write-Host @'
squad long-run — start long-task execution mode.

Flags:
  --supervised         (default ON) start supervisor.ps1 + register dispatcher.
  --no-supervised      Opt out of supervisor + dispatcher onboarding.
  --no-morpheus        Do not launch the Morpheus loop / window.
  --no-autopilot       Do not start watcher/sweeper.
  --no-eval-daemon     Do not start the RAG eval daemon.
  --interactive        Use TUI claude window instead of the headless loop (legacy).
  --eval-every <min>   How often RAG eval runs (default 30).
  --round-sleep <sec>  Seconds between Morpheus headless rounds (default 1200).

Default (unattended): starts morpheus-headless.ps1 — one prompt per round via
`claude --print`, inheriting your shell permissions. No further input needed.
'@
                        return 0
                    }
                    default { [Console]::Error.WriteLine("unknown flag: $a"); return 2 }
                }
                $i++
            }

            if (-not (Test-Path $startScript)) {
                [Console]::Error.WriteLine("start-long-run.ps1 missing at $startScript")
                return 4
            }

            & $startScript @startArgs

            if ($supervised) {
                if (-not (Test-Path $supervisor)) {
                    Write-Host "[long-run] supervisor requested but $supervisor missing — skipping." -ForegroundColor Yellow
                } else {
                    Write-Host "[long-run] starting supervisor (auto-heal every 60s)..." -ForegroundColor Green
                    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
                        '-NoExit',
                        '-ExecutionPolicy','Bypass',
                        '-Command', "`$Host.UI.RawUI.WindowTitle = 'squad-supervisor'; & '$supervisor' -Loop"
                    ) -WindowStyle Minimized | Out-Null
                }

                # Auto-register the calling terminal as 'owner' so the user can
                # immediately `squad send owner morpheus "..."` or `squad tell "..."`
                # without having to remember the join boilerplate.
                # Added 2026-04-26 — closes the dispatcher-onboarding gap.
                # 2026-04-26: bypass squad.cmd shim by calling squad-real.exe directly.
                # Identity-lock guard added 2026-04-26: previously this path joined
                # owner unconditionally, producing owner-2 / owner-3 if a previous
                # dispatcher was still registered. Use Acquire-SquadIdentity (which
                # purges dead-PID locks before joining) so re-running long-run never
                # produces suffixed dispatchers.
                $squadCli = 'C:\Tools\squad\squad-real.exe'
                if (Test-Path $squadCli) {
                    Write-Host ""
                    Write-Host "[long-run] registering this terminal as squad agent 'owner' (dispatcher)..." -ForegroundColor Green
                    $lockMod = Join-Path $squadDir 'squad-lock.ps1'
                    if (Test-Path $lockMod) {
                        . $lockMod
                        $ownerAcq = Acquire-SquadIdentity -Role 'owner' -RealCli $squadCli
                        if (-not $ownerAcq.ok) {
                            Write-Host "  owner identity already held by PID $($ownerAcq.pid) — dispatcher onboarding skipped." -ForegroundColor Yellow
                            Write-Host "  (the existing dispatcher terminal can keep using `squad tell`/`send`.)" -ForegroundColor DarkGray
                        }
                    } else {
                        # Fallback to raw join if squad-lock.ps1 is missing (shouldn't happen).
                        & $squadCli join owner --role owner --client claude --protocol-version 2 2>&1 | Out-Null
                    }
                    # Pin dispatcher id to .squad/state so `squad tell` knows who to send-as.
                    $dispDir = Join-Path $RepoRoot '.squad\state'
                    if (-not (Test-Path $dispDir)) { New-Item -ItemType Directory -Path $dispDir -Force | Out-Null }
                    Set-Content -Path (Join-Path $dispDir 'dispatcher.txt') -Value 'owner' -Encoding UTF8
                    Write-Host ""
                    Write-Host "Dispatcher ready. You can now type:" -ForegroundColor Cyan
                    Write-Host "  squad tell `"<your task>`"                       # short form (auto-routes to morpheus)" -ForegroundColor White
                    Write-Host "  squad send owner morpheus `"<your task>`"        # long form" -ForegroundColor DarkGray
                    Write-Host "  squad agents                                   # see who is online" -ForegroundColor DarkGray
                    Write-Host "  squad pending                                  # check unread messages" -ForegroundColor DarkGray
                    Write-Host ""
                }
            }
            return 0
        }

        'stop' {
            $stopArgs = @{}
            $dryRun = $false
            foreach ($a in $CmdArgs) {
                switch -Regex ($a) {
                    '^--nuke$'   { $stopArgs.Nuke   = $true }
                    '^--dry-run$'{ $stopArgs.DryRun = $true; $dryRun = $true }
                }
            }

            if (-not (Test-Path $stopScript)) {
                [Console]::Error.WriteLine("squad-cleanup.ps1 missing at $stopScript")
                return 4
            }
            & $stopScript @stopArgs

            # ----- self-protect: build PID chain from current shell up to root -----
            # NEVER kill ourselves, our shell parent, claude-code (the dispatch terminal),
            # WindowsTerminal/wt, conhost, explorer, etc.
            $selfChain = @{}
            $cur = $PID
            for ($i = 0; $i -lt 12; $i++) {
                if (-not $cur -or $cur -le 4) { break }
                $selfChain[$cur] = $true
                try {
                    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction Stop
                    if (-not $p -or -not $p.ParentProcessId) { break }
                    $cur = [int]$p.ParentProcessId
                } catch { break }
            }
            # Also exempt all live claude.exe processes (Claude Code dispatcher) by PID.
            Get-Process -Name claude -ErrorAction SilentlyContinue | ForEach-Object {
                if ($_.Path -and $_.Path -like '*claude-code*') { $selfChain[$_.Id] = $true }
            }

            # Graceful agent-table eviction BEFORE force-kill. Force-kill skips the
            # script's `finally { squad leave }`, which leaves stale entries in the
            # agent registry. The next time supervisor or long-run starts morpheus,
            # `squad join morpheus` collides on the stale name and auto-suffixes to
            # `morpheus-2` — breaking task routing. So we evict here, before the kill.
            # Added 2026-04-26 — symmetric with supervisor's pre-restart leave.
            if (-not $dryRun) {
                # 2026-04-26: bypass squad.cmd shim by calling squad-real.exe directly.
                $squadCli = 'C:\Tools\squad\squad-real.exe'
                if (Test-Path $squadCli) {
                    foreach ($agentId in @('morpheus','morpheus-2','morpheus-3','morpheus-4','morpheus-5')) {
                        try { & $squadCli leave $agentId 2>&1 | Out-Null } catch {}
                    }
                }
            }

            # Also try to kill our named background windows.
            # morpheus-headless added 2026-04-26 (was missing from kill list).
            # --dry-run now also gates this loop (was not before — bug fix 2026-04-26).
            # Self-chain whitelist added 2026-04-26 — never kill the dispatch terminal or its ancestors.
            foreach ($title in @('squad-watcher','squad-sweeper','rag-eval-daemon','squad-supervisor','morpheus-headless')) {
                Get-Process -Name 'powershell','pwsh' -ErrorAction SilentlyContinue |
                    Where-Object { $_.MainWindowTitle -eq $title } |
                    ForEach-Object {
                        if ($selfChain.ContainsKey($_.Id)) {
                            Write-Host "[long-stop] REFUSE kill $title (pid=$($_.Id)) — protected (self/ancestor/dispatcher)" -ForegroundColor Magenta
                            return
                        }
                        if ($dryRun) {
                            Write-Host "[long-stop] [DRY] would kill $title (pid=$($_.Id))" -ForegroundColor DarkCyan
                        } else {
                            Write-Host "[long-stop] killing $title (pid=$($_.Id))" -ForegroundColor DarkYellow
                            try { Stop-Process -Id $_.Id -Force -ErrorAction Stop } catch {}
                        }
                    }
            }

            # Clear stale lock files so the next `long-run` starts from a clean slate.
            # Without this, supervisor's first heal-pass sees an old lock pointing to a
            # dead PID, judges the daemon dead, and spawns a duplicate alongside the
            # one start-long-run is in the process of starting.
            # Added 2026-04-26 — second half of daemon-twin bug fix.
            # 2026-04-26: morpheus.lock added — see squad-lock.ps1. Identity lock
            # is cleared on long-stop so the next `claude /squad morpheus` (manual
            # mode) or `squad long-run` (headless mode) can take the name without
            # tripping anti-collision dead-PID detection on a still-readable file.
            if (-not $dryRun) {
                $lockDir = Join-Path $RepoRoot '.squad\state'
                foreach ($lockName in @('squad-watcher.lock','squad-sweeper.lock','rag-eval-daemon.lock','morpheus-headless.lock','morpheus.lock')) {
                    $lp = Join-Path $lockDir $lockName
                    if (Test-Path $lp) {
                        Remove-Item -Path $lp -Force -ErrorAction SilentlyContinue
                        Write-Host "[long-stop] cleared stale lock $lockName" -ForegroundColor DarkGray
                    }
                }
            }

            return 0
        }

        'status' {
            if (-not (Test-Path $statusScript)) {
                [Console]::Error.WriteLine("long-status-check.ps1 missing at $statusScript")
                return 4
            }
            # Translate flags. Accept both POSIX (--halt-check) and bareword (halt-check)
            # forms since PowerShell's parent param block can consume leading `--` args.
            $splat = @{}
            foreach ($a in $CmdArgs) {
                switch -Regex ($a) {
                    '^(--)?halt-check$' { $splat.HaltCheck = $true }
                    '^(--)?json$'       { $splat.Json      = $true }
                }
            }
            # Pass the call straight through. Do NOT return — leave the exit code in
            # $global:LASTEXITCODE for squad.ps1 to forward. Returning would pollute
            # the output stream with an int next to the child's JSON.
            $global:LASTEXITCODE = 0
            & $statusScript @splat
            return
        }

        default {
            [Console]::Error.WriteLine("unknown long subcommand: $SubCmd")
            return 2
        }
    }
}
