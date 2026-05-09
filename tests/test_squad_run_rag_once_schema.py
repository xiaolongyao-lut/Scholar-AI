from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_RAG_ONCE = REPO_ROOT / "tools" / "squad" / "run-rag-once.ps1"
CHECK_EVAL_SCHEMA = REPO_ROOT / "tools" / "squad" / "check-eval-schema.ps1"


def test_run_rag_once_invokes_eval_schema_checker_after_atomic_write() -> None:
    script = RUN_RAG_ONCE.read_text(encoding="utf-8")

    atomic_write_index = script.index("Move-Item -Path $tmp -Destination $outFile -Force")
    checker_path_index = script.index("check-eval-schema.ps1")
    checker_run_file_index = script.index("-RunFile $outFile")

    assert atomic_write_index < checker_path_index < checker_run_file_index


def test_check_eval_schema_accepts_explicit_run_file_when_called_with_file(tmp_path: Path) -> None:
    run_file = tmp_path / "run-test.json"
    run_file.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "question": "q",
                        "response_text": "answer",
                        "elapsed_ms": 1,
                        "traceback": None,
                        "citation_count": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(CHECK_EVAL_SCHEMA),
            "-RunFile",
            str(run_file),
            "-Json",
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "compliant"
    assert payload["file"] == run_file.name
