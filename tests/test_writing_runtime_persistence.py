# -*- coding: utf-8 -*-
"""Persistence regression tests for the writing runtime."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from harness_protocols import ArtifactType, EventType, JobKind, JobStatus, SessionMode
from writing_runtime import WritingRuntime

pytestmark = pytest.mark.persistence_full

@pytest.mark.persistence_smoke
@pytest.mark.asyncio
async def test_runtime_persists_sessions_jobs_events_and_artifacts_across_instances(tmp_path: Path) -> None:
    """SQLite-backed runtime state should survive recreation of the runtime object."""
    db_path = tmp_path / "writing_runtime_state.sqlite3"

    first_runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = first_runtime.create_session(
        mode=SessionMode.SKILL,
        user_id="runtime-user",
        tags=["sqlite"],
    )
    job = first_runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="Persist this job",
        action_id="action-1",
    )

    await first_runtime.start_job(job.job_id)
    await first_runtime.complete_job(job.job_id, result="Persisted result")
    approval = first_runtime.request_approval(
        job_id=job.job_id,
        session_id=session.session_id,
        reason="Manual review",
    )

    second_runtime = WritingRuntime(database_path=db_path, autosave=True)
    loaded_session = second_runtime.get_session(session.session_id)
    loaded_job = second_runtime.get_job(job.job_id)
    loaded_events = second_runtime.get_job_events(job.job_id)
    loaded_artifacts = second_runtime.get_job_artifacts(job.job_id)
    loaded_approval = second_runtime.get_approval_request(approval.approval_id)

    assert loaded_session is not None
    assert loaded_session.session_id == session.session_id
    assert loaded_session.user_id == "runtime-user"

    assert loaded_job is not None
    assert loaded_job.job_id == job.job_id
    assert loaded_job.status == JobStatus.COMPLETED

    assert [event.event_type for event in loaded_events] == [
        EventType.JOB_CREATED,
        EventType.JOB_STARTED,
        EventType.JOB_COMPLETED,
        EventType.APPROVAL_REQUIRED,
    ]

    assert loaded_artifacts
    assert loaded_artifacts[0].artifact_type == ArtifactType.TRANSFORMED_TEXT
    assert loaded_artifacts[0].content == "Persisted result"

    assert loaded_approval is not None
    assert loaded_approval.approval_id == approval.approval_id
    assert loaded_approval.reason == "Manual review"
    assert loaded_approval.status.value == "pending"


def _workspace_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace_root = tmp_path / "workspace"
    entry_cwd = workspace_root / "notes"
    entry_cwd.mkdir(parents=True)
    db_path = workspace_root / ".modular" / "sessions" / "index.sqlite3"
    return workspace_root, entry_cwd, db_path


def _workspace_metadata(workspace_root: Path, entry_cwd: Path) -> dict[str, str]:
    normalized_root = str(workspace_root.resolve())
    return {
        "workspace_root": normalized_root,
        "entry_cwd": str(entry_cwd.resolve()),
        "title": "Persistent workspace session",
        "workspace_key": sha256(normalized_root.encode("utf-8")).hexdigest(),
    }


@pytest.mark.asyncio
async def test_runtime_resume_restores_workspace_bound_session_timeline_and_checkpoints(tmp_path: Path) -> None:
    """A persisted workspace session should resume from the last active transcript head."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    first_runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = first_runtime.create_session(
        mode=SessionMode.SKILL,
        user_id="workspace-user",
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )
    first_job = first_runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="First persisted run",
        skill_id="skill-one",
    )
    await first_runtime.start_job(first_job.job_id)
    await first_runtime.complete_job(first_job.job_id, result="first-result")

    transcript_path = workspace_root / ".modular" / "sessions" / "transcripts" / f"{session.session_id}.jsonl"
    assert transcript_path.exists(), "expected append-only transcript file to be created"

    second_runtime = WritingRuntime(database_path=db_path, autosave=True)

    current_session = second_runtime.get_current_session(workspace_root=str(workspace_root))
    assert current_session is not None
    assert current_session.session_id == session.session_id
    assert current_session.metadata["workspace_key"] == sha256(str(workspace_root.resolve()).encode("utf-8")).hexdigest()

    resumed = second_runtime.resume_session(session.session_id)
    assert resumed["session"]["session_id"] == session.session_id
    assert resumed["head_event_id"]
    assert resumed["head_checkpoint_id"]

    timeline_page = second_runtime.get_session_timeline(session.session_id, limit=3)
    assert [item["event_kind"] for item in timeline_page["items"][:2]] == [
        "session_created",
        "checkpoint_created",
    ]
    assert timeline_page["next_cursor"] is not None

    remaining_page = second_runtime.get_session_timeline(
        session.session_id,
        after_event_id=timeline_page["next_cursor"],
        limit=20,
    )
    assert any(item["event_kind"] == "job_completed" for item in remaining_page["items"])

    checkpoints = second_runtime.list_checkpoints(session.session_id)
    assert len(checkpoints) >= 2
    assert checkpoints[-1]["checkpoint_id"] == resumed["head_checkpoint_id"]


