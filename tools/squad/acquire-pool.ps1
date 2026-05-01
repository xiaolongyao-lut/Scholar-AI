# acquire-pool.ps1 — Multi-terminal coordination lock for resources mentioned in
# the kernel docs (e.g., requirement-pool). Wraps Acquire-PoolLock from
# squad-guard.ps1 with a CLI-friendly surface.
#
# Usage:
#   .\tools\squad\acquire-pool.ps1 -Name requirement-pool -Purpose 'morpheus-pull'
#   .\tools\squad\acquire-pool.ps1 -Name requirement-pool -Release
#
# Holds the lock for the lifetime of THIS process (so a hosting script keeps
# the file open). With -Release, removes a stale lockfile if the owner is gone.

param(
    [Parameter(Mandatory)] [string]$Name,
    [string]$Purpose = 'manual',
    [int]$StaleSeconds = 0,
    [switch]$Release,
    [switch]$WaitForever,
    [string]$Command,
    [string[]]$CommandArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'squad-guard.ps1')

if ($Release) {
    $lockPath = Join-Path (Get-ProjectRoot) ".squad\locks\$Name.lock"
    if (-not (Test-Path $lockPath)) {
        Write-Output "No lock file at $lockPath; nothing to release."
        exit 0
    }
    try {
        # If we can open exclusively, the previous owner is gone — safe to delete.
        $h = [System.IO.File]::Open($lockPath, 'Open', 'ReadWrite', 'None')
        $h.Dispose()
        Remove-Item -Path $lockPath -Force -ErrorAction SilentlyContinue
        Write-Output "Released stale lock $Name."
        exit 0
    } catch {
        Write-Error "Lock $Name still held by a live process; refusing to force-release."
        exit 8
    }
}

$handle = Acquire-PoolLock -Name $Name -Purpose $Purpose -StaleSeconds $StaleSeconds
if (-not $handle) {
    Write-Error "Pool lock '$Name' is held by another process."
    exit 9
}

Write-Output "Acquired pool lock '$Name' (purpose=$Purpose, pid=$PID). Path=$($handle.Path)"

try {
    if (-not [string]::IsNullOrWhiteSpace($Command)) {
        & $Command @CommandArgs
        exit $LASTEXITCODE
    }

    if ($WaitForever) {
        Write-Output "Holding lock; press Ctrl+C to release."
        while ($true) { Start-Sleep -Seconds 60 }
    }
    # Otherwise return immediately. The lock is released when this process exits
    # because the OS closes the file handle.
} finally {
    Release-PoolLock -Handle $handle
}
