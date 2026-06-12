"""Lock the structured-sibling inclusion module + chat-router integration.

Two contracts are pinned here:

1. Module-level: ``select_structured_siblings`` returns the right neighbours
   for each anchor narrative, respecting material_id / section_path / page
   matching rules and the max_siblings cap. ``merge_with_siblings`` never
   drops structured chunks that earned their spot via rerank.

2. Chat-router integration: when the flag is off (default), the existing
   ``_build_project_context_chunks`` results are byte-identical. When on,
   structured siblings are appended for narrative anchors that have them.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_CORE = Path(__file__).resolve().parents[1] / "literature_assistant" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from rag_structured_sibling_inclusion import (  # noqa: E402
    DEFAULT_MAX_SIBLINGS,
    DEFAULT_STRUCTURED_TYPES,
    is_sibling_inclusion_enabled,
    merge_with_siblings,
    select_structured_siblings,
)


def _reset_flag_cache() -> None:
    import feature_flags

    if hasattr(feature_flags, "_FLAG_CACHE"):
        feature_flags._FLAG_CACHE = {}


# ---------- Module-level: select_structured_siblings ----------

def test_default_constants_align_with_typical_marker_types() -> None:
    assert "table" in DEFAULT_STRUCTURED_TYPES
    assert "formula" in DEFAULT_STRUCTURED_TYPES
    assert "figure_caption" in DEFAULT_STRUCTURED_TYPES
    assert "narrative" not in DEFAULT_STRUCTURED_TYPES
    assert "heading" not in DEFAULT_STRUCTURED_TYPES
    assert DEFAULT_MAX_SIBLINGS == 2


def test_select_returns_empty_when_no_narrative_anchor() -> None:
    final = [
        {"chunk_id": "t1", "chunk_type": "table", "section_path": ["S1"], "material_id": "m"},
    ]
    pool = [
        {"chunk_id": "t2", "chunk_type": "table", "section_path": ["S1"], "material_id": "m"},
    ]
    assert select_structured_siblings(final, pool) == []


def test_select_pulls_same_section_table_for_narrative_anchor() -> None:
    final = [
        {"chunk_id": "n1", "chunk_type": "narrative", "section_path": ["S1"], "material_id": "m"},
    ]
    pool = [
        {"chunk_id": "n1", "chunk_type": "narrative", "section_path": ["S1"], "material_id": "m"},
        {"chunk_id": "t1", "chunk_type": "table",     "section_path": ["S1"], "material_id": "m"},
        {"chunk_id": "t2", "chunk_type": "table",     "section_path": ["S2"], "material_id": "m"},  # different section
        {"chunk_id": "f1", "chunk_type": "formula",   "section_path": ["S1"], "material_id": "m"},
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=5)
    sib_ids = [s["chunk_id"] for s in sibs]
    assert "t1" in sib_ids
    assert "f1" in sib_ids
    assert "t2" not in sib_ids
    # Each sibling must carry provenance for evidence.
    assert all(s["sibling_anchor"] == "n1" for s in sibs)
    assert all(s["sibling_reason"] == "section_path" for s in sibs)


def test_select_skips_chunks_already_in_final_results() -> None:
    final = [
        {"chunk_id": "n1", "chunk_type": "narrative", "section_path": ["S1"], "material_id": "m"},
        {"chunk_id": "t1", "chunk_type": "table",     "section_path": ["S1"], "material_id": "m"},
    ]
    pool = list(final) + [
        {"chunk_id": "t2", "chunk_type": "table", "section_path": ["S1"], "material_id": "m"},
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=5)
    assert [s["chunk_id"] for s in sibs] == ["t2"]


def test_select_caps_at_max_siblings() -> None:
    final = [
        {"chunk_id": "n1", "chunk_type": "narrative", "section_path": ["S1"], "material_id": "m"},
    ]
    pool = [
        {"chunk_id": "n1", "chunk_type": "narrative", "section_path": ["S1"], "material_id": "m"},
        {"chunk_id": "t1", "chunk_type": "table",     "section_path": ["S1"], "material_id": "m"},
        {"chunk_id": "t2", "chunk_type": "table",     "section_path": ["S1"], "material_id": "m"},
        {"chunk_id": "t3", "chunk_type": "table",     "section_path": ["S1"], "material_id": "m"},
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=2)
    assert len(sibs) == 2


def test_select_falls_back_to_page_match_when_no_section_path() -> None:
    """Legacy PyMuPDF chunks lack section_path; same-page is the next best."""
    final = [
        {"chunk_id": "n1", "chunk_type": "narrative", "page": 5, "material_id": "m"},
    ]
    pool = [
        {"chunk_id": "n1", "chunk_type": "narrative", "page": 5, "material_id": "m"},
        {"chunk_id": "t1", "chunk_type": "table",     "page": 5, "material_id": "m"},
        {"chunk_id": "t2", "chunk_type": "table",     "page": 6, "material_id": "m"},
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=5)
    sib_ids = [s["chunk_id"] for s in sibs]
    assert "t1" in sib_ids
    assert "t2" not in sib_ids
    assert sibs[0]["sibling_reason"] == "same_page"


def test_select_falls_back_to_section_title_when_no_section_path() -> None:
    """Legacy PyMuPDF chunks lack section_path but DO have section_title.
    The fallback chain is section_path > section_title > page, so two
    chunks sharing only a section_title still match — and that beats
    a same-page-but-different-title chunk."""
    final = [
        {
            "chunk_id": "n1",
            "chunk_type": "narrative",
            "section_title": "3. Results",
            "page": 5,
            "material_id": "m",
        },
    ]
    pool = list(final) + [
        {
            "chunk_id": "t_same_title",
            "chunk_type": "table",
            "section_title": "3. Results",
            "page": 7,  # different page
            "material_id": "m",
        },
        {
            "chunk_id": "t_same_page_only",
            "chunk_type": "table",
            "section_title": "4. Discussion",  # different title
            "page": 5,  # same page
            "material_id": "m",
        },
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=5)
    sib_ids = [s["chunk_id"] for s in sibs]
    # section_title match wins; same-page-only must NOT match because
    # both sides have a section_title that disagrees.
    assert "t_same_title" in sib_ids
    assert "t_same_page_only" not in sib_ids
    # Provenance is recorded so the chat layer / evidence reports know
    # which fallback rung the sibling came through.
    section_title_sib = next(s for s in sibs if s["chunk_id"] == "t_same_title")
    assert section_title_sib["sibling_reason"] == "section_title"


def test_select_section_path_wins_over_section_title_when_both_present() -> None:
    """Modern marker chunks have BOTH section_path and section_title. The
    stronger signal (section_path) must be the deciding factor; a chunk
    with matching section_title but mismatched section_path is NOT a
    sibling because the document structure says otherwise."""
    final = [
        {
            "chunk_id": "n1",
            "chunk_type": "narrative",
            "section_path": ["3.2. Mechanical properties"],
            "section_title": "3. Results",  # broader title
            "material_id": "m",
        },
    ]
    pool = list(final) + [
        {
            "chunk_id": "t_path_match",
            "chunk_type": "table",
            "section_path": ["3.2. Mechanical properties"],
            "section_title": "3. Results",
            "material_id": "m",
        },
        {
            "chunk_id": "t_title_only",
            "chunk_type": "table",
            "section_path": ["3.1. Microstructure"],  # different subsection
            "section_title": "3. Results",  # same broader title
            "material_id": "m",
        },
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=5)
    sib_ids = [s["chunk_id"] for s in sibs]
    assert "t_path_match" in sib_ids
    assert "t_title_only" not in sib_ids
    assert sibs[0]["sibling_reason"] == "section_path"


def test_select_does_not_cross_material_boundary() -> None:
    final = [
        {"chunk_id": "n1", "chunk_type": "narrative", "section_path": ["S1"], "material_id": "matA"},
    ]
    pool = list(final) + [
        {"chunk_id": "t_other", "chunk_type": "table", "section_path": ["S1"], "material_id": "matB"},
    ]
    assert select_structured_siblings(final, pool, max_siblings=5) == []


def test_select_handles_non_mapping_inputs_gracefully() -> None:
    """Robust against junk in final_results / pool — should not raise."""
    final = [
        {"chunk_id": "n1", "chunk_type": "narrative", "section_path": ["S1"], "material_id": "m"},
        "not a dict",
        None,
    ]
    pool = [
        {"chunk_id": "t1", "chunk_type": "table", "section_path": ["S1"], "material_id": "m"},
        42,
        ["junk"],
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=5)
    assert [s["chunk_id"] for s in sibs] == ["t1"]


# ---------- Content-aware ranking ----------

def test_select_prefers_table_explicitly_cited_by_narrative() -> None:
    """Anchor narrative mentions 'Table 2' → Table 2 sibling outranks Table 1
    sibling, even though both share the same section. Closes the "Table 1
    drowns out Table 2" failure mode from the real Reis e2e."""
    final = [
        {
            "chunk_id": "n1",
            "chunk_type": "narrative",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "The creep test data are summarised in Table 2 across all three temperatures.",
        },
    ]
    pool = list(final) + [
        {
            "chunk_id": "t1",
            "chunk_type": "table",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "[meta]\nTable 1 EDS data showing the nitrogen concentration.",
        },
        {
            "chunk_id": "t2",
            "chunk_type": "table",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "[meta]\nTable 2 Creep data at 500 C, 600 C and 700 C.",
        },
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=1)
    # max_siblings=1 forces a tiebreak — the cited Table 2 must win.
    assert [s["chunk_id"] for s in sibs] == ["t2"]


