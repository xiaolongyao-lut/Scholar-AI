param(
    [switch]$PrintOnly
)

$ErrorActionPreference = "Stop"

function Test-RepositoryRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate
    )

    if (Test-Path -LiteralPath (Join-Path $Candidate "AI_WORKSPACE_GUIDE.md") -PathType Leaf) {
        return $true
    }

    return (
        (Test-Path -LiteralPath (Join-Path $Candidate "SOURCE_RELEASE_POLICY.md") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Candidate "pyproject.toml") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Candidate "agent_mcp_server") -PathType Container) -and
        (Test-Path -LiteralPath (Join-Path $Candidate "literature_assistant") -PathType Container)
    )
}

function Resolve-RepositoryRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    $current = (Resolve-Path -LiteralPath $ScriptPath).Path
    while ($true) {
        if (Test-RepositoryRoot -Candidate $current) {
            return $current
        }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrWhiteSpace($parent) -or $parent -eq $current) {
            throw "Could not find repository root containing Scholar AI repository anchors"
        }
        $current = $parent
    }
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-RepositoryRoot -ScriptPath $scriptDirectory
$wrapperPath = Join-Path $repoRoot "agent_mcp_server\bin\lit-assistant-mcp.ps1"

if (-not (Test-Path -LiteralPath $wrapperPath -PathType Leaf)) {
    throw "Missing wrapper: $wrapperPath"
}

$commandParts = @(
    "codex",
    "mcp",
    "add",
    "literature_assistant",
    "--",
    "powershell",
    "-NoProfile",
    "-WindowStyle",
    "Hidden",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $wrapperPath
)

if ($PrintOnly) {
    $renderedCommand = ($commandParts | ForEach-Object {
        if ($_ -match "\s") { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join " "
    Write-Output $renderedCommand
    exit 0
}

& codex mcp add literature_assistant -- powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $wrapperPath
exit $LASTEXITCODE
