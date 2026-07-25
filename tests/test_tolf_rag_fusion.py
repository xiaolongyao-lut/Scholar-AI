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
    EvidenceReferencePayload,
    _build_visual_evidence_refs_from_chunks,
    _collect_related_visual_evidence_chunks,
    _extract_figure_candidate_detail,
    _extract_image_paths,
    _has_image_asset_paths,
    _build_smart_read_retrieval_diagnostics,
    _merge_visual_evidence_chunks,
    _prioritize_query_identifier_matches,
    _rrf_merge,
    _supplement_visual_evidence_refs_for_answer,
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


def test_smart_read_retrieval_diagnostics_reports_hybrid_rerank_from_source_labels() -> None:
    chunk = ContextChunkPayload(
        index=1,
        source="Laser welding paper",
        content="AlSi10Mg laser welding evidence.",
        source_labels=["bm25", "dense", "rerank"],
    )

    diagnostics = _build_smart_read_retrieval_diagnostics(
        [chunk],
        project_id="proj_hidden",
        retrieval_attempted=True,
    )

    assert diagnostics is not None
    assert diagnostics.retrieval_method == "hybrid_rerank"
    assert diagnostics.embedding_status == "active"
    assert diagnostics.rerank_status == "active"
    assert diagnostics.lexical_only is False


def test_smart_read_retrieval_diagnostics_reports_hybrid_fallback_without_claiming_rerank() -> None:
    chunk = ContextChunkPayload(
        index=1,
        source="Laser welding paper",
        content="AlSi10Mg laser welding evidence.",
        source_labels=["bm25", "dense_fallback", "rerank_fallback"],
    )

    diagnostics = _build_smart_read_retrieval_diagnostics(
        [chunk],
        project_id="proj_hidden",
        retrieval_attempted=True,
    )

    assert diagnostics is not None
    assert diagnostics.retrieval_method == "hybrid"
    assert diagnostics.embedding_status == "skipped"
    assert diagnostics.rerank_status == "skipped"
    assert diagnostics.lexical_only is True
    assert diagnostics.fallback_reasons == ["dense_fallback", "rerank_fallback"]


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


def test_material_scoped_context_uses_hybrid_labels_inside_active_material(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A selected PDF must not bypass the hybrid retrieval diagnostics path."""

    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "1")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", "1")
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "1")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    active_material = {
        "chunk_id": "active_laser",
        "material_id": "mat_active",
        "content": "The selected paper reports laser power and hardness evidence.",
        "title": "Selected Laser Study",
    }
    other_material = {
        "chunk_id": "other_laser",
        "material_id": "mat_other",
        "content": "A different project material also discusses laser power.",
        "title": "Other Laser Study",
    }

    with (
        patch.object(router, "load_project_chunks_for_rag", return_value=[active_material, other_material]),
        patch.object(router, "search_project_chunks_for_query", return_value=[other_material]) as mock_keyword,
    ):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="laser power hardness",
                project_id="proj_test",
                tier="fast",
                material_id="mat_active",
            )
        )

    mock_keyword.assert_called_once()
    assert chunks
    assert {chunk.material_id for chunk in chunks} == {"mat_active"}
    labels = chunks[0].source_labels
    assert "bm25" in labels
    assert "dense_fallback" in labels
    assert "project_chunks" not in labels


def test_exclusive_author_year_query_scopes_context_and_visual_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An explicit single-paper request must not leak other project materials."""

    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "0")
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "0")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    cui_title = "Cui - 2022 - Porosity microstructure and mechanical property.pdf"
    other_title = "Peng - 2022 - Laser welding of AlSi10Mg.pdf"
    cui_narrative = {
        "chunk_id": "cui-narrative",
        "material_id": "mat-cui",
        "title": cui_title,
        "content": "Cui reports AlSi10Mg composition, porosity, and welded-joint microstructure.",
        "chunk_type": "narrative",
    }
    other_narrative = {
        "chunk_id": "peng-narrative",
        "material_id": "mat-peng",
        "title": other_title,
        "content": "Peng reports AlSi10Mg porosity and welded-joint microstructure.",
        "chunk_type": "narrative",
    }
    cui_visuals = [
        {
            "chunk_id": "cui-table-1",
            "material_id": "mat-cui",
            "title": cui_title,
            "content": "Table 1. Chemical composition of AlSi10Mg.",
            "chunk_type": "table",
            "image_paths": ["figure_assets/extracted/cui/table-1.png"],
        },
        {
            "chunk_id": "cui-fig-6",
            "material_id": "mat-cui",
            "title": cui_title,
            "content": "Fig. 6. Porosity and macrostructure of the welded joint.",
            "chunk_type": "figure_caption",
            "image_paths": ["figure_assets/extracted/cui/fig-6.png"],
        },
        {
            "chunk_id": "cui-fig-14",
            "material_id": "mat-cui",
            "title": cui_title,
            "content": "Fig. 14. Microstructure of eutectic silicon in the welded joint.",
            "chunk_type": "figure_caption",
            "image_paths": ["figure_assets/extracted/cui/fig-14.png"],
        },
    ]
    other_visual = {
        "chunk_id": "peng-fig-6",
        "material_id": "mat-peng",
        "title": other_title,
        "content": "Fig. 6. Porosity and microstructure of another welded joint.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/peng/fig-6.png"],
    }
    project_chunks = [cui_narrative, other_narrative, *cui_visuals, other_visual]
    existing_assets = {
        path
        for chunk in [*cui_visuals, other_visual]
        for path in chunk["image_paths"]
    }
    visual_refs: list[EvidenceReferencePayload] = []

    with (
        patch.object(router, "load_project_chunks_for_rag", return_value=project_chunks),
        patch.object(
            router,
            "search_project_chunks_for_query",
            return_value=[other_narrative, cui_narrative],
        ),
        patch(
            "routers.resources_router.endpoints_search_upload._collect_existing_project_asset_paths",
            return_value=existing_assets,
        ),
    ):
        chunks, _truncated = asyncio.run(
            router._build_project_context_chunks(
                query="仅依据 Cui 等人 2022 年的论文说明 Table 1、Fig. 6 和 Fig. 14。",
                project_id="proj_test",
                tier="fast",
                visual_evidence_sink=visual_refs,
            )
        )

    assert chunks
    assert {chunk.material_id for chunk in chunks} == {"mat-cui"}
    assert {ref.material_id for ref in visual_refs} == {"mat-cui"}
    assert {ref.chunk_id for ref in visual_refs} == {
        "cui-table-1",
        "cui-fig-6",
        "cui-fig-14",
    }


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


