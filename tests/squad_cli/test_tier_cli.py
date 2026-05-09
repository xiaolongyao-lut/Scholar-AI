from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "tools" / "squad" / "squad.ps1"


def run_wrapper(
    args: list[str],
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("SQUAD_REAL_CLI", None)
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WRAPPER),
        ]
        + args,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
    )


@pytest.fixture()
def temp_squad_root(tmp_path: Path) -> Path:
    squad_dir = tmp_path / ".squad"
    squad_dir.mkdir()
    kernel_dir = squad_dir / "kernel"
    kernel_dir.mkdir()

    (squad_dir / "config.json").write_text(
        json.dumps({"version": 1}),
        encoding="utf-8",
    )

    defaults = {
        "kernel_version": "1.0.0",
        "tiers": {
            "default": {
                "description": "Conservative mode: self-heal minor issues, escalate on blockers",
                "behaviors": {
                    "env_mismatch": "self_heal",
                    "missing_dep": "queue",
                    "constraint": "escalate",
                    "ambiguity": "escalate",
                },
            },
            "autopilot": {
                "description": "Autonomous mode: resolve blockers independently when safe",
                "behaviors": {
                    "env_mismatch": "self_heal",
                    "missing_dep": "self_heal",
                    "constraint": "escalate",
                    "ambiguity": "degrade",
                },
            },
        },
    }
    (kernel_dir / "defaults.json").write_text(
        json.dumps(defaults, indent=2),
        encoding="utf-8",
    )

    return tmp_path


def test_tier_get_defaults_to_default(temp_squad_root: Path) -> None:
    """squad tier (no args) shows 'Current tier: default' when autonomy_tier is not set."""
    result = run_wrapper(["tier"], extra_env={"SQUAD_TEST_ROOT": str(temp_squad_root)})
    assert result.returncode == 0, result.stderr
    assert "Current tier: default" in result.stdout


def test_tier_set_autopilot(temp_squad_root: Path) -> None:
    """squad tier autopilot sets tier and confirms."""
    result = run_wrapper(
        ["tier", "autopilot"], extra_env={"SQUAD_TEST_ROOT": str(temp_squad_root)}
    )
    assert result.returncode == 0, result.stderr
    assert "Tier set to autopilot" in result.stdout

    cfg = json.loads((temp_squad_root / ".squad" / "config.json").read_text(encoding="utf-8-sig"))
    assert cfg.get("autonomy_tier") == "autopilot"


def test_tier_set_is_idempotent(temp_squad_root: Path) -> None:
    """squad tier autopilot twice does not error on the second call."""
    run_wrapper(["tier", "autopilot"], extra_env={"SQUAD_TEST_ROOT": str(temp_squad_root)})
    result = run_wrapper(
        ["tier", "autopilot"], extra_env={"SQUAD_TEST_ROOT": str(temp_squad_root)}
    )
    assert result.returncode == 0, result.stderr


def test_tier_explain_shows_matrix(temp_squad_root: Path) -> None:
    """squad tier --explain prints the behavior matrix from defaults.json."""
    result = run_wrapper(
        ["tier", "--explain"], extra_env={"SQUAD_TEST_ROOT": str(temp_squad_root)}
    )
    assert result.returncode == 0, result.stderr
    assert "default" in result.stdout
    assert "autopilot" in result.stdout
    assert "constraint" in result.stdout
    assert "escalate" in result.stdout


def test_tier_invalid_name_exits_1(temp_squad_root: Path) -> None:
    """squad tier <unknown> exits with code 1 and prints an error."""
    result = run_wrapper(
        ["tier", "unknown_tier"], extra_env={"SQUAD_TEST_ROOT": str(temp_squad_root)}
    )
    assert result.returncode == 1
    assert "Invalid tier" in result.stderr
