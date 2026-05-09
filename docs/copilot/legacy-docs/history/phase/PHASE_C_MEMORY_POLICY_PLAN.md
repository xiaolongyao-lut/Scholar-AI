# Harness V2 Phase C - Memory Policy Engine

**Date**: 2026-04-09  
**Phase**: V2 Phase C - Memory Policy Engine  
**Status**: Planning & Implementation  
**Dependencies**: Phase A ✅, Phase B ✅  

## Objective

Implement intelligent memory write policies that bridge canonical event stream to AI memory fabric:
- Canonical Events (Phase B) → Policy Decision → MemPalace or Fact Store or Skip
- Transforms raw events into memory-worthy facts  
- Separates what goes to long-term memory vs temporal facts vs session-only
- Foundation for memory-aware execution (Phase E)

## Core Problem Addressed

Currently two issues exist:
1. **Undifferentiated writing**: All terminal events go to MemPalace indiscriminately
2. **No temporal facts**: Only durable project memory; no "current facts" layer

Phase C creates explicit policies:
- Policy decides for EACH canonical event what happens
- Memory-worthy events → MemPalace (semantic recall)
- Fact changes → Temporal Fact Store (current state + history)
- Most events → Skip (reduce noise)

## Architecture

### Input Sources
```
WritingEvent (job lifecycle)
    ↓
AuditEvent (capability execution) ──→ Canonical Event Stream (Phase B)
    ↓                           ↓
RevisionEvent (resource changes) ──→ MemoryPolicy Engine
                                ↓
                          (3 decision paths)
                        
    Path 1: MemPalace       (→ Long-term project memory)
    Path 2: Fact Store      (→ Temporal facts about current state)
    Path 3: Skip            (→ Not worth remembering)
```

### Policy Rule Structure

```python
@dataclass(frozen=True)
class MemoryPolicyRule:
    """Immutable rule for deciding what to do with events."""
    
    condition: Callable[[CanonicalEvent, ResourceContext] → bool]
    # When to apply this rule
    
    action: Literal['skip', 'memory', 'fact', 'both']
    # What to do: skip | write to memory | write to fact store | both
    
    memory_category: str | None
    # If writing to memory: wing name in MemPalace
    
    fact_namespace: str | None  
    # If writing to fact store: namespace (e.g. 'resource.draft', 'approval', 'skill')
    
    dedupe_key: Callable[[CanonicalEvent] → str] | None
    # Optional: prevent duplicate memory entries
    
    ttl_seconds: int | None
    # Optional: how long this memory is valid (fact store)
    
    priority: int = 0
    # Rule priority (higher wins, for overlap resolution)
```

## Policy Categories

### Category 1: Terminal Job Events (Always Process)

**Condition**: event_type in [JOB_COMPLETED, JOB_FAILED]  
**Processing**:
- Extract outcome (success/failure)
- Extract duration
- Extract key artifacts
- Check for repeated patterns → Memory
- Update fact store current state

**Rules**:
```
Rule: Terminal Success
  IF: event_type = JOB_COMPLETED AND job in important_kinds
  THEN: action = 'memory'
        memory_category = 'project_decisions'
        fact_namespace = 'job.completion'
        
Rule: Terminal Failure (First Time)
  IF: event_type = JOB_FAILED AND first_failure_of_type
  THEN: action = 'fact'
        fact_namespace = 'error.first'
        
Rule: Terminal Failure (Nth Time)
  IF: event_type = JOB_FAILED AND nth_failure_of_type (n >= 3)
  THEN: action = 'both'  # Worth long-term memory
        memory_category = 'repeated_problems'
```

### Category 2: Resource Mutations (Context-Dependent)

**Condition**: event_type in [RESOURCE_MODIFIED, RESOURCE_PUBLISHED, RESOURCE_DELETED]  
**Processing**:
- Check if mutation is significant (not minor formatting)
- Check if mutation is stable (not thrashing)
- Update fact store "current resource state"
- If significant + stable → long-term memory

**Rules**:
```
Rule: Major Resource Decision
  IF: event_type = RESOURCE_PUBLISHED 
      AND content_diff > 500_chars
      AND same_user_within_1_hour = False
  THEN: action = 'both'
        memory_category = 'structure_decisions'
        fact_namespace = 'resource.published'
        
Rule: Resource State Update
  IF: event_type = RESOURCE_MODIFIED
  THEN: action = 'fact'
        fact_namespace = 'resource.current_state'
        ttl_seconds = None  (permanent until next mutation)
```

### Category 3: Approval Decisions (Always Persistent)

**Condition**: event_type in [APPROVAL_REQUESTED, APPROVAL_DECIDED]  
**Processing**:
- Approval decisions are permanent facts
- Reasons for approval/denial are memory-worthy

