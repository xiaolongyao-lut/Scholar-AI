# -*- coding: utf-8 -*-
"""
Harness V2 Phase F: Recovery Console

Provides inspection, replay, and recovery capabilities for:
- Canonical event streams
- Memory syncs and facts
- Execution state reconstruction
- Fact invalidation and rebuild

This module enables:
- Event timeline inspection
- Memory audit and validation
- Recovery from failed states
- Fact store correction
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from canonical_event_store import CanonicalEventStore, CanonicalEvent
from memory_fact_store import MemoryFactStore, TemporalFact
from models.recovery import RecoveryActionType


class EventFilter(str, Enum):
    """Filters for event timeline inspection."""
    BY_SESSION = "by_session"
    BY_JOB = "by_job"
    BY_AGGREGATE = "by_aggregate"
    BY_CORRELATION = "by_correlation"
    ALL = "all"


@dataclass(frozen=True)
class InspectionContext:
    """Context for recovery console operations."""
    session_id: str
    job_id: Optional[str] = None
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    filter_type: EventFilter = EventFilter.ALL
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


@dataclass(frozen=True)
class EventTimeline:
    """Timeline of events for inspection."""
    timeline_id: str
    session_id: str
    events: list[CanonicalEvent]
    event_count: int
    earliest_timestamp: datetime
    latest_timestamp: datetime
    aggregate_types: list[str]
    event_types: list[str]


@dataclass(frozen=True)
class MemorySnapshot:
    """Snapshot of memory state at a point in time."""
    snapshot_id: str
    session_id: str
    timestamp: datetime
    current_facts: list[TemporalFact]
    fact_count: int
    namespaces: list[str]
    sources: list[str]


@dataclass(frozen=True)
class FactInvalidation:
    """Record of fact invalidation."""
    invalidation_id: str
    fact_id: str
    namespace: str
    reason: str
    invalidated_at: datetime
    invalidated_by: str
    previous_value: Optional[str] = None


@dataclass(frozen=True)
class RecoveryAction:
    """A recovery action to execute."""
    action_id: str
    action_type: RecoveryActionType
    context: InspectionContext
    timestamp: datetime
    parameters: dict[str, Any]
    applied: bool = False


class RecoveryConsole:
    """Recovery console for inspecting and repairing Harness state."""

    def __init__(
        self,
        event_store: CanonicalEventStore,
        fact_store: MemoryFactStore,
    ):
        """Initialize recovery console.

        Args:
            event_store: Access to canonical events
            fact_store: Access to temporal facts
        """
        self.event_store = event_store
        self.fact_store = fact_store

    def inspect_event_timeline(
        self,
        context: InspectionContext,
    ) -> EventTimeline:
        """Inspect the timeline of events for a session/job.

        Args:
            context: Inspection context with filters

        Returns:
            EventTimeline with sorted events
        """
        events = []

        # Query based on filter type
        if context.filter_type == EventFilter.BY_SESSION:
            events = self.event_store.get_session_timeline(context.session_id)

        elif context.filter_type == EventFilter.BY_JOB and context.job_id:
            events = self.event_store.get_job_timeline(context.job_id)

        elif context.filter_type == EventFilter.BY_AGGREGATE and context.aggregate_id:
            events = self.event_store.get_events_by_aggregate("job", context.aggregate_id)

        elif context.filter_type == EventFilter.BY_CORRELATION and context.correlation_id:
            events = self.event_store.get_events_by_correlation_id(context.correlation_id)

        elif context.filter_type == EventFilter.ALL:
            events = self.event_store.get_all_events()

        else:
            events = []

        # Filter by time range if specified
        if context.start_time or context.end_time:
            filtered = []
            for event in events:
                raw_time = event.timestamp
                if isinstance(raw_time, datetime):
                    event_time = raw_time
                elif isinstance(raw_time, str):
                    try:
                        event_time = datetime.fromisoformat(raw_time)
                    except ValueError:
                        continue
                else:
                    continue
                if context.start_time and event_time < context.start_time:
                    continue
                if context.end_time and event_time > context.end_time:
                    continue
                filtered.append(event)
            events = filtered

        # Sort by timestamp
        events = sorted(events, key=lambda e: e.timestamp)

        # Extract metadata
        aggregate_types = list(set(e.aggregate_type for e in events))
        event_types = list(set(e.event_type for e in events))

        if not events:
            return EventTimeline(
                timeline_id=f"timeline_{context.session_id}",
                session_id=context.session_id,
                events=[],
                event_count=0,
                earliest_timestamp=datetime.now(timezone.utc),
                latest_timestamp=datetime.now(timezone.utc),
                aggregate_types=[],
                event_types=[],
            )

        def _to_dt(t):
            return t if isinstance(t, datetime) else datetime.fromisoformat(t)

        earliest = _to_dt(events[0].timestamp)
        latest = _to_dt(events[-1].timestamp)

        return EventTimeline(
            timeline_id=f"timeline_{context.session_id}",
            session_id=context.session_id,
            events=events,
            event_count=len(events),
            earliest_timestamp=earliest,
            latest_timestamp=latest,
            aggregate_types=aggregate_types,
            event_types=event_types,
        )

    def inspect_memory_state(
        self,
        context: InspectionContext,
    ) -> MemorySnapshot:
        """Inspect current state of memory facts.

        Args:
            context: Inspection context with namespace/subject filters

        Returns:
            MemorySnapshot with current facts
        """
        if not context or not context.session_id:
            raise ValueError("InspectionContext with session_id is required")

        now = datetime.now(timezone.utc)

        # Query current facts from all available namespaces
        current_facts = []
        try:
            available_namespaces = self.fact_store.get_all_namespaces()
        except (AttributeError, sqlite3.Error):
            available_namespaces = ["execution", "skills", "resources", "approvals", "pipeline"]
        
        for namespace in available_namespaces:
            try:
                facts = self.fact_store.get_current_facts(namespace)
                current_facts.extend(facts)
            except Exception:
                # Skip namespaces that fail to query
                pass

        # Extract metadata
        namespaces = list(set(f.namespace for f in current_facts))
        sources = list(set(f.source_event_id for f in current_facts if f.source_event_id))

        return MemorySnapshot(
            snapshot_id=f"snapshot_{context.session_id}_{int(now.timestamp())}",
            session_id=context.session_id,
            timestamp=now,
            current_facts=current_facts,
            fact_count=len(current_facts),
            namespaces=namespaces,
            sources=sources,
        )

    def invalidate_fact(
        self,
        fact_id: str,
        namespace: str,
        reason: str,
        invalidated_by: str,
    ) -> FactInvalidation:
        """Invalidate a temporal fact.

        Args:
            fact_id: Fact to invalidate
            namespace: Fact namespace
            reason: Reason for invalidation
            invalidated_by: User/agent performing invalidation

        Returns:
            FactInvalidation record
        """
        if not fact_id or not namespace or not reason or not invalidated_by:
            raise ValueError("fact_id, namespace, reason, and invalidated_by are required")
        
        # Get the fact first
        try:
            facts = self.fact_store.get_current_facts(namespace)
        except (sqlite3.Error, AttributeError, ValueError):
            facts = []
        
        target_fact = None
        for fact in facts:
            if fact.fact_id == fact_id:
                target_fact = fact
                break

        # Invalidate by setting valid_to to now
        now = datetime.now(timezone.utc)

        # Create invalidation record
        invalidation = FactInvalidation(
            invalidation_id=f"inv_{fact_id}_{int(now.timestamp())}",
            fact_id=fact_id,
            namespace=namespace,
            reason=reason,
            invalidated_at=now,
            invalidated_by=invalidated_by,
            previous_value=target_fact.object if target_fact else None,
        )

        # Perform the invalidation if fact exists
        if target_fact:
            try:
                self.fact_store.invalidate_fact(fact_id, now)
            except (sqlite3.Error, AttributeError, ValueError):
                # If invalidation fails, still return the audit record
                pass

        return invalidation

    def get_fact_history(
        self,
        namespace: str,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
    ) -> list[TemporalFact]:
        """Get complete history of a fact (including invalidated versions).

        Args:
            namespace: Fact namespace
            subject: Optional subject filter
            predicate: Optional predicate filter

        Returns:
            List of all fact versions chronologically
        """
        return self.fact_store.get_fact_timeline(namespace, subject, predicate)

    def create_recovery_action(
        self,
        action_type: RecoveryActionType,
        context: InspectionContext,
        parameters: dict[str, Any],
    ) -> RecoveryAction:
        """Create a recovery action record.

        Args:
            action_type: Type of recovery action
            context: Inspection context
            parameters: Action-specific parameters

        Returns:
            RecoveryAction ready for execution
        """
        now = datetime.now(timezone.utc)
        return RecoveryAction(
            action_id=f"recover_{action_type.value}_{int(now.timestamp())}",
            action_type=action_type,
            context=context,
            timestamp=now,
            parameters=parameters,
        )


def create_recovery_console(
    event_store: CanonicalEventStore,
    fact_store: MemoryFactStore,
) -> RecoveryConsole:
    """Factory function for recovery console.

    Args:
        event_store: Canonical event store
        fact_store: Memory fact store

    Returns:
        Initialized RecoveryConsole
    """
    return RecoveryConsole(event_store, fact_store)
