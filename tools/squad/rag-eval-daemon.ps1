# rag-eval-daemon.ps1 — Dedicated eval loop. Runs run-rag-once.ps1 every N minutes
# and PUSHES a summary message to Morpheus via `squad send`, so Morpheus gets
# woken up even if its own loop stalls.
#
# Designed to be launched by start-long-run.ps1 or `squad long-run`.
#
# Usage:
#   .\tools\squad\rag-eval-daemon.ps1                  # every 30 min
#   .\tools\squad\rag-eval-daemon.ps1 -EveryMinutes 15
#   .\tools\squad\rag-eval-daemon.ps1 -NotifyAgent morpheus -From rag-eval-daemon
#   .\tools\squad\rag-eval-daemon.ps1 -Once            # run one eval and exit

param(
    [int]$EveryMinutes = 30,
    [string]$NotifyAgent = 'morpheus',
    [string]$From = 'rag-eval-daemon',
    [switch]$Once
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

. (Join-Path $PSScriptRoot 'squad-guard.ps1')

$projectRoot = Get-ProjectRoot
$runOnce     = Join-Path $PSScriptRoot 'run-rag-once.ps1'
$squadExe    = 'C:\Tools\squad\squad-real.exe'  # 2026-04-26: bypass squad.cmd shim to avoid recursion

if (-not (Test-Path $runOnce)) {
    throw "run-rag-once.ps1 missing at $runOnce"
}

$Host.UI.RawUI.WindowTitle = 'rag-eval-daemon'

function Invoke-OneTick {
    Write-Host ""
    Write-Host ("[rag-eval-daemon] tick " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -ForegroundColor Cyan

    $outFile = $null
    try {
        $outFile = & $runOnce
    } catch {
        Write-Host "[rag-eval-daemon] run-rag-once failed: $_" -ForegroundColor Red
        Write-GuardLog -Level WARN -Message 'rag eval failed' -Context @{ err = "$_" }
        return
    }

    if (-not $outFile -or -not (Test-Path $outFile)) {
        Write-Host "[rag-eval-daemon] run-rag-once returned no output file." -ForegroundColor Yellow
        return
    }

    # Parse summary.
    try {
        $data = Get-Content $outFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Write-Host "[rag-eval-daemon] parse failed: $_" -ForegroundColor Yellow
        return
    }

    $runId = $data.run_id
    $pass  = $data.summary.passed
    $total = $data.summary.total
    $rate  = $data.summary.pass_rate

    # Build a short notification. Include per-question status so Morpheus doesn't
    # have to open the JSON to know what failed.
    $qLines = @()
    foreach ($q in $data.questions) {
        $tag = if ($q.passed) { 'OK ' } else { 'FAIL' }
        $snippet = if ($q.question.Length -gt 30) { $q.question.Substring(0,30) + '...' } else { $q.question }
        $qLines += ("  [{0}] status={1} ms={2} {3}" -f $tag, $q.http_status, $q.elapsed_ms, $snippet)
    }

    $msg = @"
[rag-eval] $runId  pass=$pass/$total  rate=$rate
$($qLines -join "`n")
file=$outFile
"@

    # Push to Morpheus. Non-fatal if squad send fails.
    if (Test-Path $squadExe) {
        try {
            & $squadExe send $From $NotifyAgent $msg 2>&1 | Out-Null
            Write-Host "[rag-eval-daemon] pushed summary to $NotifyAgent" -ForegroundColor Green
            Write-GuardLog -Level EXEC -Message 'rag eval summary pushed' -Context @{
                run = $runId; rate = $rate; to = $NotifyAgent
            }
        } catch {
            Write-Host "[rag-eval-daemon] squad send failed: $_" -ForegroundColor Yellow
            Write-GuardLog -Level WARN -Message 'squad send failed' -Context @{ err = "$_" }
        }
    } else {
        Write-Host "[rag-eval-daemon] squad.exe not found at $squadExe; skipping notify." -ForegroundColor Yellow
    }
}

if ($Once) {
    Invoke-OneTick
    exit 0
}

Write-Host "[rag-eval-daemon] loop: every $EveryMinutes min. notify=$NotifyAgent. Ctrl+C to stop." -ForegroundColor Green
Write-GuardLog -Level INFO -Message 'rag-eval-daemon started' -Context @{ every = $EveryMinutes; notify = $NotifyAgent }

while ($true) {
    Invoke-OneTick
    Write-Host "[rag-eval-daemon] sleeping $EveryMinutes min..." -ForegroundColor DarkGray
    Start-Sleep -Seconds ($EveryMinutes * 60)
}
