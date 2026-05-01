# Harness V2 Phase D: Temporal Fact Store
## Design Document

**Phase**: D  
**Component**: Temporal Fact Store  
**Purpose**: Extract and store temporal facts from canonical events  
**Status**: Design (Ready to Implement)

---

## Problem Statement

### Current State
Phase C (Memory Policy Engine) routes events but doesn't extract facts. Systems need to know:
- What is the current project state?
- Which skills are currently enabled/disabled?
- What are current approval decisions?
- What pipeline strategy is active?
- How have these facts changed over time?

### The Gap
- Canonical events show **what happened**
- But don't directly show **what is true now**
- Queries like "was skill X enabled when job Y failed?" are difficult
- Historical fact changes not tracked
- Current state queries require scanning full event stream

### Solution
Build a temporal fact store that:
1. Extracts facts from canonical events
2. Maintains temporal validity windows (valid_from → valid_to)
3. Allows querying current facts (what is true now?)
4. Allows historical queries (what was true at time T?)
5. Links facts to source events for traceability

---

## Architecture

### Temporal Fact Model

```python
@dataclass(frozen=True)
class TemporalFact:
    """Immutable temporal fact with validity window."""
    
    fact_id: str                    # Unique identifier
    namespace: str                  # Domain (project, skills, approval, etc.)
    subject: str                    # Entity subject (project_id, skill_name)
    predicate: str                  # Property (status, enabled, strategy)
    object: str | int | float       # Property value (active, true, 3.14)
    valid_from: datetime            # Validity start (inclusive)
    valid_to: datetime | None       # Validity end (exclusive), None = current
    source_event_id: str            # Canonical event that created this fact
    created_at: datetime            # Fact creation timestamp
```

### Data Model Examples

**Project Status Fact**:
```
namespace: "project"
subject: "proj_001"
predicate: "status"
object: "active"
valid_from: 2024-01-15 10:30:00
valid_to: None  ← Still valid
source_event_id: "evt_proj_001"
```

**Skill Enabled Fact**:
```
namespace: "skills"
subject: "code_generator"
predicate: "enabled"
object: "true"
valid_from: 2024-01-15 09:00:00
valid_to: 2024-01-15 14:30:00  ← Disabled at this time
source_event_id: "evt_skill_disabled"
```

**Approval Decision Fact**:
```
namespace: "approvals"
subject: "req_001"
predicate: "decision"
object: "approved"
valid_from: 2024-01-15 11:45:00
valid_to: None
source_event_id: "evt_approval_001"
```

**Pipeline Strategy Fact**:
```
namespace: "pipeline"
subject: "strategy"
predicate: "current_mode"
object: "sequential"
valid_from: 2024-01-10 08:00:00
valid_to: 2024-01-15 16:00:00
source_event_id: "evt_strategy_change"
```

### Storage Schema

```sql
CREATE TABLE temporal_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id TEXT UNIQUE NOT NULL,
    namespace TEXT NOT NULL,            -- Domain classification
    subject TEXT NOT NULL,              -- Entity being described
    predicate TEXT NOT NULL,            -- Property name
    object TEXT NOT NULL,               -- Property value (JSON-serialized)
    object_type TEXT DEFAULT 'string',  -- Type hint (string, int, float, bool)
    valid_from TEXT NOT NULL,           -- Validity start (ISO-8601)
    valid_to TEXT,                      -- Validity end (ISO-8601, NULL = current)
    source_event_id TEXT NOT NULL,      -- Linking back to canonical event
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY(source_event_id) REFERENCES canonical_events(event_id),
    
    -- Indexes for fast queries
    INDEX idx_namespace_subject (namespace, subject),
    INDEX idx_namespace_predicate (namespace, predicate),
    INDEX idx_validity (valid_from, valid_to),
    INDEX idx_current_facts (valid_to IS NULL)
)
```

---

## Core Operations

### 1. Extract Fact from Event

**Input**: CanonicalEvent  
**Process**: Match event to fact extraction rules  
**Output**: List[TemporalFact]

```python
def extract_facts_from_event(event: CanonicalEvent) -> list[TemporalFact]:
    """
    Extract temporal facts from a canonical event.
    
    Rules:
    - job_started → execution_started fact
    - job_completed → execution_completed fact
    - resource_published → resource_available fact
    - skill_enabled/disabled → skill_status fact
    - approval_granted → approval_decision fact
    """
```

