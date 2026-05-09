import asyncio
import json

from key_pool import Credential, KeyPool
from layers.r_layer_hybrid_retriever import ContextAwareRetriever
from layers.semantic_router import SemanticRouter


def _disable_local_dotenv(monkeypatch):
    monkeypatch.setenv("RUNTIME_ENV_DISABLE_DOTENV", "1")


def _embedding_pool() -> KeyPool:
    return KeyPool(
        {
            "embedding": [
                Credential(
                    category="embedding",
                    provider="bad-gateway",
                    api_key="bad-key",
                    base_url="https://bad.example/v1/embeddings",
                    model="bad-model",
                ),
                Credential(
                    category="embedding",
                    provider="good-gateway",
                    api_key="good-key",
                    base_url="https://good.example/v1/embeddings",
                    model="good-model",
                ),
            ],
            "rerank": [],
            "generation": [],
        },
        cooldown_seconds=3600.0,
    )


def test_context_aware_retriever_rotates_failed_embedding_credential(monkeypatch):
    _disable_local_dotenv(monkeypatch)

    import layers.r_layer_hybrid_retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "build_embedding_failover_pool", lambda **_kwargs: _embedding_pool())

    retriever = ContextAwareRetriever()
    attempts: list[tuple[str, str, str]] = []

    async def fake_embed_query_once(query, api_key, base_url, model):
        attempts.append((api_key, base_url, model))
        if api_key == "bad-key":
            raise RuntimeError("primary embedding credential failed")
        return [0.1, 0.2, 0.3]

    retriever._embed_query_once = fake_embed_query_once

    first = asyncio.run(retriever._embed_query("laser query"))
    second = asyncio.run(retriever._embed_query("laser query again"))

    assert first == [0.1, 0.2, 0.3]
    assert second == [0.1, 0.2, 0.3]
    assert attempts == [
        ("bad-key", "https://bad.example/v1/embeddings", "bad-model"),
        ("good-key", "https://good.example/v1/embeddings", "good-model"),
        ("good-key", "https://good.example/v1/embeddings", "good-model"),
    ]


def test_context_aware_retriever_uses_dashscope_multimodal_payload(monkeypatch):
    _disable_local_dotenv(monkeypatch)

    import layers.r_layer_hybrid_retriever as retriever_mod

    class FakeResponse:
        status_code = 200
        text = "OK"

        def json(self):
            return {
                "output": {
                    "embeddings": [
                        {"embedding": [0.1, 0.2, 0.3]},
                    ]
                }
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            assert url == (
                "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
                "multimodal-embedding/multimodal-embedding"
            )
            assert headers["Authorization"] == "Bearer dashscope-key"
            assert json == {
                "model": "multimodal-embedding-v1",
                "input": {"contents": [{"text": "laser query"}]},
            }
            return FakeResponse()

    monkeypatch.setattr(retriever_mod.httpx, "AsyncClient", FakeAsyncClient)

    retriever = ContextAwareRetriever()
    vector = asyncio.run(
        retriever._embed_query_once(
            "laser query",
            "dashscope-key",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding",
            "multimodal-embedding-v1",
        )
    )

    assert vector == [0.1, 0.2, 0.3]


def test_semantic_router_rotates_failed_embedding_credential(monkeypatch, tmp_path):
    _disable_local_dotenv(monkeypatch)

    import layers.semantic_router as router_mod

    monkeypatch.setattr(router_mod, "build_embedding_failover_pool", lambda **_kwargs: _embedding_pool())

    focus_points_path = tmp_path / "focus_points.json"
    focus_points_path.write_text(json.dumps({"points": ["laser", "grain"]}), encoding="utf-8")

    router = SemanticRouter(
        api_key="bootstrap-key",
        focus_points_path=str(focus_points_path),
        lazy_vectorize=True,
    )
    attempts: list[tuple[str, str, str]] = []

    async def fake_call_embedding_api_once(texts, api_key, base_url, model):
        attempts.append((api_key, base_url, model))
        if api_key == "bad-key":
            raise RuntimeError("primary embedding credential failed")
        return [[0.1, 0.2, 0.3] for _ in texts]

    router._call_embedding_api_once = fake_call_embedding_api_once

    first = asyncio.run(router._call_embedding_api(["laser", "grain"]))
    second = asyncio.run(router._call_embedding_api(["powder"]))
    asyncio.run(router.close())

    assert first == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    assert second == [[0.1, 0.2, 0.3]]
    assert attempts == [
        ("bad-key", "https://bad.example/v1/embeddings", "bad-model"),
        ("good-key", "https://good.example/v1/embeddings", "good-model"),
        ("good-key", "https://good.example/v1/embeddings", "good-model"),
    ]


def test_semantic_router_uses_dashscope_multimodal_payload(monkeypatch, tmp_path):
    _disable_local_dotenv(monkeypatch)

    import layers.semantic_router as router_mod

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def post(self, url, *, headers, json):
            assert url == (
                "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
                "multimodal-embedding/multimodal-embedding"
            )
            assert headers["Authorization"] == "Bearer dashscope-key"
            assert json == {
                "model": "multimodal-embedding-v1",
                "input": {"contents": [{"text": "laser"}]},
            }

            class _Response:
                status_code = 200
                text = "OK"

                def json(self):
                    return {
                        "output": {
                            "embeddings": [
                                {"embedding": [0.1, 0.2, 0.3]},
                            ]
                        }
                    }

            return _Response()

        async def aclose(self):
            return None

    monkeypatch.setattr(router_mod.httpx, "AsyncClient", lambda *a, **kw: FakeClient())

    focus_points_path = tmp_path / "focus_points.json"
    focus_points_path.write_text(json.dumps({"points": ["laser"]}), encoding="utf-8")

    router = SemanticRouter(
        api_key="dashscope-key",
        focus_points_path=str(focus_points_path),
        base_url=(
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding"
        ),
        embedding_model="multimodal-embedding-v1",
        lazy_vectorize=True,
    )

    vectors = asyncio.run(
        router._call_embedding_api_once(
            ["laser"],
            "dashscope-key",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding",
            "multimodal-embedding-v1",
        )
    )
    asyncio.run(router.close())

    assert vectors == [[0.1, 0.2, 0.3]]