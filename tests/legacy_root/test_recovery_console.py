# -*- coding: utf-8 -*-
"""
Tests for Harness V2 Phase F: Recovery Console

Comprehensive test suite for:
- Event timeline inspection
- Memory state inspection
- Fact invalidation
- Recovery action creation
- History tracking
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from recovery_console import (
    EventFilter,
    EventTimeline,
    FactInvalidation,
    InspectionContext,
    MemorySnapshot,
    RecoveryAction,
    RecoveryActionType,
    RecoveryConsole,
    create_recovery_console,
)
from canonical_event_store import CanonicalEvent
from memory_fact_store import TemporalFact


class TestInspectionContext(unittest.TestCase):
    """Tests for InspectionContext input model."""

    def test_context_creation_minimal(self):
        """Can create context with minimal fields."""
        ctx = InspectionContext(session_id="sess_001")

        self.assertEqual(ctx.session_id, "sess_001")
        self.assertIsNone(ctx.job_id)
        self.assertEqual(ctx.filter_type, EventFilter.ALL)

    def test_context_creation_with_filters(self):
        """Can create context with temporal filters."""
        now = datetime.now()
        start = now - timedelta(hours=1)

        ctx = InspectionContext(
            session_id="sess_001",
            job_id="job_001",
            filter_type=EventFilter.BY_JOB,
            start_time=start,
            end_time=now,
        )

        self.assertEqual(ctx.session_id, "sess_001")
        self.assertEqual(ctx.job_id, "job_001")
        self.assertEqual(ctx.filter_type, EventFilter.BY_JOB)
        self.assertEqual(ctx.start_time, start)


class TestEventTimeline(unittest.TestCase):
    """Tests for EventTimeline inspection results."""

    def test_timeline_creation(self):
        """Can create valid timeline."""
        now = datetime.now()
        events = [
            MagicMock(timestamp=now.isoformat(), aggregate_type="job", event_type="created"),
            MagicMock(timestamp=(now + timedelta(seconds=1)).isoformat(), aggregate_type="job", event_type="completed"),
        ]

        timeline = EventTimeline(
            timeline_id="tl_001",
            session_id="sess_001",
            events=events,
            event_count=2,
            earliest_timestamp=now,
            latest_timestamp=now + timedelta(seconds=1),
            aggregate_types=["job"],
            event_types=["created", "completed"],
        )

        self.assertEqual(timeline.event_count, 2)
        self.assertEqual(len(timeline.aggregate_types), 1)

    def test_timeline_empty(self):
        """Can create empty timeline."""
        now = datetime.now()

        timeline = EventTimeline(
            timeline_id="tl_001",
            session_id="sess_001",
            events=[],
            event_count=0,
            earliest_timestamp=now,
            latest_timestamp=now,
            aggregate_types=[],
            event_types=[],
        )

        self.assertEqual(timeline.event_count, 0)


class TestMemorySnapshot(unittest.TestCase):
    """Tests for MemorySnapshot inspection results."""

    def test_snapshot_creation(self):
        """Can create valid memory snapshot."""
        now = datetime.now()
        facts = [
            MagicMock(namespace="execution", source_event_id="evt_001"),
            MagicMock(namespace="execution", source_event_id="evt_002"),
        ]

        snapshot = MemorySnapshot(
            snapshot_id="snap_001",
            session_id="sess_001",
            timestamp=now,
            current_facts=facts,
            fact_count=2,
            namespaces=["execution"],
            sources=["evt_001", "evt_002"],
        )

        self.assertEqual(snapshot.fact_count, 2)
        self.assertEqual(len(snapshot.namespaces), 1)

    def test_snapshot_immutable(self):
        """Snapshot is immutable."""
        snapshot = MemorySnapshot(
            snapshot_id="snap_001",
            session_id="sess_001",
            timestamp=datetime.now(),
            current_facts=[],
            fact_count=0,
            namespaces=[],
            sources=[],
        )

        with self.assertRaises(AttributeError):
            snapshot.fact_count = 10


class TestFactInvalidation(unittest.TestCase):
    """Tests for fact invalidation records."""

    def test_invalidation_creation(self):
        """Can create invalidation record."""
        now = datetime.now()

        invalidation = FactInvalidation(
            invalidation_id="inv_001",
            fact_id="fact_001",
            namespace="execution",
            reason="Incorrect skill state",
            invalidated_at=now,
            invalidated_by="user_001",
            previous_value="enabled",
        )

        self.assertEqual(invalidation.fact_id, "fact_001")
        self.assertEqual(invalidation.reason, "Incorrect skill state")
        self.assertEqual(invalidation.previous_value, "enabled")

    def test_invalidation_immutable(self):
        """Invalidation is immutable."""
        invalidation = FactInvalidation(
            invalidation_id="inv_001",
            fact_id="fact_001",
            namespace="execution",
            reason="Test",
            invalidated_at=datetime.now(),
            invalidated_by="user_001",
        )

        with self.assertRaises(AttributeError):
            invalidation.reason = "Modified"


class TestRecoveryAction(unittest.TestCase):
    """Tests for recovery actions."""

    def test_action_creation(self):
        """Can create recovery action."""
        ctx = InspectionContext(session_id="sess_001")

        action = RecoveryAction(
            action_id="rec_001",
            action_type=RecoveryActionType.INSPECT_EVENTS,
            context=ctx,
            timestamp=datetime.now(),
            parameters={"filter": "by_session"},
        )

        self.assertEqual(action.action_type, RecoveryActionType.INSPECT_EVENTS)
        self.assertFalse(action.applied)

    def test_action_immutable(self):
        """Action is immutable."""
        ctx = InspectionContext(session_id="sess_001")

        action = RecoveryAction(
            action_id="rec_001",
            action_type=RecoveryActionType.INSPECT_EVENTS,
            context=ctx,
            timestamp=datetime.now(),
            parameters={},
        )

        with self.assertRaises(AttributeError):
            action.applied = True


class TestRecoveryConsoleEventInspection(unittest.TestCase):
    """Tests for event timeline inspection."""

    def setUp(self):
        """Set up mocks."""
        self.mock_event_store = MagicMock()
        self.mock_fact_store = MagicMock()
        self.console = RecoveryConsole(self.mock_event_store, self.mock_fact_store)

    def test_inspect_by_session(self):
        """Can inspect events by session."""
        now = datetime.now()
        events = [
            MagicMock(
                timestamp=now.isoformat(),
                aggregate_type="job",
                event_type="created",
            )
        ]

        self.mock_event_store.get_session_timeline.return_value = events

        ctx = InspectionContext(
            session_id="sess_001",
            filter_type=EventFilter.BY_SESSION,
        )

        timeline = self.console.inspect_event_timeline(ctx)

        self.assertEqual(timeline.event_count, 1)
        self.mock_event_store.get_session_timeline.assert_called_once()

    def test_inspect_by_job(self):
        """Can inspect events by job."""
        now = datetime.now()
        events = [MagicMock(timestamp=now.isoformat(), aggregate_type="job")]

        self.mock_event_store.get_job_timeline.return_value = events

        ctx = InspectionContext(
            session_id="sess_001",
            job_id="job_001",
            filter_type=EventFilter.BY_JOB,
        )

        timeline = self.console.inspect_event_timeline(ctx)

        self.assertEqual(timeline.event_count, 1)
        self.mock_event_store.get_job_timeline.assert_called_once()

    def test_inspect_all_events(self):
        """Can inspect all events."""
        now = datetime.now()
        events = [
            MagicMock(
                timestamp=now.isoformat(),
                aggregate_type="job",
                event_type="created",
            ),
            MagicMock(
                timestamp=(now + timedelta(seconds=1)).isoformat(),
                aggregate_type="job",
                event_type="completed",
            ),
        ]

        self.mock_event_store.get_all_events.return_value = events

        ctx = InspectionContext(
            session_id="sess_001",
            filter_type=EventFilter.ALL,
        )

        timeline = self.console.inspect_event_timeline(ctx)

        self.assertEqual(timeline.event_count, 2)

    def test_inspect_with_time_filter(self):
        """Can inspect with time range filter."""
        now = datetime.now()
        start = now - timedelta(hours=1)

        events = [MagicMock(timestamp=now.isoformat(), aggregate_type="job", event_type="status")]
        self.mock_event_store.get_session_timeline.return_value = events

        ctx = InspectionContext(
            session_id="sess_001",
            filter_type=EventFilter.BY_SESSION,
            start_time=start,
            end_time=now,
        )

        timeline = self.console.inspect_event_timeline(ctx)

        self.assertEqual(timeline.event_count, 1)

    def test_inspect_empty_timeline(self):
        """Returns empty timeline when no events."""
        self.mock_event_store.get_session_timeline.return_value = []

        ctx = InspectionContext(session_id="sess_001")

        timeline = self.console.inspect_event_timeline(ctx)

        self.assertEqual(timeline.event_count, 0)


class TestRecoveryConsoleMemoryInspection(unittest.TestCase):
    """Tests for memory state inspection."""

    def setUp(self):
        """Set up mocks."""
        self.mock_event_store = MagicMock()
        self.mock_fact_store = MagicMock()
        self.console = RecoveryConsole(self.mock_event_store, self.mock_fact_store)

    def test_inspect_memory_state(self):
        """Can inspect current memory facts."""
        facts = [
            MagicMock(
                namespace="execution",
                source_event_id="evt_001",
                fact_id="fact_001",
            ),
            MagicMock(
                namespace="execution",
                source_event_id="evt_002",
                fact_id="fact_002",
            ),
        ]

        # New API: get_all_namespaces() then get_current_facts() per namespace
        self.mock_fact_store.get_all_namespaces.return_value = ["execution"]
        self.mock_fact_store.get_current_facts.return_value = facts

        ctx = InspectionContext(session_id="sess_001")

        snapshot = self.console.inspect_memory_state(ctx)

        self.assertEqual(snapshot.fact_count, 2)
        self.assertEqual(len(snapshot.namespaces), 1)

    def test_inspect_empty_memory(self):
        """Returns empty snapshot when no facts."""
        # New API
        self.mock_fact_store.get_all_namespaces.return_value = []
        self.mock_fact_store.get_current_facts.return_value = []

        ctx = InspectionContext(session_id="sess_001")

        snapshot = self.console.inspect_memory_state(ctx)

        self.assertEqual(snapshot.fact_count, 0)


class TestRecoveryConsoleFactInvalidation(unittest.TestCase):
    """Tests for fact invalidation."""

    def setUp(self):
        """Set up mocks."""
        self.mock_event_store = MagicMock()
        self.mock_fact_store = MagicMock()
        self.console = RecoveryConsole(self.mock_event_store, self.mock_fact_store)

    def test_invalidate_fact(self):
        """Can invalidate a fact."""
        fact = MagicMock(
            fact_id="fact_001",
            namespace="execution",
            object="enabled",  # Fixed: was object_value
        )

        self.mock_fact_store.get_current_facts.return_value = [fact]
        self.mock_fact_store.invalidate_fact.return_value = True  # New method

        invalidation = self.console.invalidate_fact(
            fact_id="fact_001",
            namespace="execution",
            reason="Incorrect state",
            invalidated_by="user_001",
        )

        self.assertEqual(invalidation.fact_id, "fact_001")
        self.assertEqual(invalidation.reason, "Incorrect state")
        self.assertEqual(invalidation.previous_value, "enabled")

    def test_invalidate_nonexistent_fact(self):
        """Handles invalidation of missing fact gracefully."""
        self.mock_fact_store.get_current_facts.return_value = []

        invalidation = self.console.invalidate_fact(
            fact_id="missing_001",
            namespace="execution",
            reason="Not found",
            invalidated_by="user_001",
        )

        self.assertEqual(invalidation.fact_id, "missing_001")
        self.assertEqual(invalidation.reason, "Not found")


class TestRecoveryConsoleFactHistory(unittest.TestCase):
    """Tests for fact history retrieval."""

    def setUp(self):
        """Set up mocks."""
        self.mock_event_store = MagicMock()
        self.mock_fact_store = MagicMock()
        self.console = RecoveryConsole(self.mock_event_store, self.mock_fact_store)

    def test_get_fact_history(self):
        """Can retrieve complete fact history."""
        facts = [
            MagicMock(fact_id="fact_001", object_value="v1"),
            MagicMock(fact_id="fact_001", object_value="v2"),
            MagicMock(fact_id="fact_001", object_value="v3"),
        ]

        self.mock_fact_store.get_fact_timeline.return_value = facts

        history = self.console.get_fact_history(
            namespace="execution",
            subject="skill_1",
            predicate="state",
        )

        self.assertEqual(len(history), 3)
        self.mock_fact_store.get_fact_timeline.assert_called_once()


class TestRecoveryConsoleActionCreation(unittest.TestCase):
    """Tests for recovery action creation."""

    def setUp(self):
        """Set up mocks."""
        self.mock_event_store = MagicMock()
        self.mock_fact_store = MagicMock()
        self.console = RecoveryConsole(self.mock_event_store, self.mock_fact_store)

    def test_create_inspect_events_action(self):
        """Can create event inspection action."""
        ctx = InspectionContext(session_id="sess_001")

        action = self.console.create_recovery_action(
            action_type=RecoveryActionType.INSPECT_EVENTS,
            context=ctx,
            parameters={"filter_type": "by_session"},
        )

        self.assertEqual(action.action_type, RecoveryActionType.INSPECT_EVENTS)
        self.assertIn("recover_", action.action_id)

    def test_create_invalidate_fact_action(self):
        """Can create fact invalidation action."""
        ctx = InspectionContext(session_id="sess_001")

        action = self.console.create_recovery_action(
            action_type=RecoveryActionType.INVALIDATE_FACT,
            context=ctx,
            parameters={"fact_id": "fact_001", "reason": "Incorrect"},
        )

        self.assertEqual(action.action_type, RecoveryActionType.INVALIDATE_FACT)
        self.assertIn("recover_", action.action_id)


class TestCreateRecoveryConsole(unittest.TestCase):
    """Tests for recovery console factory."""

    def test_creates_console_with_stores(self):
        """Factory creates console with dependencies."""
        mock_event_store = MagicMock()
        mock_fact_store = MagicMock()

        console = create_recovery_console(mock_event_store, mock_fact_store)

        self.assertIsInstance(console, RecoveryConsole)
        self.assertEqual(console.event_store, mock_event_store)
        self.assertEqual(console.fact_store, mock_fact_store)


if __name__ == "__main__":
    unittest.main()
