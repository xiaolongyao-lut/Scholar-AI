from __future__ import annotations

import json
from pathlib import Path

import pipeline_core


class _DummyScorer:
    def __init__(self, goal: str):
        self.goal = goal
        self.llm_status = "disabled_missing_dependency"

    async def analyze_bound_data(self, _bound):
        return {
            "status": "analysis_complete",
            "goal": self.goal,
            "overall_score": 0.88,
            "llm_status": "disabled_missing_dependency",
            "selected_writing_points": [
                {
                    "writing_point_id": "wp001",
                    "claim": "Test claim",
                    "point_type": "result",
                    "boundary_type": "result_fact",
                    "boundary_note": "from observed evidence",
                    "goal_hits": ["test"],
                    "relevance_score": 0.9,
                    "source_text": "test source text",
                    "linked_figures": [],
                    "linked_tables": [],
                }
            ],
            "selected_figures": [],
            "selected_tables": [],
            "selected_references": [],
            "selected_parameters": [],
            "selected_results": [],
            "semantic_themes": [
                {
                    "theme_id": "theme_001",
                    "theme_title": "Test Theme",
                    "summary": "Theme summary",
                    "linked_writing_point_ids": ["wp001"],
                    "linked_figure_ids": [],
                    "linked_table_ids": [],
                }
            ],
            "stats_analysis": {"writing_point_count": 1},
        }


class _DummyKLayerManager:
    def __init__(self, _output_dir):
        pass

    def build_project_view(self, _extract, _bound, _analysis, goal):
        return {
            "goal": goal,
            "quality_gates": {"overall_pass": True},
        }


def _patch_minimal_pipeline(monkeypatch, pdf_path: Path):
    def fake_full_extract(_pdf):
        return {
            "source_pdf": str(pdf_path.resolve()),
            "chunks": [
                {
                    "chunk_id": "c0001",
                    "text": "Test chunk text with numeric 123 and result cue.",
                    "page": 1,
                    "bbox": [0, 0, 100, 100],
                    "mentioned_figures": [],
                    "mentioned_tables": [],
                    "section_title": "Results",
                }
            ],
            "figures": [],
            "tables": [],
            "relation_edges": [],
        }

    bound_contract = {
        "source_pdf": str(pdf_path.resolve()),
        "chunks": [],
        "figures": [],
        "tables": [],
        "references": [],
        "relation_edges": [{"source_id": "c0001", "target_type": "figure", "target_id": "f001"}],
        "evidence_clusters": [{"cluster_id": "ec1"}],
        "figure_bindings": [],
        "table_bindings": [],
        "parameter_cards": [],
        "result_cards": [],
        "page_images": [],
    }

    monkeypatch.setattr(pipeline_core.e_layer, "full_extract", fake_full_extract)
    monkeypatch.setattr(pipeline_core.a_layer, "infer_open_focus_points", lambda *_args, **_kwargs: ["focus"])
    monkeypatch.setattr(
        pipeline_core.r_layer,
        "hybrid_search",
        lambda *_args, **_kwargs: [{"id": "hit1", "text": "retrieval hit", "score": 0.8}],
    )
    monkeypatch.setattr(pipeline_core.contracts, "bind_evidence", lambda _raw: bound_contract)
    monkeypatch.setattr(pipeline_core, "AcademicScorer", _DummyScorer)
    monkeypatch.setattr(pipeline_core, "KLayerManager", _DummyKLayerManager)

    monkeypatch.setattr(
        pipeline_core,
        "build_material_pack",
        lambda analysis, bound: {
            "goal": analysis.get("goal", ""),
            "source_pdf": bound.get("source_pdf", ""),
            "writing_point_cards": [
                {
                    "writing_point_id": "wp001",
                    "claim": "Test claim",
                    "point_type": "result",
                    "boundary_type": "result_fact",
                    "boundary_note": "from observed evidence",
                    "linked_figure_ids": [],
                    "linked_table_ids": [],
                    "linked_parameter_ids": [],
                    "linked_result_ids": [],
                    "linked_reference_ids": [],
                    "evidence_summary": "0 图 / 0 表 / 0 参数 / 0 结果 / 0 引用",
                    "original_reference_markers": [],
                }
            ],
            "single_figure_cards": [],
            "single_table_cards": [],
            "reference_directory_with_original_markers": [],
            "pack_summary": {"selected_writing_points": 1},
        },
    )

    def fake_refine(material_pack, out_dir, dpi=220):
        assert isinstance(material_pack, dict)
        assert isinstance(out_dir, Path)
        assert dpi == 220
        return {
            "status": "ok",
            "single_figure_cards_refined": material_pack.get("single_figure_cards", []),
            "single_table_cards_refined": material_pack.get("single_table_cards", []),
        }

    def fake_docx(material_pack_path, output_docx):
        material_path = Path(material_pack_path)
        assert material_path.exists()
        Path(output_docx).write_text("docx stub", encoding="utf-8")

    monkeypatch.setattr(pipeline_core.e_layer, "refine_multimodal_assets", fake_refine)
    monkeypatch.setattr(pipeline_core.p_layer, "generate_docx_report", fake_docx)


def test_pipeline_writes_material_pack_artifact(monkeypatch, tmp_path):
    pdf_path = tmp_path / "materials-19-01104.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    _patch_minimal_pipeline(monkeypatch, pdf_path)

    result = pipeline_core.run_pipeline(str(pdf_path), "Conclusion Extraction", str(tmp_path / "out"))

    assert result["status"] == "success"
    material_json = Path(result["output_dir"]) / "02_writing_material_pack.json"
    assert material_json.exists()


def test_pipeline_succeeds_without_openai_and_marks_status(monkeypatch, tmp_path):
    pdf_path = tmp_path / "s41467-025-60162-0.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    _patch_minimal_pipeline(monkeypatch, pdf_path)

    result = pipeline_core.run_pipeline(str(pdf_path), "No OpenAI mode", str(tmp_path / "out"))

    assert result["status"] == "success"

    scoring_json = Path(result["output_dir"]) / "03_academic_scoring.json"
    scoring_payload = json.loads(scoring_json.read_text(encoding="utf-8"))
    assert scoring_payload["scoring"]["llm_status"] == "disabled_missing_dependency"

    material_payload = json.loads(Path(result["material_pack"]).read_text(encoding="utf-8"))
    assert material_payload["llm_status"] == "disabled_missing_dependency"


def test_pipeline_handles_chinese_title_with_trailing_dots(monkeypatch, tmp_path):
    pdf_path = tmp_path / "Nature Communications｜晶型调控新依据！成分判据....pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    _patch_minimal_pipeline(monkeypatch, pdf_path)

    result = pipeline_core.run_pipeline(str(pdf_path), "Goal", str(tmp_path / "out"))

    out_dir = Path(result["output_dir"])
    assert result["status"] == "success"
    assert out_dir.exists()
    assert out_dir.name != pdf_path.stem
    assert not out_dir.name.endswith(".")
    assert not out_dir.name.endswith(" ")
    assert (out_dir / "01_full_extract.json").exists()
    assert (out_dir / "02_writing_material_pack.json").exists()
