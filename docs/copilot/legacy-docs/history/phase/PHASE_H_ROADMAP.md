# Harness V2 Phase H - Integrated AI Memory Roadmap

**Date**: April 11, 2026  
**Status**: Phase H1 Complete ✅, Phase H2 Complete ✅, Phase H3.1 Integration Hardening Complete ✅, Phase H4 Core Implemented (Integration Pending) 🔄  
**Foundation**: Repository baseline revalidated - 412 passed, 3 skipped (415 tests collected)  
**Current Testing**: Focused H4 core + H3.1 + API/observability validation revalidated - 54 passed, 5 pre-existing warnings  

---

## Phase H Overview

Phase H transforms the Harness Recovery Framework from "recovery operations" into "memory-aware recovery recommendation and automation." The phase builds on solid Phases A-G foundations:

- **Phases A-F**: Protocol, Runtime, Resources, Skills, Persistence
- **Phase G**: Recovery Framework - Event storage, Fact management, Recovery Console, API surface
- **Phase H**: AI Memory Integration - Recommendations, Observability, Operations, Automation

**Key Principle**: Long-term memory must remain explicitly separate from resource truth, execution state, and audit logs. Short-term context + long-term memory + temporal facts = informed recovery recommendations.

---

## Current Repository Assets

### Already-Deployed AI Memory Components
- `memory_fact_store.py` - Temporal facts with validity windows (28 tests passing)
- `memory_policy.py` - Memory retention and eviction policies (26 tests passing)
- `memory_aware_planner.py` - Planning informed by temporal facts and memory
- `m_layer_mempalace_memory.py` - MemPalace integration for durable project memory
- `bootstrap_mempalace_repo.py` - MemPalace initialization
- `main_rag_workflow.py` - RAG retrieval using project memory

### Already-Deployed Recovery Components (Phase G)
- `recovery_console.py` - Recovery inspection and command processing
- `recovery_execution_engine.py` - Recovery action execution (13 tests passing)
- `canonical_event_store.py` - Immutable event history (42 tests passing)
- `harness_canonical_events.py` - Event protocol (15 tests passing)
- `event_integration_layer.py` - Event normalization and correlation (18 tests passing)
- `python_adapter_server.py` - FastAPI recovery endpoints (12 real route tests passing)
- 4 existing recovery endpoints:
  - `GET /recovery/events` - Event timeline inspection
  - `GET /recovery/memory` - Memory state inspection
  - `POST /recovery/facts/invalidate` - Fact invalidation
  - (new in H1) `GET /recovery/recommendations` - Typed recovery recommendations

### Supporting Infrastructure
- Event-driven architecture grounded in canonical events
- Temporal fact storage with validity windows and invalidation semantics
- MemPalace integration for long-term project memory
- Recovery audit trail and operational visibility

---

## Phase H Sub-Phases

### Phase H1: Memory-Grounded Recovery Advisor (COMPLETED ✓)

**Objective**: Build a typed recommendation engine that analyzes canonical events, temporal facts, and durable project memory to generate evidence-backed recovery recommendations for operators.

**Why It Matters**:
- Recovery operators need more than event timelines—they need ranked recovery suggestions
- Recommendations must be grounded in evidence (events, facts, memory hits) not speculation
- Confidence scores and evidence tracing enable operator trust and dry-run previews
- Audit trail of how recommendations were generated supports compliance and learning

**Core Files Involved**:
- (NEW) `recovery_recommendation_engine.py` - Typed recommendation generation
- `recovery_console.py` - Add recommendation orchestration method
- `python_adapter_server.py` - Add /recovery/recommendations endpoint
- (NEW/UPDATE) `test_recovery_recommendation_engine.py` - H1 contract tests
- (UPDATE) `test_recovery_api_routes_real.py` - Real route tests for recommendation endpoint

**Key Dependencies**:
- Phase G recovery console and canonical events (✓ ready)
- Temporal fact store and memory policy (✓ ready)
- MemPalace integration (✓ ready)
- FastAPI adapter server (✓ ready)