def test_select_ranks_multiple_cited_refs_in_narrative_order() -> None:
    """Narrative mentions 'Table 2 ... Fig. 4' — Table 2 must rank ahead of
    Fig 4 when max_siblings forces a choice, because narrative order is the
    proxy for human-author intent."""
    final = [
        {
            "chunk_id": "n1",
            "chunk_type": "narrative",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "The creep rates appear in Table 2, then Fig. 4 plots stress dependence.",
        },
    ]
    pool = list(final) + [
        {
            "chunk_id": "fig4",
            "chunk_type": "figure_caption",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "[meta]\nFig. 4 Stress dependence of the steady-state creep rate.",
        },
        {
            "chunk_id": "table2",
            "chunk_type": "table",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "[meta]\nTable 2 Creep data at 500/600/700 C.",
        },
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=1)
    assert [s["chunk_id"] for s in sibs] == ["table2"]


def test_select_falls_back_to_uncited_siblings_when_capacity_allows() -> None:
    """When max_siblings has room beyond cited siblings, the uncited
    same-section siblings still ride in — they just rank lower."""
    final = [
        {
            "chunk_id": "n1",
            "chunk_type": "narrative",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "Mentions Table 2 only.",
        },
    ]
    pool = list(final) + [
        {
            "chunk_id": "t1",
            "chunk_type": "table",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "[meta]\nTable 1 EDS data.",
        },
        {
            "chunk_id": "t2",
            "chunk_type": "table",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "[meta]\nTable 2 Creep data.",
        },
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=2)
    # Table 2 (cited) first, Table 1 (uncited but same section) second.
    assert [s["chunk_id"] for s in sibs] == ["t2", "t1"]


