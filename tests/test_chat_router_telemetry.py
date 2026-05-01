from __future__ import annotations

import json

from fastapi.testclient import TestClient

from python_adapter_server import app
from routers import chat_router


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, post_payload: dict | None = None, stream_lines: list[str] | None = None, **kwargs):
        self._post_payload = post_payload
        self._stream_lines = stream_lines or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, *, json: dict, headers: dict):
        return _FakeResponse(self._post_payload or {})

    def stream(self, method: str, url: str, *, json: dict, headers: dict):
        return _FakeStreamResponse(self._stream_lines)


class _FakeStreamResponse:
    def __init__(self, lines: list[str]):
        self.status_code = 200
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _request_body() -> dict:
    return {
        "query": "hello",
        "context": [],
        "history": [],
        "llm": {
            "provider": "DeepSeek",
            "api_key": "test-key",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 50,
            "max_tokens": 2048,
            "system_prompt": "",
        },
    }


def test_chat_ask_logs_one_chat_telemetry_row(monkeypatch) -> None:
    log_calls: list[dict] = []
    monkeypatch.setattr(
        chat_router,
        "httpx",
        type(
            "_HTTPXModule",
            (),
            {
                "AsyncClient": lambda **kwargs: _FakeAsyncClient(
                    post_payload={
                        "choices": [{"message": {"content": "hello back"}}],
                        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
                        "model": "deepseek-chat",
                    }
                )
            },
        ),
    )
    monkeypatch.setattr(chat_router, "log_llm_call", lambda **kwargs: log_calls.append(kwargs), raising=False)

    client = TestClient(app)
    response = client.post("/chat/ask", json=_request_body())

    assert response.status_code == 200
    assert response.json()["answer"] == "hello back"
    assert len(log_calls) == 1
    assert log_calls[0]["task"] == "chat"
    assert log_calls[0]["prompt_tokens"] == 12
    assert log_calls[0]["completion_tokens"] == 5
    assert log_calls[0]["status"] == "ok"
    assert log_calls[0]["cache_status"] == "miss"
    assert log_calls[0]["decision"] == "invoke"


def test_chat_stream_logs_one_chat_telemetry_row(monkeypatch) -> None:
    log_calls: list[dict] = []
    monkeypatch.setattr(
        chat_router,
        "httpx",
        type(
            "_HTTPXModule",
            (),
            {
                "AsyncClient": lambda **kwargs: _FakeAsyncClient(
                    stream_lines=[
                        'data: {"choices":[{"delta":{"content":"hello"}}]}',
                        'data: {"usage":{"prompt_tokens":9,"completion_tokens":4,"total_tokens":13},"model":"deepseek-chat"}',
                        "data: [DONE]",
                    ]
                )
            },
        ),
    )
    monkeypatch.setattr(chat_router, "log_llm_call", lambda **kwargs: log_calls.append(kwargs), raising=False)

    client = TestClient(app)
    response = client.post("/chat/stream", json={**_request_body(), "stream": True})

    assert response.status_code == 200
    assert "text_delta" in response.text
    assert len(log_calls) == 1
    assert log_calls[0]["task"] == "chat"
    assert log_calls[0]["prompt_tokens"] == 9
    assert log_calls[0]["completion_tokens"] == 4
    assert log_calls[0]["status"] == "ok"
    assert log_calls[0]["cache_status"] == "miss"
    assert log_calls[0]["decision"] == "invoke"
