# Autopilot Integration Points - Quick Reference

**Status**: Phase H4.1 Implementation Complete (28/28 CLI tests passing)

---

## 1. User Interaction Path

```
User Command
    ↓
recovery_cli.py [autopilot] <subcommand> [args]
    ↓
    ├─ autopilot status          → cmd_autopilot_status()
    ├─ autopilot enable          → cmd_autopilot_enable()
    ├─ autopilot disable         → cmd_autopilot_disable()
    ├─ autopilot emergency-stop  → cmd_autopilot_emergency_stop()
    ├─ autopilot emergency-resume→ cmd_autopilot_emergency_resume()
    ├─ autopilot policy show     → cmd_autopilot_policy_show()
    └─ autopilot policy set      → cmd_autopilot_policy_set()
```

---

## 2. Core Classes & Their Roles

```
┌──────────────────────────────────────────────────────────────┐
│ AutopilotControlPlane                                        │
│ Role: State machine for autopilot enable/disable/emergency   │
│ Location: recovery_autopilot_control_plane.py                │
│ Key Methods:                                                  │
│   - enable(operator_id, policy, reason) → emits event       │
│   - disable(operator_id, reason) → emits event              │
│   - emergency_stop(operator_id, reason) → emits event       │
│   - emergency_resume(operator_id, reason) → emits event     │
│   - is_enabled() → bool                                      │
│   - get_status() → dict with state, policy, operator        │
├──────────────────────────────────────────────────────────────┤
│ AutopilotPolicy                                              │
│ Role: Immutable policy definition for autonomous execution   │
│ Location: recovery_autopilot_policy.py                       │
│ Key Attributes:                                              │
│   - confidence_threshold (0.0-1.0)                          │
│   - action_policies (dict: action_type → ActionPolicy)      │
│   - global_max_concurrent_actions                           │
│   - enable_emergency_stop, enable_operator_override         │
├──────────────────────────────────────────────────────────────┤
│ AutopilotExecutor                                            │
│ Role: Authorization & execution of recovery actions          │
│ Location: recovery_autopilot_executor.py                     │
│ Key Methods:                                                  │
│   - authorize_execution(recommendation) → authorization      │
│   - execute_autonomous(recommendation) → execution record    │
│   - rollback_execution(execution_id) → bool                 │
│   - set_emergency_stop(bool)                                │
│   - get_status() → dict with current state                  │
├──────────────────────────────────────────────────────────────┤
│ CanonicalEventStore                                          │
│ Role: Authoritative audit trail                             │
│ Location: canonical_event_store.py                          │
│ Events Emitted:                                              │
│   - autopilot_enabled                                        │
│   - autopilot_disabled                                       │
│   - autopilot_emergency_stop                                │
│   - autopilot_emergency_resume                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. State Transitions & Events

```
DISABLED
  ├─ enable()  → ENABLED + autopilot_enabled event
  └─ (no other transitions)

ENABLED
  ├─ disable() → DISABLED + autopilot_disabled event
  ├─ emergency_stop() → EMERGENCY_STOPPED + autopilot_emergency_stop event
  └─ policy update() → still ENABLED + event logged

EMERGENCY_STOPPED
  ├─ emergency_resume() → ENABLED + autopilot_emergency_resume event
  ├─ disable() → DISABLED + autopilot_disabled event
  └─ (no autonomous actions allowed)
```

---

## 4. Request Authorization Model

```
RecoveryRecommendation
    ├─ action_type: RecoveryActionType
    └─ confidence: float (0.0-1.0)
         ↓
AutopilotExecutor.authorize_execution()
    ├─ Check 1: confidence > policy.global_confidence_threshold?
    ├─ Check 2: policy.allow_action(action_type)?
    │           ├─ Check confidence_threshold for this action
    │           ├─ Check max_affected_resources
    │           ├─ Check affected_namespaces_allowlist
    │           └─ Check approval_gate type
    ├─ Check 3: Not in emergency_stop?
    └─ Check 4: Not exceeding concurrent actions limit?
         ↓
