# -*- coding: utf-8 -*-
"""
Harness V2 Phase H4: Autopilot Recovery Policy Framework

Defines policy language for bounded autonomous recovery actions:
- Confidence thresholds for action execution
- Action type allowlists (which recovery actions can run autonomously)
- Scope limits (which jobs/resources are in scope)
- Approval and audit requirements
- Emergency override and disable mechanisms

Design Principle: Operators define policies explicitly; autonomous execution only
proceeds when confidence > threshold AND policy permits AND audit trail can be established.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional, Protocol

from recovery_recommendation_engine import RecoveryActionType
from datetime_utils import utc_now_iso_z

logger = logging.getLogger(__name__)


class AutopilotStatus(str, Enum):
    """Autopilot operational status."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    PAUSED_INCIDENT = "paused_incident"
    ERROR_RECOVERY = "error_recovery"


class PolicyApprovalGate(str, Enum):
    """Approval gates for autonomous action execution."""
    IMMEDIATE = "immediate"  # Execute immediately without approval
    OPERATOR_REVIEW = "operator_review"  # Require operator approval before execution
    ALWAYS_DRY_RUN = "always_dry_run"  # Always preview-first, operator confirms then executes


@dataclass(frozen=True)
class ActionPolicy:
    """Policy for a single recovery action type."""
    action_type: RecoveryActionType
    
    # Execution gates
    confidence_threshold: float  # 0.0-1.0; below this, no autonomous execution
    approval_gate: PolicyApprovalGate  # None, Operator Review, DryRun Preview
    
    # Scope constraints
    max_affected_resources: int  # Limit scope to prevent cascade failures
    affected_namespaces_allowlist: list[str]  # Only allow in specific namespaces
    
    # Time constraints
    rate_limit_per_hour: Optional[int] = None  # Max executions per hour
    quiet_period_after_failure_minutes: int = 15  # Don't retry after failure
    
    # Audit requirements
    require_operator_rationale: bool = False  # Require human context for audit
    
    # Audit trail fields
    created_at: datetime = field(default_factory=lambda: datetime.now())
    created_by: str = "system"


@dataclass(frozen=True)
class AutopilotPolicy:
    """
    Comprehensive autopilot policy for a recovery domain.
    
    Defines which actions can run autonomously, under what conditions,
    with what scope and confidence thresholds.
    """
    policy_id: str
    policy_name: str  # Human-readable name
    version: int  # Policy version; enables safe upgrade paths
    
    # Operational status
    enabled: bool = True
    status: AutopilotStatus = AutopilotStatus.ENABLED
    
    # Action policies
    action_policies: dict[RecoveryActionType, ActionPolicy] = field(default_factory=dict)
    
    # Global constraints
    global_confidence_threshold: float = 0.85  # Overall minimum confidence
    global_max_concurrent_actions: int = 5  # Prevent cascade by limiting parallelism
    
    # Emergency controls
    enable_emergency_stop: bool = True  # Operator can emergency-stop autopilot
    enable_operator_override: bool = True  # Operator can override policy on-the-fly
    
    # Audit and logging
    log_all_executions: bool = True  # Comprehensive audit trail
    alert_on_policy_divergence: bool = True  # Alert if actual execution diverges from policy
    
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now())
    updated_at: datetime = field(default_factory=lambda: datetime.now())
    owner: str = "system"
    tags: list[str] = field(default_factory=list)
    
    def allow_action(
        self,
        action_type: RecoveryActionType,
        confidence: float,
        affected_resources_count: int,
        affected_namespaces: list[str],
    ) -> tuple[bool, str]:
        """
        Determine if an action should execute autonomously under this policy.
        
        Args:
            action_type: Type of recovery action
            confidence: Recommendation confidence (0.0-1.0)
            affected_resources_count: How many resources would be affected
            affected_namespaces: Which namespaces are affected
            
        Returns:
            Tuple of (allow: bool, reason: str) explaining allow/deny decision
        """
        # Check if policy is enabled
        if not self.enabled:
            return False, "Autopilot policy is disabled"
        
        if self.status != AutopilotStatus.ENABLED:
            return False, f"Autopilot status is {self.status.value}, not enabled"
        
        # Check global confidence threshold
        if confidence < self.global_confidence_threshold:
            return False, (
                f"Confidence {confidence:.1%} below global threshold "
                f"{self.global_confidence_threshold:.1%}"
            )
        
        # Check if action type is in policy
        if action_type not in self.action_policies:
            return False, f"Action type {action_type.value} not in policy"
        
        action_policy = self.action_policies[action_type]
        
        # Check action-specific confidence threshold
        if confidence < action_policy.confidence_threshold:
            return False, (
                f"Confidence {confidence:.1%} below action threshold "
                f"{action_policy.confidence_threshold:.1%}"
            )
        
        # Check scope constraints
        if affected_resources_count > action_policy.max_affected_resources:
            return False, (
                f"Affected resources ({affected_resources_count}) exceed limit "
                f"({action_policy.max_affected_resources})"
            )
        
        # Check namespace allowlist
        if action_policy.affected_namespaces_allowlist:
            if not any(ns in action_policy.affected_namespaces_allowlist for ns in affected_namespaces):
                return False, (
                    f"No affected namespaces {affected_namespaces} in allowlist "
                    f"{action_policy.affected_namespaces_allowlist}"
                )
        
        return True, "Action approved under policy"
    
    def should_require_approval(self, action_type: RecoveryActionType) -> bool:
        """Check if action type requires operator approval under this policy."""
        if action_type not in self.action_policies:
            return True  # Default: require approval for unknown action types
        
        action_policy = self.action_policies[action_type]
        return action_policy.approval_gate in [
            PolicyApprovalGate.OPERATOR_REVIEW,
            PolicyApprovalGate.ALWAYS_DRY_RUN,
        ]
    
    def should_always_dry_run(self, action_type: RecoveryActionType) -> bool:
        """Check if action type should always preview-first before execution."""
        if action_type not in self.action_policies:
            return False
        
        action_policy = self.action_policies[action_type]
        return action_policy.approval_gate == PolicyApprovalGate.ALWAYS_DRY_RUN


