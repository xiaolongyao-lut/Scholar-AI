# spawn-agent.ps1 — Open a new PowerShell window, cd into the project, start claude,
# and pre-inject /squad <role>. Cap and per-id mutex enforced via file locks under .squad/locks/.
#
# Usage:
#   .\tools\squad\spawn-agent.ps1 -Role morpheus
#   .\tools\squad\spawn-agent.ps1 -Role tank -Id tank-2 -AutoSlash:$false

param(
    [Parameter(Mandatory)] [string]$Role,
    [string]$Id,
    [bool]$AutoStartClaude = $true,
    [bool]$AutoSlash       = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'squad-guard.ps1')

$projectRoot = Get-ProjectRoot

# Read cap from casting-policy.json (fallback to 4 = aggressive default).
$maxAgents = 4
$policyPath = Join-Path $projectRoot '.squad\casting-policy.json'
if (Test-Path $policyPath) {
    try {
        $policy = Get-Content $policyPath -Raw | ConvertFrom-Json
        if ($policy.execution_profile.max_parallel_agents) {
            $maxAgents = [int]$policy.execution_profile.max_parallel_agents
        }
    } catch {}
}

if (-not $Id) { $Id = $Role }

# Circuit breaker pre-check (Finding #12).
$breaker = Test-CircuitBreaker -Scope 'spawn'
if ($breaker.Tripped) {
    Write-GuardLog -Level DENY -Message 'Spawn refused: circuit breaker tripped' -Context @{ id = $Id; until = $breaker.UntilUtc.ToString('o') }
    Write-Error "Refusing to spawn: circuit breaker tripped until $($breaker.UntilUtc.ToString('o')) UTC."
    exit 7
}

# Acquire global spawn lock + per-id mutex with contention backoff (Finding #11).
$lockDir = Join-Path $projectRoot '.squad\locks'
if (-not (Test-Path $lockDir)) { New-Item -ItemType Directory -Force -Path $lockDir | Out-Null }
$globalLockPath = Join-Path $lockDir 'spawn.lock'
$idLockPath     = Join-Path $lockDir "spawn-$Id.lock"

$backoffSec = 20
try {
    if ($policy -and $policy.execution_profile.contention_backoff_seconds) {
        $backoffSec = [int]$policy.execution_profile.contention_backoff_seconds
    }
} catch {}
$maxAttempts = 3

    function Try-OpenExclusive {
        param([string]$Path)
        try { return [System.IO.File]::Open($Path, 'CreateNew', 'ReadWrite', 'None') } catch { return $null }
    }

    function Remove-StaleEmptyLock {
        param([string]$Path)

        if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path $Path)) { return }
        try {
            $info = Get-Item -LiteralPath $Path -ErrorAction Stop
            if ($info.Length -gt 0) { return }

            $handle = [System.IO.File]::Open($Path, 'Open', 'ReadWrite', 'None')
            $handle.Dispose()
            Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
            Write-GuardLog -Level WARN -Message 'Removed stale empty spawn lock' -Context @{ lock = $Path }
        } catch {}
    }

$globalLock = $null
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    if ($attempt -eq 1) { Remove-StaleEmptyLock -Path $globalLockPath }
    $globalLock = Try-OpenExclusive $globalLockPath
    if ($globalLock) { break }
    if ($attempt -lt $maxAttempts) {
        Write-GuardLog -Level INFO -Message 'Global spawn lock contended, backing off' -Context @{ id = $Id; attempt = $attempt; backoffSec = $backoffSec }
        Start-Sleep -Seconds $backoffSec
    }
}
if (-not $globalLock) {
    Record-BreakerOutcome -Outcome failure -Scope 'spawn' -Reason 'global_lock_contention'
    Write-GuardLog -Level DENY -Message 'Spawn refused: global spawn lock held' -Context @{ id = $Id; lock = $globalLockPath; attempts = $maxAttempts }
    Write-Error "Refusing to spawn: another spawn is in flight ($globalLockPath held) after $maxAttempts attempts."
    exit 5
}

$idLock = $null
try {
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        if ($attempt -eq 1) { Remove-StaleEmptyLock -Path $idLockPath }
        $idLock = Try-OpenExclusive $idLockPath
        if ($idLock) { break }
        if ($attempt -lt $maxAttempts) {
            Write-GuardLog -Level INFO -Message 'Per-id lock contended, backing off' -Context @{ id = $Id; attempt = $attempt; backoffSec = $backoffSec }
            Start-Sleep -Seconds $backoffSec
        }
    }
    if (-not $idLock) {
        Record-BreakerOutcome -Outcome failure -Scope 'spawn' -Reason 'duplicate_id'
        Write-GuardLog -Level DENY -Message 'Spawn refused: duplicate id in flight' -Context @{ id = $Id; lock = $idLockPath; attempts = $maxAttempts }
        Write-Error "Refusing to spawn: another spawn for id '$Id' is in flight ($idLockPath held) after $maxAttempts attempts."
        exit 4
    }

    # 1. Enforce cap by counting marker files (now atomic under global lock).
    $markerDir = Join-Path $projectRoot '.squad\autopilot-logs\live-agents'
    if (-not (Test-Path $markerDir)) {
        New-Item -ItemType Directory -Force -Path $markerDir | Out-Null
    }
    $live = @(Get-ChildItem $markerDir -Filter '*.json' -ErrorAction SilentlyContinue)
    if ($live.Count -ge $maxAgents) {
        Record-BreakerOutcome -Outcome failure -Scope 'spawn' -Reason 'cap_reached'
        Write-GuardLog -Level DENY -Message 'Spawn refused: cap reached' -Context @{ role = $Role; id = $Id; live = $live.Count; cap = $maxAgents }
        Write-Error "Refusing to spawn: already $($live.Count) live agents (cap = $maxAgents from policy)."
        exit 2
    }

    # 2. Check role charter exists.
    $rolePath = Join-Path $projectRoot ".squad\roles\$Role.md"
    if (-not (Test-Path $rolePath)) {
        Record-BreakerOutcome -Outcome failure -Scope 'spawn' -Reason 'unknown_role'
        Write-GuardLog -Level DENY -Message 'Spawn refused: unknown role' -Context @{ role = $Role }
        Write-Error "Unknown role '$Role' (no $rolePath). Add the charter or fix the name."
        exit 3
    }

    # 3. Build the child-window command string.
    $claudePath = 'claude'   # on PATH via node-installed CLI
    $slashLine  = "/squad $Id"
    $markerFile = Join-Path $markerDir "$Id.json"

    $banner = @"
