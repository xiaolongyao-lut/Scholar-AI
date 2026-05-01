Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FileSha256Hex {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

function Copy-WithBackup {
    param(
        [string]$Source,
        [string]$Target,
        [string]$BackupDir
    )

    if (-not (Test-Path $Source)) {
        return [PSCustomObject]@{
            target = $Target
            action = 'skipped'
            reason = 'source-missing'
        }
    }

    $srcHash = Get-FileSha256Hex -Path $Source
    $dstHash = Get-FileSha256Hex -Path $Target

    if ($srcHash -and $dstHash -and $srcHash -eq $dstHash) {
        return [PSCustomObject]@{
            target = $Target
            action = 'unchanged'
            reason = 'same-hash'
        }
    }

    $targetDir = Split-Path -Parent $Target
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    if (Test-Path $Target) {
        if (-not (Test-Path $BackupDir)) {
            New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
        }
        $backupName = (Split-Path -Leaf $Target) + '.bak'
        Copy-Item -Path $Target -Destination (Join-Path $BackupDir $backupName) -Force
    }

    Copy-Item -Path $Source -Destination $Target -Force

    return [PSCustomObject]@{
        target = $Target
        action = 'updated'
        reason = if ($dstHash) { 'hash-diff' } else { 'new-file' }
    }
}

function Invoke-DecisionStatus {
    param([string]$RepoRoot)

    $claudeRoot = Join-Path $RepoRoot '.claude_squad'
    $copilotRoot = Join-Path $RepoRoot '.squad'

    $paths = @(
        'decisions.md',
        'decisions-archive.md',
        'casting-policy.json',
        'casting-registry.json',
        'charter.md',
        'routing.md'
    )

    Write-Host 'Decision compatibility status:'
    foreach ($p in $paths) {
        $src = Join-Path $claudeRoot $p
        $dst = Join-Path $copilotRoot $p
        $srcExists = Test-Path $src
        $dstExists = Test-Path $dst
        $state = if ($srcExists -and $dstExists) { 'ok' } elseif ($srcExists -and -not $dstExists) { 'missing-target' } else { 'missing-source' }
        Write-Host ("  {0,-24}  {1}" -f $p, $state)
    }

    if (Test-Path (Join-Path $copilotRoot 'decisions\README.md')) {
        Write-Host '  decisions/README.md         ok'
    } else {
        Write-Host '  decisions/README.md         missing-target'
    }

    if (Test-Path (Join-Path $copilotRoot 'state\README.md')) {
        Write-Host '  state/README.md             ok'
    } else {
        Write-Host '  state/README.md             missing-target'
    }
}

function Invoke-DecisionSyncClaude {
    param([string]$RepoRoot)

    $claudeRoot = Join-Path $RepoRoot '.claude_squad'
    $copilotRoot = Join-Path $RepoRoot '.squad'

    if (-not (Test-Path $claudeRoot)) {
        [Console]::Error.WriteLine("Source not found: $claudeRoot")
        return 1
    }
    if (-not (Test-Path $copilotRoot)) {
        [Console]::Error.WriteLine("Target not found: $copilotRoot")
        return 1
    }

    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
    $backupDir = Join-Path $copilotRoot ("backups\decision-sync-$stamp")

    # Safe sync surface: policy/registry/charter/routing + archive.
    # decisions.md is intentionally not overwritten because Copilot side carries local active decisions.
    $syncList = @(
        'casting-policy.json',
        'casting-registry.json',
        'charter.md',
        'routing.md',
        'decisions-archive.md'
    )

    $results = @()
    foreach ($rel in $syncList) {
        $src = Join-Path $claudeRoot $rel
        $dst = Join-Path $copilotRoot $rel
        $results += (Copy-WithBackup -Source $src -Target $dst -BackupDir $backupDir)
    }

    $inboxDir = Join-Path $copilotRoot 'decisions\inbox'
    if (-not (Test-Path $inboxDir)) {
        New-Item -ItemType Directory -Path $inboxDir -Force | Out-Null
    }
    $notePath = Join-Path $inboxDir ("claude-sync-$stamp.md")
    $note = @"
# Claude → Copilot Decision Sync Snapshot

- synced_at_utc: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
- source: `.claude_squad/`
- target: `.squad/`
- mode: safe-sync (policy/registry/charter/routing/archive)
- decisions.md: preserved (not overwritten)

## file_results
$($results | ForEach-Object { "- ``$($_.target)``: $($_.action) ($($_.reason))" } | Out-String)
"@
    Set-Content -Path $notePath -Value $note -Encoding UTF8

    Write-Host 'Claude sync completed (safe surface).'
    foreach ($r in $results) {
        Write-Host ("  {0,-8} {1}" -f $r.action, $r.target)
    }
    Write-Host ("  noted    {0}" -f $notePath)

    return 0
}

function Invoke-SquadDecision {
    param(
        [string]$RepoRoot,
        [string[]]$CmdArgs
    )

    if ($null -eq $CmdArgs -or $CmdArgs.Count -eq 0) {
        [Console]::Error.WriteLine("Usage: squad decision <status|sync-claude>")
        return 1
    }

    switch ($CmdArgs[0]) {
        'status' {
            Invoke-DecisionStatus -RepoRoot $RepoRoot
            return 0
        }
        'sync-claude' {
            return (Invoke-DecisionSyncClaude -RepoRoot $RepoRoot)
        }
        default {
            [Console]::Error.WriteLine("Unknown decision sub-command: $($CmdArgs[0])")
            [Console]::Error.WriteLine("Usage: squad decision <status|sync-claude>")
            return 1
        }
    }
}
