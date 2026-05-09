# run-rag-once.ps1 — Canonical RAG evaluation harness.
# Launches uvicorn, probes /api/chat with the 4 canonical questions from
# .squad/identity/goal-drift.md, captures everything to
# .squad/evaluations/run-<timestamp>.json, then tears the server down.
#
# This is the eyes-and-ears of the long-run loop. Morpheus calls this every
# round and diffs the result against goal-drift.md to generate new requirements.
#
# Usage:
#   .\tools\squad\run-rag-once.ps1
#   .\tools\squad\run-rag-once.ps1 -Port 8765 -KeepServer
#   .\tools\squad\run-rag-once.ps1 -ExtraQuestion "某个具体的自定义问题"

param(
    [int]$Port = 8765,
    [string]$Host_ = '127.0.0.1',
    [int]$StartupTimeoutSec = 30,
    [int]$PerQuestionTimeoutSec = 120,
    [string[]]$ExtraQuestion = @(),
    [switch]$KeepServer,
    [switch]$ReuseExisting
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'squad-guard.ps1')

$projectRoot = Get-ProjectRoot
$appDir      = Join-Path $projectRoot 'my-project\src'
$pythonExe   = Join-Path $projectRoot '.venv-1\Scripts\python.exe'
$qualityScorer = Join-Path $projectRoot 'tools\squad\_score-quality.py'
$evalDir     = Join-Path $projectRoot '.squad\evaluations'
$logDir      = Join-Path $projectRoot '.squad\autopilot-logs\rag-runs'

