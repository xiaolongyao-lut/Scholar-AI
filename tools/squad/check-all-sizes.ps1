[CmdletBinding()]
param(
    [switch]$Json
)

# Round 19 brief 133747 - aggregator wrapping the 3 size-check siblings
# shipped at L12799 (pool, round 14), L133710 (trail + open-threads, round 21).
# Followup #1 from L132622 / re-noted in L133710 ("aggregator wrapping the 3
# PowerShell siblings - candidate for next non-test-author round").
#
# Plain text mode: emit each child's POOL_SIZE / TRAIL_SIZE / OPEN_THREADS_SIZE
# line verbatim, then a final ALL_SIZES status= aggregate line.
# Json mode: emit a single JSON object {pool: {...}, trail: {...},
# openThreads: {...}, status: <worst>, exitCode: <max>}.
# Exit code = max(child exit codes) so cron consumers see worst-case status.
# No caching, no JSON file writes (per L132622 followup #5 - read-only).

$siblings = @(
    @{ Name = 'pool';        Script = 'check-pool-size.ps1';         JsonKey = 'pool'        }
    @{ Name = 'trail';       Script = 'check-trail-size.ps1';        JsonKey = 'trail'       }
    @{ Name = 'openThreads'; Script = 'check-open-threads-size.ps1'; JsonKey = 'openThreads' }
)

$results = @()
$exitCodes = @()

foreach ($sib in $siblings) {
    $scriptPath = Join-Path $PSScriptRoot $sib.Script
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        # Sibling missing - report a synthetic entry, contribute exit 3.
        if ($Json) {
            $results += [pscustomobject]@{
                key      = $sib.JsonKey
                status   = 'sibling_missing'
                path     = $scriptPath
                exitCode = 3
            }
        } else {
            Write-Output ("{0}_SIZE status=sibling_missing script={1}" -f $sib.Name.ToUpper(), $scriptPath)
        }
        $exitCodes += 3
        continue
    }

    if ($Json) {
        # Capture child JSON output and parse it back into an object.
        $rawJson = & pwsh -NoProfile -File $scriptPath -Json
        $childExit = $LASTEXITCODE
        $exitCodes += $childExit
        try {
            $obj = $rawJson | ConvertFrom-Json
            # Tag with the sibling key for stable JSON-shape output.
            $obj | Add-Member -NotePropertyName 'key' -NotePropertyValue $sib.JsonKey -Force
            $results += $obj
        } catch {
            $results += [pscustomobject]@{
                key      = $sib.JsonKey
                status   = 'parse_error'
                rawJson  = $rawJson
                exitCode = $childExit
            }
        }
    } else {
        # Plain text passthrough: child's own status line is fine for human consumers.
        & pwsh -NoProfile -File $scriptPath
        $exitCodes += $LASTEXITCODE
    }
}

# Aggregate exit code = max(children).
$aggExit = 0
foreach ($e in $exitCodes) {
    if ($e -gt $aggExit) { $aggExit = $e }
}
$aggStatus = switch ($aggExit) {
    0 { 'safe' }
    1 { 'warn' }
    2 { 'fail' }
    3 { 'missing' }
    default { 'unknown' }
}

if ($Json) {
    [pscustomobject]@{
        children = $results
        status   = $aggStatus
        exitCode = $aggExit
    } | ConvertTo-Json -Depth 5 -Compress
} else {
    Write-Output ("ALL_SIZES status={0} exit={1}" -f $aggStatus, $aggExit)
}

exit $aggExit
