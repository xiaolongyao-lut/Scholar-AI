# -*- coding: utf-8 -*-
"""
Harness V2 Phase B: Canonical Event Infrastructure

Unified event envelope and converters for WritingEvent, AuditEvent, and RevisionEvent.
All Harness state changes flow through CanonicalEvent for centralized history, auditing, and replay.

Architecture:
  WritingEvent (job lifecycle)
      ↓
  CanonicalEvent (unified envelope) ← converters from multiple sources
      ↓                              ← AuditEvent (capability execution)
  Canonical Event Stream (single timeline)
      ↓                              ← RevisionEvent (resource changes)
  Phase C (Memory Policy Engine)
  Phase D (Recovery/Replay)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any
from uuid import uuid4

from datetime_utils import utc_now_iso_z

# Import from Phase A protocol layer
try:
    from harness_protocols import WritingEvent, EventType
except ImportError:
    WritingEvent = None
    EventType = None

try:
    from skills.audit import AuditEvent, AuditEventType
except ImportError:
    AuditEvent = None
    AuditEventType = None


class CanonicalEventType(str, Enum):
    """Unified event type enum combining all Harness event categories."""
    
    # Job lifecycle (4)
    JOB_CREATED = "job_created"
    JOB_STARTED = "job_started"
    JOB_PAUSED = "job_paused"
    JOB_RESUMED = "job_resumed"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"
    
    # Capability execution (7)
    CAPABILITY_RESOLVED = "capability_resolved"
    EXECUTION_ATTEMPTED = "execution_attempted"
    EXECUTION_BLOCKED = "execution_blocked"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    
    # Approvals (2)
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    
    # Artifacts (3)
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_UPDATED = "artifact_updated"
    ARTIFACT_FINALIZED = "artifact_finalized"
    
    # Resources (4)
    RESOURCE_CREATED = "resource_created"
    RESOURCE_MODIFIED = "resource_modified"
    RESOURCE_PUBLISHED = "resource_published"
    RESOURCE_DELETED = "resource_deleted"
    
    # Errors (1)
    ERROR_OCCURRED = "error_occurred"


@dataclass(frozen=True)
class CanonicalEvent:
    """
    Unified event envelope for all Harness state changes.
    
    Immutable record that represents a single state change event from any source:
    - Job execution (WritingEvent)
    - Capability audit (AuditEvent)
    - Resource mutation (RevisionEvent)
    
    All events flow through this canonical format for centralized:
    - History tracking
    - Audit trail
    - Replay and recovery
    - Memory integration
    """
    
    # Universal identifier
    event_id: str
    correlation_id: str
    
    # Time
    timestamp: str  # ISO 8601 UTC
    
    # Context (aggregates across all three sources)
    session_id: str | None = None
    job_id: str | None = None
    user_id: str | None = None
    
    # Event classification
    aggregate_type: str = "job"  # 'job' | 'capability' | 'resource' | 'approval' | 'artifact'
    aggregate_id: str = ""  # ID of the affected entity
    event_type: str = ""  # Unified event type (from CanonicalEventType)
    
    # Data payload
    payload: dict[str, Any] = field(default_factory=dict)
    
    # Metadata (audit trail)
    actor_id: str | None = None
    actor_type: str = "system"  # 'user' | 'system' | 'workflow'
    severity: str = "info"  # 'debug' | 'info' | 'warning' | 'error' | 'critical'
    
    # Optional state tracking (for resource changes)
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    
    # Optional error info
    error_code: str | None = None
    error_message: str | None = None
    
    # Source tracking (for migration/debugging)
    source: str = "harness"  # 'writing_runtime' | 'skills_audit' | 'resource_manager'
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for storage/transmission."""
        return asdict(self)
    
    def is_error(self) -> bool:
        """Check if event represents an error."""
        return self.severity in ('error', 'critical')
    
    def is_job_event(self) -> bool:
        """Check if event is job-related."""
        return self.aggregate_type in ('job', 'artifact', 'approval')
    
    def is_resource_event(self) -> bool:
        """Check if event is resource-related."""
        return self.aggregate_type == 'resource'
    
    def is_capability_event(self) -> bool:
        """Check if event is capability-related."""
        return self.aggregate_type == 'capability'


