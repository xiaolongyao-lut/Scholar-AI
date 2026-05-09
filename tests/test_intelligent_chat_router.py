from __future__ import annotations

from fastapi.testclient import TestClient

import main_rag_workflow
from python_adapter_server import app
from routers import intelligent_chat_router
from routers import resources_router
import writing_resources
from tolf_text_selector import select_tolf_context_chunks as _original_select


def _select_with_test_thresholds(query, chunks, *, top_k, max_candidates, **_kwargs):
    return _original_select(
        query, chunks, top_k=top_k, max_candidates=max_candidates,
        activation_threshold=0.05, evidence_threshold=0.1,
    )


class _FakeChatAnswer:
    answer = "Laser power is discussed in the supplied context."
    usage = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}


class _FakeChatAnswerChartJson:
    """Returned by the chart-aware fake when the prompt is the chart prompt."""

    answer = (
        '{"title":{"text":"Laser Power vs Hardness"},'
        ' "xAxis":{"type":"category","data":["2000W","3000W"]},'
        ' "yAxis":{"type":"value"},'
        ' "series":[{"type":"bar","name":"hardness HV","data":[285,320]}]}'
    )
    usage = {"prompt_tokens": 50, "completion_tokens": 40, "total_tokens": 90}


async def _fake_chat_ask(_request):
    return _FakeChatAnswer()


async def _fake_chat_ask_chart_aware(request):
    """Test fake that recognizes the chart prompt and returns valid JSON."""
    query = getattr(request, "query", "") or ""
    if "ECharts option" in query or "JSON object" in query:
        return _FakeChatAnswerChartJson()
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


