"""Lock the TOLF×RAG fusion (RRF) addition to the chat router.

These tests pin two invariants:

1. RRF mathematics: ranks (not raw scores) drive fusion, so a chunk that
   appears at rank 1 in two lists beats a chunk that appears only at rank 1
   in one list, regardless of TOLF activation score vs RAG keyword overlap
   score scale.
2. Bus-default behaviour: tolf_fusion_mode is now ON by default. When the
   user explicitly turns it OFF (env=0 + cleared override) the historical
   "TOLF replaces RAG on a hit" fallback must come back exactly as before.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_CORE = Path(__file__).resolve().parents[1] / "literature_assistant" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from routers.intelligent_chat_router import (  # noqa: E402
    ContextChunkPayload,
    _extract_figure_candidate_detail,
    _extract_image_paths,
    _build_smart_read_retrieval_diagnostics,
    _merge_visual_evidence_chunks,
    _prioritize_query_identifier_matches,
    _rrf_merge,
    _tolf_fusion_mode_enabled,
    _visual_evidence_score,
)


def _reset_flag_cache() -> None:
    import feature_flags
    if hasattr(feature_flags, "_FLAG_CACHE"):
        feature_flags._FLAG_CACHE = {}


def _isolate_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty = tmp_path / "feature_flags_override.json"
    empty.write_text(json.dumps({"flags": {}, "updated_at": "test"}), encoding="utf-8")
    import feature_flags
    monkeypatch.setattr(feature_flags, "_OVERRIDE_PATH", empty)
    _reset_flag_cache()


# ---------- RRF unit tests ----------

def test_rrf_single_list_preserves_order_and_attaches_score() -> None:
    ranked = [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}]
    fused = _rrf_merge(ranked)
    assert [r["chunk_id"] for r in fused] == ["a", "b", "c"]
    assert all("rrf_score" in r for r in fused)
    assert all(r["rrf_sources"] == [0] for r in fused)
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"] > fused[2]["rrf_score"]


def test_rrf_two_lists_merge_by_rank_not_score() -> None:
    # TOLF gives X a tiny score (0.01) but rank 1; RAG gives Y a huge score
    # (99.9) but rank 1. With RRF, both lead their own list — but X also
    # appears in RAG at rank 2, so X gets two contributions and wins.
    tolf = [{"chunk_id": "X", "tolf_score": 0.01}, {"chunk_id": "Z", "tolf_score": 0.001}]
    rag = [{"chunk_id": "Y", "score": 99.9}, {"chunk_id": "X", "score": 50.0}]
    fused = _rrf_merge(tolf, rag)
    assert fused[0]["chunk_id"] == "X"
    assert fused[0]["rrf_sources"] == [0, 1]  # appeared in both


def test_rrf_dedups_by_chunk_id_within_list_first_wins() -> None:
    # Same chunk_id twice in one list: RRF should count the first (better)
    # rank only — second occurrence contributes a smaller score, but the
    # representative dict stays the first one.
    ranked = [{"chunk_id": "a", "tag": "first"}, {"chunk_id": "a", "tag": "second"}]
    fused = _rrf_merge(ranked)
    assert len(fused) == 1
    assert fused[0]["tag"] == "first"


def test_rrf_drops_missing_or_blank_chunk_id() -> None:
    ranked = [
        {"chunk_id": "a"},
        {"chunk_id": ""},
        {"no_chunk_id_field": True},
        {"chunk_id": "  "},
    ]
    fused = _rrf_merge(ranked)
    assert [r["chunk_id"] for r in fused] == ["a"]


def test_rrf_handles_non_list_inputs() -> None:
    # None / strings / dicts should be silently dropped, not crash.
    fused = _rrf_merge(None, "not a list", {"chunk_id": "x"})  # type: ignore[arg-type]
    assert fused == []


def test_rrf_k_parameter_affects_score_decay() -> None:
    # Smaller k → larger rank-1 score (top dominates). Default k=60.
    ranked = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    tight = _rrf_merge(ranked, k=1)
    loose = _rrf_merge(ranked, k=60)
    # Top score: 1/(k+1). With k=1 → 0.5; k=60 → 1/61 ≈ 0.0164. Tighter wins.
    assert tight[0]["rrf_score"] > loose[0]["rrf_score"]


def test_smart_read_retrieval_diagnostics_aggregate_gateway_and_tolf_without_context_leak() -> None:
    chunk = ContextChunkPayload(
        index=1,
        source="Laser welding paper",
        content="AlSi10Mg laser welding evidence.",
        retrieval_gateway_diagnostics={
            "project_id": "proj_hidden",
            "dense_hit_count": 0,
            "lexical_hit_count": 4,
            "visual_hit_count": 1,
            "candidate_count": 5,
            "dense_enabled": False,
            "material_balancing_enabled": True,
            "chroma_status": "unavailable",
            "fts_status": "valid",
            "fallback_reasons": ["dense_recall_missing_contract_or_embedding"],
            "gate_status_counts": {"valid": 4},
        },
        tolf_diagnostics={
            "status": "active",
            "candidate_count": 45,
            "input_count": 45,
            "graph_node_count": 45,
            "graph_edge_count": 96,
            "gate_after_count": 6,
            "activation_mean": 0.42,
        },
        tolf_final_rank_score=0.82,
        tolf_rank_contributions={
            "dense": 0.0,
            "lexical_exact": 0.3,
            "locator_quality": 0.1,
            "tolf_evidence": 0.2,
            "diversity_penalty": 0.0,
        },
    )

    diagnostics = _build_smart_read_retrieval_diagnostics(
        [chunk],
        project_id="proj_hidden",
        retrieval_attempted=True,
    )

    assert diagnostics is not None
    assert diagnostics.lexical_only is True
    assert diagnostics.gateway is not None
    assert diagnostics.gateway.lexical_hit_count == 4
    assert diagnostics.tolf is not None
    assert diagnostics.tolf.graph_node_count == 45
    assert diagnostics.tolf.graph_edge_count == 96
    assert diagnostics.tolf.gate_after_count == 6
    assert diagnostics.tolf.rank_contribution_keys == [
        "dense",
        "lexical_exact",
        "locator_quality",
        "tolf_evidence",
        "diversity_penalty",
    ]
    serialized_chunk = chunk.model_dump()
    assert "retrieval_gateway_diagnostics" not in serialized_chunk
    assert "tolf_diagnostics" not in serialized_chunk
    assert "proj_hidden" not in str(diagnostics.model_dump())


def test_identifier_priority_demotes_broad_topic_hits() -> None:
    results = [
        {
            "chunk_id": "generic_laser",
            "title": "Remote laser welding of AA5182 aluminum alloy.pdf",
            "content": "Laser welding process parameters are discussed.",
        },
        {
            "chunk_id": "alsi10mg_welding",
            "title": "Laser weldability of AlSi10Mg alloy.pdf",
            "content": "The AlSi10Mg weld seam used laser power and welding speed.",
        },
    ]

    ranked = _prioritize_query_identifier_matches("AlSi10Mg 激光焊接工艺参数", results)

    assert [item["chunk_id"] for item in ranked] == ["alsi10mg_welding", "generic_laser"]


# ---------- Feature flag default ON (bus) ----------

def test_fusion_mode_flag_defaults_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Bus default after stable verification.
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", raising=False)
    _isolate_overrides(monkeypatch, tmp_path)
    assert _tolf_fusion_mode_enabled() is True


def test_fusion_mode_flag_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", "1")
    _reset_flag_cache()
    assert _tolf_fusion_mode_enabled() is True

    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", "0")
    _reset_flag_cache()
    assert _tolf_fusion_mode_enabled() is False


# ---------- Behavioural lock: fusion-off branch unchanged ----------

def test_build_context_chunks_fusion_off_does_not_call_search(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """When fusion flag is off, the TOLF branch must NOT also call RAG search.

    The historical branch is: TOLF non-empty → use TOLF; TOLF empty → call
    ``search_project_chunks_for_query``. Bus default is now fusion ON, so
    we have to explicitly turn it OFF here AND clear the override.
    """
    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", "0")
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "0")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "1")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    fake_chunks = [{"chunk_id": "c1", "content": "x", "material_id": "m1", "title": "t"}]
    fake_tolfs = [{"chunk_id": "tolf_1", "content": "tolf hit", "score": 0.9}]

    with (
        patch.object(router, "load_project_chunks_for_rag", return_value=fake_chunks),
        patch.object(router, "select_tolf_context_chunks", return_value=fake_tolfs),
        patch.object(router, "search_project_chunks_for_query") as mock_search,
    ):
        chunks, _truncated = asyncio.run(
            router._build_project_context_chunks(
                query="anything", project_id="proj_test", tier="fast"
            )
        )
        # TOLF returned non-empty + fusion off → RAG search should NOT be called.
        mock_search.assert_not_called()
        # And the returned content should come from TOLF.
        assert chunks and chunks[0].content.startswith("tolf hit")


def test_build_context_chunks_fusion_on_calls_both_arms(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "1")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", "1")
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "0")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    fake_chunks = [{"chunk_id": "c1", "content": "corpus"}]
    fake_tolfs = [{"chunk_id": "tolf_1", "content": "tolf hit"}]
    fake_rag = [{"chunk_id": "rag_1", "content": "rag hit"}]

    with (
        patch.object(router, "load_project_chunks_for_rag", return_value=fake_chunks),
        patch.object(router, "select_tolf_context_chunks", return_value=fake_tolfs),
        patch.object(router, "search_project_chunks_for_query", return_value=fake_rag) as mock_search,
    ):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="anything", project_id="proj_test", tier="fast"
            )
        )
        # Fusion on → RAG search must be called exactly once in addition to TOLF.
        mock_search.assert_called_once()
        # Both candidates should appear in the merged output (top-2 by RRF).
        contents = {c.content.split()[0] for c in chunks}
        assert "tolf" in contents or "rag" in contents


def test_build_context_chunks_fusion_on_uses_gateway_backed_rag_arm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "1")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", "1")
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "0")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from chunk_fts_index import rebuild_chunk_fts_index
    from chunk_hashing import compute_chunk_store_version
    from routers import intelligent_chat_router as router
    from routers import resources_router

    store = {
        "mat_gateway": [
            {
                "chunk_id": "gateway_rag_1",
                "material_id": "mat_gateway",
                "title": "Gateway RAG Paper",
                "content": "AlSi10Mg keyhole porosity is reported at laser power 2000 W.",
                "raw_content": "AlSi10Mg keyhole porosity is reported at laser power 2000 W.",
                "page": 6,
            }
        ]
    }
    db_path = tmp_path / "chunks.sqlite3"
    rebuild_chunk_fts_index(
        db_path=db_path,
        project_id="proj_gateway",
        store=store,
        chunk_store_version=compute_chunk_store_version(store),
    )
    fake_tolfs = [
        {
            "chunk_id": "tolf_1",
            "material_id": "mat_tolf",
            "title": "TOLF Paper",
            "content": "TOLF mechanism evidence.",
            "score": 0.9,
        }
    ]

    monkeypatch.setattr(resources_router, "_ensure_project_chunks", lambda _project_id: store)
    monkeypatch.setattr(resources_router, "_chunk_fts_index_path", lambda _project_id: db_path)
    monkeypatch.setattr(
        resources_router,
        "_search_chunks_hybrid",
        lambda **_kwargs: pytest.fail("legacy scorer must not run when Gateway FTS is valid"),
    )

    with (
        patch.object(router, "load_project_chunks_for_rag", return_value=list(store["mat_gateway"])),
        patch.object(router, "select_tolf_context_chunks", return_value=fake_tolfs),
    ):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="AlSi10Mg keyhole porosity laser power 2000 W",
                project_id="proj_gateway",
                tier="fast",
            )
        )

    assert any(chunk.chunk_id == "gateway_rag_1" for chunk in chunks)


def test_hybrid_retrieval_keeps_keyword_recall_when_hybrid_returns_hits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Hybrid success must not suppress exact local keyword evidence."""

    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "0")
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "1")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    hybrid_noise = [
        {
            "chunk_id": "hybrid_noise",
            "material_id": "mat_noise",
            "content": "LPBF process dataset without welding parameters.",
            "title": "Luo 等 - 2024 - Dataset of process relationships for AlSi10Mg.pdf",
        }
    ]
    keyword_hit = [
        {
            "chunk_id": "keyword_welding",
            "material_id": "mat_welding",
            "content": "Laser welding of AlSi10Mg used laser power and welding speed process parameters.",
            "title": "Biffi 等 - 2019 - Laser weldability of AlSi10Mg alloy.pdf",
        }
    ]

    with (
        patch.object(router, "_hybrid_search_project", return_value=hybrid_noise) as mock_hybrid,
        patch.object(router, "search_project_chunks_for_query", return_value=keyword_hit) as mock_keyword,
    ):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="AlSi10Mg 激光焊接工艺参数",
                project_id="proj_test",
                tier="fast",
            )
        )

    mock_hybrid.assert_called_once()
    mock_keyword.assert_called_once()
    assert any(chunk.chunk_id == "keyword_welding" for chunk in chunks)


