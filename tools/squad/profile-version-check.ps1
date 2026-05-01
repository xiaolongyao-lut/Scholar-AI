# tools/squad/profile-version-check.ps1
# Purpose: Validate the canonical owner profile (DD4) at Squad startup.
# Created: 2026-04-27 as part of Squad 0.9.3-modular hardening.
#
# PowerShell 5 note:
#   Avoid hard-coding non-ASCII profile paths in source literals because a
#   UTF-8-no-BOM script can be misread under Windows PowerShell and corrupt the
#   path. Resolve the canonical profile dynamically from the tools directory.
[CmdletBinding()]
param(
    [string]$ProfilePath = '',
    [string]$ExpectedVersion = 'v4',
    [string]$ProfileRoot = 'C:\Users\xiao\Desktop\tools'
)

$ErrorActionPreference = 'Stop'

function Resolve-ProfilePath {
    param(
        [string]$RequestedPath,
        [string]$Root
    )

    if ($RequestedPath -and (Test-Path -LiteralPath $RequestedPath)) {
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    if (-not (Test-Path -LiteralPath $Root)) {
        return $null
    }

    $candidates = @(Get-ChildItem -LiteralPath $Root -File -Filter '*_v4_AI*.md' -ErrorAction SilentlyContinue)
    if ($candidates.Count -eq 0) {
        return $null
    }

    return ($candidates | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).FullName
}

$resolvedProfilePath = Resolve-ProfilePath -RequestedPath $ProfilePath -Root $ProfileRoot

if (-not $resolvedProfilePath) {
    [Console]::Error.WriteLine("FAIL: canonical v4 profile not found under $ProfileRoot (filter: *_v4_AI*.md)")
    exit 49
}

$head = Get-Content -LiteralPath $resolvedProfilePath -TotalCount 200 -ErrorAction SilentlyContinue
if (-not $head) {
    [Console]::Error.WriteLine("FAIL: profile is empty or unreadable at $resolvedProfilePath")
    exit 49
}

$found = $null
foreach ($line in $head) {
    if ($line -match '^\s*version\s*[:=]\s*v?(\d+)') { $found = "v$($Matches[1])"; break }
    if ($line -match 'canonical\s+v(\d+)') { $found = "v$($Matches[1])"; break }
}

# Fallback: derive version from filename (e.g. ..._v4_...md)
if (-not $found) {
    $leaf = Split-Path -Leaf $resolvedProfilePath
    if ($leaf -match '_v(\d+)[_\.]') { $found = "v$($Matches[1])" }
}

if (-not $found) {
    [Console]::Error.WriteLine("FAIL: no version marker (filename _vN_ | version: N | canonical vN) found in first 200 lines of $resolvedProfilePath")
    exit 49
}

if ($found -ne $ExpectedVersion) {
    [Console]::Error.WriteLine("FAIL: profile version mismatch - found '$found', expected '$ExpectedVersion' at $resolvedProfilePath")
    exit 49
}

Write-Output "OK: profile=$resolvedProfilePath version=$found"
exit 0
