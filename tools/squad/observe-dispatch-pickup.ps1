# observe-dispatch-pickup.ps1 — passive read-only observer of dispatched-task pickup latency
#
# Spec: .squad/identity/requirement-pool.md "[2026-04-25 09:07 round-8] dispatched-task-pickup-latency-observer" (43/50)
# Owner: morpheus self-shipped round 10 (2026-04-25)
#
# Hard guardrails:
#   - READ-ONLY across `squad task list`, file mtimes, Test-Path probes
#   - DO NOT mutate any task body / status
#   - DO NOT spawn agents / call LLMs
#   - Atomic write of verdict file (.tmp + Move-Item -Force) per CLAUDE.md §4.7
#
# Behavior:
#   1. Run `squad task list` and parse {id, title, assigned_to, status, created_by} blocks.
#   2. For tasks with status=queued, derive an "expected disk anchor" from the body:
#        regex first match of `tools/squad/[^\s,;)]+|\.squad/[^\s,;)]+|my-project/src/[^\s,;)]+`
#   3. Test-Path each anchor; record exists True/False.
#   4. Atomic-write .squad/diagnostics/dispatch-pickup-<ts>.md with one row per queued task.
#   5. Exit 0 always (advisory).

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$outFile = Join-Path $repoRoot ".squad/diagnostics/dispatch-pickup-$ts.md"
$tmpFile = "$outFile.tmp"

# 1. Capture squad task list output (text mode; --json not assumed available)
$raw = & squad task list 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: squad task list exit=$LASTEXITCODE — emitting empty verdict"
    $raw = ''
}

# 2. Parse text blocks. Each block starts with `[task <uuid>] <status>` line.
$blocks = [regex]::Split($raw, '(?m)^\[task ') | Where-Object { $_ -match '^\s*[0-9a-f]{8}-' }

$rows = New-Object System.Collections.ArrayList

foreach ($block in $blocks) {
    $idMatch = [regex]::Match($block, '^([0-9a-f-]{36})\]\s+(\w+)')
    if (-not $idMatch.Success) { continue }
    $id = $idMatch.Groups[1].Value
    $status = $idMatch.Groups[2].Value
    if ($status -ne 'queued') { continue }

    $assignedMatch = [regex]::Match($block, '(?m)^\s*assigned_to:\s*(\S+)')
    $assigned = if ($assignedMatch.Success) { $assignedMatch.Groups[1].Value } else { '?' }

    $titleMatch = [regex]::Match($block, '(?m)^\s*title:\s*(.+)$')
    $title = if ($titleMatch.Success) { $titleMatch.Groups[1].Value.Trim() } else { '?' }

    # Derive expected anchor from body text — first repo-relative path mention
    $anchorMatch = [regex]::Match($block, '(tools/squad/[^\s,;)`]+|\.squad/[^\s,;)`]+|my-project/src/[^\s,;)`]+)')
    $anchor = if ($anchorMatch.Success) { $anchorMatch.Groups[1].Value.TrimEnd('.', ',', ';') } else { '(no anchor)' }

    $exists = if ($anchor -ne '(no anchor)') { Test-Path (Join-Path $repoRoot $anchor) } else { $false }

    [void]$rows.Add([pscustomobject]@{
        id       = $id.Substring(0, 8)
        assigned = $assigned
        anchor   = $anchor
        exists   = $exists
        title    = if ($title.Length -gt 60) { $title.Substring(0, 57) + '...' } else { $title }
    })
}

# 3. Build markdown report
$lines = New-Object System.Collections.ArrayList
[void]$lines.Add("# dispatch-pickup observer — $ts")
[void]$lines.Add('')
[void]$lines.Add("- repo: ``$repoRoot``")
[void]$lines.Add("- queued tasks observed: $($rows.Count)")
[void]$lines.Add("- with-disk-anchor: $(($rows | Where-Object { $_.anchor -ne '(no anchor)' }).Count)")
[void]$lines.Add("- anchor-exists=True: $(($rows | Where-Object { $_.exists }).Count)")
[void]$lines.Add("- anchor-exists=False: $(($rows | Where-Object { -not $_.exists -and $_.anchor -ne '(no anchor)' }).Count)")
[void]$lines.Add('')
[void]$lines.Add('| id8 | assigned | exists | anchor | title |')
[void]$lines.Add('|---|---|---|---|---|')
foreach ($r in $rows) {
    [void]$lines.Add("| $($r.id) | $($r.assigned) | $($r.exists) | ``$($r.anchor)`` | $($r.title) |")
}
[void]$lines.Add('')
[void]$lines.Add('Notes: anchor heuristic = first regex match of `tools/squad/...`, `.squad/...`, or `my-project/src/...` in task body. False positives possible (anchor mentioned but not the deliverable). Read-only; advisory.')

# 4. Atomic write
$content = $lines -join "`n"
Set-Content -Path $tmpFile -Value $content -Encoding UTF8 -NoNewline
Move-Item -Path $tmpFile -Destination $outFile -Force

Write-Host "OK: wrote $outFile ($($rows.Count) queued rows)"
exit 0
