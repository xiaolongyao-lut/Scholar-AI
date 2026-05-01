# -*- coding: utf-8 -*-
"""
Tests for Harness V2 Phase B Part 3: Event Integration Layer

Coverage:
- Hook registration
- Runtime event forwarding (jobs)
- Audit event forwarding (skills)
- Resource event forwarding (mutations)
- Integration end-to-end
- Error handling
"""

import unittest
import tempfile
import os

from datetime_utils import utc_now_naive

from event_integration_layer import (
    EventHookRegistry,
    RuntimeEventHook,
    AuditEventHook,
    ResourceEventHook,
    create_default_registry,
)
from canonical_event_store import CanonicalEventStore


class TestRuntimeEventHook(unittest.TestCase):
    """Tests for WritingRuntime event forwarding."""
    
    def setUp(self):
        """Initialize for each test."""
        # Use temp database file
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.event_store = CanonicalEventStore(self.temp_db.name)
        self.hook = RuntimeEventHook(self.event_store)
    
    def tearDown(self):
        """Clean up temp database."""
        try:
            os.unlink(self.temp_db.name)
        except FileNotFoundError:
            pass
    
    def test_session_created_event(self):
        """Session creation events are forwarded."""
        event = self.hook.on_event(
            'runtime',
            event_type='session_created',
            session_id='sess_001',
            user_id='user_123',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'session_created')
        self.assertEqual(event.aggregate_type, 'session')
        self.assertEqual(event.session_id, 'sess_001')
        self.assertEqual(event.actor_id, 'user_123')
    
    def test_job_started_event(self):
        """Job start events are forwarded."""
        event = self.hook.on_event(
            'runtime',
            event_type='job_started',
            job_id='job_001',
            session_id='sess_001',
            job_kind='refactor',
            user_id='user_123',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'job_started')
        self.assertEqual(event.aggregate_type, 'job')
        self.assertEqual(event.job_id, 'job_001')
        self.assertEqual(event.payload['job_kind'], 'refactor')
    
    def test_job_completed_event(self):
        """Job completion events are forwarded."""
        result = {'status': 'success', 'artifacts': ['art_001']}
        
        event = self.hook.on_event(
            'runtime',
            event_type='job_completed',
            job_id='job_001',
            session_id='sess_001',
            user_id='user_123',
            result_summary=result,
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'job_completed')
        self.assertEqual(event.severity, 'info')
        self.assertEqual(event.error_code, None)
        self.assertEqual(event.new_state['status'], 'completed')
    
    def test_job_failed_event(self):
        """Job failure events are forwarded."""
        event = self.hook.on_event(
            'runtime',
            event_type='job_failed',
            job_id='job_001',
            session_id='sess_001',
            user_id='user_123',
            error_code='ERR_TIMEOUT',
            error_message='Job timed out',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'job_failed')
        self.assertEqual(event.severity, 'error')
        self.assertEqual(event.error_code, 'ERR_TIMEOUT')
        self.assertEqual(event.new_state['status'], 'failed')
    
    def test_job_cancelled_event(self):
        """Job cancellation events are forwarded."""
        event = self.hook.on_event(
            'runtime',
            event_type='job_cancelled',
            job_id='job_001',
            session_id='sess_001',
            user_id='user_123',
            reason='user_requested',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'job_cancelled')
        self.assertEqual(event.new_state['status'], 'cancelled')
    
    def test_non_runtime_event_ignored(self):
        """Non-runtime events are ignored."""
        event = self.hook.on_event(
            'resources',  # Wrong source
            event_type='job_started',
            job_id='job_001',
            session_id='sess_001',
            job_kind='test',
            user_id='user_123',
        )
        
        self.assertIsNone(event)
    
    def test_unknown_event_type_ignored(self):
        """Unknown event types are ignored."""
        event = self.hook.on_event(
            'runtime',
            event_type='unknown_type',
            job_id='job_001',
        )
        
        self.assertIsNone(event)


