# -*- coding: utf-8 -*-
"""FastAPI adapter server - Modular entry point."""

from __future__ import annotations
import asyncio
import logging
import os
import sys
import time
import re
import uuid
from pathlib import Path
from typing import Any
from literature_assistant.bootstrap import configure_runtime_paths


configure_runtime_paths()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
try:
    import uvicorn
except ImportError:
    pass

from project_paths import FRONTEND_ROOT, runtime_state_path

# Import configuration and models
from datetime_utils import to_iso_z
from models import *
from models.common import ErrorCode, ErrorDetail, ErrorResponse

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


def _get_allowed_origins() -> list[str]:
    """
    Resolve browser origins allowed to call the local adapter.

    Why:
        The frontend runs on a separate dev origin under Vite, so the API must
        answer preflight requests or the browser will block the workspace.
    """
    raw_origins = os.environ.get("FRONTEND_ALLOW_ORIGINS", "").strip()
    if not raw_origins:
        return [
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]

    if raw_origins == "*":
        return ["*"]

    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def _stable_operation_id(route: Any) -> str:
    """Generate stable operation IDs for OpenAPI-driven SDK generation."""
    methods = sorted(getattr(route, "methods", None) or ["GET"])
    method = methods[0].lower()
    path = getattr(route, "path_format", getattr(route, "path", ""))
    normalized = path.lstrip("/") or "root"
    normalized = re.sub(r"\{([^}]+)\}", r"\1", normalized)
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", normalized).strip("_")
    if not normalized:
        normalized = "root"
    return f"{method}_{normalized}"


# App initialization
OPENAPI_TAGS = [
    {"name": "System", "description": "系统健康与状态"},
    {"name": "Chat", "description": "LLM 对话代理（同步 + 流式）"},
    {"name": "Resources", "description": "项目、章节、素材、草稿管理"},
    {"name": "Wiki", "description": "Wiki 页面编译、查询、图谱与审计诊断"},
    {"name": "Volume", "description": "批处理合卷与跨论文对比分析"},
    {"name": "Pipeline", "description": "分析管线执行与任务管理"},
    {"name": "Runtime", "description": "写作运行时：会话、作业、事件"},
    {"name": "Skills", "description": "技能注册与执行"},
    {"name": "Memory", "description": "MemPalace 记忆搜索与同步"},
    {"name": "Inspiration", "description": "启发点生成与续写上下文"},
    {"name": "Recovery", "description": "恢复控制台、事件、推荐"},
    {"name": "Recovery: Autopilot & Observability", "description": "自动驾驶恢复与可观测性"},
    {"name": "Agent", "description": "AI 调度与工具注册"},
    {"name": "Export", "description": "项目导出（Markdown / BibTeX / ZIP）"},
    {"name": "Statistics", "description": "项目统计与分析数据"},
]

app = FastAPI(
    title="Scholar AI API",
    description="学术研究智能体 — 论文分析、知识管理与智能写作辅助平台",
    version="1.3.0",
    generate_unique_id_function=_stable_operation_id,
    openapi_tags=OPENAPI_TAGS,
)
_allowed_origins = _get_allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials="*" not in _allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global Request Tracing Middleware (learned from open-webui X-Process-Time)
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_tracing_middleware(request: Request, call_next):
    """Inject trace ID and processing time into every response."""
    trace_id = request.headers.get("X-Request-Id", uuid.uuid4().hex[:16])
    request.state.trace_id = trace_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    response.headers["X-Request-Id"] = trace_id
    response.headers["X-Process-Time-Ms"] = str(round(elapsed_ms, 2))
    return response


# ---------------------------------------------------------------------------
# Global Exception Handlers (learned from textgen / open-webui)
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return structured error for Pydantic validation failures."""
    first = exc.errors()[0] if exc.errors() else {}
    field = " -> ".join(str(l) for l in first.get("loc", [])) if first else None
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.VALIDATION_ERROR,
                message=first.get("msg", "请求参数验证失败"),
                field=field,
                trace_id=getattr(request.state, "trace_id", None),
            )
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Wrap FastAPI HTTPException into unified ErrorResponse."""
    code_map = {
        400: ErrorCode.BAD_REQUEST,
        404: ErrorCode.NOT_FOUND,
        422: ErrorCode.VALIDATION_ERROR,
        500: ErrorCode.INTERNAL_ERROR,
        502: ErrorCode.LLM_CONNECTION_ERROR,
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=code_map.get(exc.status_code, ErrorCode.INTERNAL_ERROR),
                message=str(exc.detail),
                trace_id=getattr(request.state, "trace_id", None),
            )
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions — never leak stack traces."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.INTERNAL_ERROR,
                message="服务器内部错误，请稍后重试",
                trace_id=getattr(request.state, "trace_id", None),
            )
        ).model_dump(),
    )

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


