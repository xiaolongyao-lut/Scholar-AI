"""Public provider-probe service — single source of truth for SSRF validation,
endpoint reachability checks, and model discovery.

Before this module existed, six different files each re-implemented their own
"is this provider reachable" / "is this endpoint trusted" logic with subtle
behavior drift (B7/B7.1/B14/B15/B18/B20 had to patch each of them separately).
This module consolidates them into TWO clearly-named public functions:

  - validate_outbound_endpoint(base_url, provider, *, strict)
      Used before sending ANY outbound request. `strict=True` for real chat /
      embedding / rerank traffic (full SSRF + IP classification). `strict=False`
      for user-initiated exploration (credential test, "获取模型", "应用" button
      reachability check) where the user just confirmed they want to talk to
      this host — IP classification would just block normal third-party
      gateways without protecting anything the user didn't already accept.

  - probe_endpoint_reachability(base_url, api_key, protocol)
      Used by user-initiated "测试连接" / discover / apply flows. Tries HEAD →
      GET → POST /chat/completions in order, surfaces upstream error message
      with secrets redacted, normalizes the response shape so every UI shows
      the same thing.

Real chat traffic uses validate_outbound_endpoint() only; it does NOT call
probe_endpoint_reachability() (that's user-facing).
"""
from __future__ import annotations

import json as _json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from provider_endpoint_policy import TrustSource, validate_endpoint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    """Normalized reachability probe outcome shared by every UI surface.

    Why this shape: prior to consolidation, three UIs each rendered a different
    subset of the underlying probe response (credential card / settings apply /
    discover). Pinning a single shape means "测试连接" and "应用" can never
    drift again — both go through this dataclass.
    """
    ok: bool
    """True iff the endpoint responded in a way that proves auth+routing work."""
    status_code: int | None = None
    """HTTP status of the final probe attempt; None on transport failure."""
    method: str | None = None
    """Which HTTP method finally produced the verdict (HEAD/GET/POST)."""
    url_used: str = ""
    """The exact URL that produced status_code (for debugging)."""
    error: str = ""
    """Single-line, redacted, user-facing error string. Empty when ok=True."""
    provider_message: str | None = None
    """Upstream provider's own error message (when extractable), already redacted."""
    note: str | None = None
    """Optional success annotation, e.g. "base_url 404 but chat endpoint reachable"."""


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def _redact_secrets(text: str) -> str:
    """Mask API-key-shaped tokens before they reach the user.

    Patterns:
      - sk-/sk_ prefixed runs of 16+ chars (OpenAI / Anthropic / SiliconFlow)
      - nb-/nb_ prefixed runs of 16+ chars (krill / Niubi)
      - mixed-alphanumeric 32+ char runs (request ids, session tokens, UUIDs).
        Pure-alpha and pure-digit runs are intentionally left alone so legitimate
        words and version numbers in error prose don't get masked.
    """
    text = re.sub(r"\b(?:sk[-_][A-Za-z0-9]{16,}|nb[-_][A-Za-z0-9]{16,})\b", "[REDACTED]", text)

    def _maybe(m: "re.Match[str]") -> str:
        s = m.group(0)
        if any(c.isalpha() for c in s) and any(c.isdigit() for c in s):
            return "[REDACTED]"
        return s

    text = re.sub(r"\b[A-Za-z0-9]{32,}\b", _maybe, text)
    return text


def _extract_provider_error_message(body: str) -> str | None:
    """Pull a user-actionable message out of common upstream error envelopes.

    Recognized shapes (in priority order):
      OpenAI:           {"error": {"message": "...", "type": "..."}}
      NewAPI/one-api:   {"error": {"code": "...", "message": "...", "type": "new_api_error"}}
      Anthropic:        {"error": {"type": "...", "message": "..."}}
      Generic:          {"message": "..."} | {"detail": "..."}

    Returns a redacted, ≤240-char string. Returns None when nothing actionable
    is present (caller falls back to "HTTP <code>").
    """
    if not isinstance(body, str) or not body.strip():
        return None
    try:
        data = _json.loads(body)
    except Exception:
        return _redact_secrets(body)[:240] or None
    if not isinstance(data, dict):
        return None
    candidates: list[Any] = []
    err = data.get("error")
    if isinstance(err, dict):
        candidates.append(err.get("message"))
        candidates.append(err.get("code"))
    elif isinstance(err, str):
        candidates.append(err)
    candidates.append(data.get("message"))
    candidates.append(data.get("detail"))
    for cand in candidates:
        if isinstance(cand, str) and cand.strip():
            return _redact_secrets(cand.strip())[:240]
    return None


