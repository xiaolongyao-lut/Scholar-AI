# -*- coding: utf-8 -*-
"""Tests for recovery execution engine."""

import unittest
import tempfile
import os
from unittest.mock import MagicMock, patch

from datetime_utils import utc_now_naive

from recovery_execution_engine import (
    RecoveryExecutionEngine,
    ActionExecutionStatus,
    ExecutionResult,
)
from recovery_console import (
    RecoveryConsole,
    RecoveryAction,
    RecoveryActionType,
    InspectionContext,
)
from memory_fact_store import MemoryFactStore, TemporalFact
from canonical_event_store import CanonicalEventStore


class TestExecutionEngine(unittest.TestCase):
    """Test recovery execution engine."""

    def setUp(self):
        """Set up test engine with temporary databases."""
        # Create temporary database files
        self.temp_db_event = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_event_path = self.temp_db_event.name
        self.temp_db_event.close()

        self.temp_db_fact = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db_fact_path = self.temp_db_fact.name
        self.temp_db_fact.close()

        # Initialize stores
        self.event_store = CanonicalEventStore(self.temp_db_event_path)
        self.fact_store = MemoryFactStore(self.temp_db_fact_path)
        self.console = RecoveryConsole(self.event_store, self.fact_store)
        self.engine = RecoveryExecutionEngine(
            self.console, self.event_store, self.fact_store
        )

    def tearDown(self):
        """Clean up temporary databases."""
        if os.path.exists(self.temp_db_event_path):
            os.unlink(self.temp_db_event_path)
        if os.path.exists(self.temp_db_fact_path):
            os.unlink(self.temp_db_fact_path)

    def test_engine_initialization(self):
        """Engine initializes with required components."""
        self.assertIsNotNone(self.engine.console)
        self.assertIsNotNone(self.engine.event_store)
        self.assertIsNotNone(self.engine.fact_store)

    def test_replay_job_requires_job_id(self):
        """REPLAY_JOB validates job_id parameter."""
        action = RecoveryAction(
            action_id="action_001",
            action_type=RecoveryActionType.REPLAY_JOB,
            context=InspectionContext(session_id="sess_001"),
            timestamp=utc_now_naive(),
            parameters={},  # Missing job_id
        )

        result = self.engine.execute_action(action)

        self.assertEqual(result.status, ActionExecutionStatus.FAILED)
        self.assertIn("job_id", result.error)

    def test_rebuild_wakeup_requires_session_id(self):
        """REBUILD_WAKEUP validates session_id parameter."""
        action = RecoveryAction(
            action_id="action_002",
            action_type=RecoveryActionType.REBUILD_WAKEUP,
            context=InspectionContext(session_id="sess_001"),
            timestamp=utc_now_naive(),
            parameters={},  # Missing session_id
        )

        result = self.engine.execute_action(action)

        self.assertEqual(result.status, ActionExecutionStatus.FAILED)
        self.assertIn("session_id", result.error)

    def test_rehydrate_runtime_requires_session_id(self):
        """REHYDRATE_RUNTIME validates session_id parameter."""
        action = RecoveryAction(
            action_id="action_003",
            action_type=RecoveryActionType.REHYDRATE_RUNTIME,
            context=InspectionContext(session_id="sess_001"),
            timestamp=utc_now_naive(),
            parameters={},  # Missing session_id
        )

        result = self.engine.execute_action(action)

        self.assertEqual(result.status, ActionExecutionStatus.FAILED)
        self.assertIn("session_id", result.error)

    def test_replay_job_execution_success(self):
        """REPLAY_JOB executes successfully with valid job_id."""
        action = RecoveryAction(
            action_id="action_004",
            action_type=RecoveryActionType.REPLAY_JOB,
            context=InspectionContext(session_id="sess_001", job_id="job_001"),
            timestamp=utc_now_naive(),
            parameters={"job_id": "job_001"},
        )

        result = self.engine.execute_action(action)

        self.assertEqual(result.status, ActionExecutionStatus.SUCCEEDED)
        self.assertIn("job_id", result.output)
        self.assertEqual(result.output["job_id"], "job_001")
        self.assertIn("replay_sequence", result.output)

    def test_rebuild_wakeup_execution_success(self):
        """REBUILD_WAKEUP executes successfully with valid session_id."""
        action = RecoveryAction(
            action_id="action_005",
            action_type=RecoveryActionType.REBUILD_WAKEUP,
            context=InspectionContext(session_id="sess_001"),
            timestamp=utc_now_naive(),
            parameters={"session_id": "sess_001"},
        )

        result = self.engine.execute_action(action)

        self.assertEqual(result.status, ActionExecutionStatus.SUCCEEDED)
        self.assertIn("session_id", result.output)
        self.assertTrue(result.output["wakeup_ready"])
        self.assertIn("context", result.output)

    def test_rehydrate_runtime_execution_success(self):
        """REHYDRATE_RUNTIME executes successfully with valid session_id."""
        action = RecoveryAction(
            action_id="action_006",
            action_type=RecoveryActionType.REHYDRATE_RUNTIME,
            context=InspectionContext(session_id="sess_001"),
            timestamp=utc_now_naive(),
            parameters={"session_id": "sess_001"},
        )

        result = self.engine.execute_action(action)

        self.assertEqual(result.status, ActionExecutionStatus.SUCCEEDED)
        self.assertIn("session_id", result.output)
        self.assertTrue(result.output["rehydrated"])
        self.assertIn("state", result.output)

    def test_execution_result_contains_timing(self):
        """Execution results include timing information."""
        action = RecoveryAction(
            action_id="action_007",
            action_type=RecoveryActionType.REBUILD_WAKEUP,
            context=InspectionContext(session_id="sess_001"),
            timestamp=utc_now_naive(),
            parameters={"session_id": "sess_001"},
        )

        result = self.engine.execute_action(action)

        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.completed_at)
        self.assertGreater(result.duration_seconds, 0)
        self.assertGreaterEqual(
            result.completed_at, result.started_at
        )

    def test_get_execution_result(self):
        """Can retrieve execution result by action_id."""
        action = RecoveryAction(
            action_id="action_008",
            action_type=RecoveryActionType.REBUILD_WAKEUP,
            context=InspectionContext(session_id="sess_001"),
            timestamp=utc_now_naive(),
            parameters={"session_id": "sess_001"},
        )

        result1 = self.engine.execute_action(action)
        result2 = self.engine.get_execution_result("action_008")

        self.assertIsNotNone(result2)
        self.assertEqual(result1.action_id, result2.action_id)
        self.assertEqual(result1.status, result2.status)

    def test_get_execution_history(self):
        """Can retrieve full execution history."""
        action1 = RecoveryAction(
            action_id="action_009",
            action_type=RecoveryActionType.REBUILD_WAKEUP,
            context=InspectionContext(session_id="sess_001"),
            timestamp=utc_now_naive(),
            parameters={"session_id": "sess_001"},
        )

        action2 = RecoveryAction(
            action_id="action_010",
            action_type=RecoveryActionType.REPLAY_JOB,
            context=InspectionContext(session_id="sess_001", job_id="job_001"),
            timestamp=utc_now_naive(),
            parameters={"job_id": "job_001"},
        )

        self.engine.execute_action(action1)
        self.engine.execute_action(action2)

        history = self.engine.get_execution_history()

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].action_id, "action_009")
        self.assertEqual(history[1].action_id, "action_010")

    def test_unsupported_action_type(self):
        """Rejects unsupported action types gracefully."""
        # Create action with unsupported type (INSPECT_EVENTS has no executor)
        action = RecoveryAction(
            action_id="action_011",
            action_type=RecoveryActionType.INSPECT_EVENTS,
            context=InspectionContext(session_id="sess_001"),
            timestamp=utc_now_naive(),
            parameters={},
        )

        result = self.engine.execute_action(action)

        self.assertEqual(result.status, ActionExecutionStatus.FAILED)
        self.assertIn("Unsupported action type", result.error)


