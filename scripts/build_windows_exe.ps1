# -*- ps1: build Scholar AI Windows onedir bundle ------------------------
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
#   Optional installer signing:
#     $env:LITERATURE_ASSISTANT_INNO_SIGNTOOL_COMMAND = 'signtool sign ... $f'
#     .\scripts\build_windows_exe.ps1 -Version 1.0.0
#
# Output: workspace_artifacts\releases\<version>\onedir\Scholar-AI\

param(
    [string]$Version = "1.0.0",
    [switch]$SkipFrontend,
    [switch]$SkipInno,
    [switch]$SkipFrozenSmoke,
    [string]$InnoSignToolName = $env:LITERATURE_ASSISTANT_INNO_SIGNTOOL_NAME,
    [string]$InnoSignToolCommand = $env:LITERATURE_ASSISTANT_INNO_SIGNTOOL_COMMAND
)

# Validate version format
if ($Version -notmatch '^\d+\.\d+\.\d+(\.\d+)?$') {
    throw "Invalid version format: $Version (expected: x.y.z or x.y.z.w)"
}

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

function Get-ReleaseFileSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Hash path cannot be empty"
    }

    $ResolvedPath = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).ProviderPath
    if (-not (Test-Path -LiteralPath $ResolvedPath -PathType Leaf)) {
        throw "Hash path is not a file: $ResolvedPath"
    }

    $Stream = [System.IO.File]::Open(
        $ResolvedPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    try {
        $Sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            $Bytes = $Sha256.ComputeHash($Stream)
        }
        finally {
            if ($null -ne $Sha256) {
                $Sha256.Dispose()
            }
        }
    }
    finally {
        $Stream.Dispose()
    }

    $Hex = -join ($Bytes | ForEach-Object { $_.ToString('x2') })
    return $Hex.ToUpperInvariant()
}

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

# Step 2.5. Audit hiddenimports completeness
$HiddenimportsAuditScript = Join-Path $Repo 'scripts\audit_pyinstaller_hiddenimports.py'
Write-Host "[build:2.5] audit hiddenimports vs registered routers"
& $VenvPython $HiddenimportsAuditScript --spec $Spec
if ($LASTEXITCODE -ne 0) {
    throw "Hiddenimports audit failed — missing router modules in spec hiddenimports list"
}

