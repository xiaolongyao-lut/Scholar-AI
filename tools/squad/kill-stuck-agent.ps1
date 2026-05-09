# kill-stuck-agent.ps1 — Detect stuck agents by heartbeat, kill the window,
# and requeue their unfinished tasks to another agent.
#
# Usage (one-shot check):
#   .\tools\squad\kill-stuck-agent.ps1
#   .\tools\squad\kill-stuck-agent.ps1 -StaleMinutes 5 -ReassignTo morpheus
#
# Usage (loop mode, run alongside spawn-watcher):
#   .\tools\squad\kill-stuck-agent.ps1 -Loop

param(
    [int]$StaleMinutes  = 10,
    [string]$ReassignTo = 'morpheus',
    [switch]$Loop,
    [int]$LoopSleepSec  = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'squad-guard.ps1')

$projectRoot = Get-ProjectRoot
$squadExe    = 'C:\Tools\squad\squad-real.exe'  # 2026-04-26: bypass squad.cmd shim to avoid recursion
$markerDir   = Join-Path $projectRoot '.squad\autopilot-logs\live-agents'
$idleReaperMinutes = 30

# Override thresholds from .squad/casting-policy.json if present.
$policyPath = Join-Path $projectRoot '.squad\casting-policy.json'
if (Test-Path $policyPath) {
    try {
        $policy = Get-Content $policyPath -Raw | ConvertFrom-Json
        if ($policy.execution_profile.auto_close_idle_seconds) {
            $policyIdleMin = [math]::Max(1, [int]([int]$policy.execution_profile.auto_close_idle_seconds / 60))
            # Only tighten if not explicitly overridden via -StaleMinutes.
            if (-not $PSBoundParameters.ContainsKey('StaleMinutes')) { $StaleMinutes = $policyIdleMin }
            $idleReaperMinutes = [math]::Max($policyIdleMin, $idleReaperMinutes / 2)
        }
    } catch {}
}

function Get-ProcessCpuSeconds {
    param([int]$ProcessId)

    if ($ProcessId -le 0) { throw 'process id must be positive' }
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    return [double]$proc.CPU
}

function Test-IdleProcess {
    param([int]$ProcessId)

    if ($ProcessId -le 0) { throw 'process id must be positive' }
    $before = Get-ProcessCpuSeconds -ProcessId $ProcessId
    if ($null -eq $before) { return $false }

    Start-Sleep -Seconds 2

    $after = Get-ProcessCpuSeconds -ProcessId $ProcessId
    if ($null -eq $after) { return $false }

    return (($after - $before) -lt 1.0)
}

function Stop-AgentProcess {
    param(
        [int]$ProcessId,
        [string]$AgentId,
        [string]$Role,
        [string]$MarkerPath,
        [string]$WrapperStartTime,
        [switch]$RequeueTasks,
        [string]$Reason,
        [string]$LogLevel = 'WARN'
    )

    if ($ProcessId -le 0) { throw 'process id must be positive' }
    if ([string]::IsNullOrWhiteSpace($AgentId)) { throw 'agent id is required' }
    if ([string]::IsNullOrWhiteSpace($MarkerPath)) { throw 'marker path is required' }
    if ([string]::IsNullOrWhiteSpace($Reason)) { throw 'kill reason is required' }

    # Verify identity before kill (defends against PID recycling).
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) {
        Remove-Item $MarkerPath -Force -ErrorAction SilentlyContinue
        return
    }
    $allowedNames = @('powershell','pwsh','WindowsTerminal','wt','claude')
    if ($allowedNames -notcontains $proc.Name) {
        Write-GuardLog -Level WARN -Message 'kill-stuck refused (name not in allowlist)' -Context @{ id = $AgentId; pid = $ProcessId; name = $proc.Name }
        Write-Host "[sweep] REFUSE kill pid=$ProcessId ($AgentId): name=$($proc.Name) not allowed" -ForegroundColor Yellow
        return
    }
    if ($WrapperStartTime) {
        try {
            $expected = [datetime]$WrapperStartTime
            if ([math]::Abs(($proc.StartTime - $expected).TotalSeconds) -gt 5) {
                Write-GuardLog -Level WARN -Message 'kill-stuck refused (StartTime mismatch — PID recycled?)' -Context @{ id = $AgentId; pid = $ProcessId }
                Write-Host "[sweep] REFUSE kill pid=$ProcessId ($AgentId): StartTime mismatch" -ForegroundColor Yellow
                return
            }
        } catch {}
    }

    Write-GuardLog -Level $LogLevel -Message $Reason -Context @{ id = $AgentId; role = $Role; pid = $ProcessId }

    try { Stop-Process -Id $ProcessId -Force -ErrorAction Stop } catch {
        Write-Host "[sweep] kill failed for pid $ProcessId : $_" -ForegroundColor Red
    }

    try { & $squadExe leave $AgentId 2>$null | Out-Null } catch {}

    if ($RequeueTasks) {
        try {
            $openTasks = & $squadExe task list --agent $AgentId --status in_progress 2>$null
            if ($openTasks) {
                $openTasks -split "`n" | Where-Object { $_ -match 'task_[a-zA-Z0-9]+' } | ForEach-Object {
                    $taskId = $matches[0]
                    Write-Host "[sweep] requeueing $taskId -> $ReassignTo" -ForegroundColor Yellow
                    & $squadExe task requeue $taskId --to $ReassignTo 2>$null | Out-Null
                    Write-GuardLog -Level EXEC -Message 'Task requeued' -Context @{ task = $taskId; from = $AgentId; to = $ReassignTo }
                }
            }
        } catch {
            Write-GuardLog -Level WARN -Message 'Requeue failed' -Context @{ id = $AgentId; err = "$_" }
        }
    }

    Remove-Item $MarkerPath -Force -ErrorAction SilentlyContinue
}

