from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import pytest
from starlette.routing import Match

from harness_protocols import JobKind, SessionMode
import routers.agent_bridge_router as agent_bridge_router_module
import routers.knowledge_router as knowledge_router_module
import routers.runtime_router as runtime_router_module
from python_adapter_server import app, get_local_api_capability_token
from source_vault import SourceChunkInput, SourceVault
from writing_runtime import WritingRuntime

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_ENDPOINT_LITERAL = re.compile(r"""['"`](?P<endpoint>/runtime/[^'"`]+)['"`]""")
_RUNTIME_ENDPOINT_TOKEN = "route-proof"


def _concrete_runtime_fixture_path(endpoint: str) -> str:
    """Convert an acceptance fixture endpoint literal into a resolvable local path."""

    concrete_path = endpoint.strip()
    assert concrete_path.startswith("/runtime/")
    replacements = {
        "{job_id}": "job-route-proof",
        "{job.job_id}": "job-route-proof",
        "{normalized_job_id}": "job-route-proof",
        "{ref_id}": "job-route-proof",
        "{session_id}": "session-route-proof",
        "{request_id}": "request-route-proof",
        "{receipt_id}": "receipt-route-proof",
        "${encodeURIComponent(jobId)}": "job-route-proof",
        "{" + _RUNTIME_ENDPOINT_TOKEN + "}": "job-route-proof",
    }
    for token, value in replacements.items():
        concrete_path = concrete_path.replace(token, value)
    assert "{" not in concrete_path and "}" not in concrete_path
    return concrete_path


def _runtime_endpoints_from_python_source(source_path: Path) -> set[str]:
    """Return statically recoverable runtime endpoint templates from Python source."""

    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    endpoints: set[str] = set()

    class _Visitor(ast.NodeVisitor):
        def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
            if isinstance(node.value, str) and node.value.startswith("/runtime/"):
                endpoints.add(node.value.split("?", maxsplit=1)[0])

        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:  # noqa: N802
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    parts.append("{" + _RUNTIME_ENDPOINT_TOKEN + "}")
            endpoint = "".join(parts)
            if endpoint.startswith("/runtime/"):
                endpoints.add(endpoint.split("?", maxsplit=1)[0])

    _Visitor().visit(tree)
    return endpoints


def _runtime_endpoints_from_text_source(source_path: Path) -> set[str]:
    """Return runtime endpoint literals from a non-Python source file."""

    source_text = source_path.read_text(encoding="utf-8")
    return {
        match.group("endpoint").split("?", maxsplit=1)[0]
        for match in _RUNTIME_ENDPOINT_LITERAL.finditer(source_text)
    }


def _is_static_runtime_endpoint_template(endpoint: str) -> bool:
    """Return whether a runtime endpoint template has enough literal path to verify."""

    normalized = endpoint.split("?", maxsplit=1)[0].strip()
    return normalized.startswith("/runtime/") and normalized != "/runtime/{" + _RUNTIME_ENDPOINT_TOKEN + "}"


def _assert_full_app_get_route_exists(path: str) -> None:
    """Assert one concrete GET route in the full app can resolve path."""

    normalized_path = str(path or "").strip()
    assert normalized_path.startswith("/")
    matches: list[str] = []
    for route in app.routes:
        route_path = str(getattr(route, "path", ""))
        if route_path == "/{full_path:path}":
            continue
        route_methods = getattr(route, "methods", None)
        if route_methods is not None and "GET" not in route_methods:
            continue
        if not hasattr(route, "matches"):
            continue
        match, _ = route.matches({"type": "http", "path": normalized_path, "method": "GET"})
        if match is not Match.NONE:
            matches.append(route_path)
    assert matches, f"GET route not registered on full app: {normalized_path}"


def _probe_path(probe: Mapping[str, object]) -> str:
    """Return the concrete local path from a runtime resume probe."""

    url = str(probe.get("url") or probe.get("endpoint") or "").strip()
    path = urlsplit(url).path
    assert path.startswith("/")
    return path


