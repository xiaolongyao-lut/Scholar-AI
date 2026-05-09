from __future__ import annotations

import os
from typing import Any

import pytest

import chunk_vector_store as cvs


class _EmbeddingResponse:
    status_code = 200
    text = "OK"

    def __init__(self, count: int) -> None:
        if count < 0:
            raise ValueError("count must be non-negative")
        self._count = count

    def json(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "data": [
                {"index": index, "embedding": [float(index)] * cvs.EMBEDDING_DIM}
                for index in range(self._count)
            ]
        }


class _CapturingAsyncClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_CapturingAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _EmbeddingResponse:
        payload_input = json.get("input")
        if not isinstance(payload_input, list):
            raise AssertionError("embedding payload input must be a list")
        self.calls.append({"url": url, "headers": headers, "json": json})
        return _EmbeddingResponse(len(payload_input))


@pytest.fixture(autouse=True)
def isolated_embedding_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    import chunk_vector_store as cvs

    _CapturingAsyncClient.calls = []
    monkeypatch.setattr(cvs.httpx, "AsyncClient", _CapturingAsyncClient)
    monkeypatch.setattr(cvs, "inspect_text", lambda _text: {"is_oversize": False})
    monkeypatch.setattr(cvs, "count_tokens", lambda _text: 1)
    monkeypatch.delenv("EMBED_CONCURRENCY", raising=False)


@pytest.mark.asyncio
async def test_under_limit_single_request() -> None:
    from chunk_vector_store import _batch_embed

    vectors = await _batch_embed([f"text-{index}" for index in range(10)], "key", "https://example.test/v1", "model", batch_size=64)

    assert len(vectors) == 10
    assert len(_CapturingAsyncClient.calls) == 1
    assert len(_CapturingAsyncClient.calls[0]["json"]["input"]) == 10


@pytest.mark.asyncio
async def test_batch_embed_applies_provider_rate_limit_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from chunk_vector_store import _batch_embed

    captured: list[dict[str, Any]] = []

    async def _fake_wait(base_url: str | None, *, kind: str, token_count: int) -> float:
        captured.append({"base_url": base_url, "kind": kind, "token_count": token_count})
        return 0.0

    monkeypatch.setattr(cvs.provider_rate_limit, "maybe_wait_for_rate_limit_async", _fake_wait)

    vectors = await _batch_embed(
        ["text-a", "text-b"],
        "key",
        "https://api.siliconflow.cn/v1/embeddings",
        "model",
        batch_size=64,
    )

    assert len(vectors) == 2
    assert captured == [
        {
            "base_url": "https://api.siliconflow.cn/v1/embeddings",
            "kind": "embedding",
            "token_count": 2,
        }
    ]


@pytest.mark.asyncio
async def test_over_limit_auto_chunks() -> None:
    from chunk_vector_store import _batch_embed

    vectors = await _batch_embed([f"text-{index}" for index in range(200)], "key", "https://example.test/v1", "model", batch_size=64)

    assert len(vectors) == 200
    assert [len(call["json"]["input"]) for call in _CapturingAsyncClient.calls] == [64, 64, 64, 8]


@pytest.mark.asyncio
async def test_provider_limit_is_configurable_via_batch_size_arg() -> None:
    from chunk_vector_store import _batch_embed

    vectors = await _batch_embed([f"text-{index}" for index in range(200)], "key", "https://example.test/v1", "model", batch_size=32)

    assert len(vectors) == 200
    assert [len(call["json"]["input"]) for call in _CapturingAsyncClient.calls] == [32, 32, 32, 32, 32, 32, 8]


@pytest.mark.asyncio
async def test_embedding_batch_size_env_override() -> None:
    from chunk_vector_store import _batch_embed

    os.environ["EMBEDDING_BATCH_SIZE"] = "16"
    try:
        vectors = await _batch_embed([f"text-{index}" for index in range(200)], "key", "https://example.test/v1", "model")
    finally:
        os.environ.pop("EMBEDDING_BATCH_SIZE", None)

    assert len(vectors) == 200
    assert [len(call["json"]["input"]) for call in _CapturingAsyncClient.calls] == [16] * 12 + [8]


@pytest.mark.asyncio
async def test_empty_input_returns_empty_without_request() -> None:
    from chunk_vector_store import _batch_embed

    vectors = await _batch_embed([], "key", "https://example.test/v1", "model", batch_size=64)

    assert vectors == []
    assert _CapturingAsyncClient.calls == []


