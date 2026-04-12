# -*- coding: utf-8 -*-
"""
WritingRuntime - Long-lived backend runtime for session and job management.

Phase 2 of harness upgrade: Manages WritingSession, WritingJob, WritingEvent, and WritingArtifact.
Provides stable in-memory state management with clean interfaces for future persistence.
Maintains backward compatibility with legacy run_action flows.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable
from datetime import datetime
from uuid import uuid4

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

logger = logging.getLogger("WritingRuntime")


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

    def __init__(self):
        """Initialize runtime with empty state."""
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
        self._logger.info(f"Created session {session.session_id} with mode {mode.value}")
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

        self._logger.info(f"Created job {job.job_id} in session {session_id}")
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

        self._logger.info(f"Started job {job_id}")

        if executor:
            ctx = self._job_contexts[job_id]
            try:
                await executor(job)
            except Exception as e:
                self._logger.error(f"Executor error for job {job_id}: {e}")
                await self.fail_job(job_id, str(e))

        return job

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

        self._logger.info(f"Paused job {job_id}")
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

        self._logger.info(f"Resumed job {job_id}")
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

        self._logger.info(f"Cancelled job {job_id}")
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
        self._logger.info(f"Completed job {job_id}")
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
        self._logger.info(f"Failed job {job_id}: {error}")
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

    def get_job_events(self, job_id: str) -> list[WritingEvent]:
        """Get all events for a job."""
        job = self.get_job(job_id)
        if not job:
            return []

        session_id = job.session_id
        session_events = self._events.get(session_id, [])
        return [e for e in session_events if e.job_id == job_id]

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
            except Exception as e:
                self._logger.error(f"Error in event subscriber: {e}")

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

        self._logger.info(f"Created approval request {approval.approval_id} for job {job_id}")
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

        self._logger.info(f"Granted approval {approval_id}")
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

        self._logger.info(f"Rejected approval {approval_id}")
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
        await self.complete_job(job.job_id)

        artifacts = self.get_job_artifacts(job.job_id)
        output_text = ""
        if artifacts:
            first_artifact = artifacts[0]
            if isinstance(first_artifact.content, str):
                output_text = first_artifact.content
            elif isinstance(first_artifact.content, dict):
                output_text = first_artifact.content.get("text", str(first_artifact.content))

        return {
            "job_id": job.job_id,
            "status": "succeeded",
            "input": input_text,
            "output": output_text,
            "action_id": action_id,
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
        # This is a placeholder for future persistence integration
        # For now, intentionally left minimal to avoid complex deserialization
        self._logger.info("State import not yet implemented")

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
        except Exception as exc:  # pragma: no cover - optional integration path
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
        except Exception as exc:  # pragma: no cover - defensive boundary
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


# Global singleton instance
_runtime_instance: WritingRuntime | None = None


def get_writing_runtime() -> WritingRuntime:
    """Get or create the global WritingRuntime instance."""
    global _runtime_instance
    if _runtime_instance is None:
        _runtime_instance = WritingRuntime()
    return _runtime_instance
