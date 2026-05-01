# Harness V2 Phase B Part 3 - Event Integration Layer

**Date**: 2026-04-09  
**Phase**: V2-Phase B Part 3: Event Integration Layer  
**Priority**: HIGH (enables Phase C + D)  
**Status**: Planning & Implementation  

## Objective

Create **automatic, transparent event forwarding** from existing WritingRuntime, skills, and resources systems to the canonical event stream. This bridges the gap between:
- Current event generation (WritingRuntime, AuditLog, ResourceMutations)
- New canonical event storage (Phase B)
- Policy routing (Phase C)

**Key Principle**: No modifications to existing business logic. Pure event forwarding via hooks.

## The Problem This Solves

Currently:
- Canonical events (Phase B) exist but aren't being populated
- WritingRuntime creates jobs but events aren't captured
- Skills/audit produce logs but not canonical events
- Resources mutate but changes aren't tracked in canonical stream
- Phase C policy engine has nothing to route!

**Result**: Memory policy engine (Phase C) starves for events

## Solution Architecture

```
WritingRuntime Job Lifecycle          Skills/Audit Execution
    ↓                                  ↓
Create session/job                   Log action
    ↓                                  ↓
[Hook 1] ──────────────────→ CanonicalEventBuilder ←──[Hook 2]
                              ↓
                         Create canonical event
                              ↓
                    CanonicalEventStore.append()
                              ↓
                         Immutable event trail
                              ↓
                    [Phase C] MemoryPolicyEngine
                              ↓
                         Route to MemPalace/Facts
```

## Three Integration Points

### 1. WritingRuntime Hooks (Job Lifecycle)

**When to capture**:
```python
# In WritingRuntime._create_session()
session_created (event_type='session_created')

# In WritingRuntime._start_job()
job_started (event_type='job_started')

# In WritingRuntime._execute_job()
job_in_progress (event_type='job_in_progress')

# In WritingRuntime.complete_job(result)
job_completed OR job_failed (event_type='job_completed'/'job_failed')

# In WritingRuntime.cancel_job()
job_cancelled (event_type='job_cancelled')
```

**Raw data available**:
- session_id, job_id, user_id
- job_kind, status, result
- duration, error_code, error_message
- artifacts created, approvals needed

### 2. Skills/Audit Hooks (Capability Execution)

**When to capture** (in skills/audit.py):
```python
# In AuditLog.log_action()
execution_started (event_type='execution_started')

# In AuditLog.log_result()
execution_completed OR execution_failed (matches event_type)

# In AuditLog.log_audit()
audit_event (with payload)
```

**Raw data available**:
- skill_name, action_type
- input_params, output_result
- error_code if failed
- timestamp, duration
- actor_id

### 3. Writing Resources Hooks (Resource Mutations)

**When to capture** (in writing_resources.py):
```python
# In WritingResources.save_draft()
resource_modified (event_type='resource_modified')

# In WritingResources.publish_revision()
resource_published (event_type='resource_published')

# In WritingResources.delete_resource()
resource_deleted (event_type='resource_deleted')

# In WritingResources.restore_resource()
resource_restored (event_type='resource_restored')
```

**Raw data available**:
- draft_id, revision_id, project_id
- content_diff, size_change
- status, visibility
- user_id, timestamp

## Implementation: event_integration_layer.py (380 lines)

### Part 1: Hook Registry (100 lines)

```python
class CanonicalEventHook:
    """Base class for event forwarding hooks."""
    
    def on_event(self, source: str, **kwargs) -> CanonicalEvent | None:
        """
        Override to convert source event to canonical event.
        
        Args:
            source: 'runtime' | 'audit' | 'resources'
            **kwargs: Event data
            
        Returns:
            CanonicalEvent or None (skip)
        """
        raise NotImplementedError

class RuntimeEventHook(CanonicalEventHook):
    """Forwards WritingRuntime events to canonical stream."""
    
    def on_event(self, source: str, **kwargs) -> CanonicalEvent | None:
        if source != 'runtime':
            return None
        
        event_type = kwargs.get('event_type')
        if event_type == 'job_started':
            return self._on_job_started(kwargs)
        elif event_type == 'job_completed':
            return self._on_job_completed(kwargs)
        elif event_type == 'job_failed':
            return self._on_job_failed(kwargs)
        # ... etc

class AuditEventHook(CanonicalEventHook):
    """Forwards skills/audit events to canonical stream."""

class ResourceEventHook(CanonicalEventHook):
    """Forwards resource mutation events to canonical stream."""

class EventHookRegistry:
    """Registers and dispatches hooks to subscribe systems."""
    
    def __init__(self, event_store: CanonicalEventStore):
        self.event_store = event_store
        self.hooks: list[CanonicalEventHook] = []
    
    def register_hook(self, hook: CanonicalEventHook) -> None:
        """Register a hook."""
        self.hooks.append(hook)
    
    def fire(self, source: str, **kwargs) -> CanonicalEvent | None:
        """Fire hooks and store resulting event."""
        for hook in self.hooks:
            try:
                event = hook.on_event(source, **kwargs)
                if event:
                    self.event_store.append_event(event)
                    return event
            except Exception:
                continue  # Try next hook
        return None
```

