from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from lit_assistant_mcp.server import create_mcp_server
import pytest
from starlette.routing import Match


core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

import routers.agent_workspace_router as agent_workspace_router
import routers.agent_bridge_router as agent_bridge_router_module
import routers.knowledge_router as knowledge_router_module
import routers.pdf_backend_router as pdf_backend_router_module
import routers.runtime_router as runtime_router_module
import python_adapter_server as server
from literature_assistant.core import academic_english_resources, product_docs_knowledge
from harness_protocols import JobKind, SessionMode
from source_vault import SourceChunkInput, SourceVault, build_source_vault_chunk_ref_id
from wiki.source_registry import ChunkInput, SourceRecord, WikiRegistry
from writing_runtime import WritingRuntime


def _agent_workspace_probe_url(
    probe: Mapping[str, object],
    *,
    identifiers: Mapping[str, str] | None = None,
) -> str:
    """Return the concrete local URL advertised by an Agent Workspace recovery probe."""

    raw_route = probe.get("route")
    if not isinstance(raw_route, str) or not raw_route.strip():
        raise AssertionError("Agent Workspace recovery probe route must be a non-empty string.")
    replacements = {
        "{job_id}": "job-route-proof",
        "{requirement_id}": "N306-agent-workspace-readonly-annotations",
        "{ref_id}": "source-vault:route-proof",
        "{query}": "route-proof",
    }
    if identifiers is not None:
        for token, value in identifiers.items():
            if not token.startswith("{") or not token.endswith("}") or not value.strip():
                raise AssertionError(f"Invalid Agent Workspace recovery probe identifier: {token!r}")
            replacements[token] = value
    concrete_route = raw_route.strip()
    for token, value in replacements.items():
        concrete_route = concrete_route.replace(token, value)
    if "{" in concrete_route or "}" in concrete_route:
        raise AssertionError(f"Agent Workspace recovery probe route has unresolved identifiers: {raw_route}")
    return concrete_route


def _agent_workspace_probe_path(
    probe: Mapping[str, object],
    *,
    identifiers: Mapping[str, str] | None = None,
) -> str:
    """Return the local path advertised by an Agent Workspace recovery probe."""

    concrete_route = _agent_workspace_probe_url(probe, identifiers=identifiers)
    path = urlsplit(concrete_route).path
    if not path.startswith("/"):
        raise AssertionError(f"Agent Workspace recovery probe route must be absolute: {concrete_route}")
    return path


def _assert_agent_workspace_probe_resolves_to_full_app_read_route(
    probe: Mapping[str, object],
    *,
    method: str,
    identifiers: Mapping[str, str] | None = None,
) -> None:
    """Assert an Agent Workspace recovery probe points at a registered local read route."""

    if method not in {"GET", "POST"}:
        raise AssertionError(f"Unsupported Agent Workspace recovery probe method: {method}")
    assert probe.get("read_only") is True
    path = _agent_workspace_probe_path(probe, identifiers=identifiers)
    assert "_passport" not in path
    assert "_gate" not in path
    assert "_card" not in path
    matches: list[str] = []
    for route in server.app.routes:
        route_path = str(getattr(route, "path", ""))
        if route_path == "/{full_path:path}":
            continue
        route_methods = getattr(route, "methods", None)
        if route_methods is not None and method not in route_methods:
            continue
        if not hasattr(route, "matches"):
            continue
        match, _ = route.matches({"type": "http", "path": path, "method": method})
        if match is not Match.NONE:
            matches.append(route_path)
    assert matches, f"Agent Workspace probe does not resolve to a full-app {method} route: {path}"


def _assert_agent_workspace_probe_resolves_to_full_app_get_route(
    probe: Mapping[str, object],
    *,
    identifiers: Mapping[str, str] | None = None,
) -> None:
    """Assert an Agent Workspace recovery probe points at a registered local GET route."""

    _assert_agent_workspace_probe_resolves_to_full_app_read_route(
        probe,
        method="GET",
        identifiers=identifiers,
    )


