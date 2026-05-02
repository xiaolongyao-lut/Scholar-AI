from __future__ import annotations

import json

import pytest

from tools.eval.export_project_chunks_for_tolf_comparison import export_project_chunks, main


def test_export_project_chunks_writes_jsonl(monkeypatch, tmp_path) -> None:
    output_path = tmp_path / "chunks.jsonl"

    monkeypatch.setattr(
        "tools.eval.export_project_chunks_for_tolf_comparison.load_project_chunks_for_rag",
        lambda project_id: [
            {
                "chunk_id": "c1",
                "material_id": "m1",
                "title": "Laser Paper",
                "content": "Laser power increased hardness to 280 HV.",
                "source_labels": ["project_chunks"],
            },
            {
                "chunk_id": "empty",
                "material_id": "m2",
                "content": "",
            },
        ],
    )

    summary = export_project_chunks("project_a", output_path)
    rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert summary["status"] == "ok"
    assert summary["chunk_count"] == 1
    assert rows[0]["project_id"] == "project_a"
    assert rows[0]["chunk_id"] == "c1"
    assert rows[0]["content"] == "Laser power increased hardness to 280 HV."


def test_export_project_chunks_rejects_empty_project_id(tmp_path) -> None:
    with pytest.raises(ValueError, match="project_id must be a non-empty string"):
        export_project_chunks("", tmp_path / "chunks.jsonl")


def test_cli_exports_project_chunks(monkeypatch, tmp_path, capsys) -> None:
    output_path = tmp_path / "chunks.jsonl"
    monkeypatch.setattr(
        "tools.eval.export_project_chunks_for_tolf_comparison.load_project_chunks_for_rag",
        lambda _project_id: [
            {
                "chunk_id": "c1",
                "material_id": "m1",
                "content": "Laser hardness evidence.",
            }
        ],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_project_chunks_for_tolf_comparison.py",
            "--project-id",
            "project_a",
            "--output",
            str(output_path),
        ],
    )

    main()

    printed = json.loads(capsys.readouterr().out)
    assert printed["chunk_count"] == 1
    assert output_path.exists()
