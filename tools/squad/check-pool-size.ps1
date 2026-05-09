[CmdletBinding()]
param(
    [int]$WarnTokens = 150000,
    [int]$FailTokens = 200000,
    [int]$CharsPerToken = 4,
    [string]$PoolPath = (Join-Path $PSScriptRoot '..\..\.squad\identity\requirement-pool.md'),
    [switch]$Json
)

# L12799 acceptance #1: pool-size monitor.
# Reports lines / bytes / chars / token-estimate vs context-window thresholds.
# Exit codes: 0 = safe (<WarnTokens), 1 = warn (WarnTokens..FailTokens), 2 = fail (>=FailTokens),
#             3 = pool file missing.

if (-not (Test-Path -LiteralPath $PoolPath)) {
    if ($Json) {
        [pscustomobject]@{
            status   = 'missing'
            path     = $PoolPath
            exitCode = 3
        } | ConvertTo-Json -Compress
    } else {
        Write-Output "POOL_MISSING path=$PoolPath"
    }
    exit 3
}

$item  = Get-Item -LiteralPath $PoolPath
$bytes = [int64]$item.Length

# Single streaming pass: count lines and characters without slurping into memory twice.
$lines = 0
$chars = [int64]0
$reader = [System.IO.StreamReader]::new($PoolPath, [System.Text.Encoding]::UTF8)
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
        path          = $PoolPath
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
    Write-Output ("POOL_SIZE status={0} bytes={1} lines={2} chars={3} tokens_est={4} (chars/{5}) warn={6} fail={7} claude200k={8} gpt4o128k={9}" -f `
        $status, $bytes, $lines, $chars, $tokensEst, $CharsPerToken, $WarnTokens, $FailTokens, $claude200k, $gpt4o128k)
}

exit $exitCode
