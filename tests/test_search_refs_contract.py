# -*- coding: utf-8 -*-
"""Contract tests for the read-only chunk search refs endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Match
from urllib.parse import urlsplit

import routers.resources_router as resources_router
from python_adapter_server import app


def _client() -> TestClient:
    """Return the shared FastAPI test client for search-ref contracts."""

    return TestClient(app)


def _full_app_get_route_matches(path: str) -> list[str]:
    """Return registered full-app GET route paths that resolve a concrete path.

    Args:
        path: Concrete request path (query string already stripped).

    Returns:
        Registered route path templates whose GET handler matches ``path``,
        excluding the catch-all SPA fallback. Empty when nothing resolves,
        which proves a read_endpoint would 404 against the full app.
    """

    normalized_path = str(path or "").strip()
    assert normalized_path.startswith("/")
    matches: list[str] = []
    for route in app.routes:
        route_path = str(getattr(route, "path", ""))
        if route_path == "/{full_path:path}":
            continue
        route_methods = getattr(route, "methods", None)
        if route_methods is not None and "GET" not in route_methods:
            continue
        if not hasattr(route, "matches"):
            continue
        match, _ = route.matches(
            {"type": "http", "path": normalized_path, "method": "GET"}
        )
        if match is not Match.NONE:
            matches.append(route_path)
    return matches


def _create_project(client: TestClient, title: str = "Search Refs Project") -> dict[str, Any]:
    """Create a project through the public resources API."""

    response = client.post("/resources/project", json={"title": title})
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["project_id"], str)
    return payload


def _write_chunk_fixture(project_id: str, *, content: str | None = None) -> None:
    """Persist a chunk store containing large fields that must not leak."""

    chunk_content = (
        content
        if content is not None
        else "Transformer attention improves sequence modeling and retrieval quality."
    )
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_alpha": [
                {
                    "chunk_id": "chunk_alpha_1",
                    "material_id": "mat_alpha",
                    "title": "Transformer Attention Review",
                    "content": chunk_content,
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


def _write_pdf(path: Path) -> None:
    """Create a tiny local PDF-like fixture for metadata-only scan tests."""

    path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF")


def test_scan_dedupe_key_collapses_translation_outputs() -> None:
    """mono/dual translated PDFs should share the original paper key."""

    original = "Biffi - Laser weldability of AlSi10Mg.pdf"
    mono = "Biffi - Laser weldability of AlSi10Mg.no_watermark.zh-CN.mono.pdf"
    dual = "Biffi - Laser weldability of AlSi10Mg.no_watermark.zh-CN.dual.pdf"

    assert resources_router._build_scan_dedupe_key(original) == resources_router._build_scan_dedupe_key(mono)
    assert resources_router._build_scan_dedupe_key(original) == resources_router._build_scan_dedupe_key(dual)
    assert resources_router._is_translated_scan_derivative(mono) is True
    assert resources_router._is_translated_scan_derivative(dual) is True
    assert resources_router._is_translated_scan_derivative(original) is False


def test_collect_pending_scan_candidates_skips_translation_and_copy_duplicates(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Folder scan should only queue the original paper among generated copies."""

    source_folder = tmp_path / "papers"
    source_folder.mkdir()
    _write_pdf(source_folder / "Sun - Application of adjustable ring mode laser.pdf")
    _write_pdf(source_folder / "Sun - Application of adjustable ring mode laser (1).pdf")
    _write_pdf(source_folder / "Sun - Application of adjustable ring mode laser.no_watermark.zh-CN.mono.pdf")
    _write_pdf(source_folder / "Sun - Application of adjustable ring mode laser.no_watermark.zh-CN.dual.pdf")

    monkeypatch.setattr(resources_router, "_load_doc_store", lambda _project_id: {})

    payload = resources_router._collect_pending_scan_candidates("proj-scan-dedupe", source_folder)

    assert [item["relative_posix"] for item in payload["pending"]] == [
        "Sun - Application of adjustable ring mode laser.pdf"
    ]
    skipped_by_title = {item["title"]: item for item in payload["skipped_results"]}
    assert skipped_by_title[
        "Sun - Application of adjustable ring mode laser.no_watermark.zh-CN.mono.pdf"
    ]["decision"] == "translated_duplicate"
    assert skipped_by_title[
        "Sun - Application of adjustable ring mode laser.no_watermark.zh-CN.dual.pdf"
    ]["decision"] == "translated_duplicate"
    assert skipped_by_title[
        "Sun - Application of adjustable ring mode laser (1).pdf"
    ]["decision"] == "scan_duplicate"


