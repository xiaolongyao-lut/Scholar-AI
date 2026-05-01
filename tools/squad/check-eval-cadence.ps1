# check-eval-cadence.ps1 — eval daemon cadence watchdog (req 45/50, round-6 self-apply)
#
# Reads .squad/evaluations/run-*.json mtimes. If the newest is older than
# -StaleMin minutes, emit a structured ONE-LINE marker that next round's
# Morpheus brief-emitter / OPEN_THREADS sweep can grep for. Exit code:
#   0 = fresh (newest within threshold)
#   2 = stale (newest mtime older than threshold)
#   3 = empty (no run-*.json present at all)
#
# Pure read. No product touch. No my-project/ touch. No creds. No spawn.
# Companion to OPEN_THREADS [rag-eval-daemon-stale] auto-close criterion.

[CmdletBinding()]
param(
    [int]$StaleMin = 60,
    [string]$EvalDir = (Join-Path $PSScriptRoot '..\..\.squad\evaluations'),
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $EvalDir)) {
    $marker = "EVAL-CADENCE empty dir=$EvalDir"
    if ($Json) { @{ status = 'empty'; eval_dir = $EvalDir } | ConvertTo-Json -Compress }
    else { Write-Output $marker }
    exit 3
}

$newest = Get-ChildItem -LiteralPath $EvalDir -Filter 'run-*.json' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $newest) {
    $marker = "EVAL-CADENCE empty dir=$EvalDir pattern=run-*.json"
    if ($Json) { @{ status = 'empty'; eval_dir = $EvalDir } | ConvertTo-Json -Compress }
    else { Write-Output $marker }
    exit 3
}

$ageMin = [math]::Round(((Get-Date) - $newest.LastWriteTime).TotalMinutes, 1)
$status = if ($ageMin -gt $StaleMin) { 'stale' } else { 'fresh' }

if ($Json) {
    @{
        status      = $status
        newest_file = $newest.Name
        mtime       = $newest.LastWriteTime.ToString('o')
        age_min     = $ageMin
        threshold   = $StaleMin
    } | ConvertTo-Json -Compress
} else {
    Write-Output "EVAL-CADENCE $status newest=$($newest.Name) age_min=$ageMin threshold=$StaleMin"
}

if ($status -eq 'stale') { exit 2 } else { exit 0 }
