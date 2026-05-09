# supervisor.ps1 — Process self-heal for long-run daemons.
#
# Watches the three background windows — squad-watcher, squad-sweeper, rag-eval-daemon —
# and if any one is gone, restarts it minimised. No-op when everything is alive.
#
# Detection: by window title (each daemon sets `$Host.UI.RawUI.WindowTitle`).
# Action: Start-Process with the same script and flags used by start-long-run.ps1.
#
# Usage:
#   .\tools\squad\supervisor.ps1           # one-shot heal pass
#   .\tools\squad\supervisor.ps1 -Loop     # heal every 60s (meant for its own window)

param(
    [switch]$Loop,
    [int]$LoopSleepSec = 60,
    [int]$EvalEveryMinutes = 30,
    [int]$RoundSleepSec = 1200
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

. (Join-Path $PSScriptRoot 'squad-guard.ps1')

$scriptDir = $PSScriptRoot
$projectRoot = Get-ProjectRoot
$stateDir = Join-Path $projectRoot '.squad\state'
$restartHistoryPath = Join-Path $stateDir 'supervisor-restart-history.jsonl'
$restartWindowMinutes = 5
$restartLimit = 3
$circuitOpenLogged = @{}

$watcherScript = Join-Path $scriptDir 'spawn-watcher.ps1'
$sweeperScript = Join-Path $scriptDir 'kill-stuck-agent.ps1'
$evalScript    = Join-Path $scriptDir 'rag-eval-daemon.ps1'

$targets = @(
    @{
        title  = 'squad-watcher'
        script = $watcherScript
        args   = @()
    },
    @{
        title  = 'squad-sweeper'
        script = $sweeperScript
        args   = @('-Loop')
    },
    @{
        title  = 'rag-eval-daemon'
        script = $evalScript
        args   = @('-EveryMinutes', "$EvalEveryMinutes")
    },
    @{
          title  = 'morpheus-headless'
          script = (Join-Path $scriptDir 'morpheus-headless.ps1')
          args   = @('-RoundSleepSec', "$RoundSleepSec")
    }
)

if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }

function Get-DaemonLockPath {
    param([string]$Title)

    if ([string]::IsNullOrWhiteSpace($Title)) { throw 'daemon title is required' }
    return (Join-Path $stateDir "$Title.lock")
}

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

function Test-DaemonAlive {
    param([string]$Title)

    $lockPath = Get-DaemonLockPath -Title $Title
    $pidValue = Get-LockPid -Path $lockPath
    if ($null -eq $pidValue) { return $false }

    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }

    # Window-title check removed 2026-04-26 — claude CLI hijacks the console title
    # to 'claude' when daemons spawn it (e.g. morpheus-headless), causing false-dead.
    # Process name + lock-PID match is sufficient: if a foreign process recycled
    # this PID, it would not be powershell/pwsh.
    return ($proc.ProcessName -in @('powershell','pwsh'))
}

function Test-RestartCircuitOpen {
    param([string]$Title)

    if ([string]::IsNullOrWhiteSpace($Title)) { throw 'daemon title is required' }
    $now = Get-Date
    $cutoff = $now.AddMinutes(-1 * $restartWindowMinutes)
    $history = @(Get-RestartHistory -Title $Title | Where-Object { $_ -ge $cutoff })
    return ($history.Count -ge $restartLimit)
}

function Get-RestartHistory {
    param([string]$Title)

    if ([string]::IsNullOrWhiteSpace($Title)) { throw 'daemon title is required' }
    if (-not (Test-Path $restartHistoryPath)) { return @() }

    $entries = @()
    foreach ($line in @(Get-Content -Path $restartHistoryPath -ErrorAction SilentlyContinue)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        try {
            $entry = $line | ConvertFrom-Json
            if (($entry.PSObject.Properties.Name -contains 'daemon') -and
                ($entry.PSObject.Properties.Name -contains 'ts') -and
                $entry.daemon -eq $Title -and
                $entry.ts) {
                $entries += [datetime]$entry.ts
            }
        } catch {}
    }
    return $entries
}