def _assert_agent_workspace_probe_returns_http_success(
    client: TestClient,
    probe: Mapping[str, object],
    *,
    headers: Mapping[str, str],
    identifiers: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Assert a read-only Agent Workspace recovery probe returns local HTTP 200.

    Args:
        client: FastAPI TestClient bound to the full Scholar AI app.
        probe: Serialized Agent Workspace recovery probe payload.
        headers: Capability headers required by protected local diagnostic routes.
        identifiers: Concrete route identifiers for templated read-only recovery probes.
    """

    method = probe.get("method")
    if method != "GET":
        raise AssertionError(f"Only GET recovery probes are safe for HTTP-success proof: {probe!r}")
    _assert_agent_workspace_probe_resolves_to_full_app_get_route(probe, identifiers=identifiers)
    url = _agent_workspace_probe_url(probe, identifiers=identifiers)
    response = client.get(url, headers=dict(headers))
    assert response.status_code == 200, f"{url} returned {response.status_code}: {response.text}"
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"{url} must return a JSON object payload.")
    return payload


def _assert_agent_workspace_probe_mcp_tool_is_read_only(
    probe: Mapping[str, object],
    server_tools: Mapping[str, object],
) -> None:
    """Assert a recovery probe's advertised MCP tool declares the local read contract."""

    mcp_tool = probe.get("mcp_tool")
    if not isinstance(mcp_tool, str) or not mcp_tool.strip():
        raise AssertionError(f"Agent Workspace recovery probe lacks an MCP tool: {probe!r}")
    tool = server_tools.get(mcp_tool)
    assert tool is not None, f"Agent Workspace probe advertises an unregistered MCP tool: {mcp_tool}"
    annotations = getattr(tool, "annotations", None)
    assert annotations is not None, f"Agent Workspace probe MCP tool lacks annotations: {mcp_tool}"
    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is True
    assert annotations.openWorldHint is False


def _seed_agent_workspace_source_vault(vault: SourceVault) -> str:
    """Seed a disposable Source Vault chunk for read-only recovery probes."""

    source = vault.upsert_source_bytes(
        b"paper bytes for agent workspace source vault proof",
        filename="agent-workspace-source.pdf",
        source_type="pdf",
        title="Agent Workspace Source Vault Proof",
        parser_version="parser-v1",
        chunker_version="chunker-v1",
        project_id="agent-workspace-project",
        now_iso="2026-06-29T06:45:00Z",
    ).source
    vault.register_chunks(
        source.source_id,
        [
            SourceChunkInput(
                text=(
                    "AgentWorkspaceSourceVaultAnchor proves the advertised Source Vault "
                    "search ref is readable as a bounded Agent Bridge resource."
                ),
                chunk_index=0,
                page=1,
            )
        ],
        now_iso="2026-06-29T06:46:00Z",
    )
    results = vault.search_chunks("AgentWorkspaceSourceVaultAnchor", limit=1)
    if not results:
        raise AssertionError("Seeded Source Vault chunk must be searchable.")
    return build_source_vault_chunk_ref_id(results[0].chunk_id)


def _seed_agent_workspace_academic_english(root: Path) -> None:
    """Seed generated academic-English artifacts for full-app search probes."""

    root.mkdir(parents=True, exist_ok=True)
    chunk_text = (
        "AgentWorkspaceAcademicAnchor calibrates claims so resumed agents can "
        "recover academic-English refs through a read-only search endpoint."
    )
    phrase_text = "These findings should be interpreted within the local proof boundary."
    source_hash = hashlib.sha256(b"agent workspace academic source").hexdigest()
    chunk_record = {
        "chunk_id": "chunk-agent-workspace-academic",
        "source_id": "source-agent-workspace",
        "source_type": "text",
        "source_path": "workspace_references/agent-workspace-academic.txt",
        "source_hash": source_hash,
        "title": "Agent Workspace Academic Proof",
        "locator": "agent-workspace-academic.txt",
        "section": "discussion",
        "text": chunk_text,
        "summary": "AgentWorkspaceAcademicAnchor calibrates claims.",
        "content_hash": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        "span_start": 0,
        "span_end": len(chunk_text),
        "rhetorical_moves": ["limitation"],
        "features": ["hedging"],
        "keywords": ["AgentWorkspaceAcademicAnchor", "claims"],
        "char_count": len(chunk_text),
        "word_count": len(chunk_text.split()),
    }
    phrase_record = {
        "phrase_id": "phrase-agent-workspace-academic",
        "source_id": "source-agent-workspace",
        "source_type": "text",
        "source_path": "workspace_references/agent-workspace-academic.txt",
        "source_hash": source_hash,
        "text": phrase_text,
        "normalized": "these findings should be interpreted",
        "content_hash": hashlib.sha256(phrase_text.encode("utf-8")).hexdigest(),
        "span_start": 0,
        "span_end": len(phrase_text),
        "move": "limitation",
        "features": ["hedging"],
        "section": "discussion",
        "locator": "agent-workspace-academic.txt",
        "adaptation_note": "Use when limiting a claim.",
    }
    habits = {
        "schema_version": "0.2",
        "knowledge_type": "academic_english_habits",
        "policy_markdown": "# Academic English Discourse Habits\n\nHedging protects evidential scope.",
        "policy_source": "references/english_discourse_habits.md",
        "policy_source_path": "references/english_discourse_habits.md",
        "policy_loaded": True,
        "policy_load_status": "loaded",
        "policy_content_hash": hashlib.sha256(
            "# Academic English Discourse Habits\n\nHedging protects evidential scope.".encode("utf-8")
        ).hexdigest(),
        "policy_char_count": 71,
        "purpose": "Help Scholar AI plan academic prose.",
    }
    chunks_path = root / "chunks.jsonl"
    phrases_path = root / "phrases.jsonl"
    habits_path = root / "academic_english_habits.json"
    frames_path = root / "discourse_frames.json"
    report_path = root / "build_report.md"
    chunks_path.write_text(json.dumps(chunk_record, ensure_ascii=False) + "\n", encoding="utf-8")
    phrases_path.write_text(json.dumps(phrase_record, ensure_ascii=False) + "\n", encoding="utf-8")
    habits_path.write_text(json.dumps(habits, ensure_ascii=False), encoding="utf-8")
    frames_path.write_text("[]", encoding="utf-8")
    report_path.write_text("# report\n", encoding="utf-8")
    manifest = {
        "schema_version": "0.2",
        "builder_version": "0.2.0",
        "built_at": "2026-06-29T06:45:00+08:00",
        "counts": {"chunks": 1, "phrases": 1},
        "warnings": [],
        "errors": [],
        "knowledge_sources": {
            "academic_english_habits": {
                "source_path": "references/english_discourse_habits.md",
                "source_label": "references/english_discourse_habits.md",
                "loaded": True,
                "load_status": "loaded",
                "content_hash": habits["policy_content_hash"],
                "char_count": habits["policy_char_count"],
            }
        },
        "output_artifacts": {
            "chunks_jsonl": {
                "path": "chunks.jsonl",
                "exists": True,
                "bytes": chunks_path.stat().st_size,
                "sha256": hashlib.sha256(chunks_path.read_bytes()).hexdigest(),
                "status": "written",
                "rows": 1,
            },
            "phrases_jsonl": {
                "path": "phrases.jsonl",
                "exists": True,
                "bytes": phrases_path.stat().st_size,
                "sha256": hashlib.sha256(phrases_path.read_bytes()).hexdigest(),
                "status": "written",
                "rows": 1,
            },
            "academic_english_habits_json": {
                "path": "academic_english_habits.json",
                "exists": True,
                "bytes": habits_path.stat().st_size,
                "sha256": hashlib.sha256(habits_path.read_bytes()).hexdigest(),
                "status": "written",
            },
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _seed_agent_workspace_product_docs(repo_root: Path) -> None:
    """Seed isolated product docs for read-only recovery search probes."""

    docs_root = repo_root / "docs"
    docs_root.mkdir(parents=True)
    (repo_root / "README.md").write_text(
        "# Scholar AI\n\nAgentWorkspaceProductDocsAnchor documents local MCP-first recovery.",
        encoding="utf-8",
    )
    (docs_root / "MCP_SECURITY_ISOLATION.md").write_text(
        "# MCP Security Isolation\n\nExternal agents inspect bounded refs before mutating local workflow state.",
        encoding="utf-8",
    )


def test_agent_workspace_core_recovery_probes_return_http_success(monkeypatch) -> None:
    """Core recovery probes must be live local HTTP links, not only route-shaped metadata."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "agent-workspace-http-proof"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="agent workspace recovery probe HTTP proof",
        metadata={"project_id": "agent-workspace-http-proof"},
    )
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    client = TestClient(server.app)
    headers = {"X-LitAssist-Capability": server.get_local_api_capability_token()}
    response = client.get("/api/agent-workspace/status", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    goal_state = payload["workspace_state"]["goal_state"]
    latest_requirement_id = goal_state["latest_requirement_id"]
    assert isinstance(latest_requirement_id, str) and latest_requirement_id.strip()
    probes = {
        probe["label"]: probe
        for probe in payload["workspace_state"]["recovery_probes"]
        if isinstance(probe.get("label"), str)
    }
    expected_labels = {
        "Agent Workspace Status",
        "Goal Lifecycle Completion Gate",
        "MCP Result Envelope",
        "Workflow Passport",
        "Evidence Integrity Gate",
        "Research Action Lifecycle",
        "Agent Handoff Card",
        "Goal Requirement Drilldown",
    }
    assert expected_labels <= set(probes)
    identifiers_by_label = {
        "Agent Handoff Card": {"{job_id}": job.job_id},
        "Goal Requirement Drilldown": {"{requirement_id}": latest_requirement_id},
    }

    for label in sorted(expected_labels):
        _assert_agent_workspace_probe_returns_http_success(
            client,
            probes[label],
            headers=headers,
            identifiers=identifiers_by_label.get(label),
        )


def test_agent_workspace_ocr_status_probe_returns_http_success_and_matches_status_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OCR runtime recovery must stay read-only and match the advertised status probe."""

    ocr_status_payload = {
        "policy": "engine",
        "configured_engine": "mock_local",
        "selected_engine": "mock_local",
        "language": "en",
        "source": "test_config",
        "engine_config": {
            "api_key": "sk-test-redacted",
            "base_url": "https://ocr.example.test",
            "nested": {"value": "shape-only"},
        },
        "available_engines": [
            {
                "name": "mock_local",
                "display_name": "Mock Local OCR",
                "engine_type": "local",
                "available": True,
                "requires_network": False,
                "readiness_status": "ready",
                "readiness_blockers": [],
                "next_safe_local_actions": ["Run OCR only through an explicit execution probe."],
            },
            {
                "name": "remote_api",
                "display_name": "Remote OCR API",
                "engine_type": "remote",
                "available": False,
                "requires_network": True,
                "unavailable_reason": "remote OCR requires explicit upload consent",
                "readiness_status": "configuration_required",
                "readiness_blockers": ["allow_remote_upload must be true"],
                "next_safe_local_actions": ["Keep remote OCR disabled until upload consent is explicit."],
            },
        ],
        "warning": "OCR policy is engine and mock_local is ready for explicit local probes only",
        "next_safe_local_actions": ["Inspect literature.ocr_engines before running OCR."],
    }
    monkeypatch.setattr(agent_workspace_router, "public_ocr_status", lambda: ocr_status_payload)
    monkeypatch.setattr(pdf_backend_router_module, "public_ocr_status", lambda: ocr_status_payload)

    client = TestClient(server.app)
    headers = {"X-LitAssist-Capability": server.get_local_api_capability_token()}
    response = client.get("/api/agent-workspace/status", headers=headers)
    assert response.status_code == 200
    workspace_state = response.json()["workspace_state"]
    ocr_runtime = workspace_state["ocr_runtime"]
    probes = {
        probe["label"]: probe
        for probe in workspace_state["recovery_probes"]
        if isinstance(probe.get("label"), str)
    }
    assert "OCR Runtime Status" in probes

    status_payload = _assert_agent_workspace_probe_returns_http_success(
        client,
        probes["OCR Runtime Status"],
        headers=headers,
    )
    engines_by_name = {engine["name"]: engine for engine in status_payload["available_engines"]}

    assert ocr_runtime["available"] is True
    assert ocr_runtime["read_only"] is True
    assert ocr_runtime["policy"] == status_payload["policy"]
    assert ocr_runtime["configured_engine"] == status_payload["configured_engine"]
    assert ocr_runtime["selected_engine"] == status_payload["selected_engine"]
    assert ocr_runtime["language"] == status_payload["language"]
    assert ocr_runtime["source"] == status_payload["source"]
    assert ocr_runtime["engine_config"] == {
        "api_key": "***",
        "base_url": "https://ocr.example.test",
        "nested": "dict",
    }
    assert ocr_runtime["engine_count"] == len(status_payload["available_engines"])
    assert ocr_runtime["ready_engine_count"] == sum(
        1 for engine in status_payload["available_engines"] if engine["available"] is True
    )
    assert ocr_runtime["warning"] == status_payload["warning"]
    assert ocr_runtime["next_safe_local_actions"] == status_payload["next_safe_local_actions"]
    assert ocr_runtime["engines"][0]["name"] == "mock_local"
    assert ocr_runtime["engines"][0]["readiness_status"] == engines_by_name["mock_local"]["readiness_status"]
    assert ocr_runtime["engines"][1]["name"] == "remote_api"
    assert ocr_runtime["engines"][1]["readiness_blockers"] == engines_by_name["remote_api"][
        "readiness_blockers"
    ]
    assert ocr_runtime["readiness_blockers"] == [
        "OCR policy is engine and mock_local is ready for explicit local probes only",
        "remote_api: allow_remote_upload must be true",
    ]


def test_agent_workspace_krt_actual_loading_gate_probe_returns_http_success_and_matches_status_projection() -> None:
    """KRT actual-loading recovery must be inspectable without live provider execution."""

    client = TestClient(server.app)
    headers = {"X-LitAssist-Capability": server.get_local_api_capability_token()}
    response = client.get("/api/agent-workspace/status", headers=headers)
    assert response.status_code == 200
    workspace_state = response.json()["workspace_state"]
    status_gate = workspace_state["knowledge_actual_loading_gate"]
    probes = {
        probe["label"]: probe
        for probe in workspace_state["recovery_probes"]
        if isinstance(probe.get("label"), str)
    }
    assert "Knowledge Runtime Conformance" in probes

    conformance = _assert_agent_workspace_probe_returns_http_success(
        client,
        probes["Knowledge Runtime Conformance"],
        headers=headers,
    )
    gate = conformance["actual_loading_gate"]
    recovery = gate["recovery"]
    recovery_refs = recovery["recovery_refs"]

    assert status_gate["available"] is True
    assert status_gate["read_only"] is True
    assert status_gate["status"] == gate["status"]
    assert status_gate["verdict"] == gate["verdict"]
    assert status_gate["artifact_ref"] == gate["artifact_ref"]
    assert status_gate["artifact_exists"] is gate["artifact_exists"]
    assert status_gate["artifact_schema_valid"] is gate["artifact_schema_valid"]
    assert status_gate["artifact_contract_valid"] is gate["artifact_contract_valid"]
    assert status_gate["provider_preflight_status"] == gate["provider_preflight"]["status"]
    assert status_gate["provider_latest_status"] == gate["provider_preflight"]["latest_status"]
    assert status_gate["provider_record_count"] == gate["provider_preflight"]["record_count"]
    assert status_gate["auth_required_count"] == gate["provider_preflight"]["auth_required_count"]
    assert status_gate["tool_call_ok_count"] == gate["provider_preflight"]["tool_call_ok_count"]
    assert (
        status_gate["provider_ready_for_authorized_live_smoke"]
        is gate["provider_preflight"]["provider_ready_for_authorized_live_smoke"]
    )
    assert status_gate["recovery_state"] == recovery["state"]
    assert status_gate["recovery_blocked_by"] == recovery["blocked_by"][
        : agent_workspace_router.MAX_KRT_ACTUAL_LOADING_BLOCKERS
    ]
    assert status_gate["recovery_ref_count"] == len(recovery_refs)
    assert status_gate["authorization_required_ref_count"] == sum(
        1 for item in recovery_refs if item["requires_authorization"]
    )
    assert (
        status_gate["completion_requires_authorized_live_smoke"]
        is recovery["completion_requires_authorized_live_smoke"]
    )
    assert status_gate["missing"] == gate["missing"][: agent_workspace_router.MAX_KRT_ACTUAL_LOADING_MISSING]
    assert status_gate["next_safe_local_actions"] == gate["next_safe_local_actions"][
        : agent_workspace_router.MAX_KRT_ACTUAL_LOADING_ACTIONS
    ]
    assert status_gate["claim_boundary"] == gate["claim_boundary"][:240]
    assert any(ref["ref"] == "/api/knowledge/runtime-conformance" for ref in recovery_refs)
    assert any(
        ref["ref"] == "/api/chat/tool-capability/test" and ref["requires_authorization"] is True
        for ref in recovery_refs
    ) or gate["status"] == "proved"


def test_agent_workspace_search_and_resource_recovery_probes_return_http_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Search/resource recovery probes must be live read-only full-app GET links."""

    vault = SourceVault(
        db_path=tmp_path / "source_vault" / "source_vault.sqlite3",
        storage_root=tmp_path / "source_vault",
    )
    source_vault_ref_id = _seed_agent_workspace_source_vault(vault)
    academic_root = tmp_path / "english_discourse"
    product_docs_root = tmp_path / "product_docs_repo"
    _seed_agent_workspace_academic_english(academic_root)
    _seed_agent_workspace_product_docs(product_docs_root)
    monkeypatch.setitem(server.app.dependency_overrides, knowledge_router_module.get_source_vault, lambda: vault)
    monkeypatch.setattr(agent_bridge_router_module, "SourceVault", lambda: vault)
    monkeypatch.setattr(academic_english_resources, "output_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(product_docs_knowledge, "REPO_ROOT", product_docs_root)

    client = TestClient(server.app)
    headers = {"X-LitAssist-Capability": server.get_local_api_capability_token()}
    response = client.get("/api/agent-workspace/status", headers=headers)
    assert response.status_code == 200
    probes = {
        probe["label"]: probe
        for probe in response.json()["workspace_state"]["recovery_probes"]
        if isinstance(probe.get("label"), str)
    }
    expected_labels = {
        "Academic English Search",
        "Product Docs Search",
        "Source Vault Status",
        "Source Vault Search",
        "Source Vault Resource Read",
    }
    assert expected_labels <= set(probes)

    source_status = _assert_agent_workspace_probe_returns_http_success(
        client,
        probes["Source Vault Status"],
        headers=headers,
    )
    assert source_status["total_sources"] == 1

    academic_search = _assert_agent_workspace_probe_returns_http_success(
        client,
        probes["Academic English Search"],
        headers=headers,
        identifiers={"{query}": "AgentWorkspaceAcademicAnchor"},
    )
    assert academic_search["results"]
    assert academic_search["results"][0]["ref_id"] == "academic_english:chunk:chunk-agent-workspace-academic"

    product_docs_search = _assert_agent_workspace_probe_returns_http_success(
        client,
        probes["Product Docs Search"],
        headers=headers,
        identifiers={"{query}": "AgentWorkspaceProductDocsAnchor"},
    )
    assert product_docs_search["results"]
    assert product_docs_search["results"][0]["ref_id"].startswith("product_docs:chunk:")

    source_vault_search = _assert_agent_workspace_probe_returns_http_success(
        client,
        probes["Source Vault Search"],
        headers=headers,
        identifiers={"{query}": "AgentWorkspaceSourceVaultAnchor"},
    )
    assert source_vault_search["results"]
    assert source_vault_search["results"][0]["ref_id"] == source_vault_ref_id

    source_vault_resource = _assert_agent_workspace_probe_returns_http_success(
        client,
        probes["Source Vault Resource Read"],
        headers=headers,
        identifiers={"{ref_id}": source_vault_ref_id},
    )
    assert source_vault_resource["kind"] == "source_vault"
    assert "AgentWorkspaceSourceVaultAnchor" in source_vault_resource["content"]


def test_load_knowledge_actual_loading_gate_state_projects_owner_gate(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "workspace_artifacts" / "generated" / "output" / "live_smoke.json"
    monkeypatch.setattr(agent_workspace_router, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        agent_workspace_router,
        "_read_knowledge_actual_loading_gate",
        lambda: SimpleNamespace(
            status="blocked",
            verdict="missing_artifact",
            artifact_ref="workspace_artifacts/generated/output/live_smoke.json",
            artifact_path=str(artifact),
            artifact_exists=False,
            artifact_schema_valid=False,
            artifact_contract_valid=False,
            provider_preflight=SimpleNamespace(
                status="blocked",
                latest_status="auth_required",
                record_count=2,
                auth_required_count=1,
                tool_call_ok_count=1,
                provider_ready_for_authorized_live_smoke=False,
            ),
            recovery=SimpleNamespace(
                state="blocked_provider_preflight_and_missing_live_smoke",
                blocked_by=["provider_preflight:blocked:auth_required", "live_smoke_artifact:missing"],
                recovery_refs=[
                    SimpleNamespace(requires_authorization=False),
                    SimpleNamespace(requires_authorization=True),
                    SimpleNamespace(requires_authorization=True),
                ],
                completion_requires_authorized_live_smoke=True,
            ),
            missing=[
                "authorized live provider smoke artifact with verdict=ok",
                "provider_preflight.status=proved",
            ],
            next_safe_local_actions=[
                "Require provider_preflight.status=proved before running live context-receipt smoke."
            ],
            claim_boundary="Deterministic context receipts are proved, but live QA/model loading is not.",
        ),
    )

    state = agent_workspace_router._load_knowledge_actual_loading_gate_state()

    assert state.schema_version == "scholar_ai_krt_actual_loading_gate_state_v1"
    assert state.available is True
    assert state.read_only is True
    assert state.status == "blocked"
    assert state.verdict == "missing_artifact"
    assert state.artifact_path == "workspace_artifacts/generated/output/live_smoke.json"
    assert state.artifact_exists is False
    assert state.artifact_contract_valid is False
    assert state.provider_preflight_status == "blocked"
    assert state.provider_latest_status == "auth_required"
    assert state.provider_record_count == 2
    assert state.auth_required_count == 1
    assert state.tool_call_ok_count == 1
    assert state.provider_ready_for_authorized_live_smoke is False
    assert state.recovery_state == "blocked_provider_preflight_and_missing_live_smoke"
    assert state.recovery_blocked_by == [
        "provider_preflight:blocked:auth_required",
        "live_smoke_artifact:missing",
    ]
    assert state.recovery_ref_count == 3
    assert state.authorization_required_ref_count == 2
    assert state.completion_requires_authorized_live_smoke is True
    assert state.missing == [
        "authorized live provider smoke artifact with verdict=ok",
        "provider_preflight.status=proved",
    ]
    assert state.next_safe_local_actions == [
        "Require provider_preflight.status=proved before running live context-receipt smoke."
    ]
    assert state.claim_boundary == "Deterministic context receipts are proved, but live QA/model loading is not."


def test_agent_workspace_status_lists_artifacts_and_redacted_audit(tmp_path, monkeypatch) -> None:
    workspace_root = tmp_path / "agent_mcp_workflows"
    runtime_root = tmp_path / "runtime_state"
    output_root = tmp_path / "generated" / "output"
    desktop_smoke_root = tmp_path / "generated" / "desktop_smoke" / "n75-desktop-smoke"
    unrelated_desktop_smoke_root = tmp_path / "generated" / "desktop_smoke" / "newer-close-path-smoke"
    audit_root = workspace_root / ".audit"
    audit_root.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    output_root.mkdir(parents=True)
    desktop_smoke_root.mkdir(parents=True)
    unrelated_desktop_smoke_root.mkdir(parents=True)
    (desktop_smoke_root / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "n75-desktop-smoke",
                "status": "passed",
                "initial_path": "/__desktop_acceptance/agent-workspace",
                "screenshot_png": str(desktop_smoke_root / "window.png"),
                "accessibility_tree_json": str(desktop_smoke_root / "accessibility-tree.json"),
                "screenshot_nonblank": True,
                "accessibility_tree_available": True,
                "accessibility_tree_root_name": "文献助手",
                "accessibility_tree_root_control_type": "窗口",
                "accessibility_tree_node_count": 20,
                "accessibility_tree_named_node_count": 9,
                "warnings": ["native window could not be foregrounded before screenshot"],
                "errors": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (unrelated_desktop_smoke_root / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "newer-close-path-smoke",
                "status": "passed",
                "initial_path": "/",
                "screenshot_png": str(unrelated_desktop_smoke_root / "window.png"),
                "accessibility_tree_json": str(unrelated_desktop_smoke_root / "accessibility-tree.json"),
                "screenshot_nonblank": True,
                "accessibility_tree_available": True,
                "accessibility_tree_root_name": "文献助手",
                "accessibility_tree_root_control_type": "窗口",
                "accessibility_tree_node_count": 8,
                "accessibility_tree_named_node_count": 4,
                "warnings": ["unrelated close-path smoke should not satisfy Agent Workspace acceptance"],
                "errors": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    newer_mtime = (desktop_smoke_root / "summary.json").stat().st_mtime + 20

    os.utime(unrelated_desktop_smoke_root / "summary.json", (newer_mtime, newer_mtime))
    (workspace_root / "reports").mkdir()
    (workspace_root / "reports" / "summary.md").write_text(
        "Result contains sk-ant-api" + "A" * 60,
        encoding="utf-8",
    )
    (audit_root / "2026-06-17.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-06-17T12:00:00+00:00",
                "tool_name": "literature.search_literature",
                "args_summary": {"endpoint": "/resources/chunks/search"},
                "touched_paths": [],
                "allow_block_reason": "backend_http",
                "result_preview": "Authorization: Bearer " + "B" * 48,
                "duration_ms": 9,
                "error_code": None,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(agent_workspace_router, "WORKSPACE_ARTIFACTS_ROOT", tmp_path)
    monkeypatch.setattr(agent_workspace_router, "WORKSPACE_RUNTIME_STATE_ROOT", runtime_root)
    monkeypatch.setattr(agent_workspace_router, "WORKSPACE_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(agent_workspace_router, "REPO_ROOT", tmp_path)
    wiki_db_path = runtime_root / "wiki.db"
    source_hash = "a" * 64
    registry = WikiRegistry(wiki_db_path, mirror_to_source_vault=False)
    registry.upsert_source(
        SourceRecord(
            source_id="markdown-source-backlog",
            source_type="markdown",
            title="Backlog Source",
            source_hash=source_hash,
            source_path=tmp_path / "source.md",
        ),
        now_iso="2026-06-28T02:00:00+00:00",
    )
    registry.register_chunks(
        "markdown-source-backlog",
        source_hash,
        [
            ChunkInput(
                chunk_index=0,
                text="Backlog source text should be visible only as counts.",
                page=None,
                section="Overview",
                span_start=0,
                span_end=52,
            )
        ],
        now_iso="2026-06-28T02:00:00+00:00",
    )
    monkeypatch.setattr(agent_workspace_router, "wiki_enabled", lambda: True)
    monkeypatch.setattr(agent_workspace_router, "wiki_runtime_db_path", lambda: wiki_db_path)
    monkeypatch.setattr(
        agent_workspace_router,
        "_read_git_workspace_state",
        lambda: agent_workspace_router.AgentWorkspaceGitState(
            available=True,
            branch="main",
            ahead=33,
            changed_count=2,
            unstaged_count=1,
            untracked_count=1,
            dirty_paths=["literature_assistant/core/routers/agent_workspace_router.py", "docs/plans"],
        ),
    )
    monkeypatch.setattr(
        agent_workspace_router,
        "_load_goal_state_summary",
        lambda: agent_workspace_router.AgentWorkspaceGoalState(
            available=True,
            path="docs/plans/longrun-goal-state-local.json",
            updated_at="2026-06-24T17:55:00+08:00",
            checkpoint_id="20260624-173328-n112-sandboxpolicy-knowledge-runtime-continuatio",
            rollback_caveat="Restore only with explicit user intent after checking dirty worktree ownership.",
            requirement_count=125,
            proved_count=125,
            incomplete_count=0,
            out_of_scope_count=0,
            latest_requirement_id="N112-sandboxpolicy-current-state-alignment",
            requirement_status=agent_workspace_router.AgentWorkspaceGoalRequirementStatus(
                total=125,
                proved=125,
                incomplete=0,
                out_of_scope=0,
                latest_id="N112-sandboxpolicy-current-state-alignment",
            ),
            open_requirements=[],
            completion_claim=agent_workspace_router.AgentWorkspaceGoalCompletionClaim(
                this_slice="N112 aligned current recovery state with local UIA accessibility-tree evidence.",
                full_goal="The full Scholar AI workflow spine remains active, not complete.",
                can_mark_goal_complete=False,
                why_not_complete="Live provider/model actual-loading is still blocked.",
            ),
            next_authorized_local_actions=[
                "Create a rollback checkpoint and search mature references before the next slice."
            ],
            stop_boundaries=["No push, tag, release, deploy, or external upload."],
            mature_references_checked=[
                agent_workspace_router.AgentWorkspaceGoalMatureReference(
                    topic="N112 recovery state response model",
                    source="FastAPI response-model documentation",
                    url="https://fastapi.tiangolo.com/tutorial/response-model/",
                    status="HEAD checked 200",
                    checked_at="2026-06-24T17:55:00+08:00",
                    use_in_slice="Keep the recovery state on the typed status response.",
                )
            ],
            changed_files_for_this_slice=[
                "literature_assistant/core/routers/agent_workspace_router.py",
                "tests/test_agent_workspace_router.py",
            ],
            verification_commands=[
                ".\\.venv-1\\Scripts\\python.exe -m pytest tests\\test_agent_workspace_router.py -q -> passed",
            ],
        ),
    )
    monkeypatch.setattr(
        agent_workspace_router,
        "public_ocr_status",
        lambda: {
            "policy": "engine",
            "configured_engine": "remote_api",
            "selected_engine": None,
            "language": "en",
            "source": "config",
            "engine_config": {
                "api_key": "raw-secret-should-not-leak",
                "base_url": "https://ocr.example.test",
                "nested": {"hidden": "value"},
            },
            "available_engines": [
                {
                    "name": "remote_api",
                    "display_name": "Remote OCR API",
                    "engine_type": "remote",
                    "available": False,
                    "requires_network": True,
                    "unavailable_reason": "remote upload consent is not enabled",
                    "readiness_status": "configuration_required",
                    "readiness_blockers": ["allow_remote_upload must be true"],
                    "next_safe_local_actions": ["Set allow_remote_upload only after explicit consent."],
                },
                {
                    "name": "mock_local",
                    "display_name": "Mock Local OCR",
                    "engine_type": "local",
                    "available": True,
                    "requires_network": False,
                    "unavailable_reason": None,
                    "readiness_status": "ready",
                    "readiness_blockers": [],
                    "next_safe_local_actions": ["Run literature.ocr_execution_probe with confirm_execution=true."],
                },
            ],
            "warning": "OCR policy is engine but remote_api is not ready",
            "next_safe_local_actions": ["Inspect literature.ocr_engines before running OCR."],
        },
    )
    monkeypatch.setattr(
        agent_workspace_router,
        "_load_knowledge_actual_loading_gate_state",
        lambda: agent_workspace_router.AgentWorkspaceKnowledgeActualLoadingGateState(
            available=True,
            status="blocked",
            verdict="missing_artifact",
            artifact_ref="workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json",
            artifact_path="workspace_artifacts/generated/output/live_api_chat_knowledge_context_receipt_smoke.summary.json",
            artifact_exists=False,
            artifact_schema_valid=False,
            artifact_contract_valid=False,
            provider_preflight_status="blocked",
            provider_latest_status="auth_required",
            provider_record_count=1,
            auth_required_count=1,
            tool_call_ok_count=0,
            provider_ready_for_authorized_live_smoke=False,
            recovery_state="blocked_provider_preflight_and_missing_live_smoke",
            recovery_blocked_by=["provider_preflight:blocked:auth_required", "live_smoke_artifact:missing"],
            recovery_ref_count=5,
            authorization_required_ref_count=2,
            completion_requires_authorized_live_smoke=True,
            missing=[
                "authorized live provider smoke artifact with verdict=ok",
                "provider_preflight.status=proved",
            ],
            next_safe_local_actions=[
                "Require provider_preflight.status=proved before running live context-receipt smoke."
            ],
            claim_boundary="Deterministic context receipts are proved, but live QA/model loading is not.",
        ),
    )
    monkeypatch.setenv("LITASSIST_API_CAPABILITY_AUTH", "1")
    client = TestClient(server.app)

    response = client.get(
        "/api/agent-workspace/status",
        headers={server.LOCAL_API_CAPABILITY_HEADER: server.get_local_api_capability_token()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_count"] == 1
    assert payload["audit_count"] == 1
    assert payload["workspace_state"]["schema_version"] == "scholar_ai_agent_workspace_state_v1"
    assert payload["workspace_state"]["workspace_ready"] is True
    assert payload["workspace_state"]["read_only"] is True
    assert payload["workspace_state"]["git"]["branch"] == "main"
    assert payload["workspace_state"]["git"]["ahead"] == 33
    assert payload["workspace_state"]["git"]["changed_count"] == 2
    assert payload["workspace_state"]["git"]["dirty_paths"] == [
        "literature_assistant/core/routers/agent_workspace_router.py",
        "docs/plans",
    ]
    assert payload["workspace_state"]["artifact_root"]["file_count"] == 1
    assert payload["workspace_state"]["artifact_root"]["path"] == "agent_mcp_workflows"
    assert payload["workspace_state"]["artifact_root"]["truncated"] is False
    assert payload["workspace_state"]["runtime_state_root"]["exists"] is True
    assert payload["workspace_state"]["output_root"]["exists"] is True
    desktop_smoke = payload["workspace_state"]["desktop_smoke"]
    assert desktop_smoke["schema_version"] == "scholar_ai_desktop_smoke_state_v1"
    assert desktop_smoke["available"] is True
    assert desktop_smoke["read_only"] is True
    assert desktop_smoke["run_id"] == "n75-desktop-smoke"
    assert desktop_smoke["status"] == "passed"
    assert desktop_smoke["initial_path"] == "/__desktop_acceptance/agent-workspace"
    assert desktop_smoke["expected_initial_path"] == "/__desktop_acceptance/agent-workspace"
    assert desktop_smoke["candidate_count"] == 2
    assert desktop_smoke["ignored_count"] == 1
    assert desktop_smoke["summary_path"] == "generated/desktop_smoke/n75-desktop-smoke/summary.json"
    assert desktop_smoke["screenshot_path"] == "generated/desktop_smoke/n75-desktop-smoke/window.png"
    assert desktop_smoke["accessibility_tree_path"] == "generated/desktop_smoke/n75-desktop-smoke/accessibility-tree.json"
    assert desktop_smoke["screenshot_nonblank"] is True
    assert desktop_smoke["accessibility_tree_available"] is True
    assert desktop_smoke["accessibility_tree_root_name"] == "文献助手"
    assert desktop_smoke["accessibility_tree_root_control_type"] == "窗口"
    assert desktop_smoke["accessibility_tree_node_count"] == 20
    assert desktop_smoke["accessibility_tree_named_node_count"] == 9
    assert desktop_smoke["warnings"] == ["native window could not be foregrounded before screenshot"]
    assert desktop_smoke["errors"] == []
    ocr_runtime = payload["workspace_state"]["ocr_runtime"]
    assert ocr_runtime["schema_version"] == "scholar_ai_ocr_runtime_state_v1"
    assert ocr_runtime["available"] is True
    assert ocr_runtime["read_only"] is True
    assert ocr_runtime["policy"] == "engine"
    assert ocr_runtime["configured_engine"] == "remote_api"
    assert ocr_runtime["selected_engine"] is None
    assert ocr_runtime["language"] == "en"
    assert ocr_runtime["source"] == "config"
    assert ocr_runtime["engine_config"] == {
        "api_key": "***",
        "base_url": "https://ocr.example.test",
        "nested": "dict",
    }
    assert ocr_runtime["engine_count"] == 2
    assert ocr_runtime["ready_engine_count"] == 1
    assert ocr_runtime["engines"][0]["name"] == "remote_api"
    assert ocr_runtime["engines"][0]["readiness_status"] == "configuration_required"
    assert ocr_runtime["engines"][0]["readiness_blockers"] == ["allow_remote_upload must be true"]
    assert ocr_runtime["engines"][1]["available"] is True
    assert ocr_runtime["warning"] == "OCR policy is engine but remote_api is not ready"
    assert ocr_runtime["readiness_blockers"][:2] == [
        "OCR policy is engine but remote_api is not ready",
        "remote_api: allow_remote_upload must be true",
    ]
    assert ocr_runtime["next_safe_local_actions"] == ["Inspect literature.ocr_engines before running OCR."]
    wiki_doctor = payload["workspace_state"]["wiki_doctor"]
    assert wiki_doctor["schema_version"] == "scholar_ai_wiki_doctor_state_v1"
    assert wiki_doctor["available"] is True
    assert wiki_doctor["read_only"] is True
    assert wiki_doctor["status"] == "warning"
    assert wiki_doctor["registry_db_path"] == "runtime_state/wiki.db"
    assert wiki_doctor["source_count"] == 1
    assert wiki_doctor["chunk_count"] == 1
    assert wiki_doctor["pending_source_count"] == 1
    assert wiki_doctor["pending_chunk_count"] == 1
    assert wiki_doctor["needs_replay"] is True
    assert wiki_doctor["source_status_counts"] == {"not_mirrored": 1}
    assert wiki_doctor["chunk_status_counts"] == {"not_mirrored": 1}
    assert wiki_doctor["sample_count"] == 2
    assert wiki_doctor["samples"][0] == {
        "record_type": "source",
        "record_id": "markdown-source-backlog",
        "source_id": "markdown-source-backlog",
        "status": "not_mirrored",
        "error": None,
    }
    assert wiki_doctor["samples"][1]["record_type"] == "chunk"
    assert wiki_doctor["samples"][1]["source_id"] == "markdown-source-backlog"
    assert wiki_doctor["samples"][1]["status"] == "not_mirrored"
    assert wiki_doctor["samples"][1]["error"] is None
    assert wiki_doctor["action_count"] == 1
    assert "Source Vault mirror backlog has 1 source rows and 1 chunk rows pending replay." == wiki_doctor["warning"]
    assert wiki_doctor["next_safe_local_actions"] == [
        "Read /api/wiki/doctor, then run an explicit local maintenance slice before WikiRegistry.replay_source_vault_mirror()."
    ]
    actual_loading_gate = payload["workspace_state"]["knowledge_actual_loading_gate"]
    assert actual_loading_gate["schema_version"] == "scholar_ai_krt_actual_loading_gate_state_v1"
    assert actual_loading_gate["available"] is True
    assert actual_loading_gate["read_only"] is True
    assert actual_loading_gate["status"] == "blocked"
    assert actual_loading_gate["verdict"] == "missing_artifact"
    assert actual_loading_gate["artifact_exists"] is False
    assert actual_loading_gate["artifact_contract_valid"] is False
    assert actual_loading_gate["provider_preflight_status"] == "blocked"
    assert actual_loading_gate["provider_latest_status"] == "auth_required"
    assert actual_loading_gate["provider_record_count"] == 1
    assert actual_loading_gate["auth_required_count"] == 1
    assert actual_loading_gate["tool_call_ok_count"] == 0
    assert actual_loading_gate["provider_ready_for_authorized_live_smoke"] is False
    assert actual_loading_gate["recovery_state"] == "blocked_provider_preflight_and_missing_live_smoke"
    assert actual_loading_gate["recovery_blocked_by"] == [
        "provider_preflight:blocked:auth_required",
        "live_smoke_artifact:missing",
    ]
    assert actual_loading_gate["recovery_ref_count"] == 5
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
    goal_state = payload["workspace_state"]["goal_state"]
    assert goal_state["available"] is True
    assert goal_state["path"] == "docs/plans/longrun-goal-state-local.json"
    assert goal_state["checkpoint_id"] == "20260624-173328-n112-sandboxpolicy-knowledge-runtime-continuatio"
    assert goal_state["rollback_caveat"] == (
        "Restore only with explicit user intent after checking dirty worktree ownership."
    )
    assert goal_state["mature_references_checked"][0]["topic"] == "N112 recovery state response model"
    assert goal_state["mature_references_checked"][0]["source"] == "FastAPI response-model documentation"
    assert goal_state["changed_files_for_this_slice"] == [
        "literature_assistant/core/routers/agent_workspace_router.py",
        "tests/test_agent_workspace_router.py",
    ]
    assert goal_state["verification_commands"] == [
        ".\\.venv-1\\Scripts\\python.exe -m pytest tests\\test_agent_workspace_router.py -q -> passed"
    ]
    assert goal_state["requirement_count"] == 125
    assert goal_state["proved_count"] == 125
    assert goal_state["incomplete_count"] == 0
    assert goal_state["out_of_scope_count"] == 0
    assert goal_state["latest_requirement_id"] == "N112-sandboxpolicy-current-state-alignment"
    assert goal_state["requirement_status"] == {
        "total": 125,
        "proved": 125,
        "incomplete": 0,
        "out_of_scope": 0,
        "latest_id": "N112-sandboxpolicy-current-state-alignment",
    }
    assert goal_state["open_requirements"] == []
    assert goal_state["completion_claim"]["this_slice"] == (
        "N112 aligned current recovery state with local UIA accessibility-tree evidence."
    )
    assert goal_state["completion_claim"]["full_goal"] == "The full Scholar AI workflow spine remains active, not complete."
    probes = payload["workspace_state"]["recovery_probes"]
    assert [probe["label"] for probe in probes] == [
        "Desktop Smoke Evidence",
        "OCR Runtime Status",
        "Wiki Doctor",
        "Knowledge Runtime Conformance",
        "Knowledge Packages",
        "Wiki Search",
        "Academic English Search",
        "Product Docs Search",
        "Source Vault Status",
        "Source Vault Search",
        "Source Vault Resource Read",
        "Knowledge Context Receipt",
        "MCP Result Envelope",
        "Goal Lifecycle Completion Gate",
        "Workflow Passport",
        "Evidence Integrity Gate",
        "Research Action Lifecycle",
        "Agent Handoff Card",
        "Agent Workspace Status",
        "Goal Requirement Drilldown",
    ]
    assert all(probe["read_only"] is True for probe in probes)
    server_tools = {tool.name: tool for tool in create_mcp_server()._tool_manager.list_tools()}
    for probe in probes:
        method = probe.get("method")
        assert method in {"GET", "POST"}
        _assert_agent_workspace_probe_resolves_to_full_app_read_route(probe, method=method)
        _assert_agent_workspace_probe_mcp_tool_is_read_only(probe, server_tools)
    desktop_probe = next(probe for probe in probes if probe["label"] == "Desktop Smoke Evidence")
    assert desktop_probe["route"] == "/api/agent-workspace/status"
    assert desktop_probe["mcp_tool"] == "literature.agent_workspace_status"
    assert "source desktop screenshot" in desktop_probe["purpose"]
    ocr_probe = next(probe for probe in probes if probe["label"] == "OCR Runtime Status")
    assert ocr_probe["route"] == "/api/pdf-backend/ocr-status"
    assert ocr_probe["mcp_tool"] == "literature.ocr_status"
    assert "OCR policy" in ocr_probe["purpose"]
    assert "readiness blockers" in ocr_probe["purpose"]
    wiki_doctor_probe = next(probe for probe in probes if probe["label"] == "Wiki Doctor")
    assert wiki_doctor_probe["route"] == "/api/wiki/doctor"
    assert wiki_doctor_probe["mcp_tool"] == "literature.wiki_doctor"
    assert "wiki integrity diagnostics" in wiki_doctor_probe["purpose"]
    assert "Source Vault mirror backlog" in wiki_doctor_probe["purpose"]
    krt_probe = next(probe for probe in probes if probe["label"] == "Knowledge Runtime Conformance")
    assert krt_probe["route"] == "/api/knowledge/runtime-conformance"
    assert krt_probe["mcp_tool"] == "literature.knowledge_runtime_conformance"
    assert "actual-loading gate state" in krt_probe["purpose"]
    assert "model-context readiness" in krt_probe["purpose"]
    packages_probe = next(probe for probe in probes if probe["label"] == "Knowledge Packages")
    assert packages_probe["route"] == "/api/knowledge/packages"
    assert packages_probe["mcp_tool"] == "literature.knowledge_packages"
    assert "source paths" in packages_probe["purpose"]
    assert "runtime consumers" in packages_probe["purpose"]
    wiki_search_probe = next(probe for probe in probes if probe["label"] == "Wiki Search")
    assert wiki_search_probe["route"] == "/api/wiki/search"
    assert wiki_search_probe["method"] == "POST"
    assert wiki_search_probe["mcp_tool"] == "literature.wiki_search"
    assert wiki_search_probe["requires_identifier"] is True
    assert wiki_search_probe["identifier_hint"] == "query"
    assert "wiki refs" in wiki_search_probe["purpose"]
    academic_search_probe = next(probe for probe in probes if probe["label"] == "Academic English Search")
    assert academic_search_probe["route"] == "/api/knowledge/academic-english/search?q={query}"
    assert academic_search_probe["method"] == "GET"
    assert academic_search_probe["mcp_tool"] == "literature.academic_english_search"
    assert academic_search_probe["requires_identifier"] is True
    assert academic_search_probe["identifier_hint"] == "query"
    assert "academic-English refs" in academic_search_probe["purpose"]
    product_docs_search_probe = next(probe for probe in probes if probe["label"] == "Product Docs Search")
    assert product_docs_search_probe["route"] == "/api/knowledge/product-docs/search?q={query}"
    assert product_docs_search_probe["mcp_tool"] == "literature.product_docs_search"
    assert product_docs_search_probe["requires_identifier"] is True
    assert product_docs_search_probe["identifier_hint"] == "query"
    assert "product-doc refs" in product_docs_search_probe["purpose"]
    source_vault_probe = next(probe for probe in probes if probe["label"] == "Source Vault Status")
    assert source_vault_probe["route"] == "/api/knowledge/source-vault"
    assert source_vault_probe["mcp_tool"] == "literature.source_vault_status"
    assert "Source Vault manifest" in source_vault_probe["purpose"]
    assert "source-to-context proof" in source_vault_probe["purpose"]
    source_search_probe = next(probe for probe in probes if probe["label"] == "Source Vault Search")
    assert source_search_probe["route"] == "/api/knowledge/source-vault/search?q={query}"
    assert source_search_probe["mcp_tool"] == "literature.source_vault_search"
    assert source_search_probe["requires_identifier"] is True
    assert source_search_probe["identifier_hint"] == "query"
    assert "search refs" in source_search_probe["purpose"]
    source_read_probe = next(probe for probe in probes if probe["label"] == "Source Vault Resource Read")
    assert source_read_probe["route"] == "/api/agent-bridge/resource/{ref_id}"
    assert source_read_probe["mcp_tool"] == "literature.source_vault_read"
    assert source_read_probe["requires_identifier"] is True
    assert source_read_probe["identifier_hint"] == "ref_id"
    assert "bounded Source Vault resource" in source_read_probe["purpose"]
    context_receipt_probe = next(probe for probe in probes if probe["label"] == "Knowledge Context Receipt")
    assert context_receipt_probe["route"] == "/api/knowledge/context-receipt"
    assert context_receipt_probe["method"] == "POST"
    assert context_receipt_probe["mcp_tool"] == "literature.knowledge_context_receipt"
    assert context_receipt_probe["requires_identifier"] is True
    assert context_receipt_probe["identifier_hint"] == "ref_id"
    assert "context receipt proof" in context_receipt_probe["purpose"]
    result_envelope_probe = next(probe for probe in probes if probe["label"] == "MCP Result Envelope")
    assert result_envelope_probe["route"] == "/api/agent-workspace/status"
    assert result_envelope_probe["mcp_tool"] == "source.read_file"
    assert result_envelope_probe["requires_identifier"] is False
    assert "safe_result envelope fields" in result_envelope_probe["purpose"]
    assert "structured truncation metadata" in result_envelope_probe["purpose"]
    assert "serialization_failed" in result_envelope_probe["purpose"]
    lifecycle_gate_probe = next(probe for probe in probes if probe["label"] == "Goal Lifecycle Completion Gate")
    assert lifecycle_gate_probe["route"] == "/api/agent-workspace/status"
    assert lifecycle_gate_probe["mcp_tool"] == "literature.agent_workspace_status"
    assert lifecycle_gate_probe["requires_identifier"] is False
    assert "can_mark_goal_complete" in lifecycle_gate_probe["purpose"]
    assert "completion_blockers" in lifecycle_gate_probe["purpose"]
    assert "all-proved requirements" in lifecycle_gate_probe["purpose"]
    workflow_passport_probe = next(probe for probe in probes if probe["label"] == "Workflow Passport")
    assert workflow_passport_probe["route"] == "/runtime/workflow-passport"
    assert workflow_passport_probe["mcp_tool"] == "literature.workflow_passport"
    assert workflow_passport_probe["requires_identifier"] is False
    assert "stage" in workflow_passport_probe["purpose"]
    assert "provenance" in workflow_passport_probe["purpose"]
    _assert_agent_workspace_probe_resolves_to_full_app_get_route(workflow_passport_probe)
    evidence_gate_probe = next(probe for probe in probes if probe["label"] == "Evidence Integrity Gate")
    assert evidence_gate_probe["route"] == "/runtime/evidence-integrity-gate"
    assert evidence_gate_probe["mcp_tool"] == "literature.evidence_integrity_gate"
    assert evidence_gate_probe["requires_identifier"] is False
    assert "blockers" in evidence_gate_probe["purpose"]
    assert "integrity signals" in evidence_gate_probe["purpose"]
    _assert_agent_workspace_probe_resolves_to_full_app_get_route(evidence_gate_probe)
    research_lifecycle_probe = next(
        probe for probe in probes if probe["label"] == "Research Action Lifecycle"
    )
    assert research_lifecycle_probe["route"] == "/runtime/research-action-lifecycle"
    assert research_lifecycle_probe["mcp_tool"] == "literature.research_action_lifecycle"
    assert research_lifecycle_probe["requires_identifier"] is False
    assert "preflight" in research_lifecycle_probe["purpose"]
    assert "forbidden-action" in research_lifecycle_probe["purpose"]
    _assert_agent_workspace_probe_resolves_to_full_app_get_route(research_lifecycle_probe)
    handoff_probe = next(probe for probe in probes if probe["label"] == "Agent Handoff Card")
    assert handoff_probe["route"] == "/runtime/job/{job_id}/agent-handoff-card"
    assert handoff_probe["requires_identifier"] is True
    assert handoff_probe["identifier_hint"] == "job_id"
    assert handoff_probe["mcp_tool"] == "literature.agent_handoff_card"
    assert "replay recovery" in handoff_probe["purpose"]
    _assert_agent_workspace_probe_resolves_to_full_app_get_route(handoff_probe)
    requirement_probe = next(probe for probe in probes if probe["label"] == "Goal Requirement Drilldown")
    assert requirement_probe["route"] == "/api/agent-workspace/goal-requirements/{requirement_id}"
    assert requirement_probe["requires_identifier"] is True
    assert requirement_probe["identifier_hint"] == "requirement_id"
    assert requirement_probe["mcp_tool"] == "literature.agent_workspace_requirement"
    assert "requirement-to-evidence" in requirement_probe["purpose"]
    assert any("MCP Result Envelope" in item for item in payload["workspace_state"]["next_safe_local_actions"])
    assert any("Goal Lifecycle Completion Gate" in item for item in payload["workspace_state"]["next_safe_local_actions"])
    assert any("Goal Requirement Drilldowns" in item for item in payload["workspace_state"]["next_safe_local_actions"])
    assert any("rollback checkpoint" in item for item in payload["workspace_state"]["boundaries"])
    assert payload["artifacts"][0]["path"] == "reports/summary.md"
    assert ".audit" not in payload["artifacts"][0]["path"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-ant-api" not in serialized
    assert "raw-secret-should-not-leak" not in serialized
    assert "Authorization: Bearer" not in serialized
    assert str(tmp_path) not in serialized


def test_goal_state_summary_is_bounded_and_path_safe(tmp_path, monkeypatch) -> None:
    plans_root = tmp_path / "docs" / "plans"
    plans_root.mkdir(parents=True)
    goal_path = plans_root / "longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
    goal_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-06-22T21:36:00+08:00",
                "current_objective": "sensitive full local objective should not be returned",
                "rollback": {
                    "checkpoint_id": "20260622-213822-n41-goal-state-workspace-visibility",
                    "latest_checkpoint_id": "20260626-061743-n201-agent-workspace-latest-checkpoint",
                    "latest_goal_state_checkpoint_id": "20260626-061744-n201-goal-state-latest-checkpoint",
                    "latest_checkpoint_caveat": "Rollback checkpoint for C:/Users/xiao/private N201 goal-state projection; restore only with explicit user intent.",
                    "checkpoint_path": "C:/Users/xiao/.codex/rollback-checkpoints/private",
                    "restore_command": "restore C:/Users/xiao/private",
                },
                "requirements": [
                    {"id": "N39", "status": "proved"},
                    {"id": "N40", "status": "proved"},
                    {
                        "id": "E01",
                        "status": "incomplete",
                        "requirement": "External Computer Use package residual at C:/Users/xiao/private/app",
                        "residual_risk": "Keep local UIA proof separate from external package residual risk.",
                    },
                    {
                        "id": "D01",
                        "status": "out_of_scope",
                        "requirement": "import-to-wiki writes remain deferred unless reauthorized.",
                        "residual_risk": "Future write-path safety tests need C:/Users/xiao/private/data redaction.",
                    },
                    {
                        "id": "M01",
                        "status": "missing_evidence",
                        "requirement": "missing evidence " + "x" * 300,
                        "residual_risk": "risk " + "y" * 300,
                    },
                    {
                        "id": "W01",
                        "status": "weak_indirect_evidence",
                        "requirement": "weak row",
                        "residual_risk": "weak risk",
                    },
                    {
                        "id": "C01",
                        "status": "contradicted",
                        "requirement": "contradicted row",
                        "residual_risk": "contradicted risk",
                    },
                    {
                        "id": "C02",
                        "status": "contradicted",
                        "requirement": "sixth open row is intentionally omitted",
                        "residual_risk": "sixth risk is intentionally omitted",
                    },
                ],
                "completion_claim": {
                    "this_slice": "N41 exposed bounded recovery state to Agent Workspace. "
                    + "x" * 280,
                    "full_goal": "The full goal remains active and C:/Users/xiao/private must stay hidden.",
                    "can_mark_goal_complete": False,
                    "why_not_complete": "C:/Users/xiao/private provider proof is still missing.",
                },
                "goal_lifecycle_rollup": {
                    "schema_version": "scholar_ai_goal_lifecycle_rollup_v1",
                    "updated_at": "2026-06-25T23:59:30+08:00",
                    "status": "active_requirements_proved_pending_authorized_gates",
                    "is_goal_complete": False,
                    "can_mark_goal_complete": False,
                    "requirements_total": 8,
                    "requirement_status_counts": {
                        "proved": 2,
                        "incomplete": 1,
                        "out_of_scope": 1,
                    },
                    "requirements_all_proved": True,
                    "requirements_all_proved_or_out_of_scope": True,
                    "latest_requirement_id": "N173-goal-lifecycle-rollup",
                    "latest_slice_id": "N173-goal-lifecycle-rollup",
                    "completion_blockers": [
                        {
                            "id": "actual_loading_gate_live_model_proof",
                            "status": "blocked_pending_explicit_authorization",
                            "requirement_surface": "Knowledge Runtime Pipeline at C:/Users/xiao/private",
                            "missing_evidence": "Authorized live provider/model smoke artifact with verdict=ok.",
                            "current_boundary": "Deterministic contract tests are proved only.",
                            "evidence": "N289 projection evidence at C:/Users/xiao/private proves deterministic visibility only.",
                        },
                        {
                            "id": "real_ocr_provider_execution",
                            "status": "blocked_pending_explicit_authorization",
                            "requirement_surface": "OCR local processing capability",
                            "missing_evidence": "A real provider smoke without committed model cache.",
                            "current_boundary": "Readiness endpoints are deterministically proved only.",
                        },
                        "git_persistence_user_signoff",
                    ],
                    "machine_readable_completion_rule": "Goal may be complete only when blockers are empty.",
                    "why_not_complete": "All requirement rows are proved, but C:/Users/xiao/private proof gates remain.",
                },
                "next_authorized_local_actions": [
                    "Create rollback checkpoint.",
                    "Search mature references.",
                    "Run focused tests.",
                    "This fourth action is intentionally omitted.",
                ],
                "stop_boundary": [
                    "No push.",
                    "No upload.",
                    "No Zotero DB mutation.",
                    "This fourth boundary remains visible.",
                ],
                "authoritative_records": [
                    "AI_WORKSPACE_GUIDE.md",
                    "AGENTS.md",
                    "docs/plans/autonomous-execution-framework.md",
                    "docs/plans/autonomous-execution-planning-playbook.md",
                    "C:/Users/xiao/private/local-only-record.md",
                    "tests/test_ci_visibility_contract.py",
                    "agent_mcp_server/tests/test_runtime_tools.py",
                    "frontend/src/pages/AgentWorkspace.tsx",
                    "This ninth record is intentionally omitted.",
                ],
                "mature_references_checked": [
                    {
                        "topic": "N41 response model at C:/Users/xiao/private",
                        "source": "FastAPI response-model documentation",
                        "url": "https://fastapi.tiangolo.com/tutorial/response-model/",
                        "status": "HEAD checked 200",
                        "checked_at": "2026-06-22T21:36:00+08:00",
                        "use_in_slice": "Keep recovery projection bounded and typed.",
                    },
                    {
                        "topic": "N41 field constraints",
                        "source": "Pydantic fields documentation",
                        "url": "https://docs.pydantic.dev/latest/concepts/fields/",
                        "status": "HEAD checked 200",
                        "checked_at": "2026-06-22T21:36:00+08:00",
                        "use_in_slice": "Bound text fields before display.",
                    },
                    {
                        "topic": "N41 assertions",
                        "source": "pytest assertion documentation",
                        "url": "https://docs.pytest.org/en/stable/how-to/assert.html",
                        "status": "HEAD checked 200",
                        "checked_at": "2026-06-22T21:36:00+08:00",
                        "use_in_slice": "Compare visible projection to source record.",
                    },
                    {
                        "topic": "N41 observability",
                        "source": "Google SRE monitoring distributed systems chapter",
                        "url": "https://sre.google/sre-book/monitoring-distributed-systems/",
                        "status": "HEAD checked 200",
                        "checked_at": "2026-06-22T21:36:00+08:00",
                        "use_in_slice": "Catch recovery-state drift in CI.",
                    },
                    {
                        "topic": "fifth reference intentionally omitted",
                        "source": "Reference five",
                    },
                ],
                "changed_files_for_this_slice": [
                    "literature_assistant/core/routers/agent_workspace_router.py",
                    "tests/test_agent_workspace_router.py",
                    "tests/test_ci_visibility_contract.py",
                    "agent_mcp_server/tests/test_runtime_tools.py",
                    "frontend/src/services/agentWorkspaceApi.ts",
                    "frontend/src/pages/AgentWorkspace.tsx",
                    "frontend/src/pages/AgentWorkspace.test.tsx",
                    "C:/Users/xiao/private/local-only-output.json",
                    "ninth-file-intentionally-omitted.py",
                ],
                "verification_commands": [
                    "Read AI_WORKSPACE_GUIDE.md before implementation.",
                    "git status --short --branch -> clean at C:/Users/xiao/private",
                    "HEAD FastAPI response-model -> 200",
                    ".\\.venv-1\\Scripts\\python.exe -m pytest tests\\test_agent_workspace_router.py -q -> passed",
                    "npm run test -- AgentWorkspace.test.tsx --run -> passed",
                    "npm exec tsc -- --noEmit -> passed",
                    "seventh command intentionally omitted",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_workspace_router, "REPO_ROOT", tmp_path)

    summary = agent_workspace_router._load_goal_state_summary()

    assert summary.available is True
    assert summary.path == "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
    assert summary.updated_at == "2026-06-22T21:36:00+08:00"
    assert summary.checkpoint_id == "20260626-061744-n201-goal-state-latest-checkpoint"
    assert summary.rollback_caveat == (
        "Rollback checkpoint for [redacted-local-path] N201 goal-state projection; restore only with explicit user intent."
    )
    assert summary.requirement_count == 8
    assert summary.proved_count == 2
    assert summary.incomplete_count == 1
    assert summary.out_of_scope_count == 1
    assert summary.latest_requirement_id == "C02"
    assert summary.requirement_status.total == 8
    assert summary.requirement_status.proved == 2
    assert summary.requirement_status.incomplete == 1
    assert summary.requirement_status.out_of_scope == 1
    assert summary.requirement_status.latest_id == "C02"
    assert [item.id for item in summary.open_requirements] == ["E01", "D01", "M01", "W01", "C01"]
    assert summary.open_requirements[0].requirement == (
        "External Computer Use package residual at [redacted-local-path]"
    )
    assert summary.open_requirements[1].residual_risk == (
        "Future write-path safety tests need [redacted-local-path] redaction."
    )
    assert summary.open_requirements[2].requirement is not None
    assert len(summary.open_requirements[2].requirement) == 240
    assert summary.open_requirements[2].residual_risk is not None
    assert len(summary.open_requirements[2].residual_risk) == 240
    assert summary.completion_claim.this_slice is not None
    assert len(summary.completion_claim.this_slice) == agent_workspace_router.MAX_GOAL_COMPLETION_CHARS
    assert summary.completion_claim.this_slice.startswith("N41 exposed bounded recovery state")
    assert summary.completion_claim.full_goal == "The full goal remains active and [redacted-local-path] must stay hidden."
    assert summary.completion_claim.can_mark_goal_complete is False
    assert summary.completion_claim.why_not_complete == "[redacted-local-path] provider proof is still missing."
    assert summary.lifecycle_rollup.schema_version == "scholar_ai_goal_lifecycle_rollup_v1"
    assert summary.lifecycle_rollup.status == "active_requirements_proved_pending_authorized_gates"
    assert summary.lifecycle_rollup.is_goal_complete is False
    assert summary.lifecycle_rollup.can_mark_goal_complete is False
    assert summary.lifecycle_rollup.requirements_total == 8
    assert summary.lifecycle_rollup.requirement_status_counts == {
        "proved": 2,
        "incomplete": 1,
        "out_of_scope": 1,
    }
    assert summary.lifecycle_rollup.requirements_all_proved is True
    assert summary.lifecycle_rollup.requirements_all_proved_or_out_of_scope is True
    assert summary.lifecycle_rollup.latest_requirement_id == "N173-goal-lifecycle-rollup"
    assert summary.lifecycle_rollup.latest_slice_id == "N173-goal-lifecycle-rollup"
    assert len(summary.lifecycle_rollup.completion_blockers) == 3
    assert summary.lifecycle_rollup.completion_blockers[0].id == "actual_loading_gate_live_model_proof"
    assert summary.lifecycle_rollup.completion_blockers[0].requirement_surface == (
        "Knowledge Runtime Pipeline at [redacted-local-path]"
    )
    assert summary.lifecycle_rollup.completion_blockers[0].evidence == (
        "N289 projection evidence at [redacted-local-path] proves deterministic visibility only."
    )
    assert summary.lifecycle_rollup.completion_blockers[2].id == "git_persistence_user_signoff"
    assert summary.lifecycle_rollup.completion_blockers[2].status is None
    assert summary.lifecycle_rollup.machine_readable_completion_rule == (
        "Goal may be complete only when blockers are empty."
    )
    assert summary.lifecycle_rollup.why_not_complete == [
        "All requirement rows are proved, but [redacted-local-path] proof gates remain."
    ]
    assert summary.next_authorized_local_actions == [
        "Create rollback checkpoint.",
        "Search mature references.",
        "Run focused tests.",
    ]
    assert summary.stop_boundaries == [
        "No push.",
        "No upload.",
        "No Zotero DB mutation.",
        "This fourth boundary remains visible.",
    ]
    assert summary.authoritative_records == [
        "AI_WORKSPACE_GUIDE.md",
        "AGENTS.md",
        "docs/plans/autonomous-execution-framework.md",
        "docs/plans/autonomous-execution-planning-playbook.md",
        "[redacted-local-path]",
        "tests/test_ci_visibility_contract.py",
        "agent_mcp_server/tests/test_runtime_tools.py",
        "frontend/src/pages/AgentWorkspace.tsx",
    ]
    assert len(summary.mature_references_checked) == agent_workspace_router.MAX_GOAL_STATE_MATURE_REFERENCES
    assert summary.mature_references_checked[0].topic == "N41 response model at [redacted-local-path]"
    assert summary.mature_references_checked[0].source == "FastAPI response-model documentation"
    assert summary.mature_references_checked[0].url == "https://fastapi.tiangolo.com/tutorial/response-model/"
    assert summary.mature_references_checked[0].status == "HEAD checked 200"
    assert summary.mature_references_checked[0].checked_at == "2026-06-22T21:36:00+08:00"
    assert summary.mature_references_checked[0].use_in_slice == "Keep recovery projection bounded and typed."
    assert summary.mature_references_checked[-1].topic == "N41 observability"
    assert summary.changed_files_for_this_slice == [
        "literature_assistant/core/routers/agent_workspace_router.py",
        "tests/test_agent_workspace_router.py",
        "tests/test_ci_visibility_contract.py",
        "agent_mcp_server/tests/test_runtime_tools.py",
        "frontend/src/services/agentWorkspaceApi.ts",
        "frontend/src/pages/AgentWorkspace.tsx",
        "frontend/src/pages/AgentWorkspace.test.tsx",
        "[redacted-local-path]",
    ]
    assert summary.verification_commands == [
        "Read AI_WORKSPACE_GUIDE.md before implementation.",
        "git status --short --branch -> clean at [redacted-local-path]",
        "HEAD FastAPI response-model -> 200",
        ".\\.venv-1\\Scripts\\python.exe -m pytest tests\\test_agent_workspace_router.py -q -> passed",
        "npm run test -- AgentWorkspace.test.tsx --run -> passed",
        "npm exec tsc -- --noEmit -> passed",
    ]
    serialized = summary.model_dump_json()
    assert "current_objective" not in serialized
    assert "restore_command" not in serialized
    assert "C:/Users/xiao" not in serialized
    assert "fifth reference" not in serialized
    assert "ninth-file-intentionally-omitted" not in serialized
    assert "seventh command" not in serialized
    assert "sixth open row" not in serialized
    assert "Fourth reason is intentionally omitted." not in serialized


def test_goal_requirement_drilldown_is_bounded_and_path_safe(tmp_path, monkeypatch) -> None:
    plans_root = tmp_path / "docs" / "plans"
    plans_root.mkdir(parents=True)
    goal_path = plans_root / "longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
    goal_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-06-22T21:36:00+08:00",
                "rollback": {
                    "checkpoint_id": "20260622-213822-n41-goal-state-workspace-visibility",
                    "latest_checkpoint_id": "20260626-061743-n201-agent-workspace-latest-checkpoint",
                    "latest_goal_state_checkpoint_id": "20260626-061744-n201-goal-state-latest-checkpoint",
                    "checkpoint_path": "C:/Users/xiao/.codex/rollback-checkpoints/private",
                    "restore_command": "restore C:/Users/xiao/private",
                },
                "requirements": [
                    {"id": "N39", "status": "proved", "requirement": "proved row"},
                    {
                        "id": "E01",
                        "status": "incomplete",
                        "requirement": "External Computer Use package residual at C:/Users/xiao/private/app",
                        "residual_risk": "Keep local UIA proof separate from external package residual risk.",
                        "evidence": [
                            {
                                "id": "router-test",
                                "file": "C:/Users/xiao/private/evidence.json",
                                "command": "pytest tests/test_agent_workspace_router.py",
                            },
                            "manual note at C:/Users/xiao/private/note.md",
                            {"ref_id": "mcp-contract", "status": "covered"},
                            {"ref_id": "frontend-visible", "status": "covered"},
                            {"ref_id": "desktop-visible", "status": "covered"},
                            {"ref_id": "goal-state", "status": "covered"},
                            {"ref_id": "rollback", "status": "covered"},
                            {"ref_id": "mature-reference", "status": "covered"},
                            {"ref_id": "ninth-evidence", "status": "omitted"},
                        ],
                    },
                ],
                "next_authorized_local_actions": [
                    "Create rollback checkpoint.",
                    "Search mature references.",
                    "Run focused tests.",
                    "This fourth action is intentionally omitted.",
                ],
                "stop_boundary": [
                    "No push.",
                    "No upload.",
                    "No Zotero DB mutation.",
                    "This fourth boundary remains visible.",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_workspace_router, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("LITASSIST_API_CAPABILITY_AUTH", "1")
    client = TestClient(server.app)

    response = client.get(
        "/api/agent-workspace/goal-requirements/E01",
        headers={server.LOCAL_API_CAPABILITY_HEADER: server.get_local_api_capability_token()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "scholar_ai_goal_requirement_drilldown_v1"
    assert payload["available"] is True
    assert payload["read_only"] is True
    assert payload["path"] == "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
    assert payload["updated_at"] == "2026-06-22T21:36:00+08:00"
    assert payload["checkpoint_id"] == "20260626-061744-n201-goal-state-latest-checkpoint"
    assert payload["id"] == "E01"
    assert payload["status"] == "incomplete"
    assert payload["requirement"] == "External Computer Use package residual at [redacted-local-path]"
    assert payload["residual_risk"] == "Keep local UIA proof separate from external package residual risk."
    assert payload["evidence_count"] == 9
    assert payload["truncated"] is True
    assert len(payload["evidence"]) == agent_workspace_router.MAX_GOAL_REQUIREMENT_EVIDENCE
    assert payload["evidence"][0]["label"] == "router-test"
    assert "[redacted-local-path]" in payload["evidence"][0]["text"]
    assert payload["next_safe_local_actions"] == [
        "Create rollback checkpoint.",
        "Search mature references.",
        "Run focused tests.",
    ]
    assert payload["stop_boundaries"] == [
        "No push.",
        "No upload.",
        "No Zotero DB mutation.",
        "This fourth boundary remains visible.",
    ]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "restore_command" not in serialized
    assert "C:/Users/xiao" not in serialized
    assert "ninth-evidence" not in serialized


def test_goal_requirement_drilldown_reports_missing_id(tmp_path, monkeypatch) -> None:
    plans_root = tmp_path / "docs" / "plans"
    plans_root.mkdir(parents=True)
    (plans_root / "longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-06-22T21:36:00+08:00",
                "requirements": [{"id": "E01", "status": "incomplete"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_workspace_router, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("LITASSIST_API_CAPABILITY_AUTH", "1")
    client = TestClient(server.app)

    response = client.get(
        "/api/agent-workspace/goal-requirements/NOPE",
        headers={server.LOCAL_API_CAPABILITY_HEADER: server.get_local_api_capability_token()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["read_only"] is True
    assert payload["id"] == "NOPE"
    assert payload["error"] == "requirement id was not found in the selected goal-state record"


def test_directory_state_is_path_safe_and_bounded(tmp_path, monkeypatch) -> None:
    workspace_root = tmp_path / "external-workspace-root"
    workspace_root.mkdir()
    for index in range(3):
        (workspace_root / f"{index}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(agent_workspace_router, "MAX_DIRECTORY_STATE_FILES", 2)

    state = agent_workspace_router._count_directory_state("external", workspace_root)

    assert state.path == "[redacted-local-path]"
    assert state.file_count == 2
    assert state.total_bytes == 2
    assert state.truncated is True


def test_agent_workspace_status_requires_capability_when_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(agent_workspace_router, "WORKSPACE_ARTIFACTS_ROOT", tmp_path)
    monkeypatch.setenv("LITASSIST_API_CAPABILITY_AUTH", "1")
    client = TestClient(server.app)

    response = client.get("/api/agent-workspace/status")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOCAL_API_CAPABILITY_REQUIRED"


def test_git_porcelain_summary_redacts_absolute_paths() -> None:
    stdout = "\n".join(
        [
            "# branch.oid abcdef",
            "# branch.head feature/state",
            "# branch.upstream origin/main",
            "# branch.ab +2 -1",
            "1 .M N... 100644 100644 100644 abc abc C:/Users/Alice/private/token.txt",
            "1 M. N... 100644 100644 100644 abc abc frontend/src/pages/AgentWorkspace.tsx",
            "? docs/plans/local-state.json",
            "u UU N... 100644 100644 100644 100644 abc abc abc abc private/conflict.txt",
        ]
    )

    state = agent_workspace_router._parse_git_porcelain(stdout)

    assert state.available is True
    assert state.branch == "feature/state"
    assert state.ahead == 2
    assert state.behind == 1
    assert state.changed_count == 4
    assert state.staged_count == 1
    assert state.unstaged_count == 1
    assert state.untracked_count == 1
    assert state.conflicted_count == 1
    assert "[redacted-local-path]" in state.dirty_paths
    assert "frontend/src/pages/AgentWorkspace.tsx" in state.dirty_paths
    assert all("C:/Users/Alice" not in path for path in state.dirty_paths)