class TestAuditEventHook(unittest.TestCase):
    """Tests for skills/audit event forwarding."""
    
    def setUp(self):
        """Initialize for each test."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.event_store = CanonicalEventStore(self.temp_db.name)
        self.hook = AuditEventHook(self.event_store)
    
    def tearDown(self):
        """Clean up temp database."""
        try:
            os.unlink(self.temp_db.name)
        except FileNotFoundError:
            pass
    
    def test_capability_requested_event(self):
        """Capability request events are forwarded."""
        event = self.hook.on_event(
            'audit',
            event_type='capability_requested',
            skill_name='code_generator',
            action='generate',
            session_id='sess_001',
            job_id='job_001',
            user_id='user_123',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'capability_requested')
        self.assertEqual(event.aggregate_type, 'capability')
        self.assertEqual(event.payload['skill'], 'code_generator')
    
    def test_execution_started_event(self):
        """Execution start events are forwarded."""
        event = self.hook.on_event(
            'audit',
            event_type='execution_started',
            skill_name='code_generator',
            session_id='sess_001',
            job_id='job_001',
            user_id='user_123',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'execution_started')
    
    def test_execution_completed_event(self):
        """Execution completion events are forwarded."""
        event = self.hook.on_event(
            'audit',
            event_type='execution_completed',
            skill_name='code_generator',
            duration_seconds=5.2,
            session_id='sess_001',
            job_id='job_001',
            user_id='user_123',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'execution_completed')
        self.assertEqual(event.severity, 'info')
        self.assertEqual(event.payload['duration'], 5.2)
        self.assertEqual(event.new_state['status'], 'completed')
    
    def test_execution_failed_event(self):
        """Execution failure events are forwarded."""
        event = self.hook.on_event(
            'audit',
            event_type='execution_failed',
            skill_name='code_generator',
            error='Invalid input format',
            error_message='Skill execution failed',
            session_id='sess_001',
            job_id='job_001',
            user_id='user_123',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'execution_failed')
        self.assertEqual(event.severity, 'error')
        self.assertEqual(event.error_code, 'EXECUTION_ERROR')
    
    def test_non_audit_event_ignored(self):
        """Non-audit events are ignored."""
        event = self.hook.on_event(
            'runtime',  # Wrong source
            event_type='execution_completed',
            skill_name='test',
        )
        
        self.assertIsNone(event)


class TestResourceEventHook(unittest.TestCase):
    """Tests for writing_resources event forwarding."""
    
    def setUp(self):
        """Initialize for each test."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.event_store = CanonicalEventStore(self.temp_db.name)
        self.hook = ResourceEventHook(self.event_store)
    
    def tearDown(self):
        """Clean up temp database."""
        try:
            os.unlink(self.temp_db.name)
        except FileNotFoundError:
            pass
    
    def test_resource_modified_event(self):
        """Resource modification events are forwarded."""
        event = self.hook.on_event(
            'resources',
            event_type='resource_modified',
            resource_id='draft_001',
            user_id='user_123',
            resource_type='draft',
            status='draft',
            content_size=5000,
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'resource_modified')
        self.assertEqual(event.aggregate_type, 'resource')
        self.assertEqual(event.payload['resource_type'], 'draft')
        self.assertEqual(event.payload['size'], 5000)
    
    def test_resource_published_event(self):
        """Resource publication events are forwarded."""
        event = self.hook.on_event(
            'resources',
            event_type='resource_published',
            resource_id='draft_001',
            revision_id='rev_001',
            user_id='user_123',
            visibility='public',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'resource_published')
        self.assertEqual(event.payload['revision_id'], 'rev_001')
        self.assertEqual(event.payload['visibility'], 'public')
        self.assertEqual(event.new_state['status'], 'published')
    
    def test_resource_deleted_event(self):
        """Resource deletion events are forwarded."""
        event = self.hook.on_event(
            'resources',
            event_type='resource_deleted',
            resource_id='draft_001',
            user_id='user_123',
            resource_type='draft',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'resource_deleted')
        self.assertEqual(event.new_state['status'], 'deleted')
    
    def test_resource_restored_event(self):
        """Resource restoration events are forwarded."""
        event = self.hook.on_event(
            'resources',
            event_type='resource_restored',
            resource_id='draft_001',
            user_id='user_123',
            timestamp=utc_now_naive(),
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'resource_restored')
        self.assertEqual(event.new_state['status'], 'restored')
    
    def test_non_resource_event_ignored(self):
        """Non-resource events are ignored."""
        event = self.hook.on_event(
            'runtime',  # Wrong source
            event_type='resource_modified',
            resource_id='draft_001',
        )
        
        self.assertIsNone(event)


