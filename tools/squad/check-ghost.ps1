# tools/squad/check-ghost.ps1
# Purpose: Detect and (with -AutoKill) clean up ghost Squad/long-run processes (DC5 + DC5a=B).
# Created: 2026-04-27 as part of Squad 0.9.3-modular hardening.
#
# A "ghost" is an owner record (now.md / locks/*.lock) that satisfies BOTH:
#   1. Owner PID does not exist OR PID's process commandline does not contain "squad"
#      OR the process is older than the owner record (PID was reused).
#   2. Lock file mtime > $StaleMinutes (default 5) AND no fresh heartbeat written.
#
# Behavior:
#   * Without -AutoKill: prints findings and exits 0 (no findings) or 2 (ghosts found).
#   * With -AutoKill (DC5a=B): kills any owned-but-orphaned process (commandline must still
#     match "squad" to be killable; mismatched PIDs are only logged, never killed) and writes
#     a cleanup log to .squad/orchestration-log/{utc-ts}-ghost-cleanup.md.
#
# Always logs to the orchestration-log when -AutoKill removes anything (DC5a=B requirement).
[CmdletBinding()]
param(
    [string]$TeamRoot = (Get-Location).Path,
    [int]$StaleMinutes = 5,
    [switch]$AutoKill
)

$ErrorActionPreference = 'Stop'
$utcNow = (Get-Date).ToUniversalTime()
$utcStamp = $utcNow.ToString('yyyyMMddTHHmmssZ')

$squadDir = Join-Path $TeamRoot '.squad'
$identityNow = Join-Path $squadDir 'identity/now.md'
$locksDir = Join-Path $squadDir 'locks'
$orchLogDir = Join-Path $squadDir 'orchestration-log'

if (-not (Test-Path $squadDir)) {
    Write-Output "OK: no .squad/ at $TeamRoot - nothing to check."
    exit 0
}

$findings = New-Object System.Collections.ArrayList

function Test-GhostByPid {
    param([int]$ProcId, [string]$RecordPath)
    if ($ProcId -le 0) { return $true, 'invalid-pid' }
    $proc = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    if (-not $proc) { return $true, 'pid-not-found' }
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue).CommandLine
    if (-not $cmd) { return $true, 'no-cmdline-readable' }
    if ($cmd -notmatch 'squad') { return $true, 'cmdline-mismatch' }
    return $false, 'live'
}

# Inspect now.md for owner PID
if (Test-Path $identityNow) {
    $nowContent = Get-Content $identityNow -Raw -ErrorAction SilentlyContinue
    if ($nowContent -match 'owner_pid:\s*(\d+)') {
        $ownerPid = [int]$Matches[1]
        $isGhost, $reason = Test-GhostByPid -ProcId $ownerPid -RecordPath $identityNow
        if ($isGhost) {
            [void]$findings.Add([pscustomobject]@{ Type='now.md owner'; ProcPid=$ownerPid; Path=$identityNow; Reason=$reason })
        }
    }
}

# Inspect lock files
if (Test-Path $locksDir) {
    Get-ChildItem $locksDir -Filter '*.lock' -ErrorAction SilentlyContinue | ForEach-Object {
        $ageMin = ($utcNow - $_.LastWriteTimeUtc).TotalMinutes
        $lockBody = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
        $lockPid = 0
        if ($lockBody -match '(?:pid|owner_pid)[:=]\s*(\d+)') { $lockPid = [int]$Matches[1] }
        $isGhost, $reason = if ($lockPid -gt 0) { Test-GhostByPid -ProcId $lockPid -RecordPath $_.FullName } else { $true, 'no-pid-in-lock' }
        if ($isGhost -and $ageMin -gt $StaleMinutes) {
            [void]$findings.Add([pscustomobject]@{ Type='lock'; ProcPid=$lockPid; Path=$_.FullName; Reason="$reason; age=${ageMin}min" })
        }
    }
}

if ($findings.Count -eq 0) {
    Write-Output "OK: no ghosts detected."
    exit 0
}

Write-Output "GHOSTS FOUND: $($findings.Count)"
$findings | Format-Table -AutoSize | Out-String | Write-Output

if (-not $AutoKill) { exit 2 }

# DC5a=B: auto-kill + mandatory log
New-Item -ItemType Directory -Path $orchLogDir -Force | Out-Null
$logPath = Join-Path $orchLogDir "${utcStamp}-ghost-cleanup.md"
$logLines = New-Object System.Collections.ArrayList
[void]$logLines.Add("# Ghost Cleanup Log - $utcStamp")
[void]$logLines.Add('')
[void]$logLines.Add("Team root: $TeamRoot")
[void]$logLines.Add("Stale threshold: $StaleMinutes minutes")
[void]$logLines.Add("Findings: $($findings.Count)")
[void]$logLines.Add('')

foreach ($f in $findings) {
    [void]$logLines.Add("## $($f.Type) | PID=$($f.ProcPid) | $($f.Reason)")
    [void]$logLines.Add("Path: $($f.Path)")
    if ($f.ProcPid -gt 0 -and $f.Reason -eq 'cmdline-mismatch') {
        [void]$logLines.Add("Action: SKIP-KILL (PID alive but cmdline mismatch - PID likely reused)")
    } elseif ($f.ProcPid -gt 0) {
        $killExit = 'no-process'
        try {
            $proc = Get-Process -Id $f.ProcPid -ErrorAction SilentlyContinue
            if ($proc) {
                Stop-Process -Id $f.ProcPid -Force -ErrorAction Stop
                $killExit = 'killed'
            }
        } catch {
            $killExit = "kill-failed: $($_.Exception.Message)"
        }
        [void]$logLines.Add("Action: $killExit")
    } else {
        [void]$logLines.Add("Action: stale-lock-only (no PID to kill); record removal candidate")
    }
    if ($f.Type -eq 'lock' -and (Test-Path $f.Path)) {
        try { Remove-Item $f.Path -Force; [void]$logLines.Add("Lock removed: $($f.Path)") } catch { [void]$logLines.Add("Lock-remove-failed: $($_.Exception.Message)") }
    }
    [void]$logLines.Add('')
}

Set-Content -Path $logPath -Value ($logLines -join "`r`n") -Encoding UTF8
Write-Output "CLEANUP LOG: $logPath"
exit 0
