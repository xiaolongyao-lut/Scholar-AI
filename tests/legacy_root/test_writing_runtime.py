# -*- coding: utf-8 -*-
"""
Test suite for WritingRuntime (Phase 2)

Tests core runtime functionality:
- Session creation and retrieval
- Job creation, status tracking, and lifecycle transitions
- Event emission
- Artifact storage
- Approval gate workflow
- Backward compatibility with legacy action execution
"""

import asyncio
import pytest

from writing_runtime import WritingRuntime
from harness_protocols import (
    SessionMode,
    JobKind,
    JobStatus,
    EventType,
    ArtifactType,
    ApprovalStatus,
)
from skills.runtime import SkillRunResult, ExecutionStatus

pytestmark = pytest.mark.persistence_full


class TestWritingRuntimeSessions:
    """Test session management."""

    def test_create_session(self):
        """Test creating a new session."""
        runtime = WritingRuntime()
        session = runtime.create_session(
            mode=SessionMode.SKILL,
            user_id="user_123",
            tags=["test"],
        )

        assert session.session_id.startswith("session_")
        assert session.user_id == "user_123"
        assert session.mode == SessionMode.SKILL
        assert "test" in session.tags

    def test_get_session(self):
        """Test retrieving a session."""
        runtime = WritingRuntime()
        created = runtime.create_session(mode=SessionMode.PROMPT)
        retrieved = runtime.get_session(created.session_id)

        assert retrieved is not None
        assert retrieved.session_id == created.session_id
        assert retrieved.mode == SessionMode.PROMPT

    def test_list_sessions(self):
        """Test listing sessions."""
        runtime = WritingRuntime()
        _session1 = runtime.create_session(mode=SessionMode.PROMPT, user_id="user_1")
        _session2 = runtime.create_session(mode=SessionMode.SKILL, user_id="user_2")
        _session3 = runtime.create_session(mode=SessionMode.HYBRID, user_id="user_1")

        all_sessions = runtime.list_sessions()
        assert len(all_sessions) == 3

        user1_sessions = runtime.list_sessions(user_id="user_1")
        assert len(user1_sessions) == 2
        assert all(s.user_id == "user_1" for s in user1_sessions)


class TestWritingRuntimeJobs:
    """Test job management."""

    def test_create_job(self):
        """Test creating a job."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.SKILL_ACTION,
            input_text="Test input",
            skill_id="skill_123",
        )

        assert job.job_id.startswith("job_")
        assert job.session_id == session.session_id
        assert job.kind == JobKind.SKILL_ACTION
        assert job.status == JobStatus.CREATED

    def test_create_job_invalid_session(self):
        """Test creating a job with invalid session."""
        runtime = WritingRuntime()
        
        with pytest.raises(ValueError, match="Session .* not found"):
            runtime.create_job(
                session_id="invalid_session",
                kind=JobKind.PROMPT_ACTION,
            )

    def test_get_job(self):
        """Test retrieving a job."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        created_job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        retrieved_job = runtime.get_job(created_job.job_id)
        assert retrieved_job is not None
        assert retrieved_job.job_id == created_job.job_id

    def test_list_jobs(self):
        """Test listing jobs in a session."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        
        _job1 = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )
        _job2 = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.SKILL_ACTION,
        )

        jobs = runtime.list_jobs(session.session_id)
        assert len(jobs) == 2

    def test_query_job_status(self):
        """Test querying job status."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        status = runtime.query_job_status(job.job_id)
        assert status["job_id"] == job.job_id
        assert status["status"] == JobStatus.CREATED.value
        assert status["is_paused"] is False
        assert status["is_cancelled"] is False


