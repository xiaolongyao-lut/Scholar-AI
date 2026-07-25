from __future__ import annotations

from typing import Any

import pytest

from routers import intelligent_chat_router, model_config_router, rerank_config_router
from routers.model_config_router import ConfigUpdate
from routers.rerank_config_router import RerankConfigUpdate
from provider_capabilities import ProviderCapabilityStore
from provider_probe import ToolCallingProbeResult


class _ProbeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _AsyncProbeClient:
    payload: dict[str, Any] = {}
    captured_json: dict[str, Any] | None = None
    captured_follow_redirects: bool | None = None
    captured_timeout: float | None = None

    def __init__(self, *_args: Any, **kwargs: Any) -> None:
        self.__class__.captured_follow_redirects = kwargs.get("follow_redirects")
        self.__class__.captured_timeout = float(kwargs.get("timeout") or 0)

    async def __aenter__(self) -> _AsyncProbeClient:
        return self

    async def __aexit__(self, *_args: Any) -> bool:
        return False

    async def post(
        self,
        _url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> _ProbeResponse:
        _ = headers
        self.__class__.captured_json = json
        return _ProbeResponse(self.__class__.payload)


class _StaticSettingsStore:
    def __init__(self, settings: dict[str, Any]) -> None:
        self._settings = dict(settings)

    def get_settings(self) -> dict[str, Any]:
        return dict(self._settings)


class _StaticResolvedFieldStore:
    def __init__(self, fields: dict[str, str]) -> None:
        self._fields = dict(fields)

    def get_resolved_field(self, name: str) -> str:
        return self._fields.get(name, "")


@pytest.fixture(autouse=True)
def _allow_example_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["104.18.6.192"],
    )


@pytest.mark.asyncio
async def test_chat_probe_requires_usable_reply_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_config_router.httpx, "AsyncClient", _AsyncProbeClient)
    _AsyncProbeClient.payload = {"choices": [{"message": {"content": ""}}]}

    result = await model_config_router.test_chat_endpoint(
        ConfigUpdate(base_url="https://example.test/v1", api_key="test-key", model="chat-model")
    )

    assert result.ok is False
    assert "没有返回可用的回复内容" in result.error
    assert _AsyncProbeClient.captured_follow_redirects is False


def test_context_compression_payload_normalizes_legacy_high_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _StaticSettingsStore(
        {
            "enabled": True,
            "trigger_tokens": 600_000,
            "target_tokens": 64_000,
            "keep_recent_turns": 100,
            "updated_at": "2026-05-28T17:26:15Z",
        }
    )
    monkeypatch.setattr(model_config_router, "chat_context_compression_store", store)

    payload = model_config_router._chat_context_compression_payload()

    assert payload.enabled is True
    assert payload.model_auto_compact_token_limit == 150_000
    assert payload.trigger_tokens == 150_000
    assert payload.model_context_window == 258_400
    assert payload.tool_output_token_limit == 8_000
    assert payload.target_tokens == 2_000
    assert payload.keep_recent_turns == 6
    assert payload.updated_at == "2026-05-28T17:26:15Z"


def test_intelligent_chat_policy_uses_the_same_bounded_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _StaticSettingsStore(
        {
            "enabled": True,
            "trigger_tokens": 600_000,
            "target_tokens": 64_000,
            "keep_recent_turns": 100,
        }
    )
    monkeypatch.setattr(intelligent_chat_router, "chat_context_compression_store", store)

    policy = intelligent_chat_router._compression_policy()

    assert policy == {
        "enabled": True,
        "trigger_tokens": 150_000,
        "target_tokens": 2_000,
        "keep_recent_turns": 6,
    }


def test_intelligent_chat_default_llm_uses_chat_sampling_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        intelligent_chat_router,
        "chat_store",
        _StaticResolvedFieldStore(
            {
                "provider": "OpenAI",
                "base_url": "https://example.test/v1",
                "api_key": "test-key",
                "model": "chat-model",
            }
        ),
    )
    monkeypatch.setattr(intelligent_chat_router, "load_user_sampling", lambda: {}, raising=False)
    monkeypatch.setattr(
        intelligent_chat_router,
        "env_value",
        lambda _name, *_fallback_names, default=None: default,
    )

    llm = intelligent_chat_router._load_default_llm_config()

    assert llm.temperature == 0.35
    assert llm.top_p == 0.8
    assert llm.top_k == 40
    assert llm.max_tokens == 12000


