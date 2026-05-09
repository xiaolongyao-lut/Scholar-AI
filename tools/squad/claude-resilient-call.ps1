# claude-resilient-call.ps1
#
# Sidecar for tools/squad/morpheus-headless.ps1.
# Provides Invoke-ClaudeOnceRetried, a thin retry-wrapper around the
# `Get-Content $tmp -Raw | claude @args` pipeline that already lives in
# Invoke-ClaudeRound (line ~530 of morpheus-headless.ps1).
#
# Why this exists (root cause, 2026-04-26):
#   The user's `claude` binary points at a third-party reverse-proxied
#   endpoint that fluctuates. A single transient blip mid-round (5xx,
#   ECONNRESET, empty stream, partial-chunk JSON) caused
#   ConvertFrom-Json -ErrorAction Stop to throw, which made the whole
#   round record ok=false / cost=$0 in morpheus-rounds.jsonl. Round 25
#   was the concrete loss event: three real artifacts existed on disk
#   (two pool entries + one task dispatch) but the JSONL falsely marked
#   the round as failed and DECISION_TRAIL.md skipped it for ~24h until
#   manual reconciliation.
#
# Design (kept minimal per CLAUDE.md §3 surgical-changes):
#   - 3 attempts, exponential backoff 2s/4s/8s.
#   - RETRYABLE  (loop, do not record failure):
#       * empty $raw
#       * $raw non-empty but ConvertFrom-Json throws (proxy returned HTML
#         5xx body, partial chunk, etc.)
#       * stderr matches /timeout|ECONNRESET|EAI_AGAIN|getaddrinfo|
#         HTTP\/.\d 5\d\d|socket hang up|fetch failed/ (case insensitive)
#   - HARD-FAIL (return immediately, no retry):
#       * stderr matches /401|403|invalid api key|authentication/
#       * parsed JSON has is_error=true with explicit message
#       * ANY other unexpected exception bubbles up to the caller
#         unchanged
#   - Final-failure shape preserves diagnosability: returns hashtable
#     with ok=$false, raw, parse_error, attempt_count, retry_log, so
#     post-hoc inspection can see what each attempt did.
#
# Integration footprint in main file is two lines:
#   1. dot-source at top:        . "$PSScriptRoot\claude-resilient-call.ps1"
#   2. replace single pipeline:  $callResult = Invoke-ClaudeOnceRetried -PromptTmp $tmp -ClaudeArgs $claudeArgs -Verbose:$Verbose
#
# This file does NOT modify morpheus-headless.ps1 directly. The caller
# decides whether to use the wrapper or fall back to the raw pipeline.

Set-StrictMode -Version Latest

$script:ResilientRetryableStderrPattern = '(?i)timeout|ECONNRESET|EAI_AGAIN|getaddrinfo|HTTP/\d(\.\d)? 5\d\d|socket hang up|fetch failed|connection reset|connection refused|network|stream'
$script:ResilientHardFailStderrPattern = '(?i)401|403|invalid api key|authentication|unauthorized|forbidden|quota exceeded|insufficient_quota'

