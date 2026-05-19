# -*- coding: utf-8 -*-
"""
Harness V2 Phase D: Temporal Fact Store

Extracts and stores temporal facts from canonical events with validity windows.
Enables queries like "what was true at time T?" and "what is true now?"

This module:
- Defines TemporalFact immutable model
- Persists facts to SQLite with temporal indexes
- Extracts facts from CanonicalEvent using configurable rules
- Provides current/historical/timeline queries
- Maintains source event tracing for audit trail
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from datetime_utils import utc_now
from harness_canonical_events import CanonicalEvent


class FactNamespace(Enum):
    """Logical domains for temporal facts."""
    EXECUTION = "execution"
    SKILLS = "skills"
    RESOURCES = "resources"
    APPROVALS = "approvals"
    PIPELINE = "pipeline"


@dataclass(frozen=True)
class TemporalFact:
    """
    Immutable temporal fact with validity window.
    
    Represents a single fact that is true during a time window.
    valid_to=None means the fact is currently true.
    """
    
    fact_id: str                        # Unique identifier
    namespace: str                      # Domain (execution, skills, resources, etc.)
    subject: str                        # Entity subject (job_id, skill_name, etc.)
    predicate: str                      # Property name (status, enabled, decision, etc.)
    object: str                         # Property value (as JSON string)
    object_type: str                    # Type hint (string, int, float, bool, json)
    valid_from: datetime                # Validity start (inclusive)
    valid_to: datetime | None           # Validity end (exclusive), None = currently valid
    source_event_id: str                # CanonicalEvent that created this fact
    created_at: datetime                # Fact creation timestamp
    
    def is_current(self) -> bool:
        """Check if this fact is currently valid."""
        return self.valid_to is None
    
    def was_valid_at(self, timestamp: datetime) -> bool:
        """Check if this fact was valid at a given timestamp."""
        return (self.valid_from <= timestamp and 
                (self.valid_to is None or timestamp < self.valid_to))


class FactExtractionRule(ABC):
    """Base class for fact extraction rules."""
    
    @abstractmethod
    def can_handle(self, event: CanonicalEvent) -> bool:
        """Check if this rule applies to the event."""
    
    @abstractmethod
    def extract(self, event: CanonicalEvent) -> list[TemporalFact]:
        """Extract facts from the event."""


class ExecutionFactRule(FactExtractionRule):
    """Extract execution status facts from job events."""
    
    def can_handle(self, event: CanonicalEvent) -> bool:
        """Handle job_started, job_completed, job_failed events."""
        return event.aggregate_type == "job" and event.event_type in [
            "job_started", "job_completed", "job_failed", "job_cancelled"
        ]
    
    def extract(self, event: CanonicalEvent) -> list[TemporalFact]:
        """Extract execution status fact from job event."""
        if not event.job_id:
            return []
        
        status_map = {
            "job_started": "running",
            "job_completed": "completed",
            "job_failed": "failed",
            "job_cancelled": "cancelled",
        }
        
        status = status_map.get(event.event_type)
        if not status:
            return []
        
        return [TemporalFact(
            fact_id=f"fact_exec_{event.job_id}_{int(event.timestamp.timestamp())}",
            namespace=FactNamespace.EXECUTION.value,
            subject=event.job_id,
            predicate="status",
            object=status,
            object_type="string",
            valid_from=event.timestamp,
            valid_to=None,
            source_event_id=event.event_id,
            created_at=utc_now(),
        )]


class SkillFactRule(FactExtractionRule):
    """Extract skill state facts from capability events."""
    
    def can_handle(self, event: CanonicalEvent) -> bool:
        """Handle capability and execution events."""
        return event.aggregate_type == "capability" and event.event_type in [
            "capability_requested", "execution_started", "execution_completed",
            "execution_failed"
        ]
    
    def extract(self, event: CanonicalEvent) -> list[TemporalFact]:
        """Extract skill state fact from capability event."""
        skill_name = event.payload.get("skill")
        if not skill_name:
            return []
        
        # Default to enabled on any capability event
        # In production, check payload for explicit enable/disable
        is_enabled = event.payload.get("enabled", True)
        
        return [TemporalFact(
            fact_id=f"fact_skill_{skill_name}_{int(event.timestamp.timestamp())}",
            namespace=FactNamespace.SKILLS.value,
            subject=skill_name,
            predicate="enabled",
            object="true" if is_enabled else "false",
            object_type="bool",
            valid_from=event.timestamp,
            valid_to=None,
            source_event_id=event.event_id,
            created_at=utc_now(),
        )]


class ResourceFactRule(FactExtractionRule):
    """Extract resource state facts from resource events."""
    
    def can_handle(self, event: CanonicalEvent) -> bool:
        """Handle resource mutation events."""
        return event.aggregate_type == "resource" and event.event_type in [
            "resource_modified", "resource_published", "resource_deleted",
            "resource_restored"
        ]
    
    def extract(self, event: CanonicalEvent) -> list[TemporalFact]:
        """Extract resource state facts from resource event."""
        if not event.aggregate_id:
            return []
        
        status_map = {
            "resource_modified": "modified",
            "resource_published": "published",
            "resource_deleted": "deleted",
            "resource_restored": "restored",
        }
        
        status = status_map.get(event.event_type)
        if not status:
            return []
        
        facts = [TemporalFact(
            fact_id=f"fact_res_{event.aggregate_id}_{status}_{int(event.timestamp.timestamp())}",
            namespace=FactNamespace.RESOURCES.value,
            subject=event.aggregate_id,
            predicate="status",
            object=status,
            object_type="string",
            valid_from=event.timestamp,
            valid_to=None,
            source_event_id=event.event_id,
            created_at=utc_now(),
        )]
        
        return facts


class ApprovalFactRule(FactExtractionRule):
    """Extract approval decision facts."""
    
    def can_handle(self, event: CanonicalEvent) -> bool:
        """Handle approval-related events."""
        return "approval" in event.event_type.lower()
    
    def extract(self, event: CanonicalEvent) -> list[TemporalFact]:
        """Extract approval fact from approval event."""
        approval_id = event.payload.get("approval_id", event.aggregate_id)
        if not approval_id:
            return []
        
        decision = "approved" if "approved" in event.event_type else "rejected"
        
        return [TemporalFact(
            fact_id=f"fact_appr_{approval_id}_{int(event.timestamp.timestamp())}",
            namespace=FactNamespace.APPROVALS.value,
            subject=approval_id,
            predicate="decision",
            object=decision,
            object_type="string",
            valid_from=event.timestamp,
            valid_to=None,
            source_event_id=event.event_id,
            created_at=utc_now(),
        )]


class PipelineFactRule(FactExtractionRule):
    """Extract pipeline strategy facts."""
    
    def can_handle(self, event: CanonicalEvent) -> bool:
        """Handle pipeline strategy events."""
        return event.payload.get("strategy") is not None
    
    def extract(self, event: CanonicalEvent) -> list[TemporalFact]:
        """Extract pipeline strategy fact."""
        strategy = event.payload.get("strategy")
        if not strategy:
            return []
        
        return [TemporalFact(
            fact_id=f"fact_pipe_{int(event.timestamp.timestamp())}",
            namespace=FactNamespace.PIPELINE.value,
            subject="strategy",
            predicate="current_mode",
            object=str(strategy),
            object_type="string",
            valid_from=event.timestamp,
            valid_to=None,
            source_event_id=event.event_id,
            created_at=utc_now(),
        )]


class MemoryFactStore:
    """
    Temporal fact store with SQLite backend.
    
    Stores facts with validity windows and enables queries:
    - What is true now?
    - What was true at time T?
    - How did a fact change over time?
    """
    
    def __init__(self, db_path: str = "harness_facts.db"):
        """
        Initialize temporal fact store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_schema()
        self._init_extraction_rules()

    def _open_conn(self) -> sqlite3.Connection:
        # Audit fix 2026-05-19: bare sqlite3.connect(self.db_path) was
        # missing timeout — under concurrent writers from multiple uvicorn
        # workers the second writer raised SQLITE_BUSY instantly. Centralise
        # connection pragmas here so every caller is safe.
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        """Initialize temporal facts table."""
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS temporal_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact_id TEXT UNIQUE NOT NULL,
                    namespace TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    object_type TEXT DEFAULT 'string',
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    source_event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    
                    UNIQUE(namespace, subject, predicate, valid_from)
                )
            """)
            
            # Indexes for efficient queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_namespace_subject 
                ON temporal_facts(namespace, subject)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_namespace_predicate 
                ON temporal_facts(namespace, predicate)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_validity 
                ON temporal_facts(valid_from, valid_to)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_current_facts 
                ON temporal_facts(valid_to) WHERE valid_to IS NULL
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_source_event 
                ON temporal_facts(source_event_id)
            """)
            
            conn.commit()
        finally:
            conn.close()
    
    def _init_extraction_rules(self) -> None:
        """Initialize default extraction rules."""
        self.extraction_rules: list[FactExtractionRule] = [
            ExecutionFactRule(),
            SkillFactRule(),
            ResourceFactRule(),
            ApprovalFactRule(),
            PipelineFactRule(),
        ]
    
    def extract_facts(self, event: CanonicalEvent) -> list[TemporalFact]:
        """
        Extract all applicable facts from a canonical event.
        
        Args:
            event: CanonicalEvent to extract from
        
        Returns:
            List of extracted TemporalFact objects
        """
        facts = []
        for rule in self.extraction_rules:
            if rule.can_handle(event):
                extracted = rule.extract(event)
                facts.extend(extracted)
        return facts
    
    def record_fact(self, fact: TemporalFact) -> str:
        """
        Record a temporal fact, closing predecessors.
        
        Process:
        1. Find facts with same (namespace, subject, predicate)
        2. Set valid_to = fact.valid_from for all predecessors
        3. Insert new fact with valid_to = None
        
        Args:
            fact: TemporalFact to record
        
        Returns:
            Fact ID of the recorded fact
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            # Close any current fact with same (namespace, subject, predicate)
            cursor.execute("""
                UPDATE temporal_facts
                SET valid_to = ?
                WHERE namespace = ? AND subject = ? AND predicate = ?
                  AND valid_to IS NULL
            """, (
                fact.valid_from.isoformat(),
                fact.namespace,
                fact.subject,
                fact.predicate,
            ))
            
            # Insert new fact
            cursor.execute("""
                INSERT INTO temporal_facts
                (fact_id, namespace, subject, predicate, object, object_type,
                 valid_from, valid_to, source_event_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fact.fact_id,
                fact.namespace,
                fact.subject,
                fact.predicate,
                fact.object,
                fact.object_type,
                fact.valid_from.isoformat(),
                None,  # valid_to
                fact.source_event_id,
                fact.created_at.isoformat(),
            ))
            
            conn.commit()
            return fact.fact_id
        finally:
            conn.close()
    
    def get_current_facts(
        self,
        namespace: str,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[TemporalFact]:
        """
        Get all currently valid facts in a namespace.
        
        Args:
            namespace: Fact namespace to query
            subject: Optional subject filter
            predicate: Optional predicate filter
        
        Returns:
            List of currently valid TemporalFact objects
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT fact_id, namespace, subject, predicate, object, object_type,
                       valid_from, valid_to, source_event_id, created_at
                FROM temporal_facts
                WHERE namespace = ? AND valid_to IS NULL
            """
            params = [namespace]
            
            if subject:
                query += " AND subject = ?"
                params.append(subject)
            
            if predicate:
                query += " AND predicate = ?"
                params.append(predicate)
            
            query += " ORDER BY valid_from DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            facts = []
            for row in rows:
                facts.append(self._row_to_fact(row))
            
            return facts
        finally:
            conn.close()
    
    def get_facts_at_time(
        self,
        namespace: str,
        timestamp: datetime,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[TemporalFact]:
        """
        Get all facts that were valid at a specific timestamp.
        
        Args:
            namespace: Fact namespace to query
            timestamp: Time point to query
            subject: Optional subject filter
            predicate: Optional predicate filter
        
        Returns:
            List of TemporalFact objects valid at the timestamp
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT fact_id, namespace, subject, predicate, object, object_type,
                       valid_from, valid_to, source_event_id, created_at
                FROM temporal_facts
                WHERE namespace = ?
                  AND valid_from <= ?
                  AND (valid_to IS NULL OR valid_to > ?)
            """
            params = [namespace, timestamp.isoformat(), timestamp.isoformat()]
            
            if subject:
                query += " AND subject = ?"
                params.append(subject)
            
            if predicate:
                query += " AND predicate = ?"
                params.append(predicate)
            
            query += " ORDER BY valid_from DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            facts = []
            for row in rows:
                facts.append(self._row_to_fact(row))
            
            return facts
        finally:
            conn.close()
    
    def get_fact_timeline(
        self,
        namespace: str,
        subject: str,
        predicate: str,
    ) -> list[TemporalFact]:
        """
        Get complete history of how a fact changed over time.
        
        Args:
            namespace: Fact namespace
            subject: Fact subject
            predicate: Fact predicate
        
        Returns:
            List of TemporalFact objects in chronological order
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT fact_id, namespace, subject, predicate, object, object_type,
                       valid_from, valid_to, source_event_id, created_at
                FROM temporal_facts
                WHERE namespace = ? AND subject = ? AND predicate = ?
                ORDER BY valid_from ASC
            """, (namespace, subject, predicate))
            
            rows = cursor.fetchall()
            
            facts = []
            for row in rows:
                facts.append(self._row_to_fact(row))
            
            return facts
        finally:
            conn.close()
    
    def get_source_event(self, fact_id: str) -> str | None:
        """
        Get the source event ID for a fact.
        
        Args:
            fact_id: Fact identifier
        
        Returns:
            Source event ID or None if not found
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT source_event_id FROM temporal_facts WHERE fact_id = ?",
                (fact_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    
    @staticmethod
    def _row_to_fact(row: tuple) -> TemporalFact:
        """Convert database row to TemporalFact object."""
        (fact_id, namespace, subject, predicate, object_val, object_type,
         valid_from_str, valid_to_str, source_event_id, created_at_str) = row
        
        return TemporalFact(
            fact_id=fact_id,
            namespace=namespace,
            subject=subject,
            predicate=predicate,
            object=object_val,
            object_type=object_type,
            valid_from=datetime.fromisoformat(valid_from_str),
            valid_to=datetime.fromisoformat(valid_to_str) if valid_to_str else None,
            source_event_id=source_event_id,
            created_at=datetime.fromisoformat(created_at_str),
        )
    
    def get_all_namespaces(self) -> list[str]:
        """
        Get all active namespaces with current facts.
        
        Returns:
            List of namespace strings
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT DISTINCT namespace FROM temporal_facts WHERE valid_to IS NULL ORDER BY namespace"
            )
            rows = cursor.fetchall()
            return [row[0] for row in rows]
        finally:
            conn.close()
    
    def invalidate_fact(
        self,
        fact_id: str,
        invalidated_at: datetime,
    ) -> bool:
        """
        Invalidate a temporal fact by setting its valid_to timestamp.
        
        Args:
            fact_id: Fact to invalidate
            invalidated_at: Timestamp when invalidation occurs
        
        Returns:
            True if fact was invalidated, False if not found
        """
        conn = self._open_conn()
        cursor = conn.cursor()
        
        try:
            # Check if fact exists and is current
            cursor.execute(
                "SELECT fact_id FROM temporal_facts WHERE fact_id = ? AND valid_to IS NULL",
                (fact_id,)
            )
            if not cursor.fetchone():
                return False
            
            # Mark as invalid
            cursor.execute(
                "UPDATE temporal_facts SET valid_to = ? WHERE fact_id = ?",
                (invalidated_at.isoformat(), fact_id)
            )
            
            conn.commit()
            return True
        finally:
            conn.close()
    
    def register_extraction_rule(self, rule: FactExtractionRule) -> None:
        """
        Register a custom extraction rule.
        
        Args:
            rule: FactExtractionRule to register
        """
        self.extraction_rules.append(rule)


def create_default_fact_store(db_path: str = "harness_facts.db") -> MemoryFactStore:
    """
    Create a temporal fact store with default configuration.
    
    Args:
        db_path: Path to SQLite database file
    
    Returns:
        Initialized MemoryFactStore
    """
    return MemoryFactStore(db_path)
