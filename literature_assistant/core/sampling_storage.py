from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from llm_defaults import resolve_llm_params

_ALLOWED_KEYS = ("temperature", "top_p", "top_k", "max_tokens")
_WRITE_LOCK = threading.Lock()

_LEGACY_HIGH_DEFAULTS: dict[str, dict[str, float | int]] = {
    "chat": {"temperature": 0.7, "top_p": 0.9, "top_k": 50, "max_tokens": 2048},
    "inspiration": {"temperature": 0.85, "top_p": 0.95, "top_k": 80, "max_tokens": 1024},
    "extraction": {"temperature": 0.1, "top_p": 0.5, "top_k": 20, "max_tokens": 4096},
    "summarization": {"temperature": 0.3, "top_p": 0.7, "top_k": 30, "max_tokens": 2048},
    "rewrite": {"temperature": 0.5, "top_p": 0.8, "top_k": 40, "max_tokens": 2048},
}


def _sampling_file() -> Path:
    return Path.home() / ".literature-lab" / "sampling.json"


def _is_legacy_high_default(task: str, key: str, value: float | int) -> bool:
    legacy_value = _LEGACY_HIGH_DEFAULTS.get(task, {}).get(key)
    if legacy_value is None:
        return False
    if isinstance(value, float) or isinstance(legacy_value, float):
        return abs(float(value) - float(legacy_value)) < 1e-9
    return int(value) == int(legacy_value)


def _looks_like_legacy_default_snapshot(task: str, overrides: dict[str, Any]) -> bool:
    legacy_defaults = _LEGACY_HIGH_DEFAULTS.get(task)
    if legacy_defaults is None:
        return False
    valid_legacy_values = 0
    for key in _ALLOWED_KEYS:
        if key not in overrides or overrides.get(key) is None:
            continue
        try:
            resolve_llm_params(task, {key: overrides[key]})
        except (TypeError, ValueError):
            continue
        if not _is_legacy_high_default(task, key, overrides[key]):
            return False
        valid_legacy_values += 1
    return valid_legacy_values >= 2


def _sanitize_loaded_overrides(task: str, overrides: dict[str, Any]) -> dict[str, float | int]:
    drop_legacy_snapshot = _looks_like_legacy_default_snapshot(task, overrides)
    sanitized: dict[str, float | int] = {}
    for key in _ALLOWED_KEYS:
        if key not in overrides or overrides.get(key) is None:
            continue
        try:
            resolve_llm_params(task, {key: overrides[key]})
        except (TypeError, ValueError):
            continue
        value = int(overrides[key]) if key in {"top_k", "max_tokens"} else float(overrides[key])
        if drop_legacy_snapshot and _is_legacy_high_default(task, key, value):
            continue
        sanitized[key] = value
    return sanitized


def load_user_sampling() -> dict[str, dict[str, float | int]]:
    """Return persisted per-task sampling overrides, or {} on missing/corrupt data."""
    try:
        with _WRITE_LOCK:
            path = _sampling_file()
            if not path.is_file():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        if any(not isinstance(task, str) or not isinstance(overrides, dict) for task, overrides in data.items()):
            return {}
        sanitized: dict[str, dict[str, float | int]] = {}
        for task, overrides in data.items():
            next_overrides = _sanitize_loaded_overrides(task, overrides)
            if next_overrides:
                sanitized[task] = next_overrides
        return sanitized
    except Exception:
        return {}


def save_user_sampling(
    payload: dict[str, Any],
    *,
    max_tokens_limit: int | None = None,
) -> None:
    """Validate and persist per-task sampling overrides.

    Args:
        payload: Per-task sampling overrides keyed by task name.
        max_tokens_limit: Optional active model-context ceiling. The sampling
            endpoint supplies this value so a saved output budget cannot exceed
            the model context configured for answer generation.

    Raises:
        ValueError: If the payload shape, a sampling value, or the configured
            output-token ceiling is invalid.
    """
    if not isinstance(payload, dict):
        raise ValueError("tasks payload must be an object")
    if max_tokens_limit is not None and (
        isinstance(max_tokens_limit, bool)
        or not isinstance(max_tokens_limit, int)
        or max_tokens_limit < 1
    ):
        raise ValueError("max_tokens_limit must be a positive integer")

    sanitized: dict[str, dict[str, float | int]] = {}
    for task, overrides in payload.items():
        if not isinstance(task, str):
            raise ValueError("task name must be a string")
        if not isinstance(overrides, dict):
            raise ValueError(f"{task} overrides must be an object")

        resolved = resolve_llm_params(task, user_overrides=overrides)
        if (
            max_tokens_limit is not None
            and overrides.get("max_tokens") is not None
            and int(resolved["max_tokens"]) > max_tokens_limit
        ):
            raise ValueError(
                "max_tokens exceeds the configured model context window "
                f"({max_tokens_limit})"
            )
        sanitized[task] = {
            key: resolved[key]
            for key in _ALLOWED_KEYS
            if key in overrides and overrides.get(key) is not None
        }

    path = _sampling_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(sanitized, ensure_ascii=False, indent=2)

    with _WRITE_LOCK:
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)
