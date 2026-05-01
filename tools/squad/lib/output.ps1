Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-SquadStatus {
    param(
        [string]$Message,
        [ValidateSet('ok','warn','error')]
        [string]$Level = 'ok'
    )

    switch ($Level) {
        'ok' { Write-Host $Message -ForegroundColor Green }
        'warn' { Write-Host $Message -ForegroundColor Yellow }
        'error' { Write-Host $Message -ForegroundColor Red }
    }
}

function Exit-Squad {
    param(
        [int]$Code,
        [string]$Reason
    )

    if ($Reason) {
        [Console]::Error.WriteLine($Reason)
    }
    exit $Code
}
