# spawn-watcher.ps1 — Background daemon. Polls .squad/spawn-queue/ every 2s
# for new order files; runs spawn-agent.ps1 per order; moves the order to
# processed/ or rejected/.
#
# Run in its own window:
#   .\tools\squad\spawn-watcher.ps1
#
# Order file format (json, drop under .squad/spawn-queue/):
#   {
#     "role": "tank",
#     "id": "tank",
#     "auto_start_claude": true,
#     "auto_slash": true,
#     "requested_by": "morpheus",
#     "reason": "need parallel test runner"
#   }

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'squad-guard.ps1')

$projectRoot = Get-ProjectRoot
$queueDir    = Join-Path $projectRoot '.squad\spawn-queue'
$doneDir     = Join-Path $queueDir 'processed'
$failDir     = Join-Path $queueDir 'rejected'
foreach ($d in @($queueDir, $doneDir, $failDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

Write-Host "[squad-watcher] watching $queueDir (Ctrl+C to stop)" -ForegroundColor Green
Write-GuardLog -Level INFO -Message 'spawn-watcher started' -Context @{ queue = $queueDir }

while ($true) {
    try {
        $orders = Get-ChildItem $queueDir -Filter '*.json' -File -ErrorAction SilentlyContinue
        foreach ($order in $orders) {
            $ts = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
            $baseName = [System.IO.Path]::GetFileNameWithoutExtension($order.Name)

            try {
                $raw  = Get-Content $order.FullName -Raw -ErrorAction Stop
                $data = $raw | ConvertFrom-Json -ErrorAction Stop
            } catch {
                Write-Host "[squad-watcher] malformed JSON: $($order.Name)" -ForegroundColor Red
                Write-GuardLog -Level WARN -Message 'Malformed order' -Context @{ file = $order.Name; err = "$_" }
                Move-Item $order.FullName (Join-Path $failDir "$baseName-$ts-malformed.json") -Force
                continue
            }

            $role = $data.role
            $id   = if ($data.PSObject.Properties['id'] -and $data.id) { $data.id } else { $role }
            $autoClaude = if ($data.PSObject.Properties['auto_start_claude']) { [bool]$data.auto_start_claude } else { $true }
            $autoSlash  = if ($data.PSObject.Properties['auto_slash']) { [bool]$data.auto_slash } else { $true }

            if (-not $role) {
                Write-Host "[squad-watcher] order missing 'role': $($order.Name)" -ForegroundColor Red
                Move-Item $order.FullName (Join-Path $failDir "$baseName-$ts-norole.json") -Force
                continue
            }

            Write-Host "[squad-watcher] spawning role=$role id=$id" -ForegroundColor Cyan
            try {
                & (Join-Path $PSScriptRoot 'spawn-agent.ps1') `
                    -Role $role `
                    -Id   $id `
                    -AutoStartClaude $autoClaude `
                    -AutoSlash       $autoSlash
                Move-Item $order.FullName (Join-Path $doneDir "$baseName-$ts.json") -Force
                Write-GuardLog -Level EXEC -Message 'Order processed' -Context @{ role = $role; id = $id; file = $order.Name }
            } catch {
                Write-Host "[squad-watcher] spawn failed: $_" -ForegroundColor Red
                Write-GuardLog -Level WARN -Message 'Spawn failed' -Context @{ role = $role; err = "$_" }
                Move-Item $order.FullName (Join-Path $failDir "$baseName-$ts-spawn-error.json") -Force
            }
        }
    } catch {
        Write-Host "[squad-watcher] loop error: $_" -ForegroundColor Red
        Write-GuardLog -Level WARN -Message 'Loop error' -Context @{ err = "$_" }
    }

    Start-Sleep -Seconds 2
}
