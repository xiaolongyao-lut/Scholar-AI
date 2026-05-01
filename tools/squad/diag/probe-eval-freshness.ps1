#requires -Version 5.1
# probe-eval-freshness.ps1
# Round-5-brief-at-07:23 (physical round 12) Morpheus self-applied artifact.
#
# WHAT: Read-only diagnostic that finds the newest .squad/evaluations/run-*.json
#       and classifies eval-daemon cadence into FRESH / STALE / HARD-STOP-INFRA
#       per the specs filed at requirement-pool.md lines 1514 (33/50) and
#       1533 (34/50). Machine-greppable verdict replaces ad-hoc trail-line
#       "eval_age: Nm FRESH" annotations written by hand for 11+ rounds.
# WHY:  Round-11 parallel-Morpheus trail (DECISION_TRAIL line 2940) observed
#       eval_age crossed 30m STALE threshold at round 10 and predicted
#       60m HARD-STOP-INFRA at round 12 if run-20260425-062845 remains newest.
#       This probe turns that ad-hoc prediction into a runnable check.
# SCOPE: Pure read-only. Reads only mtime + filename of run-*.json. Does NOT
#        open any run file, does NOT touch OPEN_THREADS, does NOT touch .env.
#        Atomic tmp+rename per CLAUDE.md §4.7.
# EXIT:  Always 0 (diagnostic, not gate). Emits verdict to stdout in parseable
#        key=value form for trail/harness consumers.

$ErrorActionPreference = 'Continue'

$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath)))
$EvalDir  = Join-Path $RepoRoot '.squad/evaluations'
$AuditsDir = Join-Path $RepoRoot '.squad/audits'
if (-not (Test-Path $AuditsDir)) { New-Item -ItemType Directory -Path $AuditsDir -Force | Out-Null }

$ts  = Get-Date -Format 'yyyyMMdd-HHmmss'
$Out = Join-Path $AuditsDir "eval-freshness-$ts.md"
$Tmp = "$Out.tmp"

# Find newest run-*.json
$newest = $null
$newestAgeMin = $null
$runCount = 0
if (Test-Path $EvalDir) {
    $runs = Get-ChildItem -LiteralPath $EvalDir -Filter 'run-*.json' -File -ErrorAction SilentlyContinue |
        Sort-Object -Property LastWriteTime -Descending
    $runCount = $runs.Count
    if ($runs.Count -gt 0) {
        $newest = $runs[0]
        $newestAgeMin = [math]::Round(((Get-Date) - $newest.LastWriteTime).TotalMinutes, 1)
    }
}

# Verdict (deterministic thresholds per pool 33/50 + 34/50)
$verdict = if (-not (Test-Path $EvalDir)) {
    'EVAL_DIR_MISSING'
} elseif ($runCount -eq 0) {
    'NO_EVAL_RUNS'
} elseif ($newestAgeMin -le 30) {
    'FRESH'
} elseif ($newestAgeMin -le 60) {
    'STALE'
} else {
    'HARD_STOP_INFRA'
}

# Emit report
$body = @()
$body += "# eval-freshness-$ts"
$body += ''
$body += "Generated: $(Get-Date -Format 'o')"
$body += ''
$body += '## A. Scan'
$body += "- eval_dir: ``.squad/evaluations/``"
$body += "- exists: $(Test-Path $EvalDir)"
$body += "- run_count: $runCount"
if ($newest) {
    $body += "- newest_file: ``$($newest.Name)``"
    $body += "- newest_mtime: $($newest.LastWriteTime.ToString('o'))"
    $body += "- newest_age_minutes: $newestAgeMin"
}
$body += ''
$body += '## B. Thresholds (pool-filed)'
$body += '- FRESH: age <= 30 min (per req-065112 / 33-50 trail-liveness rule)'
$body += '- STALE: 30 < age <= 60 min'
$body += '- HARD_STOP_INFRA: age > 60 min (per req at pool line ~1533, 34/50 cadence monitor)'
$body += ''
$body += '## C. Verdict'
$body += "**$verdict**"
$body += ''
$body += '## D. Consumer contract'
$body += '- trail line should include `[eval_age: <N>m <VERDICT>]` per round-7 33/50 discipline'
$body += '- HARD_STOP_INFRA verdict means the next-round halt-check must escalate; the loop can continue non-eval work but MUST log the escalation'
$body += '- This probe is orthogonal to `6908f3cc` chat-cred fix and to `72d37679` RLHF pool writer'
$body += '- Exit 0 regardless of verdict — probe is diagnostic, not a gate'

$body -join "`r`n" | Out-File -FilePath $Tmp -Encoding utf8 -NoNewline
Move-Item -LiteralPath $Tmp -Destination $Out -Force

Write-Output "newest_file=$($newest.Name) age_min=$newestAgeMin verdict=$verdict report=$Out"
exit 0