function Invoke-Sweep {
    if (-not (Test-Path $markerDir)) { return }
    $markers = @(Get-ChildItem $markerDir -Filter '*.json' -File -ErrorAction SilentlyContinue)
    if (-not $markers) { return }

    foreach ($m in $markers) {
        try {
            $marker = Get-Content $m.FullName -Raw | ConvertFrom-Json
        } catch {
            Write-Host "[sweep] bad marker, removing: $($m.Name)" -ForegroundColor Yellow
            Remove-Item $m.FullName -Force
            continue
        }

        $id        = $marker.id
        $markerPid = $marker.pid
        $role      = $marker.role
        $wstart    = if ($marker.PSObject.Properties.Name -contains 'wrapper_start_time') { $marker.wrapper_start_time } else { $null }

        # 1. Process still alive?
        $proc = Get-Process -Id $markerPid -ErrorAction SilentlyContinue
        if (-not $proc) {
            Write-Host "[sweep] $id already gone (pid $markerPid), removing marker" -ForegroundColor DarkGray
            Remove-Item $m.FullName -Force
            continue
        }

        $markerAgeMin = ((Get-Date) - $m.LastWriteTime).TotalMinutes
        if ($markerAgeMin -gt $idleReaperMinutes -and (Test-IdleProcess -ProcessId $markerPid)) {
            Write-Host "[sweep] idle reaper killed PID $markerPid ($id), marker idle $([math]::Round($markerAgeMin, 1)) min." -ForegroundColor Yellow
            Stop-AgentProcess -ProcessId $markerPid -AgentId $id -Role $role -MarkerPath $m.FullName -WrapperStartTime $wstart -Reason 'idle reaper killed agent' -LogLevel INFO
            continue
        }

        # 2. Heartbeat from squad history: last message/ack timestamp for this id.
        $heartbeatOk = $false
        try {
            $hist = & $squadExe history $id --json 2>$null | ConvertFrom-Json -ErrorAction SilentlyContinue
            if ($hist) {
                $latestEpoch = ($hist | ForEach-Object { [int64]$_.created_at_unix } | Measure-Object -Maximum).Maximum
                if ($latestEpoch) {
                    $ageMin = ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $latestEpoch) / 60
                    if ($ageMin -lt $StaleMinutes) { $heartbeatOk = $true }
                }
            }
        } catch {
            # squad history might not support --json or that id; fall back to marker age
        }

        if (-not $heartbeatOk) {
            $spawnedAt = [datetime]$marker.spawned_at
            $procAgeMin = ((Get-Date) - $spawnedAt).TotalMinutes
            if ($procAgeMin -lt $StaleMinutes) {
                # Newborn, give it grace.
                continue
            }
        } else {
            continue
        }

        # 3. Stuck. Kill and requeue.
        Write-Host "[sweep] $id stuck > $StaleMinutes min. Killing pid $markerPid." -ForegroundColor Red
        Stop-AgentProcess -ProcessId $markerPid -AgentId $id -Role $role -MarkerPath $m.FullName -WrapperStartTime $wstart -RequeueTasks -Reason 'Killing stuck agent'
    }
}

if ($Loop) {
    # Single-instance lock: refuse to start if another -Loop kill-stuck is already running.
    $loopLockDir  = Join-Path $projectRoot '.squad\locks'
    if (-not (Test-Path $loopLockDir)) { New-Item -ItemType Directory -Force -Path $loopLockDir | Out-Null }
    $loopLockPath = Join-Path $loopLockDir 'kill-stuck.lock'
    $loopLock = $null
    try {
        $loopLock = [System.IO.File]::Open($loopLockPath, 'OpenOrCreate', 'ReadWrite', 'None')
    } catch {
        Write-Error "Refusing to start: another kill-stuck-agent -Loop is running ($loopLockPath held)."
        exit 6
    }
    try {
        Write-Host "[kill-stuck] loop mode, every $LoopSleepSec s. Stale threshold = $StaleMinutes min." -ForegroundColor Green
        while ($true) {
            Invoke-Sweep
            Start-Sleep -Seconds $LoopSleepSec
        }
    } finally {
        if ($loopLock) { try { $loopLock.Dispose() } catch {}; Remove-Item -Path $loopLockPath -Force -ErrorAction SilentlyContinue }
    }
} else {
    Invoke-Sweep
    Write-Host "[kill-stuck] one-shot sweep done." -ForegroundColor Green
}
