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

import pytest

# Tests run with the standard test bootstrap; importing directly is fine.
_CORE = Path(__file__).resolve().parents[1] / "literature_assistant" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from chunk_vector_store import (  # noqa: E402
    EMBEDDING_DIM,
    _embed_dimensions_arg,
    _model_accepts_dimensions,
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