class TestWritingRuntimeJobLifecycle:
    """Test job lifecycle transitions."""

    @pytest.mark.asyncio
    async def test_start_job(self):
        """Test starting a job."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        started_job = await runtime.start_job(job.job_id)
        assert started_job.status == JobStatus.STARTED
        assert started_job.started_at is not None

    @pytest.mark.asyncio
    async def test_pause_resume_job(self):
        """Test pausing and resuming a job."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        await runtime.start_job(job.job_id)
        paused = await runtime.pause_job(job.job_id)
        assert paused.status == JobStatus.PAUSED

        resumed = await runtime.resume_job(job.job_id)
        assert resumed.status == JobStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_cancel_job(self):
        """Test cancelling a job."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        await runtime.start_job(job.job_id)
        cancelled = await runtime.cancel_job(job.job_id)
        assert cancelled.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_complete_job(self):
        """Test completing a job."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        await runtime.start_job(job.job_id)
        completed = await runtime.complete_job(job.job_id, result="Test result")
        assert completed.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_fail_job(self):
        """Test failing a job."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        await runtime.start_job(job.job_id)
        failed = await runtime.fail_job(job.job_id, "Test error")
        assert failed.status == JobStatus.FAILED
        assert failed.error == "Test error"

    @pytest.mark.asyncio
    async def test_start_job_with_skill_result_executor_completes_job(self):
        """Test that a skill result returned from the executor finalizes the job."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.SKILL_ACTION,
            input_text="Rewrite this paragraph",
            skill_id="skill_rewrite",
        )

        async def executor(executing_job):
            return SkillRunResult(
                job_id=f"external_{executing_job.job_id}",
                skill_id="skill_rewrite",
                status=ExecutionStatus.SUCCESS,
                input_text=executing_job.input_text,
                output_text="Rewritten paragraph",
                execution_time_ms=17,
                warnings=["all good"],
            )

        final_job = await runtime.start_job(job.job_id, executor=executor)

        assert final_job.status == JobStatus.COMPLETED
        assert final_job.completed_at is not None

        artifacts = runtime.get_job_artifacts(job.job_id)
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == ArtifactType.TRANSFORMED_TEXT
        assert artifacts[0].content["job_id"] == job.job_id
        assert artifacts[0].content["output_text"] == "Rewritten paragraph"
        assert artifacts[0].metadata["source_skill_job_id"].startswith("external_")

        events = runtime.get_job_events(job.job_id)
        assert [event.event_type for event in events] == [
            EventType.JOB_CREATED,
            EventType.JOB_STARTED,
            EventType.JOB_COMPLETED,
        ]

    @pytest.mark.asyncio
    async def test_start_job_with_failed_skill_result_executor_marks_failed(self):
        """Test that a failed skill result returned from the executor marks the job failed."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.SKILL_ACTION,
            input_text="Rewrite this paragraph",
            skill_id="skill_rewrite",
        )

        async def executor(executing_job):
            return SkillRunResult(
                job_id=f"external_{executing_job.job_id}",
                skill_id="skill_rewrite",
                status=ExecutionStatus.FAILED,
                input_text=executing_job.input_text,
                output_text="",
                warnings=["boom"],
            )

        final_job = await runtime.start_job(job.job_id, executor=executor)

        assert final_job.status == JobStatus.FAILED
        assert final_job.error == "boom"

        artifacts = runtime.get_job_artifacts(job.job_id)
        assert len(artifacts) == 1
        assert artifacts[0].artifact_type == ArtifactType.AUDIT_RECORD
        assert artifacts[0].content["job_id"] == job.job_id
        assert artifacts[0].content["status"] == ExecutionStatus.FAILED.value

        events = runtime.get_job_events(job.job_id)
        assert [event.event_type for event in events] == [
            EventType.JOB_CREATED,
            EventType.JOB_STARTED,
            EventType.JOB_FAILED,
        ]


class TestWritingRuntimeEvents:
    """Test event management."""

    def test_job_creation_emits_event(self):
        """Test that job creation emits an event."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        events = runtime.get_job_events(job.job_id)
        assert len(events) >= 1
        assert events[0].event_type == EventType.JOB_CREATED

    @pytest.mark.asyncio
    async def test_job_lifecycle_events(self):
        """Test that job transitions emit events."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        await runtime.start_job(job.job_id)
        await runtime.complete_job(job.job_id)

        events = runtime.get_job_events(job.job_id)
        event_types = [e.event_type for e in events]
        
        assert EventType.JOB_CREATED in event_types
        assert EventType.JOB_STARTED in event_types
        assert EventType.JOB_COMPLETED in event_types

    @pytest.mark.persistence_smoke
    def test_get_job_events_supports_cursor_and_limit(self):
        """Test incremental event polling semantics and stable sort order."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        asyncio.run(runtime.start_job(job.job_id))
        asyncio.run(runtime.complete_job(job.job_id, result="done"))

        ordered_events = runtime.get_job_events(job.job_id)
        assert [event.event_type for event in ordered_events] == [
            EventType.JOB_CREATED,
            EventType.JOB_STARTED,
            EventType.JOB_COMPLETED,
        ]

        cursor_events = runtime.get_job_events(
            job.job_id,
            since_timestamp=ordered_events[1].timestamp,
            after_event_id=ordered_events[1].event_id,
        )
        assert [event.event_id for event in cursor_events] == [ordered_events[2].event_id]

        limited_events = runtime.get_job_events(job.job_id, limit=1)
        assert [event.event_id for event in limited_events] == [ordered_events[0].event_id]

    def test_event_subscription(self):
        """Test event subscription."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        
        received_events = []

        def on_event(event):
            received_events.append(event)

        runtime.subscribe_to_events(session.session_id, on_event)
        
        _job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        assert len(received_events) >= 1


class TestWritingRuntimeArtifacts:
    """Test artifact management."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_artifacts(self):
        """Test storing and retrieving artifacts."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        result_text = "Transformed output"
        await runtime.complete_job(job.job_id, result=result_text)

        artifacts = runtime.get_job_artifacts(job.job_id)
        assert len(artifacts) >= 1
        assert artifacts[0].artifact_type == ArtifactType.TRANSFORMED_TEXT


class TestWritingRuntimeApprovals:
    """Test approval gate workflow."""

    @pytest.mark.asyncio
    async def test_request_and_grant_approval(self):
        """Test requesting and granting approval."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.APPROVAL,
        )

        approval = runtime.request_approval(
            job_id=job.job_id,
            session_id=session.session_id,
            reason="Review requested",
        )

        assert approval.status == ApprovalStatus.PENDING

        granted = await runtime.grant_approval(approval.approval_id, response_by="user")
        assert granted.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_request_and_reject_approval(self):
        """Test requesting and rejecting approval."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.APPROVAL,
        )

        approval = runtime.request_approval(
            job_id=job.job_id,
            session_id=session.session_id,
            reason="Review requested",
        )

        rejected = await runtime.reject_approval(approval.approval_id, response_by="user")
        assert rejected.status == ApprovalStatus.REJECTED


class TestWritingRuntimeCompatibility:
    """Test backward compatibility with legacy action execution."""

    @pytest.mark.asyncio
    async def test_execute_action_compatibility(self):
        """Test executing a legacy action through the runtime."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.PROMPT)

        async def dummy_executor(_job):
            """Dummy executor for testing."""
            return None

        result = await runtime.execute_action(
            session_id=session.session_id,
            action_id="test_action",
            input_text="Test input",
            scope="section",
            executor=dummy_executor,
        )

        assert result["status"] == "succeeded"
        assert result["job_id"].startswith("job_")
        assert result["action_id"] == "test_action"


