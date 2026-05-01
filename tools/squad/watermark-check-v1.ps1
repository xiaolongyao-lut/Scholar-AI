# watermark-check-v1.ps1 — round-5 SELF-APPLIED artifact (brief 075151)
#
# Purpose: schema-collision-safe successor to watermark-check.ps1 (round-7).
# Round-7 observed two parallel-Morpheus instances both writing
# `.squad/memory/file-size-watermark.json` with `schema_version:"v0"` but
# DIFFERENT field shapes (mine: {files:{<path>:{lines,bytes}}, last_rollback};
# sibling: {files:{<short>:{bytes,mtime_unix}}}). When prev-snapshot is foreign,
# the round-7 watchdog silently treats it as first-run and the rollback signal
# is lost.
#
# v1 fixes:
#   1. New path .squad/memory/file-size-watermark-v1.json (no collision).
#   2. `schema_version: "v1"` + `producer: "morpheus-watermark-check-v1"` field;
#      script REFUSES to merge against any prev-snapshot that lacks both.
#   3. Per-file required keys: {lines:int, bytes:int}. Missing key on prev → treat
#      that file as first-run (not whole-snapshot reset), so a partial foreign
#      write only loses one file's history, not all.
#   4. Atomic .tmp+replace per CLAUDE.md §4.7 (same as round-7 sibling).
#
# Usage:
#   pwsh -NoProfile -File tools/squad/watermark-check-v1.ps1            # update + report
#   pwsh -NoProfile -File tools/squad/watermark-check-v1.ps1 -DryRun    # report only
#
# Exit codes: 0 = ok / first-run / increased; 2 = rollback detected; 3 = foreign-schema rejected.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot/../..").Path,
    [string[]]$Files  = @('.squad/identity/requirement-pool.md',
                          '.squad/memory/DECISION_TRAIL.md'),
    [string]$WatermarkPath = '.squad/memory/file-size-watermark-v1.json',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $RepoRoot

$PRODUCER = 'morpheus-watermark-check-v1'
$SCHEMA   = 'v1'
$nowIso   = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
$wmFull   = Join-Path $RepoRoot $WatermarkPath

# --- Load prev snapshot, but only if schema+producer match (foreign-write defense). ---
$prev = $null
$foreignReason = $null
if (Test-Path -LiteralPath $wmFull) {
    try { $prev = Get-Content -LiteralPath $wmFull -Raw | ConvertFrom-Json } catch { $prev = $null; $foreignReason = 'parse-error' }
    if ($prev) {
        if ($prev.schema_version -ne $SCHEMA) { $foreignReason = "schema_version='$($prev.schema_version)' (want '$SCHEMA')"; $prev = $null }
        elseif ($prev.producer -ne $PRODUCER) { $foreignReason = "producer='$($prev.producer)' (want '$PRODUCER')"; $prev = $null }
    }
}

# --- Snapshot current. ---
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

# --- Detect rollbacks (per-file, missing-key tolerant). ---
$rollbacks = @()
if ($prev -and $prev.files) {
    foreach ($f in $Files) {
        $p = $prev.files.$f
        $c = $current[$f]
        if ($null -ne $p -and $null -ne $p.lines -and $c.lines -lt $p.lines) {
            $rollbacks += [ordered]@{
                file       = $f
                prev_lines = [int]$p.lines
                curr_lines = [int]$c.lines
                delta      = [int]($c.lines - $p.lines)
            }
        }
    }
}

# --- Emit structured stdout report. ---
$report = [ordered]@{
    schema_version    = $SCHEMA
    producer          = $PRODUCER
    checked_at        = $nowIso
    files             = $current
    rollbacks         = $rollbacks
    rollback_detected = ($rollbacks.Count -gt 0)
    foreign_prev      = $foreignReason
    dry_run           = [bool]$DryRun
}
$report | ConvertTo-Json -Depth 6

if ($DryRun) {
    if ($foreignReason)        { exit 3 }
    elseif ($rollbacks.Count)  { exit 2 }
    else                       { exit 0 }
}

# --- Persist new watermark (monotonic-or-equal merge to defend against own race). ---
$persistFiles = @{}
foreach ($f in $Files) {
    $c = $current[$f]
    $maxLines = [int]$c.lines
    $maxBytes = [int]$c.bytes
    if ($prev -and $prev.files -and $null -ne $prev.files.$f) {
        $p = $prev.files.$f
        if ($null -ne $p.lines -and $p.lines -gt $maxLines) { $maxLines = [int]$p.lines }
        if ($null -ne $p.bytes -and $p.bytes -gt $maxBytes) { $maxBytes = [int]$p.bytes }
    }
    $persistFiles[$f] = [ordered]@{ lines = $maxLines; bytes = $maxBytes }
}

$persist = [ordered]@{
    schema_version  = $SCHEMA
    producer        = $PRODUCER
    last_updated_at = $nowIso
    files           = $persistFiles
    last_rollback   = $(if ($rollbacks.Count -gt 0) { @{ at = $nowIso; rollbacks = $rollbacks } } elseif ($prev) { $prev.last_rollback } else { $null })
}

$tmp = "$wmFull.tmp"
$persist | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $tmp -Encoding UTF8
Move-Item -LiteralPath $tmp -Destination $wmFull -Force

if ($foreignReason)        { exit 3 }
elseif ($rollbacks.Count)  { exit 2 }
else                       { exit 0 }