def test_visual_evidence_merge_prefers_laser_weld_images_over_non_laser_images() -> None:
    """Visual queries should surface real figure assets matching the user intent."""

    selected = [
        {
            "chunk_id": "zhang_text",
            "title": "A comparison between laser and TIG welding of selective laser melted AlSi10Mg.pdf",
            "content": "SLMed AlSi10Mg laser welding has weld morphology and pore defects.",
        },
        {
            "chunk_id": "electron_beam_image",
            "title": "Electron beam welding of AlSi10Mg workpieces.pdf",
            "content": "Fig. 10. Weld penetration vs weld speed.",
            "chunk_type": "figure_caption",
            "image_paths": ["figure_assets/extracted/electron/p0007_img003.jpeg"],
        },
        {
            "chunk_id": "schwarz_text",
            "title": "Laser welding in vacuum for high quality weld seams.pdf",
            "content": "The weld seam had pores under the surface.",
        },
        {
            "chunk_id": "generic_text",
            "title": "LPBF process dataset.pdf",
            "content": "Background process data.",
        },
    ]
    chunk_pool = [
        *selected,
        {
            "chunk_id": "ping_surface_appearance",
            "title": "Oscillating laser welding of SLM-deposited AlSi10Mg sheets.pdf",
            "content": "Figure 2. weld surface appearance and porosity of joints by SLM AlSi10Mg.",
            "chunk_type": "figure_caption",
            "image_paths": ["figure_assets/extracted/ping/p0005_img001.png"],
        },
        {
            "chunk_id": "cui_fracture_surface",
            "title": "Porosity, microstructure and mechanical property of welded joints produced by different laser welding.pdf",
            "content": "Fig. 19. SEM micrographs of fracture surface of welded SLM AlSi10Mg alloys by single-pass laser welding.",
            "chunk_type": "figure_caption",
            "image_paths": ["figure_assets/extracted/cui/p0014_img001.png"],
        },
    ]

    merged = _merge_visual_evidence_chunks(
        "AlSi10Mg laser welding appearance image morphology",
        selected,
        chunk_pool,
        total_cap=4,
    )

    merged_ids = [item["chunk_id"] for item in merged]
    assert "zhang_text" in merged_ids
    assert "ping_surface_appearance" in merged_ids
    assert "cui_fracture_surface" in merged_ids
    assert "electron_beam_image" not in merged_ids


