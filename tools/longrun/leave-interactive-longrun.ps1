param(
    [string]$Workspace = ""
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

$workspacePath = Resolve-Workspace -Candidate $Workspace
$stateDir = Join-Path $workspacePath 'workspace_artifacts\runtime_state\longrun-supervisor'
$sessionPath = Join-Path $stateDir 'interactive-session.json'
$eventsPath = Join-Path $stateDir 'events.jsonl'

if (Test-Path -LiteralPath $sessionPath) {
    $raw = Get-Content -LiteralPath $sessionPath -Raw -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $sessionPath -Force
    $event = [ordered]@{
        ts = (Get-Date).ToString('o')
        event = 'interactive_session_left'
        previous_session = $raw
    } | ConvertTo-Json -Compress
    Add-Content -LiteralPath $eventsPath -Value $event -Encoding UTF8
    Write-Host "Interactive longrun marker removed."
} else {
    Write-Host "No interactive longrun marker was present."
}
