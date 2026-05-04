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
$stopPath = Join-Path $workspacePath 'workspace_artifacts\runtime_state\longrun-supervisor\STOP'
if (Test-Path -LiteralPath $stopPath) {
    Remove-Item -LiteralPath $stopPath -Force
    Write-Host "Resumed longrun supervisor."
} else {
    Write-Host "Longrun supervisor was not paused."
}
