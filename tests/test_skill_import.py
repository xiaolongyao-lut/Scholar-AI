# -*- coding: utf-8 -*-
"""Tests for user skill import pipeline (TASK-185)."""

import json
from pathlib import Path
import zipfile

import pytest

from skills.importers.user_skill_importer import (
    import_user_skill,
    compute_directory_hash,
    validate_package_size,
    ImportResult,
)


MINIMAL_SKILL_MD = """---
id: test.import.skill
name: Test Import Skill
version: 1.0.0
kind: transform
description: A test skill for import validation
entry_mode: manual
ui_visibility: skill_assisted
supported_scopes: [selection]
---

# Test Import Skill

This is a test skill.
"""


@pytest.fixture
def managed_root(tmp_path: Path) -> Path:
    """Create a temporary managed root directory."""
    root = tmp_path / "managed_skills"
    root.mkdir()
    return root


@pytest.fixture
def valid_skill_dir(tmp_path: Path) -> Path:
    """Create a minimal valid skill package directory."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(MINIMAL_SKILL_MD, encoding="utf-8")
    (skill_dir / "prompts").mkdir()
    (skill_dir / "prompts" / "main.txt").write_text("You are a helpful assistant.", encoding="utf-8")
    return skill_dir


@pytest.fixture
def valid_skill_zip(tmp_path: Path, valid_skill_dir: Path) -> Path:
    """Create a zip package that wraps the skill in a single top-level directory."""
    zip_path = tmp_path / "my-skill.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("wrapped-skill/SKILL.md", (valid_skill_dir / "SKILL.md").read_text(encoding="utf-8"))
        archive.writestr(
            "wrapped-skill/prompts/main.txt",
            (valid_skill_dir / "prompts" / "main.txt").read_text(encoding="utf-8"),
        )
    return zip_path


class TestImportSuccess:
    def test_import_creates_target_dir(self, valid_skill_dir, managed_root):
        result = import_user_skill(valid_skill_dir, managed_root)
        assert result.success is True
        assert result.skill_id == "test.import.skill"
        assert (managed_root / "test.import.skill").exists()

    def test_import_writes_install_meta(self, valid_skill_dir, managed_root):
        result = import_user_skill(valid_skill_dir, managed_root)
        meta_path = managed_root / "test.import.skill" / ".install_meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["enabled"] is False
        assert meta["trust_level"] == "untrusted"
        assert meta["content_hash"] == result.content_hash

    def test_import_records_origin(self, valid_skill_dir, managed_root):
        result = import_user_skill(valid_skill_dir, managed_root, origin="github:user/repo")
        assert result.origin == "github:user/repo"

    def test_import_preserves_files(self, valid_skill_dir, managed_root):
        import_user_skill(valid_skill_dir, managed_root)
        target = managed_root / "test.import.skill"
        assert (target / "SKILL.md").exists()
        assert (target / "prompts" / "main.txt").exists()

    def test_import_accepts_zip_with_single_top_level_directory(self, valid_skill_zip, managed_root):
        result = import_user_skill(valid_skill_zip, managed_root)
        assert result.success is True
        assert result.skill_id == "test.import.skill"
        target = managed_root / "test.import.skill"
        assert (target / "SKILL.md").exists()
        assert (target / "prompts" / "main.txt").exists()


class TestImportOverwrite:
    def test_overwrite_creates_backup(self, valid_skill_dir, managed_root):
        # First import
        import_user_skill(valid_skill_dir, managed_root)
        # Second import should backup
        result = import_user_skill(valid_skill_dir, managed_root)
        assert result.success is True
        backup_dir = managed_root / ".rollback_snapshots"
        assert backup_dir.exists()
        backups = list(backup_dir.iterdir())
        assert len(backups) == 1


class TestImportFailure:
    def test_missing_skill_md(self, tmp_path, managed_root):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = import_user_skill(empty_dir, managed_root)
        assert result.success is False
        assert "SKILL.md" in result.errors[0]

    def test_invalid_manifest(self, tmp_path, managed_root):
        bad_dir = tmp_path / "bad-skill"
        bad_dir.mkdir()
        (bad_dir / "SKILL.md").write_text("---\nid: INVALID ID\n---\n", encoding="utf-8")
        result = import_user_skill(bad_dir, managed_root)
        assert result.success is False
        assert len(result.errors) > 0

    def test_invalid_zip_archive(self, tmp_path, managed_root):
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_text("not a zip archive", encoding="utf-8")
        result = import_user_skill(bad_zip, managed_root)
        assert result.success is False
        assert result.error_code == "INVALID_ZIP_ARCHIVE"
        assert "valid zip archive" in result.errors[0]

    def test_zip_path_traversal_is_rejected(self, tmp_path, managed_root):
        zip_path = tmp_path / "traversal.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("wrapped-skill/SKILL.md", MINIMAL_SKILL_MD)
            archive.writestr("../escape.txt", "blocked")
        result = import_user_skill(zip_path, managed_root)
        assert result.success is False
        assert result.error_code == "UNSAFE_ARCHIVE_ENTRY"
        assert any("traversal" in error.lower() for error in result.errors)


class TestHashAndSize:
    def test_directory_hash_deterministic(self, valid_skill_dir):
        h1 = compute_directory_hash(valid_skill_dir)
        h2 = compute_directory_hash(valid_skill_dir)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_size_validation_passes_small_package(self, valid_skill_dir):
        errors = validate_package_size(valid_skill_dir)
        assert errors == []


class TestHighRiskWarning:
    def test_high_risk_generates_warning(self, tmp_path, managed_root):
        skill_dir = tmp_path / "risky-skill"
        skill_dir.mkdir()
        md = (
            "---\n"
            "id: test.risky\n"
            "name: Risky Skill\n"
            "version: 1.0.0\n"
            "kind: transform\n"
            "description: A risky skill\n"
            "permissions:\n"
            "  network: true\n"
            "---\n"
            "\n"
            "# Risky\n"
        )
        (skill_dir / "SKILL.md").write_text(md, encoding="utf-8")
        result = import_user_skill(skill_dir, managed_root)
        assert result.success is True
        assert any("high-risk" in w for w in result.warnings)
