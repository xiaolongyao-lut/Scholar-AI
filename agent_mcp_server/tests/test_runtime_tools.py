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


def test_academic_english_status_uses_knowledge_endpoint(tools: RuntimeTools, backend: FakeBackend) -> None:
    """academic_english_status must read the backend manifest/status endpoint."""

    tools.academic_english_status()

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/academic-english/status",
        None,
    )


def test_knowledge_packages_uses_read_only_registry_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """knowledge_packages must expose the unified backend registry to MCP callers."""

    backend.set_json(
        "/api/knowledge/packages",
        {
            "schema_version": "scholar-ai-knowledge-packages/v1",
            "packages": [
                {
                    "package_id": "wiki",
                    "status": "loaded",
                    "source_hash": "s" * 64,
                    "content_hash": "c" * 64,
                    "read_endpoint": "/api/wiki/status",
                }
            ],
        },
    )

    result = tools.knowledge_packages()

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar-ai-knowledge-packages/v1"
    assert result["data"]["packages"][0]["package_id"] == "wiki"
    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/packages",
        None,
    )


def test_knowledge_runtime_conformance_uses_read_only_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """knowledge_runtime_conformance exposes the backend conformance projection."""

    backend.set_json(
        "/api/knowledge/runtime-conformance",
        {
            "schema_version": "scholar-ai-knowledge-runtime-conformance/v1",
            "summary": {"proved": 1, "pending": 1, "blocked": 0},
            "actual_loading_gate": {
                "status": "blocked",
                "evidence_level": "contract_evidence",
                "artifact_contract": "scholar-ai-live-context-receipt-smoke/v1",
                "artifact_path": "workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json",
                "verdict": "missing_artifact",
                "evidence_scope": [
                    "/api/chat",
                    "literature.agent_resource_read",
                    "literature.knowledge_context_receipt",
                    "assembled_context_hash_backflow",
                ],
                "evidence": [],
                "missing": ["authorized live provider smoke artifact with verdict=ok"],
                "validation_errors": [],
                "required_checks": [
                    "artifact.schema.valid",
                    "artifact.generated_at.utc_aware",
                    "artifact.verdict.ok",
                    "artifact.status_code.200",
                    "artifact.required_tools.used",
                    "artifact.required_tools.names",
                    "artifact.receipt_hash.preview",
                    "artifact.receipt_hash.final_answer",
                    "artifact.receipt_hash.query_matches_direct",
                    "artifact.direct_receipt.assembled_context_hash",
                ],
                "next_safe_local_actions": [
                    "Require provider_preflight.status=proved before running live context-receipt smoke.",
                    "Run tests/live_api_chat_knowledge_context_receipt_smoke.py only with explicit live-provider authorization.",
                ],
                "claim_boundary": "Deterministic package conformance is not live QA/model loading proof.",
                "provider_preflight": {
                    "status": "blocked",
                    "evidence_level": "contract_evidence",
                    "artifact_path": "workspace_artifacts/runtime_state/provider-capabilities.json",
                    "artifact_ref": "workspace_artifacts/runtime_state/provider-capabilities.json",
                    "artifact_exists": True,
                    "artifact_schema_valid": True,
                    "checked_at": "2026-06-27T09:08:21Z",
                    "record_count": 1,
                    "latest_status": "auth_required",
                    "status_counts": {"auth_required": 1},
                    "auth_required_count": 1,
                    "tool_call_ok_count": 0,
                    "provider_ready_for_authorized_live_smoke": False,
                    "records": [
                        {
                            "fingerprint": "a" * 64,
                            "provider": "hhl",
                            "base_url_host": "free.hanhanapi.top",
                            "model": "gpt-5.5",
                            "status": "auth_required",
                            "ordinary_chat_ok": False,
                            "forced_tool_choice_ok": False,
                            "last_probe_at": "2026-06-27T09:08:21Z",
                            "failure_class": "models",
                            "masked_error": "HTTP 401: Invalid token (request id: [REDACTED])",
                        }
                    ],
                    "evidence_scope": [
                        "/api/chat/tool-capability/test",
                        "workspace_artifacts/runtime_state/provider-capabilities.json",
                        "OpenAI-compatible forced tool_choice preflight",
                    ],
                    "evidence": [
                        "workspace_artifacts/runtime_state/provider-capabilities.json",
                        "latest_provider_tool_call_status=auth_required",
                    ],
                    "missing": [
                        "provider_tool_call_status=tool_call_ok",
                        "valid provider credentials before live actual-loading smoke",
                    ],
                    "validation_errors": [],
                    "next_safe_local_actions": [
                        "Stop live actual-loading smoke while latest provider status is auth_required.",
                        "After the user corrects provider credentials/config, rerun provider tool-capability preflight.",
                    ],
                    "claim_boundary": (
                        "Provider preflight has not proven forced tool calls; Knowledge Runtime "
                        "actual-loading remains blocked before any live model-context claim."
                    ),
                },
                "recovery": {
                    "schema_version": "scholar-ai-knowledge-runtime-recovery/v1",
                    "read_only": True,
                    "state": "blocked_provider_preflight_and_missing_live_smoke",
                    "blocked_by": [
                        "provider_preflight:blocked:auth_required",
                        "live_smoke_artifact:missing",
                    ],
                    "recovery_refs": [
                        {
                            "ref_type": "conformance_endpoint",
                            "ref": "/api/knowledge/runtime-conformance",
                            "status": "blocked",
                            "method": "GET",
                            "access_mode": "read_only",
                            "required_before_completion": True,
                            "requires_authorization": False,
                        },
                        {
                            "ref_type": "provider_preflight_endpoint",
                            "ref": "/api/chat/tool-capability/test",
                            "status": "requires_configured_credentials",
                            "method": "POST",
                            "access_mode": "authorized_provider_preflight",
                            "required_before_completion": True,
                            "requires_authorization": True,
                        },
                        {
                            "ref_type": "live_smoke_harness",
                            "ref": "tests/live_api_chat_knowledge_context_receipt_smoke.py",
                            "status": "requires_explicit_authorization",
                            "method": "RUN",
                            "access_mode": "explicit_live_provider_smoke",
                            "required_before_completion": True,
                            "requires_authorization": True,
                        },
                    ],
                    "provider_ready_for_authorized_live_smoke": False,
                    "completion_requires_authorized_live_smoke": True,
                },
            },
            "packages": [
                {
                    "package_id": "product_docs",
                    "overall_status": "pending",
                    "conformance": [
                        {"requirement": "prompt_assembly_context_receipt", "status": "pending"},
                    ],
                }
            ],
        },
    )

    result = tools.knowledge_runtime_conformance()

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar-ai-knowledge-runtime-conformance/v1"
    gate = result["data"]["actual_loading_gate"]
    assert gate["status"] == "blocked"
    assert gate["verdict"] == "missing_artifact"
    assert gate["artifact_contract"] == "scholar-ai-live-context-receipt-smoke/v1"
    assert gate["validation_errors"] == []
    assert len(gate["required_checks"]) == 10
    assert "artifact.generated_at.utc_aware" in gate["required_checks"]
    assert "artifact.direct_receipt.assembled_context_hash" in gate["required_checks"]
    assert "authorized live provider smoke artifact with verdict=ok" in gate["missing"]
    assert gate["next_safe_local_actions"][0] == (
        "Require provider_preflight.status=proved before running live context-receipt smoke."
    )
    assert gate["recovery"]["state"] == "blocked_provider_preflight_and_missing_live_smoke"
    assert gate["recovery"]["blocked_by"] == [
        "provider_preflight:blocked:auth_required",
        "live_smoke_artifact:missing",
    ]
    assert gate["provider_preflight"]["latest_status"] == "auth_required"
    assert gate["provider_preflight"]["status_counts"] == {"auth_required": 1}
    assert gate["provider_preflight"]["auth_required_count"] == 1
    assert gate["provider_preflight"]["tool_call_ok_count"] == 0
    assert gate["provider_preflight"]["provider_ready_for_authorized_live_smoke"] is False
    assert gate["provider_preflight"]["next_safe_local_actions"][0] == (
        "Stop live actual-loading smoke while latest provider status is auth_required."
    )
    refs = {item["ref_type"]: item for item in gate["recovery"]["recovery_refs"]}
    assert refs["provider_preflight_endpoint"]["method"] == "POST"
    assert refs["provider_preflight_endpoint"]["access_mode"] == "authorized_provider_preflight"
    assert refs["provider_preflight_endpoint"]["requires_authorization"] is True
    assert refs["live_smoke_harness"]["method"] == "RUN"
    assert refs["live_smoke_harness"]["requires_authorization"] is True
    assert result["data"]["packages"][0]["package_id"] == "product_docs"
    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/runtime-conformance",
        None,
    )


