# Phase H4: Guarded Autopilot Recovery - Implementation Report

**Phase Status**: H4 core implementation complete; integration hardening still pending

**Date**: April 2026  
**Components**: Policy framework (recovery_autopilot_policy.py), Executor (recovery_autopilot_executor.py), Tests (16 comprehensive validation tests)

## Executive Summary

Phase H4 implements safe, bounded autonomous recovery under explicit operator-defined policies. The implementation enables:

1. **Policy Language**: Confidence thresholds, action allowlists, scope limits, approval gates
2. **Guarded Execution**: Checks policies before execution, maintains comprehensive audit trail
3. **Safety Controls**: Emergency stop, operator override, easy rollback
4. **Audit Trail**: Timestamp every autonomous action with decision reason and execution log

The H4 core policy and executor primitives are implemented and validated. A later verification pass found that the broader H4 acceptance scope is only partially complete: CLI/API operator controls, canonical audit persistence, explicit default-off operator control, and observability integration are not yet wired end-to-end.

---

## Implementation Details

### 1. Policy Language (`recovery_autopilot_policy.py` - ~260 lines)

**Core Types**:

- **`AutopilotStatus`** (enum)
  - `ENABLED`: Normal operation
  - `DISABLED`: Policy not active
  - `PAUSED_INCIDENT`: Temporarily halted during incident
  - `ERROR_RECOVERY`: Recovery from policy violation

- **`PolicyApprovalGate`** (enum)
  - `IMMEDIATE`: Execute immediately without approval
  - `OPERATOR_REVIEW`: Require operator approval before execution
  - `ALWAYS_DRY_RUN`: Always preview-first, operator confirms then executes

- **`ActionPolicy`** (frozen dataclass)
  - `action_type`: Which recovery action (REPLAY_JOB, REBUILD_STATE, etc.)
  - `confidence_threshold`: Minimum confidence required (0.0-1.0)
  - `approval_gate`: Gate type for this action
  - `max_affected_resources`: Scope limit to prevent cascade failures
  - `affected_namespaces_allowlist`: Only allow in specific namespaces
  - `rate_limit_per_hour`: Throttle repeated executions
  - `quiet_period_after_failure_minutes`: Backoff after failures
  - `require_operator_rationale`: Audit requirement

- **`AutopilotPolicy`** (frozen dataclass)
  - `policy_id`, `policy_name`, `version`: Identification and versioning
  - `enabled`, `status`: Operational state
  - `action_policies`: Map of action_type → ActionPolicy
  - `global_confidence_threshold`: Overall minimum confidence
  - `global_max_concurrent_actions`: Prevent cascade by limiting parallelism
  - `enable_emergency_stop`: Operator can emergency-stop autonomously
  - `enable_operator_override`: Operator can override policy on-the-fly
  - `log_all_executions`: Comprehensive audit trail flag
  - Methods:
    - `allow_action()`: Determines if action should execute autonomously (returns allow/reason tuple)
    - `should_require_approval()`: Checks if action needs operator approval
    - `should_always_dry_run()`: Checks if action should preview-first

**Pre-configured Policies**:

1. **Conservative Policy** (recommended for production)
   - Global threshold: 90% confidence
   - Max concurrent: 2 actions
   - Actions:
     - REPLAY_JOB: 95% threshold, ALWAYS_DRY_RUN, max 10 affected resources
   - Production/Staging only
   - Rate limit: 5/hour

2. **Standard Policy** (typical environments)
   - Global threshold: 80% confidence
   - Max concurrent: 5 actions
   - Multiple action types supported
   - Action thresholds: 80-85%
   - Rate limit: 5-10/hour

3. **Permissive Policy** (dev/test only)
   - Global threshold: 70% confidence
   - Max concurrent: 10 actions
   - No rate limits
   - All namespaces allowed
   - All actions: IMMEDIATE (no approval)

---

### 2. Guarded Executor (`recovery_autopilot_executor.py` - ~280 lines)

**Core Types**:

- **`ExecutionAuthorization`** (result object)
  - `authorized`: bool (allow/deny)
  - `reason`: Explanation of decision
  - `requires_approval`: bool (needs operator review)
  - `requires_dry_run`: bool (needs preview first)
  - `policy_applied`: policy_id that made decision

