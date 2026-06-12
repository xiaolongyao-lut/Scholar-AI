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
