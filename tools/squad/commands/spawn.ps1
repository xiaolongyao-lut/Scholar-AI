# commands/spawn.ps1 — `squad spawn <role> [reason]` subcommand handler.
#
# Promotes the old "write a JSON into .squad/spawn-queue/" ritual to a first-class
# squad subcommand. Under the hood it still calls spawn-agent.ps1 so all the
# existing guardrails (10-cap, role charter check, marker files) keep working.
#
# Usage (invoked via squad.ps1):
#   squad spawn tank "need parallel test runner"
#   squad spawn oracle --id oracle-2 "second opinion"
#   squad spawn morpheus --no-auto-slash
#   squad spawn --list-roles
#   squad spawn --live

function Invoke-SquadSpawn {
    param(
        [Parameter(Mandatory)] [string]$RepoRoot,
        [string[]]$CmdArgs = @()
    )

    $squadDir    = Join-Path $RepoRoot 'tools\squad'
    $spawnAgent  = Join-Path $squadDir 'spawn-agent.ps1'
    $rolesDir    = Join-Path $RepoRoot '.squad\roles'
    $markerDir   = Join-Path $RepoRoot '.squad\autopilot-logs\live-agents'

    # --- Parse flags ---
    $role            = $null
    $id              = $null
    $reason          = ''
    $autoStartClaude = $true
    $autoSlash       = $true
    $listRoles       = $false
    $showLive        = $false
    $requestedBy     = 'cli'

    $i = 0
    while ($i -lt $CmdArgs.Count) {
        $a = $CmdArgs[$i]
        switch -Regex ($a) {
            '^--list-roles$'    { $listRoles = $true }
            '^--live$'          { $showLive = $true }
            '^--id$'            { $i++; $id = $CmdArgs[$i] }
            '^--no-claude$'     { $autoStartClaude = $false }
            '^--no-auto-slash$' { $autoSlash = $false }
            '^--by$'            { $i++; $requestedBy = $CmdArgs[$i] }
            '^--reason$'        { $i++; $reason = $CmdArgs[$i] }
            '^-h$|^--help$' {
                Write-Host @'
squad spawn — open a new agent window.

Usage:
  squad spawn <role> [reason...]
  squad spawn <role> --id <custom-id> [reason...]
  squad spawn --list-roles
  squad spawn --live

Flags:
  --id <id>          Override the default agent id (default = role name).
  --reason <text>    Why you are spawning (also accepts trailing positional).
  --by <name>        Who requested the spawn (default: cli). For audit trail.
  --no-claude        Open window but do not auto-start claude.
  --no-auto-slash    Do not pre-stage /squad <id> on clipboard.
  --list-roles       Show available charters under .squad/roles/.
  --live             Show currently live agents (from marker files).

Guardrails (enforced by spawn-agent.ps1):
  - Max 10 live agents.
  - Role must exist as .squad/roles/<role>.md.
  - Path lock + command denylist via squad-guard.ps1.
'@
                return 0
            }
            default {
                if (-not $role) { $role = $a }
                else {
                    if ($reason) { $reason += ' ' }
                    $reason += $a
                }
            }
        }
        $i++
    }

    # --- Info modes ---
    if ($listRoles) {
        if (-not (Test-Path $rolesDir)) {
            Write-Host "(no .squad/roles directory)" -ForegroundColor Yellow
            return 0
        }
        Write-Host "Available roles:" -ForegroundColor Cyan
        Get-ChildItem $rolesDir -Filter '*.md' -File | ForEach-Object {
            Write-Host ("  " + [IO.Path]::GetFileNameWithoutExtension($_.Name))
        }
        return 0
    }

    if ($showLive) {
        if (-not (Test-Path $markerDir)) {
            Write-Host "No live agents." -ForegroundColor Yellow
            return 0
        }
        $markers = @(Get-ChildItem $markerDir -Filter '*.json' -File -ErrorAction SilentlyContinue)
        if ($markers.Count -eq 0) {
            Write-Host "No live agents." -ForegroundColor Yellow
            return 0
        }
        Write-Host ("Live agents: {0} / 10" -f $markers.Count) -ForegroundColor Cyan
        foreach ($m in $markers) {
            try {
                $mk = Get-Content $m.FullName -Raw | ConvertFrom-Json
                $alive = $null -ne (Get-Process -Id $mk.pid -ErrorAction SilentlyContinue)
                $tag   = if ($alive) { '[LIVE]' } else { '[DEAD]' }
                $color = if ($alive) { 'Green' }  else { 'DarkRed' }
                Write-Host ("  {0} {1,-15} pid={2,-6} role={3} spawned={4}" -f `
                    $tag, $mk.id, $mk.pid, $mk.role, $mk.spawned_at) -ForegroundColor $color
            } catch {
                Write-Host ("  [BAD]  " + $m.Name) -ForegroundColor Yellow
            }
        }
        return 0
    }

    # --- Spawn mode ---
    if (-not $role) {
        [Console]::Error.WriteLine("squad spawn: missing <role>. Run 'squad spawn --help' for usage.")
        return 1
    }

    # Refresh .squad/roles/<role>.md from .claude_squad/agents/<role>/charter.md
    # before spawn-agent.ps1 reads it. Quiet mode so we don't spam the spawn log.
    # If the sync script is missing or fails, carry on — spawn-agent will detect
    # a missing role the usual way.
    $syncScript = Join-Path $squadDir 'sync-roles.ps1'
    if (Test-Path $syncScript) {
        try { & $syncScript -Role $role -Quiet 2>$null | Out-Null } catch {}
    }

    if (-not (Test-Path $spawnAgent)) {
        [Console]::Error.WriteLine("spawn-agent.ps1 not found at $spawnAgent")
        return 4
    }

    # Audit trail: record intent before we actually spawn.
    $auditDir = Join-Path $RepoRoot '.claude_squad\decisions\inbox'
    if (-not (Test-Path $auditDir)) { New-Item -ItemType Directory -Force -Path $auditDir | Out-Null }
    $slug = ($role -replace '[^a-zA-Z0-9]+', '-').ToLower()
    $auditFile = Join-Path $auditDir ("spawn-$slug-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.md')
    # Atomic write per CLAUDE.md §4.7: write to .tmp then Move-Item -Force.
    # Crash mid-write would leave a partial markdown audit file in
    # .claude_squad/decisions/inbox/, which downstream readers (Squad audits,
    # daily decisions sweeps) parse as YAML frontmatter — partial content can
    # silently fail-open. Audit anchor: .squad/audits/atomic-write-audit-2026-04-25.md
    # (P1 violator #6, the last open one). Variable named $auditFileTmp to satisfy
    # tools/squad/check-atomic-write.ps1's compliant regex.
    $auditFileTmp = "$auditFile.tmp"
    @"
# Spawn order — $role ($(if ($id) { $id } else { $role }))

- Requested by: $requestedBy
- At: $((Get-Date).ToString('o'))
- Reason: $reason

via `squad spawn` subcommand.
"@ | Set-Content -Path $auditFileTmp -Encoding UTF8
    Move-Item -LiteralPath $auditFileTmp -Destination $auditFile -Force

    $spawnArgs = @{ Role = $role }
    if ($id)                  { $spawnArgs.Id              = $id }
    $spawnArgs.AutoStartClaude = $autoStartClaude
    $spawnArgs.AutoSlash       = $autoSlash

    try {
        & $spawnAgent @spawnArgs
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
        return $code
    } catch {
        [Console]::Error.WriteLine("spawn failed: $_")
        return 5
    }
}
