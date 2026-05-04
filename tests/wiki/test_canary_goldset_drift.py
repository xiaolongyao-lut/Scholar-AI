from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.eval.wiki_canary_goldset_drift import (
    CanaryGoldsetDriftError,
    build_goldset_drift_report,
    build_goldset_update_proposal,
    build_material_catalog,
    build_title_groups,
    load_chunk_store_chunks,
    write_report,
)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _write_project(
    root: Path,
    *,
    project_id: str,
    material_id: str,
    title: str,
    chunk_count: int = 1,
) -> None:
    project_dir = root / project_id
    rows = [
        {
            "chunk_id": f"{material_id}_chunk_{index}",
            "material_id": material_id,
            "title": title,
            "content": f"[文献: {title}] chunk {index}",
        }
        for index in range(chunk_count)
    ]
    _write_jsonl(project_dir / f"{material_id}.jsonl", rows)
    _write_json(
        project_dir / "manifest.json",
        {
            "version": 2,
            "materials": {
                material_id: {
                    "relative_path": f"{material_id}.jsonl",
                    "total_chunks": chunk_count,
                }
            },
        },
    )


def test_build_material_catalog_reports_duplicate_title_groups(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    _write_project(root, project_id="proj-a", material_id="mat_a", title="Same Paper.pdf")
    _write_project(root, project_id="proj-b", material_id="mat_b", title="Same Paper.pdf")

    chunks = load_chunk_store_chunks(root)
    catalog = build_material_catalog(chunks)
    title_groups = build_title_groups(catalog)

    assert sorted(catalog) == ["mat_a", "mat_b"]
    assert title_groups == [
        {
            "normalized_title": "same paper",
            "material_ids": ["mat_a", "mat_b"],
            "titles": ["Same Paper.pdf"],
        }
    ]


def test_build_goldset_drift_report_labels_buried_and_same_title_cases(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    _write_project(
        root,
        project_id="gold",
        material_id="mat_gold",
        title="Man 等 - 2011 - Laser diffusion nitriding of Ti-6Al-4V.pdf",
        chunk_count=2,
    )
    _write_project(
        root,
        project_id="competing",
        material_id="mat_competing",
        title="刘浩东和戴京涛 - 2022 - 激光焊接技术的应用研究进展与分析.pdf",
        chunk_count=5,
    )
    _write_project(root, project_id="duplicate", material_id="mat_duplicate", title="Gold Paper.pdf")

    queries = _write_jsonl(
        tmp_path / "queries.jsonl",
        [
            {
                "query_id": "q_0001",
                "query_text": "激光焊接的最新研究进展",
                "difficulty_level": "simple",
                "source_title": "Man 等 - 2011 - Laser diffusion nitriding of Ti-6Al-4V.pdf",
                "evidence_set": [{"doc_id": "mat_gold"}],
            },
            {
                "query_id": "q_0002",
                "query_text": "重复论文材料",
                "difficulty_level": "simple",
                "source_title": "Gold Paper.pdf",
                "evidence_set": [{"doc_id": "mat_gold"}],
            },
        ],
    )
    trace = _write_jsonl(
        tmp_path / "trace.jsonl",
        [
            {
                "query_id": "q_0001",
                "top_k": 5,
                "expected_doc_ids": ["mat_gold"],
                "returned_hits": [
                    {"rank": 1, "chunk_id": "mat_competing_chunk_0", "material_id": "mat_competing"},
                    {"rank": 2, "chunk_id": "mat_competing_chunk_1", "material_id": "mat_competing"},
                    {"rank": 3, "chunk_id": "mat_competing_chunk_2", "material_id": "mat_competing"},
                    {"rank": 4, "chunk_id": "mat_competing_chunk_3", "material_id": "mat_competing"},
                    {"rank": 5, "chunk_id": "mat_competing_chunk_4", "material_id": "mat_competing"},
                    {"rank": 6, "chunk_id": "mat_gold_chunk_0", "material_id": "mat_gold"},
                ],
            },
            {
                "query_id": "q_0002",
                "top_k": 5,
                "expected_doc_ids": ["mat_gold"],
                "returned_hits": [
                    {"rank": 1, "chunk_id": "mat_duplicate_chunk_0", "material_id": "mat_duplicate"},
                    {"rank": 2, "chunk_id": "mat_gold_chunk_0", "material_id": "mat_gold"},
                ],
            },
        ],
    )

    report = build_goldset_drift_report(
        queries_path=queries,
        trace_path=trace,
        chunk_store_dir=root,
    )

    assert report["status"] == "DRIFT_DETECTED"
    assert report["summary"]["total_queries"] == 2
    assert report["summary"]["hit_top_k_count"] == 1
    first = report["query_records"][0]
    assert first["first_gold_rank"] == 6
    assert "gold_buried_after_top_k" in first["drift_labels"]
    assert "non_gold_top_k_dominance" in first["drift_labels"]
    assert "broad_query_competing_topic" in first["drift_labels"]
    second = report["query_records"][1]
    assert second["first_gold_rank"] == 2
    assert second["same_title_alternate_material_ids"] == ["mat_duplicate"]
    assert "same_title_alternate_in_top_k" in second["drift_labels"]


def test_build_goldset_update_proposal_is_no_write_and_simulates_candidates(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    _write_project(root, project_id="gold", material_id="mat_gold", title="Gold Paper.pdf")
    _write_project(root, project_id="alt", material_id="mat_alt", title="Better Topic Paper.pdf")
    queries = _write_jsonl(
        tmp_path / "queries.jsonl",
        [
            {
                "query_id": "q_1",
                "query_text": "激光焊接的最新研究进展",
                "source_title": "Gold Paper.pdf",
                "evidence_set": [{"doc_id": "mat_gold"}],
            }
        ],
    )
    trace = _write_jsonl(
        tmp_path / "trace.jsonl",
        [
            {
                "query_id": "q_1",
                "top_k": 5,
                "expected_doc_ids": ["mat_gold"],
                "returned_hits": [
                    {"rank": 1, "chunk_id": "mat_alt_chunk_0", "material_id": "mat_alt"},
                    {"rank": 6, "chunk_id": "mat_gold_chunk_0", "material_id": "mat_gold"},
                ],
            }
        ],
    )
    report = build_goldset_drift_report(queries_path=queries, trace_path=trace, chunk_store_dir=root)

    proposal = build_goldset_update_proposal(report)

    assert proposal["mode"] == "read_only_goldset_proposal_no_file_mutation"
    assert proposal["guardrails"]["does_not_modify_queries_qrels_goldset_or_canary30"] is True
    assert proposal["summary"]["current_hit_top_k_count"] == 0
    assert proposal["summary"]["simulated_hit_top_k_count_if_all_candidates_accepted"] == 1
    assert proposal["actions"][0]["candidate_alternates"][0]["material_id"] == "mat_alt"
    assert proposal["actions"][0]["review_required"] is True


def test_load_chunk_store_chunks_rejects_manifest_path_escape(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    _write_json(
        project_dir / "manifest.json",
        {"version": 2, "materials": {"mat": {"relative_path": "../outside.jsonl"}}},
    )

    with pytest.raises(CanaryGoldsetDriftError, match="escapes"):
        load_chunk_store_chunks(project_dir)


def test_write_report_sorts_keys(tmp_path: Path) -> None:
    output = write_report({"b": 2, "a": 1}, tmp_path / "report.json")

    assert output.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": 2\n}\n'
