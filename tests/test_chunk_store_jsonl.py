# -*- coding: utf-8 -*-
"""Tests for the per-material JSONL chunk store layout.

Covers: roundtrip, incremental writes, legacy migration, deletion cleanup,
corrupted-file tolerance. Public API of `_load_chunk_store` /
`_save_chunk_store` is unchanged: dict[material_id -> list[chunk]].
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from routers import resources_router as rr


@pytest.fixture
def tmp_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect chunk store writes for ``proj`` to ``tmp_path``."""
    def fake_resolve(_project_id: str) -> tuple[Path, Path]:
        return tmp_path, tmp_path
    monkeypatch.setattr(rr, "_resolve_data_dir", fake_resolve)
    return tmp_path


def _sample_store() -> dict[str, list[dict]]:
    return {
        "mat-A": [
            {
                "chunk_id": "a1",
                "content": "alpha one",
                "material_id": "mat-A",
                "title": "Alpha Notes.pdf",
            },
            {
                "chunk_id": "a2",
                "content": "alpha two",
                "material_id": "mat-A",
                "title": "Alpha Notes.pdf",
            },
        ],
        "mat/B": [  # contains unsafe filename char on purpose
            {
                "chunk_id": "b1",
                "content": "beta one",
                "material_id": "mat/B",
                "title": "Beta Notes (Final).md",
            },
        ],
    }


def _assert_manifest_sha_consistency(project_dir: Path) -> None:
    manifest = json.loads((project_dir / "manifest.json").read_text("utf-8"))
    for entry in manifest["materials"].values():
        jsonl = project_dir / entry["relative_path"]
        lines = [
            json.loads(line)
            for line in jsonl.read_text("utf-8").splitlines()
            if line.strip()
        ]
        assert rr._hash_chunks(lines) == entry["sha256"]
        assert len(lines) == entry["total_chunks"]


def test_roundtrip_preserves_dict(tmp_store: Path) -> None:
    store = _sample_store()
    rr._save_chunk_store("proj", store)
    loaded = rr._load_chunk_store("proj")
    assert loaded == store


