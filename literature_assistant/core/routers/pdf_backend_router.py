# -*- coding: utf-8 -*-
"""PDF parser backend status endpoint."""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from pdf_backends import ENV_VAR


router = APIRouter(prefix="/api/pdf-backend", tags=["PDF Backend"])


class PDFBackendStatus(BaseModel):
    """Status payload consumed by Settings frontend."""

    active_backend: str
    active_source: str
    env_var_name: str
    env_var_value: str | None
    external_backends_supported: bool
    install_hint: str


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
    return PDFBackendStatus(
        active_backend=backend,
        active_source=source,
        env_var_name=ENV_VAR,
        env_var_value=os.environ.get(ENV_VAR),
        external_backends_supported=False,
        install_hint=(
            "Core PDF parsing uses PyMuPDF. Heavy OCR/parser runtimes should "
            "be installed as optional local providers outside core source."
        ),
    )
