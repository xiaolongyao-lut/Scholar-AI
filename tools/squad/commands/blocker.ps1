Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-BlockerCommand {
    param(
        [string]$RepoRoot,
        [string[]]$CmdArgs
    )

    $blockersPath = Join-Path $RepoRoot '.squad\state\blockers.jsonl'

    if ($null -eq $CmdArgs -or $CmdArgs.Count -eq 0) {
        [Console]::Error.WriteLine("Usage: squad blocker <open|list|close|reclassify>")
        exit 1
    }

    $sub  = $CmdArgs[0]
    $rest = if ($CmdArgs.Count -gt 1) { [string[]]($CmdArgs[1..($CmdArgs.Count - 1)]) } else { [string[]]@() }

    switch ($sub) {
        'open'       { Invoke-BlockerOpen      -RepoRoot $RepoRoot -Path $blockersPath -FnArgs $rest }
        'list'       { Invoke-BlockerList      -Path $blockersPath -FnArgs $rest }
        'close'      { Invoke-BlockerClose     -Path $blockersPath -FnArgs $rest }
        'reclassify' { Invoke-BlockerReclassify -Path $blockersPath -FnArgs $rest }
        default {
            [Console]::Error.WriteLine("Unknown blocker sub-command: $sub")
            exit 1
        }
    }
}

# ---------- helpers ----------