@pytest.mark.asyncio
async def test_batch_embed_does_not_duplicate_embeddings_suffix() -> None:
    from chunk_vector_store import _batch_embed

    vectors = await _batch_embed(
        ["text-a", "text-b"],
        "key",
        "https://example.test/v1/embeddings",
        "model",
        batch_size=64,
    )

    assert len(vectors) == 2
    assert _CapturingAsyncClient.calls[0]["url"] == "https://example.test/v1/embeddings"


@pytest.mark.asyncio
async def test_single_text_gateway_path_does_not_duplicate_embeddings_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import chunk_vector_store as cvs
    from chunk_vector_store import _batch_embed

    captured: dict[str, str] = {}

    class _SyncResponse:
        status_code = 200
        text = "OK"

        def json(self) -> dict[str, list[dict[str, Any]]]:
            return {"data": [{"index": 0, "embedding": [0.0] * cvs.EMBEDDING_DIM}]}

    class _SyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_SyncClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _SyncResponse:
            del headers, json
            captured["url"] = url
            return _SyncResponse()

    monkeypatch.setattr(cvs.httpx, "Client", _SyncClient)
    monkeypatch.setattr(cvs, "gated_call", lambda **kwargs: kwargs["invoke"]())

    vectors = await _batch_embed(
        ["text-a"],
        "key",
        "https://example.test/v1/embeddings",
        "model",
        batch_size=64,
    )

    assert len(vectors) == 1
    assert captured["url"] == "https://example.test/v1/embeddings"


@pytest.mark.asyncio
async def test_single_text_gateway_path_applies_provider_rate_limit_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from chunk_vector_store import _batch_embed

    captured: list[dict[str, Any]] = []

    class _SyncResponse:
        status_code = 200
        text = "OK"

        def json(self) -> dict[str, list[dict[str, Any]]]:
            return {"data": [{"index": 0, "embedding": [0.0] * cvs.EMBEDDING_DIM}]}

    class _SyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_SyncClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _SyncResponse:
            del url, headers, json
            return _SyncResponse()

    def _fake_wait(base_url: str | None, *, kind: str, token_count: int) -> float:
        captured.append({"base_url": base_url, "kind": kind, "token_count": token_count})
        return 0.0

    monkeypatch.setattr(cvs.httpx, "Client", _SyncClient)
    monkeypatch.setattr(cvs, "gated_call", lambda **kwargs: kwargs["invoke"]())
    monkeypatch.setattr(cvs.provider_rate_limit, "maybe_wait_for_rate_limit_sync", _fake_wait)

    vectors = await _batch_embed(
        ["text-a"],
        "key",
        "https://api.siliconflow.cn/v1/embeddings",
        "model",
        batch_size=64,
    )

    assert len(vectors) == 1
    assert captured == [
        {
            "base_url": "https://api.siliconflow.cn/v1/embeddings",
            "kind": "embedding",
            "token_count": 1,
        }
    ]


@pytest.mark.asyncio
async def test_single_text_dashscope_multimodal_uses_provider_aware_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import chunk_vector_store as cvs
    from chunk_vector_store import _batch_embed

    captured: dict[str, Any] = {}

    class _SyncResponse:
        status_code = 200
        text = "OK"

        def json(self) -> dict[str, Any]:
            return {
                "output": {
                    "embeddings": [
                        {"embedding": [0.0] * cvs.EMBEDDING_DIM},
                    ]
                }
            }

    class _SyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_SyncClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _SyncResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _SyncResponse()

    monkeypatch.setattr(cvs.httpx, "Client", _SyncClient)
    monkeypatch.setattr(cvs, "gated_call", lambda **kwargs: kwargs["invoke"]())

    vectors = await _batch_embed(
        ["text-a"],
        "key",
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding",
        "multimodal-embedding-v1",
        batch_size=64,
    )

    assert len(vectors) == 1
    assert captured["url"] == (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding"
    )
    assert captured["headers"]["Authorization"] == "Bearer key"
    assert captured["json"] == {
        "model": "multimodal-embedding-v1",
        "input": {"contents": [{"text": "text-a"}]},
    }


