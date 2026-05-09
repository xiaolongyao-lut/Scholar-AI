from __future__ import annotations

import json
from pathlib import Path

import pytest

from literature_assistant.core.wiki.evaluation import (
    audit_wiki_page_text,
    audit_wiki_pages,
    compare_wiki_vs_raw_retrieval,
    compute_retrieval_metrics,
    load_wiki_eval_manifest,
    scan_paths_for_secrets,
    scan_text_for_secrets,
)
from literature_assistant.core.wiki.page_store import render_page
from literature_assistant.core.wiki.query import WikiQueryResult, build_query_trace, write_query_trace
from literature_assistant.core.project_paths import WORKSPACE_TESTS_ROOT

pytestmark = pytest.mark.wiki_wave14


def _write_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "description": "wiki zero-cost eval fixture",
                "cases": [
                    {
                        "case_id": "q1",
                        "query": "What does Paper A support?",
                        "expected_source_ids": ["src-a"],
                        "wiki_context_source_ids": ["src-a", "src-b"],
                        "raw_context_source_ids": ["src-b", "src-a"],
                        "answer_page_path": "synthesis/q1.md",
                    },
                    {
                        "case_id": "q2",
                        "query": "What does Paper C contradict?",
                        "expected_chunk_ids": ["chunk-c"],
                        "wiki_context_chunk_ids": ["chunk-c"],
                        "raw_context_chunk_ids": [],
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_load_wiki_eval_manifest_validates_and_normalizes_cases(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)

    manifest = load_wiki_eval_manifest(manifest_path)

    assert manifest.schema_version == 1
    assert len(manifest.cases) == 2
    assert manifest.cases[0].expected_ids == ("src-a",)
    assert manifest.cases[1].wiki_context_ids == ("chunk-c",)


def test_load_wiki_eval_manifest_rejects_empty_cases(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": 1, "cases": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="cases must be a non-empty list"):
        load_wiki_eval_manifest(manifest_path)


def test_compute_retrieval_metrics_reports_hit_mrr_precision_and_recall() -> None:
    row = compute_retrieval_metrics("q1", ["src-a", "src-c"], ["src-b", "src-a", "src-d"], top_k=3)

    assert row.hit_rate == 1.0
    assert row.mrr == 0.5
    assert row.precision == pytest.approx(1 / 3)
    assert row.recall == 0.5


def test_compare_wiki_vs_raw_retrieval_uses_zero_cost_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    manifest = load_wiki_eval_manifest(manifest_path)

    report = compare_wiki_vs_raw_retrieval(manifest, top_k=2)
    payload = report.to_dict()

    assert payload["case_count"] == 2
    assert report.wiki["hit_rate"] == 1.0
    assert report.wiki["mrr"] == 1.0
    assert report.raw["hit_rate"] == 0.5
    assert report.raw["mrr"] == 0.25
    assert len(payload["per_case"]) == 2


def test_audit_wiki_page_text_passes_cited_page_with_evidence_refs() -> None:
    page = render_page(
        Path("synthesis/q1.md"),
        {
            "id": "q1",
            "kind": "synthesis",
            "status": "final",
            "title": "Q1",
            "evidence_refs": [{"source_id": "src-a", "quote": "quoted evidence"}],
        },
        "This claim is supported [[src-a]].",
    )

    result = audit_wiki_page_text("synthesis/q1.md", page.text)

    assert result.level == "passed"
    assert result.citation_count == 1
    assert result.evidence_ref_count == 1
    assert result.citation_density == 1.0


def test_audit_wiki_page_text_fails_final_page_without_citations_or_evidence() -> None:
    page = render_page(
        Path("synthesis/q2.md"),
        {"id": "q2", "kind": "synthesis", "status": "final", "title": "Q2"},
        "This claim has no citation.",
    )

    result = audit_wiki_page_text("synthesis/q2.md", page.text)

    assert result.level == "failed"
    assert "failed: page has no citations" in result.issues
    assert "failed: final page has no evidence_refs" in result.issues


def test_audit_wiki_pages_aggregates_status_counts(tmp_path: Path) -> None:
    good = render_page(
        Path("final/good.md"),
        {
            "id": "good",
            "kind": "synthesis",
            "status": "final",
            "title": "Good",
            "evidence_refs": [{"source_id": "src-a", "quote": "q"}],
        },
        "This claim is cited [[src-a]].",
    )
    draft = render_page(
        Path("draft/warn.md"),
        {"id": "warn", "kind": "synthesis", "status": "draft", "title": "Warn"},
        "This draft claim has no citation.",
    )
    root = tmp_path / "wiki"
    (root / good.relative_path).parent.mkdir(parents=True)
    (root / draft.relative_path).parent.mkdir(parents=True)
    (root / good.relative_path).write_text(good.text, encoding="utf-8")
    (root / draft.relative_path).write_text(draft.text, encoding="utf-8")

    report = audit_wiki_pages(root)

    assert report.page_count == 2
    assert report.passed_count == 1
    assert report.warning_count == 1
    assert report.failed_count == 0
    assert report.to_dict()["average_citation_density"] == 0.5


def test_audit_wiki_pages_rejects_escape_paths(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    root.mkdir()

    with pytest.raises(ValueError, match="page_paths must stay inside page_root"):
        audit_wiki_pages(root, [Path("../escape.md")])


def test_workspace_wiki_eval_smoke_fixture_loads_compares_audits_and_has_no_secrets() -> None:
    fixture_root = WORKSPACE_TESTS_ROOT / "fixtures" / "wiki_eval_smoke"
    manifest = load_wiki_eval_manifest(fixture_root / "manifest.json")

    comparison = compare_wiki_vs_raw_retrieval(manifest, top_k=2)
    audit = audit_wiki_pages(fixture_root / "pages")
    secret_scan = scan_paths_for_secrets(
        [
            fixture_root / "manifest.json",
            fixture_root / "pages" / "synthesis" / "paper-a.md",
            fixture_root / "pages" / "synthesis" / "baseline-contrast.md",
        ]
    )

    assert comparison.wiki["hit_rate"] == 1.0
    assert comparison.raw["hit_rate"] == 0.5
    assert audit.failed_count == 0
    assert audit.passed_count == 2
    assert secret_scan.passed is True


def test_secret_scan_detects_tokens_and_private_paths_without_echoing_values() -> None:
    secret_text = "\n".join(
        [
            "Authorization: Bearer sk-supersecretvalue1234567890",
            r"source_path=C:\Users\xiao\private\paper.pdf",
        ]
    )

    report = scan_text_for_secrets(secret_text, source="trace.json")
    payload = report.to_dict()

    assert report.passed is False
    assert report.finding_count >= 2
    assert "sk-supersecretvalue1234567890" not in json.dumps(payload)
    assert "private\\paper.pdf" not in json.dumps(payload)


def test_written_query_trace_passes_no_secret_scan(tmp_path: Path) -> None:
    query_result = WikiQueryResult(
        wiki_hits=[],
        linked_hits=[],
        fallback_used=True,
        fallback_reason="no wiki hits",
    )
    trace = build_query_trace("secret research question with sk-hidden123456789012345", query_result, None, enabled=True)
    trace_path = write_query_trace(trace, trace_dir=tmp_path)

    report = scan_paths_for_secrets([trace_path])

    assert report.passed is True
