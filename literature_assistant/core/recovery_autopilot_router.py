"""
Recovery Autopilot Router - APIRouter for autopilot and observability endpoints

Provides modular FastAPI router with:
- Autopilot control endpoints (enable, disable, emergency-stop, etc.)
- Policy management endpoints
- Event history endpoints
- Metrics export endpoint
- Health check endpoints

This router is designed to be included in the main FastAPI adapter application.
"""

from __future__ import annotations

import logging
from argparse import Namespace
from typing import TYPE_CHECKING, Any, Dict, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from literature_assistant.core.datetime_utils import utc_now_iso_z
    from literature_assistant.core.models import (
        AutopilotEmergencyActionRequest,
        AutopilotEnableRequest,
        AutopilotPolicySetRequest,
        AutopilotStatusResponse,
        EventLogEntry,
        PolicyInfo,
    )
    from literature_assistant.core.recovery_autopilot_control_plane import ControlPlaneState
    from literature_assistant.core.recovery_autopilot_policy import (
        create_conservative_policy,
        create_permissive_policy,
        create_standard_policy,
    )
    from literature_assistant.core.recovery_metrics_exporter import (
        get_recovery_metrics_collector,
    )
    from literature_assistant.core.recovery_store_provider import get_event_store, get_fact_store
else:
    from datetime_utils import utc_now_iso_z
    from models import (
        AutopilotEmergencyActionRequest,
        AutopilotEnableRequest,
        AutopilotPolicySetRequest,
        AutopilotStatusResponse,
        EventLogEntry,
        PolicyInfo,
    )
    from recovery_autopilot_control_plane import ControlPlaneState
    from recovery_autopilot_policy import (
        create_conservative_policy,
        create_permissive_policy,
        create_standard_policy,
    )
    from recovery_metrics_exporter import get_recovery_metrics_collector
    from recovery_store_provider import get_event_store, get_fact_store

logger = logging.getLogger("RecoveryAutopilotRouter")

_API_OPERATOR_ID = "api-client"


class AutopilotEnableResult(TypedDict):
    """Successful autopilot enable response."""

    status: Literal["enabled"]
    policy: str
    timestamp: str
    reason: str | None


class AutopilotDisableResult(TypedDict):
    """Successful autopilot disable response."""

    status: Literal["disabled"]
    timestamp: str


class AutopilotEmergencyStopResult(TypedDict):
    """Successful emergency-stop response."""

    status: Literal["emergency_stopped"]
    reason: str
    timestamp: str


class AutopilotEmergencyResumeResult(TypedDict):
    """Successful emergency-resume response."""

    status: Literal["resumed"]
    timestamp: str


class AutopilotPolicySetResult(TypedDict):
    """Successful policy-change response."""

    status: Literal["policy_set"]
    policy: str
    timestamp: str

# ---
# Create APIRouter
# ---

router = APIRouter(
    prefix="/recovery",
    tags=["Recovery: Autopilot & Observability"],
)


# ===
# Autopilot Status Endpoint
# ===


