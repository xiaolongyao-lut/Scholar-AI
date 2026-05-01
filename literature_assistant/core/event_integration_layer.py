# -*- coding: utf-8 -*-
"""
Harness V2 Phase B Part 3: Event Integration Layer

Automatic, transparent event forwarding from existing systems:
- WritingRuntime (job lifecycle)
- Skills/Audit (capability execution)
- Writing Resources (resource mutations)

Bridges current event generation to canonical event stream without
modifying any business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from datetime_utils import utc_now, utc_timestamp
from harness_canonical_events import CanonicalEvent
from canonical_event_store import CanonicalEventStore


class CanonicalEventHook(ABC):
    """Base class for event forwarding hooks."""
    
    @abstractmethod
    def on_event(self, source: str, **kwargs: Any) -> CanonicalEvent | None:
        """
        Convert source event to canonical event.
        
        Args:
            source: Event source identifier
            **kwargs: Event data
            
        Returns:
            CanonicalEvent or None (to skip)
        """
        pass


class RuntimeEventHook(CanonicalEventHook):
    """Forwards WritingRuntime job lifecycle events to canonical stream."""
    
    def __init__(self, event_store: CanonicalEventStore):
        """Initialize with reference to event store."""
        self.event_store = event_store
    
    def on_event(self, source: str, **kwargs: Any) -> CanonicalEvent | None:
        """Forward WritingRuntime events."""
        if source != 'runtime':
            return None
        
        event_type = kwargs.get('event_type')
        
        if event_type == 'session_created':
            return self._create_session_event(kwargs)
        elif event_type == 'job_started':
            return self._create_job_started_event(kwargs)
        elif event_type == 'job_completed':
            return self._create_job_completed_event(kwargs)
        elif event_type == 'job_failed':
            return self._create_job_failed_event(kwargs)
        elif event_type == 'job_cancelled':
            return self._create_job_cancelled_event(kwargs)
        
        return None
    
    @staticmethod
    def _create_session_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create session created event."""
        session_id = data['session_id']
        return CanonicalEvent(
            event_id=f'evt_session_{session_id}_{utc_timestamp()}',
            correlation_id=f'sess_{session_id}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=session_id,
            job_id=None,
            user_id=data['user_id'],
            aggregate_type='session',
            aggregate_id=session_id,
            event_type='session_created',
            payload={},
            actor_id=data['user_id'],
            actor_type='user',
            severity='info',
            previous_state=None,
            new_state=None,
            error_code=None,
            error_message=None,
            source='runtime',
        )
    
    @staticmethod
    def _create_job_started_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create job started event."""
        job_id = data['job_id']
        return CanonicalEvent(
            event_id=f'evt_job_start_{job_id}_{utc_timestamp()}',
            correlation_id=f'job_{job_id}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data['session_id'],
            job_id=job_id,
            user_id=data['user_id'],
            aggregate_type='job',
            aggregate_id=job_id,
            event_type='job_started',
            payload={'job_kind': data.get('job_kind', 'unknown')},
            actor_id=data['user_id'],
            actor_type='user',
            severity='info',
            previous_state=None,
            new_state=None,
            error_code=None,
            error_message=None,
            source='runtime',
        )
    
    @staticmethod
    def _create_job_completed_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create job completed event."""
        job_id = data['job_id']
        return CanonicalEvent(
            event_id=f'evt_job_done_{job_id}_{utc_timestamp()}',
            correlation_id=f'job_{job_id}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data['session_id'],
            job_id=job_id,
            user_id=data['user_id'],
            aggregate_type='job',
            aggregate_id=job_id,
            event_type='job_completed',
            payload=data.get('result_summary', {}),
            actor_id=data['user_id'],
            actor_type='user',
            severity='info',
            previous_state={'status': 'in_progress'},
            new_state={'status': 'completed'},
            error_code=None,
            error_message=None,
            source='runtime',
        )
    
    @staticmethod
    def _create_job_failed_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create job failed event."""
        job_id = data['job_id']
        return CanonicalEvent(
            event_id=f'evt_job_fail_{job_id}_{utc_timestamp()}',
            correlation_id=f'job_{job_id}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data['session_id'],
            job_id=job_id,
            user_id=data['user_id'],
            aggregate_type='job',
            aggregate_id=job_id,
            event_type='job_failed',
            payload={'error_details': data.get('error_details', {})},
            actor_id=data['user_id'],
            actor_type='user',
            severity='error',
            previous_state={'status': 'in_progress'},
            new_state={'status': 'failed'},
            error_code=data.get('error_code'),
            error_message=data.get('error_message'),
            source='runtime',
        )
    
    @staticmethod
    def _create_job_cancelled_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create job cancelled event."""
        job_id = data['job_id']
        return CanonicalEvent(
            event_id=f'evt_job_cancel_{job_id}_{utc_timestamp()}',
            correlation_id=f'job_{job_id}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data['session_id'],
            job_id=job_id,
            user_id=data['user_id'],
            aggregate_type='job',
            aggregate_id=job_id,
            event_type='job_cancelled',
            payload={'reason': data.get('reason', 'user_cancelled')},
            actor_id=data['user_id'],
            actor_type='user',
            severity='info',
            previous_state={'status': 'in_progress'},
            new_state={'status': 'cancelled'},
            error_code=None,
            error_message=None,
            source='runtime',
        )


