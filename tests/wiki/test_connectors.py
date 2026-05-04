from __future__ import annotations

from pathlib import Path

import pytest

from literature_assistant.core.wiki.connectors.base import (
    ConnectorPermissionError,
    ensure_path_within_allowed_roots,
    format_connector_source_id,
)
from literature_assistant.core.wiki.connectors.endnote import get_endnote_connector_spec
from literature_assistant.core.wiki.connectors.markdown import MarkdownConnector
from literature_assistant.core.wiki.connectors.pdf_folder import PdfFolderConnector
from literature_assistant.core.wiki.connectors.zotero import get_zotero_connector_spec


def test_external_path_guard_requires_configured_root(tmp_path: Path) -> None:
    with pytest.raises(ConnectorPermissionError, match="configured root"):
        ensure_path_within_allowed_roots(tmp_path / "notes", ())


def test_external_path_guard_rejects_outside_path_without_leaking_it(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "private" / "notes"
    allowed.mkdir()
    outside.mkdir(parents=True)

    with pytest.raises(ConnectorPermissionError) as exc_info:
        ensure_path_within_allowed_roots(outside, (allowed,))

    assert "outside configured connector roots" in str(exc_info.value)
    assert str(outside) not in str(exc_info.value)


def test_markdown_connector_lists_reads_and_reports_dry_run_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "external"
    notes = workspace / "notes"
    notes.mkdir(parents=True)
    note_path = notes / "paper-a.md"
    note_path.write_text("# Paper A\n\nImportant note body.", encoding="utf-8")

    connector = MarkdownConnector(notes, allowed_roots=(workspace,))
    sources = connector.list_sources()

    assert len(sources) == 1
    assert sources[0].source_id.startswith("obsidian:")
    assert sources[0].source_type == "markdown"
    assert sources[0].title == "Paper A"
    assert sources[0].metadata["relative_path"] == "paper-a.md"
    assert connector.read_source(sources[0].source_id) == "# Paper A\n\nImportant note body."
    assert connector.extract_metadata(sources[0].source_id)["title"] == "Paper A"

    report = connector.dry_run_scan()

    assert report.connector == "obsidian"
    assert report.source_count == 1
    assert report.would_write is False
    assert report.source_ids == (sources[0].source_id,)


def test_markdown_connector_excludes_private_obsidian_and_template_notes(tmp_path: Path) -> None:
    workspace = tmp_path / "external"
    notes = workspace / "notes"
    notes.mkdir(parents=True)
    (notes / "keep.md").write_text("# Keep\n", encoding="utf-8")
    (notes / ".obsidian").mkdir()
    (notes / ".obsidian" / "workspace.md").write_text("# Private\n", encoding="utf-8")
    (notes / "templates").mkdir()
    (notes / "templates" / "paper-template.md").write_text("# Template\n", encoding="utf-8")
    (notes / "sketch.excalidraw.md").write_text("# Sketch\n", encoding="utf-8")

    connector = MarkdownConnector(notes, allowed_roots=(workspace,))
    sources = connector.list_sources()

    assert [source.metadata["relative_path"] for source in sources] == ["keep.md"]


def test_markdown_connector_handles_slug_collision_with_hash_suffix(tmp_path: Path) -> None:
    workspace = tmp_path / "external"
    notes = workspace / "notes"
    notes.mkdir(parents=True)
    (notes / "Paper A.md").write_text("# First\n", encoding="utf-8")
    (notes / "Paper-A.md").write_text("# Second\n", encoding="utf-8")

    connector = MarkdownConnector(notes, allowed_roots=(workspace,))
    source_ids = [source.source_id for source in connector.list_sources()]

    assert len(source_ids) == 2
    assert len(set(source_ids)) == 2
    assert source_ids[0] == "obsidian:paper-a"
    assert source_ids[1].startswith("obsidian:paper-a-")


def test_pdf_folder_connector_lists_metadata_without_content_extraction(tmp_path: Path) -> None:
    workspace = tmp_path / "external"
    pdfs = workspace / "pdfs"
    pdfs.mkdir(parents=True)
    pdf_path = pdfs / "Paper A.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    connector = PdfFolderConnector(pdfs, allowed_roots=(workspace,))
    sources = connector.list_sources()

    assert len(sources) == 1
    assert sources[0].source_id.startswith("pdf:")
    assert sources[0].source_type == "pdf"
    assert sources[0].title == "Paper A"
    assert sources[0].metadata["size_bytes"] == len(b"%PDF-1.4\n")

    with pytest.raises(NotImplementedError, match="PDF text extraction"):
        connector.read_source(sources[0].source_id)


def test_connector_dry_run_does_not_write_registry_or_page_store(tmp_path: Path) -> None:
    workspace = tmp_path / "external"
    notes = workspace / "notes"
    registry = workspace / "wiki_registry.sqlite"
    page_store = workspace / "pages"
    notes.mkdir(parents=True)
    (notes / "paper-a.md").write_text("# Paper A\n", encoding="utf-8")

    connector = MarkdownConnector(notes, allowed_roots=(workspace,))
    report = connector.dry_run_scan()

    assert report.source_count == 1
    assert report.would_write is False
    assert not registry.exists()
    assert not page_store.exists()


def test_connector_dry_run_sanitizes_private_read_error_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "external"
    notes = workspace / "notes"
    private_path = notes / "private" / "secret.md"
    notes.mkdir(parents=True)
    private_path.parent.mkdir()
    private_path.write_text("# Secret\n", encoding="utf-8")
    connector = MarkdownConnector(notes, allowed_roots=(workspace,))

    def raise_private_os_error(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError(f"cannot read {private_path}")

    monkeypatch.setattr(Path, "read_text", raise_private_os_error)

    report = connector.dry_run_scan()

    assert report.source_count == 0
    assert report.warnings == ("OSError: connector source could not be read",)
    assert str(private_path) not in report.warnings[0]


def test_connector_source_id_namespaces_do_not_collide() -> None:
    assert format_connector_source_id("obsidian", "Paper A") == "obsidian:paper-a"
    assert format_connector_source_id("pdf", "Paper A") == "pdf:paper-a"
    assert format_connector_source_id("obsidian", "Paper A") != format_connector_source_id("pdf", "Paper A")


def test_zotero_and_endnote_connector_specs_are_read_only_contracts() -> None:
    zotero = get_zotero_connector_spec()
    endnote = get_endnote_connector_spec()

    assert zotero.namespace == "zotero"
    assert endnote.namespace == "endnote"
    assert zotero.read_only is True
    assert endnote.read_only is True
    assert zotero.writes_user_library is False
    assert endnote.writes_user_library is False
    assert zotero.supports_content_read is False
    assert endnote.supports_content_read is False
    assert {field.field_name for field in zotero.readable_fields} >= {"item_key", "title", "notes", "annotations"}
    assert {field.field_name for field in endnote.readable_fields} >= {"record_id", "title", "database_generation"}
