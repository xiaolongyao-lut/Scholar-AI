"""
Autopilot-related Pydantic models for REST API.

Includes models for autopilot control, policy management, and event tracking.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AutopilotStatusResponse(BaseModel):
    """Autopilot control plane status."""

    state: str = Field(
        ..., description="Current state: DISABLED, ENABLED, EMERGENCY_STOPPED"
    )
    is_enabled: bool = Field(..., description="Whether autopilot is enabled")
    is_emergency_stopped: bool = Field(..., description="Whether in emergency stop")
    current_policy: Optional[Dict[str, Any]] = Field(
        None, description="Current policy if enabled"
    )
    last_state_change: Optional[str] = Field(
        None, description="ISO timestamp of last change"
    )


class AutopilotEnableRequest(BaseModel):
    """Request to enable autopilot."""

    policy: str = Field(
        default="conservative",
        description="Policy: conservative, standard, permissive",
    )
    reason: Optional[str] = Field(None, description="Reason for enabling")


class AutopilotPolicySetRequest(BaseModel):
    """Request to change policy."""

    policy: str = Field(
        ..., description="New policy: conservative, standard, permissive"
    )
    reason: Optional[str] = Field(None, description="Reason for policy change")


class AutopilotEmergencyActionRequest(BaseModel):
    """Request for emergency stop/resume."""

    reason: str = Field(..., description="Reason for action")


class PolicyInfo(BaseModel):
    """Information about an autopilot policy."""

    name: str = Field(..., description="Policy name")
    policy_id: str = Field(..., description="Policy unique ID")
    confidence_threshold: float = Field(
        ..., description="Global confidence threshold (0.0-1.0)"
    )
    max_concurrent_actions: int = Field(
        ..., description="Max concurrent autonomous actions"
    )
    status: str = Field(..., description="Policy status")


class EventLogEntry(BaseModel):
    """Canonical event log entry."""

    event_id: str
    timestamp: str
    event_type: str
    severity: str
    aggregate_id: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
