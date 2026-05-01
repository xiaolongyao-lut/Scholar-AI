Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-RecommendedDecision {
    param(
        [string]$RepoRoot,
        [string]$Tier,
        [string]$BlockerType
    )

    $kernelPath = Join-Path $RepoRoot '.squad\kernel\defaults.json'
    $defaults = Get-Content -LiteralPath $kernelPath -Raw | ConvertFrom-Json

    if ($defaults.tiers.PSObject.Properties.Name -notcontains $Tier) {
        throw "Unknown tier: $Tier"
    }

    $tierDef = $defaults.tiers.$Tier
    if ($tierDef.behaviors.PSObject.Properties.Name -notcontains $BlockerType) {
        throw "Unknown blocker type: $BlockerType"
    }

    return [string]$tierDef.behaviors.$BlockerType
}

function Test-MustEscalate {
    param([string]$BlockerType)

    return $BlockerType -eq 'constraint'
}
