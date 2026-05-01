# eval-daemon-watchdog.ps1 — fires when newest .squad/evaluations/run-*.json
# is older than -MaxAgeMinutes. Per pool 45/50 SELF-APPLIED-NEXT-ROUND entry
# (round 6 session 073042). Scope v0: detect-only stale check + optional kill
# + respawn. Does NOT touch .env or credentials. Recovery just re-stamps the
# artifact; real pass/fail still comes from /api/chat behind HARD-STOP-CODE.

[CmdletBinding()]
param(
    [string]$EvalDir = '.squad/evaluations',
    [int]$MaxAgeMinutes = 60,
    [string]$LockFile = '.squad/evaluations/.run-lock',
    [string]$RunScript = 'tools/squad/run-rag-once.ps1',
    [string]$TrailFile = '.squad/memory/DECISION_TRAIL.md',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $EvalDir)) {
    Write-Output "no-op: eval dir missing"
    exit 0
}

$newest = Get-ChildItem -Path $EvalDir -Filter 'run-*.json' -File -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $newest) {
    Write-Output "no-op: no eval files"
    exit 0
}

$ageMin = [int]((Get-Date) - $newest.LastWriteTime).TotalMinutes
if ($ageMin -le $MaxAgeMinutes) {
    Write-Output "fresh: age=${ageMin}m newest=$($newest.Name)"
    exit 0
}

# Stale path
$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$killedPids = @()
$procs = Get-Process pwsh,powershell -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -and $_.CommandLine -match 'run-rag-once' }
if ($DryRun) {
    Write-Output "DRY: would-kill PIDs=$($procs.Id -join ',') age=${ageMin}m"
    exit 0
}
foreach ($p in $procs) {
    try { Stop-Process -Id $p.Id -Force -ErrorAction Stop; $killedPids += $p.Id } catch { }
}
if (Test-Path $LockFile) { Remove-Item $LockFile -Force -ErrorAction SilentlyContinue }

$respawnExit = -1
if (Test-Path $RunScript) {
    $proc = Start-Process pwsh -ArgumentList '-NoProfile','-File',$RunScript -PassThru -WindowStyle Hidden
    $respawnExit = if ($proc) { 0 } else { 1 }
}

$line = "`nDAEMON-STALE-RECOVERY [$ts] age=${ageMin}m killed=[$($killedPids -join ',')] respawn_exit=$respawnExit newest_was=$($newest.Name)"
Add-Content -Path $TrailFile -Value $line -Encoding UTF8
Write-Output $line.Trim()
exit 0
