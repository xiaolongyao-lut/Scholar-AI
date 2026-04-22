from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llm_defaults import MODEL_MAX_TOKENS, TASK_DEFAULTS
from python_adapter_server import app


def test_sampling_router_get_returns_empty_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = TestClient(app)

    response = client.get("/sampling")

    assert response.status_code == 200
    assert response.json() == {
        "tasks": {},
        "defaults_version": "2026-04-21",
        "task_defaults": TASK_DEFAULTS,
        "model_max_tokens": MODEL_MAX_TOKENS,
    }


def test_sampling_router_put_and_delete_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = TestClient(app)

    put_response = client.put(
        "/sampling",
        json={"tasks": {"chat": {"temperature": 0.25}, "inspiration": {"top_p": 0.88}}},
    )
    assert put_response.status_code == 200
    assert put_response.json() == {"ok": True}

    get_response = client.get("/sampling")
    assert get_response.status_code == 200
    assert get_response.json()["tasks"] == {
        "chat": {"temperature": 0.25},
        "inspiration": {"top_p": 0.88},
    }

    delete_response = client.delete("/sampling/chat")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"ok": True}

    final_get = client.get("/sampling")
    assert final_get.status_code == 200
    assert final_get.json()["tasks"] == {"inspiration": {"top_p": 0.88}}


def test_sampling_router_put_returns_422_for_invalid_payload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = TestClient(app)

    response = client.put("/sampling", json={"tasks": {"chat": {"temperature": 5}}})

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "temperature out of range"
