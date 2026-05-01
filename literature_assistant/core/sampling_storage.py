from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from llm_defaults import resolve_llm_params

_ALLOWED_KEYS = ("temperature", "top_p", "top_k", "max_tokens")
_WRITE_LOCK = threading.Lock()


def _sampling_file() -> Path:
    return Path.home() / ".literature-lab" / "sampling.json"


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
        return data
    except Exception:
        return {}


def save_user_sampling(payload: dict[str, Any]) -> None:
    """Validate and persist per-task sampling overrides."""
    if not isinstance(payload, dict):
        raise ValueError("tasks payload must be an object")

    sanitized: dict[str, dict[str, float | int]] = {}
    for task, overrides in payload.items():
        if not isinstance(task, str):
            raise ValueError("task name must be a string")
        if not isinstance(overrides, dict):
            raise ValueError(f"{task} overrides must be an object")

        resolved = resolve_llm_params(task, user_overrides=overrides)
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
