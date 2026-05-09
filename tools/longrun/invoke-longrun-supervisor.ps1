param(
    [string]$Workspace = "",
    [int]$MaxRunMinutes = 25,
    [ValidateSet('Scheduled', 'Manual')]
    [string]$RunSource = 'Scheduled',
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-Workspace {
    param([string]$Candidate)

    if (-not [string]::IsNullOrWhiteSpace($Candidate)) {
        $resolved = Resolve-Path -LiteralPath $Candidate -ErrorAction Stop
        return $resolved.Path
    }

    $scriptDir = Split-Path -Parent $PSCommandPath
    $root = Split-Path -Parent (Split-Path -Parent $scriptDir)
    $resolvedRoot = Resolve-Path -LiteralPath $root -ErrorAction Stop
    return $resolvedRoot.Path
}

function New-StateDirectory {
    param([string]$WorkspacePath)

    if ([string]::IsNullOrWhiteSpace($WorkspacePath)) {
        throw 'WorkspacePath is required.'
    }

    $stateDir = Join-Path $WorkspacePath 'workspace_artifacts\runtime_state\longrun-supervisor'
    $logDir = Join-Path $stateDir 'logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    return @{
        StateDir = $stateDir
        LogDir = $logDir
    }
}

function Write-JsonLine {
    param(
        [string]$Path,
        [hashtable]$Event
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'Path is required.'
    }
    if ($null -eq $Event) {
        throw 'Event is required.'
    }

    $payload = [ordered]@{
        ts = (Get-Date).ToString('o')
    }
    foreach ($key in $Event.Keys) {
        $payload[$key] = $Event[$key]
    }
    Add-Content -LiteralPath $Path -Value ($payload | ConvertTo-Json -Compress -Depth 8) -Encoding UTF8
}

function Get-LivePidFromLock {
    param([string]$LockPath)

    if (-not (Test-Path -LiteralPath $LockPath)) {
        return $null
    }

    $raw = Get-Content -LiteralPath $LockPath -Raw -ErrorAction SilentlyContinue
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }

    try {
        $entry = $raw | ConvertFrom-Json
        if (-not ($entry.PSObject.Properties.Name -contains 'pid')) {
            return $null
        }
        $pidValue = [int]$entry.pid
        if ($pidValue -le 0) {
            return $null
        }
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($null -eq $proc) {
            return $null
        }
        return $pidValue
    } catch {
        return $null
    }
}