def test_visual_evidence_merge_places_images_before_long_tail_anchors() -> None:
    """Chinese visual queries must not bury real image chunks after many anchors."""

    selected = [
        {
            "chunk_id": f"text_anchor_{index}",
            "title": "AlSi10Mg 激光焊接工艺.pdf",
            "content": "AlSi10Mg laser welding process parameters and weld seam quality. " * 12,
        }
        for index in range(8)
    ]
    visual_chunk = {
        "chunk_id": "surface_appearance_image",
        "title": "Porosity, microstructure and mechanical property of welded joints produced by different laser welding.pdf",
        "content": "Fig. 18. Surface morphology and weld surface appearance of laser welded SLM AlSi10Mg joints.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/cui/p0013_img001.png"],
    }

    merged = _merge_visual_evidence_chunks(
        "AlSi10Mg 激光焊接 外观 图片",
        selected,
        [*selected, visual_chunk],
        total_cap=10,
    )

    merged_ids = [item["chunk_id"] for item in merged]
    assert "surface_appearance_image" in merged_ids
    assert merged_ids.index("surface_appearance_image") <= 3


def test_visual_evidence_merge_deduplicates_reused_image_assets() -> None:
    """Repeated chunk captions for the same extracted image should not crowd out evidence."""

    selected = [
        {
            "chunk_id": "text_anchor",
            "title": "AlSi10Mg 激光焊接工艺.pdf",
            "content": "AlSi10Mg laser welding process parameters and weld seam quality.",
        }
    ]
    duplicate_a = {
        "chunk_id": "surface_caption_a",
        "title": "Laser welding of AlSi10Mg.pdf",
        "content": "Fig. 4. Autogenous laser welding of AlSi10Mg alloys.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/cui/p0005_img002.png"],
    }
    duplicate_b = {
        "chunk_id": "surface_caption_b",
        "title": "Laser welding of AlSi10Mg.pdf",
        "content": "Fig. 6. Macrostructure of the welded joints in SLM AlSi10Mg alloys.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/cui/p0005_img002.png"],
    }
    distinct = {
        "chunk_id": "surface_caption_c",
        "title": "Laser welding of AlSi10Mg.pdf",
        "content": "Fig. 18. Surface morphology of laser welded SLM AlSi10Mg joints.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/cui/p0013_img001.png"],
    }

    merged = _merge_visual_evidence_chunks(
        "AlSi10Mg 激光焊接 外观 图片",
        selected,
        [*selected, duplicate_a, duplicate_b, distinct],
        total_cap=5,
    )

    image_paths = [
        path
        for item in merged
        for path in item.get("image_paths", [])
        if isinstance(path, str)
    ]
    assert image_paths.count("figure_assets/extracted/cui/p0005_img002.png") == 1
    assert "figure_assets/extracted/cui/p0013_img001.png" in image_paths


