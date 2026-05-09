# check-trail-size.tests.ps1 — sibling test for tools/squad/check-trail-size.ps1.
#
# Pester-free pwsh harness (matches the squad's existing .tests.ps1 convention):
# spawns the SUT as a child process per case so exit codes are real, not throws.
# Read-only against $PSScriptRoot. Writes only into $env:TEMP via New-TemporaryFile.
#
# Anchors:
#   - Round 25 brief 151208 self-explore virgin-axis (.ps1 lane saturated of
#     .py-side coverage; check-trail-size.ps1 had no test sibling).
#   - Spec §4.7: this checker is read-only (no atomic-write contract to assert)
#     but its 4-state exit-code contract (0/1/2/3) IS load-bearing for cron and
#     for the trail-archival.md trigger policy. Tests pin all four.
#   - Goal-drift §5 line 102: pass-rate trend predicate consumers eventually
#     read this checker's JSON envelope; the shape contract is therefore
#     downstream-relevant.
#
# Exit: 0 if all cases pass; non-zero on first failure.

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$SUT = Join-Path $PSScriptRoot 'check-trail-size.ps1'
if (-not (Test-Path -LiteralPath $SUT)) {
    Write-Error "SUT missing: $SUT"
    exit 99
}

$script:Failed = 0
$script:Passed = 0

function Assert-Equal {
    param($Expected, $Actual, [string]$Label)
    if ($Expected -ceq $Actual) {
        $script:Passed++
        Write-Host "  PASS $Label"
    } else {
        $script:Failed++
        Write-Host "  FAIL $Label : expected=[$Expected] actual=[$Actual]"
    }
}

function Assert-True {
    param([bool]$Cond, [string]$Label)
    if ($Cond) { $script:Passed++; Write-Host "  PASS $Label" }
    else       { $script:Failed++; Write-Host "  FAIL $Label" }
}

function Invoke-SUT {
    param([hashtable]$Params)
    $argList = @()
    foreach ($k in $Params.Keys) {
        $v = $Params[$k]
        if ($v -is [switch] -or ($v -is [bool] -and $v -eq $true)) {
            $argList += "-$k"
        } else {
            $argList += "-$k"; $argList += $v
        }
    }
    $stdout = & pwsh -NoProfile -File $SUT @argList 2>&1
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Stdout   = ($stdout | Out-String).TrimEnd()
    }
}

function New-TempTrail {
    param([int]$LineCount, [int]$LineLength)
    $f = New-TemporaryFile
    $sb = [System.Text.StringBuilder]::new()
    for ($i = 0; $i -lt $LineCount; $i++) {
        [void]$sb.AppendLine([string]::new('a', $LineLength))
    }
    [System.IO.File]::WriteAllText($f.FullName, $sb.ToString(), [System.Text.UTF8Encoding]::new($false))
    return $f.FullName
}

Write-Host "[check-trail-size.tests] SUT = $SUT"

# Case 1: missing trail → exit 3 + 'TRAIL_MISSING'
Write-Host "Case 1: missing trail file"
$missing = Join-Path ([System.IO.Path]::GetTempPath()) ("does_not_exist_" + [guid]::NewGuid().ToString() + ".md")
$r = Invoke-SUT -Params @{ TrailPath = $missing }
Assert-Equal 3 $r.ExitCode "exit code = 3"
Assert-True ($r.Stdout -match 'TRAIL_MISSING') "stdout contains TRAIL_MISSING"

# Case 2: tiny trail → exit 0 (safe)
Write-Host "Case 2: tiny trail = safe"
$tinyPath = New-TempTrail -LineCount 5 -LineLength 20  # ~100 chars → ~25 tokens
try {
    $r = Invoke-SUT -Params @{ TrailPath = $tinyPath }
    Assert-Equal 0 $r.ExitCode "tiny → exit 0"
    Assert-True ($r.Stdout -match 'status=safe') "stdout status=safe"
    Assert-True ($r.Stdout -match 'tokens_est=') "stdout has tokens_est"
} finally { Remove-Item -LiteralPath $tinyPath -Force -ErrorAction SilentlyContinue }

