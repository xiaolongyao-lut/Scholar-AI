# -*- coding: utf-8 -*-
"""
Harness V2 Phase H4: Autopilot Policy and Executor Tests

Validates:
1. Policy language enables safe bounded autonomy
2. Confidence and scope constraints are enforced
3. Approval gates work correctly
4. Rollback and emergency stop mechanisms function
5. Audit trail is comprehensive
"""

from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from recovery_autopilot_policy import (
    AutopilotPolicy,
    AutopilotStatus,
    PolicyApprovalGate,
    ActionPolicy,
    create_conservative_policy,
    create_standard_policy,
    create_permissive_policy,
)
from recovery_autopilot_executor import (
    AutopilotExecutor,
    AutonomousExecution,
    ExecutionAuthorization,
)
from recovery_recommendation_engine import RecoveryActionType, RecoveryRecommendation
from recovery_store_provider import get_event_store, get_fact_store, reset_stores


class TestAutopilotPolicy:
    """Test autopilot policy language and constraints."""
    
    def test_conservative_policy_creation(self):
        """Conservative policy should have restrictive defaults."""
        policy = create_conservative_policy()
        
        assert policy.enabled
        assert policy.status == AutopilotStatus.ENABLED
        assert policy.global_confidence_threshold == 0.90
        assert policy.global_max_concurrent_actions == 2
        assert RecoveryActionType.REPLAY_JOB in policy.action_policies
    
    def test_policy_allow_action_high_confidence(self):
        """Policy should allow high-confidence actions within thresholds."""
        policy = create_conservative_policy()
        
        allowed, reason = policy.allow_action(
            action_type=RecoveryActionType.REPLAY_JOB,
            confidence=0.95,
            affected_resources_count=5,
            affected_namespaces=["production"],
        )
        
        assert allowed, f"Action should be allowed: {reason}"
    
    def test_policy_allow_action_low_confidence(self):
        """Policy should deny low-confidence actions."""
        policy = create_conservative_policy()
        
        allowed, reason = policy.allow_action(
            action_type=RecoveryActionType.REPLAY_JOB,
            confidence=0.70,  # Below conservative threshold of 0.90
            affected_resources_count=5,
            affected_namespaces=["production"],
        )
        
        assert not allowed, "Low-confidence action should be denied"
        assert "below" in reason.lower()
    
    def test_policy_allow_action_scope_exceeded(self):
        """Policy should deny actions exceeding scope limits."""
        policy = create_conservative_policy()
        
        allowed, reason = policy.allow_action(
            action_type=RecoveryActionType.REPLAY_JOB,
            confidence=0.95,
            affected_resources_count=50,  # Exceeds conservative limit of 10
            affected_namespaces=["production"],
        )
        
        assert not allowed, "Action exceeding scope should be denied"
        assert "exceed" in reason.lower()
    
    def test_policy_allow_action_namespace_not_in_allowlist(self):
        """Policy should deny actions in disallowed namespaces."""
        policy = create_conservative_policy()  # Only allows production, staging
        
        allowed, reason = policy.allow_action(
            action_type=RecoveryActionType.REPLAY_JOB,
            confidence=0.95,
            affected_resources_count=5,
            affected_namespaces=["development"],  # Not in allowlist
        )
        
        assert not allowed, "Action in disallowed namespace should be denied"
        assert "namespace" in reason.lower()
    
    def test_policy_disabled_denies_all(self):
        """Policy should deny all when disabled."""
        # Create a disabled policy (policies are frozen, so create new one)
        disabled_policy = AutopilotPolicy(
            policy_id="disabled-test",
            policy_name="Disabled Test Policy",
            version=1,
            enabled=False,
            status=AutopilotStatus.ENABLED,
            action_policies={
                RecoveryActionType.REPLAY_JOB: ActionPolicy(
                    action_type=RecoveryActionType.REPLAY_JOB,
                    confidence_threshold=0.50,
                    approval_gate=PolicyApprovalGate.IMMEDIATE,
                    max_affected_resources=100,
                    affected_namespaces_allowlist=[],
                )
            },
        )
        
        allowed, reason = disabled_policy.allow_action(
            action_type=RecoveryActionType.REPLAY_JOB,
            confidence=0.95,
            affected_resources_count=1,
            affected_namespaces=["production"],
        )
        
        assert not allowed, "Disabled policy should deny all actions"
        assert "disabled" in reason.lower()
    
    def test_approval_gate_detection(self):
        """Policy should correctly identify approval gate requirements."""
        conservative = create_conservative_policy()
        standard = create_standard_policy()
        
        # Conservative = always dry-run
        assert conservative.should_always_dry_run(RecoveryActionType.REPLAY_JOB)
        
        # Standard = operator review
        assert standard.should_require_approval(RecoveryActionType.REPLAY_JOB)
        assert not standard.should_always_dry_run(RecoveryActionType.REPLAY_JOB)
    
    def test_permissive_policy_creation(self):
        """Permissive policy should allow faster iteration."""
        policy = create_permissive_policy()
        
        assert policy.enabled
        assert policy.global_confidence_threshold == 0.70  # Lower threshold
        # Should allow immediate execution for retry job
        action_policy = policy.action_policies[RecoveryActionType.REPLAY_JOB]
        assert action_policy.approval_gate == PolicyApprovalGate.IMMEDIATE


