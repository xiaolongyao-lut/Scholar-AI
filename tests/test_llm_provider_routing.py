import asyncio
import types

from layers.ai_adapter import AIAdapter
from layers.r_layer_hybrid_retriever import HybridRetrieverWithRerank


class _DummyOpenAIClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_ai_adapter_uses_ark_env_when_openai_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    monkeypatch.setenv("ARK_API_KEY", "ark_test_key")
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.example.com/v3")
    monkeypatch.setenv("ARK_MODEL", "ep-test-model")

    from layers import ai_adapter as ai_mod

    monkeypatch.setattr(ai_mod, "HAS_OPENAI", True)
    monkeypatch.setattr(
        ai_mod,
        "openai",
        types.SimpleNamespace(OpenAI=lambda **kwargs: _DummyOpenAIClient(**kwargs)),
        raising=False,
    )

    adapter = AIAdapter()

    assert adapter.enabled is True
    assert adapter.api_key == "ark_test_key"
    assert adapter.base_url == "https://ark.example.com/v3"
    assert adapter.model == "ep-test-model"


class _StubResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _StubAsyncClient:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        # Validate rerank endpoint and model usage
        assert url == "https://api.siliconflow.cn/v1/rerank"
        assert json["model"] == "Qwen/Qwen3-Reranker-8B"
        assert json["query"] == "laser query"
        assert len(json["documents"]) == 2

        # index=1 has higher score -> should become first after rerank
        return _StubResponse(
            status_code=200,
            payload={
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.12},
                ]
            },
        )


def test_hybrid_retriever_uses_siliconflow_rerank(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_RERANK_API_KEY", "sf_rerank_key")
    monkeypatch.setenv("SILICONFLOW_RERANK_BASE_URL", "https://api.siliconflow.cn/v1/rerank")
    monkeypatch.setenv("SILICONFLOW_RERANK_MODEL", "Qwen/Qwen3-Reranker-8B")

    import layers.r_layer_hybrid_retriever as retriever_mod

    monkeypatch.setattr(retriever_mod.httpx, "AsyncClient", _StubAsyncClient)

    retriever = HybridRetrieverWithRerank(use_reranker=True)
    candidates = [
        {"claim": "doc A", "hybrid_score": 0.8},
        {"claim": "doc B", "hybrid_score": 0.7},
    ]

    reranked = asyncio.run(retriever._rerank_with_api("laser query", candidates))

    assert reranked[0]["claim"] == "doc B"
    assert reranked[0]["rerank_score"] == 0.95
    assert reranked[1]["rerank_score"] == 0.12
