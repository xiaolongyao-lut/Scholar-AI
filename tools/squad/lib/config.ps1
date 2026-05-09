Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-SquadConfigPath {
    param([string]$RepoRoot)

    return Join-Path $RepoRoot '.squad\config.json'
}

function Get-SquadConfig {
    param(
        [string]$RepoRoot,
        [string]$Key
    )

    $path = Get-SquadConfigPath -RepoRoot $RepoRoot
    if (-not (Test-Path $path)) {
        return $null
    }

    $cfg = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if ($cfg.PSObject.Properties.Name -contains $Key) {
        return $cfg.$Key
    }

    return $null
}

function Set-SquadConfig {
    param(
        [string]$RepoRoot,
        [string]$Key,
        $Value
    )

    $path = Get-SquadConfigPath -RepoRoot $RepoRoot
    if (-not (Test-Path $path)) {
        throw '.squad/config.json not found. Run squad init first.'
    }

    $cfg = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    $cfg | Add-Member -NotePropertyName $Key -NotePropertyValue $Value -Force

    # Atomic write per CLAUDE.md §4.7: write to .tmp then Move-Item -Force.
    # Prevents corruption of .squad/config.json on crash mid-write.
    # Audit anchor: .squad/audits/atomic-write-audit-2026-04-25.md (P1 violator #1, lib/config.ps1:43).
    # Variable named $pathTmp to match the project's `<base>Tmp` convention (e.g. $markerTmp,
    # $sessIdTmp, $auditFileTmp) — also satisfies tools/squad/check-atomic-write.ps1's
    # `compliant` regex `Set-Content -LiteralPath \$\w*[Tt]mp\b`.
    $pathTmp = "$path.tmp"
    $cfg | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $pathTmp -Encoding utf8
    Move-Item -LiteralPath $pathTmp -Destination $path -Force
}

function Get-AutonomyTier {
    param([string]$RepoRoot)

    $tier = Get-SquadConfig -RepoRoot $RepoRoot -Key 'autonomy_tier'
    if (-not $tier) {
        return 'default'
    }

    return [string]$tier
}

function Set-AutonomyTier {
    param(
        [string]$RepoRoot,
        [ValidateSet('default','autopilot')]
        [string]$Tier
    )

    Set-SquadConfig -RepoRoot $RepoRoot -Key 'autonomy_tier' -Value $Tier
}
