Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-MemoryAudit {
    param([string]$RepoRoot)

    $memDir       = Join-Path $RepoRoot '.squad\memory'
    $blockersPath = Join-Path $RepoRoot '.squad\state\blockers.jsonl'
    $poolPath     = Join-Path $RepoRoot '.squad\state\pool.jsonl'

    $failed = $false

    # ---- SESSION_SNAPSHOT.md ----
    $snapshotPath = Join-Path $memDir 'SESSION_SNAPSHOT.md'
    if (-not (Test-Path $snapshotPath)) {
        Write-Host "[FAIL] SESSION_SNAPSHOT.md not found at: $snapshotPath" -ForegroundColor Red
        $failed = $true
    } else {
        $content = Get-Content -LiteralPath $snapshotPath -Raw
        foreach ($section in @('## Next', '## Facts', '## Decisions', '## Open')) {
            if ($content -notmatch [regex]::Escape($section)) {
                Write-Host "[FAIL] SESSION_SNAPSHOT.md missing required section: $section" -ForegroundColor Red
                $failed = $true
            }
        }
        if (-not $failed) {
            Write-Host "[OK]   SESSION_SNAPSHOT.md has all required sections." -ForegroundColor Green
        }
    }

    # ---- DECISION_TRAIL.md ----
    $trailPath = Join-Path $memDir 'DECISION_TRAIL.md'
    if (-not (Test-Path $trailPath)) {
        Write-Host "[FAIL] DECISION_TRAIL.md not found at: $trailPath" -ForegroundColor Red
        $failed = $true
    } else {
        $lines = Get-Content -LiteralPath $trailPath
        $decisionLines = @($lines | Where-Object { $_ -match '^##\s' -or $_ -match '^###\s' })
        $missingEvidence = 0
        $trailContent = Get-Content -LiteralPath $trailPath -Raw
        # Evidence anchors: [file:L14], [file.md], (file.md line 14)
        $evidencePattern = '\[[\w./-]+(?::L\d+)?\]|\([\w./-]+ line \d+\)'
        # Check overall file has at least one evidence anchor if it's not empty
        if ($trailContent.Trim() -ne '' -and $trailContent -notmatch $evidencePattern) {
            Write-Host "[WARN] DECISION_TRAIL.md: no evidence anchors found (expected [file.md] or [file:L14] format)." -ForegroundColor Yellow
        } else {
            Write-Host "[OK]   DECISION_TRAIL.md readable." -ForegroundColor Green
        }
    }

    # ---- OPEN_THREADS.md ----
    $threadsPath = Join-Path $memDir 'OPEN_THREADS.md'
    if (-not (Test-Path $threadsPath)) {
        Write-Host "[FAIL] OPEN_THREADS.md not found at: $threadsPath" -ForegroundColor Red
        $failed = $true
    } else {
        $content = Get-Content -LiteralPath $threadsPath -Raw
        # Look for BLK-NNN references and verify they exist in blockers.jsonl
        $blkRefs = [regex]::Matches($content, 'BLK-\d{3}')
        $blockerIds = @{}
        if (Test-Path $blockersPath) {
            . (Join-Path (Split-Path $PSScriptRoot -Parent) 'lib\jsonl.ps1')
            $allBlockers = Read-JsonlFile -Path $blockersPath
            foreach ($b in $allBlockers) { $blockerIds[$b.id] = $true }
        }
        $orphaned = @()
        foreach ($ref in $blkRefs) {
            if (-not $blockerIds.ContainsKey($ref.Value)) {
                $orphaned += $ref.Value
            }
        }
        if ($orphaned.Count -gt 0) {
            Write-Host "[WARN] OPEN_THREADS.md references blockers not in blockers.jsonl: $($orphaned -join ', ')" -ForegroundColor Yellow
        } else {
            Write-Host "[OK]   OPEN_THREADS.md blocker references validated." -ForegroundColor Green
        }
    }

    # ---- TEAM_MEMORY.md ----
    $teamPath = Join-Path $memDir 'TEAM_MEMORY.md'
    if (-not (Test-Path $teamPath)) {
        Write-Host "[FAIL] TEAM_MEMORY.md not found at: $teamPath" -ForegroundColor Red
        $failed = $true
    } else {
        $content = Get-Content -LiteralPath $teamPath -Raw
        if ([string]::IsNullOrWhiteSpace($content)) {
            Write-Host "[WARN] TEAM_MEMORY.md exists but is empty." -ForegroundColor Yellow
        } else {
            Write-Host "[OK]   TEAM_MEMORY.md readable and non-empty." -ForegroundColor Green
        }
    }

    if ($failed) {
        exit 1
    }
    exit 0
}
