# -*- coding: utf-8 -*-
"""FastAPI adapter server - Modular entry point."""

from __future__ import annotations
import asyncio
import hmac
import logging
import mimetypes
import os
import secrets
import sys
import time
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from literature_assistant.bootstrap import configure_runtime_paths

mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/javascript", ".js")

configure_runtime_paths()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.routing import Match
try:
    import uvicorn
except ImportError:
    pass

from project_paths import (
    FRONTEND_ROOT,
    runtime_state_path,
    ensure_directory,
    api_port_file_path,
    desktop_runtime_file_path,
)
from runtime_descriptor import delete_desktop_runtime_descriptor, refresh_desktop_runtime_descriptor

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
# Stdout + rotating file. Disk log so 4xx/5xx survives after the terminal
# closes; the env var lets packaging override the location, while the
# default sits under workspace_artifacts/ (gitignored).
_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_LOG_LEVEL_NAME = os.environ.get("LITASSIST_LOG_LEVEL", "INFO").upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, logging.INFO)

_SENSITIVE_LOG_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)\b((?:authorization|x-api-key|[A-Za-z0-9_.-]*"
            r"(?:api[_-]?key|token|secret|password|passwd)[A-Za-z0-9_.-]*)"
            r"\s*[:=]\s*)(?:Bearer\s+)?[^\s,;]+"
        ),
        r"\1***REDACTED***",
    ),
    (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{8,}"),
        "Bearer ***REDACTED***",
    ),
    (
        re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{10,}\b"),
        "sk-***REDACTED***",
    ),
)


