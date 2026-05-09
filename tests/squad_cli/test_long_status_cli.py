from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_SQUAD = REPO_ROOT / "tools" / "squad"


def run_script(script: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)] + args,
        cwd=script.parents[2],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def copy_status_scripts(tmp_path: Path) -> Path:
    script_dir = tmp_path / "tools" / "squad"
    script_dir.mkdir(parents=True)

    (script_dir / "long-status-check.ps1").write_text(
        (TOOLS_SQUAD / "long-status-check.ps1").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    guard_text = (TOOLS_SQUAD / "squad-guard.ps1").read_text(encoding="utf-8")
    test_root = str(tmp_path).replace("'", "''")
    guard_text = guard_text.replace(
        "$script:ProjectRoot = 'C:\\Users\\xiao\\Desktop\\tools\\Modular-Pipeline-Script'",
        f"$script:ProjectRoot = '{test_root}'",
    )
    (script_dir / "squad-guard.ps1").write_text(guard_text, encoding="utf-8")

    return script_dir / "long-status-check.ps1"


def test_long_status_halt_check_uses_test_root_and_handles_fresh_green_evals(
    tmp_path: Path,
) -> None:
    squad_dir = tmp_path / ".squad"
    identity_dir = squad_dir / "identity"
    eval_dir = squad_dir / "evaluations"
    memory_dir = squad_dir / "memory"
    identity_dir.mkdir(parents=True)
    eval_dir.mkdir(parents=True)
    memory_dir.mkdir(parents=True)

    (identity_dir / "goal-drift.md").write_text(
        "## 3. Product capabilities\n"
        "- [x] done\n"
        "## 4. Hardening\n"
        "- [x] stable\n"
        "## 5. Archive\n",
        encoding="utf-8",
    )
    (memory_dir / "OPEN_THREADS.md").write_text("", encoding="utf-8")

    for idx in range(3):
        payload = {
            "run_id": f"green-{idx}",
            "finished_at": "2026-04-27T00:00:00Z",
            "summary": {"passed": 3, "total": 3, "pass_rate": 1.0},
        }
        (eval_dir / f"run-{idx}.json").write_text(json.dumps(payload), encoding="utf-8")

    script = copy_status_scripts(tmp_path)
    result = run_script(script, ["-HaltCheck"])

    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, combined
    report = json.loads(result.stdout)
    assert report["halt_legal"] is True
    assert report["halt_reasons"] == []