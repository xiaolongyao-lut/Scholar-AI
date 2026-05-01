# watermark-check.ps1 — round-7 SELF-APPLIED artifact (brief 074604)
#
# Purpose: detect concurrent-writer rollback on append-only Morpheus/squad memory files.
# `.squad/identity/requirement-pool.md` and `.squad/memory/DECISION_TRAIL.md` are append-only
# by convention; if a subsequent line-count is *smaller* than the watermark, a concurrent
# writer overwrote with a stale snapshot. Round-7 brief 074604 measured pool 4377 -> 4050
# (-313 lines) and trail 3430 -> 3004 (-416 lines) within minutes -- empirical anchor for
# this watchdog.
#
# Usage:
#   pwsh -NoProfile -File tools/squad/watermark-check.ps1            # update + report
#   pwsh -NoProfile -File tools/squad/watermark-check.ps1 -DryRun    # report only
#
# Exit codes: 0 = ok / first-run / increased; 2 = rollback detected (line-count regressed).
# No my-project/ touch. No .env touch. No new pip dep. Pure PowerShell + JSON.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot/../..").Path,
    [string[]]$Files  = @('.squad/identity/requirement-pool.md',
                          '.squad/memory/DECISION_TRAIL.md'),
    [string]$WatermarkPath = '.squad/memory/file-size-watermark.json',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $RepoRoot

$nowIso = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
$wmFull = Join-Path $RepoRoot $WatermarkPath

$prev = $null
if (Test-Path -LiteralPath $wmFull) {
    try { $prev = Get-Content -LiteralPath $wmFull -Raw | ConvertFrom-Json } catch { $prev = $null }
}

$current = @{}
foreach ($f in $Files) {
    $abs = Join-Path $RepoRoot $f
    if (Test-Path -LiteralPath $abs) {
        $lines = (Get-Content -LiteralPath $abs | Measure-Object -Line).Lines
        $bytes = (Get-Item -LiteralPath $abs).Length
        $current[$f] = [ordered]@{ lines = [int]$lines; bytes = [int]$bytes }
    } else {
        $current[$f] = [ordered]@{ lines = 0; bytes = 0; missing = $true }
    }
}

$rollbacks = @()
if ($prev -and $prev.files) {
    foreach ($f in $Files) {
        $p = $prev.files.$f
        $c = $current[$f]
        if ($null -ne $p -and $c.lines -lt $p.lines) {
            $rollbacks += [ordered]@{
                file       = $f
                prev_lines = [int]$p.lines
                curr_lines = [int]$c.lines
                delta      = [int]($c.lines - $p.lines)
            }
        }
    }
}

$report = [ordered]@{
    schema_version    = 'v0'
    checked_at        = $nowIso
    files             = $current
    rollbacks         = $rollbacks
    rollback_detected = ($rollbacks.Count -gt 0)
    dry_run           = [bool]$DryRun
}

# Emit structured report to stdout for pipe consumers / human read.
$report | ConvertTo-Json -Depth 6

if ($DryRun) { exit ($(if ($rollbacks.Count -gt 0) { 2 } else { 0 })) }

# Persist new watermark only on monotonic-or-equal (don't poison the watermark with a stale snapshot).
$persistFiles = @{}
if ($prev -and $prev.files) {
    foreach ($f in $Files) {
        $p = $prev.files.$f
        $c = $current[$f]
        $maxLines = if ($p -and $p.lines -gt $c.lines) { [int]$p.lines } else { [int]$c.lines }
        $maxBytes = if ($p -and $p.bytes -gt $c.bytes) { [int]$p.bytes } else { [int]$c.bytes }
        $persistFiles[$f] = [ordered]@{ lines = $maxLines; bytes = $maxBytes }
    }
} else {
    foreach ($f in $Files) {
        $persistFiles[$f] = [ordered]@{ lines = [int]$current[$f].lines; bytes = [int]$current[$f].bytes }
    }
}

$persist = [ordered]@{
    schema_version  = 'v0'
    last_updated_at = $nowIso
    files           = $persistFiles
    last_rollback   = $(if ($rollbacks.Count -gt 0) { @{ at = $nowIso; rollbacks = $rollbacks } } else { $prev.last_rollback })
}

# Atomic write per CLAUDE.md §4.7: .tmp + replace.
$tmp = "$wmFull.tmp"
$persist | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $tmp -Encoding UTF8
Move-Item -LiteralPath $tmp -Destination $wmFull -Force

if ($rollbacks.Count -gt 0) { exit 2 } else { exit 0 }
