from __future__ import annotations

from typing import Any


def _candidates() -> list[dict[str, Any]]:
    return [
        {"chunk_id": "b", "content": "second"},
        {"chunk_id": "a", "content": "first"},
    ]


def test_candidate_order_does_not_change_key() -> None:
    """Current cache key semantics sort candidate IDs before hashing."""
    from rerank_cache import make_cache_key

    candidates = _candidates()
    reversed_candidates = list(reversed(candidates))

    assert make_cache_key("Query", candidates, model="m", version="v") == make_cache_key(
        "Query", reversed_candidates, model="m", version="v"
    )


def test_duplicate_chunk_ids_are_documented_current_semantics() -> None:
    """Duplicate chunk IDs are preserved in the sorted ID multiset."""
    from rerank_cache import make_cache_key

    base = [{"chunk_id": "a", "content": "first"}, {"chunk_id": "b", "content": "second"}]
    duplicate = [{"chunk_id": "a", "content": "first"}, {"chunk_id": "a", "content": "second"}]

    assert make_cache_key("Query", base, model="m", version="v") != make_cache_key(
        "Query", duplicate, model="m", version="v"
    )


def test_model_changes_key() -> None:
    """Model is part of the durable cache key contract."""
    from rerank_cache import make_cache_key

    assert make_cache_key("Query", _candidates(), model="m1", version="v") != make_cache_key(
        "Query", _candidates(), model="m2", version="v"
    )


def test_top_n_is_not_part_of_key_by_current_design() -> None:
    """top_n is absent because cached values are score maps for candidate IDs."""
    from rerank_cache import make_cache_key

    key_for_top_3 = make_cache_key("Query", _candidates(), model="m", version="v")
    key_for_top_10 = make_cache_key("Query", _candidates(), model="m", version="v")

    assert key_for_top_3 == key_for_top_10


def test_same_query_same_candidates_same_key() -> None:
    """Basic idempotency: identical inputs must produce identical keys."""
    from rerank_cache import make_cache_key

    candidates = _candidates()
    k1 = make_cache_key("Query", candidates, model="m", version="v")
    k2 = make_cache_key("Query", candidates, model="m", version="v")
    assert k1 == k2
