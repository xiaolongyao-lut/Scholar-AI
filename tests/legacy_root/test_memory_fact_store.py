# -*- coding: utf-8 -*-
"""
Tests for Harness V2 Phase D: Temporal Fact Store

Coverage:
- TemporalFact model immutability
- Fact extraction from canonical events
- Fact storage and closure of predecessors
- Current and historical fact queries
- Fact timeline retrieval
- Integration with Phase B.3 events
"""

import unittest
import tempfile
import os
from datetime import datetime, timedelta

from datetime_utils import utc_now_naive

from memory_fact_store import (
    TemporalFact,
    FactNamespace,
    ExecutionFactRule,
    SkillFactRule,
    ResourceFactRule,
    ApprovalFactRule,
    PipelineFactRule,
    MemoryFactStore,
    create_default_fact_store,
)
from harness_canonical_events import CanonicalEvent


class TestTemporalFact(unittest.TestCase):
    """Tests for TemporalFact immutable model."""
    
    def setUp(self):
        """Create test fact."""
        self.fact = TemporalFact(
            fact_id='fact_test_001',
            namespace='execution',
            subject='job_001',
            predicate='status',
            object='running',
            object_type='string',
            valid_from=datetime(2024, 1, 1, 10, 0, 0),
            valid_to=None,
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
    
    def test_fact_immutability(self):
        """TemporalFact cannot be modified after creation."""
        with self.assertRaises(AttributeError):
            self.fact.object = 'completed'
    
    def test_fact_is_current(self):
        """is_current() returns True when valid_to is None."""
        self.assertTrue(self.fact.is_current())
        
        closed_fact = TemporalFact(
            fact_id='fact_closed',
            namespace='execution',
            subject='job_001',
            predicate='status',
            object='completed',
            object_type='string',
            valid_from=datetime(2024, 1, 1, 10, 0, 0),
            valid_to=datetime(2024, 1, 1, 11, 0, 0),
            source_event_id='evt_002',
            created_at=utc_now_naive(),
        )
        self.assertFalse(closed_fact.is_current())
    
    def test_fact_was_valid_at_time(self):
        """was_valid_at() checks validity window."""
        # Fact valid Jan 1 10:00 - Jan 1 11:00
        fact = TemporalFact(
            fact_id='fact_time_001',
            namespace='test',
            subject='sub_001',
            predicate='prop_001',
            object='value',
            object_type='string',
            valid_from=datetime(2024, 1, 1, 10, 0, 0),
            valid_to=datetime(2024, 1, 1, 11, 0, 0),
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
        
        # Before window
        self.assertFalse(fact.was_valid_at(datetime(2024, 1, 1, 9, 59, 0)))
        
        # At start
        self.assertTrue(fact.was_valid_at(datetime(2024, 1, 1, 10, 0, 0)))
        
        # During window
        self.assertTrue(fact.was_valid_at(datetime(2024, 1, 1, 10, 30, 0)))
        
        # At end (exclusive)
        self.assertFalse(fact.was_valid_at(datetime(2024, 1, 1, 11, 0, 0)))
    
    def test_current_fact_valid_at_any_time(self):
        """Current fact (valid_to=None) is valid at any time."""
        current_fact = TemporalFact(
            fact_id='fact_current',
            namespace='test',
            subject='sub_001',
            predicate='prop_001',
            object='value',
            object_type='string',
            valid_from=datetime(2024, 1, 1, 10, 0, 0),
            valid_to=None,
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
        
        self.assertTrue(current_fact.was_valid_at(datetime(2024, 1, 1, 10, 0, 0)))
        self.assertTrue(current_fact.was_valid_at(datetime(2025, 1, 1, 0, 0, 0)))
        self.assertTrue(current_fact.was_valid_at(utc_now_naive()))


class TestExecutionFactRule(unittest.TestCase):
    """Tests for execution status fact extraction."""
    
    def setUp(self):
        """Initialize rule."""
        self.rule = ExecutionFactRule()
    
    def test_can_handle_job_started(self):
        """Rule handles job_started events."""
        event = CanonicalEvent(
            event_id='evt_001',
            correlation_id='corr_001',
            timestamp=utc_now_naive(),
            session_id='sess_001',
            job_id='job_001',
            user_id='user_001',
            aggregate_type='job',
            aggregate_id='job_001',
            event_type='job_started',
            payload={'job_kind': 'test'},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='runtime',
        )
        self.assertTrue(self.rule.can_handle(event))
    
    def test_extract_job_started_fact(self):
        """Extract running status from job_started event."""
        event = CanonicalEvent(
            event_id='evt_job_start',
            correlation_id='corr_001',
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            session_id='sess_001',
            job_id='job_001',
            user_id='user_001',
            aggregate_type='job',
            aggregate_id='job_001',
            event_type='job_started',
            payload={},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='runtime',
        )
        
        facts = self.rule.extract(event)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].subject, 'job_001')
        self.assertEqual(facts[0].predicate, 'status')
        self.assertEqual(facts[0].object, 'running')
    
    def test_extract_job_completed_fact(self):
        """Extract completed status from job_completed event."""
        event = CanonicalEvent(
            event_id='evt_job_complete',
            correlation_id='corr_001',
            timestamp=datetime(2024, 1, 1, 11, 0, 0),
            session_id='sess_001',
            job_id='job_001',
            user_id='user_001',
            aggregate_type='job',
            aggregate_id='job_001',
            event_type='job_completed',
            payload={},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='runtime',
        )
        
        facts = self.rule.extract(event)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].object, 'completed')
    
    def test_extract_job_failed_fact(self):
        """Extract failed status from job_failed event."""
        event = CanonicalEvent(
            event_id='evt_job_fail',
            correlation_id='corr_001',
            timestamp=datetime(2024, 1, 1, 10, 30, 0),
            session_id='sess_001',
            job_id='job_001',
            user_id='user_001',
            aggregate_type='job',
            aggregate_id='job_001',
            event_type='job_failed',
            payload={},
            actor_id='user_001',
            actor_type='user',
            severity='error',
            source='runtime',
        )
        
        facts = self.rule.extract(event)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].object, 'failed')
    
    def test_ignore_non_job_events(self):
        """Non-job events are ignored."""
        event = CanonicalEvent(
            event_id='evt_res_001',
            correlation_id='corr_001',
            timestamp=utc_now_naive(),
            session_id='sess_001',
            job_id='job_001',
            user_id='user_001',
            aggregate_type='resource',
            aggregate_id='res_001',
            event_type='resource_modified',
            payload={},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='resources',
        )
        self.assertFalse(self.rule.can_handle(event))


