from __future__ import annotations

# pylint: disable=redefined-outer-name

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "tools" / "squad" / "squad.ps1"


def _make_fake_cli(tmp_path: Path, exit_code: int = 0, output: str = "fake-cli-output") -> Path:
    fake = tmp_path / "fake_squad.ps1"
    fake.write_text(
        f"param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)\n"
        f"Write-Host '{output}'\n"
        f"if ($Args) {{ Write-Host ('ARGS=' + ($Args -join ' ')) }}\n"
        f"exit {exit_code}\n",
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
        check=False,
        env=env,
    )


@pytest.fixture()
def squad_root(tmp_path: Path) -> Path:
    squad_dir = tmp_path / ".squad"
    squad_dir.mkdir(parents=True)
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


def test_agent_list_is_local_command(fake_cli_env: dict) -> None:
    result = run_wrapper(["agent", "list"], extra_env=fake_cli_env)
    assert result.returncode == 0, result.stderr
    assert "Agent bridge map" in result.stdout
    assert "Expert React Frontend Engineer" in result.stdout


def test_agent_bridge_dispatches_task_without_spawn(fake_cli_env: dict) -> None:
    result = run_wrapper(
        [
            "agent",
            "run",
            "Expert React Frontend Engineer",
            "--no-spawn",
            "--task",
            "请优化设置页渲染性能",
        ],
        extra_env=fake_cli_env,
    )

    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, combined
    assert "fake-cli-output" in combined
    assert "ARGS=task create" in combined


def test_agent_unknown_mapping_requires_role(fake_cli_env: dict) -> None:
    result = run_wrapper(["agent", "run", "Unknown Agent Name", "--no-spawn"], extra_env=fake_cli_env)
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 1, combined
    assert "no role mapping found" in combined
