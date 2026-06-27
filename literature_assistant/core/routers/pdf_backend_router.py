# -*- coding: utf-8 -*-
"""PDF parser backend status endpoint."""

from __future__ import annotations

import os
import base64
import binascii
import hashlib
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from pdf_backends import (
    ENV_VAR,
    OcrEngine,
    OcrRuntimeConfig,
    OcrReadinessStatus,
    build_ocr_engine,
    list_ocr_engine_info,
    ocr_engine_next_safe_local_actions,
    public_ocr_status,
    resolve_ocr_runtime_config,
    select_ocr_engine,
    write_ocr_runtime_config,
)
from project_paths import REPO_ROOT, WORKSPACE_ARTIFACTS_ROOT


router = APIRouter(prefix="/api/pdf-backend", tags=["PDF Backend"])
_MAX_OCR_PROBE_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_OCR_PROBE_BASE64_CHARS = 16 * 1024 * 1024
_OCR_PROBE_IMAGE_SUFFIXES = {
    ".bmp",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
_OCR_READINESS_STATUS_VALUES = set(OcrReadinessStatus.__args__)


class PDFBackendStatus(BaseModel):
    """Status payload consumed by Settings frontend."""

    active_backend: str
    active_source: str
    env_var_name: str
    env_var_value: str | None
    external_backends_supported: bool
    install_hint: str
    ocr_policy: str
    ocr_configured_engine: str | None
    ocr_selected_engine: str | None
    ocr_language: str
    ocr_config_source: str
    ocr_warning: str | None


class OcrEnginePublicInfo(BaseModel):
    """Public metadata for one OCR engine."""

    name: str
    display_name: str
    engine_type: Literal["local", "remote"]
    available: bool
    requires_network: bool
    unavailable_reason: str | None = None
    readiness_status: OcrReadinessStatus = "ready"
    readiness_blockers: list[str] = Field(default_factory=list)
    next_safe_local_actions: list[str] = Field(default_factory=list)


class OcrStatusResponse(BaseModel):
    """Current OCR runtime selection and registered engine inventory."""

    policy: Literal["auto", "none", "engine"]
    configured_engine: str | None = None
    selected_engine: str | None = None
    language: str
    source: str
    engine_config: dict[str, Any] = Field(default_factory=dict)
    available_engines: list[OcrEnginePublicInfo] = Field(default_factory=list)
    warning: str | None = None
    next_safe_local_actions: list[str] = Field(default_factory=list)


class OcrEngineSelectionRequest(BaseModel):
    """Request body for local OCR engine selection."""

    policy: Literal["auto", "none", "engine"] = "auto"
    engine: str | None = None
    language: str = "en"
    engine_config: dict[str, Any] = Field(default_factory=dict)


class OcrEngineSelectionResponse(BaseModel):
    """Result of writing OCR runtime selection."""

    saved: bool
    config_path: str
    status: OcrStatusResponse


class OcrHealthRequest(BaseModel):
    """Request body for a lightweight OCR engine readiness probe."""

    engine: str | None = None
    engine_config: dict[str, Any] = Field(default_factory=dict)


class OcrHealthResponse(BaseModel):
    """OCR engine health-check response."""

    ok: bool
    detail: str
    engine: str
    latency_ms: float | None = None
    readiness_status: OcrReadinessStatus = "ready"
    readiness_blockers: list[str] = Field(default_factory=list)
    next_safe_local_actions: list[str] = Field(default_factory=list)


class OcrExecutionProbeRequest(BaseModel):
    """Request body for an explicit OCR execution proof.

    Args:
        confirm_execution: Must be true because OCR may run local heavy
            runtimes or upload page images for remote engines.
        image_base64: Optional PNG/JPEG/etc. payload encoded as base64.
        image_path: Optional local image path under allowed workspace roots.
        engine: Optional engine id. Omitted means use resolved runtime policy.
        engine_config: Engine-specific options; secrets never return.
        language: OCR language tag forwarded to the selected engine.
        preview_chars: Maximum OCR text preview characters returned.
    """

    confirm_execution: bool = False
    image_base64: str | None = None
    image_path: str | None = None
    engine: str | None = None
    engine_config: dict[str, Any] = Field(default_factory=dict)
    language: str = "en"
    preview_chars: int = Field(default=240, ge=0, le=1000)


class OcrExecutionProbeResponse(BaseModel):
    """Bounded proof that one OCR engine executed on one image payload."""

    schema_version: str
    confirmed: bool
    engine: str
    engine_type: Literal["local", "remote"]
    requires_network: bool
    language: str
    input_kind: Literal["image_base64", "image_path"]
    input_bytes: int
    input_sha256: str
    text_length: int
    text_sha256: str
    text_preview: str
    duration_ms: int


class OcrExecutionBlockedResponse(BaseModel):
    """Bounded proof that OCR execution was blocked before provider work."""

    schema_version: Literal["scholar-ai-ocr-execution-blocked/v1"] = (
        "scholar-ai-ocr-execution-blocked/v1"
    )
    confirmed: Literal[False] = False
    status: Literal["blocked"] = "blocked"
    engine: str
    engine_type: Literal["local", "remote"]
    requires_network: bool
    language: str
    input_kind: Literal["image_base64", "image_path"]
    input_bytes: int
    input_sha256: str
    reason: str
    readiness_status: OcrReadinessStatus
    readiness_blockers: list[str] = Field(default_factory=list)
    next_safe_local_actions: list[str] = Field(default_factory=list)


def _sha256_hex(data: bytes) -> str:
    """Return a stable SHA-256 hex digest for evidence receipts."""

    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    return hashlib.sha256(data).hexdigest()


def _normalize_probe_language(value: str) -> str:
    """Return a bounded OCR language string for execution probes."""

    if not isinstance(value, str):
        raise ValueError("language must be a string")
    text = value.strip()
    if not text:
        raise ValueError("language must be non-empty")
    if len(text) > 32:
        raise ValueError("language must be 32 characters or fewer")
    return text


def _path_is_under(path: Path, root: Path) -> bool:
    """Return whether path is contained by root after resolution."""

    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_ocr_probe_path(path: Path) -> bool:
    """Return whether a local image path is inside allowed execution roots."""

    allowed_roots = (
        REPO_ROOT.resolve(),
        WORKSPACE_ARTIFACTS_ROOT.resolve(),
        Path(tempfile.gettempdir()).resolve(),
    )
    return any(_path_is_under(path, root) for root in allowed_roots)


def _resolve_probe_image_path(raw_path: str, *, max_bytes: int) -> tuple[Path, bytes]:
    """Resolve and hash a bounded local OCR probe image path."""

    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("image_path must be non-empty")
    path = Path(raw_path).expanduser().resolve()
    if not _allowed_ocr_probe_path(path):
        raise ValueError("image_path must be under the repository, workspace artifacts, or temp root")
    if path.suffix.lower() not in _OCR_PROBE_IMAGE_SUFFIXES:
        raise ValueError("image_path must point to a supported image file")
    if not path.is_file():
        raise FileNotFoundError(f"OCR image not found: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("OCR image file must be non-empty")
    if size > max_bytes:
        raise ValueError(f"OCR image file must be {max_bytes} bytes or fewer")
    return path, path.read_bytes()


def _decode_probe_image(
    request: OcrExecutionProbeRequest,
) -> tuple[bytes | Path, bytes, Literal["image_base64", "image_path"]]:
    """Return engine input, bytes for hashing, and public input kind."""

    has_base64 = isinstance(request.image_base64, str) and bool(request.image_base64.strip())
    has_path = isinstance(request.image_path, str) and bool(request.image_path.strip())
    if has_base64 == has_path:
        raise ValueError("provide exactly one of image_base64 or image_path")

    if has_base64:
        raw = str(request.image_base64 or "").strip()
        if len(raw) > _MAX_OCR_PROBE_BASE64_CHARS:
            raise ValueError("image_base64 is too large")
        if "," in raw and raw.lower().startswith("data:"):
            raw = raw.split(",", 1)[1].strip()
        try:
            image_bytes = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("image_base64 must contain valid base64 image bytes") from exc
        if not image_bytes:
            raise ValueError("image_base64 must decode to non-empty bytes")
        if len(image_bytes) > _MAX_OCR_PROBE_IMAGE_BYTES:
            raise ValueError(f"image_base64 must decode to {_MAX_OCR_PROBE_IMAGE_BYTES} bytes or fewer")
        return image_bytes, image_bytes, "image_base64"

    path, image_bytes = _resolve_probe_image_path(
        str(request.image_path),
        max_bytes=_MAX_OCR_PROBE_IMAGE_BYTES,
    )
    return path, image_bytes, "image_path"


def _resolve_probe_engine(request: OcrExecutionProbeRequest) -> OcrEngine:
    """Return the selected OCR engine or raise a bounded preflight error."""

    if request.engine is not None and str(request.engine).strip():
        return build_ocr_engine(str(request.engine).strip(), request.engine_config)

    runtime_config = resolve_ocr_runtime_config()
    engine, warning = select_ocr_engine(runtime_config)
    if engine is None:
        raise ValueError(str(warning or "no OCR engine selected"))
    return engine


def _ocr_health_response_payload(engine: OcrEngine, health: Any) -> dict[str, Any]:
    """Return health payload with bounded recovery actions attached."""

    payload = dict(health.as_dict())
    actions = payload.get("next_safe_local_actions")
    if isinstance(actions, list) and actions:
        return payload
    blockers = payload.get("readiness_blockers")
    raw_readiness_status = str(payload.get("readiness_status") or "unavailable")
    readiness_status = cast(
        OcrReadinessStatus,
        raw_readiness_status if raw_readiness_status in _OCR_READINESS_STATUS_VALUES else "unavailable",
    )
    payload["next_safe_local_actions"] = list(
        ocr_engine_next_safe_local_actions(
            engine_name=engine.name,
            engine_type=engine.engine_type,
            requires_network=engine.requires_network,
            readiness_status=readiness_status,
            readiness_blockers=blockers if isinstance(blockers, list) else [],
        )
    )
    return payload


def _ocr_execution_blocked_payload(
    *,
    engine: OcrEngine,
    language: str,
    input_kind: Literal["image_base64", "image_path"],
    image_bytes: bytes,
    reason: str,
) -> dict[str, Any]:
    """Return a non-secret blocked execution receipt for recovery agents."""

    if not reason.strip():
        raise ValueError("reason must be non-empty")
    readiness_status = engine.readiness_status()
    readiness_blockers = list(engine.readiness_blockers())
    return OcrExecutionBlockedResponse(
        engine=engine.name,
        engine_type=engine.engine_type,
        requires_network=engine.requires_network,
        language=language,
        input_kind=input_kind,
        input_bytes=len(image_bytes),
        input_sha256=_sha256_hex(image_bytes),
        reason=reason,
        readiness_status=readiness_status,
        readiness_blockers=readiness_blockers,
        next_safe_local_actions=list(
            ocr_engine_next_safe_local_actions(
                engine_name=engine.name,
                engine_type=engine.engine_type,
                requires_network=engine.requires_network,
                readiness_status=readiness_status,
                readiness_blockers=readiness_blockers,
            )
        ),
    ).model_dump()


def _resolve_active_backend() -> tuple[str, str]:
    """Return the active core backend and why it was selected."""
    raw_env = os.environ.get(ENV_VAR)
    if raw_env is not None and raw_env.strip():
        return "pymupdf", "env"
    return "pymupdf", "default"


@router.get("/status", response_model=PDFBackendStatus)
def get_pdf_backend_status() -> PDFBackendStatus:
    """Return current core PDF backend wiring."""
    backend, source = _resolve_active_backend()
    ocr_status = public_ocr_status()
    return PDFBackendStatus(
        active_backend=backend,
        active_source=source,
        env_var_name=ENV_VAR,
        env_var_value=os.environ.get(ENV_VAR),
        external_backends_supported=True,
        install_hint=(
            "Core PDF parsing uses PyMuPDF. Heavy OCR/parser runtimes should "
            "be installed as optional local providers outside core source."
        ),
        ocr_policy=str(ocr_status["policy"]),
        ocr_configured_engine=ocr_status["configured_engine"],
        ocr_selected_engine=ocr_status["selected_engine"],
        ocr_language=str(ocr_status["language"]),
        ocr_config_source=str(ocr_status["source"]),
        ocr_warning=ocr_status["warning"],
    )


@router.get("/ocr-engines", response_model=list[OcrEnginePublicInfo])
def list_ocr_engines() -> list[OcrEnginePublicInfo]:
    """Return registered OCR engines with availability metadata."""

    return [OcrEnginePublicInfo(**item.as_dict()) for item in list_ocr_engine_info()]


@router.get("/ocr-status", response_model=OcrStatusResponse)
def get_ocr_status() -> OcrStatusResponse:
    """Return the redacted OCR runtime status."""

    return OcrStatusResponse(**public_ocr_status())


@router.post("/ocr-engine", response_model=OcrEngineSelectionResponse)
def select_ocr_engine_endpoint(
    request: OcrEngineSelectionRequest,
) -> OcrEngineSelectionResponse:
    """Persist local OCR policy/engine selection.

    Secrets are accepted only as local runtime config values and are redacted
    from the response.
    """

    try:
        config = OcrRuntimeConfig(
            policy=request.policy,
            engine=request.engine,
            language=request.language,
            source="config",
            engine_config=request.engine_config,
        )
        if request.policy == "engine" and not request.engine:
            raise ValueError("policy 'engine' requires an engine id")
        if request.engine:
            build_ocr_engine(request.engine, request.engine_config)
        path = write_ocr_runtime_config(config)
        resolved = resolve_ocr_runtime_config(config_path=path)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return OcrEngineSelectionResponse(
        saved=True,
        config_path=str(path),
        status=OcrStatusResponse(**public_ocr_status(resolved)),
    )


@router.post("/ocr-health", response_model=OcrHealthResponse)
def check_ocr_engine_health(request: OcrHealthRequest) -> OcrHealthResponse:
    """Run a lightweight readiness probe for one OCR engine."""

    try:
        if request.engine:
            engine = build_ocr_engine(request.engine, request.engine_config)
        else:
            status = public_ocr_status()
            selected = status.get("selected_engine")
            if not isinstance(selected, str) or not selected:
                raise ValueError(str(status.get("warning") or "no OCR engine selected"))
            engine = build_ocr_engine(selected, request.engine_config)
        health = engine.health_check()
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OcrHealthResponse(**_ocr_health_response_payload(engine, health))


@router.post(
    "/ocr-execution-probe",
    response_model=OcrExecutionProbeResponse,
    responses={
        409: {
            "model": OcrExecutionBlockedResponse,
            "description": "OCR execution was blocked before provider work.",
        }
    },
)
def run_ocr_execution_probe(
    request: OcrExecutionProbeRequest,
) -> OcrExecutionProbeResponse | JSONResponse:
    """Run one explicit OCR execution probe and return bounded proof only."""

    started = time.perf_counter()
    if request.confirm_execution is not True:
        raise HTTPException(
            status_code=400,
            detail="confirm_execution=true is required before OCR execution",
        )

    try:
        language = _normalize_probe_language(request.language)
        image_input, image_bytes, input_kind = _decode_probe_image(request)
        engine = _resolve_probe_engine(request)
        unavailable = engine.unavailable_reason()
        if unavailable is not None:
            return JSONResponse(
                status_code=409,
                content=_ocr_execution_blocked_payload(
                    engine=engine,
                    language=language,
                    input_kind=input_kind,
                    image_bytes=image_bytes,
                    reason=unavailable,
                ),
            )
        text = engine.ocr_image(image_input, language=language)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:500]) from exc

    text_value = str(text)
    preview_chars = request.preview_chars
    duration_ms = int((time.perf_counter() - started) * 1000)
    return OcrExecutionProbeResponse(
        schema_version="scholar-ai-ocr-execution-probe/v1",
        confirmed=True,
        engine=engine.name,
        engine_type=engine.engine_type,
        requires_network=engine.requires_network,
        language=language,
        input_kind=input_kind,
        input_bytes=len(image_bytes),
        input_sha256=_sha256_hex(image_bytes),
        text_length=len(text_value),
        text_sha256=_sha256_hex(text_value.encode("utf-8")),
        text_preview=text_value[:preview_chars],
        duration_ms=duration_ms,
    )