**Rules**:
```
Rule: Approval Decided
  IF: event_type = APPROVAL_DECIDED
  THEN: action = 'fact'
        fact_namespace = 'approval.decision'
        ttl_seconds = None
        
Rule: Repeated Approval Pattern
  IF: event_type = APPROVAL_DECIDED
      AND approval_type repeated >= 3 times
      AND consistent_decision
  THEN: action = 'memory'
        memory_category = 'approval_patterns'
```

### Category 4: Artifact Generation (Selective)

**Condition**: event_type = ARTIFACT_CREATED  
**Processing**:
- Store artifact → fact store immediately
- Write summary to memory only if:
  - Artifact is "final" (marked complete)
  - Artifact is "important" (marked by user)
  - Artifact type is memory-worthy

**Rules**:
```
Rule: Important Artifact
  IF: event_type = ARTIFACT_CREATED
      AND artifact.metadata['importance'] = 'high'
  THEN: action = 'both'
        memory_category = 'key_artifacts'
        fact_namespace = 'artifact.created'
        
Rule: Routine Artifact
  IF: event_type = ARTIFACT_CREATED
      AND artifact.metadata['importance'] in ['low', 'normal']
  THEN: action = 'skip'  # Too noisy otherwise
```

### Category 5: Capability Execution (Mostly Skip)

**Condition**: event_type in [EXECUTION_STARTED, EXECUTION_COMPLETED, EXECUTION_FAILED]  
**Processing**:
- Most executions are not memory-worthy
- Only skip failures that are new patterns
- And skip recoveries from known failures

**Rules**:
```
Rule: New Failure Type
  IF: event_type = EXECUTION_FAILED
      AND failure_code not_in historical_errors
  THEN: action = 'fact'
        fact_namespace = 'execution.failed'
        
Rule: Recovered from Error
  IF: event_type = EXECUTION_COMPLETED
      AND previous_event = EXECUTION_FAILED (same capability)
      AND gap < 1 hour
  THEN: action = 'memory'
        memory_category = 'error_resolutions'
        
Rule: Routine Execution
  IF: event_type in [EXECUTION_STARTED, EXECUTION_COMPLETED]
      AND is_routine_invocation
  THEN: action = 'skip'
```

### Category 6: Error Events (Always Track)

**Condition**: event_type = ERROR_OCCURRED  
**Processing**:
- All errors go to fact store immediately
- First occurrence of error type → long-term memory
- Recurring pattern (3+) → high-priority memory

**Rules**:
```
Rule: New Error
  IF: event_type = ERROR_OCCURRED
      AND error_code not_in historical_errors
  THEN: action = 'both'
        memory_category = 'error_catalog'
        fact_namespace = 'error.first_occurrence'
        
Rule: Recurring Error
  IF: event_type = ERROR_OCCURRED
      AND error_code in historical_errors
      AND occurrence_count >= 3
  THEN: action = 'memory'
        memory_category = 'recurring_problems'
        fact_namespace = 'error.recurring'
```

## Implementation: memory_policy.py (450 lines)

### Part 1: Rule System (120 lines)
```python
@dataclass(frozen=True)
class MemoryDecision:
    """Immutable result of policy evaluation."""
    action: Literal['skip', 'memory', 'fact', 'both']
    memory_category: str | None
    fact_namespace: str | None
    confidence: float  # 0.0-1.0
    reason: str  # Human-readable explanation
    
class MemoryPolicyEngine:
    """Policy decision engine for canonical events."""
    
    def __init__(self, fact_store, mempalace_adapter):
        self.fact_store = fact_store
        self.mempalace = mempalace_adapter
        self.rules = self._load_default_rules()
        self.historical_facts = {}  # Cache for deduplication
    
    def evaluate(
        self,
        event: CanonicalEvent,
        resource_context: dict[str, Any] | None = None,
    ) -> MemoryDecision:
        """
        Evaluate canonical event against policy rules.
        
        Returns:
            MemoryDecision with action and metadata
        """
        # Apply rules in priority order
        for rule in sorted(self.rules, key=lambda r: r.priority, reverse=True):
            if rule.condition(event, resource_context):
                return MemoryDecision(
                    action=rule.action,
                    memory_category=rule.memory_category,
                    fact_namespace=rule.fact_namespace,
                    confidence=0.95,  # Rules are high-confidence
                    reason=f"Matched rule: {rule.name}"
                )
        
        # Default: skip unknown
        return MemoryDecision(
            action='skip',
            memory_category=None,
            fact_namespace=None,
            confidence=0.5,
            reason="No rule matched; conservative skip"
        )
    
    def apply_decision(self, event: CanonicalEvent, decision: MemoryDecision) -> None:
        """
        Apply the policy decision to write the event somewhere.
        """
        if decision.action in ['skip']:
            pass  # Do nothing
        
        elif decision.action in ['memory', 'both']:
            self._write_to_memory(event, decision.memory_category)
        
        if decision.action in ['fact', 'both']:
            self._write_to_fact_store(event, decision.fact_namespace)
    
    def _write_to_memory(self, event: CanonicalEvent, category: str) -> None:
        """Write to MemPalace long-term memory."""
        # Convert event to memory format
        memory_entry = {
            'category': category,
            'timestamp': event.timestamp,
            'source_event': event.event_id,
            'content': self._summarize_for_memory(event),
            'tags': self._extract_tags(event),
        }
        # Write to appropriate MemPalace wing
        self.mempalace.write_to_wing(category, memory_entry)
    
    def _write_to_fact_store(self, event: CanonicalEvent, namespace: str) -> None:
        """Write to temporal fact store."""
        fact = {
            'namespace': namespace,
            'subject': self._extract_subject(event),
            'predicate': self._extract_predicate(event),
            'object': self._extract_object(event),
            'valid_from': event.timestamp,
            'valid_to': None,  # Current fact; will expire on next update
            'source_event_id': event.event_id,
            'confidence': 0.95,
        }
        self.fact_store.upsert_fact(fact)
```