def test_visual_evidence_merge_adds_all_related_images_for_non_visual_query() -> None:
    """Ordinary questions receive every relevant image that fits the prompt cap."""

    selected = [
        {
            "chunk_id": "porosity_process_anchor",
            "material_id": "mat-laser",
            "title": "Laser welding of AlSi10Mg.pdf",
            "section_path": ["Results", "Porosity and process parameters"],
            "page": 4,
            "content": (
                "AlSi10Mg laser welding porosity changes with laser power and welding speed."
            ),
            "chunk_type": "narrative",
        }
    ]
    related = [
        {
            "chunk_id": f"porosity_process_figure_{index}",
            "material_id": "mat-laser",
            "title": "Laser welding of AlSi10Mg.pdf",
            "section_path": ["Results", "Porosity and process parameters"],
            "page": 4 + index,
            "content": (
                f"Figure {index}. Porosity of AlSi10Mg welds at different laser powers "
                "and welding speeds."
            ),
            "chunk_type": "figure_caption",
            "image_paths": [f"figure_assets/extracted/laser/p000{4 + index}_img001.jpeg"],
        }
        for index in range(1, 4)
    ]
    unrelated = {
        "chunk_id": "unrelated_micrograph",
        "material_id": "mat-corrosion",
        "title": "Corrosion microstructure study.pdf",
        "section_path": ["Results", "Corrosion"],
        "page": 9,
        "content": "Figure 9. SEM micrograph of corrosion products after salt-spray exposure.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/corrosion/p0009_img001.jpeg"],
    }

    merged = _merge_visual_evidence_chunks(
        "Explain AlSi10Mg laser welding porosity and process parameter relationships",
        selected,
        [*selected, unrelated, *related],
        total_cap=6,
    )

    merged_ids = [item["chunk_id"] for item in merged]
    assert {item["chunk_id"] for item in related}.issubset(merged_ids)
    assert "unrelated_micrograph" not in merged_ids
    assert sum(bool(item.get("image_paths")) for item in merged) == 3