def _assert_registered_read_only_probe(probe: Mapping[str, object]) -> None:
    """Assert a read-only probe points at a real full-app GET route."""

    assert probe.get("method") == "GET"
    assert probe.get("read_only") is True
    path = _probe_path(probe)
    assert "_passport" not in path
    assert "_gate" not in path
    assert "_card" not in path
    _assert_full_app_get_route_exists(path)


def _probe_url(probe: Mapping[str, object]) -> str:
    """Return the concrete relative URL from a resume probe."""

    url = str(probe.get("url") or probe.get("endpoint") or "").strip()
    assert url.startswith("/")
    return url


def _assert_probe_returns_http_success(
    client: TestClient,
    probe: Mapping[str, object],
    *,
    headers: Mapping[str, str],
) -> None:
    """Assert one advertised read-only probe is resolvable and non-404."""

    _assert_registered_read_only_probe(probe)
    url = _probe_url(probe)
    response = client.get(url, headers=dict(headers))
    assert response.status_code == 200, f"{url} returned {response.status_code}: {response.text}"


def _assert_probe_endpoint_returns_http_success(
    client: TestClient,
    endpoint: object,
    *,
    headers: Mapping[str, str],
) -> None:
    """Assert one advertised runtime endpoint string is a live read-only route."""

    path = str(endpoint or "").strip()
    assert path.startswith("/runtime/")
    assert "_passport" not in path
    assert "_gate" not in path
    assert "_card" not in path
    _assert_full_app_get_route_exists(path)
    response = client.get(path, headers=dict(headers))
    assert response.status_code == 200, f"{path} returned {response.status_code}: {response.text}"


def test_runtime_lifecycle_routes_are_registered_on_full_app() -> None:
    """Full FastAPI app must expose the runtime lifecycle routes MCP tools cite."""

    route_paths = {str(getattr(route, "path", "")) for route in app.routes}

    assert "/runtime/workflow-passport" in route_paths
    assert "/runtime/evidence-integrity-gate" in route_paths
    assert "/runtime/job/{job_id}/agent-handoff-card" in route_paths
    assert "/runtime/research-action-lifecycle" in route_paths
    assert "/runtime/workflow_passport" not in route_paths
    assert "/runtime/evidence_integrity_gate" not in route_paths
    assert "/runtime/agent_handoff_card" not in route_paths