ExecutionAuthorization(authorized, reason, ...)
    │
    ├─ If authorized  → execute_autonomous()
    │                   → AutonomousExecution record
    │                   → Add to audit log
    │
    └─ If denied      → Return authorization reason
                        → Operator can override if policy allows
```

---

## 5. CLI Command Mapping

```
recovery_cli.py autopilot status
└─ recovery_autopilot_cli.py::cmd_autopilot_status()
   ├─ get_autopilot_control_plane()
   └─ control_plane.get_status()
      └─ Display: state, policy, operator, timestamp

recovery_cli.py autopilot enable --policy standard --reason "..."
└─ recovery_autopilot_cli.py::cmd_autopilot_enable()
   ├─ Get policy from POLICY_REGISTRY['standard']
   ├─ Get autopilot control plane
   ├─ control_plane.enable(operator_id, policy, reason)
   │  └─ Creates + appends autopilot_enabled event
   └─ Display: confirmation with policy details

recovery_cli.py autopilot disable --reason "..."
└─ recovery_autopilot_cli.py::cmd_autopilot_disable()
   ├─ Get autopilot control plane
   ├─ control_plane.disable(operator_id, reason)
   │  └─ Creates + appends autopilot_disabled event
   └─ Display: confirmation

recovery_cli.py autopilot emergency-stop --reason "..."
└─ recovery_autopilot_cli.py::cmd_autopilot_emergency_stop()
   ├─ Get autopilot control plane
   ├─ control_plane.emergency_stop(operator_id, reason)
   │  └─ Creates + appends autopilot_emergency_stop event
   └─ Display: confirmation (includes incident reason)

recovery_cli.py autopilot policy show
└─ recovery_autopilot_cli.py::cmd_autopilot_policy_show()
   └─ Display: All available policies
      ├─ conservative (90% confidence, limited actions)
      ├─ standard (80% confidence, moderate actions)
      └─ permissive (70% confidence, all actions)

recovery_cli.py autopilot policy set --policy conservative
└─ recovery_autopilot_cli.py::cmd_autopilot_policy_set()
   ├─ Get new policy from POLICY_REGISTRY
   ├─ Get autopilot executor
   ├─ executor.set_policy(new_policy)
   └─ Display: confirmation with new policy ID
```

---

## 6. Policy Presets

```
create_conservative_policy()
├─ Confidence threshold: 90%
├─ Max concurrent: 3
├─ Allowed actions: RETRY, WAIT_AND_RETRY
├─ Approval gate: OPERATOR_REVIEW for all
└─ Use case: Production - ultra-safe

create_standard_policy()
├─ Confidence threshold: 80%
├─ Max concurrent: 5
├─ Allowed actions: RETRY, ROLLBACK, SCALE_UP
├─ Approval gate: IMMEDIATE for low-scope, OPERATOR_REVIEW for others
└─ Use case: Standard operations

create_permissive_policy()
├─ Confidence threshold: 70%
├─ Max concurrent: 10
├─ Allowed actions: All recovery types
├─ Approval gate: IMMEDIATE for most, DRY_RUN for destructive
└─ Use case: Development/testing
```

---

## 7. Data Flow: Complete Example

```
Scenario: Recommendation engine suggests retry (85% confidence)

Step 1: Recommendation Generated
   RecoveryRecommendationEngine (H1)
   └─ recommendation = RecoveryRecommendation(
        action_type=RETRY,
        confidence=0.85
      )

Step 2: Authorization Check
   AutopilotExecutor.authorize_execution(recommendation)
   ├─ Check: 0.85 > policy.global_confidence_threshold (0.80) ✓
   ├─ Check: policy.allow_action(RETRY) 
   │          └─ Check: 0.85 > action_policy.confidence_threshold (0.75) ✓
   │          └─ Check: approval_gate != OPERATOR_REVIEW ✓
   ├─ Check: not in emergency_stop ✓
   └─ Result: ExecutionAuthorization(authorized=True)

