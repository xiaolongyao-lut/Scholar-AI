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
import os
from typing import Any, Dict, List, Optional
from argparse import Namespace

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

# Import models from centralized models package
from models import (
    AutopilotStatusResponse,
    AutopilotEnableRequest,
    AutopilotPolicySetRequest,
    AutopilotEmergencyActionRequest,
    PolicyInfo,
    EventLogEntry,
)

# Recovery stack imports
from recovery_autopilot_control_plane import ControlPlaneState
from recovery_autopilot_policy import (
    create_conservative_policy,
    create_standard_policy,
    create_permissive_policy,
)
from recovery_store_provider import get_event_store, get_fact_store
from recovery_metrics_exporter import get_recovery_metrics_collector
from datetime_utils import utc_now_iso_z

logger = logging.getLogger("RecoveryAutopilotRouter")

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
async def get_autopilot_status():
    """Get current autopilot control plane state."""
    try:
        from recovery_autopilot_cli import get_autopilot_control_plane

        cp = get_autopilot_control_plane()
        policy = cp.get_current_policy() if cp.is_enabled() else None

        # Get state from control plane
        state_val = cp._state.value if hasattr(cp._state, "value") else str(cp._state)

        return AutopilotStatusResponse(
            state=state_val,
            is_enabled=cp.is_enabled(),
            is_emergency_stopped=(cp._state == ControlPlaneState.EMERGENCY_STOPPED),
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
async def enable_autopilot(req: AutopilotEnableRequest):
    """Enable autopilot with specified policy."""
    try:
        from recovery_autopilot_cli import (
            cmd_autopilot_enable,
            get_autopilot_control_plane,
        )

        # Set operator ID from environment or default
        os.environ["RECOVERY_OPERATOR_ID"] = "api-client"

        args = Namespace(
            policy=req.policy,
            reason=req.reason or f"Enabled via REST API at {utc_now_iso_z()}",
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
async def disable_autopilot(req: Dict[str, Any] = None):
    """Disable autopilot."""
    try:
        from recovery_autopilot_cli import cmd_autopilot_disable

        os.environ["RECOVERY_OPERATOR_ID"] = "api-client"

        reason = req.get("reason") if req else None
        args = Namespace(reason=reason or "Disabled via REST API")

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
async def emergency_stop(req: AutopilotEmergencyActionRequest):
    """Trigger emergency stop."""
    try:
        from recovery_autopilot_cli import cmd_autopilot_emergency_stop

        os.environ["RECOVERY_OPERATOR_ID"] = "api-client"

        args = Namespace(reason=req.reason)
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
async def emergency_resume(req: Dict[str, Any] = None):
    """Resume from emergency stop."""
    try:
        from recovery_autopilot_cli import cmd_autopilot_emergency_resume

        os.environ["RECOVERY_OPERATOR_ID"] = "api-client"

        reason = req.get("reason") if req else None
        args = Namespace(reason=reason or "Resumed via REST API")

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
    response_model=List[PolicyInfo],
    summary="List available policies",
    tags=["Autopilot"],
)
async def list_policies():
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
async def set_policy(req: AutopilotPolicySetRequest):
    """Change the autopilot policy."""
    try:
        from recovery_autopilot_cli import cmd_autopilot_policy_set

        os.environ["RECOVERY_OPERATOR_ID"] = "api-client"

        args = Namespace(
            policy=req.policy, reason=req.reason or f"Changed via REST API to {req.policy}"
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
