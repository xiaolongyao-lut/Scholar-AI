Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $PSCommandPath
$wrapper = Join-Path $scriptDir 'squad.ps1'

if (-not (Test-Path $wrapper)) {
    throw "Wrapper script not found: $wrapper"
}

if (-not $env:SQUAD_REAL_CLI) {
    $cmd = Get-Command squad -ErrorAction SilentlyContinue
    if ($null -ne $cmd -and $cmd.CommandType -ne 'Function') {
        $env:SQUAD_REAL_CLI = $cmd.Source
    }
}

function global:squad {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Args
    )

    & $wrapper @Args
}

Write-Output "Squad wrapper enabled (current session)."