class TestWritingRuntimeStateExport:
    """Test state export for persistence."""

    def test_export_state(self):
        """Test exporting runtime state."""
        runtime = WritingRuntime()
        session = runtime.create_session(mode=SessionMode.SKILL)
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
        )

        state = runtime.export_state()
        
        assert "sessions" in state
        assert "jobs" in state
        assert "events" in state
        assert "artifacts" in state
        
        assert session.session_id in state["sessions"]
        assert job.job_id in state["jobs"]


# Integration tests
class TestWritingRuntimeIntegration:
    """Integration tests for complete workflows."""

    @pytest.mark.asyncio
    async def test_complete_workflow(self):
        """Test a complete writing workflow."""
        runtime = WritingRuntime()
        
        # Create session
        session = runtime.create_session(
            mode=SessionMode.SKILL,
            user_id="user_test",
            tags=["integration"],
        )

        # Create job
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.SKILL_ACTION,
            input_text="Rewrite this text",
            skill_id="skill_rewrite",
        )

        # Start job
        await runtime.start_job(job.job_id)

        # Simulate work
        await asyncio.sleep(0.01)

        # Complete with result
        await runtime.complete_job(job.job_id, result="Rewritten text")

        # Verify final state
        final_job = runtime.get_job(job.job_id)
        assert final_job.status == JobStatus.COMPLETED

        events = runtime.get_job_events(job.job_id)
        assert len(events) >= 3

        artifacts = runtime.get_job_artifacts(job.job_id)
        assert len(artifacts) >= 1


@pytest.mark.persistence_smoke
def test_export_state_import_state_round_trip() -> None:
    """Test that state exported and reimported preserves integrity."""
    runtime = WritingRuntime()
    
    session = runtime.create_session(
        mode=SessionMode.SKILL,
        user_id="round_trip_user",
        tags=["round-trip"],
    )
    
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="Round trip test",
        action_id="action_round_trip",
    )
    
    asyncio.run(runtime.start_job(job.job_id))
    asyncio.run(runtime.complete_job(job.job_id, result="Round trip result"))
    
    exported_state = runtime.export_state()
    
    assert "sessions" in exported_state
    assert "jobs" in exported_state
    assert "events" in exported_state
    assert "artifacts" in exported_state
    
    assert session.session_id in exported_state["sessions"]
    assert job.job_id in exported_state["jobs"]
    
    exported_session_data = exported_state["sessions"][session.session_id]
    assert exported_session_data["user_id"] == "round_trip_user"
    assert "round-trip" in exported_session_data["tags"]
    
    exported_job_data = exported_state["jobs"][job.job_id]
    assert exported_job_data["session_id"] == session.session_id
    assert exported_job_data["status"] == JobStatus.COMPLETED.value

    restored_runtime = WritingRuntime()
    restored_runtime.import_state(exported_state)

    restored_session = restored_runtime.get_session(session.session_id)
    assert restored_session is not None
    assert restored_session.user_id == session.user_id
    assert restored_session.tags == session.tags

    restored_job = restored_runtime.get_job(job.job_id)
    assert restored_job is not None
    assert restored_job.session_id == session.session_id
    assert restored_job.status == JobStatus.COMPLETED

    restored_events = restored_runtime.get_job_events(job.job_id)
    assert [event.event_type for event in restored_events] == [
        EventType.JOB_CREATED,
        EventType.JOB_STARTED,
        EventType.JOB_COMPLETED,
    ]

    restored_artifacts = restored_runtime.get_job_artifacts(job.job_id)
    assert len(restored_artifacts) == 1
    assert restored_artifacts[0].artifact_type == ArtifactType.TRANSFORMED_TEXT
    assert restored_artifacts[0].content == "Round trip result"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
