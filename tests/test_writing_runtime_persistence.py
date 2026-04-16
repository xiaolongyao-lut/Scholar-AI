# -*- coding: utf-8 -*-
"""Persistence regression tests for the writing runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_protocols import ArtifactType, EventType, JobKind, JobStatus, SessionMode
from writing_runtime import WritingRuntime


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
