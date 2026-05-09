# audit-no-bare-http-to-llm.ps1 — goal-drift §4 line 90 enforcement (req 40/50, round-7 self-apply)
#
# Scans my-project/src/**/*.py for files that BOTH (a) import an HTTP client lib
# AND (b) contain a hardcoded LLM-host cue string. The single canonical exception
# is litellm_gateway.py (the designated chokepoint per round-2 reclassification).
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

$httpImportRegex = '^\s*(import|from)\s+(httpx|requests|urllib|aiohttp)\b'
$llmHostCues = @(
    'api.openai.com',
    'api.anthropic.com',
    'ark.cn-beijing.volces.com',
    'volcengineapi.com',
    'localhost:11434',
    '127.0.0.1:11434',
    'api.deepseek.com',
    'dashscope.aliyuncs.com'
)
$allowlistFiles = @('litellm_gateway.py')

if (-not (Test-Path -LiteralPath $ScanRoot)) {
    Write-Error "ScanRoot not found: $ScanRoot"
    exit 0
}

$pyFiles = Get-ChildItem -LiteralPath $ScanRoot -Recurse -Filter '*.py' -File -ErrorAction SilentlyContinue

$importers = @()
$flagged   = @()

foreach ($f in $pyFiles) {
    $text = Get-Content -LiteralPath $f.FullName -Raw -ErrorAction SilentlyContinue
    if (-not $text) { continue }

    $hasImport = ($text -split "`n") | Where-Object { $_ -match $httpImportRegex } | Select-Object -First 1
    if (-not $hasImport) { continue }
    $importers += $f.FullName

    $hostHits = @()
    foreach ($cue in $llmHostCues) {
        if ($text -match [regex]::Escape($cue)) { $hostHits += $cue }
    }
    if ($hostHits.Count -eq 0) { continue }

    $isTest = ($f.Name -like 'test_*.py') -or ($f.Name -eq 'conftest.py')
    if ($allowlistFiles -contains $f.Name) { continue }
    if ($isTest) { continue }

    $flagged += [pscustomobject]@{
        File  = $f.FullName
        Cues  = ($hostHits -join ', ')
    }
}

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$reportName = 'no-bare-http-' + (Get-Date -Format 'yyyy-MM-dd') + '.md'
$reportPath = Join-Path $OutDir $reportName
$reportTmp  = $reportPath + '.tmp'

$verdict = if ($flagged.Count -eq 0) { 'PASS' } else { 'FAIL' }

$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("# audit-no-bare-http-to-llm — goal-drift §4 line 90 (`所有模型调用走 model_call_gateway，无裸 HTTP`)")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("- ran_at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$sb.AppendLine("- scan_root: $ScanRoot")
[void]$sb.AppendLine("- allowlist: $($allowlistFiles -join ', ')")
[void]$sb.AppendLine("- verdict: $verdict")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("## A. importers (files importing httpx/requests/urllib/aiohttp)")
foreach ($p in $importers) { [void]$sb.AppendLine("- $p") }
if ($importers.Count -eq 0) { [void]$sb.AppendLine("- (none)") }
[void]$sb.AppendLine("")
[void]$sb.AppendLine("## B. importers ALSO containing an LLM-host cue string")
if ($flagged.Count -eq 0) {
    [void]$sb.AppendLine("- (none — gateway monopoly invariant holds for non-allowlisted, non-test files)")
} else {
    foreach ($row in $flagged) {
        [void]$sb.AppendLine("- $($row.File)  cues=[$($row.Cues)]")
    }
}
[void]$sb.AppendLine("")
[void]$sb.AppendLine("## C. verdict")
if ($verdict -eq 'PASS') {
    [void]$sb.AppendLine("PASS — no 裸 HTTP to LLM hosts detected outside allowlist.")
} else {
    [void]$sb.AppendLine("FAIL — 裸 HTTP detected. See section B for offending files.")
}

Set-Content -LiteralPath $reportTmp -Value $sb.ToString() -Encoding UTF8 -NoNewline
Move-Item -LiteralPath $reportTmp -Destination $reportPath -Force

Write-Output "audit-no-bare-http: $verdict  importers=$($importers.Count) flagged=$($flagged.Count) report=$reportPath"
exit 0
