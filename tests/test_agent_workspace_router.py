from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

import routers.agent_workspace_router as agent_workspace_router
import python_adapter_server as server


def test_agent_workspace_status_lists_artifacts_and_redacted_audit(tmp_path, monkeypatch) -> None:
    workspace_root = tmp_path / "agent_mcp_workflows"
    runtime_root = tmp_path / "runtime_state"
    output_root = tmp_path / "generated" / "output"
    audit_root = workspace_root / ".audit"
    audit_root.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    output_root.mkdir(parents=True)
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
            updated_at="2026-06-22T21:50:27+08:00",
            checkpoint_id="20260622-214730-n41-goal-state-record-update",
            requirement_count=49,
            proved_count=47,
            incomplete_count=1,
            out_of_scope_count=1,
            latest_requirement_id="N41-goal-state-workspace-visibility",
            requirement_status=agent_workspace_router.AgentWorkspaceGoalRequirementStatus(
                total=49,
                proved=47,
                incomplete=1,
                out_of_scope=1,
                latest_id="N41-goal-state-workspace-visibility",
            ),
            open_requirements=[
                agent_workspace_router.AgentWorkspaceGoalOpenRequirement(
                    id="B01-computer-use-accessibility-tree",
                    status="incomplete",
                    requirement="Computer Use accessibility-tree acceptance is blocked by sandboxPolicy.",
                    residual_risk="Retry only after the external tool error is fixed.",
                )
            ],
            completion_claim=agent_workspace_router.AgentWorkspaceGoalCompletionClaim(
                this_slice="N41 made goal-state recovery visible.",
                full_goal="The full Scholar AI workflow spine remains active, not complete.",
            ),
            next_authorized_local_actions=[
                "Create a rollback checkpoint and search mature references before the next slice."
            ],
            stop_boundaries=["No push, tag, release, deploy, or external upload."],
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
    assert payload["workspace_state"]["artifact_root"]["path"] == "[redacted-local-path]"
    assert payload["workspace_state"]["artifact_root"]["truncated"] is False
    assert payload["workspace_state"]["runtime_state_root"]["exists"] is True
    assert payload["workspace_state"]["output_root"]["exists"] is True
    goal_state = payload["workspace_state"]["goal_state"]
    assert goal_state["available"] is True
    assert goal_state["path"] == "docs/plans/longrun-goal-state-local.json"
    assert goal_state["checkpoint_id"] == "20260622-214730-n41-goal-state-record-update"
    assert goal_state["requirement_count"] == 49
    assert goal_state["proved_count"] == 47
    assert goal_state["incomplete_count"] == 1
    assert goal_state["out_of_scope_count"] == 1
    assert goal_state["latest_requirement_id"] == "N41-goal-state-workspace-visibility"
    assert goal_state["requirement_status"] == {
        "total": 49,
        "proved": 47,
        "incomplete": 1,
        "out_of_scope": 1,
        "latest_id": "N41-goal-state-workspace-visibility",
    }
    assert goal_state["open_requirements"] == [
        {
            "id": "B01-computer-use-accessibility-tree",
            "status": "incomplete",
            "requirement": "Computer Use accessibility-tree acceptance is blocked by sandboxPolicy.",
            "residual_risk": "Retry only after the external tool error is fixed.",
        }
    ]
    assert goal_state["completion_claim"]["this_slice"] == "N41 made goal-state recovery visible."
    assert goal_state["completion_claim"]["full_goal"] == "The full Scholar AI workflow spine remains active, not complete."
    probes = payload["workspace_state"]["recovery_probes"]
    assert [probe["label"] for probe in probes] == [
        "Workflow Passport",
        "Evidence Integrity Gate",
        "Research Action Lifecycle",
        "Agent Handoff Card",
        "Agent Workspace Status",
        "Goal Requirement Drilldown",
    ]
    assert all(probe["read_only"] is True for probe in probes)
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
    assert any("rollback checkpoint" in item for item in payload["workspace_state"]["boundaries"])
    assert payload["artifacts"][0]["path"] == "reports/summary.md"
    assert ".audit" not in payload["artifacts"][0]["path"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-ant-api" not in serialized
    assert "Authorization: Bearer" not in serialized


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
                    "checkpoint_path": "C:/Users/xiao/.codex/rollback-checkpoints/private",
                    "restore_command": "restore C:/Users/xiao/private",
                },
                "requirements": [
                    {"id": "N39", "status": "proved"},
                    {"id": "N40", "status": "proved"},
                    {
                        "id": "B01",
                        "status": "incomplete",
                        "requirement": "Computer Use accessibility-tree acceptance blocked at C:/Users/xiao/private/app",
                        "residual_risk": "Retry only after sandboxPolicy is fixed.",
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
    assert summary.checkpoint_id == "20260622-213822-n41-goal-state-workspace-visibility"
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
    assert [item.id for item in summary.open_requirements] == ["B01", "D01", "M01", "W01", "C01"]
    assert summary.open_requirements[0].requirement == (
        "Computer Use accessibility-tree acceptance blocked at [redacted-local-path]"
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
                    "checkpoint_path": "C:/Users/xiao/.codex/rollback-checkpoints/private",
                    "restore_command": "restore C:/Users/xiao/private",
                },
                "requirements": [
                    {"id": "N39", "status": "proved", "requirement": "proved row"},
                    {
                        "id": "B01",
                        "status": "incomplete",
                        "requirement": "Computer Use accessibility-tree acceptance blocked at C:/Users/xiao/private/app",
                        "residual_risk": "Retry only after sandboxPolicy is fixed.",
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
        "/api/agent-workspace/goal-requirements/B01",
        headers={server.LOCAL_API_CAPABILITY_HEADER: server.get_local_api_capability_token()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "scholar_ai_goal_requirement_drilldown_v1"
    assert payload["available"] is True
    assert payload["read_only"] is True
    assert payload["path"] == "docs/plans/longrun-goal-state-2026-06-22-scholar-ai-research-workflow-spine.json"
    assert payload["updated_at"] == "2026-06-22T21:36:00+08:00"
    assert payload["checkpoint_id"] == "20260622-213822-n41-goal-state-workspace-visibility"
    assert payload["id"] == "B01"
    assert payload["status"] == "incomplete"
    assert payload["requirement"] == "Computer Use accessibility-tree acceptance blocked at [redacted-local-path]"
    assert payload["residual_risk"] == "Retry only after sandboxPolicy is fixed."
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
                "requirements": [{"id": "B01", "status": "incomplete"}],
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
