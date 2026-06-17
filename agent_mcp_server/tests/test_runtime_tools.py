"""Tests for runtime Literature Assistant tools."""

from pathlib import Path
from typing import Any

import pytest

from lit_assistant_mcp.audit import AuditLog
from lit_assistant_mcp.tools.runtime import RuntimeTools


class FakeBackend:
    """Small fake backend client for URL and params assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.responses: dict[tuple[str, str], dict[str, Any]] = {}

    def set_json(self, path: str, data: Any) -> None:
        self.responses[("json", path)] = {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": data,
        }

    def set_text(self, path: str, data: str) -> None:
        self.responses[("text", path)] = {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": data,
        }

    def set_error(self, path: str, error_code: str) -> None:
        self.responses[("json", path)] = {
            "is_error": True,
            "error_code": error_code,
            "message": "backend failed",
            "data": None,
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("json", path, params))
        return self.responses.get(
            ("json", path),
            {"is_error": False, "error_code": None, "message": None, "data": {"ok": True}},
        )

    def get_text(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("text", path, params))
        return self.responses.get(
            ("text", path),
            {"is_error": False, "error_code": None, "message": None, "data": "ok"},
        )

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("post_json", path, {"params": params, "payload": payload}))
        return self.responses.get(
            ("json", path),
            {"is_error": False, "error_code": None, "message": None, "data": {"ok": True}},
        )


@pytest.fixture
def backend() -> FakeBackend:
    """Create a fake backend."""
    return FakeBackend()


@pytest.fixture
def tools(tmp_path: Path, backend: FakeBackend) -> RuntimeTools:
    """Create runtime tools with audit enabled."""
    return RuntimeTools(
        backend=backend,
        audit=AuditLog(tmp_path / "workspace_artifacts/agent_mcp_workflows/.audit"),
    )


def test_config_status_calls_health(tools: RuntimeTools, backend: FakeBackend) -> None:
    """config_status calls /health."""
    backend.set_json("/health", {"status": "ok"})

    result = tools.config_status()

    assert result["is_error"] is False
    assert result["data"]["status"] == "ok"
    assert backend.calls[-1] == ("json", "/health", None)


def test_list_projects_uses_resources_prefix(tools: RuntimeTools, backend: FakeBackend) -> None:
    """list_projects calls the public /resources path."""
    backend.set_json("/resources/projects", [{"id": "p1"}])

    result = tools.list_projects()

    assert result["is_error"] is False
    assert result["data"][0]["id"] == "p1"
    assert backend.calls[-1] == ("json", "/resources/projects", None)


def test_list_materials_passes_project_id(tools: RuntimeTools, backend: FakeBackend) -> None:
    """list_materials sends project_id as a query param."""
    tools.list_materials("project-1")

    assert backend.calls[-1] == (
        "json",
        "/resources/materials",
        {"project_id": "project-1"},
    )


def test_read_material_path(tools: RuntimeTools, backend: FakeBackend) -> None:
    """read_material calls material endpoint."""
    tools.read_material("mat-1")

    assert backend.calls[-1] == ("json", "/resources/material/mat-1", None)


def test_get_material_chunks_path_and_params(tools: RuntimeTools, backend: FakeBackend) -> None:
    """get_material_chunks calls chunks endpoint."""
    tools.get_material_chunks("project-1", "mat-1")

    assert backend.calls[-1] == (
        "json",
        "/resources/material/mat-1/chunks",
        {"project_id": "project-1"},
    )


def test_search_literature_uses_ingest_none(tools: RuntimeTools, backend: FakeBackend) -> None:
    """search_literature never pre-ingests."""
    tools.search_literature("project-1", "query", top_k=7)

    assert backend.calls[-1] == (
        "json",
        "/resources/chunks/search",
        {
            "project_id": "project-1",
            "query": "query",
            "top_k": 7,
            "ingest_mode": "none",
        },
    )


def test_ingest_then_search_wraps_existing_search_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """ingest_then_search wraps chunks/search instead of a new route."""
    tools.ingest_then_search("project-1", "query", top_k=5, ingest_mode="full", ingest_limit=12)

    assert backend.calls[-1] == (
        "json",
        "/resources/chunks/search",
        {
            "project_id": "project-1",
            "query": "query",
            "top_k": 5,
            "ingest_mode": "full",
            "ingest_limit": 12,
        },
    )


def test_export_annotations_markdown_uses_text_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """export_annotations_markdown reads text Markdown."""
    backend.set_text("/api/annotations/mat-1/export.md", "# secret sk-" + "abc123def456ghi789jkl012mno345")

    result = tools.export_annotations_markdown("mat-1")

    assert result["is_error"] is False
    assert "sk-abc123" not in result["data"]
    assert backend.calls[-1] == ("text", "/api/annotations/mat-1/export.md", None)


def test_backend_error_is_preserved(tools: RuntimeTools, backend: FakeBackend) -> None:
    """Backend errors are returned as structured safe results."""
    backend.set_error("/resources/projects", "backend_unavailable")

    result = tools.list_projects()

    assert result["is_error"] is True
    assert result["error_code"] == "backend_unavailable"
    assert result["message"] == "backend failed"


def test_invalid_ingest_mode_rejected_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Only query/full modes are allowed for ingest_then_search."""
    with pytest.raises(ValueError, match="ingest_mode"):
        tools.ingest_then_search("project-1", "query", ingest_mode="none")

    assert backend.calls == []


def test_material_file_base64_uses_backend_file_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Runtime helper fetches file bytes through the backend boundary."""
    tools.get_material_file_base64("mat-1")

    assert backend.calls[-1] == ("json", "/resources/document/mat-1/file_b64", None)


def test_visual_candidates_uses_backend_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Runtime helper asks backend to prepare figure/table candidates."""
    tools.list_figure_table_candidates("project-1", limit=9, pixel_only=True, render_pdf_fallback=False)

    assert backend.calls[-1] == (
        "json",
        "/resources/figure-table-candidates",
        {
            "project_id": "project-1",
            "limit": 9,
            "pixel_only": True,
            "render_pdf_fallback": False,
        },
    )


def test_chat_ask_posts_to_backend_without_credentials(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Runtime chat helper delegates credential use to backend chat route."""
    backend.set_json("/chat/ask", {"answer": "ok", "model": "test"})

    result = tools.chat_ask("translate", context=["source"], project_id="project-1")

    assert result["is_error"] is False
    kind, path, payload = backend.calls[-1]
    assert kind == "post_json"
    assert path == "/chat/ask"
    assert payload["payload"] == {
        "query": "translate",
        "context": ["source"],
        "ai_cost_profile": "aggressive",
        "project_id": "project-1",
    }
    assert "api_key" not in str(payload)
