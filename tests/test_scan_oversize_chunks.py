from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_scan(root: Path, output_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CHUNK_HARD_MAX_CHARS"] = "5000"
    env["CHUNK_HARD_MAX_TOKENS"] = "999999"
    return subprocess.run(
        [
            sys.executable,
            "scripts/scan_oversize_chunks.py",
            "--root",
            str(root),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )


def test_scan_oversize_script_writes_material_report_from_legacy_store(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    root.mkdir(parents=True, exist_ok=True)
    (root / "proj_chunks.json").write_text(
        json.dumps(
            {
                "mat-big": [
                    {
                        "material_id": "mat-big",
                        "chunk_id": "mat-big_chunk_0",
                        "content": "A" * 6001,
                        "source_path": "papers/mat-big.pdf",
                    }
                ],
                "mat-small": [
                    {
                        "material_id": "mat-small",
                        "chunk_id": "mat-small_chunk_0",
                        "content": "small chunk",
                        "source_path": "papers/mat-small.pdf",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "oversize_materials_report.json"

    result = _run_scan(root, output_path)

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["oversize_material_count"] == 1
    assert payload["oversize_chunk_count"] == 1
    assert payload["materials"] == [
        {
            "project_id": "proj",
            "material_id": "mat-big",
            "oversize_chunk_count": 1,
            "max_char": 6001,
            "max_token": payload["materials"][0]["max_token"],
            "source_path": "papers/mat-big.pdf",
        }
    ]


def test_scan_oversize_script_prefers_v2_project_over_duplicate_legacy_json(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    project_dir = root / "proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "mat-a.jsonl").write_text(
        json.dumps(
            {
                "material_id": "mat-a",
                "chunk_id": "mat-a_chunk_0",
                "content": "safe chunk",
                "source_path": "papers/v2.pdf",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (project_dir / "manifest.json").write_text(
        json.dumps(
            {
                "version": 2,
                "materials": {
                    "mat-a": {
                        "relative_path": "mat-a.jsonl",
                        "sha256": "unused",
                        "total_chunks": 1,
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / "proj_chunks.json").write_text(
        json.dumps(
            {
                "mat-a": [
                    {
                        "material_id": "mat-a",
                        "chunk_id": "mat-a_chunk_legacy",
                        "content": "B" * 6001,
                        "source_path": "papers/legacy.pdf",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "oversize_materials_report.json"

    result = _run_scan(root, output_path)

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["oversize_material_count"] == 0
    assert payload["oversize_chunk_count"] == 0
    assert payload["materials"] == []