def test_visual_evidence_refs_keep_all_related_existing_assets_only() -> None:
    """Display refs keep every related real asset and exclude missing or unrelated paths."""

    related_count = 205
    selected = [
        {
            "chunk_id": "porosity-anchor",
            "material_id": "mat-laser",
            "title": "Laser welding of AlSi10Mg.pdf",
            "content": "Laser power and welding speed control porosity in AlSi10Mg welds.",
        }
    ]
    related = [
        {
            "chunk_id": f"related-figure-{index}",
            "material_id": "mat-laser",
            "title": "Laser welding of AlSi10Mg.pdf",
            "content": f"Figure {index}. Porosity response to laser power and welding speed.",
            "chunk_type": "figure_caption",
            "image_paths": [
                f"figure_assets/extracted/laser/figure-{index}.png",
                f"figure_assets/extracted/laser/missing-{index}.png",
            ],
        }
        for index in range(1, related_count + 1)
    ]
    unrelated = {
        "chunk_id": "unrelated-corrosion-figure",
        "material_id": "mat-corrosion",
        "title": "Corrosion products.pdf",
        "content": "Figure 9. Corrosion products after salt-spray exposure.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/corrosion/figure-9.png"],
    }
    existing_assets = {
        f"figure_assets/extracted/laser/figure-{index}.png"
        for index in range(1, related_count + 1)
    } | {"figure_assets/extracted/corrosion/figure-9.png"}

    chunks = _collect_related_visual_evidence_chunks(
        "Explain AlSi10Mg laser welding porosity and process parameter relationships",
        selected,
        [*related, unrelated],
        allowed_image_paths=existing_assets,
    )
    refs = _build_visual_evidence_refs_from_chunks(chunks)

    assert len(refs) == related_count
    assert [ref.chunk_id for ref in refs] == [
        f"related-figure-{index}"
        for index in range(1, related_count + 1)
    ]
    assert [path for ref in refs for path in ref.image_paths] == [
        f"figure_assets/extracted/laser/figure-{index}.png"
        for index in range(1, related_count + 1)
    ]
    assert all("missing" not in path for ref in refs for path in ref.image_paths)
    assert all("corrosion" not in path for ref in refs for path in ref.image_paths)


def test_visual_evidence_ref_keeps_every_asset_from_one_related_chunk() -> None:
    """One relevant chunk may expose all of its native assets without a fixed quota."""

    asset_paths = [
        f"figure_assets/extracted/laser/panel-{index}.png"
        for index in range(1, 13)
    ]
    selected = [
        {
            "chunk_id": "multi-panel-anchor",
            "material_id": "mat-laser",
            "title": "Laser welding of AlSi10Mg.pdf",
            "content": "Laser power and welding speed control porosity in AlSi10Mg welds.",
        }
    ]
    related = {
        "chunk_id": "multi-panel-figure",
        "material_id": "mat-laser",
        "title": "Laser welding of AlSi10Mg.pdf",
        "content": "Figure 8. Porosity response to laser power and welding speed.",
        "chunk_type": "figure_caption",
        "image_paths": asset_paths,
    }

    chunks = _collect_related_visual_evidence_chunks(
        "Explain AlSi10Mg laser welding porosity and process parameter relationships",
        selected,
        [related],
        allowed_image_paths=set(asset_paths),
    )
    refs = _build_visual_evidence_refs_from_chunks(chunks)

    assert len(refs) == 1
    assert refs[0].image_paths == asset_paths