def test_ocr_status_uses_read_only_pdf_backend_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """ocr_status exposes redacted OCR runtime selection without running OCR."""

    backend.set_json(
        "/api/pdf-backend/ocr-status",
        {
            "policy": "auto",
            "configured_engine": None,
            "selected_engine": None,
            "language": "en",
            "source": "default",
            "engine_config": {},
            "available_engines": [],
            "warning": "OCR policy is auto but no available OCR engine was found",
            "next_safe_local_actions": [
                "Inspect literature.ocr_engines for readiness_blockers and choose a ready local engine or configure one explicitly."
            ],
        },
    )

    result = tools.ocr_status()

    assert result["is_error"] is False
    assert result["data"]["policy"] == "auto"
    assert result["data"]["engine_config"] == {}
    assert result["data"]["next_safe_local_actions"][0].startswith("Inspect literature.ocr_engines")
    assert backend.calls[-1] == (
        "json",
        "/api/pdf-backend/ocr-status",
        None,
    )


def test_ocr_engines_uses_read_only_pdf_backend_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """ocr_engines exposes local OCR engine inventory without running OCR."""

    backend.set_json(
        "/api/pdf-backend/ocr-engines",
        [
            {
                "name": "rapidocr",
                "display_name": "RapidOCR",
                "engine_type": "local",
                "available": False,
                "requires_network": False,
                "unavailable_reason": "rapidocr is not installed",
                "readiness_status": "dependency_missing",
                "readiness_blockers": ["rapidocr is not installed"],
                "next_safe_local_actions": [
                    "Install or point to a local RapidOCR Python runtime, then rerun literature.ocr_health."
                ],
            }
        ],
    )

    result = tools.ocr_engines()

    assert result["is_error"] is False
    assert result["data"][0]["name"] == "rapidocr"
    assert result["data"][0]["readiness_status"] == "dependency_missing"
    assert "RapidOCR" in result["data"][0]["next_safe_local_actions"][0]
    assert backend.calls[-1] == (
        "json",
        "/api/pdf-backend/ocr-engines",
        None,
    )


def test_ocr_health_posts_bounded_readiness_probe_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """ocr_health exposes backend readiness probing without uploading OCR content."""

    backend.set_json(
        "/api/pdf-backend/ocr-health",
        {
            "ok": False,
            "detail": "remote OCR requires explicit api_key and base_url configuration",
            "engine": "remote_api",
            "latency_ms": 0.1,
            "readiness_status": "configuration_required",
            "readiness_blockers": [
                "remote OCR requires explicit api_key and base_url configuration"
            ],
            "next_safe_local_actions": [
                "Configure remote_api with local api_key and base_url references; rerun literature.ocr_health."
            ],
        },
    )

    result = tools.ocr_health(
        engine=" remote_api ",
        engine_config={"base_url": "https://ocr.example.test"},
    )

    assert result["is_error"] is False
    assert result["data"]["engine"] == "remote_api"
    assert result["data"]["readiness_status"] == "configuration_required"
    assert "api_key" in result["data"]["next_safe_local_actions"][0]
    assert backend.calls[-1] == (
        "post_json",
        "/api/pdf-backend/ocr-health",
        {
            "params": None,
            "payload": {
                "engine": "remote_api",
                "engine_config": {"base_url": "https://ocr.example.test"},
            },
        },
    )


