"""Wave 1 audit tool 单元测试 — agile-hugging-peacock.md §改动 2。

覆盖:
1. template 编译 + 字面匹配
2. template 拒绝非模板文本
3. classify_query 覆盖 simple/medium/hard 三档
4. compute_totals 基础计数
5. compute_doc_id_coverage missing path
6. compute_doc_id_coverage no chunk dir → None
7. collect_bad_cases duplicate_query_text_across_docs
8. collect_bad_cases hard_with_single_doc_evidence
9. run_audit schema_version=1 + 必填顶层 key + flags sidecar

依赖:
- audit_eval_dataset (top-level, 当前尚未实现 → 本文件先红灯)
- build_eval_corpus.QUERY_TEMPLATES (已存在)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit_eval_dataset import (  # noqa: F401 — 尚未实现,红灯预期
    BAD_CASE_MULTI_DOC_THRESHOLD,
    classify_query,
    collect_bad_cases,
    compile_template_patterns,
    compute_doc_id_coverage,
    compute_totals,
    run_audit,
)
from build_eval_corpus import QUERY_TEMPLATES


@pytest.fixture
def patterns():
    return compile_template_patterns(QUERY_TEMPLATES)


def test_compile_template_patterns_matches_known_literal(patterns):
    """已知语料里的 `激光焊接的最新研究进展` 必中 simple:0。"""
    is_tmpl, tid = classify_query("激光焊接的最新研究进展", patterns)
    assert is_tmpl is True
    assert tid == "simple:0"


def test_compile_template_patterns_rejects_non_template(patterns):
    """非模板 query 返回 (False, None)。"""
    is_tmpl, tid = classify_query("what is the weld penetration of Ti-6Al-4V", patterns)
    assert is_tmpl is False
    assert tid is None


def test_classify_query_returns_template_id_for_each_difficulty(patterns):
    """simple/medium/hard 各取一个真实模板字面,验证 template_id 格式。"""
    cases = [
        ("熔池的最新研究进展", "simple:0"),
        ("微观组织与力学性能之间的关系研究", "medium:0"),
        ("钛合金在热处理条件下对耐磨性的耦合效应分析", "hard:0"),
    ]
    for text, expected_tid in cases:
        is_tmpl, tid = classify_query(text, patterns)
        assert is_tmpl is True, f"expected template match for: {text!r}"
        assert tid == expected_tid, f"got {tid!r} for {text!r}, expected {expected_tid!r}"


def test_compute_totals_basic():
    queries = [
        {"query_id": "q_0001", "query_text": "A", "evidence_set": [{"doc_id": "m1"}], "source_title": "P1"},
        {"query_id": "q_0002", "query_text": "A", "evidence_set": [{"doc_id": "m2"}], "source_title": "P2"},
        {"query_id": "q_0003", "query_text": "B", "evidence_set": [{"doc_id": "m1"}], "source_title": "P1"},
    ]
    totals = compute_totals(queries)
    assert totals["total_queries"] == 3
    assert totals["unique_query_text"] == 2
    assert totals["unique_doc_ids_in_evidence"] == 2
    assert totals["unique_source_titles"] == 2


def test_compute_doc_id_coverage_missing_path():
    """evidence 里有一个 doc_id 不在 material_ids → 报告 missing=1。"""
    queries = [
        {"evidence_set": [{"doc_id": "m1"}]},
        {"evidence_set": [{"doc_id": "m_missing"}]},
    ]
    cov = compute_doc_id_coverage(queries, {"m1"})
    assert cov is not None
    assert cov["total_distinct_doc_ids"] == 2
    assert cov["hit"] == 1
    assert cov["missing"] == 1
    assert "m_missing" in cov["missing_samples"]


def test_compute_doc_id_coverage_no_chunk_dir():
    """material_ids=None → coverage=None(不做检查,字段置空)。"""
    queries = [{"evidence_set": [{"doc_id": "m1"}]}]
    cov = compute_doc_id_coverage(queries, None)
    assert cov is None


def test_collect_bad_cases_multi_doc(patterns):
    """6 条同 query_text 指向 6 个不同 doc_id → 触发 duplicate_query_text_across_docs。"""
    queries = [
        {
            "query_id": f"q_{i:04d}",
            "query_text": "same-text",
            "difficulty_level": "simple",
            "evidence_set": [{"doc_id": f"m{i}"}],
        }
        for i in range(BAD_CASE_MULTI_DOC_THRESHOLD)
    ]
    bad = collect_bad_cases(queries, coverage_result=None, patterns=patterns)
    dup_bucket = bad["duplicate_query_text_across_docs"]
    assert dup_bucket["type_count"] >= 1
    sample = dup_bucket["samples"][0]
    assert sample["query_text"] == "same-text"
    assert sample["distinct_doc_count"] == BAD_CASE_MULTI_DOC_THRESHOLD
    assert len(sample["sampled_doc_ids"]) == BAD_CASE_MULTI_DOC_THRESHOLD


def test_collect_bad_cases_hard_single_doc(patterns):
    """hard query 但 evidence_set 只有 1 条 → 触发 hard_with_single_doc_evidence。"""
    queries = [
        {
            "query_id": "q_hard",
            "query_text": "钛合金在热处理条件下对耐磨性的耦合效应分析",
            "difficulty_level": "hard",
            "evidence_set": [{"doc_id": "m1"}],
        }
    ]
    bad = collect_bad_cases(queries, coverage_result=None, patterns=patterns)
    single_bucket = bad["hard_with_single_doc_evidence"]
    assert single_bucket["type_count"] == 1
    assert single_bucket["samples"][0]["query_id"] == "q_hard"


def test_run_audit_returns_schema_v1(tmp_path):
    """mini 3-query 场景 → 产物 schema_version=1 且所有必填顶层 key 存在。"""
    queries_path = tmp_path / "qs.jsonl"
    queries = [
        {
            "query_id": "q_0001",
            "query_text": "激光焊接的最新研究进展",
            "difficulty_level": "simple",
            "evidence_set": [{"doc_id": "m1"}],
            "source_title": "P1",
        },
        {
            "query_id": "q_0002",
            "query_text": "英文非模板文本 what about that",
            "difficulty_level": "simple",
            "evidence_set": [{"doc_id": "m_missing"}],
            "source_title": "P2",
        },
        {
            "query_id": "q_0003",
            "query_text": "钛合金在热处理条件下对耐磨性的耦合效应分析",
            "difficulty_level": "hard",
            "evidence_set": [{"doc_id": "m1"}],
            "source_title": "P1",
        },
    ]
    queries_path.write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in queries),
        encoding="utf-8",
    )

    audit, flags = run_audit(queries_path=queries_path, chunk_dir=None, top_n=5)

    assert audit["schema_version"] == 1
    for key in (
        "generated_at",
        "input_queries",
        "totals",
        "per_difficulty",
        "doc_id_coverage",
        "top_repeated_query_text",
        "per_source_fanout",
        "template_match",
        "bad_cases",
    ):
        assert key in audit, f"missing top-level key: {key}"

    assert isinstance(flags, list)
    assert len(flags) == 3
    assert all({"query_id", "is_template", "template_id"} <= set(f.keys()) for f in flags)
