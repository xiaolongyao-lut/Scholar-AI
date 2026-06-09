"""Generic runtime override store for model subsystem configurations.

Each subsystem (chat, embedding, rerank) gets its own JSON file under
``runtime_state/`` with identical semantics:

- Fields: provider, base_url, api_key_secret_ref, model, updated_at
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

from _atomic_io import CrossProcessFileLock
from credential_store import CredentialSecretBackend, _select_secret_backend
from models.credentials import mask_api_key
from project_paths import runtime_state_path


MODEL_OVERRIDE_SECRET_REF_FIELD = "api_key_secret_ref"


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

    @property
    def _file_lock_path(self) -> Path:
        return self._path.with_suffix(f"{self._path.suffix}.lock")

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
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            raw = self._read_raw()
        return {k: v for k, v in raw.items() if k in self._allowed_fields or k == "updated_at"}

    def write_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Atomically write settings. Only allowed_fields are persisted."""
        with self._lock, CrossProcessFileLock(self._file_lock_path):
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
            return {
                k: v for k, v in payload.items()
                if k in self._allowed_fields or k == "updated_at"
            }

    def clear_settings(self) -> None:
        """Remove the settings file."""
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass


_VALID_FIELDS = frozenset({"provider", "base_url", "api_key", "model"})


class ModelConfigStore:
    """Runtime override store for a single model subsystem."""

    __slots__ = ("_subsystem", "_path", "_lock", "_secret_backend")

    def __init__(
        self,
        subsystem: str,
        *,
        secret_backend: CredentialSecretBackend | None = None,
    ) -> None:
        self._subsystem = subsystem
        self._path: Path = runtime_state_path(f"{subsystem}_override.json")
        self._lock = threading.RLock()
        self._secret_backend = secret_backend

    @property
    def subsystem(self) -> str:
        return self._subsystem

    @property
    def path(self) -> Path:
        return self._path

    @property
    def _file_lock_path(self) -> Path:
        return self._path.with_suffix(f"{self._path.suffix}.lock")

    @property
    def _active_secret_backend(self) -> CredentialSecretBackend:
        if self._secret_backend is not None:
            return self._secret_backend
        return _select_secret_backend(self._path)

    def _new_secret_ref(self) -> str:
        return self._active_secret_backend.create_secret_ref(f"model_override_{self._subsystem}")

    def _read_api_key_from_raw(self, raw: dict[str, Any]) -> str | None:
        legacy_key = _coerce_string(raw.get("api_key"))
        if legacy_key:
            return legacy_key
        secret_ref = _coerce_string(raw.get(MODEL_OVERRIDE_SECRET_REF_FIELD))
        if not secret_ref:
            return None
        try:
            return _coerce_string(self._active_secret_backend.get_secret(secret_ref))
        except Exception:
            return None

    def _migrate_plaintext_api_key_if_needed(self, raw: dict[str, Any]) -> dict[str, Any]:
        api_key = _coerce_string(raw.get("api_key"))
        if not api_key:
            return raw
        migrated = dict(raw)
        migrated.pop("api_key", None)
        secret_ref = _coerce_string(migrated.get(MODEL_OVERRIDE_SECRET_REF_FIELD)) or self._new_secret_ref()
        self._active_secret_backend.store_secret(secret_ref, api_key)
        migrated[MODEL_OVERRIDE_SECRET_REF_FIELD] = secret_ref
        self._write_raw_payload(migrated)
        return migrated

    def _read_raw(self) -> dict[str, Any]:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            raw = data if isinstance(data, dict) else {}
            if raw:
                return self._migrate_plaintext_api_key_if_needed(raw)
            return raw
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_raw_payload(self, payload: dict[str, Any]) -> None:
        if "api_key" in payload:
            raise ValueError("model override payload must not contain api_key")
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

    def get_public_config(self) -> dict[str, Any]:
        """Return override fields safe to surface to the UI (api_key masked)."""
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            raw = self._read_raw()
            api_key = self._read_api_key_from_raw(raw)
        masked_key = mask_api_key(api_key or "")
        return {
            "provider": _coerce_string(raw.get("provider")) or "",
            "base_url": _coerce_string(raw.get("base_url")) or "",
            "model": _coerce_string(raw.get("model")) or "",
            "has_api_key": bool(api_key),
            "api_key_masked": masked_key,
            "updated_at": _coerce_string(raw.get("updated_at")) or "",
        }

    def get_resolved_field(self, name: str) -> str | None:
        """Return the raw override value for a field, or None to fall through."""
        if name not in _VALID_FIELDS:
            return None
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            raw = self._read_raw()
            if name == "api_key":
                return self._read_api_key_from_raw(raw)
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
        with self._lock, CrossProcessFileLock(self._file_lock_path):
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
            existing_ref = _coerce_string(existing.get(MODEL_OVERRIDE_SECRET_REF_FIELD))
            if api_key is None:
                if existing_ref:
                    payload[MODEL_OVERRIDE_SECRET_REF_FIELD] = existing_ref
            else:
                cleaned_key = _coerce_string(api_key)
                if cleaned_key:
                    secret_ref = existing_ref or self._new_secret_ref()
                    self._active_secret_backend.store_secret(secret_ref, cleaned_key)
                    payload[MODEL_OVERRIDE_SECRET_REF_FIELD] = secret_ref
                elif existing_ref:
                    try:
                        self._active_secret_backend.delete_secret(existing_ref)
                    except Exception:
                        pass
            payload["updated_at"] = _now_iso()
            self._write_raw_payload(payload)
        return self.get_public_config()

    def clear_config(self) -> None:
        """Remove the override file (revert to env-only resolution)."""
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            raw = self._read_raw()
            secret_ref = _coerce_string(raw.get(MODEL_OVERRIDE_SECRET_REF_FIELD))
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass
            if secret_ref:
                try:
                    self._active_secret_backend.delete_secret(secret_ref)
                except Exception:
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

_CHAT_CONTEXT_COMPRESSION_FIELDS = frozenset({
    "enabled",
    "trigger_tokens",
    "target_tokens",
    "keep_recent_turns",
})
chat_context_compression_store = SettingsStore(
    "chat_context_compression",
    _CHAT_CONTEXT_COMPRESSION_FIELDS,
)

__all__ = [
    "ModelConfigStore",
    "SettingsStore",
    "chat_store",
    "embedding_store",
    "rerank_store",
    "discussion_defaults_store",
    "chat_context_compression_store",
]
