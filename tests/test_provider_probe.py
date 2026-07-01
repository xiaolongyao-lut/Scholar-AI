"""B20 (2026-06-14) — public provider_probe service.

Replaces 6 different "test connection" implementations with a single module.
These tests pin the public contract so future refactors can't silently drift
the UI behavior (the original problem that B7/B7.1/B14/B15/B18 each chased
in a different file).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_CORE = Path(__file__).resolve().parents[1] / "literature_assistant" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import provider_probe  # noqa: E402
from provider_probe import (  # noqa: E402
    DiscoverResult,
    ProbeResult,
    ToolCallingProbeResult,
    _build_models_url,
    _chat_probe_payload,
    _chat_probe_url,
    _extract_provider_error_message,
    _judge_scholar_probe_response,
    probe_openai_tool_calling_capability,
    _redact_secrets,
    validate_outbound_endpoint,
)


# ---------------------------------------------------------------------------
# validate_outbound_endpoint — strict vs non-strict
# ---------------------------------------------------------------------------


def test_strict_rejects_non_https_scheme() -> None:
    """strict=True must reject http (only loopback http with explicit opt-in
    is allowed, which the caller's allow_loopback_http flag controls)."""
    with pytest.raises(ValueError):
        validate_outbound_endpoint("http://api.example.com/v1", "test", strict=True)


def test_strict_accepts_when_loopback_http_optin() -> None:
    """When the caller explicitly enables loopback http (Ollama / LM Studio),
    strict mode must allow http://localhost or http://127.0.0.1."""
    # Don't raise — the loopback opt-in is the documented escape hatch.
    validate_outbound_endpoint(
        "http://localhost:11434/v1",
        "ollama",
        strict=True,
        allow_loopback_http=True,
    )


def test_non_strict_allows_arbitrary_public_host() -> None:
    """Non-strict (user-initiated probe) skips IP classification so newly
    added third-party gateways don't get rejected before reachability test."""
    # Any well-formed https URL must NOT raise in non-strict mode.
    validate_outbound_endpoint("https://free.hanhanapi.top/v1", "test", strict=False)
    validate_outbound_endpoint("https://api.krill-ai.com/codex/v1", "test", strict=False)


def test_non_strict_still_rejects_scheme_violations() -> None:
    """Scheme / userinfo / path checks run in BOTH modes — non-strict only
    relaxes IP classification, not the structural URL safety checks."""
    with pytest.raises(ValueError):
        validate_outbound_endpoint("javascript:alert(1)", "test", strict=False)
    with pytest.raises(ValueError):
        # userinfo in URL — credential leakage shape
        validate_outbound_endpoint("https://user:pass@example.com/v1", "test", strict=False)


# ---------------------------------------------------------------------------
# _build_models_url — URL derivation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("base,expected", [
    ("https://api.x.com",                     "https://api.x.com/v1/models"),
    ("https://api.x.com/",                    "https://api.x.com/v1/models"),
    ("https://api.x.com/v1",                  "https://api.x.com/v1/models"),
    ("https://api.x.com/v1/",                 "https://api.x.com/v1/models"),
    ("https://api.x.com/v1/chat/completions", "https://api.x.com/v1/models"),
    ("https://free.hanhanapi.top/v1",         "https://free.hanhanapi.top/v1/models"),
    ("https://api.krill-ai.com/codex/v1",     "https://api.krill-ai.com/codex/v1/models"),
])
def test_models_url_derivation(base: str, expected: str) -> None:
    assert _build_models_url(base) == expected


def test_models_url_empty_input() -> None:
    assert _build_models_url("") == ""
    assert _build_models_url("   ") == ""


# ---------------------------------------------------------------------------
# _chat_probe_url + _chat_probe_payload — protocol mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("protocol,suffix", [
    ("openai_chat_completions", "/chat/completions"),
    ("openai_responses",        "/responses"),
    ("anthropic_messages",      "/messages"),
])
def test_chat_probe_url_per_protocol(protocol: str, suffix: str) -> None:
    url = _chat_probe_url("https://provider.example/v1", protocol)
    assert url == f"https://provider.example/v1{suffix}"


