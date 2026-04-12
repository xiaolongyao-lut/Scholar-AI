# -*- coding: utf-8 -*-
"""Lightweight observability metrics for recovery operations.

This module keeps the project H2 observability work usable even when optional
Prometheus dependencies are unavailable. It maintains an in-memory metrics
collector that can:

- Track recovery HTTP request volume and latency
- Track recommendation generation counts, confidence, and evidence usage
- Track operator overrides and recovery outcomes
- Export a Prometheus-compatible text exposition

The implementation is intentionally dependency-light so it can run in the
current repository without extra packaging work.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


def _escape_prometheus_label(value: Any) -> str:
    """Escape a label value for Prometheus exposition text."""
    text = str(value)
    return (
        text.replace("\\", r"\\")
        .replace("\n", r"\n")
        .replace('"', r'\"')
    )


@dataclass(frozen=True)
class RecoveryMetricsSnapshot:
    """Immutable snapshot of recovery observability counters."""

    snapshot_at: str
    http_requests_total: int
    http_request_duration_ms_sum: float
    http_request_duration_ms_count: int
    http_request_counts: dict[str, int]
    recommendation_generations_total: int
    recommendation_success_total: int
    recommendation_empty_total: int
    recommendation_failure_total: int
    recommendation_duration_ms_sum: float
    recommendation_duration_ms_count: int
    recommendation_confidence_sum: float
    recommendation_confidence_count: int
    total_evidence_considered: int
    memory_hits_total: int
    operator_overrides_total: int
    operator_acceptances_total: int
    operator_rejections_total: int
    recovery_success_total: int
    recovery_failure_total: int
    evidence_totals: dict[str, int] = field(default_factory=dict)
    alternatives_total: int = 0
    trace_spans_total: int = 0
    trace_errors_total: int = 0

    @property
    def recommendation_confidence_avg(self) -> float:
        if self.recommendation_confidence_count <= 0:
            return 0.0
        return self.recommendation_confidence_sum / self.recommendation_confidence_count

    @property
    def recommendation_duration_ms_avg(self) -> float:
        if self.recommendation_duration_ms_count <= 0:
            return 0.0
        return self.recommendation_duration_ms_sum / self.recommendation_duration_ms_count

    @property
    def http_request_duration_ms_avg(self) -> float:
        if self.http_request_duration_ms_count <= 0:
            return 0.0
        return self.http_request_duration_ms_sum / self.http_request_duration_ms_count

    @property
    def operator_acceptance_rate(self) -> float:
        if self.operator_overrides_total <= 0:
            return 0.0
        return self.operator_acceptances_total / self.operator_overrides_total

    @property
    def recovery_success_rate(self) -> float:
        total = self.recovery_success_total + self.recovery_failure_total
        if total <= 0:
            return 0.0
        return self.recovery_success_total / total


class RecoveryMetricsCollector:
    """Thread-safe in-memory metrics collector for recovery observability."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._last_updated = datetime.now(timezone.utc)
        self.reset()

    def reset(self) -> None:
        """Clear all counters."""
        with self._lock:
            self._http_request_counts: Counter[str] = Counter()
            self._http_requests_total = 0
            self._http_request_duration_ms_sum = 0.0
            self._http_request_duration_ms_count = 0

            self._recommendation_generations_total = 0
            self._recommendation_success_total = 0
            self._recommendation_empty_total = 0
            self._recommendation_failure_total = 0
            self._recommendation_duration_ms_sum = 0.0
            self._recommendation_duration_ms_count = 0
            self._recommendation_confidence_sum = 0.0
            self._recommendation_confidence_count = 0
            self._total_evidence_considered = 0
            self._memory_hits_total = 0
            self._alternatives_total = 0
            self._evidence_totals: Counter[str] = Counter()

            self._operator_overrides_total = 0
            self._operator_acceptances_total = 0
            self._operator_rejections_total = 0
            self._recovery_success_total = 0
            self._recovery_failure_total = 0

            self._trace_spans_total = 0
            self._trace_errors_total = 0
            self._last_updated = datetime.now(timezone.utc)

    def _touch(self) -> None:
        self._last_updated = datetime.now(timezone.utc)

    def record_http_request(self, route: str, method: str, status_code: int, duration_ms: float) -> None:
        """Record a recovery HTTP request."""
        key = f'{method.upper()} {route} {int(status_code)}'
        with self._lock:
            self._http_requests_total += 1
            self._http_request_duration_ms_sum += max(0.0, float(duration_ms))
            self._http_request_duration_ms_count += 1
            self._http_request_counts[key] += 1
            self._touch()

    def record_recommendation_generation(
        self,
        *,
        request_id: str,
        job_id: str,
        session_id: str,
        duration_ms: float,
        total_evidence_considered: int,
        has_recommendation: bool,
        primary_confidence: float | None = None,
        alternatives_count: int = 0,
        evidence_counts: dict[str, int] | None = None,
        memory_hit_count: int = 0,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """Record a recommendation generation event.

        The request/session/job identifiers are intentionally accepted so the
        call sites can pass the full context even though the collector keeps
        aggregation anonymous to avoid high-cardinality metrics.
        """
        del request_id, job_id, session_id, error

        evidence_counts = evidence_counts or {}
        with self._lock:
            self._recommendation_generations_total += 1
            self._recommendation_duration_ms_sum += max(0.0, float(duration_ms))
            self._recommendation_duration_ms_count += 1
            self._total_evidence_considered += max(0, int(total_evidence_considered))
            self._memory_hits_total += max(0, int(memory_hit_count))
            self._alternatives_total += max(0, int(alternatives_count))

            if has_recommendation:
                self._recommendation_success_total += 1
            else:
                self._recommendation_empty_total += 1

            if not success:
                self._recommendation_failure_total += 1

            if primary_confidence is not None:
                self._recommendation_confidence_sum += max(0.0, float(primary_confidence))
                self._recommendation_confidence_count += 1

            for source_type, count in evidence_counts.items():
                self._evidence_totals[str(source_type)] += max(0, int(count))

            self._touch()

    def record_operator_override(self, decision: str) -> None:
        """Record an operator override decision (approved/rejected/etc.)."""
        normalized = (decision or "").strip().lower()
        with self._lock:
            self._operator_overrides_total += 1
            if normalized in {"approved", "accept", "accepted", "allow", "yes"}:
                self._operator_acceptances_total += 1
            elif normalized in {"rejected", "reject", "denied", "deny", "no"}:
                self._operator_rejections_total += 1
            self._touch()

    def record_recovery_outcome(self, success: bool) -> None:
        """Record the outcome of a recovery action."""
        with self._lock:
            if success:
                self._recovery_success_total += 1
            else:
                self._recovery_failure_total += 1
            self._touch()

    def record_trace_span(self, name: str, duration_ms: float, *, error: bool = False) -> None:
        """Record a completed trace span for observability accounting."""
        del name
        del duration_ms
        with self._lock:
            self._trace_spans_total += 1
            if error:
                self._trace_errors_total += 1
            self._touch()

    def snapshot(self) -> RecoveryMetricsSnapshot:
        """Return an immutable snapshot of the current counters."""
        with self._lock:
            return RecoveryMetricsSnapshot(
                snapshot_at=self._last_updated.isoformat(),
                http_requests_total=self._http_requests_total,
                http_request_duration_ms_sum=self._http_request_duration_ms_sum,
                http_request_duration_ms_count=self._http_request_duration_ms_count,
                http_request_counts=dict(self._http_request_counts),
                recommendation_generations_total=self._recommendation_generations_total,
                recommendation_success_total=self._recommendation_success_total,
                recommendation_empty_total=self._recommendation_empty_total,
                recommendation_failure_total=self._recommendation_failure_total,
                recommendation_duration_ms_sum=self._recommendation_duration_ms_sum,
                recommendation_duration_ms_count=self._recommendation_duration_ms_count,
                recommendation_confidence_sum=self._recommendation_confidence_sum,
                recommendation_confidence_count=self._recommendation_confidence_count,
                total_evidence_considered=self._total_evidence_considered,
                memory_hits_total=self._memory_hits_total,
                operator_overrides_total=self._operator_overrides_total,
                operator_acceptances_total=self._operator_acceptances_total,
                operator_rejections_total=self._operator_rejections_total,
                recovery_success_total=self._recovery_success_total,
                recovery_failure_total=self._recovery_failure_total,
                evidence_totals=dict(self._evidence_totals),
                alternatives_total=self._alternatives_total,
                trace_spans_total=self._trace_spans_total,
                trace_errors_total=self._trace_errors_total,
            )

    def render_prometheus_text(self) -> str:
        """Render the metrics snapshot in Prometheus text exposition format."""
        snapshot = self.snapshot()
        lines: list[str] = []

        def add_help_and_type(metric_name: str, metric_type: str, help_text: str) -> None:
            lines.append(f"# HELP {metric_name} {help_text}")
            lines.append(f"# TYPE {metric_name} {metric_type}")

        add_help_and_type(
            "recovery_http_requests_total",
            "counter",
            "Total number of recovery HTTP requests observed.",
        )
        for label_key, count in sorted(snapshot.http_request_counts.items()):
            method, route, status_code = label_key.split(" ", 2)
            lines.append(
                "recovery_http_requests_total{" 
                f'method="{_escape_prometheus_label(method)}",'
                f'route="{_escape_prometheus_label(route)}",'
                f'status_code="{_escape_prometheus_label(status_code)}"' 
                f"}} {count}"
            )

        add_help_and_type(
            "recovery_http_request_duration_ms_sum",
            "counter",
            "Total recovery HTTP request duration in milliseconds.",
        )
        lines.append(f"recovery_http_request_duration_ms_sum {snapshot.http_request_duration_ms_sum:.6f}")
        add_help_and_type(
            "recovery_http_request_duration_ms_count",
            "counter",
            "Number of recovery HTTP request duration samples.",
        )
        lines.append(f"recovery_http_request_duration_ms_count {snapshot.http_request_duration_ms_count}")

        add_help_and_type(
            "recovery_recommendation_generations_total",
            "counter",
            "Total recommendation generation attempts.",
        )
        lines.append(f"recovery_recommendation_generations_total {snapshot.recommendation_generations_total}")
        add_help_and_type(
            "recovery_recommendation_success_total",
            "counter",
            "Total recommendation generations that produced at least one recommendation.",
        )
        lines.append(f"recovery_recommendation_success_total {snapshot.recommendation_success_total}")
        add_help_and_type(
            "recovery_recommendation_empty_total",
            "counter",
            "Total recommendation generations that produced no recommendation.",
        )
        lines.append(f"recovery_recommendation_empty_total {snapshot.recommendation_empty_total}")
        add_help_and_type(
            "recovery_recommendation_failure_total",
            "counter",
            "Total failed recommendation generations.",
        )
        lines.append(f"recovery_recommendation_failure_total {snapshot.recommendation_failure_total}")

        add_help_and_type(
            "recovery_recommendation_duration_ms_sum",
            "counter",
            "Total recommendation generation duration in milliseconds.",
        )
        lines.append(f"recovery_recommendation_duration_ms_sum {snapshot.recommendation_duration_ms_sum:.6f}")
        add_help_and_type(
            "recovery_recommendation_duration_ms_count",
            "counter",
            "Number of recommendation generation samples.",
        )
        lines.append(f"recovery_recommendation_duration_ms_count {snapshot.recommendation_duration_ms_count}")

        add_help_and_type(
            "recovery_recommendation_confidence_sum",
            "counter",
            "Total primary recommendation confidence values.",
        )
        lines.append(f"recovery_recommendation_confidence_sum {snapshot.recommendation_confidence_sum:.6f}")
        add_help_and_type(
            "recovery_recommendation_confidence_count",
            "counter",
            "Number of primary recommendation confidence samples.",
        )
        lines.append(f"recovery_recommendation_confidence_count {snapshot.recommendation_confidence_count}")
        add_help_and_type(
            "recovery_recommendation_confidence_avg",
            "gauge",
            "Average primary recommendation confidence.",
        )
        lines.append(f"recovery_recommendation_confidence_avg {snapshot.recommendation_confidence_avg:.6f}")

        add_help_and_type(
            "recovery_total_evidence_considered",
            "counter",
            "Total evidence items considered by recommendation generation.",
        )
        lines.append(f"recovery_total_evidence_considered {snapshot.total_evidence_considered}")

        add_help_and_type(
            "recovery_memory_hits_total",
            "counter",
            "Total memory evidence references included in recommendations.",
        )
        lines.append(f"recovery_memory_hits_total {snapshot.memory_hits_total}")

        add_help_and_type(
            "recovery_evidence_total",
            "counter",
            "Total evidence items grouped by source type.",
        )
        for source_type, count in sorted(snapshot.evidence_totals.items()):
            lines.append(
                f'recovery_evidence_total{{source_type="{_escape_prometheus_label(source_type)}"}} {count}'
            )

        add_help_and_type(
            "recovery_alternatives_total",
            "counter",
            "Total alternative recommendations generated.",
        )
        lines.append(f"recovery_alternatives_total {snapshot.alternatives_total}")

        add_help_and_type(
            "recovery_operator_overrides_total",
            "counter",
            "Total operator overrides recorded.",
        )
        lines.append(f"recovery_operator_overrides_total {snapshot.operator_overrides_total}")
        add_help_and_type(
            "recovery_operator_acceptances_total",
            "counter",
            "Total operator-approved recommendation overrides.",
        )
        lines.append(f"recovery_operator_acceptances_total {snapshot.operator_acceptances_total}")
        add_help_and_type(
            "recovery_operator_rejections_total",
            "counter",
            "Total operator-rejected recommendation overrides.",
        )
        lines.append(f"recovery_operator_rejections_total {snapshot.operator_rejections_total}")
        add_help_and_type(
            "recovery_operator_acceptance_rate",
            "gauge",
            "Operator acceptance rate for recorded overrides.",
        )
        lines.append(f"recovery_operator_acceptance_rate {snapshot.operator_acceptance_rate:.6f}")

        add_help_and_type(
            "recovery_recovery_success_total",
            "counter",
            "Total recovery actions recorded as successful.",
        )
        lines.append(f"recovery_recovery_success_total {snapshot.recovery_success_total}")
        add_help_and_type(
            "recovery_recovery_failure_total",
            "counter",
            "Total recovery actions recorded as failed.",
        )
        lines.append(f"recovery_recovery_failure_total {snapshot.recovery_failure_total}")
        add_help_and_type(
            "recovery_recovery_success_rate",
            "gauge",
            "Observed recovery success rate.",
        )
        lines.append(f"recovery_recovery_success_rate {snapshot.recovery_success_rate:.6f}")

        add_help_and_type(
            "recovery_trace_spans_total",
            "counter",
            "Total completed recovery trace spans.",
        )
        lines.append(f"recovery_trace_spans_total {snapshot.trace_spans_total}")
        add_help_and_type(
            "recovery_trace_errors_total",
            "counter",
            "Total recovery trace spans that ended with an error.",
        )
        lines.append(f"recovery_trace_errors_total {snapshot.trace_errors_total}")

        lines.append(f"# recovery_metrics_last_updated {snapshot.snapshot_at}")
        return "\n".join(lines) + "\n"


_METRICS_STATE: dict[str, RecoveryMetricsCollector | None] = {"collector": None}


def get_recovery_metrics_collector() -> RecoveryMetricsCollector:
    """Return the shared recovery metrics collector."""
    collector = _METRICS_STATE["collector"]
    if collector is None:
        collector = RecoveryMetricsCollector()
        _METRICS_STATE["collector"] = collector
    return collector


def reset_recovery_metrics_collector() -> RecoveryMetricsCollector:
    """Reset and return the shared recovery metrics collector.

    Useful in tests to avoid cross-test contamination.
    """
    collector = get_recovery_metrics_collector()
    collector.reset()
    _METRICS_STATE["collector"] = collector
    return collector