Step 3: Execution
   AutopilotExecutor.execute_autonomous(recommendation)
   ├─ Execute the recovery action via RecoveryExecutionEngine
   ├─ Record outcomes in AutonomousExecution
   └─ Return: AutonomousExecution(success=True, ...)

Step 4: Audit Trail
   Create CanonicalEvent for execution
   └─ event_store.append_event(execution_event)
      └─ Canonical stream records successful autonomous action

Step 5: Metrics
   get_recovery_metrics_collector()
   ├─ .record_recommendation_generation(...)
   ├─ .record_recovery_outcome(success=True)
   └─ Next /recovery/metrics call exports updated counts
```

---

## 8. Test Coverage by Component

```
test_recovery_autopilot.py (16 tests)
├─ TestAutopilotPolicy (8 tests)
│  ├─ test_conservative_policy_creation
│  ├─ test_policy_allow_action_high_confidence
│  ├─ test_policy_allow_action_low_confidence  
│  ├─ test_policy_allow_action_scope_exceeded
│  ├─ test_policy_allow_action_namespace_not_in_allowlist
│  ├─ test_policy_disabled_denies_all
│  ├─ test_approval_gate_detection
│  └─ test_permissive_policy_creation
└─ TestAutopilotExecutor (8 tests)
   ├─ test_executor_initialization
   ├─ test_authorize_execution_high_confidence
   ├─ test_authorize_execution_low_confidence
   ├─ test_emergency_stop_blocks_execution
   ├─ test_policy_update
   ├─ test_execution_audits_trail
   ├─ test_autonomous_execution_history
   └─ test_status_summary

test_recovery_autopilot_cli.py (28 tests)
├─ TestAutopilotCLIStatus (2 tests)
├─ TestAutopilotCLIEnable (7 tests)
├─ TestAutopilotCLIDisable (3 tests)
├─ TestAutopilotCLIEmergencyStop (4 tests)
├─ TestAutopilotCLIEmergencyResume (2 tests)
├─ TestAutopilotCLIPolicyShow (3 tests)
├─ TestAutopilotCLIPolicySet (4 tests)
└─ TestAutopilotCLIWorkflows (3 tests)

TOTAL: 44/44 PASSING ✅
```

---

## 9. Singleton Pattern: Control Plane

```
In recovery_autopilot_cli.py:

Module-level singleton:
┌────────────────────────────────────────┐
│ _control_plane_instance = None         │
└────────────────────────────────────────┘

Get or create (lazy initialization):
def get_autopilot_control_plane() -> AutopilotControlPlane:
    global _control_plane_instance
    if _control_plane_instance is None:
        _control_plane_instance = AutopilotControlPlane(
            event_store=get_event_store(),
            fact_store=get_fact_store(),
        )
    return _control_plane_instance

Test cleanup:
def reset_autopilot_control_plane() -> None:
    global _control_plane_instance
    _control_plane_instance = None
```

---

## 10. Environment Integration

```
Operator ID Source:
  os.environ.get("RECOVERY_OPERATOR_ID", "unknown-operator")

Policy Registry:
  {
    "conservative": create_conservative_policy,
    "standard": create_standard_policy,
    "permissive": create_permissive_policy,
    "moderate": create_standard_policy  # backwards compatibility
  }

Event Source Identifier:
  "recovery.autopilot.control-plane"

Aggregate ID for Control Plane:
  "autopilot-control-plane"

Metrics Collection:
  get_recovery_metrics_collector() from recovery_metrics_exporter
```

---

## 11. Future Integration Points (H4.2+)

```
FastAPI Endpoints (TODO: Phase H4.2)
GET /recovery/autopilot/status
  └─ Returns: control plane state + current policy
  