function Register-DaemonRestart {
    param([string]$Title)

    if ([string]::IsNullOrWhiteSpace($Title)) { throw 'daemon title is required' }
    $entry = [ordered]@{
        daemon = $Title
        ts     = (Get-Date).ToString('o')
    }
    Add-Content -Path $restartHistoryPath -Value ($entry | ConvertTo-Json -Compress) -Encoding UTF8
}

function Start-Daemon {
    param([hashtable]$Target)

    if (-not (Test-Path $Target.script)) {
        Write-Host "[supervisor] cannot restart $($Target.title): script missing at $($Target.script)" -ForegroundColor Red
        Write-GuardLog -Level WARN -Message 'Daemon script missing' -Context @{ title = $Target.title; script = $Target.script }
        return
    }

    if (Test-RestartCircuitOpen -Title $Target.title) {
        $context = @{ title = $Target.title; window_minutes = $restartWindowMinutes; restart_limit = $restartLimit }
        Write-Host "[supervisor] circuit open for $($Target.title); restart suppressed." -ForegroundColor Red
        if (-not $circuitOpenLogged.ContainsKey($Target.title)) {
            Write-GuardLog -Level WARN -Message 'Daemon restart circuit open' -Context $context
            $circuitOpenLogged[$Target.title] = $true
        }
        return
    }

    # Before restarting morpheus-headless, evict any stale agent registry entry
    # for 'morpheus' AND clear the identity lock. Otherwise the new process's
    # `squad join morpheus` collides and squad CLI auto-suffixes to `morpheus-2`,
    # breaking task routing (owner's tasks are addressed to `morpheus` but the
    # live process is registered under `morpheus-2`). Handles the case where
    # morpheus died via force-kill, OS crash, etc. — anywhere the script's own
    # `finally { squad leave }` was skipped.
    # 2026-04-26: extended to also clear .squad/state/morpheus.lock so the new
    # headless's Acquire-SquadIdentity call sees a clean slate. Without this
    # step the new process would see the stale lock pointing to the dead PID,
    # call leave + rejoin redundantly (still correct, just noisy).
    if ($Target.title -eq 'morpheus-headless') {
        # 2026-04-26: bypass squad.cmd shim by calling squad-real.exe directly.
        $squadCli = 'C:\Tools\squad\squad-real.exe'
        if (Test-Path $squadCli) {
            try { & $squadCli leave morpheus 2>&1 | Out-Null } catch {}
        }
        $idLock = Join-Path $stateDir 'morpheus.lock'
        if (Test-Path $idLock) {
            Remove-Item -Path $idLock -Force -ErrorAction SilentlyContinue
        }
    }

    $argStr = if ($Target.args.Count -gt 0) { ' ' + ($Target.args -join ' ') } else { '' }
    $cmd = "`$Host.UI.RawUI.WindowTitle = '$($Target.title)'; & '$($Target.script)'$argStr"

    Write-Host "[supervisor] restarting $($Target.title)..." -ForegroundColor Yellow
    $proc = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy','Bypass',
        '-Command', $cmd
    ) -WindowStyle Minimized -PassThru

    Set-Content -Path (Get-DaemonLockPath -Title $Target.title) -Value ([string]$proc.Id) -Encoding UTF8
    Register-DaemonRestart -Title $Target.title

    Write-GuardLog -Level EXEC -Message 'Daemon restarted by supervisor' -Context @{ title = $Target.title; pid = $proc.Id }
}

function Invoke-HealPass {
    foreach ($t in $targets) {
        if (Test-DaemonAlive -Title $t.title) {
            # alive, nothing to do
            continue
        }
        Start-Daemon -Target $t
        Start-Sleep -Milliseconds 500
    }
}

if ($Loop) {
    Write-Host "[supervisor] loop every $LoopSleepSec s. Watching: $($targets.title -join ', ')" -ForegroundColor Green
    Write-GuardLog -Level INFO -Message 'supervisor started' -Context @{ loop_sec = $LoopSleepSec }
    while ($true) {
        try { Invoke-HealPass } catch {
            Write-Host "[supervisor] pass errored: $_" -ForegroundColor Red
            Write-GuardLog -Level WARN -Message 'supervisor pass errored' -Context @{ err = "$_" }
        }
        Start-Sleep -Seconds $LoopSleepSec
    }
} else {
    Invoke-HealPass
    Write-Host "[supervisor] one-shot heal done." -ForegroundColor Green
}
