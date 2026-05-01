from __future__ import annotations

import os
from typing import Any

TASK_DEFAULTS: dict[str, dict[str, float | int]] = {
    "chat": {"temperature": 0.7, "top_p": 0.9, "top_k": 50, "max_tokens": 2048},
    "inspiration": {"temperature": 0.85, "top_p": 0.95, "top_k": 80, "max_tokens": 1024},
    "extraction": {"temperature": 0.1, "top_p": 0.5, "top_k": 20, "max_tokens": 4096},
    "summarization": {"temperature": 0.3, "top_p": 0.7, "top_k": 30, "max_tokens": 2048},
    "rewrite": {"temperature": 0.5, "top_p": 0.8, "top_k": 40, "max_tokens": 2048},
}

TASK_ALIASES = {
    "summary": "summarization",
    "summarize": "summarization",
    "creative": "inspiration",
    "focus_extract": "extraction",
    "default": "chat",
}

MODEL_MAX_TOKENS = max(1, int(os.getenv("MODEL_MAX_TOKENS", "32768")))
_ALLOWED_KEYS = ("temperature", "top_p", "top_k", "max_tokens")


def _normalize_task(task: str | None) -> str:
    raw = str(task or "chat").strip().lower()
    return TASK_ALIASES.get(raw, raw if raw in TASK_DEFAULTS else "chat")


def _validate_params(params: dict[str, float | int]) -> None:
    temperature = float(params["temperature"])
    top_p = float(params["top_p"])
    top_k = int(params["top_k"])
    max_tokens = int(params["max_tokens"])

    if not 0 <= temperature <= 2:
        raise ValueError("temperature out of range")
    if not 0 < top_p <= 1:
        raise ValueError("top_p out of range")
    if not 1 <= top_k <= 200:
        raise ValueError("top_k out of range")
    if not 1 <= max_tokens <= MODEL_MAX_TOKENS:
        raise ValueError("max_tokens out of range")


def resolve_llm_params(task: str | None, user_overrides: dict[str, Any] | None = None) -> dict[str, float | int]:
    resolved = dict(TASK_DEFAULTS[_normalize_task(task)])
    if user_overrides:
        for key in _ALLOWED_KEYS:
            value = user_overrides.get(key)
            if value is not None:
                resolved[key] = value
    _validate_params(resolved)
    return resolved


__all__ = ["MODEL_MAX_TOKENS", "TASK_DEFAULTS", "resolve_llm_params"]
