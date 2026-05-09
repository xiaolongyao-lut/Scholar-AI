"""Phase P0 hotfix tests for chat_router._extract_chat_response.

Covers two pre-existing bugs that block MCP tool-use Phase 2:

  - Claude `tool_use`-only responses must not raise just because there is
    no final text block.
  - OpenAI-compatible responses with `content=null + tool_calls` must not
    return the literal string "None".

The fix surface: caller extracts tool_calls first, then passes
``tool_calls_present`` to `_extract_chat_response`, which then tolerates
missing/null text only when tool calls are present.
"""

from __future__ import annotations

import pytest

from routers.chat_router import _extract_chat_response, _extract_tool_calls


# ---------------------------------------------------------------------------
# Claude branch
# ---------------------------------------------------------------------------


def test_claude_tool_use_only_returns_empty_answer_when_signaled() -> None:
    data = {
        "content": [
            {
                "type": "tool_use",
                "id": "tu_1",
                "name": "search",
                "input": {"q": "transformers"},
            }
        ],
        "model": "claude-opus-4-7",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    tool_calls = _extract_tool_calls(data, "Claude")
    assert tool_calls is not None and len(tool_calls) == 1

    answer, usage, model = _extract_chat_response(
        data, "Claude", "fallback-model",
        tool_calls_present=True,
    )
    assert answer == ""
    assert model == "claude-opus-4-7"
    assert usage == {"input_tokens": 10, "output_tokens": 5}


def test_claude_tool_use_only_still_raises_when_caller_did_not_signal() -> None:
    """Regression: callers that don't extract tool_calls first still get the
    historical KeyError so existing error paths keep behaving.
    """
    data = {
        "content": [
            {"type": "tool_use", "id": "tu_1", "name": "x", "input": {}}
        ]
    }
    with pytest.raises(KeyError):
        _extract_chat_response(
            data, "Claude", "fallback",
            tool_calls_present=False,
        )


def test_claude_text_plus_tool_use_mix_returns_text() -> None:
    data = {
        "content": [
            {"type": "text", "text": "Let me search."},
            {"type": "tool_use", "id": "tu_1", "name": "search", "input": {}},
        ],
        "model": "claude-opus-4-7",
    }
    answer, _, _ = _extract_chat_response(
        data, "Claude", "fb",
        tool_calls_present=True,
    )
    assert answer == "Let me search."


def test_claude_text_only_unchanged() -> None:
    data = {
        "content": [{"type": "text", "text": "Hello."}],
        "model": "claude-opus-4-7",
    }
    answer, _, model = _extract_chat_response(
        data, "Claude", "fb",
        tool_calls_present=False,
    )
    assert answer == "Hello."
    assert model == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# OpenAI-compatible branch
# ---------------------------------------------------------------------------


def test_openai_null_content_with_tool_calls_returns_empty_not_string_None() -> None:
    data = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {"name": "search", "arguments": "{}"},
                        }
                    ],
                }
            }
        ],
        "model": "gpt-4o",
    }
    tool_calls = _extract_tool_calls(data, "openai")
    assert tool_calls is not None and len(tool_calls) == 1

    answer, _, model = _extract_chat_response(
        data, "openai", "fallback",
        tool_calls_present=True,
    )
    assert answer == ""
    assert answer != "None"
    assert model == "gpt-4o"


def test_openai_null_content_without_tool_calls_raises() -> None:
    """content=null with no tool_calls is genuinely malformed; must error
    rather than return literal 'None' string.
    """
    data = {
        "choices": [{"message": {"content": None}}],
        "model": "gpt-4o",
    }
    with pytest.raises(KeyError):
        _extract_chat_response(
            data, "openai", "fb",
            tool_calls_present=False,
        )


def test_openai_string_content_returned() -> None:
    data = {
        "choices": [{"message": {"content": "hello"}}],
        "model": "gpt-4o",
    }
    answer, _, _ = _extract_chat_response(
        data, "openai", "fb",
        tool_calls_present=False,
    )
    assert answer == "hello"


def test_openai_list_content_concatenated_text_parts() -> None:
    data = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "alpha "},
                        {"type": "output_text", "text": "beta"},
                    ]
                }
            }
        ],
        "model": "gpt-4o",
    }
    answer, _, _ = _extract_chat_response(
        data, "openai", "fb",
        tool_calls_present=False,
    )
    assert answer == "alpha beta"


def test_openai_text_plus_tool_calls_mix_returns_text() -> None:
    data = {
        "choices": [
            {
                "message": {
                    "content": "About to search.",
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "x", "arguments": "{}"}}
                    ],
                }
            }
        ],
        "model": "gpt-4o",
    }
    tool_calls = _extract_tool_calls(data, "openai")
    assert tool_calls is not None
    answer, _, _ = _extract_chat_response(
        data, "openai", "fb",
        tool_calls_present=True,
    )
    assert answer == "About to search."


# ---------------------------------------------------------------------------
# Tool-call extraction shape (sanity)
# ---------------------------------------------------------------------------


def test_extract_tool_calls_returns_none_when_absent_openai() -> None:
    data = {"choices": [{"message": {"content": "hi"}}]}
    assert _extract_tool_calls(data, "openai") is None


def test_extract_tool_calls_returns_none_when_absent_claude() -> None:
    data = {"content": [{"type": "text", "text": "hi"}]}
    assert _extract_tool_calls(data, "Claude") is None


def test_extract_tool_calls_claude_shape() -> None:
    data = {
        "content": [
            {
                "type": "tool_use",
                "id": "tu_1",
                "name": "search",
                "input": {"q": "transformers"},
            }
        ]
    }
    out = _extract_tool_calls(data, "Claude")
    assert out is not None
    assert out[0]["id"] == "tu_1"
    assert out[0]["function"]["name"] == "search"
    assert out[0]["function"]["arguments"] == '{"q": "transformers"}'
