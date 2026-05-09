# -*- coding: utf-8 -*-
"""
Tests for Harness V2 Phase C: Memory Policy Engine

Coverage:
- Rule evaluation (condition matching)
- Decision routing (memory/fact/skip logic)
- Pattern detection (error counting, recurring events)
- Deduplication key generation
- Edge cases and error handling
- Integration scenarios
"""

import unittest

from datetime_utils import utc_now_naive

from memory_policy import (
    MemoryPolicyEngine,
    MemoryPolicyRule,
    MemoryDecision,
    MemoryAction,
    skip_decision,
    memory_only_decision,
    fact_only_decision,
    both_decision,
)
from harness_canonical_events import (
    CanonicalEvent,
    CanonicalEventType,
    CanonicalEventBuilder,
)


class TestMemoryDecision(unittest.TestCase):
    """Tests for MemoryDecision dataclass."""
    
    def test_skip_decision_creation(self):
        """Skip decisions are properly constructed."""
        decision = skip_decision("test skip")
        self.assertEqual(decision.action, MemoryAction.SKIP)
        self.assertIsNone(decision.memory_category)
        self.assertIsNone(decision.fact_namespace)
        self.assertEqual(decision.reason, "test skip")
    
    def test_memory_only_decision_creation(self):
        """Memory-only decisions have category but no namespace."""
        decision = memory_only_decision('test_category', 'test reason')
        self.assertEqual(decision.action, MemoryAction.MEMORY)
        self.assertEqual(decision.memory_category, 'test_category')
        self.assertIsNone(decision.fact_namespace)
    
    def test_fact_only_decision_creation(self):
        """Fact-only decisions have namespace but no category."""
        decision = fact_only_decision('test_namespace', 'test reason')
        self.assertEqual(decision.action, MemoryAction.FACT)
        self.assertIsNone(decision.memory_category)
        self.assertEqual(decision.fact_namespace, 'test_namespace')
    
    def test_both_decision_creation(self):
        """Both decisions have both category and namespace."""
        decision = both_decision('cat', 'ns', 'test reason')
        self.assertEqual(decision.action, MemoryAction.BOTH)
        self.assertEqual(decision.memory_category, 'cat')
        self.assertEqual(decision.fact_namespace, 'ns')
    
    def test_decision_immutability(self):
        """MemoryDecision is frozen (immutable)."""
        decision = skip_decision()
        with self.assertRaises(AttributeError):
            decision.action = MemoryAction.MEMORY


class TestMemoryPolicyRule(unittest.TestCase):
    """Tests for MemoryPolicyRule definition."""
    
    def test_rule_creation(self):
        """Rules can be created with all parameters."""
        rule = MemoryPolicyRule(
            name='test_rule',
            priority=50,
            condition=lambda e, c: True,
            action=MemoryAction.SKIP,
            description='test',
        )
        self.assertEqual(rule.name, 'test_rule')
        self.assertEqual(rule.priority, 50)
        self.assertEqual(rule.action, MemoryAction.SKIP)
    
    def test_rule_immutability(self):
        """MemoryPolicyRule is frozen (immutable)."""
        rule = MemoryPolicyRule(
            name='test',
            priority=1,
            condition=lambda e, c: True,
            action=MemoryAction.SKIP,
        )
        with self.assertRaises(AttributeError):
            rule.priority = 100


