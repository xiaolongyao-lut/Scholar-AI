from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from inspiration_engine import InspirationSpark
from python_adapter_server import app
from routers import inspiration_router


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, response: _FakeResponse | None = None, error: Exception | None = None, capture: dict | None = None, **kwargs):
        self._response = response
        self._error = error
        self._capture = capture if capture is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, *, json: dict, headers: dict):
        self._capture["url"] = url
        self._capture["json"] = json
        self._capture["headers"] = headers
        if self._error is not None:
            raise self._error
        return self._response


class _FakeEngine:
    def __init__(self, sparks: list[InspirationSpark]):
        self._sparks = sparks
        self.generate_sparks_calls: list[tuple[str, int]] = []
        self.generate_sparks_from_chunks_calls: list[tuple[str, int]] = []

    def generate_sparks(self, query: str, limit: int = 10):
        self.generate_sparks_calls.append((query, limit))
        return list(self._sparks)

    def generate_sparks_from_chunks(self, query: str, chunks: list[dict], limit: int = 10):
        self.generate_sparks_from_chunks_calls.append((query, limit))
        return list(self._sparks)


def _make_spark(content: str) -> InspirationSpark:
    return InspirationSpark(
        id=content.replace(" ", "_"),
        content=content,
        spark_type="memory_association",
        source_papers=["Local paper"],
        confidence=0.61,
    )


def _llm_payload() -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "sparks": [
                                {
                                    "content": "LLM spark",
                                    "spark_type": "analogy",
                                    "source_papers": ["LLM paper"],
                                    "confidence": 0.91,
                                    "related_point_ids": [],
                                    "actionable": True,
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
        "model": "deepseek-chat",
    }


def test_generate_inspirations_prefers_llm_sampling_and_logs_success(monkeypatch) -> None:
    engine = _FakeEngine([_make_spark("local spark should not win")])
    capture: dict[str, object] = {}
    log_calls: list[dict] = []

    monkeypatch.setattr(inspiration_router, "_get_engine", lambda: engine)
    monkeypatch.setattr(inspiration_router, "load_user_sampling", lambda: {"inspiration": {"top_p": 0.77, "top_k": 64}}, raising=False)
    monkeypatch.setattr(
        inspiration_router,
        "httpx",
        type(
            "_HTTPXModule",
            (),
            {
                "AsyncClient": lambda **kwargs: _FakeAsyncClient(
                    response=_FakeResponse(_llm_payload()),
                    capture=capture,
                )
            },
        ),
        raising=False,
    )
    monkeypatch.setattr(inspiration_router, "log_llm_call", lambda **kwargs: log_calls.append(kwargs), raising=False)

    client = TestClient(app)
    response = client.post(
        "/inspiration/generate",
        json={
            "query": "laser welding pores",
            "limit": 1,
            "llm": {
                "provider": "DeepSeek",
                "api_key": "test-key",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
                "temperature": 1.9,
                "top_p": 0.1,
                "top_k": 1,
                "max_tokens": 9999,
                "system_prompt": "",
            },
            "sampling": {"temperature": 0.55, "max_tokens": 512},
        },
    )

    assert response.status_code == 200
    assert response.json()["sparks"][0]["content"] == "LLM spark"
    assert engine.generate_sparks_calls == []
    assert capture["json"]["temperature"] == 0.55
    assert capture["json"]["top_p"] == 0.77
    assert capture["json"]["max_tokens"] == 512
    assert capture["json"]["extra_body"] == {"top_k": 64}
    assert len(log_calls) == 1
    assert log_calls[0]["task"] == "inspiration"
    assert log_calls[0]["status"] == "ok"
    assert log_calls[0]["prompt_tokens"] == 21
    assert log_calls[0]["completion_tokens"] == 9
    assert log_calls[0]["cache_status"] == "miss"
    assert log_calls[0]["decision"] == "invoke"


def test_generate_inspirations_falls_back_to_local_engine_and_logs_error(monkeypatch) -> None:
    engine = _FakeEngine([_make_spark("local fallback spark")])
    log_calls: list[dict] = []

    monkeypatch.setattr(inspiration_router, "_get_engine", lambda: engine)
    monkeypatch.setattr(inspiration_router, "load_user_sampling", lambda: {}, raising=False)
    monkeypatch.setattr(
        inspiration_router,
        "httpx",
        type(
            "_HTTPXModule",
            (),
            {
                "RequestError": httpx.RequestError,
                "AsyncClient": lambda **kwargs: _FakeAsyncClient(
                    error=httpx.RequestError("vendor down"),
                )
            },
        ),
        raising=False,
    )
    monkeypatch.setattr(inspiration_router, "log_llm_call", lambda **kwargs: log_calls.append(kwargs), raising=False)

    client = TestClient(app)
    response = client.post(
        "/inspiration/generate",
        json={
            "query": "laser welding pores",
            "limit": 1,
            "llm": {
                "provider": "DeepSeek",
                "api_key": "test-key",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
                "temperature": 0.2,
                "top_p": 0.2,
                "top_k": 2,
                "max_tokens": 64,
                "system_prompt": "",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["sparks"][0]["content"] == "local fallback spark"
    assert engine.generate_sparks_calls == [("laser welding pores", 1)]
    assert len(log_calls) == 1
    assert log_calls[0]["task"] == "inspiration"
    assert log_calls[0]["status"] == "error"
    assert log_calls[0]["prompt_tokens"] == 0
    assert log_calls[0]["completion_tokens"] == 0
    assert log_calls[0]["cache_status"] == "miss"
    assert log_calls[0]["decision"] == "invoke"
