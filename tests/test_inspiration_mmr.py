from __future__ import annotations

import inspiration_engine as inspiration_module


def _candidate(
    paper_id: str,
    *,
    score: float,
    embedding: list[float],
    title: str | None = None,
    content: str | None = None,
) -> dict:
    return {
        "paper_id": paper_id,
        "title": title or paper_id,
        "content": content or f"{paper_id} content",
        "score": score,
        "embedding": embedding,
    }


def _chunk(
    paper_id: str,
    *,
    title: str,
    content: str,
    embedding: list[float],
) -> dict:
    return {
        "material_id": paper_id,
        "title": title,
        "chunk_index": 0,
        "content": content,
        "embedding": embedding,
    }


def test_mmr_returns_only_one_candidate_when_all_candidates_share_a_paper() -> None:
    query_emb = [1.0, 0.0]
    candidates = [
        _candidate("paper-a", score=0.99, embedding=[1.0, 0.0]),
        _candidate("paper-a", score=0.98, embedding=[0.98, 0.02]),
        _candidate("paper-a", score=0.97, embedding=[0.97, 0.03]),
        _candidate("paper-a", score=0.96, embedding=[0.96, 0.04]),
    ]

    selected = inspiration_module._mmr_select(candidates, query_emb, k=5, lam=0.7)

    assert [item["paper_id"] for item in selected] == ["paper-a"]


def test_mmr_matches_top_k_when_every_candidate_comes_from_a_different_paper() -> None:
    query_emb = [1.0, 0.0]
    candidates = [
        _candidate("paper-a", score=0.97, embedding=[0.97, 0.03]),
        _candidate("paper-b", score=0.95, embedding=[0.95, 0.05]),
        _candidate("paper-c", score=0.93, embedding=[0.93, 0.07]),
        _candidate("paper-d", score=0.91, embedding=[0.91, 0.09]),
    ]

    selected = inspiration_module._mmr_select(candidates, query_emb, k=3, lam=1.0)

    assert [item["paper_id"] for item in selected] == ["paper-a", "paper-b", "paper-c"]


def test_mmr_mixed_pool_keeps_at_least_two_papers_in_top_three() -> None:
    query_emb = [1.0, 0.0]
    candidates = [
        _candidate("paper-a", score=0.99, embedding=[1.0, 0.0]),
        _candidate("paper-a", score=0.98, embedding=[0.99, 0.01]),
        _candidate("paper-a", score=0.97, embedding=[0.98, 0.02]),
        _candidate("paper-b", score=0.82, embedding=[0.30, 0.95]),
        _candidate("paper-b", score=0.81, embedding=[0.28, 0.96]),
    ]

    selected = inspiration_module._mmr_select(candidates, query_emb, k=3, lam=0.7)

    assert len({item["paper_id"] for item in selected}) >= 2


def test_generate_sparks_from_chunks_uses_env_lambda_zero_for_full_diversity(monkeypatch) -> None:
    engine = inspiration_module.InspirationEngine()
    monkeypatch.setenv("MMR_LAMBDA", "0.0")
    chunks = [
        _chunk("paper-a", title="Paper A", content="laser welding pores formation", embedding=[1.0, 0.0]),
        _chunk("paper-a", title="Paper A", content="laser welding pores porosity", embedding=[0.99, 0.01]),
        _chunk("paper-a", title="Paper A", content="laser welding pores defects", embedding=[0.98, 0.02]),
        _chunk("paper-b", title="Paper B", content="laser welding dynamics study", embedding=[0.15, 0.99]),
        _chunk("paper-c", title="Paper C", content="laser welding keyhole study", embedding=[0.1, 0.95]),
    ]

    sparks = engine.generate_sparks_from_chunks("laser welding pores", chunks, limit=3)

    assert sparks[0].source_papers[0] == "Paper A"
    assert {spark.source_papers[0] for spark in sparks} == {"Paper A", "Paper B", "Paper C"}


def test_generate_sparks_from_chunks_uses_env_lambda_one_as_plain_top_k(monkeypatch) -> None:
    engine = inspiration_module.InspirationEngine()
    monkeypatch.setenv("MMR_LAMBDA", "1.0")
    chunks = [
        _chunk("paper-a", title="Paper A", content="laser welding pores formation", embedding=[1.0, 0.0]),
        _chunk("paper-a", title="Paper A", content="laser welding pores porosity", embedding=[0.99, 0.01]),
        _chunk("paper-a", title="Paper A", content="laser welding pores defects", embedding=[0.98, 0.02]),
        _chunk("paper-b", title="Paper B", content="laser welding dynamics study", embedding=[0.15, 0.99]),
        _chunk("paper-c", title="Paper C", content="laser welding keyhole study", embedding=[0.1, 0.95]),
    ]

    sparks = engine.generate_sparks_from_chunks("laser welding pores", chunks, limit=3)

    assert [spark.source_papers[0] for spark in sparks] == ["Paper A", "Paper A", "Paper A"]


def test_resolve_mmr_lambda_uses_default_for_out_of_range_numeric_env(monkeypatch) -> None:
    monkeypatch.setenv("MMR_LAMBDA", "2.0")

    assert inspiration_module._resolve_mmr_lambda() == 0.7
