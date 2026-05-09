import asyncio
import types

from layers.ai_adapter import AIAdapter
from layers.r_layer_hybrid_retriever import HybridRetrieverWithRerank


def _disable_local_dotenv(monkeypatch):
    for name in (
        "API_KEY",
        "BASE_URL",
        "MODEL",
        "RERANK_API_KEY",
        "RERANK_BASE_URL",
        "RERANK_MODEL",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_RERANK_API_KEY",
        "DASHSCOPE_RERANK_BASE_URL",
        "DASHSCOPE_RERANK_MODEL",
        "SILICONFLOW_API_KEY",
        "SILICONFLOW_RERANK_API_KEY",
        "SILICONFLOW_RERANK_BASE_URL",
        "SILICONFLOW_RERANK_MODEL",
        "RAG_RUNTIME_RERANK_ENABLED",
        "EMBEDDING_API_KEY",
        "EMBEDDING_MODEL",
        "EMBEDDING_BASE_URL",
        "SILICONFLOW_EMBEDDING_API_KEY",
        "SILICONFLOW_EMBEDDING_MODEL",
        "SILICONFLOW_EMBEDDING_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RUNTIME_ENV_DISABLE_DOTENV", "1")
    monkeypatch.setenv("RERANK_KEY_PROBE_DISABLE", "1")
    monkeypatch.setenv("EMBEDDING_KEY_PROBE_DISABLE", "1")


class _DummyOpenAIClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_ai_adapter_uses_ark_env_when_openai_missing(monkeypatch):
    _disable_local_dotenv(monkeypatch)
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


def test_hybrid_retriever_uses_siliconflow_rerank(monkeypatch):
    _disable_local_dotenv(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_RERANK_API_KEY", "sf_rerank_key")
    monkeypatch.setenv("SILICONFLOW_RERANK_BASE_URL", "https://api.siliconflow.cn/v1/rerank")
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)

    import layers.r_layer_hybrid_retriever as retriever_mod

    observed = {}

    async def _fake_rerank_async(query, candidates, top_k=10, **_kwargs):
        observed["query"] = query
        observed["candidate_count"] = len(candidates)
        observed["top_k"] = top_k
        return [
            {**candidates[1], "rerank_score": 0.95, "rerank_model": "qwen3-rerank", "rerank_source": "env"},
            {**candidates[0], "rerank_score": 0.12, "rerank_model": "qwen3-rerank", "rerank_source": "env"},
        ]

    monkeypatch.setattr(retriever_mod, "rerank_async", _fake_rerank_async)

    retriever = HybridRetrieverWithRerank(use_reranker=True)
    candidates = [
        {"claim": "doc A", "hybrid_score": 0.8},
        {"claim": "doc B", "hybrid_score": 0.7},
    ]

    reranked = asyncio.run(retriever._rerank_with_api("laser query", candidates))

    assert reranked[0]["claim"] == "doc B"
    assert reranked[0]["rerank_score"] == 0.95
    assert reranked[1]["rerank_score"] == 0.12
    assert observed == {"query": "laser query", "candidate_count": 2, "top_k": 2}


def test_hybrid_retriever_search_caps_rerank_candidates_and_warms_once(monkeypatch):
    _disable_local_dotenv(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_RERANK_API_KEY", "sf_rerank_key")
    monkeypatch.setenv("RERANK_PRE_TOPN", "3")
    monkeypatch.setenv("RERANK_PRE_TOPN_HARD_CAP", "4")

    import layers.r_layer_hybrid_retriever as retriever_mod

    observed = {}

    async def _fake_hybrid_search(raw_data, query, top_k=50, focus_keywords=None):
        observed["retrieval_top_k"] = top_k
        return [
            {"claim": f"doc {idx}", "hybrid_score": 0.95 - idx * 0.05}
            for idx in range(6)
        ]

    async def _fake_warmup():
        observed["warmup_calls"] = observed.get("warmup_calls", 0) + 1
        return {"warmed": True, "candidate_source": "env", "candidate_model": "qwen3-rerank"}

    async def _fake_rerank_async(query, candidates, top_k=10, **_kwargs):
        observed["rerank_query"] = query
        observed["rerank_candidate_count"] = len(candidates)
        observed["rerank_top_k"] = top_k
        return [
            {**item, "rerank_score": 0.99 - idx * 0.1, "rerank_model": "qwen3-rerank", "rerank_source": "env"}
            for idx, item in enumerate(candidates)
        ]

    monkeypatch.setattr(retriever_mod, "warm_rerank_live_candidate", _fake_warmup)
    monkeypatch.setattr(retriever_mod, "rerank_async", _fake_rerank_async)

    retriever = HybridRetrieverWithRerank(use_reranker=True)
    retriever.rerank_api_key = "sf_rerank_key"
    retriever.durable_cache = types.SimpleNamespace(
        lookup=lambda *_args, **_kwargs: None,
        update=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(retriever.base_retriever, "hybrid_search", _fake_hybrid_search)

    reranked = asyncio.run(retriever.search({"claim_index": []}, "laser query", top_k=2))

    assert observed["retrieval_top_k"] == 50
    assert observed["warmup_calls"] == 1
    assert observed["rerank_query"] == "laser query"
    assert observed["rerank_candidate_count"] == 3
    assert observed["rerank_top_k"] == 3
    assert len(reranked) == 2
    assert reranked[0]["rerank_score"] == 0.99


def test_hybrid_retriever_runtime_rerank_defaults_off(monkeypatch):
    _disable_local_dotenv(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_RERANK_API_KEY", "sf_rerank_key")

    retriever = HybridRetrieverWithRerank()

    assert retriever.rerank_api_key == "sf_rerank_key"
    assert retriever.use_reranker is False


def test_hybrid_retriever_runtime_rerank_env_canary_opt_in(monkeypatch):
    _disable_local_dotenv(monkeypatch)
    monkeypatch.setenv("RAG_RUNTIME_RERANK_ENABLED", "1")
    monkeypatch.setenv("SILICONFLOW_RERANK_API_KEY", "sf_rerank_key")

    retriever = HybridRetrieverWithRerank()

    assert retriever.rerank_api_key == "sf_rerank_key"
    assert retriever.use_reranker is True


def test_hybrid_retriever_explicit_constructor_overrides_runtime_env(monkeypatch):
    _disable_local_dotenv(monkeypatch)
    monkeypatch.setenv("RAG_RUNTIME_RERANK_ENABLED", "0")
    monkeypatch.setenv("SILICONFLOW_RERANK_API_KEY", "sf_rerank_key")

    retriever = HybridRetrieverWithRerank(use_reranker=True)

    assert retriever.use_reranker is True
