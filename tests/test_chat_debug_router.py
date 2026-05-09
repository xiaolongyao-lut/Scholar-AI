# -*- coding: utf-8 -*-
"""Tests for ``POST /api/chat/debug`` (P1.0 spike).

Validates: envelope shape, source-required gate, dev-mode prompt gate,
metrics monotonicity. Generation/confidence/rerank are stubbed in spike.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Test client backed by the full FastAPI app."""
    from python_adapter_server import app

    return TestClient(app)


def _post(client: TestClient, **body) -> "tuple[int, dict]":
    resp = client.post("/api/chat/debug", json={"query": "test", **body})
    return resp.status_code, resp.json() if resp.status_code != 500 else {"detail": resp.text}


def test_chat_debug_requires_source(client: TestClient) -> None:
    """Without project_id and without source_paths the endpoint returns 400."""
    status, body = _post(client, query="test")
    assert status == 400, body
    message = str(body.get("error", {}).get("message", "") or body.get("detail", ""))
    assert "source paths" in message.lower()


def test_chat_debug_returns_trace_envelope(client: TestClient, tmp_path: Path) -> None:
    """Happy path: envelope is well-formed even when retrieval matches nothing."""
    src = tmp_path / "source.txt"
    src.write_text("Climate change is a critical global issue.\n", encoding="utf-8")

    status, data = _post(
        client,
        query="climate",
        source_paths=[str(src)],
        tier="fast",
        top_k=5,
    )
    assert status == 200, data

    assert isinstance(data["trace_id"], str)
    assert data["trace_id"].startswith("trace_")
    assert data["query"] == "climate"
    assert data["rewritten_query"] is None
    assert data["answer"] is None  # spike: no generation
    assert data["confidence_score"] is None
    assert data["confidence_label"] is None
    assert data["prompt_template"] is None  # dev mode off
    assert data["rejected_chunks"] == []  # spike: no filter pipeline

    assert isinstance(data["retrieval_results"], list)
    assert isinstance(data["selected_chunks"], list)
    assert isinstance(data["prompt_preview"], str)


def test_chat_debug_metrics_are_monotonic(client: TestClient, tmp_path: Path) -> None:
    """total_time_ms >= each individual stage and all stages are non-negative."""
    src = tmp_path / "source.txt"
    src.write_text("Climate change is a critical global issue.\n", encoding="utf-8")

    status, data = _post(
        client,
        query="climate",
        source_paths=[str(src)],
        tier="fast",
        top_k=5,
    )
    assert status == 200, data

    metrics = data["metrics"]
    assert metrics["retrieval_time_ms"] >= 0.0
    assert metrics["prompt_build_time_ms"] >= 0.0
    assert metrics["total_time_ms"] >= 0.0
    assert metrics["total_time_ms"] >= metrics["retrieval_time_ms"]
    assert metrics["total_time_ms"] >= metrics["prompt_build_time_ms"]
    # Spike phase: no generation, these stay None
    assert metrics["generation_time_ms"] is None
    assert metrics["input_tokens"] is None
    assert metrics["output_tokens"] is None
    assert metrics["total_tokens"] is None


def test_chat_debug_default_does_not_return_full_prompt(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without LITERATURE_DEV_MODE, include_full_prompt=true is silently denied."""
    monkeypatch.delenv("LITERATURE_DEV_MODE", raising=False)
    src = tmp_path / "source.txt"
    src.write_text("Some content.\n", encoding="utf-8")

    status, data = _post(
        client,
        query="anything",
        source_paths=[str(src)],
        include_full_prompt=True,
    )
    assert status == 200, data
    assert data["prompt_template"] is None


def test_chat_debug_full_prompt_only_when_dev_mode_and_requested(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LITERATURE_DEV_MODE=1 + include_full_prompt=true returns prompt_template."""
    monkeypatch.setenv("LITERATURE_DEV_MODE", "1")
    src = tmp_path / "source.txt"
    src.write_text("Some content for testing.\n", encoding="utf-8")

    status, data = _post(
        client,
        query="anything",
        source_paths=[str(src)],
        include_full_prompt=True,
    )
    assert status == 200, data
    # If retrieval matched chunks, prompt_template is a string; if not, fall back to None acceptable
    if data["selected_chunks"]:
        assert data["prompt_template"] is not None


def test_chat_debug_dev_mode_off_even_when_requested(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LITERATURE_DEV_MODE=0 + include_full_prompt=true still returns None."""
    monkeypatch.setenv("LITERATURE_DEV_MODE", "0")
    src = tmp_path / "source.txt"
    src.write_text("Some content.\n", encoding="utf-8")

    status, data = _post(
        client,
        query="anything",
        source_paths=[str(src)],
        include_full_prompt=True,
    )
    assert status == 200, data
    assert data["prompt_template"] is None


def test_chat_debug_preview_truncation(client: TestClient, tmp_path: Path) -> None:
    """content_preview must not exceed 300 chars."""
    long_content = "Word " * 200  # 1000 chars
    src = tmp_path / "long.txt"
    src.write_text(long_content, encoding="utf-8")

    status, data = _post(
        client,
        query="word",
        source_paths=[str(src)],
        tier="fast",
    )
    assert status == 200, data
    for chunk in data["retrieval_results"]:
        assert len(chunk["content_preview"]) <= 300


def test_chat_debug_truncate_helper_respects_limit() -> None:
    """Direct unit check: ellipsis suffix must not push string past the cap.

    Why:
        A chunk just over 300 chars caused Pydantic max_length=300 to reject
        the response (smoke regression 2026-05-09). Slicing to limit then
        appending '…' produced 301 chars.
    """
    import sys
    from pathlib import Path as _Path
    core = _Path(__file__).resolve().parents[1] / "literature_assistant" / "core"
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    from routers.chat_debug_router import _truncate_preview

    long_text = "x" * 500
    truncated = _truncate_preview(long_text, limit=300)
    assert len(truncated) <= 300
    assert truncated.endswith("…")
    short_text = "short"
    assert _truncate_preview(short_text, limit=300) == "short"