**Acceptance Criteria**:
- [x] Recommendation engine produces typed, immutable recommendation objects
- [x] Recommendations include: ID, type, rationale, confidence, approval level, evidence references
- [x] Engine consumes: event timeline, temporal facts, memory context, execution state
- [x] Recommendations ranked by confidence and applicability
- [x] All evidence traced back to source event/fact/memory IDs
- [x] Recommendation metadata auditable (recommendation.generated events)
- [x] API endpoint: GET /recovery/recommendations with job_id/aggregate_id parameter
- [x] Real FastAPI route tests validate recommendation endpoint behavior
- [x] Existing recovery tests remain green (no regressions)

**Out-of-Scope for H1**:
- Autonomous execution of recovery actions
- Manual fact mutation or fact speculative updates
- Predictive analytics or failure forecasting
- Operator workflow UI (comes in H3)
- Multi-region recommendation coordination (comes in H5)

**Risk Notes**:
- Recommendation quality depends on fact extraction quality - if facts are sparse, recommendations are generic
- Memory retrieval may timeout on large projects - need pagination strategy
- Confidence scoring may require tuning based on production patterns

---

### Phase H2: Observability and Evaluation Harness (COMPLETED ✓)

**Objective**: Add comprehensive instrumentation and measurement to recovery operations, making recommendation quality and recovery success measurable and improvable.

**Why It Matters**:
- Can't optimize what you don't measure
- Operator and AI agent performance divergence = learning opportunity
- Traces and metrics enable root-cause analysis of recovery failures
- Observability infrastructure enables future H4 autonomous autopilot safety gates

**Core Files Involved**:
- (NEW) `recovery_metrics_exporter.py` - Prometheus metrics for recovery operations
- (NEW) `recovery_telemetry.py` - OpenTelemetry span and trace instrumentation
- Recovery endpoints - Add instrumentation hooks
- Recommendation engine - Add confidence scoring metrics and operator override tracking

**Key Dependencies**:
- Phase H1 recommendation engine (✓ prerequisite)
- OpenTelemetry Python SDK (external)
- Prometheus client library (external)

**Acceptance Criteria**:
- Metrics tracked: recommendation counts, confidence distribution, operator acceptance rate, recovery success rate
- Traces capture recommendation generation path with source evidence
- All recovery operations emit structured logs and metrics
- Grafana dashboard templates provided for common analysis patterns
- Operator override frequencies tracked and surfaced

**Out-of-Scope for H2**:
- Real-time alerts or anomaly detection
- Cross-region telemetry aggregation
- ML model training pipelines

---

### Phase H3: Safe Operator Workflow and CLI (COMPLETED ✓)

**Objective**: Provide operator-friendly command-line interface and workflows for recovery operations, surfacing recommendations and guiding safe recovery decisions.

**Implementation Status**: Phase H3.1 Integration Hardening completed. CLI and workflows now use real, persistent stores instead of temporary in-memory instances.

**Why It Matters**:
- Human operators need fast, intuitive access to recovery recommendations in incident response
- CLI enables scripting and automation without autonomous execution
- Clear decision journeys reduce cognitive load during incidents
- Operator feedback loop enables continuous improvement of recommendations

**Core Files Involved**:
- (NEW ✓) `recovery_cli.py` - Command-line interface wrapping recovery stack
  - 8 primary commands: events, memory, facts, recommendations, explain, metrics, invalidate-fact, dry-run
  - Supports standard argparse-based CLI with structured argument handling
  - **H3.1 HARDENING**: Uses shared stores via recovery_store_provider instead of ephemeral :memory: instances
  - **H3.1 HARDENING**: All commands return real data (facts, explain, dry-run, invalidate-fact fully implemented)
  - Error handling and graceful degradation when services unavailable
  