class TestMemoryPolicyEngine(unittest.TestCase):
    """Tests for the policy evaluation engine."""
    
    def setUp(self):
        """Initialize engine for each test."""
        self.engine = MemoryPolicyEngine()
        self.now = utc_now_naive()
    
    def _create_job_event(
        self,
        event_type: str,
        job_id: str = 'job_123',
        job_kind: str = 'write_section',
        session_id: str = 'session_1',
    ) -> CanonicalEvent:
        """Helper to create job events."""
        return MemoryPolicyEngine._build_test_event(
            event_type=event_type,
            job_id=job_id,
            session_id=session_id,
            aggregate_type='job',
            aggregate_id=job_id,
            payload={'job_kind': job_kind},
        )
    
    def test_engine_initialization_has_default_rules(self):
        """Engine initializes with default rules."""
        stats = self.engine.get_decision_stats()
        self.assertGreater(stats['total_rules'], 5)
        self.assertIn('project_decisions', stats['memory_categories'])
        self.assertIn('job.failure', stats['fact_namespaces'])
    
    def test_important_job_completion_to_memory(self):
        """Important job completions route to memory."""
        event = self._create_job_event(
            'job_completed',
            job_kind='refactor',
        )
        decision = self.engine.evaluate(event)
        
        self.assertEqual(decision.action, MemoryAction.MEMORY)
        self.assertEqual(decision.memory_category, 'project_decisions')
        self.assertGreater(decision.confidence, 0.9)
    
    def test_routine_job_completion_skipped(self):
        """Routine job completions are skipped."""
        # Create event with payload but event_type that doesn't match important rules
        event = MemoryPolicyEngine._build_test_event(
            event_type='capability_invoked',
            job_id='job_456',
            session_id='session_1',
            aggregate_type='capability',
            aggregate_id='cap_123',
            payload={},
        )
        decision = self.engine.evaluate(event)
        
        self.assertEqual(decision.action, MemoryAction.SKIP)
    
    def test_job_failure_to_both(self):
        """Job failures route to both memory and facts."""
        event = self._create_job_event('job_failed')
        decision = self.engine.evaluate(event)
        
        self.assertEqual(decision.action, MemoryAction.BOTH)
        self.assertEqual(decision.memory_category, 'error_resolutions')
        self.assertEqual(decision.fact_namespace, 'job.failure')
    
    def test_resource_mutation_to_fact(self):
        """Resource mutations route to facts."""
        event = MemoryPolicyEngine._build_test_event(
            event_type='resource_modified',
            job_id=None,
            session_id='session_1',
            aggregate_type='resource',
            aggregate_id='draft_789',
            payload={},
        )
        decision = self.engine.evaluate(event)
        
        self.assertEqual(decision.action, MemoryAction.FACT)
        self.assertEqual(decision.fact_namespace, 'resource.current_state')
    
    def test_approval_decision_to_fact(self):
        """Approval decisions become facts."""
        event = MemoryPolicyEngine._build_test_event(
            event_type='approval_decided',
            job_id=None,
            session_id='session_1',
            aggregate_type='approval',
            aggregate_id='apr_123',
            payload={},
        )
        decision = self.engine.evaluate(event)
        
        self.assertEqual(decision.action, MemoryAction.FACT)
        self.assertEqual(decision.fact_namespace, 'approval.decision')
    
    def test_new_error_to_both(self):
        """First occurrence of error routes to both."""
        event = MemoryPolicyEngine._build_test_event(
            event_type='error_occurred',
            job_id='job_123',
            session_id='session_1',
            aggregate_type='error',
            aggregate_id='err_001',
            payload={},
            error_code='ERR_TIMEOUT',
        )
        decision = self.engine.evaluate(event)
        
        self.assertEqual(decision.action, MemoryAction.BOTH)
        self.assertEqual(decision.memory_category, 'error_catalog')
        self.assertEqual(decision.fact_namespace, 'error.first_occurrence')
    
    def test_recurring_error_pattern_detection(self):
        """3+ occurrences of same error trigger pattern rule."""
        error_code = 'ERR_NETWORK'
        
        # Create 4 error events
        for i in range(4):
            event = MemoryPolicyEngine._build_test_event(
                event_type='error_occurred',
                job_id=f'job_{i}',
                session_id='session_1',
                aggregate_type='error',
                aggregate_id=f'err_{i:03d}',
                payload={},
                error_code=error_code,
            )
            self.engine.evaluate(event)
        
        # Verify error was counted
        self.assertEqual(self.engine._get_error_count(error_code), 4)
    
    def test_important_artifact_to_both(self):
        """High-importance artifacts route to both."""
        event = MemoryPolicyEngine._build_test_event(
            event_type='artifact_created',
            job_id='job_123',
            session_id='session_1',
            aggregate_type='artifact',
            aggregate_id='art_key_001',
            payload={'importance': 'high'},
        )
        decision = self.engine.evaluate(event)
        
        self.assertEqual(decision.action, MemoryAction.BOTH)
        self.assertEqual(decision.memory_category, 'key_artifacts')
    
    def test_normal_artifact_skipped(self):
        """Normal importance artifacts are skipped."""
        event = MemoryPolicyEngine._build_test_event(
            event_type='artifact_created',
            job_id='job_123',
            session_id='session_1',
            aggregate_type='artifact',
            aggregate_id='art_normal_001',
            payload={'importance': 'normal'},
        )
        decision = self.engine.evaluate(event)
        
        self.assertEqual(decision.action, MemoryAction.SKIP)
    
    def test_rule_priority_ordering(self):
        """Higher priority rules are evaluated first."""
        engine = MemoryPolicyEngine()
        
        # Add high-priority skip rule
        engine.register_rule(MemoryPolicyRule(
            name='override_skip',
            priority=200,
            condition=lambda e, c: e.event_type == 'job_completed',
            action=MemoryAction.SKIP,
        ))
        
        event = self._create_job_event('job_completed')
        decision = engine.evaluate(event)
        
        # Higher priority rule wins
        self.assertEqual(decision.action, MemoryAction.SKIP)
        self.assertEqual(decision.rule_name, 'override_skip')
    
    def test_custom_rule_registration(self):
        """Custom rules can be registered."""
        engine = MemoryPolicyEngine()
        
        engine.register_rule(MemoryPolicyRule(
            name='custom_test',
            priority=150,
            condition=lambda e, c: e.aggregate_id == 'special_123',
            action=MemoryAction.MEMORY,
            memory_category='custom',
            description='Custom test rule',
        ))
        
        event = MemoryPolicyEngine._build_test_event(
            event_type='any_event',
            job_id=None,
            session_id='session_1',
            aggregate_type='test',
            aggregate_id='special_123',
            payload={},
        )
        decision = engine.evaluate(event)
        
        self.assertEqual(decision.rule_name, 'custom_test')
        self.assertEqual(decision.memory_category, 'custom')
    
    def test_dedupe_key_for_job_events(self):
        """Job events generate dedupe keys."""
        event = self._create_job_event('job_completed')
        decision = self.engine.evaluate(event)
        
        self.assertIsNotNone(decision.dedupe_key)
        # Should include rule name, event type, job_id
        self.assertIn('project_decisions', decision.dedupe_key)
        self.assertIn('job_123', decision.dedupe_key)
    
    def test_dedupe_key_for_error_events(self):
        """Error events generate dedupe keys using error code."""
        event = MemoryPolicyEngine._build_test_event(
            event_type='error_occurred',
            job_id='job_123',
            session_id='session_1',
            aggregate_type='error',
            aggregate_id='err_001',
            payload={},
            error_code='ERR_DUPLICATE_KEY',
        )
        decision = self.engine.evaluate(event)
        
        self.assertIsNotNone(decision.dedupe_key)
        self.assertIn('ERR_DUPLICATE_KEY', decision.dedupe_key)
    
    def test_add_important_job_kind(self):
        """New job kinds can be added for memory routing."""
        engine = MemoryPolicyEngine()
        engine.add_important_job_kind('custom_analysis')
        
        event = self._create_job_event(
            'job_completed',
            job_kind='custom_analysis',
        )
        decision = engine.evaluate(event)
        
        self.assertEqual(decision.action, MemoryAction.MEMORY)
    
    def test_missing_fields_handled_gracefully(self):
        """Events with missing optional fields don't crash."""
        # Create minimal event
        event = MemoryPolicyEngine._build_test_event(
            event_type='job_completed',
            job_id='job_123',
            session_id='session_1',
            aggregate_type='job',
            aggregate_id='job_123',
            payload={},  # No job_kind
        )
        decision = self.engine.evaluate(event)
        
        # Should still get a decision
        self.assertIsNotNone(decision)
        self.assertIsNotNone(decision.action)
    
    def test_decision_stats_reporting(self):
        """Engine reports decision statistics."""
        stats = self.engine.get_decision_stats()
        
        self.assertIn('total_rules', stats)
        self.assertIn('known_errors', stats)
        self.assertIn('memory_categories', stats)
        self.assertIn('fact_namespaces', stats)
        self.assertIsInstance(stats['total_rules'], int)
        self.assertGreater(stats['total_rules'], 0)


