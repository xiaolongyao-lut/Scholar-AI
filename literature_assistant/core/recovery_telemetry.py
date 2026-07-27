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
from importlib import import_module
from time import perf_counter
from types import ModuleType, TracebackType
from typing import TYPE_CHECKING, Callable, Literal, Protocol, runtime_checkable
from uuid import uuid4

if TYPE_CHECKING:
    from literature_assistant.core.recovery_metrics_exporter import (
        RecoveryMetricsCollector,
        get_recovery_metrics_collector,
    )
else:
    from recovery_metrics_exporter import get_recovery_metrics_collector

logger = logging.getLogger(__name__)

def _load_otel_trace_module() -> ModuleType | None:
    """Load OpenTelemetry tracing without making it a hard dependency."""

    try:  # pragma: no cover - optional dependency
        return import_module("opentelemetry.trace")
    except ImportError:  # pragma: no cover - optional dependency guard
        return None


otel_trace = _load_otel_trace_module()


@runtime_checkable
class _OpenTelemetrySpan(Protocol):
    """Span methods used by the recovery tracing adapter."""

    def set_attribute(self, key: str, value: object) -> None:
        """Attach one attribute to the active span."""

    def record_exception(self, exc: BaseException) -> None:
        """Attach one application exception to the active span."""


@runtime_checkable
class _OpenTelemetrySpanScope(Protocol):
    """Synchronous span context manager returned by a tracer."""

    def __enter__(self) -> _OpenTelemetrySpan:
        """Enter the span scope."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> object:
        """Exit the span scope without controlling application propagation."""


@runtime_checkable
class _OpenTelemetryTracer(Protocol):
    """Tracer method required by RecoveryTelemetry."""

    def start_as_current_span(self, name: str) -> _OpenTelemetrySpanScope:
        """Create a synchronous current-span scope."""


def _require_callable_member(
    target: object,
    member_name: str,
    owner_name: str,
) -> Callable[..., object]:
    """Return a required dynamic member after verifying it is callable."""

    member: object = getattr(target, member_name, None)
    if not callable(member):
        raise TypeError(f"{owner_name} {member_name} is not callable")
    return member


def _resolve_otel_tracer(
    trace_module: object,
    service_name: str,
) -> _OpenTelemetryTracer:
    """Resolve and validate the dynamically imported OpenTelemetry tracer."""

    if not hasattr(trace_module, "get_tracer"):
        raise AttributeError("OpenTelemetry trace module has no get_tracer attribute")
    get_tracer = _require_callable_member(
        trace_module,
        "get_tracer",
        "OpenTelemetry trace module",
    )

    tracer: object = get_tracer(service_name)
    if not isinstance(tracer, _OpenTelemetryTracer):
        raise TypeError(
            "OpenTelemetry get_tracer returned an object without "
            "start_as_current_span"
        )
    _require_callable_member(
        tracer,
        "start_as_current_span",
        "OpenTelemetry tracer",
    )
    return tracer


@dataclass
class RecoveryTraceSpan:
    """Context manager that records a recovery trace span."""

    telemetry: "RecoveryTelemetry"
    name: str
    attributes: dict[str, object] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid4().hex[:16])
    duration_ms: float = 0.0
    error: str | None = None
    finished: bool = False
    _started_at: float | None = field(default=None, init=False, repr=False)
    _otel_scope: _OpenTelemetrySpanScope | None = field(default=None, init=False, repr=False)
    _otel_span: _OpenTelemetrySpan | None = field(default=None, init=False, repr=False)

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
            scope = self.telemetry._otel_tracer.start_as_current_span(self.name)
            if not isinstance(scope, _OpenTelemetrySpanScope):
                raise TypeError("OpenTelemetry tracer returned an invalid span scope")
            _require_callable_member(scope, "__enter__", "OpenTelemetry span scope")
            _require_callable_member(scope, "__exit__", "OpenTelemetry span scope")
            span = scope.__enter__()
            if not isinstance(span, _OpenTelemetrySpan):
                scope.__exit__(None, None, None)
                raise TypeError("OpenTelemetry span scope returned an invalid span")
            _require_callable_member(span, "set_attribute", "OpenTelemetry span")
            _require_callable_member(span, "record_exception", "OpenTelemetry span")
            self._otel_scope = scope
            self._otel_span = span
            for key, value in self.attributes.items():
                self._otel_span.set_attribute(key, value)

        return self

    def set_attribute(self, key: str, value: object) -> None:
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

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
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
        metrics_collector: RecoveryMetricsCollector | None = None,
    ) -> None:
        self.service_name = service_name
        self.metrics = metrics_collector or get_recovery_metrics_collector()
        self._otel_tracer: _OpenTelemetryTracer | None = None

        if enable_opentelemetry and otel_trace is not None:  # pragma: no cover - optional dependency
            self._otel_tracer = _resolve_otel_tracer(otel_trace, service_name)

    def start_span(
        self,
        name: str,
        attributes: dict[str, object] | None = None,
    ) -> RecoveryTraceSpan:
        """Create a new recovery trace span context manager."""
        return RecoveryTraceSpan(self, name, dict(attributes or {}))

    def trace(self, name: str, **attributes: object) -> RecoveryTraceSpan:
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
