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
    assert report["summary"]["queries_with_empty_bilingual_default"] == 0
    assert report["summary"]["queries_where_bilingual_default_recovers_empty_default"] == 0
    assert report["summary"]["mean_bilingual_control_overlap_at_top_k"] == 1.0
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_overlap"] == 0
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_or_bridge_overlap"] == 0
    assert report["summary"]["tolf_hits_with_query_bridge_overlap"] == 0
    assert report["comparisons"][0]["default_top_ids"] == ["c_result"]
    assert report["comparisons"][0]["bilingual_default_top_ids"] == ["c_result"]
    assert report["comparisons"][0]["bilingual_query_terms"] == []
    assert report["comparisons"][0]["tolf_top_ids"] == ["c_result"]
    assert report["comparisons"][0]["overlap_at_top_k"] == 1.0
    assert report["comparisons"][0]["bilingual_control_overlap_at_top_k"] == 1.0
    assert report["comparisons"][0]["default_empty"] is False
    assert report["comparisons"][0]["bilingual_default_empty"] is False
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
    assert report["summary"]["queries_with_empty_bilingual_default"] == 1
    assert report["summary"]["queries_where_bilingual_default_recovers_empty_default"] == 0
    assert report["summary"]["queries_with_tolf_hits"] == 1
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_overlap"] == 1
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_or_bridge_overlap"] == 1
    assert report["summary"]["tolf_hits_without_query_overlap"] == 1
    assert report["summary"]["tolf_hits_without_query_or_bridge_overlap"] == 1
    assert report["summary"]["tolf_hits_with_query_bridge_overlap"] == 0
    assert report["comparisons"][0]["default_empty"] is True
    assert report["comparisons"][0]["bilingual_default_empty"] is True
    assert report["comparisons"][0]["bilingual_query_terms"] == []
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
    assert report["summary"]["queries_with_empty_default"] == 1
    assert report["summary"]["queries_with_empty_bilingual_default"] == 0
    assert report["summary"]["queries_where_bilingual_default_recovers_empty_default"] == 1
    assert report["summary"]["mean_bilingual_control_overlap_at_top_k"] == 1.0
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_overlap"] == 1
    assert report["summary"]["queries_where_all_tolf_hits_lack_query_or_bridge_overlap"] == 0
    assert report["summary"]["tolf_hits_without_query_overlap"] == 1
    assert report["summary"]["tolf_hits_without_query_or_bridge_overlap"] == 0
    assert report["summary"]["tolf_hits_with_query_bridge_overlap"] == 1
    assert comparison["tolf_query_overlap_tokens"] == [[]]
    assert comparison["default_top_ids"] == []
    assert comparison["bilingual_default_top_ids"] == ["c1"]
    assert {"laser", "welding", "laser welding", "recent"} <= set(comparison["bilingual_query_terms"])
    assert comparison["bilingual_control_overlap_ids"] == ["c1"]
    assert comparison["bilingual_control_overlap_at_top_k"] == 1.0
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


def test_compare_context_selectors_keeps_bilingual_control_separate_from_raw_default() -> None:
    queries = [{"query_id": "q1", "query_text": "力学性能"}]
    chunks = [
        {
            "chunk_id": "mechanical",
            "content": "Mechanical properties include tensile strength and hardness.",
        },
        {
            "chunk_id": "noise",
            "content": "The manuscript describes microscope calibration.",
        },
    ]

    report = compare_context_selectors(queries, chunks, top_k=1, embedding_dim=16)
    comparison = report["comparisons"][0]

    assert comparison["default_empty"] is True
    assert comparison["bilingual_default_empty"] is False
    assert comparison["default_top_ids"] == []
    assert comparison["bilingual_default_top_ids"] == ["mechanical"]
    assert "mechanical properties" in comparison["bilingual_query_terms"]
    assert report["summary"]["queries_where_bilingual_default_recovers_empty_default"] == 1


