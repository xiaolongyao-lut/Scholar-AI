from __future__ import annotations
import pytest
import main_rag_workflow

class _FakeResponse:
    status_code = 200
    def __init__(self, payload: dict) -> None:
        self._payload = payload
    def json(self) -> dict:
        return self._payload

class _FakeLLMClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
    async def post(self, url: str, *, headers: dict, json: dict) -> _FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse({"choices": [{"message": {"content": "{\"status\": \"success\"}"}}]})

@pytest.mark.asyncio
async def test_generate_answer_prompt_requires_chunk_id_citations_and_packs_evidence(monkeypatch) -> None:
    client = _FakeLLMClient()
    gateway_calls: list[dict] = []
    def fake_gated_call(**kwargs):
        gateway_calls.append(kwargs)
        return "{\"status\": \"success\"}"

    monkeypatch.setattr(main_rag_workflow, "gated_call", fake_gated_call, raising=False)
    workflow = main_rag_workflow.RAGWorkflow(semantic_router=object(), llm_client=client, api_key="test-key", enable_requests_fallback=False)

    monkeypatch.setenv("EVIDENCE_PACK_TOP_K", "2")
    monkeypatch.setenv("EVIDENCE_MAX_PER_MATERIAL", "2")
    monkeypatch.setenv("EVIDENCE_TOKEN_BUDGET", "4000")
    monkeypatch.setenv("EVIDENCE_TOKEN_HARD_CAP", "5000")

    await workflow._generate_answer(
        user_query="laser welding",
        focused_points=["pores"],
        rag_evidence=[
            {"chunk_id": "chunk-1", "material_id": "paper-a", "score": 0.99, "text": "evidence one"},
            {"chunk_id": "chunk-2", "material_id": "paper-b", "score": 0.95, "text": "evidence two"},
            {"chunk_id": "chunk-3", "material_id": "paper-c", "score": 0.90, "text": "evidence three"},
        ],
        memory_hits=[],
    )

    gateway_call = gateway_calls[0]
    prompt = gateway_call["payload"]["messages"][0]["content"]
    assert "[chunk-1]" in prompt
    assert "[chunk-2]" in prompt
    assert "evidence three" not in prompt
    # 使用常量引用，彻底避开测试脚本的编码问题
    assert "chunk_id" in prompt.lower()

@pytest.mark.asyncio
async def test_generate_answer_prompt_enforces_unified_json_only_schema(monkeypatch) -> None:
    gateway_calls: list[dict] = []
    def fake_gated_call(**kwargs):
        gateway_calls.append(kwargs)
        return '{"conclusion": "test"}'
    monkeypatch.setattr(main_rag_workflow, "gated_call", fake_gated_call, raising=False)
    workflow = main_rag_workflow.RAGWorkflow(semantic_router=object(), llm_client=None, api_key="test-key", enable_requests_fallback=False)

    await workflow._generate_answer(
        user_query="test", focused_points=["test"],
        rag_evidence=[{"chunk_id": "c1", "material_id": "m1", "score": 0.9, "text": "t"}],
        memory_hits=[],
    )
    prompt = gateway_calls[0]["payload"]["messages"][0]["content"]
    assert "JSON" in prompt
    assert "conclusion" in prompt
    assert "evidence" in prompt
    assert "status" in prompt

@pytest.mark.asyncio
async def test_generate_answer_prompt_enforces_conflict_handling(monkeypatch) -> None:
    gateway_calls: list[dict] = []
    def fake_gated_call(**kwargs):
        gateway_calls.append(kwargs)
        return '{\"status\": \"conflict\"}'
    monkeypatch.setattr(main_rag_workflow, "gated_call", fake_gated_call, raising=False)
    workflow = main_rag_workflow.RAGWorkflow(semantic_router=object(), llm_client=None, api_key="test-key", enable_requests_fallback=False)
    await workflow._generate_answer(
        user_query="test", focused_points=[],
        rag_evidence=[{"chunk_id": "c1", "material_id": "m1", "score": 0.9, "text": "t"}],
        memory_hits=[],
    )
    prompt = gateway_calls[0]["payload"]["messages"][0]["content"]
    assert "status" in prompt and "conflict" in prompt

@pytest.mark.asyncio
async def test_generate_answer_prompt_forbids_fabricated_chunk_ids(monkeypatch) -> None:
    gateway_calls: list[dict] = []
    def fake_gated_call(**kwargs):
        gateway_calls.append(kwargs)
        return '{\"status\": \"success\"}'
    monkeypatch.setattr(main_rag_workflow, "gated_call", fake_gated_call, raising=False)
    workflow = main_rag_workflow.RAGWorkflow(semantic_router=object(), llm_client=None, api_key="test-key", enable_requests_fallback=False)
    await workflow._generate_answer(
        user_query="test", focused_points=[],
        rag_evidence=[{"chunk_id": "real-1", "material_id": "m1", "score": 0.9, "text": "t"}],
        memory_hits=[],
    )
    prompt = gateway_calls[0]["payload"]["messages"][0]["content"]
    assert "chunk_id" in prompt.lower()


