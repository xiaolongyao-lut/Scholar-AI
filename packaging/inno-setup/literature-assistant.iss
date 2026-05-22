; -*- inno-setup: Literature Assistant Windows installer ----------------
; Reference: docs/plans/runbooks/windows-exe-release-standard.md
;
; Build:
;   ISCC.exe /DAppVersion=0.1.0 packaging\inno-setup\literature-assistant.iss
;
; Output: workspace_artifacts\releases\<version>\LiteratureAssistant-Setup-<version>-windows-x64.exe

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

; ReleaseRoot is the absolute path to workspace_artifacts/releases/<AppVersion>.
; Build script (scripts/build_windows_exe.ps1) passes it via /DReleaseRoot=<abs>
; to keep ISCC's [Files] Source patterns short. Without it, ISCC composes
; "<iss_dir>\..\..\workspace_artifacts\releases\<AppVersion>\onedir\..." which
; for deep paths (e.g. ui-ux-pro-max\src\ui-ux-pro-max\data\stacks\*.csv at
; 188 chars relative) exceeds Windows MAX_PATH (260) once the ".." segments
; are kept literal during file enumeration (alpha-prep attempt 6 root cause,
; 2026-05-12). Falling back to the historical relative form preserves
; behaviour for hand-invocation outside the build script.
; Refs:
;   - https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation
;   - Inno Setup ISPP: https://jrsoftware.org/ishelp/index.php?topic=ispp
#ifndef ReleaseRoot
  #define ReleaseRoot "..\..\workspace_artifacts\releases\" + AppVersion
#endif

[Setup]
; AppId is the permanent identity for upgrade detection. NEVER change this
; after any user has installed the app — Inno uses it to find the existing
; install and upgrade in place.
AppId={{058DF2F0-81F0-4942-8BAC-EE9A8630D4EF}
AppName=LiteratureAssistant
AppVersion={#AppVersion}
AppPublisher=Literature Assistant Project
AppPublisherURL=https://example.invalid/
DefaultDirName={autopf}\LiteratureAssistant
DefaultGroupName=LiteratureAssistant
OutputBaseFilename=LiteratureAssistant-Setup-{#AppVersion}-windows-x64
OutputDir={#ReleaseRoot}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\assets\license.txt
PrivilegesRequired=lowest
; x64compatible: installs on x64 Windows (including ARM64 via emulation layer).
; Preferred over deprecated "x64" (Inno Setup 6.3+) and over "x64os" which
; excludes ARM64 machines running x64 emulation.
; Ref: https://jrsoftware.org/ishelp/index.php?topic=setup_architecturesallowed
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableDirPage=no
UninstallDisplayName=Literature Assistant {#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; NOTE (2026-05-12): ChineseSimplified.isl is a community-maintained translation
; that Inno Setup 6 does NOT ship in its default installation
; (https://jrsoftware.org/files/istrans/ — see "Unofficial / community translations").
; The default install only includes 27 languages, none of which is Simplified Chinese.
; Build attempt 4 (2026-05-12) failed at Step 8 because compiler:Languages\
; ChineseSimplified.isl did not exist after Inno Setup 6 install.
; Alpha installer keeps English-only language pack for cross-environment
; reproducibility (every Inno Setup 6 install ships Default.isl). Adding
; Simplified Chinese back is a future commit, either by:
;   (a) vendoring ChineseSimplified.isl under packaging/assets/ and pointing
;       MessagesFile at the relative path, or
;   (b) using ISPP `#if FileExists(CompilerPath + ...)` to conditionally load
;       when present on the build machine.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#ReleaseRoot}\onedir\LiteratureAssistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LiteratureAssistant"; Filename: "{app}\LiteratureAssistant.exe"
Name: "{group}\{cm:UninstallProgram,LiteratureAssistant}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\LiteratureAssistant"; Filename: "{app}\LiteratureAssistant.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LiteratureAssistant.exe"; Description: "{cm:LaunchProgram,LiteratureAssistant}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
