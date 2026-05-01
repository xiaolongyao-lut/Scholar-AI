from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "tools" / "squad" / "squad.ps1"


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
    (squad_dir / "state").mkdir()
    (squad_dir / "config.json").write_text(
        json.dumps({"version": 1, "autonomy_tier": "default"}), encoding="utf-8"
    )
    (squad_dir / "state" / "pool.jsonl").write_text("", encoding="utf-8")
    return tmp_path


# ---------- add ----------

def test_pool_add_creates_entry(squad_root: Path) -> None:
    result = run_wrapper(
        ["pool", "add", "Refactor auth module", "--reason", "not urgent right now"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode == 0, result.stderr
    assert "POOL-" in result.stdout

    lines = (squad_root / ".squad" / "state" / "pool.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["title"] == "Refactor auth module"
    assert entry["status"] == "waiting"
    assert entry["reason"] == "not urgent right now"


def test_pool_add_requires_reason(squad_root: Path) -> None:
    result = run_wrapper(
        ["pool", "add", "Some task"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode != 0


# ---------- list ----------

def test_pool_list_shows_waiting(squad_root: Path) -> None:
    run_wrapper(
        ["pool", "add", "Task A", "--reason", "later"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    result = run_wrapper(["pool", "list"], extra_env={"SQUAD_TEST_ROOT": str(squad_root)})
    assert result.returncode == 0, result.stderr
    assert "Task A" in result.stdout


def test_pool_list_empty_no_error(squad_root: Path) -> None:
    result = run_wrapper(["pool", "list"], extra_env={"SQUAD_TEST_ROOT": str(squad_root)})
    assert result.returncode == 0


# ---------- promote ----------

def test_pool_promote(squad_root: Path) -> None:
    add_result = run_wrapper(
        ["pool", "add", "Promote me", "--reason", "low priority"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    pool_id = next(w for w in add_result.stdout.split() if w.startswith("POOL-"))

    result = run_wrapper(
        ["pool", "promote", pool_id],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode == 0, result.stderr
    assert "promoted" in result.stdout.lower()


# ---------- drop ----------

def test_pool_drop_requires_reason(squad_root: Path) -> None:
    add_result = run_wrapper(
        ["pool", "add", "Drop me", "--reason", "maybe later"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    pool_id = next(w for w in add_result.stdout.split() if w.startswith("POOL-"))

    result = run_wrapper(
        ["pool", "drop", pool_id],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode != 0


def test_pool_drop_with_reason(squad_root: Path) -> None:
    add_result = run_wrapper(
        ["pool", "add", "Drop with reason", "--reason", "deferred"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    pool_id = next(w for w in add_result.stdout.split() if w.startswith("POOL-"))

    result = run_wrapper(
        ["pool", "drop", pool_id, "--reason", "out of scope now"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode == 0, result.stderr
    assert "dropped" in result.stdout.lower()
