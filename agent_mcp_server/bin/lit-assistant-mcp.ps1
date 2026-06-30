param(
    [switch]$SelfTest,
    [switch]$PrintConfig,
    [switch]$ForceLaunch
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

    if (-not [string]::IsNullOrWhiteSpace($env:LITERATURE_ASSISTANT_REPO_ROOT)) {
        $envRoot = (Resolve-Path -LiteralPath $env:LITERATURE_ASSISTANT_REPO_ROOT).Path
        if (Test-RepositoryRoot -Candidate $envRoot) {
            return $envRoot
        }
        throw "LITERATURE_ASSISTANT_REPO_ROOT does not contain Scholar AI repository anchors: $envRoot"
    }

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

function Test-LoopbackHttpUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    try {
        $uri = [System.Uri]::new($Url)
    } catch {
        return $false
    }

    return ($uri.Scheme -in @("http", "https")) -and ($uri.Host -in @("localhost", "127.0.0.1", "::1"))
}

function Hide-OwnConsoleWindow {
    if (-not [string]::IsNullOrWhiteSpace($env:LITASSIST_MCP_KEEP_CONSOLE)) {
        return
    }

    try {
        Add-Type -Namespace LitAssistantMcp -Name NativeConsoleWindow -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern System.IntPtr GetConsoleWindow();

[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool ShowWindow(System.IntPtr hWnd, int nCmdShow);
"@
        $consoleWindow = [LitAssistantMcp.NativeConsoleWindow]::GetConsoleWindow()
        if ($consoleWindow -ne [System.IntPtr]::Zero) {
            [void][LitAssistantMcp.NativeConsoleWindow]::ShowWindow($consoleWindow, 0)
        }
    } catch {
        return
    }
}

function Resolve-IsolatedCapabilityFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot
    )

    try {
        $uri = [System.Uri]::new($Url)
    } catch {
        return ""
    }

    if (($uri.Scheme -eq "http") -and ($uri.Host -in @("localhost", "127.0.0.1", "::1")) -and ($uri.Port -eq 8000)) {
        return ""
    }

    if (-not (($uri.Scheme -in @("http", "https")) -and ($uri.Host -in @("localhost", "127.0.0.1", "::1")))) {
        return ""
    }

    $safeHost = $uri.Host.Replace(":", "_").Trim("_")
    if ([string]::IsNullOrWhiteSpace($safeHost)) {
        $safeHost = "loopback"
    }
    $capabilityRoot = Join-Path $RepositoryRoot "workspace_artifacts\runtime_state\api-capabilities"
    return (Join-Path $capabilityRoot "$safeHost-$($uri.Port).json")
}

if (-not $SelfTest -and -not $PrintConfig) {
    Hide-OwnConsoleWindow
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-RepositoryRoot -ScriptPath $scriptDirectory
$pythonExe = Join-Path $repoRoot ".venv-1\Scripts\python.exe"
$mcpSourceRoot = Join-Path $repoRoot "agent_mcp_server\src"
$baseUrlWasExplicit = -not [string]::IsNullOrWhiteSpace($env:LITERATURE_ASSISTANT_BASE_URL)
$allowDesktopAutostart = -not [string]::IsNullOrWhiteSpace($env:LITASSIST_MCP_ALLOW_DESKTOP_AUTOSTART)

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Missing Python interpreter: $pythonExe"
}

if (-not (Test-Path -LiteralPath $mcpSourceRoot -PathType Container)) {
    throw "Missing MCP source root: $mcpSourceRoot"
}

