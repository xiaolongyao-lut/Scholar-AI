# Pester tests for tools/openclaw/start-wechat-gateway.ps1
# Compatible with the older Pester version available on this host.

$scriptPath = Join-Path $PSScriptRoot '..' | Join-Path -ChildPath 'start-wechat-gateway.ps1'

function New-TestStateRoot {
    param(
        [switch]$WithPersistedLogin
    )

    $root = Join-Path $env:TEMP ("openclaw-test-" + [guid]::NewGuid().ToString('N'))
    $accountsDir = Join-Path $root 'openclaw-weixin\accounts'
    New-Item -ItemType Directory -Path $accountsDir -Force | Out-Null

    if ($WithPersistedLogin) {
        Set-Content -Path (Join-Path $accountsDir 'a8afe90eb6b1-im-bot.json') -Value '{"accountId":"a8afe90eb6b1-im-bot"}'
    }

    return $root
}

Describe 'start-wechat-gateway.ps1' {

    It 'prints the self-heal commands in dry-run mode' {
        $stateRoot = New-TestStateRoot -WithPersistedLogin
        try {
            $stdout = & $scriptPath -StateRoot $stateRoot -DryRun
            $LASTEXITCODE | Should Be 0
            ($stdout -join "`n") | Should Match 'openclaw config set gateway.mode local'
            ($stdout -join "`n") | Should Match 'openclaw config set gateway.bind loopback'
            ($stdout -join "`n") | Should Match 'openclaw gateway run --force'
        }
        finally {
            Remove-Item -Path $stateRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'prints backend ACP environment in dry-run mode' {
        $stateRoot = New-TestStateRoot -WithPersistedLogin
        $projectRoot = Join-Path $env:TEMP ("openclaw-project-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $projectRoot -Force | Out-Null
        try {
            $stdout = & $scriptPath -StateRoot $stateRoot -ProjectRoot $projectRoot -DryRun
            $LASTEXITCODE | Should Be 0
            $joined = $stdout -join "`n"
            $escapedProjectRoot = [regex]::Escape([System.IO.Path]::GetFullPath($projectRoot))
            $joined | Should Match ("WEIXIN_CODEX_ACP_CWD={0}" -f $escapedProjectRoot)
            $joined | Should Match ("WEIXIN_CLAUDE_ACP_CWD={0}" -f $escapedProjectRoot)
            $joined | Should Match ("WEIXIN_COPILOT_ACP_CWD={0}" -f $escapedProjectRoot)
            $joined | Should Match 'WEIXIN_COPILOT_ACP_ARGS=--acp --stdio --allow-all'
        }
        finally {
            Remove-Item -Path $stateRoot -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $projectRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'passes openclaw command arguments separately' {
        $stateRoot = New-TestStateRoot -WithPersistedLogin
        $projectRoot = Join-Path $env:TEMP ("openclaw-project-" + [guid]::NewGuid().ToString('N'))
        $fakeBin = Join-Path $env:TEMP ("openclaw-fake-bin-" + [guid]::NewGuid().ToString('N'))
        $logPath = Join-Path $env:TEMP ("openclaw-args-" + [guid]::NewGuid().ToString('N') + '.log')
        New-Item -ItemType Directory -Path $projectRoot -Force | Out-Null
        New-Item -ItemType Directory -Path $fakeBin -Force | Out-Null
        Set-Content -Path (Join-Path $fakeBin 'openclaw.ps1') -Value @'
Add-Content -Path $env:OPENCLAW_FAKE_ARGS_LOG -Value ("count={0};args={1}" -f $args.Count, ($args -join '|'))
exit 0
'@
        $oldPath = $env:Path
        $oldFakeArgsLog = $env:OPENCLAW_FAKE_ARGS_LOG
        try {
            $env:Path = ("{0};{1}" -f $fakeBin, $oldPath)
            $env:OPENCLAW_FAKE_ARGS_LOG = $logPath
            & $scriptPath -StateRoot $stateRoot -ProjectRoot $projectRoot | Out-Null
            $LASTEXITCODE | Should Be 0
            $lines = @(Get-Content -Path $logPath)
            $lines[0] | Should Be 'count=4;args=config|set|gateway.mode|local'
            $lines[1] | Should Be 'count=4;args=config|set|gateway.bind|loopback'
            $lines[2] | Should Be 'count=3;args=gateway|run|--force'
        }
        finally {
            $env:Path = $oldPath
            $env:OPENCLAW_FAKE_ARGS_LOG = $oldFakeArgsLog
            Remove-Item -Path $stateRoot -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $projectRoot -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $fakeBin -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -Path $logPath -Force -ErrorAction SilentlyContinue
        }
    }

    It 'reports persisted login when account artifacts exist' {
        $stateRoot = New-TestStateRoot -WithPersistedLogin
        try {
            $stdout = & $scriptPath -StateRoot $stateRoot -DryRun
            $LASTEXITCODE | Should Be 0
            ($stdout -join "`n") | Should Match 'Persisted Weixin session artifacts found'
            ($stdout -join "`n") | Should Match 'QR login is likely not required'
        }
        finally {
            Remove-Item -Path $stateRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'warns that QR login may be required when no account artifact exists' {
        $stateRoot = New-TestStateRoot
        try {
            $stdout = & $scriptPath -StateRoot $stateRoot -DryRun
            $LASTEXITCODE | Should Be 0
            ($stdout -join "`n") | Should Match 'No persisted Weixin account artifact found'
            ($stdout -join "`n") | Should Match 'QR login may be required'
        }
        finally {
            Remove-Item -Path $stateRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
