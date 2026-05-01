# -*- coding: utf-8 -*-
"""
Test suite for canonical_event_store.py

Tests cover:
- Event persistence and retrieval
- Query operations by various filters
- Timeline exports
- Integration with harness_store
"""

import unittest
import tempfile
import os
from datetime import datetime

from harness_canonical_events import (
    CanonicalEvent,
    CanonicalEventType,
    CanonicalEventBuilder,
)
from canonical_event_store import CanonicalEventStore, create_integrated_store


class TestCanonicalEventStore(unittest.TestCase):
    """Test CanonicalEventStore functionality."""
    
    def setUp(self):
        """Create temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_harness.db")
        self.store = CanonicalEventStore(self.db_path)
    
    def tearDown(self):
        """Clean up temporary files."""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)
    
    def test_store_initialization(self):
        """Test store initializes with schema."""
        self.assertTrue(os.path.exists(self.db_path))
    
    def test_append_and_retrieve_event(self):
        """Test appending and retrieving a single event."""
        event = CanonicalEventBuilder() \
            .with_job("job_123") \
            .with_event_type(CanonicalEventType.JOB_CREATED) \
            .build()
        
        self.store.append_event(event)
        retrieved = self.store.get_event_by_id(event.event_id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.event_id, event.event_id)
        self.assertEqual(retrieved.job_id, "job_123")
    
    def test_retrieve_nonexistent_event(self):
        """Test retrieving non-existent event returns None."""
        retrieved = self.store.get_event_by_id("nonexistent_123")
        self.assertIsNone(retrieved)
    
    def test_append_duplicate_event_raises_error(self):
        """Test that appending duplicate event_id raises error."""
        event = CanonicalEventBuilder() \
            .with_job("job_123") \
            .build()
        
        self.store.append_event(event)
        
        with self.assertRaises(Exception):  # sqlite3.IntegrityError
            self.store.append_event(event)
    
    def test_get_job_timeline(self):
        """Test retrieving all events for a job in chronological order."""
        job_id = "job_456"
        
        # Create multiple events for same job
        event1 = CanonicalEventBuilder() \
            .with_job(job_id) \
            .with_event_type(CanonicalEventType.JOB_CREATED) \
            .build()
        
        event2 = CanonicalEventBuilder() \
            .with_job(job_id) \
            .with_event_type(CanonicalEventType.JOB_STARTED) \
            .build()
        
        event3 = CanonicalEventBuilder() \
            .with_job(job_id) \
            .with_event_type(CanonicalEventType.JOB_COMPLETED) \
            .build()
        
        self.store.append_event(event1)
        self.store.append_event(event2)
        self.store.append_event(event3)
        
        timeline = self.store.get_job_timeline(job_id)
        
        self.assertEqual(len(timeline), 3)
        self.assertEqual(timeline[0].event_type, "job_created")
        self.assertEqual(timeline[1].event_type, "job_started")
        self.assertEqual(timeline[2].event_type, "job_completed")
    
    def test_get_session_timeline(self):
        """Test retrieving all events for a session."""
        session_id = "sess_789"
        
        event1 = CanonicalEventBuilder() \
            .with_session(session_id) \
            .with_job("job_1") \
            .build()
        
        event2 = CanonicalEventBuilder() \
            .with_session(session_id) \
            .with_job("job_2") \
            .build()
        
        self.store.append_event(event1)
        self.store.append_event(event2)
        
        timeline = self.store.get_session_timeline(session_id)
        
        self.assertEqual(len(timeline), 2)
    
    def test_get_events_by_type(self):
        """Test filtering events by type."""
        event1 = CanonicalEventBuilder() \
            .with_event_type(CanonicalEventType.JOB_COMPLETED) \
            .build()
        
        event2 = CanonicalEventBuilder() \
            .with_event_type(CanonicalEventType.JOB_FAILED) \
            .build()
        
        event3 = CanonicalEventBuilder() \
            .with_event_type(CanonicalEventType.JOB_COMPLETED) \
            .build()
        
        self.store.append_event(event1)
        self.store.append_event(event2)
        self.store.append_event(event3)
        
        completed_events = self.store.get_events_by_type(CanonicalEventType.JOB_COMPLETED.value)
        
        self.assertEqual(len(completed_events), 2)
        for event in completed_events:
            self.assertEqual(event.event_type, "job_completed")
    
    def test_get_events_by_aggregate(self):
        """Test filtering events by aggregate."""
        draft_id = "draft_999"
        
        event1 = CanonicalEventBuilder() \
            .with_aggregate('resource', draft_id) \
            .with_event_type(CanonicalEventType.RESOURCE_CREATED) \
            .build()
        
        event2 = CanonicalEventBuilder() \
            .with_aggregate('resource', draft_id) \
            .with_event_type(CanonicalEventType.RESOURCE_MODIFIED) \
            .build()
        
        self.store.append_event(event1)
        self.store.append_event(event2)
        
        events = self.store.get_events_by_aggregate('resource', draft_id)
        
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertEqual(event.aggregate_id, draft_id)
    
    def test_get_events_by_correlation_id(self):
        """Test retrieving linked events by correlation ID."""
        correlation_id = "flow_123"
        
        event1 = CanonicalEventBuilder() \
            .with_correlation_id(correlation_id) \
            .build()
        
        event2 = CanonicalEventBuilder() \
            .with_correlation_id(correlation_id) \
            .build()
        
        event3 = CanonicalEventBuilder() \
            .build()  # Different correlation ID
        
        self.store.append_event(event1)
        self.store.append_event(event2)
        self.store.append_event(event3)
        
        events = self.store.get_events_by_correlation_id(correlation_id)
        
        self.assertEqual(len(events), 2)
    
    def test_get_events_by_actor(self):
        """Test retrieving events by actor."""
        user_id = "user_abc"
        
        event1 = CanonicalEventBuilder() \
            .with_actor(user_id, 'user') \
            .build()
        
        event2 = CanonicalEventBuilder() \
            .with_actor(user_id, 'user') \
            .build()
        
        self.store.append_event(event1)
        self.store.append_event(event2)
        
        events = self.store.get_events_by_actor(user_id)
        
        self.assertEqual(len(events), 2)
    
    def test_get_events_by_severity(self):
        """Test retrieving events by severity."""
        event1 = CanonicalEventBuilder() \
            .with_severity("warning") \
            .build()
        
        event2 = CanonicalEventBuilder() \
            .with_severity("info") \
            .build()
        
        event3 = CanonicalEventBuilder() \
            .with_severity("warning") \
            .build()
        
        self.store.append_event(event1)
        self.store.append_event(event2)
        self.store.append_event(event3)
        
        warning_events = self.store.get_events_by_severity("warning")
        
        self.assertEqual(len(warning_events), 2)
    
    def test_get_error_events(self):
        """Test retrieving error events."""
        event1 = CanonicalEventBuilder() \
            .with_severity("info") \
            .build()
        
        event2 = CanonicalEventBuilder() \
            .with_error("ERR_001", "Test error", "error") \
            .build()
        
        event3 = CanonicalEventBuilder() \
            .with_error("ERR_002", "Critical error", "critical") \
            .build()
        
        self.store.append_event(event1)
        self.store.append_event(event2)
        self.store.append_event(event3)
        
        error_events = self.store.get_error_events()
        
        self.assertEqual(len(error_events), 2)
        for event in error_events:
            self.assertIn(event.severity, ('error', 'critical'))
    
    def test_get_event_count(self):
        """Test getting total event count."""
        self.assertEqual(self.store.get_event_count(), 0)
        
        for i in range(5):
            event = CanonicalEventBuilder().build()
            self.store.append_event(event)
        
        self.assertEqual(self.store.get_event_count(), 5)
    
    def test_export_job_timeline(self):
        """Test exporting job timeline as report."""
        job_id = "job_export_test"
        
        for i in range(3):
            event = CanonicalEventBuilder() \
                .with_job(job_id) \
                .build()
            self.store.append_event(event)
        
        report = self.store.export_job_timeline(job_id)
        
        self.assertEqual(report['job_id'], job_id)
        self.assertEqual(report['event_count'], 3)
        self.assertEqual(len(report['events']), 3)
        self.assertIsNotNone(report['start_time'])
        self.assertIsNotNone(report['end_time'])
        self.assertIsNotNone(report['exported_at'])
    
    def test_export_session_timeline(self):
        """Test exporting session timeline as report."""
        session_id = "sess_export_test"
        
        for i in range(3):
            event = CanonicalEventBuilder() \
                .with_session(session_id) \
                .build()
            self.store.append_event(event)
        
        report = self.store.export_session_timeline(session_id)
        
        self.assertEqual(report['session_id'], session_id)
        self.assertEqual(report['event_count'], 3)
    
    def test_export_correlation_flow(self):
        """Test exporting correlation flow as report."""
        correlation_id = "flow_export_test"
        
        for i in range(3):
            event = CanonicalEventBuilder() \
                .with_correlation_id(correlation_id) \
                .build()
            self.store.append_event(event)
        
        report = self.store.export_correlation_flow(correlation_id)
        
        self.assertEqual(report['correlation_id'], correlation_id)
        self.assertEqual(report['event_count'], 3)
    
    def test_event_persistence_with_full_details(self):
        """Test storing and retrieving event with all fields populated."""
        event = CanonicalEventBuilder() \
            .with_event_type(CanonicalEventType.RESOURCE_MODIFIED) \
            .with_job("job_full") \
            .with_session("sess_full") \
            .with_user("user_full") \
            .with_actor("actor_full", "user") \
            .with_aggregate("resource", "res_full") \
            .with_payload({"data": "test"}) \
            .with_severity("warning") \
            .with_state_change({"old": 1}, {"new": 2}) \
            .with_error("ERR_TEST", "Test error") \
            .with_correlation_id("corr_full") \
            .with_source("test_source") \
            .build()
        
        self.store.append_event(event)
        retrieved = self.store.get_event_by_id(event.event_id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.job_id, "job_full")
        self.assertEqual(retrieved.session_id, "sess_full")
        self.assertEqual(retrieved.user_id, "user_full")
        self.assertEqual(retrieved.actor_id, "actor_full")
        self.assertEqual(retrieved.payload, {"data": "test"})
        self.assertEqual(retrieved.previous_state, {"old": 1})
        self.assertEqual(retrieved.new_state, {"new": 2})
        self.assertEqual(retrieved.error_code, "ERR_TEST")
        self.assertEqual(retrieved.source, "test_source")


class TestIntegratedStore(unittest.TestCase):
    """Test integrated store creation."""
    
    def setUp(self):
        """Create temporary database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_integrated.db")
        self.base_store = None
        self.canonical_store = None
    
    def tearDown(self):
        """Clean up."""
        # Close any open connections
        if self.base_store:
            try:
                if hasattr(self.base_store, 'close'):
                    self.base_store.close()
            except:
                pass
        if self.canonical_store:
            del self.canonical_store
        
        # Give file system time to release lock
        import time
        time.sleep(0.1)
        
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except:
                pass
        try:
            os.rmdir(self.temp_dir)
        except:
            pass
    
    def test_create_integrated_store(self):
        """Test creating both stores together."""
        self.base_store, self.canonical_store = create_integrated_store(self.db_path)
        
        self.assertIsNotNone(self.base_store)
        self.assertIsNotNone(self.canonical_store)
        
        # Test that they share the same database
        event = CanonicalEventBuilder().with_job("job_integrated").build()
        self.canonical_store.append_event(event)
        
        retrieved = self.canonical_store.get_event_by_id(event.event_id)
        self.assertIsNotNone(retrieved)


