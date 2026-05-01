from __future__ import annotations

from fastapi.testclient import TestClient

from python_adapter_server import app
from routers import intelligent_chat_router


class _FakeChatAnswer:
    answer = "Laser power is discussed in the supplied context."
    usage = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}


async def _fake_chat_ask(_request):
    return _FakeChatAnswer()


def test_api_chat_requires_literature_sources(monkeypatch) -> None:
    monkeypatch.delenv("LITERATURE_SOURCE_PATHS", raising=False)

    client = TestClient(app)
    response = client.post("/api/chat", json={"query": "laser power", "tier": "balanced"})

    assert response.status_code == 400
    assert "No literature source paths configured" in response.text


def test_api_chat_returns_context_and_evidence_refs(monkeypatch, tmp_path) -> None:
    source = tmp_path / "paper.txt"
    source.write_text(
        "Laser power changes molten pool geometry and affects hardness.\n\n"
        "Cooling rate controls microstructure in titanium alloy welding.",
        encoding="utf-8",
    )
    monkeypatch.setenv("LITERATURE_SOURCE_PATHS", str(tmp_path))
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setattr(intelligent_chat_router, "chat_ask", _fake_chat_ask)

    client = TestClient(app)
    response = client.post("/api/chat", json={"query": "laser power hardness", "tier": "fast"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"] == _FakeChatAnswer.answer
    assert payload["session_id"].startswith("session_")
    assert payload["context_chunks_used"] == 1
    assert payload["tokens_used"] == {"prompt": 12, "completion": 8, "total": 20}
    assert payload["tier_used"] == "fast"
    assert payload["context_metadata"]["chunks"][0]["source"].endswith("paper.txt")
    assert payload["evidence_refs"][0]["source"].endswith("paper.txt")
    assert payload["actual_sampling_params"]["max_tokens"] == 2048


def test_api_chat_sessions_and_resume_return_recent_turns(monkeypatch, tmp_path) -> None:
    source = tmp_path / "paper.txt"
    source.write_text("Laser welding power improves hardness.", encoding="utf-8")
    session_store = tmp_path / "sessions.json"
    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setenv("LITERATURE_SOURCE_PATHS", str(tmp_path))
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setattr(intelligent_chat_router, "chat_ask", _fake_chat_ask)

    client = TestClient(app)
    first = client.post(
        "/api/chat",
        json={"query": "laser hardness", "tier": "balanced", "session_id": "session_test"},
    )
    second = client.post(
        "/api/chat",
        json={"query": "laser power", "tier": "thorough", "session_id": "session_test"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    sessions = client.get("/api/chat/sessions")
    assert sessions.status_code == 200
    assert sessions.json()["sessions"][0]["session_id"] == "session_test"
    assert sessions.json()["sessions"][0]["total_turns"] == 4

    resumed = client.post("/api/chat/resume", json={"session_id": "session_test", "limit": 2})
    assert resumed.status_code == 200
    messages = resumed.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "laser power"
    assert messages[1]["tier_used"] == "thorough"


def test_api_budget_status_and_openapi_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        intelligent_chat_router,
        "_read_cost_aggregate",
        lambda _start, _end: {"total_calls": 3, "total_cost_usd": 0.25},
    )
    monkeypatch.setenv("INTELLIGENT_CHAT_DAILY_CALL_CAP", "10")
    monkeypatch.setenv("INTELLIGENT_CHAT_DAILY_BUDGET_USD", "1")

    client = TestClient(app)
    response = client.get("/api/budget/status")

    assert response.status_code == 200
    assert response.json() == {
        "call_count": 3,
        "call_cap": 10,
        "cost_usd": 0.25,
        "budget_usd": 1.0,
        "percent_calls": 30.0,
        "percent_usd": 25.0,
    }

    schema = client.get("/openapi.json").json()
    assert "/api/chat" in schema["paths"]
    assert "/api/chat/sessions" in schema["paths"]
    assert "/api/chat/resume" in schema["paths"]
    assert "/api/budget/status" in schema["paths"]
    assert "IntelligentChatResponse" in schema["components"]["schemas"]
    assert "EvidenceReferencePayload" in schema["components"]["schemas"]
