# -*- coding: utf-8 -*-
"""Contract tests for runtime routes."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from harness_protocols import ArtifactType, JobKind, SessionMode
from writing_runtime import WritingRuntime
import writing_runtime as writing_runtime_module
import routers.runtime_router as runtime_router_module
import routers.resources_router as resources_router_module
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


class _FakeFigureAsset:
    """Minimal figure asset object matching the store's public to_dict shape."""

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_id": "fig_asset_runtime",
            "project_id": "project-runtime-figures",
            "kind": "figure",
            "caption": "图 0：已保存图表",
            "numbering": "图 0",
            "material_id": "material-a",
            "source_page": 1,
            "bbox": None,
            "asset_path": "figures/existing.png",
            "width": None,
            "height": None,
            "format": "png",
            "created_at": "2026-06-01T00:00:00Z",
            "updated_at": "2026-06-01T00:00:00Z",
        }


class _FakeFigureStore:
    """Store seam used by figure-load runtime contract tests."""

    def list_figure_assets(self, project_id: str) -> list[_FakeFigureAsset]:
        if project_id != "project-runtime-figures":
            raise ValueError("unexpected project_id")
        return [_FakeFigureAsset()]


def _wait_for_job_terminal(client: TestClient, job_id: str) -> dict[str, object]:
    """Poll runtime status until a background job reaches a terminal state."""
    for _ in range(50):
        status_response = client.get(f"/runtime/job/{job_id}/status")
        assert status_response.status_code == 200
        payload = status_response.json()
        if payload["status"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"runtime job did not reach terminal state: {job_id}")


async def _start_runtime_job_and_wait(
    runtime: WritingRuntime,
    job_id: str,
    executor: Callable[[object], Any],
) -> None:
    """Start a runtime job and drain the background task inside one event loop."""
    await runtime.start_job(job_id, executor=executor)
    task = runtime._job_tasks.get(job_id)
    if task is not None:
        await task


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
    assert [event["sequence"] for event in ordered_events] == [1, 2, 3]

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

    sequence_response = client.get(
        f"/runtime/job/{job.job_id}/events",
        params={
            "after_sequence": ordered_events[1]["sequence"],
            "limit": 1,
        },
    )
    assert sequence_response.status_code == 200
    assert [event["event_id"] for event in sequence_response.json()] == [ordered_events[2]["event_id"]]

    snapshot_response = client.get(
        f"/runtime/job/{job.job_id}/snapshot",
        params={"after_sequence": 1, "limit": 1},
    )
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["job_id"] == job.job_id
    assert snapshot["status"]["status"] == "completed"
    assert snapshot["events"][0]["event_type"] == "job_started"
    assert snapshot["events"][0]["sequence"] == 2
    assert snapshot["next_after_sequence"] == 2
    assert snapshot["latest_sequence"] == 3
    assert snapshot["has_more"] is True


