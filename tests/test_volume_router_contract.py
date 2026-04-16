# -*- coding: utf-8 -*-
"""Contract tests for volume bundle discovery and cross-paper analysis APIs."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.volume_router import router as volume_router
import volume_analysis_service as vas


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_volume_router_lists_and_analyzes_bundles(tmp_path, monkeypatch) -> None:
    batch_root = tmp_path / "batch_output_demo"
    bundle_path = batch_root / "volume_V01" / "volume_bundle_V01.json"
    report_path = batch_root / "batch_logs" / "batch_report_20260415_000000.json"

    _write_json(
        bundle_path,
        {
            "status": "volume_bundle_ready",
            "volume_id": "V01",
            "created_at": "2026-04-15T10:30:00",
            "paper_count": 2,
            "writing_points": [
                {
                    "writing_point_id": "wp001",
                    "source_paper_id": "P0001",
                    "claim": "Laser power increased hardness and reduced porosity.",
                    "relevance_score": 0.9,
                },
                {
                    "writing_point_id": "wp002",
                    "source_paper_id": "P0002",
                    "claim": "Laser power reduced hardness under unstable shielding gas.",
                    "relevance_score": 0.82,
                },
                {
                    "writing_point_id": "wp003",
                    "source_paper_id": "P0002",
                    "claim": "Powder content remained stable across repeated trials.",
                    "relevance_score": 0.73,
                },
            ],
            "figures": [],
            "references": [],
            "stats": {
                "writing_point_count": 3,
                "figure_count": 0,
                "reference_count": 0,
            },
        },
    )
    _write_json(
        report_path,
        {
            "start_time": "2026-04-15T10:25:00",
            "pdf_folder": str(tmp_path / "papers"),
            "output_root": batch_root.name,
            "goal": "Conclusion Extraction",
            "batch_size": 13,
            "total_pdfs": 2,
            "successful_pdfs": 2,
            "failed_pdfs": 0,
            "status": "completed",
        },
    )

    monkeypatch.setattr(vas, "REPO_ROOT", tmp_path)

    app = FastAPI()
    app.include_router(volume_router)
    client = TestClient(app)

    list_response = client.get("/volumes")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 1

    volume = list_payload["volumes"][0]
    assert volume["volume_id"] == "V01"
    assert volume["paper_count"] == 2
    assert volume["batch_summary"]["successful_pdfs"] == 2

    analysis_response = client.get(f"/volumes/{volume['volume_key']}/analysis")
    assert analysis_response.status_code == 200
    analysis_payload = analysis_response.json()

    assert analysis_payload["volume"]["status"] == "indexed"
    assert analysis_payload["analysis"]["tracked_parameter_count"] >= 2
    assert analysis_payload["analysis"]["high_conflict_count"] >= 1
    assert "power" in analysis_payload["analysis"]["top_conflicts"][0]["parameter"]

    report_paths = analysis_payload["analysis"]["report_paths"]
    assert (tmp_path / report_paths["conflict"]).is_file()
    assert (tmp_path / report_paths["trend"]).is_file()
    assert (tmp_path / report_paths["master_index"]).is_file()