def test_select_recognises_latex_tag_for_formula_siblings() -> None:
    """Formula chunks don't carry "Table N" / "Fig N"; they use LaTeX
    ``\\tag{N}``. When the narrative cites "Eq. 2", the chunk with
    ``\\tag{2}`` must rank ahead of one with ``\\tag{1}``."""
    final = [
        {
            "chunk_id": "n1",
            "chunk_type": "narrative",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "The steady-state rate follows Eq. 2.",
        },
    ]
    pool = list(final) + [
        {
            "chunk_id": "f1",
            "chunk_type": "formula",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "[meta]\nt_p = A sigma^m \\tag{1}",
        },
        {
            "chunk_id": "f2",
            "chunk_type": "formula",
            "section_path": ["S1"],
            "material_id": "m",
            "content": "[meta]\n\\dot\\varepsilon_s = B sigma^n \\tag{2}",
        },
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=1)
    assert [s["chunk_id"] for s in sibs] == ["f2"]


def test_select_tags_sibling_with_source_labels_and_hint() -> None:
    """Siblings must be tagged so the LLM / UI / answer judge can tell them
    apart from rerank-decided chunks. The chat-router copies source_labels
    onto ContextChunkPayload, which surfaces in the prompt builder."""
    final = [
        {"chunk_id": "n1", "chunk_type": "narrative", "section_path": ["S1"], "material_id": "m"},
    ]
    pool = list(final) + [
        {"chunk_id": "t1", "chunk_type": "table", "section_path": ["S1"], "material_id": "m"},
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=5)
    assert sibs and "structured_sibling" in sibs[0]["source_labels"]
    assert sibs[0]["source_hint"] == "structured_sibling"