# ---------------------------------------------------------------------------
# SSRF gate — single entry point for outbound validation
# ---------------------------------------------------------------------------


def validate_outbound_endpoint(
    base_url: str,
    provider: str,
    *,
    strict: bool,
    allow_loopback_http: bool = False,
) -> None:
    """Reject unsafe outbound endpoints before issuing any HTTP request.

    Args:
        base_url: provider's base URL (e.g. https://api.example.com/v1).
        provider: provider label (used for logging + error messages).
        strict: when True, runs full DNS + IP classification (real chat /
            embedding / rerank traffic). When False, skips IP classification
            (user-initiated probes — credential test, model discover, "应用"
            button reachability check, etc.). scheme / userinfo / path checks
            run in both modes.
        allow_loopback_http: opt-in for `http://localhost` providers (Ollama,
            LM Studio). Caller decides; we don't infer from the URL.

    Raises ValueError when rejected. The exception message is safe to surface
    to the UI (no upstream URLs / keys).
    """
    decision = validate_endpoint(
        base_url,
        trust_source=TrustSource.RUNTIME_USER_CONFIRMED,
        allow_loopback_http=allow_loopback_http,
        skip_dns=not strict,
    )
    if not decision.allowed:
        raise ValueError(f"provider endpoint rejected: {decision.reason}")


# ---------------------------------------------------------------------------
# Reachability probe — single implementation for every UI surface
# ---------------------------------------------------------------------------


_PROBE_CHAT_PATHS: dict[str, str] = {
    "openai_chat_completions": "/chat/completions",
    "openai_responses": "/responses",
    "anthropic_messages": "/messages",
}


def _chat_probe_url(base_url: str, protocol: str) -> str | None:
    """Return the chat-style endpoint URL for a 1-token ping, or None when N/A.

    Embeddings / Rerank protocols return None — their HEAD/GET on base_url is
    already meaningful, no chat fallback needed.
    """
    if not isinstance(base_url, str) or not base_url.strip():
        return None
    suffix = _PROBE_CHAT_PATHS.get((protocol or "").lower())
    if suffix is None:
        return None
    return f"{base_url.rstrip('/')}{suffix}"


def _chat_probe_payload(protocol: str) -> dict[str, Any] | None:
    """Smallest possible request body for the chat-style ping per protocol.

    Uses a deliberately-invalid model id so providers that strictly validate
    the model surface `model_not_found` (which proves auth+routing work
    without burning real tokens). Providers that don't validate the model
    accept `max_tokens=1` and burn ~1 token.
    """
    proto = (protocol or "").lower()
    if proto == "anthropic_messages":
        return {
            "model": "claude-3-5-haiku-20241022",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "."}],
        }
    if proto in ("openai_chat_completions", "openai_responses"):
        return {
            "model": "_provider_probe_no_real_model",
            "messages": [{"role": "user", "content": "."}],
            "max_tokens": 1,
        }
    return None