def test_ocr_health_rejects_malformed_engine_config_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """MCP OCR health config must stay bounded and JSON serializable."""

    with pytest.raises(ValueError, match="engine_config"):
        tools.ocr_health(engine_config={"bad": object()})

    with pytest.raises(ValueError, match="engine_config"):
        tools.ocr_health(engine_config={"large": "x" * 9000})

    assert backend.calls == []


def test_ocr_execution_probe_posts_explicit_execution_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """ocr_execution_probe should require intent and delegate execution to backend."""

    backend.set_json(
        "/api/pdf-backend/ocr-execution-probe",
        {
            "schema_version": "scholar-ai-ocr-execution-probe/v1",
            "confirmed": True,
            "engine": "mock_local",
            "engine_type": "local",
            "requires_network": False,
            "language": "en",
            "input_kind": "image_base64",
            "input_bytes": 4,
            "input_sha256": "a" * 64,
            "text_length": 9,
            "text_sha256": "b" * 64,
            "text_preview": "mock text",
            "duration_ms": 3,
        },
    )

    result = tools.ocr_execution_probe(
        confirm_execution=True,
        image_base64=" ZmFrZQ== ",
        engine=" mock_local ",
        engine_config={"suffix": "ok"},
        language=" en ",
        preview_chars=80,
    )

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar-ai-ocr-execution-probe/v1"
    assert backend.calls[-1] == (
        "post_json",
        "/api/pdf-backend/ocr-execution-probe",
        {
            "params": None,
            "payload": {
                "confirm_execution": True,
                "image_base64": "ZmFrZQ==",
                "image_path": None,
                "engine": "mock_local",
                "engine_config": {"suffix": "ok"},
                "language": "en",
                "preview_chars": 80,
            },
        },
    )


def test_ocr_execution_probe_rejects_unconfirmed_or_ambiguous_input_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """MCP OCR execution must fail closed before backend content handling."""

    with pytest.raises(ValueError, match="confirm_execution=true"):
        tools.ocr_execution_probe(image_base64="ZmFrZQ==", engine="mock_local")

    with pytest.raises(ValueError, match="exactly one"):
        tools.ocr_execution_probe(confirm_execution=True, engine="mock_local")

    with pytest.raises(ValueError, match="exactly one"):
        tools.ocr_execution_probe(
            confirm_execution=True,
            image_base64="ZmFrZQ==",
            image_path="C:/tmp/probe.png",
            engine="mock_local",
        )

    with pytest.raises(ValueError, match="preview_chars"):
        tools.ocr_execution_probe(
            confirm_execution=True,
            image_base64="ZmFrZQ==",
            engine="mock_local",
            preview_chars=1001,
        )

    assert backend.calls == []