class CanonicalEventBuilder:
    """Fluent builder for creating CanonicalEvent instances."""
    
    def __init__(self) -> None:
        """Initialize builder with defaults."""
        self._event_id = f"event_{uuid4().hex[:16]}"
        self._correlation_id = self._event_id
        self._timestamp = utc_now_iso_z()
        self._session_id: str | None = None
        self._job_id: str | None = None
        self._user_id: str | None = None
        self._aggregate_type = "job"
        self._aggregate_id = ""
        self._event_type = ""
        self._payload: dict[str, Any] = {}
        self._actor_id: str | None = None
        self._actor_type = "system"
        self._severity = "info"
        self._previous_state: dict[str, Any] | None = None
        self._new_state: dict[str, Any] | None = None
        self._error_code: str | None = None
        self._error_message: str | None = None
        self._source = "harness"
    
    def with_event_type(self, event_type: str | CanonicalEventType) -> CanonicalEventBuilder:
        """Set event type."""
        self._event_type = event_type.value if isinstance(event_type, Enum) else event_type
        return self
    
    def with_aggregate(self, agg_type: str, agg_id: str) -> CanonicalEventBuilder:
        """Set aggregate type and ID."""
        self._aggregate_type = agg_type
        self._aggregate_id = agg_id
        return self
    
    def with_session(self, session_id: str) -> CanonicalEventBuilder:
        """Set session ID."""
        self._session_id = session_id
        return self
    
    def with_job(self, job_id: str) -> CanonicalEventBuilder:
        """Set job ID."""
        self._job_id = job_id
        self._aggregate_id = job_id
        return self
    
    def with_user(self, user_id: str) -> CanonicalEventBuilder:
        """Set user ID and actor type."""
        self._user_id = user_id
        self._actor_id = user_id
        self._actor_type = "user"
        return self
    
    def with_actor(self, actor_id: str, actor_type: str = "system") -> CanonicalEventBuilder:
        """Set actor ID and type."""
        self._actor_id = actor_id
        self._actor_type = actor_type
        return self
    
    def with_payload(self, payload: dict[str, Any]) -> CanonicalEventBuilder:
        """Set payload dict."""
        self._payload = payload
        return self
    
    def with_severity(self, severity: str) -> CanonicalEventBuilder:
        """Set severity level."""
        self._severity = severity
        return self
    
    def with_state_change(
        self,
        previous_state: dict[str, Any] | None = None,
        new_state: dict[str, Any] | None = None,
    ) -> CanonicalEventBuilder:
        """Set state change information."""
        self._previous_state = previous_state
        self._new_state = new_state
        return self
    
    def with_error(self, code: str, message: str, severity: str = "error") -> CanonicalEventBuilder:
        """Set error information."""
        self._error_code = code
        self._error_message = message
        self._severity = severity
        return self
    
    def with_correlation_id(self, correlation_id: str) -> CanonicalEventBuilder:
        """Set correlation ID for linked events."""
        self._correlation_id = correlation_id
        return self
    
    def with_source(self, source: str) -> CanonicalEventBuilder:
        """Set source system."""
        self._source = source
        return self
    
    def build(self) -> CanonicalEvent:
        """Build and return the CanonicalEvent."""
        return CanonicalEvent(
            event_id=self._event_id,
            correlation_id=self._correlation_id,
            timestamp=self._timestamp,
            session_id=self._session_id,
            job_id=self._job_id,
            user_id=self._user_id,
            aggregate_type=self._aggregate_type,
            aggregate_id=self._aggregate_id,
            event_type=self._event_type,
            payload=self._payload,
            actor_id=self._actor_id,
            actor_type=self._actor_type,
            severity=self._severity,
            previous_state=self._previous_state,
            new_state=self._new_state,
            error_code=self._error_code,
            error_message=self._error_message,
            source=self._source,
        )


