from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "literature_assistant" / "core"
MCP_SRC = ROOT / "agent_mcp_server" / "src"
for import_root in (CORE, MCP_SRC):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

from lit_assistant_mcp.audit import AuditLog
from lit_assistant_mcp.tools.runtime import RuntimeTools

import python_adapter_server as server
import routers.agent_workspace_router as agent_workspace_router


class _ParityBackend:
    """Backend fake that returns one prevalidated REST payload to MCP runtime tools.

    Args:
        expected_path: Encoded backend route the MCP tool must call.
        payload: REST response-model output to expose through the fake backend.
    """

    def __init__(self, expected_path: str, payload: dict[str, Any]) -> None:
        if not expected_path.startswith("/"):
            raise ValueError("expected_path must be an absolute backend route")
        self.expected_path = expected_path
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the captured REST payload for the single expected route."""

        self.calls.append(("json", path, params))
        if path != self.expected_path:
            return {
                "is_error": True,
                "error_code": "UNEXPECTED_PATH",
                "message": f"unexpected path: {path}",
                "data": None,
            }
        return {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": self.payload,
        }

    def get_text(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Reject text calls because Agent Workspace parity is JSON-only."""

        raise AssertionError(f"unexpected text request: {path}")

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Reject mutations because Agent Workspace parity is read-only."""

        raise AssertionError(f"unexpected JSON mutation: {path}")

    def post_binary(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Reject binary calls because Agent Workspace parity is JSON-only."""

        raise AssertionError(f"unexpected binary mutation: {path}")


