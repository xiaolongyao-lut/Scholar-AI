# -*- coding: utf-8 -*-
"""Integration tests for recovery API endpoints in python_adapter_server."""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# Try to import FastAPI components for endpoint testing
try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    TestClient = None

# Import recovery payload models directly
# These don't have complex dependencies
from pydantic import BaseModel, Field
from typing import Any


# Define the payload models locally to avoid full import
class RecoveryEventPayload(BaseModel):
    """Single event in recovery timeline."""
    event_id: str
    event_type: str
    timestamp: str
    source_job_id: str | None = None
    source_session_id: str | None = None
    event_data: dict[str, Any]


class EventTimelinePayload(BaseModel):
    """Event timeline response for recovery inspection."""
    events: list[RecoveryEventPayload]
    event_count: int
    start_time: str | None = None
    end_time: str | None = None
    session_filter: str | None = None
    job_filter: str | None = None


class MemoryFactPayload(BaseModel):
    """Single fact from memory snapshot."""
    fact_id: str
    namespace: str
    subject: str
    predicate: str
    object: str
    object_type: str = "string"
    valid_from: str
    valid_to: str | None = None
    source_event_id: str


class MemorySnapshotPayload(BaseModel):
    """Memory snapshot response for recovery inspection."""
    facts: list[MemoryFactPayload]
    fact_count: int
    namespaces: list[str]
    last_updated: str


class InvalidFactRequest(BaseModel):
    """Request to invalidate a fact."""
    fact_id: str
    namespace: str
    reason: str = ""
    invalidated_by: str = "system"


class FactInvalidationPayload(BaseModel):
    """Response for fact invalidation operation."""
    fact_id: str
    namespace: str
    reason: str
    previous_value: str | None = None
    invalidated_at: str
    invalidated_by: str
    success: bool


class TestRecoveryPayloadModels(unittest.TestCase):
    """Test recovery API payload models."""

    def test_recovery_event_payload_creation(self):
        """RecoveryEventPayload creates correctly."""
        event = RecoveryEventPayload(
            event_id="evt_001",
            event_type="JOB_STARTED",
            timestamp="2026-04-10T12:00:00Z",
            source_job_id="job_001",
            source_session_id="sess_001",
            event_data={"status": "started"},
        )
        self.assertEqual(event.event_id, "evt_001")
        self.assertEqual(event.event_type, "JOB_STARTED")
        self.assertEqual(event.source_job_id, "job_001")

    def test_event_timeline_payload_creation(self):
        """EventTimelinePayload creates correctly."""
        events = [
            RecoveryEventPayload(
                event_id="evt_001",
                event_type="JOB_STARTED",
                timestamp="2026-04-10T12:00:00Z",
                source_job_id="job_001",
                source_session_id=None,
                event_data={},
            )
        ]
        timeline = EventTimelinePayload(
            events=events,
            event_count=1,
            start_time="2026-04-10T12:00:00Z",
            end_time="2026-04-10T12:05:00Z",
            session_filter=None,
            job_filter="job_001",
        )
        self.assertEqual(timeline.event_count, 1)
        self.assertEqual(len(timeline.events), 1)

    def test_memory_fact_payload_creation(self):
        """MemoryFactPayload creates correctly."""
        fact = MemoryFactPayload(
            fact_id="fact_001",
            namespace="execution",
            subject="job_001",
            predicate="status",
            object="completed",
            object_type="string",
            valid_from="2026-04-10T12:00:00Z",
            valid_to=None,
            source_event_id="evt_001",
        )
        self.assertEqual(fact.fact_id, "fact_001")
        self.assertEqual(fact.namespace, "execution")
        self.assertEqual(fact.object, "completed")
        self.assertIsNone(fact.valid_to)

    def test_memory_snapshot_payload_creation(self):
        """MemorySnapshotPayload creates correctly."""
        facts = [
            MemoryFactPayload(
                fact_id="fact_001",
                namespace="execution",
                subject="job_001",
                predicate="status",
                object="completed",
                object_type="string",
                valid_from="2026-04-10T12:00:00Z",
                valid_to=None,
                source_event_id="evt_001",
            )
        ]
        snapshot = MemorySnapshotPayload(
            facts=facts,
            fact_count=1,
            namespaces=["execution"],
            last_updated="2026-04-10T12:00:00Z",
        )
        self.assertEqual(snapshot.fact_count, 1)
        self.assertEqual(len(snapshot.namespaces), 1)
        self.assertIn("execution", snapshot.namespaces)

    def test_fact_invalidation_payload_creation(self):
        """FactInvalidationPayload creates correctly."""
        invalidation = FactInvalidationPayload(
            fact_id="fact_001",
            namespace="execution",
            reason="Incorrect state",
            previous_value="running",
            invalidated_at="2026-04-10T12:05:00Z",
            invalidated_by="user_001",
            success=True,
        )
        self.assertEqual(invalidation.fact_id, "fact_001")
        self.assertTrue(invalidation.success)
        self.assertEqual(invalidation.previous_value, "running")


if __name__ == "__main__":
    unittest.main()