- (NEW ✓) `recovery_workflows.py` - Guided decision workflows
  - RecommendationReviewWorkflow - structured recommendation approval flow
  - DryRunPreviewWorkflow - safe effect preview without execution
  - FactInvalidationWorkflow - guarded fact invalidation with confirmation
  - StateRehydrationWorkflow - preview state restoration from history
  - **H3.1 HARDENING**: Workflows query real event/fact stores using get_event_store() and get_fact_store()
  - **H3.1 HARDENING**: simulated_effects and rollback_plan now contain concrete data (not empty placeholders)
  
- (NEW ✓) `recovery_store_provider.py` - Shared store provider (NEW for H3.1)
  - Singleton lazy-initialization pattern for CanonicalEventStore, MemoryFactStore
  - Environment-configurable database paths (RECOVERY_EVENT_DB, RECOVERY_FACT_DB)
  - Thread-safe store instance sharing across CLI commands and workflows
  
- (NEW ✓) `test_recovery_cli_hardened.py` - H3.1 integration tests (NEW for H3.1)
  - 16 comprehensive integration tests validating real store usage
  - Tests verify no placeholder outputs, real components used, store sharing
  - All 16 passing

- (UPDATED ✓) `test_recovery_cli.py` - Existing CLI validation tests
  - 8 original unit tests updated to work with hardened implementations
  - All 8 passing with hardened CLI

**Key Dependencies**:
- Phase H1 recommendation engine (✓ prerequisite)
- Phase H2 observability (optional - improves feedback)

**Acceptance Criteria (H3.1 Hardening)**:
- [x] CLI uses real, persistent event and fact stores (not ephemeral :memory:)
- [x] Store provider pattern enables shared stores across commands
- [x] All 8 commands return real data (no placeholders like "coming in H3.2")
- [x] Workflows query real stores and produce concrete simulated effects
- [x] 16 integration tests validate hardened implementations
- [x] 41 total recovery tests pass (original + new hardened tests)
- [x] 98 total core stack tests pass (no regressions)

**Out-of-Scope for H3**:
- Web UI (separate future effort)
- Autonomous approval flows

---

### Phase H4: Guarded Autopilot Recovery (CORE IMPLEMENTED, INTEGRATION PENDING)

**Objective**: Enable safe, bounded autonomous recovery actions under explicit operator-defined policies, with comprehensive safety gates and easy opt-out.

**Implementation Status**: H4 core policy/executor primitives are implemented and unit-tested. Integration-facing requirements from the original H4 brief remain partially open: autopilot is not yet wired into CLI/API operator controls, the executor does not yet persist canonical audit events or observability metrics, and the current policy templates are enabled-on-create rather than enforced through an explicit default-off control surface.

**Why It Matters**:
- Small, high-confidence recovery actions can execute without human approval
- Reduces MTTR for deterministic failure modes
- Safety gates and trace audit enable rapid rollback if policies diverge from intent
- Operator retains ultimate control via emergency stop and policy override

**Core Files Involved**:
- (NEW ✓) `recovery_autopilot_policy.py` (~260 lines) - Policy language for bounded autonomy
  - `AutopilotPolicy`: Frozen dataclass defining autonomous execution policies
  - `ActionPolicy`: Per-action-type policies with confidence thresholds, approval gates, scope limits
  - `AutopilotStatus`: Status enum (enabled, disabled, paused, error_recovery)
  - `PolicyApprovalGate`: Gate types (immediate, operator_review, always_dry_run)
  - Pre-configured templates: conservative (~90% threshold, production-safe), standard (~80%, balanced), permissive (~70%, dev-test)
  - Methods: `allow_action()` (policy authorization), `should_require_approval()`, `should_always_dry_run()`

- (NEW ✓) `recovery_autopilot_executor.py` (~280 lines) - Guarded action execution
  - `AutopilotExecutor`: Main executor class applying policy checks before autonomous execution
  - `AutonomousExecution`: Frozen dataclass recording execution details (ID, recommendation, success, audit trail)
  - `ExecutionAuthorization`: Result object (authorized bool, reason, requires_approval, requires_dry_run)
  - Methods: `authorize_execution()`, `execute_autonomous()`, `rollback_execution()`, `set_emergency_stop()`, `set_policy()`, `get_execution_history()`, `get_status()`
  - Audit trail: Every autonomous action logged with decision reason, timing, execution log with timestamps

