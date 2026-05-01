# check-eval-schema.ps1 — eval JSON structural validator (goal-drift §5 L100, round-5 self-apply)
#
# Sibling of check-eval-cadence.ps1 + check-eval-trajectory.ps1. Validates that
# each .squad/evaluations/run-*.json carries the 5 required per-question fields
# specified by goal-drift §5 line 100:
#   "tools/squad/run-rag-once.ps1 产出的 .squad/evaluations/run-<ts>.json
#    必须包含：请求、响应、耗时、错误堆栈、引用数"
#
# Mapping (Chinese label -> JSON field on questions[i]):
#   请求         -> question
#   响应         -> response_text
#   耗时         -> elapsed_ms
#   错误堆栈     -> traceback
#   引用数       -> citation_count
#
# Note: this is a STRUCTURAL check (field-presence), not a semantic check.
# Rubric-based pass/fail evaluation is owned by check-eval-rubric.py (separate
# concern). A field may be present with value=null (e.g. response_text=null on
# 503 failures); presence is what L100 demands so downstream consumers can
# rely on a stable shape.
#
# Verdicts (status field):
#   compliant     all 5 fields present on every questions[i] of newest run
#   violations    >=1 missing field on >=1 question
#   empty         no run-*.json present
#   unparseable   newest run-*.json failed to parse
#
# Exit code:
#   0 = compliant
#   2 = violations
#   3 = empty
#   4 = unparseable
#
# Pure read. No product touch. No my-project/ touch. No creds. No spawn.

[CmdletBinding()]
param(
    [string]$EvalDir = '',
    [string]$RunFile = '',
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

$scriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if ($EvalDir -eq '') {
    $EvalDir = Join-Path $scriptRoot '..\..\.squad\evaluations'
}

$Required = @('question', 'response_text', 'elapsed_ms', 'traceback', 'citation_count')

$target = $null
if ($RunFile -ne '') {
    $cand = if (Test-Path -LiteralPath $RunFile) {
        Get-Item -LiteralPath $RunFile
    } elseif (Test-Path -LiteralPath $EvalDir) {
        Get-Item -LiteralPath (Join-Path $EvalDir $RunFile) -ErrorAction SilentlyContinue
    } else {
        $null
    }
    if ($null -eq $cand) {
        if ($Json) { @{ status = 'empty'; requested = $RunFile } | ConvertTo-Json -Compress }
        else { Write-Output "EVAL-SCHEMA empty requested=$RunFile" }
        exit 3
    }
    $target = $cand
} else {
    if (-not (Test-Path -LiteralPath $EvalDir)) {
        if ($Json) { @{ status = 'empty'; eval_dir = $EvalDir } | ConvertTo-Json -Compress }
        else { Write-Output "EVAL-SCHEMA empty dir=$EvalDir" }
        exit 3
    }
    $target = Get-ChildItem -LiteralPath $EvalDir -Filter 'run-*.json' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

if (-not $target) {
    if ($Json) { @{ status = 'empty'; eval_dir = $EvalDir } | ConvertTo-Json -Compress }
    else { Write-Output "EVAL-SCHEMA empty dir=$EvalDir pattern=run-*.json" }
    exit 3
}

try {
    $d = Get-Content -LiteralPath $target.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    if ($Json) { @{ status = 'unparseable'; file = $target.Name; error = "$_" } | ConvertTo-Json -Compress }
    else { Write-Output "EVAL-SCHEMA unparseable file=$($target.Name)" }
    exit 4
}

$qs = @()
if ($null -ne $d.questions) { $qs = @($d.questions) }

$violations = @()
$idx = 0
foreach ($q in $qs) {
    $missing = @()
    foreach ($f in $Required) {
        # PSCustomObject from ConvertFrom-Json: missing field has $null value
        # AND no member; presence test = NoteProperty exists.
        $hasMember = $false
        if ($null -ne $q.PSObject) {
            $hasMember = ($q.PSObject.Properties.Name -contains $f)
        }
        if (-not $hasMember) { $missing += $f }
    }
    if ($missing.Count -gt 0) {
        $violations += [pscustomobject]@{ index = $idx; missing = $missing }
    }
    $idx++
}

$status = if ($violations.Count -eq 0 -and $qs.Count -gt 0) { 'compliant' }
          elseif ($qs.Count -eq 0) { 'violations' }
          else { 'violations' }

if ($Json) {
    @{
        status      = $status
        file        = $target.Name
        question_count = $qs.Count
        required    = $Required
        violations  = @($violations | ForEach-Object { @{ index = $_.index; missing = @($_.missing) } })
    } | ConvertTo-Json -Compress -Depth 5
} else {
    if ($status -eq 'compliant') {
        Write-Output "EVAL-SCHEMA compliant file=$($target.Name) questions=$($qs.Count) required=$($Required.Count)"
    } else {
        $vsum = ($violations | ForEach-Object { "q$($_.index)[$($_.missing -join '+')]" }) -join ','
        if ($qs.Count -eq 0) { $vsum = 'no-questions-array' }
        Write-Output "EVAL-SCHEMA violations file=$($target.Name) questions=$($qs.Count) details=$vsum"
    }
}

if ($status -eq 'violations') { exit 2 } else { exit 0 }