def test_chat_probe_url_normalizes_trailing_slash() -> None:
    """Trailing slash on base_url must not produce a double slash."""
    a = _chat_probe_url("https://provider.example/v1/", "openai_chat_completions")
    b = _chat_probe_url("https://provider.example/v1", "openai_chat_completions")
    assert a == b
    assert "//chat" not in a


def test_chat_probe_url_returns_none_for_non_chat_protocols() -> None:
    assert _chat_probe_url("https://x/v1", "embeddings") is None
    assert _chat_probe_url("https://x/v1", "rerank") is None
    assert _chat_probe_url("https://x/v1", "futureproto") is None


def test_chat_probe_payload_per_protocol() -> None:
    openai = _chat_probe_payload("openai_chat_completions", "deepseek-v4-flash")
    assert openai is not None
    assert openai["model"] == "deepseek-v4-flash"
    assert openai["max_tokens"] == 180
    assert "Scholar AI" in openai["messages"][0]["content"]
    assert "evidence_ids" in openai["messages"][1]["content"]

    responses = _chat_probe_payload("openai_responses", "gpt-4.1-mini")
    assert responses is not None
    assert responses["model"] == "gpt-4.1-mini"
    assert responses["max_output_tokens"] == 180
    assert "input" in responses

    anthropic = _chat_probe_payload("anthropic_messages", "claude-3-5-haiku-20241022")
    assert anthropic is not None
    assert anthropic["model"] == "claude-3-5-haiku-20241022"
    assert anthropic["max_tokens"] == 180

    assert _chat_probe_payload("embeddings", "text-embedding-3-small") is None
    assert _chat_probe_payload("openai_chat_completions", "") is None


def test_scholar_probe_judges_template_response_ready() -> None:
    result = _judge_scholar_probe_response(
        '{"verdict":"usable","answer":"保留证据编号可以绑定来源，便于核对并降低幻觉风险。","evidence_ids":["S1"],"limits":"仅依据材料。"}'
    )

    assert result["capability_verdict"] == "scholar_ready"
    assert result["checks"]["json_template"] is True
    assert result["checks"]["evidence_id_s1"] is True


def test_scholar_probe_accepts_plain_text_with_warning() -> None:
    result = _judge_scholar_probe_response("根据 S1，证据编号能帮助核对来源并降低幻觉风险。")

    assert result["capability_verdict"] == "usable_text_response"
    assert result["checks"]["json_template"] is False


def test_chat_probe_payload_requires_real_model() -> None:
    assert _chat_probe_payload("openai_chat_completions", "   ") is None


# ---------------------------------------------------------------------------
# Result dataclasses — pin shape so UI rendering can't drift
# ---------------------------------------------------------------------------


def test_probe_result_defaults() -> None:
    """A freshly-constructed ProbeResult is safe to render: empty error / no
    status when nothing's been probed yet, ok=False until proven otherwise."""
    r = ProbeResult(ok=False)
    assert r.ok is False
    assert r.status_code is None
    assert r.method is None
    assert r.url_used == ""
    assert r.error == ""
    assert r.provider_message is None
    assert r.note is None


def test_discover_result_defaults() -> None:
    r = DiscoverResult(ok=False)
    assert r.ok is False
    assert r.models == []
    assert r.endpoint == ""
    assert r.error == ""


def test_tool_calling_probe_result_defaults() -> None:
    r = ToolCallingProbeResult(ok=False)
    assert r.ok is False
    assert r.models_ok is False
    assert r.chat_ok is False
    assert r.forced_tool_choice_ok is False
    assert r.protocol == "openai_chat_completions"


# ---------------------------------------------------------------------------
# Secret redaction + message extraction (parity with B7 contract)
# ---------------------------------------------------------------------------


def test_redact_sk_key() -> None:
    out = _redact_secrets("Bearer " + "sk-" + "zsZUx1MIrEK4UM2YPpxL5ZUGeRd5VMmsD7DiMGy1vc0ZyHwN rejected")
    assert "[REDACTED]" in out
    assert "zsZUx1MI" not in out


def test_redact_keeps_short_words() -> None:
    """Short non-mixed strings must survive — error prose must remain readable."""
    out = _redact_secrets("insufficient balance please recharge")
    assert out == "insufficient balance please recharge"


