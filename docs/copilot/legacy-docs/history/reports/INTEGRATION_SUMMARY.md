# Summary: Recovery Stack Architecture for Autopilot Integration

---

## Key Findings

### 1. Current CLI Interface ✅
- **Tool**: `recovery_cli.py` (argparse-based)
- **Pattern**: Hierarchical subcommand structure with targeted operators
- **Status**: Fully functional with 8 core commands + metrics
- **Integration Ready**: Can add autopilot subcommands
- **Implementation**: Each command → handler function (`cmd_*`) → store operations

### 2. Canonical Event Handlers ✅ 
- **Storage**: `canonical_event_store.py` (in-memory + SQLite backend)
- **Event Type**: `CanonicalEvent` (frozen dataclass from `harness_canonical_events.py`)
- **Event Categories**: 21 event types across 6 categories (job, capability, approval, artifact, resource, error)
- **Autopilot Events**: 4 specific types (enabled, disabled, emergency_stop, emergency_resume)
- **Audit Trail**: Every state change → CanonicalEvent with operator ID, timestamp, reason
- **Integration**: Control plane directly creates and appends events to canonical stream

### 3. Metrics Implementation ✅
- **Library**: `recovery_metrics_exporter.py` (zero-dependency, thread-safe)
- **Collector**: `RecoveryMetricsCollector` with 30+ metrics
- **Export Format**: Prometheus text format
- **Categories**: HTTP requests, recommendations, operator feedback, recovery outcomes, tracing
- **Integration**: FastAPI middleware auto-records all `/recovery/` requests
- **API**: `get_recovery_metrics_collector()` singleton pattern

### 4. Recovery Autopilot CLI Status ✅
- **Implementation**: `recovery_autopilot_cli.py` (Phase H4.1 complete)
- **Test Suite**: 28/28 tests passing
- **Commands**: status, enable, disable, emergency-stop, emergency-resume, policy show/set
- **Design**: Global control plane singleton with policy registry
- **Integration**: All commands emit canonical events for audit trail

### 5. Control Plane Structure ✅
- **Location**: `recovery_autopilot_control_plane.py`
- **Design**: Default-OFF state machine (DISABLED → ENABLED → EMERGENCY_STOPPED)
- **Key Methods**: enable(), disable(), emergency_stop(), emergency_resume(), get_status()
- **Audit**: Every state change creates CanonicalEvent with full traceability
- **Emergency Control**: Immediate effect, no delays or polling required
- **Policy**: Attached to control plane, must be provided at enable() time

---

## Integration Architecture: Five Layers

```
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 5: User Interface                                             │
│ recovery_cli.py [autopilot] + FastAPI endpoints (/recovery/autopilot/*) │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 4: Automation Control                                         │
│ AutopilotControlPlane (state machine) + AutopilotPolicy (rules)     │
│ AutopilotExecutor (authorization + execution)                       │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 3: Event & Memory Integration                                 │
│ CanonicalEventStore (audit trail) + MemoryFactStore (temporal)      │
│ RecoveryMetricsCollector (observability)                            │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 2: Recovery Analytics                                         │
│ RecoveryRecommendationEngine (suggests actions)                      │
│ RecoveryExecutionEngine (performs actions)                          │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 1: Data Ingestion                                             │
│ WritingRuntime (job events) + Skills (audit events)                 │
│ WritingResources (resource events)                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Critical Patterns Discovered

### Pattern 1: Immutable Events + Audit Trail
```
Every significant action:
  Command → Create CanonicalEvent (immutable) 
         → Append to EventStore 
         → Never modify or delete
Result: Complete, tamper-proof audit trail
```

### Pattern 2: Dual-Constraint Authorization
```
Autonomous Execution Decision:
  Recommendation Confidence AND Policy Permission BOTH required
  Confidence alone insufficient
  Policy alone insufficient
  Failure on either → DENY (conservative default)
```

### Pattern 3: Policy-Driven Execution
```
Three pre-configured policies available:
  Conservative (90% conf, limited actions) → Production safe
  Standard (80% conf, moderate actions) → Normal operations
  Permissive (70% conf, broad actions) → Dev/testing
Policies are immutable after creation
Changes require new enable() call
```

### Pattern 4: Singleton Control Plane
```
Module-Level Singleton (recovery_autopilot_cli.py):
  _control_plane_instance = None
  
