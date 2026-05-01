Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-PoolCommand {
    param(
        [string]$RepoRoot,
        [string[]]$CmdArgs
    )

    $poolPath = Join-Path $RepoRoot '.squad\state\pool.jsonl'

    if ($null -eq $CmdArgs -or $CmdArgs.Count -eq 0) {
        [Console]::Error.WriteLine("Usage: squad pool <add|list|promote|drop>")
        exit 1
    }

    $sub  = $CmdArgs[0]
    $rest = if ($CmdArgs.Count -gt 1) { [string[]]($CmdArgs[1..($CmdArgs.Count - 1)]) } else { [string[]]@() }

    switch ($sub) {
        'add'     { Invoke-PoolAdd     -Path $poolPath -FnArgs $rest }
        'list'    { Invoke-PoolList    -Path $poolPath -FnArgs $rest }
        'promote' { Invoke-PoolPromote -Path $poolPath -FnArgs $rest }
        'drop'    { Invoke-PoolDrop    -Path $poolPath -FnArgs $rest }
        default {
            [Console]::Error.WriteLine("Unknown pool sub-command: $sub")
            exit 1
        }
    }
}

# ---------- helpers ----------

function Parse-PoolFlags {
    param([string[]]$FnArgs)

    if ($null -eq $FnArgs) { return @{} }

    $flags = @{}
    $i = 0
    while ($i -lt $FnArgs.Count) {
        $a = $FnArgs[$i]
        if ($a -like '--*') {
            $key = $a.TrimStart('-')
            if (($i + 1) -lt $FnArgs.Count -and $FnArgs[$i + 1] -notlike '--*') {
                $flags[$key] = $FnArgs[$i + 1]
                $i += 2
            } else {
                $flags[$key] = $true
                $i++
            }
        } else {
            if (-not $flags.ContainsKey('_pos')) { $flags['_pos'] = @() }
            $flags['_pos'] += $a
            $i++
        }
    }

    return $flags
}

function Get-PoolTimestamp {
    return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

# ---------- add ----------

function Invoke-PoolAdd {
    param([string]$Path, [string[]]$FnArgs)

    if ($FnArgs.Count -eq 0) {
        [Console]::Error.WriteLine("Usage: squad pool add <title> --reason <why not now> [--score <0-50>] [--evidence <text>]")
        exit 1
    }

    $title = $FnArgs[0]
    $rest  = if ($FnArgs.Count -gt 1) { [string[]]($FnArgs[1..($FnArgs.Count - 1)]) } else { [string[]]@() }
    $flags = Parse-PoolFlags -FnArgs $rest

    $reason = $flags['reason']
    if (-not $reason) {
        [Console]::Error.WriteLine("--reason is required when adding to pool.")
        exit 1
    }

    $score = 0
    if ($flags['score']) {
        try { $score = [int]$flags['score'] } catch { $score = 0 }
    }

    $id = New-JsonlId -Path $Path -Prefix 'POOL'
    $entry = @{
        id             = $id
        title          = $title
        created_at     = Get-PoolTimestamp
        reason         = $reason
        score          = $score
        status         = 'waiting'
        evidence       = if ($flags['evidence']) { $flags['evidence'] } else { '' }
        schema_version = '1'
    }

    Add-JsonlEntry -Path $Path -Entry $entry
    Write-Host "Pool item $id added."
}

# ---------- list ----------

function Invoke-PoolList {
    param([string]$Path, [string[]]$FnArgs)

    $flags = Parse-PoolFlags -FnArgs $FnArgs
    $all = Read-JsonlFile -Path $Path

    # last-write-wins
    $latest = @{}
    foreach ($entry in $all) { $latest[$entry.id] = $entry }
    [object[]]$items = @($latest.Values)

    if ($flags['status']) { [object[]]$items = @($items | Where-Object { $_.status -eq $flags['status'] }) }

    if ($items.Count -eq 0) {
        Write-Host "No pool items found."
        return
    }

    foreach ($p in $items) {
        Write-Host "$($p.id)  [$($p.status.ToUpper())]  $($p.title)  (score=$($p.score))"
        Write-Host "    reason: $($p.reason)"
    }
}

# ---------- promote ----------

function Invoke-PoolPromote {
    param([string]$Path, [string[]]$FnArgs)

    if ($FnArgs.Count -eq 0) {
        [Console]::Error.WriteLine("Usage: squad pool promote <id>")
        exit 1
    }

    $id = $FnArgs[0]
    $all = Read-JsonlFile -Path $Path
    $existing = @($all | Where-Object { $_.id -eq $id }) | Select-Object -Last 1
    if ($null -eq $existing) {
        [Console]::Error.WriteLine("Pool item '$id' not found.")
        exit 1
    }

    Update-JsonlEntry -Path $Path -Id $id -Patch @{ status = 'promoted' }
    Write-Host "Pool item $id promoted. Move it to the active backlog."
}

# ---------- drop ----------

function Invoke-PoolDrop {
    param([string]$Path, [string[]]$FnArgs)

    if ($FnArgs.Count -eq 0) {
        [Console]::Error.WriteLine("Usage: squad pool drop <id> --reason <why>")
        exit 1
    }

    $id    = $FnArgs[0]
    $rest2 = if ($FnArgs.Count -gt 1) { [string[]]($FnArgs[1..($FnArgs.Count - 1)]) } else { [string[]]@() }
    $flags = Parse-PoolFlags -FnArgs $rest2

    $reason = $flags['reason']
    if (-not $reason) {
        [Console]::Error.WriteLine("--reason is required when dropping a pool item.")
        exit 1
    }

    $all = Read-JsonlFile -Path $Path
    $existing = @($all | Where-Object { $_.id -eq $id }) | Select-Object -Last 1
    if ($null -eq $existing) {
        [Console]::Error.WriteLine("Pool item '$id' not found.")
        exit 1
    }

    Update-JsonlEntry -Path $Path -Id $id -Patch @{
        status     = 'dropped'
        drop_reason = $reason
    }
    Write-Host "Pool item $id dropped."
}