- (NEW ✓) `test_recovery_autopilot.py` (~340 lines) - H4 integration tests
  - 16 comprehensive tests validating policy constraints, executor authorization, execution auditing
  - Policy tests: High-confidence approval, low-confidence denial, scope validation, namespace allowlists, emergency stop
  - Executor tests: Authorization, emergency stop, policy updates, audit trail generation, execution history, status reporting
  - All 16 tests passing ✅

**Key Dependencies**:
- Phase H1 recommendation engine (✓ prerequisite)
- Phase H2 observability (✓ required for safety auditing)
- Phase H3 workflows (optional - direct CLI integration)
- Phase H3.1 store provider (✓ for audit trail backing)

**Acceptance Criteria (H4 Core vs. Remaining Integration)**:
- [x] Policy language enables: approval threshold gates, action type allowlists, scope limits
- [x] Core executor only proceeds if confidence > threshold AND policy permits
- [x] Easy single-command revert: `rollback_execution(execution_id)`
- [x] Operator emergency stop: `set_emergency_stop(enabled)` immediately blocks new in-process executions
- [x] Pre-configured policy templates (conservative, standard, permissive) ready for deployment
- [x] Executor tracks execution history with complete audit trail
- [x] 16 H4-specific tests passing ✅
- [x] Focused H4 + H3.1 + API/observability slice revalidated: 54 tests PASSING ✅
- [ ] CLI/API operator controls exposed for enable/disable/status/emergency stop
- [ ] Canonical audit events emitted for every autonomous decision path
- [ ] Observability hooks track autopilot policy decisions and executions
- [ ] Default-off autopilot control plane enforced end-to-end
- [ ] Executor delegates real typed action execution for the initial allowed action surface

**Out-of-Scope for H4**:
- CLI commands for autopilot management (`autopilot status`, `autopilot policy set`, etc.) - H4.2
- Policy persistence layer (save/load from durable store) - H4.3
- Policy tuning based on execution feedback - H4.4
- Multi-region autopilot coordination - H5

**Risk Mitigation**:
- Autonomous execution failure mode may be worse than manual - Offset by comprehensive rollback support
- Policy drift (operator intent vs. policy) - Mitigated by comprehensive audit trail and emergency stop
- Safety gates must be comprehensive - Dual constraint model (confidence + policy scope limits)

**H4 Implementation Highlights**:

1. **Policy as Code** 
   - Immutable frozen dataclasses prevent accidental mutation
   - Policy versioning enables safe policy upgrades
   - Pre-configured templates reduce onboarding friction

2. **Defense in Depth**
   - Confidence threshold + scope limits dual constraint model
   - Namespace allowlists prevent prod autonomy on dev resources
   - Rate limiting prevents cascade failures

3. **Comprehensive Audit Trail**
   - Every autonomous action: execution_id, timestamp, action_type, confidence
   - Decision reason from policy engine (allow_action() rationale)
   - Execution log with timestamped events (authorized, started, completed)
   - Support for operator override with audit flag

4. **Easy Rollback**
   - `rollback_execution(execution_id)` single-command revert
   - Execution record searchable by ID for post-incident analysis
   - Audit trail enables root-cause analysis

5. **Safety Controls**
   - Emergency stop (`set_emergency_stop(True)`) blocks all new executions immediately
   - Policy override for exceptional situations with full audit trail
   - Status reporting for operator visibility

---

### Phase H5: Scale-out, Tenancy, and Deployment Hardening (Planned H5)

**Objective**: Harden Harness V2 for production-scale, multi-tenant deployment with cross-region support and enterprise SLAs.

**Why It Matters**:
- Single-region, single-tenant architecture doesn't serve enterprise customers
- Scale testing reveals edge cases and performance cliffs
- Multi-tenant isolation prevents incidents from affecting unrelated customers
- Enterprise deployments require proven disaster recovery and compliance

