"""Unit tests for token_utils."""

from __future__ import annotations

import pytest

from token_utils import count_tokens, split_by_tokens, truncate_to_tokens


def test_count_tokens_empty():
    assert count_tokens("") == 0


def test_count_tokens_short_cjk():
    # Short CJK string should produce a small but positive token count
    n = count_tokens("激光焊接的最新研究进展")
    assert 5 <= n <= 40


def test_split_by_tokens_under_limit_returns_one_piece():
    text = "激光焊接钛合金的微观组织演化"
    pieces = split_by_tokens(text, max_tokens=100)
    assert pieces == [text]


def test_split_by_tokens_over_limit_produces_all_fit():
    long_text = "激光焊接钛合金。" * 2000  # well over any realistic limit
    max_tokens = 500
    pieces = split_by_tokens(long_text, max_tokens=max_tokens)
    assert len(pieces) > 1
    for p in pieces:
        assert count_tokens(p) <= max_tokens, (
            f"piece over limit: {count_tokens(p)} > {max_tokens}"
        )
    # Sanity: concatenated pieces cover the majority of original content.
    joined = "".join(pieces)
    assert len(joined) >= int(len(long_text) * 0.8)


def test_truncate_to_tokens_respects_limit():
    long_text = "激光焊接" * 3000
    truncated = truncate_to_tokens(long_text, max_tokens=100)
    assert count_tokens(truncated) <= 100
    assert truncated and long_text.startswith(truncated[: min(len(truncated), 20)])


def test_truncate_to_tokens_zero_limit_returns_empty():
    assert truncate_to_tokens("anything", 0) == ""


def test_split_by_tokens_on_paragraphs():
    chunks = ["激光焊接介绍。" * 50, "微观组织演化。" * 50, "力学性能。" * 50]
    text = "\n\n".join(chunks)
    # Each paragraph comfortably under 1000 tokens; packing should yield ≤3 pieces.
    pieces = split_by_tokens(text, max_tokens=1000)
    assert 1 <= len(pieces) <= 3
    for p in pieces:
        assert count_tokens(p) <= 1000