# Step 3. Forbidden-path scan on manifest (early intent gate)
Write-Host "[build:3] forbidden-path scan: manifest"
& $VenvPython $PathScanScript --mode manifest --input $ManifestPath `
    --rejected-dir $RejectedDir --build-version $Version
if ($LASTEXITCODE -ne 0) {
    throw "Manifest forbidden-path scan failed — see $RejectedDir for redacted report"
}

# Step 4. Clean prior PyInstaller outputs, then PyInstaller full build
if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
if (Test-Path $OnedirDir) { Remove-Item -Recurse -Force $OnedirDir }
New-Item -ItemType Directory -Force -Path $OnedirDir | Out-Null

$PyInstaller = Join-Path $Repo '.venv-1\Scripts\pyinstaller.exe'
if (-not (Test-Path $PyInstaller)) {
    throw "PyInstaller not found at $PyInstaller — install via: .venv-1\Scripts\pip install pyinstaller"
}

Write-Host "[build:4] pyinstaller full build: $Spec"
& $PyInstaller --clean --workpath $BuildDir --distpath $OnedirDir --noconfirm $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$OnedirPayload = Join-Path $OnedirDir 'Scholar-AI'
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
$ExePath = Join-Path $OnedirPayload 'Scholar-AI.exe'
if (-not (Test-Path $ExePath)) { throw "Expected exe missing: $ExePath" }
$Sha = Get-ReleaseFileSha256 -Path $ExePath
$ShaFile = Join-Path $ReleaseDir 'SHA256SUMS.txt'
"$Sha *Scholar-AI.exe" | Out-File $ShaFile -Encoding ASCII
Write-Host "[build] sha256: $Sha"

# Step 7+8. Inno source-clause check + Inno build installer
if (-not $SkipInno) {
    $Iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    $Iss = Join-Path $Repo 'packaging\inno-setup\literature-assistant.iss'

    # L-10 mitigation: hard-fail if ISCC.exe missing (no silent SKIP)
    if (-not (Test-Path $Iscc)) {
        throw "ISCC.exe not found at $Iscc — install Inno Setup 6 or pass -SkipInno to bypass"
    }
    if (-not (Test-Path $Iss)) {
        throw "Inno script not found: $Iss"
    }

    if ((Test-Path $Iscc) -and (Test-Path $Iss)) {
        Write-Host "[build:7] inno source-clause check: $Iss"
        # C-6 mitigation: whitelist-based Source validation.
        # All [Files] Source clauses must start with {#ReleaseRoot}\onedir\Scholar-AI\
        # or be in the known safe external assets list.
        $IssText = Get-Content $Iss -Raw
        $SourceMatches = [regex]::Matches($IssText, '(?m)^\s*Source:\s*"([^"]+)"', 'IgnoreCase')
        $SafeExternalPrefixes = @('..\assets\')
        $BadSources = @()
        $LineNumber = 1
        foreach ($line in (Get-Content $Iss)) {
            if ($line -match '^\s*Source:\s*"([^"]+)"') {
                $src = $Matches[1]
                $isWhitelisted = $false
                # Check if it's the main payload
                if ($src -match '^\{#ReleaseRoot\}\\onedir\\Scholar-AI\\') {
                    $isWhitelisted = $true
                }
                # Check if it's in safe external assets
                foreach ($prefix in $SafeExternalPrefixes) {
                    if ($src.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                        $isWhitelisted = $true
                        break
                    }
                }
                if (-not $isWhitelisted) {
                    $BadSources += "Line $LineNumber : $src"
                }
            }
            $LineNumber++
        }
        if ($BadSources.Count -gt 0) {
            $BadList = $BadSources -join "`n  - "
            throw "Inno .iss contains non-whitelisted Source paths (must start with {#ReleaseRoot}\onedir\Scholar-AI\ or ..\assets\):`n  - $BadList"
        }

        Write-Host "[build:8] inno setup: $Iss"
        # Pass ReleaseRoot as an absolute path so ISCC does not enumerate files
        # through "..\..\" segments (each ".." kept literal eats ~3 chars and
        # blew MAX_PATH for ui-ux-pro-max\src\ui-ux-pro-max\data\stacks\*.csv
        # at alpha-prep attempt 6, 2026-05-12). $ReleaseDir is already absolute
        # via Resolve-Path on $Repo above.
        $env:LITASSIST_BUILD_VERSION = $Version
        $IsccArgs = @("/DAppVersion=$Version", "/DReleaseRoot=$ReleaseDir")
        $ResolvedSignToolName = $InnoSignToolName
        if ([string]::IsNullOrWhiteSpace($ResolvedSignToolName)) {
            $ResolvedSignToolName = 'ScholarAISignTool'
        }
        if (-not [string]::IsNullOrWhiteSpace($InnoSignToolCommand)) {
            if ($InnoSignToolCommand -notmatch '\$f') {
                throw "Inno signing command must include `$f placeholder for the file being signed"
            }
            $IsccArgs += "/DSignToolName=$ResolvedSignToolName"
            $IsccArgs += "/S$ResolvedSignToolName=$InnoSignToolCommand"
            Write-Host "[build:8] inno signing: enabled ($ResolvedSignToolName)"
        } else {
            Write-Host "[build:8] inno signing: unsigned (set LITERATURE_ASSISTANT_INNO_SIGNTOOL_COMMAND to enable)"
        }
        $IsccArgs += $Iss
        & $Iscc @IsccArgs
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit $LASTEXITCODE)" }
        $InstallerFileName = "Scholar-AI-Setup-$Version-windows-x64.exe"
        $InstallerPath = Join-Path $ReleaseDir $InstallerFileName
        if (-not (Test-Path $InstallerPath)) {
            throw "Expected installer missing: $InstallerPath"
        }
        $InstallerSha = Get-ReleaseFileSha256 -Path $InstallerPath
        "$InstallerSha *$InstallerFileName" | `
            Add-Content $ShaFile -Encoding ASCII
        Write-Host "[build] installer sha256: $InstallerSha"
    }
}

# Step 9. Frozen first-launch storage smoke (A0.6, DEC-001b)
if (-not $SkipFrozenSmoke) {
    # L-10 mitigation: hard-fail if smoke script missing (no silent SKIP)
    if (-not (Test-Path $FrozenSmokeScript)) {
        throw "Frozen smoke script not found: $FrozenSmokeScript — cannot verify first-launch behavior (pass -SkipFrozenSmoke to bypass)"
    }
    Write-Host "[build:9] frozen first-launch storage check"
    & $VenvPython $FrozenSmokeScript --exe $ExePath --rejected-dir $RejectedDir --build-version $Version
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen first-launch smoke failed — see $RejectedDir"
    }
} else {
    Write-Host "[build:9] frozen first-launch smoke: SKIPPED"
}

Write-Host "[build] DONE — $ReleaseDir"