class EventConverter:
    """Static methods to convert from various event types to CanonicalEvent."""
    
    @staticmethod
    def from_writing_event(event: WritingEvent, correlation_id: str | None = None) -> CanonicalEvent:
        """
        Convert WritingEvent (job lifecycle from WritingRuntime) to CanonicalEvent.
        
        Args:
            event: WritingEvent from harness_protocols
            correlation_id: Optional correlation ID to link related events
        
        Returns:
            CanonicalEvent with aggregate_type='job'
        """
        if WritingEvent is None:
            raise ImportError("WritingEvent not available; ensure harness_protocols is imported")
        
        # Map WritingEvent event types to CanonicalEventType
        event_type_map = {
            "job_created": CanonicalEventType.JOB_CREATED,
            "job_started": CanonicalEventType.JOB_STARTED,
            "job_paused": CanonicalEventType.JOB_PAUSED,
            "job_resumed": CanonicalEventType.JOB_RESUMED,
            "job_completed": CanonicalEventType.JOB_COMPLETED,
            "job_failed": CanonicalEventType.JOB_FAILED,
            "job_cancelled": CanonicalEventType.JOB_CANCELLED,
            "approval_required": CanonicalEventType.APPROVAL_REQUESTED,
            "artifact_created": CanonicalEventType.ARTIFACT_CREATED,
            "artifact_updated": CanonicalEventType.ARTIFACT_UPDATED,
        }
        
        event_type_value = event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type)
        canonical_type = event_type_map.get(event_type_value, event_type_value)
        
        return CanonicalEvent(
            event_id=event.event_id,
            correlation_id=correlation_id or event.metadata.get('correlation_id', event.event_id),
            timestamp=event.timestamp,
            session_id=event.session_id,
            job_id=event.job_id,
            aggregate_type="job" if "job" in event_type_value else "artifact",
            aggregate_id=event.job_id,
            event_type=canonical_type if isinstance(canonical_type, str) else canonical_type.value,
            payload=event.data or {},
            actor_id=event.metadata.get('actor_id'),
            actor_type=event.metadata.get('actor_type', 'system'),
            severity=event.metadata.get('severity', 'info'),
            source='writing_runtime',
        )
    
    @staticmethod
    def from_audit_event(event: AuditEvent, correlation_id: str | None = None) -> CanonicalEvent:
        """
        Convert AuditEvent (capability execution from skills/audit) to CanonicalEvent.
        
        Args:
            event: AuditEvent from skills/audit
            correlation_id: Optional correlation ID to link related events
        
        Returns:
            CanonicalEvent with aggregate_type='capability'
        """
        if AuditEvent is None:
            raise ImportError("AuditEvent not available; ensure skills/audit is imported")
        
        agg_type = 'capability' if event.capability_id else 'job'
        agg_id = event.capability_id or event.job_id or ""
        
        return CanonicalEvent(
            event_id=event.event_id,
            correlation_id=correlation_id or event.event_id,
            timestamp=event.timestamp,
            session_id=event.session_id,
            job_id=event.job_id,
            user_id=event.user_id,
            aggregate_type=agg_type,
            aggregate_id=agg_id,
            event_type=event.event_type,
            payload={
                'description': event.description,
                'context': event.context,
            },
            actor_id=event.user_id,
            actor_type='user' if event.user_id else 'system',
            severity=event.severity,
            previous_state=event.previous_state,
            new_state=event.new_state,
            error_code=event.error_code,
            error_message=event.error_message,
            source='skills_audit',
        )
    
    @staticmethod
    def from_revision(
        revision_id: str,
        draft_id: str,
        timestamp: str,
        revision_number: int,
        created_by: str | None = None,
        notes: str | None = None,
        session_id: str | None = None,
        previous_content: str | None = None,
        new_content: str | None = None,
    ) -> CanonicalEvent:
        """
        Convert WritingRevision (resource change) to CanonicalEvent.
        
        Args:
            revision_id: Revision identifier
            draft_id: Draft being revised
            timestamp: When revision was created
            revision_number: Revision sequence number
            created_by: User who created revision
            notes: Revision notes
            session_id: Associated session if any
            previous_content: Previous content (for diff)
            new_content: New content
        
        Returns:
            CanonicalEvent with aggregate_type='resource'
        """
        return CanonicalEvent(
            event_id=f"event_{uuid4().hex[:16]}",
            correlation_id=f"rev_{revision_id}",
            timestamp=timestamp,
            session_id=session_id,
            job_id=None,
            aggregate_type='resource',
            aggregate_id=draft_id,
            event_type=CanonicalEventType.RESOURCE_MODIFIED.value,
            payload={
                'revision_id': revision_id,
                'revision_number': revision_number,
                'notes': notes or '',
            },
            actor_id=created_by,
            actor_type='user' if created_by else 'system',
            previous_state={'content': previous_content} if previous_content else None,
            new_state={'content': new_content} if new_content else None,
            source='resource_manager',
        )


