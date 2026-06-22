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
    probes = payload["workspace_state"]["recovery_probes"]
    assert [probe["label"] for probe in probes] == [
        "Workflow Passport",
        "Evidence Integrity Gate",
        "Research Action Lifecycle",
        "Agent Handoff Card",
        "Agent Workspace Status",
    ]
    assert all(probe["read_only"] is True for probe in probes)
    handoff_probe = next(probe for probe in probes if probe["label"] == "Agent Handoff Card")
    assert handoff_probe["route"] == "/runtime/job/{job_id}/agent-handoff-card"
    assert handoff_probe["requires_identifier"] is True
    assert handoff_probe["identifier_hint"] == "job_id"
    assert handoff_probe["mcp_tool"] == "literature.agent_handoff_card"
    assert "replay recovery" in handoff_probe["purpose"]
    assert any("rollback checkpoint" in item for item in payload["workspace_state"]["boundaries"])
    assert payload["artifacts"][0]["path"] == "reports/summary.md"
    assert ".audit" not in payload["artifacts"][0]["path"]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-ant-api" not in serialized
    assert "Authorization: Bearer" not in serialized


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
