# -*- coding: utf-8 -*-
"""Contract tests for query-scoped evidence-pack generation."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
import pytest

import routers.resources_router as resources_router
from python_adapter_server import app


def _client() -> TestClient:
    """Return the shared FastAPI test client for evidence-pack contracts."""

    return TestClient(app)


def _create_project(client: TestClient, title: str = "Evidence Pack Project") -> dict[str, Any]:
    """Create a project through the public resources API."""

    response = client.post("/resources/project", json={"title": title})
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["project_id"], str)
    return payload


def _write_chunk_fixture(project_id: str) -> None:
    """Persist chunks with private fields that must never reach evidence packs."""

    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_pack": [
                {
                    "chunk_id": "pack_chunk_1",
                    "material_id": "mat_pack",
                    "title": "AlSi10Mg porosity fatigue evidence",
                    "summary": "AlSi10Mg porosity affects fatigue crack initiation near the surface.",
                    "content": "AlSi10Mg porosity affects fatigue crack initiation near the surface.",
                    "abstract": "SHOULD_NOT_LEAK_ABSTRACT",
                    "ocr_text": "SHOULD_NOT_LEAK_OCR",
                    "raw_ocr_blocks": [{"text": "SHOULD_NOT_LEAK_BLOCK"}],
                    "private_note": "SHOULD_NOT_LEAK_PRIVATE",
                    "page": 9,
                    "chunk_index": 1,
                    "chunk_type": "body",
                    "source_relative_path": "papers/alsi10mg.pdf",
                    "source_labels": ["bm25", "layout_pdf"],
                    "figure_candidate": "figure:porosity-1",
                    "locator": {
                        "page": 9,
                        "chunk_index": 1,
                        "bbox": [0.11, 0.22, 0.33, 0.44],
                        "text": "SHOULD_NOT_LEAK_LOCATOR_TEXT",
                    },
                },
                {
                    "chunk_id": "pack_chunk_2",
                    "material_id": "mat_pack",
                    "title": "Unrelated corrosion note",
                    "content": "Corrosion electrolyte setup.",
                    "abstract": "SHOULD_NOT_LEAK_SECOND_ABSTRACT",
                    "page": 2,
                },
            ]
        },
    )


def test_evidence_pack_build_returns_mcp_safe_lexical_pack() -> None:
    """POST evidence-pack/build returns refs, scores, and explicit rerank fallback."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "section_id": "intro",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_pack_ref"].startswith("evidence_pack:")
    assert payload["project_id"] == project_id
    assert payload["query"] == "AlSi10Mg porosity fatigue"
    assert payload["section_id"] == "intro"
    assert payload["retrieval_method"] == "lexical"
    assert payload["rerank_status"] == "unavailable"
    diagnostics = payload["retrieval_diagnostics"]
    assert diagnostics["retrieval_method"] == "lexical"
    assert diagnostics["embedding_status"] == "unavailable"
    assert diagnostics["rerank_status"] == "unavailable"
    assert "not invoked" in diagnostics["fallback_reason"]
    assert diagnostics["project_weight"] == 1.0
    assert diagnostics["wiki_weight"] == 0.0
    assert diagnostics["locator_coverage"] == {
        "schema_version": "scholar-ai-evidence-locator-coverage/v1",
        "total_refs": 1,
        "project_ref_count": 1,
        "non_project_ref_count": 0,
        "material_locator_count": 1,
        "page_locator_count": 1,
        "bbox_locator_count": 1,
        "invalid_bbox_count": 0,
        "missing_locator_count": 0,
        "page_coverage_ratio": 1.0,
        "bbox_coverage_ratio": 1.0,
        "bbox_unit_counts": {"normalized_ratio": 1},
        "source_label_count": 1,
        "source_label_coverage_ratio": 1.0,
        "figure_table_locator_count": 1,
        "coverage_state": "layout_complete",
        "risk_level": "none",
        "sample_figure_table_ids": ["figure:porosity-1"],
        "sample_invalid_bbox_ref_ids": [],
        "sample_missing_ref_ids": [],
        "notes": [
            "Every project ref has material, page, and bbox locators.",
            "Some project refs are linked to figure/table candidates for layout-aware review.",
        ],
    }
    assert diagnostics["reasoning_trace"]
    assert any("lexical" in item.lower() for item in diagnostics["reasoning_trace"])
    assert diagnostics["notes"]
    outcome = payload["outcome"]
    assert outcome["schema_version"] == "scholar-ai-tool-outcome/v1"
    assert outcome["status"] == "degraded"
    assert outcome["quality"] == "refs_only"
    assert outcome["next_action"]["kind"] == "read_resource"
    assert outcome["next_action"]["endpoint"] == (
        f"/api/agent-bridge/resource/chunk:pack_chunk_1?project_id={project_id}"
    )
    attempts = {attempt["stage"]: attempt for attempt in outcome["attempts"]}
    assert attempts["chunk_load"]["status"] == "success"
    assert attempts["chunk_load"]["metadata"]["chunk_count"] == 2
    assert attempts["retrieval"]["metadata"]["retrieval_method"] == "lexical"
    assert attempts["retrieval"]["metadata"]["returned_ref_count"] == 1
    assert attempts["rerank"]["status"] == "skipped"
    assert attempts["rerank"]["error_class"] == "rerank_unavailable"
    assert attempts["locator_coverage"]["status"] == "success"
    assert attempts["locator_coverage"]["metadata"]["coverage_state"] == "layout_complete"
    assert attempts["locator_coverage"]["metadata"]["bbox_coverage_ratio"] == 1.0
    assert attempts["qrels_quality_gate"]["status"] == "skipped"
    assert payload["total"] == 1
    assert payload["truncated"] is False
    ref = payload["evidence_refs"][0]
    assert set(ref) == {
        "project_id",
        "source_type",
        "ref_id",
        "read_endpoint",
        "chunk_id",
        "material_id",
        "page",
        "locator",
        "lexical_score",
        "rerank_score",
        "citation_anchor",
        "figure_candidate",
        "source_labels",
        "summary",
        "suitable_for_body",
        "source_title",
        "source_path",
        "joint_score",
    }
    assert ref["project_id"] == project_id
    assert ref["source_type"] == "project"
    assert ref["ref_id"] == "chunk:pack_chunk_1"
    assert ref["read_endpoint"] == f"/api/agent-bridge/resource/chunk:pack_chunk_1?project_id={project_id}"
    assert ref["chunk_id"] == "pack_chunk_1"
    assert ref["material_id"] == "mat_pack"
    assert ref["page"] == 9
    assert ref["locator"] == {
        "material_id": "mat_pack",
        "chunk_id": "pack_chunk_1",
        "page": 9,
        "chunk_index": 1,
        "bbox": [0.11, 0.22, 0.33, 0.44],
        "bbox_unit": "normalized_ratio",
    }
    assert ref["lexical_score"] > 0
    assert ref["rerank_score"] is None
    assert ref["citation_anchor"]
    assert ref["figure_candidate"] == "figure:porosity-1"
    assert ref["source_labels"] == ["bm25", "layout_pdf"]
    assert ref["suitable_for_body"] is True
    assert ref["source_title"] is None
    assert ref["source_path"] is None
    assert ref["joint_score"] is None
    assert len(ref["summary"]) <= 300

    serialized = str(payload)
    assert "content" not in ref
    assert "abstract" not in serialized
    assert "SHOULD_NOT_LEAK" not in serialized
    assert "ocr" not in serialized.lower()
    assert "private_note" not in serialized


