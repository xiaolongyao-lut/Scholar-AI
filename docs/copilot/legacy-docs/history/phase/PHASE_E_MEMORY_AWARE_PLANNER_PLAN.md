# Harness V2 Phase E: Memory-Aware Planner
## Design Document

**Phase**: E  
**Component**: Memory-Aware Planner  
**Purpose**: Make job scheduling and execution planning use memory insights  
**Status**: Design (Ready to Implement)

---

## Problem Statement

### Current State
Phase D provides temporal facts, but they're not used for planning. Systems make execution decisions without considering:
- What constraints are currently active?
- What resources are available?
- What skills succeeded/failed before?
- What was the state when previous similar jobs ran?

### The Gap
- Temporal facts exist but aren't consulted during planning
- Job scheduling doesn't consider historical context
- Skill selection is static, not adaptive
- Resource allocation doesn't use current state facts
- Memory insights unused by WritingRuntime

### Solution
Build a memory-aware planner that:
1. Queries current system state (Phase D facts)
2. Consults memory policies (Phase C)
3. Generates execution plans informed by context
4. Injects memory at session/job creation
5. Is reusable by WritingRuntime, RAG, skills, pipelines

---

## Architecture

### Input to Planner

```python
@dataclass
class PlanningContext:
    """Context for planning decisions."""
    
    session_id: str                      # Current session
    job_kind: str                        # Job type (refactor, analyze, generate, etc.)
    user_id: str                         # User identifier
    constraints: dict[str, Any]          # Resource/skill constraints
    optional_scope: str | None = None    # Execution scope (if any)
    memory_namespace: str | None  = None # Memory domain to consult
    historical_context: dict | None = None  # Previous job info
```

### Output from Planner

```python
@dataclass(frozen=True)
class ExecutionPlan:
    """Immutable execution plan informed by memory."""
    
    plan_id: str                         # Unique plan identifier
    session_id: str                      # Session this plan is for
    job_kind: str                        # Job type
    created_at: datetime                 # Plan creation time
    
    # Execution strategy
    parallelism_strategy: str            # "sequential", "parallel", "adaptive"
    skill_sequence: list[str]            # Skills to execute in order
    skill_constraints: dict[str, Any]    # Per-skill constraints
    
    # Resource strategy
    resources_required: dict[str, Any]   # Resource needs
    resource_constraints: dict[str, Any] # Reservation/conflict avoidance
    
    # Memory context
    injected_memory: dict[str, Any]      # Memory to inject at start
    memory_policy_applied: str           # Which policy rule was applied
    confidence: float                    # Confidence score (0.0-1.0)
    
    # Traceability
    fact_sources: list[str]              # IDs of facts used
    policy_sources: list[str]            # IDs of policies applied
    reasoning: str                       # Human-readable explanation
```

### Memory Planner Components

```python
class MemoryAwarePlanner:
    """Plans job execution using temporal facts and memory policies."""
    
    def __init__(
        self,
        fact_store: MemoryFactStore,
        policy_engine: MemoryPolicyEngine,
    ):
        self.fact_store = fact_store
        self.policy_engine = policy_engine
        self.planning_rules: list[PlanningRule] = []
    
    def plan_job(
        self,
        context: PlanningContext
    ) -> ExecutionPlan:
        """Generate an execution plan informed by memory."""
        ...
```

### Planning Rules (Decision Rules)

**Rule 1: Skill Availability Planning**
- Query current skill enabled/disabled facts
- If skill disabled → skip or substitute
- If skill enabled with constraints → apply constraints

**Rule 2: Resource Constraint Planning**
- Query current resource availability facts
- If resource unavailable → delay or use alternative
- If resource in use → add coordination constraint

**Rule 3: Sequential vs Parallel Strategy**
- Query current job execution facts
- If many jobs running → suggest sequential
- If few jobs running → suggest parallel
- Based on pipeline strategy facts

**Rule 4: Skill Success Pattern Planning**
- Query fact timeline for skill success/failure
- If skill failed recently → reduce confidence
- If skill succeeded repeatedly → increase confidence
- Apply risk-based strategy selection

**Rule 5: Memory Context Injection**
- Query relevant memory by namespace
- If memory hits found → inject at job start
- If memory indicates caution → flag as risky
- Include traceability to memory source

---

## Planning Workflow

