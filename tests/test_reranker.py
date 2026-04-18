from __future__ import annotations

import asyncio


class _StubResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

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
        assert url == "https://api.siliconflow.cn/v1/rerank"
        assert json["model"] == "Qwen/Qwen3-Reranker-8B"
        assert json["query"] == "laser query"
        assert len(json["documents"]) == 3
        return _StubResponse(
            status_code=200,
            payload={
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.12},
                    {"index": 2, "relevance_score": 0.01},
                ]
            },
        )


class _StubAsyncClient429Then200:
    calls = 0

    def __init__(self, *_args, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, _url, headers=None, json=None):
        _ = headers, json
        _StubAsyncClient429Then200.calls += 1
        if _StubAsyncClient429Then200.calls == 1:
            return _StubResponse(status_code=429, payload={"error": "rate limited"})
        return _StubResponse(
            status_code=200,
            payload={
                "results": [
                    {"index": 2, "relevance_score": 0.99},
                    {"index": 0, "relevance_score": 0.50},
                    {"index": 1, "relevance_score": 0.10},
                ]
            },
        )


def test_rerank_preserves_order_without_api_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_API_KEY", raising=False)
    from reranker_client import rerank

    candidates = [
        {"chunk_id": "c1", "content": "完全无关的天气预报内容", "rrf_score": 0.9},
        {"chunk_id": "c2", "content": "海洋生物泵是碳循环的核心驱动力", "rrf_score": 0.8},
        {"chunk_id": "c3", "content": "随机噪音文本", "rrf_score": 0.7},
    ]

    result = rerank("海洋碳循环的主要机制", candidates, api_key=None)

    assert [item["chunk_id"] for item in result] == ["c1", "c2", "c3"]
    assert all("rerank_score" in item for item in result)
    assert result[0]["rerank_score"] == candidates[0]["rrf_score"]


def test_rerank_respects_top_k_without_api_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_API_KEY", raising=False)
    from reranker_client import rerank

    candidates = [{"chunk_id": f"c{i}", "content": f"text {i}", "rrf_score": 1.0 / (i + 1)} for i in range(20)]
    result = rerank("query", candidates, top_k=5, api_key=None)
    assert len(result) == 5
    assert result[0]["chunk_id"] == "c0"


def test_rerank_handles_empty_candidates():
    from reranker_client import rerank

    assert rerank("query", [], api_key=None) == []


def test_rerank_async_reorders_using_api(monkeypatch):
    import reranker_client as reranker_mod

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _StubAsyncClient)
    monkeypatch.delenv("SILICONFLOW_RERANK_BASE_URL", raising=False)
    monkeypatch.delenv("SILICONFLOW_RERANK_MODEL", raising=False)

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
        {"chunk_id": "c3", "content": "doc C", "rrf_score": 0.6},
    ]

    reranked = asyncio.run(reranker_mod.rerank_async("laser query", candidates, api_key="sf_key"))

    assert [item["chunk_id"] for item in reranked] == ["c2", "c1", "c3"]
    assert reranked[0]["rerank_score"] == 0.95
    assert reranked[1]["rerank_score"] == 0.12


def test_rerank_async_retries_429_then_succeeds(monkeypatch):
    import reranker_client as reranker_mod

    _StubAsyncClient429Then200.calls = 0
    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _StubAsyncClient429Then200)

    # eliminate actual sleep/jitter delay in unit test
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(reranker_mod.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(reranker_mod.random, "uniform", lambda _a, _b: 0.0)

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
        {"chunk_id": "c3", "content": "doc C", "rrf_score": 0.6},
    ]
    timings: dict[str, float] = {}

    reranked = asyncio.run(
        reranker_mod.rerank_async("laser query", candidates, api_key="sf_key", timings=timings)
    )

    assert _StubAsyncClient429Then200.calls == 2
    assert timings.get("attempts") == 2
    assert [item["chunk_id"] for item in reranked] == ["c3", "c1", "c2"]


def test_parse_retry_after_prefers_ms_header():
    from reranker_client import _parse_retry_after

    assert _parse_retry_after({"retry-after-ms": "1500"}) == 1.5
    assert _parse_retry_after({"retry-after": "3"}) == 3.0
    assert _parse_retry_after({"retry-after-ms": "bogus", "retry-after": "2"}) == 2.0
    assert _parse_retry_after({}) is None
    assert _parse_retry_after(None) is None
    # caps oversized values at MAX_BACKOFF_SECONDS (60s)
    assert _parse_retry_after({"retry-after": "999"}) == 60.0


def test_rerank_async_honors_retry_after_header(monkeypatch):
    """When server returns Retry-After, backoff must use that value (not exponential)."""
    import reranker_client as reranker_mod

    captured_sleeps: list[float] = []

    class _RetryAfterStub:
        calls = 0

        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, *_a, **_kw):
            _RetryAfterStub.calls += 1
            if _RetryAfterStub.calls == 1:
                resp = _StubResponse(status_code=429, payload={"error": "rate limited"})
                resp.headers = {"retry-after-ms": "750"}
                return resp
            return _StubResponse(
                status_code=200,
                payload={"results": [{"index": 0, "relevance_score": 0.9}]},
            )

    async def _capture_sleep(seconds):
        captured_sleeps.append(seconds)

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _RetryAfterStub)
    monkeypatch.setattr(reranker_mod.asyncio, "sleep", _capture_sleep)
    monkeypatch.setattr(reranker_mod.random, "uniform", lambda _a, _b: 0.0)

    candidates = [{"chunk_id": "c1", "content": "doc A", "rrf_score": 0.5}]
    asyncio.run(reranker_mod.rerank_async("q", candidates, api_key="sf_key"))

    assert _RetryAfterStub.calls == 2
    assert captured_sleeps == [0.75]  # Retry-After header honored, not 0.5*2^0 exponential


def test_rerank_async_truncates_oversized_documents(monkeypatch):
    """Docs exceeding SAFE_RERANK_DOC_TOKENS must be head-truncated before the POST."""
    import reranker_client as reranker_mod
    from reranker_client import SAFE_RERANK_DOC_TOKENS
    from token_utils import count_tokens

    captured_payloads: list[dict] = []

    class _CapturingStub:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, _url, headers=None, json=None):
            captured_payloads.append(json)
            return _StubResponse(
                status_code=200,
                payload={"results": [
                    {"index": 0, "relevance_score": 0.5},
                    {"index": 1, "relevance_score": 0.3},
                ]},
            )

    monkeypatch.setattr(reranker_mod.httpx, "AsyncClient", _CapturingStub)

    long_doc = "激光焊接钛合金。" * 5000  # well above 7500 tokens
    short_doc = "微观组织演化"
    candidates = [
        {"chunk_id": "big", "content": long_doc, "rrf_score": 0.9},
        {"chunk_id": "small", "content": short_doc, "rrf_score": 0.8},
    ]

    reranked = asyncio.run(reranker_mod.rerank_async("q", candidates, api_key="sf_key"))

    assert len(captured_payloads) == 1
    sent_docs = captured_payloads[0]["documents"]
    assert len(sent_docs) == 2
    assert count_tokens(sent_docs[0]) <= SAFE_RERANK_DOC_TOKENS
    assert sent_docs[1] == short_doc  # untouched
    # Reranked output still keys back to original candidates
    assert {item["chunk_id"] for item in reranked} == {"big", "small"}

