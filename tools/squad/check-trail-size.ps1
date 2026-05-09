[CmdletBinding()]
param(
    [int]$WarnTokens = 200000,
    [int]$FailTokens = 300000,
    [int]$CharsPerToken = 4,
    [string]$TrailPath = (Join-Path $PSScriptRoot '..\..\.squad\memory\DECISION_TRAIL.md'),
    [switch]$Json
)

# Round 21 brief 133310 — sibling of check-pool-size.ps1.
# Trail-size monitor for .squad/memory/DECISION_TRAIL.md.
# Trail is allowed to grow much larger than the pool (no agent loads it
# wholesale into context; rotation is size-triggered by trail-rotate-trigger-
# policy.md §3, not by per-round read pressure). Default thresholds reflect
# this: warn at 200k tokens (~800KB), fail at 300k tokens (~1.2MB) — well
# above the pool's 150k/200k. The trail is currently ~2.35MB / ~590k tokens
# at this round, which means the 'fail' threshold IS already crossed; the
# checker's role is to make that visible to cron consumers, not to gate.
# Reports lines / bytes / chars / token-estimate vs configured thresholds.
# Exit codes: 0 = safe (<WarnTokens), 1 = warn (WarnTokens..FailTokens), 2 = fail (>=FailTokens),
#             3 = trail file missing.

if (-not (Test-Path -LiteralPath $TrailPath)) {
    if ($Json) {
        [pscustomobject]@{
            status   = 'missing'
            path     = $TrailPath
            exitCode = 3
        } | ConvertTo-Json -Compress
    } else {
        Write-Output "TRAIL_MISSING path=$TrailPath"
    }
    exit 3
}

$item  = Get-Item -LiteralPath $TrailPath
$bytes = [int64]$item.Length

# Single streaming pass: count lines and characters without slurping into memory twice.
$lines = 0
$chars = [int64]0
$reader = [System.IO.StreamReader]::new($TrailPath, [System.Text.Encoding]::UTF8)
try {
    while (-not $reader.EndOfStream) {
        $line = $reader.ReadLine()
        $lines++
        $chars += $line.Length
    }
} finally {
    $reader.Dispose()
}

$tokensEst = [int64]([math]::Ceiling($chars / [double]$CharsPerToken))

$status   = 'safe'
$exitCode = 0
if ($tokensEst -ge $FailTokens) {
    $status   = 'fail'
    $exitCode = 2
} elseif ($tokensEst -ge $WarnTokens) {
    $status   = 'warn'
    $exitCode = 1
}

# Context-window references for human-readable line.
$claude200k = if ($tokensEst -gt 200000) { 'EXCEEDS' } else { 'fits' }
$gpt4o128k  = if ($tokensEst -gt 128000) { 'EXCEEDS' } else { 'fits' }

if ($Json) {
    [pscustomobject]@{
        status        = $status
        path          = $TrailPath
        bytes         = $bytes
        lines         = $lines
        chars         = $chars
        tokensEst     = $tokensEst
        charsPerToken = $CharsPerToken
        warnTokens    = $WarnTokens
        failTokens    = $FailTokens
        claude200k    = $claude200k
        gpt4o128k     = $gpt4o128k
        mtime         = $item.LastWriteTime.ToString('o')
        exitCode      = $exitCode
    } | ConvertTo-Json -Compress
} else {
    Write-Output ("TRAIL_SIZE status={0} bytes={1} lines={2} chars={3} tokens_est={4} (chars/{5}) warn={6} fail={7} claude200k={8} gpt4o128k={9}" -f `
        $status, $bytes, $lines, $chars, $tokensEst, $CharsPerToken, $WarnTokens, $FailTokens, $claude200k, $gpt4o128k)
}

exit $exitCode