### Part 2: Runtime Integration (120 lines)

```python
class WritingRuntimeAdapter:
    """Adapter to forward WritingRuntime events."""
    
    def __init__(self, hook_registry: EventHookRegistry):
        self.registry = hook_registry
    
    def on_session_created(self, session_id: str, user_id: str) -> None:
        """Forward session creation."""
        self.registry.fire(
            'runtime',
            event_type='session_created',
            session_id=session_id,
            user_id=user_id,
            timestamp=datetime.utcnow(),
        )
    
    def on_job_started(
        self,
        job_id: str,
        session_id: str,
        job_kind: str,
        user_id: str,
    ) -> None:
        """Forward job start."""
        self.registry.fire(
            'runtime',
            event_type='job_started',
            job_id=job_id,
            session_id=session_id,
            aggregate_type='job',
            aggregate_id=job_id,
            payload={'job_kind': job_kind},
            actor_id=user_id,
            timestamp=datetime.utcnow(),
        )
    
    def on_job_completed(
        self,
        job_id: str,
        session_id: str,
        user_id: str,
        duration_seconds: float,
        result_summary: dict,
    ) -> None:
        """Forward job completion with artifacts."""
        self.registry.fire(
            'runtime',
            event_type='job_completed',
            job_id=job_id,
            session_id=session_id,
            aggregate_type='job',
            aggregate_id=job_id,
            payload={
                'duration': duration_seconds,
                'result': result_summary,
                'artifacts': result_summary.get('artifacts', []),
            },
            actor_id=user_id,
            severity='info',
            timestamp=datetime.utcnow(),
        )
    
    def on_job_failed(
        self,
        job_id: str,
        session_id: str,
        user_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        """Forward job failure."""
        self.registry.fire(
            'runtime',
            event_type='job_failed',
            job_id=job_id,
            session_id=session_id,
            aggregate_type='job',
            aggregate_id=job_id,
            error_code=error_code,
            error_message=error_message,
            actor_id=user_id,
            severity='error',
            timestamp=datetime.utcnow(),
        )
```

### Part 3: Audit Integration (80 lines)

```python
class AuditLogAdapter:
    """Adapter to forward skills/audit events."""
    
    def __init__(self, hook_registry: EventHookRegistry):
        self.registry = hook_registry
    
    def on_skill_invoked(
        self,
        skill_name: str,
        action: str,
        job_id: str | None,
        user_id: str,
        input_params: dict,
    ) -> None:
        """Forward skill/capability invocation."""
        self.registry.fire(
            'audit',
            event_type='capability_requested',
            aggregate_type='capability',
            aggregate_id=f'{skill_name}:{action}',
            payload={
                'skill': skill_name,
                'action': action,
                'input_params': input_params,
            },
            actor_id=user_id,
            job_id=job_id,
            timestamp=datetime.utcnow(),
        )
    
    def on_skill_completed(
        self,
        skill_name: str,
        job_id: str | None,
        user_id: str,
        duration_seconds: float,
        result: dict,
    ) -> None:
        """Forward successful skill execution."""
        self.registry.fire(
            'audit',
            event_type='execution_completed',
            aggregate_type='capability',
            aggregate_id=f'{skill_name}:exec',
            payload={
                'skill': skill_name,
                'duration': duration_seconds,
                'result': result,
            },
            actor_id=user_id,
            job_id=job_id,
            severity='info',
            timestamp=datetime.utcnow(),
        )
    
    def on_skill_failed(
        self,
        skill_name: str,
        job_id: str | None,
        user_id: str,
        error: str,
    ) -> None:
        """Forward failed skill execution."""
        self.registry.fire(
            'audit',
            event_type='execution_failed',
            aggregate_type='capability',
            aggregate_id=f'{skill_name}:exec',
            payload={'skill': skill_name, 'error': error},
            error_code='SKILL_ERROR',
            error_message=error,
            actor_id=user_id,
            job_id=job_id,
            severity='error',
            timestamp=datetime.utcnow(),
        )
```

### Part 4: Resource Integration (80 lines)