class TestSkillFactRule(unittest.TestCase):
    """Tests for skill state fact extraction."""
    
    def setUp(self):
        """Initialize rule."""
        self.rule = SkillFactRule()
    
    def test_extract_skill_enabled_fact(self):
        """Extract enabled status from capability event."""
        event = CanonicalEvent(
            event_id='evt_cap_001',
            correlation_id='corr_001',
            timestamp=utc_now_naive(),
            session_id='sess_001',
            job_id='job_001',
            user_id='user_001',
            aggregate_type='capability',
            aggregate_id='cap_001',
            event_type='capability_requested',
            payload={'skill': 'code_generator', 'enabled': True},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='audit',
        )
        
        facts = self.rule.extract(event)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].namespace, 'skills')
        self.assertEqual(facts[0].subject, 'code_generator')
        self.assertEqual(facts[0].object, 'true')


class TestResourceFactRule(unittest.TestCase):
    """Tests for resource state fact extraction."""
    
    def setUp(self):
        """Initialize rule."""
        self.rule = ResourceFactRule()
    
    def test_extract_resource_published_fact(self):
        """Extract published status from resource event."""
        event = CanonicalEvent(
            event_id='evt_res_pub',
            correlation_id='corr_001',
            timestamp=utc_now_naive(),
            session_id='sess_001',
            job_id='job_001',
            user_id='user_001',
            aggregate_type='resource',
            aggregate_id='res_001',
            event_type='resource_published',
            payload={},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='resources',
        )
        
        facts = self.rule.extract(event)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].namespace, 'resources')
        self.assertEqual(facts[0].subject, 'res_001')
        self.assertEqual(facts[0].object, 'published')


class TestApprovalFactRule(unittest.TestCase):
    """Tests for approval decision fact extraction."""
    
    def setUp(self):
        """Initialize rule."""
        self.rule = ApprovalFactRule()
    
    def test_can_handle_approval_event(self):
        """Rule handles approval events."""
        event = CanonicalEvent(
            event_id='evt_appr_001',
            correlation_id='corr_001',
            timestamp=utc_now_naive(),
            session_id='sess_001',
            job_id='job_001',
            user_id='user_001',
            aggregate_type='approval',
            aggregate_id='appr_001',
            event_type='approval_granted',
            payload={'approval_id': 'appr_001'},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='audit',
        )
        self.assertTrue(self.rule.can_handle(event))


