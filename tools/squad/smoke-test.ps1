# tools/squad/smoke-test.ps1
# Purpose: Scripted version of squad-doctor (DE5). Validates routing/agent/chatmodes/profile/prompts/skills/HR links.
# Created: 2026-04-27 as part of Squad 0.9.3-modular hardening.
#
# PowerShell 5 note:
#   Keep runtime string matches ASCII-only to avoid parser trouble when the file
#   is executed from a UTF-8-no-BOM checkout under Windows PowerShell.
[CmdletBinding()]
param(
    [string]$RepoRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Continue'
$results = New-Object System.Collections.ArrayList

function Add-Result {
    param([string]$Name, [bool]$Pass, [string]$Detail)
    [void]$results.Add([pscustomobject]@{ Check=$Name; Pass=$Pass; Detail=$Detail })
}

# Check 1: agent file
$agent = Join-Path $RepoRoot '.github/agents/squad.agent.md'
if (-not (Test-Path -LiteralPath $agent)) {
    Add-Result 'agent-file' $false "missing: $agent"
} else {
    $head = Get-Content -LiteralPath $agent -TotalCount 50 -ErrorAction SilentlyContinue
    $headText = $head -join "`n"
    $hasVersion = $headText -match 'version:\s*0\.9\.3-modular'
    $body = Get-Content -LiteralPath $agent -Raw -ErrorAction SilentlyContinue
    $hasSection = ($body -match 'You are \*\*Squad \(Coordinator\)\*\*') -or ($body -match 'Coordinator Identity')
    Add-Result 'agent-file' ($hasVersion -and $hasSection) "version=$hasVersion section=$hasSection"
}

# Check 2: routing rules
$routing = Join-Path $RepoRoot '.squad/routing.md'
if (-not (Test-Path -LiteralPath $routing)) {
    Add-Result 'routing-rules' $false "missing: $routing"
} else {
    $body = Get-Content -LiteralPath $routing -Raw -ErrorAction SilentlyContinue
    $ok = $body -match 'Coordinator Auto-Routing Rules'
    Add-Result 'routing-rules' $ok "auto-routing-section=$ok"
}

# Check 3: chatmodes
$chatDir = Join-Path $RepoRoot '.github/chatmodes'
if (-not (Test-Path -LiteralPath $chatDir)) {
    Add-Result 'chatmodes' $false "directory missing: $chatDir"
} else {
    $modes = Get-ChildItem -LiteralPath $chatDir -Filter '*.chatmode.md' -ErrorAction SilentlyContinue
    if ($modes.Count -eq 0) {
        Add-Result 'chatmodes' $false 'no .chatmode.md files'
    } else {
        $sample = Get-Content -LiteralPath $modes[0].FullName -TotalCount 1 -ErrorAction SilentlyContinue
        $hasFrontmatter = $sample -match '^---\s*$'
        Add-Result 'chatmodes' ($hasFrontmatter) "count=$($modes.Count) sample-frontmatter=$hasFrontmatter"
    }
}

# Check 4: profile (call profile-version-check.ps1 if present)
$pvc = Join-Path $RepoRoot 'tools/squad/profile-version-check.ps1'
if (-not (Test-Path -LiteralPath $pvc)) {
    Add-Result 'profile' $true 'profile-version-check.ps1 absent (suggestion only)'
} else {
    $stdout = & powershell -NoProfile -ExecutionPolicy Bypass -File $pvc 2>&1
    $exit = $LASTEXITCODE
    Add-Result 'profile' ($exit -eq 0) "exit=$exit out=$stdout"
}

# Check 5: prompt and skill split
$promptDir = Join-Path $RepoRoot '.github/prompts'
$skillDir = Join-Path $RepoRoot '.github/skills'
$squadPlanPrompt = Join-Path $promptDir 'squad-plan.prompt.md'
$squadDoctorPrompt = Join-Path $promptDir 'squad-doctor.prompt.md'
$squadRoundPrompt = Join-Path $promptDir 'squad-round.prompt.md'
$legacyPrompt = Join-Path $promptDir 'prompts.md'
$deprecatedPrompt = Join-Path $promptDir 'prompts.md.deprecated'
$startupSkill = Join-Path $skillDir 'squad-startup-packet/SKILL.md'
$handoffSkill = Join-Path $skillDir 'squad-cli-handoff/SKILL.md'
$promptSkillChecks = @(
    (Test-Path -LiteralPath $squadPlanPrompt),
    (Test-Path -LiteralPath $squadDoctorPrompt),
    (Test-Path -LiteralPath $squadRoundPrompt),
    (-not (Test-Path -LiteralPath $legacyPrompt)),
    (Test-Path -LiteralPath $deprecatedPrompt),
    (Test-Path -LiteralPath $startupSkill),
    (Test-Path -LiteralPath $handoffSkill)
)
$promptSkillOk = $promptSkillChecks -notcontains $false
Add-Result 'prompt-skill-split' $promptSkillOk "squad-plan=$($promptSkillChecks[0]) doctor=$($promptSkillChecks[1]) round=$($promptSkillChecks[2]) legacy-removed=$($promptSkillChecks[3]) deprecated=$($promptSkillChecks[4]) startup-skill=$($promptSkillChecks[5]) handoff-skill=$($promptSkillChecks[6])"

# Check 6: HR1-6 anchors
$claudeMd = Join-Path $RepoRoot 'CLAUDE.md'
if (-not (Test-Path -LiteralPath $claudeMd)) {
    Add-Result 'hr-anchors' $false "missing: $claudeMd"
} else {
    $body = Get-Content -LiteralPath $claudeMd -Raw -ErrorAction SilentlyContinue
    $hasAll = ('HR1','HR2','HR3','HR4','HR5','HR6' | ForEach-Object { $body -match $_ }) -notcontains $false
    $poolTool = Test-Path -LiteralPath (Join-Path $RepoRoot '.squad/tools/pool_append.py')
    Add-Result 'hr-anchors' ($hasAll -and $poolTool) "claude-hr-keywords=$hasAll pool-tool=$poolTool"
}

# Report
$passed = ($results | Where-Object Pass).Count
$total = $results.Count
$results | Format-Table -AutoSize | Out-String | Write-Output

if ($passed -eq $total) {
    Write-Output "SMOKE: OK ($passed/$total)"
    exit 0
}
[Console]::Error.WriteLine("SMOKE: FAIL ($passed/$total)")
exit 1
