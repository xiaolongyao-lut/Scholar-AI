$base = "https://ai.centos.hk/v1"
$key = $env:TEST_API_KEY
if (-not $key) {
    throw "Set TEST_API_KEY before running this manual connectivity probe."
}
$headers = @{ "Authorization" = "Bearer $key"; "Content-Type" = "application/json" }

function Test-Endpoint {
    param($url, $method, $body = $null, $name)
    try {
        $params = @{
            Uri = $url
            Method = $method
            Headers = $headers
            UseBasicParsing = $true
            ErrorAction = "Stop"
        }
        if ($body) { $params["Body"] = $body }

        $res = Invoke-WebRequest @params
        Write-Host "Endpoint: $name"
        Write-Host "Status: $($res.StatusCode)"
        Write-Host "Response: $($res.Content.Substring(0, [Math]::Min(300, $res.Content.Length)))"
    } catch {
        Write-Host "Endpoint: $name"
        if ($_.Exception.Response) {
            $stream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $respBody = $reader.ReadToEnd()
            Write-Host "Status: $([int]$_.Exception.Response.StatusCode)"
            Write-Host "Error Body: $respBody"
        } else {
            Write-Host "Error: $($_.Exception.Message)"
        }
    }
    Write-Host ""
}

Test-Endpoint -url "$base/models" -method Get -name "/models"

$body2 = @{
    model = "claude-3-5-sonnet-20241022"
    messages = @(@{ role = "user"; content = "ping" })
} | ConvertTo-Json
Test-Endpoint -url "$base/chat/completions" -method Post -body $body2 -name "/chat/completions"

$body3 = @{
    model = "claude-3-5-sonnet-20241022"
    input = "ping"
} | ConvertTo-Json
Test-Endpoint -url "$base/responses" -method Post -body $body3 -name "/responses"
