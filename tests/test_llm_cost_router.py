from __future__ import annotations

import importlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import python_adapter_server


def _load_cost_router_module():
    try:
        return importlib.import_module("routers.llm_cost_router")
    except ModuleNotFoundError as exc:  # pragma: no cover - TDD red phase guard
        pytest.fail("routers.llm_cost_router must exist for the /llm/cost endpoints", pytrace=False)


def _patch_log_file(monkeypatch, tmp_path: Path) -> Path:
    llm_cost_router = _load_cost_router_module()
    log_file = tmp_path / "llm_cost.jsonl"
    monkeypatch.setattr(llm_cost_router, "_LOG_FILE", log_file)
    return log_file


def _write_rows(path: Path, *rows: str) -> None:
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_llm_cost_today_aggregates_live_log_with_malformed_line_metadata(tmp_path, monkeypatch) -> None:
    log_file = _patch_log_file(monkeypatch, tmp_path)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _write_rows(
        log_file,
        json.dumps(
            {
                "ts": f"{today}T10:00:00+00:00",
                "model": "qwen-max",
                "task": "chat",
                "prompt_tokens": 4,
                "completion_tokens": 6,
                "total_tokens": 10,
                "cost_usd": 0.12,
                "latency_ms": 10.0,
                "status": "ok",
                "pricing_known": True,
            }
        ),
        "{bad json",
        json.dumps(
            {
                "ts": f"{today}T11:00:00+00:00",
                "model": "qwen-plus",
                "task": "extraction",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
                "latency_ms": 11.0,
                "status": "error",
                "pricing_known": True,
            }
        ),
        json.dumps(
            {
                "ts": f"{yesterday}T09:00:00+00:00",
                "model": "ignored-model",
                "task": "ignored-task",
                "prompt_tokens": 99,
                "completion_tokens": 1,
                "total_tokens": 100,
                "cost_usd": 9.99,
                "latency_ms": 12.0,
                "status": "ok",
                "pricing_known": True,
            }
        ),
    )
    client = TestClient(python_adapter_server.app)

    response = client.get("/llm/cost/today")

    assert response.status_code == 200
    assert response.json() == {
        "date": today,
        "total_calls": 2,
        "total_tokens": 10,
        "total_cost_usd": 0.12,
        "by_task": {
            "chat": {"calls": 1, "total_tokens": 10, "total_cost_usd": 0.12},
            "extraction": {"calls": 1, "total_tokens": 0, "total_cost_usd": 0.0},
        },
        "by_model": {
            "qwen-max": {"calls": 1, "total_tokens": 10, "total_cost_usd": 0.12},
            "qwen-plus": {"calls": 1, "total_tokens": 0, "total_cost_usd": 0.0},
        },
        "meta": {"malformed_lines": 1},
    }


def test_llm_cost_range_aggregates_inclusive_date_window(tmp_path, monkeypatch) -> None:
    log_file = _patch_log_file(monkeypatch, tmp_path)
    _write_rows(
        log_file,
        json.dumps(
            {
                "ts": "2026-04-20T10:00:00+00:00",
                "model": "qwen-max",
                "task": "chat",
                "prompt_tokens": 5,
                "completion_tokens": 5,
                "total_tokens": 10,
                "cost_usd": 0.1,
                "latency_ms": 10.0,
                "status": "ok",
                "pricing_known": True,
            }
        ),
        json.dumps(
            {
                "ts": "2026-04-21T11:00:00+00:00",
                "model": "qwen-max",
                "task": "chat",
                "prompt_tokens": 3,
                "completion_tokens": 4,
                "total_tokens": 7,
                "cost_usd": 0.05,
                "latency_ms": 11.0,
                "status": "ok",
                "pricing_known": True,
            }
        ),
        json.dumps(
            {
                "ts": "2026-04-22T12:00:00+00:00",
                "model": "qwen-plus",
                "task": "rewrite",
                "prompt_tokens": 2,
                "completion_tokens": 8,
                "total_tokens": 10,
                "cost_usd": 0.2,
                "latency_ms": 12.0,
                "status": "ok",
                "pricing_known": True,
            }
        ),
    )
    client = TestClient(python_adapter_server.app)

    response = client.get("/llm/cost/range?start=2026-04-20&end=2026-04-21")

    assert response.status_code == 200
    assert response.json() == {
        "start": "2026-04-20",
        "end": "2026-04-21",
        "total_calls": 2,
        "total_tokens": 17,
        "total_cost_usd": 0.15,
        "by_task": {
            "chat": {"calls": 2, "total_tokens": 17, "total_cost_usd": 0.15},
        },
        "by_model": {
            "qwen-max": {"calls": 2, "total_tokens": 17, "total_cost_usd": 0.15},
        },
        "meta": {"malformed_lines": 0},
    }


def test_llm_cost_range_rejects_inverted_window() -> None:
    client = TestClient(python_adapter_server.app)

    response = client.get("/llm/cost/range?start=2026-04-22&end=2026-04-21")

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "start must be on or before end"


def test_llm_cost_endpoints_return_503_when_log_exceeds_guard(tmp_path, monkeypatch) -> None:
    log_file = _patch_log_file(monkeypatch, tmp_path)
    log_file.write_text("{}", encoding="utf-8")
    llm_cost_router = _load_cost_router_module()
    monkeypatch.setattr(llm_cost_router, "_MAX_LOG_BYTES", 1)
    client = TestClient(python_adapter_server.app)

    response = client.get("/llm/cost/today")

    assert response.status_code == 503
    assert "archive" in response.json()["error"]["message"].lower()


def test_live_app_does_not_spa_fallback_unknown_llm_paths(tmp_path, monkeypatch) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    index_file = dist_dir / "index.html"
    index_file.write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.setattr(python_adapter_server, "FRONTEND_DIST_DIR", dist_dir)
    monkeypatch.setattr(python_adapter_server, "FRONTEND_INDEX_FILE", index_file)
    client = TestClient(python_adapter_server.app)

    response = client.get("/llm/not-a-real-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["message"] == "Route not found: /llm/not-a-real-route"
