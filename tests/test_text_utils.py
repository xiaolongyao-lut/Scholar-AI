"""Focused tests for CJK-aware fallback tokenization."""

from __future__ import annotations

import pytest

from rag_integration_entry import _create_passthrough_router
from text_utils import cjk_aware_tokenize


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("强化学习应用", ["强化", "化学", "学习", "习应", "应用"]),
        ("deep reinforcement learning", ["deep", "reinforcement", "learning"]),
        ("GAN 网络", ["GAN", "网络"]),
        ("", []),
        ("学习, 应用!", ["学习", "应用"]),
        ("学", ["学"]),
        ("GPT-4 模型", ["GPT", "4", "模型"]),
        ("学习🙂应用🚀", ["学习", "应用"]),
    ],
)
def test_cjk_aware_tokenize_contract_matrix(query: str, expected: list[str]):
    assert cjk_aware_tokenize(query) == expected


async def test_passthrough_router_uses_cjk_aware_fallback_tokens():
    router = _create_passthrough_router({})

    assert await router.route_query("激光焊接", top_k=2) == ["激光", "光焊"]
