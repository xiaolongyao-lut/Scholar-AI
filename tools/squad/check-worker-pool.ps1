# check-worker-pool.ps1
#
# Pre-dispatch worker-liveness gate for the squad task queue.
#
# Reads `squad agents` output and reports whether at least one *fresh*
# non-morpheus claude-protocol-2 worker is reachable. Morpheus calls this
# BEFORE `squad task create` so a dispatch never lands in a graveyard queue.
#
# Source: requirement-pool.md session 070436 entry "pre-dispatch worker-
# liveness gate" (43/50, line ~2546). Spec called for the regex shape
#   ^\s*(\S+).*role:\s*(\S+).*(idle|active)\s*\((\d+)m\)
# but the current `squad agents` output uses "(2m ago)" rather than "(2m)";
# also emits "(56s ago)" for sub-minute heartbeats. This implementation
# tightens the regex accordingly and treats seconds-units as 0 minutes.
#
# Exit codes:
#   0  FRESH            — at least one worker satisfies all filters; ids on stdout
#   2  WORKER-POOL-STALE — no qualifying worker; structured reason on stderr
#   3  CLI-ERROR        — `squad agents` not reachable / unparseable
#
# Read-only: never writes any file in v0.

[CmdletBinding()]
param(
    [int]$MaxAgeMinutes = 5,
    [string]$RequireProtocol = '2',
    [string]$RequireClient = 'claude',
    [string]$ExcludeRole = 'morpheus',
    # Test hook: when set, parse this string instead of shelling out.
    [string]$AgentsOutput = ''
)

$ErrorActionPreference = 'Continue'

# 1. Acquire `squad agents` output (or use injected fixture for tests).
if ([string]::IsNullOrEmpty($AgentsOutput)) {
    $raw = & squad agents 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        [Console]::Error.WriteLine('CLI-ERROR: squad agents unreachable or empty')
        exit 3
    }
    $lines = @($raw)
} else {
    $lines = $AgentsOutput -split "`r?`n"
}

# 2. Parse each line.  Format observed:
#   <id> (role: <role>) — <state> (<n><unit> ago) [client: <client>, protocol: <n>]
# unit is s | m | h.  Seconds count as 0 minutes for the gate.
$pattern = '^\s*(?<id>\S+)\s+\(role:\s*(?<role>\S+)\)\s+\S+\s+(?<state>\S+)\s+\((?<n>\d+)(?<unit>[smh])\s+ago\)\s+\[client:\s*(?<client>[^,\]]+),\s*protocol:\s*(?<proto>\d+)\]'

$fresh = New-Object System.Collections.ArrayList

foreach ($line in $lines) {
    $m = [regex]::Match($line, $pattern)
    if (-not $m.Success) { continue }

    $id      = $m.Groups['id'].Value
    $role    = $m.Groups['role'].Value
    $state   = $m.Groups['state'].Value
    $n       = [int]$m.Groups['n'].Value
    $unit    = $m.Groups['unit'].Value
    $client  = $m.Groups['client'].Value.Trim()
    $proto   = $m.Groups['proto'].Value

    if ($role -eq $ExcludeRole) { continue }
    if ($client -ne $RequireClient) { continue }
    if ($proto -ne $RequireProtocol) { continue }
    if ($state -notin @('idle', 'active')) { continue }

    $minutes = switch ($unit) { 's' { 0 }  'm' { $n }  'h' { $n * 60 } }
    if ($minutes -gt $MaxAgeMinutes) { continue }

    [void]$fresh.Add($id)
}

# 3. Decide.
if ($fresh.Count -eq 0) {
    $ts = Get-Date -Format 's'
    [Console]::Error.WriteLine("WORKER-POOL-STALE: no claude-protocol-$RequireProtocol worker (excluding role=$ExcludeRole) with heartbeat <= ${MaxAgeMinutes}m at $ts")
    exit 2
}

foreach ($id in $fresh) { Write-Output $id }
exit 0