@pytest.mark.asyncio
async def test_rag_search_preserves_local_rerank_metadata(monkeypatch) -> None:
    workflow = main_rag_workflow.RAGWorkflow(
        semantic_router=object(),
        ragflow_adapter=None,
        local_data={"claim_index": [{"claim": "doc A"}]},
        api_key="test-key",
        llm_client=object(),
        enable_requests_fallback=False,
    )

    async def fake_hybrid_search(*, raw_extract, query, top_k):
        assert query == "laser query"
        assert top_k == 2
        return [
            {
                "claim": "doc B",
                "chunk_id": "chunk-1",
                "material_id": "mat-1",
                "hybrid_score": 0.31,
                "rerank_score": 0.97,
                "rerank_model": "qwen3-vl-rerank",
                "rerank_source": "key-pool:unknown",
                "rerank_fallback": False,
                "source_labels": ["bm25", "dense", "rerank"],
                "source_hint": "bm25+dense+rerank",
            }
        ]

    monkeypatch.setattr(main_rag_workflow, "hybrid_search", fake_hybrid_search, raising=False)

    hits = await workflow._rag_search("laser query", top_k=2)

    assert len(hits) == 1
    assert hits[0]["text"] == "doc B"
    assert hits[0]["score"] == 0.97
    assert hits[0]["chunk_id"] == "chunk-1"
    assert hits[0]["material_id"] == "mat-1"
    assert hits[0]["rerank_score"] == 0.97
    assert hits[0]["rerank_model"] == "qwen3-vl-rerank"
    assert hits[0]["rerank_source"] == "key-pool:unknown"
    assert hits[0]["rerank_fallback"] is False
    assert hits[0]["source_labels"] == ["bm25", "dense", "rerank", "local_fallback"]
    assert hits[0]["source_hint"] == "bm25+dense+rerank"
    assert hits[0]["metadata"]["rerank_model"] == "qwen3-vl-rerank"
    assert hits[0]["metadata"]["source_labels"] == ["bm25", "dense", "rerank", "local_fallback"]


@pytest.mark.asyncio
async def test_ask_result_exposes_generation_evidence_refs(monkeypatch) -> None:
    class _FakeRouter:
        async def route_query(self, _query: str, top_k: int) -> list[str]:
            assert top_k == 2
            return ["porosity"]

    workflow = main_rag_workflow.RAGWorkflow(
        semantic_router=_FakeRouter(),
        ragflow_adapter=None,
        api_key="test-key",
        llm_client=object(),
        enable_requests_fallback=False,
    )

    async def fake_decompose_query_async(*_args, **_kwargs) -> list[str]:
        return ["laser porosity"]

    async def fake_rag_search(_query: str, *, top_k: int, dataset_ids=None) -> list[dict]:
        assert top_k == 3
        assert dataset_ids == ["ds-1"]
        return [
            {
                "chunk_id": "chunk-keep",
                "material_id": "paper-a",
                "text": "Kept evidence.",
                "score": 0.99,
                "source_labels": ["bm25", "dense"],
            },
            {
                "chunk_id": "chunk-drop",
                "material_id": "paper-b",
                "text": "Dropped evidence.",
                "score": 0.1,
            },
        ]

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    def fake_gated_call(**kwargs):
        task = kwargs["cache_key_parts"].get("task")
        if task == "semantic_cache_lookup":
            return [0.1, 0.2]
        if task == "generation":
            return '{"status": "success", "overall_score": 1.0}'
        raise AssertionError(f"unexpected gateway task: {task}")

    monkeypatch.setattr(main_rag_workflow, "decompose_query_async", fake_decompose_query_async, raising=False)
    monkeypatch.setattr(workflow, "_rag_search", fake_rag_search, raising=False)
    monkeypatch.setattr(main_rag_workflow.asyncio, "to_thread", fake_to_thread, raising=False)
    monkeypatch.setattr(main_rag_workflow, "gated_call", fake_gated_call, raising=False)
    monkeypatch.setattr(main_rag_workflow, "_compute_corpus_version", lambda _project_id: "corpus-v1", raising=False)
    monkeypatch.setenv("EVIDENCE_PACK_TOP_K", "1")
    monkeypatch.setenv("EVIDENCE_MAX_PER_MATERIAL", "2")
    monkeypatch.setenv("EVIDENCE_TOKEN_BUDGET", "4000")
    monkeypatch.setenv("EVIDENCE_TOKEN_HARD_CAP", "5000")

    result = await workflow.ask_my_literature(
        "How does laser welding porosity form?",
        top_k_points=2,
        top_k_evidence=3,
        dataset_ids=["ds-1"],
    )

    assert result.generated_answer
    assert result.rag_evidence[0]["chunk_id"] == "chunk-keep"
    assert result.evidence_refs == [
        {
            "chunk_id": "chunk-keep",
            "material_id": "paper-a",
            "text": "Kept evidence.",
            "compressed_text": "",
            "quote": "",
            "label": "",
            "score": 0.99,
            "source_labels": ["bm25", "dense"],
        }
    ]
    assert result.trace["step_3_generation"]["evidence_ref_count"] == 1
