"""Test H1: Writing projects API alias (2026-05-27).

Verify /api/writing/projects aliases to /resources/projects.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

# Add literature_assistant/core to sys.path
core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))


class TestWritingProjectsAlias:
    """H1: /api/writing/projects alias."""

    def test_list_projects_endpoint_exists(self):
        """GET /api/writing/projects endpoint exists."""
        from routers.writing_router import router
        routes = [r.path for r in router.routes]
        assert "/api/writing/projects" in routes

    def test_get_project_endpoint_exists(self):
        """GET /api/writing/projects/{id} endpoint exists."""
        from routers.writing_router import router
        routes = [r.path for r in router.routes]
        assert "/api/writing/projects/{project_id}" in routes

    def test_create_project_endpoint_exists(self):
        """POST /api/writing/projects endpoint exists."""
        from routers.writing_router import router
        routes = [r.path for r in router.routes]
        methods = {r.path: r.methods for r in router.routes}
        assert "/api/writing/projects" in routes
        assert "POST" in methods.get("/api/writing/projects", set())

    def test_update_project_status_endpoint_exists(self):
        """PUT /api/writing/projects/{id}/status endpoint exists."""
        from routers.writing_router import router
        routes = [r.path for r in router.routes]
        assert "/api/writing/projects/{project_id}/status" in routes

    def test_delete_project_endpoint_exists(self):
        """DELETE /api/writing/projects/{id} endpoint exists."""
        from routers.writing_router import router
        routes = [r.path for r in router.routes]
        methods = {r.path: r.methods for r in router.routes}
        assert "/api/writing/projects/{project_id}" in routes
        assert "DELETE" in methods.get("/api/writing/projects/{project_id}", set())

    def test_retention_and_restore_aliases_exist(self):
        """The writing alias exposes explicit receipt and restore paths."""
        from routers.writing_router import router
        routes = [r.path for r in router.routes]
        assert "/api/writing/projects/{project_id}/retention" in routes
        assert "/api/writing/projects/{project_id}/restore" in routes

    def test_router_prefix_is_api_writing(self):
        """Router prefix is /api/writing."""
        from routers.writing_router import router
        assert router.prefix == "/api/writing"

    def test_delete_hides_project_and_restore_reads_persisted_receipt(self, tmp_path, monkeypatch):
        """Alias routes must pass concrete query values instead of FastAPI Query objects."""
        from literature_assistant.core.python_adapter_server import app
        from writing_resources import WritingResourceStore
        import routers.resources_router as resources_router

        store = WritingResourceStore(
            persistence_path=tmp_path / "state.json",
            database_path=tmp_path / "state.sqlite3",
            autosave=True,
        )
        project = store.create_project(title="Alias Retention", user_id="tester")
        monkeypatch.setattr(resources_router, "get_writing_resource_store", lambda: store)
        client = TestClient(app)

        response = client.delete(
            f"/api/writing/projects/{project.project_id}",
            params={"expected_updated_at": project.updated_at, "user_id": "tester"},
        )
        assert response.status_code == 200
        receipt = response.json()["receipt_id"]
        assert client.get("/api/writing/projects").json() == []
        assert client.get("/api/writing/projects", params={"include_archived": True}).json()[0]["status"] == "archived"

        archived = store.get_project(project.project_id, include_archived=True)
        assert archived is not None
        restored = client.post(
            f"/api/writing/projects/{project.project_id}/restore",
            params={
                "archive_receipt_id": receipt,
                "expected_updated_at": archived.updated_at,
                "user_id": "tester",
            },
        )
        assert restored.status_code == 200
        assert restored.json()["status"] == "draft"