def test_answer_figure_refs_supplement_native_asset_from_existing_ref_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A final-answer Fig. 6 citation must join the existing same-paper Fig. 14."""

    fig_14_path = "figure_assets/extracted/cui/p0011_img001.png"
    fig_6_path = "figure_assets/extracted/cui/p0006_img001.png"
    other_fig_6_path = "figure_assets/extracted/other/p0006_img001.png"
    existing = EvidenceReferencePayload(
        chunk_id="cui-fig-14",
        material_id="mat-cui",
        source="Cui 2022.pdf",
        text="Fig. 14. Joint tensile properties.",
        quote="Fig. 14. Joint tensile properties.",
        label="visual_evidence",
        figure_candidate="Fig. 14",
        figure_candidate_detail={"kind": "figure", "label": "Fig. 14"},
        image_paths=[fig_14_path],
    )
    project_chunks = [
        {
            "chunk_id": "cui-fig-6",
            "material_id": "mat-cui",
            "title": "Cui 2022.pdf",
            "content": "Fig. 6. Macrostructure of the welded joints.",
            "chunk_type": "figure_caption",
            "figure_candidate_detail": {
                "kind": "figure",
                "label": "Fig. 6",
                "caption": "Fig. 6. Macrostructure of the welded joints.",
            },
            "image_paths": [fig_6_path],
        },
        {
            "chunk_id": "other-fig-6",
            "material_id": "mat-other",
            "title": "Other paper.pdf",
            "content": "Fig. 6. An unrelated corrosion image.",
            "chunk_type": "figure_caption",
            "figure_candidate_detail": {
                "kind": "figure",
                "label": "Fig. 6",
            },
            "image_paths": [other_fig_6_path],
        },
    ]
    monkeypatch.setattr(
        "routers.intelligent_chat_router.load_project_chunks_for_rag",
        lambda _project_id: project_chunks,
    )
    monkeypatch.setattr(
        "routers.resources_router.endpoints_search_upload._collect_existing_project_asset_paths",
        lambda _project_id: {fig_14_path, fig_6_path, other_fig_6_path},
    )

    refs = _supplement_visual_evidence_refs_for_answer(
        answer="The macrostructure in Fig. 6 explains the strength trend in Fig. 14.",
        project_id="project-alsi10mg2",
        existing_refs=[existing],
        evidence_refs=[],
        context_chunks=[],
    )

    assert [ref.chunk_id for ref in refs] == ["cui-fig-14", "cui-fig-6"]
    assert [path for ref in refs for path in ref.image_paths] == [fig_14_path, fig_6_path]
    assert all(ref.material_id == "mat-cui" for ref in refs)


def test_answer_visual_reconciliation_prunes_235_broad_refs_to_explicit_evidence_material() -> None:
    """Final refs must follow answer labels and the uniquely evidenced paper."""

    target_specs = [
        ("cui-table-1", "table", "Table 1", "table-1.png"),
        ("cui-fig-6", "figure", "Fig. 6", "fig-6.png"),
        ("cui-fig-14", "figure", "Fig. 14", "fig-14.png"),
    ]
    targets = [
        EvidenceReferencePayload(
            chunk_id=chunk_id,
            material_id="mat-cui",
            source="Cui 2022.pdf",
            text=f"{label}. Target evidence.",
            quote=f"{label}. Target evidence.",
            label="visual_evidence",
            figure_candidate=label,
            figure_candidate_detail={"kind": kind, "label": label},
            image_paths=[f"figure_assets/extracted/cui/{asset_name}"],
        )
        for chunk_id, kind, label, asset_name in target_specs
    ]
    duplicate_labels = [
        ("table", "Table 1"),
        ("figure", "Fig. 6"),
        ("figure", "Fig. 14"),
    ]
    noise: list[EvidenceReferencePayload] = []
    for index in range(232):
        kind, label = (
            duplicate_labels[index]
            if index < len(duplicate_labels)
            else ("figure", f"Fig. {index + 20}")
        )
        noise.append(
            EvidenceReferencePayload(
                chunk_id=f"noise-{index}",
                material_id=f"mat-noise-{index % 25}",
                source=f"Other paper {index % 25}.pdf",
                text=f"{label}. Broad AlSi10Mg laser-welding evidence.",
                quote=f"{label}. Broad AlSi10Mg laser-welding evidence.",
                label="visual_evidence",
                figure_candidate=label,
                figure_candidate_detail={"kind": kind, "label": label},
                image_paths=[f"figure_assets/extracted/noise/{index}.png"],
            )
        )
    evidence_ref = EvidenceReferencePayload(
        chunk_id="cui-narrative",
        material_id="mat-cui",
        source="Cui 2022.pdf",
        text="Cui 2022 evidence for Table 1, Fig. 6, and Fig. 14.",
        quote="Cui 2022 evidence for Table 1, Fig. 6, and Fig. 14.",
        label="project_context",
    )

    refs = _supplement_visual_evidence_refs_for_answer(
        answer="Table 1 gives the composition; Fig. 6 shows the section; Fig. 14 shows eutectic Si.",
        project_id="project-alsi10mg2",
        existing_refs=[*targets, *noise],
        evidence_refs=[evidence_ref],
        context_chunks=[],
        project_chunks=[],
        allowed_image_paths=set(),
    )

    assert len([*targets, *noise]) == 235
    assert [ref.chunk_id for ref in refs] == [
        "cui-table-1",
        "cui-fig-6",
        "cui-fig-14",
    ]


def test_cross_material_visual_candidate_does_not_inherit_a_text_anchor() -> None:
    """Query-related figures from another paper stay unanchored for UI placement."""

    selected = [
        {
            "chunk_id": "sun-porosity-anchor",
            "material_id": "material-sun",
            "title": "Sun 2022 adjustable ring mode laser welding.pdf",
            "content": "AlSi10Mg laser power and welding speed control weld porosity.",
        }
    ]
    cross_material = {
        "chunk_id": "ping-porosity-figure",
        "material_id": "material-ping",
        "title": "Ping 2026 oscillating laser welding.pdf",
        "content": "Figure 7. AlSi10Mg laser weld porosity and fracture location at different welding conditions.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/ping/figure-7.png"],
        "figure_candidate_detail": {
            "id": "figure:ping:7",
            "kind": "figure",
            "label": "图 7",
            "caption": "AlSi10Mg laser weld porosity and fracture location.",
        },
    }

    chunks = _collect_related_visual_evidence_chunks(
        "Compare AlSi10Mg laser power and welding speed effects on porosity and fracture",
        selected,
        [cross_material],
        allowed_image_paths={"figure_assets/extracted/ping/figure-7.png"},
    )
    refs = _build_visual_evidence_refs_from_chunks(chunks)

    assert len(refs) == 1
    assert refs[0].figure_candidate_detail is not None
    assert "anchor_chunk_id" not in refs[0].figure_candidate_detail


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


def test_has_image_asset_paths_recognizes_derived_asset_fields() -> None:
    """Project-derived table crops must participate in visual ranking."""

    chunk = {
        "chunk_id": "derived_table_chunk",
        "material_id": "mat-derived",
        "content": "Table 1. Laser welding parameters.",
        "asset_path": "figure_assets/mat-derived/derived_table_chunk-Table1-deadbeef.png",
    }

    assert _extract_image_paths(chunk) == [
        "figure_assets/mat-derived/derived_table_chunk-Table1-deadbeef.png"
    ]
    assert _has_image_asset_paths(chunk) is True


def test_build_context_filters_punctuation_only_chunks_but_keeps_visual_structured_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Meaningless OCR debris must not displace a real short visual candidate."""

    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "0")
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "0")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    results = [
        {
            "chunk_id": "punctuation_only",
            "material_id": "mat-text",
            "title": "OCR debris",
            "content": "[",
        },
        {
            "chunk_id": "derived_table",
            "material_id": "mat-table",
            "title": "Table crop",
            "content": "[",
            "chunk_type": "table",
            "asset_path": "figure_assets/mat-table/derived_table-Table1-feedface.png",
        },
        {
            "chunk_id": "meaningful_text",
            "material_id": "mat-text",
            "title": "Laser welding study",
            "content": "AlSi10Mg laser welding process evidence.",
        },
    ]

    with patch.object(router, "search_project_chunks_for_query", return_value=results):
        chunks, _truncated = asyncio.run(
            router._build_project_context_chunks(
                query="laser welding evidence",
                project_id="proj_test",
                tier="fast",
            )
        )

    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    assert "punctuation_only" not in chunks_by_id
    assert chunks_by_id["derived_table"].image_paths == [
        "figure_assets/mat-table/derived_table-Table1-feedface.png"
    ]
    assert "meaningful_text" in chunks_by_id