class TestMemoryFactStore(unittest.TestCase):
    """Tests for temporal fact store."""
    
    def setUp(self):
        """Initialize temporary database."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.store = MemoryFactStore(self.temp_db.name)
    
    def tearDown(self):
        """Clean up database."""
        try:
            os.unlink(self.temp_db.name)
        except FileNotFoundError:
            pass
    
    def test_store_initialization(self):
        """Store initializes with schema."""
        # Create a fact and record it
        fact = TemporalFact(
            fact_id='fact_init_001',
            namespace='test',
            subject='sub_001',
            predicate='prop_001',
            object='value',
            object_type='string',
            valid_from=utc_now_naive(),
            valid_to=None,
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
        
        fact_id = self.store.record_fact(fact)
        self.assertEqual(fact_id, 'fact_init_001')
    
    def test_record_fact(self):
        """Record a fact to the store."""
        now = datetime(2024, 1, 1, 10, 0, 0)
        fact = TemporalFact(
            fact_id='fact_record_001',
            namespace='execution',
            subject='job_001',
            predicate='status',
            object='running',
            object_type='string',
            valid_from=now,
            valid_to=None,
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
        
        fact_id = self.store.record_fact(fact)
        self.assertIsNotNone(fact_id)
    
    def test_close_predecessor_on_new_fact(self):
        """Recording new fact closes previous fact with same (ns, subj, pred)."""
        time1 = datetime(2024, 1, 1, 10, 0, 0)
        time2 = datetime(2024, 1, 1, 11, 0, 0)
        
        # Record first fact
        fact1 = TemporalFact(
            fact_id='fact_1',
            namespace='execution',
            subject='job_001',
            predicate='status',
            object='running',
            object_type='string',
            valid_from=time1,
            valid_to=None,
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
        self.store.record_fact(fact1)
        
        # Record second fact (should close first)
        fact2 = TemporalFact(
            fact_id='fact_2',
            namespace='execution',
            subject='job_001',
            predicate='status',
            object='completed',
            object_type='string',
            valid_from=time2,
            valid_to=None,
            source_event_id='evt_002',
            created_at=utc_now_naive(),
        )
        self.store.record_fact(fact2)
        
        # Query at time1 - should get fact1
        facts_at_time1 = self.store.get_facts_at_time(
            'execution', time1 + timedelta(seconds=1)
        )
        self.assertEqual(len(facts_at_time1), 1)
        self.assertEqual(facts_at_time1[0].object, 'running')
        
        # Query at time2 - should get fact2
        facts_at_time2 = self.store.get_facts_at_time(
            'execution', time2 + timedelta(seconds=1)
        )
        self.assertEqual(len(facts_at_time2), 1)
        self.assertEqual(facts_at_time2[0].object, 'completed')
    
    def test_get_current_facts(self):
        """Query currently valid facts."""
        fact = TemporalFact(
            fact_id='fact_current_001',
            namespace='skills',
            subject='code_generator',
            predicate='enabled',
            object='true',
            object_type='bool',
            valid_from=utc_now_naive(),
            valid_to=None,
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
        self.store.record_fact(fact)
        
        current = self.store.get_current_facts('skills')
        self.assertGreaterEqual(len(current), 1)
        self.assertTrue(any(f.subject == 'code_generator' for f in current))
    
    def test_get_current_facts_by_subject(self):
        """Filter current facts by subject."""
        fact = TemporalFact(
            fact_id='fact_subj_001',
            namespace='resources',
            subject='res_001',
            predicate='status',
            object='published',
            object_type='string',
            valid_from=utc_now_naive(),
            valid_to=None,
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
        self.store.record_fact(fact)
        
        current = self.store.get_current_facts('resources', subject='res_001')
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].subject, 'res_001')
    
    def test_get_facts_at_time(self):
        """Query facts valid at specific timestamp."""
        time1 = datetime(2024, 1, 1, 10, 0, 0)
        time2 = datetime(2024, 1, 1, 11, 0, 0)
        time_between = datetime(2024, 1, 1, 10, 30, 0)
        
        fact = TemporalFact(
            fact_id='fact_time_001',
            namespace='execution',
            subject='job_001',
            predicate='status',
            object='running',
            object_type='string',
            valid_from=time1,
            valid_to=time2,
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
        self.store.record_fact(fact)
        
        # Should find fact between time1 and time2
        facts = self.store.get_facts_at_time('execution', time_between)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0].object, 'running')
    
    def test_get_fact_timeline(self):
        """Get complete history of fact changes."""
        time1 = datetime(2024, 1, 1, 10, 0, 0)
        time2 = datetime(2024, 1, 1, 11, 0, 0)
        time3 = datetime(2024, 1, 1, 12, 0, 0)
        
        # Record three versions of same fact
        fact1 = TemporalFact(
            fact_id='fact_v1',
            namespace='execution',
            subject='job_001',
            predicate='status',
            object='running',
            object_type='string',
            valid_from=time1,
            valid_to=None,
            source_event_id='evt_001',
            created_at=utc_now_naive(),
        )
        self.store.record_fact(fact1)
        
        fact2 = TemporalFact(
            fact_id='fact_v2',
            namespace='execution',
            subject='job_001',
            predicate='status',
            object='completed',
            object_type='string',
            valid_from=time2,
            valid_to=None,
            source_event_id='evt_002',
            created_at=utc_now_naive(),
        )
        self.store.record_fact(fact2)
        
        fact3 = TemporalFact(
            fact_id='fact_v3',
            namespace='execution',
            subject='job_001',
            predicate='status',
            object='archived',
            object_type='string',
            valid_from=time3,
            valid_to=None,
            source_event_id='evt_003',
            created_at=utc_now_naive(),
        )
        self.store.record_fact(fact3)
        
        # Get timeline
        timeline = self.store.get_fact_timeline('execution', 'job_001', 'status')
        self.assertGreaterEqual(len(timeline), 3)


class TestMemoryFactStoreIntegration(unittest.TestCase):
    """Integration tests with canonical events."""
    
    def setUp(self):
        """Initialize store."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.store = create_default_fact_store(self.temp_db.name)
    
    def tearDown(self):
        """Clean up."""
        try:
            os.unlink(self.temp_db.name)
        except FileNotFoundError:
            pass
    
    def test_extract_and_record_job_event(self):
        """Extract facts from canonical event and record."""
        event = CanonicalEvent(
            event_id='evt_job_start',
            correlation_id='corr_001',
            timestamp=datetime(2024, 1, 1, 10, 0, 0),
            session_id='sess_001',
            job_id='job_001',
            user_id='user_001',
            aggregate_type='job',
            aggregate_id='job_001',
            event_type='job_started',
            payload={'job_kind': 'test'},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='runtime',
        )
        
        # Extract facts
        facts = self.store.extract_facts(event)
        self.assertGreater(len(facts), 0)
        
        # Record them
        for fact in facts:
            self.store.record_fact(fact)
        
        # Query
        current = self.store.get_current_facts('execution')
        self.assertTrue(any(f.subject == 'job_001' for f in current))
    
    def test_event_flow_to_fact(self):
        """Full flow: event → fact extraction → storage → query."""
        # Create job started event
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        start_event = CanonicalEvent(
            event_id='evt_start',
            correlation_id='corr_001',
            timestamp=start_time,
            session_id='sess_001',
            job_id='job_workflow',
            user_id='user_001',
            aggregate_type='job',
            aggregate_id='job_workflow',
            event_type='job_started',
            payload={'job_kind': 'analysis'},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='runtime',
        )
        
        # Extract and record
        facts = self.store.extract_facts(start_event)
        for fact in facts:
            self.store.record_fact(fact)
        
        # Create job completed event
        complete_time = datetime(2024, 1, 1, 11, 0, 0)
        complete_event = CanonicalEvent(
            event_id='evt_complete',
            correlation_id='corr_001',
            timestamp=complete_time,
            session_id='sess_001',
            job_id='job_workflow',
            user_id='user_001',
            aggregate_type='job',
            aggregate_id='job_workflow',
            event_type='job_completed',
            payload={},
            actor_id='user_001',
            actor_type='user',
            severity='info',
            source='runtime',
        )
        
        # Extract and record
        facts = self.store.extract_facts(complete_event)
        for fact in facts:
            self.store.record_fact(fact)
        
        # Query at start time - should show running
        facts_at_start = self.store.get_facts_at_time(
            'execution', start_time + timedelta(seconds=1)
        )
        self.assertTrue(any(
            f.subject == 'job_workflow' and f.object == 'running'
            for f in facts_at_start
        ))
        
        # Query at complete time - should show completed
        facts_at_complete = self.store.get_facts_at_time(
            'execution', complete_time + timedelta(seconds=1)
        )
        self.assertTrue(any(
            f.subject == 'job_workflow' and f.object == 'completed'
            for f in facts_at_complete
        ))


if __name__ == '__main__':
    unittest.main(verbosity=2)
