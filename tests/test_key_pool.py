"""Tests for ``key_pool`` parser and rotation helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from key_pool import Credential, KeyPool, parse_env_pools


FIXTURE_ENV = """\
##\u4e13\u95e8\u7528\u6765\u6d4b\u8bd5\u7684api\uff0c\u6279\u51c6\u8c03\u7528##
####\u963f\u91cc\u9650\u65f6\u514d\u8d39\u4f18\u5148\u4f7f\u7528####
KEY=sk-top-1
#embeding
URL=https://dashscope.aliyuncs.com/embeddings
MODEL=text-embedding-v4
MODEL=text-embedding-v3
#rerank
URL=https://dashscope.aliyuncs.com/rerank
MODEL=gte-rerank-v2

##embeding##
##\u963f\u91cc\u4e91\u5b98\u65b9##
API_KEY=sk-ali-emb-1
BASE_URL=https://dashscope.aliyuncs.com/embeddings
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_MODEL=text-embedding-async-v2

##\u706b\u5c71\u534f\u4f5c##
API_KEY=sk-volc-emb-1
BASE_URL=https://ark.cn-beijing.volces.com/embeddings
EMBEDDING_MODEL=doubao-embedding-large-text-240515

##rerank##
##\u963f\u91cc\u4e91\u5b98\u65b9##
RERANK_API_KEY=sk-ali-rr-1
RERANK_BASE_URL=https://dashscope.aliyuncs.com/rerank
RERANK_MODEL=gte-rerank-v2

##\u56de\u7b54\u6a21\u578b##
##\u706b\u5c71##
ARK_API_KEY=sk-ark-1
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=doubao-1-5-pro-32k-250115
ARK_MODEL=doubao-pro-256k-241218