def test_collect_pending_scan_candidates_skips_obvious_non_literature_pdf(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """High-signal non-paper artifacts should not enter literature indexing."""

    source_folder = tmp_path / "papers"
    source_folder.mkdir()
    _write_pdf(source_folder / "TheBlessedDark_English_PnP_W_Cutlines.pdf")

    monkeypatch.setattr(resources_router, "_load_doc_store", lambda _project_id: {})

    payload = resources_router._collect_pending_scan_candidates("proj-scan-dedupe", source_folder)

    assert payload["pending"] == []
    assert payload["skipped_results"] == [
        {
            "title": "TheBlessedDark_English_PnP_W_Cutlines.pdf",
            "status": "skipped",
            "reason": "疑似非论文 PDF（文件名含 PnP/cutlines 等制图标记）",
            "decision": "non_literature_artifact",
            "dedupe_key": "pdf:theblesseddark english pnp w cutlines",
        }
    ]


def test_batch_upload_skips_translated_and_non_literature_pdfs() -> None:
    """Upload path should apply the same source-admission rules as folder scan."""

    client = _client()
    project = _create_project(client, title="Upload Dedupe Project")

    response = client.post(
        "/resources/upload/batch",
        data={"project_id": project["project_id"]},
        files=[
            (
                "files",
                (
                    "Biffi - Laser weldability of AlSi10Mg.no_watermark.zh-CN.mono.pdf",
                    b"not parsed because skipped",
                    "application/pdf",
                ),
            ),
            (
                "files",
                (
                    "TheBlessedDark_English_PnP_W_Cutlines.pdf",
                    b"not parsed because skipped",
                    "application/pdf",
                ),
            ),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["successful_files"] == 0
    assert payload["skipped_files"] == 2
    assert payload["failed_files"] == 0
    assert [item["decision"] for item in payload["results"]] == [
        "translated_duplicate",
        "non_literature_artifact",
    ]


@pytest.mark.asyncio
async def test_single_upload_skips_normalized_duplicate_before_persist(monkeypatch: Any) -> None:
    """Duplicate filename variants should be blocked before source persistence."""

    class _Upload:
        filename = "Sun - Application of adjustable ring mode laser (1).pdf"

    monkeypatch.setattr(
        resources_router,
        "_load_doc_store",
        lambda _project_id: {
            "mat-existing": {
                "title": "Sun - Application of adjustable ring mode laser.pdf",
                "source_relative_path": "Sun - Application of adjustable ring mode laser.pdf",
            }
        },
    )

    async def _fail_persist(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("duplicate upload should not be persisted")

    monkeypatch.setattr(resources_router, "_persist_upload_to_source_file", _fail_persist)

    result = await resources_router._ingest_uploaded_document("proj-upload-dedupe", _Upload(), store=object())

    assert result["status"] == "skipped"
    assert result["decision"] == "scan_duplicate"


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
        "sample_figure_table_ids": ["figure:attention-1"],
        "sample_invalid_bbox_ref_ids": [],
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
        "figure_candidate_detail",
        "image_paths",
    }
    assert ref["metadata"] | {"figure_candidate_detail": None} == {
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
        "figure_candidate_detail": None,
        "image_paths": [],
    }
    detail = ref["metadata"]["figure_candidate_detail"]
    assert detail["id"] == "figure:attention-1"
    assert detail["kind"] == "figure"
    assert detail["material_id"] == "mat_alpha"
    assert detail["chunk_id"] == "chunk_alpha_1"
    assert detail["page"] == 7
    assert detail["chunk_index"] == 2
    assert detail["source"] == "chunk_metadata"
    serialized = str(payload)
    assert "content" not in ref
    assert "abstract" not in serialized
    assert "SHOULD_NOT_LEAK" not in serialized
    assert "ocr" not in serialized.lower()
    assert "private_note" not in serialized


def test_search_refs_blends_pixel_backed_visual_refs_for_appearance_query() -> None:
    """Visual queries should not lose real chunk image assets behind text hits."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    text_chunks = [
        {
            "chunk_id": f"text_hit_{index}",
            "material_id": f"mat_text_{index}",
            "title": f"AlSi10Mg laser welding process paper {index}",
            "content": "AlSi10Mg laser welding process parameters and porosity suppression.",
            "page": index + 1,
            "chunk_index": index,
            "bbox": [0.1, 0.1, 0.2, 0.2],
        }
        for index in range(5)
    ]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            **{f"mat_text_{index}": [chunk] for index, chunk in enumerate(text_chunks)},
            "mat_page_list": [
                {
                    "chunk_id": "visual_page_list_1",
                    "material_id": "mat_page_list",
                    "title": "Ping AlSi10Mg laser welding figure list",
                    "content": "Figure 7. Weld upper surface appearance and bead formation results.",
                    "raw_content": "Figure 7. Weld upper surface appearance and bead formation results.",
                    "page": 3,
                    "chunk_index": 12,
                    "chunk_type": "figure_caption",
                    "bbox": [0.0, 0.0, 1.0, 1.0],
                    "image_paths": [
                        "figure_assets/extracted/Ping/p0003_page_list.png",
                    ],
                }
            ],
            "mat_cross": [
                {
                    "chunk_id": "visual_cross_section_1",
                    "material_id": "mat_cross",
                    "title": "Ping AlSi10Mg laser welding cross-section figures",
                    "content": "Figure 6. Weld cross-section morphology and penetration depth.",
                    "raw_content": "Figure 6. Weld cross-section morphology and penetration depth.",
                    "page": 9,
                    "chunk_index": 67,
                    "chunk_type": "figure_caption",
                    "bbox": [0.1, 0.2, 0.7, 0.4],
                    "image_paths": [
                        "figure_assets/extracted/Ping/p0009_img001.jpeg",
                    ],
                }
            ],
            "mat_visual": [
                {
                    "chunk_id": "visual_surface_1",
                    "material_id": "mat_visual",
                    "title": "Ping AlSi10Mg laser welding appearance figures",
                    "content": "Figure 7. Weld upper surface appearance and bead formation results.",
                    "raw_content": "Figure 7. Weld upper surface appearance and bead formation results.",
                    "page": 10,
                    "chunk_index": 68,
                    "chunk_type": "figure_caption",
                    "bbox": [0.1, 0.2, 0.7, 0.4],
                    "image_paths": [
                        "figure_assets/extracted/Ping/p0010_img001.jpeg",
                    ],
                }
            ],
        },
    )

    response = client.get(
        "/resources/chunks/search-refs",
        params={"project_id": project_id, "query": "AlSi10Mg 外观 上表面 图片", "top_k": 4},
    )

    assert response.status_code == 200
    refs = response.json()["refs"]
    visual_refs = [ref for ref in refs if ref["metadata"]["image_paths"]]
    assert visual_refs[0]["chunk_id"] == "visual_surface_1"
    assert "visual_page_list_1" not in {ref["chunk_id"] for ref in visual_refs}
    assert visual_refs[0]["metadata"]["source_labels"] == ["visual_image_asset"]
    assert visual_refs[0]["metadata"]["figure_candidate_detail"]["asset_path"] == (
        "figure_assets/extracted/Ping/p0010_img001.jpeg"
    )


def test_search_refs_blends_project_figure_asset_files_without_mutating_chunks() -> None:
    """Derived project figure assets should enter visual refs without editing truth."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    chunk_store = {
        "mat_surface": [
            {
                "chunk_id": "surface_asset_chunk",
                "material_id": "mat_surface",
                "title": "AlSi10Mg surface appearance figure",
                "content": "Figure 7 shows surface appearance, morphology, and weld bead formation.",
                "page": 10,
                "chunk_index": 4,
                "chunk_type": "figure_caption",
                "bbox": [0.12, 0.18, 0.48, 0.36],
            }
        ],
        "mat_text": [
            {
                "chunk_id": f"text_only_{index}",
                "material_id": "mat_text",
                "title": f"AlSi10Mg process parameters {index}",
                "content": "AlSi10Mg laser welding process parameters and porosity control.",
                "page": index + 1,
                "chunk_index": index,
            }
            for index in range(4)
        ],
    }
    resources_router._save_chunk_store(project_id, chunk_store)  # type: ignore[attr-defined]
    asset_path = resources_router.project_data_path(  # type: ignore[attr-defined]
        project_id,
        "figure_assets",
        "mat_surface",
        "surface_asset_chunk-Figure7-deadbeef.jpg",
    )
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"derived project figure asset")

    response = client.get(
        "/resources/chunks/search-refs",
        params={
            "project_id": project_id,
            "query": "surface appearance morphology figure image",
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    refs_by_chunk = {ref["chunk_id"]: ref for ref in payload["refs"]}
    ref = refs_by_chunk["surface_asset_chunk"]
    assert ref["metadata"]["image_paths"] == [
        "figure_assets/mat_surface/surface_asset_chunk-Figure7-deadbeef.jpg"
    ]
    assert ref["metadata"]["figure_candidate_detail"]["source"] == "project_figure_asset"
    assert ref["metadata"]["figure_candidate_detail"]["asset_path"] == (
        "figure_assets/mat_surface/surface_asset_chunk-Figure7-deadbeef.jpg"
    )
    assert "visual_project_figure_asset" in ref["metadata"]["source_labels"]
    assert "visual_image_asset" in ref["metadata"]["source_labels"]

    persisted = resources_router._load_chunk_store(project_id)  # type: ignore[attr-defined]
    assert "image_paths" not in persisted["mat_surface"][0]
    assert "asset_path" not in persisted["mat_surface"][0]


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


def test_search_refs_reports_invalid_bbox_without_leaking_coordinates() -> None:
    """Malformed bbox metadata must stay visible as a repairable locator gap."""

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        {
            "mat_invalid_bbox": [
                {
                    "chunk_id": "chunk_invalid_bbox",
                    "material_id": "mat_invalid_bbox",
                    "title": "Attention invalid bbox",
                    "content": "Attention evidence with malformed layout coordinates.",
                    "page": 5,
                    "locator": {
                        "material_id": "mat_invalid_bbox",
                        "chunk_id": "chunk_invalid_bbox",
                        "page": 5,
                        "bbox": [1.2, 0.1, 0.2, 0.3],
                        "bbox_unit": "normalized_ratio",
                    },
                }
            ]
        },
    )

    response = client.get(
        "/resources/chunks/search-refs",
        params={"project_id": project_id, "query": "attention malformed layout", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_refs"] == 1
    ref = payload["refs"][0]
    assert ref["metadata"]["locator"] == {
        "material_id": "mat_invalid_bbox",
        "chunk_id": "chunk_invalid_bbox",
        "page": 5,
    }
    locator_coverage = payload["locator_coverage"]
    assert locator_coverage["coverage_state"] == "page_located"
    assert locator_coverage["risk_level"] == "warn"
    assert locator_coverage["page_locator_count"] == 1
    assert locator_coverage["bbox_locator_count"] == 0
    assert locator_coverage["invalid_bbox_count"] == 1
    assert locator_coverage["sample_invalid_bbox_ref_ids"] == ["chunk:chunk_invalid_bbox"]
    assert locator_coverage["bbox_unit_counts"] == {}
    assert "invalid bbox" in " ".join(locator_coverage["notes"]).lower()
    serialized = str(payload)
    assert "1.2" not in serialized
    assert "[1.2, 0.1, 0.2, 0.3]" not in serialized


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
            "invalid_bbox_count": 0,
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
            "sample_invalid_bbox_ref_ids": [],
            "sample_missing_ref_ids": [],
            "notes": ["No project chunk refs were returned for locator coverage."],
        },
        "refs": [],
    }


def test_search_ref_read_endpoint_resolves_to_registered_read_only_route(
    monkeypatch: Any,
) -> None:
    """Each search-ref read_endpoint must resolve to a real read-only GET route.

    The searchable-ref link in the knowledge runtime chain is only auditable if
    its advertised read_endpoint resolves to a registered full-app GET route
    (not a 404 dead link) and is read-only. A matching endpoint string alone is
    not proof, so this asserts route resolution and GET-method binding against
    the full FastAPI app for every ref returned by the contract.
    """

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    monkeypatch.setattr(
        resources_router,
        "_collect_pending_scan_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ingest helper called")
        ),
    )
    monkeypatch.setattr(
        resources_router,
        "_ingest_pending_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ingest helper called")
        ),
    )

    response = client.get(
        "/resources/chunks/search-refs",
        params={"project_id": project_id, "query": "transformer attention", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_refs"] >= 1
    for ref in payload["refs"]:
        read_endpoint = ref["read_endpoint"]
        assert read_endpoint.startswith("/api/agent-bridge/resource/chunk:")
        # Strip the query string before route resolution; the path carries identity.
        read_path = urlsplit(read_endpoint).path
        matches = _full_app_get_route_matches(read_path)
        assert matches, f"read_endpoint not registered as GET route: {read_endpoint}"
        # The resolved route must be read-only: no POST/PUT/PATCH/DELETE binding.
        for route in app.routes:
            if str(getattr(route, "path", "")) not in matches:
                continue
            route_methods = getattr(route, "methods", None)
            if route_methods is None:
                continue
            assert "GET" in route_methods
            assert not (route_methods & {"POST", "PUT", "PATCH", "DELETE"}), (
                f"search-ref read route exposes write methods: {route_methods}"
            )


def test_search_ref_route_resolution_guard_has_teeth() -> None:
    """The route-resolution guard must reject a read_endpoint that 404s.

    Negative self-check: a fabricated read_endpoint that does not correspond to
    any registered route must produce no full-app GET match, proving the
    positive assertion above is not vacuously true.
    """

    fabricated = "/api/agent-bridge/does-not-exist/chunk:ghost"
    assert _full_app_get_route_matches(fabricated) == []


def test_search_ref_read_endpoint_loads_bounded_chunk_context(monkeypatch: Any) -> None:
    """Following a search-ref read_endpoint must load that ref's bounded chunk.

    Route resolution alone does not prove the searchable-ref -> bounded-context
    link works end to end: the producer (search-refs) and the reader could drift
    on ref-id format, query params, or chunk lookup while each half stays green.
    This issues a real GET against the exact read_endpoint string emitted by
    search-refs and asserts the reader returns 200, the same ref identity, the
    chunk's actual content, bound locator metadata, and no leaked private fields.
    """

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    monkeypatch.setattr(
        resources_router,
        "_collect_pending_scan_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ingest helper called")
        ),
    )
    monkeypatch.setattr(
        resources_router,
        "_ingest_pending_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ingest helper called")
        ),
    )

    search_response = client.get(
        "/resources/chunks/search-refs",
        params={"project_id": project_id, "query": "transformer attention", "top_k": 5},
    )
    assert search_response.status_code == 200
    refs = search_response.json()["refs"]
    assert refs, "search-refs returned no refs to follow"
    ref = refs[0]
    assert ref["chunk_id"] == "chunk_alpha_1"
    read_endpoint = ref["read_endpoint"]

    # Follow the exact emitted read_endpoint string, not a hand-built URL.
    read_response = client.get(read_endpoint)
    assert read_response.status_code == 200, (
        f"read_endpoint {read_endpoint} returned {read_response.status_code}: "
        f"{read_response.text}"
    )
    payload = read_response.json()
    # The reader must resolve to the same ref identity and kind.
    assert payload["ref_id"] == ref["ref_id"] == "chunk:chunk_alpha_1"
    assert payload["kind"] == "chunk"
    # Bounded context must carry the chunk's actual content, not a placeholder.
    assert "Transformer attention improves sequence modeling" in payload["content"]
    # Locator/source metadata must bind back to the same chunk.
    assert payload["metadata"]["chunk_id"] == "chunk_alpha_1"
    assert payload["metadata"]["material_id"] == "mat_alpha"
    assert payload["metadata"]["page"] == 7
    assert payload["metadata"]["source_relative_path"] == "papers/attention.pdf"
    # The bounded reader must not leak the private chunk fields.
    serialized = read_response.text
    assert "SHOULD_NOT_LEAK" not in serialized
    assert "abstract" not in serialized.lower()
    assert "ocr" not in serialized.lower()
    assert "private_note" not in serialized


