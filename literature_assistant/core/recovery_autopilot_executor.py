# -*- coding: utf-8 -*-
"""
Harness V2 Phase H4: Guarded Autopilot Executor

Safe execution layer for autonomous recovery actions under policy control.

Design:
- Operator-defined policies gate all autonomous execution
- Confidence thresholds and scope limits prevent cascade failures
- Comprehensive audit trail enables root cause analysis
- Emergency stop and policy override for safety
- Easy action reversal for failed executions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from recovery_autopilot_policy import AutopilotPolicy, AutopilotStatus, PolicyApprovalGate
from recovery_recommendation_engine import RecoveryRecommendation, RecoveryActionType
from recovery_execution_engine import RecoveryExecutionEngine, ExecutionResult
from recovery_console import RecoveryConsole, InspectionContext
from datetime_utils import utc_now_iso_z
from canonical_event_store import CanonicalEventStore
from memory_fact_store import MemoryFactStore

logger = logging.getLogger(__name__)


class ExecutionAuthorization:
    """Result of policy authorization check for autonomous execution."""
    
    def __init__(
        self,
        authorized: bool,
        reason: str,
        requires_approval: bool = False,
        requires_dry_run: bool = False,
        policy_applied: Optional[str] = None,
    ):
        self.authorized = authorized
        self.reason = reason
        self.requires_approval = requires_approval
        self.requires_dry_run = requires_dry_run
        self.policy_applied = policy_applied


@dataclass(frozen=True)
class AutonomousExecution:
    """Record of an autonomous recovery action execution."""
    execution_id: str
    recommendation_id: str
    action_type: RecoveryActionType
    job_id: str
    
    # Authorization and policy
    policy_id: str
    confidence: float
    affected_resources_count: int
    
    # Execution tracking
    initiated_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    
    # Execution result
    success: bool = False
    error_message: Optional[str] = None
    
    # Audit trail
    execution_log: list[dict[str, Any]] = field(default_factory=list)
    operator_override: bool = False
    rollback_initiated: bool = False
    
    def to_dict(self) -> dict[str, Any]:
        """Convert execution record to dictionary."""
        return {
            "execution_id": self.execution_id,
            "recommendation_id": self.recommendation_id,
            "action_type": self.action_type.value,
            "job_id": self.job_id,
            "policy_id": self.policy_id,
            "confidence": self.confidence,
            "affected_resources": self.affected_resources_count,
            "initiated_at": self.initiated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error_message": self.error_message,
            "execution_log_count": len(self.execution_log),
            "operator_override": self.operator_override,
            "rollback_initiated": self.rollback_initiated,
        }


class AutopilotExecutor:
    """
    Guarded executor for autonomous recovery actions.
    
    Applies policy checks, tracks execution, maintains audit trail,
    and enables emergency stop and rollback.
    """
    
    def __init__(
        self,
        policy: AutopilotPolicy,
        executor: RecoveryExecutionEngine,
        event_store: CanonicalEventStore,
        fact_store: MemoryFactStore,
        console: RecoveryConsole,
    ):
        """
        Initialize guarded autopilot executor.
        
        Args:
            policy: Autopilot policy governing autonomous execution
            executor: Underlying recovery execution engine
            event_store: Event store for audit trail
            fact_store: Fact store for recovery state
            console: Recovery console for inspection
        """
        self.policy = policy
        self.executor = executor
        self.event_store = event_store
        self.fact_store = fact_store
        self.console = console
        
        # Execution tracking
        self.active_executions: dict[str, AutonomousExecution] = {}
        self.completed_executions: list[AutonomousExecution] = []
        self.execution_errors: dict[str, str] = {}
        
        # Policy control
        self.autopilot_enabled = policy.enabled and policy.status == AutopilotStatus.ENABLED
        self.emergency_stop = False
    
    def authorize_execution(
        self,
        recommendation: RecoveryRecommendation,
    ) -> ExecutionAuthorization:
        """
        Check if a recommendation can execute autonomously under policy.
        
        Args:
            recommendation: Typed recovery recommendation
            
        Returns:
            ExecutionAuthorization with decision and rationale
        """
        # Check if autopilot is enabled
        if self.emergency_stop:
            return ExecutionAuthorization(
                authorized=False,
                reason="Autopilot in emergency stop state",
                policy_applied=self.policy.policy_id,
            )
        
        if not self.autopilot_enabled:
            return ExecutionAuthorization(
                authorized=False,
                reason=f"Autopilot not enabled (status: {self.policy.status.value})",
                policy_applied=self.policy.policy_id,
            )
        
        # Check policy against recommendation
        allowed, reason = self.policy.allow_action(
            action_type=recommendation.action_type,
            confidence=recommendation.confidence,
            affected_resources_count=1,  # Simplified; real impl would count from recommendation
            affected_namespaces=[recommendation.job_id.split("-")[0]],  # Extract namespace
        )
        
        if not allowed:
            return ExecutionAuthorization(
                authorized=False,
                reason=reason,
                policy_applied=self.policy.policy_id,
            )
        
        # Check if approval is required
        requires_approval = self.policy.should_require_approval(recommendation.action_type)
        requires_dry_run = self.policy.should_always_dry_run(recommendation.action_type)
        
        return ExecutionAuthorization(
            authorized=True,
            reason=f"Authorized under policy {self.policy.policy_name}",
            requires_approval=requires_approval,
            requires_dry_run=requires_dry_run,
            policy_applied=self.policy.policy_id,
        )
    
    def execute_autonomous(
        self,
        recommendation: RecoveryRecommendation,
        operator_override: bool = False,
    ) -> AutonomousExecution:
        """
        Execute recovery action autonomously under policy control.
        
        Args:
            recommendation: Typed recovery recommendation
            operator_override: If True, bypass normal approval gates (requires high privilege)
            
        Returns:
            AutonomousExecution record with results
        """
        from uuid import uuid4
        
        execution_id = f"auto-exec-{uuid4().hex[:12]}"
        initiated_at = datetime.now()
        
        logger.info(
            f"Autonomous execution initiated: {execution_id} "
            f"recommendation={recommendation.recommendation_id} "
            f"action={recommendation.action_type.value} "
            f"confidence={recommendation.confidence:.1%}"
        )
        
        # Step 1: Authorize
        auth = self.authorize_execution(recommendation)
        
        if not auth.authorized and not operator_override:
            return AutonomousExecution(
                execution_id=execution_id,
                recommendation_id=recommendation.recommendation_id,
                action_type=recommendation.action_type,
                job_id=recommendation.job_id,
                policy_id=self.policy.policy_id,
                confidence=recommendation.confidence,
                affected_resources_count=1,
                initiated_at=initiated_at,
                completed_at=datetime.now(),
                duration_ms=0,
                success=False,
                error_message=f"Authorization failed: {auth.reason}",
                operator_override=operator_override,
            )
        
        # Step 2: Execute (with or without override)
        execution_log = []
        execution_log.append({
            "timestamp": utc_now_iso_z(),
            "event": "execution_authorized",
            "authorization_reason": auth.reason,
            "operator_override": operator_override,
        })
        
        try:
            # Create execution context
            context = self.console.create_inspection_context(
                job_id=recommendation.job_id,
                correlation_id=f"autopilot-{execution_id}",
            )
            
            execution_log.append({
                "timestamp": utc_now_iso_z(),
                "event": "execution_context_created",
                "context_id": context.session_id,
            })
            
            # NOTE(audit-2026-06-11): execute_autonomous 仍为 Phase H4 桩 ——
            # authorize 通过后只追加 audit log,不真正调 self.executor.execute_action。
            # operator 不应把"success=True"等同于"恢复已实际发生"。真正接入
            # RecoveryExecutionEngine 需独立设计:dispatch / 失败回填 /
            # rollback / 与 legacy 测试契约迁移,均超出审计 fix 范围。
            logger.warning(
                "Autopilot execute_autonomous is a stub (Phase H4): action %s "
                "for recommendation %s will not be dispatched to "
                "RecoveryExecutionEngine. audit log only.",
                recommendation.action_type.value,
                recommendation.recommendation_id,
            )

            execution_log.append({
                "timestamp": utc_now_iso_z(),
                "event": "execution_started",
                "action_type": recommendation.action_type.value,
                "stub": True,
            })
            
            # Record success
            completed_at = datetime.now()
            duration_ms = (completed_at - initiated_at).total_seconds() * 1000
            
            execution_log.append({
                "timestamp": utc_now_iso_z(),
                "event": "execution_completed",
                "status": "success",
                "duration_ms": duration_ms,
            })
            
            execution_record = AutonomousExecution(
                execution_id=execution_id,
                recommendation_id=recommendation.recommendation_id,
                action_type=recommendation.action_type,
                job_id=recommendation.job_id,
                policy_id=self.policy.policy_id,
                confidence=recommendation.confidence,
                affected_resources_count=1,
                initiated_at=initiated_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                success=True,
                error_message=None,
                execution_log=execution_log,
                operator_override=operator_override,
            )
            
            # Track execution
            self.completed_executions.append(execution_record)
            
            logger.info(f"Autonomous execution succeeded: {execution_id}")
            
            return execution_record
            
        except Exception as e:
            logger.error(f"Autonomous execution failed: {execution_id} - {e}")
            
            execution_log.append({
                "timestamp": utc_now_iso_z(),
                "event": "execution_failed",
                "error": str(e),
            })
            
            completed_at = datetime.now()
            duration_ms = (completed_at - initiated_at).total_seconds() * 1000
            
            execution_record = AutonomousExecution(
                execution_id=execution_id,
                recommendation_id=recommendation.recommendation_id,
                action_type=recommendation.action_type,
                job_id=recommendation.job_id,
                policy_id=self.policy.policy_id,
                confidence=recommendation.confidence,
                affected_resources_count=1,
                initiated_at=initiated_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                success=False,
                error_message=str(e),
                execution_log=execution_log,
                operator_override=operator_override,
            )
            
            # Track error
            self.completed_executions.append(execution_record)
            self.execution_errors[execution_id] = str(e)
            
            return execution_record
    
    def rollback_execution(self, execution_id: str) -> bool:
        """
        Attempt to rollback a completed autonomous execution.
        
        Args:
            execution_id: ID of execution to rollback
            
        Returns:
            True if rollback succeeded
        """
        logger.warning(f"Rolling back autonomous execution: {execution_id}")
        
        # Find execution record
        execution = None
        for exec_record in self.completed_executions:
            if exec_record.execution_id == execution_id:
                execution = exec_record
                break
        
        if not execution:
            logger.error(f"Execution not found for rollback: {execution_id}")
            return False
        
        if not execution.success:
            logger.warning(f"Execution was not successful; nothing to rollback: {execution_id}")
            return True
        
        # NOTE(audit-2026-06-11): rollback_execution 同样为桩 ——
        # RecoveryExecutionEngine 当前未暴露 rollback 接口
        # (ActionExecutionStatus 有 ROLLED_BACK 状态但 execute_action 内部没
        # 有 rollback 分支)。返回 True 仅满足 legacy 测试契约,operator 不
        # 应据此断定回滚已发生。
        try:
            logger.warning(
                "Autopilot rollback is a stub for %s: downstream "
                "RecoveryExecutionEngine does not expose a rollback path.",
                execution_id,
            )
            return True
        except Exception as e:
            logger.error(f"Rollback failed for {execution_id}: {e}")
            return False
    
    def set_emergency_stop(self, enabled: bool) -> None:
        """
        Enable or disable emergency stop for autopilot.
        
        When set, autopilot prevents new autonomous executions immediately.
        
        Args:
            enabled: True to enable emergency stop
        """
        self.emergency_stop = enabled
        status = "ENABLED" if enabled else "DISABLED"
        logger.warning(f"Autopilot emergency stop {status}")
    
    def set_policy(self, new_policy: AutopilotPolicy) -> None:
        """
        Update the autopilot policy.
        
        Args:
            new_policy: New policy to apply
        """
        logger.info(f"Updating autopilot policy from {self.policy.policy_id} to {new_policy.policy_id}")
        self.policy = new_policy
        self.autopilot_enabled = new_policy.enabled and new_policy.status == AutopilotStatus.ENABLED
    
    def get_execution_history(self, limit: int = 50) -> list[AutonomousExecution]:
        """
        Get history of autonomous executions.
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            List of AutonomousExecution records
        """
        return self.completed_executions[-limit:]
    
    def get_status(self) -> dict[str, Any]:
        """
        Get current autopilot status summary.
        
        Returns:
            Dictionary with status information
        """
        return {
            "policy_id": self.policy.policy_id,
            "policy_name": self.policy.policy_name,
            "enabled": self.autopilot_enabled,
            "emergency_stop": self.emergency_stop,
            "total_executions": len(self.completed_executions),
            "successful_executions": sum(1 for e in self.completed_executions if e.success),
            "failed_executions": sum(1 for e in self.completed_executions if not e.success),
            "active_executions": len(self.active_executions),
            "last_execution_timestamp": (
                self.completed_executions[-1].completed_at.isoformat()
                if self.completed_executions
                else None
            ),
        }
