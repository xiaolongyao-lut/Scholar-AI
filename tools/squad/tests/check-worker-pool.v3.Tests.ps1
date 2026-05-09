# Pester-3.4.0-compatible tests for tools/squad/check-worker-pool.ps1
#
# A parallel Morpheus instance authored check-worker-pool.Tests.ps1 against
# Pester v5 syntax (BeforeAll outside Describe; Should -Be). The installed
# Pester on this machine is 3.4.0, which rejects that syntax. Rather than
# overwrite the v5 tests (Surgical Changes rule, CLAUDE.md repo guidance),
# this file ships an additive v3-compatible variant covering the same 4 DoD
# cases (FRESH path with seconds, FRESH path with minutes, STALE path,
# morpheus-self-exclusion). When Pester v5 is installed in the future, the
# other file will work; today this one runs green on the installed runtime.
#
# Run with:
#   Invoke-Pester tools/squad/tests/check-worker-pool.v3.Tests.ps1

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $here '..' 'check-worker-pool.ps1'

Describe 'check-worker-pool.ps1 (Pester 3 compatible)' {

    It 'exits 0 and emits the agent id when one fresh claude-protocol-2 worker exists' {
        $fixture = "  morpheus (role: morpheus) - idle (2m ago) [client: claude, protocol: 2]`n  tank-r4 (role: tank) - idle (3m ago) [client: claude, protocol: 2]`n  tank-r3 (role: tank) - stale (50m ago) [client: claude, protocol: 2]"
        $stdout = & $scriptPath -AgentsOutput $fixture
        $LASTEXITCODE | Should Be 0
        $stdout | Should Be 'tank-r4'
    }

    It 'counts seconds-units as fresh (0m)' {
        $fixture = '  inspector-r1 (role: inspector) - active (45s ago) [client: claude, protocol: 2]'
        $stdout = & $scriptPath -AgentsOutput $fixture
        $LASTEXITCODE | Should Be 0
        $stdout | Should Be 'inspector-r1'
    }

    It 'exits 2 when every non-morpheus worker is stale beyond MaxAgeMinutes' {
        $fixture = "  morpheus (role: morpheus) - idle (2m ago) [client: claude, protocol: 2]`n  tank-r3 (role: tank) - stale (50m ago) [client: claude, protocol: 2]`n  inspector-r1 (role: inspector) - idle (14m ago) [client: claude, protocol: 2]"
        & $scriptPath -AgentsOutput $fixture 2>$null
        $LASTEXITCODE | Should Be 2
    }

    It 'excludes role=morpheus even when fresh' {
        $fixture = '  morpheus (role: morpheus) - idle (1m ago) [client: claude, protocol: 2]'
        & $scriptPath -AgentsOutput $fixture 2>$null
        $LASTEXITCODE | Should Be 2
    }
}
