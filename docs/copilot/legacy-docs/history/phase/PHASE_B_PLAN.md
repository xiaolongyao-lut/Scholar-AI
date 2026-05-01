# Harness V2 Phase B - Event History Unification

**Status**: Planning  
**Target Scope**: Unified event envelope and event stream consolidation  
**Dependencies**: Phase A (Durable Harness State) ✅ Complete  

## Objective

Merge three currently-separate event systems into one canonical event stream:

1. **WritingEvent** (harness_protocols.py) - Job lifecycle events
2. **AuditEvent** (skills/audit.py) - Capability execution audit trail
3. **RevisionEvent** (from writing_resources.py) - Resource/draft mutation history

Result: All job execution, capability changes, and resource writes can be traced via a unified timeline.

## Current State Analysis

### WritingEvent (Protocol Layer)
**Location**: harness_protocols.py line 237  
**Current Fields**:
- event_id, job_id, session_id
- event_type (EventType enum)
- timestamp (ISO 8601)
- data, metadata (generic dicts)

**Event Types**: ~14 types (job_created, job_started, approval_required, artifact_created, etc)

**Limitation**: Only captures job-level events; doesn't track resource mutations or audit context

### AuditEvent (Audit Layer)
**Location**: skills/audit.py line 31  
**Current Fields**:
- event_id, event_type (AuditEventType enum)
- timestamp
- job_id, capability_id, user_id, session_id
- description, status, severity
- context, previous_state, new_state
- error_code, error_message

**Event Types**: ~11 types (job_created, capability_resolved, approval_requested, execution_attempted, etc)

**Limitation**: Parallel to WritingEvent; not integrated into durable state

### RevisionEvent (Resource Layer)
**Location**: writing_resources.py (WritingRevision class)  
**Current Fields**:
- revision_id
- draft_id
- created_at, modified_at
- content (markdown)
- revision_number
- created_by, notes

**Limitation**: Revision history only; not part of central event stream

## Design: Canonical Event Envelope

### CanonicalEvent (New)
```python
@dataclass(frozen=True)
class CanonicalEvent:
    """Unified event envelope for all Harness state changes."""
    
    # Universal identifier
    event_id: str
    correlation_id: str  # Links events that are part of same logical flow
    
    # Time
    timestamp: str  # ISO 8601 UTC
    
    # Context (aggregates across all three sources)
    session_id: str | None
    job_id: str | None
    user_id: str | None
    
    # Event classification
    aggregate_type: str  # 'job' | 'capability' | 'resource' | 'approval' | 'artifact'
    aggregate_id: str  # ID of the affected entity
    event_type: str  # Unified enum combining all EventType + AuditEventType
    
    # Data payload (event-specific)
    payload: dict[str, Any]  # Replaces 'data' - clearer semantics
    
    # Metadata (audit trail)
    actor_id: str | None  # Who triggered it (user/system)
    actor_type: str  # 'user' | 'system' | 'workflow'
    severity: str  # 'debug' | 'info' | 'warning' | 'error' | 'critical'
    
    # Optional state tracking
    previous_state: dict[str, Any] | None  # For resource changes
    new_state: dict[str, Any] | None  # For resource changes
    
    # Optional error info
    error_code: str | None
    error_message: str | None
    
    # Source tracking (for migration/debugging)
    source: str  # 'writing_runtime' | 'skills_audit' | 'resource_manager'
```

### Unified Event Type Enum
```python
class CanonicalEventType(str, Enum):
    # Job lifecycle
    JOB_CREATED = "job_created"
    JOB_STARTED = "job_started"
    JOB_PAUSED = "job_paused"
    JOB_RESUMED = "job_resumed"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"
    
    # Capability execution
    CAPABILITY_RESOLVED = "capability_resolved"
    EXECUTION_ATTEMPTED = "execution_attempted"
    EXECUTION_BLOCKED = "execution_blocked"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    
    # Approvals
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    
    # Artifacts
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_UPDATED = "artifact_updated"
    ARTIFACT_FINALIZED = "artifact_finalized"
    
    # Resources (draft/revision)
    RESOURCE_CREATED = "resource_created"
    RESOURCE_MODIFIED = "resource_modified"
    RESOURCE_PUBLISHED = "resource_published"
    RESOURCE_DELETED = "resource_deleted"
    
    # Errors
    ERROR_OCCURRED = "error_occurred"
```