@pytest.mark.asyncio
async def test_batch_embed_dashscope_multimodal_uses_provider_aware_payload() -> None:
    import chunk_vector_store as cvs
    from chunk_vector_store import _batch_embed

    class _DashScopeAsyncResponse:
        status_code = 200
        text = "OK"

        def json(self) -> dict[str, Any]:
            return {
                "output": {
                    "embeddings": [
                        {"embedding": [0.0] * cvs.EMBEDDING_DIM},
                        {"embedding": [1.0] * cvs.EMBEDDING_DIM},
                    ]
                }
            }

    class _DashScopeAsyncClient:
        calls: list[dict[str, Any]] = []

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_DashScopeAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _DashScopeAsyncResponse:
            self.calls.append({"url": url, "headers": headers, "json": json})
            return _DashScopeAsyncResponse()

    _DashScopeAsyncClient.calls = []
    cvs.httpx.AsyncClient = _DashScopeAsyncClient

    vectors = await _batch_embed(
        ["text-a", "text-b"],
        "key",
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding",
        "multimodal-embedding-v1",
        batch_size=64,
    )

    assert len(vectors) == 2
    assert _DashScopeAsyncClient.calls[0]["url"] == (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding"
    )
    assert _DashScopeAsyncClient.calls[0]["headers"]["Authorization"] == "Bearer key"
    assert _DashScopeAsyncClient.calls[0]["json"] == {
        "model": "multimodal-embedding-v1",
        "input": {"contents": [{"text": "text-a"}, {"text": "text-b"}]},
    }


@pytest.mark.asyncio
async def test_batch_embed_dashscope_multimodal_caps_batch_size_at_20() -> None:
    import chunk_vector_store as cvs
    from chunk_vector_store import _batch_embed

    class _DashScopeLimitedAsyncResponse:
        status_code = 200
        text = "OK"

        def __init__(self, count: int) -> None:
            self._count = count

        def json(self) -> dict[str, Any]:
            return {
                "output": {
                    "embeddings": [
                        {"embedding": [float(index)] * cvs.EMBEDDING_DIM}
                        for index in range(self._count)
                    ]
                }
            }

    class _DashScopeLimitedAsyncClient:
        calls: list[dict[str, Any]] = []

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_DashScopeLimitedAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _DashScopeLimitedAsyncResponse:
            self.calls.append({"url": url, "headers": headers, "json": json})
            contents = json["input"]["contents"]
            return _DashScopeLimitedAsyncResponse(len(contents))

    _DashScopeLimitedAsyncClient.calls = []
    cvs.httpx.AsyncClient = _DashScopeLimitedAsyncClient

    vectors = await _batch_embed(
        [f"text-{index}" for index in range(45)],
        "key",
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding",
        "qwen3-vl-embedding",
    )

    assert len(vectors) == 45
    assert [len(call["json"]["input"]["contents"]) for call in _DashScopeLimitedAsyncClient.calls] == [20, 20, 5]


@pytest.mark.asyncio
async def test_single_text_gateway_path_truncates_oversized_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import chunk_vector_store as cvs
    from chunk_vector_store import _batch_embed

    class _SyncResponse:
        status_code = 200
        text = "OK"

        def json(self) -> dict[str, list[dict[str, Any]]]:
            return {
                "data": [
                    {"index": 0, "embedding": [0.1] * (cvs.EMBEDDING_DIM + 16)},
                ]
            }

    class _SyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_SyncClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _SyncResponse:
            del url, headers, json
            return _SyncResponse()

    monkeypatch.setattr(cvs.httpx, "Client", _SyncClient)
    monkeypatch.setattr(cvs, "gated_call", lambda **kwargs: kwargs["invoke"]())

    vectors = await _batch_embed(
        ["text-a"],
        "key",
        "https://example.test/v1/embeddings",
        "model",
        batch_size=64,
    )

    assert len(vectors) == 1
    assert len(vectors[0]) == cvs.EMBEDDING_DIM


