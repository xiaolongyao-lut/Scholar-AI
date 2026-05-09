from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ENABLE = REPO_ROOT / "tools" / "squad" / "enable.ps1"
WRAPPER = REPO_ROOT / "tools" / "squad" / "squad.ps1"


def run_powershell(command: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("SQUAD_REAL_CLI", None)

    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=env,
    )


def test_enable_script_can_be_dot_sourced_and_registers_squad_function() -> None:
    command = (
        f". '{ENABLE}'; "
        "$cmd = Get-Command squad -CommandType Function -ErrorAction SilentlyContinue; "
        "if ($null -ne $cmd) { Write-Output 'ok'; exit 0 } else { Write-Output 'missing'; exit 1 }"
    )

    result = run_powershell(command)

    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "ok" in result.stdout


def test_wrapper_returns_clear_error_when_real_cli_missing() -> None:
    env = os.environ.copy()
    env.pop("SQUAD_REAL_CLI", None)
    env["PATH"] = ""

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WRAPPER),
            "status",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=env,
    )

    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 4, combined
    assert "Official squad CLI not found" in combined
