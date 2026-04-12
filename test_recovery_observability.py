# -*- coding: utf-8 -*-
"""Tests for Phase H2 recovery observability.

Covers:
- In-memory metrics collection and Prometheus text export
- Lightweight tracing spans
- Recommendation-engine instrumentation
- Recovery metrics HTTP endpoint
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from datetime_utils import utc_now_naive

from fastapi.testclient import TestClient

from python_adapter_server import app
from recovery_metrics_exporter import reset_recovery_metrics_collector
from recovery_recommendation_engine import RecommendationRequest, RecoveryRecommendationEngine
from recovery_telemetry import RecoveryTelemetry


class StubEventStore:
    """Minimal event store for observability tests."""

    def __init__(self) -> None:
        self.appended_events: list[object] = []

    def get_job_timeline(self, job_id: str):
        return [
            SimpleNamespace(
                event_id=f"evt-{job_id}-001",
                event_type="job_failed",
                job_id=job_id,
                session_id="sess-observability",
                payload={"error": "timeout"},
                timestamp=utc_now_naive(),
            )
        ]

    def append_event(self, event):
        self.appended_events.append(event)


class StubFactStore:
    """Minimal fact store for observability tests."""

    def get_current_facts(self, *_args, **_kwargs):
        return []


class TestRecoveryMetricsCollector(unittest.TestCase):
    """Validate Prometheus-style metrics accounting."""

    def setUp(self) -> None:
        self.collector = reset_recovery_metrics_collector()

    def test_metrics_collector_tracks_requests_and_generation(self) -> None:
        self.collector.record_http_request("/recovery/recommendations", "GET", 200, 12.5)
        self.collector.record_recommendation_generation(
            request_id="req-001",
            job_id="job-001",
            session_id="sess-001",
            duration_ms=34.25,
            total_evidence_considered=7,
            has_recommendation=True,
            primary_confidence=0.85,
            alternatives_count=1,
            evidence_counts={"event": 2, "fact": 1, "memory": 3},
            memory_hit_count=3,
        )
        self.collector.record_operator_override("approved")
        self.collector.record_recovery_outcome(True)
        self.collector.record_trace_span("recovery.recommendations.generate", 34.25)

        snapshot = self.collector.snapshot()
        self.assertEqual(snapshot.http_requests_total, 1)
        self.assertEqual(snapshot.recommendation_generations_total, 1)
        self.assertEqual(snapshot.recommendation_success_total, 1)
        self.assertEqual(snapshot.recommendation_duration_ms_count, 1)
        self.assertEqual(snapshot.memory_hits_total, 3)
        self.assertEqual(snapshot.operator_acceptances_total, 1)
        self.assertEqual(snapshot.recovery_success_total, 1)
        self.assertEqual(snapshot.trace_spans_total, 1)
        self.assertIn("GET /recovery/recommendations 200", snapshot.http_request_counts)
        self.assertIn("memory", snapshot.evidence_totals)
        self.assertGreater(snapshot.recommendation_confidence_avg, 0.8)
        self.assertGreater(snapshot.recovery_success_rate, 0.9)

        exposition = self.collector.render_prometheus_text()
        self.assertIn("# HELP recovery_recommendation_generations_total", exposition)
        self.assertIn("recovery_http_requests_total{method=\"GET\",route=\"/recovery/recommendations\",status_code=\"200\"} 1", exposition)
        self.assertIn('recovery_evidence_total{source_type="memory"} 3', exposition)
        self.assertIn("recovery_operator_acceptance_rate", exposition)

    def test_reset_clears_counters(self) -> None:
        self.collector.record_http_request("/recovery/events", "GET", 200, 3.0)
        self.collector.reset()
        snapshot = self.collector.snapshot()
        self.assertEqual(snapshot.http_requests_total, 0)
        self.assertEqual(snapshot.recommendation_generations_total, 0)
        self.assertEqual(snapshot.trace_spans_total, 0)


class TestRecoveryTelemetry(unittest.TestCase):
    """Validate lightweight tracing spans."""

    def test_span_records_attributes_and_duration(self) -> None:
        telemetry = RecoveryTelemetry(enable_opentelemetry=False)
        with telemetry.start_span("recovery.recommendations.generate", {"job_id": "job-001"}) as span:
            span.set_attribute("confidence", 0.91)
            span.set_attribute("evidence_count", 4)

        self.assertTrue(span.finished)
        self.assertGreaterEqual(span.duration_ms, 0.0)
        self.assertEqual(span.attributes["job_id"], "job-001")
        self.assertEqual(span.attributes["confidence"], 0.91)
        self.assertEqual(span.attributes["evidence_count"], 4)
        self.assertIsNone(span.error)

    def test_span_records_exceptions_without_swallowing(self) -> None:
        telemetry = RecoveryTelemetry(enable_opentelemetry=False)

        with self.assertRaisesRegex(RuntimeError, "boom"):
            with telemetry.start_span("recovery.recommendations.generate") as span:
                raise RuntimeError("boom")

        self.assertTrue(span.finished)
        self.assertEqual(span.error, "boom")
        self.assertGreaterEqual(span.duration_ms, 0.0)


class TestRecoveryRecommendationMetricsIntegration(unittest.TestCase):
    """Validate engine instrumentation against the shared metrics collector."""

    def setUp(self) -> None:
        self.collector = reset_recovery_metrics_collector()
        self.engine = RecoveryRecommendationEngine(StubEventStore(), StubFactStore())

    def test_generate_recommendations_records_metrics(self) -> None:
        request = RecommendationRequest(
            session_id="sess-obs-001",
            job_id="job-obs-001",
            max_recommendations=5,
            include_alternatives=True,
        )

        result = self.engine.generate_recommendations(request)
        snapshot = self.collector.snapshot()

        self.assertTrue(result.has_recommendations)
        self.assertEqual(snapshot.recommendation_generations_total, 1)
        self.assertEqual(snapshot.recommendation_success_total, 1)
        self.assertEqual(snapshot.recommendation_duration_ms_count, 1)
        self.assertEqual(snapshot.trace_spans_total, 1)
        self.assertGreaterEqual(snapshot.total_evidence_considered, 1)
        self.assertGreaterEqual(snapshot.evidence_totals.get("event", 0), 1)
        self.assertGreaterEqual(snapshot.recommendation_confidence_count, 1)


class TestRecoveryMetricsEndpoint(unittest.TestCase):
    """Validate the /recovery/metrics endpoint."""

    def setUp(self) -> None:
        self.collector = reset_recovery_metrics_collector()
        self.client = TestClient(app)

    def test_metrics_endpoint_returns_prometheus_text(self) -> None:
        self.collector.record_http_request("/recovery/recommendations", "GET", 200, 10.0)
        self.collector.record_recommendation_generation(
            request_id="req-002",
            job_id="job-002",
            session_id="sess-002",
            duration_ms=10.0,
            total_evidence_considered=3,
            has_recommendation=True,
            primary_confidence=0.72,
            evidence_counts={"event": 1},
        )

        response = self.client.get("/recovery/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        body = response.text
        self.assertIn("# HELP recovery_recommendation_generations_total", body)
        self.assertIn("recovery_recommendation_generations_total", body)
        self.assertIn("recovery_http_requests_total", body)
        self.assertIn("recovery_trace_spans_total", body)
