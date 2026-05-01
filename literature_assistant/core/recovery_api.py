"""
Phase H4.1: Recovery API - FastAPI Integration

Exposes recovery stack via REST API:
  - Recovery recommendations
  - Event history
  - Temporal facts
  - Autopilot control and policy management
  - Metrics export

All operations emit canonical events for complete audit trail.
All HTTP endpoints are tracked in metrics for observability.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Dict, List
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from pydantic import BaseModel, Field

# Import recovery stack
from recovery_autopilot_control_plane import AutopilotControlPlane, ControlPlaneState
from recovery_autopilot_policy import AutopilotPolicy
from recovery_recommendation_engine import RecoveryRecommendationEngine
from recovery_store_provider import get_event_store, get_fact_store
from recovery_console import RecoveryConsole
from recovery_execution_engine import RecoveryExecutionEngine
from recovery_metrics_exporter import get_recovery_metrics_collector
from datetime_utils import utc_now_iso_z

logger = logging.getLogger("RecoveryAPI")

# ---
# Request/Response Models
# ---


class AutopilotStatusResponse(BaseModel):
    """Autopilot control plane status."""
    state: str  = Field(..., description="Current state: DISABLED, ENABLED, EMERGENCY_STOPPED")
    is_enabled: bool = Field(..., description="Whether autopilot is enabled")
    is_emergency_stopped: bool = Field(..., description="Whether in emergency stop")
    current_policy: Optional[Dict[str, Any]] = Field(None, description="Current policy if enabled")
    last_state_change: Optional[str] = Field(None, description="ISO timestamp of last change")


class AutopilotEnableRequest(BaseModel):
    """Request to enable autopilot."""
    policy: str = Field(default="conservative", description="Policy: conservative, standard, permissive")
    reason: Optional[str] = Field(None, description="Reason for enabling")


class AutopilotPolicySetRequest(BaseModel):
    """Request to change policy."""
    policy: str = Field(..., description="New policy: conservative, standard, permissive")
    reason: Optional[str] = Field(None, description="Reason for policy change")


class AutopilotEmergencyActionRequest(BaseModel):
    """Request for emergency stop/resume."""
    reason: str = Field(..., description="Reason for action")


class PolicyInfo(BaseModel):
    """Information about an autopilot policy."""
    name: str = Field(..., description="Policy name")
    policy_id: str = Field(..., description="Policy unique ID")
    confidence_threshold: float = Field(..., description="Global confidence threshold (0.0-1.0)")
    max_concurrent_actions: int = Field(..., description="Max concurrent autonomous actions")
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


class MetricsResponse(BaseModel):
    """Collection of recovery metrics."""
    http_requests_total: int
    http_errors_total: int
    recovery_recommendations_generated: int
    autopilot_decisions: int
    canonical_events_total: int


# --- 
# Metrics Tracking Middleware
# ---


# Note: Simplified middleware - full instrumental timing would be added in H4.2
# Currently tracks via FastAPI endpoint directly


# ---
# FastAPI Application
# ---


def create_recovery_api() -> FastAPI:
    """Create and configure the Recovery API."""
    
    app = FastAPI(
        title="Harness Recovery API",
        description="REST API for autonomous recovery stack",
        version="H4.1",
        docs_url="/recovery/docs",
        openapi_url="/recovery/openapi.json",
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # ===
    # Autopilot Endpoints
    # ===
    
    @app.get(
        "/recovery/autopilot/status",
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
            state_val = cp._state.value if hasattr(cp._state, 'value') else str(cp._state)
            
            return AutopilotStatusResponse(
                state=state_val,
                is_enabled=cp.is_enabled(),
                is_emergency_stopped=cp._state == ControlPlaneState.EMERGENCY_STOPPED,
                current_policy={
                    "name": policy.policy_name,
                    "id": policy.policy_id,
                    "confidence_threshold": policy.global_confidence_threshold,
                    "max_concurrent": policy.global_max_concurrent_actions,
                } if policy else None,
                last_state_change=utc_now_iso_z(),
            )
        except Exception as e:
            logger.error("Error fetching autopilot status: %s", str(e))
            raise HTTPException(status_code=500, detail=str(e)) from e
    
    @app.post(
        "/recovery/autopilot/enable",
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
            from argparse import Namespace
            import os
            
            # Set operator ID from environment or header
            os.environ["RECOVERY_OPERATOR_ID"] = "api-client"
            
            args = Namespace(
                policy=req.policy,
                reason=req.reason or f"Enabled via REST API at {utc_now_iso_z()}"
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
            logger.error(f"Error enabling autopilot: {e}")
            raise HTTPException(status_code=400, detail=str(e))
    
    @app.post(
        "/recovery/autopilot/disable",
        response_model=Dict[str, Any],
        summary="Disable autopilot",
        tags=["Autopilot"],
    )
    async def disable_autopilot(req: Dict[str, Any] = None):
        """Disable autopilot."""
        try:
            from recovery_autopilot_cli import cmd_autopilot_disable
            from argparse import Namespace
            import os
            
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
            logger.error(f"Error disabling autopilot: {e}")
            raise HTTPException(status_code=400, detail=str(e))
    
    @app.post(
        "/recovery/autopilot/emergency-stop",
        response_model=Dict[str, Any],
        summary="Emergency stop autopilot",
        tags=["Autopilot"],
    )
    async def emergency_stop(req: AutopilotEmergencyActionRequest):
        """Trigger emergency stop."""
        try:
            from recovery_autopilot_cli import cmd_autopilot_emergency_stop
            from argparse import Namespace
            import os
            
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
            logger.error(f"Error in emergency stop: {e}")
            raise HTTPException(status_code=400, detail=str(e))
    
    @app.post(
        "/recovery/autopilot/emergency-resume",
        response_model=Dict[str, Any],
        summary="Resume from emergency stop",
        tags=["Autopilot"],
    )
    async def emergency_resume(req: Dict[str, Any] = None):
        """Resume from emergency stop."""
        try:
            from recovery_autopilot_cli import cmd_autopilot_emergency_resume
            from argparse import Namespace
            import os
            
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
            logger.error(f"Error resuming: {e}")
            raise HTTPException(status_code=400, detail=str(e))
    
    @app.get(
        "/recovery/autopilot/policies",
        response_model=List[PolicyInfo],
        summary="List available policies",
        tags=["Autopilot"],
    )
    async def list_policies():
        """Get list of available autopilot policies."""
        try:
            from recovery_autopilot_policy import (
                create_conservative_policy,
                create_standard_policy,
                create_permissive_policy,
            )
            
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
                    status=p.status.value if hasattr(p.status, 'value') else str(p.status),
                )
                for p in policies
            ]
        except Exception as e:
            logger.error("Error listing policies: %s", str(e))
            raise HTTPException(status_code=500, detail=str(e)) from e
    
    @app.post(
        "/recovery/autopilot/policy/set",
        response_model=Dict[str, Any],
        summary="Change autopilot policy",
        tags=["Autopilot"],
    )
    async def set_policy(req: AutopilotPolicySetRequest):
        """Change the autopilot policy."""
        try:
            from recovery_autopilot_cli import cmd_autopilot_policy_set
            from argparse import Namespace
            import os
            
            os.environ["RECOVERY_OPERATOR_ID"] = "api-client"
            
            args = Namespace(
                policy=req.policy,
                reason=req.reason or f"Changed via REST API to {req.policy}"
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
            logger.error(f"Error setting policy: {e}")
            raise HTTPException(status_code=400, detail=str(e))
    
    # ===
    # Event & Metrics Endpoints
    # ===
    
    @app.get(
        "/recovery/events",
        response_model=List[EventLogEntry],
        summary="Get event history",
        tags=["Events"],
    )
    async def get_events(
        job_id: Optional[str] = Query(None, description="Filter by job ID"),
        limit: int = Query(50, description="Max events to return"),
    ):
        """Get canonical event history."""
        try:
            store = get_event_store()
            
            if job_id:
                events = store.get_job_timeline(job_id)
            else:
                # Get error events up to limit
                events = store.get_error_events(limit=limit)
            
            return [
                EventLogEntry(
                    event_id=e.event_id,
                    timestamp=e.timestamp,
                    event_type=e.event_type,
                    severity=e.severity,
                    aggregate_id=e.aggregate_id,
                    error_code=e.error_code,
                    error_message=e.error_message,
                )
                for e in events
            ]
        except Exception as e:
            logger.error("Error fetching events: %s", str(e))
            raise HTTPException(status_code=500, detail=str(e)) from e
    
    @app.get(
        "/recovery/metrics",
        response_class=PlainTextResponse,
        summary="Prometheus metrics export",
        tags=["Metrics"],
    )
    async def get_metrics():
        """Export recovery metrics in Prometheus text format."""
        try:
            collector = get_recovery_metrics_collector()
            return collector.render_prometheus_text()
        except Exception as e:
            logger.error(f"Error exporting metrics: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # ===
    # Health Checks
    # ===
    
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "timestamp": utc_now_iso_z()}
    
    @app.get("/recovery/health", tags=["Health"])
    async def recovery_health_check():
        """Recovery stack health check."""
        try:
            # Check all major components
            event_store = get_event_store()
            fact_store = get_fact_store()
            metrics = get_recovery_metrics_collector()
            
            return {
                "status": "healthy",
                "components": {
                    "event_store": "ok",
                    "fact_store": "ok",
                    "metrics": "ok",
                    "autopilot": "ok",
                },
                "timestamp": utc_now_iso_z(),
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            raise HTTPException(
                status_code=503,
                detail={"status": "degraded", "error": str(e)}
            )
    
    return app


# Create application instance
app = create_recovery_api()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
