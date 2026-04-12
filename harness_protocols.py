# -*- coding: utf-8 -*-
"""
Harness Protocol Layer - First-class typed protocol for writing system.

Defines immutable, strictly-typed entities for session, job, event, artifact, and approval.
All models are serializable and maintain backward compatibility with legacy action calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
from uuid import uuid4

from datetime_utils import utc_now_iso_z


class SessionMode(str, Enum):
    """User interface execution mode."""
    PROMPT = "prompt"  # Prompt-only, first-class mode
    SKILL = "skill"    # Skill-assisted mode with backend support
    HYBRID = "hybrid"  # Combined prompt + skill support


class JobKind(str, Enum):
    """Type of work being performed."""
    PROMPT_ACTION = "prompt_action"      # Simple prompt-based action
    SKILL_ACTION = "skill_action"        # Skill-backed action
    PIPELINE_RUN = "pipeline_run"        # Full document pipeline
    APPROVAL = "approval"                # Human review/approval  gate
    ARTIFACT_EXPORT = "artifact_export"  # Output formatting/export


class JobStatus(str, Enum):
    """Lifecycle state of a job."""
    CREATED = "created"
    QUEUED = "queued"
    STARTED = "started"
    PAUSED = "paused"
    IN_PROGRESS = "in_progress"
    APPROVAL_PENDING = "approval_pending"
    APPROVAL_REJECTED = "approval_rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    """Event vocabulary for protocol state changes."""
    JOB_CREATED = "job_created"
    JOB_STARTED = "job_started"
    JOB_PROGRESS = "job_progress"
    TOOL_REQUESTED = "tool_requested"
    TOOL_BLOCKED = "tool_blocked"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_UPDATED = "artifact_updated"
    JOB_PAUSED = "job_paused"
    JOB_RESUMED = "job_resumed"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"


class ArtifactType(str, Enum):
    """Classification of output artifacts."""
    TRANSFORMED_TEXT = "transformed_text"      # Text rewrite/transform result
    DRAFT = "draft"                            # Document draft
    REVIEW_NOTE = "review_note"                # Human review or comment
    EXPORT_REQUEST = "export_request"          # Export or rendering config
    AUDIT_RECORD = "audit_record"              # Audit trail or log
    METADATA = "metadata"                      # Structural metadata


class ApprovalStatus(str, Enum):
    """State of approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class WritingSession:
    """
    Represents a user session with shared writing context.
    
    Immutable container for session-level configuration and state.
    All jobs spawned in this session inherit mode and settings.
    """
    session_id: str
    user_id: str | None
    mode: SessionMode
    created_at: str  # ISO 8601
    settings: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        mode: SessionMode,
        user_id: str | None = None,
        settings: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingSession:
        """Factory method to create a new session."""
        return WritingSession(
            session_id=f"session_{uuid4().hex[:16]}",
            user_id=user_id,
            mode=mode,
            created_at=utc_now_iso_z(),
            settings=settings or {},
            tags=tags or [],
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)