## Implementation Plan

### Part 1: Create Canonical Event Infrastructure (harness_canonical_events.py)

**450 lines** covering:
1. CanonicalEvent dataclass (immutable, frozen)
2. CanonicalEventType enum (unified types)
3. CanonicalEventBuilder - fluent API for creating events
4. EventConverter - static methods to convert from:
   - WritingEvent → CanonicalEvent
   - AuditEvent → CanonicalEvent
   - WritingRevision → CanonicalEvent

**Example converters**:
```python
@staticmethod
def from_writing_event(event: WritingEvent) -> CanonicalEvent:
    """Convert WritingEvent to CanonicalEvent."""
    return CanonicalEvent(
        event_id=event.event_id,
        correlation_id=event.metadata.get('correlation_id', event.event_id),
        timestamp=event.timestamp,
        session_id=event.session_id,
        job_id=event.job_id,
        aggregate_type='job',
        aggregate_id=event.job_id,
        event_type=EventConverter.map_writing_event_type(event.event_type),
        payload=event.data,
        actor_id=event.metadata.get('actor_id'),
        source='writing_runtime',
    )

@staticmethod
def from_audit_event(event: AuditEvent) -> CanonicalEvent:
    """Convert AuditEvent to CanonicalEvent."""
    agg_type = 'capability' if event.capability_id else 'job'
    return CanonicalEvent(
        event_id=event.event_id,
        timestamp=event.timestamp,
        session_id=event.session_id,
        job_id=event.job_id,
        aggregate_type=agg_type,
        aggregate_id=event.capability_id or event.job_id,
        event_type=event.event_type,
        payload={'description': event.description},
        actor_id=event.user_id,
        severity=event.severity,
        previous_state=event.previous_state,
        new_state=event.new_state,
        source='skills_audit',
    )

@staticmethod
def from_revision(revision: WritingRevision, draft_id: str) -> CanonicalEvent:
    """Convert WritingRevision to CanonicalEvent."""
    return CanonicalEvent(
        event_id=f"event_{uuid4().hex[:16]}",
        timestamp=revision.created_at,
        aggregate_type='resource',
        aggregate_id=draft_id,
        event_type='resource_modified',
        payload={
            'revision_id': revision.revision_id,
            'revision_number': revision.revision_number,
            'notes': revision.notes,
        },
        actor_id=revision.created_by,
        source='resource_manager',
    )
```

### Part 2: Event Stream Repository (canonical_event_store.py)

**350 lines** covering:
1. CanonicalEventStore - new table in harness database
2. Write canonical events to SQLite
3. Query by:
   - job_id
   - session_id
   - aggregate_type
   - date range
   - actor_id
4. Export timeline for job execution
5. Rebuild full state from event stream

**Key methods**:
```python
def append_canonical_event(self, event: CanonicalEvent) -> None
def get_job_timeline(self, job_id: str) -> list[CanonicalEvent]
def get_session_timeline(self, session_id: str) -> list[CanonicalEvent]
def get_events_by_type(self, event_type: str, limit: int = 100) -> list[CanonicalEvent]
def export_timeline_report(self, job_id: str) -> dict
```

### Part 3: Integration Adapters (event_integration_layer.py)

**400 lines** covering:
1. HarnessStoreIntegration - extend Phase A store to handle canonical events
2. AuditIntegration - hook into skills/audit.py
3. ResourceIntegration - hook into writing_resources.py
4. Auto-convert and forward events:
   - WritingEvent → append to canonical stream
   - AuditEvent → append to canonical stream
   - RevisionEvent → append to canonical stream

**Key pattern**:
```python
@staticmethod
def forward_writing_event(event: WritingEvent, store: HarnessStore) -> None:
    """When WritingEvent created, also append to canonical stream."""
    canonical = EventConverter.from_writing_event(event)
    store.append_canonical_event(canonical)

@staticmethod
def forward_audit_event(event: AuditEvent, store: HarnessStore) -> None:
    """When AuditEvent logged, also append to canonical stream."""
    canonical = EventConverter.from_audit_event(event)
    store.append_canonical_event(canonical)
```

### Part 4: Comprehensive Tests (test_canonical_events.py)

