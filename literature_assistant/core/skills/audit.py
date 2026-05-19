# -*- coding: utf-8 -*-
"""Audit logging and event persistence for capability execution tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from datetime_utils import utc_now_iso_z


class AuditEventType(str, Enum):
    """Types of auditable events."""
    JOB_CREATED = "job_created"
    CAPABILITY_RESOLVED = "capability_resolved"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    EXECUTION_ATTEMPTED = "execution_attempted"
    EXECUTION_BLOCKED = "execution_blocked"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    ARTIFACT_GENERATED = "artifact_generated"
    ERROR_OCCURRED = "error_occurred"


@dataclass(frozen=True)
class AuditEvent:
    """
    Immutable audit event record.
    
    Tracks execution events with full context for replay and auditing.
    """
    event_id: str
    event_type: str  # AuditEventType value
    timestamp: str = field(default_factory=utc_now_iso_z)
    
    # Context identifiers
    job_id: str | None = None
    capability_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    
    # Event details
    description: str = ""
    status: str = "logged"  # 'logged', 'processed', 'archived'
    severity: str = "info"  # 'debug', 'info', 'warning', 'error', 'critical'
    
    # Contextual data (replay support)
    context: dict[str, Any] = field(default_factory=dict)
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    
    # Error/failure info
    error_code: str | None = None
    error_message: str | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)
    
    def is_error(self) -> bool:
        """Check if event represents an error."""
        return self.severity in ('error', 'critical')


@dataclass(frozen=True)
class ExecutionRecord:
    """
    Record of a single execution of a capability.
    
    Used to replay execution history and audit user actions.
    """
    job_id: str
    capability_id: str
    started_at: str
    completed_at: str | None = None
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    status: str = "in_progress"  # 'in_progress', 'completed', 'failed', 'cancelled'
    user_id: str | None = None
    approval_decision_id: str | None = None
    execution_time_ms: int = 0
    error_info: dict[str, Any] | None = None
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)
    
    def is_complete(self) -> bool:
        """Check if execution is complete."""
        return self.status != "in_progress"


class AuditLog:
    """
    Audit log for tracking all execution events.
    
    Provides replay capability through event storage and querying.
    """
    
    def __init__(self, jsonl_path: str | Path | None = None):
        """Initialize audit log with optional append-only JSONL persistence."""
        self._events: dict[str, AuditEvent] = {}
        self._records: dict[str, ExecutionRecord] = {}
        self._event_sequence: list[str] = []  # Maintain order for replay
        self._jsonl_path = Path(jsonl_path).expanduser().resolve() if jsonl_path else None
        if self._jsonl_path is not None:
            self._load_jsonl_events(self._jsonl_path)
    
    def log_event(self, event_type: str, **kwargs) -> AuditEvent:
        """Log an audit event."""
        event_id = kwargs.get('event_id', f"evt_{uuid4().hex[:12]}")
        event = AuditEvent(
            event_id=event_id,
            event_type=event_type,
            **{k: v for k, v in kwargs.items() if k != 'event_id'}
        )
        self._events[event_id] = event
        self._event_sequence.append(event_id)
        self._append_jsonl_event(event)
        return event
    
    def get_event(self, event_id: str) -> AuditEvent | None:
        """Get an audit event by ID."""
        return self._events.get(event_id)
    
    def list_events(self) -> list[AuditEvent]:
        """List all audit events in order."""
        return [self._events[eid] for eid in self._event_sequence if eid in self._events]
    
    def list_events_for_job(self, job_id: str) -> list[AuditEvent]:
        """List all events for a specific job."""
        return [e for e in self.list_events() if e.job_id == job_id]
    
    def list_events_by_type(self, event_type: str) -> list[AuditEvent]:
        """List all events of a specific type."""
        return [e for e in self.list_events() if e.event_type == event_type]
    
    def list_events_by_severity(self, severity: str) -> list[AuditEvent]:
        """List all events with a specific severity."""
        return [e for e in self.list_events() if e.severity == severity]
    
    def register_execution(self, record: ExecutionRecord) -> None:
        """Register an execution record."""
        self._records[record.job_id] = record
    
    def get_execution_record(self, job_id: str) -> ExecutionRecord | None:
        """Get execution record by job ID."""
        return self._records.get(job_id)
    
    def list_execution_records(self) -> list[ExecutionRecord]:
        """List all execution records."""
        return list(self._records.values())
    
    def update_execution_status(
        self,
        job_id: str,
        status: str,
        output_data: dict[str, Any] | None = None,
        error_info: dict[str, Any] | None = None,
    ) -> ExecutionRecord | None:
        """Update status of an execution record."""
        record = self._records.get(job_id)
        if record is None:
            return None
        
        # Create updated record (frozen dataclass)
        updated = ExecutionRecord(
            job_id=record.job_id,
            capability_id=record.capability_id,
            started_at=record.started_at,
            completed_at=utc_now_iso_z() if status != "in_progress" else None,
            input_data=record.input_data,
            output_data=output_data or record.output_data,
            status=status,
            user_id=record.user_id,
            approval_decision_id=record.approval_decision_id,
            execution_time_ms=record.execution_time_ms,
            error_info=error_info or record.error_info,
        )
        self._records[job_id] = updated
        return updated
    
    def clear(self) -> None:
        """Clear all audit data (for testing)."""
        self._events.clear()
        self._records.clear()
        self._event_sequence.clear()
        if self._jsonl_path is not None and self._jsonl_path.exists():
            self._jsonl_path.unlink()

    def _load_jsonl_events(self, jsonl_path: Path) -> None:
        """Load persisted audit events while ignoring corrupt trailing rows."""
        if not jsonl_path.exists():
            return
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                event = AuditEvent(**payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            self._events[event.event_id] = event
            self._event_sequence.append(event.event_id)

    def _append_jsonl_event(self, event: AuditEvent) -> None:
        """Append one audit event to the configured JSONL file."""
        if self._jsonl_path is None:
            return
        self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self._jsonl_path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")))
            file_obj.write("\n")


# Global audit log instance
_audit_log_instance: AuditLog | None = None


def get_audit_log() -> AuditLog:
    """Get or create the global audit log instance."""
    global _audit_log_instance
    if _audit_log_instance is None:
        _audit_log_instance = AuditLog()
    return _audit_log_instance


def reset_audit_log() -> None:
    """Reset the global audit log (for testing)."""
    global _audit_log_instance
    _audit_log_instance = AuditLog()