### 2. Record Current Fact

**Input**: TemporalFact  
**Process**: Store new fact, close any conflicting facts  
**Output**: Stored fact ID

```python
def record_fact(fact: TemporalFact) -> str:
    """
    Store a temporal fact with automatic closure of predecessors.
    
    Process:
    1. Find facts with same (namespace, subject, predicate)
    2. Set valid_to = fact.valid_from for predecessors
    3. Insert new fact with valid_to = None (current)
    """
```

### 3. Query Current Facts

**Input**: Namespace, optional subject filter  
**Output**: List[TemporalFact]

```python
def get_current_facts(
    namespace: str,
    subject: str | None = None
) -> list[TemporalFact]:
    """
    Get all currently valid facts in a namespace.
    
    Query: WHERE valid_to IS NULL AND namespace = ?
    """
```

### 4. Query Historical Facts at Time T

**Input**: Namespace, timestamp  
**Output**: List[TemporalFact]

```python
def get_facts_at_time(
    namespace: str,
    timestamp: datetime,
    subject: str | None = None
) -> list[TemporalFact]:
    """
    Get all facts that were valid at a given timestamp.
    
    Query: WHERE valid_from <= ? AND (valid_to > ? OR valid_to IS NULL)
    """
```

### 5. Get Fact Timeline

**Input**: Namespace, subject, predicate  
**Output**: List[TemporalFact with timeline]

```python
def get_fact_timeline(
    namespace: str,
    subject: str,
    predicate: str
) -> list[TemporalFact]:
    """
    Get complete history of how a fact changed.
    
    Example:
    skill_enabled=true (Jan 1-5)
    skill_enabled=false (Jan 5-10)
    skill_enabled=true (Jan 10-present)
    """
```

---

## Fact Extraction Rules

### Rule 1: Job Execution Facts
**Source Event**: job_started, job_completed, job_failed  
**Extract Facts**:
```
namespace: execution
subject: {job_id}
predicate: status
object: running|completed|failed
```

### Rule 2: Skill State Facts
**Source Event**: skill_enabled, skill_disabled, capability_requested  
**Extract Facts**:
```
namespace: skills
subject: {skill_name}
predicate: enabled
object: true|false
```

### Rule 3: Resource State Facts
**Source Event**: resource_modified, resource_published, resource_deleted  
**Extract Facts**:
```
namespace: resources
subject: {resource_id}
predicate: availability
object: draft|published|deleted
```

### Rule 4: Approval Facts
**Source Event**: approval_granted, approval_rejected  
**Extract Facts**:
```
namespace: approvals
subject: {approval_id}
predicate: decision
object: granted|rejected|pending
```

### Rule 5: Pipeline Strategy Facts
**Source Event**: strategy_changed, mode_switch  
**Extract Facts**:
```
namespace: pipeline
subject: strategy
predicate: current_mode
object: sequential|parallel|adaptive
```

---

## Integration with Phase B.3 Events

```
CanonicalEvent Stream (from Phase B.3)
         ↓
   Event Consumer Loop
         ↓
   Match Against Rules
         ↓
   Extract TemporalFact(s)
         ↓
   Record to TemporalFactStore
         ↓
   Update Current Fact Cache
         ↓
   Available for Phase E Queries
```

### Example Flow: Job Failure

1. RuntimeEventHook fires job_failed event
2. CanonicalEvent stored in EventStore
3. Phase D consumer reads event
4. Matches rule: "job_failed → execution status change"
5. Extracts fact:
   - namespace: execution
   - subject: job_123
   - predicate: status
   - object: failed
   - valid_from: now
   - valid_to: None
   - source_event_id: evt_job_fail_123
6. Records fact:
   - Finds previous fact (job_123, status=running)
   - Sets its valid_to = now
   - Inserts new fact with valid_to=None
7. Query available: get_current_facts("execution") shows job_123=failed

---

## Current vs. Historical Queries

### Current Fact Query
```python
# "What skills are enabled RIGHT NOW?"
current_facts = store.get_current_facts("skills")
enabled_skills = [f.subject for f in current_facts if f.object == "true"]
```

