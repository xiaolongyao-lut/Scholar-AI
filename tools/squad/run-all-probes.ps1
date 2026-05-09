# run-all-probes.ps1 — cron-fitness wrapper for .squad/tools/run_all_probes.py
#
# Discharges R6 of .squad/specs/probe-runner-aggregator.md (round 21
# brief 141937): "callable from check-eval-cadence.ps1-style scheduler
# with no positional args and exits in <2 minutes total against the 4
# live probes". Round 24 brief 142501. R5 contract test was claimed by
# parallel-Morpheus at 14:25 (race-loss); R6 wrapper is virgin per
# `ls tools/squad/run-all-probes.ps1` → ENOENT at brief-142501.
#
# Sibling cohort: tools/squad/check-eval-cadence.ps1 (which spec §3 R6
# explicitly references as the wrapper-style template).
#
# Exit codes (passthrough from Python runner):
#   0 = all probes passed
#   1 = >=1 probe failed predicate
#   2 = environmental failure (no probes matched, timeout, missing binary)
#
# Output:
#   - Default: emits the runner's JSON to stdout (cron-fitness contract).
#   - With -ReportPath <path>: also writes JSON to that path atomically
#     (.tmp + Move-Item). Useful for cron loops that archive runs.

[CmdletBinding()]
param(
    [string] $Probes = 'probe_*.py',
    [string] $ReportPath = '',
    [int]    $TimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$Runner   = Join-Path $RepoRoot '.squad\tools\run_all_probes.py'

if (-not (Test-Path $Runner)) {
    Write-Error "runner not found at $Runner"
    exit 2
}

$pythonExe = if ($env:PYTHON) { $env:PYTHON } else { 'python' }

$args = @('-u', $Runner, '--probes', $Probes)

$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING        = 'utf-8'

$proc = Start-Process -FilePath $pythonExe -ArgumentList $args `
    -NoNewWindow -PassThru -RedirectStandardOutput 'stdout.tmp' `
    -RedirectStandardError 'stderr.tmp' -WorkingDirectory $RepoRoot

if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
    try { $proc.Kill() } catch { }
    Remove-Item -Force 'stdout.tmp', 'stderr.tmp' -ErrorAction SilentlyContinue
    Write-Error "runner exceeded $TimeoutSeconds s wall-clock; killed"
    exit 2
}

$stdout = Get-Content 'stdout.tmp' -Raw -ErrorAction SilentlyContinue
$stderr = Get-Content 'stderr.tmp' -Raw -ErrorAction SilentlyContinue
Remove-Item -Force 'stdout.tmp', 'stderr.tmp' -ErrorAction SilentlyContinue

if ($stderr) { Write-Host $stderr -ForegroundColor Yellow }
if ($stdout) { Write-Output $stdout }

if ($ReportPath) {
    $tmp = "$ReportPath.tmp"
    Set-Content -Path $tmp -Value $stdout -Encoding UTF8 -NoNewline
    Move-Item -Path $tmp -Destination $ReportPath -Force
}

exit $proc.ExitCode
