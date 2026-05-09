from __future__ import annotations

import json
from pathlib import Path

from contextual_chunker import CONTEXTUAL_SUMMARY_FIELDS


def _write_chunk_store(project_dir: Path, materials: dict[str, list[dict[str, object]]]) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    manifest_materials: dict[str, dict[str, object]] = {}
    for material_id, chunks in materials.items():
        relative_path = f"{material_id}.jsonl"
        with (project_dir / relative_path).open("w", encoding="utf-8") as handle:
            for chunk in chunks:
                handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        manifest_materials[material_id] = {
            "relative_path": relative_path,
            "sha256": material_id,
            "total_chunks": len(chunks),
        }
    (project_dir / "manifest.json").write_text(
        json.dumps({"version": 2, "materials": manifest_materials}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_summary(summaries_root: Path, project_id: str, material_id: str) -> None:
    payload = {
        "topic": f"topic-{material_id}",
        "objective": f"objective-{material_id}",
        "material_system": f"system-{material_id}",
        "process_method": f"method-{material_id}",
        "key_metrics": f"metric-{material_id}",
        "main_conclusion": f"conclusion-{material_id}",
        "keywords": [f"kw-{material_id}", "shared"],
    }
    path = summaries_root / project_id / f"{material_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_validate_project_contextual_coverage_passes_when_all_summaries_exist(tmp_path) -> None:
    from scripts import validate_contextual_miss as script

    project_id = "demo"
    _write_chunk_store(
        tmp_path / "output" / "chunk_store" / project_id,
        {
            "m1": [{"material_id": "m1", "content": "alpha", "chunk_id": "c1"}],
            "m2": [{"material_id": "m2", "content": "beta", "chunk_id": "c2"}],
        },
    )
    _write_summary(tmp_path / "output" / "contextual_summaries", project_id, "m1")
    _write_summary(tmp_path / "output" / "contextual_summaries", project_id, "m2")

    report = script.validate_project_contextual_coverage(
        project_id,
        chunk_store_root=tmp_path / "output" / "chunk_store",
        summaries_root=tmp_path / "output" / "contextual_summaries",
    )

    assert report["status"] == "pass"
    assert report["material_count"] == 2
    assert report["summary_artifact_count"] == 2
    assert report["validation_miss_count"] == 0
    assert report["missing_summary_material_ids"] == []
    assert report["invalid_summary_material_ids"] == []


def test_validate_project_contextual_coverage_detects_missing_summary(tmp_path) -> None:
    from scripts import validate_contextual_miss as script

    project_id = "demo"
    _write_chunk_store(
        tmp_path / "output" / "chunk_store" / project_id,
        {
            "m1": [{"material_id": "m1", "content": "alpha", "chunk_id": "c1"}],
        },
    )

    report = script.validate_project_contextual_coverage(
        project_id,
        chunk_store_root=tmp_path / "output" / "chunk_store",
        summaries_root=tmp_path / "output" / "contextual_summaries",
    )

    assert report["status"] == "fail"
    assert report["missing_summary_material_ids"] == ["m1"]
    assert report["summary_artifact_count"] == 0
    assert report["validation_miss_count"] == 1
    assert report["validation_miss_rows"][0]["project_id"] == project_id
    assert report["validation_miss_rows"][0]["material_id"] == "m1"


def test_archive_and_reset_live_miss_log_preserves_history(tmp_path) -> None:
    from scripts import validate_contextual_miss as script

    live_log = tmp_path / "output" / "contextual_miss.jsonl"
    live_log.parent.mkdir(parents=True, exist_ok=True)
    original = (
        json.dumps({"ts": "2026-04-30T00:00:00+00:00", "project_id": "", "material_id": "m1"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"ts": "2026-04-30T00:01:00+00:00", "project_id": "demo", "material_id": "m2"}, ensure_ascii=False)
        + "\n"
    )
    live_log.write_text(original, encoding="utf-8")

    result = script.archive_and_reset_live_miss_log(
        live_log,
        archive_dir=tmp_path / "output" / "contextual_miss_archive",
    )

    archive_path = Path(result["archive_path"])
    assert result["row_count"] == 2
    assert result["blank_project_count"] == 1
    assert archive_path.read_text(encoding="utf-8") == original
    assert live_log.read_text(encoding="utf-8") == ""
    assert result["status"] == "archived-and-reset"


def test_summary_keys_fixture_matches_contextual_contract() -> None:
    assert CONTEXTUAL_SUMMARY_FIELDS == (
        "topic",
        "objective",
        "material_system",
        "process_method",
        "key_metrics",
        "main_conclusion",
        "keywords",
    )