class PolicyValidationProtocol(Protocol):
    """Protocol for policy validation."""
    
    def validate_policy(self, policy: AutopilotPolicy) -> tuple[bool, list[str]]:
        """
        Validate an autopilot policy for consistency and safety.
        
        Args:
            policy: Policy to validate
            
        Returns:
            Tuple of (valid: bool, errors: list[str])
        """
        ...


def create_conservative_policy() -> AutopilotPolicy:
    """
    Create a conservative autopilot policy for high-confidence, low-risk actions.
    
    Suitable for production environments where safety is paramount.
    """
    policy_id = f"conservative-{utc_now_iso_z()}"
    
    # Only replay_job runs autonomously, with high confidence
    action_policies = {
        RecoveryActionType.REPLAY_JOB: ActionPolicy(
            action_type=RecoveryActionType.REPLAY_JOB,
            confidence_threshold=0.95,  # Very high confidence required
            approval_gate=PolicyApprovalGate.ALWAYS_DRY_RUN,  # Always preview first
            max_affected_resources=10,
            affected_namespaces_allowlist=["production", "staging"],
            rate_limit_per_hour=5,
            require_operator_rationale=False,
        ),
    }
    
    return AutopilotPolicy(
        policy_id=policy_id,
        policy_name="Conservative - High Confidence Only",
        version=1,
        enabled=True,
        status=AutopilotStatus.ENABLED,
        action_policies=action_policies,
        global_confidence_threshold=0.90,
        global_max_concurrent_actions=2,
        enable_emergency_stop=True,
        enable_operator_override=True,
        log_all_executions=True,
        alert_on_policy_divergence=True,
        owner="system",
        tags=["production-safe", "conservative"],
    )


def create_standard_policy() -> AutopilotPolicy:
    """
    Create a standard autopilot policy for typical environments.
    
    Balances safety and responsiveness.
    """
    policy_id = f"standard-{utc_now_iso_z()}"
    
    action_policies = {
        RecoveryActionType.REPLAY_JOB: ActionPolicy(
            action_type=RecoveryActionType.REPLAY_JOB,
            confidence_threshold=0.80,
            approval_gate=PolicyApprovalGate.OPERATOR_REVIEW,
            max_affected_resources=20,
            affected_namespaces_allowlist=["production", "staging", "qa"],
            rate_limit_per_hour=10,
        ),
        RecoveryActionType.REBUILD_STATE: ActionPolicy(
            action_type=RecoveryActionType.REBUILD_STATE,
            confidence_threshold=0.85,
            approval_gate=PolicyApprovalGate.OPERATOR_REVIEW,
            max_affected_resources=5,
            affected_namespaces_allowlist=["staging", "qa"],
            rate_limit_per_hour=5,
        ),
    }
    
    return AutopilotPolicy(
        policy_id=policy_id,
        policy_name="Standard - Balanced Safety and Responsiveness",
        version=1,
        enabled=True,
        status=AutopilotStatus.ENABLED,
        action_policies=action_policies,
        global_confidence_threshold=0.80,
        global_max_concurrent_actions=5,
        enable_emergency_stop=True,
        enable_operator_override=True,
        log_all_executions=True,
        alert_on_policy_divergence=True,
        owner="system",
        tags=["standard", "balanced"],
    )


def create_permissive_policy() -> AutopilotPolicy:
    """
    Create a permissive autopilot policy for development/test environments.
    
    Allows faster iteration, assumes lower risk environment.
    """
    policy_id = f"permissive-{utc_now_iso_z()}"
    
    action_policies = {
        RecoveryActionType.REPLAY_JOB: ActionPolicy(
            action_type=RecoveryActionType.REPLAY_JOB,
            confidence_threshold=0.70,
            approval_gate=PolicyApprovalGate.IMMEDIATE,  # Execute immediately
            max_affected_resources=50,
            affected_namespaces_allowlist=[],  # All namespaces allowed
            rate_limit_per_hour=None,  # No rate limit
        ),
    }
    
    return AutopilotPolicy(
        policy_id=policy_id,
        policy_name="Permissive - Development/Test Only",
        version=1,
        enabled=True,
        status=AutopilotStatus.ENABLED,
        action_policies=action_policies,
        global_confidence_threshold=0.70,
        global_max_concurrent_actions=10,
        enable_emergency_stop=True,
        enable_operator_override=True,
        log_all_executions=True,
        alert_on_policy_divergence=False,
        owner="system",
        tags=["dev-test", "permissive"],
    )