=== squad autopilot: spawning agent ===
role: $Role
id:   $Id
project: $projectRoot

Next step: after claude loads, paste this (already on clipboard if supported):
  $slashLine
"@

    # Quote everything for the child session. Includes a PowerShell.Exiting hook
    # so closing the window via X (or claude exit) removes the live-agent marker,
    # and a heartbeat timer (Finding #13) that touches the marker every 20s.
    $childCmd = @"
`$ErrorActionPreference='Continue';
`$env:HOME = `$env:USERPROFILE;
Set-Location '$projectRoot';
Register-EngineEvent PowerShell.Exiting -Action { Remove-Item -Path '$markerFile' -Force -ErrorAction SilentlyContinue } | Out-Null;
`$global:__sqHeartbeatTimer = New-Object System.Timers.Timer 20000;
`$global:__sqHeartbeatTimer.AutoReset = `$true;
Register-ObjectEvent -InputObject `$global:__sqHeartbeatTimer -EventName Elapsed -SourceIdentifier 'SquadHeartbeat' -Action { try { [System.IO.File]::SetLastWriteTimeUtc('$markerFile', [DateTime]::UtcNow) } catch {} } | Out-Null;
`$global:__sqHeartbeatTimer.Start();
Set-Clipboard -Value '$slashLine' -ErrorAction SilentlyContinue;
Write-Host @'
$banner
'@ -ForegroundColor Cyan;
"@

    if ($AutoStartClaude) {
        $childCmd += "& $claudePath;"
    } else {
        $childCmd += "Write-Host 'Autopilot: claude not auto-started (AutoStartClaude=`$false). Run claude manually.' -ForegroundColor Yellow;"
    }

    # 4. Drop a live-agent marker (atomic write) so the cap and cleanup scripts can find it.
    $markerBody = @{
        role         = $Role
        id           = $Id
        spawned_at   = (Get-Date).ToString('o')
        project_root = $projectRoot
        slash        = $slashLine
    } | ConvertTo-Json
    $markerTmp = "$markerFile.tmp"
    Set-Content -Path $markerTmp -Value $markerBody -Encoding UTF8
    Move-Item -Force -Path $markerTmp -Destination $markerFile

    # 5. Launch the window.
    $proc = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy','Bypass',
        '-Command', $childCmd
    ) -PassThru -WindowStyle Normal

    # 6. Record the wrapper PID and its start time (for safe kill verification later).
    $marker = Get-Content $markerFile -Raw | ConvertFrom-Json
    $marker | Add-Member -NotePropertyName pid -NotePropertyValue $proc.Id -Force
    try {
        $marker | Add-Member -NotePropertyName wrapper_start_time -NotePropertyValue ($proc.StartTime.ToString('o')) -Force
    } catch {
        # StartTime may be unavailable for elevated/short-lived procs; not fatal.
    }

    # 6b. Best-effort: locate the actual claude TUI child PID (Finding #3).
    Start-Sleep -Milliseconds 1200
    try {
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($proc.Id)" -ErrorAction SilentlyContinue)
        $claudeChild = $children | Where-Object { $_.Name -match '^(claude|node)(\.exe)?$' } | Select-Object -First 1
        if ($claudeChild) {
            $marker | Add-Member -NotePropertyName claude_pid -NotePropertyValue ([int]$claudeChild.ProcessId) -Force
            try {
                $cp = Get-Process -Id $claudeChild.ProcessId -ErrorAction SilentlyContinue
                if ($cp) { $marker | Add-Member -NotePropertyName claude_start_time -NotePropertyValue ($cp.StartTime.ToString('o')) -Force }
            } catch {}
        }
    } catch {}

    $patched = $marker | ConvertTo-Json
    Set-Content -Path $markerTmp -Value $patched -Encoding UTF8
    Move-Item -Force -Path $markerTmp -Destination $markerFile

    Record-BreakerOutcome -Outcome success -Scope 'spawn'
    $claudePidForLog = $null
    if ($marker.PSObject.Properties.Name -contains 'claude_pid') {
        $claudePidForLog = $marker.claude_pid
    }
    Write-GuardLog -Level EXEC -Message 'Agent spawned' -Context @{ role = $Role; id = $Id; pid = $proc.Id; claude_pid = $claudePidForLog; cap = $maxAgents }
    Write-Output "Spawned $Id (role=$Role, pid=$($proc.Id), cap=$maxAgents). Marker: $markerFile"
}
finally {
    if ($idLock)     { try { $idLock.Dispose() }     catch {}; Remove-Item -Path $idLockPath     -Force -ErrorAction SilentlyContinue }
    if ($globalLock) { try { $globalLock.Dispose() } catch {}; Remove-Item -Path $globalLockPath -Force -ErrorAction SilentlyContinue }
}
