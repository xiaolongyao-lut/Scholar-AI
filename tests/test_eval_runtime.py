from __future__ import annotations

import asyncio

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


def test_retrieve_applies_rerank_after_rrf(monkeypatch) -> None:
    import eval_retrieval_runtime as eval_mod

    async def _fake_hybrid(_corpus, _query, top_k=5):
        return [
            {"chunk_id": "c1", "content": "first", "rrf_score": 0.9},
            {"chunk_id": "c2", "content": "second", "rrf_score": 0.8},
        ][:top_k]

    async def _fake_rerank(query, candidates, top_k=5, **_kwargs):
        assert query == "laser query"
        assert [item["chunk_id"] for item in candidates] == ["c1", "c2"]
        return [
            {**candidates[1], "rerank_score": 0.95},
            {**candidates[0], "rerank_score": 0.12},
        ][:top_k]

    monkeypatch.setattr(eval_mod, "hybrid_search_async", _fake_hybrid)
    monkeypatch.setattr(eval_mod, "graph_keyword_search", None)
    monkeypatch.setattr(eval_mod, "rerank_async", _fake_rerank)

    hits = asyncio.run(
        eval_mod._retrieve(
            "laser query",
            {"chunks": [{"chunk_id": "c1"}, {"chunk_id": "c2"}]},
            top_k=2,
            use_rerank=True,
        )
    )

    assert [item["chunk_id"] for item in hits] == ["c2", "c1"]
    assert hits[0]["rerank_score"] == 0.95