def test_runtime_lifecycle_underscore_aliases_do_not_resolve_over_http(monkeypatch) -> None:
    """Runtime lifecycle contract should not silently accept stale underscore URLs."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-runtime-alias-proof"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="runtime alias proof",
        metadata={"project_id": "project-runtime-alias-proof"},
    )
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    client = TestClient(app)
    headers = {"X-LitAssist-Capability": get_local_api_capability_token()}

    stale_paths = [
        "/runtime/workflow_passport",
        "/runtime/evidence_integrity_gate",
        f"/runtime/job/{job.job_id}/agent_handoff_card",
    ]

    for path in stale_paths:
        response = client.get(path, headers=headers)
        assert response.status_code == 404, path


def test_runtime_lifecycle_openapi_paths_are_hyphenated() -> None:
    """Generated API clients should see only the canonical hyphen runtime paths."""

    openapi_paths = set(app.openapi()["paths"])

    assert "/runtime/workflow-passport" in openapi_paths
    assert "/runtime/evidence-integrity-gate" in openapi_paths
    assert "/runtime/job/{job_id}/agent-handoff-card" in openapi_paths
    assert "/runtime/workflow_passport" not in openapi_paths
    assert "/runtime/evidence_integrity_gate" not in openapi_paths
    assert "/runtime/job/{job_id}/agent_handoff_card" not in openapi_paths


def test_desktop_acceptance_runtime_endpoint_literals_match_full_app_get_routes() -> None:
    """Read-only desktop acceptance probes must not cite nonexistent runtime routes."""

    fixture_path = _REPO_ROOT / "frontend" / "src" / "pages" / "DesktopAcceptanceAgentWorkspace.tsx"
    fixture_source = fixture_path.read_text(encoding="utf-8")
    endpoints = sorted({match.group("endpoint") for match in _RUNTIME_ENDPOINT_LITERAL.finditer(fixture_source)})

    assert endpoints
    assert "/runtime/workflow-action-preflight" not in endpoints
    for endpoint in endpoints:
        _assert_full_app_get_route_exists(_concrete_runtime_fixture_path(endpoint))


def test_frontend_runtime_api_literals_match_full_app_get_routes() -> None:
    """Frontend runtime API client literals must point at registered GET routes."""

    service_path = _REPO_ROOT / "frontend" / "src" / "services" / "agentWorkspaceApi.ts"
    endpoints = _runtime_endpoints_from_text_source(service_path)
    expected_endpoints = {
        "/runtime/workflow-passport",
        "/runtime/evidence-integrity-gate",
        "/runtime/job/${encodeURIComponent(jobId)}/agent-handoff-card",
        "/runtime/research-action-lifecycle",
        "/runtime/behavior-eval-pack",
        "/runtime/jobs",
        "/runtime/job/${encodeURIComponent(jobId)}/workflow-replay-lineage",
        "/runtime/workflow-replay-index",
    }

    assert endpoints >= expected_endpoints
    assert "/runtime/workflow_passport" not in endpoints
    assert "/runtime/evidence_integrity_gate" not in endpoints
    assert "/runtime/job/${encodeURIComponent(jobId)}/agent_handoff_card" not in endpoints
    for endpoint in endpoints:
        _assert_full_app_get_route_exists(_concrete_runtime_fixture_path(endpoint))


def test_frontend_dist_runtime_api_literals_stay_hyphenated_when_present() -> None:
    """Desktop-served dist must not preserve stale underscore runtime lifecycle URLs."""

    dist_root = _REPO_ROOT / "frontend" / "dist"
    if not dist_root.exists():
        return

    dist_files = [
        path
        for path in dist_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".js", ".css"}
    ]
    assert dist_files
    combined_dist = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in dist_files)

    assert "/runtime/workflow_passport" not in combined_dist
    assert "/runtime/evidence_integrity_gate" not in combined_dist
    assert "/runtime/agent_handoff_card" not in combined_dist
    assert "/runtime/workflow-passport" in combined_dist
    assert "/runtime/evidence-integrity-gate" in combined_dist
    assert "/agent-handoff-card" in combined_dist


def test_runtime_endpoint_literals_in_runtime_source_match_full_app_get_routes() -> None:
    """Runtime resume probes and MCP runtime tools must cite registered GET routes."""

    source_paths = [
        _REPO_ROOT / "literature_assistant" / "core" / "writing_runtime.py",
        _REPO_ROOT / "literature_assistant" / "core" / "routers" / "agent_workspace_router.py",
        _REPO_ROOT / "literature_assistant" / "core" / "routers" / "wiki_router.py",
        _REPO_ROOT
        / "agent_mcp_server"
        / "src"
        / "lit_assistant_mcp"
        / "tools"
        / "runtime.py",
    ]
    endpoints: dict[str, str] = {}
    for source_path in source_paths:
        for endpoint in _runtime_endpoints_from_python_source(source_path):
            if not _is_static_runtime_endpoint_template(endpoint):
                continue
            endpoints[endpoint] = source_path.as_posix()

    assert endpoints
    assert "/runtime/workflow_passport" not in endpoints
    assert "/runtime/evidence_integrity_gate" not in endpoints
    assert "/runtime/agent_handoff_card" not in endpoints
    assert "/runtime/workflow-action-preflight" not in endpoints
    for endpoint, source_path in sorted(endpoints.items()):
        try:
            _assert_full_app_get_route_exists(_concrete_runtime_fixture_path(endpoint))
        except AssertionError as exc:
            raise AssertionError(f"{source_path} cites unregistered runtime endpoint {endpoint}") from exc


def test_runtime_lifecycle_routes_return_http_success_on_full_app(monkeypatch) -> None:
    """Full FastAPI app must answer the runtime lifecycle routes with HTTP 200."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-runtime-http-proof"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="runtime lifecycle proof",
        metadata={
            "agent_bridge": True,
            "agent_request_id": "agentreq-runtime-http-proof",
            "project_id": "project-runtime-http-proof",
            "output_targets": {"wiki_candidate": True, "graph_candidate": True},
        },
    )
    runtime.request_approval(
        job_id=job.job_id,
        session_id=session.session_id,
        reason="Confirm runtime lifecycle proof.",
        metadata={"project_id": "project-runtime-http-proof"},
    )
    runtime.build_action_preflight(
        action_id="agent.handoff_card",
        required_claim_id="handoff_readiness",
        session_id=session.session_id,
        job_id=job.job_id,
        project_id="project-runtime-http-proof",
        require_ready=False,
        persist_refresh_receipt=True,
    )
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    monkeypatch.setattr(agent_bridge_router_module, "get_runtime", lambda: (runtime, SessionMode))

    headers = {"X-LitAssist-Capability": get_local_api_capability_token()}
    client = TestClient(app)

    passport_response = client.get("/runtime/workflow-passport", params={"limit": 1}, headers=headers)
    gate_response = client.get("/runtime/evidence-integrity-gate", params={"limit": 1}, headers=headers)
    lifecycle_response = client.get("/runtime/research-action-lifecycle", params={"limit": 1}, headers=headers)
    handoff_response = client.get(f"/runtime/job/{job.job_id}/agent-handoff-card", headers=headers)

    assert passport_response.status_code == 200
    assert gate_response.status_code == 200
    assert lifecycle_response.status_code == 200
    assert handoff_response.status_code == 200

    passport = passport_response.json()
    gate = gate_response.json()
    lifecycle = lifecycle_response.json()
    handoff = handoff_response.json()

    assert passport["schema_version"] == "scholar_ai_workflow_passport_v1"
    assert gate["schema_version"] == "scholar_ai_evidence_integrity_gate_v1"
    assert lifecycle["schema_version"] == "scholar_ai_research_action_lifecycle_v1"
    assert handoff["schema_version"] == "scholar_ai_agent_handoff_card_v1"

    agent_stage = next(stage for stage in passport["stages"] if stage["stage_id"] == "agent_handoff")
    research_action_refs = agent_stage["reproducibility"]["research_action_refs"]
    assert agent_stage["diagnostics"]["research_action_count"] >= 1
    assert any(ref["action_type"] == "agent_handoff" for ref in research_action_refs)
    assert any(ref["action_type"] == "wiki_candidate" for ref in research_action_refs)
    assert all(ref["probe_endpoint"] == "/runtime/research-action-lifecycle" for ref in research_action_refs)
    assert all(ref["read_only"] is True for ref in research_action_refs)
    for ref in research_action_refs:
        _assert_probe_endpoint_returns_http_success(client, ref["probe_endpoint"], headers=headers)

    gate_research_refs = gate["summary"]["research_action_refs"]
    assert gate["summary"]["research_action_count"] >= 1
    assert any(ref["action_type"] == "agent_handoff" for ref in gate_research_refs)
    assert "runtime.research_action_lifecycle_refs" in gate["provenance"]["derived_from"]
    assert gate["provenance"]["research_action_lifecycle_schema_version"] == (
        "scholar_ai_research_action_lifecycle_v1"
    )

    gate_boundary = gate["blocking_action_boundary"]
    assert gate_boundary["schema_version"] == "scholar_ai_blocking_action_boundary_v1"
    assert gate_boundary["status"] == "blocked"
    assert gate_boundary["can_proceed"] is False
    assert gate_boundary["recovery_drilldowns"]
    for probe in gate_boundary["local_read_only_probes"]:
        _assert_probe_returns_http_success(client, probe, headers=headers)

    handoff_recovery = handoff["action_lifecycle_recovery"]
    assert handoff_recovery["schema_version"] == "scholar_ai_handoff_action_lifecycle_recovery_v1"
    assert handoff_recovery["read_only"] is True
    assert handoff_recovery["pending_confirmation_count"] >= 1
    assert any(ref["action_type"] == "agent_handoff" for ref in handoff_recovery["action_refs"])
    assert "runtime.research_action_lifecycle_refs" in handoff["provenance"]["derived_from"]
    for ref in handoff_recovery["action_refs"]:
        _assert_probe_endpoint_returns_http_success(client, ref["probe_endpoint"], headers=headers)
    for probe in handoff_recovery["resume_probes"]:
        _assert_probe_returns_http_success(client, probe, headers=headers)

    handoff_boundary = handoff["action_preflight"]["blocking_action_boundary"]
    drilldown = next(
        item
        for item in handoff_boundary["recovery_drilldowns"]
        if item["signal_id"] == "workflow_stage:agent_handoff"
    )
    assert drilldown["linked_stage_id"] == "agent_handoff"
    assert drilldown["checked_facts"]["requires_user_confirmation"] is True
    assert drilldown["raw_path_exposed"] is False
    assert any(ref["ref_type"] == "workflow_passport_stage" for ref in drilldown["recovery_refs"])
    for ref in drilldown["recovery_refs"]:
        endpoint = ref.get("probe_endpoint")
        if endpoint is not None:
            _assert_probe_endpoint_returns_http_success(client, endpoint, headers=headers)
    for probe in drilldown["local_read_only_probes"]:
        _assert_probe_returns_http_success(client, probe, headers=headers)
    for probe in handoff["resume_probes"]:
        _assert_probe_returns_http_success(client, probe, headers=headers)
    for probe in lifecycle["resume_probes"]:
        _assert_probe_returns_http_success(client, probe, headers=headers)


