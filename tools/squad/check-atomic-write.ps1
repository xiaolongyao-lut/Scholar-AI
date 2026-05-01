# check-atomic-write.ps1 — atomic-write compliance auditor (goal-drift §4 L91, round-6 self-apply)
#
# Sibling of check-eval-cadence.ps1 / check-eval-trajectory.ps1 / check-eval-schema.ps1
# and audit-no-bare-http-to-llm.ps1 (the L92 precedent that ticks goal-drift §4).
#
# Re-runs the static audit in .squad/audits/atomic-write-audit-2026-04-25.md
# but anchors by CONTENT PATTERN, not line number — line numbers drifted
# during the 2026-04-26 morpheus-headless / spawn-agent refactor, making the
# static audit partially out-of-date.
#
# Originally-flagged P1 callsites (audit 2026-04-25 §P1, entries 7,8,9,10,12,13):
#   1. tools/squad/lib/config.ps1                — `$cfg | ConvertTo-Json | Set-Content -LiteralPath $path`
#   2. tools/squad/spawn-agent.ps1               — `Set-Content -Path $markerFile` (formerly line 96)
#   3. tools/squad/spawn-agent.ps1               — `$marker | ConvertTo-Json | Set-Content -Path $markerFile` (formerly 108)
#   4. tools/squad/morpheus-headless.ps1         — `Set-Content -Path $sessIdFile` (formerly line 91)
#   5. tools/squad/morpheus-headless.ps1         — `Set-Content -Path $sessSeeded` (formerly line 275)
#   6. tools/squad/commands/spawn.ps1            — `Set-Content -Path $auditFile`
#
# A callsite is COMPLIANT if it writes to a `.tmp` (`$markerTmp`, `"$X.tmp"`,
# etc.) and Move-Item to the final destination, OR if the original signature
# is no longer present (refactored away). VIOLATING if the original final-name
# Set-Content is still present without `.tmp` companion.
#
# Verdicts emitted in summary line:
#   compliant     all 6 callsites no longer violate
#   violations    >=1 still violates
#
# Exit code:
#   0 = compliant
#   2 = violations
#
# Pure read. No product touch. No my-project/ touch. No creds. No spawn.

[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

# Each rule:
#   file       = path relative to repo root
#   violating  = regex that, if matched on a line, is the legacy violation signature
#   compliant  = regex that, if matched on the same line, indicates the .tmp form (i.e. NOT a violation)
# A file is VIOLATING if it has any line matching `violating` AND NOT matching `compliant`.
$rules = @(
    @{
        id        = 'config-json'
        file      = 'tools/squad/lib/config.ps1'
        violating = 'Set-Content\s+-LiteralPath\s+\$path\b(?!.*\.tmp)'
        compliant = 'Set-Content\s+-LiteralPath\s+\$\w*[Tt]mp\b'
    },
    @{
        id        = 'spawn-agent-marker-1'
        file      = 'tools/squad/spawn-agent.ps1'
        violating = 'Set-Content\s+-Path\s+\$markerFile\b'
        compliant = 'Set-Content\s+-Path\s+\$markerTmp\b'
    },
    @{
        id        = 'spawn-agent-marker-2'
        file      = 'tools/squad/spawn-agent.ps1'
        violating = 'ConvertTo-Json\s*\|\s*Set-Content\s+-Path\s+\$markerFile\b'
        compliant = 'ConvertTo-Json\s*\|\s*Set-Content\s+-Path\s+\$markerTmp\b'
    },
    @{
        id        = 'morpheus-sess-id'
        file      = 'tools/squad/morpheus-headless.ps1'
        violating = 'Set-Content\s+-Path\s+\$sessIdFile\b'
        compliant = 'Set-Content\s+-Path\s+\$sessIdTmp\b'
    },
    @{
        id        = 'morpheus-sess-seeded'
        file      = 'tools/squad/morpheus-headless.ps1'
        violating = 'Set-Content\s+-Path\s+\$sessSeeded\b'
        compliant = 'Set-Content\s+-Path\s+\$sessSeededTmp\b'
    },
    @{
        id        = 'commands-spawn-audit'
        file      = 'tools/squad/commands/spawn.ps1'
        violating = 'Set-Content\s+-Path\s+\$auditFile\b'
        compliant = 'Set-Content\s+-Path\s+\$auditFileTmp\b'
    }
)

$results = @()
foreach ($r in $rules) {
    $abs = Join-Path $RepoRoot $r.file
    $entry = [ordered]@{
        id        = $r.id
        file      = $r.file
        verdict   = 'compliant'
        violating_lines = @()
        note      = ''
    }
    if (-not (Test-Path -LiteralPath $abs)) {
        $entry.verdict = 'compliant'
        $entry.note    = 'file-missing-or-renamed'
        $results += [pscustomobject]$entry
        continue
    }
    $lines = Get-Content -LiteralPath $abs -Encoding UTF8
    $hits = @()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line -match $r.violating -and $line -notmatch $r.compliant) {
            $hits += [pscustomobject]@{ line = ($i + 1); text = $line.Trim() }
        }
    }
    if ($hits.Count -gt 0) {
        $entry.verdict = 'violating'
        $entry.violating_lines = @($hits)
    } else {
        # Try to detect that the .tmp pattern is now in use (gives us "fixed" vs "removed")
        $hasTmp = $false
        foreach ($l in $lines) { if ($l -match $r.compliant) { $hasTmp = $true; break } }
        $entry.note = if ($hasTmp) { 'fixed-tmp-then-move' } else { 'pattern-no-longer-present' }
    }
    $results += [pscustomobject]$entry
}

$violatingCount = ($results | Where-Object { $_.verdict -eq 'violating' }).Count
$status = if ($violatingCount -eq 0) { 'compliant' } else { 'violations' }

if ($Json) {
    @{
        status      = $status
        rule_count  = $rules.Count
        violating   = $violatingCount
        results     = @($results | ForEach-Object {
            @{
                id              = $_.id
                file            = $_.file
                verdict         = $_.verdict
                note            = $_.note
                violating_lines = @($_.violating_lines | ForEach-Object { @{ line = $_.line; text = $_.text } })
            }
        })
    } | ConvertTo-Json -Compress -Depth 6
} else {
    $sum = ($results | ForEach-Object {
        $tag = if ($_.verdict -eq 'violating') { "$($_.id)@$(($_.violating_lines | ForEach-Object { $_.line }) -join ',')" } else { "$($_.id)=$($_.note)" }
        $tag
    }) -join ';'
    Write-Output "ATOMIC-WRITE $status rules=$($rules.Count) violating=$violatingCount detail=$sum"
}

if ($status -eq 'violations') { exit 2 } else { exit 0 }
