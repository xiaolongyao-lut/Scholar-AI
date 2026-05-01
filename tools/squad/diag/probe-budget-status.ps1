# Probe /api/budget/status endpoint on local uvicorn.
# Usage: pwsh -File tools/squad/diag/probe-budget-status.ps1 [-Port 8765]
param(
    [int]$Port = 8765,
    [int]$TimeoutSec = 10
)

$uri = "http://127.0.0.1:$Port/api/budget/status"
$result = [ordered]@{
    probed_at = (Get-Date -Format 'o')
    uri       = $uri
    status    = $null
    body      = $null
    error     = $null
}

try {
    $r = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec $TimeoutSec
    $result.status = [int]$r.StatusCode
    $result.body = $r.Content
} catch {
    $exResponse = $null
    try { $exResponse = $_.Exception.Response } catch { $exResponse = $null }
    if ($exResponse) {
        $result.status = [int]$exResponse.StatusCode
        try {
            $stream = $exResponse.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $result.body = $reader.ReadToEnd()
        } catch {
            $result.body = "(unable to read response body)"
        }
    } else {
        $result.error = $_.Exception.Message
    }
}

$json = $result | ConvertTo-Json -Depth 6
$outPath = Join-Path $PSScriptRoot 'budget-status-probe.json'
[System.IO.File]::WriteAllText($outPath, $json, [System.Text.UTF8Encoding]::new($false))
Write-Output $json
