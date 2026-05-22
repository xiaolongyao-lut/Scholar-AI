# -*- ps1: build Literature Assistant Windows onedir bundle ---------------
# Reference: docs/plans/runbooks/windows-exe-release-standard.md
#
# Slice A0 release-gate integration (plan v2 §15.4):
#   1. Frontend build
#   2. PyInstaller Analysis manifest dump (preflight, R3)
#   3. Forbidden-path scan on manifest (early intent gate)
#   4. PyInstaller full build
#   5. Forbidden-path scan on onedir (final fact gate)
#   6. Bare secret scan on onedir (no baseline; R1)
#   7. Inno source-clause check (lightweight)
#   8. Inno build installer
#   9. Frozen first-launch storage smoke (A0.6)
#
# Usage:
#   .\scripts\build_windows_exe.ps1 [-Version 1.0.0] [-SkipFrontend] [-SkipInno] [-SkipFrozenSmoke]
#
# Output: workspace_artifacts\releases\<version>\onedir\LiteratureAssistant\

param(
    [string]$Version = "1.0.0",
    [switch]$SkipFrontend,
    [switch]$SkipInno,
    [switch]$SkipFrozenSmoke
)

$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ReleaseDir = Join-Path $Repo "workspace_artifacts\releases\$Version"
$OnedirDir = Join-Path $ReleaseDir 'onedir'
$BuildDir = Join-Path $ReleaseDir 'build'
$ManifestDir = Join-Path $ReleaseDir 'build-manifests'
$RejectedDir = Join-Path $Repo 'workspace_artifacts\releases\_rejected'
$VenvPython = Join-Path $Repo '.venv-1\Scripts\python.exe'
$DumpScript = Join-Path $Repo 'scripts\dump_pyinstaller_analysis.py'
$PathScanScript = Join-Path $Repo 'scripts\release_forbidden_path_scan.py'
$SecretScanScript = Join-Path $Repo 'scripts\release_secret_scan.py'
$FrozenSmokeScript = Join-Path $Repo 'scripts\smoke_frozen_first_launch.py'

if (-not (Test-Path $VenvPython)) {
    throw "venv python missing: $VenvPython"
}

Write-Host "[build] repo=$Repo version=$Version"
New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null
New-Item -ItemType Directory -Force -Path $RejectedDir | Out-Null

# Step 1. Frontend build
if (-not $SkipFrontend) {
    Write-Host "[build:1] frontend: npm run build"
    Push-Location (Join-Path $Repo 'frontend')
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
    }
    finally { Pop-Location }
} else {
    Write-Host "[build:1] frontend: SKIPPED"
}

if (-not (Test-Path (Join-Path $Repo 'frontend\dist\index.html'))) {
    throw "frontend/dist/index.html missing — cannot proceed without built SPA"
}

# Step 2. PyInstaller Analysis manifest dump (R3 preflight)
$Spec = Join-Path $Repo 'packaging\pyinstaller\literature-assistant.spec'
$ManifestPath = Join-Path $ManifestDir 'pyinstaller-analysis-datas.json'
Write-Host "[build:2] pyinstaller analysis manifest dump"
& $VenvPython $DumpScript --spec $Spec --out $ManifestPath
if ($LASTEXITCODE -ne 0) { throw "Analysis manifest dump failed (exit $LASTEXITCODE)" }

# Step 3. Forbidden-path scan on manifest (early intent gate)
Write-Host "[build:3] forbidden-path scan: manifest"
& $VenvPython $PathScanScript --mode manifest --input $ManifestPath `
    --rejected-dir $RejectedDir --build-version $Version
if ($LASTEXITCODE -ne 0) {
    throw "Manifest forbidden-path scan failed — see $RejectedDir for redacted report"
}

# Step 4. Clean prior onedir, then PyInstaller full build
if (Test-Path $OnedirDir) { Remove-Item -Recurse -Force $OnedirDir }
New-Item -ItemType Directory -Force -Path $OnedirDir | Out-Null

$PyInstaller = Join-Path $Repo '.venv-1\Scripts\pyinstaller.exe'
if (-not (Test-Path $PyInstaller)) {
    throw "PyInstaller not found at $PyInstaller — install via: .venv-1\Scripts\pip install pyinstaller"
}

Write-Host "[build:4] pyinstaller full build: $Spec"
& $PyInstaller --workpath $BuildDir --distpath $OnedirDir --noconfirm $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$OnedirPayload = Join-Path $OnedirDir 'LiteratureAssistant'
if (-not (Test-Path $OnedirPayload)) {
    throw "Expected onedir payload missing: $OnedirPayload"
}

# Step 5. Forbidden-path scan on onedir (final fact gate)
Write-Host "[build:5] forbidden-path scan: onedir"
& $VenvPython $PathScanScript --mode onedir --input $OnedirPayload `
    --rejected-dir $RejectedDir --build-version $Version
