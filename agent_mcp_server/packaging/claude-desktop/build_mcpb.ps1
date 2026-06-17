param(
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

function Resolve-RepositoryRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    $current = (Resolve-Path -LiteralPath $ScriptPath).Path
    while ($true) {
        if (Test-Path -LiteralPath (Join-Path $current "AI_WORKSPACE_GUIDE.md")) {
            return $current
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) {
            throw "Could not find repository root containing AI_WORKSPACE_GUIDE.md"
        }
        $current = $parent
    }
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-RepositoryRoot -ScriptPath $scriptDirectory
$packageRoot = Join-Path $repoRoot "agent_mcp_server\packaging\claude-desktop"
$manifestPath = Join-Path $packageRoot "manifest.json"

if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Missing manifest: $manifestPath"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $outputDirectory = Join-Path $repoRoot "workspace_artifacts\agent_mcp_workflows\packages"
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    $OutputPath = Join-Path $outputDirectory "literature-assistant-toolbox.mcpb"
}

$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("lit-assistant-mcpb-" + [System.Guid]::NewGuid().ToString("N"))
$serverDirectory = Join-Path $stagingRoot "server"
New-Item -ItemType Directory -Force -Path $serverDirectory | Out-Null

try {
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $stagingRoot "manifest.json") -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot "agent_mcp_server\bin\lit-assistant-mcp.ps1") -Destination (Join-Path $serverDirectory "lit-assistant-mcp.ps1") -Force

    if (Test-Path -LiteralPath $OutputPath) {
        Remove-Item -LiteralPath $OutputPath -Force
    }
    Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $OutputPath -Force
    if ([System.IO.Path]::GetExtension($OutputPath) -ne ".mcpb") {
        Write-Warning "Output file does not use .mcpb extension: $OutputPath"
    }
    Write-Output (Resolve-Path -LiteralPath $OutputPath).Path
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
