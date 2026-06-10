"""Tests for the frozen first-launch smoke host-APPDATA probe (plan §1 P1-3)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture
def probe():
    """Import the pure function from scripts/. The script lives outside
    the package; ensure scripts/ is on sys.path for the duration of the
    test session.
    """
    repo_root = Path(__file__).resolve().parent.parent
    scripts_dir = repo_root / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        from smoke_frozen_first_launch import probe_host_appdata  # type: ignore[import-not-found]
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass
    return probe_host_appdata


def test_missing_appdata_env_emits_warning(probe):
    findings = probe("")
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "host_appdata_env_missing"
    assert findings[0]["severity"] == "warning"


def test_missing_appdata_env_none_emits_warning(probe):
    findings = probe(None)
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "host_appdata_env_missing"


def test_clean_appdata_emits_no_findings(probe, tmp_path):
    # tmp_path has no LiteratureAssistant subdir → host APPDATA is "clean"
    assert probe(str(tmp_path)) == []


def test_appdata_with_literature_subdir_but_empty_is_clean(probe, tmp_path):
    (tmp_path / "LiteratureAssistant").mkdir()
    assert probe(str(tmp_path)) == []


def test_orphan_files_in_appdata_emit_warning(probe, tmp_path):
    la = tmp_path / "LiteratureAssistant"
    la.mkdir()
    (la / "writing_resources_state.sqlite3").write_bytes(b"orphan-data")
    (la / "workspace_artifacts").mkdir()
    (la / "workspace_artifacts" / "leftover.json").write_text("{}")
    findings = probe(str(tmp_path))
    assert len(findings) == 1
    finding = findings[0]
    assert finding["rule_id"] == "host_appdata_not_empty_pre_launch"
    assert finding["severity"] == "warning"
    # Both files should be listed.
    assert "writing_resources_state.sqlite3" in finding["files"]
    assert any("leftover.json" in f for f in finding["files"])
    # masked_snippet must not leak file *content*, only counts.
    assert "orphan-data" not in finding["masked_snippet"]
    assert "2" in finding["masked_snippet"]  # the count


def test_orphan_files_list_caps_at_twenty(probe, tmp_path):
    la = tmp_path / "LiteratureAssistant"
    la.mkdir()
    for i in range(30):
        (la / f"file_{i:02d}.bin").write_bytes(b"x")
    findings = probe(str(tmp_path))
    assert len(findings[0]["files"]) == 20
