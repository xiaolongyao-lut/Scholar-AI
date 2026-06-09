"""Test G2: Wiki page CRUD operations (2026-05-26).

Verify POST/PUT/DELETE /api/wiki/pages endpoints.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
def mock_wiki_service():
    """Mock WikiService for testing."""
    with patch("wiki.service.get_wiki_service") as mock_get:
        service = MagicMock()
        mock_get.return_value = service
        yield service


@pytest.fixture
def mock_wiki_enabled():
    """Mock wiki_enabled to return True."""
    with patch("routers.wiki_router.wiki_enabled", return_value=True):
        yield


class TestWikiPageCreate:
    """G2: POST /api/wiki/pages endpoint."""

    def test_create_page_success(self, client, mock_wiki_service, mock_wiki_enabled):
        """Successful create returns slug."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="synthesis-test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Test Page",
            body="Test content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T00:00:00Z",
        )
        mock_wiki_service.create_page.return_value = page

        resp = client.post(
            "/api/wiki/pages",
            json={
                "title": "Test Page",
                "kind": "synthesis",
                "body": "Test content",
                "status": "draft",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["slug"] == "synthesis-test-page"

    def test_create_page_already_exists(self, client, mock_wiki_service, mock_wiki_enabled):
        """Create duplicate page returns 409."""
        mock_wiki_service.create_page.side_effect = ValueError("Page already exists: synthesis-test")

        resp = client.post(
            "/api/wiki/pages",
            json={
                "title": "Test",
                "kind": "synthesis",
                "body": "Content",
            },
        )
        assert resp.status_code == 409

    def test_create_page_invalid_kind(self, client, mock_wiki_service, mock_wiki_enabled):
        """Create with invalid kind returns 400."""
        mock_wiki_service.create_page.side_effect = ValueError("'invalid' is not a valid WikiPageKind")

        resp = client.post(
            "/api/wiki/pages",
            json={
                "title": "Test",
                "kind": "invalid",
                "body": "Content",
            },
        )
        assert resp.status_code == 400

    def test_create_page_wiki_disabled(self, client, mock_wiki_service):
        """Create when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.post(
                "/api/wiki/pages",
                json={
                    "title": "Test",
                    "kind": "synthesis",
                    "body": "Content",
                },
            )
            assert resp.status_code == 404


class TestWikiPageUpdate:
    """G2: PUT /api/wiki/pages/{slug} endpoint."""

    def test_update_page_success(self, client, mock_wiki_service, mock_wiki_enabled):
        """Successful update returns slug."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="synthesis-test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Updated Title",
            body="Updated content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T01:00:00Z",
        )
        mock_wiki_service.update_page.return_value = page

        resp = client.put(
            "/api/wiki/pages/synthesis-test-page",
            json={
                "title": "Updated Title",
                "body": "Updated content",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["slug"] == "synthesis-test-page"

    def test_update_page_not_found(self, client, mock_wiki_service, mock_wiki_enabled):
        """Update non-existent page returns 404."""
        mock_wiki_service.update_page.side_effect = ValueError("Page not found: nonexistent")

        resp = client.put(
            "/api/wiki/pages/nonexistent",
            json={"title": "New Title"},
        )
        assert resp.status_code == 404

    def test_update_page_partial(self, client, mock_wiki_service, mock_wiki_enabled):
        """Partial update only changes specified fields."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="synthesis-test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.final,
            title="Test Page",
            body="Test content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T01:00:00Z",
        )
        mock_wiki_service.update_page.return_value = page

        resp = client.put(
            "/api/wiki/pages/synthesis-test-page",
            json={"status": "final"},
        )
        assert resp.status_code == 200

        # Verify only status was passed to service
        mock_wiki_service.update_page.assert_called_once()
        call_kwargs = mock_wiki_service.update_page.call_args.kwargs
        assert call_kwargs["status"] == "final"
        assert call_kwargs["title"] is None
        assert call_kwargs["body"] is None

    def test_update_page_wiki_disabled(self, client, mock_wiki_service):
        """Update when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.put(
                "/api/wiki/pages/test-page",
                json={"title": "New Title"},
            )
            assert resp.status_code == 404


class TestWikiPageDelete:
    """G2: DELETE /api/wiki/pages/{slug} endpoint."""

    def test_delete_page_success(self, client, mock_wiki_service, mock_wiki_enabled):
        """Successful delete returns slug."""
        mock_wiki_service.delete_page.return_value = None

        resp = client.delete("/api/wiki/pages/synthesis-test-page")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["slug"] == "synthesis-test-page"

    def test_delete_page_not_found(self, client, mock_wiki_service, mock_wiki_enabled):
        """Delete non-existent page returns 404."""
        mock_wiki_service.delete_page.side_effect = ValueError("Page not found: nonexistent")

        resp = client.delete("/api/wiki/pages/nonexistent")
        assert resp.status_code == 404

    def test_delete_page_wiki_disabled(self, client, mock_wiki_service):
        """Delete when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.delete("/api/wiki/pages/test-page")
            assert resp.status_code == 404


class TestWikiImport:
    """G16: POST /api/wiki/import local Markdown import endpoint."""

    def test_import_markdown_dry_run_plans_create(self, client, mock_wiki_service, mock_wiki_enabled, tmp_path):
        """Dry-run validates local Markdown and returns the planned wiki page."""
        source = tmp_path / "import-note.md"
        source.write_text("# Imported Note\n\nEvidence-backed note.", encoding="utf-8")
        mock_wiki_service.get_page.return_value = None

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post("/api/wiki/import", json={"source_paths": [str(source)]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["dry_run"] is True
        assert data["imported"] == 0
        assert data["skipped"] == 1
        assert data["errored"] == 0
        assert data["pages"][0]["title"] == "Imported Note"
        assert data["pages"][0]["slug"] == "synthesis-imported-note"
        assert data["pages"][0]["action"] == "planned_create"
        mock_wiki_service.create_page.assert_not_called()

    def test_import_markdown_apply_creates_private_page(self, client, mock_wiki_service, mock_wiki_enabled, tmp_path):
        """Apply mode creates a private page with import provenance."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        source = tmp_path / "source-note.md"
        source.write_text("# Source Note\n\nImported body.", encoding="utf-8")
        mock_wiki_service.get_page.return_value = None
        mock_wiki_service.create_page.return_value = WikiPage(
            stable_slug="synthesis-source-note",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Source Note",
            body="Imported body.",
            evidence_refs=(),
            source_hashes=("hash",),
            created_at_iso="2026-06-05T00:00:00Z",
            updated_at_iso="2026-06-05T00:00:00Z",
        )

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post(
                "/api/wiki/import?user_id=owner123",
                json={"source_paths": [str(source)], "dry_run": False},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 1
        assert data["pages"][0]["action"] == "created"
        call_kwargs = mock_wiki_service.create_page.call_args.kwargs
        assert call_kwargs["title"] == "Source Note"
        assert call_kwargs["kind"] == "synthesis"
        assert call_kwargs["status"] == "draft"
        assert call_kwargs["body"] == "# Source Note\n\nImported body."
        assert call_kwargs["extra"]["permissions"]["owner"] == "owner123"
        assert call_kwargs["extra"]["permissions"]["visibility"] == "private"
        assert call_kwargs["extra"]["import_source"]["type"] == "local_markdown"
        assert call_kwargs["extra"]["import_source"]["path"] == "source-note.md"
        assert len(call_kwargs["source_hashes"]) == 1

    def test_import_markdown_skips_existing_without_overwrite(self, client, mock_wiki_service, mock_wiki_enabled, tmp_path):
        """Existing slugs are skipped by default to avoid overwriting local wiki pages."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        source = tmp_path / "existing.md"
        source.write_text("# Existing\n\nReplacement body.", encoding="utf-8")
        mock_wiki_service.get_page.return_value = WikiPage(
            stable_slug="synthesis-existing",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.final,
            title="Existing",
            body="Original body.",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-06-05T00:00:00Z",
            updated_at_iso="2026-06-05T00:00:00Z",
        )

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post(
                "/api/wiki/import",
                json={"source_paths": [str(source)], "dry_run": False},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["skipped"] == 1
        assert data["pages"][0]["action"] == "skipped_exists"
        mock_wiki_service.update_page.assert_not_called()

    def test_import_markdown_blocks_protected_github_path(self, client, mock_wiki_service, mock_wiki_enabled, tmp_path):
        """Import refuses protected reference-repo paths even when they are under the repo root."""
        github_dir = tmp_path / "github" / "reference"
        github_dir.mkdir(parents=True)
        source = github_dir / "note.md"
        source.write_text("# Reference\n\nProtected.", encoding="utf-8")

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post("/api/wiki/import", json={"source_paths": [str(source)]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["errored"] == 1
        assert "protected workspace area" in data["pages"][0]["error"]
        mock_wiki_service.create_page.assert_not_called()

    def test_import_markdown_rejects_non_markdown_source(self, client, mock_wiki_service, mock_wiki_enabled, tmp_path):
        """Only Markdown files are accepted for the reduced G16 local slice."""
        source = tmp_path / "note.txt"
        source.write_text("Plain text", encoding="utf-8")

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post("/api/wiki/import", json={"source_paths": [str(source)]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["errored"] == 1
        assert "Markdown .md file" in data["pages"][0]["error"]

    def test_import_markdown_apply_writes_page_with_real_service(self, client, mock_wiki_enabled, tmp_path):
        """Apply mode can write a real generated wiki page in an isolated store."""
        from wiki.page_store import WikiPageStore
        from wiki.service import WikiService

        wiki_root = tmp_path / "wiki"
        service = WikiService(WikiPageStore(wiki_root, create=True))
        source = tmp_path / "local-source.md"
        source.write_text("# Local Source\n\nBody from local note.", encoding="utf-8")

        with patch("routers.wiki_router.REPO_ROOT", tmp_path), patch("wiki.service.get_wiki_service", return_value=service):
            resp = client.post(
                "/api/wiki/import?user_id=owner123",
                json={"source_paths": [str(source)], "dry_run": False},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 1
        page_file = wiki_root / "synthesis" / "synthesis-local-source.md"
        assert page_file.exists()
        text = page_file.read_text(encoding="utf-8")
        assert "Body from local note." in text
        assert '"owner": "owner123"' in text
        assert '"visibility": "private"' in text
        assert '"type": "local_markdown"' in text


class TestWikiServiceCRUD:
    """G2: WikiService CRUD methods."""

    def test_create_page_generates_slug(self, tmp_path):
        """create_page generates stable slug from title and kind."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        page = service.create_page(
            title="My Test Page",
            kind="synthesis",
            body="Test content",
        )

        assert page.stable_slug == "synthesis-my-test-page"
        assert page.title == "My Test Page"
        assert page.body == "Test content"
        assert page.kind.value == "synthesis"
        assert page.status.value == "draft"

    def test_create_page_duplicate_raises_error(self, tmp_path):
        """create_page raises ValueError for duplicate slug."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        service.create_page(title="Test", kind="synthesis", body="Content 1")

        with pytest.raises(ValueError, match="already exists"):
            service.create_page(title="Test", kind="synthesis", body="Content 2")

    def test_update_page_modifies_fields(self, tmp_path):
        """update_page modifies specified fields only."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        page = service.create_page(title="Test", kind="synthesis", body="Original")
        original_created = page.created_at_iso

        updated = service.update_page(page.stable_slug, body="Updated", status="final")

        assert updated.body == "Updated"
        assert updated.status.value == "final"
        assert updated.title == "Test"  # Unchanged
        assert updated.created_at_iso == original_created  # Unchanged
        assert updated.updated_at_iso != original_created  # Changed

    def test_update_page_records_version_history(self, tmp_path):
        """Create/update/delete append local version metadata sidecars."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        page = service.create_page(title="Versioned", kind="synthesis", body="Original")
        updated = service.update_page(page.stable_slug, body="Updated")
        service.delete_page(updated.stable_slug)

        versions = service.list_page_versions(page.stable_slug)
        assert [item["version"] for item in versions] == [1, 2, 3]
        assert [item["action"] for item in versions] == ["create", "update", "delete"]
        assert versions[0]["body_hash"] != versions[1]["body_hash"]

    def test_delete_page_removes_file(self, tmp_path):
        """delete_page removes page file."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        page = service.create_page(title="Test", kind="synthesis", body="Content")
        page_file = tmp_path / "synthesis" / f"{page.stable_slug}.md"
        assert page_file.exists()

        service.delete_page(page.stable_slug)
        assert not page_file.exists()

    def test_delete_page_not_found_raises_error(self, tmp_path):
        """delete_page raises ValueError for non-existent page."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        with pytest.raises(ValueError, match="not found"):
            service.delete_page("nonexistent")
