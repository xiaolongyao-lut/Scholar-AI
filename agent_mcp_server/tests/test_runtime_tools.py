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

    def post_binary(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("post_binary", path, {"params": params, "payload": payload}))
        return self.responses.get(
            ("binary", path),
            {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": {
                    "content": b"PK\x03\x04fake-docx",
                    "headers": {
                        "content-type": (
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                        "x-litassist-export-quality": (
                            "citations=2;tables=1;captions=1;"
                            "style_profile=gb_t_7714_review;citation_style=numeric;"
                            "crossrefs=0;formulas=0;"
                            "word_verify=requested_unavailable"
                        ),
                        "x-litassist-action-preflight": (
                            '{"action_id":"export.docx","can_proceed":true,'
                            '"claim_status":"ready","gate_status":"pass",'
                            '"required_claim_id":"export_readiness",'
                            '"schema_version":"scholar_ai_action_preflight_v1",'
                            '"status":"ready"}'
                        ),
                    },
                    "status_code": 200,
                },
            },
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


def test_health_check_calls_passive_health_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """health_check should request passive diagnostics unless live is explicit."""

    backend.set_json(
        "/api/health/check",
        {"schema_version": "scholar-ai-health-check/v1", "status": "degraded"},
    )

    result = tools.health_check()

    assert result["is_error"] is False
    assert result["data"]["status"] == "degraded"
    assert backend.calls[-1] == ("json", "/api/health/check", {"include_live": False})


def test_health_check_forwards_explicit_live_flag(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Explicit live intent is forwarded as a bounded boolean query param."""

    tools.health_check(include_live=True)

    assert backend.calls[-1] == ("json", "/api/health/check", {"include_live": True})


def test_zotero_attachment_health_calls_read_only_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """zotero_attachment_health should delegate inspection to the backend route."""

    backend.set_json(
        "/api/zotero/attachment-health",
        {"schema_version": "scholar-ai-zotero-attachment-health/v1", "status": "degraded"},
    )

    result = tools.zotero_attachment_health(
        zotero_data_dir=" C:/Users/xiao/Zotero ",
        allowed_root=" C:/Users/xiao/Zotero ",
        min_text_chars=50,
        max_items=20,
        write_reports=False,
    )

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "json",
        "/api/zotero/attachment-health",
        {
            "zotero_data_dir": "C:/Users/xiao/Zotero",
            "allowed_root": "C:/Users/xiao/Zotero",
            "min_text_chars": 50,
            "max_items": 20,
            "write_reports": False,
        },
    )


def test_zotero_attachment_health_rejects_invalid_bounds_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """MCP Zotero diagnostics should reject malformed bounds locally."""

    with pytest.raises(ValueError, match="zotero_data_dir"):
        tools.zotero_attachment_health("")

    with pytest.raises(ValueError, match="max_items"):
        tools.zotero_attachment_health("C:/Users/xiao/Zotero", max_items=0)

    assert backend.calls == []


def test_list_projects_uses_resources_prefix(tools: RuntimeTools, backend: FakeBackend) -> None:
    """list_projects calls the public /resources path."""
    backend.set_json("/resources/projects", [{"id": "p1"}])

    result = tools.list_projects()

    assert result["is_error"] is False
    assert result["data"][0]["id"] == "p1"
    assert backend.calls[-1] == ("json", "/resources/projects", None)


def test_list_projects_removes_source_folder_paths_for_mcp(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """MCP project listings must not expose local absolute source-folder paths."""

    backend.set_json(
        "/resources/projects",
        [
            {
                "project_id": "project-1",
                "title": "Private Source Project",
                "source_folder": "C:/Users/xiao/Downloads/AlSi10Mg",
                "source_folder_ref": {
                    "path": "C:/Users/xiao/Downloads/AlSi10Mg",
                    "display_name": "AlSi10Mg",
                    "bound_at": "2026-06-18T00:00:00Z",
                    "bound_by": "desktop_picker",
                },
            }
        ],
    )

    result = tools.list_projects()

    assert result["is_error"] is False
    project = result["data"][0]
    assert "source_folder" not in project
    assert project["source_folder_ref"] == {
        "display_name": "AlSi10Mg",
        "bound_at": "2026-06-18T00:00:00Z",
        "bound_by": "desktop_picker",
    }
    assert "C:/Users/xiao" not in str(result["data"])


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


def test_search_refs_uses_pure_read_refs_endpoint(tools: RuntimeTools, backend: FakeBackend) -> None:
    """search_refs must call the backend refs endpoint without write/full-text flags."""
    tools.search_refs("project-1", "query", top_k=7)

    assert backend.calls[-1] == (
        "json",
        "/resources/chunks/search-refs",
        {
            "project_id": "project-1",
            "query": "query",
            "top_k": 7,
        },
    )
    assert "ingest_mode" not in str(backend.calls[-1])
    assert "include_content" not in str(backend.calls[-1])


def test_academic_writing_lint_posts_quality_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """academic_writing_lint should call the backend deterministic linter."""

    backend.set_json(
        "/api/linter/academic-writing",
        {"passed": True, "score": 91.0, "issues": []},
    )

    result = tools.academic_writing_lint(
        text="# 引言\n因此，该机制得到证据支持[chunk:c1]。图 1、表 1 和式（1）给出依据。",
        content_type="introduction",
        language="zh",
        required_sections=["引言"],
        require_figure_table_formula_refs=True,
        style_profile="GB-T-7714-Review",
    )

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "post_json",
        "/api/linter/academic-writing",
        {
            "params": None,
            "payload": {
                "text": "# 引言\n因此，该机制得到证据支持[chunk:c1]。图 1、表 1 和式（1）给出依据。",
                "html": None,
                "content_type": "introduction",
                "language": "zh",
                "required_sections": ["引言"],
                "require_evidence_refs": True,
                "require_figure_table_formula_refs": True,
                "style_profile": "gb_t_7714_review",
                "audit_context": {
                    "invocation_surface": "external_mcp",
                    "agent_host": "external-mcp",
                    "source": "mcp",
                    "tool_chain": ["academic_writing_lint"],
                    "used_mcp_tools": ["literature.academic_writing_lint"],
                },
            },
        },
    )


def test_academic_writing_lint_accepts_explicit_agent_audit_context(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """MCP callers can preserve prior writing-tool provenance in lint payloads."""

    backend.set_json(
        "/api/linter/academic-writing",
        {
            "passed": True,
            "score": 93.0,
            "audit": {"invocation_surface": "external_mcp"},
            "issues": [],
        },
    )

    result = tools.academic_writing_lint(
        text="# 综述\n证据包 evidence_pack:abc 表明该机制成立[chunk:c1]。因此，图 1、表 1 和式（1）给出依据。",
        content_type="review",
        language="zh",
        required_sections=["综述"],
        require_figure_table_formula_refs=True,
        style_profile="gb_t_7714_review",
        audit_context={
            "invocation_surface": "external_mcp",
            "agent_host": "codex",
            "source": "mcp",
            "project_id": "project-1",
            "tool_chain": ["search_refs", "evidence_pack_build", "academic_writing_lint"],
            "used_mcp_tools": ["literature.search_refs", "literature.evidence_pack_build"],
            "retrieval_diagnostics": {
                "retrieval_method": "hybrid_rerank",
                "embedding_status": "active",
                "rerank_status": "active",
                "project_weight": 0.4,
                "wiki_weight": 0.6,
                "joint_recall": {
                    "enabled": True,
                    "status": "active",
                    "fusion_method": "weighted_rrf",
                    "project_weight": 0.4,
                    "wiki_weight": 0.6,
                    "wiki_share_after_fusion": 0.6,
                    "project_hit_count": 2,
                    "wiki_hit_count": 5,
                    "source_counts": {"project": 2, "wiki": 3},
                    "top_doc_ids": ["chunk:c1", "wiki:synthesis/alsi10mg.md"],
                    "wiki_summaries": [
                        {
                            "ref_id": "wiki:synthesis/alsi10mg.md",
                            "read_endpoint": "/api/agent-bridge/resource/wiki:synthesis/alsi10mg.md",
                            "title": "AlSi10Mg synthesis",
                            "summary": "Bounded wiki note.",
                            "content": "SHOULD_NOT_FORWARD_RAW_WIKI_CONTENT",
                        }
                    ],
                    "raw_content": "SHOULD_NOT_FORWARD_RAW_JOINT_CONTENT",
                },
            },
        },
    )

    assert result["is_error"] is False
    payload = backend.calls[-1][2]["payload"]  # type: ignore[index]
    assert payload["audit_context"]["agent_host"] == "codex"
    assert payload["audit_context"]["project_id"] == "project-1"
    assert payload["audit_context"]["tool_chain"] == [
        "search_refs",
        "evidence_pack_build",
        "academic_writing_lint",
    ]
    assert payload["audit_context"]["used_mcp_tools"] == [
        "literature.search_refs",
        "literature.evidence_pack_build",
    ]
    diagnostics = payload["audit_context"]["retrieval_diagnostics"]
    assert diagnostics["retrieval_method"] == "hybrid_rerank"
    assert diagnostics["embedding_status"] == "active"
    assert diagnostics["rerank_status"] == "active"
    joint = diagnostics["joint_recall"]
    assert joint["enabled"] is True
    assert joint["fusion_method"] == "weighted_rrf"
    assert joint["source_counts"] == {"project": 2, "wiki": 3}
    assert joint["top_doc_ids"] == ["chunk:c1", "wiki:synthesis/alsi10mg.md"]
    assert joint["wiki_summaries"][0]["ref_id"] == "wiki:synthesis/alsi10mg.md"
    assert joint["wiki_summaries"][0]["read_endpoint"] == "/api/agent-bridge/resource/wiki:synthesis/alsi10mg.md"
    assert "content" not in joint["wiki_summaries"][0]
    assert "SHOULD_NOT_FORWARD" not in str(payload)


def test_evidence_pack_build_posts_bounded_query_payload(tools: RuntimeTools, backend: FakeBackend) -> None:
    """evidence_pack_build must delegate retrieval to the backend pack endpoint."""
    backend.set_json(
        "/api/evidence-pack/build",
        {
            "evidence_pack_ref": "evidence_pack:abc",
            "project_id": "project-1",
            "query": "query",
            "section_id": "intro",
            "retrieval_method": "lexical",
            "rerank_status": "unavailable",
            "total": 0,
            "truncated": False,
            "evidence_refs": [],
        },
    )

    result = tools.evidence_pack_build("project-1", "query", section_id="intro", top_k=7)

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "post_json",
        "/api/evidence-pack/build",
        {
            "params": None,
            "payload": {
                "project_id": "project-1",
                "query": "query",
                "top_k": 7,
                "section_id": "intro",
            },
        },
    )


def test_project_scan_folder_submits_runtime_job(tools: RuntimeTools, backend: FakeBackend) -> None:
    """project_scan_folder should submit scan-folder as an async runtime job."""
    backend.set_json(
        "/resources/project/project-1/scan-folder",
        {
            "runtime_job_ref": {"job_id": "job_1", "kind": "resource_ingest"},
            "status_url": "/runtime/job/job_1/snapshot",
        },
    )

    result = tools.project_scan_folder("project-1", scan_mode="legacy", batch_size=2, max_workers=3)

    assert result["is_error"] is False
    assert result["data"]["runtime_job_ref"]["kind"] == "resource_ingest"
    assert backend.calls[-1] == (
        "post_json",
        "/resources/project/project-1/scan-folder",
        {
            "params": {
                "async_job": True,
                "scan_mode": "legacy",
                "batch_size": 2,
                "max_workers": 3,
            },
            "payload": {},
        },
    )


def test_figures_candidates_uses_writing_alias_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """figures_candidates should read the writing route without creating jobs."""
    tools.figures_candidates("project-1", limit=9, pixel_only=True, render_pdf_fallback=False)

    assert backend.calls[-1] == (
        "json",
        "/api/writing/figures/candidates",
        {
            "project_id": "project-1",
            "limit": 9,
            "pixel_only": True,
            "render_pdf_fallback": False,
        },
    )


def test_figures_candidates_adds_actionable_empty_outcome(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Empty figure candidates should keep list data and add an outcome."""

    backend.set_json("/api/writing/figures/candidates", [])

    result = tools.figures_candidates("project-1")

    assert result["is_error"] is False
    assert result["data"] == []
    assert result["outcome"]["schema_version"] == "scholar-ai-tool-outcome/v1"
    assert result["outcome"]["status"] == "empty"
    assert result["outcome"]["quality"] == "none"
    assert result["outcome"]["next_action"]["kind"] == "scan_folder"
    assert result["outcome"]["next_action"]["tool_name"] == "literature.project_scan_folder"


def test_figures_generate_posts_synchronous_materialization_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """figures_generate should stay sync and only materialize existing candidates."""
    backend.set_json(
        "/api/writing/figures/generate",
        {"project_id": "project-1", "generated_count": 1, "generated_assets": []},
    )

    result = tools.figures_generate(
        "project-1",
        candidate_ids=[" fig-a ", "", "table-b"],
        max_items=2,
        kind="Figure",
        overwrite_existing=True,
    )

    assert result["is_error"] is False
    assert result["outcome"]["status"] == "success"
    assert result["outcome"]["quality"] == "full"
    assert backend.calls[-1] == (
        "post_json",
        "/api/writing/figures/generate",
        {
            "params": None,
            "payload": {
                "project_id": "project-1",
                "candidate_ids": ["fig-a", "table-b"],
                "max_items": 2,
                "kind": "figure",
                "overwrite_existing": True,
            },
        },
    )


def test_figures_generate_adds_next_action_when_no_assets_created(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Zero generated assets should be actionable without changing backend data."""

    backend.set_json(
        "/api/writing/figures/generate",
        {
            "project_id": "project-1",
            "generated_count": 0,
            "generated_assets": [],
            "skipped_candidate_ids": [],
            "message": "none",
        },
    )

    result = tools.figures_generate("project-1")

    assert result["data"]["generated_count"] == 0
    assert result["outcome"]["status"] == "empty"
    assert result["outcome"]["next_action"]["kind"] == "call_tool"
    assert result["outcome"]["next_action"]["tool_name"] == "literature.figures_candidates"


def test_citations_sources_uses_writing_metadata_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """citations_sources should list backend CSL metadata by project."""
    tools.citations_sources("project-1")

    assert backend.calls[-1] == (
        "json",
        "/api/writing/citations/sources",
        {"project_id": "project-1"},
    )


def test_citations_sources_adds_metadata_outcome(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Citation source listings should carry ToolOutcome-style diagnostics."""

    backend.set_json("/api/writing/citations/sources", [{"source_id": "src-1"}])

    result = tools.citations_sources("project-1")

    assert result["data"] == [{"source_id": "src-1"}]
    assert result["outcome"]["status"] == "success"
    assert result["outcome"]["quality"] == "metadata_only"
    assert result["outcome"]["attempts"][0]["metadata"]["item_count"] == 1


def test_citations_detect_overlap_posts_bounded_anchor_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """citations_detect_overlap should send a small deterministic overlap request."""
    tools.citations_detect_overlap(
        "project-1",
        anchors=[
            {
                "anchor_id": " a1 ",
                "material_id": "mat-1",
                "chunk_id": "chunk-1",
                "text": "shared evidence",
                "ignored": "not-forwarded",
            },
            {"anchor_id": "a2", "text": "shared evidence"},
        ],
        threshold=0.5,
        draft_id=" draft-1 ",
    )

    assert backend.calls[-1] == (
        "post_json",
        "/api/citations/detect_overlap",
        {
            "params": None,
            "payload": {
                "project_id": "project-1",
                "draft_id": "draft-1",
                "threshold": 0.5,
                "anchors": [
                    {
                        "anchor_id": "a1",
                        "material_id": "mat-1",
                        "chunk_id": "chunk-1",
                        "text": "shared evidence",
                    },
                    {
                        "anchor_id": "a2",
                        "material_id": "",
                        "chunk_id": "",
                        "text": "shared evidence",
                    },
                ],
            },
        },
    )


def test_citations_detect_overlap_empty_result_is_successful(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """No overlap is a successful diagnostic result, not a blocked state."""

    backend.set_json("/api/citations/detect_overlap", [])

    result = tools.citations_detect_overlap("project-1", anchors=[])

    assert result["data"] == []
    assert result["outcome"]["status"] == "success"
    assert result["outcome"]["reason"] == "No overlapping citation anchors were detected."


def test_outline_generate_posts_evidence_grounded_request(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """outline_generate should call the backend evidence-grounded outline route."""
    backend.set_json(
        "/api/writing/outline/generate",
        {"project_id": "project-1", "items": []},
    )

    result = tools.outline_generate(
        "project-1",
        topic=" AlSi10Mg fatigue literature review ",
        content_type="academic",
        target_length=6000,
        focus_areas=[" defect control ", "", " fatigue mechanisms "],
        existing_materials=[" mat-a ", "mat-b"],
    )

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "post_json",
        "/api/writing/outline/generate",
        {
            "params": None,
            "payload": {
                "project_id": "project-1",
                "topic": "AlSi10Mg fatigue literature review",
                "content_type": "academic",
                "target_length": 6000,
                "focus_areas": ["defect control", "fatigue mechanisms"],
                "existing_materials": ["mat-a", "mat-b"],
            },
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


def test_export_docx_posts_html_and_writes_artifact(
    tools: RuntimeTools,
    backend: FakeBackend,
    tmp_path: Path,
) -> None:
    """export_docx should return an artifact path instead of DOCX bytes."""

    result = tools.export_docx(
        html="<h1>引言</h1><p>证据支持该结论[chunk:abc]。</p>",
        title="AlSi10Mg Review",
        style_profile="GB-T-7714-Review",
        verify_with_word=True,
        project_id="project-1",
    )

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "post_binary",
        "/api/export/docx",
        {
            "params": None,
            "payload": {
                "html": "<h1>引言</h1><p>证据支持该结论[chunk:abc]。</p>",
                "title": "AlSi10Mg Review",
                "style_profile": "gb_t_7714_review",
                "verify_with_word": True,
                "project_id": "project-1",
                "require_action_preflight": False,
            },
        },
    )
    artifact_path = Path(result["data"]["artifact_path"])
    assert artifact_path.exists()
    assert artifact_path.read_bytes().startswith(b"PK\x03\x04")
    assert artifact_path.is_relative_to(tmp_path)
    assert result["data"]["bytes"] == len(b"PK\x03\x04fake-docx")
    assert result["data"]["quality"] == (
        "citations=2;tables=1;captions=1;style_profile=gb_t_7714_review;"
        "citation_style=numeric;crossrefs=0;formulas=0;word_verify=requested_unavailable"
    )
    assert result["data"]["action_preflight"]["schema_version"] == "scholar_ai_action_preflight_v1"
    assert result["data"]["action_preflight"]["can_proceed"] is True
    assert "content" not in result["data"]
    assert result["outcome"]["schema_version"] == "scholar-ai-tool-outcome/v1"
    assert result["outcome"]["status"] == "success"
    assert result["outcome"]["quality"] == "full"


def test_export_docx_can_request_hard_action_preflight(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """export_docx exposes an explicit hard preflight switch for agents."""

    result = tools.export_docx(
        html="<p>需要导出。</p>",
        title="Preflighted Review",
        project_id="project-1",
        require_action_preflight=True,
    )

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "post_binary",
        "/api/export/docx",
        {
            "params": None,
            "payload": {
                "html": "<p>需要导出。</p>",
                "title": "Preflighted Review",
                "style_profile": "gb_t_7714_review",
                "verify_with_word": False,
                "require_action_preflight": True,
                "project_id": "project-1",
            },
        },
    )


def test_journal_style_spec_tools_post_reviewable_profile_payloads(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """MCP style-spec tools should draft and confirm via backend contracts."""

    backend.set_json(
        "/api/export/journal-style-specs/draft",
        {
            "draft_id": "style_draft_1",
            "status": "draft",
            "profile": {"profile_id": "custom_ieee_abc12345"},
            "requires_confirmation": True,
        },
    )
    draft = tools.journal_style_spec_draft(
        "project-1",
        "IEEE Journal",
        "Use IEEE numeric references, Times New Roman 10 pt, and 1.9 cm margins.",
    )

    assert draft["is_error"] is False
    assert backend.calls[-1] == (
        "post_json",
        "/api/export/journal-style-specs/draft",
        {
            "params": None,
            "payload": {
                "project_id": "project-1",
                "journal_name": "IEEE Journal",
                "spec_text": "Use IEEE numeric references, Times New Roman 10 pt, and 1.9 cm margins.",
            },
        },
    )

    backend.set_json(
        "/api/export/journal-style-specs/confirm",
        {"status": "confirmed", "profile": {"profile_id": "custom_ieee_abc12345"}},
    )
    confirmed = tools.journal_style_spec_confirm("project-1", "style_draft_1", confirmed_by="agent")

    assert confirmed["is_error"] is False
    assert backend.calls[-1] == (
        "post_json",
        "/api/export/journal-style-specs/confirm",
        {
            "params": None,
            "payload": {
                "project_id": "project-1",
                "draft_id": "style_draft_1",
                "confirmed_by": "agent",
            },
        },
    )


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


def test_invalid_scan_mode_rejected_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Only legacy/fast scan modes are allowed for MCP scan submission."""
    with pytest.raises(ValueError, match="scan_mode"):
        tools.project_scan_folder("project-1", scan_mode="full")

    assert backend.calls == []


def test_invalid_figure_kind_rejected_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Only figure/table kinds are accepted for local asset generation."""
    with pytest.raises(ValueError, match="kind"):
        tools.figures_generate("project-1", kind="chart")

    assert backend.calls == []


def test_invalid_overlap_payload_rejected_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Overlap detection should reject malformed anchors before HTTP."""
    with pytest.raises(ValueError, match="anchor_id"):
        tools.citations_detect_overlap("project-1", anchors=[{"text": "missing id"}])

    with pytest.raises(ValueError, match="threshold"):
        tools.citations_detect_overlap("project-1", anchors=[], threshold=1.1)

    with pytest.raises(ValueError, match="text"):
        tools.citations_detect_overlap("project-1", anchors=[{"anchor_id": "a1", "text": {"bad": True}}])

    assert backend.calls == []


def test_invalid_outline_generate_payload_rejected_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """MCP outline generation should reject unbounded or empty inputs locally."""
    with pytest.raises(ValueError, match="topic"):
        tools.outline_generate("project-1", topic="")

    with pytest.raises(ValueError, match="target_length"):
        tools.outline_generate("project-1", topic="review", target_length=10)

    assert backend.calls == []


def test_invalid_export_docx_payload_rejected_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """MCP DOCX export should reject empty HTML and unknown style profiles."""

    with pytest.raises(ValueError, match="html"):
        tools.export_docx(html="", title="Title")

    with pytest.raises(ValueError, match="style_profile"):
        tools.export_docx(html="<p>ok</p>", title="Title", style_profile="unknown")

    assert backend.calls == []


def test_invalid_academic_writing_lint_payload_rejected_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Academic writing lint should reject malformed local inputs."""

    with pytest.raises(ValueError, match="text or html"):
        tools.academic_writing_lint(text="", html="")

    with pytest.raises(ValueError, match="content_type"):
        tools.academic_writing_lint(text="ok", content_type="blog")

    with pytest.raises(ValueError, match="language"):
        tools.academic_writing_lint(text="ok", language="fr")

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


def test_agent_request_create_posts_bounded_envelope(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Agent request creation should post a small envelope to the bridge route."""
    backend.set_json("/api/agent-bridge/request", {"request_id": "agentreq_1"})

    result = tools.agent_request_create(
        intent="smart_read_answer",
        user_text="compare methods",
        project_id="project-1",
        resource_refs=[{"ref_id": "material:abc", "kind": "material"}],
        max_chars=12000,
        max_chunks=8,
        smart_read_conversation=True,
        wiki_candidate=True,
        graph_candidate=True,
    )

    assert result["is_error"] is False
    kind, path, payload = backend.calls[-1]
    assert kind == "post_json"
    assert path == "/api/agent-bridge/request"
    assert payload["payload"]["intent"] == "smart_read_answer"
    assert payload["payload"]["context_budget"]["include_full_text"] is False
    assert payload["payload"]["resource_refs"] == [{"ref_id": "material:abc", "kind": "material"}]
    assert payload["payload"]["output_targets"]["smart_read_conversation"] is True
    assert payload["payload"]["output_targets"]["wiki_candidate"] is True
    assert payload["payload"]["output_targets"]["graph_candidate"] is True
    assert payload["payload"]["output_targets"]["evolution_capture"] is True


def test_agent_handoff_card_reads_runtime_card_by_request_id(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Agent handoff card reads the request job before fetching the runtime card."""

    backend.set_json(
        "/api/agent-bridge/request/agentreq_1",
        {
            "job_id": "job_agent_1",
            "metadata": {"agent_request_id": "agentreq_1"},
        },
    )
    backend.set_json(
        "/runtime/job/job_agent_1/agent-handoff-card",
        {
            "schema_version": "scholar_ai_agent_handoff_card_v1",
            "request_id": "agentreq_1",
            "job_id": "job_agent_1",
            "action_preflight": {
                "schema_version": "scholar_ai_action_preflight_v1",
                "action_id": "agent.handoff_card",
                "required_claim_id": "handoff_readiness",
                "blocking_action_boundary": {
                    "schema_version": "scholar_ai_blocking_action_boundary_v1",
                    "action_id": "agent.handoff_card",
                    "required_claim_id": "handoff_readiness",
                    "status": "blocked",
                    "can_proceed": False,
                    "recovery_drilldowns": [
                        {
                            "signal_id": "workflow_stage:agent_handoff",
                            "category": "workflow_stage",
                            "status": "block",
                            "linked_stage_id": "agent_handoff",
                            "source_ref": {"source_kind": "workflow_passport_stage"},
                            "checked_facts": {"requires_user_confirmation": True},
                            "evidence_refs": [
                                {"ref_type": "approval_gate", "ref_id": "approval:agent"}
                            ],
                            "replay_refs": [
                                {
                                    "ref_type": "preflight_refresh_receipt",
                                    "ref_id": "preflight_refresh:agent",
                                }
                            ],
                            "recovery_refs": [
                                {
                                    "ref_type": "workflow_passport_stage",
                                    "ref_id": "agent_handoff",
                                }
                            ],
                            "local_read_only_probes": [
                                {"endpoint": "/runtime/evidence-integrity-gate", "read_only": True}
                            ],
                            "next_safe_local_actions": ["Review handoff readiness before retry."],
                            "requires_human_review": True,
                            "blocks_claims": True,
                            "read_only": True,
                            "raw_path_exposed": False,
                        }
                    ],
                },
            },
            "replay_recovery": {
                "schema_version": "scholar_ai_agent_handoff_replay_recovery_v1",
                "index": {"index_is_read_only": True, "requires_exact_job_id": False},
                "highest_priority_attempt": {"job_id": "job_agent_1", "latest_status": "blocked"},
                "resume_probes": [{"endpoint": "/runtime/workflow-replay-index", "read_only": True}],
                "read_only": True,
            },
            "action_lifecycle_recovery": {
                "schema_version": "scholar_ai_handoff_action_lifecycle_recovery_v1",
                "read_only": True,
                "action_ref_count": 1,
                "pending_confirmation_count": 1,
                "blocked_action_count": 1,
                "missing_preflight_count": 0,
                "action_refs": [
                    {
                        "ref_type": "research_action_lifecycle",
                        "action_type": "agent_handoff",
                        "action_id": "agent.handoff_card",
                        "status": "pending_approval",
                        "job_id": "job_agent_1",
                        "probe_endpoint": "/runtime/research-action-lifecycle",
                        "read_only": True,
                    }
                ],
                "resume_probes": [
                    {"endpoint": "/runtime/research-action-lifecycle", "read_only": True}
                ],
                "forbidden_actions": [
                    "Do not execute approvals from the lifecycle projection.",
                    "Do not write import-to-wiki content from the handoff card.",
                ],
            },
            "resume_probes": [{"endpoint": "/runtime/job/job_agent_1/snapshot"}],
            "provenance": {
                "derived_from": [
                    "runtime.agent_request",
                    "runtime.research_action_lifecycle_refs",
                ],
                "external_mutation": False,
                "source_material_mutation": False,
            },
        },
    )

    result = tools.agent_handoff_card("agentreq_1")

    assert result["is_error"] is False
    assert result["data"]["job_id"] == "job_agent_1"
    boundary = result["data"]["action_preflight"]["blocking_action_boundary"]
    drilldown = boundary["recovery_drilldowns"][0]
    assert boundary["schema_version"] == "scholar_ai_blocking_action_boundary_v1"
    assert drilldown["signal_id"] == "workflow_stage:agent_handoff"
    assert drilldown["linked_stage_id"] == "agent_handoff"
    assert drilldown["recovery_refs"][0]["ref_type"] == "workflow_passport_stage"
    assert drilldown["local_read_only_probes"][0]["read_only"] is True
    assert drilldown["raw_path_exposed"] is False
    assert result["data"]["replay_recovery"]["read_only"] is True
    assert result["data"]["replay_recovery"]["highest_priority_attempt"]["job_id"] == "job_agent_1"
    assert result["data"]["action_lifecycle_recovery"]["read_only"] is True
    assert result["data"]["action_lifecycle_recovery"]["pending_confirmation_count"] == 1
    assert result["data"]["action_lifecycle_recovery"]["blocked_action_count"] == 1
    assert result["data"]["action_lifecycle_recovery"]["missing_preflight_count"] == 0
    assert result["data"]["action_lifecycle_recovery"]["resume_probes"] == [
        {"endpoint": "/runtime/research-action-lifecycle", "read_only": True}
    ]
    assert "execute approvals" in result["data"]["action_lifecycle_recovery"]["forbidden_actions"][0]
    action_ref = result["data"]["action_lifecycle_recovery"]["action_refs"][0]
    assert action_ref["action_type"] == "agent_handoff"
    assert action_ref["probe_endpoint"] == "/runtime/research-action-lifecycle"
    assert "runtime.research_action_lifecycle_refs" in result["data"]["provenance"]["derived_from"]
    assert result["data"]["provenance"]["external_mutation"] is False
    assert result["data"]["provenance"]["source_material_mutation"] is False
    assert backend.calls[-2] == ("json", "/api/agent-bridge/request/agentreq_1", None)
    assert backend.calls[-1] == ("json", "/runtime/job/job_agent_1/agent-handoff-card", None)


def test_behavior_eval_pack_runs_builtin_canaries_without_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Behavior eval canaries should prove every red-flag rule is live locally."""

    result = tools.behavior_eval_pack(write_record=False)

    assert result["is_error"] is False
    data = result["data"]
    assert data["schema_version"] == "scholar_ai_behavior_eval_pack_v1"
    assert data["mode"] == "canary"
    assert data["summary"]["case_count"] == 8
    assert data["summary"]["observation_count"] == 8
    assert data["summary"]["structural_status"] == "pass"
    assert data["summary"]["behavior_status"] == "block"
    assert data["summary"]["block_count"] == 7
    assert data["summary"]["warn_count"] == 1
    assert {item["case_id"] for item in data["cases"]} == {
        "hallucinated_citation_metadata",
        "offline_verification_overclaim",
        "missing_layout_locator",
        "private_path_or_secret_leak",
        "external_content_as_instruction",
        "export_readiness_overclaim",
        "bounded_resource_overrun",
        "unauthorized_external_action",
    }
    assert backend.calls == []


def test_behavior_eval_pack_persists_local_run_record(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Behavior eval run records should stay local under workspace_artifacts."""

    result = tools.behavior_eval_pack(include_cases=False)

    assert result["is_error"] is False
    record_path = Path(result["data"]["run_record"]["path"])
    assert record_path.exists()
    assert "workspace_artifacts" in str(record_path)
    payload = record_path.read_text(encoding="utf-8")
    assert "scholar_ai_behavior_eval_pack_v1" in payload
    assert "\"cases\"" not in payload
    assert backend.calls == []


def test_behavior_eval_pack_accepts_safe_observations(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Observation mode should separate safe behavior from canary structure."""

    result = tools.behavior_eval_pack(
        observations=[
            {
                "observation_id": "safe-1",
                "text": "Evidence remains unresolved; no citation verification is claimed.",
                "evidence_refs": [
                    {
                        "ref_id": "chunk:c1",
                        "material_id": "mat1",
                        "chunk_id": "c1",
                        "page": 3,
                        "bbox": [0.1, 0.2, 0.3, 0.4],
                    }
                ],
                "metadata": {"integrity_gate": {"status": "unresolved"}},
            }
        ],
        write_record=False,
    )

    assert result["is_error"] is False
    assert result["data"]["mode"] == "observations"
    assert result["data"]["summary"]["structural_status"] == "not_applicable"
    assert result["data"]["summary"]["behavior_status"] == "pass"
    assert result["data"]["summary"]["red_flag_count"] == 0
    assert backend.calls == []


def test_behavior_eval_pack_flags_observation_red_flags_and_redacts(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Observation mode should catch source overclaims, locator gaps, and leaks."""

    result = tools.behavior_eval_pack(
        observations=[
            {
                "observation_id": "bad-1",
                "text": (
                    "All citations are verified by DOI 10.5555/fiction.1. "
                    "The draft is ready for submission from C:/Users/xiao/private/source.pdf "
                    "with token='sk-abcdefghijklmnopqrstuvwxyz123456'."
                ),
                "evidence_refs": [{"ref_id": "chunk:c1", "material_id": "mat1"}],
                "metadata": {
                    "citation_verification": {"status": "offline"},
                    "integrity_gate": {"status": "unresolved"},
                },
            }
        ],
        write_record=False,
    )

    assert result["is_error"] is False
    data = result["data"]
    assert data["summary"]["behavior_status"] == "block"
    findings = data["results"][0]["findings"]
    case_ids = {item["case_id"] for item in findings}
    assert {
        "hallucinated_citation_metadata",
        "offline_verification_overclaim",
        "missing_layout_locator",
        "private_path_or_secret_leak",
        "export_readiness_overclaim",
    }.issubset(case_ids)
    assert "C:/Users/xiao/private" not in str(data)
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in str(data)
    assert "[REDACTED:LOCAL_PATH]" in str(data)
    assert "[REDACTED:API_KEY_ASSIGN]" in str(data)
    assert backend.calls == []


def test_behavior_eval_pack_rejects_unbounded_observation_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Behavior eval observations should stay bounded before local processing."""

    with pytest.raises(ValueError, match="observations\\[0\\]"):
        tools.behavior_eval_pack(observations=[{"text": "A" * 60000}])

    with pytest.raises(ValueError, match="observations"):
        tools.behavior_eval_pack(observations=[{"ok": True}] * 51)

    assert backend.calls == []


def test_workflow_passport_reads_runtime_projection(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Workflow passport should expose the backend read-only stage ledger to MCP."""

    backend.set_json(
        "/runtime/workflow-passport",
        {
            "schema_version": "scholar_ai_workflow_passport_v1",
            "scope": {"project_id": "project-1"},
            "stages": [],
            "gate_summary": {"blocking_stage_ids": []},
        },
    )

    result = tools.workflow_passport(project_id=" project-1 ", limit=12)

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar_ai_workflow_passport_v1"
    assert backend.calls[-1] == (
        "json",
        "/runtime/workflow-passport",
        {"limit": 12, "project_id": "project-1"},
    )


def test_evidence_integrity_gate_reads_runtime_projection(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Evidence integrity gate should expose pass/warn/block/unresolved state to MCP."""

    backend.set_json(
        "/runtime/evidence-integrity-gate",
        {
            "schema_version": "scholar_ai_evidence_integrity_gate_v1",
            "status": "unresolved",
            "summary": {"unresolved_is_pass": False},
            "signals": [],
            "blocking_action_boundary": {
                "schema_version": "scholar_ai_blocking_action_boundary_v1",
                "action_id": "writing.export_project",
                "required_claim_id": "export_readiness",
                "status": "blocked",
                "can_proceed": False,
                "recovery_drilldowns": [
                    {
                        "signal_id": "citation_verification:unsupported:1",
                        "category": "citation_verification",
                        "status": "block",
                        "linked_stage_id": "citation_review",
                        "source_ref": {"source_kind": "citation_verification"},
                        "checked_facts": {"citation_id": "cite:unsupported"},
                        "evidence_refs": [
                            {"ref_type": "citation_verification", "ref_id": "cite:unsupported"}
                        ],
                        "replay_refs": [
                            {
                                "ref_type": "preflight_refresh_receipt",
                                "ref_id": "preflight_refresh:export",
                            }
                        ],
                        "recovery_refs": [
                            {
                                "ref_type": "evidence_integrity_signal",
                                "ref_id": "citation_verification:unsupported:1",
                            }
                        ],
                        "local_read_only_probes": [
                            {"endpoint": "/runtime/evidence-integrity-gate", "read_only": True}
                        ],
                        "next_safe_local_actions": ["Verify citation support before export."],
                        "requires_human_review": False,
                        "blocks_claims": True,
                        "read_only": True,
                        "raw_path_exposed": False,
                    }
                ],
            },
        },
    )

    result = tools.evidence_integrity_gate(
        session_id=" session-1 ",
        job_id=" job-1 ",
        project_id=" project-1 ",
        limit=25,
    )

    assert result["is_error"] is False
    assert result["data"]["status"] == "unresolved"
    boundary = result["data"]["blocking_action_boundary"]
    drilldown = boundary["recovery_drilldowns"][0]
    assert boundary["schema_version"] == "scholar_ai_blocking_action_boundary_v1"
    assert drilldown["signal_id"] == "citation_verification:unsupported:1"
    assert drilldown["linked_stage_id"] == "citation_review"
    assert drilldown["checked_facts"]["citation_id"] == "cite:unsupported"
    assert drilldown["local_read_only_probes"][0]["read_only"] is True
    assert drilldown["raw_path_exposed"] is False
    assert backend.calls[-1] == (
        "json",
        "/runtime/evidence-integrity-gate",
        {
            "limit": 25,
            "session_id": "session-1",
            "job_id": "job-1",
            "project_id": "project-1",
        },
    )


def test_research_action_lifecycle_reads_runtime_projection(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Research action lifecycle should expose backend action/effect rows to MCP."""

    backend.set_json(
        "/runtime/research-action-lifecycle",
        {
            "schema_version": "scholar_ai_research_action_lifecycle_v1",
            "scope": {"project_id": "project-1"},
            "actions": [
                {
                    "action_uid": "wiki_candidate:job-1",
                    "action_id": "agent.wiki_candidate",
                    "action_type": "wiki_candidate",
                    "status": "pending_approval",
                    "project_id": "project-1",
                    "session_id": "session-1",
                    "job_id": "job-1",
                    "approval": {"requires_user_confirmation": True},
                    "preflight": {
                        "present": True,
                        "status": "blocked",
                        "can_proceed": False,
                        "receipt_refs": [{"ref_type": "preflight_refresh_receipt"}],
                    },
                    "effect_summary": {
                        "external_mutation": False,
                        "source_material_mutation": False,
                    },
                    "effect_refs": [{"ref_type": "wiki_ref", "ref_id": "wiki:candidate"}],
                    "recovery": {
                        "read_only": True,
                        "resume_probes": [
                            {"endpoint": "/runtime/research-action-lifecycle", "read_only": True}
                        ],
                    },
                    "forbidden_actions": ["Do not execute approvals from the lifecycle projection."],
                }
            ],
            "summary": {"read_only": True, "requires_user_confirmation": True},
            "blockers": ["Pending user confirmation is required."],
        },
    )

    result = tools.research_action_lifecycle(
        session_id=" session-1 ",
        job_id=" job-1 ",
        project_id=" project-1 ",
        limit=14,
    )

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar_ai_research_action_lifecycle_v1"
    action = result["data"]["actions"][0]
    assert action["action_type"] == "wiki_candidate"
    assert action["approval"]["requires_user_confirmation"] is True
    assert action["preflight"]["can_proceed"] is False
    assert action["effect_summary"]["external_mutation"] is False
    assert action["recovery"]["resume_probes"][0]["read_only"] is True
    assert backend.calls[-1] == (
        "json",
        "/runtime/research-action-lifecycle",
        {
            "limit": 14,
            "session_id": "session-1",
            "job_id": "job-1",
            "project_id": "project-1",
        },
    )


def test_agent_workspace_status_reads_recovery_state(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Agent Workspace status should expose read-only recovery state to MCP callers."""

    backend.set_json(
        "/api/agent-workspace/status",
        {
            "schema_version": "scholar_ai_agent_workspace_status_v1",
            "workspace_state": {
                "schema_version": "scholar_ai_agent_workspace_state_v1",
                "read_only": True,
                "git": {
                    "available": True,
                    "branch": "main",
                    "ahead": 34,
                    "changed_count": 2,
                    "staged_count": 0,
                    "unstaged_count": 1,
                    "untracked_count": 1,
                    "conflicted_count": 0,
                    "dirty_paths": [
                        ".gitignore",
                        "agent_mcp_server/src/lit_assistant_mcp/tools/runtime.py",
                    ],
                },
                "goal_state": {
                    "available": True,
                    "path": "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json",
                    "updated_at": "2026-06-22T21:50:27+08:00",
                    "checkpoint_id": "20260622-214730-n41-goal-state-record-update",
                    "requirement_count": 49,
                    "proved_count": 47,
                    "incomplete_count": 1,
                    "out_of_scope_count": 1,
                    "latest_requirement_id": "N41-goal-state-workspace-visibility",
                    "requirement_status": {
                        "total": 49,
                        "proved": 47,
                        "incomplete": 1,
                        "out_of_scope": 1,
                        "latest_id": "N41-goal-state-workspace-visibility",
                    },
                    "open_requirements": [
                        {
                            "id": "B01-computer-use-accessibility-tree",
                            "status": "incomplete",
                            "requirement": "Computer Use accessibility-tree acceptance is blocked by sandboxPolicy.",
                            "residual_risk": "Retry only after the external tool error is fixed.",
                        }
                    ],
                    "completion_claim": {
                        "this_slice": "N41 made goal-state recovery visible.",
                        "full_goal": "The full Scholar AI workflow spine remains active, not complete.",
                    },
                    "next_authorized_local_actions": [
                        "Create a rollback checkpoint and search mature references before edits."
                    ],
                    "stop_boundaries": ["No push, tag, release, deploy, or external upload."],
                    "error": None,
                },
                "artifact_root": {
                    "label": "agent_mcp_workflows",
                    "path": "workspace_artifacts/agent_mcp_workflows",
                    "exists": True,
                    "file_count": 12,
                    "total_bytes": 4096,
                    "truncated": False,
                },
                "runtime_state_root": {
                    "label": "runtime_state",
                    "path": "workspace_artifacts/runtime_state",
                    "exists": True,
                    "file_count": 7,
                    "total_bytes": 1024,
                    "truncated": False,
                },
                "output_root": {
                    "label": "generated_output",
                    "path": "workspace_artifacts/generated/output",
                    "exists": True,
                    "file_count": 3,
                    "total_bytes": 512,
                    "truncated": False,
                },
                "recovery_probes": [
                    {
                        "label": "Research Action Lifecycle",
                        "route": "/runtime/research-action-lifecycle",
                        "read_only": True,
                        "requires_identifier": False,
                        "identifier_hint": None,
                        "purpose": "Recover action lifecycle state.",
                        "mcp_tool": "literature.research_action_lifecycle",
                    },
                    {
                        "label": "Agent Handoff Card",
                        "route": "/runtime/job/{job_id}/agent-handoff-card",
                        "read_only": True,
                        "requires_identifier": True,
                        "identifier_hint": "job_id",
                        "purpose": "Recover handoff card state for one job.",
                        "mcp_tool": "literature.agent_handoff_card",
                    },
                    {
                        "label": "Agent Workspace Status",
                        "route": "/api/agent-workspace/status",
                        "read_only": True,
                        "requires_identifier": False,
                        "identifier_hint": None,
                        "purpose": "Recover workspace state.",
                        "mcp_tool": "literature.agent_workspace_status",
                    },
                ],
                "boundaries": [
                    "Do not restore rollback checkpoints without explicit user intent."
                ],
                "next_safe_local_actions": [
                    "Run focused MCP contract tests before staging this slice."
                ],
            },
        },
    )

    result = tools.agent_workspace_status(artifact_limit=25, audit_limit=30)

    assert result["is_error"] is False
    state = result["data"]["workspace_state"]
    assert state["read_only"] is True
    assert state["git"]["dirty_paths"] == [
        ".gitignore",
        "agent_mcp_server/src/lit_assistant_mcp/tools/runtime.py",
    ]
    assert state["artifact_root"]["file_count"] == 12
    assert state["goal_state"]["available"] is True
    assert state["goal_state"]["checkpoint_id"] == "20260622-214730-n41-goal-state-record-update"
    assert state["goal_state"]["requirement_count"] == 49
    assert state["goal_state"]["incomplete_count"] == 1
    assert state["goal_state"]["latest_requirement_id"] == "N41-goal-state-workspace-visibility"
    assert state["goal_state"]["requirement_status"]["total"] == 49
    assert state["goal_state"]["requirement_status"]["proved"] == 47
    assert state["goal_state"]["requirement_status"]["incomplete"] == 1
    assert state["goal_state"]["requirement_status"]["out_of_scope"] == 1
    assert state["goal_state"]["requirement_status"]["latest_id"] == "N41-goal-state-workspace-visibility"
    assert state["goal_state"]["open_requirements"] == [
        {
            "id": "B01-computer-use-accessibility-tree",
            "status": "incomplete",
            "requirement": "Computer Use accessibility-tree acceptance is blocked by sandboxPolicy.",
            "residual_risk": "Retry only after the external tool error is fixed.",
        }
    ]
    assert state["goal_state"]["completion_claim"]["this_slice"] == "N41 made goal-state recovery visible."
    assert state["goal_state"]["completion_claim"]["full_goal"] == "The full Scholar AI workflow spine remains active, not complete."
    assert state["recovery_probes"][0]["route"] == "/runtime/research-action-lifecycle"
    assert state["recovery_probes"][0]["read_only"] is True
    handoff_probe = state["recovery_probes"][1]
    assert handoff_probe["route"] == "/runtime/job/{job_id}/agent-handoff-card"
    assert handoff_probe["requires_identifier"] is True
    assert handoff_probe["identifier_hint"] == "job_id"
    assert handoff_probe["mcp_tool"] == "literature.agent_handoff_card"
    assert "explicit user intent" in state["boundaries"][0]
    assert backend.calls[-1] == (
        "json",
        "/api/agent-workspace/status",
        {"artifact_limit": 25, "audit_limit": 30},
    )


def test_workflow_refresh_receipt_reads_runtime_receipt(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Workflow refresh receipt should expose replay evidence to MCP."""

    backend.set_json(
        "/runtime/job/job-refresh-1/preflight-refresh-receipt",
        {
            "schema_version": "scholar_ai_preflight_refresh_receipt_v1",
            "receipt_id": "preflight_refresh:abc123",
            "action_id": "writing.export_project",
            "status": "unresolved",
            "projection_digests": {"workflow_passport": "sha256:passport"},
            "validation": {"unresolved_count": 1},
        },
    )

    result = tools.workflow_refresh_receipt(" job-refresh-1 ", receipt_id=" preflight_refresh:abc123 ")

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar_ai_preflight_refresh_receipt_v1"
    assert result["data"]["receipt_id"] == "preflight_refresh:abc123"
    assert backend.calls[-1] == (
        "json",
        "/runtime/job/job-refresh-1/preflight-refresh-receipt",
        {"receipt_id": "preflight_refresh:abc123"},
    )


def test_workflow_replay_lineage_reads_bounded_runtime_projection(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Workflow replay lineage should expose receipt history to MCP."""

    backend.set_json(
        "/runtime/job/job-refresh-1/workflow-replay-lineage",
        {
            "schema_version": "scholar_ai_workflow_replay_lineage_v1",
            "job_id": "job-refresh-1",
            "receipt_count": 2,
            "latest_receipt_id": "preflight_refresh:latest",
            "items": [
                {
                    "receipt_id": "preflight_refresh:latest",
                    "status": "blocked",
                    "blocker_count": 1,
                    "unresolved_count": 0,
                }
            ],
            "comparison": {"changed_digest_keys": ["evidence_integrity_gate"]},
        },
    )

    result = tools.workflow_replay_lineage(" job-refresh-1 ", limit=7)

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar_ai_workflow_replay_lineage_v1"
    assert result["data"]["latest_receipt_id"] == "preflight_refresh:latest"
    assert backend.calls[-1] == (
        "json",
        "/runtime/job/job-refresh-1/workflow-replay-lineage",
        {"limit": 7},
    )


def test_workflow_replay_index_reads_bounded_runtime_projection(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Workflow replay index should expose cross-job recovery discovery to MCP."""

    backend.set_json(
        "/runtime/workflow-replay-index",
        {
            "schema_version": "scholar_ai_workflow_replay_index_v1",
            "matching_job_count": 1,
            "returned_count": 1,
            "items": [
                {
                    "job_id": "job-refresh-1",
                    "latest_receipt_id": "preflight_refresh:latest",
                    "latest_status": "blocked",
                    "latest_blocker_count": 1,
                }
            ],
            "summary": {"requires_exact_job_id": False, "index_is_read_only": True},
        },
    )

    result = tools.workflow_replay_index(
        project_id=" project-1 ",
        session_id=" session-1 ",
        status=" blocked ",
        action_id=" writing.export_project ",
        limit=9,
    )

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar_ai_workflow_replay_index_v1"
    assert result["data"]["summary"]["requires_exact_job_id"] is False
    assert backend.calls[-1] == (
        "json",
        "/runtime/workflow-replay-index",
        {
            "limit": 9,
            "project_id": "project-1",
            "session_id": "session-1",
            "status": "blocked",
            "action_id": "writing.export_project",
        },
    )


def test_runtime_projection_tools_reject_invalid_bounds_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Projection tools should bound filters before hitting backend routes."""

    with pytest.raises(ValueError, match="limit"):
        tools.workflow_passport(limit=0)

    with pytest.raises(ValueError, match="project_id"):
        tools.evidence_integrity_gate(project_id=" " * 4)

    with pytest.raises(ValueError, match="limit"):
        tools.research_action_lifecycle(limit=0)

    with pytest.raises(ValueError, match="session_id"):
        tools.research_action_lifecycle(session_id=" " * 4)

    with pytest.raises(ValueError, match="job_id"):
        tools.workflow_refresh_receipt(" " * 4)

    with pytest.raises(ValueError, match="limit"):
        tools.workflow_replay_lineage("job-1", limit=0)

    with pytest.raises(ValueError, match="job_id"):
        tools.workflow_replay_lineage(" " * 4)

    with pytest.raises(ValueError, match="limit"):
        tools.workflow_replay_index(limit=0)

    with pytest.raises(ValueError, match="artifact_limit"):
        tools.agent_workspace_status(artifact_limit=0)

    with pytest.raises(ValueError, match="audit_limit"):
        tools.agent_workspace_status(audit_limit=0)

    assert backend.calls == []


def test_single_paper_task_create_posts_local_task_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Single-paper task creation must stay local to Scholar AI workflows."""

    backend.set_json(
        "/api/agent-bridge/single-paper-task",
        {
            "task_id": "paper_task_1",
            "schema_version": "scholar-ai-single-paper-task/v1",
            "outcome": {"status": "success"},
        },
    )

    result = tools.single_paper_task_create(
        project_id=" project-1 ",
        material_id=" material-1 ",
        task_goal=" 提炼论文写作方法 ",
        output_language="bilingual",
        target_document="deep_summary",
        create_agent_request=False,
        max_chars=8000,
        max_chunks=6,
    )

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "post_json",
        "/api/agent-bridge/single-paper-task",
        {
            "params": None,
            "payload": {
                "project_id": "project-1",
                "material_id": "material-1",
                "task_goal": "提炼论文写作方法",
                "output_language": "bilingual",
                "target_document": "deep_summary",
                "create_agent_request": False,
                "agent_host": "mcp",
                "source": "mcp",
                "max_chars": 8000,
                "max_chunks": 6,
            },
        },
    )
    assert "feishu" not in str(backend.calls[-1]).lower()
    assert "cloud_target" not in str(backend.calls[-1])


def test_single_paper_task_create_rejects_external_upload_target(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Old cloud/export target names should be rejected before backend calls."""

    with pytest.raises(ValueError, match="target_document"):
        tools.single_paper_task_create("project-1", "material-1", target_document="feishu_draft")

    assert backend.calls == []


def test_single_paper_completion_check_posts_local_completion_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Single-paper completion checks should post only local diagnostic fields."""

    backend.set_json(
        "/api/agent-bridge/single-paper-task/completion-check",
        {
            "schema_version": "scholar-ai-single-paper-completion-check/v1",
            "completion_state": "complete",
            "outcome": {"status": "success"},
        },
    )

    result = tools.single_paper_completion_check(
        output_text=" ## 论文元数据与附件健康检查\n完成 ",
        task_manifest={
            "task_id": "paper_task_1",
            "required_output_sections": ["论文元数据与附件健康检查"],
        },
        evidence_refs=[{"ref_id": "chunk:1", "kind": "chunk"}],
        figure_table_refs=[{"ref_id": "figure:1", "kind": "figure"}],
        lint_passed=True,
        docx_artifact_path="workspace_artifacts/generated/output/paper.docx",
    )

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "post_json",
        "/api/agent-bridge/single-paper-task/completion-check",
        {
            "params": None,
            "payload": {
                "output_text": "## 论文元数据与附件健康检查\n完成",
                "task_manifest": {
                    "task_id": "paper_task_1",
                    "required_output_sections": ["论文元数据与附件健康检查"],
                },
                "evidence_refs": [{"ref_id": "chunk:1", "kind": "chunk"}],
                "figure_table_refs": [{"ref_id": "figure:1", "kind": "figure"}],
                "lint_passed": True,
                "sentinel": "待补充",
                "docx_artifact_path": "workspace_artifacts/generated/output/paper.docx",
            },
        },
    )
    assert "feishu" not in str(backend.calls[-1]).lower()
    assert "cloud_target" not in str(backend.calls[-1])


def test_single_paper_completion_check_rejects_empty_manifest(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Completion checks need the task manifest returned by task creation."""

    with pytest.raises(ValueError, match="task_manifest"):
        tools.single_paper_completion_check(
            output_text="draft",
            task_manifest={},
        )

    assert backend.calls == []


def test_agent_request_list_uses_small_query_params(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Agent request listing should use backend filters, not local state."""
    tools.agent_request_list(status="started", project_id="project-1", source="mcp", limit=12)

    assert backend.calls[-1] == (
        "json",
        "/api/agent-bridge/requests",
        {"limit": 12, "status": "started", "project_id": "project-1", "source": "mcp"},
    )


def test_agent_progress_result_and_fail_post_to_bridge(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Agent progress/result/fail should write through backend runtime routes."""
    tools.agent_progress("agentreq_1", "reading", "Reading refs", progress=30)
    assert backend.calls[-1] == (
        "post_json",
        "/api/agent-bridge/request/agentreq_1/progress",
        {"params": None, "payload": {"stage": "reading", "message": "Reading refs", "progress": 30}},
    )

    tools.agent_result(
        "agentreq_1",
        text="final answer",
        evidence_refs=[{"ref_id": "chunk:1"}],
    )
    assert backend.calls[-1][0] == "post_json"
    assert backend.calls[-1][1] == "/api/agent-bridge/request/agentreq_1/result"
    assert backend.calls[-1][2]["payload"]["text"] == "final answer"
    assert backend.calls[-1][2]["payload"]["evidence_refs"] == [{"ref_id": "chunk:1"}]

    tools.agent_fail("agentreq_1", "stopped")
    assert backend.calls[-1] == (
        "post_json",
        "/api/agent-bridge/request/agentreq_1/fail",
        {"params": None, "payload": {"error": "stopped"}},
    )


def test_agent_resource_read_uses_bounded_reader(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Agent resource reads must carry explicit bounds and cursor metadata."""
    tools.agent_resource_read("chunk:mat_1_chunk_0", project_id="project-1", max_chars=500, cursor="100")

    assert backend.calls[-1] == (
        "json",
        "/api/agent-bridge/resource/chunk:mat_1_chunk_0",
        {"max_chars": 500, "project_id": "project-1", "cursor": "100"},
    )


def test_agent_result_requires_terminal_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """MCP should reject empty terminal results before hitting the backend."""
    with pytest.raises(ValueError, match="text or content"):
        tools.agent_result("agentreq_1")

    assert backend.calls == []


def test_agent_request_create_rejects_unbounded_refs(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Resource refs must be small objects with ref_id and kind."""
    with pytest.raises(ValueError, match="resource ref"):
        tools.agent_request_create(intent="x", resource_refs=[{"ref_id": "missing-kind"}])

    assert backend.calls == []
