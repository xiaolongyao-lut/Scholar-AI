from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import types

os.environ.setdefault("RUNTIME_ENV_DISABLE_DOTENV", "1")

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


def test_import_with_dotenv_disabled_does_not_contaminate_rerank_defaults(monkeypatch) -> None:
    import eval_retrieval_runtime as eval_mod
    import reranker_client as rc

    monkeypatch.setenv("RUNTIME_ENV_DISABLE_DOTENV", "1")
    for name in ("RERANK_MODEL", "SILICONFLOW_RERANK_MODEL", "DASHSCOPE_RERANK_MODEL"):
        monkeypatch.delenv(name, raising=False)

    load_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    fake_dotenv = types.ModuleType("dotenv")

    def _fake_load_dotenv(*args, **kwargs):
        load_calls.append((args, kwargs))
        os.environ.setdefault("RERANK_MODEL", "netease-youdao/bce-reranker-base_v1")
        return True

    fake_dotenv.load_dotenv = _fake_load_dotenv
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)

    importlib.reload(eval_mod)

    assert load_calls == []
    assert os.getenv("RERANK_MODEL") is None
    assert rc.resolve_rerank_config()[2] == "qwen3-rerank"


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


def test_retrieve_with_expansion_embeds_translation_while_hybrid_runs(monkeypatch) -> None:
    """Expanded retrieval should overlap translated dense embedding with async BM25 work."""
    import eval_retrieval_runtime as eval_mod

    async def _fake_translate(query: str, **_kwargs) -> str:
        assert query == "热输入影响"
        return "heat input effect"

    async def _run_case() -> list[str]:
        order: list[str] = []
        hybrid_started = asyncio.Event()
        embedding_started = asyncio.Event()

        async def _fake_hybrid(_corpus, query_text: str, top_k: int = 10) -> list[dict[str, object]]:
            assert query_text == "热输入影响"
            order.append("hybrid-start")
            hybrid_started.set()
            await embedding_started.wait()
            order.append("hybrid-end")
            return [{"chunk_id": "h1", "content": "bm25 hit", "rrf_score": 0.9}][:top_k]

        class _FakeVectorStore:
            async def embed_query(self, text: str) -> list[float]:
                assert text == "heat input effect"
                await hybrid_started.wait()
                order.append("embed-start")
                embedding_started.set()
                return [0.2, 0.4]

        async def _fake_dense_precomputed(
            _store: _FakeVectorStore, query_vec: list[float], top_k: int
        ) -> list[dict[str, object]]:
            assert query_vec == [0.2, 0.4]
            return [{"chunk_id": "d1", "content": "dense hit", "rrf_score": 0.95}][:top_k]

        monkeypatch.setattr(eval_mod, "translate_query_async", _fake_translate)
        monkeypatch.setattr(eval_mod, "hybrid_search_async", _fake_hybrid)
        monkeypatch.setattr(eval_mod, "graph_keyword_search", None)
        monkeypatch.setattr(eval_mod, "_dense_retrieve_precomputed", _fake_dense_precomputed)
        monkeypatch.setattr(eval_mod, "rerank_async", None)

        retrieve_with_expansion_fn = getattr(eval_mod, "_retrieve_with_expansion")
        hits = await asyncio.wait_for(
            retrieve_with_expansion_fn(
                "热输入影响",
                {"chunks": [{"chunk_id": "c0"}]},
                top_k=2,
                keyword_graph=None,
                vector_store=_FakeVectorStore(),
                query_vec=[0.0, 0.0],
                use_rerank=False,
                use_expansion=True,
            ),
            timeout=1.0,
        )

        assert {hit["chunk_id"] for hit in hits} == {"h1", "d1"}
        return order

    order = asyncio.run(_run_case())

    assert order == ["hybrid-start", "embed-start", "hybrid-end"]


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


