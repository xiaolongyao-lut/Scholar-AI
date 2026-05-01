# trail-rotate-scheduled.ps1
# Scheduled-task wrapper for trail rotation. Discharges
# .squad/specs/trail-rotate-trigger-policy.md §4 Acceptance #A6
# (the wrapper script the Windows Task Scheduler Squad-TrailRotate job
# will invoke every 15 minutes per §5 cadence).
#
# Contract (from trail-rotate-trigger-policy.md §4):
#   1. Invoke check-trail-size.ps1; capture exit code.
#   2. If exit != 2 (not HARD-FAIL), exit 0 immediately — no rotation.
#   3. If exit == 2, append authorisation line to DECISION_TRAIL.md via
#      trail_append.py per trail-archival.md §3 (serialised against
#      parallel-Morpheus trail-writers via .DECISION_TRAIL.md.lock).
#   4. Invoke trail_rotate.py --cut-fraction 0.40; capture exit + summary.
#   5. Append audit line to .squad/audits/trail-archival-pass-<ts>.md
#      per trail-archival.md §8.
#   6. Exit with trail_rotate's exit code (scheduler logs it).
#
# Steps 3 and 4 both hold the trail lock but do NOT share one critical
# section — per trigger-policy §4 rationale, a crashed process between
# steps leaves a recoverable dangling authorisation line.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Get-Location).Path,
    [double]$CutFraction = 0.40
)

$ErrorActionPreference = 'Stop'

# ---- Step 1: threshold check ----
$checkScript = Join-Path $RepoRoot '.squad/tools/check-trail-size.ps1'
if (-not (Test-Path -LiteralPath $checkScript)) {
    Write-Output "ERROR: check-trail-size.ps1 missing at $checkScript"
    exit 2
}

# Invoke the monitor; capture its text output AND its exit code separately.
# PowerShell has no $? for arbitrary-script exit codes until we read $LASTEXITCODE.
$checkOutput = & pwsh -NoProfile -File $checkScript -RepoRoot $RepoRoot 2>&1 | Out-String
$checkExit = $LASTEXITCODE

Write-Output "---- check-trail-size.ps1 output ----"
Write-Output $checkOutput
Write-Output "---- check exit code: $checkExit ----"

if ($checkExit -ne 2) {
    # Safe or warn tier; do not rotate. Scheduler sees exit 0 = healthy cadence absorb.
    Write-Output "[trail-rotate-scheduled] no-op: trail below HARD-FAIL threshold (check exit $checkExit)"
    exit 0
}

# ---- Step 2: parse pre-rotation tokens from check output for audit ----
$preTokens = $null
$preBytes  = $null
$preEntries = $null
if ($checkOutput -match 'trail_tokens_est\s*:\s*(\d+)') { $preTokens  = [int]$Matches[1] }
if ($checkOutput -match 'trail_entries\s*:\s*(\d+)')    { $preEntries = [int]$Matches[1] }
$trailPath = Join-Path $RepoRoot '.squad/memory/DECISION_TRAIL.md'
if (Test-Path -LiteralPath $trailPath) {
    $preBytes = (Get-Item -LiteralPath $trailPath).Length
}

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$tsCompact = Get-Date -Format 'yyyyMMdd-HHmm'

# ---- Step 3: append authorisation line via trail_append.py ----
# Matches the canonical format in trail-archival.md §3.
$auth = @"

### [$ts UTC+8 scheduled-task Squad-TrailRotate] trail archival pass authorised
- trail_tokens_pre: $preTokens
- trail_entries_pre: $preEntries
- trail_bytes_pre: $preBytes
- cut_fraction: $CutFraction
- archive_target: .squad/memory/DECISION_TRAIL-archive-$(Get-Date -Format 'yyyyMMdd').md
- authorised_by: Squad-TrailRotate (scheduled task, per .squad/specs/trail-rotate-trigger-policy.md §4 step 3)
"@

$appendPy = Join-Path $RepoRoot '.squad/tools/trail_append.py'
if (-not (Test-Path -LiteralPath $appendPy)) {
    Write-Output "ERROR: trail_append.py missing at $appendPy"
    exit 2
}

# trail_append.py supports --text per its docstring; pass the authorisation block.
$auth | & py -3 $appendPy --text -
$appendExit = $LASTEXITCODE
if ($appendExit -ne 0) {
    Write-Output "ERROR: trail_append.py failed (exit $appendExit); aborting before rotation to avoid unattested pass"
    exit 1
}
Write-Output "[trail-rotate-scheduled] authorisation line appended (trail_append exit 0)"

# ---- Step 4: invoke trail_rotate.py ----
$rotatePy = Join-Path $RepoRoot 'tools/squad/trail_rotate.py'
if (-not (Test-Path -LiteralPath $rotatePy)) {
    Write-Output "ERROR: trail_rotate.py missing at $rotatePy"
    exit 2
}

$rotateOutput = & py -3 $rotatePy --cut-fraction $CutFraction 2>&1 | Out-String
$rotateExit = $LASTEXITCODE
Write-Output "---- trail_rotate.py output ----"
Write-Output $rotateOutput
Write-Output "---- rotate exit code: $rotateExit ----"

# ---- Step 5: audit file per trail-archival.md §8 ----
$auditDir = Join-Path $RepoRoot '.squad/audits'
if (-not (Test-Path -LiteralPath $auditDir)) {
    New-Item -ItemType Directory -Path $auditDir | Out-Null
}
$auditPath = Join-Path $auditDir "trail-archival-pass-$tsCompact.md"

$postBytes = $null
if (Test-Path -LiteralPath $trailPath) {
    $postBytes = (Get-Item -LiteralPath $trailPath).Length
}

$audit = @"
# Trail archival pass — $ts

Invoked by: Squad-TrailRotate scheduled task (per .squad/specs/trail-rotate-trigger-policy.md §4).

## Pre-rotation (from check-trail-size.ps1)

- trail_tokens_pre: $preTokens
- trail_bytes_pre: $preBytes
- trail_entries_pre: $preEntries

## Post-rotation (from trail_rotate.py)

- trail_bytes_post: $postBytes
- cut_fraction: $CutFraction
- rotate_exit: $rotateExit

## trail_rotate summary (verbatim)

``````
$rotateOutput
``````

## check-trail-size output (verbatim, pre-rotation)

``````
$checkOutput
``````

## Authorisation trail line

Appended at: $ts by Squad-TrailRotate. See DECISION_TRAIL.md search string ``scheduled-task Squad-TrailRotate`` at or near the rotation timestamp.
"@

# Atomic write per CLAUDE.md §4.7: .tmp + Move-Item -Force.
$auditTmp = "$auditPath.tmp"
Set-Content -LiteralPath $auditTmp -Value $audit -Encoding UTF8 -NoNewline
Move-Item -LiteralPath $auditTmp -Destination $auditPath -Force
Write-Output "[trail-rotate-scheduled] audit written: $auditPath"

# ---- Step 6: exit with rotate's code so scheduler Event Log reflects the rotation result ----
exit $rotateExit
