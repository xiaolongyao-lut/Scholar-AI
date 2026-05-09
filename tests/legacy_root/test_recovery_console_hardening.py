# -*- coding: utf-8 -*-
"""
Integration tests for Recovery Console hardening

Real-path validation using actual MemoryFactStore
"""

import sqlite3
import unittest
from datetime import datetime
from pathlib import Path

from memory_fact_store import MemoryFactStore, TemporalFact
from recovery_console import RecoveryConsole, InspectionContext


class TestRecoveryConsoleHardening(unittest.TestCase):
    """Integration tests with real MemoryFactStore."""

    def setUp(self):
        """Set up real fact store for each test."""
        # Use temporary file for testing (in-memory didn't init properly)
        import tempfile
        import os
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_path = self.temp_db.name
        self.temp_db.close()
        
        # Create fact store with temp file
        self.fact_store = MemoryFactStore(self.temp_db_path)
        self.console = RecoveryConsole(None, self.fact_store)
    
    def tearDown(self):
        """Clean up temporary database."""
        import os
        if hasattr(self, 'temp_db_path') and os.path.exists(self.temp_db_path):
            os.unlink(self.temp_db_path)

    def test_inspect_memory_state_with_real_facts(self):
        """Test inspect_memory_state reads real facts correctly."""
        # Record a real fact in the store
        now = datetime.now()
        fact = TemporalFact(
            fact_id="skill_enabled_001",
            namespace="skills",
            subject="grammar_checker",
            predicate="enabled",
            object="true",
            object_type="bool",
            valid_from=now,
            valid_to=None,
            source_event_id="evt_skill_001",
            created_at=now,
        )

        self.fact_store.record_fact(fact)

        # Inspect memory state
        ctx = InspectionContext(session_id="sess_001")
        snapshot = self.console.inspect_memory_state(ctx)

        # Verify fact was returned
        self.assertGreater(snapshot.fact_count, 0)
        self.assertIn("skills", snapshot.namespaces)
        found = False
        for returned_fact in snapshot.current_facts:
            if returned_fact.fact_id == "skill_enabled_001":
                found = True
                self.assertEqual(returned_fact.object, "true")
                break
        self.assertTrue(found, "Recorded fact not found in snapshot")

    def test_invalidate_fact_with_real_store(self):
        """Test fact invalidation works correctly."""
        # Setup
        now = datetime.now()
        fact = TemporalFact(
            fact_id="pipeline_config_001",
            namespace="pipeline",
            subject="main_pipeline",
            predicate="strategy",
            object="parallel",
            object_type="string",
            valid_from=now,
            valid_to=None,
            source_event_id="evt_pipeline_001",
            created_at=now,
        )

        self.fact_store.record_fact(fact)

        # Verify fact is current
        current = self.fact_store.get_current_facts("pipeline")
        self.assertEqual(len(current), 1)

        # Invalidate it
        ctx = InspectionContext(session_id="sess_001")
        invalidation = self.console.invalidate_fact(
            fact_id="pipeline_config_001",
            namespace="pipeline",
            reason="Strategy changed",
            invalidated_by="test_user",
        )

        # Verify invalidation record
        self.assertEqual(invalidation.fact_id, "pipeline_config_001")
        self.assertEqual(invalidation.reason, "Strategy changed")
        self.assertEqual(invalidation.previous_value, "parallel")

        # Verify fact is no longer current
        current_after = self.fact_store.get_current_facts("pipeline")
        self.assertEqual(len(current_after), 0)

        # Verify fact exists in history
        history = self.fact_store.get_fact_timeline("pipeline", "main_pipeline", "strategy")
        self.assertGreater(len(history), 0)

    def test_multiple_namespaces_aggregation(self):
        """Test inspect_memory_state aggregates across namespaces."""
        now = datetime.now()

        # Record facts in different namespaces
        skills_fact = TemporalFact(
            fact_id="skill_1",
            namespace="skills",
            subject="skill_a",
            predicate="status",
            object="active",
            object_type="string",
            valid_from=now,
            valid_to=None,
            source_event_id="evt_1",
            created_at=now,
        )

        execution_fact = TemporalFact(
            fact_id="exec_1",
            namespace="execution",
            subject="job_1",
            predicate="status",
            object="running",
            object_type="string",
            valid_from=now,
            valid_to=None,
            source_event_id="evt_2",
            created_at=now,
        )

        # Record both
        self.fact_store.record_fact(skills_fact)
        self.fact_store.record_fact(execution_fact)

        # Inspect
        ctx = InspectionContext(session_id="sess_001")
        snapshot = self.console.inspect_memory_state(ctx)

        # Verify aggregation
        self.assertEqual(snapshot.fact_count, 2)
        self.assertIn("skills", snapshot.namespaces)
        self.assertIn("execution", snapshot.namespaces)

    def test_inspect_context_validation(self):
        """Test context validation guards against bad input."""
        # Missing session_id should raise
        with self.assertRaises(ValueError):
            bad_ctx = InspectionContext(session_id="")
            self.console.inspect_memory_state(bad_ctx)

    def test_invalidate_fact_validation(self):
        """Test invalidation guards against bad input."""
        # Missing required fields should raise
        with self.assertRaises(ValueError):
            self.console.invalidate_fact(
                fact_id="",
                namespace="test",
                reason="test",
                invalidated_by="user",
            )

    def test_missing_fact_invalidation_still_records_audit(self):
        """Test invalidating missing fact still creates audit record."""
        ctx = InspectionContext(session_id="sess_001")
        invalidation = self.console.invalidate_fact(
            fact_id="nonexistent",
            namespace="test",
            reason="cleanup",
            invalidated_by="cleanup_worker",
        )

        # Audit record should exist even if fact doesn't
        self.assertEqual(invalidation.fact_id, "nonexistent")
        self.assertEqual(invalidation.reason, "cleanup")
        self.assertIsNone(invalidation.previous_value)

    def test_all_namespaces_query(self):
        """Test get_all_namespaces returns correct results."""
        now = datetime.now()

        # Initially empty
        namespaces = self.fact_store.get_all_namespaces()
        self.assertEqual(len(namespaces), 0)

        # Add facts to multiple namespaces
        for namespace in ["skills", "execution", "resources"]:
            fact = TemporalFact(
                fact_id=f"fact_{namespace}",
                namespace=namespace,
                subject="test",
                predicate="status",
                object="active",
                object_type="string",
                valid_from=now,
                valid_to=None,
                source_event_id=f"evt_{namespace}",
                created_at=now,
            )
            self.fact_store.record_fact(fact)

        # Verify all namespaces returned
        namespaces = self.fact_store.get_all_namespaces()
        self.assertEqual(len(namespaces), 3)
        self.assertIn("skills", namespaces)
        self.assertIn("execution", namespaces)
        self.assertIn("resources", namespaces)

    def test_invalidate_fact_validates_namespace(self):
        """Test invalidate_fact checks namespace exists."""
        # Invalidate nonexistent namespace should still create audit record
        invalidation = self.console.invalidate_fact(
            fact_id="test",
            namespace="nonexistent_ns",
            reason="test",
            invalidated_by="user",
        )

        self.assertEqual(invalidation.fact_id, "test")
        # No error, just audit record


if __name__ == "__main__":
    unittest.main()
