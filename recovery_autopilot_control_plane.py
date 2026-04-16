"""
Phase H4.1: Autopilot Control Plane

Explicit default-OFF control layer for autonomous execution management.

Key Features:
  - Default-OFF state (requires explicit enable())
  - State machine: DISABLED → ENABLED → EMERGENCY_STOPPED → ENABLED/DISABLED
  - Canonical event emission for audit trail (authoritative log)
  - Operator-driven state transitions with full traceability
  - Policy attachment and validation

Design: Control plane manages autopilot enable/disable semantics.
Execution specifics are delegated to AutopilotExecutor.
"""

import logging
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any

from harness_canonical_events import CanonicalEvent
from datetime_utils import utc_now_iso_z
from recovery_autopilot_policy import AutopilotPolicy
from canonical_event_store import CanonicalEventStore
from memory_fact_store import MemoryFactStore
from recovery_telemetry import get_recovery_telemetry

logger = logging.getLogger(__name__)


class ControlPlaneState(Enum):
    """State enumeration for autopilot control plane."""
    DISABLED = "disabled"
    ENABLED = "enabled"
    EMERGENCY_STOPPED = "emergency_stopped"


class AutopilotControlPlane:
    """
    Explicit default-OFF autopilot control plane.
    
    Manages state transitions and operator controls for autonomous execution.
    All state changes emit canonical events for audit trail.
    
    Initial State: DISABLED (no implicit enablement)
    """
    
    def __init__(
        self,
        event_store: CanonicalEventStore,
        fact_store: MemoryFactStore,
        initial_policy: Optional[AutopilotPolicy] = None,
    ):
        """
        Initialize control plane.
        
        Args:
            event_store: Store for canonical events (audit trail)
            fact_store: Store for temporal facts
            initial_policy: Initial policy (optional, default None)
        """
        self.event_store = event_store
        self.fact_store = fact_store
        
        # State: default to DISABLED
        self._state = ControlPlaneState.DISABLED
        self._current_policy = initial_policy
        
        # Audit metadata
        self._operator_enabled_by = None
        self._operator_enabled_at = None
        
        logger.info("AutopilotControlPlane initialized in DISABLED state")
    
    def enable(
        self,
        operator_id: str,
        policy: AutopilotPolicy,
        reason: str = "",
    ) -> bool:
        """
        Enable autopilot with explicit policy.
        
        Args:
            operator_id: ID of operator performing enable
            policy: RecoveryAutopilotPolicy to activate
            reason: Reason for enabling
            
        Returns:
            True if successfully enabled, False if already enabled
        """
        telemetry = get_recovery_telemetry()
        with telemetry.trace("autopilot.control.enable", operator_id=operator_id, policy_id=policy.policy_id) as span:
            if self._state == ControlPlaneState.ENABLED:
                logger.warning(f"Autopilot already enabled; request from {operator_id}")
                span.set_attribute("status", "already_enabled")
                return False
        
        # Create and log canonical event (primary audit trail)
        from uuid import uuid4
        event = CanonicalEvent(
            event_id=f"autopilot-enable-{uuid4().hex[:12]}",
            correlation_id=f"autopilot-control-{operator_id}",
            timestamp=utc_now_iso_z(),
            aggregate_type="autopilot",
            aggregate_id="autopilot-control-plane",
            event_type="autopilot_enabled",
            payload={
                "operator_id": operator_id,
                "policy_id": policy.policy_id,
                "policy_name": policy.policy_name,
                "reason": reason,
            },
            actor_id=operator_id,
            actor_type="user",
            severity="info",
            source="recovery.autopilot.control-plane",
        )
        self.event_store.append_event(event)
        
        # Update control state
        self._state = ControlPlaneState.ENABLED
        self._current_policy = policy
        self._operator_enabled_by = operator_id
        self._operator_enabled_at = datetime.now()
        
        logger.info(f"Autopilot enabled by {operator_id}: policy={policy.policy_id}, reason={reason}")
        return True
    
    def disable(self, operator_id: str, reason: str = "") -> bool:
        """
        Disable autopilot.
        
        Args:
            operator_id: ID of operator performing disable
            reason: Reason for disabling
            
        Returns:
            True if successfully disabled, False if already disabled
        """
        telemetry = get_recovery_telemetry()
        with telemetry.trace("autopilot.control.disable", operator_id=operator_id) as span:
            if self._state == ControlPlaneState.DISABLED:
                logger.warning(f"Autopilot already disabled; request from {operator_id}")
                span.set_attribute("status", "already_disabled")
                return False
        
        # Create and log canonical event (primary audit trail)
        from uuid import uuid4
        event = CanonicalEvent(
            event_id=f"autopilot-disable-{uuid4().hex[:12]}",
            correlation_id=f"autopilot-control-{operator_id}",
            timestamp=utc_now_iso_z(),
            aggregate_type="autopilot",
            aggregate_id="autopilot-control-plane",
            event_type="autopilot_disabled",
            payload={
                "operator_id": operator_id,
                "reason": reason,
            },
            actor_id=operator_id,
            actor_type="user",
            severity="info",
            source="recovery.autopilot.control-plane",
        )
        self.event_store.append_event(event)
        
        # Clear control state
        self._state = ControlPlaneState.DISABLED
        self._current_policy = None
        
        logger.info(f"Autopilot disabled by {operator_id}: reason={reason}")
        return True
    
    def emergency_stop(self, operator_id: str, reason: str = "") -> bool:
        """
        Trigger emergency stop.
        
        Immediately halts autopilot regardless of state.
        Blocks execution until explicit resume.
        
        Args:
            operator_id: ID of operator performing stop
            reason: Reason for emergency stop (typically incident description)
            
        Returns:
            True if emergency stop triggered, False if already stopped
        """
        telemetry = get_recovery_telemetry()
        with telemetry.trace("autopilot.control.emergency_stop", operator_id=operator_id) as span:
            if self._state == ControlPlaneState.EMERGENCY_STOPPED:
                logger.warning(f"Autopilot already in emergency stop; request from {operator_id}")
                span.set_attribute("status", "already_stopped")
                return False
        
        prev_state = self._state
        
        # Create and log canonical event (primary audit trail)
        from uuid import uuid4
        event = CanonicalEvent(
            event_id=f"autopilot-estop-{uuid4().hex[:12]}",
            correlation_id=f"autopilot-control-{operator_id}",
            timestamp=utc_now_iso_z(),
            aggregate_type="autopilot",
            aggregate_id="autopilot-control-plane",
            event_type="autopilot_emergency_stop",
            payload={
                "operator_id": operator_id,
                "previous_state": prev_state.value,
                "reason": reason,
            },
            actor_id=operator_id,
            actor_type="user",
            severity="critical",
            source="recovery.autopilot.control-plane",
        )
        self.event_store.append_event(event)
        
        # Set emergency stop state
        self._state = ControlPlaneState.EMERGENCY_STOPPED
        
        logger.warning(f"EMERGENCY STOP triggered by {operator_id}: reason={reason}, prev_state={prev_state.value}")
        return True
    
    def resume_from_emergency(self, operator_id: str, reason: str = "") -> bool:
        """
        Resume from emergency stop.
        
        Transitions from EMERGENCY_STOPPED back to ENABLED.
        
        Args:
            operator_id: ID of operator performing resume
            reason: Reason for resuming
            
        Returns:
            True if successfully resumed, False if not in emergency stop
        """
        telemetry = get_recovery_telemetry()
        with telemetry.trace("autopilot.control.resume_from_emergency", operator_id=operator_id) as span:
            if self._state != ControlPlaneState.EMERGENCY_STOPPED:
                logger.warning(f"Autopilot not in emergency stop; resume request from {operator_id}")
                span.set_attribute("status", "not_stopped")
                return False
        
        # Create and log canonical event (primary audit trail)
        from uuid import uuid4
        event = CanonicalEvent(
            event_id=f"autopilot-resume-{uuid4().hex[:12]}",
            correlation_id=f"autopilot-control-{operator_id}",
            timestamp=utc_now_iso_z(),
            aggregate_type="autopilot",
            aggregate_id="autopilot-control-plane",
            event_type="autopilot_emergency_resumed",
            payload={
                "operator_id": operator_id,
                "reason": reason,
            },
            actor_id=operator_id,
            actor_type="user",
            severity="info",
            source="recovery.autopilot.control-plane",
        )
        self.event_store.append_event(event)
        
        # Resume to enabled (most likely previous state)
        self._state = ControlPlaneState.ENABLED
        
        logger.info(f"Autopilot resumed from emergency by {operator_id}: reason={reason}")
        return True
    
    def set_policy(
        self,
        operator_id: str,
        policy: AutopilotPolicy,
        reason: str = "",
    ) -> bool:
        """
        Update active policy.
        
        Can only be called when autopilot is enabled.
        
        Args:
            operator_id: ID of operator performing policy change
            policy: New policy to activate
            reason: Reason for policy change
            
        Returns:
            True if policy updated, False if not enabled
        """
        telemetry = get_recovery_telemetry()
        with telemetry.trace("autopilot.control.set_policy", operator_id=operator_id, new_policy_id=policy.policy_id) as span:
            if self._state != ControlPlaneState.ENABLED:
                logger.warning(f"Cannot change policy when not enabled; request from {operator_id}")
                span.set_attribute("status", "not_enabled")
                return False
        
        # Create and log canonical event (primary audit trail)
        from uuid import uuid4
        event = CanonicalEvent(
            event_id=f"autopilot-policy-change-{uuid4().hex[:12]}",
            correlation_id=f"autopilot-control-{operator_id}",
            timestamp=utc_now_iso_z(),
            aggregate_type="autopilot",
            aggregate_id="autopilot-control-plane",
            event_type="autopilot_policy_changed",
            payload={
                "operator_id": operator_id,
                "old_policy_id": self._current_policy.policy_id if self._current_policy else None,
                "new_policy_id": policy.policy_id,
                "reason": reason,
            },
            actor_id=operator_id,
            actor_type="user",
            severity="info",
            source="recovery.autopilot.control-plane",
        )
        self.event_store.append_event(event)
        
        # Update policy
        self._current_policy = policy
        
        logger.info(f"Autopilot policy changed by {operator_id}: old={self._current_policy.policy_id}, new={policy.policy_id}")
        return True
    
    # --- Query Methods ---
    
    def is_enabled(self) -> bool:
        """Check if autopilot is enabled."""
        return self._state == ControlPlaneState.ENABLED
    
    def is_emergency_stopped(self) -> bool:
        """Check if autopilot is in emergency stop."""
        return self._state == ControlPlaneState.EMERGENCY_STOPPED
    
    def get_current_policy(self) -> Optional[AutopilotPolicy]:
        """Get current active policy (or None if disabled)."""
        return self._current_policy
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get comprehensive control plane status.
        
        Returns:
            Dict with state, policy, operator info, and timestamps
        """
        policy_info = None
        if self._current_policy:
            policy_info = {
                "policy_id": self._current_policy.policy_id,
                "policy_name": self._current_policy.policy_name,
                "enabled": self._current_policy.enabled,
                "global_max_concurrent_actions": self._current_policy.global_max_concurrent_actions,
                "global_confidence_threshold": self._current_policy.global_confidence_threshold,
            }
        
        return {
            "state": self._state.value,
            "policy": policy_info,
            "operator": self._operator_enabled_by,
            "timestamp": self._operator_enabled_at.isoformat() if self._operator_enabled_at else None,
        }