- **`AutonomousExecution`** (frozen dataclass)
  - `execution_id`: Unique identifier
  - `recommendation_id`: Source recommendation
  - `action_type`: REPLAY_JOB, etc.
  - `job_id`: Target job
  - `policy_id`: Applied policy
  - `confidence`: Recommendation confidence
  - `affected_resources_count`: Scope
  - `initiated_at`, `completed_at`: Timing
  - `duration_ms`: Execution time
  - `success`: bool (success/failure)
  - `error_message`: Failure reason if any
  - `execution_log`: list of timestamped events
  - `operator_override`: bool (policy override used)
  - `rollback_initiated`: bool (rollback in progress)
  - Method: `to_dict()` - Audit trail export

**`AutopilotExecutor` Class** (~200 lines)

Constructor:
```python
AutopilotExecutor(
    policy: AutopilotPolicy,
    executor: RecoveryExecutionEngine,
    event_store: CanonicalEventStore,
    fact_store: MemoryFactStore,
    console: RecoveryConsole,
)
```

Methods:

- **`authorize_execution(recommendation)`** → `ExecutionAuthorization`
  - Check emergency stop state
  - Verify policy enabled
  - Call `policy.allow_action()` with recommendation details
  - Return authorization decision

- **`execute_autonomous(recommendation, operator_override)`** → `AutonomousExecution`
  - Step 1: Authorize (returns early if denied unless override)
  - Step 2: Create execution context with inspection session
  - Step 3: Execute action via executor
  - Step 4: Log completion with timing and result
  - Returns full audit record with execution log

- **`rollback_execution(execution_id)`** → bool
  - Find execution record by ID
  - Call executor rollback method
  - Log rollback attempt and result
  - Return success/failure

- **`set_emergency_stop(enabled)`** → None
  - Enable/disable emergency stop state
  - Immediately blocks new autonomous executions
  - Log state change with timestamp

- **`set_policy(new_policy)`** → None
  - Update policy used for authorization
  - Re-evaluate enabled state based on new policy
  - Log policy change

- **`get_execution_history(limit)`** → `list[AutonomousExecution]`
  - Return recent execution records
  - Supports pagination via limit parameter

- **`get_status()`** → dict
  - Policy ID and name
  - Enabled state and emergency stop flag
  - Execution statistics (total, successful, failed)
  - Last execution timestamp

---

### 3. Test Coverage (`test_recovery_autopilot.py` - ~340 lines)

**16 Tests Validating H4**:

#### Policy Tests (8 tests):

1. `test_conservative_policy_creation`
   - Verifies conservative policy has correct restrictive defaults
   - ✅ Policy creation with strict thresholds

2. `test_policy_allow_action_high_confidence`
   - High-confidence actions within thresholds should allow
   - ✅ Authorization granted for valid scenarios

3. `test_policy_allow_action_low_confidence`
   - Low-confidence actions should deny
   - ✅ Authorization denied below threshold

4. `test_policy_allow_action_scope_exceeded`
   - Actions exceeding scope limits should deny
   - ✅ Scope constraint enforcement

5. `test_policy_allow_action_namespace_not_in_allowlist`
   - Actions in disallowed namespaces should deny
   - ✅ Namespace allowlist validation

6. `test_policy_disabled_denies_all`
   - Disabled policies deny all actions
   - ✅ Policy disable state blocks all

7. `test_approval_gate_detection`
   - Policies correctly identify approval gate types
   - ✅ Gate detection (immediate vs. review vs. dry-run)

8. `test_permissive_policy_creation`
   - Permissive policy allows faster iteration
   - ✅ Development/test policy configuration

#### Executor Tests (8 tests):

1. `test_executor_initialization`
   - Executor initializes with policy and components
   - ✅ Component integration

2. `test_authorize_execution_high_confidence`
   - High-confidence recommendations authorized
   - ✅ Policy-based authorization

3. `test_authorize_execution_low_confidence`
   - Low-confidence recommendations denied
   - ✅ Authorization failure handling

4. `test_emergency_stop_blocks_execution`
   - Emergency stop immediately blocks all
   - ✅ Safety control validation

5. `test_policy_update`
   - Executor updates policy and re-evaluates
   - ✅ Policy change during operation

6. `test_execution_audits_trail`
   - Autonomous execution creates audit trail
   - ✅ Audit log generation with timestamps

7. `test_autonomous_execution_history`
   - Executor tracks execution history
   - ✅ Execution record storage

8. `test_status_summary`
   - Executor provides status summary
   - ✅ Status reporting API

**All 16 tests: ✅ PASSING**

---

## Acceptance Criteria: H4 Core Complete, Integration Pending

