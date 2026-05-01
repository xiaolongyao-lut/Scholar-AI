from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_migration_script_converts_legacy_chunk_store(tmp_path: Path) -> None:
    legacy_payload = {
        "mat-A": [
            {
                "chunk_id": "a1",
                "material_id": "mat-A",
                "title": "Alpha Notes.pdf",
                "content": "alpha one",
            }
        ]
    }
    legacy_path = tmp_path / "proj_chunks.json"
    legacy_path.write_text(json.dumps(legacy_payload, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_chunk_store_to_jsonl.py",
            "--root",
            str(tmp_path),
            "--project-id",
            "proj",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parent.parent,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert (tmp_path / "proj" / "manifest.json").exists()
    assert (tmp_path / "proj_chunks.json.legacy.bak").exists()
    compat_view = json.loads((tmp_path / "proj_chunks.json").read_text(encoding="utf-8"))
    assert compat_view == legacy_payload