def test_intelligent_chat_default_llm_applies_saved_chat_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        intelligent_chat_router,
        "chat_store",
        _StaticResolvedFieldStore(
            {
                "provider": "OpenAI",
                "base_url": "https://example.test/v1",
                "api_key": "test-key",
                "model": "chat-model",
            }
        ),
    )
    monkeypatch.setattr(
        intelligent_chat_router,
        "load_user_sampling",
        lambda: {"chat": {"temperature": 0.42, "max_tokens": 1200}},
        raising=False,
    )
    monkeypatch.setattr(
        intelligent_chat_router,
        "env_value",
        lambda _name, *_fallback_names, default=None: default,
    )

    llm = intelligent_chat_router._load_default_llm_config()

    assert llm.temperature == 0.42
    assert llm.top_p == 0.8
    assert llm.top_k == 40
    assert llm.max_tokens == 1200


@pytest.mark.asyncio
async def test_chat_probe_accepts_non_empty_reply_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_config_router.httpx, "AsyncClient", _AsyncProbeClient)
    _AsyncProbeClient.payload = {"choices": [{"message": {"content": "ok"}}]}

    result = await model_config_router.test_chat_endpoint(
        ConfigUpdate(base_url="https://example.test/v1", api_key="test-key", model="chat-model")
    )

    assert result.ok is True
    assert result.extra["response_chars"] == 2
    assert _AsyncProbeClient.captured_json is not None
    assert _AsyncProbeClient.captured_json["messages"][0]["content"].startswith("You are a Scholar AI")
    assert "evidence_ids" in _AsyncProbeClient.captured_json["messages"][1]["content"]
    assert _AsyncProbeClient.captured_follow_redirects is False


@pytest.mark.asyncio
async def test_chat_probe_accepts_anthropic_messages_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_config_router.httpx, "AsyncClient", _AsyncProbeClient)
    _AsyncProbeClient.payload = {"content": [{"type": "text", "text": "ok"}]}

    result = await model_config_router.test_chat_endpoint(
        ConfigUpdate(
            provider="Anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key="test-key",
            model="claude-3-5-haiku-20241022",
            protocol="anthropic_messages",
        )
    )

    assert result.ok is True
    assert result.extra["response_chars"] == 2
    assert _AsyncProbeClient.captured_json is not None
    assert _AsyncProbeClient.captured_json["system"].startswith("You are a Scholar AI")
    assert "evidence_ids" in _AsyncProbeClient.captured_json["messages"][0]["content"]
    assert _AsyncProbeClient.captured_json["max_tokens"] >= 180


@pytest.mark.asyncio
async def test_nvidia_chat_probe_uses_provider_payload_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_config_router.httpx, "AsyncClient", _AsyncProbeClient)
    monkeypatch.delenv("LITASSIST_NVIDIA_HTTP_TIMEOUT", raising=False)
    _AsyncProbeClient.payload = {"choices": [{"message": {"content": "ok"}}]}

    result = await model_config_router.test_chat_endpoint(
        ConfigUpdate(
            provider="NVIDIA",
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="test-key",
            model="deepseek-ai/deepseek-v4-flash",
        )
    )

    assert result.ok is True
    assert _AsyncProbeClient.captured_timeout is not None
    assert _AsyncProbeClient.captured_timeout >= 180.0
    assert _AsyncProbeClient.captured_json is not None
    assert _AsyncProbeClient.captured_json["reasoning_effort"] == "none"
    assert "extra_body" not in _AsyncProbeClient.captured_json


@pytest.mark.asyncio
async def test_embedding_probe_requires_embedding_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_config_router.httpx, "AsyncClient", _AsyncProbeClient)
    _AsyncProbeClient.payload = {"data": [{"index": 0, "object": "embedding"}]}

    result = await model_config_router.test_embedding_endpoint(
        ConfigUpdate(base_url="https://example.test/v1", api_key="test-key", model="embed-model")
    )

    assert result.ok is False
    assert "没有返回可用的向量数组" in result.error
    assert _AsyncProbeClient.captured_follow_redirects is False


