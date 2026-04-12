[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [string]$DescriptorRef = "",
    [string]$SkillFlowVersion = "1.3.3"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-CommandPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $command = Get-Command -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Required command '$Name' is not available in PATH."
    }
    return $command.Source
}

function Resolve-PythonExecutable {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false)]
        [string]$RequestedPath
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $resolved = (Resolve-Path -LiteralPath $RequestedPath -ErrorAction Stop).Path
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "Python executable does not exist: $resolved"
        }
        return $resolved
    }

    try {
        return Resolve-CommandPath -Name "python"
    } catch {
        $knownPath = "C:\Users\xiao\AppData\Local\Programs\Python\Python314\python.exe"
        if (Test-Path -LiteralPath $knownPath -PathType Leaf) {
            return $knownPath
        }
        throw "Could not find python. Please specify via -PythonExe."
    }
}

function Resolve-SkillFlowInvoker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot,

        [Parameter(Mandatory = $true)]
        [string]$FallbackVersion
    )

    $localSkillFlowRoot = Join-Path $RepositoryRoot "github\skill-flow-1.3.3"
    $localCliEntry = Join-Path $localSkillFlowRoot "apps\cli\dist\cli.js"
    if (Test-Path -LiteralPath (Join-Path $localSkillFlowRoot "package.json") -PathType Leaf) {
        $nodePath = Resolve-CommandPath -Name "node"
        $npmPath = Resolve-CommandPath -Name "npm"

        if (-not (Test-Path -LiteralPath $localCliEntry -PathType Leaf)) {
            Write-Host ">>> Building local skill-flow CLI from github\\skill-flow-1.3.3 ..." -ForegroundColor DarkCyan
            Push-Location -LiteralPath $localSkillFlowRoot
            try {
                & $npmPath "install" "--no-fund" "--no-audit" | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    throw "npm install failed while preparing the local skill-flow CLI."
                }

                & $npmPath "run" "build" | Out-Host
                if ($LASTEXITCODE -ne 0) {
                    throw "npm run build failed while preparing the local skill-flow CLI."
                }
            } finally {
                Pop-Location
            }
        }

        if (-not (Test-Path -LiteralPath $localCliEntry -PathType Leaf)) {
            throw "Local skill-flow CLI entry was not produced at $localCliEntry"
        }

        return @{
            type = "local"
            nodePath = $nodePath
            cliPath = $localCliEntry
            root = $localSkillFlowRoot
        }
    }

    return @{
        type = "npx"
        npxPath = (Resolve-CommandPath -Name "npx")
        version = $FallbackVersion
    }
}

function Invoke-SkillFlowCli {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Invoker,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    if ($Invoker.type -eq "local") {
        Push-Location -LiteralPath $Invoker.root
        try {
            return & $Invoker.nodePath $Invoker.cliPath @Arguments
        } finally {
            Pop-Location
        }
    }

    return & $Invoker.npxPath "--yes" "skill-flow@$($Invoker.version)" @Arguments
}

function Invoke-SkillFlowBridge {
    # (Existing function truncated for brevity in thought, but I will provide full source as seen earlier)
    # ... fully restored below ...
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Invoker,

        [Parameter(Mandatory = $true)]
        [hashtable]$Request
    )

    $requestJson = $Request | ConvertTo-Json -Depth 32 -Compress
    
    # Use stdin instead of --request argument to avoid PowerShell escaping issues
    if ($Invoker.type -eq "local") {
        Push-Location -LiteralPath $Invoker.root
        try {
            $responseText = $requestJson | & $Invoker.nodePath $Invoker.cliPath bridge --json
        } finally {
            Pop-Location
        }
    } else {
        $responseText = $requestJson | & $Invoker.npxPath "--yes" "skill-flow@$($Invoker.version)" bridge --json
    }
    if ($LASTEXITCODE -ne 0 -and [string]::IsNullOrWhiteSpace($responseText)) {
        throw "skill-flow bridge invocation failed before returning JSON."
    }

    $responsePayload = [string]::Join("`n", @($responseText))

    try {
        $response = $responsePayload | ConvertFrom-Json -Depth 64
    } catch {
        throw "skill-flow bridge returned non-JSON output: $responsePayload"
    }

    if (-not $response.ok) {
        throw "skill-flow bridge request failed."
    }

    return $response
}

function Save-JsonSnapshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $Value | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $Path -Encoding utf8
}

function Get-SourceSummaryByLocator {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$ListResponse,

        [Parameter(Mandatory = $true)]
        [string]$Locator
    )

    if ($null -eq $ListResponse.data -or $null -eq $ListResponse.data.summaries) {
        return $null
    }

    foreach ($summary in $ListResponse.data.summaries) {
        if ([string]::Equals([string]$summary.source.locator, $Locator, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $summary
        }
    }

    return $null
}

function New-CustomTargetDefinition {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryRoot,

        [Parameter(Mandatory = $false)]
        [object]$ExistingTarget
    )

    $timestamp = [datetime]::UtcNow.ToString("o")
    $targetRoot = Join-Path $RepositoryRoot "skills\imported\skill-flow"
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null

    return [ordered]@{
        id = "modular-pipeline-script"
        name = "Modular Pipeline Skills"
        globalPath = $targetRoot
        projectPathTemplate = "skills/imported/skill-flow"
        strategy = "copy"
        createdAt = if ($null -ne $ExistingTarget) { [string]$ExistingTarget.createdAt } else { $timestamp }
        updatedAt = $timestamp
    }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath $repoRoot).Path
$skillsRoot = Join-Path $repoRoot "skills"
$catalogRoot = Join-Path $skillsRoot "catalog"
$summaryJsonPath = Join-Path $catalogRoot ".skill-flow-export.json"
$pythonPath = Resolve-PythonExecutable -RequestedPath $PythonExe
$skillFlowInvoker = Resolve-SkillFlowInvoker -RepositoryRoot $repoRoot -FallbackVersion $SkillFlowVersion

Write-Host ">>> [1/2] Syncing Skill-Flow bridge..." -ForegroundColor Cyan
& $pythonPath (Join-Path $skillsRoot "skill_flow_adapter.py")

Invoke-SkillFlowBridge -Invoker $skillFlowInvoker -Request @{
    protocolVersion = "1.0"
    command = "list"
}

Write-Host "`nSkill-Flow synchronization complete." -ForegroundColor Green