@pytest.mark.persistence_smoke
def test_runtime_failed_job_status_and_snapshot_do_not_look_like_missing_job(monkeypatch) -> None:
    """A failed job's error field is job state, not a 404 sentinel."""
    runtime = WritingRuntime()
    session = runtime.create_session(mode=SessionMode.SKILL)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="Failure status test",
    )
    asyncio.run(runtime.start_job(job.job_id))
    asyncio.run(runtime.fail_job(job.job_id, "provider timed out"))

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    status_response = client.get(f"/runtime/job/{job.job_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "failed"
    assert status_response.json()["error"] == "provider timed out"

    snapshot_response = client.get(f"/runtime/job/{job.job_id}/snapshot")
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["status"]["status"] == "failed"
    assert snapshot["status"]["error"] == "provider timed out"
    assert [event["sequence"] for event in snapshot["events"]] == [1, 2, 3]


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

    job = runtime.get_job(job_id)
    assert job is not None
    executor = runtime_router_module._build_job_executor(job)
    assert executor is not None
    asyncio.run(_start_runtime_job_and_wait(runtime, job_id, executor))
    completed_job = runtime.get_job(job_id)
    assert completed_job is not None
    assert completed_job.status.value == "completed"

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

    job = runtime.get_job(job_id)
    assert job is not None
    executor = runtime_router_module._build_job_executor(job)
    assert executor is not None
    asyncio.run(_start_runtime_job_and_wait(runtime, job_id, executor))
    completed_job = runtime.get_job(job_id)
    assert completed_job is not None
    assert completed_job.status.value == "completed"

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
    refreshed_session = runtime.get_session(session_id)
    assert refreshed_session is not None
    assert refreshed_session.metadata["title"] == "router flow"
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

    delete_response = client.delete(f"/runtime/session/{session_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"session_id": session_id, "deleted": True}
    assert client.get(f"/runtime/session/{session_id}").status_code == 404
    assert client.get(f"/runtime/session/{session_id}/timeline").status_code == 404
    assert client.delete(f"/runtime/session/{session_id}").status_code == 404


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
def test_runtime_delete_job_clears_owned_runtime_data(monkeypatch, tmp_path) -> None:
    """DELETE /runtime/job/{id} removes the job, events, artifacts, and transcript rows."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)
    runtime = WritingRuntime(database_path=workspace_root / ".modular" / "sessions" / "index.sqlite3", autosave=True)
    session = runtime.create_session(mode=SessionMode.PROMPT)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="delete me",
    )
    asyncio.run(runtime.start_job(job.job_id))
    asyncio.run(runtime.complete_job(job.job_id, {"text": "artifact"}))

    assert runtime.get_job_events(job.job_id)
    assert runtime.get_job_artifacts(job.job_id)

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.delete(f"/runtime/job/{job.job_id}")

    assert response.status_code == 200
    assert response.json() == {"job_id": job.job_id, "deleted": True}
    assert runtime.get_job(job.job_id) is None
    assert runtime.get_job_events(job.job_id) == []
    assert runtime.get_job_artifacts(job.job_id) == []
    assert all(
        event.get("payload", {}).get("job_id") != job.job_id
        for event in runtime._session_transcripts[session.session_id]
        if isinstance(event.get("payload"), dict)
    )


@pytest.mark.persistence_smoke
def test_runtime_router_updates_writing_workflow_state(monkeypatch, tmp_path) -> None:
    """Runtime API should expose writing workflow state without changing job response contracts."""

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True)
    runtime = WritingRuntime(database_path=workspace_root / ".modular" / "sessions" / "index.sqlite3", autosave=True)
    session = runtime.create_session(mode=SessionMode.SKILL)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="wire workflow state",
        metadata={"project_id": "project-1"},
    )

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.post(
        f"/runtime/job/{job.job_id}/writing-workflow-state",
        json={
            "phase": "linted_export_ready",
            "intake": {"task_type": "review", "target_venue": "Example Journal"},
            "evidence_refs": [{"ref_id": "chunk:c1", "claim": "claim", "support_status": "supported"}],
            "citation_bank": [{"citation_id": "cite:c1", "ref_id": "chunk:c1"}],
            "lint_report": {"passed": True, "score": 91},
            "export_manifest": {"format": "docx", "artifact_path": "workspace_artifacts/generated/output/out.docx"},
            "change_log": [{"stage": "lint", "summary": "Ready for export."}],
        },
    )

    assert response.status_code == 200
    state = response.json()
    assert state["phase"] == "linted_export_ready"
    assert state["readiness"]["has_export_manifest"] is True

    snapshot_response = client.get(f"/runtime/job/{job.job_id}/snapshot")
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["job"]["metadata"]["writing_workflow_state"]["phase"] == "linted_export_ready"
    assert any(
        event["data"].get("workflow_phase") == "linted_export_ready"
        for event in snapshot["events"]
    )

    artifacts_response = client.get(f"/runtime/job/{job.job_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    assert any(
        artifact["artifact_type"] == "metadata"
        and artifact["content"]["kind"] == "writing_workflow_state"
        and artifact["content"]["state"]["phase"] == "linted_export_ready"
        for artifact in artifacts
    )


@pytest.mark.persistence_smoke
def test_runtime_jobs_project_writing_workflow_state_summary(monkeypatch, tmp_path) -> None:
    """Runtime job lists should expose compact workflow state without metadata parsing."""

    workspace_root = tmp_path / "runtime-workspace"
    workspace_root.mkdir(parents=True)
    runtime = WritingRuntime(database_path=workspace_root / ".modular" / "sessions" / "index.sqlite3", autosave=True)
    session = runtime.create_session(mode=SessionMode.SKILL, user_id="agent-workspace")
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export paper",
        metadata={"project_id": "project-runtime-summary"},
    )
    runtime.update_writing_workflow_state(
        job.job_id,
        phase="export_ready",
        intake={"project_id": "project-runtime-summary", "format": "json"},
        export_manifest={"format": "json", "filename": "paper.json"},
        lint_report={"writing_audit_present": True},
        change_log=[{"stage": "export", "summary": "Exported JSON."}],
    )

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get("/runtime/jobs")

    assert response.status_code == 200
    payload = response.json()
    exported = next(item for item in payload if item["job_id"] == job.job_id)
    summary = exported["writing_workflow_state_summary"]
    assert summary["phase"] == "export_ready"
    assert summary["readiness"]["has_export_manifest"] is True
    assert summary["export_format"] == "json"
    assert summary["export_filename"] == "paper.json"
    claims = summary["readiness_claims"]
    assert claims["schema_version"] == "scholar_ai_workflow_enforcement_v1"
    export_claim = next(
        claim
        for claim in claims["claims"]
        if claim["claim_id"] == "export_readiness"
    )
    assert export_claim["status"] == "unresolved"
    assert claims["summary"]["unresolved_is_ready"] is False
    assert "citation_bank" not in summary
    assert "evidence_refs" not in summary


@pytest.mark.persistence_smoke
def test_runtime_router_updates_material_processing_task(monkeypatch, tmp_path) -> None:
    """Runtime API should expose resumable material-processing task contracts."""

    workspace_root = tmp_path / "runtime-material-workspace"
    workspace_root.mkdir(parents=True)
    runtime = WritingRuntime(database_path=workspace_root / ".modular" / "sessions" / "index.sqlite3", autosave=True)
    session = runtime.create_session(mode=SessionMode.PROMPT, user_id="material-router")
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text="process material",
        metadata={"project_id": "project-material-router"},
    )

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.post(
        f"/runtime/job/{job.job_id}/material-processing-task",
        json={
            "schema_version": "material_processing_task_v1",
            "project_id": "project-material-router",
            "material_id": "material-router",
            "input_ref": {
                "ref_type": "uploaded_source_file",
                "material_id": "material-router",
                "source_path_label": "router.pdf",
                "content_digest": "sha256:router",
                "size_bytes": 4096,
            },
            "page_range": {"mode": "range", "start_page": 2, "end_page": 4},
            "processing_mode": "fast_text",
            "cache": {"policy": "refresh", "content_digest": "sha256:router"},
            "output_targets": ["chunks", "locators", "text_sidecar"],
            "metadata": {"source": "router-test"},
        },
    )

    assert response.status_code == 200
    task = response.json()
    assert task["status"] == "queued"
    assert task["request"]["page_range"] == {"mode": "range", "start_page": 2, "end_page": 4, "pages": []}
    assert task["cache"]["policy"] == "refresh"
    assert task["cache"]["parameter_digest"].startswith("sha256:")
    assert task["cache"]["decision_record"]["schema_version"] == "material_processing_cache_decision_v1"
    assert task["cache"]["decision_record"]["decision"] == "pending"
    assert task["cache"]["decision_record"]["replayable"] is False

    get_response = client.get(f"/runtime/job/{job.job_id}/material-processing-task")
    assert get_response.status_code == 200
    assert get_response.json()["cache"]["cache_key"] == task["cache"]["cache_key"]
    assert get_response.json()["cache"]["decision_record"]["decision_id"] == task["cache"]["decision_record"]["decision_id"]

    jobs_response = client.get("/runtime/jobs")
    assert jobs_response.status_code == 200
    exported = next(item for item in jobs_response.json() if item["job_id"] == job.job_id)
    summary = exported["material_processing_task_summary"]
    assert summary["material_id"] == "material-router"
    assert summary["processing_mode"] == "fast_text"
    assert summary["cache"]["policy"] == "refresh"
    assert summary["source_path_label"] == "router.pdf"

    invalid_response = client.post(
        f"/runtime/job/{job.job_id}/material-processing-task",
        json={
            "schema_version": "material_processing_task_v1",
            "project_id": "project-material-router",
            "material_id": "material-router",
            "input_ref": {"ref_type": "uploaded_source_file", "material_id": "material-router"},
            "page_range": {"mode": "range", "start_page": 5, "end_page": 4},
            "processing_mode": "fast_text",
            "output_targets": ["chunks"],
        },
    )
    assert invalid_response.status_code == 422


@pytest.mark.persistence_smoke
def test_uploaded_pdf_extraction_job_records_material_processing_contract(monkeypatch, tmp_path) -> None:
    """Background PDF upload extraction should create and complete a material task record."""

    runtime = WritingRuntime(database_path=tmp_path / "upload-runtime.sqlite3", autosave=True)
    monkeypatch.setattr(writing_runtime_module, "get_writing_runtime", lambda: runtime)
    source_path = tmp_path / "paper.pdf"
    source_path.write_bytes(b"%PDF-1.4\n")

    def _fake_extract(filename: str, path: object) -> object:
        assert filename == "paper.pdf"
        assert path == source_path
        return resources_router_module.ExtractedDocumentPayload(
            content="Title\n\nBody text",
            blocks=None,
            markdown_full="# Title\n\nBody text",
        )

    def _fake_write_material_document_content(
        project_id: str,
        material_id: str,
        filename: str,
        content: str,
        **kwargs: object,
    ) -> dict[str, object]:
        assert project_id == "project-upload-contract"
        assert material_id == "material-upload-contract"
        assert filename == "paper.pdf"
        assert "Body text" in content
        assert kwargs["source_fingerprint"] == "sha256:upload"
        return {
            "material_id": material_id,
            "title": filename,
            "content_length": len(content),
            "chunks": 2,
            "status": "ok",
            "sidecar_markdown_path": str(tmp_path / "paper.md"),
        }

    monkeypatch.setattr(resources_router_module, "_extract_document_payload_from_path", _fake_extract)
    monkeypatch.setattr(resources_router_module, "_write_material_document_content", _fake_write_material_document_content)

    async def _run_upload_job() -> str:
        _, job_id = await resources_router_module._start_uploaded_document_extraction_job(
            "project-upload-contract",
            "material-upload-contract",
            "paper.pdf",
            source_path,
            source_fingerprint="sha256:upload",
            source_size=source_path.stat().st_size,
        )
        queued_task = runtime.get_material_processing_task(job_id)
        assert queued_task is not None
        assert queued_task["request"]["material_id"] == "material-upload-contract"
        assert queued_task["request"]["output_targets"] == ["chunks", "locators", "text_sidecar"]
        task = runtime._job_tasks.get(job_id)
        assert task is not None
        await task
        return job_id

    job_id = asyncio.run(_run_upload_job())
    job = runtime.get_job(job_id)
    task = runtime.get_material_processing_task(job_id)
    events = runtime.get_job_events(job_id)

    assert job is not None
    assert job.status.value == "completed"
    assert task is not None
    assert task["status"] == "completed"
    assert task["result"]["chunks"] == 2
    assert task["cache"]["content_digest"] == "sha256:upload"
    assert task["cache"]["decision"] == "miss"
    assert task["cache"]["decision_record"]["decision"] == "miss"
    assert task["cache"]["decision_record"]["has_all_requested_outputs"] is True
    assert task["cache"]["decision_record"]["artifact_family_digest"].startswith("sha256:")
    assert {artifact["output_target"] for artifact in task["artifacts"]} == {"chunks", "locators", "text_sidecar"}
    assert any(event.data.get("material_processing_status") == "completed" for event in events)


@pytest.mark.persistence_smoke
def test_runtime_research_projection_projects_objects_events_and_approval_boundaries(monkeypatch) -> None:
    """Research projection should expose auditable objects/events without private payload fields."""

    runtime = WritingRuntime()
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        user_id="research-agent",
        metadata={"project_id": "project-research-object", "title": "Runtime Projection Project"},
    )
    material_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text="private material prompt",
        metadata={
            "project_id": "project-research-object",
            "material_id": "material-001",
            "title": "Additive manufacturing review.pdf",
            "source_path": "workspace_artifacts/input/review.pdf",
            "api_key": "sk-test-secret",
            "prompt": "private prompt",
        },
    )
    evidence_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SMART_READ,
        input_text="build evidence pack",
        metadata={
            "project_id": "project-research-object",
            "material_id": "material-001",
            "evidence_pack_id": "pack-001",
            "task_type": "evidence_pack_build",
        },
    )
    runtime.add_job_artifact(
        evidence_job.job_id,
        artifact_type=ArtifactType.METADATA,
        content={"kind": "evidence_pack", "summary": "bounded support only"},
        created_by="pytest",
        metadata={"evidence_pack_id": "pack-001", "project_id": "project-research-object"},
    )
    agent_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="agent should summarize",
        metadata={
            "project_id": "project-research-object",
            "agent_request_id": "agent-request-001",
            "material_id": "material-001",
            "raw_content": "private raw result",
        },
    )
    approval = runtime.request_approval(
        job_id=agent_job.job_id,
        session_id=session.session_id,
        reason="Confirm generated synthesis before export.",
        metadata={"project_id": "project-research-object", "review_step": "human_confirm"},
    )

    asyncio.run(runtime.start_job(material_job.job_id))
    asyncio.run(runtime.complete_job(material_job.job_id, result={"kind": "resource_ingest", "indexed": 1}))
    asyncio.run(runtime.start_job(evidence_job.job_id))
    asyncio.run(runtime.complete_job(evidence_job.job_id, result={"kind": "evidence_pack", "pack_id": "pack-001"}))

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get(
        "/runtime/research-projection",
        params={"project_id": "project-research-object", "limit": 50},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "research_object_projection_v1"
    assert payload["scope"]["project_id"] == "project-research-object"
    object_by_id = {item["object_id"]: item for item in payload["objects"]}
    assert object_by_id["research_project:project-research-object"]["title"] == "Runtime Projection Project"
    assert object_by_id["research_material:material-001"]["material_id"] == "material-001"
    assert object_by_id["evidence_pack:pack-001"]["object_type"] == "evidence_pack"
    assert object_by_id["agent_request:agent-request-001"]["confirmation_boundary"]["pending_approval_count"] == 1
    assert object_by_id[f"approval_gate:{approval.approval_id}"]["confirmation_boundary"][
        "requires_user_confirmation"
    ] is True

    event_types = {event["event_type"] for event in payload["events"]}
    assert {"material.ingest.started", "material.ingest.completed", "evidence.pack.created", "approval.required"} <= event_types
    assert payload["approval_boundaries"][0]["target_object_id"] == "agent_request:agent-request-001"
    assert payload["status_projection"]["requires_user_confirmation"] is True
    assert payload["status_projection"]["pending_approval_count"] == 1
    serialized = str(payload)
    assert "sk-test-secret" not in serialized
    assert "private prompt" not in serialized
    assert "private raw result" not in serialized

    job_response = client.get(
        "/runtime/research-projection",
        params={"job_id": agent_job.job_id, "limit": 10},
    )
    assert job_response.status_code == 200
    job_payload = job_response.json()
    assert all(event["job_id"] == agent_job.job_id for event in job_payload["events"])
    assert job_payload["status_projection"]["effect_counts"]["jobs"] == 1

    missing_response = client.get(
        "/runtime/research-projection",
        params={"job_id": "job_missing"},
    )
    assert missing_response.status_code == 404


@pytest.mark.persistence_smoke
def test_runtime_workflow_passport_projects_stage_gates(monkeypatch, tmp_path) -> None:
    """Workflow passport should project stage evidence and blocking approvals."""

    runtime = WritingRuntime(database_path=tmp_path / "workflow-passport.sqlite3", autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        user_id="passport-user",
        metadata={"project_id": "project-passport", "title": "Passport Project"},
    )
    material_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text="ingest material",
        metadata={"project_id": "project-passport", "material_id": "material-passport"},
    )
    runtime.update_material_processing_task(
        material_job.job_id,
        request={
            "schema_version": "material_processing_task_v1",
            "project_id": "project-passport",
            "material_id": "material-passport",
            "input_ref": {
                "ref_type": "uploaded_source_file",
                "material_id": "material-passport",
                "content_digest": "sha256:passport-material",
            },
            "processing_mode": "fast_text",
            "cache": {"policy": "use", "decision": "hit"},
            "output_targets": ["chunks", "locators"],
        },
        status="completed",
        result={"chunks": 2},
        artifacts=[
            {
                "artifact_type": "chunk_index",
                "output_target": "chunks",
                "count": 2,
                "path": "C:\\Users\\xiao\\private\\chunks.jsonl",
            },
            {
                "artifact_type": "locator_index",
                "output_target": "locators",
                "count": 2,
                "path": "workspace_artifacts/private/locators.jsonl",
            },
        ],
        provenance={"source": "pytest"},
    )
    evidence_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SMART_READ,
        input_text="build evidence",
        metadata={
            "project_id": "project-passport",
            "material_id": "material-passport",
            "evidence_pack_id": "pack-passport",
        },
    )
    runtime.add_job_artifact(
        evidence_job.job_id,
        artifact_type=ArtifactType.METADATA,
        content={
            "kind": "evidence_pack",
            "locator_coverage": {
                "coverage_state": "strong",
                "risk_level": "none",
                "project_ref_count": 2,
                "page_locator_count": 2,
                "bbox_locator_count": 2,
                "bbox_unit_counts": {"pdf_point": 2},
                "source_label_coverage_ratio": 1.0,
                "figure_table_locator_count": 1,
            },
            "qrels_status": {
                "status": "available",
                "quality_claim": "semantic_qrels_ready",
                "semantic_quality_claim_allowed": True,
            },
        },
        created_by="pytest",
        metadata={"evidence_pack_id": "pack-passport", "project_id": "project-passport"},
    )
    asyncio.run(runtime.start_job(evidence_job.job_id))
    asyncio.run(runtime.complete_job(evidence_job.job_id, {"kind": "evidence_pack"}))
    draft_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="draft and export",
        metadata={"project_id": "project-passport", "export_artifact_id": "export-passport"},
    )
    runtime.update_writing_workflow_state(
        draft_job.job_id,
        phase="export_ready",
        intake={"project_id": "project-passport", "task_type": "draft"},
        evidence_refs=[{"ref_id": "chunk:1"}],
        citation_bank=[{"citation_id": "cite:1"}],
        lint_report={"passed": True},
        export_manifest={"format": "docx", "filename": "passport.docx"},
        change_log=[{"stage": "export", "summary": "ready"}],
    )
    preflight = runtime.build_action_preflight(
        action_id="writing.export_project",
        required_claim_id="export_readiness",
        session_id=session.session_id,
        job_id=draft_job.job_id,
        project_id="project-passport",
        require_ready=False,
        persist_refresh_receipt=True,
    )
    agent_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="handoff",
        metadata={"project_id": "project-passport", "agent_request_id": "agent-passport"},
    )
    approval = runtime.request_approval(
        job_id=agent_job.job_id,
        session_id=session.session_id,
        reason="Confirm handoff.",
        metadata={"project_id": "project-passport"},
    )

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get("/runtime/workflow-passport", params={"project_id": "project-passport"})

    assert response.status_code == 200
    passport = response.json()
    assert passport["schema_version"] == "scholar_ai_workflow_passport_v1"
    assert passport["scope"]["project_id"] == "project-passport"
    stage_by_id = {stage["stage_id"]: stage for stage in passport["stages"]}
    assert list(stage_by_id) == [
        "material_ingest",
        "material_read",
        "evidence_pack",
        "outline",
        "draft",
        "citation_review",
        "export",
        "agent_handoff",
    ]
    assert stage_by_id["material_ingest"]["status"] == "complete"
    assert stage_by_id["material_ingest"]["gate"]["status"] == "pass"
    assert {item["output_target"] for item in stage_by_id["material_ingest"]["present_artifacts"] if "output_target" in item} >= {
        "chunks",
        "locators",
    }
    ingest_diagnostics = stage_by_id["material_ingest"]["diagnostics"]
    ingest_reproducibility = stage_by_id["material_ingest"]["reproducibility"]
    assert ingest_diagnostics["task_count"] == 1
    assert ingest_diagnostics["cache_decisions"] == {"hit": 1}
    assert ingest_reproducibility["read_only"] is True
    assert ingest_reproducibility["parameter_digest_count"] == 1
    assert ingest_reproducibility["cache_key_count"] == 1
    assert ingest_reproducibility["cache_decision_record_count"] == 1
    assert ingest_reproducibility["cache_refs"][0]["decision"] == "hit"
    assert ingest_reproducibility["cache_decision_refs"][0]["ref_type"] == "material_processing_cache_decision"
    assert ingest_reproducibility["cache_decision_refs"][0]["decision"] == "hit"
    assert ingest_reproducibility["cache_decision_refs"][0]["replayable"] is True
    assert ingest_reproducibility["cache_decision_refs"][0]["has_all_requested_outputs"] is True
    artifact_refs = stage_by_id["material_read"]["reproducibility"]["artifact_refs"]
    assert {item["output_target"] for item in artifact_refs if "output_target" in item} >= {"chunks", "locators"}
    assert all("path" not in item for item in artifact_refs)
    assert any(item.get("path_present") is True and str(item.get("path_digest", "")).startswith("sha256:") for item in artifact_refs)
    assert stage_by_id["evidence_pack"]["status"] == "complete"
    evidence_reproducibility = stage_by_id["evidence_pack"]["reproducibility"]
    assert evidence_reproducibility["locator_refs"][0]["risk_level"] == "none"
    assert evidence_reproducibility["locator_refs"][0]["bbox_unit_counts"] == {"pdf_point": 2}
    assert evidence_reproducibility["qrels_refs"][0]["semantic_quality_claim_allowed"] is True
    assert stage_by_id["draft"]["gate"]["status"] == "pass"
    assert stage_by_id["citation_review"]["gate"]["status"] == "pass"
    assert stage_by_id["export"]["gate"]["status"] == "unresolved"
    export_reproducibility = stage_by_id["export"]["reproducibility"]
    assert export_reproducibility["preflight_receipts"][0]["ref_id"] == preflight["refresh_receipt_id"]
    assert "workflow_passport" in export_reproducibility["projection_digest_keys"]
    assert any(
        probe["endpoint"] == f"/runtime/job/{draft_job.job_id}/workflow-replay-lineage"
        for probe in export_reproducibility["replay_probe_refs"]
    )
    assert stage_by_id["agent_handoff"]["gate"]["status"] == "block"
    assert stage_by_id["agent_handoff"]["gate"]["requires_user_confirmation"] is True
    assert approval.approval_id in str(stage_by_id["agent_handoff"])
    assert passport["gate_summary"]["requires_user_confirmation"] is True
    assert passport["gate_summary"]["blocking_stage_ids"] == ["agent_handoff"]
    assert "runtime.research_projection" in passport["provenance"]["derived_from"]
    serialized = str(passport)
    assert "C:\\Users\\xiao\\private" not in serialized
    assert "workspace_artifacts/private" not in serialized

    gate_response = client.get("/runtime/evidence-integrity-gate", params={"project_id": "project-passport"})
    assert gate_response.status_code == 200
    gate = gate_response.json()
    stage_signal = next(
        signal
        for signal in gate["signals"]
        if signal["signal_id"] == "workflow_stage:agent_handoff"
    )
    assert stage_signal["status"] == "block"
    assert stage_signal["drilldown"]["source_ref"]["source_kind"] == "workflow_passport_stage"
    assert stage_signal["drilldown"]["checked_facts"]["stage_id"] == "agent_handoff"
    assert stage_signal["drilldown"]["checked_facts"]["requires_user_confirmation"] is True
    assert stage_signal["drilldown"]["blocks_claims"] is True
    assert any(
        str(ref.get("ref_id", "")).startswith("approval_gate:")
        for ref in stage_signal["drilldown"]["evidence_refs"]
    )
    export_signal = next(
        signal
        for signal in gate["signals"]
        if signal["signal_id"] == "workflow_stage:export"
    )
    assert export_signal["status"] == "unresolved"
    assert export_signal["drilldown"]["checked_facts"]["preflight_receipt_count"] == 1
    assert export_signal["drilldown"]["checked_facts"]["unresolved_count"] >= 1
    assert "workflow_passport" in export_signal["drilldown"]["checked_facts"]["projection_digest_keys"]
    assert any(
        ref.get("ref_type") == "preflight_refresh_receipt"
        for ref in export_signal["drilldown"]["replay_refs"]
    )
    serialized_gate = str(gate)
    assert "C:\\Users\\xiao\\private" not in serialized_gate
    assert "workspace_artifacts/private" not in serialized_gate


@pytest.mark.persistence_smoke
def test_runtime_evidence_integrity_gate_route_keeps_unresolved_separate(monkeypatch) -> None:
    """The integrity gate route should expose block and unresolved states distinctly."""

    runtime = WritingRuntime()
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        user_id="integrity-route-user",
        metadata={"project_id": "project-integrity-route"},
    )
    writing_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="route export",
        metadata={"project_id": "project-integrity-route", "export_artifact_id": "export-route"},
    )
    runtime.update_writing_workflow_state(
        writing_job.job_id,
        phase="export_ready",
        intake={"project_id": "project-integrity-route"},
        evidence_refs=[{"ref_id": "chunk:route"}],
        citation_bank=[{"citation_id": "cite:route"}],
        lint_report={"passed": True, "issues": []},
        export_manifest={"format": "docx", "filename": "route.docx"},
        change_log=[{"stage": "export"}],
    )
    runtime.add_job_artifact(
        writing_job.job_id,
        artifact_type=ArtifactType.METADATA,
        content={
            "kind": "route_integrity",
            "retrieval_diagnostics": {
                "locator_coverage": {
                    "schema_version": "scholar-ai-evidence-locator-coverage/v1",
                    "total_refs": 1,
                    "project_ref_count": 1,
                    "non_project_ref_count": 0,
                    "material_locator_count": 1,
                    "page_locator_count": 1,
                    "bbox_locator_count": 0,
                    "missing_locator_count": 0,
                    "page_coverage_ratio": 1.0,
                    "bbox_coverage_ratio": 0.0,
                    "coverage_state": "page_located",
                    "risk_level": "warn",
                    "sample_missing_ref_ids": [],
                    "notes": ["Page locator exists but bbox is absent."],
                },
                "qrels_status": {
                    "schema_version": "retrieval-qrels-status/v1",
                    "status": "missing",
                    "candidate_qrels_count": 0,
                    "reviewed_qrels_count": 0,
                    "canonical_qrels_count": 0,
                    "semantic_quality_claim_allowed": False,
                    "quality_claim": "no_qrels_available",
                    "notes": ["No canonical qrels."],
                },
            },
            "citation_verifications": [
                {
                    "verification_id": "verify-route",
                    "project_id": "project-integrity-route",
                    "citation_id": "cite:route",
                    "status": "needs_review",
                    "rationale": "Offline review required.",
                    "source_kind": "local",
                }
            ],
        },
        created_by="pytest",
        metadata={"project_id": "project-integrity-route"},
    )

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get(
        "/runtime/evidence-integrity-gate",
        params={"project_id": "project-integrity-route"},
    )

    assert response.status_code == 200
    gate = response.json()
    assert gate["schema_version"] == "scholar_ai_evidence_integrity_gate_v1"
    assert gate["status"] == "unresolved"
    assert gate["summary"]["unresolved_is_pass"] is False
    assert any(
        signal["category"] == "citation_verification" and signal["status"] == "unresolved"
        for signal in gate["signals"]
    )
    citation_signal = next(
        signal
        for signal in gate["signals"]
        if signal["category"] == "citation_verification" and signal["status"] == "unresolved"
    )
    assert citation_signal["drilldown"]["schema_version"] == "scholar_ai_integrity_signal_drilldown_v1"
    assert citation_signal["drilldown"]["source_ref"]["source_kind"] == "citation_verification"
    assert citation_signal["drilldown"]["checked_facts"]["citation_id"] == "cite:route"
    assert citation_signal["drilldown"]["requires_human_review"] is True
    assert any(
        signal["category"] == "retrieval_quality" and signal["status"] == "unresolved"
        for signal in gate["signals"]
    )
    qrels_signal = next(
        signal
        for signal in gate["signals"]
        if signal["category"] == "retrieval_quality" and signal["status"] == "unresolved"
    )
    assert qrels_signal["drilldown"]["checked_facts"]["quality_claim"] == "no_qrels_available"
    export_signal = next(
        signal
        for signal in gate["signals"]
        if signal["category"] == "export_readiness" and signal["status"] == "unresolved"
    )
    assert export_signal["drilldown"]["source_ref"]["source_kind"] == "export_manifest"
    assert export_signal["drilldown"]["checked_facts"]["has_evidence_rows"] is False
    assert not gate["blockers"]
    assert gate["unresolved"]

    missing_response = client.get(
        "/runtime/evidence-integrity-gate",
        params={"job_id": "job_missing"},
    )
    assert missing_response.status_code == 404


def test_runtime_behavior_eval_pack_route_exposes_read_only_canary_projection(tmp_path, monkeypatch) -> None:
    """Behavior eval route should expose deterministic red flags without persisting run records."""

    artifact_root = tmp_path / "workspace_artifacts"
    monkeypatch.setenv("LITERATURE_ASSISTANT_USER_ROOT", str(artifact_root))
    monkeypatch.setattr(runtime_router_module, "_REPO_ROOT", runtime_router_module.Path(__file__).resolve().parents[1])
    monkeypatch.setattr(
        runtime_router_module,
        "_MCP_SRC_ROOT",
        runtime_router_module.Path(__file__).resolve().parents[1] / "agent_mcp_server" / "src",
    )
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get("/runtime/behavior-eval-pack", params={"include_cases": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "scholar_ai_behavior_eval_pack_v1"
    assert payload["mode"] == "canary"
    assert payload["summary"]["case_count"] == 8
    assert payload["summary"]["observation_count"] == 8
    assert payload["summary"]["structural_status"] == "pass"
    assert payload["summary"]["behavior_status"] == "block"
    assert payload["summary"]["block_count"] == 7
    assert payload["summary"]["warn_count"] == 1
    assert len(payload["cases"]) == 8
    assert len(payload["results"]) == 8
    assert payload["provenance"]["read_only"] is True
    assert payload["provenance"]["record_written"] is False
    assert payload["run_record"] == {}
    assert not list(artifact_root.glob("**/behavior_eval_runs/*.json"))

    compact_response = client.get("/runtime/behavior-eval-pack", params={"include_cases": False})
    assert compact_response.status_code == 200
    assert compact_response.json()["cases"] == []


def test_runtime_preflight_refresh_receipt_route_reads_persisted_replay_evidence(monkeypatch) -> None:
    """Runtime route should expose persisted workflow refresh receipts."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-receipt-route"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export receipt route",
        metadata={"project_id": "project-receipt-route"},
    )
    state = runtime.update_writing_workflow_state(
        job.job_id,
        phase="export_ready",
        intake={"project_id": "project-receipt-route"},
        evidence_refs=[{"ref_id": "chunk:receipt-route", "material_id": "material-receipt-route"}],
        citation_bank=[{"citation_id": "cite:receipt-route", "ref_id": "chunk:receipt-route"}],
        lint_report={"passed": True, "issues": []},
        export_manifest={"format": "docx", "filename": "receipt-route.docx"},
        change_log=[{"stage": "export", "summary": "export manifest exists"}],
    )
    preflight = runtime.build_action_preflight(
        action_id="writing.export_project",
        required_claim_id="export_readiness",
        session_id=session.session_id,
        job_id=job.job_id,
        project_id="project-receipt-route",
        workflow_state=state,
        persist_refresh_receipt=True,
    )
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get(f"/runtime/job/{job.job_id}/preflight-refresh-receipt")

    assert response.status_code == 200
    receipt = response.json()
    assert receipt["schema_version"] == "scholar_ai_preflight_refresh_receipt_v1"
    assert receipt["receipt_id"] == preflight["refresh_receipt_id"]
    assert receipt["validation"]["preflight_schema_version"] == "scholar_ai_action_preflight_v1"
    assert receipt["replay"]["external_mutation"] is False

    missing_response = client.get(
        f"/runtime/job/{job.job_id}/preflight-refresh-receipt",
        params={"receipt_id": "preflight_refresh:missing"},
    )
    assert missing_response.status_code == 404


def test_runtime_workflow_replay_lineage_route_lists_receipt_history(monkeypatch) -> None:
    """Runtime route should expose bounded receipt lineage for retry decisions."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-lineage-route"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export lineage route",
        metadata={"project_id": "project-lineage-route"},
    )
    state = runtime.update_writing_workflow_state(
        job.job_id,
        phase="export_ready",
        intake={"project_id": "project-lineage-route"},
        evidence_refs=[{"ref_id": "chunk:lineage-route", "material_id": "material-lineage-route"}],
        citation_bank=[{"citation_id": "cite:lineage-route", "ref_id": "chunk:lineage-route"}],
        lint_report={"passed": True, "issues": []},
        export_manifest={"format": "docx", "filename": "lineage-route.docx"},
        change_log=[{"stage": "export", "summary": "export manifest exists"}],
    )
    preflight = runtime.build_action_preflight(
        action_id="writing.export_project",
        required_claim_id="export_readiness",
        session_id=session.session_id,
        job_id=job.job_id,
        project_id="project-lineage-route",
        workflow_state=state,
        persist_refresh_receipt=True,
    )
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get(
        f"/runtime/job/{job.job_id}/workflow-replay-lineage",
        params={"limit": 5},
    )

    assert response.status_code == 200
    lineage = response.json()
    assert lineage["schema_version"] == "scholar_ai_workflow_replay_lineage_v1"
    assert lineage["receipt_count"] == 1
    assert lineage["returned_count"] == 1
    assert lineage["latest_receipt_id"] == preflight["refresh_receipt_id"]
    assert lineage["items"][0]["receipt_id"] == preflight["refresh_receipt_id"]
    assert lineage["summary"]["lineage_is_read_only"] is True
    assert any(probe["endpoint"].endswith("/workflow-replay-lineage") for probe in lineage["resume_probes"])

    invalid_response = client.get(
        f"/runtime/job/{job.job_id}/workflow-replay-lineage",
        params={"limit": 0},
    )
    assert invalid_response.status_code == 422

    missing_response = client.get("/runtime/job/job_missing/workflow-replay-lineage")
    assert missing_response.status_code == 404


def test_runtime_workflow_replay_index_route_discovers_receipts_without_job_id(monkeypatch) -> None:
    """Runtime route should expose bounded project/session replay discovery."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-index-route"},
    )
    export_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export index route",
        metadata={"project_id": "project-index-route"},
    )
    state = runtime.update_writing_workflow_state(
        export_job.job_id,
        phase="export_ready",
        intake={"project_id": "project-index-route"},
        evidence_refs=[{"ref_id": "chunk:index-route", "material_id": "material-index-route"}],
        citation_bank=[{"citation_id": "cite:index-route", "ref_id": "chunk:index-route"}],
        lint_report={"passed": True, "issues": []},
        export_manifest={"format": "docx", "filename": "index-route.docx"},
        change_log=[{"stage": "export", "summary": "export manifest exists"}],
    )
    preflight = runtime.build_action_preflight(
        action_id="writing.export_project",
        required_claim_id="export_readiness",
        session_id=session.session_id,
        job_id=export_job.job_id,
        project_id="project-index-route",
        workflow_state=state,
        persist_refresh_receipt=True,
    )
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get(
        "/runtime/workflow-replay-index",
        params={"project_id": "project-index-route", "limit": 5},
    )

    assert response.status_code == 200
    replay_index = response.json()
    assert replay_index["schema_version"] == "scholar_ai_workflow_replay_index_v1"
    assert replay_index["scope"]["project_id"] == "project-index-route"
    assert replay_index["matching_job_count"] == 1
    assert replay_index["returned_count"] == 1
    assert replay_index["total_receipts_seen"] == 1
    assert replay_index["items"][0]["job_id"] == export_job.job_id
    assert replay_index["items"][0]["latest_receipt_id"] == preflight["refresh_receipt_id"]
    assert replay_index["summary"]["requires_exact_job_id"] is False
    assert replay_index["summary"]["index_is_read_only"] is True
    assert any(probe["endpoint"] == f"/runtime/job/{export_job.job_id}/workflow-replay-lineage" for probe in replay_index["items"][0]["resume_probes"])

    status_response = client.get(
        "/runtime/workflow-replay-index",
        params={"session_id": session.session_id, "status": replay_index["items"][0]["latest_status"], "limit": 5},
    )
    assert status_response.status_code == 200
    assert status_response.json()["matching_job_count"] == 1

    invalid_response = client.get("/runtime/workflow-replay-index", params={"limit": 0})
    assert invalid_response.status_code == 422

    missing_response = client.get("/runtime/workflow-replay-index", params={"session_id": "session_missing"})
    assert missing_response.status_code == 404


