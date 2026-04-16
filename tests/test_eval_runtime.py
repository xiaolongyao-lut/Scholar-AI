from __future__ import annotations

from eval_retrieval_runtime import aggregate_metrics


def test_eval_runtime_outputs_required_keys() -> None:
    sample = [
        {
            "recall_at_1": 0.0,
            "recall_at_3": 1.0,
            "recall_at_5": 1.0,
            "recall_at_10": 1.0,
            "mrr": 0.5,
            "latency_ms": 20.0,
            "difficulty": "medium",
        },
        {
            "recall_at_1": 0.0,
            "recall_at_3": 0.0,
            "recall_at_5": 0.0,
            "recall_at_10": 1.0,
            "mrr": 0.0,
            "latency_ms": 40.0,
            "difficulty": "hard",
        },
    ]

    metrics = aggregate_metrics(sample)

    assert "aggregated_metrics" in metrics
    assert "per_difficulty" in metrics

    agg = metrics["aggregated_metrics"]
    assert agg["recall_at_3"] == 0.5
    assert agg["recall_at_5"] == 0.5
    assert agg["mrr"] == 0.25
    assert agg["avg_latency_ms"] == 30.0

    per_difficulty = metrics["per_difficulty"]
    assert per_difficulty["medium"]["count"] == 1
    assert per_difficulty["hard"]["count"] == 1