def test_knowledge_context_receipt_posts_bounded_ref_payload(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """knowledge_context_receipt should expose bounded context proof through MCP."""

    backend.set_json(
        "/api/knowledge/context-receipt",
        {
            "schema_version": "scholar-ai-knowledge-context-receipt/v1",
            "prompt_hash": "p" * 64,
            "assembled_context_hash": "c" * 64,
            "resource_read_receipts": [{"ref_id": "product_docs:chunk:readme"}],
        },
    )

    result = tools.knowledge_context_receipt(
        [" product_docs:chunk:readme "],
        project_id=" project-1 ",
        prompt_name=" qa_prompt ",
        max_chars_per_ref=800,
    )

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar-ai-knowledge-context-receipt/v1"
    assert backend.calls[-1] == (
        "post_json",
        "/api/knowledge/context-receipt",
        {
            "params": None,
            "payload": {
                "ref_ids": ["product_docs:chunk:readme"],
                "project_id": "project-1",
                "prompt_name": "qa_prompt",
                "max_chars_per_ref": 800,
            },
        },
    )


def test_knowledge_context_receipt_rejects_unbounded_inputs_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """The MCP tool should not proxy malformed receipt requests."""

    with pytest.raises(ValueError, match="ref_ids"):
        tools.knowledge_context_receipt([])
    with pytest.raises(ValueError, match="ref_ids"):
        tools.knowledge_context_receipt(["valid:ref"] * 21)
    with pytest.raises(ValueError, match="ref_ids"):
        tools.knowledge_context_receipt(["   "])
    with pytest.raises(ValueError, match="max_chars_per_ref"):
        tools.knowledge_context_receipt(["product_docs:chunk:readme"], max_chars_per_ref=99)

    assert backend.calls == []


def test_wiki_status_uses_read_only_status_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """wiki_status must expose the backend wiki manifest/status surface."""

    tools.wiki_status(user_id=" reader-a ")

    assert backend.calls[-1] == (
        "json",
        "/api/wiki/status",
        {"user_id": "reader-a"},
    )


def test_wiki_doctor_uses_read_only_doctor_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """wiki_doctor must expose recovery diagnostics without mutating wiki state."""

    backend.set_json(
        "/api/wiki/doctor",
        {
            "schema_version": "scholar-ai-wiki-doctor/v1",
            "status": "warning",
            "checks": [
                {
                    "id": "source_registry",
                    "status": "warning",
                    "metrics": {
                        "source_vault_mirror_backlog": {
                            "needs_replay": True,
                            "pending_source_count": 1,
                        }
                    },
                }
            ],
        },
    )

    result = tools.wiki_doctor()

    assert backend.calls[-1] == (
        "json",
        "/api/wiki/doctor",
        None,
    )
    assert result["is_error"] is False
    backlog = result["data"]["checks"][0]["metrics"]["source_vault_mirror_backlog"]
    assert backlog["needs_replay"] is True
    assert backlog["pending_source_count"] == 1


def test_wiki_search_returns_refs_only(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """wiki_search delegates bounded ref retrieval without reading page bodies."""

    backend.set_json(
        "/api/wiki/search",
        {
            "query": "laser welding",
            "results": [
                {
                    "schema_version": "scholar-ai-wiki-knowledge-ref/v1",
                    "ref_id": "wiki:concepts/laser-welding.md",
                    "chunk_id": "wiki:concepts/laser-welding.md#0",
                    "kind": "wiki",
                    "summary": "Laser welding evidence enters the wiki pipeline.",
                    "read_endpoint": "/api/agent-bridge/resource/wiki:concepts/laser-welding.md",
                    "metadata": {
                        "content_hash": "a" * 64,
                        "source_hash": "b" * 64,
                    },
                }
            ],
        },
    )

    result = tools.wiki_search(" laser welding ", top_k=3, user_id=" reader-a ")

    assert backend.calls[-1] == (
        "post_json",
        "/api/wiki/search",
        {
            "params": None,
            "payload": {
                "query": "laser welding",
                "limit": 3,
                "user_id": "reader-a",
            },
        },
    )
    assert result["is_error"] is False
    assert result["data"]["results"][0]["ref_id"] == "wiki:concepts/laser-welding.md"
    assert result["data"]["results"][0]["read_endpoint"] == (
        "/api/agent-bridge/resource/wiki:concepts/laser-welding.md"
    )
    assert "content" not in result["data"]["results"][0]


def test_wiki_search_rejects_unbounded_inputs_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """wiki_search validates query and top_k before backend calls."""

    with pytest.raises(ValueError, match="query"):
        tools.wiki_search("   ")
    with pytest.raises(ValueError, match="top_k"):
        tools.wiki_search("laser", top_k=0)
    with pytest.raises(ValueError, match="top_k"):
        tools.wiki_search("laser", top_k=51)

    assert backend.calls == []


def test_skill_package_status_uses_allowlisted_knowledge_endpoint(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """skill_package_status exposes provenance without executing package code."""

    tools.skill_package_status(" academic-english-discourse ")

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/skill-packages/academic-english-discourse/status",
        None,
    )


def test_skill_package_status_rejects_unknown_package_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """The MCP boundary should not become an arbitrary package-id proxy."""

    with pytest.raises(ValueError, match="package_id"):
        tools.skill_package_status("../other-skill")

    assert backend.calls == []


def test_source_vault_status_uses_knowledge_endpoint(tools: RuntimeTools, backend: FakeBackend) -> None:
    """source_vault_status must read the backend Source Vault overview endpoint."""

    tools.source_vault_status(limit=12)

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/source-vault",
        {"limit": 12},
    )


def test_bridge_lexicon_status_uses_knowledge_endpoint(tools: RuntimeTools, backend: FakeBackend) -> None:
    """bridge_lexicon_status must read the backend manifest/status endpoint."""

    tools.bridge_lexicon_status()

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/bridge-lexicon/status",
        None,
    )


def test_bridge_lexicon_read_uses_knowledge_endpoint(tools: RuntimeTools, backend: FakeBackend) -> None:
    """bridge_lexicon_read must read the backend bounded artifact endpoint."""

    tools.bridge_lexicon_read()

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/bridge-lexicon/read",
        None,
    )


def test_bridge_lexicon_search_returns_refs_only(tools: RuntimeTools, backend: FakeBackend) -> None:
    """bridge_lexicon_search must expose entry refs without reading resource bodies."""

    backend.set_json(
        "/api/knowledge/bridge-lexicon/search",
        {
            "query": "laser",
            "package_id": "bridge_lexicon",
            "results": [
                {
                    "schema_version": "scholar-ai-bridge-lexicon-knowledge-ref/v1",
                    "ref_id": "bridge_lexicon:entry:laser-a1",
                    "kind": "bridge_lexicon",
                    "resource_kind": "entry",
                    "title": "Bridge lexicon: 激光",
                    "summary": "激光: laser",
                    "score": 4.0,
                    "rank": 1,
                    "read_endpoint": "/api/agent-bridge/resource/bridge_lexicon:entry:laser-a1",
                    "metadata": {
                        "source_hash": "a" * 64,
                        "package_content_hash": "b" * 64,
                    },
                }
            ],
        },
    )

    result = tools.bridge_lexicon_search("laser", top_k=3)

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/bridge-lexicon/search",
        {"q": "laser", "top_k": 3},
    )
    assert result["data"]["results"][0]["ref_id"] == "bridge_lexicon:entry:laser-a1"
    assert "content" not in result["data"]["results"][0]


def test_bridge_lexicon_search_rejects_unbounded_inputs_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """bridge_lexicon_search validates query and top_k before backend calls."""

    with pytest.raises(ValueError, match="query"):
        tools.bridge_lexicon_search("   ")
    with pytest.raises(ValueError, match="top_k"):
        tools.bridge_lexicon_search("laser", top_k=0)
    with pytest.raises(ValueError, match="top_k"):
        tools.bridge_lexicon_search("laser", top_k=51)

    assert backend.calls == []


def test_scoring_rules_status_uses_knowledge_endpoint(tools: RuntimeTools, backend: FakeBackend) -> None:
    """scoring_rules_status must read the backend manifest/status endpoint."""

    tools.scoring_rules_status()

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/scoring-rules/status",
        None,
    )