# Case 3: warn threshold crossed → exit 1
Write-Host "Case 3: warn threshold crossed"
# WarnTokens=10, FailTokens=100, CharsPerToken=4. We need tokens_est in [10,100):
# chars in [40, 400). 50 lines of 4 chars = 200 chars → 50 tokens → warn.
$warnPath = New-TempTrail -LineCount 50 -LineLength 4
try {
    $r = Invoke-SUT -Params @{ TrailPath = $warnPath; WarnTokens = 10; FailTokens = 100; CharsPerToken = 4 }
    Assert-Equal 1 $r.ExitCode "warn → exit 1"
    Assert-True ($r.Stdout -match 'status=warn') "stdout status=warn"
} finally { Remove-Item -LiteralPath $warnPath -Force -ErrorAction SilentlyContinue }

# Case 4: fail threshold crossed → exit 2
Write-Host "Case 4: fail threshold crossed"
# WarnTokens=5, FailTokens=10, CharsPerToken=4. 50 lines of 4 chars = 50 tokens >= 10 → fail.
$failPath = New-TempTrail -LineCount 50 -LineLength 4
try {
    $r = Invoke-SUT -Params @{ TrailPath = $failPath; WarnTokens = 5; FailTokens = 10; CharsPerToken = 4 }
    Assert-Equal 2 $r.ExitCode "fail → exit 2"
    Assert-True ($r.Stdout -match 'status=fail') "stdout status=fail"
} finally { Remove-Item -LiteralPath $failPath -Force -ErrorAction SilentlyContinue }

# Case 5: -Json on missing trail emits compact JSON with exitCode=3
Write-Host "Case 5: JSON shape — missing trail"
$r = Invoke-SUT -Params @{ TrailPath = $missing; Json = $true }
Assert-Equal 3 $r.ExitCode "json missing → exit 3"
$obj = $null
try { $obj = $r.Stdout | ConvertFrom-Json } catch { }
Assert-True ($null -ne $obj) "stdout parses as JSON"
if ($obj) {
    Assert-Equal 'missing' $obj.status "json status=missing"
    Assert-Equal 3 $obj.exitCode "json exitCode=3"
}

# Case 6: -Json on valid trail emits full envelope keys
Write-Host "Case 6: JSON shape — valid trail"
$validPath = New-TempTrail -LineCount 5 -LineLength 20
try {
    $r = Invoke-SUT -Params @{ TrailPath = $validPath; Json = $true }
    Assert-Equal 0 $r.ExitCode "json safe → exit 0"
    $obj = $r.Stdout | ConvertFrom-Json
    foreach ($k in @('status','path','bytes','lines','chars','tokensEst',
                     'charsPerToken','warnTokens','failTokens',
                     'claude200k','gpt4o128k','mtime','exitCode')) {
        Assert-True ($null -ne $obj.PSObject.Properties[$k]) "json has key '$k'"
    }
    Assert-Equal 5 $obj.lines "json lines=5"
    Assert-Equal 'safe' $obj.status "json status=safe"
    Assert-Equal 'fits' $obj.claude200k "json claude200k=fits for tiny trail"
} finally { Remove-Item -LiteralPath $validPath -Force -ErrorAction SilentlyContinue }

# Case 7: CharsPerToken parameter actually drives the estimate
Write-Host "Case 7: CharsPerToken affects tokensEst"
$cptPath = New-TempTrail -LineCount 10 -LineLength 40  # 400 chars
try {
    $r1 = Invoke-SUT -Params @{ TrailPath = $cptPath; Json = $true; CharsPerToken = 4 }
    $r2 = Invoke-SUT -Params @{ TrailPath = $cptPath; Json = $true; CharsPerToken = 8 }
    $o1 = $r1.Stdout | ConvertFrom-Json
    $o2 = $r2.Stdout | ConvertFrom-Json
    Assert-True ($o1.tokensEst -gt $o2.tokensEst) "smaller chars/token → larger token estimate"
    Assert-Equal 100 $o1.tokensEst "400 chars / 4 = 100 tokens"
    Assert-Equal 50  $o2.tokensEst "400 chars / 8 = 50 tokens"
} finally { Remove-Item -LiteralPath $cptPath -Force -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "[check-trail-size.tests] passed=$($script:Passed) failed=$($script:Failed)"
if ($script:Failed -gt 0) { exit 1 } else { exit 0 }
