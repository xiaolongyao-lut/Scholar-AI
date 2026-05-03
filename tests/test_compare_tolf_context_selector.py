from __future__ import annotations

import json

import pytest

from tools.eval.compare_tolf_context_selector import compare_context_selectors, main


def test_compare_context_selectors_reports_overlap() -> None:
    queries = [{"query_id": "q1", "query_text": "laser power hardness"}]
    chunks = [
        {
            "chunk_id": "c_result",
            "material_id": "mat_result",
            "title": "Laser Result",
            "content": "This study reports laser power increased hardness to 280 HV.",
        },
        {
            "chunk_id": "c_noise",
            "material_id": "mat_noise",
            "title": "Botany",
            "content": "Urban trees and rainfall were observed in autumn parks.",
        },
    ]

    report = compare_context_selectors(queries, chunks, top_k=1, embedding_dim=16)

    assert report["schema_version"] == "tolf-context-selector-comparison/v1"
    assert report["input"]["external_api_calls"] == 0
    assert report["summary"]["queries_with_tolf_hits"] == 1
    assert report["summary"]["queries_with_empty_default"] == 0
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_overlap"] == 0
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_or_bridge_overlap"] == 0
    assert report["summary"]["tolf_hits_with_query_bridge_overlap"] == 0
    assert report["comparisons"][0]["default_top_ids"] == ["c_result"]
    assert report["comparisons"][0]["tolf_top_ids"] == ["c_result"]
    assert report["comparisons"][0]["overlap_at_top_k"] == 1.0
    assert report["comparisons"][0]["default_empty"] is False
    assert report["comparisons"][0]["tolf_empty"] is False
    assert report["comparisons"][0]["tolf_hits_without_query_overlap"] == 0
    assert report["comparisons"][0]["tolf_hits_without_query_or_bridge_overlap"] == 0
    assert report["comparisons"][0]["tolf_hits_with_query_bridge_overlap"] == 0
    assert report["comparisons"][0]["tolf_query_overlap_tokens"] == [["hardness", "laser", "power"]]


def test_compare_context_selectors_flags_tolf_hits_without_query_overlap() -> None:
    queries = [{"query_id": "q1", "query_text": "不存在的中文查询"}]
    chunks = [
        {
            "chunk_id": "c1",
            "content": "Laser power increased hardness to 280 HV.",
        }
    ]

    report = compare_context_selectors(queries, chunks, top_k=1, embedding_dim=16)

    assert report["summary"]["queries_with_empty_default"] == 1
    assert report["summary"]["queries_with_tolf_hits"] == 1
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_overlap"] == 1
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_or_bridge_overlap"] == 1
    assert report["summary"]["tolf_hits_without_query_overlap"] == 1
    assert report["summary"]["tolf_hits_without_query_or_bridge_overlap"] == 1
    assert report["summary"]["tolf_hits_with_query_bridge_overlap"] == 0
    assert report["comparisons"][0]["default_empty"] is True
    assert report["comparisons"][0]["tolf_empty"] is False
    assert report["comparisons"][0]["tolf_hits_without_query_overlap"] == 1
    assert report["comparisons"][0]["tolf_hits_without_query_or_bridge_overlap"] == 1
    assert report["comparisons"][0]["tolf_hits_with_query_bridge_overlap"] == 0


def test_compare_context_selectors_reports_query_bridge_overlap() -> None:
    queries = [{"query_id": "q1", "query_text": "激光焊接的最新研究进展"}]
    chunks = [
        {
            "chunk_id": "c1",
            "content": "Recent laser welding research reports melt pool stability and hardness changes.",
        }
    ]

    report = compare_context_selectors(queries, chunks, top_k=1, embedding_dim=16)

    comparison = report["comparisons"][0]
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_overlap"] == 1
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_or_bridge_overlap"] == 0
    assert report["summary"]["tolf_hits_without_query_overlap"] == 1
    assert report["summary"]["tolf_hits_without_query_or_bridge_overlap"] == 0
    assert report["summary"]["tolf_hits_with_query_bridge_overlap"] == 1
    assert comparison["tolf_query_overlap_tokens"] == [[]]
    assert comparison["tolf_hits_without_query_or_bridge_overlap"] == 0
    assert comparison["tolf_hits_with_query_bridge_overlap"] == 1
    hit_matches = {
        item["query_term"]: set(item["matched_terms"])
        for item in comparison["tolf_query_bridge_matches"][0]
    }
    assert {"laser", "welding", "laser welding"} <= hit_matches["激光焊接"]
    assert hit_matches["激光"] == {"laser"}
    assert "welding" in hit_matches["焊接"]
    assert "research" in hit_matches["研究进展"]
    assert hit_matches["最新"] == {"recent"}


def test_compare_context_selectors_rejects_invalid_args() -> None:
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        compare_context_selectors([], [], top_k=0)

    with pytest.raises(TypeError, match="queries must be a sequence"):
        compare_context_selectors("bad", [], top_k=1)  # type: ignore[arg-type]


def test_cli_writes_comparison_report(monkeypatch, tmp_path, capsys) -> None:
    queries_path = tmp_path / "queries.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    output_path = tmp_path / "report.json"
    queries_path.write_text('{"query_id":"q1","query_text":"laser hardness"}\n', encoding="utf-8")
    chunks_path.write_text(
        '{"chunk_id":"c1","content":"Laser hardness increased to 280 HV.","material_id":"m1"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "compare_tolf_context_selector.py",
            "--queries",
            str(queries_path),
            "--chunks",
            str(chunks_path),
            "--output",
            str(output_path),
            "--top-k",
            "1",
            "--embedding-dim",
            "16",
        ],
    )

    main()

    printed = json.loads(capsys.readouterr().out)
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert printed["status"] == "ok"
    assert printed["query_count"] == 1
    assert report["comparisons"][0]["overlap_ids"] == ["c1"]


def test_cli_stdout_remains_json_when_tolf_uses_small_corpus_fallback(
    monkeypatch, tmp_path, capsys
) -> None:
    queries_path = tmp_path / "queries.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    output_path = tmp_path / "report.json"
    queries_path.write_text('{"query_id":"q1","query_text":"不存在的中文查询"}\n', encoding="utf-8")
    chunks_path.write_text(
        '{"chunk_id":"c1","content":"Laser hardness increased to 280 HV.","material_id":"m1"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "compare_tolf_context_selector.py",
            "--queries",
            str(queries_path),
            "--chunks",
            str(chunks_path),
            "--output",
            str(output_path),
            "--top-k",
            "1",
            "--embedding-dim",
            "16",
        ],
    )

    main()

    stdout = capsys.readouterr().out.strip()
    printed = json.loads(stdout)
    assert printed["status"] == "ok"
