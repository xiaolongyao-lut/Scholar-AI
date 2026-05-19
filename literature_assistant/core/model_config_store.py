"""Generic runtime override store for model subsystem configurations.

Each subsystem (chat, embedding, rerank) gets its own JSON file under
``runtime_state/`` with identical semantics:

- Fields: provider, base_url, api_key, model, updated_at
- Missing fields fall through to the env resolution chain
- api_key is never exposed in public config (masked only)
- Writes are atomic (tempfile + os.replace)
- Thread-safe via per-instance lock

Usage::

    from model_config_store import ModelConfigStore

    chat_config = ModelConfigStore("chat")
    embedding_config = ModelConfigStore("embedding")
    rerank_config = ModelConfigStore("rerank")
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from project_paths import runtime_state_path


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _coerce_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


_VALID_FIELDS = frozenset({"provider", "base_url", "api_key", "model"})


class SettingsStore:
    """Generic JSON settings store for non-model subsystems.

    Unlike ModelConfigStore (which has fixed fields for LLM configs),
    this accepts arbitrary field names and stores them as-is.
    """

    __slots__ = ("_subsystem", "_path", "_lock", "_allowed_fields")

    def __init__(self, subsystem: str, allowed_fields: frozenset[str]) -> None:
        self._subsystem = subsystem
        self._path: Path = runtime_state_path(f"{subsystem}_settings.json")
        self._lock = threading.Lock()
        self._allowed_fields = allowed_fields

    @property
    def subsystem(self) -> str:
        return self._subsystem

    @property
    def path(self) -> Path:
        return self._path

    def _read_raw(self) -> dict[str, Any]:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def get_settings(self) -> dict[str, Any]:
        """Return all stored settings."""
        raw = self._read_raw()
        return {k: v for k, v in raw.items() if k in self._allowed_fields or k == "updated_at"}

    def write_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Atomically write settings. Only allowed_fields are persisted."""
        with self._lock:
            existing = self._read_raw()
            payload: dict[str, Any] = dict(existing)
            for field, value in updates.items():
                if field in self._allowed_fields:
                    payload[field] = value
            payload["updated_at"] = _now_iso()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=f"{self._subsystem}_settings_",
                suffix=".json.tmp",
                dir=str(self._path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, self._path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        return self.get_settings()

    def clear_settings(self) -> None:
        """Remove the settings file."""
        with self._lock:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass


_VALID_FIELDS = frozenset({"provider", "base_url", "api_key", "model"})


class ModelConfigStore:
    """Runtime override store for a single model subsystem."""

    __slots__ = ("_subsystem", "_path", "_lock")

    def __init__(self, subsystem: str) -> None:
        self._subsystem = subsystem
        self._path: Path = runtime_state_path(f"{subsystem}_override.json")
        self._lock = threading.Lock()

    @property
    def subsystem(self) -> str:
        return self._subsystem

    @property
    def path(self) -> Path:
        return self._path

    def _read_raw(self) -> dict[str, Any]:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def get_public_config(self) -> dict[str, Any]:
        """Return override fields safe to surface to the UI (api_key masked)."""
        raw = self._read_raw()
        api_key = _coerce_string(raw.get("api_key"))
        masked_key = ""
        has_key = bool(api_key)
        if has_key:
            if len(api_key or "") >= 8:
                masked_key = f"{api_key[:4]}***{api_key[-4:]}"
            else:
                masked_key = "***"
        return {
            "provider": _coerce_string(raw.get("provider")) or "",
            "base_url": _coerce_string(raw.get("base_url")) or "",
            "model": _coerce_string(raw.get("model")) or "",
            "has_api_key": has_key,
            "api_key_masked": masked_key,
            "updated_at": _coerce_string(raw.get("updated_at")) or "",
        }

    def get_resolved_field(self, name: str) -> str | None:
        """Return the raw override value for a field, or None to fall through."""
        if name not in _VALID_FIELDS:
            return None
        raw = self._read_raw()
        return _coerce_string(raw.get(name))

    def write_config(
        self,
        *,
        provider: str | None,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
    ) -> dict[str, Any]:
        """Atomically write the override document.

        api_key semantics: None = keep existing, "" = clear, str = set.
        """
        with self._lock:
            existing = self._read_raw()
            payload: dict[str, Any] = {}
            for field, value in (
                ("provider", provider),
                ("base_url", base_url),
                ("model", model),
            ):
                cleaned = _coerce_string(value)
                if cleaned:
                    payload[field] = cleaned
            if api_key is None:
                existing_key = _coerce_string(existing.get("api_key"))
                if existing_key:
                    payload["api_key"] = existing_key
            else:
                cleaned_key = _coerce_string(api_key)
                if cleaned_key:
                    payload["api_key"] = cleaned_key
            payload["updated_at"] = _now_iso()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=f"{self._subsystem}_override_",
                suffix=".json.tmp",
                dir=str(self._path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, self._path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        return self.get_public_config()

    def clear_config(self) -> None:
        """Remove the override file (revert to env-only resolution)."""
        with self._lock:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass


# Singleton instances for each subsystem
chat_store = ModelConfigStore("chat")
embedding_store = ModelConfigStore("embedding")
rerank_store = ModelConfigStore("rerank")

# Discussion defaults store (C3a carry-over plan)
_DISCUSSION_DEFAULTS_FIELDS = frozenset({
    "auto_stop",
    "min_turns",
    "convergence_threshold",
    "convergence_judge_agent_id",
})
discussion_defaults_store = SettingsStore("discussion_defaults", _DISCUSSION_DEFAULTS_FIELDS)

__all__ = [
    "ModelConfigStore",
    "SettingsStore",
    "chat_store",
    "embedding_store",
    "rerank_store",
    "discussion_defaults_store",
]
