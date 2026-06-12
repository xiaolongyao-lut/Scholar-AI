"""Lock the hybrid_retrieval feature flag added in task #6.

When the flag is on (now the bus default), _build_project_context_chunks
routes RAG candidate generation through _hybrid_search_project (true BM25
+ dense + rerank via ContextAwareRetriever), and only falls back to the
legacy search_project_chunks_for_query when hybrid returns empty.

When the flag is explicitly turned OFF (env var = "0" + cleared override),
behaviour must be byte-identical to the legacy keyword-overlap path: no
hybrid call, no extra retriever construction.

These tests pin the bus-default flip from False → True at the spec level
(see feature_flags.FEATURE_FLAGS['hybrid_retrieval']).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_CORE = Path(__file__).resolve().parents[1] / "literature_assistant" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))


def _reset_flag_cache() -> None:
    import feature_flags

    if hasattr(feature_flags, "_FLAG_CACHE"):
        feature_flags._FLAG_CACHE = {}


def _isolate_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point feature_flags at an empty override file so the bus defaults
    decide the test, not whatever the running session committed to
    runtime_state/feature_flags_override.json."""
    empty = tmp_path / "feature_flags_override.json"
    empty.write_text(json.dumps({"flags": {}, "updated_at": "test"}), encoding="utf-8")
    import feature_flags

    monkeypatch.setattr(feature_flags, "_OVERRIDE_PATH", empty)
    _reset_flag_cache()


# ---------- Flag default / env-var sensitivity ----------

def test_hybrid_retrieval_flag_defaults_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Bus default after the A15+ stable verification: hybrid_retrieval is ON."""
    monkeypatch.delenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", raising=False)
    _isolate_overrides(monkeypatch, tmp_path)
    from routers.intelligent_chat_router import _hybrid_retrieval_enabled

    assert _hybrid_retrieval_enabled() is True


def test_hybrid_retrieval_flag_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_overrides(monkeypatch, tmp_path)
    from routers.intelligent_chat_router import _hybrid_retrieval_enabled

    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "1")
    _reset_flag_cache()
    assert _hybrid_retrieval_enabled() is True

    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "0")
    _reset_flag_cache()
    assert _hybrid_retrieval_enabled() is False


# ---------- Flag-off behaviour: hybrid path not used ----------

def test_flag_off_does_not_call_hybrid_search(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _isolate_overrides(monkeypatch, tmp_path)
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "0")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", "0")
    monkeypatch.setenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", "0")
    monkeypatch.setenv("RAG_STRUCTURED_SIBLING_INCLUSION_ENABLED", "0")
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    fake_rag = [{"chunk_id": "rag_1", "content": "rag hit", "title": "t"}]

    with (
        patch.object(router, "_hybrid_search_project", new_callable=AsyncMock) as mock_hybrid,
        patch.object(router, "search_project_chunks_for_query", return_value=fake_rag),
    ):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="anything", project_id="proj_test", tier="fast"
            )
        )
        mock_hybrid.assert_not_called()
        assert chunks and chunks[0].content.startswith("rag hit")


# ---------- Flag-on behaviour: hybrid path takes over ----------

def test_flag_on_calls_hybrid_search_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "1")
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", raising=False)
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    fake_hybrid = [{"chunk_id": "h_1", "content": "hybrid hit", "title": "t"}]

    with (
        patch.object(router, "_hybrid_search_project", new_callable=AsyncMock, return_value=fake_hybrid) as mock_hybrid,
        patch.object(router, "search_project_chunks_for_query") as mock_legacy,
    ):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="anything", project_id="proj_test", tier="fast"
            )
        )
        mock_hybrid.assert_called_once()
        # Hybrid returned non-empty → legacy must NOT be invoked.
        mock_legacy.assert_not_called()
        assert chunks and chunks[0].content.startswith("hybrid hit")


def test_flag_on_falls_back_to_legacy_on_empty_hybrid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hybrid returns []? Legacy keyword search must still answer."""
    monkeypatch.setenv("INTELLIGENT_CHAT_HYBRID_RETRIEVAL_ENABLED", "1")
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED", raising=False)
    monkeypatch.delenv("INTELLIGENT_CHAT_TOLF_FUSION_MODE_ENABLED", raising=False)
    _reset_flag_cache()

    from routers import intelligent_chat_router as router

    fake_legacy = [{"chunk_id": "leg_1", "content": "legacy hit", "title": "t"}]

    with (
        patch.object(router, "_hybrid_search_project", new_callable=AsyncMock, return_value=[]) as mock_hybrid,
        patch.object(router, "search_project_chunks_for_query", return_value=fake_legacy) as mock_legacy,
    ):
        chunks, _ = asyncio.run(
            router._build_project_context_chunks(
                query="anything", project_id="proj_test", tier="fast"
            )
        )
        mock_hybrid.assert_called_once()
        mock_legacy.assert_called_once()
        assert chunks and chunks[0].content.startswith("legacy hit")


# ---------- _hybrid_search_project safety: no chunks / import error ----------

def test_hybrid_search_project_no_chunks_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from routers import intelligent_chat_router as router

    with patch.object(router, "load_project_chunks_for_rag", return_value=[]):
        result = asyncio.run(router._hybrid_search_project("proj_x", "q", top_k=5))
        assert result == []


def test_hybrid_search_project_blank_query_returns_empty() -> None:
    from routers import intelligent_chat_router as router

    assert asyncio.run(router._hybrid_search_project("proj_x", "", top_k=5)) == []
    assert asyncio.run(router._hybrid_search_project("proj_x", "   ", top_k=5)) == []


def test_hybrid_search_project_retriever_exception_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ContextAwareRetriever.hybrid_search raises, the helper must swallow
    and return [] so the caller falls back to legacy keyword search instead
    of failing the whole chat turn."""
    from routers import intelligent_chat_router as router
    from layers import r_layer_hybrid_retriever as retriever_mod

    fake_chunks = [{"chunk_id": "c1", "content": "x"}]

    class _Boom:
        async def hybrid_search(self, *_args, **_kwargs):
            raise RuntimeError("simulated embedding API down")

    with (
        patch.object(router, "load_project_chunks_for_rag", return_value=fake_chunks),
        patch.object(retriever_mod, "ContextAwareRetriever", _Boom),
    ):
        result = asyncio.run(router._hybrid_search_project("proj_x", "q", top_k=5))
        assert result == []
