from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "gateb_phase_b_pool_export.py"


def _load_module():
    if not MODULE_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("gateb_phase_b_pool_export", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def test_merge_query_candidates_deduplicates_docs_and_preserves_source_labels() -> None:
    module = _load_module()
    assert module is not None, "implement gateb_phase_b_pool_export.py"

    doc_lookup = module.build_doc_lookup(
        [
            {
                "material_id": "mat-1",
                "chunk_id": "mat-1_chunk_0",
                "title": "Paper One",
                "content": "bm25 preview for mat-1",
            },
            {
                "material_id": "mat-2",
                "chunk_id": "mat-2_chunk_0",
                "title": "Paper Two",
                "content": "bm25 preview for mat-2",
            },
            {
                "material_id": "mat-3",
                "chunk_id": "mat-3_chunk_0",
                "title": "Paper Three",
                "content": "evidence preview for mat-3",
            },
            {
                "material_id": "mat-4",
                "chunk_id": "mat-4_chunk_0",
                "title": "Paper Four",
                "content": "rrf preview for mat-4",
            },
        ]
    )

    pool_record = module.merge_query_candidates(
        goldset_record={
            "query_id": "q_gateb_0001",
            "query_text": "激光焊接的最新研究进展",
            "original_query_id": "q_0001",
        },
        original_query={
            "query_id": "q_0001",
            "evidence_set": [{"doc_id": "mat-1"}, {"doc_id": "mat-3"}],
        },
        source_hits={
            "bm25": [
                {
                    "material_id": "mat-1",
                    "chunk_id": "mat-1_chunk_2",
                    "title": "Paper One",
                    "content": "bm25 hit for mat-1",
                },
                {
                    "material_id": "mat-2",
                    "chunk_id": "mat-2_chunk_2",
                    "title": "Paper Two",
                    "content": "bm25 hit for mat-2",
                },
            ],
            "dense": [
                {
                    "material_id": "mat-2",
                    "chunk_id": "mat-2_chunk_9",
                    "title": "Paper Two",
                    "content": "dense hit for mat-2",
                },
                {
                    "material_id": "mat-3",
                    "chunk_id": "mat-3_chunk_7",
                    "title": "Paper Three",
                    "content": "dense hit for mat-3",
                },
            ],
            "graph": [
                {
                    "material_id": "mat-2",
                    "chunk_id": "mat-2_chunk_5",
                    "title": "Paper Two",
                    "content": "graph hit for mat-2",
                }
            ],
            "rrf": [
                {
                    "material_id": "mat-2",
                    "chunk_id": "mat-2_chunk_9",
                    "title": "Paper Two",
                    "content": "rrf hit for mat-2",
                },
                {
                    "material_id": "mat-4",
                    "chunk_id": "mat-4_chunk_1",
                    "title": "Paper Four",
                    "content": "rrf hit for mat-4",
                },
            ],
            "rerank": [
                {
                    "material_id": "mat-4",
                    "chunk_id": "mat-4_chunk_1",
                    "title": "Paper Four",
                    "content": "rerank hit for mat-4",
                },
                {
                    "material_id": "mat-1",
                    "chunk_id": "mat-1_chunk_2",
                    "title": "Paper One",
                    "content": "rerank hit for mat-1",
                },
            ],
        },
        doc_lookup=doc_lookup,
    )

    by_doc_id = {candidate["doc_id"]: candidate for candidate in pool_record["candidates"]}

    assert set(by_doc_id) == {"mat-1", "mat-2", "mat-3", "mat-4"}
    assert by_doc_id["mat-1"]["source_labels"] == ["bm25", "rerank", "evidence_set"]
    assert by_doc_id["mat-2"]["source_labels"] == ["bm25", "dense", "graph", "rrf"]
    assert by_doc_id["mat-3"]["source_labels"] == ["dense", "evidence_set"]
    assert by_doc_id["mat-4"]["source_labels"] == ["rrf", "rerank"]
    assert by_doc_id["mat-3"]["title"] == "Paper Three"
    assert by_doc_id["mat-3"]["content_preview"].startswith("evidence preview")


def test_build_annotation_record_keeps_only_annotation_fields() -> None:
    module = _load_module()
    assert module is not None, "implement gateb_phase_b_pool_export.py"

    record = module.build_annotation_record(
        {
            "query_id": "q_gateb_0001",
            "query_text": "激光焊接的最新研究进展",
            "original_query_id": "q_0001",
            "source_stratum": "S2",
            "source_template_id": "simple:0",
            "pool_stats": {"candidate_count": 2},
            "source_doc_ids": {"bm25": ["mat-1"], "dense": ["mat-2"]},
            "candidates": [
                {
                    "doc_id": "mat-1",
                    "title": "Paper One",
                    "content_preview": "preview one",
                    "source_labels": ["bm25", "evidence_set"],
                    "source_hint": "bm25+evidence_set",
                },
                {
                    "doc_id": "mat-2",
                    "title": "Paper Two",
                    "content_preview": "preview two",
                    "source_labels": ["dense"],
                    "source_hint": "dense",
                },
            ],
        }
    )

    assert record["query_id"] == "q_gateb_0001"
    assert record["pool_size"] == 2
    assert "source_doc_ids" not in record
    assert record["candidates"][0]["source_hint"] == "bm25+evidence_set"
    assert record["candidates"][1]["source_labels"] == ["dense"]


def test_export_phase_b_pools_writes_separate_artifacts_and_keeps_goldset_unchanged(
    tmp_path: Path,
) -> None:
    module = _load_module()
    assert module is not None, "implement gateb_phase_b_pool_export.py"

    goldset_path = tmp_path / "gateb_goldset.jsonl"
    eval_queries_path = tmp_path / "eval_queries_v2.1.jsonl"
    pool_output_path = tmp_path / "gateb_phase_b_pools.jsonl"
    annotation_output_path = tmp_path / "gateb_phase_b_annotation_input.jsonl"

    goldset_records = [
        {
            "query_id": "q_gateb_0001",
            "query_text": "激光焊接的最新研究进展",
            "original_query_id": "q_0001",
            "source_stratum": "S2",
            "source_template_id": "simple:0",
            "qrels": [],
            "annotator_id": "phase_a_scaffold",
            "no_gold": True,
            "created_at": "2026-04-22T00:00:00+00:00",
            "schema_version": "1",
        }
    ]
    goldset_before = (
        "\n".join(json.dumps(record, ensure_ascii=False) for record in goldset_records) + "\n"
    )
    goldset_path.write_text(goldset_before, encoding="utf-8")

    _write_jsonl(
        eval_queries_path,
        [
            {
                "query_id": "q_0001",
                "query_text": "激光焊接的最新研究进展",
                "evidence_set": [{"doc_id": "mat-1"}],
            }
        ],
    )

    async def _fake_collect(query_text: str, *, top_k: int, **_kwargs):
        assert query_text == "激光焊接的最新研究进展"
        assert top_k == 10
        return {
            "bm25": [{"material_id": "mat-1", "chunk_id": "mat-1_chunk_0", "title": "Paper One", "content": "bm25 preview"}],
            "dense": [{"material_id": "mat-2", "chunk_id": "mat-2_chunk_0", "title": "Paper Two", "content": "dense preview"}],
            "graph": [],
            "rrf": [{"material_id": "mat-2", "chunk_id": "mat-2_chunk_0", "title": "Paper Two", "content": "rrf preview"}],
            "rerank": [{"material_id": "mat-1", "chunk_id": "mat-1_chunk_0", "title": "Paper One", "content": "rerank preview"}],
        }

    export_result = module.export_phase_b_pools(
        goldset_path=goldset_path,
        eval_queries_path=eval_queries_path,
        pool_output_path=pool_output_path,
        annotation_output_path=annotation_output_path,
        corpus={"chunks": []},
        retrieval_collector=_fake_collect,
    )

    assert export_result["query_count"] == 1
    assert pool_output_path.exists()
    assert annotation_output_path.exists()
    assert goldset_path.read_text(encoding="utf-8") == goldset_before

    pool_records = [
        json.loads(line)
        for line in pool_output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    annotation_records = [
        json.loads(line)
        for line in annotation_output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(pool_records) == 1
    assert len(annotation_records) == 1
    assert pool_records[0]["source_doc_ids"]["evidence_set"] == ["mat-1"]
    assert annotation_records[0]["pool_size"] == 2
    assert {candidate["doc_id"] for candidate in annotation_records[0]["candidates"]} == {
        "mat-1",
        "mat-2",
    }