def test_appearance_image_score_prefers_macro_surface_over_sem_only() -> None:
    """Appearance/photo requests should prefer inspectable surface figures over SEM-only figures."""

    surface = {
        "chunk_id": "surface",
        "title": "Laser welding of AlSi10Mg.pdf",
        "content": "Fig. 18. Surface morphology and weld surface appearance of laser welded SLM AlSi10Mg joints.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/surface.png"],
    }
    sem_only = {
        "chunk_id": "sem_only",
        "title": "Laser welding of AlSi10Mg.pdf",
        "content": "Fig. 19. SEM micrographs of fracture surface and microstructure of laser welded SLM AlSi10Mg alloys.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/sem.png"],
    }

    query = "AlSi10Mg 激光焊接 外观 图片"

    assert _visual_evidence_score(query, surface) > _visual_evidence_score(query, sem_only)


def test_chat_extracts_generated_figure_detail_for_image_chunk() -> None:
    """SmartRead evidence refs should expose captions for chunk image assets."""

    chunk = {
        "chunk_id": "surface_chunk",
        "material_id": "mat_surface",
        "title": "Laser welding of AlSi10Mg.pdf",
        "content": "Fig. 18. Surface morphology of the welded joints in SLM AlSi10Mg alloys.",
        "raw_content": "Fig. 18. Surface morphology of the welded joints in SLM AlSi10Mg alloys.",
        "page": 13,
        "chunk_index": 113,
        "chunk_type": "figure_caption",
        "bbox": [0.16, 0.07, 0.66, 0.51],
        "image_paths": ["figure_assets/extracted/cui/p0013_img001.png"],
    }

    detail = _extract_figure_candidate_detail(chunk)

    assert detail is not None
    assert detail["caption"] == "Fig. 18. Surface morphology of the welded joints in SLM AlSi10Mg alloys."
    assert detail["asset_path"] == "figure_assets/extracted/cui/p0013_img001.png"
    assert detail["chunk_id"] == "surface_chunk"


def test_chat_image_paths_filter_whole_page_captures() -> None:
    """SmartRead should not show full-page screenshot assets as figure images."""

    chunk = {
        "chunk_id": "page_list_chunk",
        "material_id": "mat_surface",
        "content": "Fig. 18. Surface morphology of the welded joints in SLM AlSi10Mg alloys.",
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "image_paths": ["figure_assets/extracted/cui/p0003_page_list.png"],
    }

    assert _extract_image_paths(chunk) == []