def test_select_preserves_existing_source_labels_when_tagging() -> None:
    final = [
        {"chunk_id": "n1", "chunk_type": "narrative", "section_path": ["S1"], "material_id": "m"},
    ]
    pool = list(final) + [
        {
            "chunk_id": "t1",
            "chunk_type": "table",
            "section_path": ["S1"],
            "material_id": "m",
            "source_labels": ["bm25", "dense"],
            "source_hint": "bm25+dense",
        },
    ]
    sibs = select_structured_siblings(final, pool, max_siblings=5)
    assert sibs
    labels = sibs[0]["source_labels"]
    assert labels == ["bm25", "dense", "structured_sibling"]
    assert sibs[0]["source_hint"] == "bm25+dense+structured_sibling"


# ---------- Module-level: merge_with_siblings ----------

def test_merge_appends_when_capacity_allows() -> None:
    base = [{"chunk_id": "a", "chunk_type": "narrative"}, {"chunk_id": "b", "chunk_type": "narrative"}]
    sibs = [{"chunk_id": "t1", "chunk_type": "table"}]
    merged = merge_with_siblings(base, sibs, total_cap=10)
    assert [c["chunk_id"] for c in merged] == ["a", "b", "t1"]


def test_merge_displaces_narrative_when_at_cap() -> None:
    base = [
        {"chunk_id": "a", "chunk_type": "narrative"},
        {"chunk_id": "b", "chunk_type": "narrative"},
        {"chunk_id": "c", "chunk_type": "narrative"},
    ]
    sibs = [{"chunk_id": "t1", "chunk_type": "table"}]
    merged = merge_with_siblings(base, sibs, total_cap=3)
    # Lowest-ranked narrative ('c') should be dropped to make room for t1.
    assert "c" not in {c["chunk_id"] for c in merged}
    assert "t1" in {c["chunk_id"] for c in merged}
    assert len(merged) == 3


def test_merge_never_displaces_structured_already_in_base() -> None:
    base = [
        {"chunk_id": "n1", "chunk_type": "narrative"},
        {"chunk_id": "t_kept", "chunk_type": "table"},  # earned via rerank
    ]
    sibs = [
        {"chunk_id": "t_sib1", "chunk_type": "table"},
        {"chunk_id": "t_sib2", "chunk_type": "table"},
    ]
    merged = merge_with_siblings(base, sibs, total_cap=2)
    ids = {c["chunk_id"] for c in merged}
    # t_kept must NOT be dropped to make room for a sibling.
    assert "t_kept" in ids
    # n1 (the only narrative) should be dropped instead.
    assert "n1" not in ids
    # Cannot fit both siblings; takes one.
    assert len(merged) == 2


def test_merge_with_empty_siblings_is_passthrough() -> None:
    base = [{"chunk_id": "a", "chunk_type": "narrative"}]
    assert merge_with_siblings(base, [], total_cap=10) == base


def test_merge_inserts_sibling_immediately_after_anchor() -> None:
    """When a sibling carries a ``sibling_anchor``, it lands right after its
    anchor — NOT at the tail. The chat-router truncate loop walks chunks in
    order and stops on max_chars; inserting after the anchor gives the
    sibling priority over downstream narrative entries that would otherwise
    eat the budget."""
    base = [
        {"chunk_id": "n1", "chunk_type": "narrative"},
        {"chunk_id": "n2", "chunk_type": "narrative"},
        {"chunk_id": "n3", "chunk_type": "narrative"},
    ]
    sibs = [
        {"chunk_id": "t1", "chunk_type": "table", "sibling_anchor": "n1"},
        {"chunk_id": "t2", "chunk_type": "table", "sibling_anchor": "n2"},
    ]
    merged = merge_with_siblings(base, sibs, total_cap=10)
    ids = [c["chunk_id"] for c in merged]
    # Each sibling immediately follows its anchor.
    assert ids.index("t1") == ids.index("n1") + 1
    assert ids.index("t2") == ids.index("n2") + 1
    # And the original narratives are still all present (no displacement
    # when capacity allows).
    assert {"n1", "n2", "n3"}.issubset(set(ids))


def test_merge_without_anchor_id_falls_back_to_tail_append() -> None:
    base = [{"chunk_id": "n1", "chunk_type": "narrative"}]
    sibs = [{"chunk_id": "t1", "chunk_type": "table"}]  # no sibling_anchor
    merged = merge_with_siblings(base, sibs, total_cap=10)
    assert [c["chunk_id"] for c in merged] == ["n1", "t1"]


def test_merge_validates_total_cap() -> None:
    with pytest.raises(ValueError):
        merge_with_siblings([], [], total_cap=0)
    with pytest.raises(ValueError):
        merge_with_siblings([], [], total_cap=-1)