POST /recovery/autopilot/enable
  └─ Body: {policy: string, reason: string}
  
POST /recovery/autopilot/disable
  └─ Body: {reason: string}
  
POST /recovery/autopilot/emergency-stop
  └─ Body: {reason: string}
  
POST /recovery/autopilot/emergency-resume
  └─ Body: {reason: string}
  
GET /recovery/autopilot/policies
  └─ Returns: Available policy templates
  
PUT /recovery/autopilot/policy
  └─ Body: {policy: string}
  └─ Sets active policy
```

---

## 12. Dependency Chain

```
recovery_autopilot_cli.py
├─ recovery_autopilot_control_plane.py
│  ├─ harness_canonical_events.py (CanonicalEvent definition)
│  ├─ datetime_utils.py (utc_now_iso_z)
│  ├─ canonical_event_store.py (persistence)
│  └─ memory_fact_store.py (for temporal facts)
├─ recovery_autopilot_policy.py (policy definitions)
├─ recovery_store_provider.py (get_event_store, get_fact_store)
└─ datetime_utils.py (timestamp generation)

recovery_cli.py
├─ recovery_autopilot_cli.py (autopilot subcommands)
├─ recovery_recommendation_engine.py (recommendations)
├─ recovery_execution_engine.py (execution)
├─ memory_fact_store.py (temporal facts)
├─ canonical_event_store.py (event storage)
└─ recovery_metrics_exporter.py (metrics)
```

---

## 13. Key Invariants

```
1. Immutability
   - Policies never mutate after creation
   - Events never mutate after append
   - Execution records never mutate

2. Audit Trail
   - Every state change → event
   - Event persisted before returning
   - Operator ID always recorded

3. Default Safety
   - Start in DISABLED state
   - Require explicit enable()
   - Policy must be provided

4. Emergency Control
   - emergency_stop() takes effect immediately
   - No polling, no delay
   - Blocks all new execution

5. Isolation
   - CLI singleton resets between tests
   - Each control plane instance independent
   - No global state sharing between invocations
```

---

## 14. Error Scenarios

```
Scenario 1: Recommendation below confidence threshold
   - Recommendation: ROLLBACK with 70% confidence
   - Policy threshold: 80%
   - Result: DENIED
   - Reason: "Confidence 0.70 below policy threshold 0.80"

Scenario 2: Policy conflict
   - Recommendation: DELETE_RESOURCE (not in allowlist)
   - Policy: Only allows RETRY, ROLLBACK
   - Result: DENIED
   - Reason: "Action DELETE_RESOURCE not in policy allowlist"

Scenario 3: Scope exceeded
   - Recommendation: 50 affected resources
   - Policy: max 10 resources
   - Result: DENIED
   - Reason: "Scope 50 exceeds policy limit 10"

Scenario 4: Emergency stop active
   - Recommendation: Valid (high confidence, in-policy)
   - Control plane: In emergency_stop state
   - Result: DENIED
   - Reason: "Autopilot in emergency stop state"

Scenario 5: Approval required
   - Recommendation: Valid, in-policy
   - Action policy: approval_gate = OPERATOR_REVIEW
   - Result: AUTHORIZATION APPROVED but EXECUTION REQUIRES APPROVAL
   - Next step: Operator must call execute_with_operator_approval()
```

---

**Quick Links**:
- Full analysis: [ARCHITECTURE_ANALYSIS.md](ARCHITECTURE_ANALYSIS.md)
- Control plane: [recovery_autopilot_control_plane.py](recovery_autopilot_control_plane.py)
- CLI commands: [recovery_autopilot_cli.py](recovery_autopilot_cli.py)
- Test suite: `test_recovery_autopilot_cli.py` (28/28 passing)
- Phase status: See [PHASE_H4_1_INTEGRATION_HARDENING_PROMPT_EN.md](PHASE_H4_1_INTEGRATION_HARDENING_PROMPT_EN.md)
