# start-long-run.ps1 — Single-button starter for "long-task execution mode".
# Brings up the full long-run stack:
#   1. spawn-watcher          (polls .squad/spawn-queue/ every 2s)
#   2. kill-stuck sweeper     (reassigns stale agents every 60s)
#   3. RAG eval daemon        (runs run-rag-once.ps1 every 30 min,
#                              pushes results into .squad/evaluations/)
#   4. Morpheus Claude window (pre-staged with the long-run prompt on clipboard)
#
# Usage:
#   .\tools\squad\start-long-run.ps1
#   .\tools\squad\start-long-run.ps1 -EvalEveryMinutes 30 -SkipMorpheus
#
# Stop with:
#   Close the minimised windows (titles: squad-watcher / squad-sweeper / rag-eval-daemon)
#   Then:  .\tools\squad\squad-cleanup.ps1

param(
    [int]$EvalEveryMinutes = 30,
    [int]$RoundSleepSec   = 1200,
    [switch]$SkipAutopilot,
    [switch]$SkipMorpheus,
    [switch]$SkipEvalDaemon,
    [switch]$Interactive          # legacy: open a TUI claude window instead of the headless loop
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-LiveLockPid {
    param([Parameter(Mandatory)][string]$LockPath)

    if (-not (Test-Path $LockPath)) { return $null }
    $raw = Get-Content -Path $LockPath -Raw -ErrorAction SilentlyContinue
    if ($null -eq $raw) { return $null }

    $pidValue = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$pidValue)) { return $null }
    if ($pidValue -le 0) { return $null }

    try {
        $proc = Get-Process -Id $pidValue -ErrorAction Stop
        if ($null -ne $proc) { return $pidValue }
    } catch {}

    Remove-Item -Path $LockPath -Force -ErrorAction SilentlyContinue
    return $null
}

$scriptDir   = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $scriptDir)
$promptFile  = Join-Path $projectRoot '.squad\identity\long-run-prompt.md'
$stateDir    = Join-Path $projectRoot '.squad\state'
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Long-Run Mode — Modular Pipeline Script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# --- 1 + 2. Autopilot (watcher + sweeper) ---
if (-not $SkipAutopilot) {
    Write-Host "[1/4] Starting autopilot (watcher + sweeper)..." -ForegroundColor Green
    & (Join-Path $scriptDir 'start-squad-autopilot.ps1')
} else {
    Write-Host "[1/4] Skipped autopilot (--SkipAutopilot)." -ForegroundColor DarkGray
}

# --- 3. RAG eval daemon (pushes summary to Morpheus via `squad send`) ---
if (-not $SkipEvalDaemon) {
    Write-Host "[2/4] Starting RAG eval daemon (every $EvalEveryMinutes min, notifies morpheus)..." -ForegroundColor Green
    $evalScript = Join-Path $scriptDir 'rag-eval-daemon.ps1'
    if (-not (Test-Path $evalScript)) {
        Write-Host "  rag-eval-daemon.ps1 missing at $evalScript — skipping." -ForegroundColor Yellow
    } else {
        $evalLock = Join-Path $stateDir 'rag-eval-daemon.lock'
        $evalPid = Get-LiveLockPid -LockPath $evalLock
        if ($null -ne $evalPid) {
            Write-Host "  rag-eval-daemon already running (pid=$evalPid) — skipping." -ForegroundColor Yellow
        } else {
            # -PassThru + write lock so supervisor doesn't false-dead this on first pass.
            # Added 2026-04-26 — fixes daemon-twin bug.
            $evalProc = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
                '-NoExit',
                '-ExecutionPolicy','Bypass',
                '-Command', "`$Host.UI.RawUI.WindowTitle = 'rag-eval-daemon'; & '$evalScript' -EveryMinutes $EvalEveryMinutes"
            ) -WindowStyle Minimized -PassThru
            Set-Content -Path $evalLock -Value ([string]$evalProc.Id) -Encoding UTF8
        }
    }
} else {
    Write-Host "[2/4] Skipped RAG eval daemon (--SkipEvalDaemon)." -ForegroundColor DarkGray
}