def test_compare_context_selectors_can_include_inspection_snapshots() -> None:
    queries = [{"query_id": "q1", "query_text": "激光焊接"}]
    chunks = [
        {
            "chunk_id": "laser",
            "material_id": "paper-1",
            "title": "Laser Welding Paper",
            "section_title": "Results",
            "page": 3,
            "content": "Laser welding improved joint stability and reduced porosity in the weld zone.",
        }
    ]

    report = compare_context_selectors(
        queries,
        chunks,
        top_k=1,
        embedding_dim=16,
        include_inspection=True,
        inspection_snippet_chars=48,
    )

    inspection = report["comparisons"][0]["inspection"]
    assert inspection["raw_default_hits"] == []
    assert inspection["bilingual_default_hits"][0]["chunk_id"] == "laser"
    assert inspection["bilingual_default_hits"][0]["material_id"] == "paper-1"
    assert inspection["bilingual_default_hits"][0]["section_title"] == "Results"
    assert inspection["bilingual_default_hits"][0]["page"] == 3
    assert inspection["bilingual_default_hits"][0]["snippet"].endswith("…")
    assert inspection["tolf_hits"][0]["query_bridge_matches"]
    assert "snippet" in inspection["tolf_hits"][0]


def test_compare_context_selectors_rejects_invalid_args() -> None:
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        compare_context_selectors([], [], top_k=0)

    with pytest.raises(TypeError, match="queries must be a sequence"):
        compare_context_selectors("bad", [], top_k=1)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="inspection_snippet_chars must be a positive integer"):
        compare_context_selectors([], [], inspection_snippet_chars=0)


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
            "--include-inspection",
            "--inspection-snippet-chars",
            "80",
        ],
    )

    main()

    printed = json.loads(capsys.readouterr().out)
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert printed["status"] == "ok"
    assert printed["query_count"] == 1
    assert report["comparisons"][0]["overlap_ids"] == ["c1"]
    assert report["comparisons"][0]["inspection"]["raw_default_hits"][0]["chunk_id"] == "c1"


def test_cli_writes_review_markdown_when_inspection_enabled(monkeypatch, tmp_path, capsys) -> None:
    queries_path = tmp_path / "queries.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    output_path = tmp_path / "report.json"
    review_path = tmp_path / "review.md"
    queries_path.write_text('{"query_id":"q1","query_text":"激光焊接"}\n', encoding="utf-8")
    chunks_path.write_text(
        '{"chunk_id":"c1","content":"Laser welding improved joint stability.","material_id":"m1","title":"Paper"}\n',
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
            "--include-inspection",
            "--review-markdown-output",
            str(review_path),
            "--review-max-queries",
            "1",
        ],
    )

    main()

    printed = json.loads(capsys.readouterr().out)
    markdown = review_path.read_text(encoding="utf-8")
    assert printed["status"] == "ok"
    assert "# TOLF Comparison Review Packet" in markdown
    assert "## q1: 激光焊接" in markdown
    assert "| raw_default | unknown |  |" in markdown
    assert "| `queries_with_empty_default` | `1` |" in markdown
    assert "| `mean_bilingual_control_overlap_at_top_k` | `1.0` |" in markdown
    assert "### Bilingual Default Hits" in markdown
    assert "`c1`" in markdown


def test_cli_writes_judgment_template_when_inspection_enabled(monkeypatch, tmp_path, capsys) -> None:
    queries_path = tmp_path / "queries.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    output_path = tmp_path / "report.json"
    judgment_path = tmp_path / "judgments.jsonl"
    queries_path.write_text('{"query_id":"q1","query_text":"激光焊接"}\n', encoding="utf-8")
    chunks_path.write_text(
        '{"chunk_id":"c1","content":"Laser welding improved joint stability.","material_id":"m1","title":"Paper"}\n',
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
            "--include-inspection",
            "--judgment-template-output",
            str(judgment_path),
            "--judgment-max-queries",
            "1",
        ],
    )

    main()

    printed = json.loads(capsys.readouterr().out)
    rows = [json.loads(line) for line in judgment_path.read_text(encoding="utf-8").splitlines()]
    assert printed["status"] == "ok"
    assert {row["arm"] for row in rows} == {"bilingual_default", "tolf"}
    assert all(row["schema_version"] == "tolf-comparison-judgment/v1" for row in rows)
    assert all(row["judgment"] == "unknown" for row in rows)
    assert rows[0]["allowed_judgments"] == ["relevant", "partial", "offtopic", "unknown"]
    assert rows[0]["query_id"] == "q1"
    assert rows[0]["chunk_id"] == "c1"


