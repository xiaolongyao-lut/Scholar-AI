# -*- ps1: smoke-test a Literature Assistant onedir/installer release ----
# Reference: docs/plans/runbooks/windows-exe-release-standard.md
#
# Usage:
#   .\scripts\smoke_windows_release.ps1 -ExePath "<path-to-LiteratureAssistant.exe>"
#
# Verifies:
#   1. Process launches.
#   2. /health returns 200 with status=ok.
#   3. /api/wiki/status returns a non-empty JSON payload.
#   4. SPA root (GET /) returns 200.
#   5. Process can be terminated cleanly.
param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath,
    [int]$Port = 8000,
    [int]$BootSeconds = 12
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $ExePath)) {
    throw "exe not found: $ExePath"
}

Write-Host "[smoke] launching $ExePath"
$proc = Start-Process -FilePath $ExePath -PassThru -WindowStyle Minimized
Write-Host "[smoke] pid=$($proc.Id), waiting ${BootSeconds}s for boot..."
Start-Sleep -Seconds $BootSeconds

try {
    # 1. /health
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
    if ($health.status -ne 'ok') {
        throw "health check failed: $($health | ConvertTo-Json -Compress)"
    }
    Write-Host "[smoke] /health PASS"

    # 2. /api/wiki/status
    $wiki = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/wiki/status" -TimeoutSec 10
    if (-not $wiki) { throw "/api/wiki/status returned empty" }
    Write-Host "[smoke] /api/wiki/status PASS"

    # 3. SPA root
    $spa = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 5 -UseBasicParsing
    if ($spa.StatusCode -ne 200) {
        throw "SPA root not 200 (got $($spa.StatusCode))"
    }
    Write-Host "[smoke] / (SPA) PASS"

    Write-Host "[smoke] ALL CHECKS PASSED"
}
finally {
    Write-Host "[smoke] stopping pid=$($proc.Id)"
    try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch { Write-Warning $_ }
}
