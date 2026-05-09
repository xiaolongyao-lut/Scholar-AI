# -*- coding: utf-8 -*-
"""E2E test: Batch processing -> Volume bundle -> Analysis pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from batch_controller import BatchProcessController


def _create_mock_material_pack(pack_path: Path, paper_id: str, point_count: int = 3) -> None:
    """Create a mock material pack JSON file."""
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    material_pack = {
        "source_pdf": f"{paper_id}.pdf",
        "paper_id": paper_id,
        "writing_points": [
            {
                "writing_point_id": f"{paper_id}_wp{i:03d}",
                "claim": f"Sample claim {i} from {paper_id}",
                "relevance_score": 0.8 + (i * 0.05),
            }
            for i in range(1, point_count + 1)
        ],
        "figures": [],
        "references": [],
    }
    pack_path.write_text(json.dumps(material_pack, ensure_ascii=False, indent=2), encoding="utf-8")


def test_batch_to_volume_pipeline_generates_stats(tmp_path) -> None:
    """Test: Batch processing -> Volume creation includes volume_stats."""
    batch_output_root = tmp_path / "batch_output_test"
    batch_output_root.mkdir(parents=True, exist_ok=True)
    batch_time_folder = batch_output_root / "batch_20260415_120000"
    batch_time_folder.mkdir(parents=True, exist_ok=True)

    # Create mock material packs
    material_packs = []
    for paper_idx in range(1, 3):
        paper_id = f"P{paper_idx:04d}"
        pack_path = batch_time_folder / f"{paper_id}" / "02_writing_material_pack.json"
        _create_mock_material_pack(pack_path, paper_id, point_count=3)
        material_packs.append(pack_path)

    # Mock the pipeline and volume merge to use direct mode
    controller = BatchProcessController(
        pdf_folder=str(tmp_path / "papers"),
        output_root=str(batch_output_root),
        goal="Test Analysis",
        batch_size=2,
        enable_llm=False,
    )

    # Test: create_volume_bundle should generate volume_stats
    result = controller.create_volume_bundle(material_packs, "V01_TEST")

    assert result is True

    # Verify volume_stats was created
    volume_dir = batch_output_root / "volume_V01_TEST"
    assert volume_dir.exists()

    volume_stats_path = volume_dir / "volume_stats_V01_TEST.json"
    assert volume_stats_path.exists(), f"volume_stats not found at {volume_stats_path}"

    # Verify volume_stats content
    with open(volume_stats_path, "r", encoding="utf-8") as f:
        volume_stats = json.load(f)

    assert volume_stats["volume_id"] == "V01_TEST"
    assert volume_stats["paper_count"] == 2
    assert volume_stats["writing_point_count"] == 6  # 3 points per paper * 2 papers
    assert "created_at" in volume_stats
    assert "material_packs" in volume_stats
    assert len(volume_stats["material_packs"]) == 2


def test_batch_to_volume_analysis_with_metadata(tmp_path) -> None:
    """Test: W-Layer analysis includes schema version and timestamps."""
    from layers.w_layer_cross_paper_analysis import CrossPaperAnalyzer
    from datetime import datetime

    # Create a mock volume bundle
    volume_bundle = {
        "volume_id": "V01_META_TEST",
        "created_at": datetime.now().isoformat(),
        "paper_count": 2,
        "writing_points": [
            {
                "writing_point_id": "wp001",
                "source_paper_id": "P0001",
                "claim": "Parameter X shows positive correlation.",
                "relevance_score": 0.9,
            },
            {
                "writing_point_id": "wp002",
                "source_paper_id": "P0002",
                "claim": "Parameter X shows negative correlation.",
                "relevance_score": 0.85,
            },
        ],
        "all_parameters": ["Parameter X", "Parameter Y"],
        "figures": [],
        "references": [],
    }

    bundle_path = tmp_path / "test_bundle.json"
    bundle_path.write_text(
        json.dumps(volume_bundle, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report_path = tmp_path / "test_report.json"

    # Run analysis
    analyzer = CrossPaperAnalyzer()
    analyzer.generate_final_report(report_path)

    # Verify report was created
    assert report_path.exists()

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # P1 enhancement: Check versioning metadata
    assert report.get("schema_version") == "v3.cross-paper-aware"
    assert "analysis_version" in report
    assert report["analysis_version"] == "1.0"
    assert "w_layer_version" in report
    assert report["w_layer_version"] == "1.1"

    # P1 enhancement: Check timestamps
    assert "generated_at" in report
    assert "analysis_generated_at" in report
    # Both should be close in time (within 1 second due to datetime.now() calls)
    generated_time = datetime.fromisoformat(report["generated_at"])
    analysis_time = datetime.fromisoformat(report["analysis_generated_at"])
    time_diff = abs((analysis_time - generated_time).total_seconds())
    assert time_diff < 1.0

    # Verify metadata is timestamp-like
    import re

    iso_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    assert re.match(iso_pattern, report["generated_at"])
    assert re.match(iso_pattern, report["analysis_generated_at"])