# ---------- Feature flag wiring ----------

def test_sibling_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", raising=False)
    _reset_flag_cache()
    assert is_sibling_inclusion_enabled() is False


def test_sibling_flag_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "1")
    _reset_flag_cache()
    assert is_sibling_inclusion_enabled() is True

    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()
    assert is_sibling_inclusion_enabled() is False


# ---------- Chat-router integration ----------

def test_router_flag_off_does_not_call_select_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", raising=False)
    _reset_flag_cache()

    from routers import intelligent_chat_router as router
    import rag_structured_sibling_inclusion as sibling_mod

    fake_rag = [
        {"chunk_id": "n1", "chunk_type": "narrative", "content": "narrative", "title": "t"},
    ]

    with (
        patch.object(router, "search_project_chunks_for_query", return_value=fake_rag),
        patch.object(sibling_mod, "select_structured_siblings") as mock_select,
    ):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="anything", project_id="proj_test", tier="fast"
            )
        )
        mock_select.assert_not_called()
        assert [c.chunk_id for c in chunks] == ["n1"]


def test_router_flag_on_appends_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "1")
    monkeypatch.delenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", raising=False)
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    fake_rag = [
        {
            "chunk_id": "n1",
            "chunk_type": "narrative",
            "content": "narrative body",
            "title": "Paper title",
            "material_id": "m",
            "section_path": ["S1"],
        },
    ]
    fake_pool = list(fake_rag) + [
        {
            "chunk_id": "t1",
            "chunk_type": "table",
            "content": "table data here",
            "title": "Paper title",
            "material_id": "m",
            "section_path": ["S1"],
        },
    ]

    # Force the inclusion flag on regardless of override.json.
    monkeypatch.setattr(router, "_structured_sibling_inclusion_enabled", lambda: True)
    monkeypatch.setattr(router, "_hybrid_retrieval_enabled", lambda: False)
    monkeypatch.setattr(router, "_tolf_context_enabled", lambda: False)

    with (
        patch.object(router, "search_project_chunks_for_query", return_value=fake_rag),
        patch.object(router, "load_project_chunks_for_rag", return_value=fake_pool),
    ):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="anything", project_id="proj_test", tier="fast"
            )
        )
        chunk_ids = [c.chunk_id for c in chunks]
        assert "n1" in chunk_ids
        assert "t1" in chunk_ids


def test_router_structured_chunks_get_budget_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long narrative chunks must not starve a structured chunk down to a
    metadata-header sliver. tier=fast has max_chars=2000; without the
    reservation, a 1800-char narrative leaves 200 chars total for everything
    after it — most of which is chunk-header boilerplate. The reservation
    is computed as min(structured_count * per_floor, max_chars // 2)
    where per_floor = clamp(max_chars // 8, 400, 1200)."""

    monkeypatch.delenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", raising=False)
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    # max_chars for "fast" is 2000. Without reservation: narrative eats
    # 1800, table is left with 200. With reservation (per_floor=400
    # since 2000//8=250 → clamped to 400; structured_count=1 → reserve=400):
    # narrative gets 1600 max, table sees 400+ from the reserved pool.
    long_narrative_body = "x" * 1800
    table_body = "y" * 1500  # bigger than what would fit without reservation

    rag = [
        {
            "chunk_id": "n1",
            "chunk_type": "narrative",
            "content": long_narrative_body,
            "title": "Paper",
            "material_id": "m",
        },
        {
            "chunk_id": "t1",
            "chunk_type": "table",
            "content": table_body,
            "title": "Paper",
            "material_id": "m",
        },
    ]

    monkeypatch.setattr(router, "_hybrid_retrieval_enabled", lambda: False)
    monkeypatch.setattr(router, "_tolf_context_enabled", lambda: False)
    monkeypatch.setattr(router, "_structured_sibling_inclusion_enabled", lambda: False)

    with patch.object(router, "search_project_chunks_for_query", return_value=rag):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="anything", project_id="proj_test", tier="fast"
            )
        )

    chunk_by_id = {c.chunk_id: c for c in chunks}
    assert "n1" in chunk_by_id
    assert "t1" in chunk_by_id
    # The structured chunk must hold at least its per_floor (=400 here),
    # not the leftover sliver after the narrative.
    assert len(chunk_by_id["t1"].content) >= 400
    # The narrative was clamped by max_chars - reserve = 2000 - 400 = 1600.
    assert len(chunk_by_id["n1"].content) <= 1600
