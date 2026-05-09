Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-AgentBridgeMap {
    param([Parameter(Mandatory)] [string]$RepoRoot)

    $builtIn = [ordered]@{
        'Squad' = [ordered]@{ role = 'morpheus'; notes = 'Coordinator-oriented requests route to morpheus as architect lead in CLI lane' }
        'Expert React Frontend Engineer' = [ordered]@{ role = 'dozer'; notes = 'Frontend implementation' }
        'Frontend Orchestrator' = [ordered]@{ role = 'trinity'; notes = 'Cross-component implementation orchestration' }
        'Frontend Performance Investigator' = [ordered]@{ role = 'tank'; notes = 'Performance/QA lane' }
        'gem-designer' = [ordered]@{ role = 'switch'; notes = 'Frontend design lane' }
    }

    $fileMap = @{}
    $mapPath = Join-Path $RepoRoot 'tools\squad\agent-bridge.map.json'
    if (Test-Path $mapPath) {
        try {
            $raw = Get-Content -LiteralPath $mapPath -Raw -Encoding utf8 | ConvertFrom-Json
            if ($raw.agents) {
                foreach ($p in $raw.agents.PSObject.Properties) {
                    if ($p.Name) {
                        $fileMap[$p.Name] = [ordered]@{
                            role  = "$($p.Value.role)"
                            notes = "$($p.Value.notes)"
                        }
                    }
                }
            }
        } catch {
            [Console]::Error.WriteLine("[agent-bridge] warning: failed to read $mapPath, using built-in defaults.")
        }
    }

    $custom = @{}
    $customPath = Join-Path $RepoRoot '.squad\wiring\agent-cli-bridge.json'
    if (Test-Path $customPath) {
        try {
            $raw2 = Get-Content -LiteralPath $customPath -Raw -Encoding utf8 | ConvertFrom-Json
            if ($raw2.agents) {
                foreach ($p in $raw2.agents.PSObject.Properties) {
                    if ($p.Name) {
                        $custom[$p.Name] = [ordered]@{
                            role  = "$($p.Value.role)"
                            notes = "$($p.Value.notes)"
                        }
                    }
                }
            }
        } catch {
            [Console]::Error.WriteLine("[agent-bridge] warning: failed to read $customPath, ignoring override.")
        }
    }

    $merged = @{}
    foreach ($k in $builtIn.Keys) { $merged[$k] = $builtIn[$k] }
    foreach ($k in $fileMap.Keys) { $merged[$k] = $fileMap[$k] }
    foreach ($k in $custom.Keys) { $merged[$k] = $custom[$k] }

    return [PSCustomObject]@{
        map = $merged
        source_builtin = $true
        source_file = (Test-Path $mapPath)
        source_custom = (Test-Path $customPath)
    }
}

function Resolve-AgentNameToRole {
    param(
        [hashtable]$Map,
        [string]$AgentName
    )

    if ([string]::IsNullOrWhiteSpace($AgentName)) { return $null }

    foreach ($k in $Map.Keys) {
        if ($k -ieq $AgentName) {
            return [PSCustomObject]@{ name = $k; role = "$($Map[$k].role)"; notes = "$($Map[$k].notes)" }
        }
    }

    return $null
}

function Find-LiveAgentIdByRole {
    param(
        [Parameter(Mandatory)] [string]$RepoRoot,
        [Parameter(Mandatory)] [string]$Role
    )

    $markerDir = Join-Path $RepoRoot '.squad\autopilot-logs\live-agents'
    if (-not (Test-Path $markerDir)) { return $null }

    $markers = Get-ChildItem $markerDir -Filter '*.json' -File -ErrorAction SilentlyContinue
    if (-not $markers) { return $null }

    foreach ($m in ($markers | Sort-Object LastWriteTimeUtc -Descending)) {
        try {
            $mk = Get-Content -LiteralPath $m.FullName -Raw -Encoding utf8 | ConvertFrom-Json
            if ("$($mk.role)" -ieq $Role) {
                return "$($mk.id)"
            }
        } catch {}
    }

    return $null
}