def test_save_emits_manifest_and_per_material_jsonl(tmp_store: Path) -> None:
    rr._save_chunk_store("proj", _sample_store())
    project_dir = tmp_store / "proj"
    assert (project_dir / "manifest.json").exists(), "manifest.json missing"
    manifest = json.loads((project_dir / "manifest.json").read_text("utf-8"))
    assert set(manifest["materials"].keys()) == {"mat-A", "mat/B"}
    alpha_entry = manifest["materials"]["mat-A"]
    beta_entry = manifest["materials"]["mat/B"]
    assert alpha_entry["relative_path"].startswith("alpha-notes_")
    assert alpha_entry["relative_path"].endswith(".jsonl")
    assert beta_entry["relative_path"].startswith("beta-notes-final_")
    assert beta_entry["relative_path"].endswith(".jsonl")
    assert alpha_entry["total_chunks"] == 2
    assert beta_entry["total_chunks"] == 1

    for entry in manifest["materials"].values():
        assert set(entry.keys()) == {"relative_path", "sha256", "total_chunks"}
        jsonl = project_dir / entry["relative_path"]
        assert jsonl.exists()
        assert jsonl.suffix == ".jsonl"
        lines = [
            json.loads(line)
            for line in jsonl.read_text("utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == entry["total_chunks"]


def test_manifest_sha_matches_material_jsonl_payload(tmp_store: Path) -> None:
    rr._save_chunk_store("proj", _sample_store())
    _assert_manifest_sha_consistency(tmp_store / "proj")


def test_incremental_save_only_rewrites_changed(
    tmp_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rr._save_chunk_store("proj", _sample_store())
    project_dir = tmp_store / "proj"
    manifest_before = json.loads((project_dir / "manifest.json").read_text("utf-8"))
    file_a = project_dir / manifest_before["materials"]["mat-A"]["relative_path"]
    file_b = project_dir / manifest_before["materials"]["mat/B"]["relative_path"]
    mtime_a_before = file_a.stat().st_mtime_ns
    mtime_b_before = file_b.stat().st_mtime_ns

    # Modify only mat/B; mat-A must not be rewritten.
    store = _sample_store()
    store["mat/B"].append({"chunk_id": "b2", "content": "beta two", "material_id": "mat/B"})
    rr._save_chunk_store("proj", store)

    assert file_a.stat().st_mtime_ns == mtime_a_before, "mat-A jsonl was needlessly rewritten"
    assert file_b.stat().st_mtime_ns != mtime_b_before, "mat/B jsonl was not rewritten"

    loaded = rr._load_chunk_store("proj")
    assert loaded == store


def test_deleted_material_is_cleaned_up(tmp_store: Path) -> None:
    rr._save_chunk_store("proj", _sample_store())
    project_dir = tmp_store / "proj"
    manifest_before = json.loads((project_dir / "manifest.json").read_text("utf-8"))
    file_a = project_dir / manifest_before["materials"]["mat-A"]["relative_path"]
    assert file_a.exists()

    rr._save_chunk_store("proj", {"mat/B": _sample_store()["mat/B"]})

    assert not file_a.exists(), "orphan jsonl for deleted material was not cleaned up"
    loaded = rr._load_chunk_store("proj")
    assert set(loaded.keys()) == {"mat/B"}


def test_legacy_single_file_is_migrated_on_first_save(tmp_store: Path) -> None:
    legacy_payload = _sample_store()
    legacy_path = tmp_store / "proj_chunks.json"
    legacy_path.write_text(
        json.dumps(legacy_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    # Load reads from legacy when no new layout exists.
    loaded_legacy = rr._load_chunk_store("proj")
    assert loaded_legacy == legacy_payload

    # First save migrates: new layout appears, legacy file renamed to .legacy.bak.
    rr._save_chunk_store("proj", legacy_payload)
    assert (tmp_store / "proj" / "manifest.json").exists()
    assert not legacy_path.exists()
    assert (tmp_store / "proj_chunks.json.legacy.bak").exists()

    # Second load uses new layout.
    loaded_new = rr._load_chunk_store("proj")
    assert loaded_new == legacy_payload


def test_corrupted_jsonl_is_tolerated(tmp_store: Path) -> None:
    rr._save_chunk_store("proj", _sample_store())
    project_dir = tmp_store / "proj"
    manifest = json.loads((project_dir / "manifest.json").read_text("utf-8"))
    file_a = project_dir / manifest["materials"]["mat-A"]["relative_path"]
    # Append a malformed line.
    with file_a.open("a", encoding="utf-8") as fh:
        fh.write("\n{not json\n")

    loaded = rr._load_chunk_store("proj")
    # The two valid chunks survive; corrupted line is dropped silently.
    assert len(loaded["mat-A"]) == 2
    assert loaded["mat/B"] == _sample_store()["mat/B"]


def test_empty_store_loads_as_empty_dict(tmp_store: Path) -> None:
    assert rr._load_chunk_store("proj") == {}


def test_unsafe_material_id_does_not_escape_dir(tmp_store: Path) -> None:
    rr._save_chunk_store("proj", {"../evil": [{"chunk_id": "x", "content": "x"}]})
    project_dir = tmp_store / "proj"
    # No file should be created outside project_dir.
    siblings = list(tmp_store.iterdir())
    assert all(p == project_dir or p.is_file() for p in siblings)
    for child in project_dir.iterdir():
        assert ".." not in child.name


def test_concurrent_identical_saves_keep_manifest_consistent(tmp_store: Path) -> None:
    store = _sample_store()
    sync = threading.Barrier(2)
    errors: list[BaseException] = []

    def _writer() -> None:
        try:
            sync.wait(timeout=5)
            rr._save_chunk_store("proj", store)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=_writer), threading.Thread(target=_writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert rr._load_chunk_store("proj") == store
    _assert_manifest_sha_consistency(tmp_store / "proj")