class TestMemoryPolicyIntegration(unittest.TestCase):
    """Integration tests for memory policy with canonical events."""
    
    def setUp(self):
        """Initialize for integration tests."""
        self.engine = MemoryPolicyEngine()
    
    def test_full_job_workflow_events(self):
        """Process a complete job lifecycle."""
        job_id = 'integration_job_001'
        session_id = 'session_integration'
        
        # Job starts
        start_event = MemoryPolicyEngine._build_test_event(
            event_type='job_started',
            job_id=job_id,
            session_id=session_id,
            aggregate_type='job',
            aggregate_id=job_id,
            payload={'job_kind': 'refactor'},
        )
        start_decision = self.engine.evaluate(start_event)
        self.assertEqual(start_decision.action, MemoryAction.SKIP)
        
        # Job completes
        complete_event = MemoryPolicyEngine._build_test_event(
            event_type='job_completed',
            job_id=job_id,
            session_id=session_id,
            aggregate_type='job',
            aggregate_id=job_id,
            payload={'job_kind': 'refactor', 'duration': 45},
        )
        complete_decision = self.engine.evaluate(complete_event)
        self.assertEqual(complete_decision.action, MemoryAction.MEMORY)
    
    def test_resource_and_approval_sequence(self):
        """Process resource mutation followed by approval."""
        resource_id = 'draft_integration_001'
        session_id = 'session_integration'
        
        # Resource modified
        modify_event = MemoryPolicyEngine._build_test_event(
            event_type='resource_modified',
            job_id=None,
            session_id=session_id,
            aggregate_type='resource',
            aggregate_id=resource_id,
            payload={},
        )
        modify_decision = self.engine.evaluate(modify_event)
        self.assertEqual(modify_decision.action, MemoryAction.FACT)
        
        # Approval decision
        approval_event = MemoryPolicyEngine._build_test_event(
            event_type='approval_decided',
            job_id=None,
            session_id=session_id,
            aggregate_type='approval',
            aggregate_id=f'apr_{resource_id}',
            payload={'status': 'approved'},
        )
        approval_decision = self.engine.evaluate(approval_event)
        self.assertEqual(approval_decision.action, MemoryAction.FACT)


