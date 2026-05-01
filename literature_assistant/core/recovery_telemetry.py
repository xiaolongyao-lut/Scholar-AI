# -*- coding: utf-8 -*-
"""Lightweight tracing helpers for recovery observability.

This module provides a tiny tracing abstraction that works without external
OpenTelemetry dependencies. If OpenTelemetry is installed, the span helper
will use it automatically; otherwise it falls back to structured logging plus
an in-memory trace accounting hook.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import uuid4

from recovery_metrics_exporter import get_recovery_metrics_collector

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    from opentelemetry import trace as otel_trace
except ImportError:  # pragma: no cover - optional dependency guard
    otel_trace = None


@dataclass
class RecoveryTraceSpan:
    """Context manager that records a recovery trace span."""

    telemetry: "RecoveryTelemetry"
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid4().hex[:16])
    duration_ms: float = 0.0
    error: str | None = None
    finished: bool = False
    _started_at: float | None = field(default=None, init=False, repr=False)
    _otel_scope: Any = field(default=None, init=False, repr=False)
    _otel_span: Any = field(default=None, init=False, repr=False)

    def __enter__(self) -> "RecoveryTraceSpan":
        self._started_at = perf_counter()
        logger.info(
            "trace.start name=%s trace_id=%s span_id=%s attributes=%s",
            self.name,
            self.trace_id,
            self.span_id,
            self.attributes,
        )

        if self.telemetry._otel_tracer is not None:  # pragma: no cover - optional dependency
            self._otel_scope = self.telemetry._otel_tracer.start_as_current_span(self.name)
            self._otel_span = self._otel_scope.__enter__()
            for key, value in self.attributes.items():
                self._otel_span.set_attribute(key, value)

        return self

    def set_attribute(self, key: str, value: Any) -> None:
        """Attach a new attribute to the span."""
        self.attributes[key] = value
        if self._otel_span is not None:  # pragma: no cover - optional dependency
            self._otel_span.set_attribute(key, value)

    def record_exception(self, exc: BaseException) -> None:
        """Record an exception on the span without swallowing it."""
        self.error = str(exc)
        self.attributes["error"] = self.error
        if self._otel_span is not None:  # pragma: no cover - optional dependency
            self._otel_span.record_exception(exc)
            self._otel_span.set_attribute("error", self.error)

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.record_exception(exc)

        end_time = perf_counter()
        if self._started_at is not None:
            self.duration_ms = max(0.0, (end_time - self._started_at) * 1000.0)
        self.attributes["duration_ms"] = round(self.duration_ms, 3)
        self.finished = True

        telemetry_status = "error" if exc is not None else "ok"
        logger.info(
            "trace.end name=%s trace_id=%s span_id=%s status=%s duration_ms=%.3f attributes=%s",
            self.name,
            self.trace_id,
            self.span_id,
            telemetry_status,
            self.duration_ms,
            self.attributes,
        )

        if self._otel_scope is not None:  # pragma: no cover - optional dependency
            self._otel_scope.__exit__(exc_type, exc, tb)

        self.telemetry.metrics.record_trace_span(self.name, self.duration_ms, error=exc is not None)
        return False


class RecoveryTelemetry:
    """Tracing facade for recovery operations."""

    def __init__(
        self,
        service_name: str = "modular.recovery",
        enable_opentelemetry: bool = True,
        metrics_collector=None,
    ) -> None:
        self.service_name = service_name
        self.metrics = metrics_collector or get_recovery_metrics_collector()
        self._otel_tracer = None

        if enable_opentelemetry and otel_trace is not None:  # pragma: no cover - optional dependency
            self._otel_tracer = otel_trace.get_tracer(service_name)

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> RecoveryTraceSpan:
        """Create a new recovery trace span context manager."""
        return RecoveryTraceSpan(self, name, dict(attributes or {}))

    def trace(self, name: str, **attributes: Any) -> RecoveryTraceSpan:
        """Convenience alias for start_span()."""
        return self.start_span(name, attributes)


_TELEMETRY_STATE: dict[str, RecoveryTelemetry | None] = {"telemetry": None}


def get_recovery_telemetry() -> RecoveryTelemetry:
    """Return the shared recovery telemetry helper."""
    telemetry = _TELEMETRY_STATE["telemetry"]
    if telemetry is None:
        telemetry = RecoveryTelemetry()
        _TELEMETRY_STATE["telemetry"] = telemetry
    return telemetry


def reset_recovery_telemetry() -> RecoveryTelemetry:
    """Reset the shared telemetry helper.

    Tests can call this to obtain a clean instance after monkeypatching.
    """
    telemetry = RecoveryTelemetry()
    _TELEMETRY_STATE["telemetry"] = telemetry
    return telemetry