- [x] **Policy Language Enables Bounded Autonomy**
  - Approval threshold gates: confidence_threshold per action
  - Action type allowlists: action_policies dict
  - Scope limits: max_affected_resources per action
  - Namespace allowlists: affected_namespaces_allowlist

- [x] **Autonomous Execution Only with Confidence + Permission**
  - `authorize_execution()` checks confidence > threshold AND policy permits
  - Both conditions required; single failure denies

- [x] **In-Memory Execution Audit Trail**
  - Every autonomous action logged with: execution_id, timestamp, action_type, confidence
  - Approval path tracked (allow_action reason)
  - Policy applied (policy_id)
  - Results recorded (success/failure, duration)
  - Execution log array: timestamped events during execution
- [ ] **Canonical Audit Persistence**
  - Canonical event emission for authorization, execution, rollback, and emergency-stop paths is still pending

- [x] **Easy Single-Command Revert**
  - `rollback_execution(execution_id)` method
  - Finds execution record by ID
  - Calls executor rollback (returns success/failure)

- [x] **Operator Emergency Stop**
  - `set_emergency_stop(enabled)` method
  - Immediately blocks new autonomous executions
  - Can be toggled without policy change

- [ ] **Default-Off Control Plane**
  - Policy templates are currently enabled on creation
  - Explicit operator enable/disable/status control surface is still pending

- [ ] **CLI / API Operator Controls**
  - Autopilot controls are not yet exposed through `recovery_cli.py` or `python_adapter_server.py`

- [ ] **Observability Integration**
  - Metrics / telemetry accounting for autopilot decisions is still pending

- [x] **All Tests Passing**
  - 16 H4-specific tests: PASSING
  - 24 H3.1 legacy tests: PASSING (no regressions)
  - Total recovery stack: 40 tests PASSING

---

## Key Design Decisions

### 1. **Frozen Dataclasses for Policy**
- Policies immutable after creation
- Prevents accidental policy mutation during execution
- All policy changes go through `set_policy()` method with logging

### 2. **Pre-configured Policy Templates**
- Three templates (conservative, standard, permissive)
- Bootstrap common scenarios without custom policy language
- Reduces onboarding friction for operators

### 3. **Comprehensive Audit Trail**
- Every autonomous action logged with decision reason
- Execution log with timestamped events during execution
- Enables root-cause analysis and policy tuning

### 4. **Emergency Stop + Policy Override**
- Two-level safety: instant emergency stop + policy override for super-users
- Emergency stop prevents cascading failures immediately
- Policy override for exceptional situations with full audit trail

### 5. **Scope Limits via Resource Count + Namespace Allowlist**
- Prevents cascade failures by limiting affected resources
- Namespace allowlist prevents prod actions on dev namespaces
- Dual constraint model for defense-in-depth

---

## Integration with H3.1

H4 builds directly on H3.1's foundation:

- **H3.1 Stores**: Uses `get_event_store()` and `get_fact_store()` for audit trail
- **H3.1 CLI**: Recovery CLI can be updated to use `AutopilotExecutor` for autonomous mode
- **H3.1 Workflows**: DryRunPreviewWorkflow can be used in ALWAYS_DRY_RUN approval gate

H4 adds autonomous execution layer sitting above H3 operator workflows.

---

## Residual Limitations

### Not Included in H4 (Future):

- **H4.2 Guarded Autopilot CLI**: CLI integration commands (`autopilot start`, `autopilot policy set`, `autopilot stop`)
- **H4.3 Policy Persistence**: Save/load policies from durable store
- **H4.4 Policy Tuning**: Feedback loop from execution outcomes to policy recommendations
- **H5 Scale-out**: Multi-region autopilot coordination

### Known Constraints:

- Policy is immutable; policy changes require full replacement (not incremental updates)
- Emergency stop is global; no per-action-type emergency pause
- Rollback is best-effort; some action types may not support full reversal

---

## Files Added/Modified

### Added Files:

1. **`recovery_autopilot_policy.py`** (260 lines)
   - AutopilotPolicy, ActionPolicy, AutopilotStatus, PolicyApprovalGate
   - Policy language for bounded autonomy
   - Pre-configured policy templates (conservative, standard, permissive)

2. **`recovery_autopilot_executor.py`** (280 lines)
   - AutopilotExecutor, AutonomousExecution, ExecutionAuthorization
   - Guarded execution with policy enforcement
   - Audit trail, emergency stop, policy override, rollback support

3. **`test_recovery_autopilot.py`** (340 lines)
   - 16 comprehensive integration tests
   - Tests cover policy constraints, executor authorization, execution auditing

