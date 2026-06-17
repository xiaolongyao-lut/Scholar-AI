param(
    [switch]$PrintOnly
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

& codex mcp add literature_assistant -- powershell -NoProfile -ExecutionPolicy Bypass -File $wrapperPath
exit $LASTEXITCODE
