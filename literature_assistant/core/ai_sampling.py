"""Centralised LLM sampling defaults per task type.

This module provides a single, lightweight resolver that maps a task type
(``"focus_extract"``, ``"summarize"``, ``"citation"``, ``"creative"``,
``"default"``) to a baseline ``{temperature, top_p}`` payload. Callers
may pass an ``override`` dict (typically sourced from a frontend request
like ``llm.temperature`` / ``llm.top_p``) which wins per-key.

It is intentionally additive: existing call sites that hardcode their
own sampling values continue to work unchanged. New code should prefer
``resolve_sampling()`` so behaviour is consistent and tunable.
"""

from __future__ import annotations

from typing import Any

LLM_SAMPLING_DEFAULTS: dict[str, dict[str, float]] = {
    # Deterministic structured extraction. Lower top_p reduces the chance
    # of the model drifting into prose when we want JSON-like output.
    "focus_extract": {"temperature": 0.1, "top_p": 0.5},
    # Faithful condensation; allow some lexical variety but stay grounded.
    "summarize": {"temperature": 0.3, "top_p": 0.9},
    # Citation / reference rendering — must be precise.
    "citation": {"temperature": 0.2, "top_p": 0.7},
    # Brainstorming / spark generation — favour exploration.
    "creative": {"temperature": 0.7, "top_p": 0.95},
    # Generic chat / mixed tasks.
    "default": {"temperature": 0.3, "top_p": 0.9},
}

# Keys we recognise as sampling overrides from upstream callers.
_ALLOWED_KEYS = ("temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty")


def _coerce_number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_sampling(
    task_type: str | None,
    override: dict[str, Any] | None = None,
) -> dict[str, float | int]:
    """Return a sampling payload for ``task_type``, with per-key overrides.

    Unknown ``task_type`` values fall back to ``"default"``. Keys not in
    :data:`_ALLOWED_KEYS` are ignored. Numeric overrides that fail to
    coerce are dropped silently rather than raising — this is a config
    helper, not an input validator.
    """
    base_key = (task_type or "default").strip().lower()
    base = dict(LLM_SAMPLING_DEFAULTS.get(base_key) or LLM_SAMPLING_DEFAULTS["default"])
    if not override:
        return base
    for key in _ALLOWED_KEYS:
        if key not in override:
            continue
        coerced = _coerce_number(override[key])
        if coerced is None:
            continue
        base[key] = coerced
    return base


__all__ = ["LLM_SAMPLING_DEFAULTS", "resolve_sampling"]
