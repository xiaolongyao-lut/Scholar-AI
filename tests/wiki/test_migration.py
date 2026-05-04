from __future__ import annotations

import json
from pathlib import Path

import pytest

from literature_assistant.core.wiki.migration import (
    evidence_refs_migration_dry_run,
    evidence_refs_migration_dry_run_from_jsonl,
)
from literature_assistant.core.wiki.source_registry import (
    ChunkInput,
    SourceRecord,
    WikiRegistry,
    utc_now_iso,
)


def test_evidence_refs_migration_dry_run_reports_would_import_without_writes() -> None:
    refs = [
        {
            "chunk_id": "mat-a_chunk_0",
            "material_id": "mat-a",
            "text": "Laser welding improves joint stability.",
            "title": "Laser Welding Paper",
            "page": 3,
        }
    ]

    report = evidence_refs_migration_dry_run(refs)

    payload = report.to_dict()
    assert payload["ok"] is True
    assert payload["would_write"] is False
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["source_id"] == "rag_evidence:mat-a"
    assert payload["candidates"][0]["chunk_id"] == "mat-a_chunk_0"
    assert payload["candidates"][0]["has_text"] is True
    assert payload["candidates"][0]["text_length"] == len("Laser welding improves joint stability.")


def test_evidence_refs_migration_dry_run_deduplicates_and_counts_registered_chunks(tmp_path: Path) -> None:
    registry = WikiRegistry(tmp_path / "wiki.db")
    registry.upsert_source(
        SourceRecord(
            source_id="rag_evidence:mat-a",
            source_type="rag_evidence",
            title="Mat A",
            source_hash="source-hash-a",
            source_path=Path("mat-a"),
        ),
        now_iso=utc_now_iso(),
    )
    registry.register_chunks(
        "rag_evidence:mat-a",
        "source-hash-a",
        [ChunkInput(text="registered chunk", chunk_index=0)],
        now_iso=utc_now_iso(),
    )
    chunk_id = registry.get_chunks_by_source("rag_evidence:mat-a")[0]["chunk_id"]
    refs = [
        {"chunk_id": chunk_id, "material_id": "mat-a", "text": "registered chunk"},
        {"chunk_id": chunk_id, "material_id": "mat-a", "text": "duplicate chunk"},
    ]

    report = evidence_refs_migration_dry_run(refs, registry=registry)

    assert report.candidate_count == 1
    assert report.duplicate_count == 1
    assert report.already_registered_count == 1
    assert report.skipped[0]["reason"] == "duplicate"


def test_evidence_refs_migration_dry_run_from_jsonl_accepts_nested_evidence_refs(tmp_path: Path) -> None:
    input_path = tmp_path / "refs.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "query": "laser",
                "evidence_refs": [
                    {
                        "chunk_id": "c1",
                        "material_id": "m1",
                        "compressed_text": "compressed evidence",
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = evidence_refs_migration_dry_run_from_jsonl(input_path)

    assert report.ok is True
    assert report.candidate_count == 1
    assert report.candidates[0].source_id == "rag_evidence:m1"


def test_evidence_refs_migration_dry_run_from_jsonl_reports_invalid_lines(tmp_path: Path) -> None:
    input_path = tmp_path / "refs.jsonl"
    input_path.write_text("{invalid json}\n[]\n", encoding="utf-8")

    report = evidence_refs_migration_dry_run_from_jsonl(input_path)

    assert report.ok is False
    assert report.candidate_count == 0
    assert report.skipped_count == 2
    assert {item["reason"] for item in report.skipped} == {"invalid_json", "payload_not_a_mapping"}


def test_evidence_refs_migration_dry_run_rejects_bad_inputs() -> None:
    with pytest.raises(TypeError, match="iterable"):
        evidence_refs_migration_dry_run("not-jsonl")

    with pytest.raises(ValueError, match="max_candidates"):
        evidence_refs_migration_dry_run([], max_candidates=0)
