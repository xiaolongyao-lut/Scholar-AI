# -*- coding: utf-8 -*-
"""
Harness Persistence Adapter - Bridge between WritingRuntime and HarnessStore.

Phase A Integration: Gracefully converts WritingRuntime operations to durable store operations
without breaking backward compatibility.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from harness_protocols import (
    WritingSession,
    WritingJob,
    WritingEvent,
    WritingArtifact,
    WritingApprovalRequest,
    EventType,
    ArtifactType,
)
from harness_store import (
    HarnessStore,
    DurableSession,
    DurableJob,
    DurableEvent,
    DurableArtifact,
    DurableApproval,
    get_harness_store,
)

logger = logging.getLogger("HarnessPersistenceAdapter")


class HarnessPersistenceAdapter:
    """
    Adapter layer that converts WritingRuntime protocol objects to durable store objects.
    Enables automatic persistence without requiring changes to existing runtime code.
    """

    def __init__(self, store: Optional[HarnessStore] = None):
        """Initialize adapter with optional custom store."""
        self.store = store or get_harness_store()

    @staticmethod
    def _now_iso() -> str:
        """Get current time in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    # ===== Session Persistence =====

    def persist_session(self, runtime_session: WritingSession) -> None:
        """
        Persist a WritingSession from runtime to durable store.
        
        Args:
            runtime_session: WritingSession from WritingRuntime
        """
        durable_session = DurableSession(
            session_id=runtime_session.session_id,
            user_id=runtime_session.user_id,
            mode=runtime_session.mode.value,
            created_at=runtime_session.created_at,  # Already ISO format string
            updated_at=self._now_iso(),
            metadata=runtime_session.metadata or {},
        )
        self.store.save_session(durable_session)
        logger.debug("Persisted session: %s", runtime_session.session_id)

    def load_session(self, session_id: str) -> Optional[WritingSession]:
        """
        Load a session from durable store back to WritingSession.
        
        Args:
            session_id: Session ID to load
            
        Returns:
            WritingSession or None if not found
        """
        durable = self.store.get_session(session_id)
        if not durable:
            return None

        # Return restored WritingSession
        from harness_protocols import SessionMode

        return WritingSession(
            session_id=durable.session_id,
            user_id=durable.user_id,
            mode=SessionMode(durable.mode),
            created_at=durable.created_at,  # Already ISO format string
            metadata=durable.metadata,
        )

    # ===== Job Persistence =====

    def persist_job(self, runtime_job: WritingJob) -> None:
        """
        Persist a WritingJob from runtime to durable store.
        
        Args:
            runtime_job: WritingJob from WritingRuntime
        """
        durable_job = DurableJob(
            job_id=runtime_job.job_id,
            session_id=runtime_job.session_id,
            kind=runtime_job.kind.value,
            status=runtime_job.status.value,
            created_at=runtime_job.created_at,  # Already ISO format string
            updated_at=self._now_iso(),
            started_at=runtime_job.started_at,  # Already ISO format string or None
            completed_at=runtime_job.completed_at,  # Already ISO format string or None
            payload={"input_text": runtime_job.input_text, "skill_id": runtime_job.skill_id},
            result=runtime_job.metadata or {},
        )
        self.store.save_job(durable_job)
        logger.debug(f"Persisted job: {runtime_job.job_id}")

    def load_job(self, job_id: str) -> Optional[WritingJob]:
        """
        Load a job from durable store back to WritingJob.
        
        Args:
            job_id: Job ID to load
            
        Returns:
            WritingJob or None if not found
        """
        durable = self.store.get_job(job_id)
        if not durable:
            return None

        from harness_protocols import JobKind, JobStatus

        # Extract input_text from payload
        input_text = durable.payload.get("input_text", "") if durable.payload else ""
        skill_id = durable.payload.get("skill_id") if durable.payload else None

        return WritingJob(
            job_id=durable.job_id,
            session_id=durable.session_id,
            kind=JobKind(durable.kind),
            status=JobStatus(durable.status),
            input_text=input_text,
            created_at=durable.created_at,
            started_at=durable.started_at,
            completed_at=durable.completed_at,
            skill_id=skill_id,
            metadata=durable.result or {},
        )

    # ===== Event Persistence =====

    def persist_event(
        self,
        runtime_event: WritingEvent,
        job_id: str,
        session_id: str,
    ) -> None:
        """
        Persist a WritingEvent to canonical event history.
        
        Args:
            runtime_event: WritingEvent from WritingRuntime
            job_id: Job ID this event belongs to
            session_id: Session ID this event belongs to
        """
        durable_event = DurableEvent(
            event_id=runtime_event.event_id,
            job_id=job_id,
            session_id=session_id,
            event_type=runtime_event.event_type.value
            if hasattr(runtime_event.event_type, "value")
            else str(runtime_event.event_type),
            timestamp=runtime_event.timestamp,
            actor_id=None,  # WritingEvent doesn't have actor_id
            payload=runtime_event.data or {},
            correlation_id=None,
        )
        self.store.append_event(durable_event)
        logger.debug("Persisted event: %s", durable_event.event_type)

    # ===== Artifact Persistence =====

    def persist_artifact(
        self, runtime_artifact: WritingArtifact, job_id: str, session_id: str
    ) -> None:
        """
        Persist a WritingArtifact to durable store.
        
        Args:
            runtime_artifact: WritingArtifact from WritingRuntime
            job_id: Job ID this artifact belongs to
            session_id: Session ID this artifact belongs to
        """
        durable_artifact = DurableArtifact(
            artifact_id=runtime_artifact.artifact_id,
            job_id=job_id,
            session_id=session_id,
            artifact_type=runtime_artifact.artifact_type.value
            if hasattr(runtime_artifact.artifact_type, "value")
            else str(runtime_artifact.artifact_type),
            created_at=runtime_artifact.created_at,
            content=runtime_artifact.content if isinstance(runtime_artifact.content, str) else str(runtime_artifact.content),
            metadata=runtime_artifact.metadata or {},
        )
        self.store.save_artifact(durable_artifact)
        logger.debug("Persisted artifact: %s", runtime_artifact.artifact_id)

    # ===== Approval Persistence =====

    def persist_approval(
        self,
        approval_id: str,
        job_id: str,
        session_id: str,
        capability_id: str,
        policy: str,
        status: str,
        requested_at: str,
        decided_at: Optional[str] = None,
        decided_by: Optional[str] = None,
        decision: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """
        Persist an approval request/decision to durable store.
        
        Args:
            approval_id: Unique approval ID
            job_id: Associated job ID
            session_id: Associated session ID
            capability_id: The capability being approved
            policy: Approval policy (e.g., REQUIRES_USER_APPROVAL)
            status: Current status (pending, approved, rejected)
            requested_at: ISO timestamp of request
            decided_at: ISO timestamp of decision (if decided)
            decided_by: User ID who decided (if decided)
            decision: "approved" or "rejected" (if decided)
            reason: Optional reason for decision
        """
        durable_approval = DurableApproval(
            approval_id=approval_id,
            job_id=job_id,
            session_id=session_id,
            capability_id=capability_id,
            policy=policy,
            status=status,
            requested_at=requested_at,
            decided_at=decided_at,
            decided_by=decided_by,
            decision=decision,
            reason=reason,
        )
        self.store.save_approval(durable_approval)
        logger.debug(f"Persisted approval: {approval_id}")

    # ===== State Recovery =====

    def recover_session_state(self, session_id: str) -> dict[str, Any]:
        """
        Recover full session state from durable store.
        Useful for restoring execution context after process restart.
        
        Args:
            session_id: Session ID to recover
            
        Returns:
            Exported state dictionary
        """
        return self.store.export_state(session_id)

    def restore_session_state(self, state: dict[str, Any]) -> str:
        """
        Restore session state from exported data.
        
        Args:
            state: Exported state dictionary
            
        Returns:
            Restored session ID
        """
        return self.store.import_state(state)


# Global adapter instance
_global_adapter: Optional[HarnessPersistenceAdapter] = None


def get_persistence_adapter() -> HarnessPersistenceAdapter:
    """Get or create global HarnessPersistenceAdapter instance."""
    global _global_adapter  # noqa: F841
    if _global_adapter is None:
        _global_adapter = HarnessPersistenceAdapter()
    return _global_adapter


def set_persistence_adapter(adapter: HarnessPersistenceAdapter) -> None:
    """Set global HarnessPersistenceAdapter instance (for testing)."""
    global _global_adapter  # noqa: F841
    _global_adapter = adapter
