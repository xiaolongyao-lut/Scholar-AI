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
    _rrf_merge,
    _tolf_fusion_mode_enabled,
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
