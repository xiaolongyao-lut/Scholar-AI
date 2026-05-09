from __future__ import annotations

import json
from pathlib import Path


def _write_v2_project(root: Path, project_id: str, chunk_id: str, content: str) -> None:
    project_dir = root / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "mat-a.jsonl").write_text(
        json.dumps({"chunk_id": chunk_id, "material_id": "mat-a", "content": content}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (project_dir / "manifest.json").write_text(
        json.dumps(
            {
                "version": 2,
                "materials": {
                    "mat-a": {
                        "relative_path": "mat-a.jsonl",
                        "sha256": "unused-in-loader-tests",
                        "total_chunks": 1,
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_legacy_project(root: Path, project_id: str, chunk_id: str, content: str) -> None:
    (root / f"{project_id}_chunks.json").write_text(
        json.dumps(
            {
                "mat-a": [
                    {"chunk_id": chunk_id, "material_id": "mat-a", "content": content},
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_load_retrieval_corpus_reads_v2_manifest_layout(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    chunk_store_dir = tmp_path / "output" / "chunk_store"
    _write_v2_project(chunk_store_dir, "proj", "v2-only", "laser welding")
    monkeypatch.chdir(tmp_path)

    corpus = eval_mod._load_retrieval_corpus()

    assert [chunk["chunk_id"] for chunk in corpus["chunks"]] == ["v2-only"]
    assert corpus["oversize_count"] == 0


def test_load_retrieval_corpus_falls_back_to_legacy_json_with_warning(caplog, monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    chunk_store_dir = tmp_path / "output" / "chunk_store"
    chunk_store_dir.mkdir(parents=True, exist_ok=True)
    _write_legacy_project(chunk_store_dir, "proj", "legacy-only", "laser welding")
    monkeypatch.chdir(tmp_path)
    caplog.set_level("WARNING")

    corpus = eval_mod._load_retrieval_corpus()

    assert [chunk["chunk_id"] for chunk in corpus["chunks"]] == ["legacy-only"]
    assert "legacy chunk view detected" in caplog.text


def test_load_retrieval_corpus_prefers_v2_over_legacy_when_both_exist(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    chunk_store_dir = tmp_path / "output" / "chunk_store"
    _write_v2_project(chunk_store_dir, "proj", "v2-win", "laser welding")
    _write_legacy_project(chunk_store_dir, "proj", "legacy-lose", "legacy content")
    monkeypatch.chdir(tmp_path)

    corpus = eval_mod._load_retrieval_corpus()

    assert [chunk["chunk_id"] for chunk in corpus["chunks"]] == ["v2-win"]
