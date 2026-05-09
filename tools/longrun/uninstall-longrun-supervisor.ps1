param(
    [string]$Workspace = "",
    [string]$TaskName = "LiteratureAssistantLongrunAutopilot",
    [switch]$LeaveStopFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-Workspace {
    param([string]$Candidate)

    if (-not [string]::IsNullOrWhiteSpace($Candidate)) {
        return (Resolve-Path -LiteralPath $Candidate -ErrorAction Stop).Path
    }

    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path -LiteralPath (Split-Path -Parent (Split-Path -Parent $scriptDir)) -ErrorAction Stop).Path
}

if ([string]::IsNullOrWhiteSpace($TaskName)) {
    throw 'TaskName cannot be empty.'
}

$workspacePath = Resolve-Workspace -Candidate $Workspace
$stateDir = Join-Path $workspacePath 'workspace_artifacts\runtime_state\longrun-supervisor'
$stopPath = Join-Path $stateDir 'STOP'

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $task) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

if ($LeaveStopFile) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    Set-Content -LiteralPath $stopPath -Value "Stopped at $(Get-Date -Format o)" -Encoding UTF8
} elseif (Test-Path -LiteralPath $stopPath) {
    Remove-Item -LiteralPath $stopPath -Force
}

Write-Host "Uninstalled scheduled task: $TaskName"
if ($LeaveStopFile) {
    Write-Host "Stop file left at: $stopPath"
}
