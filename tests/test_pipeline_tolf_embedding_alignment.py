from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import patch

import numpy as np


@patch("pipeline_core.build_material_pack", return_value={})
@patch("layers.e_layer_multimodal.full_extract")
@patch("layers.a_layer_agent_coordinator.infer_open_focus_points")
@patch("layers.r_layer_hybrid_retriever.hybrid_search")
@patch("layers.contracts.bind_evidence")
@patch("layers.g_layer_academic_generator.AcademicScorer.analyze_bound_data")
@patch("layers.k_layer_index_builder.KLayerManager.build_project_view")
@patch("layers.e_layer_multimodal.refine_multimodal_assets")
@patch("layers.p_layer_presentation_word.generate_docx_report")
def test_pipeline_tolf_uses_batch_embed_guard_stack(
    mock_docx,
    mock_refine,
    mock_k,
    mock_scoring,
    mock_bind,
    mock_search,
    mock_focus,
    mock_extract,
    mock_build_material_pack,
    tmp_path: Path,
) -> None:
    import pipeline_core

    captured: dict[str, object] = {}

    long_chunk = "A" * 700
    mock_extract.return_value = {
        "chunks": [
            {"content": long_chunk},
            {"content": "chunk two"},
            {"content": "chunk three"},
        ]
    }
    mock_scoring.return_value = {"overall_score": 0.8}
    mock_refine.return_value = {"status": "ok"}

    async def fake_batch_embed_texts(
        texts,
        *,
        api_key=None,
        base_url=None,
        model=None,
        batch_size=None,
        concurrency=None,
        stage=None,
    ):
        captured["texts"] = list(texts)
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["model"] = model
        captured["batch_size"] = batch_size
        captured["concurrency"] = concurrency
        captured["stage"] = stage
        return [[float(index), float(index) + 0.5] for index, _ in enumerate(texts)]

    class FakeTOLFEngine:
        def generate_aspect_queries(self, goal):
            captured["goal"] = goal
            return {
                "K": "aspect-k",
                "S": "aspect-s",
                "R": "aspect-r",
                "V": "aspect-v",
            }

        def run(self, goal, chunks, chunk_embs, aspect_embs):
            captured["run_goal"] = goal
            captured["chunk_count"] = len(chunks)
            captured["chunk_embs_shape"] = tuple(chunk_embs.shape)
            captured["aspect_embs_shape"] = tuple(aspect_embs.shape)
            return [
                types.SimpleNamespace(
                    chunk_id="chunk-1",
                    activation_score=0.9,
                    evidence_score=0.8,
                    point_type="result",
                    in_convex_hull=True,
                    content="fish content",
                )
            ]

    with (
        patch.object(pipeline_core, "_TOLF_AVAILABLE", True),
        patch.object(pipeline_core, "TOLFEngine", FakeTOLFEngine, create=True),
        patch.object(pipeline_core, "batch_embed_texts", fake_batch_embed_texts),
        patch.object(
            pipeline_core,
            "resolve_embedding_config",
            return_value=("embed-key", "https://embed.example/v1", "embed-model"),
        ),
        patch.object(pipeline_core, "_np", np, create=True),
    ):
        result = pipeline_core.run_pipeline("test.pdf", "test goal", output_dir=str(tmp_path))

    assert captured["texts"][0] == long_chunk
    assert captured["texts"][-4:] == ["aspect-k", "aspect-s", "aspect-r", "aspect-v"]
    assert captured["api_key"] == "embed-key"
    assert captured["base_url"] == "https://embed.example/v1"
    assert captured["model"] == "embed-model"
    assert captured["stage"] == "tolf"
    assert captured["chunk_count"] == 3
    assert captured["chunk_embs_shape"] == (3, 2)
    assert captured["aspect_embs_shape"] == (4, 2)
    assert result["artifacts"]["tolf_fish"][0]["chunk_id"] == "chunk-1"
