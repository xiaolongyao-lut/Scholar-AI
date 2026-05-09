from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "tools" / "squad" / "squad.ps1"


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


def test_long_run_without_flags_does_not_treat_empty_arg_as_unknown_flag(tmp_path: Path) -> None:
    script_dir = tmp_path / "tools" / "squad"
    script_dir.mkdir(parents=True)
    (script_dir / "start-long-run.ps1").write_text(
        "Write-Host 'fake-long-run-started'\nexit 0\n",
        encoding="utf-8",
    )

    result = run_wrapper(["long-run"], extra_env={"SQUAD_TEST_ROOT": str(tmp_path)})

    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, combined
    assert "fake-long-run-started" in combined
    assert "unknown flag" not in combined
