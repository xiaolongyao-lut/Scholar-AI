# -*- coding: utf-8 -*-
"""PDF parser backend status — A16a 状态探测 + 安装指引 endpoint.

Plan: docs/plans/active/2026-06-11-marker-pdf-rag-pipeline-plan.md
OPEN_THREADS A16a:Settings UI 需要知道:
  - marker-pdf 包是否已安装 + 版本
  - 当前活跃 backend(pymupdf / marker)+ 选中来源(env / feature flag / default)
  - 安装命令引导(`pip install marker-pdf`)

Frontend reads ``/api/pdf-backend/status`` to render the "PDF 解析后端"
card in Settings → 实验性功能 section.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os

from fastapi import APIRouter
from pydantic import BaseModel

from pdf_backends import ENV_VAR, _normalize_env_choice
from feature_flags import is_enabled


router = APIRouter(prefix="/api/pdf-backend", tags=["PDF Backend"])


# Stable package name shipped on PyPI. Renaming requires an OPEN_THREADS entry.
_MARKER_PKG = "marker-pdf"
_MARKER_IMPORT_PROBE = "marker.converters.pdf"


class PDFBackendStatus(BaseModel):
    """Status payload consumed by Settings frontend."""

    active_backend: str  # "pymupdf" | "marker"
    active_source: str   # "env" | "feature_flag" | "default"
    env_var_name: str
    env_var_value: str | None  # raw env value or None
    feature_flag_name: str  # "pdf_parser_marker"
    feature_flag_enabled: bool
    marker_installed: bool
    marker_version: str | None
    marker_install_hint: str


def _resolve_active_backend() -> tuple[str, str]:
    """Mirror get_pdf_backend's resolution + return (backend_name, source)."""
    raw_env = os.environ.get(ENV_VAR)
    if raw_env is not None and raw_env.strip():
        # env var fully decides backend(even when its value resolves to
        # PyMuPDF), mirroring get_pdf_backend's env-priority guarantee.
        choice = _normalize_env_choice(raw_env)
        if choice == "marker":
            return "marker", "env"
        return "pymupdf", "env"
    if is_enabled("pdf_parser_marker"):
        return "marker", "feature_flag"
    return "pymupdf", "default"


def _probe_marker_installed() -> tuple[bool, str | None]:
    """Return (installed, version_string).

    Two-pass check:
      1. ``importlib.metadata.version(_MARKER_PKG)`` — reliable for pip installs
      2. importable probe — catches edge case where metadata is missing but
         module is on the path

    Either passing → installed=True. Missing import is the deciding signal:
    if marker.converters.pdf cannot be imported the backend cannot run.
    """
    version: str | None = None
    try:
        version = importlib.metadata.version(_MARKER_PKG)
    except importlib.metadata.PackageNotFoundError:
        version = None
    try:
        importlib.import_module(_MARKER_IMPORT_PROBE)
        importable = True
    except ImportError:
        importable = False
    installed = importable
    return installed, version


@router.get("/status", response_model=PDFBackendStatus)
def get_pdf_backend_status() -> PDFBackendStatus:
    """Return the current PDF backend wiring + marker installability."""
    backend, source = _resolve_active_backend()
    installed, version = _probe_marker_installed()
    return PDFBackendStatus(
        active_backend=backend,
        active_source=source,
        env_var_name=ENV_VAR,
        env_var_value=os.environ.get(ENV_VAR),
        feature_flag_name="pdf_parser_marker",
        feature_flag_enabled=is_enabled("pdf_parser_marker"),
        marker_installed=installed,
        marker_version=version,
        marker_install_hint=(
            "pip install marker-pdf"
            "  # ~2GB(含 torch / surya-ocr 等),首次解析每篇 PDF 约 5-15 分钟"
        ),
    )
