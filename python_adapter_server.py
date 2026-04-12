# -*- coding: utf-8 -*-
"""FastAPI adapter server - Modular entry point."""

from __future__ import annotations
import asyncio
import logging
import os
import sys
import time
from typing import Any
from fastapi import FastAPI, Request
try:
    import uvicorn
except ImportError:
    pass

# Ensure current directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import configuration and models
from datetime_utils import to_iso_z
from models import *

# Module availability flags
try:
    from integrated_pipeline import run_pipeline
    HAS_PIPELINE = True
except ImportError:
    HAS_PIPELINE = False

try:
    from skills.service import get_writing_skill_service
    HAS_SKILLS = True
except ImportError:
    HAS_SKILLS = False

try:
    from writing_runtime import get_writing_runtime
    HAS_RUNTIME = True
except ImportError:
    HAS_RUNTIME = False

try:
    from writing_resources import get_writing_resource_store
    HAS_RESOURCES = True
except ImportError:
    HAS_RESOURCES = False

try:
    from layers.m_layer_mempalace_memory import MempalaceMemoryAdapter, load_mempalace_settings
    HAS_MEMPALACE = True
except ImportError:
    HAS_MEMPALACE = False

# Core recovery components
from recovery_console import RecoveryConsole
from memory_fact_store import MemoryFactStore
from canonical_event_store import CanonicalEventStore
from recovery_metrics_exporter import get_recovery_metrics_collector
from recovery_telemetry import get_recovery_telemetry

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("PipelineAdapter")

# App initialization
app = FastAPI(title="Modular Pipeline Adapter API")

@app.middleware("http")
async def recovery_observability_middleware(request: Request, call_next):
    """Record real HTTP metrics for all recovery endpoints."""
    if not request.url.path.startswith("/recovery/"):
        return await call_next(request)

    metrics = get_recovery_metrics_collector()
    telemetry = get_recovery_telemetry()
    start_time = time.perf_counter()
    
    path = request.url.path
    route_pattern = path
    if "/recovery/autopilot/" in path:
        parts = path.split("/")
        if len(parts) >= 4:
            route_pattern = f"/recovery/autopilot/{parts[3]}"
    elif "/recovery/events" in path:
        route_pattern = "/recovery/events"
    elif "/recovery/metrics" in path:
        route_pattern = "/recovery/metrics"
    elif "/recovery/health" in path:
        route_pattern = "/recovery/health"

    with telemetry.start_span(
        "recovery.http.request",
        {
            "http.method": request.method,
            "http.route": route_pattern,
            "http.path": path,
        },
    ) as span:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        
        span.set_attribute("http.status_code", response.status_code)
        span.set_attribute("duration_ms", duration_ms)
        
        # Inject trace headers for test compliance
        response.headers["X-Recovery-Trace-Id"] = span.trace_id
        response.headers["X-Recovery-Span-Id"] = span.span_id
        response.headers["X-Recovery-Duration-Ms"] = str(round(duration_ms, 2))
        
        # Record metrics
        metrics.record_http_request(
            method=request.method,
            route=route_pattern,
            status_code=response.status_code,
            duration_ms=duration_ms
        )
        return response

# ===
# Shared Service Providers
# ===

_memory_adapter_instance = None

def get_memory_adapter() -> Any:
    """Return shared MemPalace adapter."""
    if not HAS_MEMPALACE: return None
    global _memory_adapter_instance
    if _memory_adapter_instance is None:
        _memory_adapter_instance = MempalaceMemoryAdapter(load_mempalace_settings())
    return _memory_adapter_instance

_event_store_instance = None
_fact_store_instance = None
_recovery_console_instance = None

def get_event_store() -> CanonicalEventStore:
    global _event_store_instance
    if _event_store_instance is None:
        _event_store_instance = CanonicalEventStore(
            db_path=os.path.join(os.path.dirname(__file__), "harness_canonical_events.db")
        )
    return _event_store_instance

def get_fact_store() -> MemoryFactStore:
    global _fact_store_instance
    if _fact_store_instance is None:
        _fact_store_instance = MemoryFactStore(
            db_path=os.path.join(os.path.dirname(__file__), "harness_facts.db")
        )
    return _fact_store_instance

# Global recovery console instance (singleton)
_recovery_console_instance = None

_observer_instance = None

def get_pipeline_observer() -> Any:
    """Return shared pipeline observer (Logging + Metrics)."""
    global _observer_instance
    if _observer_instance is None:
        from modules.container import create_default_container
        container = create_default_container()
        _observer_instance = container.get("observer")
    return _observer_instance

def get_recovery_console() -> RecoveryConsole:
    global _recovery_console_instance
    if _recovery_console_instance is None:
        _recovery_console_instance = RecoveryConsole(
            event_store=get_event_store(),
            fact_store=get_fact_store(),
        )
    return _recovery_console_instance

# ===
# System Health
# ===

@app.get("/health", tags=["System"])
async def health_check() -> dict[str, Any]:
    """Return adapter server system health state."""
    return {
        "status": "ok",
        "version": "1.2.0",
        "timestamp": time.time(),
        "modules": {
            "pipeline": HAS_PIPELINE,
            "skills": HAS_SKILLS,
            "runtime": HAS_RUNTIME,
            "resources": HAS_RESOURCES,
            "mempalace": HAS_MEMPALACE
        }
    }

# ===
# Mount Modular Routers
# ===
from routers.pipeline_router import router as pipeline_router
from routers.skills_router import router as skills_router
from routers.resources_router import router as resources_router
from routers.memory_router import router as memory_router
from routers.runtime_router import router as runtime_router
from routers.recovery_router import router as recovery_router
from recovery_autopilot_router import router as autopilot_router

app.include_router(pipeline_router)
app.include_router(skills_router)
app.include_router(runtime_router)
app.include_router(resources_router)
app.include_router(memory_router)
app.include_router(recovery_router)
app.include_router(autopilot_router)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(app, host="127.0.0.1", port=port)
