from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

import routers.agent_workspace_router as agent_workspace_router
import python_adapter_server as server
from wiki.source_registry import ChunkInput, SourceRecord, WikiRegistry


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
            ),
            next_authorized_local_actions=[
                "Create a rollback checkpoint and search mature references before the next slice."
            ],
            stop_boundaries=["No push, tag, release, deploy, or external upload."],
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
    assert wiki_search_probe["mcp_tool"] == "literature.wiki_search"
    assert wiki_search_probe["requires_identifier"] is True
    assert wiki_search_probe["identifier_hint"] == "query"
    assert "wiki refs" in wiki_search_probe["purpose"]
    academic_search_probe = next(probe for probe in probes if probe["label"] == "Academic English Search")
    assert academic_search_probe["route"] == "/api/knowledge/academic-english/search?q={query}"
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
    handoff_probe = next(probe for probe in probes if probe["label"] == "Agent Handoff Card")
    assert handoff_probe["route"] == "/runtime/job/{job_id}/agent-handoff-card"
    assert handoff_probe["requires_identifier"] is True
    assert handoff_probe["identifier_hint"] == "job_id"
    assert handoff_probe["mcp_tool"] == "literature.agent_handoff_card"
    assert "replay recovery" in handoff_probe["purpose"]
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
                },
                "goal_lifecycle_rollup": {
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
                            "requirement_surface": "Knowledge Runtime Pipeline at C:/Users/xiao/private",
                            "missing_evidence": "Authorized live provider/model smoke artifact with verdict=ok.",
                            "current_boundary": "Deterministic contract tests are proved only.",
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
                    "This fourth boundary is intentionally omitted.",
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
    assert summary.lifecycle_rollup.schema_version == "scholar_ai_goal_lifecycle_rollup_v1"
    assert summary.lifecycle_rollup.status == "active_requirements_proved_pending_authorized_gates"
    assert summary.lifecycle_rollup.is_goal_complete is False
    assert summary.lifecycle_rollup.can_mark_goal_complete is False
    assert summary.lifecycle_rollup.requirements_all_proved is True
    assert summary.lifecycle_rollup.requirements_all_proved_or_out_of_scope is True
    assert summary.lifecycle_rollup.latest_requirement_id == "N173-goal-lifecycle-rollup"
    assert summary.lifecycle_rollup.latest_slice_id == "N173-goal-lifecycle-rollup"
    assert len(summary.lifecycle_rollup.completion_blockers) == 3
    assert summary.lifecycle_rollup.completion_blockers[0].id == "actual_loading_gate_live_model_proof"
    assert summary.lifecycle_rollup.completion_blockers[0].requirement_surface == (
        "Knowledge Runtime Pipeline at [redacted-local-path]"
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
    assert summary.stop_boundaries == ["No push.", "No upload.", "No Zotero DB mutation."]
    serialized = summary.model_dump_json()
    assert "current_objective" not in serialized
    assert "restore_command" not in serialized
    assert "C:/Users/xiao" not in serialized
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
                    "This fourth boundary is intentionally omitted.",
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
    assert payload["stop_boundaries"] == ["No push.", "No upload.", "No Zotero DB mutation."]
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
