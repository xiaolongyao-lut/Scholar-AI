# -*- coding: utf-8 -*-
"""
Harness V2 Phase B Part 2: Canonical Event Store

Extends HarnessStore (from Phase A) with canonical event persistence and retrieval.

This module:
- Adds CanonicalEvent table to SQLite schema
- Provides methods to append, query, and export canonical events
- Maintains all Phase A functionality while adding canonical event capabilities
- Enables unified event stream for Phase C (Memory Policy Engine)
"""

from __future__ import annotations

import sqlite3
import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from literature_assistant.core.datetime_utils import utc_now_iso_z
    from literature_assistant.core.harness_canonical_events import CanonicalEvent
    from literature_assistant.core.harness_store import HarnessStore
    from literature_assistant.core.recovery_telemetry import get_recovery_telemetry
else:
    from datetime_utils import utc_now_iso_z
    from harness_canonical_events import CanonicalEvent
    from harness_store import HarnessStore
    from recovery_telemetry import get_recovery_telemetry


class CanonicalEventStore:
    """
    Manages canonical event persistence in SQLite.
    
    Extends the Phase A HarnessStore with canonical event capabilities.
    All Harness state changes (WritingEvent, AuditEvent, RevisionEvent) are
    converted to CanonicalEvent and stored in a unified timeline.
    """
    
    def __init__(self, db_path: str = "harness_state.db"):
        """
        Initialize the canonical event store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_schema()

    def _open_conn(self) -> sqlite3.Connection:
        # Audit fix 2026-05-19: was bare sqlite3.connect(self.db_path) — no
        # timeout meant concurrent writers (Harness V2 + Phase B) hit
        # SQLITE_BUSY immediately under multi-worker uvicorn. WAL is set by
        # the sibling HarnessStore on the same DB (persists), but we set it
        # again here so a standalone CanonicalEventStore is safe on its own.
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        """Initialize canonical events table if not exists."""
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS canonical_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    correlation_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    session_id TEXT,
                    job_id TEXT,
                    user_id TEXT,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSON NOT NULL,
                    actor_id TEXT,
                    actor_type TEXT DEFAULT 'system',
                    severity TEXT DEFAULT 'info',
                    previous_state JSON,
                    new_state JSON,
                    error_code TEXT,
                    error_message TEXT,
                    source TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id)
                )
            """)
            
            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_job_id 
                ON canonical_events(job_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_session_id 
                ON canonical_events(session_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_event_type 
                ON canonical_events(event_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_timestamp 
                ON canonical_events(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_aggregate 
                ON canonical_events(aggregate_type, aggregate_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_correlation 
                ON canonical_events(correlation_id)
            """)
            
            conn.commit()
        finally:
            conn.close()
    
    def append_event(self, event: CanonicalEvent) -> None:
        """
        Append a canonical event to the store.
        
        Args:
            event: CanonicalEvent to append
            
        Raises:
            sqlite3.IntegrityError: If event_id already exists (duplicate)
        """
        telemetry = get_recovery_telemetry()
        with telemetry.trace("store.append_event", event_type=event.event_type, aggregate_id=event.aggregate_id, event_id=event.event_id) as span:
            conn = self._open_conn()
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    INSERT INTO canonical_events (
                        event_id, correlation_id, timestamp, session_id, job_id, user_id,
                        aggregate_type, aggregate_id, event_type, payload, actor_id, actor_type,
                        severity, previous_state, new_state, error_code, error_message, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    event.correlation_id,
                    event.timestamp,
                    event.session_id,
                    event.job_id,
                    event.user_id,
                    event.aggregate_type,
                    event.aggregate_id,
                    event.event_type,
                    json.dumps(event.payload),
                    event.actor_id,
                    event.actor_type,
                    event.severity,
                    json.dumps(event.previous_state) if event.previous_state else None,
                    json.dumps(event.new_state) if event.new_state else None,
                    event.error_code,
                    event.error_message,
                    event.source,
                ))
                conn.commit()
                span.set_attribute("rows_inserted", cursor.rowcount)
            finally:
                conn.close()
    
    def get_event_by_id(self, event_id: str) -> CanonicalEvent | None:
        """
        Retrieve a canonical event by ID.
        
        Args:
            event_id: Event identifier
            
        Returns:
            CanonicalEvent if found, None otherwise
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM canonical_events WHERE event_id = ?", (event_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_event(row, cursor.description)
        finally:
            conn.close()
    
    def get_job_timeline(self, job_id: str) -> list[CanonicalEvent]:
        """
        Get all canonical events for a job, ordered by timestamp.
        
        Args:
            job_id: Job identifier
            
        Returns:
            List of CanonicalEvent objects in chronological order
        """
        telemetry = get_recovery_telemetry()
        with telemetry.trace("store.get_job_timeline", job_id=job_id) as span:
            conn = self._open_conn()
            cursor = conn.cursor()
            
            try:
                cursor.execute("""
                    SELECT * FROM canonical_events 
                    WHERE job_id = ? 
                    ORDER BY timestamp ASC
                """, (job_id,))
                rows = cursor.fetchall()
                span.set_attribute("timeline_length", len(rows))
                return [self._row_to_event(row, cursor.description) for row in rows]
            finally:
                conn.close()
    
    def get_session_timeline(self, session_id: str) -> list[CanonicalEvent]:
        """
        Get all canonical events for a session, ordered by timestamp.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of CanonicalEvent objects in chronological order
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM canonical_events 
                WHERE session_id = ? 
                ORDER BY timestamp ASC
            """, (session_id,))
            rows = cursor.fetchall()
            
            return [self._row_to_event(row, cursor.description) for row in rows]
        finally:
            conn.close()
    
    def get_events_by_type(self, event_type: str, limit: int = 100) -> list[CanonicalEvent]:
        """
        Get canonical events by type, most recent first.
        
        Args:
            event_type: Event type to filter by
            limit: Maximum number of results
            
        Returns:
            List of CanonicalEvent objects
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM canonical_events 
                WHERE event_type = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (event_type, limit))
            rows = cursor.fetchall()
            
            return [self._row_to_event(row, cursor.description) for row in rows]
        finally:
            conn.close()
    
    def get_events_by_aggregate(
        self,
        aggregate_type: str,
        aggregate_id: str,
    ) -> list[CanonicalEvent]:
        """
        Get all canonical events for an aggregate, ordered by timestamp.
        
        Args:
            aggregate_type: Type of aggregate (job, resource, capability, etc)
            aggregate_id: ID of the aggregate
            
        Returns:
            List of CanonicalEvent objects in chronological order
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM canonical_events 
                WHERE aggregate_type = ? AND aggregate_id = ? 
                ORDER BY timestamp ASC
            """, (aggregate_type, aggregate_id))
            rows = cursor.fetchall()
            
            return [self._row_to_event(row, cursor.description) for row in rows]
        finally:
            conn.close()
    
    def get_events_by_correlation_id(self, correlation_id: str) -> list[CanonicalEvent]:
        """
        Get all canonical events linked by correlation ID (same logical flow).
        
        Args:
            correlation_id: Correlation ID to filter by
            
        Returns:
            List of CanonicalEvent objects in chronological order
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM canonical_events 
                WHERE correlation_id = ? 
                ORDER BY timestamp ASC
            """, (correlation_id,))
            rows = cursor.fetchall()
            
            return [self._row_to_event(row, cursor.description) for row in rows]
        finally:
            conn.close()
    
    def get_events_by_actor(self, actor_id: str, limit: int = 100) -> list[CanonicalEvent]:
        """
        Get events triggered by a specific actor.
        
        Args:
            actor_id: Actor identifier
            limit: Maximum results
            
        Returns:
            List of CanonicalEvent objects
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM canonical_events 
                WHERE actor_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (actor_id, limit))
            rows = cursor.fetchall()
            
            return [self._row_to_event(row, cursor.description) for row in rows]
        finally:
            conn.close()
    
    def get_events_by_severity(self, severity: str, limit: int = 100) -> list[CanonicalEvent]:
        """
        Get events with a specific severity level.
        
        Args:
            severity: Severity level filter
            limit: Maximum results
            
        Returns:
            List of CanonicalEvent objects
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM canonical_events 
                WHERE severity = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (severity, limit))
            rows = cursor.fetchall()
            
            return [self._row_to_event(row, cursor.description) for row in rows]
        finally:
            conn.close()
    
    def get_all_events(self, limit: int = 1000) -> list[CanonicalEvent]:
        """
        Get all canonical events across all sessions and jobs.
        
        Args:
            limit: Maximum number of results
            
        Returns:
            List of CanonicalEvent objects, most recent first
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM canonical_events 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            
            return [self._row_to_event(row, cursor.description) for row in rows]
        finally:
            conn.close()

    def get_error_events(self, limit: int = 100) -> list[CanonicalEvent]:
        """
        Get all error events (severity = 'error' or 'critical').
        
        Args:
            limit: Maximum results
            
        Returns:
            List of CanonicalEvent objects
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM canonical_events 
                WHERE severity IN ('error', 'critical') 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            
            return [self._row_to_event(row, cursor.description) for row in rows]
        finally:
            conn.close()
    
    def get_event_count(self) -> int:
        """Get total count of canonical events."""
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT COUNT(*) FROM canonical_events")
            row = cursor.fetchone()
            if not isinstance(row, tuple) or len(row) != 1:
                raise RuntimeError("canonical event count query returned an invalid row")
            count = row[0]
            if isinstance(count, bool) or not isinstance(count, int):
                raise RuntimeError("canonical event count must be an integer")
            return int(count)
        finally:
            conn.close()
    
    def export_job_timeline(self, job_id: str) -> dict[str, Any]:
        """
        Export complete job timeline as a report.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Dict with timeline metadata and events
        """
        events = self.get_job_timeline(job_id)
        
        return {
            'job_id': job_id,
            'event_count': len(events),
            'start_time': events[0].timestamp if events else None,
            'end_time': events[-1].timestamp if events else None,
            'events': [event.to_dict() for event in events],
            'exported_at': utc_now_iso_z(),
        }
    
    def export_session_timeline(self, session_id: str) -> dict[str, Any]:
        """
        Export complete session timeline as a report.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dict with timeline metadata and events
        """
        events = self.get_session_timeline(session_id)
        
        return {
            'session_id': session_id,
            'event_count': len(events),
            'start_time': events[0].timestamp if events else None,
            'end_time': events[-1].timestamp if events else None,
            'events': [event.to_dict() for event in events],
            'exported_at': utc_now_iso_z(),
        }
    
    def export_correlation_flow(self, correlation_id: str) -> dict[str, Any]:
        """
        Export all events in a correlation flow.
        
        Args:
            correlation_id: Correlation ID linking related events
            
        Returns:
            Dict with flow metadata and events
        """
        events = self.get_events_by_correlation_id(correlation_id)
        
        return {
            'correlation_id': correlation_id,
            'event_count': len(events),
            'event_types': list(set(e.event_type for e in events)),
            'aggregates_affected': list(set(e.aggregate_id for e in events)),
            'start_time': events[0].timestamp if events else None,
            'end_time': events[-1].timestamp if events else None,
            'events': [event.to_dict() for event in events],
            'exported_at': utc_now_iso_z(),
        }
    
    @staticmethod
    def _decode_json_object(
        value: object,
        *,
        field_name: str,
        optional: bool = False,
    ) -> dict[str, Any] | None:
        """Decode a persisted JSON object after validating its database shape."""

        if value is None:
            if optional:
                return None
            raise ValueError(f"{field_name} must contain a JSON object")
        if not isinstance(value, (str, bytes, bytearray)):
            raise ValueError(f"{field_name} must contain encoded JSON")
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"{field_name} contains invalid JSON") from exc
        if not isinstance(decoded, dict) or any(
            not isinstance(key, str) for key in decoded
        ):
            raise ValueError(f"{field_name} must decode to a JSON object")
        return {
            key: item
            for key, item in decoded.items()
            if isinstance(key, str)
        }

    @staticmethod
    def _required_text_column(
        columns: Mapping[str, object],
        name: str,
        *,
        default: str = "",
    ) -> str:
        """Read a required SQLite text column without leaking untyped values."""

        value = columns.get(name, default)
        if not isinstance(value, str):
            raise ValueError(f"{name} must be stored as text")
        return value

    @staticmethod
    def _optional_text_column(
        columns: Mapping[str, object],
        name: str,
    ) -> str | None:
        """Read a nullable SQLite text column without coercing corrupt values."""

        value = columns.get(name)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{name} must be stored as text or null")
        return value

    def _row_to_event(
        self,
        row: Sequence[object],
        description: Sequence[Sequence[object]] | None,
    ) -> CanonicalEvent:
        """
        Convert database row to CanonicalEvent.
        
        Args:
            row: Database row tuple
            description: Cursor description for column names
            
        Returns:
            CanonicalEvent object
        """
        if description is None or len(description) != len(row):
            raise ValueError("canonical event row does not match its cursor description")

        columns: dict[str, object] = {}
        for index, descriptor in enumerate(description):
            if not descriptor or not isinstance(descriptor[0], str):
                raise ValueError("canonical event cursor contains an invalid column name")
            columns[descriptor[0]] = row[index]
        
        # Parse JSON fields
        payload = self._decode_json_object(
            columns.get("payload"),
            field_name="payload",
        )
        if payload is None:  # pragma: no cover - required payloads cannot be null
            raise ValueError("payload must contain a JSON object")
        previous_state = self._decode_json_object(
            columns.get("previous_state"),
            field_name="previous_state",
            optional=True,
        )
        new_state = self._decode_json_object(
            columns.get("new_state"),
            field_name="new_state",
            optional=True,
        )
        
        return CanonicalEvent(
            event_id=self._required_text_column(columns, "event_id"),
            correlation_id=self._required_text_column(columns, "correlation_id"),
            timestamp=self._required_text_column(columns, "timestamp"),
            session_id=self._optional_text_column(columns, "session_id"),
            job_id=self._optional_text_column(columns, "job_id"),
            user_id=self._optional_text_column(columns, "user_id"),
            aggregate_type=self._required_text_column(columns, "aggregate_type"),
            aggregate_id=self._required_text_column(columns, "aggregate_id"),
            event_type=self._required_text_column(columns, "event_type"),
            payload=payload,
            actor_id=self._optional_text_column(columns, "actor_id"),
            actor_type=self._required_text_column(
                columns,
                "actor_type",
                default="system",
            ),
            severity=self._required_text_column(columns, "severity", default="info"),
            previous_state=previous_state,
            new_state=new_state,
            error_code=self._optional_text_column(columns, "error_code"),
            error_message=self._optional_text_column(columns, "error_message"),
            source=self._required_text_column(columns, "source", default="harness"),
        )


def create_integrated_store(db_path: str = "harness_state.db") -> tuple[HarnessStore, CanonicalEventStore]:
    """
    Convenience function to create both HarnessStore and CanonicalEventStore.
    
    Args:
        db_path: Path to SQLite database
        
    Returns:
        Tuple of (HarnessStore, CanonicalEventStore) sharing the same database
    """
    base_store = HarnessStore(db_path)
    canonical_store = CanonicalEventStore(db_path)
    return base_store, canonical_store
