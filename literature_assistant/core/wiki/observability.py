from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import TypeAlias
from uuid import uuid4

from literature_assistant.core.project_paths import ensure_directory, wiki_observability_path


SafeJson: TypeAlias = str | int | float | bool | None | list["SafeJson"] | dict[str, "SafeJson"]

SCHEMA_VERSION = 1
_MAX_ATTRIBUTE_DEPTH = 4
_MAX_ATTRIBUTE_ITEMS = 32
_MAX_ATTRIBUTE_STRING = 256
_VALID_KINDS = {"event", "metric", "span"}
_VALID_STATUSES = {"ok", "warning", "error"}
_SENSITIVE_KEY_PARTS = {
    "answer",
    "api",
    "api_key",
    "authorization",
    "body",
    "content",
    "credential",
    "directory",
    "file",
    "key",
    "password",
    "path",
    "prompt",
    "query",
    "question",
    "quote",
    "root",
    "secret",
    "text",
    "token",
}
_SECRET_VALUE_RE = re.compile(
    r"(?i)(authorization\s*:|bearer\s+[A-Za-z0-9._~+/=-]{12,}|sk-[A-Za-z0-9_-]{12,}|api[_-]?key)"
)
_WINDOWS_PATH_RE = re.compile(r"(?i)(^[A-Z]:[\\/]|\\Users\\|/Users/|/home/|/mnt/|\\\\)")
_SAFE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
_WRITE_LOCKS: dict[Path, threading.Lock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WikiObservationRecord:
    """One sanitized local observability row.

    Attributes contain bounded JSON values only. Sensitive user text, secrets,
    and private paths are represented by hashes and lengths so records remain
    useful for debugging without becoming a secondary knowledge store.
    """

    kind: str
    name: str
    timestamp: str
    trace_id: str
    attributes: dict[str, SafeJson] = field(default_factory=dict)
    status: str = "ok"
    span_id: str | None = None
    parent_span_id: str | None = None
    duration_ms: float | None = None
    value: float | None = None
    unit: str = ""
    error_type: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, SafeJson]:
        """Return the JSONL payload shape for events, metrics, and spans."""

        payload: dict[str, SafeJson] = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "name": self.name,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "status": self.status,
            "attributes": self.attributes,
        }
        if self.span_id is not None:
            payload["span_id"] = self.span_id
        if self.parent_span_id is not None:
            payload["parent_span_id"] = self.parent_span_id
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        if self.value is not None:
            payload["value"] = self.value
        if self.unit:
            payload["unit"] = self.unit
        if self.error_type:
            payload["error_type"] = self.error_type
        return payload


