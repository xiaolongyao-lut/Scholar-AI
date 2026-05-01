# -*- coding: utf-8 -*-
"""
Comprehensive test suite for HarnessStore.

Tests cover:
- Session CRUD operations
- Job persistence and recovery
- Event history tracking
- Artifact storage
- Approval management
- State export/import
- Full session recovery from event history
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_store import (
    HarnessStore,
    DurableSession,
    DurableJob,
    DurableEvent,
    DurableArtifact,
    DurableApproval,
    get_harness_store,
    set_harness_store,
)


class TestHarnessStore(unittest.TestCase):
    """Test cases for HarnessStore."""

    def setUp(self) -> None:
        """Create temporary database for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.store = HarnessStore(db_path=self.db_path)
        set_harness_store(self.store)

    def tearDown(self) -> None:
        """Clean up resources."""
        self.store.close()
        self.temp_dir.cleanup()

    @staticmethod
    def _now_iso() -> str:
        """Get current time in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def test_session_crud(self) -> None:
        """Test session creation, retrieval, and listing."""
        session_id = str(uuid4())
        user_id = "user_123"
        
        # Create
        session = DurableSession(
            session_id=session_id,
            user_id=user_id,
            mode="interactive",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            metadata={"project": "test"},
        )
        self.store.save_session(session)
        
        # Retrieve
        retrieved = self.store.get_session(session_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.session_id, session_id)
        self.assertEqual(retrieved.user_id, user_id)
        self.assertEqual(retrieved.metadata["project"], "test")
        
        # List
        sessions = self.store.list_sessions(user_id=user_id)
        self.assertGreaterEqual(len(sessions), 1)
        self.assertTrue(any(s.session_id == session_id for s in sessions))

    def test_job_persistence(self) -> None:
        """Test job creation and recovery."""
        session_id = str(uuid4())
        job_id = str(uuid4())
        
        # Setup session first
        session = DurableSession(
            session_id=session_id,
            user_id="user_123",
            mode="batch",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            metadata={},
        )
        self.store.save_session(session)
        
        # Create job
        job = DurableJob(
            job_id=job_id,
            session_id=session_id,
            kind="SKILL_EXECUTION",
            status="pending",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            payload={"skill_id": "grammar_checker"},
            result={},
        )
        self.store.save_job(job)
        
        # Retrieve and verify
        retrieved = self.store.get_job(job_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.kind, "SKILL_EXECUTION")
        self.assertEqual(retrieved.status, "pending")

    def test_event_history_append(self) -> None:
        """Test appending events to history."""
        session_id = str(uuid4())
        job_id = str(uuid4())
        
        # Create session and job
        session = DurableSession(
            session_id=session_id,
            user_id="user_123",
            mode="interactive",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            metadata={},
        )
        self.store.save_session(session)
        
        job = DurableJob(
            job_id=job_id,
            session_id=session_id,
            kind="SKILL_EXECUTION",
            status="pending",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
        )
        self.store.save_job(job)
        
        # Append events
        event1 = DurableEvent(
            event_id=str(uuid4()),
            job_id=job_id,
            session_id=session_id,
            event_type="job_created",
            timestamp=self._now_iso(),
            actor_id="system",
            payload={"message": "Job created"},
        )
        self.store.append_event(event1)
        
        event2 = DurableEvent(
            event_id=str(uuid4()),
            job_id=job_id,
            session_id=session_id,
            event_type="execution_started",
            timestamp=self._now_iso(),
            actor_id="system",
            payload={"skill": "grammar_checker"},
        )
        self.store.append_event(event2)
        
        # Retrieve and verify order
        events = self.store.get_events(job_id=job_id)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].event_type, "job_created")
        self.assertEqual(events[1].event_type, "execution_started")

    def test_artifact_storage(self) -> None:
        """Test artifact persistence."""
        session_id = str(uuid4())
        job_id = str(uuid4())
        artifact_id = str(uuid4())
        
        # Setup
        session = DurableSession(
            session_id=session_id,
            user_id="user_123",
            mode="interactive",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            metadata={},
        )
        self.store.save_session(session)
        
        job = DurableJob(
            job_id=job_id,
            session_id=session_id,
            kind="SKILL_EXECUTION",
            status="completed",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
        )
        self.store.save_job(job)
        
        # Create artifact
        artifact = DurableArtifact(
            artifact_id=artifact_id,
            job_id=job_id,
            session_id=session_id,
            artifact_type="text_output",
            created_at=self._now_iso(),
            content="This is corrected text.",
            metadata={"skill": "grammar_checker"},
        )
        self.store.save_artifact(artifact)
        
        # Retrieve
        retrieved = self.store.get_artifact(artifact_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.content, "This is corrected text.")
        
        # List
        artifacts = self.store.list_artifacts(job_id)
        self.assertEqual(len(artifacts), 1)

    def test_approval_tracking(self) -> None:
        """Test approval request and decision tracking."""
        session_id = str(uuid4())
        job_id = str(uuid4())
        approval_id = str(uuid4())
        
        # Setup
        session = DurableSession(
            session_id=session_id,
            user_id="user_123",
            mode="interactive",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            metadata={},
        )
        self.store.save_session(session)
        
        job = DurableJob(
            job_id=job_id,
            session_id=session_id,
            kind="SKILL_EXECUTION",
            status="pending_approval",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
        )
        self.store.save_job(job)
        
        # Create approval request
        approval = DurableApproval(
            approval_id=approval_id,
            job_id=job_id,
            session_id=session_id,
            capability_id="imported_skill_xyz",
            policy="REQUIRES_USER_APPROVAL",
            status="pending",
            requested_at=self._now_iso(),
        )
        self.store.save_approval(approval)
        
        # Retrieve
        retrieved = self.store.get_approval(approval_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.status, "pending")
        
        # Update with decision
        decided_approval = DurableApproval(
            approval_id=approval_id,
            job_id=job_id,
            session_id=session_id,
            capability_id="imported_skill_xyz",
            policy="REQUIRES_USER_APPROVAL",
            status="approved",
            requested_at=approval.requested_at,
            decided_at=self._now_iso(),
            decided_by="user_123",
            decision="approved",
        )
        self.store.save_approval(decided_approval)
        
        # Verify update
        updated = self.store.get_approval(approval_id)
        self.assertEqual(updated.status, "approved")
        self.assertEqual(updated.decision, "approved")

    def test_rebuild_job_state_from_events(self) -> None:
        """Test rebuilding job state from event history."""
        session_id = str(uuid4())
        job_id = str(uuid4())
        
        # Setup
        session = DurableSession(
            session_id=session_id,
            user_id="user_123",
            mode="interactive",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            metadata={},
        )
        self.store.save_session(session)
        
        job = DurableJob(
            job_id=job_id,
            session_id=session_id,
            kind="SKILL_EXECUTION",
            status="completed",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
        )
        self.store.save_job(job)
        
        # Append event history
        events_to_append = [
            ("job_created", {"message": "Job started"}),
            ("execution_started", {"skill": "grammar_checker"}),
            ("execution_completed", {"output_chars": 1500}),
        ]
        
        for event_type, payload in events_to_append:
            event = DurableEvent(
                event_id=str(uuid4()),
                job_id=job_id,
                session_id=session_id,
                event_type=event_type,
                timestamp=self._now_iso(),
                actor_id="system",
                payload=payload,
            )
            self.store.append_event(event)
        
        # Rebuild state from history
        state = self.store.rebuild_job_state(job_id)
        
        # Verify
        self.assertEqual(state["job_id"], job_id)
        self.assertEqual(state["events_count"], 3)
        self.assertEqual(len(state["event_timeline"]), 3)
        self.assertEqual(state["event_timeline"][0]["event_type"], "job_created")

    def test_export_import_session_state(self) -> None:
        """Test exporting and re-importing complete session state."""
        session_id = str(uuid4())
        job_id = str(uuid4())
        artifact_id = str(uuid4())
        
        # Create a session with jobs, events, artifacts
        session = DurableSession(
            session_id=session_id,
            user_id="user_123",
            mode="interactive",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            metadata={"project": "test", "version": "1.0"},
        )
        self.store.save_session(session)
        
        job = DurableJob(
            job_id=job_id,
            session_id=session_id,
            kind="SKILL_EXECUTION",
            status="completed",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            payload={"skill_id": "grammar_checker"},
            result={"status": "success"},
        )
        self.store.save_job(job)
        
        event = DurableEvent(
            event_id=str(uuid4()),
            job_id=job_id,
            session_id=session_id,
            event_type="execution_completed",
            timestamp=self._now_iso(),
            actor_id="system",
            payload={"message": "Completed"},
        )
        self.store.append_event(event)
        
        artifact = DurableArtifact(
            artifact_id=artifact_id,
            job_id=job_id,
            session_id=session_id,
            artifact_type="text_output",
            created_at=self._now_iso(),
            content="Corrected output",
            metadata={"quality": "high"},
        )
        self.store.save_artifact(artifact)
        
        # Export
        exported = self.store.export_state(session_id)
        self.assertEqual(exported["session"]["session_id"], session_id)
        self.assertEqual(len(exported["jobs"]), 1)
        self.assertEqual(len(exported["events"]), 1)
        self.assertEqual(len(exported["artifacts"]), 1)
        
        # Create new store and import
        temp_dir2 = tempfile.TemporaryDirectory()
        db_path2 = Path(temp_dir2.name) / "imported.db"
        store2 = HarnessStore(db_path=db_path2)
        
        # Import
        imported_session_id = store2.import_state(exported)
        self.assertEqual(imported_session_id, session_id)
        
        # Verify imported data
        imported_session = store2.get_session(session_id)
        self.assertIsNotNone(imported_session)
        self.assertEqual(imported_session.metadata["project"], "test")
        
        imported_job = store2.get_job(job_id)
        self.assertIsNotNone(imported_job)
        
        imported_events = store2.get_events(job_id=job_id)
        self.assertEqual(len(imported_events), 1)
        
        # Cleanup
        store2.close()
        temp_dir2.cleanup()

    def test_session_not_found(self) -> None:
        """Test handling of non-existent session."""
        session = self.store.get_session("non_existent")
        self.assertIsNone(session)

    def test_job_not_found(self) -> None:
        """Test handling of non-existent job."""
        job = self.store.get_job("non_existent")
        self.assertIsNone(job)

    def test_concurrent_event_appending(self) -> None:
        """Test that events maintain order even with multiple appends."""
        session_id = str(uuid4())
        job_id = str(uuid4())
        
        session = DurableSession(
            session_id=session_id,
            user_id="user_123",
            mode="batch",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
            metadata={},
        )
        self.store.save_session(session)
        
        job = DurableJob(
            job_id=job_id,
            session_id=session_id,
            kind="BATCH_JOB",
            status="running",
            created_at=self._now_iso(),
            updated_at=self._now_iso(),
        )
        self.store.save_job(job)
        
        # Append many events
        for i in range(10):
            event = DurableEvent(
                event_id=str(uuid4()),
                job_id=job_id,
                session_id=session_id,
                event_type=f"step_{i}",
                timestamp=self._now_iso(),
                actor_id="system",
                payload={"step": i},
            )
            self.store.append_event(event)
        
        # Verify all events are present and in order
        events = self.store.get_events(job_id=job_id)
        self.assertEqual(len(events), 10)
        for i, event in enumerate(events):
            self.assertEqual(event.event_type, f"step_{i}")


if __name__ == "__main__":
    unittest.main()