@dataclass(frozen=True)
class WritingJob:
    """
    Represents a unit of work within a session.
    
    Immutable container for job definition, status, and result associations.
    Jobs can be simple prompt actions or complex skill-backed operations.
    """
    job_id: str
    session_id: str
    kind: JobKind
    status: JobStatus
    input_text: str
    created_at: str  # ISO 8601
    started_at: str | None = None
    completed_at: str | None = None
    action_id: str | None = None              # Legacy action reference
    skill_id: str | None = None               # Skill backing this job
    scope: str | None = None                  # 'selection', 'section', 'full_draft'
    output_mode: str | None = None            # 'latex', 'word_safe', 'plain'
    error: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
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
        """Factory method to create a new job."""
        return WritingJob(
            job_id=f"job_{uuid4().hex[:16]}",
            session_id=session_id,
            kind=kind,
            status=JobStatus.CREATED,
            input_text=input_text,
            created_at=utc_now_iso_z(),
            action_id=action_id,
            skill_id=skill_id,
            scope=scope,
            output_mode=output_mode,
            tags=tags or [],
            metadata=metadata or {},
        )

    def with_status(self, status: JobStatus) -> WritingJob:
        """Return a new job with updated status."""
        started = self.started_at
        # Set started_at if transitioning to any running/active state
        if status in (JobStatus.STARTED, JobStatus.IN_PROGRESS) and self.started_at is None:
            started = utc_now_iso_z()

        completed = self.completed_at
        # Set completed_at if transitioning to any terminal state
        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED) and self.completed_at is None:
            completed = utc_now_iso_z()

        return WritingJob(
            job_id=self.job_id,
            session_id=self.session_id,
            kind=self.kind,
            status=status,
            input_text=self.input_text,
            created_at=self.created_at,
            started_at=started,
            completed_at=completed,
            action_id=self.action_id,
            skill_id=self.skill_id,
            scope=self.scope,
            output_mode=self.output_mode,
            error=self.error,
            tags=self.tags,
            metadata=self.metadata,
        )

    def with_error(self, error: str) -> WritingJob:
        """Return a new job with error set and status FAILED."""
        return WritingJob(
            job_id=self.job_id,
            session_id=self.session_id,
            kind=self.kind,
            status=JobStatus.FAILED,
            input_text=self.input_text,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=utc_now_iso_z(),
            action_id=self.action_id,
            skill_id=self.skill_id,
            scope=self.scope,
            output_mode=self.output_mode,
            error=error,
            tags=self.tags,
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        data = asdict(self)
        # Ensure all enum values are strings
        data["kind"] = self.kind.value
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class WritingEvent:
    """
    Represents a protocol-level state change event.
    
    Immutable event record for tracking job lifecycle, approvals, and important transitions.
    """
    event_id: str
    job_id: str
    session_id: str
    event_type: EventType
    timestamp: str  # ISO 8601
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        job_id: str,
        session_id: str,
        event_type: EventType,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingEvent:
        """Factory method to create a new event."""
        return WritingEvent(
            event_id=f"event_{uuid4().hex[:16]}",
            job_id=job_id,
            session_id=session_id,
            event_type=event_type,
            timestamp=utc_now_iso_z(),
            data=data or {},
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        data_copy = dict(self.data)
        metadata_copy = dict(self.metadata)
        return {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "session_id": self.session_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "data": data_copy,
            "metadata": metadata_copy,
        }


@dataclass(frozen=True)
class WritingArtifact:
    """
    Represents an output from job execution.
    
    Immutable container for typed results (transformed text, draft, review notes, etc).
    Multiple artifacts can be associated with a single job.
    """
    artifact_id: str
    job_id: str
    session_id: str
    artifact_type: ArtifactType
    content: str | dict[str, Any]
    created_at: str  # ISO 8601
    created_by: str | None = None  # "system", "user", or skill ID
    metadata: dict[str, Any] = field(default_factory=dict)
    mime_type: str = "application/json"

    @staticmethod
    def create(
        job_id: str,
        session_id: str,
        artifact_type: ArtifactType,
        content: str | dict[str, Any],
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
        mime_type: str = "application/json",
    ) -> WritingArtifact:
        """Factory method to create a new artifact."""
        return WritingArtifact(
            artifact_id=f"artifact_{uuid4().hex[:16]}",
            job_id=job_id,
            session_id=session_id,
            artifact_type=artifact_type,
            content=content,
            created_at=utc_now_iso_z(),
            created_by=created_by or "system",
            metadata=metadata or {},
            mime_type=mime_type,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "artifact_id": self.artifact_id,
            "job_id": self.job_id,
            "session_id": self.session_id,
            "artifact_type": self.artifact_type.value,
            "content": self.content,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "metadata": self.metadata,
            "mime_type": self.mime_type,
        }


@dataclass(frozen=True)
class WritingApprovalRequest:
    """
    Represents a human approval gate for sensitive operations.
    
    Immutable request for user intervention. Multiple approval requests
    can be chained in complex workflows.
    """
    approval_id: str
    job_id: str
    session_id: str
    status: ApprovalStatus
    requested_at: str  # ISO 8601
    reason: str
    content_preview: str | None = None
    response_by: str | None = None
    responded_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        job_id: str,
        session_id: str,
        reason: str,
        content_preview: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingApprovalRequest:
        """Factory method to create a new approval request."""
        return WritingApprovalRequest(
            approval_id=f"approval_{uuid4().hex[:16]}",
            job_id=job_id,
            session_id=session_id,
            status=ApprovalStatus.PENDING,
            requested_at=utc_now_iso_z(),
            reason=reason,
            content_preview=content_preview,
            metadata=metadata or {},
        )

    def with_approval(self, response_by: str | None = None) -> WritingApprovalRequest:
        """Return a new approval request with APPROVED status."""
        return WritingApprovalRequest(
            approval_id=self.approval_id,
            job_id=self.job_id,
            session_id=self.session_id,
            status=ApprovalStatus.APPROVED,
            requested_at=self.requested_at,
            reason=self.reason,
            content_preview=self.content_preview,
            response_by=response_by or "user",
            responded_at=utc_now_iso_z(),
            metadata=self.metadata,
        )

    def with_rejection(self, response_by: str | None = None) -> WritingApprovalRequest:
        """Return a new approval request with REJECTED status."""
        return WritingApprovalRequest(
            approval_id=self.approval_id,
            job_id=self.job_id,
            session_id=self.session_id,
            status=ApprovalStatus.REJECTED,
            requested_at=self.requested_at,
            reason=self.reason,
            content_preview=self.content_preview,
            response_by=response_by or "user",
            responded_at=utc_now_iso_z(),
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "approval_id": self.approval_id,
            "job_id": self.job_id,
            "session_id": self.session_id,
            "status": self.status.value,
            "requested_at": self.requested_at,
            "reason": self.reason,
            "content_preview": self.content_preview,
            "response_by": self.response_by,
            "responded_at": self.responded_at,
            "metadata": self.metadata,
        }


# Protocol version for compatibility checks
PROTOCOL_VERSION = "1.0.0"
