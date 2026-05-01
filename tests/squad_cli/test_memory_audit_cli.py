from __future__ import annotations

import os
import subprocess
from pathlib import Path
import textwrap

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
    (squad_dir / "memory").mkdir()
    (squad_dir / "state" / "blockers.jsonl").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def valid_memory_root(squad_root: Path) -> Path:
    mem_dir = squad_root / ".squad" / "memory"

    (mem_dir / "SESSION_SNAPSHOT.md").write_text(
        textwrap.dedent("""\
            ## Facts
            - Fact one

            ## Decisions
            - Decision one

            ## Open
            - Open item

            ## Next
            - Next action
        """),
        encoding="utf-8",
    )
    (mem_dir / "DECISION_TRAIL.md").write_text(
        textwrap.dedent("""\
            # Decision Trail

            ## 2024-01-01 Do the thing [docs/thing.md:L5]
            Because reasons.
        """),
        encoding="utf-8",
    )
    (mem_dir / "OPEN_THREADS.md").write_text("# Open Threads\n\nNo active blockers.\n", encoding="utf-8")
    (mem_dir / "TEAM_MEMORY.md").write_text("# Team Memory\n\nSome notes.\n", encoding="utf-8")

    return squad_root


# ---------- happy path ----------

def test_memory_audit_passes_valid_structure(valid_memory_root: Path) -> None:
    result = run_wrapper(
        ["memory", "audit"],
        extra_env={"SQUAD_TEST_ROOT": str(valid_memory_root)},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "[OK]" in result.stdout


# ---------- missing files ----------

def test_memory_audit_fails_missing_snapshot(squad_root: Path) -> None:
    mem_dir = squad_root / ".squad" / "memory"
    # Only create some files, not SESSION_SNAPSHOT
    (mem_dir / "DECISION_TRAIL.md").write_text("[ref.md:L1]\n", encoding="utf-8")
    (mem_dir / "OPEN_THREADS.md").write_text("# Open\n", encoding="utf-8")
    (mem_dir / "TEAM_MEMORY.md").write_text("# Team\n content\n", encoding="utf-8")

    result = run_wrapper(
        ["memory", "audit"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode != 0
    assert "SESSION_SNAPSHOT.md" in result.stdout


def test_memory_audit_fails_missing_sections_in_snapshot(squad_root: Path) -> None:
    mem_dir = squad_root / ".squad" / "memory"
    (mem_dir / "SESSION_SNAPSHOT.md").write_text("# Minimal\n\nno required sections\n", encoding="utf-8")
    (mem_dir / "DECISION_TRAIL.md").write_text("[ref.md]\n", encoding="utf-8")
    (mem_dir / "OPEN_THREADS.md").write_text("# Open\n", encoding="utf-8")
    (mem_dir / "TEAM_MEMORY.md").write_text("# Team\n content\n", encoding="utf-8")

    result = run_wrapper(
        ["memory", "audit"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode != 0
    assert "## Next" in result.stdout or "## Facts" in result.stdout


# ---------- unknown sub-command ----------

def test_memory_unknown_subcommand_fails(squad_root: Path) -> None:
    result = run_wrapper(
        ["memory", "doesnotexist"],
        extra_env={"SQUAD_TEST_ROOT": str(squad_root)},
    )
    assert result.returncode != 0