@pytest.mark.asyncio
async def test_runtime_rewind_and_fork_preserve_append_only_parent_history(tmp_path: Path) -> None:
    """Rewind should move the active head back, and fork should branch without mutating the parent."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )

    for ordinal in range(2):
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
            input_text=f"step-{ordinal}",
            action_id=f"action-{ordinal}",
        )
        await runtime.start_job(job.job_id)
        await runtime.complete_job(job.job_id, result=f"result-{ordinal}")

    checkpoints = runtime.list_checkpoints(session.session_id)
    rewind_target = checkpoints[1]

    rewind_result = runtime.rewind_session(session.session_id, rewind_target["checkpoint_id"])
    assert rewind_result["head_checkpoint_id"] == rewind_target["checkpoint_id"]

    rewound_timeline = runtime.get_session_timeline(session.session_id, limit=50)
    assert not any(
        item["payload"].get("job_id") == "action-1" or item["payload"].get("input_text") == "step-1"
        for item in rewound_timeline["items"]
    )
    assert any(item["event_kind"] == "session_rewound" for item in rewound_timeline["items"])

    fork_result = runtime.fork_session(
        session.session_id,
        rewind_target["checkpoint_id"],
        title="Forked branch",
    )
    forked_session = runtime.get_session(fork_result["session"]["session_id"])
    assert forked_session is not None
    assert forked_session.metadata["parent_session_id"] == session.session_id
    assert forked_session.metadata["forked_from_checkpoint_id"] == rewind_target["checkpoint_id"]

    forked_job = runtime.create_job(
        session_id=forked_session.session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="branch-only",
        skill_id="branch-skill",
    )
    await runtime.start_job(forked_job.job_id)
    await runtime.complete_job(forked_job.job_id, result="branch-result")

    parent_timeline = runtime.get_session_timeline(session.session_id, limit=50)
    fork_timeline = runtime.get_session_timeline(forked_session.session_id, limit=50)
    assert not any(item["payload"].get("input_text") == "branch-only" for item in parent_timeline["items"])
    assert any(item["payload"].get("input_text") == "branch-only" for item in fork_timeline["items"])


@pytest.mark.asyncio
async def test_runtime_repair_truncates_damaged_transcript_tail(tmp_path: Path) -> None:
    """Broken JSONL tails should be discarded back to the last valid transcript event."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )

    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="repair-me",
        action_id="repair-action",
    )
    await runtime.start_job(job.job_id)
    await runtime.complete_job(job.job_id, result="repair-result")

    transcript_path = workspace_root / ".modular" / "sessions" / "transcripts" / f"{session.session_id}.jsonl"
    with transcript_path.open("a", encoding="utf-8") as handle:
        handle.write('{"event_id":"broken-tail"')

    reloaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    repaired_timeline = reloaded_runtime.get_session_timeline(session.session_id, limit=50)
    assert repaired_timeline["items"]

    repaired_lines = transcript_path.read_text(encoding="utf-8").splitlines()
    assert repaired_lines
    last_payload = json.loads(repaired_lines[-1])
    assert last_payload["event_kind"] != "broken-tail"


