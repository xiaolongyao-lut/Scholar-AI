# queue-lease-rate-burst.ps1
# Discharges AC1-AC4 of requirement-pool L15973 queue-lease-rate sliding-window burst detector
# (filed round 22 brief 140613, empirically grounded by 7-sample series across 45min ending sample-6
# at brief 141308: 206→208→208→209→220→220→221, with one burst regime crossing 2.32/min at 141057).
#
# Reads the last N (default 4) `.squad/evaluations/queue-lease-rate-*.txt` files,
# parses `queued=K` from each, computes inter-sample tasks/min using filename `-<yyyymmdd-HHMMSS>`,
# emits `samples=N max_rate=R recent_rate=R' lease_floor_breaches=K`,
# exits non-zero when max_rate > BurstThreshold OR lease_floor_breaches >= N (sustained saturation).
# Atomic writes report per CLAUDE.md §4.7 .tmp + Move-Item.
#
# Invariants enforced:
#   AC3a: <N samples → exit 0 + stderr note (skips analysis, reports sample shortfall)
#   AC3b: malformed filename → skip that sample, continue
#   AC4: report file `.squad/evaluations/queue-lease-rate-burst-<ts>.txt` via .tmp + Move-Item
#
# This is a NEW tool, not a modification of queue-lease-rate.ps1; the spot-gauge remains untouched.

[CmdletBinding()]
param(
    [int]$Window = 4,
    [double]$BurstThreshold = 0.5,
    [double]$Floor = 0.05,
    [string]$EvalDir = ".squad/evaluations",
    [string]$ReportDir = ".squad/evaluations"
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $EvalDir)) {
    Write-Error "EvalDir not found: $EvalDir"
    exit 2
}

# Collect spot-gauge sample files, sort by filename timestamp ascending, take last $Window
$pattern = 'queue-lease-rate-(\d{8})-(\d{6})\.txt$'
$all = Get-ChildItem -LiteralPath $EvalDir -Filter 'queue-lease-rate-*.txt' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match $pattern -and $_.Name -notmatch 'queue-lease-rate-burst-' } |
    Sort-Object Name

$samples = @()
foreach ($f in $all) {
    if ($f.Name -notmatch $pattern) { continue }                    # AC3b: malformed name → skip
    $stamp = "$($Matches[1])-$($Matches[2])"
    try {
        $dt = [DateTime]::ParseExact($stamp, 'yyyyMMdd-HHmmss', $null)
    } catch {
        continue                                                     # AC3b: unparseable timestamp → skip
    }
    $body = Get-Content -LiteralPath $f.FullName -Raw -ErrorAction SilentlyContinue
    if ($body -notmatch 'queued=(\d+)\s+leased=(\d+)\s+ratio=([\d.]+)') { continue }
    $samples += [pscustomobject]@{
        when    = $dt
        queued  = [int]$Matches[1]
        leased  = [int]$Matches[2]
        ratio   = [double]$Matches[3]
        path    = $f.FullName
    }
}

$total = $samples.Count
if ($total -lt $Window) {
    $msg = "samples=$total window=$Window — insufficient samples for burst analysis (need >= $Window)"
    Write-Output $msg
    [Console]::Error.WriteLine("note: $msg ; AC3a skip")
    exit 0
}

$tail = $samples | Select-Object -Last $Window

# Inter-sample tasks/min over the tail window
$rates = @()
$breaches = 0
for ($i = 0; $i -lt $tail.Count; $i++) {
    if ($tail[$i].ratio -lt $Floor) { $breaches++ }
    if ($i -eq 0) { continue }
    $dtMin = ($tail[$i].when - $tail[$i-1].when).TotalMinutes
    if ($dtMin -le 0) { continue }                                   # guard same-second / clock-skew
    $deltaQ = $tail[$i].queued - $tail[$i-1].queued
    $rates += [Math]::Round($deltaQ / $dtMin, 4)
}

if ($rates.Count -eq 0) {
    $maxRate    = 0.0
    $recentRate = 0.0
} else {
    $maxRate    = ($rates | Measure-Object -Maximum).Maximum
    $recentRate = $rates[-1]
}

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$report = "samples=$($tail.Count) max_rate=$maxRate recent_rate=$recentRate lease_floor_breaches=$breaches threshold=$BurstThreshold floor=$Floor"
Write-Output $report

# Atomic write of report (AC4)
if (Test-Path -LiteralPath $ReportDir) {
    $tmp  = Join-Path $ReportDir "queue-lease-rate-burst-$ts.txt.tmp"
    $dest = Join-Path $ReportDir "queue-lease-rate-burst-$ts.txt"
    Set-Content -LiteralPath $tmp -Value $report -Encoding UTF8 -NoNewline
    Move-Item -LiteralPath $tmp -Destination $dest -Force
}

# AC2 exit semantics: burst-mode OR sustained saturation → exit 1
$burst     = ($maxRate -gt $BurstThreshold)
$saturated = ($breaches -ge $tail.Count)

if ($burst) {
    Write-Warning "BURST detected: max_rate $maxRate > threshold $BurstThreshold (window=$($tail.Count) samples)"
}
if ($saturated) {
    Write-Warning "SUSTAINED SATURATION: $breaches/$($tail.Count) samples below floor $Floor"
}

if ($burst -or $saturated) { exit 1 }
exit 0