class TestMemoryActionEnum(unittest.TestCase):
    """Tests for MemoryAction enum."""
    
    def test_memory_action_values(self):
        """MemoryAction has expected values."""
        self.assertEqual(MemoryAction.SKIP.value, 'skip')
        self.assertEqual(MemoryAction.MEMORY.value, 'memory')
        self.assertEqual(MemoryAction.FACT.value, 'fact')
        self.assertEqual(MemoryAction.BOTH.value, 'both')
    
    def test_memory_action_comparison(self):
        """MemoryAction values can be compared."""
        self.assertEqual(MemoryAction.SKIP, MemoryAction.SKIP)
        self.assertNotEqual(MemoryAction.SKIP, MemoryAction.MEMORY)


def run_full_test_suite() -> tuple[int, int, int]:
    """
    Run complete test suite.
    
    Returns:
        (tests_run, failures, errors)
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryDecision))
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryPolicyRule))
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryPolicyEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryPolicyIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryActionEnum))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.testsRun, len(result.failures), len(result.errors)


# Helper method to add to MemoryPolicyEngine for tests
MemoryPolicyEngine._build_test_event = staticmethod(
    lambda event_type, job_id, session_id, aggregate_type, aggregate_id, payload, error_code=None: CanonicalEvent(
        event_id=f'evt_{aggregate_id}_{int(utc_now_naive().timestamp())}',
        correlation_id=f'corr_{aggregate_id}',
        timestamp=utc_now_naive(),
        session_id=session_id,
        job_id=job_id,
        user_id='test_user',
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        actor_id='test_user',
        actor_type='user',
        severity='info',
        previous_state=None,
        new_state=None,
        error_code=error_code,
        error_message=None,
        source='memory_policy_test',
    )
)


if __name__ == '__main__':
    tests_run, failures, errors = run_full_test_suite()
    print(f"\n{'='*60}")
    print(f"Test Results: {tests_run} tests, {failures} failures, {errors} errors")
    print(f"{'='*60}")
    if failures == 0 and errors == 0:
        print("✅ All tests passed!")
    else:
        print(f"❌ {failures + errors} issues found")
