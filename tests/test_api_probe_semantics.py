from __future__ import annotations

from typing import Any

import pytest

from routers import model_config_router, rerank_config_router
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

    def __init__(self, *_args: Any, **kwargs: Any) -> None:
        self.__class__.captured_follow_redirects = kwargs.get("follow_redirects")

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
    assert _AsyncProbeClient.captured_json["messages"][0]["content"] == "Hi"
    assert _AsyncProbeClient.captured_follow_redirects is False


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
    _AsyncProbeClient.payload = {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}

    result = await model_config_router.test_embedding_endpoint(
        ConfigUpdate(base_url="https://example.test/v1", api_key="test-key", model="embed-model")
    )

    assert result.ok is True
    assert result.extra == {"dimension": 3, "vectors": 1}
    assert _AsyncProbeClient.captured_follow_redirects is False


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

    def _probe(_base_url: str, _api_key: str, _model: str) -> ToolCallingProbeResult:
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
async def test_chat_tool_capability_probe_persists_probe_failed_when_tools_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = ProviderCapabilityStore(path=tmp_path / "provider-capabilities.json")
    monkeypatch.setattr(model_config_router, "provider_capability_store", store)

    def _probe(_base_url: str, _api_key: str, _model: str) -> ToolCallingProbeResult:
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

    def _probe(_base_url: str, _api_key: str, _model: str) -> ToolCallingProbeResult:
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
