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
        """Pages without permissions are public by default."""
        from wiki.permissions import can_read, can_write

        page_extra = {}

        # No permissions = public read
        assert can_read(page_extra, None) is True
        assert can_read(page_extra, "any_user") is True

        # No permissions = writable (backward compat)
        assert can_write(page_extra, None) is True
        assert can_write(page_extra, "any_user") is True