def _redact_sensitive_log_text(value: object) -> str:
    """Return log text with credential-shaped values removed.

    Args:
        value: Any object being formatted into a log record.

    Returns:
        A string safe for local rotating logs and terminal output.
    """

    text = str(value)
    for pattern, replacement in _SENSITIVE_LOG_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class SensitiveDataFilter(logging.Filter):
    """Filter log records before they reach console or disk handlers.

    Why:
        Backend errors may include provider headers, env-style assignments, or
        exception strings. Logs are durable runtime artifacts, so record
        messages are normalized before any handler writes them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_sensitive_log_text(record.getMessage())
        record.args = ()
        return True


def _install_sensitive_log_filter() -> None:
    """Install credential redaction on the root logger and current handlers."""

    root_logger = logging.getLogger()
    targets: list[Any] = [root_logger, *root_logger.handlers]
    for target in targets:
        filters = getattr(target, "filters", [])
        if not any(isinstance(existing, SensitiveDataFilter) for existing in filters):
            target.addFilter(SensitiveDataFilter())


logging.basicConfig(level=_LOG_LEVEL, format=_LOG_FORMAT)
_install_sensitive_log_filter()

if os.environ.get("LITASSIST_DISABLE_FILE_LOG") != "1":
    from logging.handlers import RotatingFileHandler
    try:
        _log_dir = ensure_directory(runtime_state_path("logs"))
        _file_handler = RotatingFileHandler(
            _log_dir / "backend.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        _file_handler.setLevel(_LOG_LEVEL)
        _file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        _root_logger = logging.getLogger()
        if not any(
            isinstance(h, RotatingFileHandler)
            and getattr(h, "baseFilename", "") == str(_file_handler.baseFilename)
            for h in _root_logger.handlers
        ):
            _root_logger.addHandler(_file_handler)
        _install_sensitive_log_filter()
    except OSError as _log_exc:
        logging.getLogger(__name__).warning(
            "Disk log disabled — could not create log file: %s", _log_exc
        )

logger = logging.getLogger("PipelineAdapter")

mimetypes.add_type("text/javascript", ".mjs")

_CAPABILITY_AUTH_ENV = "LITASSIST_API_CAPABILITY_AUTH"
_CAPABILITY_TOKEN_ENV = "LITASSIST_API_CAPABILITY_TOKEN"
_CAPABILITY_FILE_ENV = "LITASSIST_API_CAPABILITY_FILE"
LOCAL_API_CAPABILITY_HEADER = "X-LitAssist-Capability"
_LOCAL_API_CAPABILITY_TOKEN = os.environ.get(_CAPABILITY_TOKEN_ENV, "").strip() or secrets.token_urlsafe(32)


def _resolve_local_api_capability_file() -> Path:
    """Resolve the runtime capability handoff file.

    Why:
        Multiple local backend ports may run during MCP tests or diagnostics.
        Port-specific launchers need isolated token files so one process cannot
        overwrite another process's active capability.
    """

    explicit_path = os.environ.get(_CAPABILITY_FILE_ENV, "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    return runtime_state_path("api-capability.json")


_LOCAL_API_CAPABILITY_FILE = _resolve_local_api_capability_file()


def _get_allowed_origins() -> list[str]:
    """
    Resolve browser origins allowed to call the local adapter.

    Why:
        The frontend runs on a separate dev origin under Vite, so the API must
        answer preflight requests or the browser will block the workspace.
    """
    raw_origins = os.environ.get("FRONTEND_ALLOW_ORIGINS", "").strip()
    return _resolve_allowed_origins(raw_origins)


def _resolve_allowed_origins(raw_origins: str) -> list[str]:
    """Return explicit CORS origins for the local browser surface.

    Why:
        CORS is not authentication. Wildcard browser origins are only allowed
        for deliberate debugging because mutating local APIs are protected by a
        separate capability token.
    """

    normalized_origins = str(raw_origins or "").strip()
    if not normalized_origins:
        return [
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ]

    if normalized_origins == "*":
        if os.environ.get("LITASSIST_ALLOW_WILDCARD_CORS", "").strip() == "1":
            logger.warning("Wildcard frontend CORS enabled by explicit debug override.")
            return ["*"]
        logger.warning("Ignoring FRONTEND_ALLOW_ORIGINS='*'; set LITASSIST_ALLOW_WILDCARD_CORS=1 for debug only.")
        return _resolve_allowed_origins("")

    return [origin.strip() for origin in normalized_origins.split(",") if origin.strip()]


def _local_api_capability_auth_enabled() -> bool:
    """Return whether local API capability checks are enabled."""

    raw_value = os.environ.get(_CAPABILITY_AUTH_ENV, "1").strip().lower()
    return raw_value not in {"0", "false", "off", "no", "disabled"}


def get_local_api_capability_token() -> str:
    """Return the current process-local API capability token."""

    return _LOCAL_API_CAPABILITY_TOKEN


def _write_local_api_capability_file() -> None:
    """Persist the runtime-only capability token for trusted local launchers."""

    import tempfile
    from datetime import datetime, timezone

    target = _LOCAL_API_CAPABILITY_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "header": LOCAL_API_CAPABILITY_HEADER,
        "token": get_local_api_capability_token(),
        "pid": os.getpid(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(target.parent),
        prefix=target.name + ".", suffix=".tmp", delete=False,
    ) as fh:
        import json
        json.dump(payload, fh)
        tmp = Path(fh.name)
    os.replace(tmp, target)


def _delete_local_api_capability_file() -> None:
    """Remove the runtime-only capability token file on clean shutdown."""

    try:
        if _LOCAL_API_CAPABILITY_FILE.exists():
            _LOCAL_API_CAPABILITY_FILE.unlink()
    except OSError:
        pass


def _request_capability_token(request: Request) -> str:
    """Return the user-supplied local API capability token, if present."""

    header_value = request.headers.get(LOCAL_API_CAPABILITY_HEADER, "")
    return str(header_value or "").strip()


def _has_valid_local_api_capability(request: Request) -> bool:
    """Return true when request carries the process-local capability token."""

    supplied = _request_capability_token(request)
    expected = get_local_api_capability_token()
    if not supplied or not expected:
        return False
    return hmac.compare_digest(supplied, expected)


def _is_frontend_static_path(path: str) -> bool:
    """Return whether a path serves frontend shell/assets instead of API data.

    Beyond the SPA shell and hashed ``/assets/`` bundle, the built frontend
    ships root-level public files (the ``theme-boot.js`` CSP/FOUC guard,
    ``app-icon*.png`` launcher icons, ``favicon.ico``). These are non-sensitive
    client assets and must be reachable without the local API capability token,
    otherwise the embedded WebView gets 403 on them (logo/icon missing, dark
    FOUC guard never runs). ``_resolve_frontend_file`` is path-traversal safe
    and only matches files that actually exist inside the built dist, so this
    cannot expose API routes or files outside the frontend output.
    """

    if path in {"", "/", "/index.html", "/favicon.ico"}:
        return True
    if path.startswith("/assets/"):
        return True
    return _resolve_frontend_file(path) is not None


def _is_documentation_path(path: str) -> bool:
    """Return whether a path serves generated API documentation.

    Note: In production, docs/openapi are disabled by default (FastAPI
    docs_url=None). This function still exists for defense-in-depth and
    to handle the explicit LITASSIST_ENABLE_DOCS=1 debug case.
    """

    return path in {"/openapi.json", "/docs", "/docs/", "/redoc", "/redoc/"} or path.startswith("/docs/")


def _route_path_format(route: Any) -> str:
    """Return the route pattern used to separate backend routes from SPA routes."""

    return str(getattr(route, "path_format", getattr(route, "path", "")) or "")


def _is_capability_protected_route(route: Any) -> bool:
    """Return whether a registered route represents backend behavior."""

    path_format = _route_path_format(route)
    if not path_format or path_format in {"/", "/{full_path}", "/{full_path:path}"}:
        return False
    if path_format.startswith("/assets") or path_format == "/health":
        return False
    if _is_documentation_path(path_format):
        return False
    return True


def _matches_capability_protected_route(request: Request) -> bool:
    """Return whether the incoming request maps to a real backend route.

    Why:
        Capability checks must fail closed for mounted APIs without relying on
        a manually synchronized prefix list, while still allowing React Router
        deep links to fall through to the frontend shell.
    """

    for route in request.app.routes:
        if not _is_capability_protected_route(route):
            continue
        match_fn = getattr(route, "matches", None)
        if match_fn is None:
            continue
        try:
            match, _ = match_fn(request.scope)
        except Exception:
            continue
        if match in {Match.FULL, Match.PARTIAL}:
            return True
    return False


def _is_frontend_navigation_request(request: Request) -> bool:
    """Return true for browser deep-link navigations served by the SPA shell."""

    if request.method.upper() not in {"GET", "HEAD"}:
        return False
    return "text/html" in request.headers.get("accept", "").lower()


def _is_capability_exempt_request(request: Request) -> bool:
    """Return true for local routes intentionally reachable without a token."""

    if request.method.upper() == "OPTIONS":
        return True
    path = request.url.path
    if path == "/health" or _is_frontend_static_path(path) or _is_documentation_path(path):
        return True
    if _matches_capability_protected_route(request):
        return False
    return _is_frontend_navigation_request(request)


def _capability_error_response() -> JSONResponse:
    """Return a structured 403 without revealing capability material."""

    return JSONResponse(
        status_code=403,
        content=ErrorResponse(
            error=ErrorDetail(
                code="LOCAL_API_CAPABILITY_REQUIRED",
                message="缺少本地 API capability token",
            )
        ).model_dump(),
    )


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

@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Audit fix 2026-05-19 (S4): three routers share the /api/discussion prefix
    # (discussion_router, discussion_advanced_router, model_config_router's
    # inner discussion_router). Today their paths don't overlap, but FastAPI
    # silently lets a later registration shadow an earlier one — making future
    # conflicts hard to debug. This startup dump prints every registered route
    # once at boot so a duplicate (path, method) pair is visible in logs.
    if os.environ.get("LITASSIST_DISABLE_ROUTE_DUMP") != "1":
        seen: dict[tuple[str, str], int] = {}
        for route in app.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if not path or not methods:
                continue
            for method in sorted(methods):
                key = (method, path)
                seen[key] = seen.get(key, 0) + 1
        duplicates = [(m, p, n) for (m, p), n in seen.items() if n > 1]
        if duplicates:
            for method, path, count in duplicates:
                print(f"[route-audit] DUPLICATE ({count}x) {method} {path}")
        else:
            print(f"[route-audit] {len(seen)} unique (method, path) routes; no duplicates")

    # 0.1.8.1 port-bridge: write the live port to a well-known file so the
    # dev frontend's vite proxy can target it even when the user passes
    # --port <other> or start_desktop.py picked a free port. start_desktop
    # writes the file before uvicorn.run; this hook covers the bare
    # `uvicorn ... --port N` case by parsing sys.argv. Best-effort; never
    # fails startup.
    try:
        _write_api_port_from_argv()
    except Exception as _port_exc:
        logger.warning("api_port_file write skipped: %s", _port_exc)

    if _local_api_capability_auth_enabled():
        try:
            _write_local_api_capability_file()
        except OSError as _capability_exc:
            logger.warning("api_capability_file write skipped: %s", _capability_exc)
        else:
            try:
                refresh_desktop_runtime_descriptor(
                    ready=True,
                    capability_file=str(_LOCAL_API_CAPABILITY_FILE),
                    process_kind="desktop",
                )
            except Exception as _descriptor_exc:
                logger.warning("desktop_runtime_descriptor refresh skipped: %s", _descriptor_exc)

    # Security: verify keyring backend availability in frozen builds
    import sys
    if getattr(sys, "frozen", False):
        try:
            import keyring
            backend = keyring.get_keyring()
            backend_name = f"{type(backend).__module__}.{type(backend).__name__}".lower()
            if "fail" in backend_name or "null" in backend_name:
                logger.warning(
                    "冻结应用凭证后端不可用（keyring 后端为 %s），凭证功能受限。",
                    backend_name
                )
        except Exception as _keyring_exc:
            logger.warning(
                "冻结应用凭证后端检测失败：%s。凭证功能可能受限。",
                _keyring_exc
            )

    from evolution.scheduler import get_curator_scheduler
    curator_scheduler = get_curator_scheduler()
    curator_scheduler.start()

    try:
        yield
    finally:
        await curator_scheduler.stop()
        try:
            _api_port_file = api_port_file_path()
            if _api_port_file.exists():
                _api_port_file.unlink()
        except OSError:
            pass
        _delete_local_api_capability_file()
        try:
            delete_desktop_runtime_descriptor()
        except Exception:
            pass


def _desktop_runtime_port_for_current_process() -> int | None:
    """Return the embedded desktop port when this process owns the descriptor.

    Why:
        start_desktop.py writes the chosen free port before uvicorn's lifespan
        starts. In the embedded thread, sys.argv is still start_desktop.py's
        argv, so parsing argv would fall back to uvicorn's default 8000 and
        overwrite the real desktop port bridge.
    """

    target = desktop_runtime_file_path()
    if not target.is_file():
        return None
    try:
        import json

        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        pid = int(payload.get("pid") or 0)
        port = int(payload.get("port") or 0)
    except (TypeError, ValueError):
        return None
    if pid != os.getpid() or port <= 0 or port > 65535:
        return None
    return port


def _write_api_port_from_argv() -> None:
    """Persist the live API port for Vite proxy and local attach clients."""
    desktop_port = _desktop_runtime_port_for_current_process()
    if desktop_port is not None:
        write_api_port_file(desktop_port)
        return

    port = 8000  # uvicorn default
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--port" and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
                break
            except ValueError:
                pass
        elif arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
                break
            except ValueError:
                pass
    write_api_port_file(port)


def write_api_port_file(port: int) -> None:
    """Atomic write of the api port file (also imported by start_desktop)."""
    import json
    import tempfile
    from datetime import datetime, timezone
    target = api_port_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "port": int(port),
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(target.parent),
        prefix=target.name + ".", suffix=".tmp", delete=False,
    ) as fh:
        json.dump(payload, fh)
        tmp = Path(fh.name)
    os.replace(tmp, target)


app = FastAPI(
    title="Scholar AI API",
    description="学术研究智能体 — 论文分析、知识管理与智能写作辅助平台",
    version="1.3.0",
    generate_unique_id_function=_stable_operation_id,
    openapi_tags=OPENAPI_TAGS,
    separate_input_output_schemas=False,
    lifespan=_lifespan,
    # Security: Disable OpenAPI/Docs in production unless explicitly enabled
    docs_url="/docs" if os.environ.get("LITASSIST_ENABLE_DOCS") == "1" else None,
    redoc_url="/redoc" if os.environ.get("LITASSIST_ENABLE_DOCS") == "1" else None,
    openapi_url="/openapi.json" if os.environ.get("LITASSIST_ENABLE_DOCS") == "1" else None,
)
_allowed_origins = _get_allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials="*" not in _allowed_origins,
    allow_methods=["*"],
    allow_headers=["Content-Type", "Authorization", "X-Request-Id", "X-LitAssist-Pdf-Stream", LOCAL_API_CAPABILITY_HEADER],
)


# ---------------------------------------------------------------------------
# Global Request Tracing Middleware (learned from open-webui X-Process-Time)
# ---------------------------------------------------------------------------

@app.middleware("http")
async def local_api_capability_middleware(request: Request, call_next):
    """Require a process-local token for backend API routes.

    Why:
        The app is local-first, but browser pages and same-user processes can
        still drive localhost APIs. This boundary grants capability only to the
        backend-served frontend shell or the trusted Vite proxy.
    """

    if (
        _local_api_capability_auth_enabled()
        and not _is_capability_exempt_request(request)
        and not _has_valid_local_api_capability(request)
    ):
        logger.warning(
            "local_api_capability_missing: method=%s path=%s origin=%s",
            request.method,
            request.url.path,
            request.headers.get("origin", ""),
        )
        return _capability_error_response()
    return await call_next(request)


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
    trace_id = getattr(request.state, "trace_id", None)
    logger.warning(
        "422 validation_error trace=%s %s %s field=%s msg=%s",
        trace_id, request.method, request.url.path, field, first.get("msg", ""),
    )
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.VALIDATION_ERROR,
                message=first.get("msg", "请求参数验证失败"),
                field=field,
                trace_id=trace_id,
            )
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Wrap FastAPI HTTPException into unified ErrorResponse."""
    code_map = {
        400: ErrorCode.BAD_REQUEST,
        403: ErrorCode.BAD_REQUEST,
        404: ErrorCode.NOT_FOUND,
        422: ErrorCode.VALIDATION_ERROR,
        500: ErrorCode.INTERNAL_ERROR,
        502: ErrorCode.LLM_CONNECTION_ERROR,
    }
    trace_id = getattr(request.state, "trace_id", None)
    # 4xx logged at WARNING so operators can grep PDF-load / not-found
    # failures from the on-disk log; 5xx escalated to ERROR.
    log_method = logger.error if exc.status_code >= 500 else logger.warning
    log_method(
        "%d http_exception trace=%s %s %s detail=%s",
        exc.status_code, trace_id, request.method, request.url.path, exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorDetail(
                code=code_map.get(exc.status_code, ErrorCode.INTERNAL_ERROR),
                message=str(exc.detail),
                trace_id=trace_id,
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


# ---------------------------------------------------------------------------
# Client-side error sink — forwards uncaught frontend errors to backend.log
# ---------------------------------------------------------------------------

_client_error_logger = logging.getLogger("ClientError")


@app.post("/api/client-error", tags=["System"])
async def report_client_error(request: Request) -> dict[str, Any]:
    """Sink for frontend ErrorBoundary + window.onerror + unhandledrejection.

    Stays loose-typed so the browser can ship whatever it has; we cap field
    sizes server-side so a runaway stack cannot bloat the log.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    def _clip(value: Any, limit: int) -> str:
        text = "" if value is None else str(value)
        return text if len(text) <= limit else text[:limit] + f"…(+{len(text) - limit} chars)"

    component = _clip(payload.get("component"), 120)
    kind = _clip(payload.get("kind"), 40) or "render"
    message = _clip(payload.get("message"), 1000)
    stack = _clip(payload.get("stack"), 4000)
    url = _clip(payload.get("url"), 500)
    ua = _clip(payload.get("userAgent"), 300)
    trace_id = getattr(request.state, "trace_id", None)

    _client_error_logger.warning(
        "client_error trace=%s kind=%s component=%s url=%s message=%s stack=%s ua=%s",
        trace_id, kind, component, url, message, stack, ua,
    )
    return {"ok": True, "trace_id": trace_id}

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
    "actions",
    "agent",
    "api",
    "autopilot",
    "capabilities",
    "chat",
    "evolution",
    "inspiration",
    "llm",
    "memory",
    "pipeline",
    "recovery",
    "resources",
    "run_action",
    "runtime",
    "sampling",
    "skill_packs",
    "skills",
    "transform_result",
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


def _frontend_index_headers() -> dict[str, str]:
    """Return cache-control headers for the SPA shell."""

    return {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


def _frontend_csp_header(nonce: str) -> str:
    """Return a CSP for the local SPA shell.

    Args:
        nonce: Per-response script nonce injected into the inline bootstrap.

    Returns:
        A Content-Security-Policy header value that blocks third-party script
        and font loads while preserving localhost API/WebSocket development.
    """

    safe_nonce = str(nonce or "").strip()
    if not safe_nonce:
        raise ValueError("nonce must be non-empty")
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{safe_nonce}'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*; "
        "worker-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )


def _render_frontend_index_response() -> HTMLResponse:
    """Return the SPA shell with a process-local API capability bootstrap."""

    if not FRONTEND_INDEX_FILE.is_file():
        raise HTTPException(status_code=404, detail="Frontend build not found")
    html = FRONTEND_INDEX_FILE.read_text(encoding="utf-8")
    nonce = secrets.token_urlsafe(16)
    if _local_api_capability_auth_enabled():
        import json
        bootstrap = (
            f'<script nonce="{nonce}">'
            "window.__LITASSIST_API_CAPABILITY__="
            + json.dumps(
                {
                    "header": LOCAL_API_CAPABILITY_HEADER,
                    "token": get_local_api_capability_token(),
                },
                ensure_ascii=False,
            )
            + ";</script>"
        )
        if "</head>" in html:
            html = html.replace("</head>", bootstrap + "</head>", 1)
        else:
            html = bootstrap + html

    # Inject nonce into theme-boot.js script tag for CSP compliance
    html = html.replace('<script src="/theme-boot.js"></script>',
                       f'<script src="/theme-boot.js" nonce="{nonce}"></script>')

    headers = _frontend_index_headers()
    headers["Content-Security-Policy"] = _frontend_csp_header(nonce)
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Referrer-Policy"] = "no-referrer"
    return HTMLResponse(content=html, headers=headers)

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
            "memory": ["/memory/status", "/memory/search", "/api/memory_palace/search"],
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
from routers.memory_router import compat_router as memory_compat_router
from routers.memory_router import router as memory_router
# NOTE (2026-05-12): `from routers.semantic_causal_router import router as semantic_causal_router`
# removed — the referenced module was never committed (lived only as untracked
# working-tree file; moved to stash@{?: integration-working-tree-hold-20260512}
# during alpha-prep). FastAPI include_router() requires the module to exist
# (https://fastapi.tiangolo.com/tutorial/bigger-applications/), and importing a
# non-existent submodule raises ModuleNotFoundError
# (https://docs.python.org/3/reference/import.html). The semantic-causal feature
# is intentionally out of alpha scope; restore this import together with the
# router file in a future feature commit.
from routers.runtime_router import router as runtime_router
from routers.recovery_router import router as recovery_router
from recovery_autopilot_router import router as autopilot_router
from routers.inspiration_router import router as inspiration_router
from routers.agent_router import router as agent_router
from routers.chat_router import router as chat_router
from routers.intelligent_chat_router import router as intelligent_chat_router
from routers.rerank_config_router import router as rerank_config_router
from routers.diagnostics_router import router as diagnostics_router
from routers.model_config_router import router as model_config_router
from routers.llm_cost_router import router as llm_cost_router
from routers.sampling_router import router as sampling_router
from routers.volume_router import router as volume_router
from routers.wiki_router import router as wiki_router
from routers.export_router import router as export_router
from routers.annotation_router import router as annotation_router
from routers.discussion_router import router as discussion_router
from routers.credentials_router import router as credentials_router
from routers.settings_router import router as settings_router
from routers.csl_styles_router import router as csl_styles_router
from routers.discussion_advanced_router import router as discussion_advanced_router
from routers.mcp_router import router as mcp_router
from routers.mcp_installer_router import router as mcp_installer_router
from routers.knowledge_router import router as knowledge_router
from routers.graph_router import kg_router as kg_graph_router
from routers.graph_router import router as graph_router
from routers.evolution_router import router as evolution_router
from routers.feature_flags_router import router as feature_flags_router
from routers.pdf_backend_router import router as pdf_backend_router
from routers.writing_router import router as writing_router
from routers.evidence_router import router as evidence_router
from routers.linter_router import router as linter_router
from routers.agent_workspace_router import router as agent_workspace_router
from routers.health_check_router import router as health_check_router
from routers.zotero_health_router import router as zotero_health_router
from routers.agent_bridge_router import router as agent_bridge_router


def _initialize_mcp_installer_runtime() -> None:
    """Wire local MCP package installation to shared runtime stores.

    User-filled MCP configs, credential material, and installed-state records
    remain in ignored runtime storage. The installer persists credential
    references, not sensitive plaintext values.
    """
    from credential_bindings import get_credential_binding_index
    from mcp_runtime.scan_registry import get_scan_registry
    from mcp_runtime.template_installer import (
        McpTemplateInstaller,
        set_template_installer,
    )
    from project_paths import runtime_state_path
    from routers.credentials_router import get_credential_store
    from routers.mcp_router import get_mcp_server_store, get_mcp_tool_catalog

    install_root = runtime_state_path("mcp_installs")
    install_root.mkdir(parents=True, exist_ok=True)
    set_template_installer(
        McpTemplateInstaller(
            server_store=get_mcp_server_store(),
            scan_registry=get_scan_registry(),
            credential_store=get_credential_store(),
            tool_catalog=get_mcp_tool_catalog(),
            binding_index=get_credential_binding_index(),
            install_root=install_root,
        )
    )


_initialize_mcp_installer_runtime()

app.include_router(pipeline_router)
app.include_router(skills_router)
app.include_router(runtime_router)
app.include_router(resources_router)
app.include_router(memory_router)
app.include_router(memory_compat_router)
# NOTE (2026-05-12): app.include_router(semantic_causal_router) removed; see
# matching note above the router imports for context.
app.include_router(recovery_router)
app.include_router(autopilot_router)
app.include_router(inspiration_router)
app.include_router(agent_router)
app.include_router(chat_router)
app.include_router(intelligent_chat_router)
app.include_router(rerank_config_router)
app.include_router(diagnostics_router)
app.include_router(model_config_router)
app.include_router(llm_cost_router)
app.include_router(sampling_router)
app.include_router(volume_router)
app.include_router(wiki_router)
app.include_router(export_router)
app.include_router(annotation_router)
app.include_router(discussion_router)
app.include_router(credentials_router)
app.include_router(settings_router)
app.include_router(csl_styles_router)
app.include_router(discussion_advanced_router)
app.include_router(mcp_router)
app.include_router(mcp_installer_router)
app.include_router(knowledge_router)
app.include_router(graph_router)
app.include_router(kg_graph_router)
app.include_router(evolution_router)
app.include_router(feature_flags_router)
app.include_router(pdf_backend_router)
app.include_router(writing_router)
app.include_router(evidence_router)
app.include_router(linter_router)
app.include_router(agent_workspace_router)
app.include_router(health_check_router)
app.include_router(zotero_health_router)
app.include_router(agent_bridge_router)


if FRONTEND_ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")


@app.get("/openapi.json", include_in_schema=False)
async def serve_openapi_schema_when_enabled() -> JSONResponse:
    """Return OpenAPI only for explicit debug/contract-test sessions."""

    if os.environ.get("LITASSIST_ENABLE_DOCS") != "1":
        raise HTTPException(status_code=404, detail="Route not found: /openapi.json")
    return JSONResponse(app.openapi())


@app.get("/", include_in_schema=False)
async def serve_frontend_root():
    return _render_frontend_index_response()


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
        return _render_frontend_index_response()

    raise HTTPException(status_code=404, detail="Frontend build not found")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(app, host="127.0.0.1", port=port)