$env:LITERATURE_ASSISTANT_REPO_ROOT = $repoRoot
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
        desktop_runtime_file = (Join-Path $repoRoot "workspace_artifacts\runtime_state\desktop-runtime.json")
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
    "literature.search_refs",
    "literature.evidence_pack_build",
    "literature.project_scan_folder",
    "literature.figures_candidates",
    "literature.figures_generate",
    "literature.citations_sources",
    "literature.citations_detect_overlap",
    "literature.academic_writing_lint",
    "literature.outline_generate",
    "literature.export_annotations_markdown",
    "literature.export_docx",
    "literature.journal_style_spec_draft",
    "literature.journal_style_spec_confirm",
    "literature.agent_bridge_status",
    "literature.agent_request_create",
    "literature.agent_request_list",
    "literature.agent_request_read",
    "literature.agent_resource_read",
    "literature.agent_progress",
    "literature.agent_result",
    "literature.agent_fail",
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
print(f"backend_base_url={os.environ.get('LITERATURE_ASSISTANT_BASE_URL') or 'desktop-runtime-or-default'}")
print(f"desktop_runtime_file={os.environ.get('LITASSIST_DESKTOP_RUNTIME_FILE') or ''}")
print(f"tool_count={len(tool_names)}")
'@
    $selfTestScript | & $pythonExe -
    exit $LASTEXITCODE
}

if ([string]::IsNullOrWhiteSpace($env:LITASSIST_MCP_SKIP_BACKEND_AUTOSTART)) {
    $startupTimeoutSec = if ([string]::IsNullOrWhiteSpace($env:LITASSIST_MCP_BACKEND_STARTUP_TIMEOUT_SEC)) {
        "60"
    } else {
        $env:LITASSIST_MCP_BACKEND_STARTUP_TIMEOUT_SEC
    }

    if (
        -not [string]::IsNullOrWhiteSpace($env:LITASSIST_MCP_ALLOW_HEADLESS_AUTOSTART) -and
        (Test-LoopbackHttpUrl -Url $env:LITERATURE_ASSISTANT_BASE_URL)
    ) {
        $isolatedCapabilityFile = Resolve-IsolatedCapabilityFile -Url $env:LITERATURE_ASSISTANT_BASE_URL -RepositoryRoot $repoRoot
        if (
            -not [string]::IsNullOrWhiteSpace($isolatedCapabilityFile) -and
            [string]::IsNullOrWhiteSpace($env:LITASSIST_API_CAPABILITY_FILE)
        ) {
            $env:LITASSIST_API_CAPABILITY_FILE = $isolatedCapabilityFile
        }
        & $pythonExe -m lit_assistant_mcp.backend_launcher `
            --repo-root $repoRoot `
            --base-url $env:LITERATURE_ASSISTANT_BASE_URL `
            --startup-timeout-sec $startupTimeoutSec *> $null
    } elseif (-not $baseUrlWasExplicit -or (Test-LoopbackHttpUrl -Url $env:LITERATURE_ASSISTANT_BASE_URL)) {
        $attachArgs = @(
            "-m",
            "lit_assistant_mcp.runtime_attach",
            "--repo-root",
            $repoRoot,
            "--startup-timeout-sec",
            $startupTimeoutSec,
            "--print-env"
        )
        if ($ForceLaunch) {
            $attachArgs += "--force-launch"
        }
        if (-not $ForceLaunch -and -not $allowDesktopAutostart) {
            $attachArgs += "--no-launch"
        }
        $attachJson = & $pythonExe @attachArgs 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($attachJson)) {
            $attach = $attachJson | ConvertFrom-Json
            if (-not [string]::IsNullOrWhiteSpace($attach.LITERATURE_ASSISTANT_BASE_URL)) {
                $env:LITERATURE_ASSISTANT_BASE_URL = [string]$attach.LITERATURE_ASSISTANT_BASE_URL
            }
            if (
                -not [string]::IsNullOrWhiteSpace($attach.LITASSIST_API_CAPABILITY_FILE) -and
                [string]::IsNullOrWhiteSpace($env:LITASSIST_API_CAPABILITY_FILE)
            ) {
                $env:LITASSIST_API_CAPABILITY_FILE = [string]$attach.LITASSIST_API_CAPABILITY_FILE
            }
            if (-not [string]::IsNullOrWhiteSpace($attach.LITASSIST_DESKTOP_RUNTIME_FILE)) {
                $env:LITASSIST_DESKTOP_RUNTIME_FILE = [string]$attach.LITASSIST_DESKTOP_RUNTIME_FILE
            }
        }
    }
}

& $pythonExe -m lit_assistant_mcp.server
exit $LASTEXITCODE
