param(
    [switch]$SelfTest,
    [switch]$PrintConfig
)

$ErrorActionPreference = "Stop"

function Resolve-RepositoryRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath
    )

    if (-not [string]::IsNullOrWhiteSpace($env:LITERATURE_ASSISTANT_REPO_ROOT)) {
        $envRoot = (Resolve-Path -LiteralPath $env:LITERATURE_ASSISTANT_REPO_ROOT).Path
        if (Test-Path -LiteralPath (Join-Path $envRoot "AI_WORKSPACE_GUIDE.md")) {
            return $envRoot
        }
        throw "LITERATURE_ASSISTANT_REPO_ROOT does not contain AI_WORKSPACE_GUIDE.md: $envRoot"
    }

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

function Join-PathList {
    param(
        [AllowEmptyString()]
        [string[]]$Paths
    )

    $existing = @()
    foreach ($path in $Paths) {
        if (-not [string]::IsNullOrWhiteSpace($path)) {
            $existing += $path
        }
    }
    return ($existing -join [System.IO.Path]::PathSeparator)
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-RepositoryRoot -ScriptPath $scriptDirectory
$pythonExe = Join-Path $repoRoot ".venv-1\Scripts\python.exe"
$mcpSourceRoot = Join-Path $repoRoot "agent_mcp_server\src"

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Missing Python interpreter: $pythonExe"
}

if (-not (Test-Path -LiteralPath $mcpSourceRoot -PathType Container)) {
    throw "Missing MCP source root: $mcpSourceRoot"
}

$env:LITERATURE_ASSISTANT_REPO_ROOT = $repoRoot
if ([string]::IsNullOrWhiteSpace($env:LITERATURE_ASSISTANT_BASE_URL)) {
    $env:LITERATURE_ASSISTANT_BASE_URL = "http://127.0.0.1:8000"
}
$env:PYTHONPATH = Join-PathList -Paths @(
    $mcpSourceRoot,
    $repoRoot,
    (Join-Path $repoRoot "literature_assistant\core"),
    $env:PYTHONPATH
)

if ($PrintConfig) {
    [PSCustomObject]@{
        repo_root = $repoRoot
        python = $pythonExe
        mcp_source_root = $mcpSourceRoot
        backend_base_url = $env:LITERATURE_ASSISTANT_BASE_URL
    } | ConvertTo-Json -Depth 3
    exit 0
}

if ($SelfTest) {
    $selfTestScript = @'
from __future__ import annotations

import os

from lit_assistant_mcp.server import create_mcp_server, find_repo_root

repo_root = find_repo_root()
server = create_mcp_server()
tool_names = sorted(tool.name for tool in server._tool_manager.list_tools())
required = {
    "source.list_tree",
    "source.search",
    "source.read_file",
    "source.read_symbols",
    "source.inspect_routes",
    "source.find_references",
    "source.explain_entrypoints",
    "literature.config_status",
    "literature.list_projects",
    "literature.list_materials",
    "literature.read_material",
    "literature.get_material_chunks",
    "literature.search_literature",
    "literature.ingest_then_search",
    "literature.export_annotations_markdown",
    "workflow.create_plan",
    "workflow.write_json_workflow",
    "workflow.run_json_workflow",
    "artifact.write_markdown",
    "artifact.read_artifact",
    "artifact.list_artifacts",
}
missing = sorted(required.difference(tool_names))
if missing:
    raise SystemExit(f"missing tools: {missing}")
print("lit-assistant-mcp self-test ok")
print(f"repo_root={repo_root}")
print(f"backend_base_url={os.environ.get('LITERATURE_ASSISTANT_BASE_URL')}")
print(f"tool_count={len(tool_names)}")
'@
    $selfTestScript | & $pythonExe -
    exit $LASTEXITCODE
}

& $pythonExe -m lit_assistant_mcp.server
exit $LASTEXITCODE