Lazy initialization:
  get_autopilot_control_plane() → creates on first call
  
Test isolation:
  reset_autopilot_control_plane() → clears singleton
```

### Pattern 5: Environment-Driven Configuration
```
RECOVERY_OPERATOR_ID environment variable → Who made the change
Policy names from POLICY_REGISTRY → Conservative/standard/permissive
Event source always → "recovery.autopilot.control-plane"
Aggregate ID always → "autopilot-control-plane"
```

---

## Autopilot-to-Recovery Stack Integration Points

### 1. Event Storage Layer
**File**: `recovery_autopilot_control_plane.py:enable/disable/emergency_stop()`
```
control_plane.enable()
  └─ Create CanonicalEvent(event_type='autopilot_enabled')
     └─ event_store.append_event(event)
        └─ Stores in canonical stream
        └─ Creates authoritative record
```

### 2. Recommendation Flow Layer
**File**: `recovery_autopilot_executor.py:authorize_execution()`
```
recommendation (from RecoveryRecommendationEngine)
  └─ executor.authorize_execution(recommendation)
     ├─ Check: confidence > policy.threshold
     ├─ Check: policy.allow_action(action_type)
     ├─ Check: not in emergency_stop
     ├─ Check: not exceeding concurrent limits
     └─ Return: ExecutionAuthorization(authorized, reason)
```

### 3. Execution Layer
**File**: `recovery_autopilot_executor.py:execute_autonomous()`
```
if authorized:
  execution = executor.execute_autonomous(recommendation)
  └─ RecoveryExecutionEngine.execute(recommendation)
  └─ Record result in AutonomousExecution (immutable)
  └─ Add to execution history
  └─ Emit event to canonical stream
```

### 4. CLI Integration Layer
**File**: `recovery_cli.py` ← `recovery_autopilot_cli.py`
```
recovery_cli.py autopilot <cmd>
  └─ recovery_autopilot_cli.py::cmd_autopilot_*()
     └─ get_autopilot_control_plane()
        └─ AutopilotControlPlane singleton
           └─ Maintains state + event emission