if ($LASTEXITCODE -ne 0) {
    throw "Onedir forbidden-path scan failed — see $RejectedDir for redacted report"
}

# Step 6. Bare secret scan on onedir (R1: NO baseline)
Write-Host "[build:6] secret scan (bare, no baseline): onedir"
& $VenvPython $SecretScanScript --input $OnedirPayload `
    --rejected-dir $RejectedDir --build-version $Version
if ($LASTEXITCODE -ne 0) {
    throw "Onedir secret scan failed — see $RejectedDir for redacted report"
}

# SHA256 of the produced exe
$ExePath = Join-Path $OnedirPayload 'LiteratureAssistant.exe'
if (-not (Test-Path $ExePath)) { throw "Expected exe missing: $ExePath" }
$Sha = (Get-FileHash $ExePath -Algorithm SHA256).Hash
$ShaFile = Join-Path $ReleaseDir 'SHA256SUMS.txt'
"$Sha *LiteratureAssistant.exe" | Out-File $ShaFile -Encoding ASCII
Write-Host "[build] sha256: $Sha"

# Step 7+8. Inno source-clause check + Inno build installer
if (-not $SkipInno) {
    $Iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    $Iss = Join-Path $Repo 'packaging\inno-setup\literature-assistant.iss'
    if ((Test-Path $Iscc) -and (Test-Path $Iss)) {
        Write-Host "[build:7] inno source-clause check: $Iss"
        # Lightweight: scan .iss for Source: clauses pointing OUTSIDE the onedir payload root
        $IssText = Get-Content $Iss -Raw
        $SourceMatches = [regex]::Matches($IssText, 'Source:\s*"([^"]+)"', 'IgnoreCase')
        $BadSources = @()
        foreach ($m in $SourceMatches) {
            $src = $m.Groups[1].Value
            # Allow templated {#OnedirRoot}, {app}, etc., and anything literally under the onedir.
            if ($src -match 'runtime_state|\.env|credentials\.json|key\.txt|chunk_store|logs|_rejected') {
                $BadSources += $src
            }
        }
        if ($BadSources.Count -gt 0) {
            $BadList = $BadSources -join "`n  - "
            throw "Inno .iss declares forbidden source paths:`n  - $BadList"
        }

        Write-Host "[build:8] inno setup: $Iss"
        # Pass ReleaseRoot as an absolute path so ISCC does not enumerate files
        # through "..\..\" segments (each ".." kept literal eats ~3 chars and
        # blew MAX_PATH for ui-ux-pro-max\src\ui-ux-pro-max\data\stacks\*.csv
        # at alpha-prep attempt 6, 2026-05-12). $ReleaseDir is already absolute
        # via Resolve-Path on $Repo above.
        & $Iscc "/DAppVersion=$Version" "/DReleaseRoot=$ReleaseDir" $Iss
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit $LASTEXITCODE)" }
        $InstallerPath = Join-Path $ReleaseDir "LiteratureAssistant-Setup-$Version-windows-x64.exe"
        if (Test-Path $InstallerPath) {
            $InstallerSha = (Get-FileHash $InstallerPath -Algorithm SHA256).Hash
            "$InstallerSha *LiteratureAssistant-Setup-$Version-windows-x64.exe" | `
                Add-Content $ShaFile -Encoding ASCII
            Write-Host "[build] installer sha256: $InstallerSha"
        }
    } else {
        Write-Host "[build:7-8] inno setup: SKIPPED (ISCC.exe or .iss missing)"
    }
}

# Step 9. Frozen first-launch storage smoke (A0.6, DEC-001b)
if (-not $SkipFrozenSmoke -and (Test-Path $FrozenSmokeScript)) {
    Write-Host "[build:9] frozen first-launch storage check"
    & $VenvPython $FrozenSmokeScript --exe $ExePath --rejected-dir $RejectedDir --build-version $Version
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen first-launch smoke failed — see $RejectedDir"
    }
} else {
    Write-Host "[build:9] frozen first-launch smoke: SKIPPED"
}

Write-Host "[build] DONE — $ReleaseDir"
