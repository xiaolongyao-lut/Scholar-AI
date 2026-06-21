"""Tests for journal metric evidence source-tier models."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from models import JournalMetricEvidencePayload, JournalMetricEvidenceSet


def test_official_journal_metric_evidence_serializes_source_provenance() -> None:
    """Official metric rows should carry verifier/date/source URL provenance."""

    record = JournalMetricEvidencePayload(
        journal_title="Journal of Additive Manufacturing Letters",
        issn="2772-3690",
        metric_name="Journal Impact Factor",
        metric_year=2025,
        metric_value="4.2",
        source_tier="official",
        source_name="Clarivate Journal Citation Reports",
        source_url="https://jcr.clarivate.com/",
        verified_at=date(2026, 6, 21),
        verified_by="local-review",
        claim_scope="official_metric",
    )

    payload = record.model_dump(mode="json")

    assert payload["schema_version"] == "scholar-ai-journal-metric-evidence/v1"
    assert payload["source_tier"] == "official"
    assert payload["claim_scope"] == "official_metric"
    assert payload["verified_at"] == "2026-06-21"


def test_aggregated_metric_cannot_support_official_claim() -> None:
    """Aggregated metrics may support screening only, not official IF claims."""

    with pytest.raises(ValidationError, match="aggregated journal metrics"):
        JournalMetricEvidencePayload(
            journal_title="Example Journal",
            metric_name="CAS partition",
            metric_year=2025,
            metric_value="一区",
            source_tier="aggregated",
            source_name="easyScholar",
            source_url="https://www.easyscholar.cc/",
            verified_at=date(2026, 6, 21),
            verified_by="local-review",
            claim_scope="official_metric",
        )


def test_metric_evidence_set_summarizes_official_and_aggregated_rows() -> None:
    """Collection summaries keep official proof separate from screening refs."""

    records = [
        JournalMetricEvidencePayload(
            journal_title="Official Journal",
            metric_name="Journal Impact Factor",
            metric_year=2025,
            metric_value="5.1",
            source_tier="official",
            source_name="Publisher official metrics page",
            source_url="https://example.org/official",
            verified_at=date(2026, 6, 21),
            verified_by="reviewer",
            claim_scope="official_metric",
        ),
        JournalMetricEvidencePayload(
            journal_title="Official Journal",
            metric_name="CCF",
            metric_year=2025,
            metric_value="B",
            source_tier="aggregated",
            source_name="easyScholar",
            source_url="https://www.easyscholar.cc/",
            verified_at=date(2026, 6, 21),
            verified_by="reviewer",
            claim_scope="screening_reference",
            notes=["聚合源仅用于候选筛选"],
        ),
    ]
    evidence_set = JournalMetricEvidenceSet(records=records)

    assert evidence_set.official_count == 1
    assert evidence_set.aggregated_count == 1
    assert evidence_set.has_official_metric_claim is True
    assert evidence_set.summary() == {
        "schema_version": "scholar-ai-journal-metric-evidence-set/v1",
        "total": 2,
        "official_count": 1,
        "aggregated_count": 1,
        "has_official_metric_claim": True,
    }
