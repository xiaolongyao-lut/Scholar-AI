"""Tests for the local-rerank status endpoint added so the Settings UI
can render an availability chip.

Pins two things:
1. The endpoint returns a populated payload whose fields match what
   ``local_rerank_adapter.get_status()`` reports.
2. When the adapter module fails to import (e.g. extension stripped),
   the endpoint degrades to a "everything off" payload instead of
   500-ing the Settings page.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_CORE = Path(__file__).resolve().parents[1] / "literature_assistant" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))


def test_local_status_payload_exposes_aggregator_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Endpoint should pass through every key get_status() returns."""
    import local_rerank_adapter
    from routers.rerank_config_router import get_local_rerank_status

    fake = {
        "available": True,
        "disabled": False,
        "weights_present": True,
        "allow_download": False,
        "model_name": "BAAI/bge-reranker-v2-m3",
        "device": "cuda",
        "device_source": "auto_detected",
        "max_length": 512,
        "batch_size": 8,
        "loaded": False,
        "hf_cache_dir": "/fake/path",
    }
    monkeypatch.setattr(local_rerank_adapter, "get_status", lambda: fake)

    result = asyncio.run(get_local_rerank_status())
    dumped = result.model_dump()
    for key, value in fake.items():
        assert dumped[key] == value, f"field {key} not propagated: {dumped[key]!r} vs {value!r}"


def test_local_status_falls_back_when_adapter_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the adapter is missing, return a degraded payload (not 500)."""
    import builtins
    real_import = builtins.__import__

    def _block_adapter(name: str, *args, **kwargs):
        if name == "local_rerank_adapter":
            raise ImportError("simulated: adapter not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_adapter)

    from routers.rerank_config_router import get_local_rerank_status
    result = asyncio.run(get_local_rerank_status())
    assert result.available is False
    assert result.disabled is True
    assert result.weights_present is False
    assert result.model_name == ""


def test_local_status_reports_device_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """When LOCAL_RERANK_DEVICE env is set, get_status flags the source."""
    import importlib
    import local_rerank_adapter
    importlib.reload(local_rerank_adapter)
    monkeypatch.setenv("LOCAL_RERANK_DEVICE", "cpu")
    status = local_rerank_adapter.get_status()
    assert status["device"] == "cpu"
    assert status["device_source"] == "env_override"


def test_local_status_reports_auto_detection_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env var → device_source is 'auto_detected'."""
    import importlib
    import local_rerank_adapter
    importlib.reload(local_rerank_adapter)
    monkeypatch.delenv("LOCAL_RERANK_DEVICE", raising=False)
    status = local_rerank_adapter.get_status()
    assert status["device_source"] == "auto_detected"