def test_scoring_rules_read_uses_knowledge_endpoint(tools: RuntimeTools, backend: FakeBackend) -> None:
    """scoring_rules_read must read the backend bounded artifact endpoint."""

    tools.scoring_rules_read()

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/scoring-rules/read",
        None,
    )


def test_product_docs_status_uses_knowledge_endpoint(tools: RuntimeTools, backend: FakeBackend) -> None:
    """product_docs_status must read the backend manifest/status endpoint."""

    tools.product_docs_status()

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/product-docs/status",
        None,
    )


def test_product_docs_read_uses_knowledge_endpoint(tools: RuntimeTools, backend: FakeBackend) -> None:
    """product_docs_read must read the backend bounded artifact endpoint."""

    tools.product_docs_read()

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/product-docs/read",
        None,
    )


def test_academic_english_search_returns_refs_only(tools: RuntimeTools, backend: FakeBackend) -> None:
    """academic_english_search delegates bounded ref retrieval to the backend."""

    tools.academic_english_search("hedging", top_k=6)

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/academic-english/search",
        {
            "q": "hedging",
            "top_k": 6,
        },
    )


def test_skill_package_search_returns_refs_only(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """skill_package_search delegates refs-only retrieval to the backend."""

    tools.skill_package_search(
        "discourse move",
        package_id=" academic-english-discourse ",
        top_k=3,
    )

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/skill-packages/academic-english-discourse/search",
        {
            "q": "discourse move",
            "top_k": 3,
        },
    )


def test_skill_package_search_rejects_invalid_package_and_top_k_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Invalid Skill package searches should fail before backend I/O."""

    with pytest.raises(ValueError, match="package_id"):
        tools.skill_package_search("discourse", package_id="private-skill", top_k=3)
    with pytest.raises(ValueError, match="top_k"):
        tools.skill_package_search("discourse", top_k=0)

    assert backend.calls == []


def test_source_vault_search_returns_refs_only(tools: RuntimeTools, backend: FakeBackend) -> None:
    """source_vault_search delegates bounded ref retrieval to the backend."""

    tools.source_vault_search("provenance", top_k=9, project_id=" project-1 ")

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/source-vault/search",
        {
            "q": "provenance",
            "limit": 9,
            "project_id": "project-1",
        },
    )


def test_scoring_rules_search_returns_refs_only(tools: RuntimeTools, backend: FakeBackend) -> None:
    """scoring_rules_search delegates bounded ref retrieval to the backend."""

    tools.scoring_rules_search("direct_evidence", top_k=4)

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/scoring-rules/search",
        {
            "q": "direct_evidence",
            "top_k": 4,
        },
    )


def test_product_docs_search_returns_refs_only(tools: RuntimeTools, backend: FakeBackend) -> None:
    """product_docs_search delegates bounded ref retrieval to the backend."""

    tools.product_docs_search("MCP-first", top_k=5)

    assert backend.calls[-1] == (
        "json",
        "/api/knowledge/product-docs/search",
        {
            "q": "MCP-first",
            "top_k": 5,
        },
    )


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


def test_wiki_import_defaults_to_dry_run_and_calls_local_route(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Wiki import should default to dry-run and delegate path checks to backend."""

    backend.set_json(
        "/api/wiki/import",
        {
            "enabled": True,
            "dry_run": True,
            "confirm_write": False,
            "imported": 0,
            "skipped": 1,
            "errored": 0,
            "pages": [{"source_path": "note.md", "action": "planned_create"}],
        },
    )

    result = tools.wiki_import([" C:/repo/note.md "])

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "post_json",
        "/api/wiki/import",
        {
            "params": None,
            "payload": {
                "source_paths": ["C:/repo/note.md"],
                "dry_run": True,
                "confirm_write": False,
                "overwrite": False,
                "kind": "synthesis",
                "status": "draft",
            },
        },
    )