# --- 4. Morpheus: headless loop (Gamma, default) or interactive TUI window ---
if (-not $SkipMorpheus) {
    if ($Interactive) {
        Write-Host "[3/4] Staging long-run kickoff prompt on clipboard (interactive mode)..." -ForegroundColor Green
        if (-not (Test-Path $promptFile)) {
            Write-Host "  prompt file missing: $promptFile" -ForegroundColor Red
        } else {
            Get-Content $promptFile -Raw | Set-Clipboard
            Write-Host "  clipboard now holds the long-run kickoff prompt." -ForegroundColor DarkGray
            Write-Host "[4/4] Opening Morpheus Claude window..." -ForegroundColor Green
            $morpheusCmd = @'
$Host.UI.RawUI.WindowTitle = 'morpheus-long-run'
Write-Host 'Morpheus long-run window. Steps:' -ForegroundColor Cyan
Write-Host '  1. Run:  claude' -ForegroundColor Yellow
Write-Host '  2. When Claude is ready, paste (Ctrl+V) and press Enter.' -ForegroundColor Yellow
Write-Host '  3. Type:  /squad morpheus' -ForegroundColor Yellow
Write-Host ''
'@
            Start-Process -FilePath 'powershell.exe' -ArgumentList @(
                '-NoExit','-ExecutionPolicy','Bypass','-Command', $morpheusCmd
            ) -WorkingDirectory $projectRoot | Out-Null
        }
    } else {
        Write-Host "[3/4] Starting Morpheus headless loop (Gamma, true unattended)..." -ForegroundColor Green
        $headless = Join-Path $scriptDir 'morpheus-headless.ps1'
        if (-not (Test-Path $headless)) {
            Write-Host "  morpheus-headless.ps1 missing at $headless — skipping." -ForegroundColor Yellow
        } else {
            # Pre-flight: refuse to start a second morpheus if the identity is
            # already held by a live PID (manual claude /squad morpheus, or a
            # surviving headless from a previous run). Otherwise the new process
            # would collide and squad CLI would auto-suffix it to morpheus-2.
            # Added 2026-04-26 — anti-collision via squad-lock.ps1.
            . (Join-Path $scriptDir 'squad-lock.ps1')
            if (Test-SquadIdentityHeld -Role 'morpheus') {
                $heldPid = (Get-SquadLockPid -Path (Resolve-LockPath -Role 'morpheus'))
                Write-Host "  morpheus identity already held by PID $heldPid — skipping headless launch." -ForegroundColor Yellow
                Write-Host "  (run 'squad long-stop' first if you want to replace it.)" -ForegroundColor DarkGray
            } else {
                # -PassThru + pre-seed process lock so supervisor doesn't race-restart
                # morpheus in the gap between Start-Process returning and the child's
                # own Acquire-MorpheusProcessLock writing its lock entry. Pre-seeded
                # PID matches what morpheus will write once it boots, so its self-
                # acquire is a no-op overwrite.
                # Added 2026-04-26 — fixes daemon-twin bug.
                $morpheusProc = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
                    '-NoExit',
                    '-ExecutionPolicy','Bypass',
                    '-Command', "`$Host.UI.RawUI.WindowTitle = 'morpheus-headless'; & '$headless' -RoundSleepSec $RoundSleepSec"
                ) -WindowStyle Minimized -WorkingDirectory $projectRoot -PassThru
                Set-Content -Path (Join-Path $stateDir 'morpheus-headless.lock') -Value ([string]$morpheusProc.Id) -Encoding UTF8
                Write-Host "[4/4] Morpheus headless window launched (title: morpheus-headless, minimised)." -ForegroundColor DarkGray
            }
        }
    }
} else {
    Write-Host "[3/4,4/4] Skipped Morpheus (--SkipMorpheus)." -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Long-run mode is up." -ForegroundColor Cyan
Write-Host "Minimised windows: squad-watcher / squad-sweeper / rag-eval-daemon / morpheus-headless" -ForegroundColor DarkGray
if ($Interactive) {
    Write-Host "Interactive mode: morpheus kickoff prompt is on your clipboard — paste it into the new claude session." -ForegroundColor DarkGray
} else {
    Write-Host "Gamma mode (default): morpheus-headless.ps1 is looping every $RoundSleepSec s. No further action needed." -ForegroundColor DarkGray
    Write-Host "Tail the round log:  Get-Content .\.squad\state\morpheus-rounds.jsonl -Wait" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Stop: close those windows, then .\tools\squad\squad-cleanup.ps1" -ForegroundColor Yellow