FRONTEND_DIST_DIR = FRONTEND_ROOT / "dist"
FRONTEND_INDEX_FILE = FRONTEND_DIST_DIR / "index.html"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
_API_ROUTE_PREFIXES = (
    "api",
    "health",
    "runtime",
    "resources",
    "skills",
    "memory",
    "recovery",
    "pipeline",
    "actions",
    "capabilities",
    "inspiration",
    "agent",
    "autopilot",
    "chat",
    "llm",
    "volumes",
)
_DOC_ROUTE_PREFIXES = ("openapi.json", "docs", "redoc")


def _first_path_segment(path: str) -> str:
    normalized = path.lstrip("/")
    if not normalized:
        return ""
    return normalized.split("/", 1)[0]


def _is_api_or_docs_path(path: str) -> bool:
    first_segment = _first_path_segment(path)
    return first_segment in _API_ROUTE_PREFIXES or first_segment in _DOC_ROUTE_PREFIXES


def _resolve_frontend_file(path: str) -> Path | None:
    if not FRONTEND_DIST_DIR.is_dir():
        return None

    normalized = path.lstrip("/")
    if not normalized:
        return FRONTEND_INDEX_FILE if FRONTEND_INDEX_FILE.is_file() else None

    candidate = (FRONTEND_DIST_DIR / normalized).resolve()
    try:
        candidate.relative_to(FRONTEND_DIST_DIR.resolve())
    except ValueError:
        return None

    if candidate.is_file():
        return candidate

    return None

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
            db_path=str(runtime_state_path("harness_canonical_events.db"))
        )
    return _event_store_instance

def get_fact_store() -> MemoryFactStore:
    global _fact_store_instance
    if _fact_store_instance is None:
        _fact_store_instance = MemoryFactStore(
            db_path=str(runtime_state_path("harness_facts.db"))
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
        "version": "1.3.0",
        "timestamp": time.time(),
        "api_version": "v1",
        "modules": {
            "pipeline": HAS_PIPELINE,
            "skills": HAS_SKILLS,
            "runtime": HAS_RUNTIME,
            "resources": HAS_RESOURCES,
            "mempalace": HAS_MEMPALACE,
        },
        "endpoints": {
            "chat": ["/chat/ask", "/chat/stream", "/chat/models"],
            "resources": ["/resources/projects", "/resources/sections", "/resources/materials",
                          "/resources/drafts", "/resources/documents", "/resources/association"],
            "volumes": ["/volumes", "/volumes/{volume_key}/analysis"],
            "export": ["/resources/project/{id}/export"],
            "statistics": ["/resources/project/{id}/stats", "/resources/stats/overview"],
            "pipeline": ["/pipeline/trigger", "/pipeline/submit", "/pipeline/task/{id}"],
            "runtime": ["/runtime/session", "/runtime/job", "/runtime/events"],
            "memory": ["/memory/status", "/memory/search"],
            "inspiration": ["/inspiration/generate"],
            "recovery": ["/recovery/events", "/recovery/recommendations"],
        },
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
from routers.inspiration_router import router as inspiration_router
from routers.agent_router import router as agent_router
from routers.chat_router import router as chat_router
from routers.intelligent_chat_router import router as intelligent_chat_router
from routers.llm_cost_router import router as llm_cost_router
from routers.sampling_router import router as sampling_router
from routers.volume_router import router as volume_router
from routers.wiki_router import router as wiki_router
from routers.export_router import router as export_router
from routers.annotation_router import router as annotation_router
from routers.discussion_router import router as discussion_router

app.include_router(pipeline_router)
app.include_router(skills_router)
app.include_router(runtime_router)
app.include_router(resources_router)
app.include_router(memory_router)
app.include_router(recovery_router)
app.include_router(autopilot_router)
app.include_router(inspiration_router)
app.include_router(agent_router)
app.include_router(chat_router)
app.include_router(intelligent_chat_router)
app.include_router(llm_cost_router)
app.include_router(sampling_router)
app.include_router(volume_router)
app.include_router(wiki_router)
app.include_router(export_router)
app.include_router(annotation_router)
app.include_router(discussion_router)

if FRONTEND_ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")


@app.get("/", include_in_schema=False)
async def serve_frontend_root():
    if not FRONTEND_INDEX_FILE.is_file():
        raise HTTPException(status_code=404, detail="Frontend build not found")
    return FileResponse(
        FRONTEND_INDEX_FILE,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend_spa(full_path: str) -> FileResponse:
    if _is_api_or_docs_path(full_path):
        raise HTTPException(status_code=404, detail=f"Route not found: /{full_path}")

    resolved_file = _resolve_frontend_file(full_path)
    if resolved_file is not None:
        return FileResponse(resolved_file)

    first_segment = _first_path_segment(full_path)
    if first_segment == "assets" or Path(full_path).suffix:
        raise HTTPException(status_code=404, detail=f"Static asset not found: /{full_path}")

    if FRONTEND_INDEX_FILE.is_file():
        return FileResponse(
            FRONTEND_INDEX_FILE,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
        )

    raise HTTPException(status_code=404, detail="Frontend build not found")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(app, host="127.0.0.1", port=port)
