# claim-self-explore.ps1
# Anti-pollution registry for parallel Morpheus self-explore filings.
# Implements design at .squad/identity/requirement-pool.md line 2819 (session 070418b).
#
# Use BEFORE writing a self-explore entry to .squad/identity/requirement-pool.md:
#   . tools/squad/diag/claim-self-explore.ps1
#   $ok = New-Claim -CandidateKey 'rlhf-pool' -SessionId '070644'
#   if (-not $ok) { Write-Host 'PIVOT: candidate already claimed'; return }
#   # ... append to pool ...
#
# Atomicity: New-Item with -ErrorAction SilentlyContinue is OS-atomic on
# Windows NTFS; if the file already exists, it returns $null and we report
# the holder. No double-claim is possible.

$script:ClaimDir = Join-Path $PSScriptRoot '..\..\..\.squad\claims' | Resolve-Path -ErrorAction SilentlyContinue
if (-not $script:ClaimDir) {
    $script:ClaimDir = Join-Path $PSScriptRoot '..\..\..\.squad\claims'
    New-Item -ItemType Directory -Path $script:ClaimDir -Force | Out-Null
}

function Test-ClaimAvailable {
    param(
        [Parameter(Mandatory)][string]$CandidateKey
    )
    $path = Join-Path $script:ClaimDir "$CandidateKey.claim"
    if (Test-Path $path) {
        $holder = (Get-Content $path -ErrorAction SilentlyContinue) -join ' '
        return [PSCustomObject]@{ Available = $false; Holder = $holder; Path = $path }
    }
    return [PSCustomObject]@{ Available = $true; Holder = $null; Path = $path }
}

function New-Claim {
    param(
        [Parameter(Mandatory)][string]$CandidateKey,
        [Parameter(Mandatory)][string]$SessionId
    )
    $path = Join-Path $script:ClaimDir "$CandidateKey.claim"
    $f = New-Item -ItemType File -Path $path -ErrorAction SilentlyContinue
    if (-not $f) { return $false }
    Set-Content -Path $path -Value "session=$SessionId`nts=$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')" -NoNewline
    return $true
}

function Get-ClaimList {
    Get-ChildItem -Path $script:ClaimDir -Filter '*.claim' -ErrorAction SilentlyContinue |
        ForEach-Object {
            [PSCustomObject]@{
                Candidate = $_.BaseName
                Holder    = (Get-Content $_.FullName -ErrorAction SilentlyContinue) -join ' '
                Mtime     = $_.LastWriteTime
            }
        }
}