### Part 2: Fact Extraction (150 lines)
```python
@staticmethod
def _summarize_for_memory(event: CanonicalEvent) -> str:
    """Convert canonical event to human-readable memory summary."""
    # Event-type specific summaries
    if event.event_type == 'job_completed':
        return f"Job {event.aggregate_id} completed successfully after {event.payload.get('duration', 'unknown')}s"
    elif event.event_type == 'job_failed':
        return f"Job {event.aggregate_id} failed: {event.error_message}"
    elif event.event_type == 'resource_modified':
        return f"Resource {event.aggregate_id} was modified by {event.actor_id}"
    # ... more types

@staticmethod
def _extract_tags(event: CanonicalEvent) -> list[str]:
    """Extract tags for memory entry indexing."""
    tags = [
        event.event_type,
        event.aggregate_type,
        f"actor:{event.actor_id}",
        f"severity:{event.severity}",
    ]
    if event.payload:
        tags.extend([f"payload:{k}" for k in event.payload.keys()])
    return tags

@staticmethod
def _extract_subject(event: CanonicalEvent) -> str:
    """Extract subject for fact (what changed)."""
    # fact namespace.subject.predicate = object
    # e.g. "draft.12345.status = published"
    return event.aggregate_id

@staticmethod
def _extract_predicate(event: CanonicalEvent) -> str:
    """Extract predicate for fact (property being tracked)."""
    if 'status' in event.payload:
        return 'status'
    if 'decision' in event.payload:
        return 'decision'
    return 'changed'

@staticmethod
def _extract_object(event: CanonicalEvent) -> str | dict[str, Any]:
    """Extract object for fact (new value)."""
    if event.new_state:
        return event.new_state
    return event.payload
```

### Part 3: Rules Definition (180 lines)
```python
def _load_default_rules(self) -> list[MemoryPolicyRule]:
    """Load default policy rules."""
    return [
        # Terminal events (highest priority)
        MemoryPolicyRule(
            name='terminal_completion',
            priority=100,
            condition=lambda e, c: (
                e.event_type == 'job_completed' and
                e.aggregate_id in self.important_job_kinds()
            ),
            action='memory',
            memory_category='project_decisions',
        ),
        
        # Resource mutations
        MemoryPolicyRule(
            name='resource_publication',
            priority=90,
            condition=lambda e, c: (
                e.event_type == 'resource_published' and
                self._is_significant_change(e)
            ),
            action='both',
            memory_category='structure_decisions',
            fact_namespace='resource.published',
        ),
        
        # Approvals
        MemoryPolicyRule(
            name='approval_decision',
            priority=95,
            condition=lambda e, c: e.event_type == 'approval_decided',
            action='fact',
            fact_namespace='approval.decision',
        ),
        
        # Errors
        MemoryPolicyRule(
            name='new_error',
            priority=85,
            condition=lambda e, c: (
                e.event_type == 'error_occurred' and
                self._is_new_error(e)
            ),
            action='both',
            memory_category='error_catalog',
            fact_namespace='error.first_occurrence',
        ),
        
        # Recovered errors
        MemoryPolicyRule(
            name='error_recovery',
            priority=80,
            condition=lambda e, c: (
                e.event_type == 'execution_completed' and
                self._is_recovery_from_error(e)
            ),
            action='memory',
            memory_category='error_resolutions',
        ),
        
        # Default skip
        MemoryPolicyRule(
            name='routine_skip',
            priority=0,
            condition=lambda e, c: True,  # Catch-all
            action='skip',
        ),
    ]
```

