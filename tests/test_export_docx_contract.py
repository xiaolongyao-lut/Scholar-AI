# -*- coding: utf-8 -*-
"""Contract tests for the TipTap HTML to academic DOCX export route."""

from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from python_adapter_server import app


def _document_xml(docx_bytes: bytes, tmp_path: Path) -> str:
    """Extract the main WordprocessingML body from a DOCX response."""

    path = tmp_path / "export.docx"
    path.write_bytes(docx_bytes)
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_export_docx_renders_academic_citations_tables_and_captions(tmp_path: Path) -> None:
    """DOCX export should preserve academic structures, not plain text only."""

    client = TestClient(app)
    response = client.post(
        "/api/export/docx",
        json={
            "title": "AlSi10Mg Review",
            "html": (
                "<h1>引言</h1>"
                "<p>AlSi10Mg 孔隙会影响疲劳裂纹萌生[1]，并且证据可回读[chunk:abc]。</p>"
                "<table>"
                "<tr><th>因素</th><th>影响</th></tr>"
                "<tr><td>孔隙</td><td>疲劳寿命降低[2]</td></tr>"
                "</table>"
                "<figcaption>图 1 熔池流动示意图</figcaption>"
            ),
            "json": {"type": "doc"},
            "style_profile": "gb_t_7714_review",
            "verify_with_word": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.headers["x-litassist-export-quality"] == (
        "citations=3;tables=1;captions=1;style_profile=gb_t_7714_review;"
        "citation_style=numeric;crossrefs=0;formulas=0;word_verify=requested_unavailable"
    )
    xml = _document_xml(response.content, tmp_path)
    assert "AlSi10Mg Review" in xml
    assert "引言" in xml
    assert "w:val=\"superscript\"" in xml
    assert xml.count("w:val=\"superscript\"") >= 3
    assert "w:tblBorders" in xml
    assert "w:val=\"nil\"" in xml
    assert "w:instrText" in xml
    assert "SEQ Figure" in xml
    assert "熔池流动示意图" in xml


def test_export_docx_renders_cross_references_and_formula_omml(tmp_path: Path) -> None:
    """Body figure/table/equation mentions should become Word fields."""

    client = TestClient(app)
    response = client.post(
        "/api/export/docx",
        json={
            "title": "Reference Ready Review",
            "html": (
                "<p>如图 1、表 1 和式（1）所示，熔池扰动会改变孔隙演化路径。</p>"
                "<figcaption>图 1 熔池扰动示意图</figcaption>"
                "<table>"
                "<tr><th>参数</th><th>趋势</th></tr>"
                "<tr><td>扫描速度</td><td>孔隙率变化</td></tr>"
                "</table>"
                "<figcaption>表 1 工艺参数对比</figcaption>"
                "<p>式（1）：<span data-formula=\"P = F / A\" data-equation-number=\"1\"></span></p>"
            ),
            "style_profile": "gb_t_7714_review",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-litassist-export-quality"] == (
        "citations=0;tables=1;captions=2;style_profile=gb_t_7714_review;"
        "citation_style=numeric;crossrefs=3;formulas=1;word_verify=skipped"
    )
    xml = _document_xml(response.content, tmp_path)
    assert "REF litassist_figure_1" in xml
    assert "REF litassist_table_1" in xml
    assert "REF litassist_equation_1" in xml
    assert "w:bookmarkStart" in xml
    assert "w:name=\"litassist_figure_1\"" in xml
    assert "w:name=\"litassist_table_1\"" in xml
    assert "w:name=\"litassist_equation_1\"" in xml
    assert "m:oMath" in xml
    assert "P = F / A" in xml


def test_export_docx_style_profile_changes_quality_and_layout(tmp_path: Path) -> None:
    """Style profiles should be explicit contract knobs, not ignored strings."""

    client = TestClient(app)
    response = client.post(
        "/api/export/docx",
        json={
            "title": "APA Manuscript",
            "html": "<h1>Introduction</h1><p>Evidence supports this claim (Smith, 2024).</p>",
            "style_profile": "apa",
        },
    )

    assert response.status_code == 200
    assert "style_profile=apa" in response.headers["x-litassist-export-quality"]
    assert "citation_style=author_year" in response.headers["x-litassist-export-quality"]
    xml = _document_xml(response.content, tmp_path)
    assert "w:pgMar" in xml
    assert "Introduction" in xml


def test_export_docx_rejects_unknown_style_profile() -> None:
    """Unknown journal profiles should fail visibly instead of silently falling back."""

    client = TestClient(app)
    response = client.post(
        "/api/export/docx",
        json={"title": "Bad Profile", "html": "<p>content</p>", "style_profile": "unknown"},
    )

    assert response.status_code == 400
    assert "unsupported style_profile" in str(response.json())


def test_export_docx_rejects_empty_html() -> None:
    """Empty HTML should be rejected by the request model before rendering."""

    client = TestClient(app)
    response = client.post(
        "/api/export/docx",
        json={"title": "Empty", "html": ""},
    )

    assert response.status_code == 422


def test_export_docx_action_preflight_blocks_when_required() -> None:
    """Project-scoped DOCX export should honor explicit workflow preflight."""

    client = TestClient(app)
    response = client.post(
        "/api/export/docx",
        json={
            "title": "Blocked DOCX",
            "html": "<p>Unverified export body.</p>",
            "project_id": "project-docx-preflight-blocked",
            "require_action_preflight": True,
        },
    )

    assert response.status_code == 409
    detail = response.json()
    assert detail["error"] == "action_preflight_blocked"
    preflight = detail["action_preflight"]
    assert preflight["schema_version"] == "scholar_ai_action_preflight_v1"
    assert preflight["action_id"] == "export.docx"
    assert preflight["required_claim_id"] == "export_readiness"
    assert preflight["require_ready"] is True
    assert preflight["can_proceed"] is False
    assert preflight["summary"]["unresolved_is_ready"] is False