@pytest.mark.asyncio
async def test_batch_embed_truncates_oversized_vectors() -> None:
    import chunk_vector_store as cvs
    from chunk_vector_store import _batch_embed

    class _OversizedAsyncResponse:
        status_code = 200
        text = "OK"

        def json(self) -> dict[str, list[dict[str, Any]]]:
            return {
                "data": [
                    {"index": 0, "embedding": [0.1] * (cvs.EMBEDDING_DIM + 16)},
                    {"index": 1, "embedding": [0.2] * (cvs.EMBEDDING_DIM + 16)},
                ]
            }

    class _OversizedAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_OversizedAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _OversizedAsyncResponse:
            del url, headers, json
            return _OversizedAsyncResponse()

    cvs.httpx.AsyncClient = _OversizedAsyncClient

    vectors = await _batch_embed(
        ["text-a", "text-b"],
        "key",
        "https://example.test/v1",
        "model",
        batch_size=64,
    )

    assert len(vectors) == 2
    assert all(len(vector) == cvs.EMBEDDING_DIM for vector in vectors)


@pytest.mark.asyncio
async def test_batch_embed_query_path_does_not_apply_chunk_hard_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import chunk_vector_store as cvs

    monkeypatch.setattr(
        cvs,
        "inspect_text",
        lambda _text: {
            "is_oversize": True,
            "char_count": 7000,
            "max_chars": 6000,
            "token_count": 1300,
            "max_tokens": 1200,
        },
    )
    monkeypatch.setattr(cvs, "count_tokens", lambda _text: 1300)
    monkeypatch.setattr(cvs, "_invoke_embedding_http", lambda *_args, **_kwargs: [0.3] * cvs.EMBEDDING_DIM)

    vectors = await cvs._batch_embed(
        ["word " * 1300],
        "key",
        "https://example.test/v1",
        "model",
        batch_size=1,
    )

    assert len(vectors) == 1


@pytest.mark.asyncio
async def test_batch_embed_rotates_to_next_credential_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import chunk_vector_store as cvs

    keys_seen: list[str] = []

    class _FailoverResponse:
        def __init__(self, status_code: int, count: int = 0, text: str = "") -> None:
            self.status_code = status_code
            self._count = count
            self.text = text

        def json(self) -> dict[str, list[dict[str, Any]]]:
            return {
                "data": [
                    {"index": index, "embedding": [float(index)] * cvs.EMBEDDING_DIM}
                    for index in range(self._count)
                ]
            }

    class _FailoverAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_FailoverAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _FailoverResponse:
            del url
            key = headers["Authorization"].split()[-1]
            payload_input = json.get("input")
            if not isinstance(payload_input, list):
                raise AssertionError("embedding payload input must be a list")
            keys_seen.append(key)
            if key == "bad-key":
                return _FailoverResponse(403, text="quota exhausted")
            return _FailoverResponse(200, count=len(payload_input), text="OK")

    class _FailoverSyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> "_FailoverSyncClient":
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> _FailoverResponse:
            del url
            key = headers["Authorization"].split()[-1]
            payload_input = json.get("input")
            if not isinstance(payload_input, list):
                raise AssertionError("embedding payload input must be a list")
            keys_seen.append(key)
            if key == "bad-key":
                return _FailoverResponse(403, text="quota exhausted")
            return _FailoverResponse(200, count=len(payload_input), text="OK")

    monkeypatch.setattr(cvs.httpx, "AsyncClient", _FailoverAsyncClient)
    monkeypatch.setattr(cvs.httpx, "Client", _FailoverSyncClient)
    monkeypatch.setattr(cvs, "gated_call", lambda **kwargs: kwargs["invoke"]())
    monkeypatch.setattr(
        cvs,
        "resolve_embedding_candidates",
        lambda *args, **kwargs: [
            ("bad-key", "https://bad.example/v1", "model-a", "bad"),
            ("good-key", "https://good.example/v1", "model-b", "good"),
        ],
    )

    pool = cvs._make_embedding_failover_pool(
        default_base_url="https://default.example/v1",
        default_model="model-a",
    )
    assert pool is not None

    vectors = await cvs._batch_embed(
        ["text-a", "text-b"],
        "bad-key",
        "https://bad.example/v1",
        "model-a",
        batch_size=64,
        credential_pool=pool,
    )

    assert len(vectors) == 2
    assert keys_seen == ["bad-key", "good-key"]

    keys_seen.clear()
    vectors = await cvs._batch_embed(
        ["text-c"],
        "bad-key",
        "https://bad.example/v1",
        "model-a",
        batch_size=64,
        credential_pool=pool,
    )

    assert len(vectors) == 1
    assert keys_seen == ["good-key"]