def test_knowledge_bridge_lexicon_routes_are_registered_on_full_app() -> None:
    """Full FastAPI app must expose bridge lexicon knowledge routes."""

    route_paths = {str(getattr(route, "path", "")) for route in app.routes}

    assert "/api/knowledge/bridge-lexicon/status" in route_paths
    assert "/api/knowledge/bridge-lexicon/read" in route_paths
    assert "/api/knowledge/bridge-lexicon/search" in route_paths
    assert "/api/knowledge/bridge_lexicon/status" not in route_paths
    assert "/api/knowledge/bridge_lexicon/read" not in route_paths
    assert "/api/knowledge/bridge_lexicon/search" not in route_paths


def test_knowledge_source_vault_routes_are_registered_on_full_app() -> None:
    """Full FastAPI app must expose Source Vault knowledge runtime routes."""

    route_paths = {str(getattr(route, "path", "")) for route in app.routes}

    assert "/api/knowledge/source-vault" in route_paths
    assert "/api/knowledge/source-vault/search" in route_paths
    assert "/api/knowledge/source_vault" not in route_paths
    assert "/api/knowledge/source_vault/search" not in route_paths


def test_full_app_source_vault_real_file_enters_search_resource_and_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A real local Source Vault file should flow through full-app bounded context routes."""

    vault = SourceVault(
        db_path=tmp_path / "source_vault" / "source_vault.sqlite3",
        storage_root=tmp_path / "source_vault",
    )
    project_id = "project-n135-source-vault-proof"
    source_path = tmp_path / "n135-source-vault-real-ingest.txt"
    source_text = "N135RealVaultAnchor is a real local Source Vault input file."
    source_path.write_text(source_text, encoding="utf-8")
    source = vault.upsert_source_from_file(
        source_path,
        source_type="text",
        title="N135 Source Vault Real Ingest Proof",
        parser_version="text-parser-v1",
        chunker_version="source-vault-real-proof-v1",
        project_id=project_id,
        now_iso="2026-06-25T10:04:00Z",
    ).source
    chunk_text = "N135RealVaultAnchor proves source_assets and source_chunks entered bounded context."
    vault.register_chunks(
        source.source_id,
        [
            SourceChunkInput(
                text=chunk_text,
                chunk_index=0,
                span_start=0,
                span_end=len(chunk_text),
                section="runtime proof",
                metadata={"proof": "n135_full_app_real_file"},
            )
        ],
        now_iso="2026-06-25T10:05:00Z",
    )

    monkeypatch.setattr(agent_bridge_router_module, "SourceVault", lambda: vault)
    monkeypatch.setattr(knowledge_router_module._agent_bridge_router, "SourceVault", lambda: vault)
    app.dependency_overrides[knowledge_router_module.get_source_vault] = lambda: vault
    try:
        client = TestClient(app)
        headers = {"X-LitAssist-Capability": get_local_api_capability_token()}

        packages_response = client.get("/api/knowledge/packages", headers=headers)
        assert packages_response.status_code == 200
        source_vault_package = {
            package["package_id"]: package
            for package in packages_response.json()["packages"]
        }["source_vault"]
        assert source_vault_package["loaded"] is True
        assert source_vault_package["status"] == "loaded"
        assert source_vault_package["source_path"] == str(vault.storage_root)
        assert source_vault_package["manifest"]["total_sources"] == 1
        assert source_vault_package["manifest"]["chunk_count"] == 1
        assert source_vault_package["manifest"]["loaded_ref_count"] == 1
        assert source_vault_package["manifest"]["empty_runtime"] is False

        conformance_response = client.get("/api/knowledge/runtime-conformance", headers=headers)
        assert conformance_response.status_code == 200
        source_vault_conformance = {
            package["package_id"]: package
            for package in conformance_response.json()["packages"]
        }["source_vault"]
        assert source_vault_conformance["overall_status"] == "proved"
        conformance_rows = {
            item["requirement"]: item
            for item in source_vault_conformance["conformance"]
        }
        for requirement in (
            "authoritative_source",
            "structured_runtime_artifact",
            "searchable_index",
            "chunk_or_ref_protocol",
            "bounded_context_loading",
            "agent_resource_read",
            "evidence_pack_ref_protocol",
            "mcp_entry",
            "prompt_assembly_context_receipt",
            "manifest_audit_test_proof",
        ):
            assert conformance_rows[requirement]["status"] == "proved"

        search_response = client.get(
            "/api/knowledge/source-vault/search",
            params={"q": "N135RealVaultAnchor", "project_id": project_id, "limit": 1},
            headers=headers,
        )
        assert search_response.status_code == 200
        search_hit = search_response.json()["results"][0]
        assert search_hit["source_id"] == source.source_id
        assert search_hit["source_hash"] == source.source_hash
        assert search_hit["ref_id"].startswith("source_vault:chunk:")
        assert search_hit["metadata"]["proof"] == "n135_full_app_real_file"

        resource_response = client.get(
            search_hit["read_endpoint"],
            params={"project_id": project_id, "max_chars": 260, "cursor": "0"},
            headers=headers,
        )
        assert resource_response.status_code == 200
        resource_body = resource_response.json()
        assert resource_body["kind"] == "source_vault"
        assert "N135RealVaultAnchor" in resource_body["content"]
        assert resource_body["metadata"]["source_id"] == source.source_id
        assert resource_body["metadata"]["source_path"].endswith("n135-source-vault-real-ingest.txt")

        receipt_response = client.post(
            "/api/knowledge/context-receipt",
            json={
                "ref_ids": [search_hit["ref_id"]],
                "project_id": project_id,
                "prompt_name": "n135_source_vault_real_file_full_app_probe",
                "max_chars_per_ref": 260,
            },
            headers=headers,
        )
        assert receipt_response.status_code == 200
        receipt_body = receipt_response.json()
        assert "N135RealVaultAnchor" in receipt_body["assembled_context_preview"]
        assert receipt_body["provenance"]["mcp_tool"] == "literature.knowledge_context_receipt"
        receipt = receipt_body["resource_read_receipts"][0]
        assert receipt["kind"] == "source_vault"
        assert receipt["source_hash"] == source.source_hash
        assert receipt["metadata"]["source_id"] == source.source_id
        assert receipt["metadata"]["proof"] == "n135_full_app_real_file"
    finally:
        app.dependency_overrides.pop(knowledge_router_module.get_source_vault, None)
