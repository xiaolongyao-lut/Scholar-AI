[CmdletBinding()]
param(
    [int]$WarnTokens = 25000,
    [int]$FailTokens = 50000,
    [int]$CharsPerToken = 4,
    [string]$ThreadsPath = (Join-Path $PSScriptRoot '..\..\.squad\memory\OPEN_THREADS.md'),
    [switch]$Json
)

# Round 21 brief 133310 — second sibling of check-pool-size.ps1 (alongside
# check-trail-size.ps1 shipped same round).
# OPEN_THREADS.md size monitor.
# OPEN_THREADS.md is read in many briefs (e.g., the "OPEN_THREADS tail" block
# in every Morpheus round brief), so its size DOES gate per-round read pressure.
# Default thresholds reflect that: warn at 25k tokens (~100KB), fail at 50k
# tokens (~200KB). The file is currently ~21.8KB / ~5500 tokens at this round
# — well under warn — so the checker reports 'safe' on healthy operation and
# becomes load-bearing if/when archival rotation falls behind closures.
# Reports lines / bytes / chars / token-estimate vs configured thresholds.
# Exit codes: 0 = safe (<WarnTokens), 1 = warn (WarnTokens..FailTokens), 2 = fail (>=FailTokens),
#             3 = threads file missing.

if (-not (Test-Path -LiteralPath $ThreadsPath)) {
    if ($Json) {
        [pscustomobject]@{
            status   = 'missing'
            path     = $ThreadsPath
            exitCode = 3
        } | ConvertTo-Json -Compress
    } else {
        Write-Output "OPEN_THREADS_MISSING path=$ThreadsPath"
    }
    exit 3
}

$item  = Get-Item -LiteralPath $ThreadsPath
$bytes = [int64]$item.Length

# Single streaming pass: count lines and characters without slurping into memory twice.
$lines = 0
$chars = [int64]0
$reader = [System.IO.StreamReader]::new($ThreadsPath, [System.Text.Encoding]::UTF8)
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
        path          = $ThreadsPath
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
    Write-Output ("OPEN_THREADS_SIZE status={0} bytes={1} lines={2} chars={3} tokens_est={4} (chars/{5}) warn={6} fail={7} claude200k={8} gpt4o128k={9}" -f `
        $status, $bytes, $lines, $chars, $tokensEst, $CharsPerToken, $WarnTokens, $FailTokens, $claude200k, $gpt4o128k)
}

exit $exitCode