### Step 1: Check Current Constraints
```python
# Query Phase D facts
current_facts = fact_store.get_current_facts("skills")
enabled_skills = [f.subject for f in current_facts if f.object == "true"]

current_facts = fact_store.get_current_facts("resources")
available_resources = {f.subject: f.object for f in current_facts}
```

### Step 2: Check Historical Context
```python
# Get timeline of previous executions
job_timeline = fact_store.get_fact_timeline(
    "execution",
    context.job_kind,  # For similar jobs
    "status"
)

# Extract patterns: success rate, avg duration, common failures
```

### Step 3: Apply Planning Rules
```python
plan = ExecutionPlan(...)

for rule in planning_rules:
    if rule.can_apply(context, facts):
        rule.apply(context, plan, fact_store)

# Rules modulate:
# - parallelism_strategy
# - skill_sequence
# - resource_constraints
# - confidence
```

### Step 4: Inject Memory
```python
# Query memory policy for this context
memory_decision = policy_engine.evaluate(
    event=context_to_event(context)
)

if memory_decision.should_inject:
    plan.injected_memory = memory_decision.memory_context
```

### Step 5: Generate Explanation
```python
# Build human-readable reasoning
plan.reasoning = f"""
Planned for {context.job_kind}:
- Skill sequence: {plan.skill_sequence}
- Strategy: {plan.parallelism_strategy}
- Used facts: {len(plan.fact_sources)}
- Applied policies: {plan.policy_sources}
- Confidence: {plan.confidence:.2%}
"""
```

---

## Planning Rules Implementation

### Rule: Skill Availability

```python
class SkillAvailabilityRule(PlanningRule):
    """Check which skills are currently available."""
    
    def can_apply(self, context, facts):
        return context.job_kind in ["generate", "analyze", "refactor"]
    
    def apply(self, context, plan, fact_store):
        # Get currently enabled skills
        enabled_skills = fact_store.get_current_facts(
            "skills",
            predicate="enabled"
        )
        enabled = {f.subject for f in enabled_skills if f.object == "true"}
        
        # Filter plan to only use enabled skills
        plan.skill_sequence = [
            s for s in plan.skill_sequence
            if s in enabled
        ]
        
        if not plan.skill_sequence:
            plan.confidence *= 0.5  # Lower confidence if no skills available
```

### Rule: Resource Constraints

```python
class ResourceConstraintRule(PlanningRule):
    """Check resource availability and conflicts."""
    
    def can_apply(self, context, facts):
        return bool(context.constraints)
    
    def apply(self, context, plan, fact_store):
        # Get resource availability
        current_resources = fact_store.get_current_facts("resources")
        
        for resource_id, status in current_resources.items():
            if status == "unavailable":
                # Add coordi nation constraint
                plan.resource_constraints[resource_id] = "wait_or_skip"
```

### Rule: Execution Strategy

```python
class ExecutionStrategyRule(PlanningRule):
    """Decide sequential vs parallel execution."""
    
    def can_apply(self, context, facts):
        return True  # Always applicable
    
    def apply(self, context, plan, fact_store):
        # Check execution load
        execution_facts = fact_store.get_current_facts("execution")
        running_jobs = [f for f in execution_facts if f.object == "running"]
        
        if len(running_jobs) > 3:
            plan.parallelism_strategy = "sequential"
            plan.confidence *= 0.8
        else:
            plan.parallelism_strategy = "parallel"
```

### Rule: Success Pattern

```python
class SuccessPatternRule(PlanningRule):
    """Adjust confidence based on historical success."""
    
    def can_apply(self, context, facts):
        return len(context.skill_sequence) > 0
    
    def apply(self, context, plan, fact_store):
        for skill in plan.skill_sequence:
            # Get skill execution history
            timeline = fact_store.get_fact_timeline(
                "skills",
                skill,
                "status"
            )
            
            # Analyze success rate
            successes = sum(1 for f in timeline if f.object == "completed")
            failures = sum(1 for f in timeline if f.object == "failed")
            
            success_rate = successes / (successes + failures) if (successes + failures) > 0 else 0.5
            plan.confidence *= success_rate
```

---

## Session Memory Injection

When creating a new session with memory context:

### Without Memory (baseline)
```python
session = runtime.create_session(user_id="user_001")
```

