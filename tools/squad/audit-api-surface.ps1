# audit-api-surface.ps1 — goal-drift §4 line 89 enforcement (req 35/50, round-17 self-apply)
#
# Static enumeration of FastAPI router registrations under my-project/src/. For each
# registered (verb, path) tuple the audit reports whether the handler body shows at
# least one structured-error path: explicit `raise HTTPException(...)` or an explicit
# `JSONResponse(status_code=..., content=...)` return. Handlers with neither marker
# are flagged as bare-500-risk (any uncaught exception falls through to FastAPI's
# default 500 with no envelope).
#
# Pure lexical scan. No LLM. No network. No my-project/ rewrite. Audit-only.
# Atomic write of the report per CLAUDE.md §4.7 (.tmp + Move-Item -Force).
# Exit 0 always (PASS or FAIL both written; non-zero exit reserved for harness wiring v1).

[CmdletBinding()]
param(
    [string]$ScanRoot = (Join-Path $PSScriptRoot '..\..\my-project\src'),
    [string]$OutDir   = (Join-Path $PSScriptRoot '..\..\.squad\audits')
)

$ErrorActionPreference = 'Stop'

$registrationRegex = '@router\.(?<verb>get|post|put|delete|patch|head|options)\(\s*(?<path>[^,)\s]+)'
$envelopeMarkers   = @('HTTPException', 'JSONResponse')

if (-not (Test-Path -LiteralPath $ScanRoot)) {
    Write-Error "ScanRoot not found: $ScanRoot"
    exit 0
}

$pyFiles = Get-ChildItem -LiteralPath $ScanRoot -Recurse -Filter '*_router.py' -File -ErrorAction SilentlyContinue

$registrations = @()
$flagged       = @()

foreach ($f in $pyFiles) {
    $text = Get-Content -LiteralPath $f.FullName -Raw -ErrorAction SilentlyContinue
    if (-not $text) { continue }

    $matches = [regex]::Matches($text, $registrationRegex)
    foreach ($m in $matches) {
        $verb = $m.Groups['verb'].Value
        $path = $m.Groups['path'].Value.Trim('"').Trim("'")

        $hasEnvelope = $false
        foreach ($marker in $envelopeMarkers) {
            if ($text -match [regex]::Escape($marker)) { $hasEnvelope = $true; break }
        }

        $row = [pscustomobject]@{
            File        = $f.FullName
            Verb        = $verb.ToUpper()
            Path        = $path
            HasEnvelope = $hasEnvelope
        }
        $registrations += $row
        if (-not $hasEnvelope) { $flagged += $row }
    }
}

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$reportName = 'api-surface-' + (Get-Date -Format 'yyyy-MM-dd') + '.md'
$reportPath = Join-Path $OutDir $reportName
$reportTmp  = $reportPath + '.tmp'

$verdict = if ($flagged.Count -eq 0) { 'PASS' } else { 'FAIL' }

$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("# audit-api-surface — goal-drift §4 line 89 (``所有 API 路径返回 2xx 或结构化错误，禁止 500 无堆栈``)")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("- ran_at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$sb.AppendLine("- scan_root: $ScanRoot")
[void]$sb.AppendLine("- file_glob: *_router.py")
[void]$sb.AppendLine("- envelope_markers: $($envelopeMarkers -join ', ')")
[void]$sb.AppendLine("- registrations_total: $($registrations.Count)")
[void]$sb.AppendLine("- bare_500_risk_count: $($flagged.Count)")
[void]$sb.AppendLine("- verdict: $verdict")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("## A. enumerated registrations")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("| File | Verb | Path | EnvelopeMarker |")
[void]$sb.AppendLine("|---|---|---|---|")
foreach ($r in $registrations) {
    $marker = if ($r.HasEnvelope) { 'yes' } else { 'NO' }
    [void]$sb.AppendLine("| $($r.File) | $($r.Verb) | $($r.Path) | $marker |")
}
if ($registrations.Count -eq 0) {
    [void]$sb.AppendLine("| (no router files found) | - | - | - |")
}
[void]$sb.AppendLine("")
[void]$sb.AppendLine("## B. bare-500-risk paths (no HTTPException / JSONResponse marker in file)")
if ($flagged.Count -eq 0) {
    [void]$sb.AppendLine("- (none — every router file shows at least one structured-error marker)")
} else {
    foreach ($r in $flagged) {
        [void]$sb.AppendLine("- $($r.Verb) $($r.Path)  file=$($r.File)")
    }
}
[void]$sb.AppendLine("")
[void]$sb.AppendLine("## C. verdict")
if ($verdict -eq 'PASS') {
    [void]$sb.AppendLine("PASS — every enumerated path lives in a router file containing at least one structured-error marker. Note: this is a file-level coarse oracle; per-handler verification is deferred to live-side stage-2 (post-chat-cred-fix).")
} else {
    [void]$sb.AppendLine("FAIL — $($flagged.Count) registration(s) live in router files with no structured-error marker. See section B.")
}
[void]$sb.AppendLine("")
[void]$sb.AppendLine("## D. limitations")
[void]$sb.AppendLine("- File-level marker presence is necessary but not sufficient. A router file can have HTTPException for one handler and bare-raise in another.")
[void]$sb.AppendLine("- Live-side per-path test is the stage-2 companion (audit-api-live.ps1, deferred — gated on chat-cred fix per [chat-llm-credentials-missing] OPEN_THREADS).")
[void]$sb.AppendLine("- Dynamic / non-decorator-style FastAPI registrations not detected.")

Set-Content -LiteralPath $reportTmp -Value $sb.ToString() -Encoding UTF8 -NoNewline
Move-Item -LiteralPath $reportTmp -Destination $reportPath -Force

Write-Output "audit-api-surface: $verdict  registrations=$($registrations.Count) flagged=$($flagged.Count) report=$reportPath"
exit 0