foreach ($d in @($evalDir, $logDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

$ts      = Get-Date -Format 'yyyyMMdd-HHmmss'
$outFile = Join-Path $evalDir "run-$ts.json"
$srvLog  = Join-Path $logDir  "uvicorn-$ts.log"

# Canonical evaluation set — must match goal-drift.md §2.
$canonicalQuestions = @(
    '激光熔池流动行为影响，匙孔如何控制？',
    '这篇文献主要研究了什么？',
    '文献库里关于焊缝结晶的控制有哪些相关研究？',
    '某种焊接工艺相关研究有哪些，写综述的材料？'
)
$allQuestions = $canonicalQuestions + $ExtraQuestion

# --- Preflight ---
if (-not (Test-Path $pythonExe)) {
    throw "python.exe not found at $pythonExe — check .venv-1 exists"
}
if (-not (Test-Path (Join-Path $appDir 'app.py'))) {
    throw "app.py not found at $appDir\app.py"
}
if (-not (Test-Path -LiteralPath $qualityScorer)) {
    throw "quality scorer not found at $qualityScorer"
}

$baseUrl = "http://${Host_}:${Port}"
$result = [ordered]@{
    run_id        = "run-$ts"
    started_at    = (Get-Date).ToString('o')
    host          = $Host_
    port          = $Port
    base_url      = $baseUrl
    questions     = @()
    server        = @{ pid = $null; startup_ok = $false; reused = $false }
    errors        = @()
    summary       = @{ total = 0; passed = 0; failed = 0; pass_rate = 0.0 }
    # /api/budget/status probe (goal-drift §4 line 88 — 首个必修).
    # Populated after canonical Q loop. Structured so halt-check / daemon
    # can key on budget_status.http_status without parsing chat questions.
    budget_status = @{ probed = $false; http_status = $null; elapsed_ms = $null; body = $null; error = $null }
    finished_at   = $null
}

# --- Start or reuse uvicorn ---
$srvProc = $null

function Test-ServerUp {
    try {
        $r = Invoke-WebRequest -Uri "$baseUrl/docs" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Test-RouterFresherThanServer {
    # Returns $true if chat_router.py on disk is newer than the running uvicorn's
    # log mtime (proxy for process start). Stale process => must respawn.
    $routerPath = Join-Path $appDir 'routers\chat_router.py'
    if (-not (Test-Path $routerPath)) { return $false }
    $routerMtime = (Get-Item $routerPath).LastWriteTimeUtc

    # Find the most recent uvicorn-*.log (excluding .err) older than routerMtime.
    $logs = Get-ChildItem -Path $logDir -Filter 'uvicorn-*.log' -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notlike '*.log.err' } |
            Sort-Object LastWriteTimeUtc -Descending
    if (-not $logs -or $logs.Count -eq 0) { return $false }
    $latestServerLog = $logs[0].LastWriteTimeUtc
    return ($routerMtime -gt $latestServerLog)
}

$reuseOk = $ReuseExisting -and (Test-ServerUp)
if ($reuseOk -and (Test-RouterFresherThanServer)) {
    Write-Host "[rag-run] router newer than running server — forcing respawn" -ForegroundColor Yellow
    Write-GuardLog -Level WARN -Message 'router fresher than uvicorn; respawning' -Context @{ run = "run-$ts" }
    # Best-effort kill of whatever holds :8765.
    try {
        $netstat = netstat -ano | Select-String ":$Port\s.*LISTENING"
        foreach ($line in $netstat) {
            $stalePid = ($line.ToString() -split '\s+')[-1]
            if ($stalePid -match '^\d+$') {
                Stop-Process -Id [int]$stalePid -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
    Start-Sleep -Milliseconds 500
    $reuseOk = $false
}

if ($reuseOk) {
    Write-Host "[rag-run] reusing existing server at $baseUrl" -ForegroundColor Green
    $result.server.reused = $true
    $result.server.startup_ok = $true
} else {
    Write-Host "[rag-run] starting uvicorn on $baseUrl" -ForegroundColor Cyan
    $srvProc = Start-Process -FilePath $pythonExe `
        -ArgumentList @('-m', 'uvicorn', 'app:app', '--host', $Host_, '--port', "$Port", '--log-level', 'info') `
        -WorkingDirectory $appDir `
        -RedirectStandardOutput $srvLog `
        -RedirectStandardError  "$srvLog.err" `
        -PassThru -WindowStyle Hidden

    $result.server.pid = $srvProc.Id
    Write-GuardLog -Level INFO -Message 'uvicorn started' -Context @{ pid = $srvProc.Id; port = $Port; run = "run-$ts" }

    # Wait for startup.
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-ServerUp) { $result.server.startup_ok = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $result.server.startup_ok) {
        $result.errors += "uvicorn did not answer within $StartupTimeoutSec s — see $srvLog"
    }
}

# --- Run canonical questions ---
if ($result.server.startup_ok) {
    $sessionId = "rag-eval-$ts"
    foreach ($q in $allQuestions) {
        $qResult = [ordered]@{
            question       = $q
            http_status    = $null
            elapsed_ms     = $null
            response_text  = $null
            citations      = @()
            citation_count = 0
            quality_score  = $null
            quality_pass   = $false
            quality_error  = $null
            error          = $null
            traceback      = $null
            passed         = $false
        }

        $repoRoot = Split-Path (Split-Path $appDir -Parent) -Parent
        $srcPath = Join-Path $repoRoot 'output'
        $body = @{ session_id = $sessionId; query = $q; source_paths = @($srcPath) } | ConvertTo-Json -Compress
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $resp = Invoke-WebRequest -Uri "$baseUrl/api/chat" `
                -Method POST -Body $body -ContentType 'application/json' `
                -TimeoutSec $PerQuestionTimeoutSec -UseBasicParsing -ErrorAction Stop
            $sw.Stop()
            $qResult.http_status = [int]$resp.StatusCode
            $qResult.elapsed_ms  = $sw.ElapsedMilliseconds

            try {
                $parsed = $resp.Content | ConvertFrom-Json -ErrorAction Stop
                $qResult.response_text = if ($parsed.PSObject.Properties['answer']) { $parsed.answer }
                                        elseif ($parsed.PSObject.Properties['response']) { $parsed.response }
                                        else { $resp.Content }
                if ($parsed.PSObject.Properties['citations']) {
                    $qResult.citations      = @($parsed.citations)
                    $qResult.citation_count = @($parsed.citations).Count
                }
            } catch {
                $qResult.response_text = $resp.Content
            }

            # Heuristic pass: 200 + non-empty response + not a punt phrase + at least 1 citation hint.
            $text = "$($qResult.response_text)"
            $puntRegex = '抱歉|无法回答|需要更多信息|我不知道|sorry.*cannot'
            $hasCitation = ($qResult.citation_count -gt 0) -or ($text -match '\[\d{4}\]|\(\d{4}\)|et al\.')
            $qualityInput = @{
                response_text = $qResult.response_text
                citations     = @($qResult.citations)
            } | ConvertTo-Json -Depth 8
            $qualityRaw = $qualityInput | & $pythonExe $qualityScorer
            $qualityExitCode = $LASTEXITCODE
            try {
                $qualityParsed = $qualityRaw | ConvertFrom-Json -ErrorAction Stop
                if ($qualityParsed.PSObject.Properties['quality_score']) {
                    $qResult.quality_score = $qualityParsed.quality_score
                }
                if ($qualityParsed.PSObject.Properties['quality_pass']) {
                    $qResult.quality_pass = [bool]$qualityParsed.quality_pass
                }
                if ($qualityParsed.PSObject.Properties['error']) {
                    $qResult.quality_error = $qualityParsed.error
                }
            } catch {
                $qResult.quality_error = "quality scorer returned invalid JSON: $_"
            }
            if ($qualityExitCode -ne 0 -and $null -eq $qResult.quality_error) {
                $qResult.quality_error = "quality scorer exited with code $qualityExitCode"
            }

            $qResult.passed = ($qResult.http_status -eq 200) -and ($text.Length -gt 40) -and ($text -notmatch $puntRegex) -and $hasCitation -and $qResult.quality_pass
        } catch {
            $sw.Stop()
            $qResult.elapsed_ms = $sw.ElapsedMilliseconds
            $qResult.error      = "$_"
            $exResponse = $null
            try { $exResponse = $_.Exception.Response } catch { $exResponse = $null }
            if ($exResponse) {
                try {
                    $qResult.http_status = [int]$exResponse.StatusCode
                    $stream = $exResponse.GetResponseStream()
                    $reader = New-Object System.IO.StreamReader($stream)
                    $qResult.traceback = $reader.ReadToEnd()
                } catch {}
            }
            $qResult.passed = $false
        }

        Write-Host ("[rag-run] Q: {0,-35}  status={1}  ms={2}  pass={3}" -f `
            ($q.Substring(0, [Math]::Min(35, $q.Length))), $qResult.http_status, $qResult.elapsed_ms, $qResult.passed) `
            -ForegroundColor $(if ($qResult.passed) { 'Green' } else { 'Yellow' })

        $result.questions += $qResult
    }

    $total  = @($result.questions).Count
    $passed = @($result.questions | Where-Object { $_.passed }).Count
    $result.summary.total     = $total
    $result.summary.passed    = $passed
    $result.summary.failed    = $total - $passed
    $result.summary.pass_rate = if ($total -gt 0) { [math]::Round($passed / $total, 3) } else { 0.0 }

    # --- /api/budget/status probe (goal-drift §4 line 88) ---
    # Single GET with short timeout. Captures http_status + body (or error) so
    # halt-check can assert the endpoint is healthy alongside chat. Does NOT
    # fail the run if budget-status is red — it is a side-signal for §4, not
    # part of the canonical §2 pass_rate.
    $result.budget_status.probed = $true
    $budgetSw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $budgetResp = Invoke-WebRequest -Uri "$baseUrl/api/budget/status" `
            -Method GET -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
        $budgetSw.Stop()
        $result.budget_status.http_status = [int]$budgetResp.StatusCode
        $result.budget_status.elapsed_ms  = $budgetSw.ElapsedMilliseconds
        $result.budget_status.body        = $budgetResp.Content
    } catch {
        $budgetSw.Stop()
        $result.budget_status.elapsed_ms = $budgetSw.ElapsedMilliseconds
        $budgetExResponse = $null
        try { $budgetExResponse = $_.Exception.Response } catch { $budgetExResponse = $null }
        if ($budgetExResponse) {
            $result.budget_status.http_status = [int]$budgetExResponse.StatusCode
            try {
                $bStream = $budgetExResponse.GetResponseStream()
                $bReader = New-Object System.IO.StreamReader($bStream)
                $result.budget_status.body = $bReader.ReadToEnd()
            } catch {
                $result.budget_status.body = "(unable to read response body)"
            }
        } else {
            $result.budget_status.error = $_.Exception.Message
        }
    }
    Write-Host ("[rag-run] GET /api/budget/status  status={0}  ms={1}" -f `
        $result.budget_status.http_status, $result.budget_status.elapsed_ms) `
        -ForegroundColor $(if ($result.budget_status.http_status -eq 200) { 'Green' } else { 'Yellow' })
}

# --- Teardown ---
if ($srvProc -and -not $KeepServer) {
    Write-Host "[rag-run] stopping uvicorn pid=$($srvProc.Id)" -ForegroundColor Cyan
    try { Stop-Process -Id $srvProc.Id -Force -ErrorAction Stop } catch {
        Write-Host "[rag-run] stop failed: $_" -ForegroundColor Yellow
    }
}

$result.finished_at = (Get-Date).ToString('o')

# Atomic write: .tmp + replace per CLAUDE.md §4.7.
$tmp = "$outFile.tmp"
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $tmp -Encoding UTF8
Move-Item -Path $tmp -Destination $outFile -Force

$schemaChecker = Join-Path $PSScriptRoot 'check-eval-schema.ps1'
if (-not (Test-Path -LiteralPath $schemaChecker)) {
    throw "eval schema checker not found at $schemaChecker"
}
& powershell -NoProfile -ExecutionPolicy Bypass -File $schemaChecker -RunFile $outFile
$schemaExitCode = $LASTEXITCODE
if ($schemaExitCode -ne 0) {
    Write-GuardLog -Level WARN -Message 'RAG eval schema validation failed' -Context @{
        run       = "run-$ts"
        out_file  = $outFile
        exit_code = $schemaExitCode
    }
    throw "eval schema validation failed for $outFile with exit code $schemaExitCode"
}

Write-Host ""
Write-Host "[rag-run] done. pass_rate=$($result.summary.pass_rate)  ($($result.summary.passed)/$($result.summary.total))" -ForegroundColor Green
Write-Host "[rag-run] wrote $outFile" -ForegroundColor Green
Write-GuardLog -Level EXEC -Message 'RAG eval completed' -Context @{
    run      = "run-$ts"
    pass     = $result.summary.passed
    total    = $result.summary.total
    rate     = $result.summary.pass_rate
    out_file = $outFile
}

# Expose path for callers.
return $outFile