def _build_auth_headers(api_key: str, protocol: str) -> dict[str, str]:
    """Per-protocol auth header shape. Caller must run validate_outbound_endpoint
    BEFORE constructing this so we never send credentials to a rejected host."""
    proto = (protocol or "").lower()
    if proto == "anthropic_messages":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    # openai_chat_completions / openai_responses / embeddings / rerank / unknown
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def probe_endpoint_reachability(
    base_url: str,
    api_key: str,
    protocol: str,
    *,
    timeout_s: float = 8.0,
) -> ProbeResult:
    """Try to reach an OpenAI/Anthropic-compatible endpoint with auth.

    Strategy (each step short-circuits on a clear verdict):
      1. HEAD base_url — fastest, but many gateways return 4xx on bare /v1.
      2. GET base_url  — picks up the 4xx body for diagnostic display.
      3. POST chat/completions with a 1-token ping — catches NewAPI/one-api
         gateways that only respond on the chat subpath. A 200 OR a
         "model_not_found"-style 4xx body counts as REACHABLE (auth works,
         routing works, only the deliberately-fake probe model is unknown).

    Caller MUST run validate_outbound_endpoint(strict=False) before calling
    this — we don't repeat that here so the caller can choose how to surface
    the rejection.
    """
    base_url = (base_url or "").strip()
    headers = {**_build_auth_headers(api_key, protocol),
               "User-Agent": "literature-assistant-provider-probe/1.0"}

    result = ProbeResult(ok=False, url_used=base_url, method="HEAD")
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=False) as client:
            # 1. HEAD then GET on base_url
            resp = client.head(base_url, headers=headers)
            sc = resp.status_code
            result.status_code = sc
            if sc in (404, 405) or sc >= 400:
                resp = client.get(base_url, headers=headers)
                result.method = "GET"
                sc = resp.status_code
                result.status_code = sc

            if 200 <= sc < 400:
                result.ok = True
                return result

            # 2. Try chat-completions ping for NewAPI-style gateways
            chat_url = _chat_probe_url(base_url, protocol)
            chat_payload = _chat_probe_payload(protocol)
            if chat_url and chat_payload:
                try:
                    chat_resp = client.post(chat_url, json=chat_payload, headers=headers)
                except httpx.HTTPError as chat_exc:
                    result.error = (
                        f"HTTP {sc}: {_extract_provider_error_message(resp.text or '') or 'base url unreachable'}; "
                        f"chat probe transport error: {type(chat_exc).__name__}"
                    )
                    return result

                chat_sc = chat_resp.status_code
                chat_body = chat_resp.text or ""
                chat_msg = _extract_provider_error_message(chat_body)
                signals = (
                    "model_not_found",
                    "no available channel",
                    "unknown model",
                    "model not found",
                    "invalid model",
                    "_provider_probe_no_real_model",
                )
                auth_ok = (
                    200 <= chat_sc < 400
                    or (chat_msg and any(s in chat_msg.lower() for s in signals))
                )
                if auth_ok:
                    result.ok = True
                    result.status_code = chat_sc
                    result.method = "POST"
                    result.url_used = chat_url
                    result.note = "base_url returned error; chat endpoint reachable"
                    result.provider_message = chat_msg
                    return result

                # chat endpoint also failed → surface its error (better signal)
                result.status_code = chat_sc
                result.method = "POST"
                result.url_used = chat_url
                result.provider_message = chat_msg
                result.error = (
                    f"HTTP {chat_sc}"
                    + (f": {chat_msg}" if chat_msg else "")
                )
                return result

            # 3. No chat fallback (embeddings/rerank/unknown) — surface base_url err
            base_msg = _extract_provider_error_message(resp.text or "")
            result.provider_message = base_msg
            result.error = (
                f"HTTP {sc}"
                + (f": {base_msg}" if base_msg else "")
            )
            return result

    except httpx.TimeoutException:
        result.error = "timeout"
        return result
    except httpx.ConnectError:
        result.error = "connect_error"
        return result
    except httpx.HTTPError as exc:
        result.error = f"http_error:{type(exc).__name__}"
        return result
    except Exception as exc:  # noqa: BLE001 — defense in depth
        logger.warning("provider probe unexpected failure: %s", type(exc).__name__)
        result.error = f"unexpected:{type(exc).__name__}"
        return result


# ---------------------------------------------------------------------------
# Model discovery — single implementation for "获取模型" everywhere
# ---------------------------------------------------------------------------


def _build_models_url(base_url: str) -> str:
    """Derive the /v1/models endpoint URL from a base URL.

    Matches cc-switch's build_models_url:
      https://api.x.com           -> https://api.x.com/v1/models
      https://api.x.com/v1        -> https://api.x.com/v1/models
      https://api.x.com/v1/chat/completions -> https://api.x.com/v1/models
    """
    trimmed = base_url.strip().rstrip("/")
    if not trimmed:
        return ""
    if trimmed.endswith("/v1/chat/completions"):
        trimmed = trimmed[: -len("/chat/completions")]
    if trimmed.endswith("/v1"):
        return f"{trimmed}/models"
    return f"{trimmed}/v1/models"


@dataclass
class DiscoverResult:
    """Normalized model-discovery result."""
    ok: bool
    models: list[dict[str, Any]] = field(default_factory=list)
    endpoint: str = ""
    error: str = ""
    status_code: int | None = None
    body: str = ""


@dataclass
class ToolCallingProbeResult:
    """Three-stage OpenAI-compatible tool-calling capability probe result."""

    ok: bool
    models_ok: bool = False
    chat_ok: bool = False
    forced_tool_choice_ok: bool = False
    protocol: str = "openai_chat_completions"
    model: str = ""
    models_url: str = ""
    chat_url: str = ""
    stage: str = ""
    status_code: int | None = None
    error: str = ""
    provider_message: str | None = None


