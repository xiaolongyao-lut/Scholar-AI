param(
    [string]$Workspace = "",
    [string]$Reason = "manual pause"
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

if ([string]::IsNullOrWhiteSpace($Reason)) {
    throw 'Reason cannot be empty.'
}

$workspacePath = Resolve-Workspace -Candidate $Workspace
$stateDir = Join-Path $workspacePath 'workspace_artifacts\runtime_state\longrun-supervisor'
$stopPath = Join-Path $stateDir 'STOP'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
Set-Content -LiteralPath $stopPath -Value "Paused at $(Get-Date -Format o): $Reason" -Encoding UTF8
Write-Host "Paused longrun supervisor with stop file: $stopPath"
