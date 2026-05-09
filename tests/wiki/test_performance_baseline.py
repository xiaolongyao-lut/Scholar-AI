from __future__ import annotations

import pytest

from tools.eval.wiki_wave14_performance_baseline import run_wiki_wave14_performance_baseline


def test_wiki_performance_baseline_reports_percentiles_and_throughput() -> None:
    payload = run_wiki_wave14_performance_baseline(iterations=2)

    assert payload["schema_version"] == 2
    assert payload["iterations"] == 2
    assert payload["mode"] == "zero_cost_temp_workspace"
    assert payload["created_pages"] >= 1
    assert payload["query_hit_count"] >= 1
    assert payload["doctor_check_count"] >= 1

    latency = payload["latency_ms"]
    assert isinstance(latency, dict)
    for key in ("compile", "index", "query", "doctor", "total"):
        summary = latency[key]
        assert isinstance(summary, dict)
        assert len(summary["samples"]) == 2
        assert summary["min"] >= 0
        assert summary["max"] >= summary["min"]
        assert summary["p50"] >= 0
        assert summary["p95"] >= summary["p50"]
        assert summary["p99"] >= summary["p95"]

    throughput = payload["throughput_per_second"]
    assert isinstance(throughput, dict)
    assert throughput["compile_pages"] > 0
    assert throughput["queries"] > 0
    assert throughput["doctor_checks"] > 0


def test_wiki_performance_baseline_rejects_invalid_iterations() -> None:
    with pytest.raises(ValueError, match="iterations"):
        run_wiki_wave14_performance_baseline(iterations=0)
