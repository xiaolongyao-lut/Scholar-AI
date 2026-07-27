# -*- coding: utf-8 -*-
"""Focused contracts for material-scoped whole-formula PDF candidates."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import routers.resources_router as resources_router
from python_adapter_server import app
from routers.resources_router import _document_extraction as document_extraction
from routers.resources_router import endpoints_search_upload as search_upload

_PYMUPDF_AVAILABLE = importlib.util.find_spec("pymupdf") is not None


def _write_formula_fixture(path: Path, *, rotated: bool = False) -> None:
    """Create a text-layer PDF containing formulas and deliberate prose traps."""

    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((72, 80), "The setting x = 3 was used for every specimen.", fontsize=11)
    page.insert_text((200, 150), "E = mc^2    (1)", fontsize=13)
    page.insert_text((240, 210), "p < 0.05", fontsize=13)
    page.insert_text((72, 270), "Accuracy = 95% in the experiment.", fontsize=11)
    page.insert_text((180, 340), "F = m * a", fontsize=13)
    page.insert_text((500, 340), "(2)", fontsize=13)
    page.insert_text((72, 410), "Figure 2: Accuracy = 95%.", fontsize=11)
    page.insert_text((72, 460), "where x = 5 for every specimen", fontsize=11)
    page.insert_text((72, 510), "https://example.test/?a=b", fontsize=11)
    if rotated:
        page.set_rotation(90)
    document.save(str(path))
    document.close()


def _raw_formula_block(
    text: str,
    bbox: tuple[float, float, float, float],
    *,
    font: str = "Helvetica",
    size: float = 11.0,
) -> dict[str, Any]:
    """Build the minimal PyMuPDF text-block shape used by fragment tests."""

    return {
        "type": 0,
        "bbox": bbox,
        "lines": [
            {
                "bbox": bbox,
                "spans": [
                    {
                        "text": text,
                        "bbox": bbox,
                        "origin": (bbox[0], bbox[3]),
                        "font": font,
                        "size": size,
                        "flags": 0,
                    }
                ],
            }
        ],
    }


@pytest.mark.skipif(not _PYMUPDF_AVAILABLE, reason="PyMuPDF is required")
def test_formula_scan_keeps_whole_lines_and_rejects_prose_equals(tmp_path: Path) -> None:
    """Only independent formula lines become atomic candidates."""

    pdf_path = tmp_path / "formula-lines.pdf"
    _write_formula_fixture(pdf_path)

    first = document_extraction.extract_pymupdf_formula_candidates(pdf_path)
    second = document_extraction.extract_pymupdf_formula_candidates(pdf_path)

    assert [candidate.candidate_id for candidate in first] == [
        candidate.candidate_id for candidate in second
    ]
    assert [candidate.text for candidate in first] == [
        "E = mc^2 (1)",
        "p < 0.05",
        "F = m * a (2)",
    ]
    assert all(candidate.page == 1 for candidate in first)
    assert all(
        0.0 <= candidate.bbox[0] < 1.0
        and 0.0 <= candidate.bbox[1] < 1.0
        and candidate.bbox[2] > 0.0
        and candidate.bbox[3] > 0.0
        and candidate.bbox[0] + candidate.bbox[2] <= 1.000001
        and candidate.bbox[1] + candidate.bbox[3] <= 1.000001
        for candidate in first
    )
    # The separately extracted equation number is part of the selection frame.
    assert first[2].bbox[2] > 0.50
    assert document_extraction.extract_pymupdf_formula_candidates(pdf_path, limit=2) == first[:2]


@pytest.mark.skipif(not _PYMUPDF_AVAILABLE, reason="PyMuPDF is required")
def test_formula_scan_rejects_plus_minus_tolerances_without_losing_equation(
    tmp_path: Path,
) -> None:
    """A tolerance sign cannot independently turn measurement prose into a formula."""

    import pymupdf

    pdf_path = tmp_path / "formula-tolerance-lines.pdf"
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((72, 80), "１０±５ nm", fontsize=11, fontname="china-s")
    page.insert_text((72, 130), "实验力精度 ±１", fontsize=11, fontname="china-s")
    page.insert_text(
        (120, 200),
        "S = (L / L) × 100%    (2)",
        fontsize=13,
        fontname="china-s",
    )
    document.save(str(pdf_path))
    document.close()

    candidates = document_extraction.extract_pymupdf_formula_candidates(pdf_path)

    assert [candidate.text for candidate in candidates] == ["S = (L / L) × 100% (2)"]


@pytest.mark.skipif(not _PYMUPDF_AVAILABLE, reason="PyMuPDF is required")
def test_formula_scan_recovers_fragmented_display_formula_with_equation_number(
    tmp_path: Path,
) -> None:
    """Spatially fragmented formula glyphs still form one atomic selection target."""

    import pymupdf

    pdf_path = tmp_path / "fragmented-formula.pdf"
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text(
        (72, 170),
        "Crack sensitivity is calculated by the following equation:",
        fontsize=11,
    )
    page.insert_text((200, 230), "S =", fontsize=13)
    page.insert_text((240, 218), "L1", fontsize=9)
    page.draw_line((238, 222), (258, 222), width=0.8)
    page.insert_text((246, 236), "L", fontsize=9)
    page.insert_text((266, 230), "x 100%", fontsize=13)
    page.insert_text((500, 230), "(2.1)", fontsize=11)
    page.insert_text((72, 275), "where S is crack sensitivity.", fontsize=11)
    document.save(str(pdf_path))
    document.close()

    candidates = document_extraction.extract_pymupdf_formula_candidates(pdf_path)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.page == 1
    assert candidate.text is not None
    assert "S =" in candidate.text
    assert "100%" in candidate.text
    assert "(2.1)" in candidate.text
    assert candidate.bbox[0] < 0.34
    assert candidate.bbox[2] > 0.50


@pytest.mark.skipif(not _PYMUPDF_AVAILABLE, reason="PyMuPDF is required")
def test_formula_scan_does_not_attach_far_same_baseline_number_from_other_column(
    tmp_path: Path,
) -> None:
    """A right-column equation number cannot widen an unnumbered left formula."""

    import pymupdf

    pdf_path = tmp_path / "two-column-equation-number.pdf"
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((80, 110), "a = b + c", fontsize=12)
    page.insert_text((360, 110), "u = v + w", fontsize=12)
    page.insert_text((540, 110), "(2)", fontsize=12)
    document.save(str(pdf_path))
    document.close()

    candidates = document_extraction.extract_pymupdf_formula_candidates(pdf_path)

    assert [candidate.text for candidate in candidates] == ["a = b + c", "u = v + w (2)"]
    assert all(candidate.bbox[2] < 0.40 for candidate in candidates)


@pytest.mark.skipif(not _PYMUPDF_AVAILABLE, reason="PyMuPDF is required")
def test_formula_scan_rejects_an_implausibly_distant_standalone_number(
    tmp_path: Path,
) -> None:
    """One remote number cannot stretch an otherwise local formula across columns."""

    import pymupdf

    pdf_path = tmp_path / "remote-equation-number.pdf"
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((80, 110), "a = b + c", fontsize=12)
    page.insert_text((540, 110), "(2)", fontsize=12)
    document.save(str(pdf_path))
    document.close()

    candidates = document_extraction.extract_pymupdf_formula_candidates(pdf_path)

    assert [candidate.text for candidate in candidates] == ["a = b + c"]
    assert candidates[0].bbox[2] < 0.30


def test_duplicate_standalone_number_stays_with_its_numbered_formula() -> None:
    """A duplicate OCR number cannot move onto another formula on the same baseline."""

    numbered = document_extraction._PdfFormulaLine(
        block_index=1,
        line_index=0,
        text="a = b (1)",
        rect=(80, 100, 170, 115),
        font_size=12,
    )
    unnumbered = document_extraction._PdfFormulaLine(
        block_index=2,
        line_index=0,
        text="u = v",
        rect=(360, 100, 410, 115),
        font_size=12,
    )
    duplicate_number = document_extraction._PdfFormulaLine(
        block_index=3,
        line_index=0,
        text="(1)",
        rect=(180, 100, 205, 115),
        font_size=11,
    )

    matched = document_extraction._formula_number_for_line(
        unnumbered,
        [numbered, unnumbered],
        [duplicate_number],
        set(),
        page_width=600,
    )

    assert matched is None


def test_fragmented_formula_clustering_does_not_merge_neighboring_anchors() -> None:
    """Two nearby displayed equations retain separate atomic hitboxes."""

    raw_blocks = [
        _raw_formula_block("The following equations are:", (72, 160, 220, 174)),
        _raw_formula_block("S =", (120, 210, 145, 225), size=13),
        _raw_formula_block("x + 1", (150, 210, 190, 225), size=13),
        _raw_formula_block("T =", (225, 210, 250, 225), size=13),
        _raw_formula_block("y + 2", (255, 210, 295, 225), size=13),
        _raw_formula_block("where S and T are responses.", (72, 250, 230, 264)),
    ]

    lines = document_extraction._fragmented_formula_lines(
        raw_blocks,
        page_width=600,
        page_height=800,
    )

    assert [line.text for line in lines] == ["S = x + 1", "T = y + 2"]
    assert lines[0].rect[2] < lines[1].rect[0]


def test_fragmented_formula_keeps_a_close_standalone_number_as_context() -> None:
    """A nearby equation number stays context evidence instead of hiding in the cluster."""

    raw_blocks = [
        _raw_formula_block("S =", (200, 210, 225, 225), size=13),
        _raw_formula_block("x + 1", (230, 210, 265, 225), size=13),
        _raw_formula_block("(2.1)", (270, 210, 300, 225), size=11),
    ]

    lines = document_extraction._fragmented_formula_lines(
        raw_blocks,
        page_width=600,
        page_height=800,
    )

    assert [line.text for line in lines] == ["S = x + 1"]
    assert lines[0].rect[2] < 270


def test_fragmented_formula_accepts_only_a_strict_isolated_relation_seed() -> None:
    """Split operands may join through '=' without restoring plus-minus false positives."""

    raw_blocks = [
        _raw_formula_block("S", (190, 210, 200, 225), size=13),
        _raw_formula_block("=", (205, 210, 215, 225), size=13),
        _raw_formula_block("x + 1", (220, 210, 255, 225), size=13),
        _raw_formula_block("(2.1)", (500, 210, 530, 225), size=11),
    ]

    lines = document_extraction._fragmented_formula_lines(
        raw_blocks,
        page_width=600,
        page_height=800,
    )
    tolerance_lines = document_extraction._fragmented_formula_lines(
        [
            _raw_formula_block("10", (190, 260, 205, 275), size=13),
            _raw_formula_block("±", (210, 260, 220, 275), size=13),
            _raw_formula_block("5 nm", (225, 260, 255, 275), size=13),
            _raw_formula_block("(2.2)", (500, 260, 530, 275), size=11),
        ],
        page_width=600,
        page_height=800,
    )

    assert [line.text for line in lines] == ["S = x + 1"]
    assert tolerance_lines == []


def test_formula_score_does_not_treat_math_font_as_prose_override() -> None:
    """A math-looking font alone cannot promote an equality sentence."""

    assert (
        document_extraction._formula_line_score(
            "Accuracy = 95% for validation samples",
            math_font=True,
            scripted=False,
        )
        is None
    )


@pytest.mark.parametrize("limit", [0, 201, True])
def test_formula_scan_rejects_out_of_contract_limits(tmp_path: Path, limit: Any) -> None:
    """The pure scanner enforces the same 1..200 public bound."""

    with pytest.raises(ValueError, match="between 1 and 200"):
        document_extraction.extract_pymupdf_formula_candidates(
            tmp_path / "unused.pdf",
            limit=limit,
        )


@pytest.mark.skipif(not _PYMUPDF_AVAILABLE, reason="PyMuPDF is required")
def test_formula_scan_rotates_raw_text_bbox_before_normalizing(tmp_path: Path) -> None:
    """A 90-degree page reports coordinates in displayed PDF.js orientation."""

    import pymupdf

    pdf_path = tmp_path / "rotated-formula.pdf"
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((120, 220), "y = a * x + b", fontsize=13)
    page.set_rotation(90)
    document.save(str(pdf_path))
    document.close()

    [candidate] = document_extraction.extract_pymupdf_formula_candidates(pdf_path)
    with pymupdf.open(str(pdf_path)) as reopened:
        rotated_page = reopened[0]
        flags = int(pymupdf.TEXTFLAGS_DICT) & ~int(pymupdf.TEXT_PRESERVE_IMAGES)
        page_dict = rotated_page.get_text("dict", sort=True, flags=flags)
        raw_line = next(
            line
            for block in page_dict["blocks"]
            if block.get("type") == 0
            for line in block.get("lines", [])
            if "y = a * x + b" in "".join(span.get("text", "") for span in line.get("spans", []))
        )
        display_rect = pymupdf.Rect(raw_line["bbox"]) * rotated_page.rotation_matrix
        page_rect = rotated_page.rect
        expected = (
            (max(page_rect.x0, display_rect.x0 - 3.0) - page_rect.x0) / page_rect.width,
            (max(page_rect.y0, display_rect.y0 - 2.0) - page_rect.y0) / page_rect.height,
            (min(page_rect.x1, display_rect.x1 + 3.0) - max(page_rect.x0, display_rect.x0 - 3.0))
            / page_rect.width,
            (min(page_rect.y1, display_rect.y1 + 2.0) - max(page_rect.y0, display_rect.y0 - 2.0))
            / page_rect.height,
        )

    assert candidate.page == 1
    assert candidate.bbox == pytest.approx(expected, abs=1e-6)
    assert candidate.bbox[2] < candidate.bbox[3]


def test_persisted_formula_chunks_are_strictly_filtered_and_preferred() -> None:
    """Reliable formula chunks survive while narrative/point bboxes do not."""

    chunks = [
        {
            "material_id": "mat-paper",
            "chunk_id": "chunk-formula-1",
            "chunk_type": "formula",
            "page": 3,
            "bbox": [0.20, 0.30, 0.40, 0.08],
            "bbox_unit": "normalized_ratio",
            "equation_latex": "E = mc^2",
        },
        {
            "material_id": "mat-paper",
            "chunk_id": "chunk-prose",
            "chunk_type": "narrative",
            "page": 3,
            "bbox": [0.10, 0.10, 0.80, 0.30],
            "raw_content": "The setting x = 3 was used.",
        },
        {
            "material_id": "mat-paper",
            "chunk_id": "chunk-points",
            "chunk_type": "equation",
            "page": 4,
            "bbox": [72, 120, 320, 28],
            "bbox_unit": "pdf_points",
            "equation_latex": "F = ma",
        },
        {
            "material_id": "mat-paper",
            "chunk_id": "chunk-unitless",
            "chunk_type": "formula",
            "page": 5,
            "bbox": [0.15, 0.25, 0.50, 0.10],
            "equation_latex": "p = mv",
        },
    ]
    persisted = document_extraction.formula_candidates_from_chunks(
        chunks,
        material_id="mat-paper",
    )
    assert [candidate.candidate_id for candidate in persisted] == ["chunk-formula-1"]

    detected = document_extraction.PdfFormulaCandidate(
        candidate_id="detected-duplicate",
        page=3,
        bbox=(0.20, 0.30, 0.40, 0.08),
        text="E = mc^2",
    )
    bound = document_extraction.bind_pdf_formula_candidates_to_chunks([detected], chunks)
    assert bound[0].chunk_id == "chunk-formula-1"
    merged = document_extraction.merge_pdf_formula_candidates(persisted, bound)
    assert merged == persisted


def test_formula_binding_does_not_infer_unitless_chunk_geometry() -> None:
    """Numeric range alone must not turn a chunk bbox into reader geometry."""

    detected = document_extraction.PdfFormulaCandidate(
        candidate_id="detected-formula",
        page=7,
        bbox=(0.20, 0.30, 0.40, 0.08),
    )
    chunks = [
        {
            "material_id": "mat-paper",
            "chunk_id": "chunk-unitless",
            "chunk_type": "formula",
            "page": 7,
            "bbox": [0.20, 0.30, 0.40, 0.08],
        }
    ]

    [bound] = document_extraction.bind_pdf_formula_candidates_to_chunks(
        [detected],
        chunks,
    )

    assert bound.chunk_id is None


def test_merge_prefers_overlapping_persisted_candidate_with_same_chunk_id() -> None:
    """One chunk-backed formula keeps one hitbox across parser text variants."""

    persisted = document_extraction.PdfFormulaCandidate(
        candidate_id="chunk-formula-1",
        page=3,
        bbox=(0.20, 0.30, 0.30, 0.08),
        text=r"\frac{L_1}{L}",
        chunk_id="chunk-formula-1",
    )
    overlapping_detected = document_extraction.PdfFormulaCandidate(
        candidate_id="detected-overlap",
        page=3,
        bbox=(0.20, 0.30, 0.30, 0.08),
        text="L₁/L",
        chunk_id="chunk-formula-1",
    )
    distant_detected = document_extraction.PdfFormulaCandidate(
        candidate_id="detected-distant",
        page=3,
        bbox=(0.65, 0.30, 0.20, 0.08),
        text="T = y + 2",
        chunk_id="chunk-formula-1",
    )

    merged = document_extraction.merge_pdf_formula_candidates(
        [persisted],
        [overlapping_detected, distant_detected],
    )

    assert merged == [persisted, distant_detected]


def test_merge_keeps_a_broad_same_chunk_candidate_with_different_geometry() -> None:
    """A shared chunk id cannot collapse a much broader, potentially multi-formula box."""

    persisted = document_extraction.PdfFormulaCandidate(
        candidate_id="chunk-formula-1",
        page=3,
        bbox=(0.20, 0.30, 0.20, 0.06),
        text=r"\frac{L_1}{L}",
        chunk_id="chunk-formula-1",
    )
    broad_detected = document_extraction.PdfFormulaCandidate(
        candidate_id="detected-broad",
        page=3,
        bbox=(0.10, 0.20, 0.80, 0.30),
        text="S = L1/L; T = y + 2",
        chunk_id="chunk-formula-1",
    )

    merged = document_extraction.merge_pdf_formula_candidates(
        [persisted],
        [broad_detected],
    )

    assert {candidate.candidate_id for candidate in merged} == {
        "chunk-formula-1",
        "detected-broad",
    }


def test_merge_replaces_one_broad_persisted_box_with_distinct_atomic_boxes() -> None:
    """A broad chunk box cannot erase two non-overlapping formulas bound to that chunk."""

    broad_persisted = document_extraction.PdfFormulaCandidate(
        candidate_id="chunk-broad",
        page=3,
        bbox=(0.10, 0.30, 0.40, 0.10),
        text="a = b; a = b",
        chunk_id="chunk-broad",
    )
    left = document_extraction.PdfFormulaCandidate(
        candidate_id="detected-left",
        page=3,
        bbox=(0.10, 0.30, 0.20, 0.10),
        text="a = b",
        chunk_id="chunk-broad",
    )
    right = document_extraction.PdfFormulaCandidate(
        candidate_id="detected-right",
        page=3,
        bbox=(0.30, 0.30, 0.20, 0.10),
        text="a = b",
        chunk_id="chunk-broad",
    )

    merged = document_extraction.merge_pdf_formula_candidates(
        [broad_persisted],
        [left, right],
    )

    assert merged == [left, right]


def test_source_resolver_can_disable_legacy_metadata_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only callers resolve a recovered source without writing doc_store."""

    source_path = tmp_path / "paper.pdf"
    source_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    material = SimpleNamespace(title="paper.pdf", title_en="", metadata={})
    store = SimpleNamespace(get_material=lambda _material_id: material)
    repairs: list[tuple[str, str, str]] = []
    monkeypatch.setattr(search_upload._rr, "_load_doc_store", lambda _project_id: {"mat": {}})
    monkeypatch.setattr(search_upload._rr, "get_writing_resource_store", lambda: store)
    monkeypatch.setattr(search_upload, "_project_source_roots", lambda _project_id: [tmp_path])
    monkeypatch.setattr(
        search_upload,
        "_repair_material_source_reference",
        lambda project_id, material_id, relative: repairs.append(
            (project_id, material_id, relative)
        ),
    )

    resolved = search_upload._resolve_material_source_path(
        "project-a",
        "mat",
        repair_missing_reference=False,
    )
    assert resolved == source_path
    assert repairs == []

    assert search_upload._resolve_material_source_path("project-a", "mat") == source_path
    assert repairs == [("project-a", "mat", "paper.pdf")]


