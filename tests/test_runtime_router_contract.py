# -*- coding: utf-8 -*-
"""Contract tests for runtime routes."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from harness_protocols import JobKind, SessionMode
from writing_runtime import WritingRuntime
import routers.runtime_router as runtime_router_module
import routers.skills_router as skills_router_module
from skills.audit import AuditLog
from skills.approval import ApprovalStore
import skills.service as skill_service_module
from skills.service import WritingSkillService


RUNTIME_SKILL_MD = """---
id: user.runtime.skill
name: Runtime Skill
version: 1.0.0
kind: transform
description: Runtime contract test skill.
entry_mode: manual
ui_visibility: skill_assisted
supported_scopes: [section]
permissions:
  draft.read: true
  retrieval.read: true
script_policy:
  has_scripts: false
  safe_to_execute: false
---

# Runtime Skill
"""


@pytest.mark.persistence_smoke
def test_runtime_events_route_supports_incremental_polling(monkeypatch) -> None:
    """The runtime job events endpoint should honor cursor and limit query params."""
    runtime = WritingRuntime()
    session = runtime.create_session(mode=SessionMode.SKILL)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="Route cursor test",
        skill_id="skill-route-test",
    )

    asyncio.run(runtime.start_job(job.job_id))
    asyncio.run(runtime.complete_job(job.job_id, result="done"))

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    ordered_response = client.get(f"/runtime/job/{job.job_id}/events")
    assert ordered_response.status_code == 200
    ordered_events = ordered_response.json()
    assert [event["event_type"] for event in ordered_events] == [
        "job_created",
        "job_started",
        "job_completed",
    ]

    cursor_response = client.get(
        f"/runtime/job/{job.job_id}/events",
        params={
            "since_timestamp": ordered_events[1]["timestamp"],
            "after_event_id": ordered_events[1]["event_id"],
            "limit": 1,
        },
    )
    assert cursor_response.status_code == 200
    assert [event["event_id"] for event in cursor_response.json()] == [ordered_events[2]["event_id"]]


@pytest.mark.persistence_smoke
def test_runtime_skill_action_preserves_structured_result_payload(monkeypatch, tmp_path) -> None:
    """Runtime skill jobs must preserve evidence/audit fields in transformed artifacts."""
    managed_root = tmp_path / "managed-skills"
    source_dir = tmp_path / "skill-source"
    source_dir.mkdir()
    (source_dir / "SKILL.md").write_text(RUNTIME_SKILL_MD, encoding="utf-8")
    (source_dir / "prompts").mkdir()
    (source_dir / "prompts" / "main.txt").write_text("Runtime={{ input_text }}", encoding="utf-8")

    skill_service = WritingSkillService(
        external_roots=None,
        approval_store=ApprovalStore(),
        audit_log=AuditLog(),
        managed_root=managed_root,
    )
    import_result = skill_service.import_user_skill(source_dir, managed_root=managed_root, origin="pytest")
    assert import_result["success"] is True
    skill_service.enable_skill("user.runtime.skill")

    runtime = WritingRuntime()
    session = runtime.create_session(mode=SessionMode.HYBRID)
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    monkeypatch.setattr(skills_router_module, "get_skill_service", lambda: skill_service)
    monkeypatch.setattr(skill_service_module, "get_writing_skill_service", lambda external_roots=None: skill_service)

    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    create_response = client.post(
        "/runtime/job",
        json={
            "session_id": session.session_id,
            "kind": "skill_action",
            "action_id": "skill:user.runtime.skill",
            "input_text": "selected paragraph",
            "scope": "section",
            "output_mode": "plain",
        },
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["job_id"]

    start_response = client.post(f"/runtime/job/{job_id}/start")
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "completed"

    artifacts_response = client.get(f"/runtime/job/{job_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    assert [artifact["artifact_type"] for artifact in artifacts] == ["transformed_text"]
    content = artifacts[0]["content"]
    assert content["job_id"] == job_id
    assert content["output_text"] == "Runtime=selected paragraph"
    assert content["structured_output"]["execution_mode"] == "prompt_only"
    assert content["structured_output"]["scope"] == "section"
    assert content["structured_output"]["output_mode"] == "plain"
    assert content["structured_output"]["permissions"]["retrieval.read"] is True
    assert content["evidence_refs"] == []
    assert content["audit_id"]


@pytest.mark.persistence_smoke
def test_runtime_direct_skill_job_preserves_structured_result_payload(monkeypatch, tmp_path) -> None:
    """Direct skill_id jobs should keep the same artifact contract as action_id jobs."""
    managed_root = tmp_path / "managed-skills"
    source_dir = tmp_path / "skill-source"
    source_dir.mkdir()
    (source_dir / "SKILL.md").write_text(RUNTIME_SKILL_MD, encoding="utf-8")
    (source_dir / "prompts").mkdir()
    (source_dir / "prompts" / "main.txt").write_text("Direct={{ input_text }}", encoding="utf-8")

    skill_service = WritingSkillService(
        external_roots=None,
        approval_store=ApprovalStore(),
        audit_log=AuditLog(),
        managed_root=managed_root,
    )
    import_result = skill_service.import_user_skill(source_dir, managed_root=managed_root, origin="pytest")
    assert import_result["success"] is True
    skill_service.enable_skill("user.runtime.skill")

    runtime = WritingRuntime()
    session = runtime.create_session(mode=SessionMode.HYBRID)
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    monkeypatch.setattr(skill_service_module, "get_writing_skill_service", lambda external_roots=None: skill_service)

    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    create_response = client.post(
        "/runtime/job",
        json={
            "session_id": session.session_id,
            "kind": "skill_action",
            "skill_id": "user.runtime.skill",
            "input_text": "direct paragraph",
            "scope": "section",
            "output_mode": "plain",
        },
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["job_id"]

    start_response = client.post(f"/runtime/job/{job_id}/start")
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "completed"

    artifacts_response = client.get(f"/runtime/job/{job_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    assert [artifact["artifact_type"] for artifact in artifacts] == ["transformed_text"]
    content = artifacts[0]["content"]
    assert content["job_id"] == job_id
    assert content["output_text"] == "Direct=direct paragraph"
    assert content["structured_output"]["execution_mode"] == "prompt_only"
    assert content["structured_output"]["scope"] == "section"
    assert content["structured_output"]["output_mode"] == "plain"
    assert content["evidence_refs"] == []
    assert content["audit_id"]


@pytest.mark.persistence_full
def test_runtime_session_routes_cover_workspace_lookup_resume_rewind_and_fork(monkeypatch, tmp_path) -> None:
    """The runtime router should expose the minimal workspace-bound persistence flow."""
    workspace_root = tmp_path / "workspace"
    entry_cwd = workspace_root / "drafts"
    entry_cwd.mkdir(parents=True)
    runtime = WritingRuntime(database_path=workspace_root / ".modular" / "sessions" / "index.sqlite3", autosave=True)

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    create_response = client.post(
        "/runtime/session",
        json={
            "mode": "skill",
            "workspace_root": str(workspace_root),
            "entry_cwd": str(entry_cwd),
            "title": "Workspace route session",
        },
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    job = runtime.create_job(
        session_id=session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="router flow",
        skill_id="skill-router",
    )
    asyncio.run(runtime.start_job(job.job_id))
    asyncio.run(runtime.complete_job(job.job_id, result="router-result"))

    sessions_response = client.get("/runtime/sessions", params={"workspace_root": str(workspace_root)})
    assert sessions_response.status_code == 200
    assert [payload["session_id"] for payload in sessions_response.json()] == [session_id]

    current_response = client.get("/runtime/session/current", params={"workspace_root": str(workspace_root)})
    assert current_response.status_code == 200
    assert current_response.json()["session_id"] == session_id

    resume_response = client.post(f"/runtime/session/{session_id}/resume")
    assert resume_response.status_code == 200
    head_checkpoint_id = resume_response.json()["head_checkpoint_id"]

    timeline_response = client.get(
        f"/runtime/session/{session_id}/timeline",
        params={"limit": 2},
    )
    assert timeline_response.status_code == 200
    assert len(timeline_response.json()["items"]) == 2

    checkpoints_response = client.get(f"/runtime/session/{session_id}/checkpoints")
    assert checkpoints_response.status_code == 200
    checkpoint_ids = [payload["checkpoint_id"] for payload in checkpoints_response.json()]
    assert head_checkpoint_id in checkpoint_ids

    rewind_response = client.post(
        f"/runtime/session/{session_id}/rewind",
        json={"checkpoint_id": checkpoint_ids[0], "mode": "conversation_only"},
    )
    assert rewind_response.status_code == 200
    assert rewind_response.json()["head_checkpoint_id"] == checkpoint_ids[0]

    fork_response = client.post(
        f"/runtime/session/{session_id}/fork",
        json={"checkpoint_id": checkpoint_ids[0], "title": "Forked route session"},
    )
    assert fork_response.status_code == 200
    assert fork_response.json()["session"]["metadata"]["parent_session_id"] == session_id


@pytest.mark.persistence_full
def test_runtime_router_handles_invalid_session_ids(monkeypatch, tmp_path) -> None:
    """The runtime router should return 404 for invalid session IDs."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)
    runtime = WritingRuntime(database_path=workspace_root / ".modular" / "sessions" / "index.sqlite3", autosave=True)

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    invalid_session_id = "session_nonexistent_12345"

    get_response = client.get(f"/runtime/session/{invalid_session_id}")
    assert get_response.status_code == 404

    resume_response = client.post(f"/runtime/session/{invalid_session_id}/resume")
    assert resume_response.status_code == 404

    timeline_response = client.get(f"/runtime/session/{invalid_session_id}/timeline")
    assert timeline_response.status_code == 404

    checkpoints_response = client.get(f"/runtime/session/{invalid_session_id}/checkpoints")
    assert checkpoints_response.status_code == 404