class TestAutopilotExecutor:
    """Test guarded autopilot executor."""
    
    def setup_method(self):
        """Reset stores before each test."""
        reset_stores()
    
    def test_executor_initialization(self):
        """Executor should initialize with policy and components."""
        policy = create_conservative_policy()
        executor_mock = MagicMock()
        
        executor = AutopilotExecutor(
            policy=policy,
            executor=executor_mock,
            event_store=get_event_store(),
            fact_store=get_fact_store(),
            console=MagicMock(),
        )
        
        assert executor.policy.policy_id == policy.policy_id
        assert not executor.emergency_stop
        assert executor.autopilot_enabled
    
    def test_authorize_execution_high_confidence(self):
        """Executor should authorize high-confidence recommendations."""
        policy = create_conservative_policy()
        executor = AutopilotExecutor(
            policy=policy,
            executor=MagicMock(),
            event_store=MagicMock(),
            fact_store=MagicMock(),
            console=MagicMock(),
        )
        
        recommendation = MagicMock()
        recommendation.action_type = RecoveryActionType.REPLAY_JOB
        recommendation.confidence = 0.95
        recommendation.job_id = "production-job-001"
        
        auth = executor.authorize_execution(recommendation)
        
        assert auth.authorized
        assert "Authorized" in auth.reason
    
    def test_authorize_execution_low_confidence(self):
        """Executor should deny low-confidence recommendations."""
        policy = create_conservative_policy()
        executor = AutopilotExecutor(
            policy=policy,
            executor=MagicMock(),
            event_store=MagicMock(),
            fact_store=MagicMock(),
            console=MagicMock(),
        )
        
        recommendation = MagicMock()
        recommendation.action_type = RecoveryActionType.REPLAY_JOB
        recommendation.confidence = 0.70  # Below threshold
        recommendation.job_id = "production-job-001"
        
        auth = executor.authorize_execution(recommendation)
        
        assert not auth.authorized
        assert "below" in auth.reason.lower()
    
    def test_emergency_stop_blocks_execution(self):
        """Emergency stop should immediately block new executions."""
        policy = create_conservative_policy()
        executor = AutopilotExecutor(
            policy=policy,
            executor=MagicMock(),
            event_store=MagicMock(),
            fact_store=MagicMock(),
            console=MagicMock(),
        )
        
        # Set emergency stop
        executor.set_emergency_stop(True)
        
        recommendation = MagicMock()
        recommendation.action_type = RecoveryActionType.REPLAY_JOB
        recommendation.confidence = 0.95
        recommendation.job_id = "production-job-001"
        
        auth = executor.authorize_execution(recommendation)
        
        assert not auth.authorized
        assert "emergency stop" in auth.reason.lower()
    
    def test_policy_update(self):
        """Executor should update policy and re-evaluate."""
        policy = create_permissive_policy()
        executor = AutopilotExecutor(
            policy=policy,
            executor=MagicMock(),
            event_store=MagicMock(),
            fact_store=MagicMock(),
            console=MagicMock(),
        )
        
        # Verify current policy
        assert executor.policy.policy_name == "Permissive - Development/Test Only"
        
        # Update to conservative
        new_policy = create_conservative_policy()
        executor.set_policy(new_policy)
        
        assert executor.policy.policy_name == "Conservative - High Confidence Only"
    
    def test_execution_audits_trail(self):
        """Autonomous execution should create comprehensive audit trail."""
        policy = create_permissive_policy()
        executor = AutopilotExecutor(
            policy=policy,
            executor=MagicMock(),
            event_store=MagicMock(),
            fact_store=MagicMock(),
            console=MagicMock(create_inspection_context=MagicMock(return_value=MagicMock(session_id="sess-123"))),
        )
        
        recommendation = MagicMock()
        recommendation.recommendation_id = "rec-001"
        recommendation.action_type = RecoveryActionType.REPLAY_JOB
        recommendation.confidence = 0.80
        recommendation.job_id = "test-job-001"
        
        execution = executor.execute_autonomous(recommendation)
        
        assert execution.success
        assert len(execution.execution_log) > 0
        # Should have timestamps for key events
        log_events = [entry.get("event") for entry in execution.execution_log]
        assert "execution_authorized" in log_events
        assert "execution_completed" in log_events or "execution_started" in log_events
    
    def test_autonomous_execution_history(self):
        """Executor should track execution history."""
        policy = create_permissive_policy()
        executor = AutopilotExecutor(
            policy=policy,
            executor=MagicMock(),
            event_store=MagicMock(),
            fact_store=MagicMock(),
            console=MagicMock(create_inspection_context=MagicMock(return_value=MagicMock(session_id="sess-123"))),
        )
        
        # Execute multiple actions
        for i in range(3):
            recommendation = MagicMock()
            recommendation.recommendation_id = f"rec-{i:03d}"
            recommendation.action_type = RecoveryActionType.REPLAY_JOB
            recommendation.confidence = 0.80
            recommendation.job_id = f"test-job-{i:03d}"
            
            executor.execute_autonomous(recommendation)
        
        history = executor.get_execution_history()
        
        assert len(history) == 3
        assert all(isinstance(e, AutonomousExecution) for e in history)
    
    def test_status_summary(self):
        """Executor should provide status summary."""
        policy = create_permissive_policy()
        executor = AutopilotExecutor(
            policy=policy,
            executor=MagicMock(),
            event_store=MagicMock(),
            fact_store=MagicMock(),
            console=MagicMock(create_inspection_context=MagicMock(return_value=MagicMock(session_id="sess-123"))),
        )
        
        status = executor.get_status()
        
        assert status["policy_id"] == policy.policy_id
        assert status["enabled"]
        assert not status["emergency_stop"]
        assert status["total_executions"] == 0
        assert status["successful_executions"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
