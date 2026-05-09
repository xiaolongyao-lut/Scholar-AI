# -*- coding: utf-8 -*-
"""
Tests for Phase H1: Memory-Grounded Recovery Advisor (Stable Sync Version)
"""

import unittest
from datetime import timedelta
from datetime_utils import utc_now

from recovery_recommendation_engine import (
    RecoveryRecommendation,
    RecoveryActionType,
    ApprovalLevel,
    EvidenceReference,
    RecommendationRequest,
    RecommendationsResult,
    RecoveryRecommendationEngine,
    JobReplayRule,
)


class TestRecoveryRecommendationModels(unittest.TestCase):
    """Test basic recommendation models."""
    
    def test_recommendation_structure(self):
        """Verify RecoveryRecommendation has basic fields."""
        rec = RecoveryRecommendation(
            recommendation_id="rec-001",
            job_id="job-001",
            session_id="session-001",
            created_at=utc_now(),
            action_type=RecoveryActionType.REPLAY_JOB,
            rationale="Test recommendation",
            confidence=0.85,
            priority=4,
            approval_level=ApprovalLevel.OPERATOR,
            dry_run_preview="Would replay job",
            time_to_remediate=timedelta(minutes=5),
            risk_level="medium",
            risk_description="Some risk",
            reversibility="fully_reversible",
        )
        
        self.assertEqual(rec.recommendation_id, "rec-001")
        self.assertEqual(rec.job_id, "job-001")
        self.assertEqual(rec.action_type, RecoveryActionType.REPLAY_JOB)
        self.assertEqual(rec.confidence, 0.85)

    def test_evidence_reference_structure(self):
        """Verify EvidenceReference model."""
        evidence = EvidenceReference(
            source_type="event",
            source_id="event-001",
            relevance=0.95,
            description="Job failure event"
        )
        
        self.assertEqual(evidence.source_type, "event")
        self.assertEqual(evidence.relevance, 0.95)


class TestRecommendationRules(unittest.TestCase):
    """Test recommendation generation rules."""
    
    def test_job_replay_rule_priority(self):
        """Verify JobReplayRule has correct priority."""
        rule = JobReplayRule()
        self.assertEqual(rule.priority, 4)


class TestRecoveryRecommendationEngine(unittest.TestCase):
    """Test recovery recommendation engine."""
    
    def setUp(self):
        """Set up test fixtures with mocks."""
        self.mock_event_store = MockEventStore()
        self.mock_fact_store = MockFactStore()
        self.engine = RecoveryRecommendationEngine(
            self.mock_event_store,
            self.mock_fact_store
        )
    
    def test_engine_initialization(self):
        """Verify engine initializes with rules."""
        self.assertGreater(len(self.engine.rules), 0)
    
    def test_generate_recommendations_returns_result(self):
        """Verify recommendation generation returns valid result."""
        request = RecommendationRequest(
            session_id="session-001",
            job_id="job-001"
        )
        
        result = self.engine.generate_recommendations(request)
        
        self.assertIsInstance(result, RecommendationsResult)
        self.assertIsNotNone(result.request_id)
        self.assertGreaterEqual(result.generation_duration_ms, 0)


# Mock classes for testing

class MockEventStore:
    def get_job_timeline(self, _job_id: str) -> list:
        return []
        
    def append_event(self, event):
        pass


class MockFactStore:
    def get_current_facts(self, _namespace: str = None, subject: str = None) -> list:
        return []


if __name__ == "__main__":
    unittest.main()