def test_cli_rejects_review_markdown_without_inspection(monkeypatch, tmp_path) -> None:
    queries_path = tmp_path / "queries.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    output_path = tmp_path / "report.json"
    review_path = tmp_path / "review.md"
    queries_path.write_text('{"query_id":"q1","query_text":"laser"}\n', encoding="utf-8")
    chunks_path.write_text('{"chunk_id":"c1","content":"Laser welding."}\n', encoding="utf-8")
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
            "--review-markdown-output",
            str(review_path),
        ],
    )

    with pytest.raises(SystemExit):
        main()


def test_cli_rejects_judgment_template_without_inspection(monkeypatch, tmp_path) -> None:
    queries_path = tmp_path / "queries.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    output_path = tmp_path / "report.json"
    judgment_path = tmp_path / "judgments.jsonl"
    queries_path.write_text('{"query_id":"q1","query_text":"laser"}\n', encoding="utf-8")
    chunks_path.write_text('{"chunk_id":"c1","content":"Laser welding."}\n', encoding="utf-8")
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
            "--judgment-template-output",
            str(judgment_path),
        ],
    )

    with pytest.raises(SystemExit):
        main()


def test_cli_summarizes_filled_judgment_jsonl(monkeypatch, tmp_path, capsys) -> None:
    judgment_path = tmp_path / "filled.jsonl"
    summary_path = tmp_path / "summary.json"
    judgment_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema_version": "tolf-comparison-judgment/v1",
                        "query_id": "q1",
                        "query_text": "激光焊接",
                        "arm": "bilingual_default",
                        "rank": 1,
                        "chunk_id": "c1",
                        "judgment": "relevant",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "schema_version": "tolf-comparison-judgment/v1",
                        "query_id": "q1",
                        "query_text": "激光焊接",
                        "arm": "tolf",
                        "rank": 1,
                        "chunk_id": "c2",
                        "judgment": "partial",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "schema_version": "tolf-comparison-judgment/v1",
                        "query_id": "q2",
                        "query_text": "力学性能",
                        "arm": "tolf",
                        "rank": 1,
                        "chunk_id": "c3",
                        "judgment": "unknown",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "compare_tolf_context_selector.py",
            "--queries",
            "unused_queries.jsonl",
            "--chunks",
            "unused_chunks.jsonl",
            "--output",
            "unused_report.json",
            "--judgment-input",
            str(judgment_path),
            "--judgment-summary-output",
            str(summary_path),
        ],
    )

    main()

    printed = json.loads(capsys.readouterr().out)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert printed["status"] == "ok"
    assert printed["row_count"] == 3
    assert summary["schema_version"] == "tolf-comparison-judgment-summary/v1"
    assert summary["row_count"] == 3
    assert summary["reviewed_count"] == 2
    assert summary["unknown_count"] == 1
    assert summary["invalid_count"] == 0
    assert summary["by_arm"]["bilingual_default"]["relevant"] == 1
    assert summary["by_arm"]["tolf"]["partial"] == 1
    assert summary["by_arm"]["tolf"]["unknown"] == 1
    assert summary["by_query"]["q1"]["tolf"]["partial"] == 1


def test_cli_requires_judgment_summary_pair(monkeypatch, tmp_path) -> None:
    judgment_path = tmp_path / "filled.jsonl"
    judgment_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "compare_tolf_context_selector.py",
            "--queries",
            "unused_queries.jsonl",
            "--chunks",
            "unused_chunks.jsonl",
            "--output",
            "unused_report.json",
            "--judgment-input",
            str(judgment_path),
        ],
    )

    with pytest.raises(SystemExit):
        main()


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
