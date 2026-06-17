"""Runtime Literature Assistant tools backed by the local HTTP API."""

import time
from pathlib import Path
from typing import Any, Protocol

from ..audit import AuditLog
from ..backend_client import BackendClient
from ..result import safe_result


class BackendGetClient(Protocol):
    """Minimal HTTP client shape used by runtime tools."""

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a structured JSON response."""

    def get_text(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a structured text response."""

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a structured JSON response from a POST request."""


class RuntimeTools:
    """HTTP-first Literature Assistant runtime tool implementations."""

    def __init__(
        self,
        backend: BackendGetClient,
        audit: AuditLog | None = None,
    ) -> None:
        """Create runtime tools.

        Args:
            backend: Backend HTTP client. It must not expose credentials.
            audit: Optional audit writer. Tools still return safely when omitted.
        """
        self.backend = backend
        self.audit = audit

    def config_status(self) -> dict[str, Any]:
        """Return Literature Assistant backend health and configuration status."""
        started = time.perf_counter()
        backend_result = self.backend.get("/health")
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.config_status", {}, result, started, "/health")

    def list_projects(self) -> dict[str, Any]:
        """List Literature Assistant projects."""
        started = time.perf_counter()
        backend_result = self.backend.get("/resources/projects")
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.list_projects", {}, result, started, "/resources/projects")

    def list_materials(self, project_id: str) -> dict[str, Any]:
        """List project materials.

        Args:
            project_id: Literature Assistant project id.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        args = {"project_id": project_id}
        endpoint = "/resources/materials"
        backend_result = self.backend.get(endpoint, params={"project_id": project_id})
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.list_materials", args, result, started, endpoint)

    def read_material(self, material_id: str) -> dict[str, Any]:
        """Read a material record.

        Args:
            material_id: Literature Assistant material id.
        """
        started = time.perf_counter()
        material_id = self._require_non_empty(material_id, "material_id")
        args = {"material_id": material_id}
        endpoint = f"/resources/material/{material_id}"
        backend_result = self.backend.get(endpoint)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.read_material", args, result, started, endpoint)

    def get_material_chunks(
        self,
        project_id: str,
        material_id: str,
    ) -> dict[str, Any]:
        """Read chunks for a material.

        Args:
            project_id: Literature Assistant project id.
            material_id: Literature Assistant material id.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        material_id = self._require_non_empty(material_id, "material_id")
        args = {"project_id": project_id, "material_id": material_id}
        endpoint = f"/resources/material/{material_id}/chunks"
        backend_result = self.backend.get(endpoint, params={"project_id": project_id})
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.get_material_chunks", args, result, started, endpoint)

    def search_literature(
        self,
        project_id: str,
        query: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search existing project chunks without pre-ingestion.

        Args:
            project_id: Literature Assistant project id.
            query: Search query.
            top_k: Maximum results, 1 through 50.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        query = self._require_non_empty(query, "query")
        top_k = self._bounded_int(top_k, "top_k", minimum=1, maximum=50)
        args = {"project_id": project_id, "query": query[:200], "top_k": top_k}
        endpoint = "/resources/chunks/search"
        backend_result = self.backend.get(
            endpoint,
            params={
                "project_id": project_id,
                "query": query,
                "top_k": top_k,
                "ingest_mode": "none",
            },
        )
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.search_literature", args, result, started, endpoint)

    def ingest_then_search(
        self,
        project_id: str,
        query: str,
        top_k: int = 10,
        ingest_mode: str = "query",
        ingest_limit: int = 8,
    ) -> dict[str, Any]:
        """Pre-ingest pending project files, then search chunks.

        Args:
            project_id: Literature Assistant project id.
            query: Search query.
            top_k: Maximum results, 1 through 50.
            ingest_mode: Either "query" or "full".
            ingest_limit: Query-mode candidate limit, 1 through 128.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        query = self._require_non_empty(query, "query")
        top_k = self._bounded_int(top_k, "top_k", minimum=1, maximum=50)
        ingest_limit = self._bounded_int(ingest_limit, "ingest_limit", minimum=1, maximum=128)
        ingest_mode = self._ingest_mode(ingest_mode)
        args = {
            "project_id": project_id,
            "query": query[:200],
            "top_k": top_k,
            "ingest_mode": ingest_mode,
            "ingest_limit": ingest_limit,
        }
        endpoint = "/resources/chunks/search"
        backend_result = self.backend.get(
            endpoint,
            params={
                "project_id": project_id,
                "query": query,
                "top_k": top_k,
                "ingest_mode": ingest_mode,
                "ingest_limit": ingest_limit,
            },
        )
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.ingest_then_search", args, result, started, endpoint)

    def export_annotations_markdown(self, material_id: str) -> dict[str, Any]:
        """Export material annotations as Markdown.

        Args:
            material_id: Literature Assistant material id.
        """
        started = time.perf_counter()
        material_id = self._require_non_empty(material_id, "material_id")
        args = {"material_id": material_id}
        endpoint = f"/api/annotations/{material_id}/export.md"
        backend_result = self.backend.get_text(endpoint)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.export_annotations_markdown", args, result, started, endpoint)

    def get_material_file_base64(self, material_id: str) -> dict[str, Any]:
        """Read a small material source file as a base64 JSON envelope.

        Args:
            material_id: Literature Assistant material id.
        """
        started = time.perf_counter()
        material_id = self._require_non_empty(material_id, "material_id")
        args = {"material_id": material_id}
        endpoint = f"/resources/document/{material_id}/file_b64"
        backend_result = self.backend.get(endpoint)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.get_material_file_base64", args, result, started, endpoint)

    def list_figure_table_candidates(
        self,
        project_id: str,
        limit: int = 20,
        pixel_only: bool = False,
        render_pdf_fallback: bool = True,
    ) -> dict[str, Any]:
        """List visual figure/table candidates prepared by the backend.

        Args:
            project_id: Literature Assistant project id.
            limit: Maximum candidate count, 1 through 100 for MCP use.
            pixel_only: Whether to require pre-existing pixel assets.
            render_pdf_fallback: Whether backend may render PDF crops.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        limit = self._bounded_int(limit, "limit", minimum=1, maximum=100)
        args = {
            "project_id": project_id,
            "limit": limit,
            "pixel_only": bool(pixel_only),
            "render_pdf_fallback": bool(render_pdf_fallback),
        }
        endpoint = "/resources/figure-table-candidates"
        backend_result = self.backend.get(endpoint, params=args)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.list_figure_table_candidates", args, result, started, endpoint)

    def chat_ask(
        self,
        query: str,
        context: list[str] | None = None,
        project_id: str | None = None,
        ai_cost_profile: str = "aggressive",
    ) -> dict[str, Any]:
        """Call the backend-managed chat model without exposing credentials.

        Args:
            query: User prompt sent to the Literature Assistant chat route.
            context: Optional context snippets.
            project_id: Optional project id for project-aware backend prompts.
            ai_cost_profile: Backend cost profile, normally ``aggressive`` for MCP tools.
        """
        started = time.perf_counter()
        query = self._require_non_empty(query, "query")
        if context is None:
            context = []
        if not isinstance(context, list) or not all(isinstance(item, str) for item in context):
            raise ValueError("context must be a list of strings")
        payload: dict[str, Any] = {
            "query": query,
            "context": context,
            "ai_cost_profile": self._cost_profile(ai_cost_profile),
        }
        args: dict[str, Any] = {
            "query_preview": query[:200],
            "context_count": len(context),
            "ai_cost_profile": payload["ai_cost_profile"],
        }
        if project_id is not None and project_id.strip():
            payload["project_id"] = project_id.strip()
            args["project_id"] = project_id.strip()
        endpoint = "/chat/ask"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.chat_ask", args, result, started, endpoint)

    def _wrap_backend_result(self, backend_result: dict[str, Any]) -> dict[str, Any]:
        if backend_result.get("is_error") is True:
            return safe_result(
                backend_result.get("data"),
                error=True,
                error_code=backend_result.get("error_code"),
                message=backend_result.get("message"),
            )
        return safe_result(backend_result.get("data"))

    def _finish(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        started: float,
        endpoint: str,
    ) -> dict[str, Any]:
        if self.audit is not None:
            self.audit.log(
                tool_name=tool_name,
                args_summary={**args, "endpoint": endpoint},
                touched_paths=[],
                allow_block_reason="backend_http",
                result_preview=str(result.get("data")),
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_code=result.get("error_code"),
            )
        return result

    def _require_non_empty(self, value: str, name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} must be non-empty")
        return cleaned

    def _bounded_int(self, value: int, name: str, minimum: int, maximum: int) -> int:
        if not isinstance(value, int):
            raise ValueError(f"{name} must be an integer")
        if value < minimum or value > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return value

    def _ingest_mode(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "ingest_mode").lower()
        if cleaned not in {"query", "full"}:
            raise ValueError("ingest_mode must be query or full")
        return cleaned

    def _cost_profile(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "ai_cost_profile").lower()
        if cleaned not in {"balanced", "aggressive", "quality"}:
            raise ValueError("ai_cost_profile must be balanced, aggressive, or quality")
        return cleaned


def create_default_runtime_tools(
    audit_root: Path | None = None,
    base_url: str = "http://127.0.0.1:8000",
) -> RuntimeTools:
    """Create RuntimeTools with the default backend client."""
    audit = AuditLog(audit_root) if audit_root is not None else None
    return RuntimeTools(backend=BackendClient(base_url=base_url), audit=audit)
