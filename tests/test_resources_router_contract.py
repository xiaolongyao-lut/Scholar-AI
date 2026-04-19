# -*- coding: utf-8 -*-
"""Contract tests for the writing resource API used by the frontend."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from python_adapter_server import app


def _build_anchor(
    anchor_id: str,
    material_id: str,
    token: str,
    start_offset: int,
    end_offset: int,
    ordinal: int,
) -> dict[str, Any]:
    """
    Build one frontend-compatible citation anchor payload.

    Why:
        The editor and backend must agree on the exact JSON shape so refresh and
        restore operations can round-trip anchor metadata losslessly.
    """
    return {
        "id": anchor_id,
        "materialId": material_id,
        "token": token,
        "startOffset": start_offset,
        "endOffset": end_offset,
        "ordinal": ordinal,
    }


def test_draft_round_trip_preserves_citation_anchor_payload() -> None:
    """Draft create/save/get should preserve citation anchor metadata."""
    client = TestClient(app)
    first_anchor = _build_anchor(
        "cite:mat-1:anchor1",
        "mat-1",
        "[^cite:mat-1:anchor1]",
        13,
        34,
        1,
    )
    second_anchor = _build_anchor(
        "cite:mat-2:anchor2",
        "mat-2",
        "[^cite:mat-2:anchor2]",
        48,
        69,
        2,
    )

    project_response = client.post("/resources/project", json={"title": "Citation QA Project"})
    assert project_response.status_code == 200
    project_payload = project_response.json()

    section_response = client.post(
        "/resources/section",
        json={
            "project_id": project_payload["project_id"],
            "title": "Introduction",
            "order": 1,
        },
    )
    assert section_response.status_code == 200
    section_payload = section_response.json()

    create_response = client.post(
        "/resources/draft",
        json={
            "project_id": project_payload["project_id"],
            "section_id": section_payload["section_id"],
            "title": "Intro Draft",
            "content": "Sentence one [^cite:mat-1:anchor1].",
            "citation_anchors": [first_anchor],
        },
    )
    assert create_response.status_code == 200
    create_payload = create_response.json()
    assert create_payload["citation_anchors"] == [first_anchor]

    save_response = client.put(
        f"/resources/draft/{create_payload['draft_id']}",
        json={
            "content": "Sentence one [^cite:mat-1:anchor1].\nSentence two [^cite:mat-2:anchor2].",
            "citation_anchors": [first_anchor, second_anchor],
        },
    )
    assert save_response.status_code == 200
    save_payload = save_response.json()
    assert save_payload["citation_anchors"] == [first_anchor, second_anchor]

    get_response = client.get(f"/resources/draft/{create_payload['draft_id']}")
    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["citation_anchors"] == [first_anchor, second_anchor]
    assert "[^cite:mat-2:anchor2]" in get_payload["content"]

    revision_response = client.get(
        "/resources/revisions",
        params={"draft_id": create_payload["draft_id"]},
    )
    assert revision_response.status_code == 200
    revision_payloads = revision_response.json()
    assert len(revision_payloads) == 1
    assert revision_payloads[0]["citation_anchors"] == [first_anchor, second_anchor]


def test_cors_preflight_allows_local_frontend_origin() -> None:
    """The API should answer browser preflight requests from the local frontend."""
    client = TestClient(app)

    response = client.options(
        "/resources/project",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


def test_material_endpoints_round_trip_project_scoped_cards() -> None:
    """Material create/list/get should expose stable cards for the reference drawer."""
    client = TestClient(app)

    project_response = client.post("/resources/project", json={"title": "Material Contract Project"})
    assert project_response.status_code == 200
    project_payload = project_response.json()

    create_response = client.post(
        "/resources/material",
        json={
            "project_id": project_payload["project_id"],
            "title": "量子纠缠协议 2024",
            "title_en": "Quantum Entanglement Protocols 2024",
            "summary": "分析了当前量子同步的主要瓶颈。",
            "summary_en": "Analyzes major bottlenecks in quantum synchronization.",
            "type": "PAPER",
            "focus_points": ["同步效率", "误码率"],
            "focus_points_en": ["Sync Efficiency", "Bit Error Rate"],
        },
    )
    assert create_response.status_code == 200
    material_payload = create_response.json()
    assert material_payload["project_id"] == project_payload["project_id"]
    assert material_payload["focus_points"] == ["同步效率", "误码率"]

    list_response = client.get(
        "/resources/materials",
        params={"project_id": project_payload["project_id"]},
    )
    assert list_response.status_code == 200
    listed_materials = list_response.json()
    assert len(listed_materials) == 1
    assert listed_materials[0]["material_id"] == material_payload["material_id"]

    get_response = client.get(f"/resources/material/{material_payload['material_id']}")
    assert get_response.status_code == 200
    assert get_response.json()["summary_en"] == "Analyzes major bottlenecks in quantum synchronization."


def test_chunk_search_query_driven_ingest_indexes_relevant_files(tmp_path) -> None:
    """chunks/search should optionally ingest query-relevant files before retrieval."""
    client = TestClient(app)
    source_folder = tmp_path / "literature"
    source_folder.mkdir(parents=True)
    (source_folder / "transformer_notes.txt").write_text(
        "Transformer attention mechanism improves sequence modeling.",
        encoding="utf-8",
    )

    project_response = client.post(
        "/resources/project",
        json={
            "title": "Query Driven Ingest Project",
            "source_folder": str(source_folder),
        },
    )
    assert project_response.status_code == 200
    project_payload = project_response.json()

    response = client.get(
        "/resources/chunks/search",
        params={
            "project_id": project_payload["project_id"],
            "query": "transformer attention",
            "top_k": 5,
            "ingest_mode": "query",
            "ingest_limit": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingest"]["enabled"] is True
    assert payload["ingest"]["indexed"] >= 1
    assert payload["results"]
    assert any("transformer" in str(item.get("title", "")).lower() for item in payload["results"])