function Invoke-ClaudeOnceRetried {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$PromptTmp,
        [Parameter(Mandatory)]
        [string[]]$ClaudeArgs,
        [int]$MaxAttempts = 3,
        [int[]]$BackoffSec = @(2, 4, 8),
        [switch]$VerboseLog
    )

    $retryLog = @()
    $lastRaw = ''
    $lastErr = $null
    $attempt = 0

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $attemptStart = Get-Date

        # 2>&1 merges stderr into the captured stream so we can
        # pattern-match on transport errors. Raw == merged.
        $raw = ''
        $invokeException = $null
        try {
            $raw = Get-Content $PromptTmp -Raw | claude @ClaudeArgs 2>&1 | Out-String
        } catch {
            $invokeException = $_
        }

        $attemptDurMs = [int]((Get-Date) - $attemptStart).TotalMilliseconds
        $rawLen = if ($raw) { $raw.Length } else { 0 }

        # Classify outcome
        $verdict = ''   # 'ok' | 'retryable' | 'hardfail' | 'unknown-throw'
        $parseError = $null
        $parsedObj = $null

        if ($invokeException) {
            # Pipeline itself threw (rare — usually claude returns a body
            # even on transport error). Treat exception text as stderr.
            $stderrLike = "$invokeException"
            if ($stderrLike -match $script:ResilientHardFailStderrPattern) {
                $verdict = 'hardfail'
                $parseError = "invoke-exception (hard-fail pattern): $stderrLike"
            } else {
                $verdict = 'retryable'
                $parseError = "invoke-exception: $stderrLike"
            }
        } elseif (-not $raw -or $rawLen -eq 0) {
            $verdict = 'retryable'
            $parseError = 'empty raw output'
        } elseif ($raw -match $script:ResilientHardFailStderrPattern) {
            # claude printed an auth/quota error to merged stream — no
            # retry will fix this; surface it as failure.
            $verdict = 'hardfail'
            $parseError = "stderr matches hard-fail pattern"
        } else {
            # Try to parse. If parse fails AND the raw matches retryable
            # patterns, retry. If parse fails on opaque content, also
            # retry (proxy returned HTML 502 body would land here).
            try {
                $parsedObj = $raw | ConvertFrom-Json -ErrorAction Stop
                # ConvertFrom-Json on '""' or '"x"' returns a String,
                # not a PSCustomObject. Guard before .PSObject.Properties.
                $isObj = ($null -ne $parsedObj) -and ($parsedObj -is [psobject]) -and ($parsedObj -isnot [string])
                if ($isObj -and $parsedObj.PSObject.Properties.Match('is_error').Count -gt 0 -and $parsedObj.is_error) {
                    $verdict = 'hardfail'
                    $parseError = "claude is_error=true: $($parsedObj.result)"
                } elseif ($isObj -and $parsedObj.PSObject.Properties.Match('result').Count -gt 0) {
                    $verdict = 'ok'
                } else {
                    # Parsed but doesn't look like a claude --print
                    # response (no .result field). Treat as retryable.
                    $verdict = 'retryable'
                    $parseError = 'parsed JSON has no .result field; not a claude response shape'
                }
            } catch {
                $parseError = "ConvertFrom-Json failed: $_"
                if ($raw -match $script:ResilientRetryableStderrPattern) {
                    $verdict = 'retryable'
                } else {
                    # Non-JSON body with no obvious transport-error
                    # signature — still retry once (proxy could have
                    # returned an HTML error page). Cap by MaxAttempts.
                    $verdict = 'retryable'
                }
            }
        }

        $logEntry = [ordered]@{
            attempt    = $attempt
            verdict    = $verdict
            duration_ms = $attemptDurMs
            raw_len    = $rawLen
            parse_error = $parseError
        }
        $retryLog += [pscustomobject]$logEntry

        if ($VerboseLog) {
            Write-Host "[claude-resilient] attempt=$attempt verdict=$verdict raw_len=$rawLen dur_ms=$attemptDurMs parse_error=$parseError" -ForegroundColor DarkGray
        }

        if ($verdict -eq 'ok') {
            return @{
                ok           = -not $parsedObj.is_error
                parsed       = $parsedObj
                raw          = $raw
                attempt_count = $attempt
                retry_log    = $retryLog
            }
        }

        if ($verdict -eq 'hardfail') {
            return @{
                ok           = $false
                parsed       = $parsedObj
                raw          = $raw
                parse_error  = $parseError
                attempt_count = $attempt
                retry_log    = $retryLog
                hard_fail    = $true
            }
        }

        $lastRaw = $raw
        $lastErr = $parseError

        if ($attempt -lt $MaxAttempts) {
            $sleepIdx = [Math]::Min($attempt - 1, $BackoffSec.Count - 1)
            $sleep = $BackoffSec[$sleepIdx]
            if ($VerboseLog) {
                Write-Host "[claude-resilient] retrying in ${sleep}s..." -ForegroundColor DarkYellow
            }
            Start-Sleep -Seconds $sleep
        }
    }

    # Exhausted retries
    return @{
        ok           = $false
        parsed       = $null
        raw          = $lastRaw
        parse_error  = "exhausted $MaxAttempts retries; last_error=$lastErr"
        attempt_count = $MaxAttempts
        retry_log    = $retryLog
        hard_fail    = $false
    }
}