### Modified Files:

- None (H4 standalone; no modifications to existing code)

---

## Deployment Notes

### Prerequisites:

- Python 3.11+
- Recovery stack from H3.1 (event_store, fact_store, executor)
- `recovery_recommendation_engine.RecoveryActionType` enum

### Configuration:

Set environment variables (optional; defaults work):
```bash
RECOVERY_EVENT_DB=harness_state.db      # Shared event store
RECOVERY_FACT_DB=harness_facts.db       # Shared fact store
```

### Initialization:

```python
from recovery_autopilot_policy import create_conservative_policy
from recovery_autopilot_executor import AutopilotExecutor
from recovery_store_provider import get_event_store, get_fact_store
from recovery_execution_engine import RecoveryExecutionEngine
from recovery_console import RecoveryConsole

# Create executor with conservative policy (production-safe)
policy = create_conservative_policy()
executor_engine = RecoveryExecutionEngine(...)
autopilot = AutopilotExecutor(
    policy=policy,
    executor=executor_engine,
    event_store=get_event_store(),
    fact_store=get_fact_store(),
    console=RecoveryConsole(...),
)

# Execute autonomously with policy enforcement
recommendation = ...  # From recommendation engine
execution = autopilot.execute_autonomous(recommendation)

# Inspect results
print(f"Success: {execution.success}")
print(f"Audit trail: {execution.to_dict()}")
```

---

## Validation Evidence

### Test Results:

```
test_recovery_autopilot.py::TestAutopilotPolicy - 8 tests PASSED
test_recovery_autopilot.py::TestAutopilotExecutor - 8 tests PASSED
test_recovery_cli_hardened.py - 16 tests PASSED (no regressions)
test_recovery_cli.py - 8 tests PASSED (no regressions)

TOTAL: 40/40 PASSED ✅
```

### Code Quality:

- ✅ Type hints on all public methods and dataclasses
- ✅ Frozen dataclasses prevent accidental mutation
- ✅ Comprehensive docstrings explaining semantics
- ✅ Audit trail generation for all autonomous actions
- ⚠️ Focused validation still shows 5 pre-existing warnings from dependency/runtime paths

---

## Truth Notes

- The current implementation provides H4 core primitives, not full end-to-end autopilot integration.
- `AutopilotExecutor` currently keeps an in-memory execution log and does not yet persist canonical audit events.
- `AutopilotExecutor.execute_autonomous()` still contains simplified execution behavior rather than a fully delegated typed action path for each allowed recovery action.
- No autopilot controls are currently exposed through the CLI or FastAPI adapter.
- Focused regression validation re-ran at `54 passed, 5 warnings`.
- Full repository validation re-ran at `412 passed, 3 skipped, 32 warnings` with `415 tests collected`.

## Next Steps (H4.1+)

### H4.1: Guarded Autopilot Integration Hardening
- Wire autopilot into `recovery_cli.py` and `python_adapter_server.py`
- Add explicit default-off enable/disable/status/emergency-stop controls
- Persist canonical audit events for authorization, blocked execution, execution start, completion, and rollback
- Emit recovery metrics / telemetry for autopilot decisions
- Replace simplified executor path with real delegated execution for the initial allowed action surface

### H4.2: Guarded Autopilot CLI
Add CLI commands for autopilot management:
- `recovery autopilot status` - Show current autopilot state
- `recovery autopilot policy set <policy_name>` - Update policy
- `recovery autopilot emergency-stop` - Activate emergency stop
- `recovery autopilot history <limit>` - Show execution history
- `recovery autopilot rollback <execution_id>` - Rollback execution

### H4.3: Policy Persistence
- Save/load policies from SQLite
- Policy versioning and rollback support
- Policy audit trail (policy change history)

### H5: Scale-out & Enterprise
- Multi-tenant autopilot policies
- Cross-region autopilot coordination
- Advanced audit trail federation

---

## References Consulted

- Python dataclasses: https://docs.python.org/3/library/dataclasses.html
- Python Enums: https://docs.python.org/3/library/enum.html
- pytest documentation: https://docs.pytest.org/
- TypedDict and typing: https://docs.python.org/3/library/typing.html

---

**Report Date**: April 11, 2026  
**Implementation Status**: H4 core primitives implemented; broader H4 integration still pending  
**Test Coverage**: ✅ 16/16 autopilot tests passing, focused H4/H3.1/API/observability slice revalidated at 54 passed, full repository baseline revalidated at 412 passed / 3 skipped
