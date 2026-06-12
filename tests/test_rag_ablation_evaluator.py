# -*- coding: utf-8 -*-
"""Unit tests for the A15 ablation evaluator framework.

不依赖真实 chunk_store / goldset:用合成 chunks + goldset 验证 5 候选配置的
relative ordering 与 metric 计算行为一致。

测试覆盖:
1. baseline 与 all_one 在所有权重 1.0 时应得到字节级相等的指标
2. table_heavy 应让 table chunk 在 query 命中时排名上升
3. heading_suppressed 应让 heading chunk 在 query 命中时排名下降
4. paired_bootstrap_ci 返回 (mean, low, high) 且 low <= mean <= high
5. ndcg / recall@k / mrr 数学正确性(small known cases)
6. load_goldset skip 模板 / 空 / 注释行
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import pytest

from literature_assistant.core.rag_ablation_evaluator import (
    CANDIDATE_CONFIGS,
    dcg,
    load_goldset,
    mrr,
    naive_bm25ish_score,
    ndcg,
    paired_bootstrap_ci,
    recall_at_k,
    search,
)


# --------------------------------------------------------------------- #
# 合成 fixtures
# --------------------------------------------------------------------- #


def make_chunk(chunk_id: str, content: str, chunk_type: str) -> dict[str, Any]:
    return {"chunk_id": chunk_id, "content": content, "chunk_type": chunk_type}


@pytest.fixture
def synthetic_chunks() -> list[dict[str, Any]]:
    """各 chunk_type 各 1 条,content 命中关键词 hardness,便于排名测试。"""
    return [
        make_chunk("c_narrative", "the hardness of titanium increases", "narrative"),
        make_chunk("c_heading", "hardness measurement section", "heading"),
        make_chunk("c_table", "hardness values table 1", "table"),
        make_chunk("c_formula", "hardness formula H = F/A", "formula"),
        make_chunk("c_figure_caption", "hardness profile figure 2", "figure_caption"),
        make_chunk("c_list", "hardness key points list", "list"),
        make_chunk("c_code", "hardness compute python code", "code"),
        make_chunk("c_image_caption", "hardness image caption", "image_caption"),
        make_chunk("c_unrelated", "unrelated content", "narrative"),  # not hit
    ]


# --------------------------------------------------------------------- #
# Metrics math
# --------------------------------------------------------------------- #


def test_dcg_two_relevant_at_top_higher_than_bottom() -> None:
    """relevant 在顶部 DCG 应高于在底部。"""
    high = dcg([1, 1, 0, 0])
    low = dcg([0, 0, 1, 1])
    assert high > low


def test_ndcg_perfect_ranking_returns_1() -> None:
    retrieved = ["a", "b", "c"]
    gold = {"a", "b"}
    # 完美排名:relevant 在前
    assert ndcg(retrieved, gold, k=5) == pytest.approx(1.0)


def test_ndcg_no_relevant_returns_0() -> None:
    assert ndcg(["x", "y"], {"a"}, k=5) == 0.0


def test_recall_at_k_basic() -> None:
    retrieved = ["a", "b", "c", "d"]
    gold = {"a", "c", "e"}
    # top@4 命中 a 和 c → 2 / 3
    assert recall_at_k(retrieved, gold, k=4) == pytest.approx(2 / 3)


def test_recall_at_k_empty_gold_returns_0() -> None:
    assert recall_at_k(["a"], set(), k=5) == 0.0


def test_mrr_first_position() -> None:
    assert mrr(["a", "b"], {"a"}) == 1.0


def test_mrr_third_position() -> None:
    assert mrr(["x", "y", "z"], {"z"}) == pytest.approx(1 / 3)


def test_mrr_no_match_returns_0() -> None:
    assert mrr(["x", "y"], {"z"}) == 0.0


# --------------------------------------------------------------------- #
# naive_bm25ish_score
# --------------------------------------------------------------------- #


def test_naive_bm25ish_no_query_or_content_returns_0() -> None:
    assert naive_bm25ish_score("", "content") == 0.0
    assert naive_bm25ish_score("query", "") == 0.0


def test_naive_bm25ish_full_hit() -> None:
    # 全部 token 命中 → 1.0
    assert naive_bm25ish_score("hardness titanium", "the hardness of titanium") == pytest.approx(1.0)


def test_naive_bm25ish_partial_hit() -> None:
    # 2 token / 1 hit → 0.5
    assert naive_bm25ish_score("hardness foo", "only hardness here") == pytest.approx(0.5)


# --------------------------------------------------------------------- #
# search behavior + candidate configs
# --------------------------------------------------------------------- #


def test_baseline_and_all_one_produce_equal_rankings(synthetic_chunks: list[dict[str, Any]]) -> None:
    """all_one 权重全 1.0 → 与 baseline (无 weighting) 必然产生相同顺序与分数。"""
    baseline = search("hardness", synthetic_chunks, CANDIDATE_CONFIGS["baseline"])
    all_one = search("hardness", synthetic_chunks, CANDIDATE_CONFIGS["all_one"])
    assert [c["chunk_id"] for c in baseline] == [c["chunk_id"] for c in all_one]
    for b, a in zip(baseline, all_one):
        assert b["rerank_score"] == pytest.approx(a["rerank_score"])


def test_table_heavy_boosts_table_chunk(synthetic_chunks: list[dict[str, Any]]) -> None:
    """table_heavy 把 table 权重抬到 1.5 → table chunk 的最终 rerank_score
    应严格高于其它 chunk_type(在 baseline 命中相同的前提下)。"""
    ranked = search("hardness", synthetic_chunks, CANDIDATE_CONFIGS["table_heavy"])
    table_chunk = next(c for c in ranked if c["chunk_id"] == "c_table")
    narrative_chunk = next(c for c in ranked if c["chunk_id"] == "c_narrative")
    assert table_chunk["rerank_score"] > narrative_chunk["rerank_score"]


def test_heading_suppressed_demotes_heading_chunk(synthetic_chunks: list[dict[str, Any]]) -> None:
    """heading_suppressed 把 heading 权重压到 0.5 → heading chunk 的最终 rerank_score
    应严格低于其它 1.0 权重 chunk_type。"""
    ranked = search("hardness", synthetic_chunks, CANDIDATE_CONFIGS["heading_suppressed"])
    heading_chunk = next(c for c in ranked if c["chunk_id"] == "c_heading")
    narrative_chunk = next(c for c in ranked if c["chunk_id"] == "c_narrative")
    assert heading_chunk["rerank_score"] < narrative_chunk["rerank_score"]


def test_proposed_config_uses_recommended_weights() -> None:
    """proposed 配置应等同 spec §2.1 推荐权重表。"""
    proposed = CANDIDATE_CONFIGS["proposed"]
    assert proposed is not None
    assert proposed["narrative"] == 1.00
    assert proposed["heading"] == 0.75
    assert proposed["table"] == 1.30
    assert proposed["formula"] == 1.20
    assert proposed["figure_caption"] == 1.15
    assert proposed["list"] == 0.95
    assert proposed["code"] == 0.90
    assert proposed["image_caption"] == 1.10


def test_search_skips_zero_score_chunks(synthetic_chunks: list[dict[str, Any]]) -> None:
    """search 应跳过 score == 0 的 chunk(无 token 命中)。"""
    ranked = search("hardness", synthetic_chunks, None)
    ids = {c["chunk_id"] for c in ranked}
    assert "c_unrelated" not in ids


# --------------------------------------------------------------------- #
# paired bootstrap CI
# --------------------------------------------------------------------- #


def test_paired_bootstrap_empty_deltas_returns_zeros() -> None:
    mean, low, high = paired_bootstrap_ci([])
    assert (mean, low, high) == (0.0, 0.0, 0.0)


def test_paired_bootstrap_ci_brackets_mean() -> None:
    """CI 区间应包含 sample mean(rng seed=42 固定)。"""
    deltas = [0.1, 0.2, 0.15, 0.05, 0.25, 0.1, 0.2, 0.15]
    mean, low, high = paired_bootstrap_ci(deltas)
    # mean 在 [low, high] 之间(允许等号:小样本时极端样本可能正好等于 mean)
    assert low <= mean <= high
    assert mean == pytest.approx(statistics.fmean(deltas))


def test_paired_bootstrap_positive_signal() -> None:
    """全正 deltas → CI 下界应严格 > 0(显著正向)。"""
    deltas = [0.1, 0.15, 0.2, 0.18, 0.12, 0.14, 0.16, 0.13, 0.17, 0.11]
    _, low, _ = paired_bootstrap_ci(deltas)
    assert low > 0


# --------------------------------------------------------------------- #
# load_goldset skip logic
# --------------------------------------------------------------------- #


def test_load_goldset_skips_template_and_comment_lines(tmp_path: Path) -> None:
    """模板行(以 # 开头)、空行、ground_truth 空 list 应被 skip。"""
    p = tmp_path / "test_goldset.jsonl"
    lines = [
        "# 这是注释行",
        "",
        '{"query": "template only", "query_type": "numeric", "ground_truth_chunk_ids": []}',
        '{"query": "real query", "query_type": "method", "ground_truth_chunk_ids": ["c1"]}',
        "# 又一条注释",
        '{"query": "另一条", "query_type": "general", "ground_truth_chunk_ids": ["c2", "c3"]}',
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    goldset = load_goldset(p)
    assert len(goldset) == 2
    assert goldset[0]["query"] == "real query"
    assert goldset[1]["query"] == "另一条"


def test_load_goldset_empty_file_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    assert load_goldset(p) == []
