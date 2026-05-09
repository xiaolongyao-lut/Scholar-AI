# queue-lease-rate.ps1
# Discharges AC1 of requirement-pool 51/50 queue-saturation-no-lease (round 19 brief 132737).
# Emits "queued=N leased=M ratio=R" and exits non-zero when ratio < floor (default 0.05).
# Lease floor rationale: at brief 132820 measurement, queue=206 leased=0 ratio=0.000;
# 0.05 means at least 1 in 20 queued tasks must have a non-NULL lease_owner.
# Atomic-write of report to .squad/evaluations/queue-lease-rate-<ts>.txt per CLAUDE.md §4.7.

[CmdletBinding()]
param(
    [double]$Floor = 0.05,
    [string]$ReportDir = ".squad/evaluations"
)

$ErrorActionPreference = 'Stop'

$raw = & squad task list --status queued 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "squad task list failed exit=$LASTEXITCODE"
    exit 2
}

$lines = $raw -split "`r?`n"
$tasks = @($lines | Where-Object { $_ -match '^\[task ' })
$queued = $tasks.Count

$leased = 0
foreach ($l in $lines) {
    if ($l -match 'lease_owner:\s+([a-zA-Z0-9_-]+)' -and $Matches[1] -ne 'unleased' -and $Matches[1] -ne 'NULL') {
        $leased++
    }
}

if ($queued -eq 0) {
    $ratio = 1.0
} else {
    $ratio = [Math]::Round($leased / $queued, 4)
}

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$report = "queued=$queued leased=$leased ratio=$ratio floor=$Floor"
Write-Output $report

# Atomic write of full report
if (Test-Path -LiteralPath $ReportDir) {
    $tmp  = Join-Path $ReportDir "queue-lease-rate-$ts.txt.tmp"
    $dest = Join-Path $ReportDir "queue-lease-rate-$ts.txt"
    Set-Content -LiteralPath $tmp -Value $report -Encoding UTF8 -NoNewline
    Move-Item -LiteralPath $tmp -Destination $dest -Force
}

if ($ratio -lt $Floor) {
    Write-Warning "lease-rate $ratio < floor $Floor — queue saturated, dispatch should be skipped per pool 51/50 AC2"
    exit 1
}
exit 0