## Implementation: Test Suite (300 lines)

Tests cover:
- Rule evaluation logic
- Decision application
- Memory/fact store writes
- Deduplication
- Edge cases (no resources, errors, etc)
- Integration with MemPalace
- Performance (bulk events)

**Examples**:
```python
def test_terminal_job_writes_to_memory()
def test_routine_execution_skipped()
def test_error_pattern_detection()
def test_deduplication_on_repeated_facts()
def test_resource_mutation_updates_fact_store()
def test_approval_decision_creates_fact()
def test_priority_ordering_of_rules()
def test_policy_decision_reasons_human_readable()
```

## Integration Points

### 1. With HarnessStore (Phase A)
- Query event history for pattern detection
- Check historical_facts to avoid duplicates

### 2. With CanonicalEventStore (Phase B)
- Consume canonical event stream
- Query by event type, timestamp range, aggregate

### 3. With MemPalace
- Call `mempalace.write_to_wing(category, entry)`
- Call `mempalace.search_wing(category, query)`

### 4. With Fact Store (Phase D)
- Write temporal facts with valid_from/to
- Query current facts for deduplication

## Data Flow During Job Execution

```
1. Job completes with artifact
   ↓
2. WritingRuntime creates JOB_COMPLETED event
   ↓
3. Event stored in canonical_event_store
   ↓
4. MemoryPolicyEngine.evaluate(event) runs
   - Checks rules in priority order
   - Returns MemoryDecision
   ↓
5. MemoryDecision.action = 'both'
   ↓
6a. Write long-term memory to MemPalace
    - Wing: 'project_decisions'
    - Entry: {timestamp, summary, tags, source_event_id}
   ↓
6b. Write fact to Fact Store
    - Namespace: 'job.completion'
    - Subject: job_id
    - Predicate: 'completed'
    - Object: {duration, result, artifacts}
    ↓
7. MemPalace indexed for future retrieval
   Fact Store indexed for current/historical query
```

## Validation Strategy

### Unit Tests (150+ tests)
- Each rule condition
- Each action
- Deduplication logic
- Priority ordering
- Error handling

### Integration Tests
- Full event → decision → storage flow
- Multiple events in sequence
- Pattern detection (nth failure)
- Cross-store consistency

### Smoke Tests
- Real job completion flow
- Resource mutation flow
- Error detection flow

## Success Criteria

- ✅ 100% of terminal events classified
- ✅ ~20% of events reach long-term memory (selective)
- ✅ ~60% of events create facts (current state tracking)
- ✅ ~20% skipped (routine executions, noise)
- ✅ No duplicate memories from same event
- ✅ Repeated errors detected within 3 occurrences
- ✅ Rules are explainable (reason field)
- ✅ All tests passing
- ✅ Performance: <1ms per event evaluation

## Timeline

- **Design**: Complete ✓
- **Implementation**: 1-2 days
- **Testing**: 1 day
- **Integration**: 1 day
- **Documentation**: 1 day

**Total**: ~1 week

## Deliverables

1. **memory_policy.py** (450 lines)
   - MemoryPolicyEngine
   - MemoryPolicyRule
   - MemoryDecision
   - Rule definitions
   - Helper methods

2. **test_memory_policy.py** (300 lines)
   - 50+ comprehensive tests
   - Unit, integration, edge case
   - 100% coverage

3. **Documentation**
   - Policy rule reference
   - Integration guide
   - Extension points

4. **Examples**
   - Adding custom rules
   - Tuning thresholds
   - Profiling behavior

## Dependencies

- ✅ Phase A: HarnessStore (event history query)
- ✅ Phase B: CanonicalEventStore (event consumption)
- ⏳ Phase D: MemoryFactStore (fact persistence)
- ✅ Existing: MemPalace adapter (memory writing)

Can start immediately; Phase D (Fact Store) can be parallel.

## Open Questions

1. **Rule learning**: Should rules adapt based on outcomes?
   - Initial: Fixed rules
   - Future: ML-based rule weighting

2. **Memory budget**: Should we limit memory writes per session?
   - Initial: No limit (filter by policy)
   - Future: Configurable quotas

3. **Temporal facts cleanup**: How to handle fact expiration?
   - Initial: Manual invalidation (Phase F)
   - Future: TTL-based auto-cleanup

---

**Next Phase**: D - Temporal Fact Store (memory_fact_store.py)  
**Status**: Ready for implementation  
**Estimated Effort**: 40-50 hours engineering  
