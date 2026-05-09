param(
    [string]$Workspace = "",
    [int]$MaxRunMinutes = 25,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($MaxRunMinutes -lt 5 -or $MaxRunMinutes -gt 180) {
    throw 'MaxRunMinutes must be between 5 and 180.'
}

$runner = Join-Path $PSScriptRoot 'invoke-longrun-supervisor.ps1'
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Runner script is missing: $runner"
}

$arguments = @{
    MaxRunMinutes = $MaxRunMinutes
    RunSource = 'Manual'
}

if (-not [string]::IsNullOrWhiteSpace($Workspace)) {
    $arguments['Workspace'] = $Workspace
}
if ($DryRun) {
    $arguments['DryRun'] = $true
}

& $runner @arguments
