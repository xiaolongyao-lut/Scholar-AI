# -*- coding: utf-8 -*-
"""
Harness Durable Store - SQLite-based persistence for sessions, jobs, events, artifacts, approvals.

Phase A of Harness V2: Provides durable state management with event history-based recovery.
Key principle: All execution state can be rebuilt from event history (inspired by Temporal).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger("HarnessStore")


@dataclass(frozen=True)
class DurableSession:
    """Immutable durable session object."""
    session_id: str
    user_id: str
    mode: str  # SessionMode value
    created_at: str  # ISO format
    updated_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class DurableJob:
    """Immutable durable job object."""
    job_id: str
    session_id: str
    kind: str  # JobKind value
    status: str  # JobStatus value
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    payload: dict[str, Any] = None
    result: dict[str, Any] = None

    def __post_init__(self):
        """Validate payload fields."""
        if self.payload is None:
            object.__setattr__(self, 'payload', {})
        if self.result is None:
            object.__setattr__(self, 'result', {})

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class DurableEvent:
    """Immutable durable event object."""
    event_id: str
    job_id: str
    session_id: str
    event_type: str
    timestamp: str  # ISO format
    actor_id: Optional[str]
    payload: dict[str, Any]
    correlation_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class DurableArtifact:
    """Immutable durable artifact object."""
    artifact_id: str
    job_id: str
    session_id: str
    artifact_type: str
    created_at: str
    content: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class DurableApproval:
    """Immutable durable approval object."""
    approval_id: str
    job_id: str
    session_id: str
    capability_id: str
    policy: str
    status: str  # ApprovalStatus value
    requested_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    decision: Optional[str] = None  # "approved" or "rejected"
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class HarnessStore:
    """SQLite-based durable store for Harness state and event history."""

    def __init__(self, db_path: str | Path = "harness_state.db"):
        """Initialize store with database connection."""
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_initialized()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            self._conn.row_factory = sqlite3.Row
            # Enable foreign keys and WAL mode for concurrency
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_initialized(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        
        # Sessions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """)
        
        # Jobs table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                payload TEXT NOT NULL DEFAULT '{}',
                result TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        
        # Events table (canonical event history)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                actor_id TEXT,
                payload TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        
        # Artifacts table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        
        # Approvals table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                policy TEXT NOT NULL,
                status TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                decided_at TEXT,
                decided_by TEXT,
                decision TEXT,
                reason TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(job_id),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        
        # Create indexes for common queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_session_id ON jobs(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_job_id ON events(job_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_job_id ON artifacts(job_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approvals_job_id ON approvals(job_id)")
        
        conn.commit()
        logger.info(f"HarnessStore initialized at {self.db_path}")

    # ===== Session operations =====

    def save_session(self, session: DurableSession) -> None:
        """Save or update a session."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions 
            (session_id, user_id, mode, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.user_id,
                session.mode,
                session.created_at,
                session.updated_at,
                json.dumps(session.metadata),
            ),
        )
        conn.commit()

    def get_session(self, session_id: str) -> Optional[DurableSession]:
        """Retrieve a session by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        
        if not row:
            return None
        
        return DurableSession(
            session_id=row["session_id"],
            user_id=row["user_id"],
            mode=row["mode"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=json.loads(row["metadata"]),
        )

    def list_sessions(self, user_id: Optional[str] = None) -> list[DurableSession]:
        """List sessions, optionally filtered by user."""
        conn = self._get_conn()
        if user_id:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        
        return [
            DurableSession(
                session_id=row["session_id"],
                user_id=row["user_id"],
                mode=row["mode"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    # ===== Job operations =====

    def save_job(self, job: DurableJob) -> None:
        """Save or update a job."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs
            (job_id, session_id, kind, status, created_at, updated_at, 
             started_at, completed_at, payload, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.session_id,
                job.kind,
                job.status,
                job.created_at,
                job.updated_at,
                job.started_at,
                job.completed_at,
                json.dumps(job.payload),
                json.dumps(job.result),
            ),
        )
        conn.commit()

    def get_job(self, job_id: str) -> Optional[DurableJob]:
        """Retrieve a job by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        
        if not row:
            return None
        
        return DurableJob(
            job_id=row["job_id"],
            session_id=row["session_id"],
            kind=row["kind"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            payload=json.loads(row["payload"]),
            result=json.loads(row["result"]),
        )

    def list_jobs(
        self, session_id: Optional[str] = None, kind: Optional[str] = None
    ) -> list[DurableJob]:
        """List jobs, optionally filtered by session and kind."""
        conn = self._get_conn()
        query = "SELECT * FROM jobs WHERE 1=1"
        params = []
        
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if kind:
            query += " AND kind = ?"
            params.append(kind)
        
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        
        return [
            DurableJob(
                job_id=row["job_id"],
                session_id=row["session_id"],
                kind=row["kind"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                payload=json.loads(row["payload"]),
                result=json.loads(row["result"]),
            )
            for row in rows
        ]

    # ===== Event operations =====

    def append_event(self, event: DurableEvent) -> None:
        """Append an event to the canonical event stream."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO events
            (event_id, job_id, session_id, event_type, timestamp, 
             actor_id, payload, correlation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.job_id,
                event.session_id,
                event.event_type,
                event.timestamp,
                event.actor_id,
                json.dumps(event.payload),
                event.correlation_id,
            ),
        )
        conn.commit()

    def get_events(
        self, job_id: Optional[str] = None, session_id: Optional[str] = None
    ) -> list[DurableEvent]:
        """Retrieve events, optionally filtered by job or session."""
        conn = self._get_conn()
        query = "SELECT * FROM events WHERE 1=1"
        params = []
        
        if job_id:
            query += " AND job_id = ?"
            params.append(job_id)
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        
        query += " ORDER BY timestamp ASC"
        rows = conn.execute(query, params).fetchall()
        
        return [
            DurableEvent(
                event_id=row["event_id"],
                job_id=row["job_id"],
                session_id=row["session_id"],
                event_type=row["event_type"],
                timestamp=row["timestamp"],
                actor_id=row["actor_id"],
                payload=json.loads(row["payload"]),
                correlation_id=row["correlation_id"],
            )
            for row in rows
        ]

    # ===== Artifact operations =====

    def save_artifact(self, artifact: DurableArtifact) -> None:
        """Save an artifact."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO artifacts
            (artifact_id, job_id, session_id, artifact_type, created_at, content, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                artifact.job_id,
                artifact.session_id,
                artifact.artifact_type,
                artifact.created_at,
                artifact.content,
                json.dumps(artifact.metadata),
            ),
        )
        conn.commit()

    def get_artifact(self, artifact_id: str) -> Optional[DurableArtifact]:
        """Retrieve an artifact by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        
        if not row:
            return None
        
        return DurableArtifact(
            artifact_id=row["artifact_id"],
            job_id=row["job_id"],
            session_id=row["session_id"],
            artifact_type=row["artifact_type"],
            created_at=row["created_at"],
            content=row["content"],
            metadata=json.loads(row["metadata"]),
        )

    def list_artifacts(self, job_id: str) -> list[DurableArtifact]:
        """List artifacts for a job."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE job_id = ? ORDER BY created_at DESC",
            (job_id,),
        ).fetchall()
        
        return [
            DurableArtifact(
                artifact_id=row["artifact_id"],
                job_id=row["job_id"],
                session_id=row["session_id"],
                artifact_type=row["artifact_type"],
                created_at=row["created_at"],
                content=row["content"],
                metadata=json.loads(row["metadata"]),
            )
            for row in rows
        ]

    # ===== Approval operations =====

    def save_approval(self, approval: DurableApproval) -> None:
        """Save an approval request/decision."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO approvals
            (approval_id, job_id, session_id, capability_id, policy, status,
             requested_at, decided_at, decided_by, decision, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval.approval_id,
                approval.job_id,
                approval.session_id,
                approval.capability_id,
                approval.policy,
                approval.status,
                approval.requested_at,
                approval.decided_at,
                approval.decided_by,
                approval.decision,
                approval.reason,
            ),
        )
        conn.commit()

    def get_approval(self, approval_id: str) -> Optional[DurableApproval]:
        """Retrieve an approval by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        
        if not row:
            return None
        
        return DurableApproval(
            approval_id=row["approval_id"],
            job_id=row["job_id"],
            session_id=row["session_id"],
            capability_id=row["capability_id"],
            policy=row["policy"],
            status=row["status"],
            requested_at=row["requested_at"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
            decision=row["decision"],
            reason=row["reason"],
        )

    def list_approvals(self, job_id: str) -> list[DurableApproval]:
        """List approvals for a job."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM approvals WHERE job_id = ? ORDER BY requested_at DESC",
            (job_id,),
        ).fetchall()
        
        return [
            DurableApproval(
                approval_id=row["approval_id"],
                job_id=row["job_id"],
                session_id=row["session_id"],
                capability_id=row["capability_id"],
                policy=row["policy"],
                status=row["status"],
                requested_at=row["requested_at"],
                decided_at=row["decided_at"],
                decided_by=row["decided_by"],
                decision=row["decision"],
                reason=row["reason"],
            )
            for row in rows
        ]

    # ===== State recovery operations =====

    def rebuild_job_state(self, job_id: str) -> dict[str, Any]:
        """
        Rebuild job state from event history.
        
        This is the core recovery mechanism: given a job_id, replay all events
        to reconstruct the job's state at any point in time.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        events = self.get_events(job_id=job_id)
        
        # Start with job metadata
        state = {
            "job_id": job_id,
            "session_id": job.session_id,
            "status": job.status,
            "kind": job.kind,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "events_count": len(events),
            "event_timeline": [],
        }
        
        # Replay events to reconstruct full state
        for event in events:
            state["event_timeline"].append({
                "event_id": event.event_id,
                "event_type": event.event_type,
                "timestamp": event.timestamp,
                "actor_id": event.actor_id,
            })
        
        return state

    def export_state(self, session_id: str) -> dict[str, Any]:
        """
        Export entire session state including all jobs, events, artifacts, approvals.
        Useful for backup and migration.
        """
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        
        jobs = self.list_jobs(session_id=session_id)
        
        # Collect all approvals across all jobs in this session
        all_approvals = []
        for job in jobs:
            all_approvals.extend(self.list_approvals(job.job_id))
        
        # Get all events and convert to dicts
        events_objs = self.get_events(session_id=session_id)
        events_dicts = [e.to_dict() for e in events_objs]
        
        exported = {
            "session": session.to_dict(),
            "jobs": [],
            "events": events_dicts,
            "artifacts": [],
            "approvals": [a.to_dict() for a in all_approvals],
        }
        
        for job in jobs:
            exported["jobs"].append(job.to_dict())
            exported["artifacts"].extend(
                [a.to_dict() for a in self.list_artifacts(job.job_id)]
            )
        
        return exported

    def import_state(self, state: dict[str, Any]) -> str:
        """
        Import session state from exported data.
        Returns the imported session_id.
        """
        session_data = state.get("session")
        if not session_data:
            raise ValueError("Invalid state: missing 'session'")
        
        # Import session
        session = DurableSession(**session_data)
        self.save_session(session)
        
        # Import jobs
        for job_data in state.get("jobs", []):
            job = DurableJob(**job_data)
            self.save_job(job)
        
        # Import events
        for event_data in state.get("events", []):
            event = DurableEvent(**event_data)
            self.append_event(event)
        
        # Import artifacts
        for artifact_data in state.get("artifacts", []):
            artifact = DurableArtifact(**artifact_data)
            self.save_artifact(artifact)
        
        # Import approvals
        for approval_data in state.get("approvals", []):
            approval = DurableApproval(**approval_data)
            self.save_approval(approval)
        
        logger.info(f"Imported state for session: {session.session_id}")
        return session.session_id


# Global store instance
_global_store: Optional[HarnessStore] = None


def get_harness_store(db_path: str | Path = "harness_state.db") -> HarnessStore:
    """Get or create global HarnessStore instance."""
    global _global_store
    if _global_store is None:
        _global_store = HarnessStore(db_path)
    return _global_store


def set_harness_store(store: HarnessStore) -> None:
    """Set global HarnessStore instance (for testing)."""
    global _global_store
    _global_store = store