@router.get(
    "/autopilot/status",
    response_model=AutopilotStatusResponse,
    summary="Get autopilot status",
    tags=["Autopilot"],
)
async def get_autopilot_status() -> AutopilotStatusResponse:
    """Get current autopilot control plane state."""
    try:
        if TYPE_CHECKING:
            from literature_assistant.core.recovery_autopilot_cli import (
                get_autopilot_control_plane,
            )
        else:
            from recovery_autopilot_cli import get_autopilot_control_plane

        cp = get_autopilot_control_plane()
        policy = cp.get_current_policy() if cp.is_enabled() else None

        # Prefer public accessor when available (legacy callers may still rely
        # on ``_state``); fall back to the underscored attribute for backwards
        # compatibility but coerce to its ``value`` for the response payload.
        raw_state: object = getattr(cp, "state", None) or getattr(cp, "_state", None)
        state_val = str(getattr(raw_state, "value", raw_state))
        is_emergency = raw_state == ControlPlaneState.EMERGENCY_STOPPED

        return AutopilotStatusResponse(
            state=state_val,
            is_enabled=cp.is_enabled(),
            is_emergency_stopped=is_emergency,
            current_policy=(
                {
                    "name": policy.policy_name,
                    "id": policy.policy_id,
                    "confidence_threshold": policy.global_confidence_threshold,
                    "max_concurrent": policy.global_max_concurrent_actions,
                }
                if policy
                else None
            ),
            last_state_change=utc_now_iso_z(),
        )
    except Exception as e:
        logger.error("Error fetching autopilot status: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===
# Autopilot Enable Endpoint
# ===


@router.post(
    "/autopilot/enable",
    response_model=Dict[str, Any],
    summary="Enable autopilot",
    tags=["Autopilot"],
)
async def enable_autopilot(req: AutopilotEnableRequest) -> AutopilotEnableResult:
    """Enable autopilot with specified policy."""
    try:
        if TYPE_CHECKING:
            from literature_assistant.core.recovery_autopilot_cli import (
                cmd_autopilot_enable,
                get_autopilot_control_plane,
            )
        else:
            from recovery_autopilot_cli import (
                cmd_autopilot_enable,
                get_autopilot_control_plane,
            )

        # Operator id passed via Namespace so concurrent requests don't race on
        # a process-wide env var (RECOVERY_OPERATOR_ID).
        args = Namespace(
            policy=req.policy,
            reason=req.reason or f"Enabled via REST API at {utc_now_iso_z()}",
            operator_id=_API_OPERATOR_ID,
        )

        result = cmd_autopilot_enable(args)

        if result != 0:
            raise Exception("Failed to enable autopilot")

        cp = get_autopilot_control_plane()
        return {
            "status": "enabled",
            "policy": req.policy,
            "timestamp": utc_now_iso_z(),
            "reason": req.reason,
        }
    except Exception as e:
        logger.error("Error enabling autopilot: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ===
# Autopilot Disable Endpoint
# ===


@router.post(
    "/autopilot/disable",
    response_model=Dict[str, Any],
    summary="Disable autopilot",
    tags=["Autopilot"],
)
async def disable_autopilot(
    req: Dict[str, Any] | None = None,
) -> AutopilotDisableResult:
    """Disable autopilot."""
    try:
        if TYPE_CHECKING:
            from literature_assistant.core.recovery_autopilot_cli import cmd_autopilot_disable
        else:
            from recovery_autopilot_cli import cmd_autopilot_disable

        reason = req.get("reason") if req else None
        args = Namespace(reason=reason or "Disabled via REST API", operator_id=_API_OPERATOR_ID)

        result = cmd_autopilot_disable(args)

        if result != 0:
            raise Exception("Failed to disable autopilot")

        return {
            "status": "disabled",
            "timestamp": utc_now_iso_z(),
        }
    except Exception as e:
        logger.error("Error disabling autopilot: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ===
# Emergency Stop Endpoint
# ===


@router.post(
    "/autopilot/emergency-stop",
    response_model=Dict[str, Any],
    summary="Emergency stop autopilot",
    tags=["Autopilot"],
)
async def emergency_stop(
    req: AutopilotEmergencyActionRequest,
) -> AutopilotEmergencyStopResult:
    """Trigger emergency stop."""
    try:
        if TYPE_CHECKING:
            from literature_assistant.core.recovery_autopilot_cli import (
                cmd_autopilot_emergency_stop,
            )
        else:
            from recovery_autopilot_cli import cmd_autopilot_emergency_stop

        args = Namespace(reason=req.reason, operator_id=_API_OPERATOR_ID)
        result = cmd_autopilot_emergency_stop(args)

        if result != 0:
            raise Exception("Failed to emergency stop")

        return {
            "status": "emergency_stopped",
            "reason": req.reason,
            "timestamp": utc_now_iso_z(),
        }
    except Exception as e:
        logger.error("Error in emergency stop: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ===
# Emergency Resume Endpoint
# ===


@router.post(
    "/autopilot/emergency-resume",
    response_model=Dict[str, Any],
    summary="Resume from emergency stop",
    tags=["Autopilot"],
)
async def emergency_resume(
    req: Dict[str, Any] | None = None,
) -> AutopilotEmergencyResumeResult:
    """Resume from emergency stop."""
    try:
        if TYPE_CHECKING:
            from literature_assistant.core.recovery_autopilot_cli import (
                cmd_autopilot_emergency_resume,
            )
        else:
            from recovery_autopilot_cli import cmd_autopilot_emergency_resume

        reason = req.get("reason") if req else None
        args = Namespace(reason=reason or "Resumed via REST API", operator_id=_API_OPERATOR_ID)

        result = cmd_autopilot_emergency_resume(args)

        if result != 0:
            raise Exception("Failed to resume")

        return {
            "status": "resumed",
            "timestamp": utc_now_iso_z(),
        }
    except Exception as e:
        logger.error("Error resuming: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ===
# Policies Endpoint
# ===


@router.get(
    "/autopilot/policies",
    response_model=list[PolicyInfo],
    summary="List available policies",
    tags=["Autopilot"],
)
async def list_policies() -> list[PolicyInfo]:
    """Get list of available autopilot policies."""
    try:
        policies = [
            create_conservative_policy(),
            create_standard_policy(),
            create_permissive_policy(),
        ]

        return [
            PolicyInfo(
                name=p.policy_name,
                policy_id=p.policy_id,
                confidence_threshold=p.global_confidence_threshold,
                max_concurrent_actions=p.global_max_concurrent_actions,
                status=p.status.value if hasattr(p.status, "value") else str(p.status),
            )
            for p in policies
        ]
    except Exception as e:
        logger.error("Error listing policies: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


# ===
# Policy Set Endpoint
# ===


@router.post(
    "/autopilot/policy/set",
    response_model=Dict[str, Any],
    summary="Change autopilot policy",
    tags=["Autopilot"],
)
async def set_policy(req: AutopilotPolicySetRequest) -> AutopilotPolicySetResult:
    """Change the autopilot policy."""
    try:
        if TYPE_CHECKING:
            from literature_assistant.core.recovery_autopilot_cli import cmd_autopilot_policy_set
        else:
            from recovery_autopilot_cli import cmd_autopilot_policy_set

        args = Namespace(
            policy=req.policy,
            reason=req.reason or f"Changed via REST API to {req.policy}",
            operator_id=_API_OPERATOR_ID,
        )

        result = cmd_autopilot_policy_set(args)

        if result != 0:
            raise Exception("Failed to set policy")

        return {
            "status": "policy_set",
            "policy": req.policy,
            "timestamp": utc_now_iso_z(),
        }
    except Exception as e:
        logger.error("Error setting policy: %s", str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ---
# Events and Observability (Removed - Handled by Main Adapter)
# ---

# Routes /events, /metrics, /health are handled by python_adapter_server
# to ensure consistent schema and extended logic.