@pytest.mark.asyncio
async def test_embedding_probe_accepts_openai_style_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_config_router.httpx, "AsyncClient", _AsyncProbeClient)
    _AsyncProbeClient.payload = {
        "model": "provider-embed-model",
        "data": [{"index": 0, "embedding": [0.6, 0.8, 0.0]}],
    }

    result = await model_config_router.test_embedding_endpoint(
        ConfigUpdate(base_url="https://example.test/v1", api_key="test-key", model="embed-model")
    )

    assert result.ok is True
    assert result.extra["dimension"] == 3
    assert result.extra["vectors"] == 1
    assert result.extra["contract_schema_version"] == "scholar-ai-embedding-contract/v1"
    assert result.extra["requested_model"] == "embed-model"
    assert result.extra["provider_response_model"] == "provider-embed-model"
    assert result.extra["dim"] == 3
    assert result.extra["representation_mode"] == "dense"
    assert result.extra["normalize"] is True
    assert isinstance(result.extra["contract_hash"], str)
    assert len(result.extra["contract_hash"]) == 64
    assert _AsyncProbeClient.captured_follow_redirects is False


def test_embedding_contract_hash_changes_with_provider_response_model() -> None:
    vectors = [[0.6, 0.8, 0.0]]

    first = model_config_router._build_embedding_contract_extra(
        provider="OpenAI",
        base_url="https://example.test/v1",
        requested_model="embed-model",
        response_model="provider-a",
        vectors=vectors,
    )
    second = model_config_router._build_embedding_contract_extra(
        provider="OpenAI",
        base_url="https://example.test/v1",
        requested_model="embed-model",
        response_model="provider-b",
        vectors=vectors,
    )

    assert first["contract_hash"] != second["contract_hash"]
    assert first["base_url_id"] == second["base_url_id"]


@pytest.mark.asyncio
async def test_rerank_probe_requires_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rerank_config_router.httpx, "AsyncClient", _AsyncProbeClient)
    _AsyncProbeClient.payload = {"results": [{"index": 0}]}

    result = await rerank_config_router.test_rerank_endpoint(
        RerankConfigUpdate(base_url="https://example.test/v1/rerank", api_key="test-key", model="rerank-model")
    )

    assert result.ok is False
    assert "没有返回可用的排序分数" in result.error
    assert _AsyncProbeClient.captured_follow_redirects is False


@pytest.mark.asyncio
async def test_rerank_probe_accepts_dashscope_style_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rerank_config_router.httpx, "AsyncClient", _AsyncProbeClient)
    _AsyncProbeClient.payload = {
        "output": {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.4},
            ]
        }
    }

    result = await rerank_config_router.test_rerank_endpoint(
        RerankConfigUpdate(base_url="https://example.test/v1/rerank", api_key="test-key", model="rerank-model")
    )

    assert result.ok is True
    assert result.extra == {"results": 2}
    assert _AsyncProbeClient.captured_follow_redirects is False


@pytest.mark.asyncio
async def test_chat_probe_rejects_unsafe_endpoint_before_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("HTTP client must not be created for rejected endpoints")

    monkeypatch.setattr(model_config_router.httpx, "AsyncClient", _FailingClient)

    result = await model_config_router.test_chat_endpoint(
        ConfigUpdate(
            base_url="http://169.254.169.254/v1",
            api_key="test-key",
            model="chat-model",
        )
    )

    assert result.ok is False
    assert "provider endpoint rejected" in result.error


