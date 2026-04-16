# -*- coding: utf-8 -*-

from routers.chat_router import (
    LLMConfig,
    _build_chat_endpoint,
    _build_chat_request,
    _extract_chat_response,
)


def _make_llm(provider: str, base_url: str) -> LLMConfig:
    return LLMConfig(
        provider=provider,
        api_key="test-key",
        model="test-model",
        base_url=base_url,
        temperature=0.3,
        top_p=0.8,
        max_tokens=512,
        system_prompt="请严格基于文献回答。",
    )


def test_build_chat_endpoint_uses_provider_specific_paths() -> None:
    assert _build_chat_endpoint("https://api.deepseek.com", "DeepSeek") == "https://api.deepseek.com/v1/chat/completions"
    assert _build_chat_endpoint("https://api.anthropic.com", "Claude") == "https://api.anthropic.com/v1/messages"
    assert _build_chat_endpoint("https://open.bigmodel.cn/api/paas", "Zhipu") == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert _build_chat_endpoint("https://ark.cn-beijing.volces.com/api", "Doubao") == "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    assert _build_chat_endpoint("https://generativelanguage.googleapis.com", "Gemini") == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def test_build_chat_endpoint_keeps_full_endpoint_urls_unchanged() -> None:
    assert _build_chat_endpoint("https://api.deepseek.com/v1/chat/completions", "DeepSeek") == "https://api.deepseek.com/v1/chat/completions"
    assert _build_chat_endpoint("https://api.openai.com/v1/chat/completions", "OpenAI") == "https://api.openai.com/v1/chat/completions"
    assert _build_chat_endpoint("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "Gemini") == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert _build_chat_endpoint("https://api.anthropic.com/v1/messages", "Claude") == "https://api.anthropic.com/v1/messages"


def test_build_chat_request_for_claude_uses_native_headers_and_payload() -> None:
    llm = _make_llm("Claude", "https://api.anthropic.com")

    url, headers, payload = _build_chat_request(
        "总结文献中的关键发现",
        ["【paper.pdf｜片段 1】\n激光功率增加会提高沉积效率。"],
        llm,
    )

    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers
    assert payload["messages"] == [{"role": "user", "content": "总结文献中的关键发现"}]
    assert payload["system"].startswith("请严格基于文献回答。")
    assert "参考文档内容" in payload["system"]


def test_extract_chat_response_supports_claude_content_blocks() -> None:
    answer, usage, model = _extract_chat_response(
        {
            "model": "claude-sonnet-test",
            "usage": {"input_tokens": 12, "output_tokens": 34},
            "content": [
                {"type": "text", "text": "第一段。"},
                {"type": "text", "text": "第二段。"},
            ],
        },
        "Claude",
        "fallback-model",
    )

    assert answer == "第一段。第二段。"
    assert usage == {"input_tokens": 12, "output_tokens": 34}
    assert model == "claude-sonnet-test"


def test_build_chat_request_auto_model_falls_back_for_hosted_provider() -> None:
    llm = LLMConfig(
        provider="DeepSeek",
        api_key="test-key",
        model="auto",
        base_url="https://api.deepseek.com",
        temperature=0.7,
        top_p=0.9,
        max_tokens=512,
        system_prompt="",
    )

    _, _, payload = _build_chat_request("ping", [], llm)

    assert payload["model"] == "deepseek-chat"


def test_build_chat_request_auto_model_rejected_for_local_provider() -> None:
    llm = LLMConfig(
        provider="Ollama",
        api_key="",
        model="auto",
        base_url="http://localhost:11434",
        temperature=0.7,
        top_p=0.9,
        max_tokens=512,
        system_prompt="",
    )

    try:
        _build_chat_request("ping", [], llm)
        assert False, "expected ValueError when model is auto for local provider"
    except ValueError as exc:
        assert "选择具体模型" in str(exc)
