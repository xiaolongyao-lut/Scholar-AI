"""Contract tests for academic writing export surfaces."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from python_adapter_server import app


def _build_export_fixture(client: TestClient) -> dict[str, Any]:
    """Create one project fixture that exercises evidence export behavior."""

    project_response = client.post(
        "/resources/project",
        json={"title": "Academic Export Contract Project"},
    )
    assert project_response.status_code == 200
    project_payload = project_response.json()

    section_response = client.post(
        "/resources/section",
        json={
            "project_id": project_payload["project_id"],
            "title": "Results",
            "order": 1,
            "description": "Section used for export contract verification.",
        },
    )
    assert section_response.status_code == 200
    section_payload = section_response.json()

    used_material_response = client.post(
        "/resources/material",
        json={
            "project_id": project_payload["project_id"],
            "title": "同步效率研究",
            "summary": "该研究总结了同步效率提升与误码率控制的关键结论。",
            "focus_points": ["同步效率", "误码率"],
        },
    )
    assert used_material_response.status_code == 200
    used_material_payload = used_material_response.json()

    unused_material_response = client.post(
        "/resources/material",
        json={
            "project_id": project_payload["project_id"],
            "title": "备用资料",
            "summary": "尚未在草稿中引用的对照资料。",
            "focus_points": ["对照实验"],
        },
    )
    assert unused_material_response.status_code == 200
    unused_material_payload = unused_material_response.json()

    anchor_id = f"cite:{used_material_payload['material_id']}:anchor1"
    anchor_token = f"[^{anchor_id}]"
    anchored_paragraph = f"Anchored claim {anchor_token} links the primary source."
    uncited_paragraph = (
        "This paragraph is intentionally long enough to exceed eighty characters "
        "without any citation token so the export review will flag it."
    )
    content = f"{anchored_paragraph}\n\n{uncited_paragraph}"
    start_offset = content.index(anchor_token)
    end_offset = start_offset + len(anchor_token)

    draft_response = client.post(
        "/resources/draft",
        json={
            "project_id": project_payload["project_id"],
            "section_id": section_payload["section_id"],
            "title": "Results Draft",
            "content": content,
            "citation_anchors": [
                {
                    "id": anchor_id,
                    "materialId": used_material_payload["material_id"],
                    "token": anchor_token,
                    "startOffset": start_offset,
                    "endOffset": end_offset,
                    "ordinal": 1,
                }
            ],
        },
    )
    assert draft_response.status_code == 200
    draft_payload = draft_response.json()

    return {
        "project": project_payload,
        "section": section_payload,
        "used_material": used_material_payload,
        "unused_material": unused_material_payload,
        "draft": draft_payload,
        "anchor_id": anchor_id,
    }


def test_json_export_includes_academic_evidence_contract() -> None:
    """JSON export should expose evidence rows, citation chain, and review findings."""

    client = TestClient(app)
    fixture = _build_export_fixture(client)

    response = client.get(
        f"/resources/project/{fixture['project']['project_id']}/export",
        params={"format": "json"},
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["project"]["project_id"] == fixture["project"]["project_id"]
    assert payload["document_count"] == 0

    evidence_rows = {
        row["material_id"]: row
        for row in payload["evidence_rows"]
    }
    used_row = evidence_rows[fixture["used_material"]["material_id"]]
    unused_row = evidence_rows[fixture["unused_material"]["material_id"]]

    assert used_row["evidence_id"] == f"evidence:{fixture['used_material']['material_id']}"
    assert used_row["status"] == "used"
    assert used_row["anchor_ids"] == [fixture["anchor_id"]]
    assert "同步效率提升" in used_row["excerpt"]
    assert used_row["provenance"]["material_title"] == fixture["used_material"]["title"]

    assert unused_row["status"] == "unused"
    assert unused_row["anchor_ids"] == []

    assert len(payload["citation_chain"]) == 1
    citation_row = payload["citation_chain"][0]
    assert citation_row["anchor_id"] == fixture["anchor_id"]
    assert citation_row["section_id"] == fixture["section"]["section_id"]
    assert citation_row["paragraph_index"] == 1
    assert citation_row["material_id"] == fixture["used_material"]["material_id"]
    assert citation_row["evidence_id"] == f"evidence:{fixture['used_material']['material_id']}"
    assert "[^" not in citation_row["claim_excerpt"]
    assert "Anchored claim" in citation_row["claim_excerpt"]
    assert "同步效率提升" in citation_row["source_excerpt"]

    assert any(
        finding["id"] == f"uncited-paragraphs:{fixture['draft']['draft_id']}"
        and finding["severity"] == "warning"
        for finding in payload["review_findings"]
    )


def test_markdown_export_renders_academic_appendix_sections() -> None:
    """Markdown export should surface the academic evidence appendix sections."""

    client = TestClient(app)
    fixture = _build_export_fixture(client)

    response = client.get(
        f"/resources/project/{fixture['project']['project_id']}/export",
        params={"format": "markdown"},
    )

    assert response.status_code == 200
    payload = response.json()
    content = payload["content"]

    assert payload["format"] == "markdown"
    assert "## 证据表" in content
    assert "| Evidence ID | Material | Status | Anchors | Excerpt |" in content
    assert f"evidence:{fixture['used_material']['material_id']}" in content
    assert fixture["used_material"]["title"] in content
    assert "## 引用链" in content
    assert fixture["anchor_id"] in content
    assert "Anchored claim" in content
    assert "## 审计提示" in content
    assert "long paragraph(s) have no citation anchors." in content


def test_openapi_export_schema_exposes_academic_appendix_contract() -> None:
    """OpenAPI should publish a named export response model with appendix fields."""

    schema = app.openapi()
    operation = schema["paths"]["/resources/project/{project_id}/export"]["get"]
    success_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success_schema == {"$ref": "#/components/schemas/ProjectExportPayload"}

    export_schema = schema["components"]["schemas"]["ProjectExportPayload"]
    assert set(export_schema["properties"]) >= {
        "project_id",
        "format",
        "evidence_rows",
        "citation_chain",
        "review_findings",
    }

    evidence_items = export_schema["properties"]["evidence_rows"]["items"]
    citation_items = export_schema["properties"]["citation_chain"]["items"]
    review_items = export_schema["properties"]["review_findings"]["items"]
    assert evidence_items == {"$ref": "#/components/schemas/ProjectExportEvidenceRowPayload"}
    assert citation_items == {"$ref": "#/components/schemas/ProjectExportCitationChainPayload"}
    assert review_items == {"$ref": "#/components/schemas/ProjectExportReviewFindingPayload"}
