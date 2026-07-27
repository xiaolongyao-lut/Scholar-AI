from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from literature_assistant.core.layers.g_layer_academic_generator import AcademicScorer


class _RecordingCache:
    def __init__(self, fetched_result: object = None) -> None:
        self.fetched_result = fetched_result
        self.fetches: list[dict[str, str]] = []
        self.commits: list[dict[str, object]] = []

    async def fetch(self, *, query: str, domain: str) -> object:
        self.fetches.append({"query": query, "domain": domain})
        return self.fetched_result

    async def commit(
        self,
        *,
        query: str,
        result: object,
        domain: str,
        confidence: float,
    ) -> object:
        self.commits.append(
            {
                "query": query,
                "result": result,
                "domain": domain,
                "confidence": confidence,
            }
        )
        return None


class _KeyedCache:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.fetches: list[str] = []
        self.commits: list[str] = []

    async def fetch(self, *, query: str, domain: str) -> object:
        assert domain == "academic_scoring"
        self.fetches.append(query)
        return self.values.get(query)

    async def commit(
        self,
        *,
        query: str,
        result: object,
        domain: str,
        confidence: float,
    ) -> object:
        assert domain == "academic_scoring"
        assert confidence == 0.88
        self.commits.append(query)
        self.values[query] = result
        return None


class _LLMUseProbe:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def extract_mechanisms(self, source_text: str, goal: str) -> list[object]:
        self.calls.append("extract_mechanisms")
        return []

    def classify_claim_boundary(self, claim: str, source_text: str) -> dict[str, object]:
        self.calls.append("classify_claim_boundary")
        return {"boundary_type": "unknown", "confidence": 0.0}

    def extract_innovation_points(self, source_text: str, goal: str) -> list[object]:
        self.calls.append("extract_innovation_points")
        return []

    def verify_multimodal_support(self, claim: str, caption: str) -> float:
        self.calls.append("verify_multimodal_support")
        return 0.5

    def _chat(
        self,
        prompt: str,
        *,
        task: str,
        overrides: dict[str, object] | None = None,
        response_format: dict[str, object] | None = None,
    ) -> object:
        self.calls.append("_chat")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Unexpected LLM result"))]
        )


class _ThreadRecordingChatAdapter:
    def __init__(self) -> None:
        self.call_thread_id: int | None = None
        self.calls: list[dict[str, object]] = []

    def _chat(
        self,
        prompt: str,
        *,
        task: str,
        overrides: dict[str, object] | None = None,
        response_format: dict[str, object] | None = None,
    ) -> object:
        self.call_thread_id = threading.get_ident()
        self.calls.append(
            {
                "prompt": prompt,
                "task": task,
                "overrides": overrides,
                "response_format": response_format,
            }
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Synthesized theme"))]
        )


def test_theme_synthesis_offloads_sync_chat_on_cache_miss() -> None:
    cache = _RecordingCache()
    scorer = AcademicScorer(
        goal="grain refinement",
        enable_llm=False,
        cache_manager=cache,
    )
    adapter = _ThreadRecordingChatAdapter()
    setattr(scorer, "ai_adapter", adapter)
    scorer.use_llm = True
    event_loop_thread_id = threading.get_ident()

    themes = asyncio.run(
        scorer._synthesize_themes(
            [
                {
                    "claim": "Fine grains improve strength.",
                    "point_type": "result",
                    "linked_figures": [],
                    "linked_tables": [],
                }
            ]
        )
    )

    assert themes[0]["summary"] == "Synthesized theme"
    assert adapter.calls[0]["task"] == "summarize"
    assert adapter.call_thread_id is not None
    assert adapter.call_thread_id != event_loop_thread_id
    assert cache.commits[0]["result"] == "Synthesized theme"


def test_complete_analysis_cache_returns_unchanged_without_side_effects() -> None:
    cached_result: dict[str, object] = {
        "goal": "grain refinement",
        "status": "analysis_complete",
        "writing_points": [{"writing_point_id": "cached-wp"}],
        "selected_writing_points": [{"writing_point_id": "cached-wp"}],
        "semantic_themes": [{"theme_title": "Cached theme"}],
        "selected_figures": [{"figure_id": "cached-figure"}],
        "selected_tables": [{"table_id": "cached-table"}],
        "cache_marker": {"source": "academic_scoring"},
    }
    cache = _RecordingCache(cached_result)
    scorer = AcademicScorer(
        goal="grain refinement",
        enable_llm=False,
        cache_manager=cache,
    )
    llm_probe = _LLMUseProbe()
    setattr(scorer, "ai_adapter", llm_probe)
    scorer.use_llm = True

    result = asyncio.run(
        scorer.analyze_bound_data(
            {
                "chunks": [
                    {
                        "chunk_id": "chunk-1",
                        "text": (
                            "Fine grains improve strength and fatigue resistance "
                            "through grain-boundary strengthening."
                        ),
                        "section_title": "Results",
                        "page": 1,
                    }
                ],
                "figures": [],
                "tables": [],
                "relation_edges": [],
            }
        )
    )

    assert result == cached_result
    assert result["cache_marker"] == {"source": "academic_scoring"}
    assert len(cache.fetches) == 1
    assert cache.fetches[0]["domain"] == "academic_scoring"
    cache_key = cache.fetches[0]["query"]
    assert cache_key.startswith("academic-scoring-v2:")
    assert len(cache_key.rsplit(":", maxsplit=1)[1]) == 64
    assert cache.commits == []
    assert llm_probe.calls == []