@pytest.mark.skipif(not _PYMUPDF_AVAILABLE, reason="PyMuPDF is required")
def test_formula_candidate_endpoint_is_material_scoped_bounded_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route returns the stable envelope without source-metadata writes."""

    import pymupdf

    pdf_path = tmp_path / "endpoint-formula.pdf"
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((200, 180), "E = mc^2", fontsize=13)
    document.save(str(pdf_path))
    document.close()
    [detected] = document_extraction.extract_pymupdf_formula_candidates(pdf_path)

    with TestClient(app) as client:
        project_response = client.post("/resources/project", json={"title": "Formula project"})
        assert project_response.status_code == 200
        project_id = project_response.json()["project_id"]
        material_response = client.post(
            "/resources/material",
            json={"project_id": project_id, "title": "endpoint-formula.pdf"},
        )
        assert material_response.status_code == 200
        material_id = material_response.json()["material_id"]

        chunks = [
            {
                "material_id": material_id,
                "chunk_id": "chunk-equation-1",
                "chunk_type": "formula",
                "page": 1,
                "bbox": list(detected.bbox),
                "bbox_unit": "normalized_ratio",
                "equation_latex": "E = mc^2",
            }
        ]
        monkeypatch.setattr(
            resources_router,
            "_load_chunk_store",
            lambda requested_project_id: (
                {material_id: chunks} if requested_project_id == project_id else {}
            ),
        )
        repair_flags: list[bool] = []

        def _resolve_source(
            requested_project_id: str,
            requested_material_id: str,
            *,
            repair_missing_reference: bool = True,
        ) -> Path | None:
            assert requested_project_id == project_id
            assert requested_material_id == material_id
            repair_flags.append(repair_missing_reference)
            return pdf_path

        monkeypatch.setattr(search_upload, "_resolve_material_source_path", _resolve_source)
        monkeypatch.setattr(
            resources_router,
            "_save_doc_store",
            lambda *_args, **_kwargs: pytest.fail("read-only endpoint attempted doc_store write"),
        )

        response = client.get(
            f"/resources/material/{material_id}/formula-candidates",
            params={"project_id": project_id, "limit": 200},
        )
        assert response.status_code == 200
        assert response.json() == {
            "project_id": project_id,
            "material_id": material_id,
            "candidates": [
                {
                    "candidate_id": "chunk-equation-1",
                    "page": 1,
                    "bbox": list(detected.bbox),
                    "bbox_unit": "normalized_ratio",
                    "chunk_id": "chunk-equation-1",
                    "text": "E = mc^2",
                }
            ],
        }
        assert repair_flags == [False]

        assert (
            client.get(
                f"/resources/material/{material_id}/formula-candidates",
                params={"project_id": project_id, "limit": 201},
            ).status_code
            == 422
        )

        other_project = client.post(
            "/resources/project",
            json={"title": "Other formula project"},
        ).json()["project_id"]
        cross_project = client.get(
            f"/resources/material/{material_id}/formula-candidates",
            params={"project_id": other_project},
        )
        assert cross_project.status_code == 404