def test_runtime_research_action_lifecycle_route_projects_actions_effects_and_gates(monkeypatch) -> None:
    """Research action lifecycle should expose read-only action/effect facts."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-action-life", "title": "Action lifecycle project"},
    )
    agent_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="private agent prompt should not leak",
        metadata={
            "agent_bridge": True,
            "agent_request_id": "agentreq-action-life",
            "project_id": "project-action-life",
            "material_id": "material-action-life",
            "output_targets": {"wiki_candidate": True, "graph_candidate": True},
            "wiki_refs": [
                {
                    "ref_id": "wiki:candidate/action-life",
                    "title": "Do not expose raw text",
                    "content": "private wiki draft",
                }
            ],
            "graph_patch_refs": [
                {
                    "ref_id": "graph_patch:action-life",
                    "node_count": 2,
                    "raw_content": "private graph payload",
                }
            ],
            "agent_result_consumers": {
                "wiki": {
                    "status": "candidate_created",
                    "wiki_slug": "action-life",
                    "path": "C:\\Users\\xiao\\private\\wiki.md",
                },
                "graph": {
                    "status": "candidate_created",
                    "graph_patch_ref_count": 1,
                    "raw_content": "private graph body",
                },
            },
            "raw_content": "private agent result",
            "api_key": "sk-route-secret",
        },
    )
    runtime.add_job_artifact(
        agent_job.job_id,
        artifact_type=ArtifactType.METADATA,
        content={
            "kind": "agent_result",
            "status": "candidate_created",
            "content": "private artifact content",
        },
        created_by="pytest",
        metadata={
            "kind": "agent_result",
            "schema_version": "scholar_ai_agent_result_v1",
            "project_id": "project-action-life",
            "agent_request_id": "agentreq-action-life",
            "path": "C:\\Users\\xiao\\private\\agent-result.json",
        },
    )
    runtime.request_approval(
        job_id=agent_job.job_id,
        session_id=session.session_id,
        reason="Confirm wiki and graph candidates before any write.",
        metadata={"project_id": "project-action-life", "path": "C:\\Users\\xiao\\private\\approval.txt"},
    )
    runtime.build_action_preflight(
        action_id="agent.handoff_card",
        required_claim_id="handoff_readiness",
        session_id=session.session_id,
        job_id=agent_job.job_id,
        project_id="project-action-life",
        require_ready=False,
        persist_refresh_receipt=True,
    )
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get(
        "/runtime/research-action-lifecycle",
        params={"project_id": "project-action-life", "limit": 10},
    )

    assert response.status_code == 200
    lifecycle = response.json()
    assert lifecycle["schema_version"] == "scholar_ai_research_action_lifecycle_v1"
    assert lifecycle["scope"]["project_id"] == "project-action-life"
    assert lifecycle["summary"]["read_only"] is True
    assert lifecycle["summary"]["external_mutation"] is False
    assert lifecycle["summary"]["source_material_mutation"] is False
    assert lifecycle["summary"]["requires_user_confirmation"] is True
    action_by_type = {item["action_type"]: item for item in lifecycle["actions"]}
    assert {"wiki_candidate", "graph_patch", "agent_handoff", "approval_gate"} <= set(action_by_type)
    wiki_action = action_by_type["wiki_candidate"]
    assert wiki_action["action_id"] == "agent.wiki_candidate"
    assert wiki_action["status"] == "pending_approval"
    assert wiki_action["approval"]["requires_user_confirmation"] is True
    assert wiki_action["preflight"]["present"] is True
    assert wiki_action["preflight"]["receipt_refs"][0]["ref_type"] == "preflight_refresh_receipt"
    assert wiki_action["effect_summary"]["external_mutation"] is False
    assert wiki_action["effect_summary"]["source_material_mutation"] is False
    assert wiki_action["recovery"]["read_only"] is True
    assert any(probe["endpoint"] == "/runtime/research-action-lifecycle" for probe in wiki_action["recovery"]["resume_probes"])
    assert any(ref["object_type"] == "agent_request" for ref in wiki_action["object_refs"])
    assert any(ref["ref_type"] == "runtime_artifact" for ref in wiki_action["effect_refs"])
    assert any(ref["ref_type"] == "wiki_ref" for ref in wiki_action["effect_refs"])
    assert any(ref["ref_type"] == "graph_patch_ref" for ref in action_by_type["graph_patch"]["effect_refs"])
    assert action_by_type["approval_gate"]["effect_summary"]["requires_user_confirmation"] is True
    assert any("Do not execute approvals" in text for text in wiki_action["forbidden_actions"])
    assert any("Pending user confirmation" in message for message in lifecycle["blockers"])
    assert any(probe["endpoint"] == "/runtime/evidence-integrity-gate" for probe in lifecycle["resume_probes"])
    serialized = str(lifecycle)
    assert "sk-route-secret" not in serialized
    assert "private agent prompt should not leak" not in serialized
    assert "private agent result" not in serialized
    assert "private wiki draft" not in serialized
    assert "private artifact content" not in serialized
    assert "C:\\Users\\xiao\\private" not in serialized

    job_response = client.get(
        "/runtime/research-action-lifecycle",
        params={"job_id": agent_job.job_id, "limit": 5},
    )
    assert job_response.status_code == 200
    assert job_response.json()["summary"]["matching_job_count"] == 1

    invalid_response = client.get("/runtime/research-action-lifecycle", params={"limit": 0})
    assert invalid_response.status_code == 422

    missing_response = client.get("/runtime/research-action-lifecycle", params={"job_id": "job_missing"})
    assert missing_response.status_code == 404


def test_runtime_lifecycle_refs_crosslink_passport_gate_boundary_and_handoff(monkeypatch) -> None:
    """Lifecycle refs should remain recoverable through read-only runtime projections."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-lifecycle-crosslinks"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="handoff lifecycle crosslinks",
        metadata={
            "agent_bridge": True,
            "agent_request_id": "agentreq-lifecycle-crosslinks",
            "project_id": "project-lifecycle-crosslinks",
            "output_targets": {"wiki_candidate": True, "graph_candidate": True},
        },
    )
    runtime.request_approval(
        job_id=job.job_id,
        session_id=session.session_id,
        reason="Confirm generated candidates before any write.",
        metadata={"project_id": "project-lifecycle-crosslinks"},
    )
    runtime.build_action_preflight(
        action_id="agent.handoff_card",
        required_claim_id="handoff_readiness",
        session_id=session.session_id,
        job_id=job.job_id,
        project_id="project-lifecycle-crosslinks",
        require_ready=False,
        persist_refresh_receipt=True,
    )
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    passport_response = client.get(
        "/runtime/workflow-passport",
        params={"project_id": "project-lifecycle-crosslinks", "limit": 20},
    )
    gate_response = client.get(
        "/runtime/evidence-integrity-gate",
        params={"project_id": "project-lifecycle-crosslinks", "limit": 20},
    )
    handoff_response = client.get(f"/runtime/job/{job.job_id}/agent-handoff-card")

    assert passport_response.status_code == 200
    assert gate_response.status_code == 200
    assert handoff_response.status_code == 200
    passport = passport_response.json()
    gate = gate_response.json()
    handoff = handoff_response.json()

    agent_stage = next(stage for stage in passport["stages"] if stage["stage_id"] == "agent_handoff")
    research_action_refs = agent_stage["reproducibility"]["research_action_refs"]
    assert agent_stage["diagnostics"]["research_action_count"] >= 1
    assert any(ref["action_type"] == "wiki_candidate" for ref in research_action_refs)
    assert any(ref["probe_endpoint"] == "/runtime/research-action-lifecycle" for ref in research_action_refs)
    assert all(ref["read_only"] is True for ref in research_action_refs)

    assert gate["summary"]["research_action_count"] >= 1
    assert any(ref["action_type"] == "agent_handoff" for ref in gate["summary"]["research_action_refs"])
    assert "runtime.research_action_lifecycle_refs" in gate["provenance"]["derived_from"]
    assert gate["provenance"]["research_action_lifecycle_schema_version"] == (
        "scholar_ai_research_action_lifecycle_v1"
    )

    boundary = gate["blocking_action_boundary"]
    assert any(
        probe["endpoint"] == "/runtime/research-action-lifecycle" and probe["read_only"] is True
        for probe in boundary["local_read_only_probes"]
    )

    recovery = handoff["action_lifecycle_recovery"]
    assert recovery["schema_version"] == "scholar_ai_handoff_action_lifecycle_recovery_v1"
    assert recovery["read_only"] is True
    assert recovery["pending_confirmation_count"] >= 1
    assert any(ref["action_type"] == "agent_handoff" for ref in recovery["action_refs"])
    assert recovery["resume_probes"][0]["endpoint"] == "/runtime/research-action-lifecycle"
    assert "runtime.research_action_lifecycle_refs" in handoff["provenance"]["derived_from"]