function Get-ActiveInteractiveSession {
    param(
        [string]$SessionPath,
        [datetime]$Now
    )

    if ([string]::IsNullOrWhiteSpace($SessionPath)) {
        throw 'SessionPath is required.'
    }

    if (-not (Test-Path -LiteralPath $SessionPath)) {
        return $null
    }

    try {
        $session = Get-Content -LiteralPath $SessionPath -Raw | ConvertFrom-Json
        if (-not ($session.PSObject.Properties.Name -contains 'expires_at')) {
            Remove-Item -LiteralPath $SessionPath -Force -ErrorAction SilentlyContinue
            return $null
        }
        $expiresAt = [datetime]$session.expires_at
        if ($expiresAt -le $Now) {
            Remove-Item -LiteralPath $SessionPath -Force -ErrorAction SilentlyContinue
            return $null
        }
        return $session
    } catch {
        Remove-Item -LiteralPath $SessionPath -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function New-RunLock {
    param(
        [string]$LockPath,
        [string]$RunId,
        [string]$RunSource
    )

    if ([string]::IsNullOrWhiteSpace($LockPath)) {
        throw 'LockPath is required.'
    }
    if ([string]::IsNullOrWhiteSpace($RunId)) {
        throw 'RunId is required.'
    }
    if ([string]::IsNullOrWhiteSpace($RunSource)) {
        throw 'RunSource is required.'
    }

    $livePid = Get-LivePidFromLock -LockPath $LockPath
    if ($null -ne $livePid) {
        throw "Another longrun supervisor is active (pid=$livePid)."
    }

    if (Test-Path -LiteralPath $LockPath) {
        Remove-Item -LiteralPath $LockPath -Force
    }

    $stream = [System.IO.File]::Open(
        $LockPath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    try {
        $lockPayload = [ordered]@{
            pid = $PID
            run_id = $RunId
            source = $RunSource
            started_at = (Get-Date).ToString('o')
        } | ConvertTo-Json -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($lockPayload)
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush()
        return $stream
    } catch {
        $stream.Dispose()
        throw
    }
}

function Invoke-CodexRun {
    param(
        [string]$WorkspacePath,
        [string]$PromptText,
        [string]$LastMessagePath,
        [string]$CodexPath,
        [int]$TimeoutSeconds
    )

    if (-not (Test-Path -LiteralPath $WorkspacePath)) {
        throw "WorkspacePath does not exist: $WorkspacePath"
    }
    if ([string]::IsNullOrWhiteSpace($PromptText)) {
        throw 'PromptText is required.'
    }
    if ([string]::IsNullOrWhiteSpace($CodexPath)) {
        throw 'CodexPath is required.'
    }
    if ($TimeoutSeconds -lt 60) {
        throw 'TimeoutSeconds must be at least 60.'
    }

    $job = Start-Job -Name "literature-assistant-longrun" -ScriptBlock {
        param(
            [string]$WorkspacePathInner,
            [string]$PromptTextInner,
            [string]$LastMessagePathInner,
            [string]$CodexPathInner
        )

        Set-Location -LiteralPath $WorkspacePathInner
        $output = New-Object System.Collections.Generic.List[string]
        $PromptTextInner | & $CodexPathInner exec --search -C $WorkspacePathInner -a never -s danger-full-access --output-last-message $LastMessagePathInner - 2>&1 |
            ForEach-Object {
                $output.Add([string]$_)
            }
        [pscustomobject]@{
            ExitCode = $LASTEXITCODE
            Output = [string[]]$output
        }
    } -ArgumentList $WorkspacePath, $PromptText, $LastMessagePath, $CodexPath

    $completed = Wait-Job -Job $job -Timeout $TimeoutSeconds
    if ($null -eq $completed) {
        Stop-Job -Job $job -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        return [pscustomobject]@{
            ExitCode = 124
            Output = @("longrun supervisor timed out after $TimeoutSeconds seconds")
            TimedOut = $true
        }
    }

    $result = Receive-Job -Job $job
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    if ($null -eq $result) {
        return [pscustomobject]@{
            ExitCode = 1
            Output = @('codex exec produced no result object')
            TimedOut = $false
        }
    }

    return [pscustomobject]@{
        ExitCode = [int]$result.ExitCode
        Output = [string[]]$result.Output
        TimedOut = $false
    }
}

if ($MaxRunMinutes -lt 5 -or $MaxRunMinutes -gt 180) {
    throw 'MaxRunMinutes must be between 5 and 180.'
}

$workspacePath = Resolve-Workspace -Candidate $Workspace
$paths = New-StateDirectory -WorkspacePath $workspacePath
$stateDir = [string]$paths.StateDir
$logDir = [string]$paths.LogDir
$eventsPath = Join-Path $stateDir 'events.jsonl'
$stopPath = Join-Path $stateDir 'STOP'
$lockPath = Join-Path $stateDir 'run.lock'
$interactiveSessionPath = Join-Path $stateDir 'interactive-session.json'
$runId = (Get-Date).ToString('yyyyMMdd-HHmmss')
$runLogPath = Join-Path $logDir "$runId.log"
$lastMessagePath = Join-Path $stateDir 'last-message.md'
$heartbeatPath = Join-Path $stateDir 'heartbeat.json'
$promptPath = Join-Path (Split-Path -Parent $PSCommandPath) 'longrun-prompt.md'

Write-JsonLine -Path $eventsPath -Event @{
    event = 'tick'
    run_id = $runId
    source = $RunSource
    workspace = $workspacePath
}

if (Test-Path -LiteralPath $stopPath) {
    Write-JsonLine -Path $eventsPath -Event @{
        event = 'stopped_by_file'
        run_id = $runId
        source = $RunSource
        stop_file = $stopPath
    }
    exit 0
}

if ($RunSource -eq 'Scheduled') {
    $interactiveSession = Get-ActiveInteractiveSession -SessionPath $interactiveSessionPath -Now (Get-Date)
    if ($null -ne $interactiveSession) {
        Write-JsonLine -Path $eventsPath -Event @{
            event = 'skipped_interactive_session_active'
            run_id = $runId
            source = $RunSource
            session_id = $interactiveSession.session_id
            expires_at = $interactiveSession.expires_at
        }
        exit 0
    }
}

if (-not (Test-Path -LiteralPath $promptPath)) {
    throw "Prompt file is missing: $promptPath"
}

$lockStream = $null
try {
    $lockStream = New-RunLock -LockPath $lockPath -RunId $runId -RunSource $RunSource
} catch {
    Write-JsonLine -Path $eventsPath -Event @{
        event = 'skipped_lock_active'
        run_id = $runId
        source = $RunSource
        reason = "$_"
    }
    exit 0
}

try {
    $codex = Get-Command codex -ErrorAction Stop
    $promptBase = Get-Content -LiteralPath $promptPath -Raw
    $prompt = @"
Scheduled run id: $runId
Workspace: $workspacePath
Max run minutes: $MaxRunMinutes
Run source: $RunSource

$promptBase
"@

    if ($DryRun) {
        Set-Content -LiteralPath $runLogPath -Value $prompt -Encoding UTF8
        Write-JsonLine -Path $eventsPath -Event @{
            event = 'dry_run'
            run_id = $runId
            source = $RunSource
            log = $runLogPath
        }
        exit 0
    }

    $result = Invoke-CodexRun `
        -WorkspacePath $workspacePath `
        -PromptText $prompt `
        -LastMessagePath $lastMessagePath `
        -CodexPath $codex.Source `
        -TimeoutSeconds ($MaxRunMinutes * 60)

    Set-Content -LiteralPath $runLogPath -Value $result.Output -Encoding UTF8
    $heartbeat = [ordered]@{
        run_id = $runId
        source = $RunSource
        finished_at = (Get-Date).ToString('o')
        exit_code = $result.ExitCode
        timed_out = [bool]$result.TimedOut
        log = $runLogPath
        last_message = $lastMessagePath
    }
    Set-Content -LiteralPath $heartbeatPath -Value ($heartbeat | ConvertTo-Json -Depth 8) -Encoding UTF8
    Write-JsonLine -Path $eventsPath -Event @{
        event = 'finished'
        run_id = $runId
        source = $RunSource
        exit_code = $result.ExitCode
        timed_out = [bool]$result.TimedOut
        log = $runLogPath
    }
    exit $result.ExitCode
} finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}