**400 lines** covering:
1. CanonicalEvent creation and validation
2. Conversion from each source type (WritingEvent, AuditEvent, Revision)
3. Event sorting and ordering
4. Timeline export
5. Query operations
6. Round-trip: Create → Store → Retrieve → Verify
7. Smoke test: Full job lifecycle with unified timeline

## Database Schema Addition

**New table** (extends Phase A schema):
```sql
CREATE TABLE IF NOT EXISTS canonical_events (
    id INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    correlation_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    session_id TEXT,
    job_id TEXT,
    aggregate_type TEXT NOT NULL,  -- 'job', 'capability', 'resource', 'approval', 'artifact'
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSON NOT NULL,
    actor_id TEXT,
    actor_type TEXT,
    severity TEXT DEFAULT 'info',
    previous_state JSON,
    new_state JSON,
    error_code TEXT,
    error_message TEXT,
    source TEXT NOT NULL,  -- 'writing_runtime', 'skills_audit', 'resource_manager'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY(session_id) REFERENCES sessions(session_id),
    FOREIGN KEY(job_id) REFERENCES jobs(job_id),
    INDEX idx_job_id (job_id),
    INDEX idx_session_id (session_id),
    INDEX idx_event_type (event_type),
    INDEX idx_timestamp (timestamp),
    INDEX idx_aggregate (aggregate_type, aggregate_id)
);
```

## Migration Strategy

**Zero Breaking Changes**:
1. Phase A store remains unchanged
2. WritingEvent, AuditEvent, Revision continue to work as-is
3. New canonicalEvents table added alongside existing tables
4. Optional integration: New code can opt-in to canonical stream
5. Fallback: If canonical events not available, rebuild from originals

**Adoption Path**:
- Week 1: Deploy infrastructure (new modules, schema, tests)
- Week 2: Enable for new jobs/capabilities (opt-in)
- Week 3: Backfill historical events from existing logs
- Week 4: Make canonical stream the default

## Validation Framework

### Unit Tests (test_canonical_events.py)
- ConversionTests: WritingEvent & AuditEvent conversion accuracy
- StorageTests: Persist and retrieve canonical events
- QueryTests: Timeline reconstruction from events
- IntegrationTests: Full job with multiple event sources
- RoundTripTests: Event→Store→Retrieve→Verify

### Integration Tests
- Real job execution with event capture
- Multi-source event correlation
- Timeline accuracy across sources

### Smoke Tests
- Create session → Create job → Record events → Export timeline
- Verify all events present and ordered

## Output Deliverables

1. **harness_canonical_events.py** (450 lines)
   - CanonicalEvent, CanonicalEventType, EventConverter, CanonicalEventBuilder

2. **canonical_event_store.py** (350 lines)
   - Event persistence and query operations
   - Extends HarnessStore with canonical event support

3. **event_integration_layer.py** (400 lines)
   - Forward hooks for WritingEvent, AuditEvent, Revision
   - Transparent proxies to canonical stream

4. **test_canonical_events.py** (400 lines)
   - 20+ unit tests covering all conversions
   - Integration and smoke tests
   - Timeline verification

5. **Documentation**
   - PHASE_B_IMPLEMENTATION_REPORT.md
   - Event conversion mapping reference
   - Query examples

## Success Criteria

✅ All WritingEvent types map to CanonicalEventType  
✅ All AuditEvent types map to CanonicalEventType  
✅ All resource revisions map to resource_modified events  
✅ Full job timeline reconstructible from canonical events  
✅ 100% test coverage (20+ tests, all passing)  
✅ Zero breaking changes to existing code  
✅ Backward compatible with Phase A  
✅ Rollback available at checkpoint  

## Timeline

- **Design**: Complete ✓
- **Implementation**: 2-3 days
- **Testing**: 1 day
- **Documentation**: 1 day
- **Review**: 1-2 days

**Total**: ~1 week from start to merge

## Next Phases

- **Phase C**: Memory Policy Engine - decides what canonical events write to MemPalace
- **Phase D**: Memory-Aware Execution - uses canonical event stream for context injection
- **Phase E**: Recovery Console - replay jobs using canonical event timeline

---

**Status**: Ready to implement  
**Approval**: Awaiting Phase B kickoff  
**Estimated Effort**: 30-40 hours engineering