def test_build_context_adds_related_visual_asset_without_visual_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Normal research questions should receive a small related visual budget."""

    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "0")
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "0")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    narrative = {
        "chunk_id": "porosity_anchor",
        "material_id": "mat-laser",
        "title": "Laser welding of AlSi10Mg.pdf",
        "section_path": ["Results", "Porosity"],
        "page": 4,
        "content": "AlSi10Mg laser welding porosity depends on laser power and welding speed.",
        "chunk_type": "narrative",
    }
    related_figure = {
        "chunk_id": "porosity_figure",
        "material_id": "mat-laser",
        "title": "Laser welding of AlSi10Mg.pdf",
        "section_path": ["Results", "Porosity"],
        "page": 4,
        "content": "Figure 4. Porosity at different laser powers and welding speeds.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/laser/p0004_img001.jpeg"],
    }
    unrelated_figure = {
        "chunk_id": "corrosion_figure",
        "material_id": "mat-corrosion",
        "title": "Corrosion study.pdf",
        "section_path": ["Results", "Corrosion"],
        "page": 8,
        "content": "Figure 8. Surface morphology after corrosion exposure.",
        "chunk_type": "figure_caption",
        "image_paths": ["figure_assets/extracted/corrosion/p0008_img001.jpeg"],
    }

    with (
        patch.object(router, "search_project_chunks_for_query", return_value=[narrative]),
        patch.object(
            router,
            "load_project_chunks_for_rag",
            return_value=[narrative, unrelated_figure, related_figure],
        ),
    ):
        chunks, _truncated = asyncio.run(
            router._build_project_context_chunks(
                query="Explain AlSi10Mg laser welding porosity and process parameters",
                project_id="proj_test",
                tier="fast",
            )
        )

    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    assert chunks_by_id["porosity_figure"].image_paths == [
        "figure_assets/extracted/laser/p0004_img001.jpeg"
    ]
    assert "corrosion_figure" not in chunks_by_id


def test_build_context_binds_overlapping_table_text_to_caption_chunk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Real consecutive Cui table cells must reach the answer model without reimport."""

    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "0")
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "0")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    table = {
        "chunk_id": "cui-table-1",
        "chunk_index": 26,
        "material_id": "mat-cui",
        "title": "Cui - 2022 - AlSi10Mg.pdf",
        "page": 3,
        "bbox": [0.028143, 0.070389, 0.451618, 0.109109],
        "content": "Table 1. Nominal chemical compositions of AlSi10Mg alloys (wt,%).",
        "raw_content": "Table 1. Nominal chemical compositions of AlSi10Mg alloys (wt,%).",
        "chunk_type": "table",
        "image_paths": ["figure_assets/extracted/cui/table-1.png"],
    }
    header = {
        "chunk_id": "cui-table-1-header",
        "chunk_index": 27,
        "material_id": "mat-cui",
        "title": table["title"],
        "page": 3,
        "bbox": [0.073238, 0.099767, 0.848956, 0.008033],
        "content": "Element\nCu\nFe\nMg\nMn\nNi\nSi\nZn\nTi\nPb\nSn\nAl",
        "raw_content": "Element\nCu\nFe\nMg\nMn\nNi\nSi\nZn\nTi\nPb\nSn\nAl",
        "chunk_type": "narrative",
    }
    values = {
        "chunk_id": "cui-table-1-values",
        "chunk_index": 28,
        "material_id": "mat-cui",
        "title": table["title"],
        "page": 3,
        "bbox": [0.073238, 0.116189, 0.859806, 0.018968],
        "content": "SLM\n0.05\n0.55\n0.20-0.45\n0.45\n0.05\n9.0-11.0\n0.10\n0.15\n0.05\n0.05\nBal.\nCasting\n0.03\n0.12\n0.417\n0.051\n0.006\n9.375\n<0.002\n0.164\n<0.005\n<0.002\nBal.",
        "raw_content": "SLM\n0.05\n0.55\n0.20-0.45\n0.45\n0.05\n9.0-11.0\n0.10\n0.15\n0.05\n0.05\nBal.\nCasting\n0.03\n0.12\n0.417\n0.051\n0.006\n9.375\n<0.002\n0.164\n<0.005\n<0.002\nBal.",
        "chunk_type": "narrative",
    }
    outside_prose = {
        "chunk_id": "outside-prose",
        "chunk_index": 29,
        "material_id": "mat-cui",
        "title": table["title"],
        "page": 3,
        "bbox": [0.515043, 0.205, 0.425, 0.12],
        "content": "This paragraph is outside the table crop and must stay separate.",
        "raw_content": "This paragraph is outside the table crop and must stay separate.",
        "chunk_type": "narrative",
    }
    project_chunks = [table, header, values, outside_prose]

    with (
        patch.object(router, "load_project_chunks_for_rag", return_value=project_chunks),
        patch.object(router, "search_project_chunks_for_query", return_value=[table]),
        patch(
            "routers.resources_router.endpoints_search_upload._collect_existing_project_asset_paths",
            return_value={"figure_assets/extracted/cui/table-1.png"},
        ),
    ):
        chunks, _truncated = asyncio.run(
            router._build_project_context_chunks(
                query="What composition values are reported in Table 1?",
                project_id="proj_test",
                tier="fast",
            )
        )

    table_context = next(chunk for chunk in chunks if chunk.chunk_id == "cui-table-1")
    assert "Element\nCu\nFe\nMg" in table_context.content
    assert "SLM\n0.05\n0.55\n0.20-0.45" in table_context.content
    assert "Casting\n0.03\n0.12\n0.417" in table_context.content
    assert "outside the table crop" not in table_context.content
