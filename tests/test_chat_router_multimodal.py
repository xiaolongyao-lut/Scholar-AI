"""Provider-payload regressions for private SmartRead image attachments."""

from __future__ import annotations

import json

from routers.chat_router import ChatImageAttachment, LLMConfig, _build_chat_request


_IMAGE = ChatImageAttachment(
    mime="image/png",
    data_b64="aGVsbG8=",
    size=5,
    name="figure.png",
)


def _llm(*, provider: str, base_url: str) -> LLMConfig:
    return LLMConfig(
        provider=provider,
        api_key="test-key",
        model="vision-model",
        base_url=base_url,
    )


def test_openai_compatible_payload_contains_text_and_image_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_MODEL_SUPPORTS_IMAGE", "1")

    _url, _headers, payload = _build_chat_request(
        "Explain the selected formula.",
        [],
        _llm(provider="OpenAI", base_url="https://api.openai.com/v1"),
        images=(_IMAGE,),
    )

    content = payload["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "Explain the selected formula."}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
    }


def test_claude_payload_contains_text_and_base64_image_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_MODEL_SUPPORTS_IMAGE", "true")

    _url, _headers, payload = _build_chat_request(
        "Explain the selected table.",
        [],
        _llm(provider="Claude", base_url="https://api.anthropic.com"),
        images=(_IMAGE,),
    )

    content = payload["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "Explain the selected table."}
    assert content[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "aGVsbG8=",
        },
    }


def test_disabled_image_transport_never_serializes_base64_for_post_or_stream(monkeypatch) -> None:
    monkeypatch.delenv("CHAT_MODEL_SUPPORTS_IMAGE", raising=False)
    llm = _llm(provider="OpenAI", base_url="https://api.openai.com/v1")

    for stream in (False, True):
        _url, _headers, payload = _build_chat_request(
            "Explain the selected region.",
            [],
            llm,
            stream=stream,
            images=(_IMAGE,),
        )
        serialized = json.dumps(payload)
        assert "aGVsbG8=" not in serialized
        assert payload["messages"][-1]["content"] == "Explain the selected region."