@pytest.mark.asyncio
async def test_large_payload_spill_and_resume(tmp_path: Path) -> None:
    """Large payloads (>64KB) should spill to blob storage and rehydrate on resume."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    
    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )
    
    # Create a large payload (100KB) that should trigger spill
    large_content = "x" * (100 * 1024)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text=f"large-payload-{len(large_content)}-bytes",
        action_id="large-action",
    )
    await runtime.start_job(job.job_id)
    await runtime.complete_job(job.job_id, result=large_content)
    
    # Verify blob spill occurred
    blobs_dir = workspace_root / ".modular" / "sessions" / "blobs"
    assert blobs_dir.exists(), "blobs directory should be created for spilled payloads"
    spilled_blobs = list(blobs_dir.rglob("*.json"))
    assert len(spilled_blobs) > 0, "expected at least one spilled blob"
    
    # Resume and verify rehydration
    second_runtime = WritingRuntime(database_path=db_path, autosave=True)
    timeline = second_runtime.get_session_timeline(session.session_id, limit=50)
    
    completed_event = next(
        (item for item in timeline["items"] if item["event_kind"] == "job_completed"),
        None,
    )
    assert completed_event is not None
    
    # Verify payload is fully rehydrated (not just blob_ref placeholder)
    payload = completed_event.get("payload", {})
    if isinstance(payload, dict) and payload.get("inlined") is False:
        pytest.fail("Expected rehydrated payload, got blob_ref placeholder in timeline")


@pytest.mark.asyncio
async def test_mixed_payload_sizes_with_rehydration(tmp_path: Path) -> None:
    """Mixed small and large payloads should handle spill/rehydrate correctly."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    
    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )
    
    # Mix of small and large payloads
    payloads = [
        ("small-1", "x" * 1000),
        ("large-1", "y" * (80 * 1024)),
        ("small-2", "z" * 500),
        ("large-2", "w" * (100 * 1024)),
    ]
    
    for i, (name, content) in enumerate(payloads):
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
            input_text=f"payload-{name}",
            action_id=f"action-{i}",
        )
        await runtime.start_job(job.job_id)
        await runtime.complete_job(job.job_id, result=content)
    
    # Verify all payloads are rehydrated on resume
    second_runtime = WritingRuntime(database_path=db_path, autosave=True)
    timeline = second_runtime.get_session_timeline(session.session_id, limit=100)
    
    completed_events = [item for item in timeline["items"] if item["event_kind"] == "job_completed"]
    assert len(completed_events) == 4
    
    for event in completed_events:
        payload = event.get("payload", {})
        if isinstance(payload, dict) and payload.get("inlined") is False:
            pytest.fail(f"Event {event['event_id']} has unresolved blob_ref in timeline")


@pytest.mark.asyncio
async def test_corrupted_blob_graceful_degradation(tmp_path: Path) -> None:
    """Missing/corrupted blobs should preserve blob_ref placeholder without crashing."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    
    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )
    
    # Create and spill a large payload
    large_content = "x" * (100 * 1024)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="corruption-test",
        action_id="corrupt-action",
    )
    await runtime.start_job(job.job_id)
    await runtime.complete_job(job.job_id, result=large_content)
    
    # Corrupt the blob files
    blobs_dir = workspace_root / ".modular" / "sessions" / "blobs"
    for blob_file in blobs_dir.rglob("*.json"):
        blob_file.write_text("invalid json {{{")
    
    # Resume should not crash, just preserve blob_refs
    second_runtime = WritingRuntime(database_path=db_path, autosave=True)
    timeline = second_runtime.get_session_timeline(session.session_id, limit=50)
    
    # Should still return events, even if payloads are degraded
    assert len(timeline["items"]) > 0
    assert any(item["event_kind"] == "job_completed" for item in timeline["items"])