def test_api_chat_uses_project_chunks_when_project_id_is_supplied(monkeypatch, tmp_path) -> None:
    session_store = tmp_path / "sessions.json"
    doc_store_dir = tmp_path / "doc_store"
    chunk_store_dir = tmp_path / "chunk_store"
    doc_store_dir.mkdir(parents=True)
    chunk_store_dir.mkdir(parents=True)
    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(resources_router, "_DOC_STORE_DIR", doc_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_STORE_DIR", chunk_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_QUARANTINE_LOG_PATH", tmp_path / "chunk_quarantine.jsonl")
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setattr(intelligent_chat_router, "chat_ask", _fake_chat_ask)

    client = TestClient(app)
    project_response = client.post("/resources/project", json={"title": "Project Chat Grounding"})
    assert project_response.status_code == 200
    project_id = project_response.json()["project_id"]

    resources_router._save_doc_store(
        project_id,
        {
            "mat_laser": {
                "title": "Laser Process Study",
                "content": "Laser power improves hardness and changes the molten pool.",
            }
        },
    )

    response = client.post(
        "/api/chat",
        json={
            "query": "laser power hardness",
            "tier": "balanced",
            "project_id": project_id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_chunks_used"] == 1
    assert payload["context_metadata"]["chunks"][0]["material_id"] == "mat_laser"
    assert payload["context_metadata"]["chunks"][0]["chunk_id"] == "mat_laser_chunk_0"
    assert payload["evidence_refs"][0]["material_id"] == "mat_laser"
    assert payload["evidence_refs"][0]["chunk_id"] == "mat_laser_chunk_0"
    assert payload["evidence_refs"][0]["source_labels"] == ["project_chunks"]

    resumed = client.post("/api/chat/resume", json={"session_id": payload["session_id"], "limit": 1})
    assert resumed.status_code == 200
    assert resumed.json()["messages"][0]["evidence_refs"][0]["material_id"] == "mat_laser"


def test_api_chat_can_use_default_off_tolf_context_selector(monkeypatch, tmp_path) -> None:
    session_store = tmp_path / "sessions.json"
    doc_store_dir = tmp_path / "doc_store"
    chunk_store_dir = tmp_path / "chunk_store"
    doc_store_dir.mkdir(parents=True)
    chunk_store_dir.mkdir(parents=True)
    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(resources_router, "_DOC_STORE_DIR", doc_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_STORE_DIR", chunk_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_QUARANTINE_LOG_PATH", tmp_path / "chunk_quarantine.jsonl")
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "1")
    monkeypatch.setattr(intelligent_chat_router, "chat_ask", _fake_chat_ask)
    monkeypatch.setattr(intelligent_chat_router, "select_tolf_context_chunks", _select_with_test_thresholds)

    client = TestClient(app)
    project_response = client.post("/resources/project", json={"title": "TOLF Chat Grounding"})
    assert project_response.status_code == 200
    project_id = project_response.json()["project_id"]

    resources_router._save_doc_store(
        project_id,
        {
            "mat_result": {
                "title": "Laser Result Paper",
                "content": "This study reports laser power increased hardness to 280 HV.",
            },
            "mat_noise": {
                "title": "Botany Paper",
                "content": "Urban trees and rainfall were observed in autumn parks.",
            },
        },
    )

    response = client.post(
        "/api/chat",
        json={
            "query": "laser power hardness",
            "tier": "balanced",
            "project_id": project_id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_chunks_used"] >= 1
    assert payload["context_metadata"]["chunks"][0]["material_id"] == "mat_result"
    assert "tolf_text_selector" in payload["context_metadata"]["chunks"][0]["source_labels"]
    assert "tolf_text_selector" in payload["evidence_refs"][0]["source_labels"]
    assert payload["evidence_refs"][0]["label"] == "project_chunk"


def test_api_chat_tolf_context_selector_falls_back_when_empty(monkeypatch, tmp_path) -> None:
    session_store = tmp_path / "sessions.json"
    doc_store_dir = tmp_path / "doc_store"
    chunk_store_dir = tmp_path / "chunk_store"
    doc_store_dir.mkdir(parents=True)
    chunk_store_dir.mkdir(parents=True)
    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(resources_router, "_DOC_STORE_DIR", doc_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_STORE_DIR", chunk_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_QUARANTINE_LOG_PATH", tmp_path / "chunk_quarantine.jsonl")
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "1")
    monkeypatch.setattr(intelligent_chat_router, "chat_ask", _fake_chat_ask)
    monkeypatch.setattr(intelligent_chat_router, "select_tolf_context_chunks", lambda *_args, **_kwargs: [])

    client = TestClient(app)
    project_response = client.post("/resources/project", json={"title": "TOLF Fallback"})
    assert project_response.status_code == 200
    project_id = project_response.json()["project_id"]
    resources_router._save_doc_store(
        project_id,
        {
            "mat_laser": {
                "title": "Laser Process Study",
                "content": "Laser power improves hardness and changes the molten pool.",
            }
        },
    )

    response = client.post(
        "/api/chat",
        json={
            "query": "laser power hardness",
            "tier": "balanced",
            "project_id": project_id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_chunks_used"] == 1
    assert payload["context_metadata"]["chunks"][0]["source_labels"] == ["project_chunks"]
    assert payload["evidence_refs"][0]["source_labels"] == ["project_chunks"]


def test_api_chat_tolf_context_selector_ignores_invalid_candidate_env(monkeypatch, tmp_path) -> None:
    session_store = tmp_path / "sessions.json"
    doc_store_dir = tmp_path / "doc_store"
    chunk_store_dir = tmp_path / "chunk_store"
    doc_store_dir.mkdir(parents=True)
    chunk_store_dir.mkdir(parents=True)
    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(resources_router, "_DOC_STORE_DIR", doc_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_STORE_DIR", chunk_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_QUARANTINE_LOG_PATH", tmp_path / "chunk_quarantine.jsonl")
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "1")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_CANDIDATES", "not-a-number")
    monkeypatch.setattr(intelligent_chat_router, "chat_ask", _fake_chat_ask)

    client = TestClient(app)
    project_response = client.post("/resources/project", json={"title": "TOLF Bad Env"})
    assert project_response.status_code == 200
    project_id = project_response.json()["project_id"]
    resources_router._save_doc_store(
        project_id,
        {
            "mat_laser": {
                "title": "Laser Process Study",
                "content": "This study reports laser power increased hardness to 280 HV.",
            }
        },
    )

    response = client.post(
        "/api/chat",
        json={
            "query": "laser power hardness",
            "tier": "balanced",
            "project_id": project_id,
        },
    )

    assert response.status_code == 200
    assert response.json()["context_chunks_used"] == 1


def test_api_chat_uses_ragworkflow_when_project_adapter_enabled(monkeypatch, tmp_path) -> None:
    session_store = tmp_path / "sessions.json"
    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setenv("INTELLIGENT_CHAT_RAGWORKFLOW_ENABLED", "1")

    client = TestClient(app)
    project_response = client.post("/resources/project", json={"title": "RAGWorkflow Chat"})
    assert project_response.status_code == 200
    project_id = project_response.json()["project_id"]

    async def fake_ragworkflow_answer(*, query: str, project_id: str, tier: str):
        assert query == "laser power"
        assert tier == "fast"
        evidence_ref = intelligent_chat_router.EvidenceReferencePayload(
            chunk_id="rag-c1",
            material_id="mat-rag",
            source="RAG Paper",
            text="RAGWorkflow evidence text.",
            quote="RAGWorkflow evidence text.",
            label="rag_workflow",
            score=0.91,
            source_labels=["rag_workflow"],
        )
        chunk = intelligent_chat_router.ContextChunkPayload(
            index=1,
            source="RAG Paper",
            content="RAGWorkflow evidence text.",
            relevance_score=0.91,
            chunk_id="rag-c1",
            material_id="mat-rag",
            source_labels=["rag_workflow"],
        )
        return (
            "RAGWorkflow answer",
            [chunk],
            False,
            [evidence_ref],
            intelligent_chat_router.SamplingParamsPayload(
                temperature=0.1,
                top_p=0.9,
                top_k=50,
                max_tokens=2048,
            ),
        )

    monkeypatch.setattr(intelligent_chat_router, "_call_project_ragworkflow_answer", fake_ragworkflow_answer)

    response = client.post(
        "/api/chat",
        json={
            "query": "laser power",
            "tier": "fast",
            "project_id": project_id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"] == "RAGWorkflow answer"
    assert payload["context_metadata"]["chunks"][0]["chunk_id"] == "rag-c1"
    assert payload["evidence_refs"][0]["label"] == "rag_workflow"
    assert payload["tokens_used"] == {"prompt": 0, "completion": 0, "total": 0}


def test_api_chat_ragworkflow_adapter_preserves_project_chunk_provenance(monkeypatch, tmp_path) -> None:
    class _NoopSemanticCache:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def lookup(self, *_args, **_kwargs) -> None:
            return None

    class _MemoryOnlyConversationManager:
        def resume_session(self, _session_id: str) -> list[dict]:
            return []

        def log_event(self, *_args, **_kwargs) -> None:
            return None

    def fake_gated_call(**kwargs):
        assert kwargs["cache_key_parts"]["task"] == "generation"
        prompt_messages = kwargs["payload"]["messages"]
        serialized_messages = "\n".join(str(message.get("content", "")) for message in prompt_messages)
        assert "mat_contract_chunk_0" in serialized_messages
        assert "Laser power increases hardness in project-local evidence." in serialized_messages
        return (
            '{"status":"success","overall_score":0.88,'
            '"conclusion":"Project-local RAGWorkflow answer."}'
        )

    async def fake_decompose_query_async(*_args, **_kwargs) -> list[dict]:
        return [{"id": 1, "task": "laser hardness"}]

    session_store = tmp_path / "sessions.json"
    doc_store_dir = tmp_path / "doc_store"
    chunk_store_dir = tmp_path / "chunk_store"
    doc_store_dir.mkdir(parents=True)
    chunk_store_dir.mkdir(parents=True)
    resource_store = writing_resources.WritingResourceStore()
    monkeypatch.setattr(intelligent_chat_router, "_SESSION_STORE_PATH", session_store)
    monkeypatch.setattr(resources_router, "_DOC_STORE_DIR", doc_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_STORE_DIR", chunk_store_dir)
    monkeypatch.setattr(resources_router, "_CHUNK_QUARANTINE_LOG_PATH", tmp_path / "chunk_quarantine.jsonl")
    monkeypatch.setattr(resources_router, "get_writing_resource_store", lambda: resource_store)
    monkeypatch.setattr(intelligent_chat_router, "get_writing_resource_store", lambda: resource_store)
    monkeypatch.setattr(main_rag_workflow, "SemanticCache", _NoopSemanticCache)
    monkeypatch.setattr(main_rag_workflow, "get_conv_manager", lambda: _MemoryOnlyConversationManager())
    monkeypatch.setattr(main_rag_workflow, "gated_call", fake_gated_call, raising=False)
    monkeypatch.setattr(main_rag_workflow, "decompose_query_async", fake_decompose_query_async, raising=False)
    monkeypatch.setattr(main_rag_workflow, "output_path", lambda *parts: (tmp_path / "output").joinpath(*parts))
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setenv("INTELLIGENT_CHAT_RAGWORKFLOW_ENABLED", "1")
    monkeypatch.delenv("RAGFLOW_API_KEY", raising=False)

    client = TestClient(app)
    project_response = client.post("/resources/project", json={"title": "RAGWorkflow Contract"})
    assert project_response.status_code == 200
    project_id = project_response.json()["project_id"]
    resources_router._save_doc_store(
        project_id,
        {
            "mat_contract": {
                "title": "Contract Paper",
                "content": "Laser power increases hardness in project-local evidence.",
            }
        },
    )

    response = client.post(
        "/api/chat",
        json={
            "query": "laser power hardness",
            "tier": "fast",
            "project_id": project_id,
            "session_id": "session_ragworkflow_contract",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Project-local RAGWorkflow answer" in payload["response"]
    assert payload["context_chunks_used"] == 1
    assert payload["context_metadata"]["chunks"][0]["chunk_id"] == "mat_contract_chunk_0"
    assert payload["context_metadata"]["chunks"][0]["material_id"] == "mat_contract"
    assert payload["context_metadata"]["chunks"][0]["source_labels"]
    assert payload["evidence_refs"][0]["chunk_id"] == "mat_contract_chunk_0"
    assert payload["evidence_refs"][0]["material_id"] == "mat_contract"
    assert "Laser power increases hardness in project-local evidence." in payload["evidence_refs"][0]["text"]
    assert payload["evidence_refs"][0]["source_labels"]
    assert payload["tokens_used"] == {"prompt": 0, "completion": 0, "total": 0}

    resumed = client.post("/api/chat/resume", json={"session_id": payload["session_id"], "limit": 1})
    assert resumed.status_code == 200
    assert resumed.json()["messages"][0]["evidence_refs"][0]["chunk_id"] == "mat_contract_chunk_0"


def test_api_chat_returns_404_for_unknown_project_id() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={
            "query": "laser power",
            "tier": "fast",
            "project_id": "missing_project",
        },
    )

    assert response.status_code == 404
    assert "Project not found" in response.text


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


def test_api_budget_status_uses_defaults_for_invalid_env(monkeypatch) -> None:
    monkeypatch.setattr(
        intelligent_chat_router,
        "_read_cost_aggregate",
        lambda _start, _end: {"total_calls": 3, "total_cost_usd": 0.25},
    )
    monkeypatch.setenv("INTELLIGENT_CHAT_DAILY_CALL_CAP", "invalid")
    monkeypatch.setenv("INTELLIGENT_CHAT_DAILY_BUDGET_USD", "invalid")

    client = TestClient(app)
    response = client.get("/api/budget/status")

    assert response.status_code == 200
    assert response.json()["call_cap"] == 200
    assert response.json()["budget_usd"] == 5.0


def test_api_chat_text_response_when_chart_agent_disabled(monkeypatch, tmp_path) -> None:
    """Default off: chart-intent query still returns response_type=text."""
    source = tmp_path / "paper.txt"
    source.write_text("Laser power values: 100W, 150W, 200W.\n", encoding="utf-8")
    monkeypatch.setenv("LITERATURE_SOURCE_PATHS", str(tmp_path))
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.delenv("LITERATURE_ENABLE_CHART_AGENT", raising=False)
    monkeypatch.setattr(intelligent_chat_router, "chat_ask", _fake_chat_ask)

    chart_query = "draw 柱状图 for laser power"
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"query": chart_query, "tier": "fast"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["response_type"] == "text"
    assert payload["chart_spec"] is None


def test_api_chat_returns_chart_when_flag_enabled(monkeypatch, tmp_path) -> None:
    """With LITERATURE_ENABLE_CHART_AGENT=1 + seed-word query → chart response."""
    source = tmp_path / "paper.txt"
    source.write_text("Laser power values: 100W, 150W, 200W.\n", encoding="utf-8")
    monkeypatch.setenv("LITERATURE_SOURCE_PATHS", str(tmp_path))
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setenv("LITERATURE_ENABLE_CHART_AGENT", "1")
    monkeypatch.setattr(intelligent_chat_router, "chat_ask", _fake_chat_ask_chart_aware)

    chart_query = "draw 柱状图 for laser power"
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"query": chart_query, "tier": "fast"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["response_type"] == "chart"
    spec = payload["chart_spec"]
    assert spec is not None
    assert spec["series"][0]["type"] in {"bar", "line", "pie", "scatter", "radar", "candlestick"}


def _conf_ref(score: float):
    """Build a minimal EvidenceReferencePayload-like object for confidence tests."""
    from routers.intelligent_chat_router import EvidenceReferencePayload
    return EvidenceReferencePayload(
        chunk_id=f"chunk-{score}",
        material_id=None,
        source="test.txt",
        text="x",
        quote="x",
        label="local_context",
        score=score,
    )


def test_compute_confidence_handles_unbounded_bm25_scores() -> None:
    """Live smoke regression: BM25 scores 6.5–9.5 must not all clamp to high.

    Why:
        evidence_refs[].score is the raw retriever output (no normalization).
        Pre-fix the formula 0.6·max + 0.4·avg always rounded to 1.0 for any
        successful project-mode match. Saturation s/(s+5) keeps the spread.
    """
    from routers.intelligent_chat_router import _compute_confidence

    score, label = _compute_confidence([_conf_ref(9.5), _conf_ref(6.83)])
    assert score is not None and 0.0 < score < 1.0
    # 9.5/(9.5+5)=0.655, 6.83/(6.83+5)=0.577 → 0.6*0.655+0.4*0.616=0.639 → medium
    assert label == "medium", f"expected medium for raw 9.5/6.83, got {label} ({score})"


def test_compute_confidence_separates_strong_from_weak() -> None:
    from routers.intelligent_chat_router import _compute_confidence

    strong_score, strong_label = _compute_confidence([_conf_ref(40.0), _conf_ref(35.0)])
    weak_score, weak_label = _compute_confidence([_conf_ref(0.5), _conf_ref(0.3)])
    assert strong_score is not None and weak_score is not None
    assert strong_score > weak_score
    assert strong_label == "high"
    assert weak_label == "very_low"


def test_compute_confidence_returns_none_when_no_scores() -> None:
    from routers.intelligent_chat_router import _compute_confidence

    score, label = _compute_confidence([])
    assert score is None and label is None


def test_compute_confidence_filters_negative_scores() -> None:
    from routers.intelligent_chat_router import _compute_confidence

    score, label = _compute_confidence([_conf_ref(-0.1), _conf_ref(8.0)])
    assert score is not None
    assert 0.0 < score < 1.0


def test_api_chat_falls_back_to_text_when_llm_returns_garbage_for_chart(
    monkeypatch, tmp_path
) -> None:
    """P3.1a regression: chart agent gets garbage from LLM → text fallback.

    Why:
        With chart flag on, the chart agent calls the LLM for an ECharts
        JSON spec. If the LLM returns prose instead of JSON (or rejected
        JSON), the chat handler must still return a valid text answer
        rather than crashing or showing an empty chart.
    """
    source = tmp_path / "paper.txt"
    source.write_text("Laser power values: 100W, 150W, 200W.\n", encoding="utf-8")
    monkeypatch.setenv("LITERATURE_SOURCE_PATHS", str(tmp_path))
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setenv("LITERATURE_ENABLE_CHART_AGENT", "1")
    # _fake_chat_ask returns prose for every prompt — simulates LLM failure
    # to produce JSON for the chart agent path.
    monkeypatch.setattr(intelligent_chat_router, "chat_ask", _fake_chat_ask)

    chart_query = "draw 柱状图 for laser power"
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"query": chart_query, "tier": "fast"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["response_type"] == "text"
    assert payload["chart_spec"] is None
    assert payload["response"] == _FakeChatAnswer.answer