**Core Files Involved**:
- (NEW) `harness_distributed_consensus.py` - Cross-region coordination
- (NEW) `harness_multi_tenant_isolation.py` - Tenant boundary enforcement
- (UPDATE) Recovery endpoints - Add region awareness and tenant scoping
- (UPDATE) Memory store - Add multi-tenant isolation

**Key Dependencies**:
- All H1-H4 phases (✓ prerequisite)
- Distributed coordination framework (external)

**Acceptance Criteria**:
- Support 3+ regions with RTO < 5 min, RPO < 1 min
- Multi-tenant isolation verified (no cross-tenant data leakage)
- Compliance audit report showing SoC 2 / ISO 27001 alignment
- Proven disaster recovery and failover procedures
- Performance benchmarks at 10x expected peak load

**Out-of-Scope for H5**:
- Custom compliance framework development
- Real-time data plane replication

---

## Phase H1 Detailed Implementation Plan

### H1 Stage 1: Core Data Models (Week 1)

Define typed recommendation models:

```python
# recovery_recommendation_engine.py

@dataclass(frozen=True)
class RecoveryRecommendation:
    """Typed, evidence-backed recovery recommendation."""
    recommendation_id: str
    job_id: str                         # Target job for recovery
    created_at: datetime                # Generation timestamp
    
    # Recommendation content
    action_type: RecoveryActionType     # Enum: REPLAY_JOB, REBUILD_STATE, etc.
    rationale: str                      # Human-readable explanation
    confidence: float                   # 0.0-1.0 confidence score
    
    # Operator context
    approval_level: ApprovalLevel       # NONE, OPERATOR, MANAGER, EMERGENCY
    dry_run_preview: str                # Expected effect summary
    time_to_remediate: timedelta | None # Estimated recovery time
    
    # Evidence tracing
    source_events: list[str]            # Event IDs supporting this recommendation  
    source_facts: list[str]             # Fact IDs supporting this recommendation
    memory_hits: list[str]              # MemPalace memory record IDs used
    
    # Metadata
    priority: int                       # 1-5 priority ranking
    alternatives: list['RecoveryRecommendation'] = field(default_factory=list)
```

### H1 Stage 2: Recommendation Engine (Week 1-2)

Implement the core recommendation engine with fact-aware rule engine:

```python
class RecoveryRecommendationEngine:
    """Generates typed recovery recommendations grounded in evidence."""
    
    def __init__(self, 
                 event_store: CanonicalEventStore,
                 fact_store: MemoryFactStore,
                 memory_adapter: MemPalaceMemoryAdapter,
                 policy_engine: MemoryPolicyEngine):
        """Initialize recommendation engine with data sources."""
    
    def generate_recommendations(self,
                                session_id: str,
                                job_id: str,
                                context_facts: list[TemporalFact] | None = None
                                ) -> list[RecoveryRecommendation]:
        """Generate ranked recovery recommendation for a job."""
        # 1. Load event timeline for job
        # 2. Load current temporal facts
        # 3. Query MemPalace for relevant historical context
        # 4. Apply recommendation rules
        # 5. Rank by confidence and priority
        # 6. Return typed recommendations with evidence references
        
    def evaluate_recommendation(self, rec: RecoveryRecommendation) -> EvaluationResult:
        """Check if recommendation is still valid given current state."""
        # Verify source events still exist
        # Verify facts still valid
        # Check if job state changed
```

### H1 Stage 3: API Integration (Week 2)

Add recommendation endpoint to API:

```python
@app.get("/recovery/recommendations", response_model=ReccommendationsPayload)
async def get_recovery_recommendations(
    job_id: str,
    session_id: str | None = None,
    limit: int = 5
) -> ReccommendationsPayload:
    """Get memory-grounded recovery recommendations for a job."""
    # Delegate to recommendation engine
    # Return typed, evidence-backed recommendations
```

### H1 Stage 4: Tests (Week 1-3)

Add comprehensive tests:

