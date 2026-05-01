# squad-lock.ps1 — Identity lock for squad agents (anti-collision shim).
#
# Why this exists:
#   Squad's own registry tracks an agent's name (e.g. "morpheus") via heartbeat.
#   When a process dies abruptly (force-kill, crash, power loss), the name stays
#   in the registry as 'stale' for ~10 minutes until the sweeper evicts it. Any
#   new process that tries `squad join morpheus` during that window collides
#   and the CLI auto-suffixes the new agent to `morpheus-2`, breaking task
#   routing (owner addresses tasks to `morpheus`).
#
#   This module replaces "trust the heartbeat" with "trust the OS PID":
#     - lock file at .squad/state/<role>.lock holds the live owner's PID
#     - PID alive (Get-Process)?  -> identity is held, refuse takeover
#     - PID dead?                 -> stale lock, force `squad leave <role>`,
#                                     overwrite lock, then `squad join`
#
#   PID-alive check is millisecond-fresh, so the moment the holder dies the
#   next caller can legally take the name. No collision, no -2 suffix.
#
# Public API:
#   Acquire-SquadIdentity -Role <name> [-OwnerPid <pid>] [-RealCli <path>]
#       Returns a hashtable: @{ ok=$bool; reason=<text>; pid=<int> }.
#       On ok=$true the caller now owns <role> in the squad registry and the
#       lock file. Caller MUST register a finally / engine-exit handler that
#       calls Release-SquadIdentity to free it on normal exit.
#
#   Release-SquadIdentity -Role <name> [-OwnerPid <pid>] [-RealCli <path>]
#       Releases the identity if and only if our PID owns the lock. Idempotent.
#
#   Test-SquadIdentityHeld -Role <name>
#       Returns $true if the lock points to an alive PID. Cheap probe; does
#       not mutate state.
#
# Concurrency:
#   Two callers racing on Acquire can both observe a missing/dead lock and
#   both write their PID. The squad CLI's own join semantics are the final
#   arbiter — whichever join lands first wins the registry; the loser's join
#   gets a -2 suffix anyway. So this lock is best-effort: it eliminates the
#   common cases (sequential restarts, manual kill + manual restart) but does
#   not pretend to solve the simultaneous-launch race. Don't launch two
#   morpheus processes at the same wall-clock instant. start-long-run holds
#   the autopilot path; supervisor's heal pass is single-threaded; manual
#   `claude /squad morpheus` is human-paced. None of these races in practice.

Set-StrictMode -Version Latest

function Resolve-LockPath {
    param([string]$Role)
    if ([string]::IsNullOrWhiteSpace($Role)) { throw 'role is required' }
    $repoRoot = if ($env:SQUAD_TEST_ROOT -and (Test-Path $env:SQUAD_TEST_ROOT)) {
        $env:SQUAD_TEST_ROOT
    } else {
        (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    }
    $stateDir = Join-Path $repoRoot '.squad\state'
    if (-not (Test-Path $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }
    return (Join-Path $stateDir "$Role.lock")
}

function Resolve-SquadCli {
    param([string]$RealCli)
    if ($RealCli -and (Test-Path $RealCli)) { return $RealCli }
    if ($env:SQUAD_REAL_CLI -and (Test-Path $env:SQUAD_REAL_CLI)) { return $env:SQUAD_REAL_CLI }
    # 2026-04-26: prefer squad-real.exe (renamed binary, bypasses our own
    # squad.cmd PATH shim to avoid recursion). Fall back to legacy squad.exe
    # for backwards compat with installations that haven't been shimmed yet.
    $renamed = 'C:\Tools\squad\squad-real.exe'
    if (Test-Path $renamed) { return $renamed }
    $installed = 'C:\Tools\squad\squad.exe'
    if (Test-Path $installed) { return $installed }
    return $null
}

function Get-SquadLockPid {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'lock path is required' }
    if (-not (Test-Path $Path)) { return $null }
    $raw = (Get-Content -Path $Path -Raw -ErrorAction SilentlyContinue)
    if ($null -eq $raw) { return $null }
    $raw = $raw.Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    $pidValue = 0
    if (-not [int]::TryParse($raw, [ref]$pidValue)) { return $null }
    if ($pidValue -le 0) { return $null }
    return $pidValue
}

function Test-PidAlive {
    param([int]$ProcessId)
    if ($ProcessId -le 0) { return $false }
    try {
        $p = Get-Process -Id $ProcessId -ErrorAction Stop
        return ($null -ne $p)
    } catch {
        return $false
    }
}

function Test-SquadIdentityHeld {
    param([Parameter(Mandatory)][string]$Role)
    $lockPath = Resolve-LockPath -Role $Role
    $existingPid = Get-SquadLockPid -Path $lockPath
    if ($null -eq $existingPid) { return $false }
    return (Test-PidAlive -ProcessId $existingPid)
}

function Acquire-SquadIdentity {
    param(
        [Parameter(Mandatory)][string]$Role,
        [int]$OwnerPid = $PID,
        [string]$RealCli
    )

    $lockPath = Resolve-LockPath -Role $Role
    $cli = Resolve-SquadCli -RealCli $RealCli

    $existingPid = Get-SquadLockPid -Path $lockPath
    if ($null -ne $existingPid -and $existingPid -eq $OwnerPid) {
        return @{
            ok     = $true
            reason = "identity '$Role' already held by PID $OwnerPid"
            pid    = $OwnerPid
        }
    }
    if ($null -ne $existingPid -and $existingPid -ne $OwnerPid) {
        if (Test-PidAlive -ProcessId $existingPid) {
            return @{
                ok     = $false
                reason = "identity '$Role' held by live PID $existingPid"
                pid    = $existingPid
            }
        }
        # Stale lock. Purge squad registry entry before takeover so the
        # subsequent join doesn't collide and get auto-suffixed.
        if ($cli) {
            try { & $cli leave $Role 2>&1 | Out-Null } catch {}
        }
        Remove-Item -Path $lockPath -Force -ErrorAction SilentlyContinue
    }

    # Write our PID first, then join. If join fails the lock is still ours
    # and the caller can decide whether to retry or release.
    Set-Content -Path $lockPath -Value ([string]$OwnerPid) -Encoding ascii -Force

    if ($cli) {
        try {
            & $cli join $Role --role $Role --client claude --protocol-version 2 2>&1 | Out-Null
        } catch {
            # Join failure is non-fatal here: caller may already be joined,
            # or the CLI may be unavailable. Lock is taken either way.
        }
    }

    return @{ ok = $true; reason = "acquired"; pid = $OwnerPid }
}

function Release-SquadIdentity {
    param(
        [Parameter(Mandatory)][string]$Role,
        [int]$OwnerPid = $PID,
        [string]$RealCli
    )

    $lockPath = Resolve-LockPath -Role $Role
    $cli = Resolve-SquadCli -RealCli $RealCli

    $existingPid = Get-SquadLockPid -Path $lockPath
    if ($null -eq $existingPid -or $existingPid -ne $OwnerPid) {
        # Not ours. Don't release — would clobber a legitimate successor.
        return @{ ok = $false; reason = "lock not held by PID $OwnerPid" }
    }

    if ($cli) {
        try { & $cli leave $Role 2>&1 | Out-Null } catch {}
    }
    Remove-Item -Path $lockPath -Force -ErrorAction SilentlyContinue
    return @{ ok = $true; reason = "released" }
}