def test_evidence_pack_build_reports_invalid_bbox_locator_gap() -> None:
    """Evidence-pack diagnostics must retain invalid bbox repair signals."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_pack_invalid_bbox": [
                {
                    "chunk_id": "pack_chunk_invalid_bbox",
                    "material_id": "mat_pack_invalid_bbox",
                    "title": "AlSi10Mg invalid bbox evidence",
                    "summary": "AlSi10Mg evidence with invalid bbox metadata.",
                    "content": "AlSi10Mg evidence with invalid bbox metadata.",
                    "page": 6,
                    "locator": {
                        "material_id": "mat_pack_invalid_bbox",
                        "chunk_id": "pack_chunk_invalid_bbox",
                        "page": 6,
                        "bbox": [0.1, 0.2, 1.5, 0.3],
                        "bbox_unit": "normalized_ratio",
                    },
                }
            ]
        },
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg invalid bbox",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    coverage = payload["retrieval_diagnostics"]["locator_coverage"]
    assert coverage["coverage_state"] == "page_located"
    assert coverage["risk_level"] == "warn"
    assert coverage["page_locator_count"] == 1
    assert coverage["bbox_locator_count"] == 0
    assert coverage["invalid_bbox_count"] == 1
    assert coverage["sample_invalid_bbox_ref_ids"] == ["chunk:pack_chunk_invalid_bbox"]
    assert payload["evidence_refs"][0]["locator"] == {
        "material_id": "mat_pack_invalid_bbox",
        "chunk_id": "pack_chunk_invalid_bbox",
        "page": 6,
    }
    attempts = {attempt["stage"]: attempt for attempt in payload["outcome"]["attempts"]}
    assert attempts["locator_coverage"]["status"] == "degraded"
    assert attempts["locator_coverage"]["error_class"] == "locator_coverage_page_located"
    assert attempts["locator_coverage"]["metadata"]["invalid_bbox_count"] == 1
    serialized = str(payload)
    assert "1.5" not in serialized
    assert "[0.1, 0.2, 1.5, 0.3]" not in serialized


def test_evidence_pack_build_reports_hybrid_rerank_when_retriever_returns_dense_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence-pack build should expose actual dense/rerank participation."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    class _HybridRetriever:
        def __init__(self, use_reranker: bool | None = None) -> None:
            self.use_reranker = use_reranker

        async def search(
            self,
            raw_data: dict[str, Any],
            query: str,
            top_k: int = 10,
            focus_keywords: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            chunks = raw_data["chunks"]
            hit = dict(chunks[0])
            hit["hybrid_score"] = 0.87
            hit["rerank_score"] = 0.93
            hit["source_labels"] = ["bm25", "dense", "rerank"]
            return [hit]

    import routers.evidence_router as evidence_router

    monkeypatch.setattr(
        evidence_router,
        "_resolve_hybrid_retriever_class",
        lambda: _HybridRetriever,
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "section_id": "intro",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieval_method"] == "hybrid_rerank"
    assert payload["rerank_status"] == "active"
    assert payload["retrieval_diagnostics"]["qrels_status"]["status"] == "missing"
    assert payload["retrieval_diagnostics"]["qrels_status"]["semantic_quality_claim_allowed"] is False
    diagnostics = payload["retrieval_diagnostics"]
    assert diagnostics["retrieval_method"] == "hybrid_rerank"
    assert diagnostics["embedding_status"] == "active"
    assert diagnostics["rerank_status"] == "active"
    assert diagnostics["fallback_reason"] == ""
    assert any("HybridRetrieverWithRerank" in item for item in diagnostics["reasoning_trace"])
    outcome = payload["outcome"]
    assert outcome["status"] == "success"
    assert outcome["quality"] == "refs_only"
    attempts = {attempt["stage"]: attempt for attempt in outcome["attempts"]}
    assert attempts["retrieval"]["metadata"]["retrieval_method"] == "hybrid_rerank"
    assert attempts["rerank"]["status"] == "success"
    assert attempts["rerank"]["error_class"] == ""
    ref = payload["evidence_refs"][0]
    assert ref["ref_id"] == "chunk:pack_chunk_1"
    assert ref["rerank_score"] == 0.93
    assert "content" not in ref


def test_evidence_pack_build_reports_wiki_project_joint_recall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Joint recall diagnostics should include wiki hits without faking chunk refs."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)

    def _wiki_searcher(query: str, limit: int) -> list[dict[str, Any]]:
        assert query == "AlSi10Mg porosity fatigue"
        assert limit >= 5
        return [
            {
                "doc_id": f"wiki:alsi10mg-{index}",
                "ref_id": f"wiki:synthesis/alsi10mg-{index}.md",
                "read_endpoint": f"/api/agent-bridge/resource/wiki:synthesis/alsi10mg-{index}.md",
                "title": f"AlSi10Mg wiki note {index}",
                "summary": f"Wiki note {index} about porosity and fatigue.",
                "page_path": f"synthesis/alsi10mg-{index}.md",
                "source": "wiki_fts",
            }
            for index in range(1, 8)
        ]

    import routers.evidence_router as evidence_router

    monkeypatch.setattr(
        evidence_router,
        "_resolve_wiki_joint_recall_searcher",
        lambda: _wiki_searcher,
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "section_id": "intro",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    diagnostics = payload["retrieval_diagnostics"]
    joint = diagnostics["joint_recall"]
    assert joint["enabled"] is True
    assert joint["status"] == "active"
    assert joint["fusion_method"] == "weighted_rrf"
    assert joint["project_weight"] == 0.4
    assert joint["wiki_weight"] == 0.6
    assert joint["project_hit_count"] == 1
    assert joint["wiki_hit_count"] == 7
    assert joint["source_counts"]["project"] >= 1
    assert joint["source_counts"]["wiki"] >= 1
    assert joint["source_counts"]["wiki"] <= 3
    assert joint["wiki_summaries"][0]["ref_id"] == "wiki:synthesis/alsi10mg-1.md"
    assert joint["wiki_summaries"][0]["read_endpoint"] == "/api/agent-bridge/resource/wiki:synthesis/alsi10mg-1.md"
    assert diagnostics["project_weight"] == 0.4
    assert diagnostics["wiki_weight"] == 0.6
    locator_coverage = diagnostics["locator_coverage"]
    assert locator_coverage["project_ref_count"] == 1
    assert locator_coverage["non_project_ref_count"] == len(payload["evidence_refs"]) - 1
    assert locator_coverage["coverage_state"] == "layout_complete"
    assert locator_coverage["bbox_coverage_ratio"] == 1.0
    assert any("wiki+project" in item.lower() for item in diagnostics["reasoning_trace"])
    refs = payload["evidence_refs"]
    assert any(ref["ref_id"] == "chunk:pack_chunk_1" and ref["source_type"] == "project" for ref in refs)
    wiki_refs = [ref for ref in refs if ref["source_type"] == "wiki"]
    assert wiki_refs
    assert len(wiki_refs) <= 3
    assert wiki_refs[0]["ref_id"].startswith("wiki:synthesis/alsi10mg-")
    assert wiki_refs[0]["read_endpoint"].startswith("/api/agent-bridge/resource/wiki:synthesis/alsi10mg-")
    assert wiki_refs[0]["material_id"] == "wiki"
    assert wiki_refs[0]["chunk_id"].startswith("wiki:synthesis/alsi10mg-")
    assert wiki_refs[0]["source_title"].startswith("AlSi10Mg wiki note")
    assert wiki_refs[0]["source_path"].startswith("synthesis/alsi10mg-")
    assert wiki_refs[0]["joint_score"] is not None
    assert wiki_refs[0]["locator"] is None
    assert wiki_refs[0]["source_labels"] == []
    assert len(wiki_refs[0]["summary"]) <= 300
    serialized = str(payload)
    assert "Wiki note 1" in serialized
    assert "content" not in wiki_refs[0]
    assert "SHOULD_NOT_LEAK" not in serialized


def test_evidence_pack_build_reports_canonical_qrels_quality_gate() -> None:
    """Canonical qrels are required before retrieval quality can be claimed."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    canonical_qrels_path = resources_router.project_data_path(  # type: ignore[attr-defined]
        project_id,
        "qrels",
        "canonical.qrels",
    )
    canonical_qrels_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_qrels_path.write_text("pkg_q_0001 0 pack_chunk_1 2\n", encoding="utf-8")

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    qrels_status = response.json()["retrieval_diagnostics"]["qrels_status"]
    assert qrels_status == {
        "schema_version": "retrieval-qrels-status/v1",
        "status": "canonical",
        "candidate_qrels_count": 0,
        "reviewed_qrels_count": 0,
        "canonical_qrels_count": 1,
        "semantic_quality_claim_allowed": True,
        "quality_claim": "canonical_qrels_available",
        "notes": [
            "Canonical qrels are available for offline retrieval-quality evaluation.",
        ],
    }


