# -*- coding: utf-8 -*-
"""Contract tests for the read-only chunk search refs endpoint."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import routers.resources_router as resources_router
from python_adapter_server import app


def _client() -> TestClient:
    """Return the shared FastAPI test client for search-ref contracts."""

    return TestClient(app)


def _create_project(client: TestClient, title: str = "Search Refs Project") -> dict[str, Any]:
    """Create a project through the public resources API."""

    response = client.post("/resources/project", json={"title": title})
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["project_id"], str)
    return payload


def _write_chunk_fixture(project_id: str) -> None:
    """Persist a chunk store containing large fields that must not leak."""

    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_alpha": [
                {
                    "chunk_id": "chunk_alpha_1",
                    "material_id": "mat_alpha",
                    "title": "Transformer Attention Review",
                    "content": "Transformer attention improves sequence modeling and retrieval quality.",
                    "abstract": "SHOULD_NOT_LEAK_ABSTRACT",
                    "ocr_text": "SHOULD_NOT_LEAK_OCR",
                    "raw_ocr_blocks": [{"text": "SHOULD_NOT_LEAK_BLOCK"}],
                    "page": 7,
                    "chunk_index": 2,
                    "chunk_type": "body",
                    "source_relative_path": "papers/attention.pdf",
                    "source_labels": ["bm25", "dense"],
                    "figure_candidate": "figure:attention-1",
                    "private_note": "SHOULD_NOT_LEAK_PRIVATE",
                    "locator": {
                        "material_id": "mat_alpha",
                        "chunk_id": "chunk_alpha_1",
                        "page": 7,
                        "chunk_index": 2,
                        "bbox": [0.1, 0.2, 0.3, 0.4],
                        "text": "SHOULD_NOT_LEAK_LOCATOR_TEXT",
                    },
                },
                {
                    "chunk_id": "chunk_beta_1",
                    "material_id": "mat_alpha",
                    "title": "Unrelated Catalyst Notes",
                    "content": "Catalyst stability and reaction conditions.",
                    "abstract": "SHOULD_NOT_LEAK_SECOND_ABSTRACT",
                    "page": 3,
                    "chunk_type": "body",
                },
            ]
        },
    )


def test_search_refs_returns_refs_without_full_chunk_fields(monkeypatch: Any) -> None:
    """GET search-refs must return only the MCP ref contract."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    monkeypatch.setattr(
        resources_router,
        "_collect_pending_scan_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ingest helper called")),
    )
    monkeypatch.setattr(
        resources_router,
        "_ingest_pending_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ingest helper called")),
    )

    response = client.get(
        "/resources/chunks/search-refs",
        params={"project_id": project_id, "query": "transformer attention", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project_id
    assert payload["query"] == "transformer attention"
    assert payload["total_refs"] == 1
    assert payload["locator_coverage"] == {
        "schema_version": "scholar-ai-evidence-locator-coverage/v1",
        "total_refs": 1,
        "project_ref_count": 1,
        "non_project_ref_count": 0,
        "material_locator_count": 1,
        "page_locator_count": 1,
        "bbox_locator_count": 1,
        "missing_locator_count": 0,
        "page_coverage_ratio": 1.0,
        "bbox_coverage_ratio": 1.0,
        "bbox_unit_counts": {"normalized_ratio": 1},
        "source_label_count": 1,
        "source_label_coverage_ratio": 1.0,
        "figure_table_locator_count": 1,
        "coverage_state": "layout_complete",
        "risk_level": "none",
        "sample_figure_table_ids": ["figure:attention-1"],
        "sample_missing_ref_ids": [],
        "notes": [
            "Every project ref has material, page, and bbox locators.",
            "Some project refs are linked to figure/table candidates for layout-aware review.",
        ],
    }
    ref = payload["refs"][0]
    assert set(ref) == {
        "chunk_id",
        "ref_id",
        "summary",
        "lexical_score",
        "rerank_score",
        "metadata",
        "read_endpoint",
    }
    assert ref["chunk_id"] == "chunk_alpha_1"
    assert ref["ref_id"] == "chunk:chunk_alpha_1"
    assert ref["lexical_score"] > 0
    assert ref["rerank_score"] is None
    assert ref["read_endpoint"] == f"/api/agent-bridge/resource/chunk:chunk_alpha_1?project_id={project_id}"
    assert set(ref["metadata"]) == {
        "material_id",
        "title",
        "page",
        "chunk_type",
        "source_relative_path",
        "locator",
        "source_labels",
        "figure_candidate",
    }
    assert ref["metadata"] == {
        "material_id": "mat_alpha",
        "title": "Transformer Attention Review",
        "page": 7,
        "chunk_type": "body",
        "source_relative_path": "papers/attention.pdf",
        "locator": {
            "material_id": "mat_alpha",
            "chunk_id": "chunk_alpha_1",
            "page": 7,
            "chunk_index": 2,
            "bbox": [0.1, 0.2, 0.3, 0.4],
            "bbox_unit": "normalized_ratio",
        },
        "source_labels": ["bm25", "dense"],
        "figure_candidate": "figure:attention-1",
    }
    serialized = str(payload)
    assert "content" not in ref
    assert "abstract" not in serialized
    assert "SHOULD_NOT_LEAK" not in serialized
    assert "ocr" not in serialized.lower()
    assert "private_note" not in serialized


def test_search_refs_rejects_write_or_full_content_flags() -> None:
    """search-refs must fail fast on legacy write-through/full-content flags."""

    client = _client()
    project = _create_project(client)
    for forbidden_param in ("ingest_mode", "include_content"):
        response = client.get(
            "/resources/chunks/search-refs",
            params={
                "project_id": project["project_id"],
                "query": "attention",
                forbidden_param: "query",
            },
        )

        assert response.status_code == 400
        assert forbidden_param in str(response.json())


def test_search_refs_marks_material_only_locators_as_blocking_risk() -> None:
    """Refs without source pages must be visible as non-reproducible evidence."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_page_missing": [
                {
                    "chunk_id": "chunk_without_page",
                    "material_id": "mat_page_missing",
                    "title": "Attention locator gap",
                    "content": "Attention evidence should remain auditable.",
                    "chunk_index": 4,
                    "bbox": [0.1, 0.2, 0.3, 0.4],
                }
            ]
        },
    )

    response = client.get(
        "/resources/chunks/search-refs",
        params={"project_id": project_id, "query": "attention auditable", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_refs"] == 1
    ref = payload["refs"][0]
    assert ref["metadata"]["locator"] == {
        "material_id": "mat_page_missing",
        "chunk_id": "chunk_without_page",
        "chunk_index": 4,
    }
    assert payload["locator_coverage"]["coverage_state"] == "material_only"
    assert payload["locator_coverage"]["risk_level"] == "block"
    assert payload["locator_coverage"]["page_coverage_ratio"] == 0.0
    assert payload["locator_coverage"]["bbox_coverage_ratio"] == 0.0
    assert payload["locator_coverage"]["bbox_unit_counts"] == {}
    assert payload["locator_coverage"]["source_label_coverage_ratio"] == 0.0


def test_search_refs_empty_store_is_stable_and_read_only(monkeypatch: Any) -> None:
    """An empty chunk store returns an empty envelope without backfilling."""

    client = _client()
    project = _create_project(client)
    monkeypatch.setattr(
        resources_router,
        "_ensure_project_chunks",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ensure/backfill called")),
    )

    response = client.get(
        "/resources/chunks/search-refs",
        params={"project_id": project["project_id"], "query": "anything", "top_k": 3},
    )

    assert response.status_code == 200
    assert response.json() == {
        "project_id": project["project_id"],
        "query": "anything",
        "total_refs": 0,
        "locator_coverage": {
            "schema_version": "scholar-ai-evidence-locator-coverage/v1",
            "total_refs": 0,
            "project_ref_count": 0,
            "non_project_ref_count": 0,
            "material_locator_count": 0,
            "page_locator_count": 0,
            "bbox_locator_count": 0,
            "missing_locator_count": 0,
            "page_coverage_ratio": 0.0,
            "bbox_coverage_ratio": 0.0,
            "bbox_unit_counts": {},
            "source_label_count": 0,
            "source_label_coverage_ratio": 0.0,
            "figure_table_locator_count": 0,
            "coverage_state": "no_refs",
            "risk_level": "none",
            "sample_figure_table_ids": [],
            "sample_missing_ref_ids": [],
            "notes": ["No project chunk refs were returned for locator coverage."],
        },
        "refs": [],
    }