def test_extract_openai_error_envelope() -> None:
    body = '{"error":{"message":"You exceeded your current quota","type":"insufficient_quota"}}'
    assert _extract_provider_error_message(body) == "You exceeded your current quota"


def test_extract_newapi_envelope_with_request_id_redacted() -> None:
    body = (
        '{"error":{"code":"model_not_found",'
        '"message":"No available channel for model gpt-4o-mini under group default '
        '(distributor) (request id: 202606131416597817693018268d9d6quHFmZSY)",'
        '"type":"new_api_error"}}'
    )
    out = _extract_provider_error_message(body)
    assert out is not None
    assert "No available channel" in out
    assert "[REDACTED]" in out
    assert "202606131416597817693018268d9d6quHFmZSY" not in out


def test_extract_empty_body_returns_none() -> None:
    assert _extract_provider_error_message("") is None
    assert _extract_provider_error_message(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# OpenAI-compatible forced tool-call capability probe
# ---------------------------------------------------------------------------


class _FakeSyncResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload, ensure_ascii=False)

    def json(self) -> dict[str, Any]:
        return dict(self._payload)


class _ToolProbeClient:
    calls: list[dict[str, Any]] = []
    forced_returns_tool_call = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def __enter__(self) -> "_ToolProbeClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def get(self, url: str, headers: dict[str, str]) -> _FakeSyncResponse:
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        return _FakeSyncResponse(
            200,
            {"object": "list", "data": [{"id": "tool-model", "owned_by": "test"}]},
        )

    def post(
        self,
        url: str,
        json: dict[str, Any],
        headers: dict[str, str],
    ) -> _FakeSyncResponse:
        self.calls.append({"method": "POST", "url": url, "json": json, "headers": headers})
        if "tool_choice" not in json:
            return _FakeSyncResponse(
                200,
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            )
        if not self.forced_returns_tool_call:
            return _FakeSyncResponse(
                200,
                {"choices": [{"message": {"role": "assistant", "content": "tools unavailable"}}]},
            )
        return _FakeSyncResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_probe",
                                    "type": "function",
                                    "function": {
                                        "name": "capability_probe",
                                        "arguments": "{\"status\":\"ok\"}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )


def test_tool_calling_probe_runs_models_chat_and_forced_tool_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ToolProbeClient.calls = []
    _ToolProbeClient.forced_returns_tool_call = True
    monkeypatch.setattr(provider_probe.httpx, "Client", _ToolProbeClient)

    result = probe_openai_tool_calling_capability(
        "https://provider.example/v1",
        "sk-" + "test1234567890abcdef",
        "tool-model",
    )

    assert result.ok is True
    assert result.models_ok is True
    assert result.chat_ok is True
    assert result.forced_tool_choice_ok is True
    assert [call["method"] for call in _ToolProbeClient.calls] == ["GET", "POST", "POST"]
    assert _ToolProbeClient.calls[0]["url"] == "https://provider.example/v1/models"
    ordinary_payload = _ToolProbeClient.calls[1]["json"]
    forced_payload = _ToolProbeClient.calls[2]["json"]
    assert ordinary_payload["model"] == "tool-model"
    assert "tools" not in ordinary_payload
    assert forced_payload["tool_choice"]["function"]["name"] == "capability_probe"
    assert forced_payload["tools"][0]["function"]["name"] == "capability_probe"
    assert "sk-test" not in result.error


def test_tool_calling_probe_detects_proxy_that_swallows_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ToolProbeClient.calls = []
    _ToolProbeClient.forced_returns_tool_call = False
    monkeypatch.setattr(provider_probe.httpx, "Client", _ToolProbeClient)

    result = probe_openai_tool_calling_capability(
        "https://provider.example/v1",
        "sk-" + "test1234567890abcdef",
        "tool-model",
    )

    assert result.ok is False
    assert result.models_ok is True
    assert result.chat_ok is True
    assert result.forced_tool_choice_ok is False
    assert result.stage == "forced_tool_choice"
    assert result.status_code == 200
    assert result.error == "forced_tool_choice_not_returned"
    assert len(_ToolProbeClient.calls) == 3
