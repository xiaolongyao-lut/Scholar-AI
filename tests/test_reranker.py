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


def test_rerank_preserves_order_without_api_key():
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


def test_rerank_respects_top_k_without_api_key():
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

    candidates = [
        {"chunk_id": "c1", "content": "doc A", "rrf_score": 0.8},
        {"chunk_id": "c2", "content": "doc B", "rrf_score": 0.7},
        {"chunk_id": "c3", "content": "doc C", "rrf_score": 0.6},
    ]

    reranked = asyncio.run(reranker_mod.rerank_async("laser query", candidates, api_key="sf_key"))

    assert [item["chunk_id"] for item in reranked] == ["c2", "c1", "c3"]
    assert reranked[0]["rerank_score"] == 0.95
    assert reranked[1]["rerank_score"] == 0.12
