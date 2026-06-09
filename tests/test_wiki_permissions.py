"""Test G14: Wiki page permissions ACL (2026-05-26).

Verify GET/PUT /api/wiki/pages/{slug}/permissions endpoints.
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


def _write_wiki_page(
    wiki_root: Path,
    relative_path: str,
    *,
    title: str,
    body: str,
    owner: str,
    visibility: str,
) -> None:
    """Write a rendered test wiki page with explicit ACL metadata."""
    from wiki.page_store import WikiPageStore, render_page

    store = WikiPageStore(wiki_root, create=True)
    page_path = Path(relative_path)
    frontmatter = {
        "id": page_path.with_suffix("").as_posix(),
        "stable_slug": page_path.stem,
        "kind": page_path.parts[0] if len(page_path.parts) > 1 else "synthesis",
        "title": title,
        "status": "draft",
        "extra": {
            "permissions": {
                "owner": owner,
                "visibility": visibility,
                "shared_with": [],
            }
        },
    }
    store.write_rendered(render_page(page_path, frontmatter, body), allow_overwrite=True)


def _patch_router_page_store(wiki_root: Path):
    """Patch the wiki router to use a test page store rooted at wiki_root."""
    from wiki.page_store import WikiPageStore

    store = WikiPageStore(wiki_root, create=False)
    return patch("routers.wiki_router._page_store", return_value=store)


class TestGetWikiPagePermissions:
    """G14: GET /api/wiki/pages/{slug}/permissions endpoint."""

    def test_get_permissions_success(self, client, mock_wiki_service, mock_wiki_enabled):
        """Successful get returns owner/visibility/shared_with."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Test Page",
            body="Test content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T00:00:00Z",
            extra={
                "permissions": {
                    "owner": "user123",
                    "visibility": "public",
                    "shared_with": [],
                }
            },
        )
        mock_wiki_service.get_page.return_value = page

        resp = client.get("/api/wiki/pages/test-page/permissions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner"] == "user123"
        assert data["visibility"] == "public"
        assert data["shared_with"] == []

    def test_get_permissions_page_not_found(self, client, mock_wiki_service, mock_wiki_enabled):
        """Get permissions for non-existent page returns 404."""
        mock_wiki_service.get_page.return_value = None

        resp = client.get("/api/wiki/pages/nonexistent/permissions")
        assert resp.status_code == 404

    def test_get_permissions_access_denied(self, client, mock_wiki_service, mock_wiki_enabled):
        """Get permissions without read access returns 403."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="private-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Private Page",
            body="Private content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T00:00:00Z",
            extra={
                "permissions": {
                    "owner": "owner123",
                    "visibility": "private",
                    "shared_with": [],
                }
            },
        )
        mock_wiki_service.get_page.return_value = page

        resp = client.get("/api/wiki/pages/private-page/permissions?user_id=other_user")
        assert resp.status_code == 403

    def test_get_permissions_wiki_disabled(self, client, mock_wiki_service):
        """Get permissions when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.get("/api/wiki/pages/test-page/permissions")
            assert resp.status_code == 404


