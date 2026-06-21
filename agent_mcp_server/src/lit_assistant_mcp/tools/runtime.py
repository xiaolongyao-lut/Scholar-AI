"""Runtime Literature Assistant tools backed by the local HTTP API."""

import json
import time
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from ..audit import AuditLog
from ..behavior_eval import build_behavior_eval_pack
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

    def post_binary(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a structured binary response from a POST request."""


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

    def health_check(self, include_live: bool = False) -> dict[str, Any]:
        """Return passive Scholar AI workflow readiness diagnostics."""
        started = time.perf_counter()
        args = {"include_live": bool(include_live)}
        endpoint = "/api/health/check"
        backend_result = self.backend.get(endpoint, params=args)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.health_check", args, result, started, endpoint)

    def zotero_attachment_health(
        self,
        zotero_data_dir: str,
        allowed_root: str | None = None,
        min_text_chars: int = 200,
        max_items: int = 500,
        write_reports: bool = True,
    ) -> dict[str, Any]:
        """Return read-only Zotero attachment health diagnostics."""
        started = time.perf_counter()
        zotero_data_dir = self._bounded_text(zotero_data_dir, "zotero_data_dir", max_chars=1000)
        normalized_allowed_root = None
        if allowed_root is not None and str(allowed_root).strip():
            normalized_allowed_root = self._bounded_text(allowed_root, "allowed_root", max_chars=1000)
        min_text_chars = self._bounded_int(min_text_chars, "min_text_chars", minimum=0, maximum=100000)
        max_items = self._bounded_int(max_items, "max_items", minimum=1, maximum=5000)
        args = {
            "zotero_data_dir": zotero_data_dir,
            "allowed_root": normalized_allowed_root,
            "min_text_chars": min_text_chars,
            "max_items": max_items,
            "write_reports": bool(write_reports),
        }
        endpoint = "/api/zotero/attachment-health"
        backend_result = self.backend.get(endpoint, params=args)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.zotero_attachment_health", args, result, started, endpoint)

    def list_projects(self) -> dict[str, Any]:
        """List Literature Assistant projects."""
        started = time.perf_counter()
        backend_result = self.backend.get("/resources/projects")
        result = self._wrap_backend_result(backend_result)
        if result.get("is_error") is not True:
            result = {
                **result,
                "data": self._project_list_for_mcp(result.get("data")),
            }
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

    def search_refs(
        self,
        project_id: str,
        query: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search existing project chunks and return MCP-safe refs only.

        Args:
            project_id: Literature Assistant project id.
            query: Search query.
            top_k: Maximum refs, 1 through 50.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        query = self._require_non_empty(query, "query")
        top_k = self._bounded_int(top_k, "top_k", minimum=1, maximum=50)
        args = {"project_id": project_id, "query": query[:200], "top_k": top_k}
        endpoint = "/resources/chunks/search-refs"
        backend_result = self.backend.get(
            endpoint,
            params={
                "project_id": project_id,
                "query": query,
                "top_k": top_k,
            },
        )
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.search_refs", args, result, started, endpoint)

    def evidence_pack_build(
        self,
        project_id: str,
        query: str,
        section_id: str | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Build a query-scoped evidence pack from backend-managed refs.

        Args:
            project_id: Literature Assistant project id.
            query: Research question or section-local retrieval query.
            section_id: Optional outline/draft section id for traceability.
            top_k: Maximum evidence refs, 1 through 50.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        query = self._require_non_empty(query, "query")
        top_k = self._bounded_int(top_k, "top_k", minimum=1, maximum=50)
        payload: dict[str, Any] = {
            "project_id": project_id,
            "query": query,
            "top_k": top_k,
        }
        if isinstance(section_id, str) and section_id.strip():
            payload["section_id"] = self._bounded_text(section_id, "section_id", max_chars=128)
        args = {
            "project_id": project_id,
            "query": query[:200],
            "section_id": payload.get("section_id"),
            "top_k": top_k,
        }
        endpoint = "/api/evidence-pack/build"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.evidence_pack_build", args, result, started, endpoint)

    def project_scan_folder(
        self,
        project_id: str,
        scan_mode: str = "fast",
        batch_size: int = 24,
        max_workers: int = 8,
    ) -> dict[str, Any]:
        """Submit project source-folder ingestion as a runtime job.

        Args:
            project_id: Literature Assistant project id with an existing
                backend-bound ``source_folder``.
            scan_mode: Either ``legacy`` or ``fast``.
            batch_size: Fast-mode batch size, 1 through 256.
            max_workers: Fast-mode worker count, 1 through 64.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        scan_mode = self._scan_mode(scan_mode)
        batch_size = self._bounded_int(batch_size, "batch_size", minimum=1, maximum=256)
        max_workers = self._bounded_int(max_workers, "max_workers", minimum=1, maximum=64)
        args = {
            "project_id": project_id,
            "scan_mode": scan_mode,
            "batch_size": batch_size,
            "max_workers": max_workers,
            "async_job": True,
        }
        endpoint = f"/resources/project/{project_id}/scan-folder"
        backend_result = self.backend.post_json(
            endpoint,
            payload={},
            params={
                "async_job": True,
                "scan_mode": scan_mode,
                "batch_size": batch_size,
                "max_workers": max_workers,
            },
        )
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.project_scan_folder", args, result, started, endpoint)

    def figures_candidates(
        self,
        project_id: str,
        limit: int = 20,
        pixel_only: bool = False,
        render_pdf_fallback: bool = True,
    ) -> dict[str, Any]:
        """List backend-derived figure/table candidates for a project.

        Args:
            project_id: Literature Assistant project id.
            limit: Maximum candidate count, 1 through 100 for MCP use.
            pixel_only: Whether candidates must already have pixel assets.
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
        endpoint = "/api/writing/figures/candidates"
        backend_result = self.backend.get(endpoint, params=args)
        result = self._wrap_backend_result(backend_result)
        result = self._with_runtime_outcome(
            tool_name="literature.figures_candidates",
            result=result,
            endpoint=endpoint,
            started=started,
            success_quality="refs_only",
            empty_next_action={
                "kind": "scan_folder",
                "message": "Scan the project source folder or enable PDF rendering before requesting figure/table candidates.",
                "tool_name": "literature.project_scan_folder",
                "args": {"project_id": project_id},
            },
        )
        return self._finish("literature.figures_candidates", args, result, started, endpoint)

    def figures_generate(
        self,
        project_id: str,
        candidate_ids: list[str] | None = None,
        max_items: int = 1,
        kind: str | None = None,
        overwrite_existing: bool = False,
    ) -> dict[str, Any]:
        """Materialize existing pixel-backed figure/table candidates.

        Args:
            project_id: Literature Assistant project id.
            candidate_ids: Optional candidate ids to materialize.
            max_items: Maximum assets to create, 1 through 20.
            kind: Optional ``figure`` or ``table`` filter.
            overwrite_existing: Whether existing asset paths may be duplicated.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        ids = self._bounded_text_list(candidate_ids, "candidate_ids", maximum=50, max_chars=160)
        max_items = self._bounded_int(max_items, "max_items", minimum=1, maximum=20)
        normalized_kind = self._figure_kind(kind)
        payload: dict[str, Any] = {
            "project_id": project_id,
            "candidate_ids": ids,
            "max_items": max_items,
            "overwrite_existing": bool(overwrite_existing),
        }
        if normalized_kind is not None:
            payload["kind"] = normalized_kind
        args = {
            "project_id": project_id,
            "candidate_id_count": len(ids),
            "max_items": max_items,
            "kind": normalized_kind,
            "overwrite_existing": bool(overwrite_existing),
        }
        endpoint = "/api/writing/figures/generate"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        result = self._with_runtime_outcome(
            tool_name="literature.figures_generate",
            result=result,
            endpoint=endpoint,
            started=started,
            success_quality="full",
            empty_count_key="generated_count",
            empty_next_action={
                "kind": "call_tool",
                "message": "List pixel-backed figure/table candidates before materializing assets.",
                "tool_name": "literature.figures_candidates",
                "args": {"project_id": project_id, "pixel_only": True},
            },
        )
        return self._finish("literature.figures_generate", args, result, started, endpoint)

    def citations_sources(self, project_id: str) -> dict[str, Any]:
        """List backend-managed citation source metadata for a project.

        Args:
            project_id: Literature Assistant project id.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        args = {"project_id": project_id}
        endpoint = "/api/writing/citations/sources"
        backend_result = self.backend.get(endpoint, params=args)
        result = self._wrap_backend_result(backend_result)
        result = self._with_runtime_outcome(
            tool_name="literature.citations_sources",
            result=result,
            endpoint=endpoint,
            started=started,
            success_quality="metadata_only",
            empty_next_action={
                "kind": "scan_folder",
                "message": "Scan or add project materials before expecting citation source metadata.",
                "tool_name": "literature.project_scan_folder",
                "args": {"project_id": project_id},
            },
        )
        return self._finish("literature.citations_sources", args, result, started, endpoint)

    def citations_detect_overlap(
        self,
        project_id: str,
        anchors: list[dict[str, Any]],
        threshold: float = 0.7,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        """Detect citation anchors that reuse the same or similar evidence.

        Args:
            project_id: Literature Assistant project id.
            anchors: Citation anchor objects with ``anchor_id`` and optional
                ``material_id``, ``chunk_id``, and bounded ``text``.
            threshold: Jaccard/exact-match threshold, 0.0 through 1.0.
            draft_id: Optional draft id for caller-side traceability.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        threshold = self._bounded_float(threshold, "threshold", minimum=0.0, maximum=1.0)
        normalized_anchors = self._citation_overlap_anchors(anchors)
        payload: dict[str, Any] = {
            "project_id": project_id,
            "threshold": threshold,
            "anchors": normalized_anchors,
        }
        if isinstance(draft_id, str) and draft_id.strip():
            payload["draft_id"] = self._bounded_text(draft_id, "draft_id", max_chars=128)
        args = {
            "project_id": project_id,
            "draft_id": payload.get("draft_id"),
            "threshold": threshold,
            "anchor_count": len(normalized_anchors),
        }
        endpoint = "/api/citations/detect_overlap"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        result = self._with_runtime_outcome(
            tool_name="literature.citations_detect_overlap",
            result=result,
            endpoint=endpoint,
            started=started,
            success_quality="full",
            empty_status="success",
            empty_reason="No overlapping citation anchors were detected.",
        )
        return self._finish("literature.citations_detect_overlap", args, result, started, endpoint)

    def academic_writing_lint(
        self,
        text: str | None = None,
        html: str | None = None,
        content_type: str = "manuscript",
        language: str = "auto",
        required_sections: list[str] | None = None,
        require_evidence_refs: bool = True,
        require_figure_table_formula_refs: bool = False,
        style_profile: str | None = None,
        audit_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check scholarly writing quality before export or submission.

        Args:
            text: Plain Markdown/text manuscript content.
            html: Optional HTML manuscript content.
            content_type: ``review``, ``introduction``, ``manuscript``, or
                ``section``.
            language: ``zh``, ``en``, or ``auto``.
            required_sections: Optional required scholarly section labels.
            require_evidence_refs: Whether citations/evidence anchors are
                required.
            require_figure_table_formula_refs: Whether figure, table, and
                equation references must all appear.
            style_profile: Optional journal/export style profile id.
            audit_context: Optional caller provenance. External MCP calls
                default to an agent-mediated audit context when omitted.
        """
        started = time.perf_counter()
        normalized_text = None
        normalized_html = None
        if isinstance(text, str) and text.strip():
            normalized_text = self._bounded_text(text, "text", max_chars=300000)
        if isinstance(html, str) and html.strip():
            normalized_html = self._bounded_text(html, "html", max_chars=300000)
        if normalized_text is None and normalized_html is None:
            raise ValueError("text or html must be non-empty")
        normalized_content_type = self._academic_content_type(content_type)
        normalized_language = self._academic_language(language)
        sections = self._bounded_text_list(
            required_sections,
            "required_sections",
            maximum=32,
            max_chars=120,
        )
        payload: dict[str, Any] = {
            "text": normalized_text,
            "html": normalized_html,
            "content_type": normalized_content_type,
            "language": normalized_language,
            "required_sections": sections,
            "require_evidence_refs": bool(require_evidence_refs),
            "require_figure_table_formula_refs": bool(require_figure_table_formula_refs),
            "style_profile": self._optional_style_profile(style_profile),
            "audit_context": self._academic_audit_context(audit_context),
        }
        args = {
            "content_type": normalized_content_type,
            "language": normalized_language,
            "required_sections": sections,
            "require_evidence_refs": bool(require_evidence_refs),
            "require_figure_table_formula_refs": bool(require_figure_table_formula_refs),
            "style_profile": payload["style_profile"],
            "audit_surface": payload["audit_context"]["invocation_surface"],
            "text_chars": len(normalized_text or ""),
            "html_chars": len(normalized_html or ""),
        }
        endpoint = "/api/linter/academic-writing"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.academic_writing_lint", args, result, started, endpoint)

    def outline_generate(
        self,
        project_id: str,
        topic: str,
        content_type: str = "academic",
        target_length: int | None = None,
        focus_areas: list[str] | None = None,
        existing_materials: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate an evidence-grounded project outline.

        Args:
            project_id: Literature Assistant project id.
            topic: Academic writing topic.
            content_type: Backend writing type, normally ``academic``.
            target_length: Optional target word count, 100 through 200000.
            focus_areas: Optional bounded focus terms.
            existing_materials: Optional material ids that must belong to the project.
        """
        started = time.perf_counter()
        project_id = self._require_non_empty(project_id, "project_id")
        topic = self._bounded_text(topic, "topic", max_chars=300)
        normalized_content_type = self._bounded_text(content_type, "content_type", max_chars=40)
        payload: dict[str, Any] = {
            "project_id": project_id,
            "topic": topic,
            "content_type": normalized_content_type,
            "focus_areas": self._bounded_text_list(focus_areas, "focus_areas", maximum=12, max_chars=120),
            "existing_materials": self._bounded_text_list(
                existing_materials,
                "existing_materials",
                maximum=50,
                max_chars=160,
            ),
        }
        if target_length is not None:
            payload["target_length"] = self._bounded_int(
                target_length,
                "target_length",
                minimum=100,
                maximum=200000,
            )
        args = {
            "project_id": project_id,
            "topic_preview": topic[:200],
            "content_type": normalized_content_type,
            "target_length": payload.get("target_length"),
            "focus_area_count": len(payload["focus_areas"]),
            "material_count": len(payload["existing_materials"]),
        }
        endpoint = "/api/writing/outline/generate"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.outline_generate", args, result, started, endpoint)

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

    def export_docx(
        self,
        html: str,
        title: str,
        style_profile: str = "gb_t_7714_review",
        verify_with_word: bool = False,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Export scholarly HTML as a DOCX artifact under MCP workflow storage.

        Args:
            html: Bounded TipTap-compatible HTML manuscript body.
            title: User-facing document title used for the download filename.
            style_profile: Journal/profile identifier understood by the backend.
            verify_with_word: Whether to request optional local Word verification.
            project_id: Optional project id required for project-scoped profiles.
        """
        started = time.perf_counter()
        html = self._bounded_text(html, "html", max_chars=500000)
        title = self._bounded_text(title, "title", max_chars=200)
        style_profile = self._style_profile(style_profile)
        payload = {
            "html": html,
            "title": title,
            "style_profile": style_profile,
            "verify_with_word": bool(verify_with_word),
        }
        if isinstance(project_id, str) and project_id.strip():
            payload["project_id"] = self._bounded_text(project_id, "project_id", max_chars=128)
        args = {
            "title": title[:120],
            "html_chars": len(html),
            "style_profile": style_profile,
            "verify_with_word": bool(verify_with_word),
            "project_id": payload.get("project_id"),
        }
        endpoint = "/api/export/docx"
        backend_result = self.backend.post_binary(endpoint, payload=payload)
        result = self._binary_docx_result(
            backend_result,
            title=title,
            style_profile=style_profile,
            started=started,
        )
        result = self._with_runtime_outcome(
            tool_name="literature.export_docx",
            result=result,
            endpoint=endpoint,
            started=started,
            success_quality="full",
            required_data_key="artifact_path",
            empty_status="failed",
            empty_reason="DOCX export did not return an artifact path.",
        )
        return self._finish("literature.export_docx", args, result, started, endpoint)

    def journal_style_spec_draft(
        self,
        project_id: str,
        journal_name: str,
        spec_text: str,
    ) -> dict[str, Any]:
        """Create a reviewable project-scoped journal style profile draft."""

        started = time.perf_counter()
        project_id = self._bounded_text(project_id, "project_id", max_chars=128)
        journal_name = self._bounded_text(journal_name, "journal_name", max_chars=160)
        spec_text = self._bounded_text(spec_text, "spec_text", max_chars=120000)
        payload = {
            "project_id": project_id,
            "journal_name": journal_name,
            "spec_text": spec_text,
        }
        args = {
            "project_id": project_id,
            "journal_name": journal_name,
            "spec_chars": len(spec_text),
        }
        endpoint = "/api/export/journal-style-specs/draft"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.journal_style_spec_draft", args, result, started, endpoint)

    def journal_style_spec_confirm(
        self,
        project_id: str,
        draft_id: str,
        confirmed_by: str = "mcp",
    ) -> dict[str, Any]:
        """Confirm a reviewable journal style profile draft."""

        started = time.perf_counter()
        project_id = self._bounded_text(project_id, "project_id", max_chars=128)
        draft_id = self._bounded_text(draft_id, "draft_id", max_chars=128)
        confirmed_by = self._bounded_text(confirmed_by, "confirmed_by", max_chars=120, allow_empty=True) or "mcp"
        payload = {
            "project_id": project_id,
            "draft_id": draft_id,
            "confirmed_by": confirmed_by,
        }
        endpoint = "/api/export/journal-style-specs/confirm"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish(
            "literature.journal_style_spec_confirm",
            {"project_id": project_id, "draft_id": draft_id, "confirmed_by": confirmed_by},
            result,
            started,
            endpoint,
        )

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

    def agent_bridge_status(self, limit: int = 20) -> dict[str, Any]:
        """Read the backend agent bridge status without large context payloads."""
        started = time.perf_counter()
        limit = self._bounded_int(limit, "limit", minimum=1, maximum=100)
        args = {"limit": limit}
        endpoint = "/api/agent-bridge/status"
        backend_result = self.backend.get(endpoint, params=args)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.agent_bridge_status", args, result, started, endpoint)

    def agent_request_create(
        self,
        intent: str,
        user_text: str = "",
        project_id: str | None = None,
        runtime_session_id: str | None = None,
        chat_session_id: str | None = None,
        route: str | None = None,
        resource_refs: list[dict[str, Any]] | None = None,
        agent_host: str = "mcp",
        source: str = "mcp",
        max_chars: int = 12000,
        max_chunks: int = 12,
        smart_read_conversation: bool = False,
        wiki_candidate: bool = False,
        graph_candidate: bool = False,
        evolution_capture: bool = True,
    ) -> dict[str, Any]:
        """Create a frontend-visible runtime job for external agent work."""
        started = time.perf_counter()
        intent = self._bounded_text(intent, "intent", max_chars=120)
        user_text = self._bounded_text(user_text, "user_text", max_chars=8000, allow_empty=True)
        max_chars = self._bounded_int(max_chars, "max_chars", minimum=100, maximum=40000)
        max_chunks = self._bounded_int(max_chunks, "max_chunks", minimum=1, maximum=50)
        refs = self._resource_refs(resource_refs)
        payload: dict[str, Any] = {
            "source": self._bounded_text(source, "source", max_chars=80),
            "agent_host": self._bounded_text(agent_host, "agent_host", max_chars=80),
            "intent": intent,
            "user_text": user_text,
            "resource_refs": refs,
            "context_budget": {
                "max_chars": max_chars,
                "max_chunks": max_chunks,
                "include_full_text": False,
            },
            "output_targets": {
                "runtime_job": True,
                "smart_read_conversation": bool(smart_read_conversation),
                "agent_workspace": True,
                "wiki_candidate": bool(wiki_candidate),
                "graph_candidate": bool(graph_candidate),
                "evolution_capture": bool(evolution_capture),
            },
        }
        for key, value in {
            "project_id": project_id,
            "runtime_session_id": runtime_session_id,
            "chat_session_id": chat_session_id,
            "route": route,
        }.items():
            if isinstance(value, str) and value.strip():
                payload[key] = value.strip()
        args = {
            "intent": intent,
            "user_text_preview": user_text[:200],
            "resource_ref_count": len(refs),
            "max_chars": max_chars,
            "max_chunks": max_chunks,
            "smart_read_conversation": bool(smart_read_conversation),
            "wiki_candidate": bool(wiki_candidate),
            "graph_candidate": bool(graph_candidate),
            "evolution_capture": bool(evolution_capture),
        }
        endpoint = "/api/agent-bridge/request"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.agent_request_create", args, result, started, endpoint)

    def single_paper_task_create(
        self,
        project_id: str,
        material_id: str,
        task_goal: str = "生成单篇论文深度精读、写作借鉴要点、可导出 Word 的结构化草稿",
        output_language: str = "zh",
        target_document: str = "word_draft",
        create_agent_request: bool = True,
        agent_host: str = "mcp",
        source: str = "mcp",
        max_chars: int = 12000,
        max_chunks: int = 12,
    ) -> dict[str, Any]:
        """Create a Scholar AI single-paper deep-reading task instance.

        Args:
            project_id: Existing Scholar AI project id.
            material_id: Existing material id within the project.
            task_goal: Goal statement embedded in the generated task.
            output_language: ``zh``, ``en``, or ``bilingual``.
            target_document: ``deep_summary`` or ``word_draft``.
            create_agent_request: Whether to create a runtime-visible job.
            agent_host: Audit label for the requesting agent host.
            source: Runtime filtering label for the invocation source.
            max_chars: Resource-read budget, 100 through 40000.
            max_chunks: Maximum indexed chunk refs, 1 through 50.
        """
        started = time.perf_counter()
        project_id = self._bounded_text(project_id, "project_id", max_chars=200)
        material_id = self._bounded_text(material_id, "material_id", max_chars=200)
        payload: dict[str, Any] = {
            "project_id": project_id,
            "material_id": material_id,
            "task_goal": self._bounded_text(task_goal, "task_goal", max_chars=500),
            "output_language": self._output_language(output_language),
            "target_document": self._single_paper_target_document(target_document),
            "create_agent_request": bool(create_agent_request),
            "agent_host": self._bounded_text(agent_host, "agent_host", max_chars=80),
            "source": self._bounded_text(source, "source", max_chars=80),
            "max_chars": self._bounded_int(max_chars, "max_chars", minimum=100, maximum=40000),
            "max_chunks": self._bounded_int(max_chunks, "max_chunks", minimum=1, maximum=50),
        }
        args = {
            "project_id": project_id,
            "material_id": material_id,
            "target_document": payload["target_document"],
            "create_agent_request": payload["create_agent_request"],
            "max_chars": payload["max_chars"],
            "max_chunks": payload["max_chunks"],
        }
        endpoint = "/api/agent-bridge/single-paper-task"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.single_paper_task_create", args, result, started, endpoint)

    def single_paper_completion_check(
        self,
        output_text: str,
        task_manifest: dict[str, Any],
        required_output_sections: list[str] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        figure_table_refs: list[dict[str, Any]] | None = None,
        lint_passed: bool = False,
        docx_artifact_path: str | None = None,
        sentinel: str = "待补充",
    ) -> dict[str, Any]:
        """Validate a completed single-paper deep-read draft locally.

        Args:
            output_text: Completed Markdown/plain-text draft.
            task_manifest: Manifest returned by ``single_paper_task_create``.
            required_output_sections: Optional section override.
            evidence_refs: Evidence refs attached to the draft.
            figure_table_refs: Figure/table refs attached to the draft.
            lint_passed: Whether academic writing lint has passed.
            docx_artifact_path: Optional local DOCX export artifact path.
            sentinel: Placeholder token that must be absent from final output.
        """
        started = time.perf_counter()
        manifest = self._optional_dict(task_manifest, "task_manifest")
        if not manifest:
            raise ValueError("task_manifest must be a non-empty object")
        payload: dict[str, Any] = {
            "output_text": self._bounded_text(output_text, "output_text", max_chars=120000),
            "task_manifest": manifest,
            "evidence_refs": self._dict_list(evidence_refs, "evidence_refs", maximum=200),
            "figure_table_refs": self._dict_list(figure_table_refs, "figure_table_refs", maximum=100),
            "lint_passed": bool(lint_passed),
            "sentinel": self._bounded_text(sentinel, "sentinel", max_chars=40),
        }
        sections = self._bounded_text_list(
            required_output_sections,
            "required_output_sections",
            maximum=30,
            max_chars=160,
        )
        if sections:
            payload["required_output_sections"] = sections
        if docx_artifact_path is not None and str(docx_artifact_path).strip():
            payload["docx_artifact_path"] = self._bounded_text(
                docx_artifact_path,
                "docx_artifact_path",
                max_chars=1000,
            )
        args = {
            "task_id": str(manifest.get("task_id") or "")[:120],
            "required_section_count": len(sections) or len(manifest.get("required_output_sections") or []),
            "evidence_ref_count": len(payload["evidence_refs"]),
            "figure_table_ref_count": len(payload["figure_table_refs"]),
            "lint_passed": payload["lint_passed"],
        }
        endpoint = "/api/agent-bridge/single-paper-task/completion-check"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.single_paper_completion_check", args, result, started, endpoint)

    def agent_request_list(
        self,
        status: str | None = None,
        project_id: str | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List runtime-visible agent requests with small job payloads."""
        started = time.perf_counter()
        limit = self._bounded_int(limit, "limit", minimum=1, maximum=200)
        params: dict[str, Any] = {"limit": limit}
        for key, value in {"status": status, "project_id": project_id, "source": source}.items():
            if isinstance(value, str) and value.strip():
                params[key] = value.strip()
        endpoint = "/api/agent-bridge/requests"
        backend_result = self.backend.get(endpoint, params=params)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.agent_request_list", params, result, started, endpoint)

    def agent_request_read(self, request_id: str) -> dict[str, Any]:
        """Read one agent request job by request id."""
        started = time.perf_counter()
        request_id = self._bounded_text(request_id, "request_id", max_chars=120)
        args = {"request_id": request_id}
        endpoint = f"/api/agent-bridge/request/{request_id}"
        backend_result = self.backend.get(endpoint)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.agent_request_read", args, result, started, endpoint)

    def agent_handoff_card(self, request_id: str) -> dict[str, Any]:
        """Read the resumable handoff card for one runtime-visible agent job."""
        started = time.perf_counter()
        request_id = self._bounded_text(request_id, "request_id", max_chars=120)
        args = {"request_id": request_id}
        request_endpoint = f"/api/agent-bridge/request/{request_id}"
        request_result = self.backend.get(request_endpoint)
        wrapped_request = self._wrap_backend_result(request_result)
        if wrapped_request.get("is_error") is True:
            return self._finish("literature.agent_handoff_card", args, wrapped_request, started, request_endpoint)
        request_data = wrapped_request.get("data")
        if not isinstance(request_data, dict):
            raise ValueError("agent request response must be an object")
        job_id = self._bounded_text(request_data.get("job_id"), "job_id", max_chars=160)
        endpoint = f"/runtime/job/{job_id}/agent-handoff-card"
        backend_result = self.backend.get(endpoint)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.agent_handoff_card", {**args, "job_id": job_id}, result, started, endpoint)

    def behavior_eval_pack(
        self,
        observations: list[dict[str, Any]] | None = None,
        include_cases: bool = True,
        write_record: bool = True,
    ) -> dict[str, Any]:
        """Run deterministic local behavior evals for MCP and agent outputs.

        Args:
            observations: Optional agent/MCP output objects. When omitted, the
                tool runs built-in unsafe canaries to verify the red-flag suite.
            include_cases: Whether to include the case manifest in the output.
            write_record: Whether to persist a local run record under
                ``workspace_artifacts`` when an audit root is configured.
        """
        started = time.perf_counter()
        bounded_observations = self._behavior_eval_observations(observations)
        payload = build_behavior_eval_pack(
            bounded_observations,
            include_cases=bool(include_cases),
        )
        record_path: str | None = None
        if write_record and self.audit is not None:
            record_path = self._write_behavior_eval_record(payload)
            payload["run_record"] = {"path": record_path}
        args = {
            "mode": payload["mode"],
            "observation_count": payload["summary"]["observation_count"],
            "include_cases": bool(include_cases),
            "write_record": bool(write_record),
            "record_path": record_path,
        }
        result = safe_result(payload)
        return self._finish("literature.behavior_eval_pack", args, result, started, "local://behavior-eval-pack")

    def workflow_passport(
        self,
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Read the workflow passport projection for runtime research state.

        Args:
            session_id: Optional runtime session filter.
            job_id: Optional runtime job filter.
            project_id: Optional Scholar AI project filter.
            limit: Maximum runtime records considered by the backend.
        """
        started = time.perf_counter()
        params = self._runtime_projection_params(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )
        endpoint = "/runtime/workflow-passport"
        backend_result = self.backend.get(endpoint, params=params)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.workflow_passport", params, result, started, endpoint)

    def evidence_integrity_gate(
        self,
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Read the evidence integrity gate projection for runtime research state.

        Args:
            session_id: Optional runtime session filter.
            job_id: Optional runtime job filter.
            project_id: Optional Scholar AI project filter.
            limit: Maximum runtime records considered by the backend.
        """
        started = time.perf_counter()
        params = self._runtime_projection_params(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )
        endpoint = "/runtime/evidence-integrity-gate"
        backend_result = self.backend.get(endpoint, params=params)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.evidence_integrity_gate", params, result, started, endpoint)

    def agent_resource_read(
        self,
        ref_id: str,
        project_id: str | None = None,
        max_chars: int = 6000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Read a bounded resource ref without returning full project context."""
        started = time.perf_counter()
        ref_id = self._bounded_text(ref_id, "ref_id", max_chars=240)
        max_chars = self._bounded_int(max_chars, "max_chars", minimum=100, maximum=20000)
        params: dict[str, Any] = {"max_chars": max_chars}
        if isinstance(project_id, str) and project_id.strip():
            params["project_id"] = project_id.strip()
        if isinstance(cursor, str) and cursor.strip():
            params["cursor"] = cursor.strip()
        args = {
            "ref_id": ref_id,
            "project_id": params.get("project_id"),
            "max_chars": max_chars,
            "cursor": params.get("cursor"),
        }
        endpoint = f"/api/agent-bridge/resource/{ref_id}"
        backend_result = self.backend.get(endpoint, params=params)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.agent_resource_read", args, result, started, endpoint)

    def agent_progress(
        self,
        request_id: str,
        stage: str,
        message: str,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write a short progress delta to a runtime-visible agent job."""
        started = time.perf_counter()
        request_id = self._bounded_text(request_id, "request_id", max_chars=120)
        stage = self._bounded_text(stage, "stage", max_chars=80)
        message = self._bounded_text(message, "message", max_chars=500)
        payload: dict[str, Any] = {"stage": stage, "message": message}
        if progress is not None:
            payload["progress"] = self._bounded_int(progress, "progress", minimum=0, maximum=100)
        if data is not None:
            if not isinstance(data, dict):
                raise ValueError("data must be an object")
            payload["data"] = data
        args = {"request_id": request_id, "stage": stage, "message_preview": message[:120]}
        endpoint = f"/api/agent-bridge/request/{request_id}/progress"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.agent_progress", args, result, started, endpoint)

    def agent_result(
        self,
        request_id: str,
        text: str = "",
        content: dict[str, Any] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        wiki_refs: list[dict[str, Any]] | None = None,
        graph_patch_refs: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write final agent output to runtime artifacts."""
        started = time.perf_counter()
        request_id = self._bounded_text(request_id, "request_id", max_chars=120)
        text = self._bounded_text(text, "text", max_chars=120000, allow_empty=True)
        if not text and content is None:
            raise ValueError("text or content must be provided")
        payload: dict[str, Any] = {
            "text": text,
            "evidence_refs": self._dict_list(evidence_refs, "evidence_refs", maximum=200),
            "wiki_refs": self._dict_list(wiki_refs, "wiki_refs", maximum=100),
            "graph_patch_refs": self._dict_list(graph_patch_refs, "graph_patch_refs", maximum=100),
            "metadata": self._optional_dict(metadata, "metadata"),
        }
        if content is not None:
            payload["content"] = self._optional_dict(content, "content")
        args = {"request_id": request_id, "text_preview": text[:200]}
        endpoint = f"/api/agent-bridge/request/{request_id}/result"
        backend_result = self.backend.post_json(endpoint, payload=payload)
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.agent_result", args, result, started, endpoint)

    def agent_fail(self, request_id: str, error: str) -> dict[str, Any]:
        """Fail a runtime-visible agent job with a redacted short error."""
        started = time.perf_counter()
        request_id = self._bounded_text(request_id, "request_id", max_chars=120)
        error = self._bounded_text(error, "error", max_chars=2000)
        args = {"request_id": request_id, "error_preview": error[:200]}
        endpoint = f"/api/agent-bridge/request/{request_id}/fail"
        backend_result = self.backend.post_json(endpoint, payload={"error": error})
        result = self._wrap_backend_result(backend_result)
        return self._finish("literature.agent_fail", args, result, started, endpoint)

    def _wrap_backend_result(self, backend_result: dict[str, Any]) -> dict[str, Any]:
        if backend_result.get("is_error") is True:
            return safe_result(
                backend_result.get("data"),
                error=True,
                error_code=backend_result.get("error_code"),
                message=backend_result.get("message"),
            )
        return safe_result(backend_result.get("data"))

    def _project_list_for_mcp(self, data: Any) -> Any:
        """Return project list data without local source-folder paths."""

        if not isinstance(data, list):
            return data
        return [self._project_for_mcp(item) for item in data]

    def _project_for_mcp(self, value: Any) -> Any:
        """Project payload projection for external MCP callers."""

        if not isinstance(value, dict):
            return value
        projected = dict(value)
        projected.pop("source_folder", None)
        source_ref = projected.get("source_folder_ref")
        if isinstance(source_ref, dict):
            projected["source_folder_ref"] = {
                key: str(source_ref[key])
                for key in ("display_name", "bound_at", "bound_by")
                if source_ref.get(key) is not None
            }
        return projected

    def _with_runtime_outcome(
        self,
        *,
        tool_name: str,
        result: dict[str, Any],
        endpoint: str,
        started: float,
        success_quality: str,
        empty_status: str = "empty",
        empty_reason: str = "Tool returned no usable data.",
        empty_next_action: dict[str, Any] | None = None,
        empty_count_key: str | None = None,
        required_data_key: str | None = None,
    ) -> dict[str, Any]:
        """Attach a ToolOutcome-compatible envelope without changing data shape."""

        if not isinstance(result, dict):
            raise ValueError("result must be an object")
        data = result.get("data")
        item_count = self._result_item_count(data, empty_count_key=empty_count_key)
        is_empty = self._result_is_empty(
            data,
            empty_count_key=empty_count_key,
            required_data_key=required_data_key,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        if result.get("is_error") is True:
            status = "failed"
            quality = "none"
            reason = str(result.get("message") or "Backend tool call failed.").strip()
            attempt_status = "failed"
            error_class = str(result.get("error_code") or "backend_error")
            next_action = {
                "kind": "retry_later",
                "message": "Inspect the backend error and rerun the tool after the local service is healthy.",
                "tool_name": None,
                "endpoint": endpoint,
                "command_preview": None,
                "args": {},
            }
        elif is_empty:
            status = empty_status
            quality = success_quality if empty_status == "success" else "none"
            reason = empty_reason
            attempt_status = "success" if empty_status == "success" else "skipped"
            error_class = "" if empty_status == "success" else "empty_result"
            next_action = self._normalized_next_action(empty_next_action)
        else:
            status = "success"
            quality = success_quality
            reason = "Tool completed with structured data."
            attempt_status = "success"
            error_class = ""
            next_action = self._normalized_next_action(None)
        outcome = {
            "schema_version": "scholar-ai-tool-outcome/v1",
            "status": status,
            "quality": quality,
            "reason": reason,
            "next_action": next_action,
            "attempts": [
                {
                    "stage": "backend_http",
                    "status": attempt_status,
                    "reason": reason,
                    "duration_ms": duration_ms,
                    "error_class": error_class,
                    "recommendation": str(next_action.get("message") or ""),
                    "metadata": {
                        "tool_name": tool_name,
                        "endpoint": endpoint,
                        "result_shape": type(data).__name__,
                        "item_count": item_count,
                    },
                }
            ],
        }
        return {**result, "outcome": outcome}

    def _normalized_next_action(self, value: dict[str, Any] | None) -> dict[str, Any]:
        """Return a ToolNextAction-compatible dict for runtime outcomes."""

        if value is None:
            return {
                "kind": "none",
                "message": "",
                "tool_name": None,
                "endpoint": None,
                "command_preview": None,
                "args": {},
            }
        if not isinstance(value, dict):
            raise ValueError("next action must be an object")
        return {
            "kind": str(value.get("kind") or "none"),
            "message": str(value.get("message") or "").strip()[:500],
            "tool_name": str(value["tool_name"]).strip()[:160] if value.get("tool_name") else None,
            "endpoint": str(value["endpoint"]).strip()[:260] if value.get("endpoint") else None,
            "command_preview": (
                str(value["command_preview"]).strip()[:500]
                if value.get("command_preview")
                else None
            ),
            "args": dict(value.get("args") or {}) if isinstance(value.get("args") or {}, dict) else {},
        }

    def _result_item_count(self, data: Any, *, empty_count_key: str | None = None) -> int:
        """Return a small count for result outcome metadata."""

        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            if empty_count_key is not None:
                raw_count = data.get(empty_count_key)
                if isinstance(raw_count, int) and not isinstance(raw_count, bool):
                    return max(0, raw_count)
            for key in ("generated_assets", "refs", "items", "evidence_refs"):
                raw_items = data.get(key)
                if isinstance(raw_items, list):
                    return len(raw_items)
            return 1 if data else 0
        if isinstance(data, str):
            return 1 if data.strip() else 0
        return 0 if data is None else 1

    def _result_is_empty(
        self,
        data: Any,
        *,
        empty_count_key: str | None = None,
        required_data_key: str | None = None,
    ) -> bool:
        """Return whether a backend result lacks usable payload for agents."""

        if required_data_key is not None:
            return not (isinstance(data, dict) and data.get(required_data_key))
        if isinstance(data, list):
            return len(data) == 0
        if isinstance(data, dict):
            if empty_count_key is not None:
                raw_count = data.get(empty_count_key)
                return not (isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count > 0)
            return len(data) == 0
        if isinstance(data, str):
            return not data.strip()
        return data is None

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
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} must be an integer")
        if value < minimum or value > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return value

    def _bounded_float(self, value: float, name: str, minimum: float, maximum: float) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be a number")
        numeric = float(value)
        if numeric < minimum or numeric > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return numeric

    def _ingest_mode(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "ingest_mode").lower()
        if cleaned not in {"query", "full"}:
            raise ValueError("ingest_mode must be query or full")
        return cleaned

    def _scan_mode(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "scan_mode").lower()
        if cleaned not in {"legacy", "fast"}:
            raise ValueError("scan_mode must be legacy or fast")
        return cleaned

    def _cost_profile(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "ai_cost_profile").lower()
        if cleaned not in {"balanced", "aggressive", "quality"}:
            raise ValueError("ai_cost_profile must be balanced, aggressive, or quality")
        return cleaned

    def _figure_kind(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = self._require_non_empty(value, "kind").lower()
        if cleaned not in {"figure", "table"}:
            raise ValueError("kind must be figure or table")
        return cleaned

    def _academic_content_type(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "content_type").lower()
        if cleaned not in {"review", "introduction", "manuscript", "section"}:
            raise ValueError("content_type must be review, introduction, manuscript, or section")
        return cleaned

    def _academic_language(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "language").lower()
        if cleaned not in {"zh", "en", "auto"}:
            raise ValueError("language must be zh, en, or auto")
        return cleaned

    def _optional_style_profile(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip().lower().replace("-", "_")
        if not cleaned:
            return None
        if len(cleaned) > 80 or not all(char.isalnum() or char == "_" for char in cleaned):
            raise ValueError("style_profile must be an identifier-like string up to 80 characters")
        return cleaned

    def _academic_audit_context(self, value: dict[str, Any] | None) -> dict[str, Any]:
        if value is not None and not isinstance(value, dict):
            raise ValueError("audit_context must be an object")
        context = dict(value or {})
        surface = str(context.get("invocation_surface") or "external_mcp").strip().lower()
        if surface not in {"direct_api", "external_mcp", "api_chat_local_tools", "unknown"}:
            raise ValueError("audit_context.invocation_surface is not supported")
        context["invocation_surface"] = surface
        context.setdefault("agent_host", "external-mcp")
        context.setdefault("source", "mcp")
        context["tool_chain"] = self._bounded_text_list(
            context.get("tool_chain") if isinstance(context.get("tool_chain"), list) else ["academic_writing_lint"],
            "audit_context.tool_chain",
            maximum=32,
            max_chars=120,
        )
        context["used_mcp_tools"] = self._bounded_text_list(
            context.get("used_mcp_tools")
            if isinstance(context.get("used_mcp_tools"), list)
            else ["literature.academic_writing_lint"],
            "audit_context.used_mcp_tools",
            maximum=64,
            max_chars=120,
        )
        for key, maximum in {"agent_host": 80, "source": 80, "project_id": 128}.items():
            value_for_key = context.get(key)
            if value_for_key is None:
                continue
            context[key] = self._bounded_text(str(value_for_key), f"audit_context.{key}", max_chars=maximum, allow_empty=True)
        if isinstance(context.get("retrieval_diagnostics"), dict):
            context["retrieval_diagnostics"] = self._retrieval_diagnostics(
                context["retrieval_diagnostics"]
            )
        else:
            context.pop("retrieval_diagnostics", None)
        if isinstance(context.get("reasoning_trace"), list):
            context["reasoning_trace"] = self._bounded_text_list(
                context["reasoning_trace"],
                "audit_context.reasoning_trace",
                maximum=16,
                max_chars=180,
            )
        else:
            context.pop("reasoning_trace", None)
        return context

    def _retrieval_diagnostics(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("retrieval_diagnostics must be an object")
        cleaned: dict[str, Any] = {}
        for key in ("retrieval_method", "embedding_status", "rerank_status", "fallback_reason"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                cleaned[key] = self._bounded_text(raw, f"retrieval_diagnostics.{key}", max_chars=240)
        for key in ("project_weight", "wiki_weight"):
            raw_number = value.get(key)
            if isinstance(raw_number, (int, float)) and not isinstance(raw_number, bool):
                cleaned[key] = max(0.0, min(1.0, float(raw_number)))
        for key in ("reasoning_trace", "notes"):
            raw_list = value.get(key)
            if isinstance(raw_list, list):
                cleaned[key] = self._bounded_text_list(
                    [str(item) for item in raw_list],
                    f"retrieval_diagnostics.{key}",
                    maximum=16,
                    max_chars=180,
                )
        joint = value.get("joint_recall")
        if isinstance(joint, dict):
            cleaned_joint = self._joint_recall_diagnostics(joint)
            if cleaned_joint:
                cleaned["joint_recall"] = cleaned_joint
        return cleaned

    def _joint_recall_diagnostics(self, value: dict[str, Any]) -> dict[str, Any]:
        """Return bounded joint project/wiki recall diagnostics for audit context."""

        if not isinstance(value, dict):
            raise ValueError("joint_recall must be an object")
        cleaned: dict[str, Any] = {}
        for key in ("enabled",):
            raw_bool = value.get(key)
            if isinstance(raw_bool, bool):
                cleaned[key] = raw_bool
        for key in ("status", "fusion_method", "reason"):
            raw_text = value.get(key)
            if isinstance(raw_text, str) and raw_text.strip():
                cleaned[key] = self._bounded_text(raw_text, f"joint_recall.{key}", max_chars=160)
        for key in (
            "project_weight",
            "wiki_weight",
            "wiki_share_after_fusion",
            "max_wiki_share_after_fusion",
        ):
            raw_number = value.get(key)
            if isinstance(raw_number, (int, float)) and not isinstance(raw_number, bool):
                cleaned[key] = max(0.0, min(1.0, float(raw_number)))
        for key in ("project_hit_count", "wiki_hit_count"):
            raw_count = value.get(key)
            if isinstance(raw_count, int) and not isinstance(raw_count, bool):
                cleaned[key] = max(0, min(100000, raw_count))
        source_counts = value.get("source_counts")
        if isinstance(source_counts, dict):
            cleaned["source_counts"] = {
                str(name)[:40]: max(0, min(100000, count))
                for name, count in source_counts.items()
                if isinstance(count, int) and not isinstance(count, bool)
            }
        top_doc_ids = value.get("top_doc_ids")
        if isinstance(top_doc_ids, list):
            cleaned["top_doc_ids"] = self._bounded_text_list(
                [str(item) for item in top_doc_ids],
                "joint_recall.top_doc_ids",
                maximum=12,
                max_chars=180,
            )
        wiki_summaries = value.get("wiki_summaries")
        if isinstance(wiki_summaries, list):
            cleaned_summaries: list[dict[str, Any]] = []
            for item in wiki_summaries[:5]:
                if not isinstance(item, dict):
                    continue
                summary: dict[str, Any] = {}
                for key, limit in {
                    "doc_id": 180,
                    "ref_id": 180,
                    "read_endpoint": 260,
                    "title": 160,
                    "summary": 300,
                    "page_path": 220,
                    "source": 80,
                }.items():
                    raw_text = item.get(key)
                    if isinstance(raw_text, str) and raw_text.strip():
                        summary[key] = self._bounded_text(raw_text, f"joint_recall.wiki_summaries.{key}", max_chars=limit)
                if summary:
                    cleaned_summaries.append(summary)
            if cleaned_summaries:
                cleaned["wiki_summaries"] = cleaned_summaries
        return cleaned

    def _style_profile(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "style_profile").lower().replace("-", "_")
        allowed = {"gb_t_7714_review", "ieee", "apa", "nature", "generic_academic"}
        if cleaned.startswith("custom_") and len(cleaned) <= 80 and all(
            char.isalnum() or char == "_" for char in cleaned
        ):
            return cleaned
        if cleaned not in allowed:
            raise ValueError(f"style_profile must be one of {sorted(allowed)}")
        return cleaned

    def _output_language(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "output_language").lower()
        if cleaned not in {"zh", "en", "bilingual"}:
            raise ValueError("output_language must be zh, en, or bilingual")
        return cleaned

    def _single_paper_target_document(self, value: str) -> str:
        cleaned = self._require_non_empty(value, "target_document").lower()
        if cleaned not in {"deep_summary", "word_draft"}:
            raise ValueError("target_document must be deep_summary or word_draft")
        return cleaned

    def _bounded_text(self, value: str, name: str, max_chars: int, allow_empty: bool = False) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        cleaned = value.strip()
        if not allow_empty and not cleaned:
            raise ValueError(f"{name} must be non-empty")
        if len(cleaned) > max_chars:
            raise ValueError(f"{name} must be at most {max_chars} characters")
        return cleaned

    def _optional_dict(self, value: dict[str, Any] | None, name: str) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError(f"{name} must be an object")
        return dict(value)

    def _dict_list(
        self,
        value: list[dict[str, Any]] | None,
        name: str,
        maximum: int,
    ) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError(f"{name} must be a list of objects")
        if len(value) > maximum:
            raise ValueError(f"{name} must contain at most {maximum} items")
        return [dict(item) for item in value]

    def _resource_refs(self, value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        refs = self._dict_list(value, "resource_refs", maximum=50)
        for item in refs:
            ref_id = str(item.get("ref_id") or "").strip()
            kind = str(item.get("kind") or "").strip()
            if not ref_id or not kind:
                raise ValueError("each resource ref must include ref_id and kind")
            item["ref_id"] = ref_id[:200]
            item["kind"] = kind[:80]
        return refs

    def _bounded_text_list(
        self,
        value: list[str] | None,
        name: str,
        maximum: int,
        max_chars: int,
    ) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{name} must be a list of strings")
        if len(value) > maximum:
            raise ValueError(f"{name} must contain at most {maximum} items")
        cleaned: list[str] = []
        for item in value:
            text = item.strip()
            if not text:
                continue
            if len(text) > max_chars:
                raise ValueError(f"{name} items must be at most {max_chars} characters")
            cleaned.append(text)
        return cleaned

    def _behavior_eval_observations(
        self,
        observations: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """Return bounded behavior-eval observations for local deterministic checks."""

        if observations is None:
            return None
        items = self._dict_list(observations, "observations", maximum=50)
        bounded: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            serialized = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            if len(serialized) > 50000:
                raise ValueError(f"observations[{index}] must serialize to at most 50000 characters")
            bounded.append(item)
        return bounded

    def _write_behavior_eval_record(self, payload: dict[str, Any]) -> str:
        """Persist one local behavior-eval run record under workspace artifacts."""

        if self.audit is None:
            raise ValueError("audit root is required to persist behavior eval records")
        root = self.audit.audit_root.parent / "behavior_eval_runs"
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = root / f"behavior-eval-{stamp}-{uuid4().hex[:8]}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return str(path)

    def _runtime_projection_params(
        self,
        *,
        session_id: str | None,
        job_id: str | None,
        project_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        """Return bounded query params for read-only runtime projections."""

        params: dict[str, Any] = {
            "limit": self._bounded_int(limit, "limit", minimum=1, maximum=1000),
        }
        for key, value in {
            "session_id": session_id,
            "job_id": job_id,
            "project_id": project_id,
        }.items():
            if value is None:
                continue
            params[key] = self._bounded_text(str(value), key, max_chars=200)
        return params

    def _citation_overlap_anchors(self, value: list[dict[str, Any]]) -> list[dict[str, str]]:
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError("anchors must be a list of objects")
        if len(value) > 200:
            raise ValueError("anchors must contain at most 200 items")
        normalized: list[dict[str, str]] = []
        for item in value:
            anchor_id = self._anchor_text_field(item, "anchor_id", max_chars=128, allow_empty=False)
            material_id = self._anchor_text_field(item, "material_id", max_chars=128, allow_empty=True)
            chunk_id = self._anchor_text_field(item, "chunk_id", max_chars=128, allow_empty=True)
            text = self._anchor_text_field(item, "text", max_chars=4096, allow_empty=True)
            normalized.append(
                {
                    "anchor_id": anchor_id,
                    "material_id": material_id,
                    "chunk_id": chunk_id,
                    "text": text,
                }
            )
        return normalized

    def _anchor_text_field(
        self,
        item: dict[str, Any],
        name: str,
        max_chars: int,
        allow_empty: bool,
    ) -> str:
        value = item.get(name)
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        return self._bounded_text(value, name, max_chars=max_chars, allow_empty=allow_empty)

    def _binary_docx_result(
        self,
        backend_result: dict[str, Any],
        *,
        title: str,
        style_profile: str,
        started: float,
    ) -> dict[str, Any]:
        if backend_result.get("is_error") is True:
            return self._wrap_backend_result(backend_result)
        data = backend_result.get("data")
        if not isinstance(data, dict):
            return safe_result(
                None,
                error=True,
                error_code="backend_openapi_mismatch",
                message="Backend returned malformed binary envelope",
            )
        content = data.get("content")
        if not isinstance(content, (bytes, bytearray)) or not content:
            return safe_result(
                None,
                error=True,
                error_code="backend_empty_export",
                message="Backend returned empty DOCX content",
            )
        output_path = self._export_output_path(title, style_profile=style_profile)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(bytes(content))
        headers = {str(key).lower(): str(value) for key, value in dict(data.get("headers") or {}).items()}
        return safe_result(
            {
                "artifact_path": str(output_path),
                "bytes": len(content),
                "style_profile": style_profile,
                "quality": headers.get("x-litassist-export-quality", ""),
                "content_type": headers.get("content-type", ""),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        )

    def _export_output_path(self, title: str, *, style_profile: str) -> Path:
        safe_title = "".join(
            char if char.isalnum() or char in "._- " else "_"
            for char in title.strip()
        ).strip(" ._")
        if not safe_title:
            safe_title = "export"
        safe_title = safe_title[:80]
        stamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"{safe_title}-{style_profile}-{stamp}-{uuid4().hex[:8]}.docx"
        if self.audit is not None:
            return self.audit.audit_root.parent / "exports" / filename
        return Path("workspace_artifacts").resolve() / "agent_mcp_workflows" / "exports" / filename


def create_default_runtime_tools(
    audit_root: Path | None = None,
    base_url: str | None = None,
) -> RuntimeTools:
    """Create RuntimeTools with the default backend client."""
    audit = AuditLog(audit_root) if audit_root is not None else None
    return RuntimeTools(backend=BackendClient(base_url=base_url), audit=audit)
