from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from literature_assistant.core import project_paths
from literature_assistant.core.wiki.backup import MANIFEST_NAME, build_wiki_backup_plan


def _seed_sqlite(path: Path) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO records (id, value) VALUES (?, ?)", ("row-1", "alpha"))
        conn.commit()


def test_wiki_backup_plan_dry_run_selects_runtime_and_generated_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    generated_root = tmp_path / "generated"
    monkeypatch.setattr(project_paths, "WORKSPACE_RUNTIME_STATE_ROOT", runtime_root)
    monkeypatch.setattr(project_paths, "WORKSPACE_GENERATED_ROOT", generated_root)

    wiki_runtime = runtime_root / "wiki"
    wiki_generated = generated_root / "wiki"
    wiki_runtime.mkdir(parents=True)
    wiki_generated.joinpath("sources").mkdir(parents=True)
    _seed_sqlite(wiki_runtime.joinpath("wiki.db"))
    wiki_runtime.joinpath("graph.json").write_text('{"nodes":[]}', encoding="utf-8")
    wiki_generated.joinpath("sources", "paper.md").write_text("# Paper\n", encoding="utf-8")

    report = build_wiki_backup_plan(
        archive_path=tmp_path / "backup.zip",
        runtime_root=wiki_runtime,
        generated_wiki_root=wiki_generated,
    )

    assert report.ok is True
    assert report.would_write is False
    assert not report.archive_path.exists()
    assert {file.role for file in report.files} >= {"registry_db", "graph_json", "wiki_page"}
    assert "generated/wiki/sources/paper.md" in {file.archive_path for file in report.files}


def test_wiki_backup_plan_write_creates_zip_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    generated_root = tmp_path / "generated"
    monkeypatch.setattr(project_paths, "WORKSPACE_RUNTIME_STATE_ROOT", runtime_root)
    monkeypatch.setattr(project_paths, "WORKSPACE_GENERATED_ROOT", generated_root)

    wiki_runtime = runtime_root / "wiki"
    wiki_generated = generated_root / "wiki"
    wiki_runtime.mkdir(parents=True)
    wiki_generated.joinpath("concepts").mkdir(parents=True)
    _seed_sqlite(wiki_runtime.joinpath("wiki.db"))
    wiki_generated.joinpath("concepts", "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    archive_path = tmp_path / "wiki-backup.zip"

    report = build_wiki_backup_plan(
        archive_path=archive_path,
        runtime_root=wiki_runtime,
        generated_wiki_root=wiki_generated,
        dry_run=False,
    )

    assert report.ok is True
    assert report.would_write is True
    assert archive_path.exists()
    assert report.manifest_path is not None
    assert report.manifest_path.exists()
    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert MANIFEST_NAME in names
    assert "runtime/wiki.db" in names
    assert "generated/wiki/concepts/alpha.md" in names
    assert manifest["file_count"] == len(report.files)


def test_wiki_backup_plan_rejects_invalid_archive_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=".zip"):
        build_wiki_backup_plan(archive_path=tmp_path / "backup")

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="not a directory"):
        build_wiki_backup_plan(archive_path=directory)


def test_wiki_backup_plan_skips_generated_file_outside_workspace(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    wiki_runtime = runtime_root / "wiki"
    wiki_generated = tmp_path / "generated" / "wiki"
    wiki_runtime.mkdir(parents=True)
    wiki_generated.joinpath("sources").mkdir(parents=True)
    _seed_sqlite(wiki_runtime.joinpath("wiki.db"))

    outside_root = Path.cwd().anchor and (tmp_path.parent / "outside-security-root")
    assert outside_root is not None
    outside_root.mkdir(parents=True, exist_ok=True)
    outside_file = outside_root / "paper.md"
    outside_file.write_text("# Outside\n", encoding="utf-8")

    linked_file = wiki_generated.joinpath("sources", "paper.md")
    try:
        linked_file.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"symlink creation not permitted in this Windows environment: {exc}")

    report = build_wiki_backup_plan(
        archive_path=tmp_path / "backup.zip",
        runtime_root=wiki_runtime,
        generated_wiki_root=wiki_generated,
    )

    archive_paths = {file.archive_path for file in report.files}
    assert "generated/wiki/sources/paper.md" not in archive_paths
    assert any(item.get("reason") == "outside_allowed_root" for item in report.missing)
