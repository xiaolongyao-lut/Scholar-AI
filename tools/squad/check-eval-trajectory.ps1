# check-eval-trajectory.ps1 — pass-rate trajectory verdict (goal-drift §5 L102, round-4 self-apply)
#
# Sibling of check-eval-cadence.ps1. Reads the most recent N runs of
# .squad/evaluations/run-*.json, extracts summary.pass_rate, and emits a
# structured ONE-LINE verdict that next round's brief / OPEN_THREADS sweep
# can grep for. Goal-drift §5 line 102 contract:
#   "连续 3 轮通过率不降 → 可以"自探索"；连续 2 轮下降 → 自动回滚到上一可用版本并写 OPEN_THREADS"
#
# Verdicts (status field):
#   explore-ok    last 3 monotonically non-decreasing (>=Window evals)
#   rollback      last 2 strictly decreasing
#   stable        none of the above (mixed / flat / insufficient data)
#   insufficient  fewer than 2 evals on disk
#
# Exit code:
#   0 = explore-ok or stable (no action needed)
#   2 = rollback (next round must write OPEN_THREADS)
#   3 = insufficient data
#
# Pure read. No product touch. No my-project/ touch. No creds. No spawn.

[CmdletBinding()]
param(
    [int]$Window = 3,
    [string]$EvalDir = (Join-Path $PSScriptRoot '..\..\.squad\evaluations'),
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $EvalDir)) {
    $marker = "EVAL-TRAJECTORY insufficient dir=$EvalDir"
    if ($Json) { @{ status = 'insufficient'; eval_dir = $EvalDir } | ConvertTo-Json -Compress }
    else { Write-Output $marker }
    exit 3
}

$runs = Get-ChildItem -LiteralPath $EvalDir -Filter 'run-*.json' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First $Window

if (-not $runs -or $runs.Count -lt 2) {
    $marker = "EVAL-TRAJECTORY insufficient count=$($runs.Count) window=$Window"
    if ($Json) { @{ status = 'insufficient'; count = $runs.Count; window = $Window } | ConvertTo-Json -Compress }
    else { Write-Output $marker }
    exit 3
}

# Pull pass_rate from each run, newest-first.
$rates = @()
foreach ($f in $runs) {
    try {
        $d = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $r = if ($null -ne $d.summary -and $null -ne $d.summary.pass_rate) { [double]$d.summary.pass_rate } else { $null }
    } catch {
        $r = $null
    }
    $rates += [pscustomobject]@{ name = $f.Name; rate = $r }
}

# Filter out runs with missing pass_rate; need >=2 numeric for any verdict.
$numeric = @($rates | Where-Object { $null -ne $_.rate })
if ($numeric.Count -lt 2) {
    $marker = "EVAL-TRAJECTORY insufficient numeric_count=$($numeric.Count) window=$Window"
    if ($Json) {
        @{ status = 'insufficient'; numeric_count = $numeric.Count; window = $Window; runs = @($rates | ForEach-Object { @{ name = $_.name; rate = $_.rate } }) } | ConvertTo-Json -Compress -Depth 4
    } else { Write-Output $marker }
    exit 3
}

# Newest-first → reverse to chronological for trend logic.
$chrono = @($numeric | Select-Object -First 3) | Sort-Object { (Get-Item (Join-Path $EvalDir $_.name)).LastWriteTime }

$status = 'stable'
if ($chrono.Count -ge 2) {
    $last2 = $chrono | Select-Object -Last 2
    if ($last2[0].rate -gt $last2[1].rate) { $status = 'rollback' }  # 2-round strict drop
}
if ($chrono.Count -ge 3 -and $status -ne 'rollback') {
    $a = $chrono[0].rate; $b = $chrono[1].rate; $c = $chrono[2].rate
    if ($a -le $b -and $b -le $c) { $status = 'explore-ok' }  # 3-round non-decreasing
}

if ($Json) {
    @{
        status   = $status
        window   = $Window
        chrono   = @($chrono | ForEach-Object { @{ name = $_.name; rate = $_.rate } })
    } | ConvertTo-Json -Compress -Depth 4
} else {
    $names = ($chrono | ForEach-Object { "$($_.name)=$($_.rate)" }) -join ','
    Write-Output "EVAL-TRAJECTORY $status window=$Window chrono=$names"
}

if ($status -eq 'rollback') { exit 2 } else { exit 0 }
