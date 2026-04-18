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

    retrieve_fn = getattr(eval_mod, "_retrieve")
    hits = asyncio.run(
        retrieve_fn(
            "laser query",
            {"chunks": [{"chunk_id": "c1"}, {"chunk_id": "c2"}]},
            top_k=2,
            use_rerank=True,
        )
    )

    assert [item["chunk_id"] for item in hits] == ["c2", "c1"]
    assert hits[0]["rerank_score"] == 0.95


def test_retrieve_with_expansion_uses_translated_query_for_retrieval(monkeypatch) -> None:
    """Phase 5.2: split-routing — BM25+Graph 走中文原 query，
    Dense 走英文翻译 + 重嵌向量，Rerank 走中文原 query。"""
    import eval_retrieval_runtime as eval_mod

    async def _fake_translate(query: str, **_kwargs):
        assert query == "海洋碳循环"
        return "ocean carbon cycle"

    hybrid_calls: list[str] = []
    graph_calls: list[str] = []

    async def _fake_hybrid(_corpus, query_text, top_k=10):
        hybrid_calls.append(query_text)
        return [{"chunk_id": "h1", "content": "bm25 hit", "rrf_score": 0.9}][:top_k]

    def _fake_graph_search(_graph, _chunks, query="", top_k=10):
        graph_calls.append(query)
        return [{"chunk_id": "g1", "content": "graph hit", "rrf_score": 0.85}][:top_k]

    class _FakeVectorStore:
        embed_calls: list[str] = []

        async def embed_query(self, text):
            self.embed_calls.append(text)
            return [0.1, 0.2]

    fake_store = _FakeVectorStore()

    async def _fake_dense_precomputed(store, query_vec, top_k):
        assert store is fake_store
        assert query_vec == [0.1, 0.2]
        return [{"chunk_id": "d1", "content": "dense hit", "rrf_score": 0.95}][:top_k]

    async def _fake_rerank(query, candidates, top_k=5, **_kwargs):
        assert query == "海洋碳循环"  # 中文原 query 给 rerank
        return [{**c, "rerank_score": 1.0 - i * 0.1} for i, c in enumerate(candidates)][:top_k]

    monkeypatch.setattr(eval_mod, "translate_query_async", _fake_translate)
    monkeypatch.setattr(eval_mod, "hybrid_search_async", _fake_hybrid)
    monkeypatch.setattr(eval_mod, "graph_keyword_search", _fake_graph_search)
    monkeypatch.setattr(eval_mod, "build_keyword_graph", lambda _chunks: {"dummy": True})
    monkeypatch.setattr(eval_mod, "_dense_retrieve_precomputed", _fake_dense_precomputed)
    monkeypatch.setattr(eval_mod, "rerank_async", _fake_rerank)

    retrieve_with_expansion_fn = getattr(eval_mod, "_retrieve_with_expansion")
    hits = asyncio.run(
        retrieve_with_expansion_fn(
            "海洋碳循环",
            {"chunks": [{"chunk_id": "c0"}]},
            top_k=3,
            keyword_graph={"dummy": True},
            vector_store=fake_store,
            query_vec=[0.0, 0.0],
            use_rerank=True,
            use_expansion=True,
        )
    )

    assert hybrid_calls == ["海洋碳循环"], "BM25 必须用中文原 query"
    assert graph_calls == ["海洋碳循环"], "Graph 必须用中文原 query"
    assert fake_store.embed_calls == ["ocean carbon cycle"], "Dense 必须用英文翻译重嵌"
    assert {h["chunk_id"] for h in hits} == {"h1", "g1", "d1"}
    assert all("rerank_score" in h for h in hits)