def test_wiki_import_apply_forwards_explicit_write_intent_and_user(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Apply mode remains explicit and carries the local wiki user id."""

    backend.set_json(
        "/api/wiki/import",
        {
            "enabled": True,
            "dry_run": False,
            "confirm_write": True,
            "imported": 1,
            "skipped": 0,
            "errored": 0,
            "pages": [{"source_path": "note.md", "action": "created"}],
        },
    )

    result = tools.wiki_import(
        ["C:/repo/note.md"],
        dry_run=False,
        confirm_write=True,
        overwrite=True,
        kind="concept",
        status="review",
        user_id=" owner123 ",
    )

    assert result["is_error"] is False
    assert backend.calls[-1] == (
        "post_json",
        "/api/wiki/import",
        {
            "params": {"user_id": "owner123"},
            "payload": {
                "source_paths": ["C:/repo/note.md"],
                "dry_run": False,
                "confirm_write": True,
                "overwrite": True,
                "kind": "concept",
                "status": "review",
            },
        },
    )


def test_wiki_import_rejects_empty_source_paths_before_backend(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """The MCP boundary should not call backend without at least one path."""

    with pytest.raises(ValueError, match="source_paths"):
        tools.wiki_import([" ", ""])

    assert backend.calls == []


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
            "stages": [
                {
                    "stage_id": "agent_handoff",
                    "diagnostics": {"research_action_count": 1},
                    "reproducibility": {
                        "research_action_refs": [
                            {
                                "ref_type": "research_action_lifecycle",
                                "action_type": "agent_handoff",
                                "status": "pending_approval",
                                "probe_endpoint": "/runtime/research-action-lifecycle",
                                "read_only": True,
                            }
                        ]
                    },
                }
            ],
            "gate_summary": {"blocking_stage_ids": []},
        },
    )

    result = tools.workflow_passport(project_id=" project-1 ", limit=12)

    assert result["is_error"] is False
    assert result["data"]["schema_version"] == "scholar_ai_workflow_passport_v1"
    action_ref = result["data"]["stages"][0]["reproducibility"]["research_action_refs"][0]
    assert action_ref["ref_type"] == "research_action_lifecycle"
    assert action_ref["probe_endpoint"] == "/runtime/research-action-lifecycle"
    assert action_ref["read_only"] is True
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
            "summary": {
                "unresolved_is_pass": False,
                "research_action_count": 1,
                "research_action_refs": [
                    {
                        "ref_type": "research_action_lifecycle",
                        "action_type": "agent_handoff",
                        "probe_endpoint": "/runtime/research-action-lifecycle",
                        "read_only": True,
                    }
                ],
            },
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
                "provenance": {
                    "derived_from": [
                        "runtime.evidence_integrity_gate",
                        "runtime.research_action_lifecycle_refs",
                    ],
                    "research_action_lifecycle_schema_version": "scholar_ai_research_action_lifecycle_v1",
                },
            },
            "provenance": {
                "derived_from": [
                    "runtime.workflow_passport",
                    "runtime.research_action_lifecycle_refs",
                ],
                "research_action_lifecycle_schema_version": "scholar_ai_research_action_lifecycle_v1",
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
    assert result["data"]["summary"]["research_action_refs"][0]["read_only"] is True
    assert "runtime.research_action_lifecycle_refs" in boundary["provenance"]["derived_from"]
    assert boundary["provenance"]["research_action_lifecycle_schema_version"] == (
        "scholar_ai_research_action_lifecycle_v1"
    )
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
                    "updated_at": "2026-06-24T17:55:00+08:00",
                    "checkpoint_id": "20260624-173328-n112-sandboxpolicy-knowledge-runtime-continuatio",
                    "rollback_caveat": "Restore only with explicit user intent after checking dirty worktree ownership.",
                    "requirement_count": 125,
                    "proved_count": 125,
                    "incomplete_count": 0,
                    "out_of_scope_count": 0,
                    "latest_requirement_id": "N112-sandboxpolicy-current-state-alignment",
                    "requirement_status": {
                        "total": 125,
                        "proved": 125,
                        "incomplete": 0,
                        "out_of_scope": 0,
                        "latest_id": "N112-sandboxpolicy-current-state-alignment",
                    },
                    "open_requirements": [],
                    "completion_claim": {
                        "this_slice": "N112 aligned current recovery state with local UIA accessibility-tree evidence.",
                        "full_goal": "The full Scholar AI workflow spine remains active, not complete.",
                        "can_mark_goal_complete": False,
                        "why_not_complete": "Live provider/model actual-loading is still blocked.",
                    },
                    "lifecycle_rollup": {
                        "schema_version": "scholar_ai_goal_lifecycle_rollup_v1",
                        "updated_at": "2026-06-25T23:59:30+08:00",
                        "status": "active_requirements_proved_pending_authorized_gates",
                        "is_goal_complete": False,
                        "can_mark_goal_complete": False,
                        "requirements_all_proved": True,
                        "requirements_all_proved_or_out_of_scope": True,
                        "latest_requirement_id": "N173-goal-lifecycle-rollup",
                        "latest_slice_id": "N173-goal-lifecycle-rollup",
                        "completion_blockers": [
                            {
                                "id": "actual_loading_gate_live_model_proof",
                                "status": "blocked_pending_explicit_authorization",
                                "requirement_surface": "Knowledge Runtime Pipeline QA/agent actual model-context loading",
                                "missing_evidence": "Authorized live provider/model smoke artifact with verdict=ok.",
                                "current_boundary": "Deterministic contract and harness tests are proved.",
                            }
                        ],
                        "machine_readable_completion_rule": "Goal may be marked complete only after blockers clear.",
                        "why_not_complete": [
                            "All requirement rows are proved, but goal-level proof gates remain."
                        ],
                    },
                    "next_authorized_local_actions": [
                        "Create a rollback checkpoint and search mature references before edits.",
                        "Continue deterministic local recovery and proof hardening.",
                        "Keep live provider/model actual-loading blocked until preflight is proved.",
                    ],
                    "stop_boundaries": [
                        "Do not call the long-run goal complete while can_mark_goal_complete is false.",
                        "No push, tag, release, deploy, or external upload.",
                        "Do not run live provider/model without explicit authorization.",
                        "Do not mutate Zotero DB, modify github/ references, or add Feishu/Lark integration.",
                    ],
                    "authoritative_records": [
                        "AI_WORKSPACE_GUIDE.md",
                        "AGENTS.md",
                        "docs/plans/autonomous-execution-framework.md",
                        "docs/plans/autonomous-execution-planning-playbook.md",
                        "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json",
                    ],
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
                "ocr_runtime": {
                    "schema_version": "scholar_ai_ocr_runtime_state_v1",
                    "available": True,
                    "read_only": True,
                    "policy": "engine",
                    "configured_engine": "remote_api",
                    "selected_engine": None,
                    "language": "en",
                    "source": "config",
                    "engine_config": {
                        "api_key": "***",
                        "base_url": "https://ocr.example.test",
                    },
                    "engine_count": 2,
                    "ready_engine_count": 1,
                    "engines": [
                        {
                            "name": "remote_api",
                            "display_name": "Remote OCR API",
                            "engine_type": "remote",
                            "available": False,
                            "requires_network": True,
                            "readiness_status": "configuration_required",
                            "readiness_blockers": ["allow_remote_upload must be true"],
                            "next_safe_local_actions": [
                                "Set allow_remote_upload only after explicit consent."
                            ],
                            "unavailable_reason": "remote upload consent is not enabled",
                        },
                        {
                            "name": "mock_local",
                            "display_name": "Mock Local OCR",
                            "engine_type": "local",
                            "available": True,
                            "requires_network": False,
                            "readiness_status": "ready",
                            "readiness_blockers": [],
                            "next_safe_local_actions": [
                                "Run literature.ocr_execution_probe with confirm_execution=true."
                            ],
                            "unavailable_reason": None,
                        },
                    ],
                    "readiness_blockers": [
                        "OCR policy is engine but remote_api is not ready",
                        "remote_api: allow_remote_upload must be true",
                    ],
                    "warning": "OCR policy is engine but remote_api is not ready",
                    "next_safe_local_actions": [
                        "Inspect literature.ocr_engines before running OCR."
                    ],
                    "error": None,
                },
                "knowledge_actual_loading_gate": {
                    "schema_version": "scholar_ai_krt_actual_loading_gate_state_v1",
                    "available": True,
                    "read_only": True,
                    "status": "blocked",
                    "verdict": "missing_artifact",
                    "artifact_ref": "workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json",
                    "artifact_path": "workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json",
                    "artifact_exists": False,
                    "artifact_schema_valid": False,
                    "artifact_contract_valid": False,
                    "provider_preflight_status": "blocked",
                    "provider_latest_status": "auth_required",
                    "provider_record_count": 1,
                    "auth_required_count": 1,
                    "tool_call_ok_count": 0,
                    "provider_ready_for_authorized_live_smoke": False,
                    "recovery_state": "blocked_provider_preflight_and_missing_live_smoke",
                    "recovery_blocked_by": [
                        "provider_preflight:blocked:auth_required",
                        "live_smoke_artifact:missing",
                    ],
                    "recovery_ref_count": 5,
                    "authorization_required_ref_count": 2,
                    "completion_requires_authorized_live_smoke": True,
                    "missing": [
                        "authorized live provider smoke artifact with verdict=ok",
                        "provider_preflight.status=proved",
                    ],
                    "next_safe_local_actions": [
                        "Require provider_preflight.status=proved before running live context-receipt smoke."
                    ],
                    "claim_boundary": "Deterministic context receipts are proved, but live QA/model loading is not.",
                    "error": None,
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
    assert state["ocr_runtime"]["schema_version"] == "scholar_ai_ocr_runtime_state_v1"
    assert state["ocr_runtime"]["read_only"] is True
    assert state["ocr_runtime"]["policy"] == "engine"
    assert state["ocr_runtime"]["configured_engine"] == "remote_api"
    assert state["ocr_runtime"]["selected_engine"] is None
    assert state["ocr_runtime"]["engine_config"]["api_key"] == "***"
    assert state["ocr_runtime"]["ready_engine_count"] == 1
    assert state["ocr_runtime"]["engines"][0]["readiness_status"] == "configuration_required"
    assert state["ocr_runtime"]["readiness_blockers"][1] == "remote_api: allow_remote_upload must be true"
    assert state["ocr_runtime"]["next_safe_local_actions"] == [
        "Inspect literature.ocr_engines before running OCR."
    ]
    actual_loading_gate = state["knowledge_actual_loading_gate"]
    assert actual_loading_gate["schema_version"] == "scholar_ai_krt_actual_loading_gate_state_v1"
    assert actual_loading_gate["read_only"] is True
    assert actual_loading_gate["status"] == "blocked"
    assert actual_loading_gate["verdict"] == "missing_artifact"
    assert actual_loading_gate["artifact_exists"] is False
    assert actual_loading_gate["artifact_contract_valid"] is False
    assert actual_loading_gate["provider_preflight_status"] == "blocked"
    assert actual_loading_gate["provider_latest_status"] == "auth_required"
    assert actual_loading_gate["auth_required_count"] == 1
    assert actual_loading_gate["tool_call_ok_count"] == 0
    assert actual_loading_gate["provider_ready_for_authorized_live_smoke"] is False
    assert actual_loading_gate["recovery_state"] == "blocked_provider_preflight_and_missing_live_smoke"
    assert actual_loading_gate["authorization_required_ref_count"] == 2
    assert actual_loading_gate["completion_requires_authorized_live_smoke"] is True
    assert actual_loading_gate["missing"] == [
        "authorized live provider smoke artifact with verdict=ok",
        "provider_preflight.status=proved",
    ]
    assert actual_loading_gate["next_safe_local_actions"] == [
        "Require provider_preflight.status=proved before running live context-receipt smoke."
    ]
    assert actual_loading_gate["claim_boundary"] == (
        "Deterministic context receipts are proved, but live QA/model loading is not."
    )
    assert state["goal_state"]["available"] is True
    assert state["goal_state"]["checkpoint_id"] == "20260624-173328-n112-sandboxpolicy-knowledge-runtime-continuatio"
    assert state["goal_state"]["rollback_caveat"] == (
        "Restore only with explicit user intent after checking dirty worktree ownership."
    )
    assert state["goal_state"]["requirement_count"] == 125
    assert state["goal_state"]["incomplete_count"] == 0
    assert state["goal_state"]["latest_requirement_id"] == "N112-sandboxpolicy-current-state-alignment"
    assert state["goal_state"]["requirement_status"]["total"] == 125
    assert state["goal_state"]["requirement_status"]["proved"] == 125
    assert state["goal_state"]["requirement_status"]["incomplete"] == 0
    assert state["goal_state"]["requirement_status"]["out_of_scope"] == 0
    assert state["goal_state"]["requirement_status"]["latest_id"] == "N112-sandboxpolicy-current-state-alignment"
    assert state["goal_state"]["open_requirements"] == []
    assert state["goal_state"]["completion_claim"]["this_slice"] == (
        "N112 aligned current recovery state with local UIA accessibility-tree evidence."
    )
    assert state["goal_state"]["completion_claim"]["full_goal"] == "The full Scholar AI workflow spine remains active, not complete."
    assert state["goal_state"]["completion_claim"]["can_mark_goal_complete"] is False
    assert state["goal_state"]["completion_claim"]["why_not_complete"] == (
        "Live provider/model actual-loading is still blocked."
    )
    assert state["goal_state"]["next_authorized_local_actions"] == [
        "Create a rollback checkpoint and search mature references before edits.",
        "Continue deterministic local recovery and proof hardening.",
        "Keep live provider/model actual-loading blocked until preflight is proved.",
    ]
    assert state["goal_state"]["stop_boundaries"] == [
        "Do not call the long-run goal complete while can_mark_goal_complete is false.",
        "No push, tag, release, deploy, or external upload.",
        "Do not run live provider/model without explicit authorization.",
        "Do not mutate Zotero DB, modify github/ references, or add Feishu/Lark integration.",
    ]
    assert state["goal_state"]["authoritative_records"] == [
        "AI_WORKSPACE_GUIDE.md",
        "AGENTS.md",
        "docs/plans/autonomous-execution-framework.md",
        "docs/plans/autonomous-execution-planning-playbook.md",
        "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json",
    ]
    lifecycle_rollup = state["goal_state"]["lifecycle_rollup"]
    assert lifecycle_rollup["status"] == "active_requirements_proved_pending_authorized_gates"
    assert lifecycle_rollup["is_goal_complete"] is False
    assert lifecycle_rollup["can_mark_goal_complete"] is False
    assert lifecycle_rollup["completion_blockers"][0]["id"] == "actual_loading_gate_live_model_proof"
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


def test_agent_workspace_requirement_reads_goal_requirement_drilldown(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Agent Workspace requirement drilldown should be exposed to MCP callers."""

    backend.set_json(
        "/api/agent-workspace/goal-requirements/B01-computer-use-accessibility-tree",
        {
            "schema_version": "scholar_ai_goal_requirement_drilldown_v1",
            "available": True,
            "read_only": True,
            "path": "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json",
            "updated_at": "2026-06-22T21:36:00+08:00",
            "checkpoint_id": "20260622-213822-n41-goal-state-workspace-visibility",
            "id": "B01-computer-use-accessibility-tree",
            "status": "proved",
            "requirement": "Local UIA accessibility-tree acceptance is restored for the source desktop app.",
            "residual_risk": "External Computer Use package exports issue remains a residual risk.",
            "evidence": [
                {
                    "label": "workspace_artifacts/generated/desktop_smoke/sandboxpolicy-diagnosis-20260623/summary.json",
                    "text": "status passed with root 文献助手 and non-empty UIA tree",
                }
            ],
            "evidence_count": 1,
            "truncated": False,
            "next_safe_local_actions": [
                "Create a rollback checkpoint and search mature references before edits."
            ],
            "stop_boundaries": ["No push, tag, release, deploy, or external upload."],
            "error": None,
        },
    )

    result = tools.agent_workspace_requirement("B01-computer-use-accessibility-tree")

    assert result["is_error"] is False
    data = result["data"]
    assert data["schema_version"] == "scholar_ai_goal_requirement_drilldown_v1"
    assert data["read_only"] is True
    assert data["id"] == "B01-computer-use-accessibility-tree"
    assert data["status"] == "proved"
    assert data["evidence_count"] == 1
    assert data["evidence"][0]["label"] == (
        "workspace_artifacts/generated/desktop_smoke/sandboxpolicy-diagnosis-20260623/summary.json"
    )
    assert backend.calls[-1] == (
        "json",
        "/api/agent-workspace/goal-requirements/B01-computer-use-accessibility-tree",
        None,
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


def test_agent_resource_read_accepts_wiki_refs(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Wiki refs should flow through the same bounded reader contract."""

    tools.agent_resource_read("wiki:concepts/laser-welding.md", max_chars=600, cursor="120")

    assert backend.calls[-1] == (
        "json",
        "/api/agent-bridge/resource/wiki:concepts/laser-welding.md",
        {"max_chars": 600, "cursor": "120"},
    )


def test_agent_resource_read_accepts_skill_package_refs(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Skill package refs should flow through the same bounded reader contract."""

    tools.agent_resource_read(
        "skill_package:academic-english-discourse:chunk:skill-source",
        max_chars=700,
        cursor="0",
    )

    assert backend.calls[-1] == (
        "json",
        "/api/agent-bridge/resource/skill_package:academic-english-discourse:chunk:skill-source",
        {"max_chars": 700, "cursor": "0"},
    )


def test_agent_resource_read_accepts_scoring_rules_refs(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Scoring-rules refs should flow through the same bounded reader contract."""

    tools.agent_resource_read(
        "scoring_rules:section:weights",
        max_chars=700,
        cursor="0",
    )

    assert backend.calls[-1] == (
        "json",
        "/api/agent-bridge/resource/scoring_rules:section:weights",
        {"max_chars": 700, "cursor": "0"},
    )


def test_agent_resource_read_accepts_product_docs_refs(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """Product-doc refs should flow through the same bounded reader contract."""

    tools.agent_resource_read(
        "product_docs:chunk:readme-1-abc123",
        max_chars=500,
        cursor="40",
    )

    assert backend.calls[-1] == (
        "json",
        "/api/agent-bridge/resource/product_docs:chunk:readme-1-abc123",
        {"max_chars": 500, "cursor": "40"},
    )


def test_source_vault_read_accepts_only_source_vault_chunk_refs(
    tools: RuntimeTools,
    backend: FakeBackend,
) -> None:
    """source_vault_read should expose bounded Source Vault refs without becoming a generic proxy."""

    tools.source_vault_read(
        "source_vault:chunk:chunk-abc",
        project_id=" project-1 ",
        max_chars=900,
        cursor=" 20 ",
    )

    assert backend.calls[-1] == (
        "json",
        "/api/agent-bridge/resource/source_vault:chunk:chunk-abc",
        {"max_chars": 900, "project_id": "project-1", "cursor": "20"},
    )

    with pytest.raises(ValueError, match="source_vault:chunk"):
        tools.source_vault_read("wiki:some-page")


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