class AuditEventHook(CanonicalEventHook):
    """Forwards skills/audit capability execution events."""
    
    def __init__(self, event_store: CanonicalEventStore):
        """Initialize with reference to event store."""
        self.event_store = event_store
    
    def on_event(self, source: str, **kwargs: Any) -> CanonicalEvent | None:
        """Forward audit events."""
        if source != 'audit':
            return None
        
        event_type = kwargs.get('event_type')
        
        if event_type == 'capability_requested':
            return self._create_capability_requested_event(kwargs)
        elif event_type == 'execution_started':
            return self._create_execution_started_event(kwargs)
        elif event_type == 'execution_completed':
            return self._create_execution_completed_event(kwargs)
        elif event_type == 'execution_failed':
            return self._create_execution_failed_event(kwargs)
        
        return None
    
    @staticmethod
    def _create_capability_requested_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create capability request event."""
        skill_name = data.get('skill_name', 'unknown')
        agg_id = f'{skill_name}:request'
        
        return CanonicalEvent(
            event_id=f'evt_cap_req_{agg_id}_{utc_timestamp()}',
            correlation_id=f'cap_{skill_name}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data.get('session_id'),
            job_id=data.get('job_id'),
            user_id=data.get('user_id', 'system'),
            aggregate_type='capability',
            aggregate_id=agg_id,
            event_type='capability_requested',
            payload={'skill': skill_name, 'action': data.get('action')},
            actor_id=data.get('user_id', 'system'),
            actor_type='user',
            severity='info',
            previous_state=None,
            new_state=None,
            error_code=None,
            error_message=None,
            source='audit',
        )
    
    @staticmethod
    def _create_execution_started_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create execution started event."""
        skill_name = data.get('skill_name', 'unknown')
        agg_id = f'{skill_name}:exec'
        
        return CanonicalEvent(
            event_id=f'evt_exec_start_{agg_id}_{utc_timestamp()}',
            correlation_id=f'exec_{skill_name}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data.get('session_id'),
            job_id=data.get('job_id'),
            user_id=data.get('user_id', 'system'),
            aggregate_type='capability',
            aggregate_id=agg_id,
            event_type='execution_started',
            payload={'skill': skill_name},
            actor_id=data.get('user_id', 'system'),
            actor_type='user',
            severity='info',
            previous_state=None,
            new_state=None,
            error_code=None,
            error_message=None,
            source='audit',
        )
    
    @staticmethod
    def _create_execution_completed_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create execution completed event."""
        skill_name = data.get('skill_name', 'unknown')
        agg_id = f'{skill_name}:exec'
        
        return CanonicalEvent(
            event_id=f'evt_exec_done_{agg_id}_{utc_timestamp()}',
            correlation_id=f'exec_{skill_name}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data.get('session_id'),
            job_id=data.get('job_id'),
            user_id=data.get('user_id', 'system'),
            aggregate_type='capability',
            aggregate_id=agg_id,
            event_type='execution_completed',
            payload={
                'skill': skill_name,
                'duration': data.get('duration_seconds', 0),
            },
            actor_id=data.get('user_id', 'system'),
            actor_type='user',
            severity='info',
            previous_state={'status': 'executing'},
            new_state={'status': 'completed'},
            error_code=None,
            error_message=None,
            source='audit',
        )
    
    @staticmethod
    def _create_execution_failed_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create execution failed event."""
        skill_name = data.get('skill_name', 'unknown')
        agg_id = f'{skill_name}:exec'
        
        return CanonicalEvent(
            event_id=f'evt_exec_fail_{agg_id}_{utc_timestamp()}',
            correlation_id=f'exec_{skill_name}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data.get('session_id'),
            job_id=data.get('job_id'),
            user_id=data.get('user_id', 'system'),
            aggregate_type='capability',
            aggregate_id=agg_id,
            event_type='execution_failed',
            payload={'skill': skill_name, 'error': data.get('error')},
            actor_id=data.get('user_id', 'system'),
            actor_type='user',
            severity='error',
            previous_state={'status': 'executing'},
            new_state={'status': 'failed'},
            error_code='EXECUTION_ERROR',
            error_message=data.get('error_message', 'Skill execution failed'),
            source='audit',
        )


