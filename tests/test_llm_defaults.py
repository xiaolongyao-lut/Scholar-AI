from __future__ import annotations

import pytest

from llm_defaults import MODEL_MAX_TOKENS, TASK_DEFAULTS, resolve_llm_params


def test_resolve_llm_params_returns_task_defaults() -> None:
    out = resolve_llm_params("chat")

    assert out == TASK_DEFAULTS["chat"]


def test_resolve_llm_params_applies_partial_override() -> None:
    out = resolve_llm_params("summarization", {"temperature": 0.6, "max_tokens": 1024})

    assert out["temperature"] == 0.6
    assert out["max_tokens"] == 1024
    assert out["top_p"] == TASK_DEFAULTS["summarization"]["top_p"]
    assert out["top_k"] == TASK_DEFAULTS["summarization"]["top_k"]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"temperature": 2.5}, "temperature"),
        ({"top_p": 0}, "top_p"),
        ({"top_k": 0}, "top_k"),
        ({"max_tokens": MODEL_MAX_TOKENS + 1}, "max_tokens"),
    ],
)
def test_resolve_llm_params_rejects_out_of_range_values(override: dict[str, float | int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_llm_params("chat", override)