class TestEventStoreQueries(unittest.TestCase):
    """Test complex query scenarios."""
    
    def setUp(self):
        """Create test database with sample data."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_queries.db")
        self.store = CanonicalEventStore(self.db_path)
        self._populate_test_data()
    
    def tearDown(self):
        """Clean up."""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)
    
    def _populate_test_data(self):
        """Populate store with sample events."""
        # Create 2 jobs with multiple events each
        for job_num in range(1, 3):
            job_id = f"job_{job_num}"
            for event_num in range(1, 4):
                event = CanonicalEventBuilder() \
                    .with_job(job_id) \
                    .with_session(f"sess_{job_num}") \
                    .with_event_type(
                        CanonicalEventType.JOB_CREATED
                        if event_num == 1
                        else CanonicalEventType.JOB_STARTED
                        if event_num == 2
                        else CanonicalEventType.JOB_COMPLETED
                    ) \
                    .build()
                self.store.append_event(event)
    
    def test_query_multiple_jobs(self):
        """Test querying multiple jobs independently."""
        timeline1 = self.store.get_job_timeline("job_1")
        timeline2 = self.store.get_job_timeline("job_2")
        
        self.assertEqual(len(timeline1), 3)
        self.assertEqual(len(timeline2), 3)
        
        all_events = timeline1 + timeline2
        self.assertEqual(len(all_events), 6)
    
    def test_query_combined_filters(self):
        """Test that events can be found with different filters."""
        job_events = self.store.get_job_timeline("job_1")
        session_events = self.store.get_session_timeline("sess_1")
        
        self.assertEqual(len(job_events), 3)
        self.assertEqual(len(session_events), 3)
        self.assertEqual(job_events, session_events)


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestCanonicalEventStore))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegratedStore))
    suite.addTests(loader.loadTestsFromTestCase(TestEventStoreQueries))
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == '__main__':
    result = run_tests()
    exit(0 if result.wasSuccessful() else 1)