async def discover_models(
    base_url: str,
    api_key: str,
    *,
    timeout_s: float = 10.0,
) -> DiscoverResult:
    """Hit /v1/models on an OpenAI-compatible endpoint.

    Returns a fixed-shape DiscoverResult; caller decides how to render. Does
    NOT call validate_outbound_endpoint — caller must do that first so the
    rejection can surface as the user-facing error path naturally.
    """
    url = _build_models_url(base_url)
    if not url:
        return DiscoverResult(ok=False, error="Base URL is empty")

    headers: dict[str, str] = {"Content-Type": "application/json",
                               "User-Agent": "literature-assistant-provider-probe/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models_list = data.get("data", []) if isinstance(data, dict) else []
        discovered = [
            {
                "id": m.get("id", ""),
                "name": m.get("id", ""),
                "description": str(m.get("owned_by") or "自动发现的模型"),
            }
            for m in models_list
            if isinstance(m, dict) and m.get("id")
        ]
        discovered.sort(key=lambda m: m["id"])
        return DiscoverResult(ok=True, models=discovered, endpoint=url)

    except httpx.HTTPStatusError as exc:
        body_snippet = ""
        try:
            body_snippet = exc.response.text[:400] if exc.response is not None else ""
        except Exception:  # noqa: BLE001
            body_snippet = ""
        status_code = exc.response.status_code if exc.response is not None else 0
        provider_msg = _extract_provider_error_message(body_snippet)
        return DiscoverResult(
            ok=False,
            endpoint=url,
            status_code=status_code,
            body=body_snippet,
            error=f"HTTP {status_code}" + (f": {provider_msg}" if provider_msg else ""),
        )
    except httpx.RequestError as exc:
        return DiscoverResult(
            ok=False,
            endpoint=url,
            error=f"连接失败: {exc.__class__.__name__}: {exc}",
        )


def _ordinary_chat_probe_payload(model: str) -> dict[str, Any]:
    """Return a real-model one-token chat payload for capability probes."""

    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string")
    return {
        "model": model.strip(),
        "messages": [{"role": "user", "content": "Reply with ok."}],
        "max_tokens": 8,
        "temperature": 0,
    }


def _forced_tool_choice_probe_payload(model: str) -> dict[str, Any]:
    """Return an OpenAI-compatible forced function-call probe payload."""

    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string")
    return {
        "model": model.strip(),
        "messages": [
            {
                "role": "user",
                "content": "Call capability_probe with status=ok.",
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "capability_probe",
                    "description": "Reports whether forced tool calls reach the model.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["ok"],
                            }
                        },
                        "required": ["status"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "tool_choice": {
            "type": "function",
            "function": {"name": "capability_probe"},
        },
        "max_tokens": 32,
        "temperature": 0,
    }


def _json_object_response(response: httpx.Response) -> dict[str, Any] | None:
    """Decode an HTTP response body only when it is a JSON object."""

    try:
        data = response.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _contains_forced_tool_call(payload: dict[str, Any], tool_name: str) -> bool:
    """Detect whether an OpenAI-compatible response returned a named tool call."""

    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                if isinstance(function, dict) and function.get("name") == tool_name:
                    return True
        function_call = message.get("function_call")
        if isinstance(function_call, dict) and function_call.get("name") == tool_name:
            return True
    return False


def _probe_failure(
    result: ToolCallingProbeResult,
    *,
    stage: str,
    status_code: int | None = None,
    error: str,
    provider_message: str | None = None,
) -> ToolCallingProbeResult:
    """Fill a probe result failure without leaking credentials."""

    result.ok = False
    result.stage = stage
    result.status_code = status_code
    result.error = _redact_secrets(error)[:320]
    result.provider_message = _redact_secrets(provider_message)[:240] if provider_message else None
    return result


def probe_openai_tool_calling_capability(
    base_url: str,
    api_key: str,
    model: str,
    *,
    protocol: str = "openai_chat_completions",
    timeout_s: float = 10.0,
) -> ToolCallingProbeResult:
    """Probe whether an OpenAI-compatible provider truly supports tools.

    Args:
        base_url: Provider base URL, typically ending in `/v1`.
        api_key: Secret used only in the Authorization header.
        model: Real configured model id; fake model probes cannot prove tools.
        protocol: Currently only `openai_chat_completions` is supported.
        timeout_s: Per-client timeout for the three short HTTP calls.

    Returns:
        A redacted result for `/v1/models`, ordinary chat, and forced
        `tool_choice` with a tiny function schema.
    """

    normalized_base = (base_url or "").strip()
    normalized_model = (model or "").strip()
    normalized_protocol = (protocol or "").strip().lower()
    result = ToolCallingProbeResult(
        ok=False,
        protocol=normalized_protocol or protocol,
        model=normalized_model,
        models_url=_build_models_url(normalized_base),
        chat_url=_chat_probe_url(normalized_base, normalized_protocol) or "",
    )

    if not normalized_base:
        return _probe_failure(result, stage="configuration", error="base_url is required")
    if not normalized_model:
        return _probe_failure(result, stage="configuration", error="model is required")
    if normalized_protocol != "openai_chat_completions":
        return _probe_failure(
            result,
            stage="configuration",
            error=f"unsupported protocol: {normalized_protocol or protocol}",
        )
    if not result.models_url or not result.chat_url:
        return _probe_failure(result, stage="configuration", error="invalid provider endpoint")

    try:
        validate_outbound_endpoint(
            normalized_base,
            "tool_calling_probe",
            strict=False,
            allow_loopback_http=True,
        )
    except ValueError as exc:
        return _probe_failure(result, stage="endpoint_validation", error=str(exc))

    headers = {
        **_build_auth_headers(api_key, normalized_protocol),
        "Content-Type": "application/json",
        "User-Agent": "literature-assistant-provider-tool-probe/1.0",
    }
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=False) as client:
            models_response = client.get(result.models_url, headers=headers)
            result.status_code = models_response.status_code
            result.stage = "models"
            if not 200 <= models_response.status_code < 400:
                provider_message = _extract_provider_error_message(models_response.text or "")
                return _probe_failure(
                    result,
                    stage="models",
                    status_code=models_response.status_code,
                    error=f"HTTP {models_response.status_code}" + (f": {provider_message}" if provider_message else ""),
                    provider_message=provider_message,
                )
            result.models_ok = True

            chat_response = client.post(
                result.chat_url,
                json=_ordinary_chat_probe_payload(normalized_model),
                headers=headers,
            )
            result.status_code = chat_response.status_code
            result.stage = "ordinary_chat"
            if not 200 <= chat_response.status_code < 400:
                provider_message = _extract_provider_error_message(chat_response.text or "")
                return _probe_failure(
                    result,
                    stage="ordinary_chat",
                    status_code=chat_response.status_code,
                    error=f"HTTP {chat_response.status_code}" + (f": {provider_message}" if provider_message else ""),
                    provider_message=provider_message,
                )
            result.chat_ok = True

            tool_response = client.post(
                result.chat_url,
                json=_forced_tool_choice_probe_payload(normalized_model),
                headers=headers,
            )
            result.status_code = tool_response.status_code
            result.stage = "forced_tool_choice"
            if not 200 <= tool_response.status_code < 400:
                provider_message = _extract_provider_error_message(tool_response.text or "")
                return _probe_failure(
                    result,
                    stage="forced_tool_choice",
                    status_code=tool_response.status_code,
                    error=f"HTTP {tool_response.status_code}" + (f": {provider_message}" if provider_message else ""),
                    provider_message=provider_message,
                )
            data = _json_object_response(tool_response)
            if data is None or not _contains_forced_tool_call(data, "capability_probe"):
                provider_message = _extract_provider_error_message(tool_response.text or "")
                return _probe_failure(
                    result,
                    stage="forced_tool_choice",
                    status_code=tool_response.status_code,
                    error="forced_tool_choice_not_returned",
                    provider_message=provider_message,
                )
            result.forced_tool_choice_ok = True
            result.ok = True
            return result
    except httpx.TimeoutException:
        return _probe_failure(result, stage=result.stage or "transport", error="timeout")
    except httpx.ConnectError:
        return _probe_failure(result, stage=result.stage or "transport", error="connect_error")
    except httpx.HTTPError as exc:
        return _probe_failure(
            result,
            stage=result.stage or "transport",
            error=f"http_error:{type(exc).__name__}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("provider tool probe unexpected failure: %s", type(exc).__name__)
        return _probe_failure(
            result,
            stage=result.stage or "unexpected",
            error=f"unexpected:{type(exc).__name__}",
        )


__all__ = [
    "ProbeResult",
    "DiscoverResult",
    "ToolCallingProbeResult",
    "validate_outbound_endpoint",
    "probe_endpoint_reachability",
    "probe_openai_tool_calling_capability",
    "discover_models",
]
