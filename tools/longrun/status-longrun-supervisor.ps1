param(
    [string]$Workspace = "",
    [string]$TaskName = "LiteratureAssistantLongrunAutopilot"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-Workspace {
    param([string]$Candidate)

    if (-not [string]::IsNullOrWhiteSpace($Candidate)) {
        return (Resolve-Path -LiteralPath $Candidate -ErrorAction Stop).Path
    }

    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path -LiteralPath (Split-Path -Parent (Split-Path -Parent $scriptDir)) -ErrorAction Stop).Path
}

$workspacePath = Resolve-Workspace -Candidate $Workspace
$stateDir = Join-Path $workspacePath 'workspace_artifacts\runtime_state\longrun-supervisor'
$heartbeatPath = Join-Path $stateDir 'heartbeat.json'
$eventsPath = Join-Path $stateDir 'events.jsonl'
$stopPath = Join-Path $stateDir 'STOP'
$lockPath = Join-Path $stateDir 'run.lock'
$interactiveSessionPath = Join-Path $stateDir 'interactive-session.json'
$lockInfo = $null
if (Test-Path -LiteralPath $lockPath) {
    try {
        $lockInfo = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
    } catch {
        $lockInfo = [ordered]@{
            unreadable = $true
            path = $lockPath
        }
    }
}
$interactiveSession = $null
if (Test-Path -LiteralPath $interactiveSessionPath) {
    try {
        $interactiveSession = Get-Content -LiteralPath $interactiveSessionPath -Raw | ConvertFrom-Json
    } catch {
        $interactiveSession = [ordered]@{
            unreadable = $true
            path = $interactiveSessionPath
        }
    }
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskInfo = if ($null -ne $task) { Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue } else { $null }

$status = [ordered]@{
    task_name = $TaskName
    task_exists = $null -ne $task
    task_state = if ($null -ne $task) { [string]$task.State } else { $null }
    last_run_time = if ($null -ne $taskInfo) { $taskInfo.LastRunTime.ToString('o') } else { $null }
    next_run_time = if ($null -ne $taskInfo) { $taskInfo.NextRunTime.ToString('o') } else { $null }
    last_task_result = if ($null -ne $taskInfo) { $taskInfo.LastTaskResult } else { $null }
    workspace = $workspacePath
    state_dir = $stateDir
    stop_file_present = Test-Path -LiteralPath $stopPath
    lock_present = Test-Path -LiteralPath $lockPath
    lock = $lockInfo
    interactive_session_present = Test-Path -LiteralPath $interactiveSessionPath
    interactive_session = $interactiveSession
    heartbeat = $null
    recent_events = @()
}

if (Test-Path -LiteralPath $heartbeatPath) {
    $status['heartbeat'] = Get-Content -LiteralPath $heartbeatPath -Raw | ConvertFrom-Json
}

if (Test-Path -LiteralPath $eventsPath) {
    $events = @(Get-Content -LiteralPath $eventsPath -Tail 10 -ErrorAction SilentlyContinue)
    $status['recent_events'] = @($events | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object {
        try { $_ | ConvertFrom-Json } catch { $_ }
    })
}

$status | ConvertTo-Json -Depth 10