##\u963f\u91cc##
ARK_API_KEY=sk-ark-2
ARK_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ARK_MODEL=qwen-max
"""


@pytest.fixture()
def fixture_env(tmp_path: Path) -> Path:
    p = tmp_path / ".env"
    p.write_text(FIXTURE_ENV, encoding="utf-8")
    return p


def test_parse_categories_split_correctly(fixture_env: Path) -> None:
    pools = parse_env_pools(fixture_env)
    assert set(pools.keys()) == {"embedding", "rerank", "generation"}
    # legacy top section: 2 embedding models + 1 rerank model under one key
    # plus 2 ali emb + 1 volc emb in dedicated section = 5 embedding rows
    assert len(pools["embedding"]) == 5
    # legacy 1 rerank model + 1 ali rerank model = 2 rerank rows
    assert len(pools["rerank"]) == 2
    # 2 ark + 1 ali generation = 3 generation rows
    assert len(pools["generation"]) == 3


def test_parse_preserves_keys_urls_models_verbatim(fixture_env: Path) -> None:
    pools = parse_env_pools(fixture_env)
    emb_models = {c.model for c in pools["embedding"]}
    assert "text-embedding-v4" in emb_models
    assert "doubao-embedding-large-text-240515" in emb_models
    keys = {c.api_key for c in pools["embedding"]}
    assert "sk-ali-emb-1" in keys and "sk-volc-emb-1" in keys


def test_legacy_section_url_flip_classifies_models(fixture_env: Path) -> None:
    pools = parse_env_pools(fixture_env)
    legacy_emb = [c for c in pools["embedding"] if c.api_key == "sk-top-1"]
    legacy_rr = [c for c in pools["rerank"] if c.api_key == "sk-top-1"]
    assert {c.model for c in legacy_emb} == {"text-embedding-v4", "text-embedding-v3"}
    assert {c.model for c in legacy_rr} == {"gte-rerank-v2"}


def test_try_call_iterates_until_success() -> None:
    creds = [
        Credential("embedding", "p1", "k1", "u1", "m1"),
        Credential("embedding", "p2", "k2", "u2", "m2"),
        Credential("embedding", "p3", "k3", "u3", "m3"),
    ]
    pool = KeyPool({"embedding": creds, "rerank": [], "generation": []})

    attempts: list[str] = []

    def fn(c: Credential) -> str:
        attempts.append(c.model)
        if c.model in ("m1", "m2"):
            raise RuntimeError("HTTP 401 Unauthorized")
        return "ok"

    assert pool.try_call("embedding", fn) == "ok"
    assert attempts == ["m1", "m2", "m3"]


def test_try_call_raises_when_all_fail() -> None:
    creds = [
        Credential("rerank", "p1", "k1", "u1", "m1"),
        Credential("rerank", "p2", "k2", "u2", "m2"),
    ]
    pool = KeyPool({"embedding": [], "rerank": creds, "generation": []})

    def fn(_c: Credential) -> str:
        raise RuntimeError("HTTP 401")

    with pytest.raises(RuntimeError, match="401"):
        pool.try_call("rerank", fn)


def test_try_call_skips_cooled_down_creds() -> None:
    cred = Credential("generation", "p", "k", "u", "m")
    pool = KeyPool({"embedding": [], "rerank": [], "generation": [cred]}, cooldown_seconds=10)

    def boom(_c: Credential) -> str:
        raise RuntimeError("HTTP 401")

    with pytest.raises(RuntimeError):
        pool.try_call("generation", boom)
    # second call: cred is cooled down, no creds to try -> RuntimeError "no credentials available"
    with pytest.raises(RuntimeError, match="no credentials available"):
        pool.try_call("generation", boom)


def test_empty_env_returns_empty_pools(tmp_path: Path) -> None:
    p = tmp_path / "missing.env"
    pools = parse_env_pools(p)
    assert pools == {"embedding": [], "rerank": [], "generation": []}


def test_explicit_typed_embedding_key_not_collapsed_into_generic_prefix(tmp_path: Path) -> None:
    """Typed embedding credentials must remain first-class in pool parsing."""
    p = tmp_path / ".env"
    p.write_text(
        "\n".join(
            [
                "##embeding##",
                "SILICONFLOW_EMBEDDING_API_KEY=typed-embed-key",
                "SILICONFLOW_EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1/embeddings",
                "SILICONFLOW_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B",
                "API_KEY=generic-key",
                "BASE_URL=https://generic.example/v1",
                "MODEL=generic-model",
            ]
        ),
        encoding="utf-8",
    )

    pools = parse_env_pools(p)
    assert pools["embedding"], "typed embedding credential should produce an embedding pool entry"
    assert pools["embedding"][0].api_key == "typed-embed-key"


def test_semantic_embedding_shape_overrides_misleading_rerank_prefix(tmp_path: Path) -> None:
    """Embedding-shaped entries should be classified by endpoint/model semantics, not var prefix alone."""
    p = tmp_path / ".env"
    p.write_text(
        "\n".join(
            [
                "##embeding##",
                "SILICONFLOW_API_KEY=typed-embed-key",
                "RERANK_BASE_URL=https://api.siliconflow.cn/v1/embeddings",
                "RERANK_MODEL=BAAI/bge-m3",
            ]
        ),
        encoding="utf-8",
    )

    pools = parse_env_pools(p)

    assert len(pools["embedding"]) == 1
    assert pools["embedding"][0].api_key == "typed-embed-key"
    assert pools["embedding"][0].base_url == "https://api.siliconflow.cn/v1/embeddings"
    assert pools["embedding"][0].model == "BAAI/bge-m3"
    assert pools["rerank"] == []


@pytest.mark.asyncio
async def test_try_call_async_blacklists_failed_credential_and_uses_next() -> None:
    creds = [
        Credential("embedding", "p1", "k1", "u1", "m1"),
        Credential("embedding", "p2", "k2", "u2", "m2"),
    ]
    pool = KeyPool({"embedding": creds, "rerank": [], "generation": []}, cooldown_seconds=30)

    attempts: list[str] = []

    async def fn(c: Credential) -> str:
        attempts.append(c.model)
        if c.model == "m1":
            raise RuntimeError("HTTP 500 upstream unavailable")
        return c.model

    result = await pool.try_call_async(
        "embedding",
        fn,
        cooldown_on=lambda _exc: True,
    )

    assert result == "m2"
    assert attempts == ["m1", "m2"]

    attempts.clear()
    reused = await pool.try_call_async(
        "embedding",
        fn,
        cooldown_on=lambda _exc: True,
    )

    assert reused == "m2"
    assert attempts == ["m2"]
