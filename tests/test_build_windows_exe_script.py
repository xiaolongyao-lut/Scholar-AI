from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT_PATH = REPO_ROOT / "scripts" / "build_windows_exe.ps1"
INNO_SCRIPT_PATH = REPO_ROOT / "packaging" / "inno-setup" / "literature-assistant.iss"
PYINSTALLER_SPEC_PATH = REPO_ROOT / "packaging" / "pyinstaller" / "literature-assistant.spec"


def _extract_powershell_function(script_text: str, function_name: str) -> str:
    """Return one named PowerShell function body from a release script.

    Args:
        script_text: Full PowerShell script source.
        function_name: Function name to extract. Must be a non-empty identifier.

    Returns:
        Complete function declaration text, including the outer braces.

    Raises:
        AssertionError: If the named function is missing or structurally invalid.
    """

    if not script_text:
        raise AssertionError("script_text must not be empty")
    if not function_name or not function_name.replace("-", "").replace("_", "").isalnum():
        raise AssertionError(f"invalid PowerShell function name: {function_name!r}")

    marker = f"function {function_name}"
    start = script_text.find(marker)
    if start < 0:
        raise AssertionError(f"{function_name}() is missing from {BUILD_SCRIPT_PATH}")

    open_brace = script_text.find("{", start)
    if open_brace < 0:
        raise AssertionError(f"{function_name}() has no opening brace")

    depth = 0
    for index in range(open_brace, len(script_text)):
        char = script_text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return script_text[start : index + 1]

    raise AssertionError(f"{function_name}() has no matching closing brace")


def _powershell_executable() -> str:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        raise AssertionError("PowerShell executable is required for release script regression tests")
    return powershell


def _powershell_single_quoted(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def test_build_windows_exe_hash_helper_is_get_file_hash_independent(tmp_path: Path) -> None:
    """Release hashing must work on hosts where Get-FileHash is unavailable."""

    script_text = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")
    helper_text = _extract_powershell_function(script_text, "Get-ReleaseFileSha256")

    assert "Get-FileHash" not in script_text
    assert "[System.Security.Cryptography.SHA256]::Create()" in helper_text

    payload = tmp_path / "payload.txt"
    payload.write_bytes(b"abc")
    expected = hashlib.sha256(b"abc").hexdigest().upper()

    probe_script = tmp_path / "probe_hash.ps1"
    probe_script.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                helper_text,
                f"$Result = Get-ReleaseFileSha256 -Path {_powershell_single_quoted(payload)}",
                "Write-Output $Result",
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            _powershell_executable(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(probe_script),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == expected


def test_windows_release_uses_scholar_ai_executable_name() -> None:
    """Windows release artifacts must use one product executable name."""

    build_script = BUILD_SCRIPT_PATH.read_text(encoding="utf-8")
    inno_script = INNO_SCRIPT_PATH.read_text(encoding="utf-8")
    pyinstaller_spec = PYINSTALLER_SPEC_PATH.read_text(encoding="utf-8")

    assert "Scholar-AI.exe" in build_script
    assert "*Scholar-AI.exe" in build_script
    assert "if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }" in build_script
    assert "& $PyInstaller --clean --workpath $BuildDir --distpath $OnedirDir --noconfirm $Spec" in build_script
    assert "Scholar-AI.exe" in inno_script
    assert "[InstallDelete]" in inno_script
    assert 'Name: "{app}\\LiteratureAssistant.exe"' in inno_script
    assert 'name="Scholar-AI"' in pyinstaller_spec

    assert "LiteratureAssistant.exe" not in build_script
    assert 'name="LiteratureAssistant"' not in pyinstaller_spec
