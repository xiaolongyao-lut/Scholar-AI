param(
    [string]$Workspace = "",
    [string]$TaskName = "LiteratureAssistantLongrunAutopilot",
    [int]$IntervalMinutes = 30,
    [int]$MaxRunMinutes = 25
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

if ([string]::IsNullOrWhiteSpace($TaskName)) {
    throw 'TaskName cannot be empty.'
}
if ($IntervalMinutes -lt 5 -or $IntervalMinutes -gt 1440) {
    throw 'IntervalMinutes must be between 5 and 1440.'
}
if ($MaxRunMinutes -lt 5 -or $MaxRunMinutes -ge $IntervalMinutes) {
    throw 'MaxRunMinutes must be at least 5 and lower than IntervalMinutes.'
}

$workspacePath = Resolve-Workspace -Candidate $Workspace
$runnerPath = Join-Path $workspacePath 'tools\longrun\invoke-longrun-supervisor.ps1'
if (-not (Test-Path -LiteralPath $runnerPath)) {
    throw "Runner script is missing: $runnerPath"
}

$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue)
$powershellExe = if ($null -ne $pwsh) { $pwsh.Source } else { (Get-Command powershell -ErrorAction Stop).Source }
$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$runnerPath`" -Workspace `"$workspacePath`" -MaxRunMinutes $MaxRunMinutes -RunSource Scheduled"
$action = New-ScheduledTaskAction -Execute $powershellExe -Argument $argument -WorkingDirectory $workspacePath
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes($IntervalMinutes) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes ($MaxRunMinutes + 5)) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$description = "Runs Codex longrun supervisor for the local literature assistant every $IntervalMinutes minutes with lock, stop-file, and workspace_artifacts logs."
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description $description -Force | Out-Null

$stateDir = Join-Path $workspacePath 'workspace_artifacts\runtime_state\longrun-supervisor'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$installRecord = [ordered]@{
    task_name = $TaskName
    workspace = $workspacePath
    interval_minutes = $IntervalMinutes
    max_run_minutes = $MaxRunMinutes
    installed_at = (Get-Date).ToString('o')
    runner = $runnerPath
    run_source = 'Scheduled'
}
Set-Content -LiteralPath (Join-Path $stateDir 'scheduled-task.json') -Value ($installRecord | ConvertTo-Json -Depth 8) -Encoding UTF8

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Interval minutes: $IntervalMinutes"
Write-Host "Runner: $runnerPath"
Write-Host "State: $stateDir"
