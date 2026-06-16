# -*- coding: utf-8 -*-
"""Tests for the core PDF backend status endpoint."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CORE = str(Path(__file__).resolve().parents[1] / "literature_assistant" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from pdf_backends import ENV_VAR, get_pdf_backend  # noqa: E402
from routers.pdf_backend_router import (  # noqa: E402
    _resolve_active_backend,
    get_pdf_backend_status,
)


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)


def test_default_backend_is_pymupdf() -> None:
    backend, source = _resolve_active_backend()
    assert backend == "pymupdf"
    assert source == "default"
    assert get_pdf_backend().name == "pymupdf"


@pytest.mark.parametrize("raw_value", ["marker", "pymupdf", "auto", "unknown"])
def test_env_var_no_longer_selects_external_backend(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
) -> None:
    monkeypatch.setenv(ENV_VAR, raw_value)
    backend, source = _resolve_active_backend()
    assert backend == "pymupdf"
    assert source == "env"
    assert get_pdf_backend().name == "pymupdf"


def test_status_payload_shape() -> None:
    payload = get_pdf_backend_status()
    assert payload.active_backend == "pymupdf"
    assert payload.active_source == "default"
    assert payload.env_var_name == ENV_VAR
    assert payload.env_var_value is None
    assert payload.external_backends_supported is False
    assert "optional local providers" in payload.install_hint


def test_status_reports_env_var_value_without_changing_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_VAR, "marker")
    payload = get_pdf_backend_status()
    assert payload.env_var_value == "marker"
    assert payload.active_backend == "pymupdf"
    assert payload.active_source == "env"
