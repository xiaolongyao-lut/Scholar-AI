# -*- coding: utf-8 -*-
"""
Real FastAPI route tests for recovery endpoints.

Tests the actual recovery routes using TestClient against the real FastAPI app.
Validates that endpoint handlers match recovery_console API and return correct schemas.
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Conditional import for FastAPI testing
try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    TestClient = None

from recovery_console import (
    RecoveryConsole,
    InspectionContext,
    EventTimeline,
    MemorySnapshot,
    FactInvalidation,
    EventFilter,
)
from canonical_event_store import CanonicalEvent, CanonicalEventStore
from memory_fact_store import TemporalFact, MemoryFactStore


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestRecoveryAPIRoutes:
    """Test real recovery API routes with TestClient."""

    @pytest.fixture
    def mock_recovery_console(self):
        """Create a mock recovery console for testing."""
        mock_console = Mock(spec=RecoveryConsole)
        return mock_console

    @pytest.fixture
    def mock_event_store(self):
        """Create mock canonical event store."""
        mock_store = Mock()
        mock_store.get_job_timeline.return_value = []  # Return empty list, not Mock
        return mock_store

    @pytest.fixture
    def mock_fact_store(self):
        """Create mock memory fact store."""
        mock_store = Mock()
        mock_store.get_current_facts.return_value = []  # Return empty list, not Mock
        return mock_store

    @pytest.fixture
    def client(self, mock_recovery_console, mock_event_store, mock_fact_store):
        """Create TestClient with mocked recovery components."""
        # Import adapter only if FastAPI is available
        if not HAS_FASTAPI:
            pytest.skip("FastAPI not available")

        try:
            import python_adapter_server
        except ImportError:
            pytest.skip("python_adapter_server import failed")

        # Patch the factory functions
        with patch.object(
            python_adapter_server, "get_recovery_console", return_value=mock_recovery_console
        ), patch.object(
            python_adapter_server, "get_event_store", return_value=mock_event_store
        ), patch.object(
            python_adapter_server, "get_fact_store", return_value=mock_fact_store
        ):
            client = TestClient(python_adapter_server.app)
            yield client

    def test_recovery_events_success(self, client, mock_recovery_console):
        """Test GET /recovery/events returns event timeline."""
        # Create mock event timeline
        event1 = Mock(spec=CanonicalEvent)
        event1.event_id = "evt_001"
        event1.event_type = "SessionStarted"
        event1.timestamp = datetime(2025, 4, 10, 12, 0, 0)
        event1.source_job_id = "job_123"
        event1.source_session_id = "sess_001"
        event1.event_data = {"status": "started"}

        timeline = EventTimeline(
            timeline_id="tl_001",
            session_id="sess_001",
            events=[event1],
            event_count=1,
            earliest_timestamp=datetime(2025, 4, 10, 12, 0, 0),
            latest_timestamp=datetime(2025, 4, 10, 12, 0, 0),
            aggregate_types=["session"],
            event_types=["SessionStarted"],
        )

        mock_recovery_console.inspect_event_timeline.return_value = timeline

        # Make request
        response = client.get(
            "/recovery/events",
            params={"session_id": "sess_001", "job_id": "job_123"},
        )

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["event_count"] == 1
        assert len(data["events"]) == 1
        assert data["events"][0]["event_id"] == "evt_001"
        assert data["events"][0]["event_type"] == "SessionStarted"
        assert data["session_filter"] == "sess_001"
        assert data["job_filter"] == "job_123"

        # Verify correct method was called
        mock_recovery_console.inspect_event_timeline.assert_called_once()

    def test_recovery_memory_success(self, client, mock_recovery_console):
        """Test GET /recovery/memory returns memory snapshot."""
        # Create mock fact
        fact = Mock(spec=TemporalFact)
        fact.fact_id = "fact_001"
        fact.namespace = "execution"
        fact.subject = "job_123"
        fact.predicate = "status"
        fact.object = "completed"
        fact.object_type = "string"
        fact.valid_from = datetime(2025, 4, 10, 12, 0, 0)
        fact.valid_to = None
        fact.source_event_id = "evt_001"

        snapshot = MemorySnapshot(
            snapshot_id="snap_001",
            session_id="sess_001",
            timestamp=datetime(2025, 4, 10, 12, 0, 0),
            current_facts=[fact],
            fact_count=1,
            namespaces=["execution"],
            sources=["runtime"],
        )

        mock_recovery_console.inspect_memory_state.return_value = snapshot

        # Make request
        response = client.get("/recovery/memory")

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["fact_count"] == 1
        assert len(data["facts"]) == 1
        assert data["facts"][0]["fact_id"] == "fact_001"
        assert data["facts"][0]["namespace"] == "execution"
        assert data["namespaces"] == ["execution"]

        # Verify correct method was called
        mock_recovery_console.inspect_memory_state.assert_called_once()

    def test_recovery_facts_invalidate_success(self, client, mock_recovery_console):
        """Test POST /recovery/facts/invalidate invalidates a fact."""
        # Create mock invalidation
        invalidation = Mock(spec=FactInvalidation)
        invalidation.invalidation_id = "inv_001"
        invalidation.fact_id = "fact_001"
        invalidation.namespace = "execution"
        invalidation.reason = "stale state"
        invalidation.invalidated_at = datetime(2025, 4, 10, 12, 0, 0)
        invalidation.invalidated_by = "recovery_system"
        invalidation.previous_value = "old_value"

        mock_recovery_console.invalidate_fact.return_value = invalidation

        # Make request
        payload = {
            "fact_id": "fact_001",
            "namespace": "execution",
            "reason": "stale state",
            "invalidated_by": "recovery_system",
        }
        response = client.post(
            "/recovery/facts/invalidate",
            json=payload,
        )

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["fact_id"] == "fact_001"
        assert data["namespace"] == "execution"
        assert data["reason"] == "stale state"
        assert data["success"] is True

        # Verify correct method was called
        mock_recovery_console.invalidate_fact.assert_called_once()

    def test_recovery_facts_invalidate_missing_fact_id(self, client):
        """Test POST /recovery/facts/invalidate with missing fact_id."""
        payload = {
            "namespace": "execution",
            "reason": "test",
            "invalidated_by": "system",
        }
        response = client.post("/recovery/facts/invalidate", json=payload)

        assert response.status_code == 422  # Validation error

    def test_recovery_memory_inspection_context(self, client, mock_recovery_console):
        """Test that memory inspection uses correct context."""
        snapshot = MemorySnapshot(
            snapshot_id="snap_001",
            session_id="inspection",
            timestamp=datetime(2025, 4, 10, 12, 0, 0),
            current_facts=[],
            fact_count=0,
            namespaces=[],
            sources=[],
        )
        mock_recovery_console.inspect_memory_state.return_value = snapshot

        response = client.get("/recovery/memory")
        assert response.status_code == 200

        # Verify context was created with session_id="inspection"
        call_args = mock_recovery_console.inspect_memory_state.call_args
        context = call_args[0][0] if call_args[0] else call_args.kwargs.get("context")
        assert isinstance(context, InspectionContext)
        assert context.session_id == "inspection"

    def test_recovery_events_inspection_context(self, client, mock_recovery_console):
        """Test that event inspection uses correct context."""
        timeline = EventTimeline(
            timeline_id="tl_001",
            session_id="sess_001",
            events=[],
            event_count=0,
            earliest_timestamp=datetime(2025, 4, 10, 12, 0, 0),
            latest_timestamp=datetime(2025, 4, 10, 12, 0, 0),
            aggregate_types=[],
            event_types=[],
        )
        mock_recovery_console.inspect_event_timeline.return_value = timeline

        response = client.get(
            "/recovery/events",
            params={"session_id": "sess_test", "job_id": "job_test"},
        )
        assert response.status_code == 200

        # Verify context was created with correct parameters
        call_args = mock_recovery_console.inspect_event_timeline.call_args
        context = call_args[0][0] if call_args[0] else call_args.kwargs.get("context")
        assert isinstance(context, InspectionContext)
        assert context.session_id == "sess_test"
        assert context.job_id == "job_test"

    def test_recovery_error_handling(self, client, mock_recovery_console):
        """Test error handling in recovery endpoints."""
        mock_recovery_console.inspect_memory_state.side_effect = RuntimeError(
            "Database connection failed"
        )

        response = client.get("/recovery/memory")
        assert response.status_code == 500
        data = response.json()
        assert "detail" in data

    def test_recovery_empty_timeline(self, client, mock_recovery_console):
        """Test recovery endpoint with empty timeline."""
        timeline = EventTimeline(
            timeline_id="tl_empty",
            session_id="sess_001",
            events=[],
            event_count=0,
            earliest_timestamp=datetime(2025, 4, 10, 12, 0, 0),
            latest_timestamp=datetime(2025, 4, 10, 12, 0, 0),
            aggregate_types=[],
            event_types=[],
        )
        mock_recovery_console.inspect_event_timeline.return_value = timeline

        response = client.get("/recovery/events", params={"session_id": "sess_001"})
        assert response.status_code == 200
        data = response.json()
        assert data["event_count"] == 0
        assert data["events"] == []

    def test_recovery_empty_snapshot(self, client, mock_recovery_console):
        """Test recovery endpoint with empty memory snapshot."""
        snapshot = MemorySnapshot(
            snapshot_id="snap_empty",
            session_id="sess_001",
            timestamp=datetime(2025, 4, 10, 12, 0, 0),
            current_facts=[],
            fact_count=0,
            namespaces=[],
            sources=[],
        )
        mock_recovery_console.inspect_memory_state.return_value = snapshot

        response = client.get("/recovery/memory")
        assert response.status_code == 200
        data = response.json()
        assert data["fact_count"] == 0
        assert data["facts"] == []
        assert data["namespaces"] == []

    def test_recovery_recommendations_missing_job_id(self, client):
        """Test GET /recovery/recommendations with missing job_id parameter."""
        response = client.get("/recovery/recommendations")
        # job_id is required (Query(...))
        assert response.status_code == 422

    def test_recovery_recommendations_success(self, client):
        """Test GET /recovery/recommendations returns recommendations."""
        # This test validates that the endpoint exists and has proper interface
        response = client.get(
            "/recovery/recommendations",
            params={"job_id": "job_001", "session_id": "sess_001", "limit": 3},
        )

        # The endpoint should handle the request (may return 503 if engine unavailable)
        # We just verify the endpoint exists and returns a valid response
        assert response.status_code in (200, 503)

        if response.status_code == 200:
            data = response.json()
            # Validate response schema
            assert "request_id" in data
            assert "generated_at" in data
            assert "total_evidence_considered" in data
            assert "generation_duration_ms" in data
            assert "primary_recommendation" in data
            assert "alternatives" in data
            assert isinstance(data["alternatives"], list)

    def test_recovery_recommendations_with_seeded_data(self, client):
        """
        Integration test: seed real events/facts, then get recommendations.
        
        This test demonstrates that /recovery/recommendations uses REAL persisted
        data sources and generates evidence-backed recommendations, not empty results.
        
        Proves Outcome 1-3 from integration hardening prompt.
        """
        import tempfile
        import os
        from pathlib import Path
        from datetime import datetime, timedelta

        from datetime_utils import utc_now_naive
        
        # Create temporary databases for this test
        with tempfile.TemporaryDirectory() as tmpdir:
            event_db_path = os.path.join(tmpdir, "seeded_events.db")
            fact_db_path = os.path.join(tmpdir, "seeded_facts.db")
            
            # Seed canonical events
            events_store = CanonicalEventStore(event_db_path)
            
            test_job_id = "test_job_recovery_seed_001"
            test_session_id = "test_session_seed_001"
            base_time = datetime(2025, 4, 10, 10, 0, 0)
            
            # Seed a job failure event
            failure_event = CanonicalEvent(
                event_id="evt_job_failure_seed_001",
                correlation_id=test_job_id,
                timestamp=base_time,
                session_id=test_session_id,
                job_id=test_job_id,
                user_id="test_user",
                aggregate_type="job",
                aggregate_id=test_job_id,
                event_type="job_failed",
                payload={"error": "transient_timeout", "attempt": 1},
                actor_id="scheduler",
                actor_type="system",
                severity="warning",
                source="test_integration",
            )
            events_store.append_event(failure_event)
            
            # Seed execution status facts
            from memory_fact_store import TemporalFact, FactNamespace
            facts_store = MemoryFactStore(fact_db_path)
            
            exec_fact = TemporalFact(
                fact_id="fact_exec_seed_001",
                namespace=FactNamespace.EXECUTION.value,
                subject=test_job_id,
                predicate="status",
                object="failed",
                object_type="string",
                valid_from=base_time,
                valid_to=None,
                source_event_id=failure_event.event_id,
                created_at=utc_now_naive(),
            )
            facts_store.record_fact(exec_fact)
            
            # Use patch context manager to override the factory functions
            # for just this request
            try:
                import python_adapter_server
                with patch.object(
                    python_adapter_server, "get_event_store", return_value=events_store
                ), patch.object(
                    python_adapter_server, "get_fact_store", return_value=facts_store
                ):
                    # Need a fresh client within the patched context
                    from fastapi.testclient import TestClient
                    test_client = TestClient(python_adapter_server.app)
                    
                    # Call the endpoint with our seeded job ID
                    response = test_client.get(
                        "/recovery/recommendations",
                        params={
                            "job_id": test_job_id,
                            "session_id": test_session_id,
                            "limit": 5
                        },
                    )
                    
                    # Must succeed with real seeded data
                    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

                    data = response.json()
                    
                    # Validate schema presence
                    assert "request_id" in data
                    assert "generated_at" in data
                    assert "total_evidence_considered" in data
                    assert "generation_duration_ms" in data
                    assert "primary_recommendation" in data
                    assert "alternatives" in data
                    
                    # CRITICAL: Assert that recommendations are NOT EMPTY
                    # This proves the route uses real data sources, not empty stores
                    assert data["total_evidence_considered"] > 0, \
                        "Must have non-zero evidence count (proves data was loaded from real stores)"
                    
                    # Seeded failure + execution fact must produce a concrete recommendation.
                    primary = data["primary_recommendation"]
                    assert primary is not None, \
                        "Seeded failure scenario must produce a primary recommendation"
                    assert isinstance(primary, dict)
                    assert "recommendation_id" in primary
                    assert "job_id" in primary
                    assert "action_type" in primary
                    assert "confidence" in primary
                    assert primary["job_id"] == test_job_id
                    assert primary["action_type"] == "replay_job"
                    assert failure_event.event_id in primary["source_event_ids"]

                    # The execution fact should contribute a fact-backed alternative.
                    assert data["alternatives"], \
                        "Seeded failure+fact scenario must produce at least one alternative recommendation"
                    rehydration = next(
                        (alt for alt in data["alternatives"] if alt["action_type"] == "rehydrate_runtime"),
                        None,
                    )
                    assert rehydration is not None, \
                        "Execution-state fact should produce a rehydrate_runtime alternative"
                    assert "fact_exec_seed_001" in rehydration["source_fact_ids"]

                    # Recommendation generation itself must leave an auditable canonical event.
                    audit_events = events_store.get_events_by_type("recommendation.generated")
                    assert audit_events, \
                        "Recommendation generation must emit a recommendation.generated audit event"
                    latest_audit = audit_events[-1]
                    assert latest_audit.job_id == test_job_id
                    assert latest_audit.payload["has_primary_recommendation"] is True
                    assert latest_audit.payload["total_evidence_considered"] > 0
            except ImportError:
                pytest.skip("python_adapter_server import failed")

    def test_recovery_recommendations_with_memory_evidence(self, client):
        """
        Integration test: validate memory evidence is integrated into recommendations.
        
        This test proves that:
        1. Memory adapter is consulted during recommendation generation
        2. Memory hits are converted to EvidenceReference objects
        3. memory_hit_ids are populated (not empty list)
        4. Evidence includes entries with source_type="memory"
        
        Proves Phase H1.1: Memory Evidence Integration
        """
        import tempfile
        import os
        from datetime import datetime
        from unittest.mock import patch, Mock

        from datetime_utils import utc_now_naive
        
        # Create temporary databases
        with tempfile.TemporaryDirectory() as tmpdir:
            event_db_path = os.path.join(tmpdir, "memory_events.db")
            fact_db_path = os.path.join(tmpdir, "memory_facts.db")
            
            # Seed canonical events
            events_store = CanonicalEventStore(event_db_path)
            
            test_job_id = "test_job_memory_seed_001"
            test_session_id = "test_session_memory_seed_001"
            base_time = datetime(2025, 4, 10, 10, 0, 0)
            
            # Seed a job failure event
            failure_event = CanonicalEvent(
                event_id="evt_memory_seed_001",
                correlation_id=test_job_id,
                timestamp=base_time,
                session_id=test_session_id,
                job_id=test_job_id,
                user_id="test_user",
                aggregate_type="job",
                aggregate_id=test_job_id,
                event_type="job_failed",
                payload={"error": "transient_timeout", "attempt": 1},
                actor_id="scheduler",
                actor_type="system",
                severity="warning",
                source="test_integration",
            )
            events_store.append_event(failure_event)
            
            # Seed execution fact
            from memory_fact_store import TemporalFact, FactNamespace
            facts_store = MemoryFactStore(fact_db_path)
            
            exec_fact = TemporalFact(
                fact_id="fact_memory_seed_001",
                namespace=FactNamespace.EXECUTION.value,
                subject=test_job_id,
                predicate="status",
                object="failed",
                object_type="string",
                valid_from=base_time,
                valid_to=None,
                source_event_id=failure_event.event_id,
                created_at=utc_now_naive(),
            )
            facts_store.record_fact(exec_fact)
            
            # Create stub memory adapter with test hits
            from dataclasses import dataclass
            
            @dataclass(frozen=True)
            class StubMemorySearchHit:
                text: str
                wing: str
                room: str
                source_file: str
                similarity: float
            
            @dataclass(frozen=True)
            class StubMemorySearchResponse:
                query: str
                wing: str
                room: str
                results: list
                available: bool
                reason: str = None
            
            # Create memory hits for recovery patterns
            memory_hits = [
                StubMemorySearchHit(
                    text="Handle transient timeout errors with exponential backoff retry",
                    wing="recovery_patterns",
                    room="timeout_handling",
                    source_file="timeout_patterns.md",
                    similarity=0.945
                ),
                StubMemorySearchHit(
                    text="Implement job replay with idempotency checks",
                    wing="recovery_patterns",
                    room="job_replay",
                    source_file="replay_patterns.md",
                    similarity=0.892
                ),
            ]
            
            # Create stub memory adapter
            class StubMemoryAdapter:
                def is_enabled(self):
                    return True
                
                def search(self, query: str, wing: str = None, room: str = None, limit: int = None):
                    return StubMemorySearchResponse(
                        query=query,
                        wing=wing or "default_wing",
                        room=room or "default_room",
                        results=memory_hits[:limit] if limit else memory_hits,
                        available=True
                    )
            
            try:
                import python_adapter_server
                from recovery_recommendation_engine import RecoveryRecommendationEngine
                
                stub_adapter = StubMemoryAdapter()
                
                # Patch both the stores AND memory adapter
                with patch.object(
                    python_adapter_server, "get_event_store", return_value=events_store
                ), patch.object(
                    python_adapter_server, "get_fact_store", return_value=facts_store
                ), patch.object(
                    python_adapter_server, "get_memory_adapter", return_value=stub_adapter
                ):
                    # Create a fresh client within patched context
                    from fastapi.testclient import TestClient
                    test_client = TestClient(python_adapter_server.app)
                    
                    # Call recommendations endpoint
                    response = test_client.get(
                        "/recovery/recommendations",
                        params={
                            "job_id": test_job_id,
                            "session_id": test_session_id,
                            "limit": 5
                        },
                    )
                    
                    # Must succeed
                    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
                    
                    data = response.json()
                    
                    # PRIMARY ASSERTION: Memory evidence must be in recommendations
                    primary = data.get("primary_recommendation")
                    assert primary is not None, \
                        "Memory-backed seeded scenario must produce a primary recommendation"

                    # Check memory_hit_ids is populated
                    memory_hit_ids = primary.get("memory_hit_ids", [])
                    assert len(memory_hit_ids) > 0, \
                        "memory_hit_ids must be populated when memory adapter returns hits"
                    
                    # Check evidence includes memory evidence
                    evidence = primary.get("evidence", [])
                    memory_evidence = [e for e in evidence if e.get("source_type") == "memory"]
                    assert len(memory_evidence) > 0, \
                        "Evidence must include memory entries when hits are available"
                    
                    # Verify memory evidence structure
                    for mem_ev in memory_evidence:
                        assert "source_id" in mem_ev
                        assert "relevance" in mem_ev
                        assert "description" in mem_ev
                        assert 0.0 <= mem_ev["relevance"] <= 1.0, \
                            "Memory relevance must be in 0-1 range"
                        # Memory evidence should reference recovery patterns
                        assert "recovery" in mem_ev["description"].lower() or \
                               "timeout" in mem_ev["description"].lower() or \
                               "retry" in mem_ev["description"].lower(), \
                            f"Memory evidence should reference recovery context: {mem_ev['description']}"
                    
                    # Total evidence count should include memory evidence
                    total_evidence = data.get("total_evidence_considered", 0)
                    assert total_evidence > 0, \
                        "Total evidence must be greater than 0"
                    
                    # Phase H1.1 proof: Memory adapter was consulted and produced evidence
                    assert data.get("total_evidence_considered", 0) > 0, \
                        "Phase H1.1 proof: Recommendation must consider all evidence types (events+facts+memory)"
                    
            except ImportError:
                pytest.skip("python_adapter_server import failed")


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
class TestRecoveryAPIContractValidation:
    """Validate that API contracts match recovery_console specifications."""

    def test_event_timeline_payload_schema(self):
        """Verify EventTimeline fields match payload expectations."""
        # This test validates the contract between EventTimeline and EventTimelinePayload
        timeline = EventTimeline(
            timeline_id="tl_001",
            session_id="sess_001",
            events=[],
            event_count=0,
            earliest_timestamp=datetime(2025, 4, 10, 12, 0, 0),
            latest_timestamp=datetime(2025, 4, 10, 12, 0, 0),
            aggregate_types=[],
            event_types=[],
        )

        # Verify fields exist and are accessible
        assert hasattr(timeline, "event_count")
        assert hasattr(timeline, "earliest_timestamp")
        assert hasattr(timeline, "latest_timestamp")
        assert hasattr(timeline, "events")
        assert timeline.earliest_timestamp is not None
        assert timeline.latest_timestamp is not None

    def test_memory_snapshot_payload_schema(self):
        """Verify MemorySnapshot fields match payload expectations."""
        snapshot = MemorySnapshot(
            snapshot_id="snap_001",
            session_id="sess_001",
            timestamp=datetime(2025, 4, 10, 12, 0, 0),
            current_facts=[],
            fact_count=0,
            namespaces=[],
            sources=[],
        )

        # Verify fields exist and are accessible
        assert hasattr(snapshot, "fact_count")
        assert hasattr(snapshot, "current_facts")
        assert hasattr(snapshot, "timestamp")
        assert hasattr(snapshot, "namespaces")
        assert snapshot.timestamp is not None
        assert isinstance(snapshot.current_facts, list)

    def test_fact_invalidation_payload_schema(self):
        """Verify FactInvalidation fields match payload expectations."""
        invalidation = FactInvalidation(
            invalidation_id="inv_001",
            fact_id="fact_001",
            namespace="execution",
            reason="stale",
            invalidated_at=datetime(2025, 4, 10, 12, 0, 0),
            invalidated_by="system",
            previous_value="old",
        )

        # Verify fields exist and are accessible
        assert hasattr(invalidation, "fact_id")
        assert hasattr(invalidation, "namespace")
        assert hasattr(invalidation, "reason")
        assert hasattr(invalidation, "invalidated_at")
        assert hasattr(invalidation, "invalidated_by")
        assert hasattr(invalidation, "previous_value")
        assert invalidation.invalidated_at is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