def _write_goal_state_fixture(root: Path, requirement_id: str) -> Path:
    """Write a bounded goal-state fixture with private fields that must stay hidden.

    Args:
        root: Temporary repository root patched into the Agent Workspace router.
        requirement_id: Requirement matrix id used to prove URL encoding parity.

    Returns:
        Path to the local goal-state fixture.
    """

    if not requirement_id.strip():
        raise ValueError("requirement_id is required")
    plans_root = root / "docs" / "plans"
    plans_root.mkdir(parents=True)
    goal_path = plans_root / "longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
    goal_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-06-23T02:30:00+08:00",
                "rollback": {
                    "checkpoint_id": "20260623-022555-n57-agent-workspace-requirement-contract-parity",
                    "latest_checkpoint_id": "20260626-061743-n201-agent-workspace-latest-checkpoint",
                    "latest_goal_state_checkpoint_id": "20260626-061744-n201-goal-state-latest-checkpoint",
                    "checkpoint_path": "C:/Users/xiao/.codex/rollback-checkpoints/private",
                    "restore_command": "restore C:/Users/xiao/private",
                },
                "requirements": [
                    {
                        "id": requirement_id,
                        "status": "incomplete",
                        "requirement": "REST and MCP drilldowns must stay in parity at C:/Users/xiao/private/app",
                        "residual_risk": "A payload field drift would hide browser-visible recovery evidence.",
                        "evidence": [
                            {
                                "id": "router-contract",
                                "file": "C:/Users/xiao/private/router.json",
                                "command": "pytest tests/test_agent_workspace_mcp_contract.py",
                            },
                            {
                                "ref_id": "mcp-contract",
                                "status": "covered",
                            },
                        ],
                    }
                ],
                "next_authorized_local_actions": [
                    "Create a rollback checkpoint before the next nontrivial edit.",
                    "Search official or mature references before changing the contract.",
                    "Run focused REST and MCP contract tests.",
                    "This fourth action must be omitted.",
                ],
                "stop_boundary": [
                    "No push, tag, release, deploy, or external upload.",
                    "Do not treat external Computer Use package residual risk as missing local UIA proof.",
                    "Do not enable import-to-wiki writes without explicit authorization.",
                    "This fourth boundary remains visible.",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return goal_path


def _write_goal_summary_fixture(root: Path) -> Path:
    """Write a bounded goal-state fixture with a live-proof blocker.

    Args:
        root: Temporary repository root patched into the Agent Workspace router.

    Returns:
        Path to the local goal-state fixture.
    """

    plans_root = root / "docs" / "plans"
    plans_root.mkdir(parents=True)
    goal_path = plans_root / "longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
    goal_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-06-29T02:00:00+08:00",
                "rollback": {
                    "latest_goal_state_checkpoint_id": "20260629-020000-n305-mcp-summary-parity",
                    "latest_checkpoint_caveat": (
                        "Rollback checkpoint for C:/Users/xiao/private N305 MCP summary parity; "
                        "restore only with explicit user intent."
                    ),
                    "checkpoint_path": "C:/Users/xiao/.codex/rollback-checkpoints/private",
                    "restore_command": "Restore-Item C:/Users/xiao/private",
                },
                "requirements": [
                    {
                        "id": "N304-mcp-search-resource-readonly-annotations",
                        "status": "proved",
                        "requirement": "MCP read tools expose read-only annotations.",
                    },
                    {
                        "id": "N305-agent-workspace-mcp-goal-summary-blocker-parity",
                        "status": "proved",
                        "requirement": (
                            "MCP Agent Workspace status must preserve the goal completion blocker "
                            "visible in the REST response-model projection."
                        ),
                    },
                ],
                "completion_claim": {
                    "this_slice": "N305 proves MCP Agent Workspace status preserves completion blockers.",
                    "full_goal": "not_complete: live model proof remains authorization gated.",
                    "can_mark_goal_complete": False,
                    "why_not_complete": "C:/Users/xiao/private provider proof is still missing.",
                },
                "goal_lifecycle_rollup": {
                    "schema_version": "scholar_ai_goal_lifecycle_rollup/v1",
                    "updated_at": "2026-06-29T02:00:00+08:00",
                    "status": "active_requirements_proved_pending_authorized_gates",
                    "is_goal_complete": False,
                    "can_mark_goal_complete": False,
                    "requirements_total": 2,
                    "requirement_status_counts": {"proved": 2},
                    "requirements_all_proved": True,
                    "requirements_all_proved_or_out_of_scope": True,
                    "latest_requirement_id": "N305-agent-workspace-mcp-goal-summary-blocker-parity",
                    "latest_slice_id": "N305-agent-workspace-mcp-goal-summary-blocker-parity",
                    "completion_blockers": [
                        {
                            "id": "actual_loading_gate_live_model_proof_auth_required_current_provider",
                            "status": "blocked",
                            "requirement_surface": (
                                "Knowledge Runtime Pipeline QA at C:/Users/xiao/private"
                            ),
                            "missing_evidence": "Authorized live provider/model context-loading proof.",
                            "current_boundary": "Deterministic MCP parity tests are local proof only.",
                            "evidence": (
                                "N305 confirms REST and MCP Agent Workspace summaries expose the same "
                                "redacted blocker without live provider calls."
                            ),
                        }
                    ],
                    "machine_readable_completion_rule": "Goal completes only when blockers are empty.",
                    "why_not_complete": "C:/Users/xiao/private provider proof gates remain.",
                },
                "next_authorized_local_actions": [
                    "Create rollback checkpoint.",
                    "Search mature references.",
                    "Run focused REST and MCP contract tests.",
                ],
                "stop_boundary": [
                    "No push.",
                    "No live provider/model.",
                    "No Zotero DB mutation.",
                    "No github/ reference edits.",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return goal_path


def _read_rest_drilldown_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requirement_id: str,
) -> dict[str, Any]:
    """Read one drilldown through FastAPI response-model serialization."""

    _write_goal_state_fixture(tmp_path, requirement_id)
    monkeypatch.setattr(agent_workspace_router, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("LITASSIST_API_CAPABILITY_AUTH", "1")
    client = TestClient(server.app)
    endpoint = f"/api/agent-workspace/goal-requirements/{quote(requirement_id, safe='')}"

    response = client.get(
        endpoint,
        headers={server.LOCAL_API_CAPABILITY_HEADER: server.get_local_api_capability_token()},
    )

    assert response.status_code == 200
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("REST drilldown response must be a JSON object")
    return payload


def _read_rest_status_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    artifact_limit: int,
    audit_limit: int,
) -> dict[str, Any]:
    """Read Agent Workspace status through FastAPI response-model serialization."""

    if artifact_limit < 1:
        raise ValueError("artifact_limit must be positive")
    if audit_limit < 1:
        raise ValueError("audit_limit must be positive")
    _write_goal_summary_fixture(tmp_path)
    monkeypatch.setattr(agent_workspace_router, "REPO_ROOT", tmp_path)
    client = TestClient(server.app)

    response = client.get(
        "/api/agent-workspace/status",
        params={"artifact_limit": artifact_limit, "audit_limit": audit_limit},
    )

    assert response.status_code == 200
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("REST status response must be a JSON object")
    return payload


def test_agent_workspace_status_rest_and_mcp_goal_summary_stay_in_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP status must preserve REST goal-state blockers and redaction."""

    artifact_limit = 7
    audit_limit = 11
    rest_payload = _read_rest_status_payload(
        tmp_path,
        monkeypatch,
        artifact_limit=artifact_limit,
        audit_limit=audit_limit,
    )
    model_payload = agent_workspace_router.AgentWorkspaceStatus(**rest_payload).model_dump(mode="json")

    assert rest_payload == model_payload
    assert set(rest_payload) == set(agent_workspace_router.AgentWorkspaceStatus.model_fields)
    assert rest_payload["workspace_state"]["read_only"] is True
    goal_state = rest_payload["workspace_state"]["goal_state"]
    assert goal_state["available"] is True
    assert goal_state["completion_claim"]["can_mark_goal_complete"] is False
    assert goal_state["completion_claim"]["why_not_complete"] == (
        "[redacted-local-path] provider proof is still missing."
    )
    blockers = goal_state["lifecycle_rollup"]["completion_blockers"]
    assert len(blockers) == 1
    assert blockers[0]["id"] == "actual_loading_gate_live_model_proof_auth_required_current_provider"
    assert blockers[0]["status"] == "blocked"
    assert blockers[0]["requirement_surface"] == (
        "Knowledge Runtime Pipeline QA at [redacted-local-path]"
    )
    assert blockers[0]["missing_evidence"] == "Authorized live provider/model context-loading proof."
    assert blockers[0]["current_boundary"] == "Deterministic MCP parity tests are local proof only."
    assert "without live provider calls" in blockers[0]["evidence"]

    backend = _ParityBackend("/api/agent-workspace/status", rest_payload)
    tools = RuntimeTools(
        backend=backend,
        audit=AuditLog(tmp_path / "workspace_artifacts" / "agent_mcp_workflows" / ".audit"),
    )

    mcp_result = tools.agent_workspace_status(
        artifact_limit=artifact_limit,
        audit_limit=audit_limit,
    )

    assert mcp_result["is_error"] is False
    assert mcp_result["data"] == rest_payload
    assert backend.calls == [
        (
            "json",
            "/api/agent-workspace/status",
            {"artifact_limit": artifact_limit, "audit_limit": audit_limit},
        )
    ]
    mcp_goal_state = mcp_result["data"]["workspace_state"]["goal_state"]
    serialized_goal_state = json.dumps(mcp_goal_state, ensure_ascii=False)
    assert "C:/Users/xiao" not in serialized_goal_state
    assert "rollback-checkpoints" not in serialized_goal_state
    assert "Restore-Item" not in serialized_goal_state
    assert "checkpoint_path" not in serialized_goal_state
    assert mcp_goal_state["lifecycle_rollup"]["completion_blockers"] == blockers


def test_agent_workspace_requirement_rest_and_mcp_payloads_stay_in_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REST response-model output and MCP structured data must remain identical."""

    requirement_id = "N57 parity: browser visible requirement"
    encoded_endpoint = f"/api/agent-workspace/goal-requirements/{quote(requirement_id, safe='')}"
    rest_payload = _read_rest_drilldown_payload(tmp_path, monkeypatch, requirement_id)
    model_payload = agent_workspace_router.AgentWorkspaceGoalRequirementDrilldown(
        **rest_payload
    ).model_dump(mode="json")

    assert rest_payload == model_payload
    assert set(rest_payload) == set(agent_workspace_router.AgentWorkspaceGoalRequirementDrilldown.model_fields)
    assert rest_payload["schema_version"] == "scholar_ai_goal_requirement_drilldown_v1"
    assert rest_payload["available"] is True
    assert rest_payload["read_only"] is True
    assert rest_payload["id"] == requirement_id
    assert rest_payload["path"] == (
        "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
    )
    assert rest_payload["checkpoint_id"] == "20260626-061744-n201-goal-state-latest-checkpoint"
    assert rest_payload["evidence_count"] == 2
    assert rest_payload["truncated"] is False
    assert len(rest_payload["evidence"]) == 2
    assert rest_payload["next_safe_local_actions"] == [
        "Create a rollback checkpoint before the next nontrivial edit.",
        "Search official or mature references before changing the contract.",
        "Run focused REST and MCP contract tests.",
    ]
    assert rest_payload["stop_boundaries"] == [
        "No push, tag, release, deploy, or external upload.",
        "Do not treat external Computer Use package residual risk as missing local UIA proof.",
        "Do not enable import-to-wiki writes without explicit authorization.",
        "This fourth boundary remains visible.",
    ]

    backend = _ParityBackend(encoded_endpoint, rest_payload)
    tools = RuntimeTools(
        backend=backend,
        audit=AuditLog(tmp_path / "workspace_artifacts" / "agent_mcp_workflows" / ".audit"),
    )

    mcp_result = tools.agent_workspace_requirement(requirement_id)

    assert mcp_result["is_error"] is False
    assert mcp_result["data"] == rest_payload
    assert backend.calls == [("json", encoded_endpoint, None)]
    serialized = json.dumps(mcp_result["data"], ensure_ascii=False)
    assert "C:/Users/xiao" not in serialized
    assert "restore_command" not in serialized
    assert "checkpoint_path" not in serialized
    assert "This fourth action must be omitted." not in serialized
