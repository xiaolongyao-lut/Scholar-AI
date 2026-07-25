"""Provider-specific payload compatibility for OpenAI-style chat endpoints."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit


_NVIDIA_PROVIDER_KEYS = frozenset({"nvidia", "nvidia nim", "nvidia api catalog", "nim"})
_NVIDIA_HOSTS = frozenset({"integrate.api.nvidia.com"})
_NVIDIA_REASONING_EFFORTS = frozenset({"none", "high", "max"})
_NVIDIA_REASONING_EFFORT_ALIASES = {
    "off": "none",
    "false": "none",
    "non-think": "none",
    "non_think": "none",
    "low": "high",
    "medium": "high",
}
_NVIDIA_DEEPSEEK_V4_FLASH_MODEL = "deepseek-ai/deepseek-v4-flash"
_NVIDIA_DEFAULT_TIMEOUT_S = 180.0
_ANTHROPIC_MESSAGES_DEFAULT_TIMEOUT_S = 120.0


def _clean_string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return value.strip()


def _host_from_url(base_url: str) -> str:
    cleaned = _clean_string(base_url)
    if not cleaned:
        return ""
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return ""
    return (parsed.hostname or "").lower().rstrip(".")


def is_nvidia_chat_endpoint(provider: str, base_url: str) -> bool:
    """Return whether a chat request targets NVIDIA's hosted NIM API.

    Args:
        provider: User-visible provider label from settings or credentials.
        base_url: Provider base URL. Query strings and fragments are rejected
            elsewhere; this helper only classifies known safe host names.

    Returns:
        True when the provider label or host is NVIDIA-specific.
    """

    provider_key = _clean_string(provider).lower()
    host = _host_from_url(base_url)
    return provider_key in _NVIDIA_PROVIDER_KEYS or host in _NVIDIA_HOSTS


def is_nvidia_deepseek_v4_flash_model(model: str) -> bool:
    """Return whether the model uses NVIDIA's DeepSeek V4 Flash chat template."""

    normalized = _clean_string(model).lower()
    return normalized == _NVIDIA_DEEPSEEK_V4_FLASH_MODEL


def is_anthropic_messages_endpoint(provider: str, base_url: str) -> bool:
    """Return whether a chat probe should use Anthropic Messages timing."""

    provider_key = _clean_string(provider).lower()
    host = _host_from_url(base_url)
    return (
        "anthropic" in provider_key
        or "claude" in provider_key
        or host == "api.anthropic.com"
        or host.endswith(".anthropic.com")
    )


def is_glm_thinking_model(model: str) -> bool:
    """Return whether the model often spends probe tokens on hidden reasoning."""

    normalized = _clean_string(model).lower()
    return normalized.startswith("glm-") or "/glm-" in normalized or "z-ai/glm-" in normalized


def _env_first_float(names: tuple[str, ...], default: float) -> float:
    if default <= 0:
        raise ValueError("default timeout must be positive")
    for name in names:
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if 1.0 <= value <= 600.0:
            return value
    return default


def provider_http_timeout_s(
    *,
    provider: str,
    base_url: str,
    model: str,
    default_s: float,
) -> float:
    """Return a provider-aware timeout for live reachability and chat probes.

    Args:
        provider: Provider label used by settings or credential records.
        base_url: Provider base URL.
        model: Configured model id.
        default_s: Existing caller timeout in seconds.

    Returns:
        The original timeout for ordinary providers. NVIDIA hosted free-tier
        chat can take well over a minute for small prompts, so its timeout is
        raised unless ``LITASSIST_NVIDIA_HTTP_TIMEOUT`` or
        ``NVIDIA_HTTP_TIMEOUT`` supplies a bounded override.
    """

    if default_s <= 0:
        raise ValueError("default_s must be positive")
    if is_nvidia_chat_endpoint(provider, base_url) or is_nvidia_deepseek_v4_flash_model(model):
        return max(
            default_s,
            _env_first_float(
                ("LITASSIST_NVIDIA_HTTP_TIMEOUT", "NVIDIA_HTTP_TIMEOUT"),
                _NVIDIA_DEFAULT_TIMEOUT_S,
            ),
        )
    if is_anthropic_messages_endpoint(provider, base_url) or is_glm_thinking_model(model):
        return max(
            default_s,
            _env_first_float(
                ("LITASSIST_ANTHROPIC_MESSAGES_HTTP_TIMEOUT", "ANTHROPIC_MESSAGES_HTTP_TIMEOUT"),
                _ANTHROPIC_MESSAGES_DEFAULT_TIMEOUT_S,
            ),
        )
    return default_s


def nvidia_reasoning_effort_for_model(model: str) -> str | None:
    """Return NVIDIA DeepSeek reasoning effort for raw HTTP payloads.

    Args:
        model: Configured model id.

    Returns:
        ``None`` for non-NVIDIA DeepSeek V4 Flash models; otherwise one of
        ``none|high|max``. The default is ``none`` because Scholar AI
        needs responsive grounded answers, while operators can opt into deeper
        hosted reasoning with ``LITASSIST_NVIDIA_REASONING_EFFORT``.
    """

    if not is_nvidia_deepseek_v4_flash_model(model):
        return None
    raw = (
        os.getenv("LITASSIST_NVIDIA_REASONING_EFFORT")
        or os.getenv("NVIDIA_REASONING_EFFORT")
        or "none"
    )
    effort = _NVIDIA_REASONING_EFFORT_ALIASES.get(raw.strip().lower(), raw.strip().lower())
    return effort if effort in _NVIDIA_REASONING_EFFORTS else "none"


def apply_openai_chat_payload_compat(
    payload: dict[str, Any],
    *,
    provider: str,
    base_url: str,
    model: str,
    top_k: int | None,
) -> None:
    """Mutate an OpenAI-compatible chat payload for provider edge cases.

    Args:
        payload: Request body already containing model/messages/token fields.
        provider: Provider label used by routing.
        base_url: Provider base URL.
        model: Provider model id already resolved by the caller.
        top_k: Optional sampling value from Scholar AI's generic settings.
    Raises:
        TypeError: If payload is not a JSON-object-like dictionary.
        ValueError: If top_k is outside the bounded positive integer shape.
    """

    if not isinstance(payload, dict):
        raise TypeError("payload must be a dictionary")
    nvidia_endpoint = is_nvidia_chat_endpoint(provider, base_url)
    if top_k is not None:
        if not isinstance(top_k, int):
            raise TypeError("top_k must be an integer or None")
        if top_k < 0:
            raise ValueError("top_k must be non-negative")
        if top_k > 0 and not nvidia_endpoint:
            extra_body = payload.get("extra_body")
            if extra_body is None:
                extra_body = {}
                payload["extra_body"] = extra_body
            if not isinstance(extra_body, dict):
                raise TypeError("payload.extra_body must be a dictionary when present")
            extra_body["top_k"] = top_k

    effort = nvidia_reasoning_effort_for_model(model) if nvidia_endpoint else None
    if effort is not None:
        payload["reasoning_effort"] = effort


__all__ = [
    "apply_openai_chat_payload_compat",
    "is_anthropic_messages_endpoint",
    "is_glm_thinking_model",
    "is_nvidia_chat_endpoint",
    "is_nvidia_deepseek_v4_flash_model",
    "nvidia_reasoning_effort_for_model",
    "provider_http_timeout_s",
]
