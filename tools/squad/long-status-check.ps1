# long-status-check.ps1 — Dashboard + legal-halt auditor for long-run mode.
#
# Two modes:
#   (default)      Print a human dashboard: daemons alive? last eval? halt-ready?
#   --halt-check   Machine mode. Exit 0 = halt legal. Exit 10 = not legal, with reason.
#                  Also prints JSON to stdout for programmatic callers.
#
# Halt is legal iff ALL hold (from goal-drift.md + Morpheus charter):
#   1. goal-drift.md has no unchecked `- [ ]` items in §3 (product capabilities) or §4 (hardening).
#   2. Last 3 consecutive RAG evals in .squad/evaluations/ all have pass_rate >= 1.0.
#   3. No HARD-STOP marker in .squad/memory/OPEN_THREADS.md (pattern `HARD-STOP`).
#   4. At least one eval in the last 2 hours (daemon is actually running).
#
# If Morpheus wants to stop, it SHOULD call this first and respect the answer.

param(
    [switch]$HaltCheck,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'squad-guard.ps1')

$projectRoot = Get-ProjectRoot
$goalFile    = Join-Path $projectRoot '.squad\identity\goal-drift.md'
$evalDir     = Join-Path $projectRoot '.squad\evaluations'
$markerDir   = Join-Path $projectRoot '.squad\autopilot-logs\live-agents'
$openThreads = Join-Path $projectRoot '.squad\memory\OPEN_THREADS.md'

$report = [ordered]@{
    checked_at  = (Get-Date).ToString('o')
    daemons     = [ordered]@{}
    live_agents = @{ count = 0; items = @() }
    last_evals  = @()
    goal_drift  = @{ total = 0; checked = 0; unchecked = 0; unchecked_items = @() }
    hard_stop   = @{ present = $false; lines = @() }
    halt_legal  = $false
    halt_reasons = @()
}

# --- 1. Daemon liveness ---
$daemonTitles = @('squad-watcher','squad-sweeper','rag-eval-daemon','squad-supervisor')
foreach ($t in $daemonTitles) {
    $procs = @(Get-Process -Name 'powershell','pwsh' -ErrorAction SilentlyContinue |
               Where-Object { $_.MainWindowTitle -eq $t })
    $report.daemons[$t] = @{
        alive = ($procs.Count -gt 0)
        pids  = @($procs | ForEach-Object { $_.Id })
    }
}

# --- 2. Live agents ---
if (Test-Path $markerDir) {
    $markers = @(Get-ChildItem $markerDir -Filter '*.json' -File -ErrorAction SilentlyContinue)
    foreach ($m in $markers) {
        try {
            $mk = Get-Content $m.FullName -Raw | ConvertFrom-Json
            $alive = $null -ne (Get-Process -Id $mk.pid -ErrorAction SilentlyContinue)
            $report.live_agents.items += [pscustomobject][ordered]@{
                id = $mk.id; role = $mk.role; pid = $mk.pid; alive = $alive
                spawned_at = $mk.spawned_at
            }
        } catch {}
    }
    $report.live_agents.count = $report.live_agents.items.Count
}

# --- 3. Recent evals ---
if (Test-Path $evalDir) {
    $evals = @(Get-ChildItem $evalDir -Filter 'run-*.json' -File -ErrorAction SilentlyContinue |
               Sort-Object LastWriteTime -Descending | Select-Object -First 5)
    foreach ($e in $evals) {
        try {
            $data = Get-Content $e.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $report.last_evals += [pscustomobject][ordered]@{
                run_id     = $data.run_id
                finished   = $data.finished_at
                pass       = $data.summary.passed
                total      = $data.summary.total
                pass_rate  = $data.summary.pass_rate
                age_min    = [math]::Round(((Get-Date) - $e.LastWriteTime).TotalMinutes, 1)
            }
        } catch {}
    }
}

# --- 4. Goal-drift parse ---
if (Test-Path $goalFile) {
    $lines = Get-Content $goalFile
    $inScope = $false
    foreach ($ln in $lines) {
        if ($ln -match '^##\s+(3\.|4\.)') { $inScope = $true;  continue }
        if ($ln -match '^##\s+(5\.|6\.|7\.|Archive)') { $inScope = $false; continue }
        if (-not $inScope) { continue }
        if ($ln -match '^\s*-\s*\[( |x|X)\]\s*(.+)$') {
            $report.goal_drift.total++
            if ($matches[1] -eq ' ') {
                $report.goal_drift.unchecked++
                $report.goal_drift.unchecked_items += $matches[2].Trim()
            } else {
                $report.goal_drift.checked++
            }
        }
    }
}