@pytest.mark.asyncio
async def test_chat_tool_capability_probe_persists_tool_call_ok(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = ProviderCapabilityStore(path=tmp_path / "provider-capabilities.json")
    monkeypatch.setattr(model_config_router, "provider_capability_store", store)

    def _probe(
        _base_url: str,
        _api_key: str,
        _model: str,
        *,
        provider: str = "",
        protocol: str = "openai_chat_completions",
        timeout_s: float = 0.0,
    ) -> ToolCallingProbeResult:
        _ = provider, protocol, timeout_s
        return ToolCallingProbeResult(
            ok=True,
            models_ok=True,
            chat_ok=True,
            forced_tool_choice_ok=True,
            model="tool-model",
            stage="forced_tool_choice",
        )

    monkeypatch.setattr(
        "provider_probe.probe_openai_tool_calling_capability",
        _probe,
    )

    result = await model_config_router.test_chat_tool_capability(
        ConfigUpdate(
            provider="OpenAI",
            base_url="https://example.test/v1",
            api_key="test-key",
            model="tool-model",
        )
    )

    assert result.ok is True
    assert result.status == "tool_call_ok"
    persisted = store.get_record(
        provider="OpenAI",
        base_url="https://example.test/v1",
        model="tool-model",
    )
    assert persisted is not None
    assert persisted.tool_call_ok is True


@pytest.mark.asyncio
async def test_chat_tool_capability_probe_passes_nvidia_provider_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = ProviderCapabilityStore(path=tmp_path / "provider-capabilities.json")
    monkeypatch.setattr(model_config_router, "provider_capability_store", store)
    captured: dict[str, Any] = {}

    def _probe(
        _base_url: str,
        _api_key: str,
        _model: str,
        *,
        provider: str = "",
        protocol: str = "openai_chat_completions",
        timeout_s: float = 0.0,
    ) -> ToolCallingProbeResult:
        captured["provider"] = provider
        captured["protocol"] = protocol
        captured["timeout_s"] = timeout_s
        return ToolCallingProbeResult(
            ok=False,
            models_ok=True,
            chat_ok=True,
            forced_tool_choice_ok=False,
            model="deepseek-ai/deepseek-v4-flash",
            stage="forced_tool_choice",
            status_code=200,
            error="forced_tool_choice_not_returned",
        )

    monkeypatch.setattr("provider_probe.probe_openai_tool_calling_capability", _probe)
    monkeypatch.delenv("LITASSIST_NVIDIA_HTTP_TIMEOUT", raising=False)

    result = await model_config_router.test_chat_tool_capability(
        ConfigUpdate(
            provider="NVIDIA",
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="test-key",
            model="deepseek-ai/deepseek-v4-flash",
        )
    )

    assert result.ok is False
    assert result.status == "probe_failed"
    assert captured["provider"] == "NVIDIA"
    assert captured["protocol"] == "openai_chat_completions"
    assert captured["timeout_s"] >= 180.0


@pytest.mark.asyncio
async def test_chat_tool_capability_transient_probe_does_not_inherit_saved_protocol(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = ProviderCapabilityStore(path=tmp_path / "provider-capabilities.json")
    monkeypatch.setattr(model_config_router, "provider_capability_store", store)
    monkeypatch.setattr(
        model_config_router,
        "chat_store",
        _StaticResolvedFieldStore({"protocol": "anthropic_messages"}),
    )
    captured: dict[str, Any] = {}

    def _probe(
        _base_url: str,
        _api_key: str,
        _model: str,
        *,
        provider: str = "",
        protocol: str = "openai_chat_completions",
        timeout_s: float = 0.0,
    ) -> ToolCallingProbeResult:
        _ = provider, timeout_s
        captured["protocol"] = protocol
        return ToolCallingProbeResult(
            ok=False,
            models_ok=True,
            chat_ok=True,
            forced_tool_choice_ok=False,
            model="deepseek-ai/deepseek-v4-flash",
            stage="forced_tool_choice",
            status_code=200,
            error="forced_tool_choice_not_returned",
        )

    monkeypatch.setattr("provider_probe.probe_openai_tool_calling_capability", _probe)

    await model_config_router.test_chat_tool_capability(
        ConfigUpdate(
            provider="NVIDIA",
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="test-key",
            model="deepseek-ai/deepseek-v4-flash",
        )
    )

    assert captured["protocol"] == "openai_chat_completions"


@pytest.mark.asyncio
async def test_chat_tool_capability_probe_passes_protocol_from_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = ProviderCapabilityStore(path=tmp_path / "provider-capabilities.json")
    monkeypatch.setattr(model_config_router, "provider_capability_store", store)
    captured: dict[str, Any] = {}

    def _probe(
        _base_url: str,
        _api_key: str,
        _model: str,
        *,
        provider: str = "",
        protocol: str = "openai_chat_completions",
        timeout_s: float = 0.0,
    ) -> ToolCallingProbeResult:
        captured["provider"] = provider
        captured["protocol"] = protocol
        captured["timeout_s"] = timeout_s
        return ToolCallingProbeResult(
            ok=True,
            models_ok=True,
            chat_ok=True,
            forced_tool_choice_ok=True,
            protocol=protocol,
            model="claude-3-5-haiku-20241022",
            stage="anthropic_tool_choice",
        )

    monkeypatch.setattr("provider_probe.probe_openai_tool_calling_capability", _probe)

    result = await model_config_router.test_chat_tool_capability(
        ConfigUpdate(
            provider="Anthropic",
            base_url="https://api.anthropic.com/v1",
            api_key="test-key",
            model="claude-3-5-haiku-20241022",
            protocol="anthropic_messages",
        )
    )

    assert result.ok is True
    assert result.status == "tool_call_ok"
    assert captured["provider"] == "Anthropic"
    assert captured["protocol"] == "anthropic_messages"


@pytest.mark.asyncio
async def test_chat_tool_capability_probe_persists_probe_failed_when_tools_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = ProviderCapabilityStore(path=tmp_path / "provider-capabilities.json")
    monkeypatch.setattr(model_config_router, "provider_capability_store", store)

    def _probe(
        _base_url: str,
        _api_key: str,
        _model: str,
        *,
        provider: str = "",
        protocol: str = "openai_chat_completions",
        timeout_s: float = 0.0,
    ) -> ToolCallingProbeResult:
        _ = provider, protocol, timeout_s
        return ToolCallingProbeResult(
            ok=False,
            models_ok=True,
            chat_ok=True,
            forced_tool_choice_ok=False,
            model="tool-model",
            stage="forced_tool_choice",
            status_code=200,
            error="forced_tool_choice_not_returned",
        )

    monkeypatch.setattr(
        "provider_probe.probe_openai_tool_calling_capability",
        _probe,
    )

    result = await model_config_router.test_chat_tool_capability(
        ConfigUpdate(
            provider="OpenAI",
            base_url="https://example.test/v1",
            api_key="test-key",
            model="tool-model",
        )
    )

    assert result.ok is False
    assert result.status == "probe_failed"
    assert result.error == "forced_tool_choice_not_returned"
    persisted = store.get_record(
        provider="OpenAI",
        base_url="https://example.test/v1",
        model="tool-model",
    )
    assert persisted is not None
    assert persisted.status == "probe_failed"


@pytest.mark.asyncio
async def test_chat_tool_capability_probe_persists_auth_required(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = ProviderCapabilityStore(path=tmp_path / "provider-capabilities.json")
    monkeypatch.setattr(model_config_router, "provider_capability_store", store)

    def _probe(
        _base_url: str,
        _api_key: str,
        _model: str,
        *,
        provider: str = "",
        protocol: str = "openai_chat_completions",
        timeout_s: float = 0.0,
    ) -> ToolCallingProbeResult:
        _ = provider, protocol, timeout_s
        return ToolCallingProbeResult(
            ok=False,
            models_ok=False,
            chat_ok=False,
            forced_tool_choice_ok=False,
            model="tool-model",
            stage="models",
            status_code=401,
            error="HTTP 401: invalid api key",
        )

    monkeypatch.setattr(
        "provider_probe.probe_openai_tool_calling_capability",
        _probe,
    )

    result = await model_config_router.test_chat_tool_capability(
        ConfigUpdate(
            provider="OpenAI",
            base_url="https://example.test/v1",
            api_key="bad-key",
            model="tool-model",
        )
    )

    assert result.ok is False
    assert result.status == "auth_required"
    persisted = store.get_record(
        provider="OpenAI",
        base_url="https://example.test/v1",
        model="tool-model",
    )
    assert persisted is not None
    assert persisted.status == "auth_required"
