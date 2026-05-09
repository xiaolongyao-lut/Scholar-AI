# Pester tests for tools/squad/check-worker-pool.ps1
#
# Compatible with Pester 3.x (the version shipped on this host).
# Runs without invoking the real `squad` CLI by passing -AgentsOutput fixtures.
# Run with:
#   Invoke-Pester -Script tools/squad/tests/check-worker-pool.Tests.ps1

$scriptPath = Join-Path $PSScriptRoot '..' | Join-Path -ChildPath 'check-worker-pool.ps1'

Describe 'check-worker-pool.ps1' {

    It 'exits 0 and emits the agent id when one fresh claude-protocol-2 worker exists' {
        $fixture = @"
  morpheus (role: morpheus) — idle (2m ago) [client: claude, protocol: 2]
  tank-r4 (role: tank) — idle (3m ago) [client: claude, protocol: 2]
  tank-r3 (role: tank) — stale (50m ago) [client: claude, protocol: 2]
"@
        $stdout = & $scriptPath -AgentsOutput $fixture
        $LASTEXITCODE | Should Be 0
        $stdout | Should Be 'tank-r4'
    }

    It 'counts seconds-units as fresh' {
        $fixture = '  inspector-r1 (role: inspector) — active (45s ago) [client: claude, protocol: 2]'
        $stdout = & $scriptPath -AgentsOutput $fixture
        $LASTEXITCODE | Should Be 0
        $stdout | Should Be 'inspector-r1'
    }

    It 'exits 2 when every non-morpheus worker is stale beyond MaxAgeMinutes' {
        $fixture = @"
  morpheus (role: morpheus) — idle (2m ago) [client: claude, protocol: 2]
  tank-r3 (role: tank) — stale (50m ago) [client: claude, protocol: 2]
  inspector-r1 (role: inspector) — idle (14m ago) [client: claude, protocol: 2]
"@
        & $scriptPath -AgentsOutput $fixture 2>$null
        $LASTEXITCODE | Should Be 2
    }

    It 'excludes role=morpheus even when fresh' {
        $fixture = '  morpheus (role: morpheus) — idle (1m ago) [client: claude, protocol: 2]'
        & $scriptPath -AgentsOutput $fixture 2>$null
        $LASTEXITCODE | Should Be 2
    }

    It 'rejects non-claude clients' {
        $fixture = '  agent-9 (role: agent) — idle (1m ago) [client: unknown, protocol: 1]'
        & $scriptPath -AgentsOutput $fixture 2>$null
        $LASTEXITCODE | Should Be 2
    }
}
