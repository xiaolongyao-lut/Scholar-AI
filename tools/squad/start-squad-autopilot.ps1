# start-squad-autopilot.ps1 — One-click starter for the two background daemons.
# Opens two minimised PowerShell windows: the spawn-watcher and the kill-stuck sweeper.
#
# Usage (from project root or anywhere):
#   .\tools\squad\start-squad-autopilot.ps1
#
# Stop with:
#   .\tools\squad\squad-cleanup.ps1   (kills agent windows, but not the daemons themselves)
# To stop the daemons, close the two minimised PowerShell windows named "squad-watcher" / "squad-sweeper".

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-LiveLockPid {
    param([Parameter(Mandatory)][string]$LockPath)

    if (-not (Test-Path $LockPath)) { return $null }
    $raw = Get-Content -Path $LockPath -Raw -ErrorAction SilentlyContinue
    if ($null -eq $raw) { return $null }

    $pidValue = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$pidValue)) { return $null }
    if ($pidValue -le 0) { return $null }

    try {
        $proc = Get-Process -Id $pidValue -ErrorAction Stop
        if ($null -ne $proc) { return $pidValue }
    } catch {}

    Remove-Item -Path $LockPath -Force -ErrorAction SilentlyContinue
    return $null
}

$scriptDir = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
$stateDir = Join-Path $projectRoot '.squad\state'
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }

# Capture spawned PID and write it to <title>.lock immediately, so
# supervisor.ps1 Test-DaemonAlive sees the daemon as alive on its first heal-pass
# and doesn't spawn a duplicate. Added 2026-04-26 — fixes daemon-twin bug
# (start-long-run + supervisor each starting one of every daemon).
$watcherLock = Join-Path $stateDir 'squad-watcher.lock'
$watcherPid = Get-LiveLockPid -LockPath $watcherLock
if ($null -ne $watcherPid) {
    Write-Host "spawn-watcher already running (pid=$watcherPid) — skipping." -ForegroundColor Yellow
} else {
    Write-Host "Starting spawn-watcher (background)..." -ForegroundColor Green
    $watcherProc = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy','Bypass',
        '-Command', "`$Host.UI.RawUI.WindowTitle = 'squad-watcher'; & '$scriptDir\spawn-watcher.ps1'"
    ) -WindowStyle Minimized -PassThru
    Set-Content -Path $watcherLock -Value ([string]$watcherProc.Id) -Encoding UTF8
}

$sweeperLock = Join-Path $stateDir 'squad-sweeper.lock'
$sweeperPid = Get-LiveLockPid -LockPath $sweeperLock
if ($null -ne $sweeperPid) {
    Write-Host "kill-stuck sweeper already running (pid=$sweeperPid) — skipping." -ForegroundColor Yellow
} else {
    Start-Sleep -Milliseconds 500

    Write-Host "Starting kill-stuck sweeper (background, loop every 60s)..." -ForegroundColor Green
    $sweeperProc = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy','Bypass',
        '-Command', "`$Host.UI.RawUI.WindowTitle = 'squad-sweeper'; & '$scriptDir\kill-stuck-agent.ps1' -Loop"
    ) -WindowStyle Minimized -PassThru
    Set-Content -Path $sweeperLock -Value ([string]$sweeperProc.Id) -Encoding UTF8
}

Write-Host ""
Write-Host "Autopilot running. Two minimised windows should now be in your taskbar:" -ForegroundColor Cyan
Write-Host "  - squad-watcher  (polls .squad/spawn-queue/ every 2s)"
Write-Host "  - squad-sweeper  (detects stuck agents every 60s)"
Write-Host ""
Write-Host "To shut down:" -ForegroundColor Yellow
Write-Host "  1. Close both minimised windows"
Write-Host "  2. Then: .\tools\squad\squad-cleanup.ps1   (kills agent windows + leaves)"