def test_eval_runtime_main_accepts_json_output_flag(monkeypatch, tmp_path, capsys) -> None:
    import eval_retrieval_runtime as eval_mod

    output_path = tmp_path / "metrics.json"
    payload = {
        "timestamp": "2026-05-02 18:45:00",
        "total_queries": 1,
        "oversize_count": 0,
        "aggregated_metrics": {"recall_at_5": 1.0, "mrr": 1.0, "p95_latency_ms": 12.0},
        "per_difficulty": {},
    }

    def _fake_run_eval(**kwargs):
        assert kwargs["output_path"] == str(output_path)
        return payload

    monkeypatch.setattr(eval_mod, "run_eval", _fake_run_eval)

    result = eval_mod.main(["--output", str(output_path), "--json-output"])

    captured = capsys.readouterr()
    assert result == payload
    assert json.loads(captured.out) == payload
    assert "Evaluation completed." not in captured.out


def test_run_eval_writes_per_query_output_jsonl(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    async def _fake_retrieve(query_text, _corpus, top_k=10, **_kwargs):
        _ = top_k
        doc_id = "doc-1" if query_text == "alpha" else "doc-2"
        return [{"doc_id": doc_id}]

    monkeypatch.setattr(eval_mod, "_retrieve_with_expansion", _fake_retrieve)
    monkeypatch.setattr(eval_mod, "ChunkVectorStore", None)

    queries = [
        {
            "query_id": "q1",
            "query_text": "alpha",
            "difficulty_level": "simple",
            "evidence_set": [{"doc_id": "doc-1"}],
        },
        {
            "query_id": "q2",
            "query_text": "beta",
            "difficulty_level": "hard",
            "evidence_set": [{"doc_id": "doc-2"}],
        },
    ]
    per_query_path = tmp_path / "per_query.jsonl"
    results = asyncio.run(
        eval_mod._run_eval_async(
            queries,
            {"chunks": []},
            None,
            5,
            recall_top_n=5,
            use_rerank=False,
            rerank_top_n=5,
            use_prefilter=False,
            prefilter_threshold=0.0,
            use_dynamic_topk=False,
            dynamic_low_rerank_top_n=5,
            dynamic_high_rerank_top_n=5,
            dynamic_score_gap_threshold=0.15,
            use_expansion=False,
            query_concurrency=1,
            strict_cache_guard=True,
            template_flags_map=None,
            progress_path=None,
            progress_every=1,
            per_query_output=str(per_query_path),
        )
    )

    assert len(results) == 2
    assert per_query_path.exists()
    records = [json.loads(line) for line in per_query_path.read_text(encoding="utf-8").splitlines()]
    assert {rec["query_id"] for rec in records} == {"q1", "q2"}
    assert all("recall_at_1" in rec and "mrr" in rec for rec in records)


def test_run_eval_writes_non_secret_rerank_trace_jsonl(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    async def _fake_hybrid(_corpus, _query, top_k=10):
        return [
            {"chunk_id": "c1", "material_id": "m1", "doc_id": "doc-1", "content": "hidden", "score": 0.8},
            {"chunk_id": "c2", "material_id": "m2", "doc_id": "doc-2", "content": "hidden", "score": 0.7},
            {"chunk_id": "c3", "material_id": "m3", "doc_id": "doc-3", "content": "hidden", "score": 0.6},
        ][:top_k]

    async def _fake_rerank(_query, candidates, top_k=5, **_kwargs):
        assert [item["chunk_id"] for item in candidates] == ["c1", "c2", "c3"]
        return [
            {**candidates[1], "rerank_score": 0.99},
            {**candidates[0], "rerank_score": 0.10},
        ][:top_k]

    monkeypatch.setattr(eval_mod, "hybrid_search_async", _fake_hybrid)
    monkeypatch.setattr(eval_mod, "graph_keyword_search", None)
    monkeypatch.setattr(eval_mod, "rerank_async", _fake_rerank)
    monkeypatch.setattr(eval_mod, "ChunkVectorStore", None)

    trace_path = tmp_path / "rerank_trace.jsonl"
    results = asyncio.run(
        eval_mod._run_eval_async(
            [
                {
                    "query_id": "q1",
                    "query_text": "sensitive query text",
                    "difficulty_level": "hard",
                    "evidence_set": [{"doc_id": "doc-2"}],
                }
            ],
            {"chunks": [{"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c3"}]},
            None,
            2,
            recall_top_n=3,
            use_rerank=True,
            rerank_top_n=3,
            use_prefilter=False,
            prefilter_threshold=0.0,
            use_dynamic_topk=False,
            dynamic_low_rerank_top_n=2,
            dynamic_high_rerank_top_n=3,
            dynamic_score_gap_threshold=0.15,
            use_expansion=False,
            query_concurrency=1,
            strict_cache_guard=True,
            template_flags_map=None,
            progress_path=None,
            progress_every=1,
            per_query_output=None,
            rerank_trace_output=str(trace_path),
        )
    )

    assert results[0]["recall_at_1"] == 1.0
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["query_id"] == "q1"
    assert "query_text" not in trace
    assert len(trace["query_text_sha256"]) == 64
    assert trace["expected_doc_ids"] == ["doc-2"]
    assert trace["rerank_fallback"] is False
    assert [hit["chunk_id"] for hit in trace["candidates_before_rerank"]] == ["c1", "c2", "c3"]
    assert [hit["rank"] for hit in trace["candidates_before_rerank"]] == [1, 2, 3]
    assert [hit["chunk_id"] for hit in trace["returned_hits"]] == ["c2", "c1"]
    assert trace["returned_hits"][0]["rank"] == 1
    assert trace["returned_hits"][0]["rerank_score"] == 0.99
    assert all("content" not in hit for hit in trace["candidates_before_rerank"])
    assert all("content" not in hit for hit in trace["returned_hits"])


def test_run_eval_marks_internal_rerank_fallback_in_trace(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    async def _fake_hybrid(_corpus, _query, top_k=10):
        return [
            {"chunk_id": "c1", "doc_id": "doc-1", "content": "hidden", "rrf_score": 0.8},
            {"chunk_id": "c2", "doc_id": "doc-2", "content": "hidden", "rrf_score": 0.7},
            {"chunk_id": "c3", "doc_id": "doc-3", "content": "hidden", "rrf_score": 0.6},
        ][:top_k]

    async def _fake_rerank(_query, candidates, top_k=5, **_kwargs):
        return [
            {
                **candidates[0],
                "rerank_score": candidates[0]["rrf_score"],
                "rerank_fallback": True,
                "warning": "no_api_key",
            },
            {
                **candidates[1],
                "rerank_score": candidates[1]["rrf_score"],
                "rerank_fallback": True,
                "warning": "no_api_key",
            },
        ][:top_k]

    monkeypatch.setattr(eval_mod, "hybrid_search_async", _fake_hybrid)
    monkeypatch.setattr(eval_mod, "graph_keyword_search", None)
    monkeypatch.setattr(eval_mod, "rerank_async", _fake_rerank)
    monkeypatch.setattr(eval_mod, "ChunkVectorStore", None)

    trace_path = tmp_path / "rerank_trace.jsonl"
    asyncio.run(
        eval_mod._run_eval_async(
            [
                {
                    "query_id": "q1",
                    "query_text": "sensitive query text",
                    "difficulty_level": "hard",
                    "evidence_set": [{"doc_id": "doc-1"}],
                }
            ],
            {"chunks": [{"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c3"}]},
            None,
            2,
            recall_top_n=3,
            use_rerank=True,
            rerank_top_n=3,
            use_prefilter=False,
            prefilter_threshold=0.0,
            use_dynamic_topk=False,
            dynamic_low_rerank_top_n=2,
            dynamic_high_rerank_top_n=3,
            dynamic_score_gap_threshold=0.15,
            use_expansion=False,
            query_concurrency=1,
            strict_cache_guard=True,
            template_flags_map=None,
            progress_path=None,
            progress_every=1,
            per_query_output=None,
            rerank_trace_output=str(trace_path),
        )
    )

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["requested_use_rerank"] is True
    assert trace["use_rerank"] is True
    assert trace["rerank_fallback"] is True
    assert trace["rerank_warning"] == "no_api_key"
    assert all(hit["rerank_fallback"] is True for hit in trace["returned_hits"])
    assert all(hit["warning"] == "no_api_key" for hit in trace["returned_hits"])


def test_run_eval_includes_oversize_count_in_report_header(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    monkeypatch.setattr(eval_mod, "_load_queries", lambda _path: [{"query_id": "q1", "query_text": "q"}])
    monkeypatch.setattr(eval_mod, "_load_retrieval_corpus", lambda: {"chunks": [], "oversize_count": 3})
    monkeypatch.setattr(eval_mod, "build_keyword_graph", None)

    async def _fake_run_eval_async(queries, corpus, keyword_graph, top_k, **kwargs):
        _ = queries, corpus, keyword_graph, top_k, kwargs
        return []

    monkeypatch.setattr(eval_mod, "_run_eval_async", _fake_run_eval_async)

    output_path = tmp_path / "metrics.json"
    payload = eval_mod.run_eval(output_path=str(output_path))

    assert payload["oversize_count"] == 3
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["oversize_count"] == 3


def test_run_eval_includes_run_provenance(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    queries_path = tmp_path / "queries.jsonl"
    queries_path.write_text(
        "\n".join(
            [
                json.dumps({"query_id": "q1", "query_text": "alpha"}),
                json.dumps({"query_id": "q2", "query_text": "beta"}),
            ]
        ),
        encoding="utf-8",
    )
    template_flags_path = tmp_path / "template_flags.jsonl"
    template_flags_path.write_text(
        json.dumps({"query_id": "q1", "is_template": True}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        eval_mod,
        "_load_queries",
        lambda _path: [
            {"query_id": "q1", "query_text": "alpha"},
            {"query_id": "q2", "query_text": "beta"},
        ],
    )
    monkeypatch.setattr(eval_mod, "_load_retrieval_corpus", lambda: {"chunks": []})
    monkeypatch.setattr(eval_mod, "build_keyword_graph", None)
    monkeypatch.setattr(
        eval_mod,
        "_resolve_rerank_model_identity",
        lambda _use_rerank: "Qwen/Qwen3-Reranker-8B",
    )

    async def _fake_run_eval_async(queries, corpus, keyword_graph, top_k, **kwargs):
        _ = queries, corpus, keyword_graph, top_k, kwargs
        return []

    monkeypatch.setattr(eval_mod, "_run_eval_async", _fake_run_eval_async)

    output_path = tmp_path / "metrics.json"
    payload = eval_mod.run_eval(
        queries_path=str(queries_path),
        output_path=str(output_path),
        template_flags_path=str(template_flags_path),
        offset=1,
        limit=1,
    )

    provenance = payload["run_provenance"]
    assert provenance["queries"]["path"] == str(queries_path.resolve())
    assert provenance["queries"]["source_total_queries"] == 2
    assert provenance["queries"]["evaluated_queries"] == 1
    assert provenance["queries"]["offset"] == 1
    assert provenance["queries"]["limit"] == 1
    assert provenance["queries"]["sha256"]
    assert provenance["template_flags"]["enabled"] is True
    assert provenance["template_flags"]["path"] == str(template_flags_path.resolve())
    assert provenance["template_flags"]["sha256"]
    assert provenance["retrieval_config"]["rerank_model"] == "Qwen/Qwen3-Reranker-8B"
    assert provenance["retrieval_config"]["strict_cache_guard"] is True


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


def test_run_eval_writes_resume_guard_config(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    monkeypatch.setattr(eval_mod, "_load_queries", lambda _path: [{"query_id": "q1", "query_text": "q"}])
    monkeypatch.setattr(eval_mod, "_load_retrieval_corpus", lambda: {"chunks": []})
    monkeypatch.setattr(eval_mod, "build_keyword_graph", None)
    monkeypatch.setattr(
        eval_mod,
        "resolve_rerank_config",
        lambda *args, **kwargs: (None, "https://api.siliconflow.cn/v1/rerank", "qwen3-rerank"),
    )

    async def _fake_run_eval_async(queries, corpus, keyword_graph, top_k, **kwargs):
        _ = queries, corpus, keyword_graph, top_k, kwargs
        return []

    monkeypatch.setattr(eval_mod, "_run_eval_async", _fake_run_eval_async)

    output_path = tmp_path / "metrics.json"
    progress_path = tmp_path / "progress.jsonl"
    per_query_path = tmp_path / "per_query.jsonl"
    eval_mod.run_eval(
        output_path=str(output_path),
        progress_path=str(progress_path),
        per_query_output=str(per_query_path),
        offset=5,
        limit=10,
    )

    guard_path = output_path.with_name(output_path.name + ".resume_config.json")
    assert guard_path.exists()
    payload = json.loads(guard_path.read_text(encoding="utf-8"))
    assert payload["query_slice"] == {"offset": 5, "limit": 10}
    assert payload["retrieval_config"]["use_rerank"] is True
    assert payload["retrieval_config"]["rerank_model"] == "qwen3-rerank"
    assert payload["append_targets"]["progress_path"] == str(progress_path.resolve())
    assert payload["append_targets"]["per_query_output"] == str(per_query_path.resolve())


def test_run_eval_rejects_resume_config_mismatch(monkeypatch, tmp_path) -> None:
    import eval_retrieval_runtime as eval_mod

    output_path = tmp_path / "metrics.json"
    progress_path = tmp_path / "progress.jsonl"
    progress_path.write_text('{"done": 1}\n', encoding="utf-8")
    per_query_path = tmp_path / "per_query.jsonl"
    guard_path = output_path.with_name(output_path.name + ".resume_config.json")
    guard_payload = eval_mod._build_resume_guard_config(
        queries_path="eval_queries_v2.0.jsonl",
        output_path=str(output_path),
        top_k=10,
        recall_top_n=100,
        use_rerank=False,
        rerank_top_n=40,
        use_prefilter=False,
        prefilter_threshold=0.3,
        use_dynamic_topk=False,
        dynamic_low_rerank_top_n=20,
        dynamic_high_rerank_top_n=60,
        dynamic_score_gap_threshold=0.15,
        use_expansion=False,
        use_contextual=False,
        query_concurrency=8,
        strict_cache_guard=True,
        template_flags_path=None,
        offset=0,
        limit=None,
        progress_path=str(progress_path),
        progress_every=100,
        per_query_output=str(per_query_path),
    )
    guard_path.write_text(json.dumps(guard_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(eval_mod, "_load_queries", lambda _path: [{"query_id": "q1", "query_text": "q"}])
    monkeypatch.setattr(eval_mod, "_load_retrieval_corpus", lambda: {"chunks": []})
    monkeypatch.setattr(eval_mod, "build_keyword_graph", None)

    async def _fake_run_eval_async(queries, corpus, keyword_graph, top_k, **kwargs):
        _ = queries, corpus, keyword_graph, top_k, kwargs
        return []

    monkeypatch.setattr(eval_mod, "_run_eval_async", _fake_run_eval_async)
    monkeypatch.setattr(
        eval_mod,
        "resolve_rerank_config",
        lambda *args, **kwargs: (None, "https://api.siliconflow.cn/v1/rerank", "qwen3-rerank"),
    )

    try:
        eval_mod.run_eval(
            output_path=str(output_path),
            progress_path=str(progress_path),
            per_query_output=str(per_query_path),
            use_rerank=True,
        )
        assert False, "expected ValueError for resume guard mismatch"
    except ValueError as exc:
        assert "Resume parity guard rejected" in str(exc)


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


def test_prefilter_hits_filters_by_threshold_and_keeps_order() -> None:
    from eval_retrieval_runtime import _prefilter_hits

    hits = [
        {"chunk_id": "a", "rrf_score": 0.91},
        {"chunk_id": "b", "rrf_score": 0.42},
        {"chunk_id": "c", "rrf_score": 0.25},
    ]

    filtered = _prefilter_hits(hits, threshold=0.4, keep_top_n=10)
    assert [h["chunk_id"] for h in filtered] == ["a", "b"]


def test_prefilter_hits_fallbacks_to_top_n_when_all_filtered() -> None:
    from eval_retrieval_runtime import _prefilter_hits

    hits = [
        {"chunk_id": "a", "rrf_score": 0.20},
        {"chunk_id": "b", "rrf_score": 0.10},
        {"chunk_id": "c", "rrf_score": 0.05},
    ]

    # 所有候选都低于阈值时，应该兜底回退到原始 top_n，而不是返回空列表。
    filtered = _prefilter_hits(hits, threshold=0.4, keep_top_n=2)
    assert [h["chunk_id"] for h in filtered] == ["a", "b"]


def test_retrieve_prefilter_applies_before_rerank(monkeypatch) -> None:
    import eval_retrieval_runtime as eval_mod

    async def _fake_hybrid(_corpus, _query, top_k=5):
        return [
            {"chunk_id": "c1", "content": "high", "rrf_score": 0.91},
            {"chunk_id": "c2", "content": "mid", "rrf_score": 0.31},
            {"chunk_id": "c3", "content": "low", "rrf_score": 0.12},
        ][:top_k]

    async def _fake_rerank(_query, candidates, top_k=5, **_kwargs):
        # 阈值 0.3 后仅 c1/c2 应进入 rerank
        assert [item["chunk_id"] for item in candidates] == ["c1", "c2"]
        return candidates[:top_k]

    monkeypatch.setattr(eval_mod, "hybrid_search_async", _fake_hybrid)
    monkeypatch.setattr(eval_mod, "graph_keyword_search", None)
    monkeypatch.setattr(eval_mod, "rerank_async", _fake_rerank)

    retrieve_fn = getattr(eval_mod, "_retrieve")
    hits = asyncio.run(
        retrieve_fn(
            "laser query",
            {"chunks": [{"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c3"}]},
            top_k=2,
            use_rerank=True,
            use_prefilter=True,
            # RRF(k=60) 下前几名分数约 0.016x，使用该量级阈值过滤尾部候选。
            prefilter_threshold=0.016,
        )
    )

    assert [item["chunk_id"] for item in hits] == ["c1", "c2"]


def test_compute_dynamic_rerank_top_n_prefers_low_when_confident() -> None:
    from eval_retrieval_runtime import _compute_dynamic_rerank_top_n

    hits = [
        {"chunk_id": "a", "rrf_score": 0.90},
        {"chunk_id": "b", "rrf_score": 0.60},
        {"chunk_id": "c", "rrf_score": 0.30},
        {"chunk_id": "d", "rrf_score": 0.10},
    ]
    n = _compute_dynamic_rerank_top_n(
        "清晰明确的问题",
        hits,
        low_top_n=2,
        high_top_n=5,
        score_gap_threshold=0.15,
    )
    assert n == 2


def test_compute_dynamic_rerank_top_n_raises_for_uncertain_query() -> None:
    from eval_retrieval_runtime import _compute_dynamic_rerank_top_n

    hits = [
        {"chunk_id": "a", "rrf_score": 0.42},
        {"chunk_id": "b", "rrf_score": 0.40},
        {"chunk_id": "c", "rrf_score": 0.39},
        {"chunk_id": "d", "rrf_score": 0.38},
        {"chunk_id": "e", "rrf_score": 0.37},
        {"chunk_id": "f", "rrf_score": 0.36},
    ]
    n = _compute_dynamic_rerank_top_n(
        "为什么",
        hits,
        low_top_n=2,
        high_top_n=5,
        score_gap_threshold=0.15,
    )
    assert n == 5


def test_retrieve_dynamic_topk_expands_rerank_candidates_when_uncertain(monkeypatch) -> None:
    import eval_retrieval_runtime as eval_mod

    async def _fake_hybrid(_corpus, _query, top_k=5):
        return [
            {"chunk_id": "c1", "content": "v1", "rrf_score": 0.42},
            {"chunk_id": "c2", "content": "v2", "rrf_score": 0.40},
            {"chunk_id": "c3", "content": "v3", "rrf_score": 0.39},
            {"chunk_id": "c4", "content": "v4", "rrf_score": 0.38},
            {"chunk_id": "c5", "content": "v5", "rrf_score": 0.37},
        ][:top_k]

    async def _fake_rerank(_query, candidates, top_k=5, **_kwargs):
        assert len(candidates) == 5
        return candidates[:top_k]

    monkeypatch.setattr(eval_mod, "hybrid_search_async", _fake_hybrid)
    monkeypatch.setattr(eval_mod, "graph_keyword_search", None)
    monkeypatch.setattr(eval_mod, "rerank_async", _fake_rerank)

    retrieve_fn = getattr(eval_mod, "_retrieve")
    hits = asyncio.run(
        retrieve_fn(
            "为什么",
            {"chunks": [{"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c3"}]},
            top_k=2,
            use_rerank=True,
            use_dynamic_topk=True,
            dynamic_low_rerank_top_n=2,
            dynamic_high_rerank_top_n=5,
            dynamic_score_gap_threshold=0.15,
        )
    )

    assert len(hits) == 2


def test_resolve_rerank_pre_top_n_balanced_defaults_to_30(monkeypatch) -> None:
    import eval_retrieval_runtime as eval_mod

    monkeypatch.delenv("LITERATURE_AI_COST_PROFILE", raising=False)
    monkeypatch.delenv("RERANK_PRE_TOPN", raising=False)
    monkeypatch.delenv("RERANK_PRE_TOPN_HARD_CAP", raising=False)

    n = eval_mod._resolve_rerank_pre_top_n(
        "清晰明确的问题",
        [{"rrf_score": 0.90}, {"rrf_score": 0.60}, {"rrf_score": 0.30}],
        rerank_top_n=80,
        hybrid_hit_count=10,
    )
    assert n == 30


def test_resolve_rerank_pre_top_n_aggressive_forces_20(monkeypatch) -> None:
    import eval_retrieval_runtime as eval_mod

    monkeypatch.setenv("LITERATURE_AI_COST_PROFILE", "aggressive")
    monkeypatch.delenv("RERANK_PRE_TOPN", raising=False)
    monkeypatch.delenv("RERANK_PRE_TOPN_HARD_CAP", raising=False)

    n = eval_mod._resolve_rerank_pre_top_n(
        "清晰明确的问题",
        [{"rrf_score": 0.90}, {"rrf_score": 0.60}, {"rrf_score": 0.30}],
        rerank_top_n=80,
        hybrid_hit_count=10,
    )
    assert n == 20


def test_resolve_rerank_pre_top_n_quality_defaults_to_50(monkeypatch) -> None:
    import eval_retrieval_runtime as eval_mod

    monkeypatch.setenv("LITERATURE_AI_COST_PROFILE", "quality")
    monkeypatch.delenv("RERANK_PRE_TOPN", raising=False)
    monkeypatch.delenv("RERANK_PRE_TOPN_HARD_CAP", raising=False)

    n = eval_mod._resolve_rerank_pre_top_n(
        "清晰明确的问题",
        [{"rrf_score": 0.90}, {"rrf_score": 0.60}, {"rrf_score": 0.30}],
        rerank_top_n=80,
        hybrid_hit_count=10,
    )
    assert n == 50


def test_resolve_rerank_pre_top_n_expands_to_hard_cap_on_uncertain_query(monkeypatch) -> None:
    import eval_retrieval_runtime as eval_mod

    monkeypatch.delenv("LITERATURE_AI_COST_PROFILE", raising=False)
    monkeypatch.delenv("RERANK_PRE_TOPN", raising=False)
    monkeypatch.delenv("RERANK_PRE_TOPN_HARD_CAP", raising=False)

    n = eval_mod._resolve_rerank_pre_top_n(
        "为什么",
        [{"rrf_score": 0.42}, {"rrf_score": 0.40}, {"rrf_score": 0.39}],
        rerank_top_n=80,
        hybrid_hit_count=10,
    )
    assert n == 60


def test_retrieve_applies_pre_topn_cap_before_rerank(monkeypatch) -> None:
    import eval_retrieval_runtime as eval_mod

    monkeypatch.delenv("LITERATURE_AI_COST_PROFILE", raising=False)
    monkeypatch.delenv("RERANK_PRE_TOPN", raising=False)
    monkeypatch.delenv("RERANK_PRE_TOPN_HARD_CAP", raising=False)

    async def _fake_hybrid(_corpus, _query, top_k=5):
        return [
            {"chunk_id": f"c{i}", "content": f"v{i}", "rrf_score": 1.0 - i * 0.01}
            for i in range(top_k)
        ]

    async def _fake_rerank(_query, candidates, top_k=5, **_kwargs):
        assert len(candidates) == 30
        return candidates[:top_k]

    monkeypatch.setattr(eval_mod, "hybrid_search_async", _fake_hybrid)
    monkeypatch.setattr(eval_mod, "graph_keyword_search", None)
    monkeypatch.setattr(eval_mod, "rerank_async", _fake_rerank)

    retrieve_fn = getattr(eval_mod, "_retrieve")
    hits = asyncio.run(
        retrieve_fn(
            "清晰明确的问题",
            {"chunks": [{"chunk_id": f"c{i}"} for i in range(100)]},
            top_k=5,
            use_rerank=True,
            rerank_top_n=80,
        )
    )

    assert len(hits) == 5
