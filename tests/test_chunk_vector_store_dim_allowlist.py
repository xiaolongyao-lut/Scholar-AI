"""Lock the per-model dimensions allow-list introduced for bge-m3 backfill.

Why:
    SiliconFlow's ``BAAI/bge-m3`` returns HTTP 400 ``code=20015 parameter is
    invalid`` when ``dimensions`` is included in the embeddings request, because
    bge-m3 is natively 1024-dim and does not expose runtime truncation. The
    previous code path hard-coded ``dimensions=EMBEDDING_DIM`` for every model,
    which silently broke any non-Qwen3 embedding model.

    These tests pin the policy: only models that explicitly support runtime
    dimension selection (Qwen3-Embedding family, OpenAI text-embedding-3 family)
    get the parameter; everyone else, including bge-m3, must not.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Tests run with the standard test bootstrap; importing directly is fine.
_CORE = Path(__file__).resolve().parents[1] / "literature_assistant" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import chunk_vector_store as cvs  # noqa: E402
from chunk_vector_store import (  # noqa: E402
    EMBEDDING_DIM,
    EmbeddingAPIError,
    _embed_dimensions_arg,
    _model_accepts_dimensions,
    batch_embed_texts,
)


@pytest.mark.parametrize(
    "model",
    [
        "Qwen/Qwen3-Embedding-8B",
        "Qwen/Qwen3-Embedding-4B",
        "qwen/qwen3-embedding-8b",  # case-insensitive
        "text-embedding-3-small",
        "text-embedding-3-large",
    ],
)
def test_models_that_accept_dimensions(model: str) -> None:
    assert _model_accepts_dimensions(model) is True
    assert _embed_dimensions_arg(model) == EMBEDDING_DIM


@pytest.mark.parametrize(
    "model",
    [
        "BAAI/bge-m3",
        "BAAI/bge-m3-multilingual",
        "BAAI/bge-large-en-v1.5",
        "BAAI/bge-reranker-v2-m3",
        "netease-youdao/bce-embedding-base_v1",
        "text-embedding-ada-002",  # legacy OpenAI — no dimensions param
        "",
        None,
    ],
)
def test_models_that_reject_dimensions(model: str | None) -> None:
    assert _model_accepts_dimensions(model) is False
    assert _embed_dimensions_arg(model) is None


@pytest.mark.asyncio
async def test_batch_embed_texts_strict_contract_does_not_build_failover_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys_seen: list[str] = []

    class _StrictResponse:
        status_code = 403
        text = "quota exhausted"

        def json(self) -> dict[str, list[dict[str, Any]]]:
            return {"data": []}

    class _StrictAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_StrictAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
        ) -> _StrictResponse:
            del url
            payload_input = json.get("input")
            if not isinstance(payload_input, list):
                raise AssertionError("embedding payload input must be a list")
            keys_seen.append(headers["Authorization"].split()[-1])
            return _StrictResponse()

    async def _skip_rate_limit(*args: Any, **kwargs: Any) -> float:
        return 0.0

    monkeypatch.setattr(cvs.httpx, "AsyncClient", _StrictAsyncClient)
    monkeypatch.setattr(cvs.provider_rate_limit, "maybe_wait_for_rate_limit_async", _skip_rate_limit)
    monkeypatch.setattr(
        cvs,
        "resolve_embedding_config",
        lambda *args, **kwargs: ("bad-key", "https://api.siliconflow.cn/v1", "BAAI/bge-m3"),
    )

    def _unexpected_failover_pool(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("strict_contract must not build a failover pool")

    monkeypatch.setattr(cvs, "_make_embedding_failover_pool", _unexpected_failover_pool)

    with pytest.raises(EmbeddingAPIError, match="last_status=403"):
        await batch_embed_texts(
            ["text-a", "text-b"],
            base_url="https://api.siliconflow.cn/v1",
            model="BAAI/bge-m3",
            batch_size=64,
            strict_contract=True,
        )

    assert keys_seen == ["bad-key"]
