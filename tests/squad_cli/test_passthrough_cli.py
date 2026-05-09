from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "tools" / "squad" / "squad.ps1"


def _make_fake_cli(tmp_path: Path, exit_code: int = 0, output: str = "fake-cli-output") -> Path:
    """Create a tiny PowerShell script that acts as the fake official CLI."""
    fake = tmp_path / "fake_squad.ps1"
    fake.write_text(
        f"Write-Host '{output}'\nexit {exit_code}\n",
        encoding="utf-8",
    )
    return fake


def run_wrapper(args: list[str], extra_env: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)] + args,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
    )


@pytest.fixture()
def squad_root(tmp_path: Path) -> Path:
    squad_dir = tmp_path / ".squad"
    squad_dir.mkdir()
    (squad_dir / "config.json").write_text(
        json.dumps({"version": 1, "autonomy_tier": "default"}), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def fake_cli_env(tmp_path: Path, squad_root: Path) -> dict:
    fake = _make_fake_cli(tmp_path)
    return {
        "SQUAD_REAL_CLI": str(fake),
        "SQUAD_TEST_ROOT": str(squad_root),
    }


# ---------- passthrough with fake CLI ----------

def test_passthrough_calls_official_cli(fake_cli_env: dict) -> None:
    """An unknown command should be forwarded to the real CLI."""
    result = run_wrapper(["status"], extra_env=fake_cli_env)
    assert result.returncode == 0, result.stderr
    assert "fake-cli-output" in result.stdout


def test_passthrough_preserves_exit_code(tmp_path: Path, squad_root: Path) -> None:
    """Exit code from official CLI is forwarded."""
    fake = _make_fake_cli(tmp_path, exit_code=42, output="failing-cli")
    env = {"SQUAD_REAL_CLI": str(fake), "SQUAD_TEST_ROOT": str(squad_root)}
    result = run_wrapper(["status"], extra_env=env)
    assert result.returncode == 42


def test_missing_cli_exits_4(squad_root: Path) -> None:
    """If SQUAD_REAL_CLI is unset and no squad in PATH, exit 4."""
    env = os.environ.copy()
    env.pop("SQUAD_REAL_CLI", None)
    env["SQUAD_TEST_ROOT"] = str(squad_root)
    # Remove all possible squad locations from PATH so the real CLI can't be found
    env["PATH"] = ""

    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER), "status"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
    )
    assert result.returncode == 4


# ---------- local commands are not forwarded ----------

def test_tier_not_forwarded_to_cli(fake_cli_env: dict) -> None:
    """squad tier is handled locally; output should NOT contain fake-cli-output."""
    result = run_wrapper(["tier"], extra_env=fake_cli_env)
    assert result.returncode == 0, result.stderr
    assert "fake-cli-output" not in result.stdout
