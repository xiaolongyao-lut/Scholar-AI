# -*- coding: utf-8 -*-
"""Regression smoke test for InspirationEngine on the 109-paper corpus.

Promoted from tmp_inspiration_smoke.py. Skipped automatically if the corpus
chunk store is not present (so CI on a clean checkout still passes).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from inspiration_engine import InspirationEngine

pytestmark = pytest.mark.smoke

CHUNK_STORE = Path("output/chunk_store/laser_welding_109_chunks.json")
QUERIES = [
    "激光焊接气孔缺陷的形成机理",
    "高强钢激光焊接接头力学性能",
    "焊接熔池动力学",
]


@pytest.fixture(scope="module")
def flat_chunks() -> list[dict]:
    if not CHUNK_STORE.exists():
        pytest.skip(f"corpus chunk store missing: {CHUNK_STORE}")
    raw = json.loads(CHUNK_STORE.read_text(encoding="utf-8"))
    flat: list[dict] = []
    for material_id, chunks in raw.items():
        for chunk in chunks:
            chunk.setdefault("material_id", material_id)
            flat.append(chunk)
    if not flat:
        pytest.skip("corpus chunk store is empty")
    return flat


def test_chinese_queries_yield_distinct_sparks(flat_chunks: list[dict]) -> None:
    """CJK bigram tokenization must produce different sparks per query.

    Regression for the bug where ``query.split()`` on Chinese strings
    returned a single token, making every query return the same top-N.
    """
    engine = InspirationEngine()
    spark_signatures: list[tuple[str, ...]] = []
    for query in QUERIES:
        sparks = engine.generate_sparks_from_chunks(query, flat_chunks, limit=3)
        assert sparks, f"no sparks returned for {query!r}"
        for spark in sparks:
            assert spark.confidence > 0
        spark_signatures.append(tuple(s.content[:80] for s in sparks))

    # All three queries must produce at least one distinct top-3 list,
    # otherwise the CJK fix has regressed.
    assert len(set(spark_signatures)) >= 2, (
        "All Chinese queries returned identical sparks — CJK tokenization "
        "regression at inspiration_engine.py (see L131 bigram block)."
    )


def test_top_sparks_show_source_diversity(flat_chunks: list[dict]) -> None:
    """MMR diversity layer should prevent a single paper from monopolising
    the top-K sparks. We require at least 2 distinct source titles among the
    top-3 for at least 2 of the 3 Chinese queries.
    """
    engine = InspirationEngine()
    diverse_query_count = 0
    for query in QUERIES:
        sparks = engine.generate_sparks_from_chunks(query, flat_chunks, limit=3)
        if not sparks:
            continue
        sources = {
            (s.source_papers[0] if s.source_papers else "") for s in sparks
        }
        sources.discard("")
        if len(sources) >= 2:
            diverse_query_count += 1
    assert diverse_query_count >= 2, (
        "Top-3 sparks lacked source diversity for too many queries — "
        "_diversify_by_source round-robin may have regressed."
    )
