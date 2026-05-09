[CmdletBinding()]
param(
    [string]$StateRoot = (Join-Path $HOME '.openclaw'),
    [string]$ProjectRoot = (Join-Path $PSScriptRoot '..\..'),
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-PersistedWeixinAccountArtifacts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedStateRoot
    )

    $accountsDir = Join-Path $ResolvedStateRoot 'openclaw-weixin\accounts'
    if (-not (Test-Path $accountsDir)) {
        return @()
    }

    return @(Get-ChildItem -Path $accountsDir -File -Filter '*.json' | Where-Object {
        $_.Name -notlike '*.context-tokens.json' -and $_.Name -notlike '*.sync.json'
    })
}

function Get-OpenClawCommandPlan {
    return @(
        @('config', 'set', 'gateway.mode', 'local'),
        @('config', 'set', 'gateway.bind', 'loopback'),
        @('gateway', 'run', '--force')
    )
}

function Get-WeixinBackendEnvironmentPlan {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ResolvedProjectRoot
    )

    return [ordered]@{
        WEIXIN_CODEX_ACP_CWD = $ResolvedProjectRoot
        CODEX_ACP_CWD = $ResolvedProjectRoot
        WEIXIN_CLAUDE_ACP_CWD = $ResolvedProjectRoot
        CLAUDE_ACP_CWD = $ResolvedProjectRoot
        WEIXIN_COPILOT_ACP_CWD = $ResolvedProjectRoot
        COPILOT_ACP_CWD = $ResolvedProjectRoot
        WEIXIN_ANTIGRAVITY_CWD = $ResolvedProjectRoot
        ANTIGRAVITY_CWD = $ResolvedProjectRoot
        WEIXIN_ANTIGRAVITY_BIN = (Join-Path $env:LOCALAPPDATA 'Programs\Antigravity\Antigravity.exe')
        WEIXIN_CODEX_ACP_PERMISSION_MODE = 'auto'
        WEIXIN_CLAUDE_ACP_PERMISSION_MODE = 'auto'
        WEIXIN_COPILOT_ACP_PERMISSION_MODE = 'auto'
        WEIXIN_COPILOT_ACP_ARGS = '--acp --stdio --allow-all'
        COPILOT_ACP_ARGS = '--acp --stdio --allow-all'
    }
}

function Set-WeixinBackendEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$EnvironmentPlan
    )

    foreach ($name in $EnvironmentPlan.Keys) {
        Set-Item -Path ("Env:{0}" -f $name) -Value $EnvironmentPlan[$name]
    }
}

function Assert-OpenClawCli {
    $cmd = Get-Command openclaw -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        throw 'openclaw CLI not found in PATH.'
    }
}

function Invoke-OpenClawCommandPlan {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Plan
    )

    foreach ($command in $Plan) {
        Write-Output ("Running: openclaw {0}" -f ($command -join ' '))
        & openclaw @command
        if ($LASTEXITCODE -ne 0) {
            throw ("openclaw command failed: openclaw {0}" -f ($command -join ' '))
        }
    }
}

$resolvedStateRoot = [System.IO.Path]::GetFullPath($StateRoot)
$resolvedProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
if (-not (Test-Path $resolvedProjectRoot)) {
    throw ("Project root does not exist: {0}" -f $resolvedProjectRoot)
}
$persistedArtifacts = @(Get-PersistedWeixinAccountArtifacts -ResolvedStateRoot $resolvedStateRoot)
$commandPlan = @(Get-OpenClawCommandPlan)
$environmentPlan = Get-WeixinBackendEnvironmentPlan -ResolvedProjectRoot $resolvedProjectRoot

Write-Output ("OpenClaw state root: {0}" -f $resolvedStateRoot)
Write-Output ("Backend project root: {0}" -f $resolvedProjectRoot)

if ($persistedArtifacts.Count -gt 0) {
    Write-Output 'Persisted Weixin session artifacts found.'
    Write-Output 'QR login is likely not required unless the saved session has expired.'
}
else {
    Write-Output 'No persisted Weixin account artifact found.'
    Write-Output 'QR login may be required on the next manual login.'
}

if ($DryRun) {
    Write-Output 'Dry run only. Environment:'
    foreach ($name in $environmentPlan.Keys) {
        Write-Output ("{0}={1}" -f $name, $environmentPlan[$name])
    }
    Write-Output 'Dry run only. Commands:'
    foreach ($command in $commandPlan) {
        Write-Output ("openclaw {0}" -f ($command -join ' '))
    }
    $global:LASTEXITCODE = 0
    return
}

Set-WeixinBackendEnvironment -EnvironmentPlan $environmentPlan
Assert-OpenClawCli
Invoke-OpenClawCommandPlan -Plan $commandPlan
$global:LASTEXITCODE = 0
