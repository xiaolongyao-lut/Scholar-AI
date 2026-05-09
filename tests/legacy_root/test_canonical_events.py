# -*- coding: utf-8 -*-
"""
Test suite for harness_canonical_events.py

Tests cover:
- CanonicalEvent creation and validation
- CanonicalEventBuilder fluent API
- Converting from WritingEvent
- Converting from AuditEvent
- Converting from RevisionEvent
- Event type mapping
- Round-trip serialization
"""

import unittest
from harness_canonical_events import (
    CanonicalEvent,
    CanonicalEventType,
    CanonicalEventBuilder,
    EventConverter,
    create_job_event,
    create_resource_event,
    create_error_event,
)


class TestCanonicalEvent(unittest.TestCase):
    """Test CanonicalEvent dataclass."""
    
    def test_create_minimal_event(self):
        """Test creating minimal CanonicalEvent."""
        event = CanonicalEvent(
            event_id="evt_001",
            correlation_id="evt_001",
            timestamp="2026-04-09T12:00:00Z",
            event_type=CanonicalEventType.JOB_CREATED.value,
            aggregate_id="job_123",
        )
        self.assertEqual(event.event_id, "evt_001")
        self.assertEqual(event.event_type, "job_created")
        self.assertFalse(event.is_error())
    
    def test_event_immutability(self):
        """Test that CanonicalEvent is frozen."""
        event = CanonicalEvent(
            event_id="evt_001",
            correlation_id="evt_001",
            timestamp="2026-04-09T12:00:00Z",
            event_type="job_created",
            aggregate_id="job_123",
        )
        with self.assertRaises(Exception):  # FrozenInstanceError
            event.event_id = "evt_002"
    
    def test_to_dict_serialization(self):
        """Test serialization to dict."""
        event = CanonicalEvent(
            event_id="evt_001",
            correlation_id="evt_001",
            timestamp="2026-04-09T12:00:00Z",
            event_type="job_created",
            aggregate_id="job_123",
            job_id="job_123",
            payload={"key": "value"},
        )
        data = event.to_dict()
        self.assertEqual(data['event_id'], "evt_001")
        self.assertEqual(data['job_id'], "job_123")
        self.assertEqual(data['payload'], {"key": "value"})
    
    def test_is_error(self):
        """Test error detection."""
        normal_event = CanonicalEvent(
            event_id="evt_001",
            correlation_id="evt_001",
            timestamp="2026-04-09T12:00:00Z",
            event_type="job_completed",
            aggregate_id="job_123",
        )
        self.assertFalse(normal_event.is_error())
        
        error_event = CanonicalEvent(
            event_id="evt_002",
            correlation_id="evt_002",
            timestamp="2026-04-09T12:00:00Z",
            event_type="error_occurred",
            aggregate_id="job_123",
            severity="error",
        )
        self.assertTrue(error_event.is_error())
    
    def test_aggregate_type_checks(self):
        """Test aggregate type checking methods."""
        job_event = CanonicalEvent(
            event_id="evt_001",
            correlation_id="evt_001",
            timestamp="2026-04-09T12:00:00Z",
            event_type="job_created",
            aggregate_type="job",
            aggregate_id="job_123",
        )
        self.assertTrue(job_event.is_job_event())
        self.assertFalse(job_event.is_resource_event())
        self.assertFalse(job_event.is_capability_event())
        
        resource_event = CanonicalEvent(
            event_id="evt_002",
            correlation_id="evt_002",
            timestamp="2026-04-09T12:00:00Z",
            event_type="resource_modified",
            aggregate_type="resource",
            aggregate_id="draft_456",
        )
        self.assertFalse(resource_event.is_job_event())
        self.assertTrue(resource_event.is_resource_event())
        self.assertFalse(resource_event.is_capability_event())