def test_runtime_agent_handoff_card_route_exposes_recovery_drilldowns(monkeypatch) -> None:
    """Agent handoff cards should carry blocking-boundary drilldowns through REST."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-handoff-drilldown"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="handoff route drilldown",
        metadata={
            "agent_bridge": True,
            "agent_request_id": "agentreq-handoff-drilldown",
            "project_id": "project-handoff-drilldown",
        },
    )
    approval = runtime.request_approval(
        job_id=job.job_id,
        session_id=session.session_id,
        reason="Confirm handoff route drilldown.",
        metadata={"project_id": "project-handoff-drilldown"},
    )
    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    response = client.get(f"/runtime/job/{job.job_id}/agent-handoff-card")

    assert response.status_code == 200
    card = response.json()
    assert card["schema_version"] == "scholar_ai_agent_handoff_card_v1"
    assert card["action_preflight"]["action_id"] == "agent.handoff_card"
    boundary = card["action_preflight"]["blocking_action_boundary"]
    assert boundary["schema_version"] == "scholar_ai_blocking_action_boundary_v1"
    assert boundary["status"] == "blocked"
    assert boundary["can_proceed"] is False
    assert boundary["recovery_drilldowns"]
    handoff_drilldown = next(
        item
        for item in boundary["recovery_drilldowns"]
        if item["signal_id"] == "workflow_stage:agent_handoff"
    )
    assert handoff_drilldown["linked_stage_id"] == "agent_handoff"
    assert handoff_drilldown["checked_facts"]["requires_user_confirmation"] is True
    assert any(
        ref.get("ref_type") == "workflow_passport_stage"
        for ref in handoff_drilldown["recovery_refs"]
    )
    assert any(
        ref.get("ref_type") == "research_object" and ref.get("ref_id") == f"approval_gate:{approval.approval_id}"
        for ref in handoff_drilldown["evidence_refs"]
    )
    assert any(
        probe.get("endpoint") == "/runtime/evidence-integrity-gate" and probe.get("read_only") is True
        for probe in handoff_drilldown["local_read_only_probes"]
    )
    assert handoff_drilldown["raw_path_exposed"] is False
    assert card["replay_recovery"]["read_only"] is True

    missing_response = client.get("/runtime/job/job_missing/agent-handoff-card")
    assert missing_response.status_code == 404


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


@pytest.mark.persistence_smoke
def test_runtime_figure_load_job_returns_pixel_only_artifact(monkeypatch) -> None:
    """Figure-load jobs should persist only chunk-backed pixel candidates."""
    runtime = WritingRuntime()
    session = runtime.create_session(mode=SessionMode.PROMPT)
    chunk_store = {
        "material-a": [
            {
                "chunk_id": "material-a_chunk_0",
                "material_id": "material-a",
                "title": "paper-a.pdf",
                "chunk_index": 0,
                "content": "Figure 1: chunk-produced pixel figure.",
                "raw_content": "Figure 1: chunk-produced pixel figure.",
                "page": 2,
                "asset_path": "figures/f1/f1_crop.png",
            },
            {
                "chunk_id": "material-a_chunk_1",
                "material_id": "material-a",
                "title": "paper-a.pdf",
                "chunk_index": 1,
                "content": "Figure 2: text-only mention.",
                "raw_content": "Figure 2: text-only mention.",
                "page": 3,
            },
        ],
    }

    monkeypatch.setattr(runtime_router_module, "get_runtime", lambda: runtime)
    monkeypatch.setattr(resources_router_module, "_ensure_upload_project", lambda project_id: _FakeFigureStore())
    monkeypatch.setattr(resources_router_module, "_ensure_project_chunks", lambda project_id: chunk_store)

    app = FastAPI()
    app.include_router(runtime_router_module.router)
    client = TestClient(app)

    create_response = client.post(
        "/runtime/job",
        json={
            "session_id": session.session_id,
            "kind": "figure_load",
            "input_text": "load figures",
            "metadata": {
                "project_id": "project-runtime-figures",
                "route": "/writing/figures",
            },
        },
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["job_id"]

    start_response = client.post(f"/runtime/job/{job_id}/start")
    assert start_response.status_code == 200

    terminal = _wait_for_job_terminal(client, job_id)
    assert terminal["status"] == "completed"
    artifacts_response = client.get(f"/runtime/job/{job_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    assert len(artifacts) == 1
    content = artifacts[0]["content"]
    assert content["kind"] == "figure_load"
    assert content["project_id"] == "project-runtime-figures"
    assert [asset["asset_path"] for asset in content["assets"]] == ["figures/existing.png"]
    assert [candidate["label"] for candidate in content["candidates"]] == ["图 1"]
    assert content["candidates"][0]["asset_path"] == "figures/f1/f1_crop.png"
    assert content["render_pdf_fallback"] is False
