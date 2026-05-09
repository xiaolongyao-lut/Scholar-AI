# squad-cleanup.ps1 — End-of-session teardown.
# Closes every agent window spawned by autopilot, removes live-agent markers,
# optionally runs `squad leave` for each, and (optionally) clears messages.db.
#
# Usage:
#   .\tools\squad\squad-cleanup.ps1            # kill windows + leave agents
#   .\tools\squad\squad-cleanup.ps1 -Nuke      # also squad clean (wipes messages.db)
#   .\tools\squad\squad-cleanup.ps1 -DryRun    # show what would happen

param(
    [switch]$Nuke,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

. (Join-Path $PSScriptRoot 'squad-guard.ps1')

$projectRoot = Get-ProjectRoot
$squadExe    = 'C:\Tools\squad\squad-real.exe'  # 2026-04-26: bypass squad.cmd shim to avoid recursion
$markerDir   = Join-Path $projectRoot '.squad\autopilot-logs\live-agents'

$markers = @()
if (Test-Path $markerDir) {
    $markers = @(Get-ChildItem $markerDir -Filter '*.json' -File)
}

if ($markers) {
    Write-Host "Found $($markers.Count) agent marker(s)." -ForegroundColor Cyan
} else {
    Write-Host "No autopilot markers found; continuing stale lock cleanup." -ForegroundColor Yellow
}
foreach ($m in $markers) {
    try {
        $marker = Get-Content $m.FullName -Raw | ConvertFrom-Json
    } catch {
        if ($DryRun) { Write-Host "  [DRY] remove bad marker $($m.Name)" } else { Remove-Item $m.FullName -Force }
        continue
    }

    $id        = $marker.id
    $markerPid = $marker.pid

    if ($DryRun) {
        Write-Host "  [DRY] would kill pid=$markerPid id=$id, squad leave $id, remove marker"
        continue
    }

    $proc = Get-Process -Id $markerPid -ErrorAction SilentlyContinue
    if ($proc) {
        # Verify identity before kill (defends against PID recycling).
        $allowedNames = @('powershell','pwsh')   # WindowsTerminal/wt 是壳，不该 kill；claude 是分派终端，永远不动
        $nameOk = $allowedNames -contains $proc.Name
        $startOk = $true
        if ($nameOk -and ($marker.PSObject.Properties.Name -contains 'wrapper_start_time')) {
            try {
                $expected = [datetime]$marker.wrapper_start_time
                if ([math]::Abs(($proc.StartTime - $expected).TotalSeconds) -gt 5) { $startOk = $false }
            } catch { $startOk = $true }  # if comparison fails, don't block kill
        }
        if ($nameOk -and $startOk) {
            Write-Host "  killing pid=$markerPid ($id, $($proc.Name))" -ForegroundColor Red
            try { Stop-Process -Id $markerPid -Force -ErrorAction Stop } catch {
                Write-Host "    kill failed: $_" -ForegroundColor DarkRed
            }
        } else {
            $why = if (-not $nameOk) { "name=$($proc.Name) not in allowlist" } else { 'StartTime mismatch (PID recycled?)' }
            Write-Host "  REFUSE kill pid=$markerPid ($id): $why" -ForegroundColor Yellow
            Write-GuardLog -Level WARN -Message 'Cleanup refused kill (identity mismatch)' -Context @{ id = $id; pid = $markerPid; reason = $why }
        }
    } else {
        Write-Host "  pid=$markerPid ($id) already gone" -ForegroundColor DarkGray
    }

    try { & $squadExe leave $id 2>$null | Out-Null } catch {}

    Remove-Item $m.FullName -Force
    Write-GuardLog -Level EXEC -Message 'Cleanup removed marker' -Context @{ id = $id; pid = $markerPid }
}

# Sweep stale daemon lockfiles whose owner process is gone.
$stateDir = Join-Path $projectRoot '.squad\state'
if (Test-Path $stateDir) {
    $lockFiles = @(Get-ChildItem $stateDir -Filter '*.lock' -File -ErrorAction SilentlyContinue)
    foreach ($lf in $lockFiles) {
        $raw = (Get-Content -Path $lf.FullName -Raw -ErrorAction SilentlyContinue).Trim()
        $lockPid = 0
        if (-not [int]::TryParse($raw, [ref]$lockPid) -or $lockPid -le 0) {
            try {
                $h = [System.IO.File]::Open($lf.FullName, 'Open', 'ReadWrite', 'None')
                $h.Dispose()
                if ($DryRun) {
                    Write-Host "  [DRY] remove malformed lock $($lf.Name)"
                } else {
                    Remove-Item $lf.FullName -Force -ErrorAction SilentlyContinue
                }
            } catch {
                # Still locked by a live process; leave it.
            }
            continue
        }
        $owner = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
        if (-not $owner) {
            if ($DryRun) {
                Write-Host "  [DRY] remove stale lock $($lf.Name) (owner pid=$lockPid gone)"
            } else {
                Remove-Item $lf.FullName -Force -ErrorAction SilentlyContinue
                Write-Host "  removed stale lock $($lf.Name) (owner pid=$lockPid gone)" -ForegroundColor DarkGray
            }
        }
    }
}

# Also sweep new-style JSON lockfiles under .squad\locks (kernel multi-terminal locks).
$locksDir = Join-Path $projectRoot '.squad\locks'
if (Test-Path $locksDir) {
    # Read auto_close_idle_seconds from policy (fallback 120s).
    $idleSec = 120
    $policyPath = Join-Path $projectRoot '.squad\casting-policy.json'
    if (Test-Path $policyPath) {
        try {
            $policy = Get-Content $policyPath -Raw | ConvertFrom-Json
            if ($policy.execution_profile.auto_close_idle_seconds) { $idleSec = [int]$policy.execution_profile.auto_close_idle_seconds }
        } catch {}
    }
    $newLocks = @(Get-ChildItem $locksDir -Filter '*.lock' -File -ErrorAction SilentlyContinue)
    foreach ($lf in $newLocks) {
        $raw = (Get-Content -Path $lf.FullName -Raw -ErrorAction SilentlyContinue)
        if (-not $raw -or -not $raw.Trim()) {
            # Empty handle file from [System.IO.File]::Open — safe to remove if process is gone (no exclusive lock now).
            try {
                $h = [System.IO.File]::Open($lf.FullName,'Open','ReadWrite','None')
                $h.Dispose()
                if ($DryRun) { Write-Host "  [DRY] remove orphan handle-lock $($lf.Name)" } else { Remove-Item $lf.FullName -Force -ErrorAction SilentlyContinue }
            } catch {
                # Still locked by a live process; leave it.
            }
            continue
        }
        try {
            $lockObj = $raw | ConvertFrom-Json
            $ownerPid = if ($lockObj.PSObject.Properties.Name -contains 'owner_pid') { [int]$lockObj.owner_pid } else { 0 }
            $started  = if ($lockObj.PSObject.Properties.Name -contains 'started_at') { [datetime]$lockObj.started_at } else { (Get-Date) }
            $owner = if ($ownerPid -gt 0) { Get-Process -Id $ownerPid -ErrorAction SilentlyContinue } else { $null }
            $ageSec = ((Get-Date) - $started).TotalSeconds
            if (-not $owner -or $ageSec -gt $idleSec) {
                if ($DryRun) {
                    Write-Host "  [DRY] reclaim stale lock $($lf.Name) (owner=$ownerPid ageSec=$([int]$ageSec))"
                } else {
                    Remove-Item $lf.FullName -Force -ErrorAction SilentlyContinue
                    Write-Host "  reclaimed stale lock $($lf.Name)" -ForegroundColor DarkGray
                }
            }
        } catch {
            try {
                $h = [System.IO.File]::Open($lf.FullName, 'Open', 'ReadWrite', 'None')
                $h.Dispose()
                if ($DryRun) {
                    Write-Host "  [DRY] remove malformed lock $($lf.Name)"
                } else {
                    Remove-Item $lf.FullName -Force -ErrorAction SilentlyContinue
                }
            } catch {
                # Still locked by a live process; leave it.
            }
        }
    }
}

if ($Nuke -and -not $DryRun) {
    Write-Host "Running squad clean (messages.db will be wiped)..." -ForegroundColor Magenta
    & $squadExe clean
    Write-GuardLog -Level EXEC -Message 'squad clean invoked'
}

Write-Host "Cleanup done." -ForegroundColor Green
