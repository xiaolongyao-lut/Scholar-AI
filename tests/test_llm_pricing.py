from __future__ import annotations

import types

from llm_pricing import (
    _FALLBACK_PRICING,
    estimate_cost_usd,
    is_known_model,
    lookup_pricing,
    usage_from_response,
)


def test_lookup_pricing_returns_known_value_for_exact_model() -> None:
    assert lookup_pricing("gpt-4o") == (2.50, 10.00)
    assert is_known_model("gpt-4o") is True


def test_lookup_pricing_matches_versioned_model_prefix() -> None:
    assert lookup_pricing("gpt-4o-2026-99-99") == (2.50, 10.00)
    assert is_known_model("gpt-4o-2026-99-99") is True


def test_lookup_pricing_uses_fallback_for_unknown_model() -> None:
    assert lookup_pricing("totally-unknown-xyz") == _FALLBACK_PRICING
    assert is_known_model("totally-unknown-xyz") is False


def test_estimate_cost_usd_computes_expected_math() -> None:
    assert estimate_cost_usd("gpt-4o", prompt_tokens=1000, completion_tokens=500) == 0.0075


def test_estimate_cost_usd_returns_zero_for_zero_tokens() -> None:
    assert estimate_cost_usd("x", prompt_tokens=0, completion_tokens=0) == 0.0


def test_estimate_cost_usd_clamps_negative_tokens_without_raising() -> None:
    cost = estimate_cost_usd("x", prompt_tokens=-10, completion_tokens=10)

    assert cost == estimate_cost_usd("x", prompt_tokens=0, completion_tokens=10)


def test_usage_from_response_reads_openai_style_usage_object() -> None:
    response = types.SimpleNamespace(
        usage=types.SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20)
    )

    assert usage_from_response(response) == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


def test_usage_from_response_reads_dict_usage() -> None:
    response = {"usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}}

    assert usage_from_response(response) == {
        "prompt_tokens": 9,
        "completion_tokens": 4,
        "total_tokens": 13,
    }


def test_usage_from_response_returns_zeroes_for_missing_usage() -> None:
    assert usage_from_response(None) == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