# --- 5. HARD-STOP scan ---
if (Test-Path $openThreads) {
    $hardLines = @(Select-String -Path $openThreads -Pattern 'HARD-STOP' -SimpleMatch -ErrorAction SilentlyContinue)
    if ($hardLines.Count -gt 0) {
        $report.hard_stop.present = $true
        $report.hard_stop.lines   = @($hardLines | ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" })
    }
}

# --- 6. Halt-legal judgement ---
if ($report.goal_drift.unchecked -gt 0) {
    $report.halt_reasons += "$($report.goal_drift.unchecked) unchecked items in goal-drift.md §3-§4"
}

$lastThree = @($report.last_evals | Select-Object -First 3)
if ($lastThree.Count -lt 3) {
    $report.halt_reasons += "only $($lastThree.Count) recent eval(s); need 3 consecutive"
} else {
    $greens = @($lastThree | Where-Object { $_.pass_rate -ge 1.0 }).Count
    if ($greens -lt 3) {
        $report.halt_reasons += "last 3 evals are not all pass_rate=1.0 ($greens / 3 green)"
    }
}

if ($report.last_evals.Count -gt 0) {
    $freshest = ($report.last_evals | Measure-Object -Property age_min -Minimum).Minimum
    if ($freshest -gt 120) {
        $report.halt_reasons += "freshest eval is $freshest min old; daemon may be down"
    }
} else {
    $report.halt_reasons += "no evals on record yet"
}

if ($report.hard_stop.present) {
    $report.halt_reasons += "HARD-STOP marker present in OPEN_THREADS.md"
}

$report.halt_legal = ($report.halt_reasons.Count -eq 0)

# --- 7. Output ---
if ($HaltCheck -or $Json) {
    $report | ConvertTo-Json -Depth 6
    if ($HaltCheck) {
        if ($report.halt_legal) { exit 0 } else { exit 10 }
    }
    exit 0
}

# Human dashboard.
Write-Host ""
Write-Host "=== Long-Run Status ===" -ForegroundColor Cyan
Write-Host ("checked_at: " + $report.checked_at)
Write-Host ""

Write-Host "Daemons:" -ForegroundColor Yellow
foreach ($k in $daemonTitles) {
    $d = $report.daemons[$k]
    $tag = if ($d.alive) { '[UP]  ' } else { '[DOWN]' }
    $col = if ($d.alive) { 'Green' } else { 'Red' }
    Write-Host ("  $tag $k" + $(if ($d.alive) { "  pids=$($d.pids -join ',')" } else { '' })) -ForegroundColor $col
}
Write-Host ""

Write-Host "Live agents ($($report.live_agents.count) / 10):" -ForegroundColor Yellow
foreach ($a in $report.live_agents.items) {
    $tag = if ($a.alive) { '[LIVE]' } else { '[DEAD]' }
    $col = if ($a.alive) { 'Green' } else { 'DarkRed' }
    Write-Host ("  $tag {0,-15} role={1,-10} pid={2}" -f $a.id, $a.role, $a.pid) -ForegroundColor $col
}
if ($report.live_agents.count -eq 0) { Write-Host "  (none)" -ForegroundColor DarkGray }
Write-Host ""

Write-Host "Recent RAG evals:" -ForegroundColor Yellow
foreach ($e in $report.last_evals) {
    $col = if ($e.pass_rate -ge 1.0) { 'Green' } elseif ($e.pass_rate -ge 0.5) { 'Yellow' } else { 'Red' }
    Write-Host ("  {0}  pass={1}/{2}  rate={3}  age={4}min" -f `
        $e.run_id, $e.pass, $e.total, $e.pass_rate, $e.age_min) -ForegroundColor $col
}
if ($report.last_evals.Count -eq 0) { Write-Host "  (no evals yet)" -ForegroundColor DarkGray }
Write-Host ""

Write-Host "Goal-drift (§3-§4): $($report.goal_drift.checked) checked, $($report.goal_drift.unchecked) unchecked" -ForegroundColor Yellow
if ($report.goal_drift.unchecked -gt 0 -and $report.goal_drift.unchecked -le 10) {
    foreach ($it in $report.goal_drift.unchecked_items) {
        Write-Host "  [ ] $it" -ForegroundColor DarkGray
    }
} elseif ($report.goal_drift.unchecked -gt 10) {
    Write-Host "  (too many to list, first 5:)" -ForegroundColor DarkGray
    foreach ($it in ($report.goal_drift.unchecked_items | Select-Object -First 5)) {
        Write-Host "  [ ] $it" -ForegroundColor DarkGray
    }
}
Write-Host ""

Write-Host "HARD-STOP: $(if ($report.hard_stop.present) { 'YES — ' + $report.hard_stop.lines.Count + ' line(s)' } else { 'none' })" `
    -ForegroundColor $(if ($report.hard_stop.present) { 'Red' } else { 'Green' })
Write-Host ""

if ($report.halt_legal) {
    Write-Host "Halt-legal: YES — Morpheus may stop." -ForegroundColor Green
} else {
    Write-Host "Halt-legal: NO — Morpheus must keep running. Reasons:" -ForegroundColor Yellow
    foreach ($r in $report.halt_reasons) {
        Write-Host "  - $r" -ForegroundColor Yellow
    }
}
Write-Host ""