### With Memory (Phase E enhancement)
```python
# Query wake-up memory
wake_up_context = planner.get_wake_up_context(
    project_id="proj_001"
)

session = runtime.create_session(
    user_id="user_001",
    memory_context=wake_up_context  # Injected
)

# Session now has initialization memory:
# - Project identity
# - Recent patterns
# - Active constraints
# - Current best practices
```

## Job Creation with Memory

### Without Memory (baseline)
```python
job = session.create_job(job_kind="generate")
```

### With Memory (Phase E enhancement)
```python
# Plan execution using memory
plan = planner.plan_job(
    PlanningContext(
        session_id=session.id,
        job_kind="generate",
        user_id="user_001"
    )
)

# Create job with plan
job = session.create_job(
    job_kind="generate",
    execution_plan=plan,
    injected_memory=plan.injected_memory
)

# Job now has:
# - Skill sequence from plan
# - Resource constraints from facts
# - Memory context injected
# - Confidence-based error handling
```

## Skill Execution with Memory

### Before Executing Skill
```python
# Check if skill is optimal for current state
recommendation = planner.recommend_skill(
    current_skill="code_generator",
    context=PlanningContext(...)
)

if recommendation.confidence < 0.5:
    alternative_skill = recommendation.suggested_alternative
    # Use alternative if risky
```

### During Skill Execution
```python
# Access current facts for context
facts = fact_store.get_current_facts(
    "skills",
    subject=skill_name
)

# Adjust skill parameters based on facts
for fact in facts:
    skill.apply_constraint(fact.predicate, fact.object)
```

---

## Query Patterns

### Pattern 1: What skills are available NOW?
```python
plan = planner.plan_job(context)
available_skills = [s for s in plan.skill_sequence if s != "skipped"]
```

### Pattern 2: Has this skill failed before?
```python
timeline = fact_store.get_fact_timeline(
    "skills",
    "code_generator",
    "status"
)
recent_failures = [f for f in timeline if "failed" in f.object]
```

### Pattern 3: What was running when this job type last succeeded?
```python
# Find last successful job of same type
prev_success = fact_store.get_fact_timeline(
    "execution",
    job_kind,
    "status"
)
success_time = [f for f in prev_success if f.object == "completed"][0].valid_from

# Get facts at that time
facts_then = fact_store.get_facts_at_time("skills", success_time)
```

---

## Test Strategy

### Test Categories

1. **Planning Context Tests**
   - Valid context creation
   - Constraint representation
   - Memory namespace specification

2. **Plan Generation Tests**
   - Generate plans for different job kinds
   - Different skill sequences
   - Different parallelism strategies

3. **Planning Rule Tests**
   - Skill availability filtering
   - Resource constraint application
   - Execution strategy selection
   - Success pattern confidence adjustment

4. **Memory Injection Tests**
   - Memory context injection
   - Wake-up context retrieval
   - Memory policy integration

5. **Integration Tests**
   - Plan→Job flow
   - Facts used correctly
   - Policies applied correctly
   - Confidence scoring meaningful

6. **Edge Cases**
   - No skills available
   - No resources available
   - No history
   - All skills disabled

**Target**: 25-30 tests, 100% passing

---

## Integration Points

### With Phase D (Temporal Facts)
- Query `get_current_facts()` for active constraints
- Query `get_facts_at_time()` for historical state
- Query `get_fact_timeline()` for patterns
- Use `source_event_id` for traceability

### With Phase C (Memory Policy)
- Call `policy_engine.evaluate()` for memory decisions
- Use policy outcomes to guide planning
- Respect policy confidence scores

### With WritingRuntime
- Generate plans before job creation
- Inject memory at session/job start
- Return confidence-adjusted plans
- Enable memory-aware scheduling

### With Skills
- Provision skill recommendations
- Guide skill parameter selection
- Track skill success patterns
- Enable adaptive strategy

---

## Success Criteria

- ✅ MemoryAwarePlanner class implemented
- ✅ PlanningContext and ExecutionPlan models
- ✅ 5 core planning rules functional
- ✅ Query current facts for constraints
- ✅ Query historical timeline for patterns
- ✅ Inject memory at session/job level
- ✅ Confidence scoring meaningful
- ✅ Traceability to facts/policies preserved
- ✅ 25-30 comprehensive tests passing
- ✅ No integration blockers for Phase F

---

**Next**: Implementation (memory_aware_planner.py + test_memory_aware_planner.py)