class TestExecutionResult(unittest.TestCase):
    """Test execution result dataclass."""

    def test_result_creation(self):
        """ExecutionResult creates with required fields."""
        now = utc_now_naive()
        result = ExecutionResult(
            action_id="action_001",
            action_type=RecoveryActionType.REPLAY_JOB,
            status=ActionExecutionStatus.SUCCEEDED,
            started_at=now,
            completed_at=now,
            duration_seconds=0.5,
            output={"job_id": "job_001"},
        )

        self.assertEqual(result.action_id, "action_001")
        self.assertEqual(result.status, ActionExecutionStatus.SUCCEEDED)
        self.assertIsNone(result.error)
        self.assertIsNone(result.rolled_back_at)

    def test_result_with_error(self):
        """ExecutionResult captures error information."""
        now = utc_now_naive()
        result = ExecutionResult(
            action_id="action_002",
            action_type=RecoveryActionType.REBUILD_WAKEUP,
            status=ActionExecutionStatus.FAILED,
            started_at=now,
            completed_at=now,
            duration_seconds=0.1,
            output={},
            error="Session not found",
        )

        self.assertEqual(result.status, ActionExecutionStatus.FAILED)
        self.assertEqual(result.error, "Session not found")


if __name__ == "__main__":
    unittest.main()
