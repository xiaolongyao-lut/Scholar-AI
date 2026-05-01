# squad-guard.ps1 — Safety rails shared by all Morpheus autopilot scripts.
# Dot-source this file: . .\tools\squad\squad-guard.ps1
#
# Guarantees:
#   - Project path lock: rejects work outside the known project root (with a short allowlist).
#   - Command denylist: blocks catastrophic operations even if Morpheus asks.
#   - Confirm list: returns 'confirm' for commands that need a human y/n.
#
# Exposes:
#   Test-PathAllowed       ($path)              -> $true/$false
#   Test-CommandAllowed    ($commandText)       -> 'allow' | 'deny' | 'confirm'
#   Write-GuardLog         ($level, $msg, $ctx) -> appends to .squad/autopilot-logs/guard.log
#   Get-ProjectRoot                             -> absolute project root

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:ProjectRoot = 'C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script'
$script:GuardLogDir = Join-Path $script:ProjectRoot '.squad\autopilot-logs'
$script:GuardLog    = Join-Path $script:GuardLogDir 'guard.log'

# Paths outside the project that autopilot is allowed to touch.
$script:PathAllowlistExtra = @(
    'C:\Tools\squad',
    'C:\Users\xiao\AppData\Roaming\npm',
    'C:\Users\xiao\AppData\Local\pip',
    'C:\Users\xiao\.claude'
)

# Absolute paths that must never be the *target* of any destructive op.
$script:PathHardBlock = @(
    'C:\',
    'C:\Windows',
    'C:\Windows\System32',
    'C:\Program Files',
    'C:\Program Files (x86)',
    'C:\Users',
    'C:\Users\xiao',
    $script:ProjectRoot   # project root itself — children ok, root itself not
)

function Get-ProjectRoot { return $script:ProjectRoot }

function Write-GuardLog {
    param(
        [Parameter(Mandatory)] [ValidateSet('INFO','WARN','DENY','CONFIRM','EXEC')] [string]$Level,
        [Parameter(Mandatory)] [string]$Message,
        [hashtable]$Context
    )
    if (-not (Test-Path $script:GuardLogDir)) {
        New-Item -ItemType Directory -Force -Path $script:GuardLogDir | Out-Null
    }
    $ts = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')
    $ctxStr = if ($Context) { ($Context | ConvertTo-Json -Compress) } else { '{}' }
    $line = "[$ts] [$Level] $Message $ctxStr"
    Add-Content -Path $script:GuardLog -Value $line -Encoding UTF8
}

