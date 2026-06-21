"""Runtime provider capability records for guarded tool dispatch."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from _atomic_io import CrossProcessFileLock, atomic_write_json
from project_paths import runtime_state_path


CAPABILITY_STATUS_UNKNOWN = "unknown"
CAPABILITY_STATUS_TOOL_CALL_OK = "tool_call_ok"
CAPABILITY_STATUS_PROBE_FAILED = "probe_failed"
CAPABILITY_STATUS_UNSUPPORTED = "unsupported"
CAPABILITY_STATUS_AUTH_REQUIRED = "auth_required"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_text(value: str | None, *, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def _endpoint_host(base_url: str) -> str:
    parsed = urlparse(str(base_url or "").strip())
    return (parsed.netloc or parsed.path).lower()


def provider_fingerprint(*, provider: str, base_url: str, model: str) -> str:
    """Return a stable non-secret fingerprint for a provider/model endpoint."""

    normalized = {
        "provider": _clean_text(provider, max_length=120).lower(),
        "host": _endpoint_host(base_url),
        "model": _clean_text(model, max_length=240),
    }
    blob = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProviderCapabilityRecord:
    """Persisted capability state for one provider/model endpoint.

    Args:
        fingerprint: Stable hash of provider, endpoint host, and model.
        provider: User-facing provider label.
        base_url_host: Host only; full URLs may contain private deployment paths.
        model: Model id supplied by the user/configuration.
        status: One of the `CAPABILITY_STATUS_*` constants.
        ordinary_chat_ok: Whether ordinary chat was proven.
        forced_tool_choice_ok: Whether forced tool_choice returned a tool call.
        last_probe_at: Timestamp for the last probe or explicit update.
        failure_class: Coarse redacted failure class.
        masked_error: Short redacted diagnostic string.
    """

    fingerprint: str
    provider: str
    base_url_host: str
    model: str
    status: str = CAPABILITY_STATUS_UNKNOWN
    ordinary_chat_ok: bool = False
    forced_tool_choice_ok: bool = False
    last_probe_at: str = ""
    failure_class: str = ""
    masked_error: str = ""

    @property
    def tool_call_ok(self) -> bool:
        return self.status == CAPABILITY_STATUS_TOOL_CALL_OK and self.forced_tool_choice_ok

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe record without credentials or full base URLs."""

        return {
            "fingerprint": self.fingerprint,
            "provider": self.provider,
            "base_url_host": self.base_url_host,
            "model": self.model,
            "status": self.status,
            "ordinary_chat_ok": self.ordinary_chat_ok,
            "forced_tool_choice_ok": self.forced_tool_choice_ok,
            "last_probe_at": self.last_probe_at,
            "failure_class": self.failure_class,
            "masked_error": self.masked_error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProviderCapabilityRecord":
        """Build a record from persisted JSON, ignoring unknown fields."""

        if not isinstance(payload, dict):
            raise ValueError("provider capability payload must be a dict")
        fingerprint = _clean_text(str(payload.get("fingerprint") or ""), max_length=128)
        if not fingerprint:
            raise ValueError("provider capability fingerprint is required")
        return cls(
            fingerprint=fingerprint,
            provider=_clean_text(str(payload.get("provider") or ""), max_length=120),
            base_url_host=_clean_text(str(payload.get("base_url_host") or ""), max_length=240),
            model=_clean_text(str(payload.get("model") or ""), max_length=240),
            status=_clean_text(str(payload.get("status") or CAPABILITY_STATUS_UNKNOWN), max_length=80),
            ordinary_chat_ok=bool(payload.get("ordinary_chat_ok")),
            forced_tool_choice_ok=bool(payload.get("forced_tool_choice_ok")),
            last_probe_at=_clean_text(str(payload.get("last_probe_at") or ""), max_length=64),
            failure_class=_clean_text(str(payload.get("failure_class") or ""), max_length=120),
            masked_error=_clean_text(str(payload.get("masked_error") or ""), max_length=320),
        )


class ProviderCapabilityStore:
    """Small runtime JSON store for provider tool-call capability records."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or runtime_state_path("provider-capabilities.json")
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def _file_lock_path(self) -> Path:
        return self._path.with_suffix(f"{self._path.suffix}.lock")

    def _read_payload(self) -> dict[str, Any]:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {"records": {}}
        except (json.JSONDecodeError, OSError):
            return {"records": {}}
        if not isinstance(data, dict):
            return {"records": {}}
        records = data.get("records")
        return {"records": records if isinstance(records, dict) else {}}

    def get_record(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
    ) -> ProviderCapabilityRecord | None:
        """Return a capability record for the exact provider/model endpoint."""

        fingerprint = provider_fingerprint(
            provider=provider,
            base_url=base_url,
            model=model,
        )
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            payload = self._read_payload()
            raw = payload["records"].get(fingerprint)
        if not isinstance(raw, dict):
            return None
        try:
            return ProviderCapabilityRecord.from_dict(raw)
        except ValueError:
            return None

    def upsert_record(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        status: str,
        ordinary_chat_ok: bool,
        forced_tool_choice_ok: bool,
        failure_class: str = "",
        masked_error: str = "",
    ) -> ProviderCapabilityRecord:
        """Create or replace one provider capability record."""

        fingerprint = provider_fingerprint(
            provider=provider,
            base_url=base_url,
            model=model,
        )
        record = ProviderCapabilityRecord(
            fingerprint=fingerprint,
            provider=_clean_text(provider, max_length=120),
            base_url_host=_endpoint_host(base_url),
            model=_clean_text(model, max_length=240),
            status=_clean_text(status, max_length=80) or CAPABILITY_STATUS_UNKNOWN,
            ordinary_chat_ok=bool(ordinary_chat_ok),
            forced_tool_choice_ok=bool(forced_tool_choice_ok),
            last_probe_at=_now_iso(),
            failure_class=_clean_text(failure_class, max_length=120),
            masked_error=_clean_text(masked_error, max_length=320),
        )
        with self._lock, CrossProcessFileLock(self._file_lock_path):
            payload = self._read_payload()
            records = dict(payload["records"])
            records[fingerprint] = record.to_dict()
            atomic_write_json(self._path, {"records": records}, indent=2)
        return record

    def clear(self) -> None:
        """Remove all persisted provider capability records."""

        with self._lock, CrossProcessFileLock(self._file_lock_path):
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass


provider_capability_store = ProviderCapabilityStore()


def ensure_tool_call_capability(
    *,
    provider: str,
    base_url: str,
    model: str,
    store: ProviderCapabilityStore | None = None,
) -> ProviderCapabilityRecord:
    """Return a proven tool-call record or raise a safe capability error."""

    active_store = store or provider_capability_store
    record = active_store.get_record(provider=provider, base_url=base_url, model=model)
    if record is not None and record.tool_call_ok:
        return record
    status = record.status if record is not None else CAPABILITY_STATUS_UNKNOWN
    raise ProviderToolCapabilityError(status=status, record=record)


class ProviderToolCapabilityError(RuntimeError):
    """Raised when a provider has not proven native tool-call support."""

    def __init__(
        self,
        *,
        status: str,
        record: ProviderCapabilityRecord | None,
    ) -> None:
        self.status = status
        self.record = record
        super().__init__(f"provider tool calling is not proven: {status}")


__all__ = [
    "CAPABILITY_STATUS_AUTH_REQUIRED",
    "CAPABILITY_STATUS_PROBE_FAILED",
    "CAPABILITY_STATUS_TOOL_CALL_OK",
    "CAPABILITY_STATUS_UNKNOWN",
    "CAPABILITY_STATUS_UNSUPPORTED",
    "ProviderCapabilityRecord",
    "ProviderCapabilityStore",
    "ProviderToolCapabilityError",
    "ensure_tool_call_capability",
    "provider_capability_store",
    "provider_fingerprint",
]