def test_evidence_pack_build_reports_candidate_qrels_without_quality_claim() -> None:
    """Candidate qrels stay visible but never authorize semantic quality claims."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    candidate_qrels_path = resources_router.project_data_path(  # type: ignore[attr-defined]
        project_id,
        "qrels",
        "qrels_candidate.trec",
    )
    candidate_qrels_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_qrels_path.write_text(
        "# candidate qrels generated from chunk-package evidence sections\n"
        "pkg_q_0001 0 pack_chunk_1 1\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/evidence-pack/build",
        json={
            "project_id": project_id,
            "query": "AlSi10Mg porosity fatigue",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    qrels_status = response.json()["retrieval_diagnostics"]["qrels_status"]
    assert qrels_status["status"] == "candidate"
    assert qrels_status["candidate_qrels_count"] == 1
    assert qrels_status["canonical_qrels_count"] == 0
    assert qrels_status["semantic_quality_claim_allowed"] is False
    assert qrels_status["quality_claim"] == "candidate_qrels_review_required"
    outcome = response.json()["outcome"]
    attempts = {attempt["stage"]: attempt for attempt in outcome["attempts"]}
    assert attempts["qrels_quality_gate"]["status"] == "blocked"
    assert attempts["qrels_quality_gate"]["error_class"] == "qrels_review_needed"
    assert attempts["qrels_quality_gate"]["metadata"]["status"] == "candidate"


def test_evidence_pack_build_empty_store_is_stable() -> None:
    """Empty project chunk stores return an empty lexical pack envelope."""

    client = _client()
    project = _create_project(client)

    response = client.post(
        "/api/evidence-pack/build",
        json={"project_id": project["project_id"], "query": "missing evidence", "top_k": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project["project_id"]
    assert payload["retrieval_method"] == "lexical"
    assert payload["rerank_status"] == "unavailable"
    assert payload["retrieval_diagnostics"]["embedding_status"] == "unavailable"
    assert payload["retrieval_diagnostics"]["rerank_status"] == "unavailable"
    assert payload["retrieval_diagnostics"]["locator_coverage"]["coverage_state"] == "no_refs"
    assert payload["retrieval_diagnostics"]["locator_coverage"]["risk_level"] == "none"
    assert payload["total"] == 0
    assert payload["truncated"] is False
    outcome = payload["outcome"]
    assert outcome["status"] == "empty"
    assert outcome["quality"] == "none"
    assert outcome["next_action"]["kind"] == "scan_folder"
    assert outcome["next_action"]["tool_name"] == "literature.project_scan_folder"
    attempts = {attempt["stage"]: attempt for attempt in outcome["attempts"]}
    assert attempts["chunk_load"]["status"] == "skipped"
    assert attempts["chunk_load"]["error_class"] == "ingest_needed"
    assert attempts["locator_coverage"]["status"] == "success"
    assert attempts["locator_coverage"]["metadata"]["coverage_state"] == "no_refs"
    assert payload["evidence_refs"] == []


def test_evidence_pack_build_rejects_blank_query() -> None:
    """Blank request fields should fail before touching retrieval."""

    client = _client()
    project = _create_project(client)

    response = client.post(
        "/api/evidence-pack/build",
        json={"project_id": project["project_id"], "query": "   "},
    )

    assert response.status_code == 422
