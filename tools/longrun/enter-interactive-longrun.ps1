param(
    [string]$Workspace = "",
    [int]$TtlMinutes = 180,
    [string]$Reason = "interactive VS Codex longrun"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-Workspace {
    param([string]$Candidate)

    if (-not [string]::IsNullOrWhiteSpace($Candidate)) {
        return (Resolve-Path -LiteralPath $Candidate -ErrorAction Stop).Path
    }

    return (Resolve-Path -LiteralPath (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) -ErrorAction Stop).Path
}

if ($TtlMinutes -lt 5 -or $TtlMinutes -gt 1440) {
    throw 'TtlMinutes must be between 5 and 1440.'
}
if ([string]::IsNullOrWhiteSpace($Reason)) {
    throw 'Reason cannot be empty.'
}

$workspacePath = Resolve-Workspace -Candidate $Workspace
$stateDir = Join-Path $workspacePath 'workspace_artifacts\runtime_state\longrun-supervisor'
$sessionPath = Join-Path $stateDir 'interactive-session.json'
$eventsPath = Join-Path $stateDir 'events.jsonl'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

$now = Get-Date
$session = [ordered]@{
    session_id = $now.ToString('yyyyMMdd-HHmmss')
    pid = $PID
    reason = $Reason
    started_at = $now.ToString('o')
    expires_at = $now.AddMinutes($TtlMinutes).ToString('o')
}
Set-Content -LiteralPath $sessionPath -Value ($session | ConvertTo-Json -Depth 8) -Encoding UTF8

$event = [ordered]@{
    ts = $now.ToString('o')
    event = 'interactive_session_entered'
    session_id = $session.session_id
    expires_at = $session.expires_at
    reason = $Reason
} | ConvertTo-Json -Compress
Add-Content -LiteralPath $eventsPath -Value $event -Encoding UTF8

Write-Host "Interactive longrun marker created: $sessionPath"
Write-Host "Scheduled supervisor will skip until: $($session.expires_at)"