def test_analysis_cache_separates_equal_count_inputs_by_content() -> None:
    cache = _KeyedCache()
    scorer = AcademicScorer(
        goal="grain refinement",
        enable_llm=False,
        cache_manager=cache,
    )
    first_text = (
        "Fine grains improve fatigue resistance through grain-boundary strengthening."
    )
    second_text = (
        "Coarse grains reduce fatigue resistance under cyclic loading conditions."
    )

    first = asyncio.run(
        scorer.analyze_bound_data(
            {
                "chunks": [{"chunk_id": "chunk-1", "text": first_text, "page": 1}],
                "figures": [],
                "tables": [],
                "relation_edges": [],
            }
        )
    )
    second = asyncio.run(
        scorer.analyze_bound_data(
            {
                "chunks": [{"chunk_id": "chunk-2", "text": second_text, "page": 1}],
                "figures": [],
                "tables": [],
                "relation_edges": [],
            }
        )
    )

    assert first["writing_points"][0]["source_text"] == first_text
    assert second["writing_points"][0]["source_text"] == second_text
    assert len(cache.commits) == 2
    assert cache.commits[0] != cache.commits[1]


def test_analysis_cache_rejects_a_complete_result_for_another_goal() -> None:
    cached_result: dict[str, object] = {
        "goal": "unrelated cached goal",
        "status": "analysis_complete",
        "writing_points": [],
        "selected_writing_points": [],
        "semantic_themes": [],
        "selected_figures": [],
        "selected_tables": [],
    }
    cache = _RecordingCache(cached_result)
    scorer = AcademicScorer(
        goal="grain refinement",
        enable_llm=False,
        cache_manager=cache,
    )

    result = asyncio.run(scorer.analyze_bound_data({}))

    assert result is not cached_result
    assert result["goal"] == "grain refinement"
    assert len(cache.commits) == 1


@pytest.mark.parametrize(
    "cached_result",
    [
        pytest.param(
            {
                "status": "analysis_complete",
                "writing_points": [],
                "selected_writing_points": [],
                "semantic_themes": [],
                "selected_figures": [],
            },
            id="missing-required-list",
        ),
        pytest.param(
            {
                "status": "analysis_complete",
                "writing_points": [],
                "selected_writing_points": [],
                "semantic_themes": "not-a-list",
                "selected_figures": [],
                "selected_tables": [],
            },
            id="non-list-required-field",
        ),
    ],
)
def test_invalid_analysis_cache_recomputes_empty_input_and_commits(
    cached_result: dict[str, object],
) -> None:
    cache = _RecordingCache(cached_result)
    scorer = AcademicScorer(
        goal="grain refinement",
        enable_llm=False,
        cache_manager=cache,
    )

    result = asyncio.run(scorer.analyze_bound_data({}))

    assert result is not cached_result
    assert result["goal"] == "grain refinement"
    assert result["status"] == "analysis_complete"
    assert result["writing_points"] == []
    assert result["selected_writing_points"] == []
    assert result["semantic_themes"] == []
    assert result["selected_figures"] == []
    assert result["selected_tables"] == []
    assert result["stats_analysis"] == {
        "writing_point_count": 0,
        "selected_writing_point_count": 0,
        "selected_figure_count": 0,
        "selected_table_count": 0,
    }
    assert len(cache.fetches) == 1
    assert cache.fetches[0]["domain"] == "academic_scoring"
    cache_key = cache.fetches[0]["query"]
    assert cache_key.startswith("academic-scoring-v2:")
    assert len(cache_key.rsplit(":", maxsplit=1)[1]) == 64
    assert len(cache.commits) == 1
    assert cache.commits[0]["result"] is result
    assert cache.commits[0] == {
        "query": cache_key,
        "result": result,
        "domain": "academic_scoring",
        "confidence": 0.88,
    }
