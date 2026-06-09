"""Test G15: Wiki export endpoint (2026-05-26).

Verify POST /api/wiki/export creates Markdown zip archive.
"""

import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Add literature_assistant/core to sys.path
core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from python_adapter_server import app


@pytest.fixture
def client():
    """TestClient for API testing."""
    return TestClient(app)


@pytest.fixture
def mock_wiki_enabled():
    """Mock wiki_enabled to return True."""
    with patch("routers.wiki_router.wiki_enabled", return_value=True):
        yield


class TestWikiExportEndpoint:
    """G15: POST /api/wiki/export endpoint."""

    def test_export_success_default_path(self, client, mock_wiki_enabled, tmp_path):
        """Successful export with default path returns output_path."""
        with patch("routers.wiki_router._page_store") as mock_store_fn:
            mock_store = mock_store_fn.return_value
            mock_store.list_pages.return_value = []

            with patch("routers.wiki_router.WORKSPACE_ARTIFACTS_ROOT", tmp_path):
                resp = client.post("/api/wiki/export")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["page_count"] == 0
                assert "wiki_export_" in data["output_path"]
                assert data["errors"] == []

    def test_export_success_custom_path(self, client, mock_wiki_enabled, tmp_path):
        """Successful export with custom filename under wiki_exports."""
        custom_path = tmp_path / "wiki_exports" / "custom_export.zip"

        with patch("routers.wiki_router._page_store") as mock_store_fn:
            mock_store = mock_store_fn.return_value
            mock_store.list_pages.return_value = []

            with patch("routers.wiki_router.WORKSPACE_ARTIFACTS_ROOT", tmp_path):
                resp = client.post("/api/wiki/export?output_path=custom_export.zip")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["output_path"] == str(custom_path)

    def test_export_rejects_path_traversal_output_path(self, client, mock_wiki_enabled, tmp_path):
        """Endpoint output_path is a filename only, not an arbitrary write path."""
        with patch("routers.wiki_router._page_store") as mock_store_fn:
            mock_store = mock_store_fn.return_value
            mock_store.list_pages.return_value = []

            with patch("routers.wiki_router.WORKSPACE_ARTIFACTS_ROOT", tmp_path):
                resp = client.post("/api/wiki/export?output_path=../escape.zip")

        assert resp.status_code == 400

    def test_export_wiki_disabled(self, client):
        """Export when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.post("/api/wiki/export")
            assert resp.status_code == 404


class TestWikiExportFunction:
    """G15: export_wiki_markdown function."""

    def test_export_creates_zip_with_pages(self, tmp_path):
        """export_wiki_markdown creates zip with all pages."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown

        # Create test pages
        store = WikiPageStore(tmp_path / "wiki", create=True)
        (tmp_path / "wiki" / "synthesis").mkdir(parents=True)
        (tmp_path / "wiki" / "synthesis" / "page1.md").write_text("# Page 1\nContent 1")
        (tmp_path / "wiki" / "concept").mkdir(parents=True)
        (tmp_path / "wiki" / "concept" / "page2.md").write_text("# Page 2\nContent 2")

        # Export
        output_path = tmp_path / "export.zip"
        result = export_wiki_markdown(store, output_path)

        assert result["success"] is True
        assert result["page_count"] == 2
        assert result["output_path"] == str(output_path)
        assert result["errors"] == []

        # Verify zip contents
        assert output_path.exists()
        with zipfile.ZipFile(output_path, "r") as zf:
            names = zf.namelist()
            assert "synthesis/page1.md" in names
            assert "concept/page2.md" in names
            assert zf.read("synthesis/page1.md").decode() == "# Page 1\nContent 1"
            assert zf.read("concept/page2.md").decode() == "# Page 2\nContent 2"

    def test_export_empty_wiki(self, tmp_path):
        """export_wiki_markdown handles empty wiki."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown

        store = WikiPageStore(tmp_path / "wiki", create=True)
        output_path = tmp_path / "export.zip"

        result = export_wiki_markdown(store, output_path)

        assert result["success"] is True
        assert result["page_count"] == 0
        assert output_path.exists()

    def test_export_creates_parent_directory(self, tmp_path):
        """export_wiki_markdown creates parent directory if missing."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown

        store = WikiPageStore(tmp_path / "wiki", create=True)
        output_path = tmp_path / "nested" / "dir" / "export.zip"

        result = export_wiki_markdown(store, output_path)

        assert result["success"] is True
        assert output_path.exists()
        assert output_path.parent.exists()

    def test_export_rejects_directory_path(self, tmp_path):
        """export_wiki_markdown raises ValueError for directory path."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown

        store = WikiPageStore(tmp_path / "wiki", create=True)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with pytest.raises(ValueError, match="must be a file path"):
            export_wiki_markdown(store, output_dir)

    def test_export_handles_read_errors(self, tmp_path):
        """export_wiki_markdown continues on individual page read errors."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown
        from unittest.mock import MagicMock

        store = WikiPageStore(tmp_path / "wiki", create=True)
        (tmp_path / "wiki" / "synthesis").mkdir(parents=True)
        (tmp_path / "wiki" / "synthesis" / "page1.md").write_text("Content 1")

        # Mock read_page to fail for one page
        original_read = store.read_page
        def mock_read(path):
            if "page1" in str(path):
                raise IOError("Read failed")
            return original_read(path)
        store.read_page = mock_read

        output_path = tmp_path / "export.zip"
        result = export_wiki_markdown(store, output_path)

        assert result["success"] is False
        assert result["page_count"] == 0
        assert len(result["errors"]) > 0
        assert "Read failed" in result["errors"][0]