@pytest.mark.persistence_full
def test_runtime_router_handles_invalid_job_ids(monkeypatch, tmp_path) -> None:
    """The runtime router should return 404 for invalid job IDs."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)
    runtime = WritingRuntime(database_path=workspace_root / ".modular" / "sessions" / "index.sqlite3", autosave=True)

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    invalid_job_id = "job_nonexistent_12345"

    get_response = client.get(f"/runtime/job/{invalid_job_id}")
    assert get_response.status_code == 404

    status_response = client.get(f"/runtime/job/{invalid_job_id}/status")
    assert status_response.status_code == 404

    events_response = client.get(f"/runtime/job/{invalid_job_id}/events")
    assert events_response.status_code == 404

    artifacts_response = client.get(f"/runtime/job/{invalid_job_id}/artifacts")
    assert artifacts_response.status_code == 404


@pytest.mark.persistence_smoke
def test_runtime_router_rejects_invalid_session_mode(monkeypatch, tmp_path) -> None:
    """The runtime router should reject invalid session modes."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)
    runtime = WritingRuntime(database_path=workspace_root / ".modular" / "sessions" / "index.sqlite3", autosave=True)

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.post(
        "/runtime/session",
        json={
            "mode": "invalid_mode_xyz",
            "workspace_root": str(workspace_root),
        },
    )
    assert response.status_code == 400
    assert "Invalid mode" in response.json()["detail"]
