from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "tools" / "squad" / "squad.ps1"

DEFAULTS = {
    # NOTE: field in JSONL is "blocker_type", not "type"
    "kernel_version": "1.0.0",
    "tiers": {
        "default": {
            "description": "Conservative mode",
            "behaviors": {
                "constructible": "self_heal",
                "economic": "degrade",
                "context": "queue",
                "constraint": "escalate",
            },
        },
        "autopilot": {
            "description": "Autonomous mode",
            "behaviors": {
                "constructible": "self_heal",
                "economic": "degrade",
                "context": "queue",
                "constraint": "escalate",
            },
        },
    },
}


def run_wrapper(args: list[str], extra_env: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("SQUAD_REAL_CLI", None)
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
    (squad_dir / "kernel").mkdir()
    (squad_dir / "state").mkdir()

    (squad_dir / "config.json").write_text(
        json.dumps({"version": 1, "autonomy_tier": "default"}), encoding="utf-8"
    )
    (squad_dir / "kernel" / "defaults.json").write_text(
        json.dumps(DEFAULTS, indent=2), encoding="utf-8"
    )
    (squad_dir / "state" / "blockers.jsonl").write_text("", encoding="utf-8")
    return tmp_path


# ---------- open ----------

def test_blocker_open_creates_entry(squad_root: Path) -> None:
    result = run_wrapper(
        ["blocker", "open", "Cannot connect to DB", "--type", "constructible"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode == 0, result.stderr
    assert "BLK-" in result.stdout

    lines = (squad_root / ".squad" / "state" / "blockers.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["title"] == "Cannot connect to DB"
    assert entry["blocker_type"] == "constructible"
    assert entry["status"] == "open"
    assert entry["decision"] == "self_heal"


def test_blocker_open_constraint_escalates(squad_root: Path) -> None:
    result = run_wrapper(
        ["blocker", "open", "Hard policy limit", "--type", "constraint"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode == 0, result.stderr
    lines = (squad_root / ".squad" / "state" / "blockers.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    assert entry["decision"] == "escalate"


def test_blocker_open_invalid_type_fails(squad_root: Path) -> None:
    result = run_wrapper(
        ["blocker", "open", "Some blocker", "--type", "badtype"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode != 0


# ---------- list ----------

def test_blocker_list_shows_open(squad_root: Path) -> None:
    # Add a blocker first
    run_wrapper(
        ["blocker", "open", "My blocker", "--type", "economic"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    result = run_wrapper(
        ["blocker", "list"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode == 0, result.stderr
    assert "My blocker" in result.stdout


def test_blocker_list_empty_no_error(squad_root: Path) -> None:
    result = run_wrapper(
        ["blocker", "list"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode == 0


# ---------- close ----------

def test_blocker_close_requires_audit(squad_root: Path) -> None:
    # Open first
    open_result = run_wrapper(
        ["blocker", "open", "Temp blocker", "--type", "context"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert open_result.returncode == 0
    # Extract BLK id from output
    blk_id = next(w for w in open_result.stdout.split() if w.startswith("BLK-"))

    close_result = run_wrapper(
        ["blocker", "close", blk_id, "--audit", "Fixed by restarting service"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert close_result.returncode == 0, close_result.stderr
    assert "closed" in close_result.stdout.lower()


def test_blocker_close_without_audit_fails(squad_root: Path) -> None:
    open_result = run_wrapper(
        ["blocker", "open", "Needs audit", "--type", "constructible"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    blk_id = next(w for w in open_result.stdout.split() if w.startswith("BLK-"))

    result = run_wrapper(
        ["blocker", "close", blk_id],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode != 0


# ---------- reclassify ----------

def test_blocker_reclassify(squad_root: Path) -> None:
    open_result = run_wrapper(
        ["blocker", "open", "Unclear blocker", "--type", "constructible"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    blk_id = next(w for w in open_result.stdout.split() if w.startswith("BLK-"))

    result = run_wrapper(
        ["blocker", "reclassify", blk_id, "--type", "constraint", "--reason", "actually a policy issue"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode == 0, result.stderr