function Parse-BlockerFlags {
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

function Get-BlockerTimestamp {
    return (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}

# ---------- open ----------

function Invoke-BlockerOpen {
    param([string]$RepoRoot, [string]$Path, [string[]]$FnArgs)

    if ($FnArgs.Count -eq 0) {
        [Console]::Error.WriteLine("Usage: squad blocker open <title> --type <constructible|economic|context|constraint>")
        exit 1
    }

    $title = $FnArgs[0]
    $rest  = if ($FnArgs.Count -gt 1) { [string[]]($FnArgs[1..($FnArgs.Count - 1)]) } else { [string[]]@() }
    $flags = Parse-BlockerFlags -FnArgs $rest

    $type = $flags['type']
    if (-not $type) {
        [Console]::Error.WriteLine("--type is required (constructible|economic|context|constraint)")
        exit 1
    }

    $validTypes = @('constructible', 'economic', 'context', 'constraint')
    if ($validTypes -notcontains $type) {
        [Console]::Error.WriteLine("Invalid type '$type'. Valid: constructible, economic, context, constraint")
        exit 1
    }

    $tier     = Get-AutonomyTier -RepoRoot $RepoRoot
    $decision = Get-RecommendedDecision -RepoRoot $RepoRoot -Tier $tier -BlockerType $type

    $id  = New-JsonlId -Path $Path -Prefix 'BLK'
    $now = Get-BlockerTimestamp

    $rollbackable = $true
    if ($flags.ContainsKey('rollbackable')) {
        $rollbackable = ($flags['rollbackable'] -eq 'true')
    }

    $entry = @{
        id             = $id
        title          = $title
        opened_at      = $now
        blocker_type   = $type
        risk           = if ($flags['risk'])     { $flags['risk'] }     else { 'medium' }
        roi            = if ($flags['roi'])      { $flags['roi'] }      else { 'medium' }
        rollbackable   = $rollbackable
        evidence       = if ($flags['evidence']) { $flags['evidence'] } else { '' }
        decision       = $decision
        status         = 'open'
        audit          = $null
        closed_at      = $null
        schema_version = '1'
    }

    Add-JsonlEntry -Path $Path -Entry $entry

    Write-Host "Blocker $id opened. Recommended decision: $decision"
    if ($decision -eq 'escalate') {
        Write-Host "[ESCALATE] This blocker requires immediate human review." -ForegroundColor Red
    }
}

# ---------- list ----------

function Invoke-BlockerList {
    param([string]$Path, [string[]]$FnArgs)

    $flags = Parse-BlockerFlags -FnArgs $FnArgs
    $all   = Read-JsonlFile -Path $Path

    $latest = @{}
    foreach ($entry in $all) { $latest[$entry.id] = $entry }
    [object[]]$items = @($latest.Values)

    if ($flags['type'])     { [object[]]$items = @($items | Where-Object { $_.blocker_type -eq $flags['type'] }) }
    if ($flags['decision']) { [object[]]$items = @($items | Where-Object { $_.decision     -eq $flags['decision'] }) }
    if ($flags['status'])   { [object[]]$items = @($items | Where-Object { $_.status       -eq $flags['status'] }) }

    if ($items.Count -eq 0) {
        Write-Host "No blockers found."
        return
    }

    foreach ($b in $items) {
        Write-Host "$($b.id)  [$($b.status.ToUpper())]  $($b.title)"
        Write-Host "    type=$($b.blocker_type)  decision=$($b.decision)  risk=$($b.risk)  roi=$($b.roi)"
    }
}

# ---------- close ----------

function Invoke-BlockerClose {
    param([string]$Path, [string[]]$FnArgs)

    if ($FnArgs.Count -eq 0) {
        [Console]::Error.WriteLine("Usage: squad blocker close <id> --audit <reason>")
        exit 1
    }

    $id    = $FnArgs[0]
    $rest2 = if ($FnArgs.Count -gt 1) { [string[]]($FnArgs[1..($FnArgs.Count - 1)]) } else { [string[]]@() }
    $flags = Parse-BlockerFlags -FnArgs $rest2

    $audit = $flags['audit']
    if (-not $audit) {
        [Console]::Error.WriteLine("--audit is required when closing a blocker.")
        exit 1
    }

    $all      = Read-JsonlFile -Path $Path
    $existing = @($all | Where-Object { $_.id -eq $id }) | Select-Object -Last 1
    if ($null -eq $existing) {
        [Console]::Error.WriteLine("Blocker '$id' not found.")
        exit 1
    }

    if ($existing.status -eq 'closed') {
        Write-Host "Blocker $id is already closed."
        return
    }

    Update-JsonlEntry -Path $Path -Id $id -Patch @{
        status    = 'closed'
        audit     = $audit
        closed_at = Get-BlockerTimestamp
    }

    Write-Host "Blocker $id closed."
}

# ---------- reclassify ----------

function Invoke-BlockerReclassify {
    param([string]$Path, [string[]]$FnArgs)

    if ($FnArgs.Count -eq 0) {
        [Console]::Error.WriteLine("Usage: squad blocker reclassify <id> --type <newtype> --reason <why>")
        exit 1
    }

    $id    = $FnArgs[0]
    $rest3 = if ($FnArgs.Count -gt 1) { [string[]]($FnArgs[1..($FnArgs.Count - 1)]) } else { [string[]]@() }
    $flags = Parse-BlockerFlags -FnArgs $rest3

    $newType = $flags['type']
    $reason  = $flags['reason']

    if (-not $newType) {
        [Console]::Error.WriteLine("--type is required for reclassify")
        exit 1
    }
    if (-not $reason) {
        [Console]::Error.WriteLine("--reason is required for reclassify")
        exit 1
    }

    $validTypes = @('constructible', 'economic', 'context', 'constraint')
    if ($validTypes -notcontains $newType) {
        [Console]::Error.WriteLine("Invalid type '$newType'. Valid: constructible, economic, context, constraint")
        exit 1
    }

    $all      = Read-JsonlFile -Path $Path
    $existing = @($all | Where-Object { $_.id -eq $id }) | Select-Object -Last 1
    if ($null -eq $existing) {
        [Console]::Error.WriteLine("Blocker '$id' not found.")
        exit 1
    }

    Update-JsonlEntry -Path $Path -Id $id -Patch @{
        blocker_type      = $newType
        reclassify_reason = $reason
        reclassified_at   = Get-BlockerTimestamp
    }

    Write-Host "Blocker $id reclassified to $newType."
}