function Test-PathAllowed {
    param([Parameter(Mandatory)] [string]$Path)
    try {
        # Resolve to absolute. Non-existent paths: use Join-Path-style normalisation.
        $abs = if (Test-Path $Path) {
            (Resolve-Path -LiteralPath $Path).Path
        } else {
            [System.IO.Path]::GetFullPath($Path)
        }
    } catch {
        return $false
    }

    # Reject hard-blocked exact paths.
    foreach ($blocked in $script:PathHardBlock) {
        if ($abs.TrimEnd('\') -ieq $blocked.TrimEnd('\')) {
            return $false
        }
    }

    # Allow if under project root.
    if ($abs.StartsWith($script:ProjectRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }

    # Allow if under one of the extra allowlist roots.
    foreach ($allow in $script:PathAllowlistExtra) {
        if ($abs.StartsWith($allow, [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    return $false
}

# Returns: 'allow' | 'deny' | 'confirm'
function Test-CommandAllowed {
    param([Parameter(Mandatory)] [string]$CommandText)

    $c = $CommandText.Trim()

    # --- DENY list ---
    $denyPatterns = @(
        # Disk / partition
        '(?i)\bformat\s+[a-z]:',
        '(?i)\bdiskpart\b',
        '(?i)\bfdisk\b',

        # Mass delete at suspicious roots
        '(?i)rmdir\s+/s\s+/q\s+c:\\?\s*(\s|$)',
        '(?i)rmdir\s+/s\s+/q\s+c:\\windows',
        '(?i)del\s+/f\s+/s\s+/q\s+c:\\?\s*(\s|$)',
        '(?i)del\s+/f\s+/s\s+/q\s+c:\\windows',
        '(?i)Remove-Item\b[^;|]*\s+(''|")?C:\\?(''|")?\s*(\s|-|$)',
        '(?i)Remove-Item\b[^;|]*\s+(''|")?C:\\Windows',
        '(?i)Remove-Item\b[^;|]*\s+(''|")?C:\\Users\\xiao(''|")?\s*(\s|-|$)',

        # System / account / power
        '(?i)\bshutdown\b',
        '(?i)\bRestart-Computer\b',
        '(?i)\bnet\s+user\b',
        '(?i)\bAdd-LocalGroupMember\b',
        '(?i)\bRemove-LocalUser\b',

        # System dirs / registry
        '(?i)Set-Content\s+[^;|]*C:\\Windows\\System32',
        '(?i)Remove-Item\s+[^;|]*HKLM:',
        '(?i)Set-ItemProperty\s+[^;|]*HKLM:',
        '(?i)New-ItemProperty\s+[^;|]*HKLM:',

        # PATH tampering (we already set it once; Morpheus should not re-touch)
        '(?i)SetEnvironmentVariable\s*\(\s*[''"]Path[''"]',

        # Force-push to remotes
        '(?i)\bgit\s+push\s+.*--force',
        '(?i)\bgit\s+push\s+.*-f\b'
    )
    foreach ($p in $denyPatterns) {
        if ($c -match $p) {
            Write-GuardLog -Level DENY -Message 'Denylist match' -Context @{ pattern = $p; cmd = $c }
            return 'deny'
        }
    }

    # --- CONFIRM list ---
    $confirmPatterns = @(
        '(?i)\bnpm\s+(install|i)\s+.*(-g|--global)\b',
        '(?i)\bpip\s+install\s+.*--user\b',
        '(?i)\bpip\s+install\s+(?!(-r|--requirement)\b)'  # pip install <pkg> without -r → confirm
    )
    foreach ($p in $confirmPatterns) {
        if ($c -match $p) {
            Write-GuardLog -Level CONFIRM -Message 'Confirm required' -Context @{ pattern = $p; cmd = $c }
            return 'confirm'
        }
    }

    return 'allow'
}

# --- Policy access -----------------------------------------------------------

function Get-SquadPolicy {
    $policyPath = Join-Path $script:ProjectRoot '.squad\casting-policy.json'
    if (-not (Test-Path $policyPath)) { return $null }
    try { return (Get-Content $policyPath -Raw | ConvertFrom-Json) } catch { return $null }
}

# --- Pool lock (Finding #6) --------------------------------------------------
# Generic JSON-backed file lock for multi-terminal coordination. Returns
# a stream handle on success ($null on contention). Caller must Release-PoolLock.

function Acquire-PoolLock {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [string]$Purpose = 'unspecified',
        [int]$StaleSeconds = 0   # 0 → use policy.execution_profile.auto_close_idle_seconds (fallback 120)
    )
    $lockDir = Join-Path $script:ProjectRoot '.squad\locks'
    if (-not (Test-Path $lockDir)) { New-Item -ItemType Directory -Force -Path $lockDir | Out-Null }
    $lockPath = Join-Path $lockDir "$Name.lock"

    if ($StaleSeconds -le 0) {
        $policy = Get-SquadPolicy
        if ($policy -and $policy.execution_profile.auto_close_idle_seconds) {
            $StaleSeconds = [int]$policy.execution_profile.auto_close_idle_seconds
        } else { $StaleSeconds = 120 }
    }

    # Stale-reclaim: if the lock file exists with JSON metadata but the owner is gone
    # or the lock is older than $StaleSeconds, try to remove it. The actual exclusive
    # acquisition below will still fail if a live process holds the OS handle.
    if (Test-Path $lockPath) {
        try {
            $raw = Get-Content $lockPath -Raw -ErrorAction SilentlyContinue
            if ($raw -and $raw.Trim()) {
                $meta = $raw | ConvertFrom-Json
                $ownerPid = if ($meta.PSObject.Properties.Name -contains 'owner_pid') { [int]$meta.owner_pid } else { 0 }
                $started  = if ($meta.PSObject.Properties.Name -contains 'started_at') { [datetime]$meta.started_at } else { (Get-Date) }
                $owner = if ($ownerPid -gt 0) { Get-Process -Id $ownerPid -ErrorAction SilentlyContinue } else { $null }
                $ageSec = ((Get-Date) - $started).TotalSeconds
                if (-not $owner -or $ageSec -gt $StaleSeconds) {
                    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
                    Write-GuardLog -Level WARN -Message 'Reclaimed stale pool lock' -Context @{ name = $Name; ownerPid = $ownerPid; ageSec = [int]$ageSec }
                }
            }
        } catch {}
    }

    # Exclusive open. FileShare=None → second caller throws.
    $stream = $null
    try {
        $stream = [System.IO.File]::Open($lockPath, 'CreateNew', 'ReadWrite', 'None')
    } catch {
        Write-GuardLog -Level DENY -Message 'Pool lock contention' -Context @{ name = $Name; purpose = $Purpose }
        return $null
    }

    # Write metadata.
    $meta = @{
        owner_pid  = $PID
        host       = $env:COMPUTERNAME
        started_at = (Get-Date).ToString('o')
        purpose    = $Purpose
        name       = $Name
    } | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($meta)
    $stream.SetLength(0)
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush()

    Write-GuardLog -Level INFO -Message 'Pool lock acquired' -Context @{ name = $Name; purpose = $Purpose }
    return [PSCustomObject]@{ Name = $Name; Path = $lockPath; Stream = $stream }
}

function Release-PoolLock {
    param([Parameter(Mandatory)] $Handle)
    if (-not $Handle) { return }
    try { $Handle.Stream.Dispose() } catch {}
    Remove-Item -Path $Handle.Path -Force -ErrorAction SilentlyContinue
    Write-GuardLog -Level INFO -Message 'Pool lock released' -Context @{ name = $Handle.Name }
}

# --- Circuit breaker (Finding #12) -------------------------------------------
# State file: .squad/state/circuit-breaker.json
# { "scope": "spawn", "window_start": "...", "failures": N, "tripped_until": "..." }

function Get-BreakerStatePath {
    param([string]$Scope = 'spawn')
    $stateDir = Join-Path $script:ProjectRoot '.squad\state'
    if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Force -Path $stateDir | Out-Null }
    return (Join-Path $stateDir "circuit-breaker-$Scope.json")
}

function Test-CircuitBreaker {
    param([string]$Scope = 'spawn')
    $path = Get-BreakerStatePath -Scope $Scope
    if (-not (Test-Path $path)) { return [PSCustomObject]@{ Tripped = $false; UntilUtc = $null } }
    try {
        $state = Get-Content $path -Raw | ConvertFrom-Json
        if ($state.PSObject.Properties.Name -contains 'tripped_until' -and $state.tripped_until) {
            $until = [datetime]$state.tripped_until
            if ((Get-Date).ToUniversalTime() -lt $until.ToUniversalTime()) {
                return [PSCustomObject]@{ Tripped = $true; UntilUtc = $until }
            }
        }
    } catch {}
    return [PSCustomObject]@{ Tripped = $false; UntilUtc = $null }
}

function Record-BreakerOutcome {
    param(
        [Parameter(Mandatory)] [ValidateSet('success','failure')] [string]$Outcome,
        [string]$Scope = 'spawn',
        [string]$Reason = ''
    )
    $policy = Get-SquadPolicy
    $cb = if ($policy -and $policy.execution_profile.circuit_breaker) { $policy.execution_profile.circuit_breaker } else { $null }
    if (-not $cb -or -not $cb.enabled) { return }

    $windowSec   = if ($cb.failure_window_seconds) { [int]$cb.failure_window_seconds } else { 300 }
    $maxFailures = if ($cb.failures_to_trip)       { [int]$cb.failures_to_trip }       else { 3 }
    $cooldownSec = if ($cb.cooldown_seconds)       { [int]$cb.cooldown_seconds }       else { 120 }

    $path = Get-BreakerStatePath -Scope $Scope
    $now = (Get-Date).ToUniversalTime()
    $state = $null
    if (Test-Path $path) {
        try { $state = Get-Content $path -Raw | ConvertFrom-Json } catch { $state = $null }
    }
    if (-not $state) {
        $state = [PSCustomObject]@{ scope = $Scope; window_start = $now.ToString('o'); failures = 0; tripped_until = $null; last_reason = '' }
    }

    if ($Outcome -eq 'success') {
        # Window-expiry reset only — preserve breaker if currently tripped.
        try {
            $ws = [datetime]$state.window_start
            if (($now - $ws.ToUniversalTime()).TotalSeconds -gt $windowSec) {
                $state.window_start = $now.ToString('o')
                $state.failures = 0
            }
        } catch {
            $state.window_start = $now.ToString('o')
            $state.failures = 0
        }
    } else {
        # Failure: reset window if expired, then increment.
        try {
            $ws = [datetime]$state.window_start
            if (($now - $ws.ToUniversalTime()).TotalSeconds -gt $windowSec) {
                $state.window_start = $now.ToString('o')
                $state.failures = 0
            }
        } catch {
            $state.window_start = $now.ToString('o')
            $state.failures = 0
        }
        $state.failures = [int]$state.failures + 1
        $state.last_reason = $Reason
        if ($state.failures -ge $maxFailures) {
            $state.tripped_until = $now.AddSeconds($cooldownSec).ToString('o')
            Write-GuardLog -Level WARN -Message 'Circuit breaker TRIPPED' -Context @{ scope = $Scope; failures = $state.failures; cooldown = $cooldownSec; reason = $Reason }
        }
    }

    $tmp = "$path.tmp"
    ($state | ConvertTo-Json) | Set-Content -Path $tmp -Encoding UTF8
    Move-Item -Force $tmp $path
}
