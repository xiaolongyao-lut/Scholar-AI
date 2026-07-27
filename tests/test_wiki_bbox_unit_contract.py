from __future__ import annotations

from literature_assistant.core.models.evidence import PdfAnchorFields
from literature_assistant.core.wiki.evidence_adapter import normalize_evidence
from literature_assistant.core.wiki.graph import _normalize_pdf_evidence_ref


def test_wiki_evidence_drops_unitless_bbox_precision() -> None:
    evidence = normalize_evidence(
        {
            "material_id": "material-unitless",
            "page": 2,
            "text": "Unitless evidence remains page-addressable.",
            "bbox": [0.1, 0.2, 0.3, 0.1],
        }
    )

    assert evidence.material_id == "material-unitless"
    assert evidence.page == 2
    assert evidence.bbox is None
    assert evidence.bbox_unit is None


def test_wiki_graph_drops_unitless_bbox_precision() -> None:
    evidence_ref = _normalize_pdf_evidence_ref(
        {
            "material_id": "material-unitless",
            "page": 3,
            "text": "Graph evidence remains page-addressable.",
            "bbox": [0.2, 0.3, 0.2, 0.1],
        }
    )

    assert evidence_ref == {
        "material_id": "material-unitless",
        "page": 3,
        "chunk_id": None,
        "text": "Graph evidence remains page-addressable.",
    }


def test_wiki_bbox_precision_requires_a_matching_explicit_unit() -> None:
    evidence = normalize_evidence(
        {
            "material_id": "material-explicit",
            "bbox": [0.1, 0.2, 0.3, 0.1],
            "bbox_unit": "normalized_ratio",
        }
    )
    graph_ref = _normalize_pdf_evidence_ref(
        {
            "material_id": "material-explicit",
            "bbox": [100.0, 200.0, 300.0, 100.0],
            "bbox_unit": "normalized_1000",
        }
    )

    assert evidence.bbox == [0.1, 0.2, 0.3, 0.1]
    assert evidence.bbox_unit == "normalized_ratio"
    assert graph_ref is not None
    assert graph_ref["bbox"] == [100.0, 200.0, 300.0, 100.0]
    assert graph_ref["bbox_unit"] == "normalized_1000"


def test_pdf_bbox_openapi_schema_requires_exactly_four_numbers() -> None:
    bbox_schema = PdfAnchorFields.model_json_schema()["properties"]["bbox"]
    array_schema = next(
        branch for branch in bbox_schema["anyOf"] if branch.get("type") == "array"
    )

    assert array_schema["minItems"] == 4
    assert array_schema["maxItems"] == 4
