from __future__ import annotations

from gateb_schema_validator import (
    validate_gateb_pilot_contract,
    validate_run_provenance_completeness,
    validate_shared_qrels_contract,
)


def _record(query_id: str, *, stratum: str = "S1", judged: int = 10, overlap: bool = False) -> dict:
    return {
        "query_id": query_id,
        "query_text": f"query-{query_id}",
        "source_stratum": stratum,
        "annotator_id": "annotator-a",
        "created_at": "2026-04-25T00:00:00+00:00",
        "kappa_overlap_group": "ovl-a" if overlap else None,
        "qrels": [{"doc_id": f"doc-{query_id}-{i}", "relevance": i % 3} for i in range(judged)],
    }


def test_validate_gateb_pilot_contract_passes_on_frozen_shape() -> None:
    records = []
    records += [_record(f"s1-{i}", stratum="S1", overlap=i < 4) for i in range(16)]
    records += [_record(f"s2-{i}", stratum="S2", overlap=i < 2) for i in range(10)]
    records += [_record(f"s3-{i}", stratum="S3", overlap=i < 2) for i in range(10)]
    records += [_record(f"s4-{i}", stratum="S4", overlap=i < 2) for i in range(4)]

    errors = validate_gateb_pilot_contract(records, observed_kappa=0.72)
    assert errors == []


def test_validate_gateb_pilot_contract_rejects_low_judged_depth() -> None:
    records = [_record(f"q-{i}", stratum="S1", judged=10) for i in range(40)]
    records[0]["source_stratum"] = "S2"
    records[1]["source_stratum"] = "S3"
    records[2]["source_stratum"] = "S4"
    records[0]["qrels"] = records[0]["qrels"][:9]

    errors = validate_gateb_pilot_contract(records)
    assert any("judged docs must be >=" in error for error in errors)


def test_validate_shared_qrels_contract_detects_mismatch() -> None:
    records_a = [_record("q1", stratum="S2"), _record("q2", stratum="S3")]
    records_b = [_record("q1", stratum="S2"), _record("q2", stratum="S3")]
    records_b[1]["qrels"][0]["relevance"] = 2

    errors = validate_shared_qrels_contract(records_a, records_b)
    assert errors == ["qrels mismatch for query_id=q2"]


def test_validate_run_provenance_completeness_flags_missing_fields() -> None:
    payload = {
        "run_provenance": {
            "queries": {"path": "x", "sha256": "y", "offset": 0},
            "template_flags": {"enabled": True},
            "retrieval_config": {"top_k": 10, "use_rerank": True},
        }
    }

    errors = validate_run_provenance_completeness(payload)
    assert "missing run_provenance.queries.limit" in errors
    assert "missing run_provenance.retrieval_config.recall_top_n" in errors
    assert "missing run_provenance.retrieval_config.rerank_model" in errors
