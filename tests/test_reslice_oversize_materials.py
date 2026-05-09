from __future__ import annotations

import json
from pathlib import Path

import pytest

from routers import resources_router as rr
from scripts.reslice_oversize_materials import reslice_from_report
from scripts.scan_oversize_chunks import build_report


@pytest.fixture
def tmp_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    def fake_resolve(_project_id: str) -> tuple[Path, Path]:
        return tmp_path, tmp_path

    monkeypatch.setattr(rr, "_resolve_data_dir", fake_resolve)
    return tmp_path


def _write_doc_store(root: Path) -> None:
    payload = {
        "mat-oversize": {
            "title": "Oversize Notes.txt",
            "content": "A" * 6001,
        },
        "mat-safe": {
            "title": "Safe Notes.txt",
            "content": "short content",
        },
    }
    (root / "proj.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_legacy_chunk_store(root: Path) -> None:
    payload = {
        "mat-oversize": [
            {
                "chunk_id": "mat-oversize_chunk_0",
                "material_id": "mat-oversize",
                "title": "Oversize Notes.txt",
                "content": "A" * 6001,
                "char_count": 6001,
            }
        ],
        "mat-safe": [
            {
                "chunk_id": "mat-safe_chunk_0",
                "material_id": "mat-safe",
                "title": "Safe Notes.txt",
                "content": "short content",
                "char_count": 13,
            }
        ],
    }
    (root / "proj_chunks.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_formula_doc_store(root: Path) -> None:
    payload = {
        "mat-oversize": {
            "title": "Formula Notes.txt",
            "content": ("x = y + z\n" * 900).strip(),
        }
    }
    (root / "proj.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_report(root: Path) -> Path:
    report_path = root / "oversize_materials_report.json"
    report = {
        "root": str(root),
        "materials": [
            {
                "project_id": "proj",
                "material_id": "mat-oversize",
                "oversize_chunk_count": 1,
                "max_char": 6001,
                "max_token": 42,
                "source_path": "papers/oversize.txt",
            }
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def _write_multi_material_report(root: Path, material_ids: list[str]) -> Path:
    report_path = root / "oversize_materials_report.json"
    report = {
        "root": str(root),
        "materials": [
            {
                "project_id": "proj",
                "material_id": material_id,
                "oversize_chunk_count": 1,
                "max_char": 6001,
                "max_token": 42,
                "source_path": f"papers/{material_id}.txt",
            }
            for material_id in material_ids
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def test_reslice_from_report_only_updates_flagged_material_and_marks_manifest(tmp_project: Path) -> None:
    _write_doc_store(tmp_project)
    _write_legacy_chunk_store(tmp_project)
    report_path = _write_report(tmp_project)

    summary = reslice_from_report(report_path=report_path, chunk_store_root=tmp_project)

    assert summary["resliced_material_count"] == 1
    assert summary["blocked_material_count"] == 0
    assert summary["fallback_material_count"] == 0
    store = rr._load_chunk_store("proj")
    assert len(store["mat-oversize"]) > 1
    assert all(len(str(chunk["content"])) <= rr.CHUNK_SIZE + rr.CHUNK_OVERLAP + 200 for chunk in store["mat-oversize"])
    assert store["mat-safe"] == [
        {
            "chunk_id": "mat-safe_chunk_0",
            "material_id": "mat-safe",
            "title": "Safe Notes.txt",
            "content": "short content",
            "char_count": 13,
        }
    ]

    manifest = json.loads((tmp_project / "proj" / "manifest.json").read_text(encoding="utf-8"))
    assert "resliced_at" in manifest["materials"]["mat-oversize"]
    assert "resliced_at" not in manifest["materials"]["mat-safe"]

    refreshed = build_report(tmp_project)
    assert refreshed["oversize_material_count"] == 0
    assert refreshed["oversize_chunk_count"] == 0


def test_reslice_from_report_falls_back_to_existing_chunk_content_when_doc_store_is_missing(tmp_project: Path) -> None:
    _write_legacy_chunk_store(tmp_project)
    report_path = _write_report(tmp_project)

    summary = reslice_from_report(report_path=report_path, chunk_store_root=tmp_project)

    assert summary["resliced_material_count"] == 1
    assert summary["fallback_material_count"] == 1
    manifest = json.loads((tmp_project / "proj" / "manifest.json").read_text(encoding="utf-8"))
    assert "resliced_at" in manifest["materials"]["mat-oversize"]
    refreshed = build_report(tmp_project)
    assert refreshed["oversize_material_count"] == 0


def test_reslice_from_report_re_splits_oversize_formula_chunks(tmp_project: Path) -> None:
    _write_formula_doc_store(tmp_project)
    _write_legacy_chunk_store(tmp_project)
    report_path = _write_report(tmp_project)

    summary = reslice_from_report(report_path=report_path, chunk_store_root=tmp_project)

    assert summary["remaining_targeted_oversize_count"] == 0
    refreshed = rr._load_chunk_store("proj")
    assert len(refreshed["mat-oversize"]) > 1


def test_reslice_from_report_preserves_existing_resliced_at_marks_on_later_runs(tmp_project: Path) -> None:
    payload = {
        "mat-first": {"title": "First.txt", "content": "A" * 6001},
        "mat-second": {"title": "Second.txt", "content": "B" * 6001},
    }
    (tmp_project / "proj.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    legacy = {
        material_id: [
            {
                "chunk_id": f"{material_id}_chunk_0",
                "material_id": material_id,
                "title": record["title"],
                "content": record["content"],
                "char_count": len(record["content"]),
            }
        ]
        for material_id, record in payload.items()
    }
    (tmp_project / "proj_chunks.json").write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    report_path = _write_multi_material_report(tmp_project, ["mat-first"])
    reslice_from_report(report_path=report_path, chunk_store_root=tmp_project, resliced_at="2026-04-22T00:00:00+00:00")
    report_path = _write_multi_material_report(tmp_project, ["mat-second"])
    reslice_from_report(report_path=report_path, chunk_store_root=tmp_project, resliced_at="2026-04-22T00:05:00+00:00")

    manifest = json.loads((tmp_project / "proj" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["materials"]["mat-first"]["resliced_at"] == "2026-04-22T00:00:00+00:00"
    assert manifest["materials"]["mat-second"]["resliced_at"] == "2026-04-22T00:05:00+00:00"

