Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-TierCommand {
    param(
        [string]$RepoRoot,
        [string[]]$CmdArgs
    )

    if ($null -eq $CmdArgs -or $CmdArgs.Count -eq 0) {
        $current = Get-AutonomyTier -RepoRoot $RepoRoot
        Write-Host "Current tier: $current"
        return
    }

    if ($CmdArgs[0] -eq '--explain') {
        $kernelPath = Join-Path $RepoRoot '.squad\kernel\defaults.json'
        if (-not (Test-Path $kernelPath)) {
            [Console]::Error.WriteLine("Kernel defaults not found at: $kernelPath")
            exit 1
        }
        $defaults = Get-Content -LiteralPath $kernelPath -Raw | ConvertFrom-Json
        Write-Host "Autonomy tier behavior matrix (kernel v$($defaults.kernel_version)):"
        Write-Host ""
        foreach ($tierProp in $defaults.tiers.PSObject.Properties) {
            $tName = $tierProp.Name
            $tDef  = $tierProp.Value
            Write-Host "[$tName] $($tDef.description)"
            foreach ($bProp in $tDef.behaviors.PSObject.Properties) {
                Write-Host ("  " + $bProp.Name.PadRight(16) + "-> " + $bProp.Value)
            }
            Write-Host ""
        }
        return
    }

    $validTiers = @('default', 'autopilot')
    if ($CmdArgs[0] -notin $validTiers) {
        [Console]::Error.WriteLine("Invalid tier '$($CmdArgs[0])'. Valid values: default, autopilot")
        exit 1
    }

    Set-AutonomyTier -RepoRoot $RepoRoot -Tier $CmdArgs[0]
    Write-Host "Tier set to $($CmdArgs[0])"
}