class ResourceEventHook(CanonicalEventHook):
    """Forwards writing_resources mutations to canonical stream."""
    
    def __init__(self, event_store: CanonicalEventStore):
        """Initialize with reference to event store."""
        self.event_store = event_store
    
    def on_event(self, source: str, **kwargs: Any) -> CanonicalEvent | None:
        """Forward resource events."""
        if source != 'resources':
            return None
        
        event_type = kwargs.get('event_type')
        
        if event_type == 'resource_modified':
            return self._create_resource_modified_event(kwargs)
        elif event_type == 'resource_published':
            return self._create_resource_published_event(kwargs)
        elif event_type == 'resource_deleted':
            return self._create_resource_deleted_event(kwargs)
        elif event_type == 'resource_restored':
            return self._create_resource_restored_event(kwargs)
        
        return None
    
    @staticmethod
    def _create_resource_modified_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create resource modified event."""
        res_id = data['resource_id']
        
        return CanonicalEvent(
            event_id=f'evt_res_mod_{res_id}_{utc_timestamp()}',
            correlation_id=f'res_{res_id}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data.get('session_id'),
            job_id=data.get('job_id'),
            user_id=data['user_id'],
            aggregate_type='resource',
            aggregate_id=res_id,
            event_type='resource_modified',
            payload={
                'resource_type': data.get('resource_type', 'draft'),
                'status': data.get('status', 'draft'),
                'size': data.get('content_size', 0),
            },
            actor_id=data['user_id'],
            actor_type='user',
            severity='info',
            previous_state=None,
            new_state={'status': data.get('status', 'draft')},
            error_code=None,
            error_message=None,
            source='resources',
        )
    
    @staticmethod
    def _create_resource_published_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create resource published event."""
        res_id = data['resource_id']
        
        return CanonicalEvent(
            event_id=f'evt_res_pub_{res_id}_{utc_timestamp()}',
            correlation_id=f'res_{res_id}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data.get('session_id'),
            job_id=data.get('job_id'),
            user_id=data['user_id'],
            aggregate_type='resource',
            aggregate_id=res_id,
            event_type='resource_published',
            payload={
                'resource_type': data.get('resource_type', 'revision'),
                'revision_id': data.get('revision_id'),
                'visibility': data.get('visibility', 'public'),
            },
            actor_id=data['user_id'],
            actor_type='user',
            severity='info',
            previous_state={'status': 'draft'},
            new_state={'status': 'published'},
            error_code=None,
            error_message=None,
            source='resources',
        )
    
    @staticmethod
    def _create_resource_deleted_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create resource deleted event."""
        res_id = data['resource_id']
        
        return CanonicalEvent(
            event_id=f'evt_res_del_{res_id}_{utc_timestamp()}',
            correlation_id=f'res_{res_id}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data.get('session_id'),
            job_id=data.get('job_id'),
            user_id=data['user_id'],
            aggregate_type='resource',
            aggregate_id=res_id,
            event_type='resource_deleted',
            payload={'resource_type': data.get('resource_type', 'draft')},
            actor_id=data['user_id'],
            actor_type='user',
            severity='info',
            previous_state={'status': 'active'},
            new_state={'status': 'deleted'},
            error_code=None,
            error_message=None,
            source='resources',
        )
    
    @staticmethod
    def _create_resource_restored_event(data: dict[str, Any]) -> CanonicalEvent:
        """Create resource restored event."""
        res_id = data['resource_id']
        
        return CanonicalEvent(
            event_id=f'evt_res_restore_{res_id}_{utc_timestamp()}',
            correlation_id=f'res_{res_id}',
            timestamp=data.get('timestamp', utc_now()),
            session_id=data.get('session_id'),
            job_id=data.get('job_id'),
            user_id=data['user_id'],
            aggregate_type='resource',
            aggregate_id=res_id,
            event_type='resource_restored',
            payload={'resource_type': data.get('resource_type', 'draft')},
            actor_id=data['user_id'],
            actor_type='user',
            severity='info',
            previous_state={'status': 'deleted'},
            new_state={'status': 'restored'},
            error_code=None,
            error_message=None,
            source='resources',
        )


class EventHookRegistry:
    """
    Registers and dispatches hooks for automatic event forwarding.
    
    Enables transparent integration of existing systems with canonical
    event stream without modifying business logic.
    """
    
    def __init__(self, event_store: CanonicalEventStore):
        """Initialize registry with event store."""
        self.event_store = event_store
        self.hooks: list[CanonicalEventHook] = []
        self._register_default_hooks()
    
    def _register_default_hooks(self) -> None:
        """Register built-in hooks."""
        self.hooks.append(RuntimeEventHook(self.event_store))
        self.hooks.append(AuditEventHook(self.event_store))
        self.hooks.append(ResourceEventHook(self.event_store))
    
    def register_hook(self, hook: CanonicalEventHook) -> None:
        """
        Register a custom hook.
        
        Args:
            hook: CanonicalEventHook subclass
        """
        self.hooks.append(hook)
    
    def fire(self, source: str, **kwargs: Any) -> CanonicalEvent | None:
        """
        Fire hooks and store resulting event.
        
        Args:
            source: Event source identifier
            **kwargs: Event data
            
        Returns:
            CanonicalEvent that was stored, or None
        """
        for hook in self.hooks:
            try:
                event = hook.on_event(source, **kwargs)
                if event:
                    # Store immutably
                    self.event_store.append_event(event)
                    return event
            except (AttributeError, KeyError, TypeError):
                # Hook failed; try next
                continue
        
        return None
    
    def get_hook_count(self) -> int:
        """Get number of registered hooks."""
        return len(self.hooks)


def create_default_registry(event_store: CanonicalEventStore) -> EventHookRegistry:
    """
    Factory function to create registry with default hooks.
    
    Args:
        event_store: Shared CanonicalEventStore instance
        
    Returns:
        Configured EventHookRegistry ready for use
    """
    return EventHookRegistry(event_store)