class WikiObservabilitySink:
    """Append-only local observability sink for wiki runtime diagnostics.

    The sink writes three JSONL files below the wiki runtime workspace:
    ``events.jsonl``, ``metrics.jsonl``, and ``spans.jsonl``. It never exports
    data over the network and defaults to fail-open behavior because telemetry
    must not break compile, query, or doctor paths.
    """

    def __init__(
        self,
        root: Path | None = None,
        *,
        enabled: bool | None = None,
        fail_open: bool = True,
    ) -> None:
        self.root = Path(root).expanduser().resolve() if root is not None else wiki_observability_path().resolve()
        self.enabled = wiki_observability_enabled() if enabled is None else bool(enabled)
        self.fail_open = bool(fail_open)

    @property
    def events_path(self) -> Path:
        """Return the event JSONL path."""

        return self.root / "events.jsonl"

    @property
    def metrics_path(self) -> Path:
        """Return the metric JSONL path."""

        return self.root / "metrics.jsonl"

    @property
    def spans_path(self) -> Path:
        """Return the span JSONL path."""

        return self.root / "spans.jsonl"

    def emit_event(
        self,
        name: str,
        attributes: Mapping[str, object] | None = None,
        *,
        status: str = "ok",
        trace_id: str | None = None,
    ) -> WikiObservationRecord:
        """Append one sanitized event row.

        ``attributes`` may include arbitrary runtime values; unsupported or
        sensitive values are converted into bounded diagnostic hashes.
        """

        record = _make_record(
            kind="event",
            name=name,
            attributes=attributes,
            status=status,
            trace_id=trace_id,
        )
        self._append(self.events_path, record)
        logger.info("wiki.observability.event name=%s status=%s trace_id=%s", record.name, record.status, record.trace_id)
        return record

    def record_metric(
        self,
        name: str,
        value: float | int,
        attributes: Mapping[str, object] | None = None,
        *,
        unit: str = "",
        status: str = "ok",
        trace_id: str | None = None,
    ) -> WikiObservationRecord:
        """Append one numeric metric row.

        Metric values must be finite numbers. Use attributes for dimensions and
        keep units explicit, for example ``ms``, ``count``, or ``pages``.
        """

        numeric_value = _validate_metric_value(value)
        record = _make_record(
            kind="metric",
            name=name,
            attributes=attributes,
            status=status,
            trace_id=trace_id,
            value=numeric_value,
            unit=unit,
        )
        self._append(self.metrics_path, record)
        logger.debug("wiki.observability.metric name=%s value=%s unit=%s", record.name, record.value, record.unit)
        return record

    def start_span(
        self,
        name: str,
        attributes: Mapping[str, object] | None = None,
        *,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> "WikiObservationSpan":
        """Create a span context manager for one wiki operation."""

        return WikiObservationSpan(
            sink=self,
            name=_validate_name(name),
            attributes=dict(attributes or {}),
            trace_id=_normalize_trace_id(trace_id),
            parent_span_id=_normalize_optional_id(parent_span_id, "parent_span_id"),
        )

    def _record_span(
        self,
        *,
        name: str,
        attributes: Mapping[str, object],
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        duration_ms: float,
        status: str,
        error_type: str | None,
    ) -> WikiObservationRecord:
        record = _make_record(
            kind="span",
            name=name,
            attributes=attributes,
            status=status,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            duration_ms=round(duration_ms, 3),
            error_type=error_type,
        )
        self._append(self.spans_path, record)
        logger.info(
            "wiki.observability.span name=%s status=%s duration_ms=%.3f trace_id=%s span_id=%s",
            record.name,
            record.status,
            record.duration_ms or 0.0,
            record.trace_id,
            record.span_id,
        )
        return record

    def _append(self, path: Path, record: WikiObservationRecord) -> None:
        if not self.enabled:
            return
        try:
            ensure_directory(path.parent)
            line = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            lock = _lock_for(path)
            with lock:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
        except OSError:
            if not self.fail_open:
                raise


@dataclass
class WikiObservationSpan:
    """Context manager that records one completed wiki span row."""

    sink: WikiObservabilitySink
    name: str
    attributes: dict[str, object] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    parent_span_id: str | None = None
    span_id: str = field(default_factory=lambda: uuid4().hex[:16])
    _started_ns: int | None = field(default=None, init=False, repr=False)

    def __enter__(self) -> "WikiObservationSpan":
        self._started_ns = time.perf_counter_ns()
        return self

    def set_attribute(self, key: str, value: object) -> None:
        """Attach an attribute before the span exits."""

        safe_key = _safe_attribute_key(key)
        self.attributes[safe_key] = value

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        del tb
        started = self._started_ns if self._started_ns is not None else time.perf_counter_ns()
        duration_ms = max(0.0, (time.perf_counter_ns() - started) / 1_000_000.0)
        status = "error" if exc is not None or exc_type is not None else "ok"
        error_type = exc_type.__name__ if exc_type is not None else None
        self.sink._record_span(
            name=self.name,
            attributes=self.attributes,
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            duration_ms=duration_ms,
            status=status,
            error_type=error_type,
        )
        return False


def wiki_observability_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether local wiki observability writes are enabled."""

    values = env if env is not None else os.environ
    raw_value = str(values.get("LITERATURE_ASSISTANT_WIKI_OBSERVABILITY", "1")).strip().lower()
    return raw_value not in {"0", "false", "no", "off", "disabled"}


def default_wiki_observability_sink() -> WikiObservabilitySink:
    """Return the default local wiki observability sink."""

    return WikiObservabilitySink()


def sanitize_attributes(attributes: Mapping[str, object] | None) -> dict[str, SafeJson]:
    """Return bounded JSON attributes with sensitive values hashed."""

    if attributes is None:
        return {}
    if not isinstance(attributes, Mapping):
        raise TypeError("attributes must be a mapping")
    output: dict[str, SafeJson] = {}
    for index, (key, value) in enumerate(attributes.items()):
        if index >= _MAX_ATTRIBUTE_ITEMS:
            output["_omitted_attribute_count"] = max(0, len(attributes) - _MAX_ATTRIBUTE_ITEMS)
            break
        safe_key = _safe_attribute_key(str(key))
        output[safe_key] = _sanitize_value(safe_key, value, depth=0)
    return output


def emit_wiki_event(
    name: str,
    attributes: Mapping[str, object] | None = None,
    *,
    sink: WikiObservabilitySink | None = None,
    status: str = "ok",
    trace_id: str | None = None,
) -> WikiObservationRecord:
    """Append one event row to the given sink or the default sink."""

    target = sink or default_wiki_observability_sink()
    return target.emit_event(name, attributes, status=status, trace_id=trace_id)


def record_wiki_metric(
    name: str,
    value: float | int,
    attributes: Mapping[str, object] | None = None,
    *,
    sink: WikiObservabilitySink | None = None,
    unit: str = "",
    status: str = "ok",
    trace_id: str | None = None,
) -> WikiObservationRecord:
    """Append one metric row to the given sink or the default sink."""

    target = sink or default_wiki_observability_sink()
    return target.record_metric(name, value, attributes, unit=unit, status=status, trace_id=trace_id)


def trace_wiki_operation(
    name: str,
    attributes: Mapping[str, object] | None = None,
    *,
    sink: WikiObservabilitySink | None = None,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
) -> WikiObservationSpan:
    """Create a span using the given sink or the default sink."""

    target = sink or default_wiki_observability_sink()
    return target.start_span(name, attributes, trace_id=trace_id, parent_span_id=parent_span_id)


def _make_record(
    *,
    kind: str,
    name: str,
    attributes: Mapping[str, object] | None,
    status: str,
    trace_id: str | None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    duration_ms: float | None = None,
    value: float | None = None,
    unit: str = "",
    error_type: str | None = None,
) -> WikiObservationRecord:
    validated_kind = _validate_kind(kind)
    validated_name = _validate_name(name)
    validated_status = _validate_status(status)
    if duration_ms is not None and (not math.isfinite(duration_ms) or duration_ms < 0):
        raise ValueError("duration_ms must be a finite non-negative number")
    return WikiObservationRecord(
        kind=validated_kind,
        name=validated_name,
        timestamp=datetime.now(UTC).isoformat(timespec="milliseconds"),
        trace_id=_normalize_trace_id(trace_id),
        attributes=sanitize_attributes(attributes),
        status=validated_status,
        span_id=_normalize_optional_id(span_id, "span_id"),
        parent_span_id=_normalize_optional_id(parent_span_id, "parent_span_id"),
        duration_ms=duration_ms,
        value=value,
        unit=_validate_unit(unit),
        error_type=_validate_error_type(error_type),
    )


def _sanitize_value(key: str, value: object, *, depth: int) -> SafeJson:
    if depth > _MAX_ATTRIBUTE_DEPTH:
        return _redacted(str(value), "max_depth")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _redacted(str(value), "non_finite_float")
    if isinstance(value, Path):
        return _redacted(value.as_posix(), "path")
    if isinstance(value, str):
        return _sanitize_string(key, value)
    if isinstance(value, Mapping):
        nested: dict[str, SafeJson] = {}
        for index, (nested_key, nested_value) in enumerate(value.items()):
            if index >= _MAX_ATTRIBUTE_ITEMS:
                nested["_omitted_attribute_count"] = max(0, len(value) - _MAX_ATTRIBUTE_ITEMS)
                break
            safe_key = _safe_attribute_key(str(nested_key))
            nested[safe_key] = _sanitize_value(safe_key, nested_value, depth=depth + 1)
        return nested
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)
        sanitized_items = [_sanitize_value(key, item, depth=depth + 1) for item in items[:_MAX_ATTRIBUTE_ITEMS]]
        if len(items) > _MAX_ATTRIBUTE_ITEMS:
            sanitized_items.append({"_omitted_item_count": len(items) - _MAX_ATTRIBUTE_ITEMS})
        return sanitized_items
    return _redacted(str(value), "unsupported_type")


def _sanitize_string(key: str, value: str) -> SafeJson:
    if _is_sensitive_key(key):
        return _redacted(value, "sensitive_key")
    if _looks_sensitive_value(value):
        return _redacted(value, "sensitive_value")
    if len(value) > _MAX_ATTRIBUTE_STRING:
        return _redacted(value, "long_string")
    return value


def _redacted(value: str, reason: str) -> dict[str, SafeJson]:
    return {
        "redacted": True,
        "reason": reason,
        "hash": _hash_text(value),
        "length": len(value),
    }


def _looks_sensitive_value(value: str) -> bool:
    if not value:
        return False
    if _SECRET_VALUE_RE.search(value):
        return True
    if _WINDOWS_PATH_RE.search(value):
        return True
    if "\n" in value or "\r" in value:
        return True
    return False


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    if lowered in {"query_hash", "path_hash"}:
        return False
    if lowered.endswith(("_path", "_file", "_root", "_directory", "_query", "_text", "_body", "_prompt", "_answer")):
        return True
    parts = {part for part in re.split(r"[^a-z0-9_]+", lowered) if part}
    return any(part in _SENSITIVE_KEY_PARTS for part in parts)


def _safe_attribute_key(key: str) -> str:
    normalized = key.strip()
    if _SAFE_KEY_RE.fullmatch(normalized):
        return normalized[:96]
    return f"attr_{_hash_text(normalized)[:12]}"


def _validate_kind(kind: str) -> str:
    normalized = str(kind or "").strip().lower()
    if normalized not in _VALID_KINDS:
        raise ValueError(f"kind must be one of {sorted(_VALID_KINDS)}")
    return normalized


def _validate_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized not in _VALID_STATUSES:
        raise ValueError(f"status must be one of {sorted(_VALID_STATUSES)}")
    return normalized


def _validate_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("name must be a non-empty string")
    if len(normalized) > 128:
        raise ValueError("name must be 128 characters or fewer")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError("name cannot contain control characters")
    return normalized


def _validate_unit(unit: str) -> str:
    normalized = str(unit or "").strip()
    if len(normalized) > 32:
        raise ValueError("unit must be 32 characters or fewer")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError("unit cannot contain control characters")
    return normalized


def _validate_error_type(error_type: str | None) -> str | None:
    if error_type is None:
        return None
    normalized = str(error_type).strip()
    if not normalized:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,127}", normalized):
        return "Error"
    return normalized


def _validate_metric_value(value: float | int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("metric value must be a number")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError("metric value must be finite")
    return round(numeric_value, 6)


def _normalize_trace_id(trace_id: str | None) -> str:
    if trace_id is None:
        return uuid4().hex
    return _normalize_required_id(trace_id, "trace_id")


def _normalize_required_id(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", normalized):
        raise ValueError(f"{field_name} must be a simple identifier")
    return normalized


def _normalize_optional_id(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _normalize_required_id(value, field_name)


def _hash_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _WRITE_LOCKS_GUARD:
        lock = _WRITE_LOCKS.get(resolved)
        if lock is None:
            lock = threading.Lock()
            _WRITE_LOCKS[resolved] = lock
        return lock
