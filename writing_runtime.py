# -*- coding: utf-8 -*-
"""
WritingRuntime - Long-lived backend runtime for session and job management.

Phase 2 of harness upgrade: Manages WritingSession, WritingJob, WritingEvent, and WritingArtifact.
Provides stable in-memory state management with clean interfaces for future persistence.
Maintains backward compatibility with legacy run_action flows.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from db import resolve_sqlite_path
from repositories.writing_runtime_repository import WritingRuntimeRepository
from harness_protocols import (
    WritingSession,
    WritingJob,
    WritingEvent,
    WritingArtifact,
    WritingApprovalRequest,
    SessionMode,
    JobKind,
    JobStatus,
    EventType,
    ArtifactType,
    ApprovalStatus,
)
from skills.runtime import SkillRunResult

logger = logging.getLogger("WritingRuntime")

_RUNTIME_RECOVERABLE_EXCEPTIONS = (
    AssertionError,
    AttributeError,
    BufferError,
    EOFError,
    ExceptionGroup,
    ImportError,
    IndexError,
    KeyError,
    LookupError,
    MemoryError,
    NameError,
    NotImplementedError,
    OSError,
    ReferenceError,
    RuntimeError,
    TypeError,
    ValueError,
)


def _default_runtime_db_path() -> Path:
    """Resolve the default SQLite path for the runtime singleton."""
    return resolve_sqlite_path("WRITING_RUNTIME_DB_PATH", "writing_runtime_state.sqlite3")


@dataclass
class JobExecutionContext:
    """Context for executing a job with runtime state."""
    job: WritingJob
    execution_state: dict[str, Any] = field(default_factory=dict)
    is_paused: bool = False
    is_cancelled: bool = False
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        """Initialize async events if not already set."""
        if not isinstance(self.pause_event, asyncio.Event):
            self.pause_event = asyncio.Event()
        if not isinstance(self.cancel_event, asyncio.Event):
            self.cancel_event = asyncio.Event()
        self.pause_event.set()  # Start as not paused


class WritingRuntime:
    """
    Long-lived backend runtime managing sessions, jobs, events, and artifacts.
    
    Responsibilities:
    - Manage session lifecycle and context
    - Queue, execute, pause, resume, and cancel jobs
    - Emit events for state transitions
    - Store artifacts from job execution
    - Maintain approval gates
    
    In-memory state: Clean interfaces support future persistence to database or file system.
    """

    def __init__(self, database_path: str | Path | None = None, autosave: bool = False):
        """Initialize runtime with empty state and optional SQLite persistence."""
        self._sessions: dict[str, WritingSession] = {}
        self._jobs: dict[str, WritingJob] = {}
        self._job_queue: list[str] = []  # job_ids in order
        self._job_contexts: dict[str, JobExecutionContext] = {}
        self._events: dict[str, list[WritingEvent]] = {}  # events by session_id
        self._artifacts: dict[str, list[WritingArtifact]] = {}  # artifacts by job_id
        self._approval_requests: dict[str, WritingApprovalRequest] = {}
        self._event_subscribers: dict[str, list[Callable]] = {}  # session_id -> callbacks
        self._logger = logging.getLogger(f"{__name__}.{id(self)}")
        self._memory_adapter: Any | None = None
        self._memory_adapter_resolved = False
        self._database_path = Path(database_path).resolve() if database_path is not None else None
        self._repository = None
        if self._database_path is not None:
            try:
                self._repository = WritingRuntimeRepository(self._database_path)
            except (OSError, sqlite3.Error) as exc:
                self._logger.warning("Unable to open SQLite runtime repository at %s: %s", self._database_path, exc)
        self._autosave = autosave and self._repository is not None

        if self._repository is not None and self._repository.is_healthy() and self._repository.has_data():
            self.load_from_database()

    # ==========================================================================
    # Session Management
    # ==========================================================================

    def create_session(
        self,
        mode: SessionMode,
        user_id: str | None = None,
        settings: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingSession:
        """Create a new writing session."""
        session = WritingSession.create(
            mode=mode,
            user_id=user_id,
            settings=settings,
            tags=tags,
            metadata=metadata,
        )
        self._sessions[session.session_id] = session
        self._events[session.session_id] = []
        self._logger.info("Created session %s with mode %s", session.session_id, mode.value)
        self._autosave_if_enabled()
        return session

    def get_session(self, session_id: str) -> WritingSession | None:
        """Retrieve a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(self, user_id: str | None = None) -> list[WritingSession]:
        """List all sessions, optionally filtered by user."""
        sessions = list(self._sessions.values())
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        return sessions

    # ==========================================================================
    # Job Management
    # ==========================================================================

    def create_job(
        self,
        session_id: str,
        kind: JobKind,
        input_text: str = "",
        action_id: str | None = None,
        skill_id: str | None = None,
        scope: str | None = None,
        output_mode: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingJob:
        """Create a new job in a session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        job = WritingJob.create(
            session_id=session_id,
            kind=kind,
            input_text=input_text,
            action_id=action_id,
            skill_id=skill_id,
            scope=scope,
            output_mode=output_mode,
            tags=tags,
            metadata=metadata,
        )

        self._jobs[job.job_id] = job
        self._job_queue.append(job.job_id)
        self._job_contexts[job.job_id] = JobExecutionContext(job=job)
        self._artifacts[job.job_id] = []

        # Emit job created event
        self._emit_event(
            session_id,
            WritingEvent.create(
                job_id=job.job_id,
                session_id=session_id,
                event_type=EventType.JOB_CREATED,
                data={"kind": kind.value, "action_id": action_id, "skill_id": skill_id},
            ),
        )

        self._logger.info("Created job %s in session %s", job.job_id, session_id)
        return job

    def get_job(self, job_id: str) -> WritingJob | None:
        """Retrieve a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(self, session_id: str, status: JobStatus | None = None) -> list[WritingJob]:
        """List all jobs in a session, optionally filtered by status."""
        jobs = [j for j in self._jobs.values() if j.session_id == session_id]
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs

    def query_job_status(self, job_id: str) -> dict[str, Any]:
        """Query current job status with detailed information."""
        job = self.get_job(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}

        ctx = self._job_contexts.get(job_id)
        return {
            "job_id": job_id,
            "session_id": job.session_id,
            "status": job.status.value,
            "kind": job.kind.value,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "is_paused": ctx.is_paused if ctx else False,
            "is_cancelled": ctx.is_cancelled if ctx else False,
            "error": job.error,
        }

    # ==========================================================================
    # Job Lifecycle Control
    # ==========================================================================

    async def start_job(self, job_id: str, executor: Callable[[WritingJob], Any] | None = None) -> WritingJob:
        """
        Start executing a job.
        
        If executor is provided, it will be called asynchronously.
        The executor should handle pause/resume/cancel via the context.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Transition to STARTED
        job = job.with_status(JobStatus.STARTED)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_STARTED,
            ),
        )

        self._logger.info("Started job %s", job_id)

        if executor:
            try:
                executor_result = executor(job)
                if inspect.isawaitable(executor_result):
                    executor_result = await executor_result
                await self._finalize_executor_result(job_id, executor_result)
            except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:
                self._logger.error("Executor error for job %s: %s", job_id, exc)
                await self.fail_job(job_id, str(exc))

        self._autosave_if_enabled()
        return self.get_job(job_id) or job

    async def pause_job(self, job_id: str) -> WritingJob:
        """Pause a running job."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status not in (JobStatus.STARTED, JobStatus.IN_PROGRESS):
            raise ValueError(f"Cannot pause job in status {job.status.value}")

        ctx = self._job_contexts.get(job_id)
        if ctx:
            ctx.is_paused = True
            ctx.pause_event.clear()

        job = job.with_status(JobStatus.PAUSED)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_PAUSED,
            ),
        )

        self._logger.info("Paused job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def resume_job(self, job_id: str) -> WritingJob:
        """Resume a paused job."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status != JobStatus.PAUSED:
            raise ValueError(f"Cannot resume job in status {job.status.value}")

        ctx = self._job_contexts.get(job_id)
        if ctx:
            ctx.is_paused = False
            ctx.pause_event.set()

        job = job.with_status(JobStatus.IN_PROGRESS)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_RESUMED,
            ),
        )

        self._logger.info("Resumed job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def cancel_job(self, job_id: str) -> WritingJob:
        """Cancel a job."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValueError(f"Cannot cancel job already in terminal status {job.status.value}")

        ctx = self._job_contexts.get(job_id)
        if ctx:
            ctx.is_cancelled = True
            ctx.cancel_event.set()

        job = job.with_status(JobStatus.CANCELLED)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_CANCELLED,
            ),
        )

        self._logger.info("Cancelled job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def complete_job(self, job_id: str, result: Any | None = None) -> WritingJob:
        """Mark a job as completed."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job = job.with_status(JobStatus.COMPLETED)
        self._jobs[job_id] = job

        if result:
            self._store_artifact(
                WritingArtifact.create(
                    job_id=job_id,
                    session_id=job.session_id,
                    artifact_type=ArtifactType.TRANSFORMED_TEXT,
                    content=result,
                    created_by="system",
                )
            )

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_COMPLETED,
                data={"result_artifact_count": len(self._artifacts.get(job_id, []))},
            ),
        )

        self._sync_job_to_memory_if_enabled(job_id)
        self._logger.info("Completed job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def fail_job(self, job_id: str, error: str) -> WritingJob:
        """Mark a job as failed with error message."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job = job.with_error(error)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_FAILED,
                data={"error": error},
            ),
        )

        self._sync_job_to_memory_if_enabled(job_id)
        self._logger.info("Failed job %s: %s", job_id, error)
        self._autosave_if_enabled()
        return job

    def _normalize_skill_run_result(self, job: WritingJob, result: SkillRunResult) -> SkillRunResult:
        """Rewrite skill results so the runtime job ID stays authoritative."""
        if result.job_id == job.job_id:
            return result

        metadata = dict(result.metadata)
        metadata.setdefault("source_skill_job_id", result.job_id)

        return SkillRunResult(
            job_id=job.job_id,
            skill_id=result.skill_id,
            status=result.status,
            input_text=result.input_text,
            output_text=result.output_text,
            timestamp=result.timestamp,
            execution_time_ms=result.execution_time_ms,
            warnings=list(result.warnings),
            metadata=metadata,
        )

    def _store_skill_run_artifact(self, job: WritingJob, result: SkillRunResult) -> WritingArtifact:
        """Persist a skill result as a typed artifact."""
        artifact_type = ArtifactType.AUDIT_RECORD if result.is_failed() else ArtifactType.TRANSFORMED_TEXT
        artifact = WritingArtifact.create(
            job_id=job.job_id,
            session_id=job.session_id,
            artifact_type=artifact_type,
            content=result.to_dict(),
            created_by=result.skill_id,
            metadata={
                "execution_time_ms": result.execution_time_ms,
                "warnings": list(result.warnings),
                "skill_result_status": result.status.value,
                "source_skill_job_id": result.job_id,
                **dict(result.metadata),
            },
            mime_type="application/json",
        )
        self._store_artifact(artifact)
        return artifact

    async def _finalize_executor_result(self, job_id: str, executor_result: Any) -> WritingJob | None:
        """Finalize a job when an executor returns a concrete result."""
        job = self.get_job(job_id)
        if not job:
            return None

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return job

        if isinstance(executor_result, SkillRunResult):
            normalized_result = self._normalize_skill_run_result(job, executor_result)
            self._store_skill_run_artifact(job, normalized_result)

            if normalized_result.is_failed():
                error_message = (
                    normalized_result.output_text
                    or "; ".join(normalized_result.warnings)
                    or f"Skill execution failed: {normalized_result.status.value}"
                )
                await self.fail_job(job_id, error_message)
            else:
                await self.complete_job(job_id)
            return self.get_job(job_id)

        if isinstance(executor_result, dict):
            status_value = str(executor_result.get("status", "")).lower()
            if status_value in {"failed", "timeout", "cancelled"} or "error" in executor_result:
                error_message = str(
                    executor_result.get("error")
                    or executor_result.get("message")
                    or executor_result.get("output_text")
                    or executor_result
                )
                await self.fail_job(job_id, error_message)
            else:
                await self.complete_job(job_id, result=executor_result)
            return self.get_job(job_id)

        if isinstance(executor_result, str):
            await self.complete_job(job_id, result=executor_result)
            return self.get_job(job_id)

        return job

    def sync_job_to_memory(
        self,
        job_id: str,
        wing: str | None = None,
        room: str | None = None,
    ) -> dict[str, Any]:
        """
        Persist a terminal job into MemPalace when the adapter is available.

        Why:
            Long-term memory should never block job lifecycle transitions. This
            method isolates the sync step behind a best-effort adapter boundary.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        adapter = self._get_memory_adapter()
        if adapter is None:
            return {
                "success": False,
                "available": False,
                "reason": "mempalace adapter unavailable",
                "wing": wing or "",
                "room": room or "",
            }

        session = self.get_session(job.session_id)
        artifacts = self.get_job_artifacts(job_id)
        events = self.get_job_events(job_id)
        result = adapter.sync_runtime_job(
            job,
            session,
            artifacts,
            events,
            wing=wing,
            room=room,
        )
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return result
        return {
            "success": False,
            "available": False,
            "reason": "unexpected mempalace sync response",
            "wing": wing or "",
            "room": room or "",
        }

    # ==========================================================================
    # Event Management
    # ==========================================================================

    def get_job_events(
        self,
        job_id: str,
        since_timestamp: str | None = None,
        after_event_id: str | None = None,
        limit: int | None = None,
    ) -> list[WritingEvent]:
        """Get events for a job, optionally filtered by a polling cursor."""
        job = self.get_job(job_id)
        if not job:
            return []

        session_id = job.session_id
        session_events = self._events.get(session_id, [])
        job_events = sorted(
            [e for e in session_events if e.job_id == job_id],
            key=lambda event: (event.timestamp, event.event_id),
        )

        if since_timestamp is not None:
            job_events = [
                event
                for event in job_events
                if event.timestamp > since_timestamp
                or (
                    event.timestamp == since_timestamp
                    and after_event_id is not None
                    and event.event_id > after_event_id
                )
            ]
        elif after_event_id is not None:
            cursor_index = next(
                (
                    index
                    for index, event in enumerate(job_events)
                    if event.event_id == after_event_id
                ),
                None,
            )
            if cursor_index is not None:
                job_events = job_events[cursor_index + 1 :]

        if limit is not None:
            job_events = job_events[:limit]

        return job_events

    def subscribe_to_events(self, session_id: str, callback: Callable[[WritingEvent], None]) -> None:
        """Subscribe to events in a session."""
        if session_id not in self._event_subscribers:
            self._event_subscribers[session_id] = []
        self._event_subscribers[session_id].append(callback)

    def _emit_event(self, session_id: str, event: WritingEvent) -> None:
        """Emit an event to all subscribers."""
        if session_id not in self._events:
            self._events[session_id] = []
        self._events[session_id].append(event)

        # Notify subscribers
        subscribers = self._event_subscribers.get(session_id, [])
        for callback in subscribers:
            try:
                callback(event)
            except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:
                self._logger.error("Error in event subscriber: %s", exc)

    # ==========================================================================
    # Artifact Management
    # ==========================================================================

    def get_job_artifacts(self, job_id: str, artifact_type: ArtifactType | None = None) -> list[WritingArtifact]:
        """Get artifacts for a job, optionally filtered by type."""
        artifacts = self._artifacts.get(job_id, [])
        if artifact_type:
            artifacts = [a for a in artifacts if a.artifact_type == artifact_type]
        return artifacts

    def _store_artifact(self, artifact: WritingArtifact) -> None:
        """Store an artifact (internal method)."""
        if artifact.job_id not in self._artifacts:
            self._artifacts[artifact.job_id] = []
        self._artifacts[artifact.job_id].append(artifact)

    # ==========================================================================
    # Approval Management
    # ==========================================================================

    def request_approval(
        self,
        job_id: str,
        session_id: str,
        reason: str,
        content_preview: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingApprovalRequest:
        """Request user approval for a job."""
        approval = WritingApprovalRequest.create(
            job_id=job_id,
            session_id=session_id,
            reason=reason,
            content_preview=content_preview,
            metadata=metadata,
        )
        self._approval_requests[approval.approval_id] = approval

        self._emit_event(
            session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=session_id,
                event_type=EventType.APPROVAL_REQUIRED,
                data={"approval_id": approval.approval_id, "reason": reason},
            ),
        )

        self._logger.info("Created approval request %s for job %s", approval.approval_id, job_id)
        self._autosave_if_enabled()
        return approval

    def get_approval_request(self, approval_id: str) -> WritingApprovalRequest | None:
        """Get an approval request by ID."""
        return self._approval_requests.get(approval_id)

    async def grant_approval(self, approval_id: str, response_by: str | None = None) -> WritingApprovalRequest:
        """Grant approval."""
        approval = self.get_approval_request(approval_id)
        if not approval:
            raise ValueError(f"Approval request {approval_id} not found")

        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Cannot grant approval already in status {approval.status.value}")

        approval = approval.with_approval(response_by=response_by)
        self._approval_requests[approval_id] = approval

        self._emit_event(
            approval.session_id,
            WritingEvent.create(
                job_id=approval.job_id,
                session_id=approval.session_id,
                event_type=EventType.APPROVAL_GRANTED,
                data={"approval_id": approval_id},
            ),
        )

        self._logger.info("Granted approval %s", approval_id)
        self._autosave_if_enabled()
        return approval

    async def reject_approval(self, approval_id: str, response_by: str | None = None) -> WritingApprovalRequest:
        """Reject approval."""
        approval = self.get_approval_request(approval_id)
        if not approval:
            raise ValueError(f"Approval request {approval_id} not found")

        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Cannot reject approval already in status {approval.status.value}")

        approval = approval.with_rejection(response_by=response_by)
        self._approval_requests[approval_id] = approval

        self._emit_event(
            approval.session_id,
            WritingEvent.create(
                job_id=approval.job_id,
                session_id=approval.session_id,
                event_type=EventType.APPROVAL_REJECTED,
                data={"approval_id": approval_id},
            ),
        )

        self._logger.info("Rejected approval %s", approval_id)
        self._autosave_if_enabled()
        return approval

    # ==========================================================================
    # Backward Compatibility - Legacy Action Execution
    # ==========================================================================

    async def execute_action(
        self,
        session_id: str,
        action_id: str,
        input_text: str,
        scope: str = "section",
        output_mode: str = "word_safe",
        executor: Callable[[WritingJob], Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a legacy action through the runtime.
        
        Creates a job, executes it, and returns compatibility-formatted result.
        Maintains backward compatibility with existing action execution flows.
        """
        job = self.create_job(
            session_id=session_id,
            kind=JobKind.PROMPT_ACTION,
            input_text=input_text,
            action_id=action_id,
            scope=scope,
            output_mode=output_mode,
            tags=["legacy_action"],
        )

        await self.start_job(job.job_id, executor=executor)

        final_job = self.get_job(job.job_id) or job
        if final_job.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            await self.complete_job(job.job_id)
            final_job = self.get_job(job.job_id) or final_job

        artifacts = self.get_job_artifacts(job.job_id)
        output_text = ""
        if artifacts:
            first_artifact = artifacts[0]
            if isinstance(first_artifact.content, str):
                output_text = first_artifact.content
            elif isinstance(first_artifact.content, dict):
                output_text = (
                    first_artifact.content.get("output_text")
                    or first_artifact.content.get("error")
                    or first_artifact.content.get("text")
                    or str(first_artifact.content)
                )

        if not output_text and final_job.error:
            output_text = final_job.error

        status_value = final_job.status.value
        if final_job.status == JobStatus.COMPLETED:
            status_value = "succeeded"

        return {
            "job_id": job.job_id,
            "status": status_value,
            "input": input_text,
            "output": output_text,
            "action_id": action_id,
            **({"error": final_job.error} if final_job.status != JobStatus.COMPLETED and final_job.error else {}),
        }

    # ==========================================================================
    # State Export (for debugging and persistence preparation)
    # ==========================================================================

    def export_state(self) -> dict[str, Any]:
        """Export full runtime state (for snapshots and persistence)."""
        return {
            "sessions": {sid: s.to_dict() for sid, s in self._sessions.items()},
            "jobs": {jid: j.to_dict() for jid, j in self._jobs.items()},
            "job_queue": self._job_queue[:],
            "events": {
                sid: [e.to_dict() for e in events]
                for sid, events in self._events.items()
            },
            "artifacts": {
                jid: [a.to_dict() for a in artifacts]
                for jid, artifacts in self._artifacts.items()
            },
            "approval_requests": {
                aid: a.to_dict() for aid, a in self._approval_requests.items()
            },
        }

    def import_state(self, state: dict[str, Any]) -> None:
        """Import runtime state (for recovery and restoration)."""
        if not isinstance(state, dict):
            raise TypeError("state must be a dictionary")

        sessions_raw = state.get("sessions", {})
        jobs_raw = state.get("jobs", {})
        job_queue_raw = state.get("job_queue", [])
        events_raw = state.get("events", {})
        artifacts_raw = state.get("artifacts", {})
        approvals_raw = state.get("approval_requests", state.get("approvals", {}))

        if not isinstance(sessions_raw, dict):
            raise TypeError("sessions must be a mapping")
        if not isinstance(jobs_raw, dict):
            raise TypeError("jobs must be a mapping")
        if not isinstance(events_raw, dict):
            raise TypeError("events must be a mapping")
        if not isinstance(artifacts_raw, dict):
            raise TypeError("artifacts must be a mapping")
        if not isinstance(approvals_raw, dict):
            raise TypeError("approval_requests must be a mapping")
        if not isinstance(job_queue_raw, list):
            raise TypeError("job_queue must be a list")

        sessions: dict[str, WritingSession] = {}
        for session_id, payload in sessions_raw.items():
            if not isinstance(payload, dict):
                raise TypeError("session payload must be a mapping")
            session = WritingSession(
                session_id=str(payload["session_id"]),
                user_id=None if payload.get("user_id") in (None, "") else str(payload.get("user_id")),
                mode=SessionMode(str(payload.get("mode", SessionMode.PROMPT.value))),
                created_at=str(payload.get("created_at")),
                settings=dict(payload.get("settings") or {}),
                tags=[str(tag) for tag in payload.get("tags", [])],
                metadata=dict(payload.get("metadata") or {}),
            )
            sessions[str(session_id)] = session

        jobs: dict[str, WritingJob] = {}
        for job_id, payload in jobs_raw.items():
            if not isinstance(payload, dict):
                raise TypeError("job payload must be a mapping")
            job = WritingJob(
                job_id=str(payload["job_id"]),
                session_id=str(payload["session_id"]),
                kind=JobKind(str(payload.get("kind", JobKind.PROMPT_ACTION.value))),
                status=JobStatus(str(payload.get("status", JobStatus.CREATED.value))),
                input_text=str(payload.get("input_text", "")),
                created_at=str(payload.get("created_at")),
                started_at=payload.get("started_at"),
                completed_at=payload.get("completed_at"),
                action_id=None if payload.get("action_id") in (None, "") else str(payload.get("action_id")),
                skill_id=None if payload.get("skill_id") in (None, "") else str(payload.get("skill_id")),
                scope=None if payload.get("scope") in (None, "") else str(payload.get("scope")),
                output_mode=None if payload.get("output_mode") in (None, "") else str(payload.get("output_mode")),
                error=None if payload.get("error") in (None, "") else str(payload.get("error")),
                tags=[str(tag) for tag in payload.get("tags", [])],
                metadata=dict(payload.get("metadata") or {}),
            )
            jobs[str(job_id)] = job

        self._sessions = sessions
        self._jobs = jobs
        self._job_queue = [str(job_id) for job_id in job_queue_raw if str(job_id) in jobs]
        if not self._job_queue:
            self._job_queue = list(jobs.keys())

        self._job_contexts = {}
        for job_id, job in jobs.items():
            ctx = JobExecutionContext(job=job)
            if job.status == JobStatus.PAUSED:
                ctx.is_paused = True
                ctx.pause_event.clear()
            if job.status == JobStatus.CANCELLED:
                ctx.is_cancelled = True
                ctx.cancel_event.set()
            self._job_contexts[job_id] = ctx

        events: dict[str, list[WritingEvent]] = {}
        for session_id, event_list in events_raw.items():
            if not isinstance(event_list, list):
                raise TypeError("event lists must be lists")
            restored_events: list[WritingEvent] = []
            for event_payload in event_list:
                if not isinstance(event_payload, dict):
                    raise TypeError("event payload must be a mapping")
                restored_events.append(
                    WritingEvent(
                        event_id=str(event_payload["event_id"]),
                        job_id=str(event_payload["job_id"]),
                        session_id=str(event_payload["session_id"]),
                        event_type=EventType(str(event_payload.get("event_type", EventType.JOB_CREATED.value))),
                        timestamp=str(event_payload.get("timestamp")),
                        data=dict(event_payload.get("data") or {}),
                        metadata=dict(event_payload.get("metadata") or {}),
                    )
                )
            events[str(session_id)] = restored_events
        self._events = events

        artifacts: dict[str, list[WritingArtifact]] = {}
        for job_id, artifact_list in artifacts_raw.items():
            if not isinstance(artifact_list, list):
                raise TypeError("artifact lists must be lists")
            restored_artifacts: list[WritingArtifact] = []
            for artifact_payload in artifact_list:
                if not isinstance(artifact_payload, dict):
                    raise TypeError("artifact payload must be a mapping")
                restored_artifacts.append(
                    WritingArtifact(
                        artifact_id=str(artifact_payload["artifact_id"]),
                        job_id=str(artifact_payload["job_id"]),
                        session_id=str(artifact_payload["session_id"]),
                        artifact_type=ArtifactType(str(artifact_payload.get("artifact_type", ArtifactType.METADATA.value))),
                        content=artifact_payload.get("content"),
                        created_at=str(artifact_payload.get("created_at")),
                        created_by=None if artifact_payload.get("created_by") in (None, "") else str(artifact_payload.get("created_by")),
                        metadata=dict(artifact_payload.get("metadata") or {}),
                        mime_type=str(artifact_payload.get("mime_type", "application/json")),
                    )
                )
            artifacts[str(job_id)] = restored_artifacts
        self._artifacts = artifacts

        approvals: dict[str, WritingApprovalRequest] = {}
        for approval_id, payload in approvals_raw.items():
            if not isinstance(payload, dict):
                raise TypeError("approval payload must be a mapping")
            approvals[str(approval_id)] = WritingApprovalRequest(
                approval_id=str(payload["approval_id"]),
                job_id=str(payload["job_id"]),
                session_id=str(payload["session_id"]),
                status=ApprovalStatus(str(payload.get("status", ApprovalStatus.PENDING.value))),
                requested_at=str(payload.get("requested_at")),
                reason=str(payload.get("reason", "")),
                content_preview=None if payload.get("content_preview") in (None, "") else str(payload.get("content_preview")),
                response_by=None if payload.get("response_by") in (None, "") else str(payload.get("response_by")),
                responded_at=None if payload.get("responded_at") in (None, "") else str(payload.get("responded_at")),
                metadata=dict(payload.get("metadata") or {}),
            )
        self._approval_requests = approvals

        for session_id in sessions.keys():
            self._events.setdefault(session_id, [])
        for job_id in jobs.keys():
            self._artifacts.setdefault(job_id, [])
        self._logger.info("Imported runtime state with %s sessions and %s jobs", len(sessions), len(jobs))

    def persist_to_database(self) -> Path | None:
        """Persist the current runtime snapshot to SQLite."""
        if self._repository is None:
            return None

        self._repository.replace_state(self.export_state())
        return self._repository.db_path

    def load_from_database(self) -> bool:
        """Load runtime state from SQLite if the repository already has rows."""
        if self._repository is None:
            return False

        if not self._repository.is_healthy():
            self._logger.warning("Skipping SQLite runtime load because %s failed health checks", self._repository.db_path)
            return False

        if not self._repository.has_data():
            return False

        self.import_state(self._repository.load_state())
        return True

    def _autosave_if_enabled(self) -> None:
        """Persist runtime state after mutating operations when autosave is enabled."""
        if self._autosave:
            self.persist_to_database()

    def _persist_state_after_event(self) -> None:
        """Persist the current state after an event or artifact mutation."""
        self._autosave_if_enabled()

    def _get_memory_adapter(self) -> Any | None:
        """Resolve the optional MemPalace adapter lazily and cache the outcome."""
        if self._memory_adapter_resolved:
            return self._memory_adapter

        self._memory_adapter_resolved = True
        try:
            from layers.m_layer_mempalace_memory import (
                MempalaceMemoryAdapter,
                load_mempalace_settings,
            )

            self._memory_adapter = MempalaceMemoryAdapter(load_mempalace_settings())
        except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:  # pragma: no cover - optional integration path
            self._logger.warning("MemPalace adapter unavailable: %s", exc)
            self._memory_adapter = None
        return self._memory_adapter

    def _sync_job_to_memory_if_enabled(self, job_id: str) -> None:
        """Best-effort terminal job sync that never changes the job outcome."""
        adapter = self._get_memory_adapter()
        if adapter is None:
            return
        settings = getattr(adapter, "settings", None)
        if settings is None or not getattr(settings, "auto_sync_runtime_jobs", False):
            return

        try:
            sync_result = self.sync_job_to_memory(job_id)
        except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:  # pragma: no cover - defensive boundary
            self._logger.warning("MemPalace sync failed for job %s: %s", job_id, exc)
            return

        if sync_result.get("success"):
            if sync_result.get("duplicate"):
                self._logger.info(
                    "MemPalace sync skipped duplicate for job %s (%s/%s)",
                    job_id,
                    sync_result.get("wing", ""),
                    sync_result.get("room", ""),
                )
            else:
                self._logger.info(
                    "MemPalace sync stored job %s in %s/%s",
                    job_id,
                    sync_result.get("wing", ""),
                    sync_result.get("room", ""),
                )
            return

        reason = sync_result.get("reason")
        if sync_result.get("available", True):
            self._logger.warning("MemPalace sync did not complete for job %s: %s", job_id, reason)


@lru_cache(maxsize=1)
def _get_writing_runtime_singleton() -> WritingRuntime:
    return WritingRuntime(
        database_path=_default_runtime_db_path(),
        autosave=True,
    )


def get_writing_runtime() -> WritingRuntime:
    """Get or create the global WritingRuntime instance."""
    return _get_writing_runtime_singleton()