```python
class ResourceEventAdapter:
    """Adapter to forward writing_resources mutations."""
    
    def __init__(self, hook_registry: EventHookRegistry):
        self.registry = hook_registry
    
    def on_draft_saved(
        self,
        draft_id: str,
        user_id: str,
        content_size: int,
        status: str,
    ) -> None:
        """Forward draft save."""
        self.registry.fire(
            'resources',
            event_type='resource_modified',
            aggregate_type='resource',
            aggregate_id=draft_id,
            payload={
                'resource_type': 'draft',
                'status': status,
                'size': content_size,
            },
            actor_id=user_id,
            timestamp=datetime.utcnow(),
        )
    
    def on_revision_published(
        self,
        draft_id: str,
        revision_id: str,
        user_id: str,
        visibility: str = 'public',
    ) -> None:
        """Forward revision publication."""
        self.registry.fire(
            'resources',
            event_type='resource_published',
            aggregate_type='resource',
            aggregate_id=draft_id,
            payload={
                'resource_type': 'revision',
                'revision_id': revision_id,
                'visibility': visibility,
            },
            actor_id=user_id,
            timestamp=datetime.utcnow(),
        )
    
    def on_resource_deleted(
        self,
        resource_id: str,
        user_id: str,
        resource_type: str = 'draft',
    ) -> None:
        """Forward resource deletion."""
        self.registry.fire(
            'resources',
            event_type='resource_deleted',
            aggregate_type='resource',
            aggregate_id=resource_id,
            payload={'resource_type': resource_type},
            actor_id=user_id,
            timestamp=datetime.utcnow(),
        )
```

## Usage Pattern

### In WritingRuntime
```python
# Initialize once
from event_integration_layer import EventHookRegistry, WritingRuntimeAdapter
from canonical_event_store import CanonicalEventStore

event_store = CanonicalEventStore()  # shared
hook_registry = EventHookRegistry(event_store)
runtime_adapter = WritingRuntimeAdapter(hook_registry)

# In job methods
class WritingRuntime:
    def _create_session(self, ...):
        # ... existing code ...
        runtime_adapter.on_session_created(session_id, user_id)
    
    def _start_job(self, job_id, job_kind, ...):
        # ... existing code ...
        runtime_adapter.on_job_started(job_id, session_id, job_kind, user_id)
    
    def complete_job(self, job_id, result):
        # ... existing code ...
        runtime_adapter.on_job_completed(
            job_id, session_id, user_id,
            duration=elapsed,
            result_summary=result,
        )
```

### In Skills/Audit
```python
from event_integration_layer import AuditLogAdapter

audit_adapter = AuditLogAdapter(hook_registry)

class AuditLog:
    def log_skill_invoked(self, skill_name, ...):
        # ... existing logging ...
        audit_adapter.on_skill_invoked(skill_name, ...)
    
    def log_result(self, skill_name, success, ...):
        if success:
            audit_adapter.on_skill_completed(skill_name, ...)
        else:
            audit_adapter.on_skill_failed(skill_name, ...)
```

### In WritingResources
```python
resource_adapter = ResourceEventAdapter(hook_registry)

class WritingResources:
    def save_draft(self, draft_id, ...):
        # ... existing save ...
        resource_adapter.on_draft_saved(draft_id, user_id, size, status)
    
    def publish_revision(self, draft_id, revision_id, ...):
        # ... existing publish ...
        resource_adapter.on_revision_published(draft_id, revision_id, user_id)
```

## Test Plan (200+ lines)

Tests verify:
1. Hook registry fires correctly
2. Runtime events captured (sessions, jobs)
3. Audit events captured (skills)
4. Resource events captured (mutations)
5. Events properly formatted
6. Deduplication works
7. Errors handled gracefully
8. Performance acceptable

## Benefits

✅ **Transparent**: No business logic changes  
✅ **Automatic**: Events flow without manual calls  
✅ **Complete**: Captures all major execution events  
✅ **Extensible**: New hooks can be added  
✅ **Testable**: Each adapter independently testable  
✅ **Optional**: System works if hooks not registered  

## Success Criteria

- ✅ WritingRuntime events captured
- ✅ Skills/audit events captured  
- ✅ Resource mutations captured
- ✅ All events properly formatted
- ✅ 50+ tests passing
- ✅ <100ms per event forwarding
- ✅ Zero crashes from hooks
- ✅ Backward compatible

## Next Steps

**Phase B Part 3** (Event Integration Layer):
1. Implement adapters
2. Write comprehensive tests
3. Integrate with existing systems
4. Verify event flow end-to-end
5. Performance test

Then **Phase D** can proceed with fact storage.

**Timeline**: 1-2 days implementation

---

**Status**: Ready for implementation  
**Blocks**: Phase D, full memory pipeline  
**Enables**: Automatic canonical event generation