def create_job_event(
    job_id: str,
    event_type: CanonicalEventType | str,
    session_id: str | None = None,
    payload: dict[str, Any] | None = None,
    actor_id: str | None = None,
    severity: str = "info",
) -> CanonicalEvent:
    """
    Convenience function to create a job-related CanonicalEvent.
    
    Args:
        job_id: Job identifier
        event_type: Event type (CanonicalEventType or string)
        session_id: Associated session
        payload: Event-specific payload
        actor_id: Who triggered the event
        severity: Severity level
    
    Returns:
        CanonicalEvent configured for job aggregate
    """
    builder = CanonicalEventBuilder().with_job(job_id)
    if session_id:
        builder = builder.with_session(session_id)
    builder = builder.with_event_type(event_type)
    if actor_id:
        builder = builder.with_actor(actor_id, 'user')
    return builder.with_payload(payload or {}).with_severity(severity).build()


def create_resource_event(
    aggregate_id: str,
    event_type: str = "resource_modified",
    payload: dict[str, Any] | None = None,
    actor_id: str | None = None,
    previous_state: dict[str, Any] | None = None,
    new_state: dict[str, Any] | None = None,
) -> CanonicalEvent:
    """
    Convenience function to create a resource-related CanonicalEvent.
    
    Args:
        aggregate_id: Resource identifier (draft_id, etc)
        event_type: Resource event type
        payload: Event-specific payload
        actor_id: Who triggered the event
        previous_state: State before change
        new_state: State after change
    
    Returns:
        CanonicalEvent configured for resource aggregate
    """
    builder = CanonicalEventBuilder()
    builder = builder.with_aggregate('resource', aggregate_id)
    builder = builder.with_event_type(event_type)
    builder = builder.with_payload(payload or {})
    builder = builder.with_state_change(previous_state, new_state)
    if actor_id:
        builder = builder.with_actor(actor_id, 'user')
    return builder.build()


def create_error_event(
    aggregate_type: str,
    aggregate_id: str,
    error_code: str,
    error_message: str,
    context: dict[str, Any] | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
) -> CanonicalEvent:
    """
    Convenience function to create an error CanonicalEvent.
    
    Args:
        aggregate_type: Type of affected aggregate
        aggregate_id: ID of affected aggregate
        error_code: Error code
        error_message: Error message
        context: Error context
        job_id: Associated job if any
        session_id: Associated session if any
    
    Returns:
        CanonicalEvent configured as error
    """
    builder = CanonicalEventBuilder().with_aggregate(aggregate_type, aggregate_id)
    if job_id:
        builder = builder.with_job(job_id)
    if session_id:
        builder = builder.with_session(session_id)
    return builder.with_event_type(CanonicalEventType.ERROR_OCCURRED) \
        .with_error(error_code, error_message, 'error') \
        .with_payload(context or {}) \
        .build()