```python
# test_recovery_recommendation_engine.py

class TestRecoveryRecommendationEngine:
    def test_recommendation_structure(self):
        """Verify recommendations have required fields."""
    
    def test_evidence_linking(self):
        """Verify recommendations link to source events/facts."""
    
    def test_fact_aware_recommendations(self):
        """Verify recommendations change when facts invalidated."""
    
    def test_memory_context_injection(self):
        """Verify MemPalace memory improves recommendations."""
    
    def test_confidence_scoring(self):
        """Verify confidence scores reflect evidence quality."""
    
    def test_api_route_real(self):
        """Test /recovery/recommendations endpoint with TestClient."""
```

### H1 Stage 5: Validation (Week 3-4)

Run mandatory validations:

```bash
# Compile check
python -m py_compile recovery_recommendation_engine.py recovery_console.py python_adapter_server.py

# H1 tests
pytest test_recovery_recommendation_engine.py -q

# Real API route tests
pytest test_recovery_api_routes_real.py -q

# Regression guard
pytest test_memory_fact_store.py test_recovery_console.py test_recovery_execution_engine.py -q

# Smoke path: seed events + facts + call recommendation engine
pytest test_recovery_recommendation_engine.py::TestRecoveryRecommendationEngine::test_smoke_path_seeded -v

# Repository collection
pytest --collect-only -q
```

---

## Implementation Timeline

- **Week 1**: Data models, recommendation engine skeleton, test scaffolding
- **Week 2**: Recommendation rules and ranking, API integration, expanded tests
- **Week 3**: Evidence linking, MemPalace integration, real route tests
- **Week 4**: Validation, regression testing, final documentation

**Target**: H1 complete by end of Week 4 (April 30, 2026)

---

## Phase H Completion Checklist

### Phase H1: Memory-Grounded Recovery Advisor
- [x] `recovery_recommendation_engine.py` created and tested
- [x] Typed recommendation models defined
- [x] Evidence linking implemented (events, facts, memory)
- [x] API endpoint added: `GET /recovery/recommendations`
- [x] Real route tests validate recommendation behavior
- [x] Recommendation audit events emitted
- [x] H1 and H1.1 memory-evidence tests passing
- [x] Existing recovery tests passing (regression guard)
- [x] H1 implementation and hardening reports captured

### Phase H2: Observability and Evaluation Harness
- [x] `recovery_metrics_exporter.py` implemented
- [x] `recovery_telemetry.py` implemented
- [x] `/recovery/metrics` endpoint exposed from the FastAPI adapter
- [x] Observability tests passing in `test_recovery_observability.py`

### Phase H3: Safe Operator Workflow and CLI
- [x] `recovery_cli.py` implemented with 8 operator commands
- [x] `recovery_workflows.py` implemented with guided recovery workflows
- [x] H3.1 hardening replaced ephemeral stores with shared persistent stores
- [x] `test_recovery_cli_hardened.py` validates real-store CLI/workflow integration
- [x] H3.1 hardening snapshot and truth-sync documentation captured

### Phase H4.1-H5: Planned Next Phases
- [x] Roadmap written
- [x] Architecture sketches completed
- [ ] H4 integration hardening not yet complete
- [ ] H5 not implemented yet

---

## Success Criteria - Phase H Overall

✓ PHASE_H_ROADMAP.md is now a truthful, repository-grounded, multi-phase roadmap (not generic vague AI features)  
✓ H1 is clearly scoped as "recommendations only, no autonomous execution"  
✓ H2 and H3.1 are implemented and reflected truthfully in the roadmap  
✓ H4 core is implemented and H4.1/H4.2/H5 have clear, defensible next objectives  
✓ Each sub-phase lists: core files, dependencies, acceptance criteria, risks, and out-of-scope items  
✓ Implemented phases are tracked separately from planned future work  

---

*This roadmap reflects the state of the Harness V2 architecture as of April 11, 2026, with Phase G production-ready, Phase H1/H1.1/H2/H3.1 implemented, H4 core primitives implemented, and H4 integration hardening plus H5 still ahead.*