```

### 5. Observability Layer
**File**: `python_adapter_server.py::recovery_observability_middleware()`
```
FastAPI /recovery/* request
  └─ Middleware intercepts
  └─ Starts telemetry span
  └─ Records metrics
  └─ Responses include trace IDs
  └─ get_recovery_metrics_collector().render_prometheus_text()
```

---

## Data Flow Examples

### Example 1: Enable Autopilot via CLI
```
$ RECOVERY_OPERATOR_ID=admin recovery_cli.py autopilot enable --policy standard

Command Handler (recovery_autopilot_cli.py)
  1. Parse args: policy='standard'
  2. Look up in POLICY_REGISTRY → create_standard_policy()
  3. Get control plane: get_autopilot_control_plane()
  4. Call: control_plane.enable(operator_id='admin', policy=policy, reason='...')

Control Plane Handler (recovery_autopilot_control_plane.py)
  1. Check state: DISABLED → OK to enable
  2. Create event:
     CanonicalEvent(
       event_type='autopilot_enabled',
       actor_id='admin',
       timestamp=utc_now_iso_z(),
       payload={operator_id: 'admin', policy_id: '...', reason: '...'}
     )
  3. Append: event_store.append_event(event)
  4. Update internal state:
     _state = ENABLED
     _current_policy = policy
     _operator_enabled_by = 'admin'
  5. Return: True

Output to Operator
  ✓ Autopilot enabled with policy 'standard'
  Policy ID: std-80-v1
  Operator: admin
  Reason: ...
```

### Example 2: Recovery Recommendation → Autonomous Execution
```
Recommendation Engine produces:
  RecoveryRecommendation(
    action_type=RETRY,
    confidence=0.85,
    job_id='job-123',
    rationale='Connection timeout - retry should succeed'
  )

Executor Authorization:
  1. Check: 0.85 > global_confidence_threshold (0.80)? YES
  2. Check: policy.allow_action(RETRY)?
     - Check: 0.85 > action_policy.confidence_threshold (0.75)? YES
     - Check: max_affected_resources not exceeded? YES
     - Check: approval_gate allows immediate? YES
     → allow_action() returns True
  3. Check: is_enabled()? YES
  4. Check: not in emergency_stop()? YES

Result: ExecutionAuthorization(authorized=True)

Executor Execution:
  1. Call: executor.execute_autonomous(recommendation)
  2. Create execution record: AutonomousExecution(...)
  3. Call: recovery_engine.execute(recommendation)
  4. Record result in execution_log
  5. Create event: CanonicalEvent(type='autonomous_execution_completed')
  6. Append to canonical stream
  7. Return: AutonomousExecution with success flag

Outcome Recorded:
  - Execution history updated
  - Metrics incremented (recovery_success_total)
  - Event stored for audit trail
```

---

## Testing Strategy

### Test Files & Coverage
```
test_recovery_autopilot.py (16 tests)
├─ Policy creation and constraint checking (8 tests)
└─ Executor authorization and execution (8 tests)

test_recovery_autopilot_cli.py (28 tests)
├─ CLI command parsing and isolation (28 tests)
├─ Control plane singleton lifecycle
├─ Event emission verification
└─ Policy registry lookups

Total: 44/44 PASSING ✅
Also: 24 H3.1 legacy tests still passing (0 regressions)
```

### Key Test Patterns
1. **Singleton Reset**: `reset_autopilot_control_plane()` in setup_method()
2. **Mock Store**: `MockEventStore`, `MockFactStore` for isolation
3. **Event Verification**: Assert events appended with correct types/payloads
4. **State Verification**: Assert control plane state transitions
5. **Policy Verification**: Assert authorization decisions match expectations

---

## Current Deployment Status

### ✅ Phase H4 Complete
- Control plane state machine: Production ready
- Policy framework: Production ready
- Executor with authorization: Production ready
- CLI commands: Production ready
- Event emission: Production ready
- Metrics collection: Production ready
- Test coverage: 44/44 passing

### ⚠️ Phase H4.2 Planned
- FastAPI REST endpoints for autopilot (/recovery/autopilot/*)
- WebSocket support for real-time state updates
- Policy persistence to durable store
- Policy versioning and rollback

### ⚠️ Phase H4.3 Planned
- Policy tuning based on outcomes
- Automatic threshold adjustment
- Policy feedback loop

---

## Critical Success Factors

1. **Immutability-First Design**
   - Policies can't accidentally mutate during execution
   - Events can't be modified or deleted
   - Records provide audit trail integrity

2. **Default-OFF Safety**  
   - Autopilot starts DISABLED
   - Requires explicit operator enable()
   - Policy must be provided

3. **Dual-Constraint Model**
   - Confidence threshold (statistical)
   - Policy permission (operational)
   - Both must allow (conservative default)

4. **Emergency Control**
   - Immediate effect (no delays)
   - Takes priority over policy
   - Returns autopilot to operator control

5. **Full Traceability**
   - Every change → canonical event
   - Includes operator ID, timestamp, reason
   - Queryable for audit/compliance

---

## Related Files Reference

| Category | Files |
|----------|-------|
| **Control Plane** | recovery_autopilot_control_plane.py |
| **Policy** | recovery_autopilot_policy.py |
| **Executor** | recovery_autopilot_executor.py |
| **CLI** | recovery_cli.py, recovery_autopilot_cli.py |
| **Events** | harness_canonical_events.py, canonical_event_store.py |
| **Memory** | memory_fact_store.py |
| **Metrics** | recovery_metrics_exporter.py |
| **API** | python_adapter_server.py |
| **Tests** | test_recovery_autopilot.py, test_recovery_autopilot_cli.py |
| **Documentation** | ARCHITECTURE_ANALYSIS.md, AUTOPILOT_INTEGRATION_REFERENCE.md |

---

## Next Steps for Integration

### Immediate (Already Done)
- [x] Control plane state machine
- [x] Policy framework
- [x] CLI commands
- [x] Event emission
- [x] Metrics collection

### Short Term (Phase H4.2)
- [ ] FastAPI endpoints for autopilot
- [ ] Policy persistence
- [ ] REST client support
- [ ] Dashboard integration

### Medium Term (Phase H4.3+)
- [ ] Policy tuning loop
- [ ] Multi-tenant support
- [ ] Scale-out coordination
- [ ] Advanced analytics

---

**Document Type**: Architecture Analysis Summary  
**Generated**: 2026-04-11  
**Phase Status**: H4.1 Complete (28/28 CLI tests passing)  
**Integration Readiness**: Production Ready for CLI + Event Layer