class TestCanonicalEventBuilder(unittest.TestCase):
    """Test CanonicalEventBuilder fluent API."""
    
    def test_builder_minimal(self):
        """Test building minimal event."""
        event = CanonicalEventBuilder().build()
        self.assertIsNotNone(event.event_id)
        self.assertEqual(event.event_id, event.correlation_id)
        self.assertIsNotNone(event.timestamp)
    
    def test_builder_with_job(self):
        """Test builder with job."""
        event = CanonicalEventBuilder() \
            .with_job("job_123") \
            .with_event_type(CanonicalEventType.JOB_STARTED) \
            .build()
        self.assertEqual(event.job_id, "job_123")
        self.assertEqual(event.aggregate_id, "job_123")
        self.assertEqual(event.event_type, "job_started")
    
    def test_builder_with_user(self):
        """Test builder with user."""
        event = CanonicalEventBuilder() \
            .with_user("user_456") \
            .build()
        self.assertEqual(event.user_id, "user_456")
        self.assertEqual(event.actor_id, "user_456")
        self.assertEqual(event.actor_type, "user")
    
    def test_builder_chaining(self):
        """Test full builder chain."""
        event = CanonicalEventBuilder() \
            .with_event_type(CanonicalEventType.JOB_COMPLETED) \
            .with_aggregate("job", "job_123") \
            .with_session("sess_789") \
            .with_user("user_456") \
            .with_payload({"result": "success"}) \
            .with_severity("info") \
            .with_correlation_id("corr_001") \
            .build()
        
        self.assertEqual(event.event_type, "job_completed")
        self.assertEqual(event.aggregate_type, "job")
        self.assertEqual(event.aggregate_id, "job_123")
        self.assertEqual(event.session_id, "sess_789")
        self.assertEqual(event.actor_id, "user_456")
        self.assertEqual(event.payload["result"], "success")
        self.assertEqual(event.correlation_id, "corr_001")
    
    def test_builder_with_state_change(self):
        """Test builder with state tracking."""
        prev = {"status": "pending"}
        new = {"status": "completed"}
        event = CanonicalEventBuilder() \
            .with_state_change(prev, new) \
            .build()
        self.assertEqual(event.previous_state, prev)
        self.assertEqual(event.new_state, new)
    
    def test_builder_with_error(self):
        """Test builder with error info."""
        event = CanonicalEventBuilder() \
            .with_error("ERR_TIMEOUT", "Job execution timed out", "error") \
            .build()
        self.assertEqual(event.error_code, "ERR_TIMEOUT")
        self.assertEqual(event.error_message, "Job execution timed out")
        self.assertEqual(event.severity, "error")
        self.assertTrue(event.is_error())


class TestEventConverter(unittest.TestCase):
    """Test EventConverter for converting from various source types."""
    
    def test_converter_from_revision(self):
        """Test converting from WritingRevision."""
        event = EventConverter.from_revision(
            revision_id="rev_001",
            draft_id="draft_123",
            timestamp="2026-04-09T12:00:00Z",
            revision_number=2,
            created_by="user_456",
            notes="Updated section 2",
            session_id="sess_789",
            previous_content="Old content",
            new_content="New content",
        )
        
        self.assertEqual(event.aggregate_type, "resource")
        self.assertEqual(event.aggregate_id, "draft_123")
        self.assertEqual(event.event_type, "resource_modified")
        self.assertEqual(event.actor_id, "user_456")
        self.assertEqual(event.source, "resource_manager")
        self.assertEqual(event.payload["revision_number"], 2)
        self.assertEqual(event.previous_state["content"], "Old content")
        self.assertEqual(event.new_state["content"], "New content")
    
    def test_converter_circular_compat(self):
        """Test that converters maintain data integrity."""
        # Create event with converters
        rev_event = EventConverter.from_revision(
            revision_id="rev_002",
            draft_id="draft_456",
            timestamp="2026-04-09T13:00:00Z",
            revision_number=3,
            created_by="user_789",
        )
        
        # Verify canonical event preserves info
        self.assertIsNotNone(rev_event.event_id)
        self.assertEqual(rev_event.timestamp, "2026-04-09T13:00:00Z")
        self.assertEqual(rev_event.actor_id, "user_789")
        
        # Serialize and restore
        data = rev_event.to_dict()
        restored = CanonicalEvent(**data)
        self.assertEqual(restored.event_id, rev_event.event_id)
        self.assertEqual(restored.aggregate_id, rev_event.aggregate_id)


class TestConvenienceFunctions(unittest.TestCase):
    """Test convenience factory functions."""
    
    def test_create_job_event(self):
        """Test creating job event."""
        event = create_job_event(
            job_id="job_123",
            event_type=CanonicalEventType.JOB_STARTED,
            session_id="sess_789",
            payload={"start_time": "2026-04-09T12:00:00Z"},
            actor_id="user_456",
        )
        self.assertEqual(event.job_id, "job_123")
        self.assertEqual(event.aggregate_id, "job_123")
        self.assertEqual(event.event_type, "job_started")
    
    def test_create_resource_event(self):
        """Test creating resource event."""
        event = create_resource_event(
            aggregate_id="draft_123",
            event_type="resource_modified",
            payload={"section": "introduction"},
            actor_id="user_456",
            previous_state={"version": 1},
            new_state={"version": 2},
        )
        self.assertEqual(event.aggregate_id, "draft_123")
        self.assertEqual(event.aggregate_type, "resource")
        self.assertEqual(event.previous_state["version"], 1)
    
    def test_create_error_event(self):
        """Test creating error event."""
        event = create_error_event(
            aggregate_type="job",
            aggregate_id="job_123",
            error_code="ERR_EXEC_FAIL",
            error_message="Execution failed",
            context={"reason": "out_of_memory"},
            job_id="job_123",
            session_id="sess_789",
        )
        self.assertEqual(event.event_type, "error_occurred")
        self.assertEqual(event.error_code, "ERR_EXEC_FAIL")
        self.assertTrue(event.is_error())


