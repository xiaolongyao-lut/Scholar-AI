Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-JsonlFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return @()
    }

    $lines = Get-Content -LiteralPath $Path -Encoding utf8
    $items = @()
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }

        try {
            $items += ($line | ConvertFrom-Json)
        } catch {
            [Console]::Error.WriteLine("Malformed JSON line in ${Path}: $line")
            exit 3
        }
    }

    return $items
}

function Add-JsonlEntry {
    param(
        [string]$Path,
        [hashtable]$Entry
    )

    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    $json = $Entry | ConvertTo-Json -Compress -Depth 32
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $stream = [System.IO.StreamWriter]::new($Path, $true, $utf8NoBom)
    try {
        $stream.WriteLine($json)
    } finally {
        $stream.Close()
    }
}

function Select-JsonlEntries {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )

    $all = Read-JsonlFile -Path $Path
    return @($all | Where-Object { $_.PSObject.Properties[$Key] -and $_.$Key -eq $Value })
}

function Update-JsonlEntry {
    param(
        [string]$Path,
        [string]$Id,
        [hashtable]$Patch
    )

    # Append-only update: read current state, merge, write new row
    $all = Read-JsonlFile -Path $Path
    $current = $all | Where-Object { $_.id -eq $Id } | Select-Object -Last 1
    if ($null -eq $current) {
        throw "Entry '$Id' not found in $Path"
    }

    $merged = @{}
    foreach ($prop in $current.PSObject.Properties) {
        $merged[$prop.Name] = $prop.Value
    }
    foreach ($key in $Patch.Keys) {
        $merged[$key] = $Patch[$key]
    }

    Add-JsonlEntry -Path $Path -Entry $merged
}

function New-JsonlId {
    param(
        [string]$Path,
        [string]$Prefix
    )

    $max = 0
    if (Test-Path $Path) {
        $all = Read-JsonlFile -Path $Path
        foreach ($entry in $all) {
            if ($entry.id -match "^$Prefix-(\d+)$") {
                $n = [int]$Matches[1]
                if ($n -gt $max) { $max = $n }
            }
        }
    }

    return '{0}-{1:D3}' -f $Prefix, ($max + 1)
}