function Invoke-SquadAgentBridge {
    param(
        [Parameter(Mandatory)] [string]$RepoRoot,
        [string[]]$CmdArgs = @()
    )

    if ($null -eq $CmdArgs) { $CmdArgs = @() }

    $bridge = Get-AgentBridgeMap -RepoRoot $RepoRoot
    $map = $bridge.map

    if ($CmdArgs.Count -eq 0 -or $CmdArgs[0] -in @('-h', '--help', 'help')) {
        Write-Host @'
squad agent — bridge VS Code Agent names to CLI squad roles.

Usage:
  squad agent list
  squad agent run <agent-name> [message...]
  squad agent <agent-name> [message...]

Flags:
  --role <role>      Override mapped role.
  --id <agent-id>    Override target agent id for task dispatch.
  --task <text>      Task body (alternative to trailing message).
  --by <name>        Task creator identity (default: dispatcher file or owner).
  --no-spawn         Do not spawn role; dispatch only.

Examples:
  squad agent list
  squad agent run "Expert React Frontend Engineer" "优化设置页渲染性能"
  squad agent "Frontend Performance Investigator" --no-spawn --role tank --task "做一次前端性能瓶颈排查"
'@
        return 0
    }

    if ($CmdArgs[0] -eq 'list') {
        Write-Host 'Agent bridge map (Agent -> CLI role):' -ForegroundColor Cyan
        foreach ($name in ($map.Keys | Sort-Object)) {
            $role = "$($map[$name].role)"
            $notes = "$($map[$name].notes)"
            Write-Host ("  {0} -> {1}  ({2})" -f $name, $role, $notes)
        }

        if ($bridge.source_custom) {
            Write-Host 'override: loaded .squad/wiring/agent-cli-bridge.json' -ForegroundColor DarkGray
        } elseif ($bridge.source_file) {
            Write-Host 'override: loaded tools/squad/agent-bridge.map.json' -ForegroundColor DarkGray
        } else {
            Write-Host 'override: using built-in defaults (no map file found)' -ForegroundColor DarkGray
        }
        return 0
    }

    $cursor = 0
    $sub = $CmdArgs[0]
    if ($sub -eq 'run') {
        $cursor = 1
    }

    if ($cursor -ge $CmdArgs.Count) {
        [Console]::Error.WriteLine('squad agent: missing <agent-name>. Run `squad agent --help`.')
        return 1
    }

    $agentName = $CmdArgs[$cursor]
    $cursor++

    $roleOverride = $null
    $idOverride = $null
    $taskOverride = $null
    $requestedBy = $null
    $noSpawn = $false
    $msgParts = New-Object System.Collections.Generic.List[string]

    while ($cursor -lt $CmdArgs.Count) {
        $a = $CmdArgs[$cursor]
        switch ($a) {
            '--role' {
                $cursor++
                if ($cursor -ge $CmdArgs.Count) { [Console]::Error.WriteLine('squad agent: --role requires a value.'); return 1 }
                $roleOverride = $CmdArgs[$cursor]
            }
            '--id' {
                $cursor++
                if ($cursor -ge $CmdArgs.Count) { [Console]::Error.WriteLine('squad agent: --id requires a value.'); return 1 }
                $idOverride = $CmdArgs[$cursor]
            }
            '--task' {
                $cursor++
                if ($cursor -ge $CmdArgs.Count) { [Console]::Error.WriteLine('squad agent: --task requires a value.'); return 1 }
                $taskOverride = $CmdArgs[$cursor]
            }
            '--by' {
                $cursor++
                if ($cursor -ge $CmdArgs.Count) { [Console]::Error.WriteLine('squad agent: --by requires a value.'); return 1 }
                $requestedBy = $CmdArgs[$cursor]
            }
            '--no-spawn' {
                $noSpawn = $true
            }
            default {
                $msgParts.Add($a)
            }
        }
        $cursor++
    }

    $resolved = Resolve-AgentNameToRole -Map $map -AgentName $agentName
    $role = if ($roleOverride) { $roleOverride } elseif ($resolved) { $resolved.role } else { $null }

    if ([string]::IsNullOrWhiteSpace($role)) {
        [Console]::Error.WriteLine("squad agent: no role mapping found for '$agentName'. Use --role <role> or add mapping in tools/squad/agent-bridge.map.json.")
        return 1
    }

    if (-not $noSpawn) {
        . (Join-Path $RepoRoot 'tools\squad\commands\spawn.ps1')
        $spawnArgs = @($role)
        if ($idOverride) {
            $spawnArgs += @('--id', $idOverride)
        }
        if ($requestedBy) {
            $spawnArgs += @('--by', $requestedBy)
        } else {
            $spawnArgs += @('--by', 'agent-bridge')
        }
        $spawnRc = Invoke-SquadSpawn -RepoRoot $RepoRoot -CmdArgs $spawnArgs
        if ($spawnRc -is [array]) { $spawnRc = $spawnRc[-1] }
        if ($null -eq $spawnRc) { $spawnRc = 0 }
        if ([int]$spawnRc -ne 0) {
            [Console]::Error.WriteLine("squad agent: spawn failed for role '$role' (exit=$spawnRc).")
            return [int]$spawnRc
        }
    }

    $taskBody = if ($taskOverride) { $taskOverride } else { ($msgParts.ToArray() -join ' ').Trim() }
    if ([string]::IsNullOrWhiteSpace($taskBody)) {
        Write-Host ("Agent bridge ready: {0} -> role {1}" -f $agentName, $role) -ForegroundColor Green
        Write-Host 'No task body provided, spawn-only mode completed.' -ForegroundColor DarkGray
        return 0
    }

    $targetId = if ($idOverride) { $idOverride } else { (Find-LiveAgentIdByRole -RepoRoot $RepoRoot -Role $role) }
    if ([string]::IsNullOrWhiteSpace($targetId)) { $targetId = $role }

    $from = $requestedBy
    if ([string]::IsNullOrWhiteSpace($from)) {
        $dispFile = Join-Path $RepoRoot '.squad\state\dispatcher.txt'
        if (Test-Path $dispFile) {
            $from = (Get-Content -LiteralPath $dispFile -Raw -Encoding utf8).Trim()
        }
    }
    if ([string]::IsNullOrWhiteSpace($from)) { $from = 'owner' }

    if (-not (Get-Command Resolve-RealSquadCli -ErrorAction SilentlyContinue)) {
        [Console]::Error.WriteLine('squad agent: Resolve-RealSquadCli not found in wrapper scope.')
        return 4
    }

    $realCli = Resolve-RealSquadCli
    if (-not $realCli) {
        [Console]::Error.WriteLine('squad agent: official squad CLI not found.')
        return 4
    }

    $title = if ($taskBody.Length -gt 60) { $taskBody.Substring(0, 60) + '...' } else { $taskBody }

    & $realCli task create $from $targetId --title $title --body $taskBody
    return $LASTEXITCODE
}