class TestUpdateWikiPagePermissions:
    """G14: PUT /api/wiki/pages/{slug}/permissions endpoint."""

    def test_update_permissions_success(self, client, mock_wiki_service, mock_wiki_enabled):
        """Successful update returns new permissions."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Test Page",
            body="Test content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T00:00:00Z",
            extra={
                "permissions": {
                    "owner": "user123",
                    "visibility": "public",
                    "shared_with": [],
                }
            },
        )
        mock_wiki_service.get_page.return_value = page

        resp = client.put(
            "/api/wiki/pages/test-page/permissions?user_id=user123",
            json={"visibility": "private", "shared_with": []},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner"] == "user123"
        assert data["visibility"] == "private"
        assert data["shared_with"] == []

        # Verify update_page_extra was called
        mock_wiki_service.update_page_extra.assert_called_once()

    def test_update_permissions_page_not_found(self, client, mock_wiki_service, mock_wiki_enabled):
        """Update permissions for non-existent page returns 404."""
        mock_wiki_service.get_page.return_value = None

        resp = client.put(
            "/api/wiki/pages/nonexistent/permissions?user_id=user123",
            json={"visibility": "private", "shared_with": []},
        )
        assert resp.status_code == 404

    def test_update_permissions_not_owner(self, client, mock_wiki_service, mock_wiki_enabled):
        """Update permissions by non-owner returns 403."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Test Page",
            body="Test content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T00:00:00Z",
            extra={
                "permissions": {
                    "owner": "owner123",
                    "visibility": "public",
                    "shared_with": [],
                }
            },
        )
        mock_wiki_service.get_page.return_value = page

        resp = client.put(
            "/api/wiki/pages/test-page/permissions?user_id=other_user",
            json={"visibility": "private", "shared_with": []},
        )
        assert resp.status_code == 403

    def test_update_permissions_invalid_visibility(self, client, mock_wiki_service, mock_wiki_enabled):
        """Update with invalid visibility returns 400."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Test Page",
            body="Test content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T00:00:00Z",
            extra={
                "permissions": {
                    "owner": "user123",
                    "visibility": "public",
                    "shared_with": [],
                }
            },
        )
        mock_wiki_service.get_page.return_value = page

        resp = client.put(
            "/api/wiki/pages/test-page/permissions?user_id=user123",
            json={"visibility": "invalid", "shared_with": []},
        )
        assert resp.status_code == 400

    def test_update_permissions_shared_with_users(self, client, mock_wiki_service, mock_wiki_enabled):
        """Update permissions with shared_with list."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Test Page",
            body="Test content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T00:00:00Z",
            extra={
                "permissions": {
                    "owner": "user123",
                    "visibility": "public",
                    "shared_with": [],
                }
            },
        )
        mock_wiki_service.get_page.return_value = page

        resp = client.put(
            "/api/wiki/pages/test-page/permissions?user_id=user123",
            json={"visibility": "shared", "shared_with": ["user456", "user789"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["visibility"] == "shared"
        assert set(data["shared_with"]) == {"user456", "user789"}

    def test_update_permissions_wiki_disabled(self, client, mock_wiki_service):
        """Update permissions when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.put(
                "/api/wiki/pages/test-page/permissions?user_id=user123",
                json={"visibility": "private", "shared_with": []},
            )
            assert resp.status_code == 404


class TestWikiPermissionsHelpers:
    """G14: Wiki permissions helper functions."""

    def test_can_read_public_page(self):
        """Public pages are readable by all users."""
        from wiki.permissions import can_read

        page_extra = {
            "permissions": {
                "owner": "user123",
                "visibility": "public",
                "shared_with": [],
            }
        }

        assert can_read(page_extra, None) is True
        assert can_read(page_extra, "user123") is True
        assert can_read(page_extra, "other_user") is True

    def test_can_read_private_page(self):
        """Private pages are readable only by owner."""
        from wiki.permissions import can_read

        page_extra = {
            "permissions": {
                "owner": "user123",
                "visibility": "private",
                "shared_with": [],
            }
        }

        assert can_read(page_extra, None) is False
        assert can_read(page_extra, "user123") is True
        assert can_read(page_extra, "other_user") is False

    def test_can_read_shared_page(self):
        """Shared pages are readable by owner and shared_with users."""
        from wiki.permissions import can_read

        page_extra = {
            "permissions": {
                "owner": "user123",
                "visibility": "shared",
                "shared_with": ["user456", "user789"],
            }
        }

        assert can_read(page_extra, None) is False
        assert can_read(page_extra, "user123") is True
        assert can_read(page_extra, "user456") is True
        assert can_read(page_extra, "user789") is True
        assert can_read(page_extra, "other_user") is False

    def test_can_write_owner_only(self):
        """Only owner can write to pages."""
        from wiki.permissions import can_write

        page_extra = {
            "permissions": {
                "owner": "user123",
                "visibility": "public",
                "shared_with": [],
            }
        }

        assert can_write(page_extra, None) is False
        assert can_write(page_extra, "user123") is True
        assert can_write(page_extra, "other_user") is False

    def test_permissions_backward_compat(self):
        """Pages without permissions fail closed to the local workspace owner."""
        from wiki.permissions import can_read, can_write

        page_extra = {}

        assert can_read(page_extra, None) is False
        assert can_read(page_extra, "local-user") is True
        assert can_read(page_extra, "other_user") is False

        assert can_write(page_extra, None) is False
        assert can_write(page_extra, "local-user") is True
        assert can_write(page_extra, "other_user") is False


class TestWikiPermissionEnforcement:
    """G14: Wiki ACL is enforced on read/list/search/export/graph paths."""

    def test_page_read_blocks_private_page_for_non_owner(self, client, mock_wiki_enabled, tmp_path):
        """Private page reads require the owner user id."""
        wiki_root = tmp_path / "wiki"
        _write_wiki_page(
            wiki_root,
            "synthesis/private-page.md",
            title="Private Page",
            body="private laser notes",
            owner="owner123",
            visibility="private",
        )

        with _patch_router_page_store(wiki_root):
            denied = client.get("/api/wiki/pages/synthesis/private-page?user_id=other_user")
            allowed = client.get("/api/wiki/pages/synthesis/private-page?user_id=owner123")

        assert denied.status_code == 403
        assert allowed.status_code == 200
        assert allowed.json()["frontmatter"]["title"] == "Private Page"

    def test_pages_list_filters_unreadable_pages(self, client, mock_wiki_enabled, tmp_path):
        """List responses never expose page titles outside the caller ACL."""
        wiki_root = tmp_path / "wiki"
        _write_wiki_page(
            wiki_root,
            "synthesis/public-page.md",
            title="Public Page",
            body="public body",
            owner="owner123",
            visibility="public",
        )
        _write_wiki_page(
            wiki_root,
            "synthesis/private-page.md",
            title="Private Page",
            body="private body",
            owner="owner123",
            visibility="private",
        )

        with _patch_router_page_store(wiki_root):
            response = client.get("/api/wiki/pages?user_id=other_user")

        assert response.status_code == 200
        titles = {page["title"] for page in response.json()["pages"]}
        assert titles == {"Public Page"}

    def test_query_filters_unreadable_fts_hits(self, client, mock_wiki_enabled, tmp_path):
        """FTS hits are filtered against the current wiki ACL before return."""
        from wiki.page_store import WikiPageStore
        from wiki.query import WikiQueryIndex, build_wiki_index

        wiki_root = tmp_path / "wiki"
        index_path = tmp_path / "runtime" / "wiki_query_index.db"
        _write_wiki_page(
            wiki_root,
            "synthesis/public-page.md",
            title="Public Laser",
            body="laser welding public notes",
            owner="owner123",
            visibility="public",
        )
        _write_wiki_page(
            wiki_root,
            "synthesis/private-page.md",
            title="Private Laser",
            body="laser welding private notes",
            owner="owner123",
            visibility="private",
        )
        store = WikiPageStore(wiki_root, create=False)
        index = WikiQueryIndex(index_path)
        build_wiki_index(store, index)
        index.close()

        with _patch_router_page_store(wiki_root), patch("routers.wiki_router.wiki_query_index_path", return_value=index_path):
            response = client.post("/api/wiki/search?user_id=other_user", json={"query": "laser"})

        assert response.status_code == 200
        refs = response.json()["evidence_refs"]
        assert [ref["title"] for ref in refs] == ["Public Laser"]

    def test_export_filters_unreadable_pages(self, client, mock_wiki_enabled, tmp_path):
        """Export archives include only pages readable by the caller."""
        import zipfile

        wiki_root = tmp_path / "wiki"
        output_path = tmp_path / "exports" / "wiki_exports" / "public-export.zip"
        _write_wiki_page(
            wiki_root,
            "synthesis/public-page.md",
            title="Public Page",
            body="public body",
            owner="owner123",
            visibility="public",
        )
        _write_wiki_page(
            wiki_root,
            "synthesis/private-page.md",
            title="Private Page",
            body="private body",
            owner="owner123",
            visibility="private",
        )

        with _patch_router_page_store(wiki_root), patch(
            "routers.wiki_router.WORKSPACE_ARTIFACTS_ROOT",
            tmp_path / "exports",
        ):
            response = client.post("/api/wiki/export?user_id=other_user&output_path=public-export.zip")

        assert response.status_code == 200
        assert response.json()["page_count"] == 1
        with zipfile.ZipFile(output_path, "r") as archive:
            assert archive.namelist() == ["synthesis/public-page.md"]

    def test_graph_filters_unreadable_nodes(self, client, mock_wiki_enabled, tmp_path):
        """Graph responses are built from the caller's readable page subset."""
        wiki_root = tmp_path / "wiki"
        _write_wiki_page(
            wiki_root,
            "synthesis/public-page.md",
            title="Public Page",
            body="public body",
            owner="owner123",
            visibility="public",
        )
        _write_wiki_page(
            wiki_root,
            "synthesis/private-page.md",
            title="Private Page",
            body="private body",
            owner="owner123",
            visibility="private",
        )

        with _patch_router_page_store(wiki_root):
            response = client.get("/api/wiki/graph?user_id=other_user")

        assert response.status_code == 200
        graph = response.json()["graph"]
        assert graph["node_count"] == 1
        assert graph["nodes"][0]["title"] == "Public Page"
