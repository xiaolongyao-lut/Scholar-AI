# check-runtime-co-failure.ps1 — runtime co-failure detector (req 41/50, round-8 self-apply)
#
# Detects the joint-failure mode where:
#   (a) eval daemon has not produced fresh `.squad/evaluations/run-*.json` in N minutes, AND
#   (b) the squad task queue has > M tasks with `lease_owner: unleased`.
#
# When BOTH thresholds are crossed, Morpheus is in "pool-pad" mode: every round
# produces dispatches into a leaseless queue against a frozen denominator. This
# script atomically writes `.squad/HALT-PROPOSAL-<ts>.md` advising human ack.
#
# Pure observability. Returns exit 0 always (advisory, never blocks loop).
# CLAUDE.md §4.7: persistence uses .tmp + Move-Item -Force atomic pattern.
# Companion to requirement-pool entry [hard-stop-infra-no-escalation-ceiling].

[CmdletBinding()]
param(
    [int]$EvalStaleMin = 120,
    [int]$UnleasedThreshold = 30,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

# ---- (a) eval freshness ----
$evalDir = Join-Path $RepoRoot '.squad\evaluations'
$evalAgeMin = $null
$newestEval = $null
if (Test-Path -LiteralPath $evalDir) {
    $newest = Get-ChildItem -LiteralPath $evalDir -Filter 'run-*.json' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newest) {
        $newestEval = $newest.Name
        $evalAgeMin = [int]((Get-Date) - $newest.LastWriteTime).TotalMinutes
    }
}

# ---- (b) lease blackout ----
$unleasedCount = -1
try {
    $taskOut = & squad task list 2>&1
    if ($LASTEXITCODE -eq 0) {
        $unleasedCount = ($taskOut | Select-String -Pattern 'lease_owner:\s*unleased').Count
    }
} catch {
    $unleasedCount = -1
}

# ---- decision ----
$evalStale = ($evalAgeMin -ne $null -and $evalAgeMin -gt $EvalStaleMin)
$leaseBlackout = ($unleasedCount -gt $UnleasedThreshold)
$coFailure = $evalStale -and $leaseBlackout

$result = [ordered]@{
    eval_age_min       = $evalAgeMin
    eval_stale_min     = $EvalStaleMin
    eval_stale         = $evalStale
    newest_eval        = $newestEval
    unleased_count     = $unleasedCount
    unleased_threshold = $UnleasedThreshold
    lease_blackout     = $leaseBlackout
    co_failure         = $coFailure
    halt_proposal      = $null
}

if ($coFailure) {
    $ts = Get-Date -Format 'yyyy-MM-ddTHH-mm-ss'
    $haltPath = Join-Path $RepoRoot ".squad\HALT-PROPOSAL-$ts.md"
    $haltTmp = "$haltPath.tmp"

    $body = @"
# HALT-PROPOSAL $ts

Runtime co-failure detected by ``tools/squad/check-runtime-co-failure.ps1``.

## Signals
- Eval daemon stale: newest ``$newestEval`` is **$evalAgeMin min** old (threshold $EvalStaleMin).
- Lease blackout: **$unleasedCount** tasks with ``lease_owner: unleased`` (threshold $UnleasedThreshold).

## Recommendation
Human ack required before next Morpheus round. The eval daemon and the
lease issuer are co-located in ``run-rag-once.ps1``; both lanes are dark.
Continued auto-rounds will pool-pad without observable progress.

## Auto-close criterion
Either signal returning under threshold (fresher eval lands OR queue drains)
allows the next ``check-runtime-co-failure.ps1`` invocation to skip writing
a new proposal. This file remains as historical evidence.
"@

    Set-Content -LiteralPath $haltTmp -Value $body -Encoding UTF8 -NoNewline
    Move-Item -LiteralPath $haltTmp -Destination $haltPath -Force
    $result.halt_proposal = $haltPath
}

if ($Json) {
    $result | ConvertTo-Json -Compress
} else {
    foreach ($k in $result.Keys) { Write-Output ("{0}={1}" -f $k, $result[$k]) }
}

exit 0
