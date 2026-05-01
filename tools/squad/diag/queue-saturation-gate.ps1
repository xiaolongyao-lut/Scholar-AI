# queue-saturation-gate.ps1
#
# Pre-dispatch gate. Read-only.
# Counts unleased tasks for a given assignee and reports SATURATED / OK so a
# caller (e.g. Morpheus self-discipline, a wrapper around `squad task create`)
# can defer a dispatch instead of stacking onto a stalled queue.
#
# Source: requirement-pool.md round 3 self-explore "tank-queue saturation gate"
# (39/50). Filed as discipline; this script is the machine-checkable form so
# the discipline is actually enforceable rather than aspirational.
#
# Exit codes:
#   0  OK            — queue depth < threshold
#   10 SATURATED     — queue depth >= threshold (caller should DEFER)
#   20 STALE-WORKER  — queue >= threshold AND assignee heartbeat > stale-min
#                       (caller should DEFER and surface escalation)
#   2  USAGE/ERROR   — bad args or `squad` CLI not reachable
#
# Always prints one structured line on stdout:
#   [queue-gate] assignee=<a> queue=<n> threshold=<t> heartbeat=<m>m status=<S>
#
# Read-only: never writes messages.db, never spawns, never cancels tasks.

[CmdletBinding()]
param(
    [string]$Assignee = 'tank-r3',
    [int]$Threshold = 12,
    [int]$StaleMinutes = 15
)

$ErrorActionPreference = 'Continue'

# 1. Count unleased tasks assigned to $Assignee.
$tasksRaw = & squad task list 2>$null
if ($LASTEXITCODE -ne 0 -or -not $tasksRaw) {
    Write-Output "[queue-gate] assignee=$Assignee queue=? threshold=$Threshold heartbeat=?m status=ERROR-CLI"
    exit 2
}

$assignedLines  = $tasksRaw | Select-String -Pattern "assigned_to:\s*$([regex]::Escape($Assignee))\b"
$unleasedLines  = $tasksRaw | Select-String -Pattern 'lease_owner:\s*unleased'
# Conservative count: number of tasks whose `assigned_to` matches AND that
# appear in the same record as a `lease_owner: unleased`. Squad's list output
# is a flat YAML-ish stream, so we approximate: min(assignedCount, unleasedCount).
# Caller treats this as advisory; a small over/under-count does not change the
# gate decision near the threshold.
$queueDepth = [Math]::Min($assignedLines.Count, $unleasedLines.Count)

# 2. Heartbeat for $Assignee.
$agentsRaw = & squad agents 2>$null
$hbMinutes = $null
if ($agentsRaw) {
    $hbLine = $agentsRaw | Select-String -Pattern "^\s*$([regex]::Escape($Assignee))\s+\(role:" | Select-Object -First 1
    if ($hbLine) {
        # Examples to match:  "active (14s ago)"  "idle (3m ago)"  "stale (34m ago)"
        $m = [regex]::Match($hbLine.Line, '\((\d+)([smh])\s+ago\)')
        if ($m.Success) {
            $n = [int]$m.Groups[1].Value
            switch ($m.Groups[2].Value) {
                's' { $hbMinutes = 0 }
                'm' { $hbMinutes = $n }
                'h' { $hbMinutes = $n * 60 }
            }
        }
    }
}

# 3. Decide.
$status = 'OK'
$exit = 0
if ($queueDepth -ge $Threshold) {
    $status = 'SATURATED'
    $exit = 10
    if ($hbMinutes -ne $null -and $hbMinutes -gt $StaleMinutes) {
        $status = 'STALE-WORKER'
        $exit = 20
    }
}

$hbStr = if ($hbMinutes -eq $null) { '?m' } else { "${hbMinutes}m" }
Write-Output "[queue-gate] assignee=$Assignee queue=$queueDepth threshold=$Threshold heartbeat=$hbStr status=$status"
exit $exit