### Historical Query
```python
# "What was the state of the project at 2 PM?"
facts_at_2pm = store.get_facts_at_time(
    "project",
    datetime(2024, 1, 15, 14, 0),
)
```

### Timeline Query
```python
# "How did skill X's enabled status change?"
timeline = store.get_fact_timeline(
    "skills",
    "code_generator",
    "enabled"
)
for fact in timeline:
    print(f"{fact.valid_from} → {fact.valid_to}: {fact.object}")
```

---

## Design Principles

### ✅ Immutable Facts
- TemporalFact is frozen dataclass
- Only insertion and closure (valid_to setting)
- No updates to existing facts

### ✅ Temporal Accuracy
- Valid_from/valid_to define exact validity window
- Enables "what was true at time T" queries
- Historical queries deterministic and reproducible

### ✅ Source Tracing
- Every fact links to source event
- Can recompute all facts from events if needed
- Audit trail preserved

### ✅ Namespace Isolation
- Facts organized by domain (skills, resources, approvals, pipeline)
- Independent fact lifecycles per namespace
- Enables scoped queries

### ✅ Efficient Queries
- Indexes on namespace, subject, predicate
- Current facts: WHERE valid_to IS NULL
- Historical facts: range query on valid_from/valid_to
- No full table scans needed

### ✅ Integration Ready
- Consumes CanonicalEvent from Phase B.3
- Produces TemporalFact for Phase E query
- Stateless: facts computed from events

---

## Implementation Components

### MemoryFactStore Class
- `__init__(db_path)`: Initialize schema
- `_init_schema()`: Create tables and indexes
- `extract_facts(event)`: Extract facts from an event
- `record_fact(fact)`: Store fact, close predecessors
- `get_current_facts(namespace, subject)`: Current state query
- `get_facts_at_time(namespace, timestamp, subject)`: Historical query
- `get_fact_timeline(namespace, subject, predicate)`: Timeline query
- `get_source_event(fact_id)`: Get original event

### TemporalFact Dataclass
- Immutable, frozen
- Type hints for all fields
- validation on creation

### Extraction Rules
- 5 core rules (jobs, skills, resources, approvals, pipeline)
- Extensible registration system
- Rule-based dispatch

---

## Test Strategy

### Test Categories

1. **Fact Model Tests**
   - Immutability verification
   - Field validation
   - Type conversion

2. **Extraction Tests**
   - Each rule extracts correct facts
   - Field mapping accuracy
   - Multi-fact extraction

3. **Storage Tests**
   - Fact insertion
   - Closure of predecessors
   - Schema integrity

4. **Current Query Tests**
   - Get current facts for empty namespace
   - Get current facts by subject
   - Filter by predicate

5. **Historical Query Tests**
   - Query at exact moment
   - Query between events
   - Multiple facts at same time

6. **Timeline Tests**
   - Single fact lifecycle
   - Multiple transitions
   - Gaps and long-running facts

7. **Integration Tests**
   - Event → fact extraction → query
   - Multiple events producing same fact
   - Cross-namespace isolation

**Target**: 30+ tests, 100% passing

---

## Scope & Future

### Phase D Scope
- [x] TemporalFact model
- [x] Extraction rules (5 core)
- [x] MemoryFactStore implementation
- [x] Current/historical queries
- [x] Comprehensive test suite

### Phase E Will Use
- Query: get_current_facts("skills") → Enable/disable decisions
- Query: get_facts_at_time(job_started_time) → State when job started
- Query: get_fact_timeline(job_id, "status") → Job state history
- Enable memory-aware planning based on temporal facts

### Future Extensions
- Fact inference rules (derive new facts from existing)
- Fact expiration policies (auto-close stale facts)
- Fact conflict resolution
- Compaction (archive old facts)

---

## Success Criteria

- ✅ TemporalFact immutable model implemented
- ✅ Extraction rules for 5 domains functional
- ✅ SQLite schema with temporal indexes
- ✅ Current & historical query APIs working
- ✅ 30+ comprehensive tests passing
- ✅ Source event tracing verified
- ✅ Predecessor closure logic working
- ✅ No integration blockers for Phase E

---

**Next**: Implementation (memory_fact_store.py + test_memory_fact_store.py)