class TestEventTypeEnum(unittest.TestCase):
    """Test CanonicalEventType enum."""
    
    def test_all_event_types_present(self):
        """Test that all expected event types exist."""
        # Job events
        self.assertIn("job_created", [e.value for e in CanonicalEventType])
        self.assertIn("job_completed", [e.value for e in CanonicalEventType])
        
        # Capability events
        self.assertIn("execution_started", [e.value for e in CanonicalEventType])
        self.assertIn("execution_completed", [e.value for e in CanonicalEventType])
        
        # Resource events
        self.assertIn("resource_modified", [e.value for e in CanonicalEventType])
        
        # Error events
        self.assertIn("error_occurred", [e.value for e in CanonicalEventType])
    
    def test_event_type_uniqueness(self):
        """Test that all event type values are unique."""
        values = [e.value for e in CanonicalEventType]
        self.assertEqual(len(values), len(set(values)))
    
    def test_event_type_string_conversion(self):
        """Test string value conversion."""
        event_type = CanonicalEventType.JOB_CREATED
        self.assertEqual(event_type.value, "job_created")
        self.assertEqual(str(event_type), "CanonicalEventType.JOB_CREATED")


class TestEventBuilderConstructorEdgeCases(unittest.TestCase):
    """Test edge cases in event creation."""
    
    def test_builder_with_no_actor_id(self):
        """Test builder without actor (should default to system)."""
        event = CanonicalEventBuilder().build()
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.actor_type, "system")
    
    def test_builder_with_empty_payload(self):
        """Test builder with empty payload."""
        event = CanonicalEventBuilder() \
            .with_payload({}) \
            .build()
        self.assertEqual(event.payload, {})
    
    def test_event_with_special_characters(self):
        """Test event with special characters."""
        event = CanonicalEventBuilder() \
            .with_payload({"message": "测试中文 @ #$%^&*()"}) \
            .build()
        self.assertIn("中文", event.payload["message"])
    
    def test_event_correlation_chain(self):
        """Test correlation ID for linked events."""
        correlation_id = "flow_abc123"
        event1 = CanonicalEventBuilder() \
            .with_correlation_id(correlation_id) \
            .build()
        event2 = CanonicalEventBuilder() \
            .with_correlation_id(correlation_id) \
            .build()
        
        self.assertEqual(event1.correlation_id, event2.correlation_id)
        self.assertNotEqual(event1.event_id, event2.event_id)


class TestEventSerialization(unittest.TestCase):
    """Test serialization and deserialization."""
    
    def test_event_to_dict_and_back(self):
        """Test serializing and restoring event."""
        original = CanonicalEventBuilder() \
            .with_event_type(CanonicalEventType.JOB_COMPLETED) \
            .with_job("job_123") \
            .with_session("sess_789") \
            .with_payload({"result": "success"}) \
            .build()
        
        # Serialize
        data = original.to_dict()
        
        # Restore
        restored = CanonicalEvent(**data)
        
        # Verify
        self.assertEqual(restored.event_id, original.event_id)
        self.assertEqual(restored.job_id, original.job_id)
        self.assertEqual(restored.payload, original.payload)
    
    def test_dict_serialization_includes_all_fields(self):
        """Test that to_dict includes all fields."""
        event = CanonicalEventBuilder() \
            .with_job("job_123") \
            .with_user("user_456") \
            .with_error("ERR_TEST", "Test error") \
            .build()
        
        data = event.to_dict()
        self.assertIn('event_id', data)
        self.assertIn('job_id', data)
        self.assertIn('user_id', data)
        self.assertIn('error_code', data)
        self.assertIn('error_message', data)


class TestEventComparison(unittest.TestCase):
    """Test comparing and classifying events."""
    
    def test_event_is_job_event(self):
        """Test job event classification."""
        event = CanonicalEventBuilder() \
            .with_aggregate("job", "job_123") \
            .build()
        self.assertTrue(event.is_job_event())
    
    def test_event_is_resource_event(self):
        """Test resource event classification."""
        event = CanonicalEventBuilder() \
            .with_aggregate("resource", "draft_123") \
            .build()
        self.assertTrue(event.is_resource_event())
    
    def test_event_is_capability_event(self):
        """Test capability event classification."""
        event = CanonicalEventBuilder() \
            .with_aggregate("capability", "cap_123") \
            .build()
        self.assertTrue(event.is_capability_event())


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestCanonicalEvent))
    suite.addTests(loader.loadTestsFromTestCase(TestCanonicalEventBuilder))
    suite.addTests(loader.loadTestsFromTestCase(TestEventConverter))
    suite.addTests(loader.loadTestsFromTestCase(TestConvenienceFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestEventTypeEnum))
    suite.addTests(loader.loadTestsFromTestCase(TestEventBuilderConstructorEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestEventSerialization))
    suite.addTests(loader.loadTestsFromTestCase(TestEventComparison))
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == '__main__':
    result = run_tests()
    exit(0 if result.wasSuccessful() else 1)