def test_run_eval_contextualizes_chunks_when_enabled(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    monkeypatch.setattr(eval_mod, "_load_queries", lambda _path: [{"query_id": "q1", "query_text": "q"}])
    monkeypatch.setattr(
        eval_mod,
        "_load_retrieval_corpus",
        lambda: {"chunks": [{"chunk_id": "c1", "material_id": "m1", "content": "raw"}]},
    )

    called = {"contextualized": False}

    def _fake_batch_contextualize(chunks, **_kwargs):
        called["contextualized"] = True
        return [{**chunks[0], "content": "[摘要]\nraw"}]

    monkeypatch.setattr(eval_mod, "batch_contextualize", _fake_batch_contextualize)
    monkeypatch.setattr(eval_mod, "build_keyword_graph", lambda chunks: {"n": len(chunks)})

    async def _fake_run_eval_async(queries, corpus, keyword_graph, top_k, **_kwargs):
        _ = queries, keyword_graph, top_k
        assert corpus["chunks"][0]["content"].startswith("[摘要]")
        return []

    monkeypatch.setattr(eval_mod, "_run_eval_async", _fake_run_eval_async)

    out_file = tmp_path / "metrics.json"
    payload = eval_mod.run_eval(
        queries_path="ignored.jsonl",
        output_path=str(out_file),
        use_contextual=True,
        use_expansion=False,
        use_rerank=False,
    )

    assert called["contextualized"] is True
    assert payload["total_queries"] == 1
    assert out_file.exists()


def test_retrieve_with_expansion_honors_independent_recall_top_n(monkeypatch) -> None:
    """首轮召回 topN 应独立于最终 topK，且传给 hybrid/graph/dense 三路。"""
    import eval_retrieval_runtime as eval_mod

    async def _fake_translate(query: str, **_kwargs):
        return "english-" + query

    hybrid_top_k: list[int] = []
    dense_top_k: list[int] = []
    graph_top_k: list[int] = []

    async def _fake_hybrid(_corpus, _query, top_k=10):
        hybrid_top_k.append(top_k)
        return [{"chunk_id": f"h{i}"} for i in range(top_k)]

    def _fake_graph(_graph, _chunks, query="", top_k=10):
        _ = query
        graph_top_k.append(top_k)
        return [{"chunk_id": f"g{i}"} for i in range(top_k)]

    async def _fake_dense_precomputed(_store, _vec, top_k):
        dense_top_k.append(top_k)
        return [{"chunk_id": f"d{i}"} for i in range(top_k)]

    async def _fake_rerank(_query, candidates, top_k=5, **_kwargs):
        return candidates[:top_k]

    class _Store:
        async def embed_query(self, _t):
            return [0.0]

    monkeypatch.setattr(eval_mod, "translate_query_async", _fake_translate)
    monkeypatch.setattr(eval_mod, "hybrid_search_async", _fake_hybrid)
    monkeypatch.setattr(eval_mod, "graph_keyword_search", _fake_graph)
    monkeypatch.setattr(eval_mod, "_dense_retrieve_precomputed", _fake_dense_precomputed)
    monkeypatch.setattr(eval_mod, "rerank_async", _fake_rerank)

    retrieve_with_expansion_fn = getattr(eval_mod, "_retrieve_with_expansion")
    hits = asyncio.run(
        retrieve_with_expansion_fn(
            "test-query",
            {"chunks": []},
            top_k=10,
            keyword_graph={"dummy": True},
            vector_store=_Store(),
            query_vec=[0.0],
            use_rerank=True,
            rerank_top_n=30,
            use_expansion=True,
            recall_top_n=100,
        )
    )

    # 三路召回都用 recall_top_n（合并候选池深度）
    assert hybrid_top_k == [100]
    assert graph_top_k == [100]
    assert dense_top_k == [100]
    assert len(hits) == 10


def test_run_eval_uses_recommended_defaults(monkeypatch, tmp_path) -> None:
    """默认参数应对齐当前线上保守策略（expansion 默认关闭，需显式开启）。"""
    import eval_retrieval_runtime as eval_mod

    monkeypatch.setattr(eval_mod, "_load_queries", lambda _path: [{"query_id": "q1", "query_text": "q"}])
    monkeypatch.setattr(eval_mod, "_load_retrieval_corpus", lambda: {"chunks": []})
    monkeypatch.setattr(eval_mod, "build_keyword_graph", None)

    captured: dict[str, object] = {}

    async def _fake_run_eval_async(queries, corpus, keyword_graph, top_k, **kwargs):
        _ = queries, corpus, keyword_graph
        captured["top_k"] = top_k
        captured.update(kwargs)
        return []

    monkeypatch.setattr(eval_mod, "_run_eval_async", _fake_run_eval_async)

    out_file = tmp_path / "metrics.json"
    eval_mod.run_eval(output_path=str(out_file))

    assert captured["top_k"] == 10
    assert captured["recall_top_n"] == 100
    assert captured["use_rerank"] is True
    assert captured["rerank_top_n"] == 40
    assert captured["use_expansion"] is False


def test_aggregate_metrics_per_template_bucket() -> None:
    """Wave 1:带 is_template 字段的 results 应产出 per_template_bucket(template/non_template 两档)。"""
    from eval_retrieval_runtime import aggregate_metrics

    sample = [
        {"recall_at_1": 0.0, "recall_at_3": 0.0, "recall_at_5": 1.0, "recall_at_10": 1.0,
         "mrr": 1.0, "latency_ms": 10.0, "difficulty": "simple", "is_template": True},
        {"recall_at_1": 0.0, "recall_at_3": 0.0, "recall_at_5": 0.0, "recall_at_10": 0.0,
         "mrr": 0.0, "latency_ms": 20.0, "difficulty": "simple", "is_template": True},
        {"recall_at_1": 0.0, "recall_at_3": 0.0, "recall_at_5": 1.0, "recall_at_10": 1.0,
         "mrr": 0.5, "latency_ms": 30.0, "difficulty": "hard", "is_template": False},
        {"recall_at_1": 0.0, "recall_at_3": 0.0, "recall_at_5": 1.0, "recall_at_10": 1.0,
         "mrr": 0.5, "latency_ms": 40.0, "difficulty": "hard", "is_template": False},
    ]
    metrics = aggregate_metrics(sample)

    assert "per_template_bucket" in metrics
    bucket = metrics["per_template_bucket"]
    assert bucket["template"]["count"] == 2
    assert bucket["template"]["recall_at_5"] == 0.5
    assert bucket["template"]["mrr"] == 0.5
    assert bucket["non_template"]["count"] == 2
    assert bucket["non_template"]["recall_at_5"] == 1.0
    assert bucket["non_template"]["mrr"] == 0.5


def test_aggregate_metrics_no_template_flag_preserves_schema() -> None:
    """Wave 1:results 都无 is_template 字段 → 不输出 per_template_bucket,保持向后兼容。"""
    from eval_retrieval_runtime import aggregate_metrics

    sample = [
        {"recall_at_1": 0.0, "recall_at_3": 1.0, "recall_at_5": 1.0, "recall_at_10": 1.0,
         "mrr": 0.5, "latency_ms": 10.0, "difficulty": "simple"}
    ]
    metrics = aggregate_metrics(sample)
    assert "per_template_bucket" not in metrics