class TestEventHookRegistry(unittest.TestCase):
    """Tests for the hook registry and dispatch."""
    
    def setUp(self):
        """Initialize for each test."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.event_store = CanonicalEventStore(self.temp_db.name)
        self.registry = EventHookRegistry(self.event_store)
    
    def tearDown(self):
        """Clean up temp database."""
        try:
            os.unlink(self.temp_db.name)
        except FileNotFoundError:
            pass
    
    def test_registry_has_default_hooks(self):
        """Registry initializes with default hooks."""
        self.assertGreaterEqual(self.registry.get_hook_count(), 3)
    
    def test_fire_runtime_event(self):
        """Registry fires runtime events correctly."""
        event = self.registry.fire(
            'runtime',
            event_type='job_started',
            job_id='job_001',
            session_id='sess_001',
            job_kind='test',
            user_id='user_123',
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'job_started')
        
        # Verify stored
        stored = self.event_store.get_event_by_id(event.event_id)
        self.assertIsNotNone(stored)
    
    def test_fire_audit_event(self):
        """Registry fires audit events correctly."""
        event = self.registry.fire(
            'audit',
            event_type='execution_completed',
            skill_name='test_skill',
            duration_seconds=1.0,
            user_id='user_123',
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'execution_completed')
    
    def test_fire_resource_event(self):
        """Registry fires resource events correctly."""
        event = self.registry.fire(
            'resources',
            event_type='resource_modified',
            resource_id='draft_001',
            user_id='user_123',
            resource_type='draft',
        )
        
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'resource_modified')
    
    def test_fire_unknown_source_ignored(self):
        """Unknown sources are ignored."""
        event = self.registry.fire(
            'unknown_source',
            event_type='some_event',
        )
        
        self.assertIsNone(event)
    
    def test_register_custom_hook(self):
        """Custom hooks can be registered."""
        from event_integration_layer import CanonicalEventHook
        
        class CustomHook(CanonicalEventHook):
            def __init__(self, event_store):
                self.event_store = event_store
            
            def on_event(self, source, **kwargs):
                if source == 'custom':
                    from harness_canonical_events import CanonicalEvent
                    return CanonicalEvent(
                        event_id='evt_custom_001',
                        correlation_id='custom_001',
                        timestamp=utc_now_naive(),
                        session_id=None,
                        job_id=None,
                        user_id='system',
                        aggregate_type='custom',
                        aggregate_id='custom_001',
                        event_type='custom_event',
                        payload={},
                        actor_id='system',
                        actor_type='system',
                        severity='info',
                        previous_state=None,
                        new_state=None,
                        error_code=None,
                        error_message=None,
                        source='custom',
                    )
                return None
        
        self.registry.register_hook(CustomHook(self.event_store))
        
        event = self.registry.fire('custom', event_type='custom_event')
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 'custom_event')
    
    def test_event_immutability_on_storage(self):
        """Stored events are immutable."""
        event = self.registry.fire(
            'runtime',
            event_type='job_started',
            job_id='job_001',
            session_id='sess_001',
            job_kind='test',
            user_id='user_123',
        )
        
        # Retrieve and verify immutability
        stored = self.event_store.get_event_by_id(event.event_id)
        with self.assertRaises(AttributeError):
            stored.event_type = 'modified'


class TestEventIntegrationEndToEnd(unittest.TestCase):
    """End-to-end integration tests."""
    
    def setUp(self):
        """Initialize for each test."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.event_store = CanonicalEventStore(self.temp_db.name)
        self.registry = create_default_registry(self.event_store)
    
    def tearDown(self):
        """Clean up temp database."""
        try:
            os.unlink(self.temp_db.name)
        except FileNotFoundError:
            pass
    
    def test_full_job_workflow_events(self):
        """Process complete job workflow through registry."""
        session_id = 'integration_session_001'
        job_id = 'integration_job_001'
        user_id = 'integration_user'
        
        # 1. Create session
        session_event = self.registry.fire(
            'runtime',
            event_type='session_created',
            session_id=session_id,
            user_id=user_id,
        )
        self.assertIsNotNone(session_event)
        
        # 2. Start job
        start_event = self.registry.fire(
            'runtime',
            event_type='job_started',
            job_id=job_id,
            session_id=session_id,
            job_kind='integration_test',
            user_id=user_id,
        )
        self.assertIsNotNone(start_event)
        
        # 3. Complete job
        complete_event = self.registry.fire(
            'runtime',
            event_type='job_completed',
            job_id=job_id,
            session_id=session_id,
            user_id=user_id,
            result_summary={'status': 'success'},
        )
        self.assertIsNotNone(complete_event)
        
        # 4. Verify timeline
        timeline = self.event_store.get_job_timeline(job_id)
        self.assertGreaterEqual(len(timeline), 2)
        self.assertEqual(timeline[0].event_type, 'job_started')
        self.assertEqual(timeline[-1].event_type, 'job_completed')
    
    def test_resource_and_audit_workflow(self):
        """Process resource + audit events together."""
        # Resource modified
        res_event = self.registry.fire(
            'resources',
            event_type='resource_modified',
            resource_id='res_001',
            user_id='user_001',
            resource_type='draft',
        )
        self.assertIsNotNone(res_event)
        
        # Skill executed
        skill_event = self.registry.fire(
            'audit',
            event_type='execution_completed',
            skill_name='analyzer',
            user_id='user_001',
            duration_seconds=2.0,
        )
        self.assertIsNotNone(skill_event)
        
        # Verify both stored
        self.assertEqual(res_event.aggregate_type, 'resource')
        self.assertEqual(skill_event.aggregate_type, 'capability')


if __name__ == '__main__':
    unittest.main(verbosity=2)
