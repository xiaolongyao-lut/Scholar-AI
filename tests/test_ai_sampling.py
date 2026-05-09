"""Tests for ai_sampling.resolve_sampling."""

from __future__ import annotations

import pytest

from ai_sampling import LLM_SAMPLING_DEFAULTS, resolve_sampling


@pytest.mark.parametrize("task_type", list(LLM_SAMPLING_DEFAULTS.keys()))
def test_known_task_types_return_defaults(task_type: str) -> None:
    out = resolve_sampling(task_type)
    expected = LLM_SAMPLING_DEFAULTS[task_type]
    assert out["temperature"] == expected["temperature"]
    assert out["top_p"] == expected["top_p"]


def test_unknown_task_falls_back_to_default() -> None:
    out = resolve_sampling("nonsense_task_xyz")
    assert out == LLM_SAMPLING_DEFAULTS["default"]


def test_none_task_falls_back_to_default() -> None:
    out = resolve_sampling(None)
    assert out == LLM_SAMPLING_DEFAULTS["default"]


def test_override_wins_per_key() -> None:
    out = resolve_sampling("focus_extract", override={"temperature": 0.9})
    assert out["temperature"] == 0.9
    # top_p untouched, falls through from default
    assert out["top_p"] == LLM_SAMPLING_DEFAULTS["focus_extract"]["top_p"]


def test_override_accepts_extra_allowed_keys() -> None:
    out = resolve_sampling(
        "default",
        override={"top_k": 40, "presence_penalty": 0.2, "frequency_penalty": 0.1},
    )
    assert out["top_k"] == 40
    assert out["presence_penalty"] == 0.2
    assert out["frequency_penalty"] == 0.1


def test_override_ignores_unknown_keys() -> None:
    out = resolve_sampling("default", override={"bogus": 999, "temperature": 0.5})
    assert "bogus" not in out
    assert out["temperature"] == 0.5


def test_override_drops_uncoercible_values() -> None:
    out = resolve_sampling("default", override={"temperature": "not-a-number"})
    assert out["temperature"] == LLM_SAMPLING_DEFAULTS["default"]["temperature"]


def test_override_rejects_boolean() -> None:
    out = resolve_sampling("default", override={"temperature": True})
    assert out["temperature"] == LLM_SAMPLING_DEFAULTS["default"]["temperature"]


def test_string_numeric_override_coerced() -> None:
    out = resolve_sampling("summarize", override={"top_p": "0.42"})
    assert out["top_p"] == pytest.approx(0.42)


def test_case_insensitive_task_type() -> None:
    assert resolve_sampling("CREATIVE") == resolve_sampling("creative")