def test_search_ref_read_endpoint_enforces_bounded_cursor_context(
    monkeypatch: Any,
) -> None:
    """The emitted read_endpoint must remain server-bounded when followed.

    Search refs are model-context entry points, so the linked reader must honor
    cursor and max_chars limits instead of returning an unbounded chunk body.
    The test follows the exact emitted URL with extra query parameters and pins
    the response envelope fields that make partial context recovery resumable.
    """

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    long_content = (
        "Transformer attention bounded context proof. "
        "Cursor pagination must return only the requested slice. "
        "Private source fields stay out of the model context. "
    ) * 4
    _write_chunk_fixture(project_id, content=long_content)
    monkeypatch.setattr(
        resources_router,
        "_collect_pending_scan_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ingest helper called")
        ),
    )
    monkeypatch.setattr(
        resources_router,
        "_ingest_pending_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ingest helper called")
        ),
    )

    search_response = client.get(
        "/resources/chunks/search-refs",
        params={"project_id": project_id, "query": "bounded context cursor", "top_k": 5},
    )
    assert search_response.status_code == 200
    ref = search_response.json()["refs"][0]
    read_endpoint = ref["read_endpoint"]
    separator = "&" if "?" in read_endpoint else "?"
    bounded_endpoint = f"{read_endpoint}{separator}max_chars=120&cursor=17"

    read_response = client.get(bounded_endpoint)

    assert read_response.status_code == 200
    payload = read_response.json()
    expected_slice = long_content[17:137]
    assert payload["ref_id"] == ref["ref_id"] == "chunk:chunk_alpha_1"
    assert payload["content"] == expected_slice
    assert len(payload["content"]) == 120
    assert payload["truncated"] is True
    assert payload["cursor"] == "17"
    assert payload["next_cursor"] == "137"
    assert payload["max_chars"] == 120
    assert payload["total_chars"] == len(long_content)
    assert payload["metadata"]["offset"] == 17
    assert payload["metadata"]["returned_chars"] == 120
    assert "SHOULD_NOT_LEAK" not in read_response.text

    too_small_response = client.get(f"{read_endpoint}{separator}max_chars=99")
    assert too_small_response.status_code == 422


def test_search_ref_reader_rejects_unknown_chunk_ref(monkeypatch: Any) -> None:
    """A read_endpoint for a non-existent chunk must 404, proving the guard bites.

    Negative self-check for the end-to-end load: a read_endpoint shaped exactly
    like the emitted one but pointing at a chunk id that is not in the store must
    return 404, so the positive content assertions cannot pass vacuously.
    """

    client = _client()
    project = _create_project(client)
    project_id = project["project_id"]
    _write_chunk_fixture(project_id)
    monkeypatch.setattr(
        resources_router,
        "_ensure_project_chunks",
        lambda *_args, **_kwargs: {},
    )

    missing_endpoint = (
        f"/api/agent-bridge/resource/chunk:chunk_absent_404?project_id={project_id}"
    )
    response = client.get(missing_endpoint)
    assert response.status_code == 404
    assert "chunk_absent_404" in response.text
