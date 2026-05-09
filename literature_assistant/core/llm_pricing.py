"""Per-model token pricing and cost estimation.

Prices are USD per 1M tokens (input / output), aligned with public
list prices for the providers the project currently routes through.
Update conservatively — when in doubt prefer slight over-estimation
so the daily budget guard errs on the safe side.

Pricing is consulted only by :mod:`llm_cost_logger`; nothing in the
production hot-path depends on it being exhaustive. Unknown models
fall back to a generic mid-tier estimate so telemetry stays useful.
"""

from __future__ import annotations

from typing import Any

# (input_per_million, output_per_million) in USD.
MODEL_PRICING_USD_PER_M: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Anthropic
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (1.00, 5.00),
    "claude-3-opus": (15.00, 75.00),
    # DashScope (Qwen)
    "qwen-max": (1.40, 5.60),
    "qwen-plus": (0.40, 1.20),
    "qwen-turbo": (0.20, 0.60),
    "qwen2.5-72b-instruct": (1.00, 3.00),
    # SiliconFlow (a representative subset)
    "deepseek-chat": (0.27, 1.10),
    "deepseek-v3": (0.27, 1.10),
    "deepseek-r1": (0.55, 2.19),
    "qwen/qwen2.5-72b-instruct": (1.00, 3.00),
}

# Used when the model identifier doesn't match anything in the table.
_FALLBACK_PRICING: tuple[float, float] = (1.00, 3.00)


def _normalize_model(model: str | None) -> str:
    if not model:
        return ""
    name = str(model).strip().lower()
    # Strip common prefixes like "openai/" or "anthropic:".
    for sep in ("/", ":"):
        if sep in name:
            tail = name.rsplit(sep, 1)[-1]
            if tail:
                name = tail
                break
    return name


def lookup_pricing(model: str | None) -> tuple[float, float]:
    """Return ``(input_usd_per_million, output_usd_per_million)``.

    Falls back to a generic mid-tier price when the model is unknown
    so cost telemetry remains continuous (downstream can detect the
    fallback by checking ``is_known_model``).
    """
    name = _normalize_model(model)
    if name in MODEL_PRICING_USD_PER_M:
        return MODEL_PRICING_USD_PER_M[name]
    # Try a prefix match for versioned aliases like "gpt-4o-2024-08-06".
    for known in MODEL_PRICING_USD_PER_M:
        if name.startswith(known):
            return MODEL_PRICING_USD_PER_M[known]
    return _FALLBACK_PRICING


def is_known_model(model: str | None) -> bool:
    name = _normalize_model(model)
    if name in MODEL_PRICING_USD_PER_M:
        return True
    return any(name.startswith(known) for known in MODEL_PRICING_USD_PER_M)


def estimate_cost_usd(
    model: str | None,
    *,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Estimate USD cost for a single completion call.

    ``prompt_tokens`` / ``completion_tokens`` map directly to the
    OpenAI ``response.usage`` fields. Negative values are clamped to
    zero. Returns a non-negative float rounded to 6 decimal places.
    """
    p_in, p_out = lookup_pricing(model)
    pt = max(0, int(prompt_tokens or 0))
    ct = max(0, int(completion_tokens or 0))
    cost = (pt / 1_000_000.0) * p_in + (ct / 1_000_000.0) * p_out
    return round(cost, 6)


def usage_from_response(response: Any) -> dict[str, int]:
    """Best-effort extraction of token usage from an OpenAI-shaped response.

    Returns ``{"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}``;
    missing fields default to 0 so callers can always log a record.
    """
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _get(field: str) -> int:
        value = getattr(usage, field, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(field)
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    pt = _get("prompt_tokens")
    ct = _get("completion_tokens")
    tt = _get("total_tokens") or (pt + ct)
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt}


__all__ = [
    "MODEL_PRICING_USD_PER_M",
    "estimate_cost_usd",
    "is_known_model",
    "lookup_pricing",
    "usage_from_response",
]
