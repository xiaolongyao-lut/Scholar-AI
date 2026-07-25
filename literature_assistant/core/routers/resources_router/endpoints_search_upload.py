# -*- coding: utf-8 -*-
"""Upload / search / document-serving endpoints split out of resources_router.__init__.

All references to module-level helpers go through ``_rr.X`` (absolute import
of the package) so that pytest ``monkeypatch.setattr(rr, "X", ...)`` keeps
affecting the live endpoint behaviour.
"""

import hashlib
import math
import re
import struct
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote
from typing import Any, Literal, cast

from fastapi import HTTPException, Query, Request, UploadFile, File, Form
from pydantic import BaseModel, ConfigDict, Field, field_validator

from models import (
    ChunkSearchRefMetadataPayload,
    ChunkSearchRefPayload,
    ChunkSearchRefsResponse,
    EvidenceLocatorCoveragePayload,
    FigureTableCandidatePayload,
    PdfBboxUnit,
    coerce_pdf_bbox,
    pdf_bbox_matches_unit,
)

import routers.resources_router as _rr
from routers.resources_router.path_guard import assert_bound_source_folder, assert_safe_source_folder
from routers.resources_router._chunk_store_internals import (
    _chunk_fts_index_path,
    _chunk_store_hash_version,
)
from chunk_fts_index import search_chunk_fts_index
from chunk_hashing import compute_chunk_store_version
from evidence_packer import _select_query_quote
from retrieval_gateway import retrieve_candidates
from text_utils import cjk_aware_tokenize


_FIGURE_TABLE_PREFIX_RE = re.compile(
    r"(?P<prefix>图|圖|表|figure|fig\.?|table)\s*"
    r"(?P<number>[A-Za-z]?\d+(?:[.\-–—]\d+)*[A-Za-z]?)",
    re.IGNORECASE,
)
_CAPTION_STOP_RE = re.compile(r"(?=(?:\s+(?:图|圖|表|figure|fig\.?|table)\s*[A-Za-z]?\d+))", re.IGNORECASE)
_MAX_FIGURE_TABLE_CANDIDATES = 96
_LOCATOR_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")
_LOCATOR_CACHE_MAX = 256
_LOCATOR_MIN_TEXT_CHARS = 24
_SEARCH_REF_FORBIDDEN_QUERY_PARAMS = frozenset({"ingest_mode", "include_content"})
_SEARCH_REF_SUMMARY_CHARS = 300
_MAX_UPLOAD_BATCH_FILES = 10000
_VISUAL_SEARCH_INTENT_RE = re.compile(
    r"外观|图片|图像|图表|表格|照片|表面|焊缝|形貌|截面|宏观|显微|"
    r"表\s*[A-Za-z]?\d+|"
    r"figure|fig\.?|image|picture|photo|appearance|surface|morpholog|"
    r"table\s*[A-Za-z]?\d+|tab\.|weld\s*seam|cross[-\s]?section|macrograph|micrograph",
    re.IGNORECASE,
)
_VISUAL_SEARCH_POSITIVE_TERMS = (
    "外观",
    "图片",
    "图像",
    "图表",
    "表格",
    "照片",
    "表面",
    "焊缝",
    "形貌",
    "截面",
    "宏观",
    "显微",
    "figure",
    "fig.",
    "table",
    "tab.",
    "image",
    "picture",
    "photo",
    "appearance",
    "surface",
    "morphology",
    "morphologies",
    "weld seam",
    "cross section",
    "cross-section",
    "macrograph",
    "micrograph",
)
_VISUAL_SEARCH_WELD_TERMS = ("焊", "weld", "welding", "laser")
_VISUAL_SEARCH_SURFACE_QUERY_RE = re.compile(
    r"外观|上表面|表面|成形|焊道|焊缝形貌|焊缝表面|"
    r"appearance|upper\s+surface|top\s+surface|top\s+view|"
    r"surface\s+(?:morpholog|appearance)|weld\s+bead|weld\s+formation",
    re.IGNORECASE,
)
_VISUAL_SEARCH_CROSS_SECTION_QUERY_RE = re.compile(
    r"截面|横截面|纵截面|断面|剖面|cross[-\s]?section|sectional|longitudinal\s+section",
    re.IGNORECASE,
)
_VISUAL_SEARCH_SURFACE_TERMS = (
    "外观",
    "上表面",
    "表面成形",
    "表面形貌",
    "焊缝表面",
    "焊缝成形",
    "焊道",
    "成形",
    "appearance",
    "upper surface",
    "top surface",
    "top view",
    "surface appearance",
    "surface morphology",
    "surface morphologies",
    "weld bead",
    "weld formation",
    "weld morphologies",
)
_VISUAL_SEARCH_CROSS_SECTION_TERMS = (
    "横截面",
    "纵截面",
    "截面",
    "断面",
    "剖面",
    "cross-section",
    "cross section",
    "cross sections",
    "cross- sections",
    "transverse cross",
    "longitudinal section",
    "sectional",
)
_VISUAL_SEARCH_LOW_PRIORITY_TERMS = (
    "schematic",
    "diagram",
    "setup",
    "hardness",
    "strength",
    "distribution",
    "curve",
    "示意",
    "装置",
    "硬度",
    "强度",
    "分布",
    "曲线",
    "能量分布",
    "应力",
    "模拟",
    "准则",
    "tensile",
    "fracture",
    "stress",
    "simulation",
    "microstructure",
    "partial melting",
    "pmz",
    "grain",
    "组织",
    "显微组织",
)
_CROPPED_IMAGE_SUFFIX = ".png"
_FIGURE_ASSET_FILE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_CHUNK_ASSET_KEY_SOURCES: dict[str, str] = {
    "asset_path": "chunk_asset",
    "image_path": "chunk_image",
    "raw_image_path": "chunk_raw_image",
    "page_crop_path": "chunk_page_crop",
    "figure_asset_path": "chunk_figure_asset",
}
_CHUNK_ASSET_LIST_KEY_SOURCES: dict[str, str] = {
    "image_paths": "chunk_image_paths",
    "figure_image_paths": "chunk_figure_image_paths",
}
_CHUNK_NESTED_ASSET_KEYS = (
    "primary_single_figure",
    "primary_figure",
    "figure",
    "table",
)
_CHUNK_DEEP_IMAGE_KEY_SOURCES: dict[str, str] = {
    "raw_embedded_image": "chunk_raw_embedded_image",
    "page_crop_image": "chunk_page_crop_image",
}
_pdf_locator_cache: dict[str, dict[str, Any] | None] = {}


class FormulaCandidatePayload(BaseModel):
    """One atomic whole-formula target for the PDF reader."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=240)
    page: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    bbox_unit: Literal["normalized_ratio"] = "normalized_ratio"
    chunk_id: str | None = Field(default=None, min_length=1, max_length=240)
    text: str | None = Field(default=None, max_length=512)

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, value: list[float]) -> list[float]:
        """Keep public geometry finite and inside normalized page bounds."""

        if len(value) != 4:
            raise ValueError("bbox must contain x, y, width, height")
        coordinates = [float(item) for item in value]
        if any(not math.isfinite(item) for item in coordinates):
            raise ValueError("bbox values must be finite")
        x, y, width, height = coordinates
        if x < 0.0 or y < 0.0 or width <= 0.0 or height <= 0.0:
            raise ValueError("bbox must have a non-negative origin and positive size")
        if x + width > 1.000001 or y + height > 1.000001:
            raise ValueError("bbox must stay inside normalized page bounds")
        return coordinates


class FormulaCandidatesResponse(BaseModel):
    """Bounded material-scoped formula candidate collection."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=200)
    material_id: str = Field(min_length=1, max_length=200)
    candidates: list[FormulaCandidatePayload] = Field(default_factory=list, max_length=200)


# =========================================================================
# Upload Endpoints
# =========================================================================

@_rr.router.post("/upload")
async def upload_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a document file, extract text content, and store as a material."""
    store = _rr._ensure_upload_project(project_id)
    try:
        return await _rr._ingest_uploaded_document(project_id, file, store=store)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@_rr.router.post("/upload/batch")
async def upload_documents_batch(
    project_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """Upload multiple knowledge-base documents in one request and summarize outcomes."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > _MAX_UPLOAD_BATCH_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"每批最多导入 {_MAX_UPLOAD_BATCH_FILES} 个文件",
        )

    store = _rr._ensure_upload_project(project_id)
    batch_id, submitted_at = _rr._new_upload_batch_identity()
    results: list[dict[str, Any]] = []
    total_chunks = 0
    accepted_files = 0
    completed_files = 0
    successful_files = 0
    failed_files = 0
    duplicate_files = 0
    queued_files = 0

    ordered_files = sorted(
        files,
        key=lambda item: (
            _rr._build_scan_dedupe_key(_rr._safe_upload_filename(item.filename or "unnamed")),
            _rr._is_translated_scan_derivative(item.filename or ""),
            len(_rr._safe_upload_filename(item.filename or "unnamed")),
            _rr._safe_upload_filename(item.filename or "unnamed").lower(),
        ),
    )
    skipped_files = 0

    batch_total = len(ordered_files)
    for batch_index, upload in enumerate(ordered_files, start=1):
        filename = upload.filename or "unnamed"
        batch_context = _rr._UploadBatchContext(
            batch_id=batch_id,
            submitted_at=submitted_at,
            batch_index=batch_index,
            batch_total=batch_total,
        )
        try:
            result = await _rr._ingest_uploaded_document(
                project_id,
                upload,
                store=store,
                batch_context=batch_context,
            )
            result = {
                **result,
                **batch_context.to_result_fields(),
            }
            if result.get("status") == "duplicate":
                duplicate_files += 1
            elif result.get("status") == "skipped":
                skipped_files += 1
            elif result.get("status") == "queued":
                accepted_files += 1
                queued_files += 1
            elif result.get("status") in {"ok", "completed"}:
                accepted_files += 1
                completed_files += 1
                total_chunks += int(result.get("chunks") or 0)
                successful_files += 1
            else:
                failed_files += 1
            results.append(result)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            failed_files += 1
            results.append({
                "title": filename,
                "status": "error",
                "error": str(exc),
                **batch_context.to_result_fields(),
            })

    return {
        "project_id": project_id,
        "batch_id": batch_id,
        "submitted_at": submitted_at,
        "total_files": len(files),
        "accepted_files": accepted_files,
        "completed_files": completed_files,
        "successful_files": successful_files,
        "duplicate_files": duplicate_files,
        "skipped_files": skipped_files,
        "queued_files": queued_files,
        "failed_files": failed_files,
        "total_chunks": total_chunks,
        "results": results,
    }


# =========================================================================
# Documents / Chunks Read Endpoints
# =========================================================================

@_rr.router.get("/documents")
async def get_project_documents(project_id: str = Query(...)) -> list[dict[str, str]]:
    """Get all document contents for a project (for RAG context)."""
    doc_store = _rr._load_doc_store(project_id)
    return [
        {"material_id": mid, "title": doc["title"], "content": doc["content"]}
        for mid, doc in doc_store.items()
    ]


@_rr.router.get("/chunks")
async def get_project_chunks(
    project_id: str = Query(...),
    material_id: str | None = Query(None, description="Filter by material"),
) -> dict[str, Any]:
    """Get chunked document content for a project (for smarter RAG context).

    Returns chunks instead of full documents, allowing the frontend to
    send only relevant chunks to the LLM.
    """
    chunk_store = _rr._ensure_project_chunks(project_id, material_id=material_id)
    all_chunks: list[dict[str, Any]] = []
    for mid, chunks in chunk_store.items():
        if material_id and mid != material_id:
            continue
        all_chunks.extend(chunks)
    return {
        "project_id": project_id,
        "total_chunks": len(all_chunks),
        "chunks": all_chunks,
    }


def _normalize_candidate_text(value: Any, *, max_chars: int = 220) -> str:
    """Return compact single-line candidate text for stable UI display."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}…"


def _coerce_positive_int(value: Any) -> int | None:
    """Coerce optional one-based numeric metadata without accepting zeros."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _coerce_non_negative_int(value: Any) -> int | None:
    """Coerce optional zero-based chunk indexes."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed >= 0 else None
    return None


def _coerce_optional_positive_page(value: Any) -> int | None:
    """Coerce optional one-based page metadata for public search refs."""

    return _coerce_positive_int(value)


def _normalize_search_ref_text(value: Any, *, max_chars: int = _SEARCH_REF_SUMMARY_CHARS) -> str:
    """Return compact text for a search ref summary or metadata string."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}…"


def _chunk_search_ref_summary(chunk: dict[str, Any]) -> str:
    """Return a bounded summary without exposing full chunk dictionaries."""

    for key in ("summary", "caption", "title", "content"):
        summary = _normalize_search_ref_text(chunk.get(key))
        if summary:
            return summary
    return "Matched chunk"


def _bounded_exact_quote(value: Any, *, max_chars: int = 320) -> str | None:
    """Return bounded exact text without adding synthetic characters."""

    text = str(value or "").strip()
    if not text or max_chars <= 0:
        return None
    return text[:max_chars].rstrip() or None


def _dedupe_bounded_strings(values: Any, *, max_items: int = 16, max_chars: int = 120) -> list[str]:
    """Return stable non-empty strings for low-risk provenance fields."""

    raw_values = values if isinstance(values, (list, tuple, set)) else [values]
    output: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        text = _normalize_search_ref_text(raw, max_chars=max_chars)
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
        if len(output) >= max_items:
            break
    return output


def _chunk_source_labels(chunk: dict[str, Any]) -> list[str]:
    """Return bounded retrieval/source labels already carried by a chunk."""

    labels = _dedupe_bounded_strings(chunk.get("source_labels"), max_items=16, max_chars=80)
    if labels:
        return labels
    source_label = _normalize_search_ref_text(chunk.get("source_label") or chunk.get("source_hint"), max_chars=80)
    return [source_label] if source_label else []


def _chunk_figure_table_candidate(chunk: dict[str, Any]) -> str | None:
    """Return a stable figure/table candidate id without exposing captions."""

    for key in (
        "figure_candidate",
        "figure_table_candidate",
        "figure_table_candidate_id",
        "candidate_id",
        "figure_id",
        "table_id",
    ):
        value = _normalize_search_ref_text(chunk.get(key), max_chars=260)
        if value:
            return value
    for key in ("linked_figure_ids", "linked_table_ids", "figure_ids", "table_ids"):
        values = _dedupe_bounded_strings(chunk.get(key), max_items=1, max_chars=260)
        if values:
            return values[0]
    return None


def _chunk_image_paths(
    chunk: dict[str, Any],
    *,
    max_items: int | None = 8,
) -> list[str]:
    """Return project-relative image assets recorded on a chunk.

    Args:
        chunk: Persisted chunk mapping from the project chunk store.
        max_items: Optional upper bound for returned image references. ``None``
            preserves every unique path carried by the finite chunk record.

    Returns:
        Deduplicated image path strings. Only existing metadata fields are read;
        this helper never renders PDF pages or creates replacement screenshots.
    """

    if not isinstance(chunk, dict):
        raise TypeError("chunk must be a dictionary")
    if max_items is not None and (
        not isinstance(max_items, int) or max_items < 1 or max_items > 32
    ):
        raise ValueError("max_items must be between 1 and 32")
    bbox_anchor = _coerce_declared_bbox_anchor(
        chunk.get("bbox"),
        chunk.get("bbox_unit"),
    )
    if (
        bbox_anchor is not None
        and bbox_anchor[1] == PdfBboxUnit.NORMALIZED_RATIO
        and _bbox_is_probable_page_screenshot(bbox_anchor[0])
    ):
        return []

    values: list[Any] = []
    for key in ("image_paths", "figure_image_paths", "table_image_paths"):
        raw = chunk.get(key)
        if isinstance(raw, list):
            values.extend(raw)
        elif raw:
            values.append(raw)
    reference = _candidate_asset_reference(chunk)
    if reference is not None:
        values.append(reference[0])
    effective_max_items = max_items if max_items is not None else max(len(values), 1)
    return _dedupe_bounded_strings(
        values,
        max_items=effective_max_items,
        max_chars=260,
    )


def _chunk_figure_candidate_detail(
    chunk: dict[str, Any],
    *,
    material_id: str,
    chunk_id: str,
) -> dict[str, Any] | None:
    """Return a bounded figure/table candidate summary for one chunk.

    Args:
        chunk: Persisted chunk mapping from the project chunk store.
        material_id: Material that owns the chunk.
        chunk_id: Stable chunk identifier used by resource readers.

    Returns:
        Metadata suitable for UI/MCP evidence inspection, or ``None`` when the
        chunk has neither a candidate id nor a recorded image asset.
    """

    if not isinstance(chunk, dict):
        raise TypeError("chunk must be a dictionary")
    normalized_material_id = _normalize_search_ref_text(material_id, max_chars=200)
    normalized_chunk_id = _normalize_search_ref_text(chunk_id, max_chars=200)
    if not normalized_material_id or not normalized_chunk_id:
        raise ValueError("material_id and chunk_id must be non-empty")

    candidate_id = _chunk_figure_table_candidate(chunk)
    image_paths = _chunk_image_paths(chunk, max_items=1)
    asset_path = image_paths[0] if image_paths else None
    if not candidate_id and not asset_path:
        return None

    raw_content = str(chunk.get("raw_content") or "").strip()
    content = raw_content or str(chunk.get("content") or "").strip()
    match = _FIGURE_TABLE_PREFIX_RE.search(content)
    if match:
        kind = _candidate_kind(match.group("prefix"))
        label = _candidate_label(kind, match.group("number"))
        caption = _candidate_caption(content, match)
    elif asset_path:
        kind, label = _candidate_label_from_asset_name(asset_path)
        caption = _candidate_caption_from_asset(label)
    else:
        kind = "figure"
        label = "图"
        caption = "来自项目切块的图表候选"

    if not candidate_id:
        candidate_id = _candidate_id(
            project_id=str(chunk.get("project_id") or "project"),
            kind=kind,
            material_id=normalized_material_id,
            chunk_id=normalized_chunk_id,
            label=label,
        )

    bbox_anchor = _coerce_declared_bbox_anchor(chunk.get("bbox"), chunk.get("bbox_unit"))
    bbox = bbox_anchor[0] if bbox_anchor is not None else None
    bbox_unit = bbox_anchor[1].value if bbox_anchor is not None else None
    source = _normalize_search_ref_text(chunk.get("figure_candidate_source"), max_chars=120)
    if not source:
        reference = _candidate_asset_reference(chunk)
        source = reference[1] if reference is not None else "chunk_metadata"
    detail: dict[str, Any] = {
        "id": candidate_id,
        "kind": kind,
        "label": _normalize_candidate_text(label, max_chars=80) or label,
        "caption": _normalize_candidate_text(caption, max_chars=220) or caption[:220],
        "material_id": normalized_material_id,
        "material_title": _normalize_candidate_text(
            chunk.get("title") or chunk.get("material_title") or normalized_material_id,
            max_chars=120,
        )
        or normalized_material_id,
        "page": _coerce_optional_positive_page(chunk.get("page")),
        "chunk_id": normalized_chunk_id,
        "chunk_index": _coerce_non_negative_int(chunk.get("chunk_index")),
        "bbox": bbox,
        "bbox_unit": bbox_unit,
        "asset_path": asset_path,
        "source": source,
    }
    return {key: value for key, value in detail.items() if value is not None}


def _chunk_search_ref_locator(chunk: dict[str, Any], *, material_id: str, chunk_id: str) -> dict[str, Any] | None:
    """Return a compact locator copied only from whitelisted scalar fields."""

    locator = chunk.get("locator")
    if isinstance(locator, dict):
        page = _coerce_optional_positive_page(locator.get("page")) or _coerce_optional_positive_page(chunk.get("page"))
        chunk_index = _coerce_non_negative_int(locator.get("chunk_index"))
        if chunk_index is None:
            chunk_index = _coerce_non_negative_int(chunk.get("chunk_index"))
        payload = _layout_locator_payload(
            material_id=material_id,
            chunk_id=chunk_id,
            page=page,
            chunk_index=chunk_index,
            bbox=locator.get("bbox"),
            bbox_unit=locator.get("bbox_unit"),
        )
        if payload is not None:
            return payload

    page = _coerce_optional_positive_page(chunk.get("page"))
    chunk_index = _coerce_non_negative_int(chunk.get("chunk_index"))
    return _layout_locator_payload(
        material_id=material_id,
        chunk_id=chunk_id,
        page=page,
        chunk_index=chunk_index,
        bbox=chunk.get("bbox"),
        bbox_unit=chunk.get("bbox_unit"),
    )


def _chunk_locator_quality(chunk: dict[str, Any]) -> dict[str, Any]:
    """Return bounded locator-quality diagnostics without exposing coordinates."""

    if not isinstance(chunk, dict):
        raise TypeError("chunk must be a dictionary")
    raw_bbox: Any = None
    raw_unit: Any = None
    locator = chunk.get("locator")
    if isinstance(locator, dict) and "bbox" in locator:
        raw_bbox = locator.get("bbox")
        raw_unit = locator.get("bbox_unit")
    elif "bbox" in chunk:
        raw_bbox = chunk.get("bbox")
        raw_unit = chunk.get("bbox_unit")
    reason = _invalid_bbox_reason(raw_bbox, raw_unit)
    if reason == "":
        return {}
    return {"invalid_bbox": True, "invalid_bbox_reason": reason}


def _invalid_bbox_reason(bbox: Any, bbox_unit: Any) -> str:
    """Classify bbox metadata that cannot be used for source recovery."""

    if bbox is None:
        return ""
    normalized_bbox = coerce_pdf_bbox(bbox)
    if normalized_bbox is None:
        return "malformed_bbox"
    raw_unit = _normalize_search_ref_text(bbox_unit, max_chars=80)
    if not raw_unit:
        return "missing_bbox_unit"
    try:
        normalized_unit = PdfBboxUnit(raw_unit)
    except ValueError:
        return "unsupported_bbox_unit"
    if not pdf_bbox_matches_unit(normalized_bbox, normalized_unit):
        return "bbox_outside_declared_unit"
    return ""


def _coerce_declared_bbox_anchor(
    bbox: Any,
    bbox_unit: Any,
) -> tuple[list[float], PdfBboxUnit] | None:
    """Return a bbox only when its coordinate unit is explicit and valid."""

    normalized_bbox = coerce_pdf_bbox(bbox)
    if normalized_bbox is None:
        return None
    if isinstance(bbox_unit, PdfBboxUnit):
        normalized_unit = bbox_unit
    else:
        raw_unit = _normalize_search_ref_text(bbox_unit, max_chars=80)
        if not raw_unit:
            return None
        try:
            normalized_unit = PdfBboxUnit(raw_unit)
        except ValueError:
            return None
    if not pdf_bbox_matches_unit(normalized_bbox, normalized_unit):
        return None
    return normalized_bbox, normalized_unit


def _layout_locator_payload(
    *,
    material_id: str,
    chunk_id: str,
    page: int | None,
    chunk_index: int | None,
    bbox: Any,
    bbox_unit: Any,
) -> dict[str, Any] | None:
    """Return a normalized layout locator for source recovery diagnostics."""

    normalized_material_id = _normalize_search_ref_text(material_id, max_chars=200)
    normalized_chunk_id = _normalize_search_ref_text(chunk_id, max_chars=200)
    if not normalized_material_id or not normalized_chunk_id:
        return None
    anchor = _coerce_declared_bbox_anchor(bbox, bbox_unit)
    normalized_bbox = anchor[0] if anchor is not None and page is not None else None
    normalized_unit = anchor[1] if anchor is not None and page is not None else None
    if page is None and chunk_index is None and normalized_bbox is None:
        return None
    payload: dict[str, Any] = {
        "material_id": normalized_material_id,
        "chunk_id": normalized_chunk_id,
    }
    if page is not None:
        payload["page"] = page
    if chunk_index is not None:
        payload["chunk_index"] = chunk_index
    if normalized_bbox is not None and normalized_unit is not None:
        payload["bbox"] = normalized_bbox
        payload["bbox_unit"] = normalized_unit.value
    return payload


def build_locator_coverage(refs: list[Any]) -> EvidenceLocatorCoveragePayload:
    """Summarize whether returned refs can be located back in source layout."""

    if not isinstance(refs, list):
        raise ValueError("refs must be a list")
    total_refs = len(refs)
    project_ref_count = 0
    non_project_ref_count = 0
    material_locator_count = 0
    page_locator_count = 0
    bbox_locator_count = 0
    invalid_bbox_count = 0
    bbox_unit_counts: dict[str, int] = {}
    source_label_count = 0
    figure_table_locator_count = 0
    sample_figure_table_ids: list[str] = []
    invalid_bbox_ref_ids: list[str] = []
    missing_ref_ids: list[str] = []
    for ref in refs:
        source_type = _ref_source_type(ref)
        if source_type and source_type != "project":
            non_project_ref_count += 1
            continue
        project_ref_count += 1
        if _ref_source_labels(ref):
            source_label_count += 1
        figure_table_id = _ref_figure_table_id(ref)
        if figure_table_id:
            figure_table_locator_count += 1
            if len(sample_figure_table_ids) < 8 and figure_table_id not in sample_figure_table_ids:
                sample_figure_table_ids.append(figure_table_id)
        locator = _ref_locator(ref)
        ref_id = _normalize_search_ref_text(_ref_attr(ref, "ref_id"), max_chars=200) or _normalize_search_ref_text(
            _ref_attr(ref, "chunk_id"), max_chars=200
        )
        if _ref_has_invalid_bbox(ref):
            invalid_bbox_count += 1
            if ref_id and len(invalid_bbox_ref_ids) < 8:
                invalid_bbox_ref_ids.append(ref_id)
        if not _locator_has_identity(locator):
            if ref_id and len(missing_ref_ids) < 8:
                missing_ref_ids.append(ref_id)
            continue
        material_locator_count += 1
        if _coerce_optional_positive_page(locator.get("page")) is not None:
            page_locator_count += 1
            anchor = _coerce_declared_bbox_anchor(
                locator.get("bbox"),
                locator.get("bbox_unit"),
            )
            if anchor is not None:
                _bbox, unit = anchor
                bbox_locator_count += 1
                bbox_unit_counts[unit.value] = bbox_unit_counts.get(unit.value, 0) + 1

    missing_locator_count = max(project_ref_count - material_locator_count, 0)
    page_ratio = _coverage_ratio(page_locator_count, project_ref_count)
    bbox_ratio = _coverage_ratio(bbox_locator_count, project_ref_count)
    source_label_ratio = _coverage_ratio(source_label_count, project_ref_count)
    coverage_state = _locator_coverage_state(
        total_refs=total_refs,
        project_ref_count=project_ref_count,
        material_locator_count=material_locator_count,
        page_locator_count=page_locator_count,
        bbox_locator_count=bbox_locator_count,
    )
    risk_level = _locator_coverage_risk(coverage_state)
    return EvidenceLocatorCoveragePayload(
        total_refs=total_refs,
        project_ref_count=project_ref_count,
        non_project_ref_count=non_project_ref_count,
        material_locator_count=material_locator_count,
        page_locator_count=page_locator_count,
        bbox_locator_count=bbox_locator_count,
        invalid_bbox_count=invalid_bbox_count,
        missing_locator_count=missing_locator_count,
        page_coverage_ratio=page_ratio,
        bbox_coverage_ratio=bbox_ratio,
        bbox_unit_counts=bbox_unit_counts,
        source_label_count=source_label_count,
        source_label_coverage_ratio=source_label_ratio,
        figure_table_locator_count=figure_table_locator_count,
        coverage_state=coverage_state,
        risk_level=risk_level,
        sample_figure_table_ids=sample_figure_table_ids,
        sample_invalid_bbox_ref_ids=invalid_bbox_ref_ids,
        sample_missing_ref_ids=missing_ref_ids,
        notes=_locator_coverage_notes(
            coverage_state=coverage_state,
            project_ref_count=project_ref_count,
            non_project_ref_count=non_project_ref_count,
            source_label_count=source_label_count,
            figure_table_locator_count=figure_table_locator_count,
            invalid_bbox_count=invalid_bbox_count,
        ),
    )


def _ref_attr(ref: Any, field_name: str) -> Any:
    """Read a field from either a Pydantic model or a plain dict."""

    if isinstance(ref, dict):
        return ref.get(field_name)
    return getattr(ref, field_name, None)


def _ref_source_type(ref: Any) -> str:
    """Return the bounded source type for a ref."""

    return _normalize_search_ref_text(_ref_attr(ref, "source_type"), max_chars=80)


def _ref_metadata_attr(ref: Any, field_name: str) -> Any:
    """Read a whitelisted metadata field from dict or model refs."""

    metadata = _ref_attr(ref, "metadata")
    if isinstance(metadata, dict):
        return metadata.get(field_name)
    return getattr(metadata, field_name, None)


def _ref_source_labels(ref: Any) -> list[str]:
    """Return source labels from evidence refs or search-ref metadata."""

    labels = _dedupe_bounded_strings(_ref_attr(ref, "source_labels"), max_items=16, max_chars=80)
    if labels:
        return labels
    return _dedupe_bounded_strings(_ref_metadata_attr(ref, "source_labels"), max_items=16, max_chars=80)


def _ref_figure_table_id(ref: Any) -> str:
    """Return the first linked figure/table candidate id on a ref."""

    for raw in (
        _ref_attr(ref, "figure_candidate"),
        _ref_attr(ref, "figure_table_candidate"),
        _ref_metadata_attr(ref, "figure_candidate"),
        _ref_metadata_attr(ref, "figure_table_candidate"),
    ):
        value = _normalize_search_ref_text(raw, max_chars=260)
        if value:
            return value
    return ""


def _ref_locator(ref: Any) -> dict[str, Any]:
    """Return a locator dict from supported search/evidence ref shapes."""

    locator = _ref_attr(ref, "locator")
    if isinstance(locator, dict):
        return locator
    metadata = _ref_attr(ref, "metadata")
    if isinstance(metadata, dict):
        locator = metadata.get("locator")
        return locator if isinstance(locator, dict) else {}
    locator = getattr(metadata, "locator", None)
    return locator if isinstance(locator, dict) else {}


def _ref_locator_quality(ref: Any) -> dict[str, Any]:
    """Return private locator diagnostics attached by local search helpers."""

    quality = getattr(ref, "_locator_quality", None)
    if isinstance(quality, dict):
        return quality
    if isinstance(ref, dict):
        quality = ref.get("locator_quality")
        return quality if isinstance(quality, dict) else {}
    return {}


def _ref_has_invalid_bbox(ref: Any) -> bool:
    """Return true when a ref had bbox metadata that failed validation."""

    return bool(_ref_locator_quality(ref).get("invalid_bbox"))


def _locator_has_identity(locator: dict[str, Any]) -> bool:
    """Return true when a locator can at least identify material and chunk."""

    return bool(
        _normalize_search_ref_text(locator.get("material_id"), max_chars=200)
        and _normalize_search_ref_text(locator.get("chunk_id"), max_chars=200)
    )


def _coverage_ratio(count: int, total: int) -> float:
    """Return a stable four-decimal ratio for API diagnostics."""

    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _locator_coverage_state(
    *,
    total_refs: int,
    project_ref_count: int,
    material_locator_count: int,
    page_locator_count: int,
    bbox_locator_count: int,
) -> Literal[
    "no_refs",
    "missing",
    "material_only",
    "page_located",
    "layout_partial",
    "layout_complete",
]:
    """Classify locator coverage for workflow-passport gate projection."""

    if total_refs == 0 or project_ref_count == 0:
        return "no_refs"
    if material_locator_count == 0:
        return "missing"
    if page_locator_count == 0:
        return "material_only"
    if bbox_locator_count == 0:
        return "page_located"
    if bbox_locator_count < project_ref_count:
        return "layout_partial"
    return "layout_complete"


def _locator_coverage_risk(coverage_state: str) -> str:
    """Map locator state to an integrity-gate-friendly risk level."""

    if coverage_state in {"missing", "material_only"}:
        return "block"
    if coverage_state in {"page_located", "layout_partial"}:
        return "warn"
    return "none"


def _locator_coverage_notes(
    *,
    coverage_state: str,
    project_ref_count: int,
    non_project_ref_count: int,
    source_label_count: int,
    figure_table_locator_count: int,
    invalid_bbox_count: int,
) -> list[str]:
    """Return bounded hints without leaking chunk text or local paths."""

    notes: list[str] = []
    if non_project_ref_count:
        notes.append("Non-project refs are bounded resources and are excluded from PDF locator coverage ratios.")
    if project_ref_count == 0:
        notes.append("No project chunk refs were returned for locator coverage.")
    elif coverage_state == "layout_complete":
        notes.append("Every project ref has material, page, and bbox locators.")
    elif coverage_state == "layout_partial":
        notes.append("Some project refs have bbox locators; remaining refs need layout extraction or review.")
    elif coverage_state == "page_located":
        notes.append("Project refs can jump to source pages but not exact layout boxes.")
    elif coverage_state == "material_only":
        notes.append("Project refs identify source chunks but cannot jump to a source page yet.")
    else:
        notes.append("Project refs are missing source locators; run or repair material processing before evidence reuse.")
    if project_ref_count and source_label_count < project_ref_count:
        notes.append("Some project refs lack source labels, so retrieval provenance is only partially explainable.")
    if invalid_bbox_count:
        notes.append("Some project refs carried invalid bbox metadata; page jumps remain available but exact layout boxes need repair.")
    if figure_table_locator_count:
        notes.append("Some project refs are linked to figure/table candidates for layout-aware review.")
    return notes[:8]


def _chunk_search_ref_metadata(
    chunk: dict[str, Any],
    *,
    material_id: str,
    chunk_id: str,
    project_id: str | None = None,
    chunk_store: dict[str, list[dict[str, Any]]] | None = None,
    query: str | None = None,
) -> ChunkSearchRefMetadataPayload:
    """Build the plan-approved metadata whitelist for one chunk ref."""

    title = _normalize_search_ref_text(
        chunk.get("title") or chunk.get("material_title") or material_id,
        max_chars=300,
    )
    chunk_type = _normalize_search_ref_text(chunk.get("chunk_type"), max_chars=120) or None
    source_relative_path = _normalize_search_ref_text(chunk.get("source_relative_path"), max_chars=500) or None
    locator = _chunk_search_ref_locator(chunk, material_id=material_id, chunk_id=chunk_id)
    if (
        isinstance(locator, dict)
        and isinstance(chunk_store, dict)
        and _normalize_search_ref_text(project_id, max_chars=200)
        and (
            _coerce_optional_positive_page(locator.get("page")) is None
            or _coerce_declared_bbox_anchor(
                locator.get("bbox"),
                locator.get("bbox_unit"),
            )
            is None
        )
    ):
        locator = enrich_chunk_locator_with_pdf(str(project_id), chunk_store, locator)
    anchor_kind = _chunk_anchor_kind(chunk)
    return ChunkSearchRefMetadataPayload(
        material_id=material_id,
        title=title or None,
        page=_coerce_optional_positive_page(chunk.get("page")),
        chunk_type=chunk_type,
        source_relative_path=source_relative_path,
        locator=locator,
        source_labels=_chunk_source_labels(chunk),
        figure_candidate=_chunk_figure_table_candidate(chunk),
        figure_candidate_detail=_chunk_figure_candidate_detail(chunk, material_id=material_id, chunk_id=chunk_id),
        image_paths=_chunk_image_paths(chunk),
        quote=_chunk_search_ref_quote(
            chunk,
            anchor_kind=anchor_kind,
            query=query,
        ),
        anchor_kind=anchor_kind,
        content_hash=_bounded_chunk_hash(chunk.get("content_hash")),
        locator_hash=_bounded_chunk_hash(chunk.get("locator_hash")),
        chunk_hash=_bounded_chunk_hash(chunk.get("chunk_hash")),
        embedding_input_hash=_bounded_chunk_hash(chunk.get("embedding_input_hash")),
        hash_version=_normalize_search_ref_text(chunk.get("hash_version"), max_chars=128) or None,
    )


def _chunk_anchor_kind(chunk: Mapping[str, Any]) -> Literal["text", "visual"] | None:
    """Return explicit or strongly implied anchor semantics for one chunk."""

    explicit = _normalize_search_ref_text(chunk.get("anchor_kind"), max_chars=16).lower()
    if explicit in {"text", "visual"}:
        return cast(Literal["text", "visual"], explicit)
    chunk_type = _normalize_search_ref_text(chunk.get("chunk_type"), max_chars=80).lower()
    if chunk_type in {"figure", "figure_caption", "table", "table_caption", "formula", "equation", "image"}:
        return "visual"
    if chunk_type in {"body", "narrative", "text", "paragraph", "section"}:
        return "text"
    return None


def _chunk_search_ref_quote(
    chunk: Mapping[str, Any],
    *,
    anchor_kind: Literal["text", "visual"] | None,
    query: str | None,
) -> str | None:
    """Return a bounded exact selector only when the chunk is text evidence."""

    if anchor_kind != "text":
        return None
    explicit_quote = _bounded_exact_quote(chunk.get("quote"))
    if explicit_quote is not None:
        return explicit_quote
    source_text = ""
    for candidate in (
        chunk.get("raw_content"),
        _strip_chunk_locator_prefix(chunk.get("content")),
        chunk.get("text"),
    ):
        source_text = str(candidate or "").strip()
        if source_text:
            break
    if not source_text:
        return None
    query_tokens = {
        token
        for token in cjk_aware_tokenize(str(query or "").casefold())
        if token
    }
    if query_tokens:
        selected = _select_query_quote(source_text, query_tokens)
        return _bounded_exact_quote(selected) if selected else None
    return _bounded_exact_quote(source_text)


def _bounded_chunk_hash(value: Any) -> str | None:
    """Return a stored SHA-256 identity without recomputing response text."""

    normalized = _normalize_search_ref_text(value, max_chars=71).lower()
    if re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", normalized):
        return normalized
    return None


def _chunk_search_read_endpoint(*, project_id: str, chunk_id: str) -> str:
    """Return the bounded agent bridge reader URL for a chunk ref."""

    return (
        f"/api/agent-bridge/resource/chunk:{quote(chunk_id, safe='')}"
        f"?project_id={quote(project_id, safe='')}"
    )


def _chunk_to_search_ref(
    project_id: str,
    score: float,
    chunk: dict[str, Any],
    *,
    chunk_store: dict[str, list[dict[str, Any]]] | None = None,
    query: str | None = None,
) -> ChunkSearchRefPayload | None:
    """Project one scored chunk into the low-token MCP search-ref contract."""

    if not isinstance(chunk, dict):
        return None
    material_id = _normalize_search_ref_text(chunk.get("material_id"), max_chars=200)
    if not material_id:
        material_id = _normalize_search_ref_text(chunk.get("source_material_id"), max_chars=200)
    if not material_id:
        material_id = "unknown_material"
    chunk_id = _normalize_search_ref_text(chunk.get("chunk_id"), max_chars=200)
    if not chunk_id:
        chunk_index = _coerce_non_negative_int(chunk.get("chunk_index"))
        chunk_id = f"{material_id}_chunk_{chunk_index if chunk_index is not None else 'unknown'}"
    if not chunk_id:
        return None
    rounded_score = round(float(score), 2)
    ref = ChunkSearchRefPayload(
        chunk_id=chunk_id,
        ref_id=f"chunk:{chunk_id}",
        summary=_chunk_search_ref_summary(chunk),
        lexical_score=rounded_score,
        rerank_score=None,
        metadata=_chunk_search_ref_metadata(
            chunk,
            material_id=material_id,
            chunk_id=chunk_id,
            project_id=project_id,
            chunk_store=chunk_store,
            query=query,
        ),
        read_endpoint=_chunk_search_read_endpoint(project_id=project_id, chunk_id=chunk_id),
    )
    ref._locator_quality = _chunk_locator_quality(chunk)
    return ref


def _flatten_chunk_store_for_search_refs(chunk_store: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Flatten chunk-store records without mutating the loaded store."""

    if not isinstance(chunk_store, dict):
        raise TypeError("chunk_store must be a dictionary")
    all_chunks: list[dict[str, Any]] = []
    for material_id, chunks in chunk_store.items():
        if not isinstance(chunks, list):
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            cloned = dict(chunk)
            cloned.setdefault("material_id", str(material_id))
            all_chunks.append(cloned)
    return all_chunks


def _search_refs_visual_query_enabled(query: str) -> bool:
    """Return whether refs should preserve inspectable image evidence."""

    return bool(_VISUAL_SEARCH_INTENT_RE.search(str(query or "")))


def _search_ref_chunk_key(chunk: Mapping[str, Any]) -> str:
    """Return a stable chunk identity for local result merging."""

    chunk_id = _normalize_search_ref_text(chunk.get("chunk_id"), max_chars=200)
    if chunk_id:
        return chunk_id
    material_id = _normalize_search_ref_text(chunk.get("material_id"), max_chars=200)
    chunk_index = _coerce_non_negative_int(chunk.get("chunk_index"))
    if material_id and chunk_index is not None:
        return f"{material_id}:chunk:{chunk_index}"
    return ""


def _search_ref_image_key(chunk: dict[str, Any]) -> str:
    """Return a stable image-asset identity for local visual dedupe."""

    return "|".join(_chunk_image_paths(chunk, max_items=8))


def _visual_search_haystack(chunk: Mapping[str, Any]) -> str:
    """Return bounded text used only for visual evidence ranking."""

    parts = [
        chunk.get("title"),
        chunk.get("material_title"),
        chunk.get("section_title"),
        chunk.get("content"),
        chunk.get("raw_content"),
    ]
    return " ".join(str(part or "") for part in parts).lower()[:6000]


def _visual_search_score(query: str, chunk: dict[str, Any]) -> float:
    """Score pixel-backed chunks for figure/image-oriented search-ref queries."""

    if not _search_refs_visual_query_enabled(query):
        return 0.0
    if not _chunk_image_paths(chunk):
        return 0.0
    haystack = _visual_search_haystack(chunk)
    if not haystack:
        return 0.0

    visual_hits = sum(1 for term in _VISUAL_SEARCH_POSITIVE_TERMS if term in haystack)
    if _visual_link_ids(chunk) or _chunk_figure_table_candidate(chunk):
        visual_hits += 1
    if visual_hits <= 0:
        return 0.0

    normalized_query = str(query or "").lower()
    wants_surface = bool(_VISUAL_SEARCH_SURFACE_QUERY_RE.search(normalized_query))
    wants_cross_section = bool(_VISUAL_SEARCH_CROSS_SECTION_QUERY_RE.search(normalized_query))
    surface_hits = sum(1 for term in _VISUAL_SEARCH_SURFACE_TERMS if term in haystack)
    cross_section_hits = sum(1 for term in _VISUAL_SEARCH_CROSS_SECTION_TERMS if term in haystack)
    score = 4.0 + visual_hits * 1.8
    score += 1.2 * sum(1 for term in _VISUAL_SEARCH_WELD_TERMS if term in haystack)
    if wants_surface:
        score += 3.8 * surface_hits
        if cross_section_hits and not wants_cross_section:
            score -= 2.6 * cross_section_hits
    elif wants_cross_section:
        score += 3.2 * cross_section_hits
    if str(chunk.get("chunk_type") or "").lower() == "figure_caption":
        score += 3.0
    if _chunk_figure_table_candidate(chunk):
        score += 1.0
    score -= 1.5 * sum(1 for term in _VISUAL_SEARCH_LOW_PRIORITY_TERMS if term in haystack)
    return max(score, 0.0)


def _merge_visual_search_ref_chunks(
    query: str,
    selected: list[tuple[float, dict[str, Any]]],
    scored_chunks: list[tuple[float, dict[str, Any]]],
    *,
    top_k: int,
) -> list[tuple[float, dict[str, Any]]]:
    """Blend real image-bearing chunks into visual search-ref results."""

    if not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    if not _search_refs_visual_query_enabled(query) or not scored_chunks:
        return selected[:top_k]

    lexical_score_by_key = {
        key: score
        for score, chunk in scored_chunks
        if (key := _search_ref_chunk_key(chunk))
    }
    ranked_visual: list[tuple[float, int, dict[str, Any]]] = []
    seen_visual_keys: set[str] = set()
    for order, (_lexical_score, chunk) in enumerate(scored_chunks):
        if not isinstance(chunk, dict):
            continue
        chunk_key = _search_ref_chunk_key(chunk)
        if not chunk_key:
            continue
        image_key = _search_ref_image_key(chunk)
        if not image_key or image_key in seen_visual_keys:
            continue
        visual_score = _visual_search_score(query, chunk)
        if visual_score <= 0.0:
            continue
        seen_visual_keys.add(image_key)
        merged_score = max(lexical_score_by_key.get(chunk_key, 0.0) + visual_score, visual_score)
        visual_chunk = dict(chunk)
        labels = _chunk_source_labels(visual_chunk)
        if "visual_image_asset" not in labels:
            visual_chunk["source_labels"] = [*labels, "visual_image_asset"]
        ranked_visual.append((merged_score, -order, visual_chunk))

    if not ranked_visual:
        return selected[:top_k]

    ranked_visual.sort(key=lambda item: (item[0], item[1]), reverse=True)
    desired_visual_count = min(3, max(1, top_k // 4))
    leading_anchor_count = min(len(selected), max(1, min(3, top_k - desired_visual_count)))

    merged: list[tuple[float, dict[str, Any]]] = []
    seen_chunk_keys: set[str] = set()
    for score, chunk in selected[:leading_anchor_count]:
        chunk_key = _search_ref_chunk_key(chunk)
        if not chunk_key or chunk_key in seen_chunk_keys:
            continue
        seen_chunk_keys.add(chunk_key)
        merged.append((score, chunk))

    for score, _order, chunk in ranked_visual:
        chunk_key = _search_ref_chunk_key(chunk)
        if not chunk_key or chunk_key in seen_chunk_keys:
            continue
        seen_chunk_keys.add(chunk_key)
        merged.append((score, chunk))
        if sum(1 for _score, item in merged if _chunk_image_paths(item)) >= desired_visual_count:
            break

    for score, chunk in [*selected[leading_anchor_count:], *selected]:
        chunk_key = _search_ref_chunk_key(chunk)
        if not chunk_key or chunk_key in seen_chunk_keys:
            continue
        seen_chunk_keys.add(chunk_key)
        merged.append((score, chunk))
        if len(merged) >= top_k:
            break

    return merged[:top_k]


def _select_search_ref_chunks(
    chunks: list[dict[str, Any]],
    query: str,
    *,
    top_k: int,
) -> list[tuple[float, dict[str, Any]]]:
    """Return ranked chunks for search refs, preserving visual assets when asked."""

    scored = _rr._score_chunks_for_query(chunks, query)
    selected = _rr._select_diverse_top_chunks(scored, top_k=top_k)
    return _merge_visual_search_ref_chunks(query, selected, scored, top_k=top_k)


def _select_search_ref_chunks_via_gateway(
    *,
    project_id: str,
    chunk_store: dict[str, list[dict[str, Any]]],
    all_chunks: list[dict[str, Any]],
    query: str,
    top_k: int,
    chunk_store_version: str | None = None,
    hash_version: str | None = None,
) -> list[tuple[float, dict[str, Any]]] | None:
    """Return Gateway-ranked refs when the derived FTS index is current.

    The old lexical scorer remains the compatibility fallback because legacy
    projects may not have a rebuilt FTS artifact yet.
    """

    if not isinstance(chunk_store, dict):
        raise TypeError("chunk_store must be a dictionary")
    if not isinstance(all_chunks, list):
        raise TypeError("all_chunks must be a list")
    normalized_project_id = _normalize_search_ref_text(project_id, max_chars=200)
    normalized_query = _normalize_search_ref_text(query, max_chars=4096)
    if not normalized_project_id or not normalized_query:
        raise ValueError("project_id and query must be non-empty")
    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")

    try:
        resolved_hash_version = (
            _normalize_search_ref_text(hash_version, max_chars=128)
            or _chunk_store_hash_version(normalized_project_id)
        )
        resolved_store_version = _normalize_search_ref_text(
            chunk_store_version,
            max_chars=64,
        )
        if not resolved_store_version:
            resolved_store_version = compute_chunk_store_version(
                chunk_store,
                hash_version=resolved_hash_version,
            )
        gateway_result = retrieve_candidates(
            normalized_project_id,
            normalized_query,
            "visual" if _search_refs_visual_query_enabled(normalized_query) else "general",
            store=chunk_store,
            chunk_store_version=resolved_store_version,
            hash_version=resolved_hash_version,
            fts_db_path=_chunk_fts_index_path(normalized_project_id),
            limit=top_k,
            lexical_limit=top_k,
            visual_budget_floor=2,
            visual_budget_intent=max(3, min(12, top_k)),
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if gateway_result.diagnostics.fts_status != "valid" or not gateway_result.candidates:
        return None

    chunk_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in all_chunks:
        if not isinstance(chunk, dict):
            continue
        material_id = _normalize_search_ref_text(chunk.get("material_id"), max_chars=200)
        chunk_id = _normalize_search_ref_text(chunk.get("chunk_id"), max_chars=200)
        if material_id and chunk_id:
            chunk_by_key[(material_id, chunk_id)] = chunk

    selected: list[tuple[float, dict[str, Any]]] = []
    for candidate in gateway_result.candidates:
        chunk = chunk_by_key.get((candidate.material_id, candidate.chunk_id))
        if chunk is None:
            continue
        selected.append((candidate.score, chunk))
    if not selected:
        return None
    if _search_refs_visual_query_enabled(normalized_query):
        scored = _rr._score_chunks_for_query(all_chunks, normalized_query)
        return _merge_visual_search_ref_chunks(
            normalized_query,
            selected,
            scored,
            top_k=top_k,
        )
    return selected[:top_k]


def _select_search_ref_chunks_fts_first(
    *,
    project_id: str,
    query: str,
    top_k: int,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    list[tuple[float, dict[str, Any]]],
] | None:
    """Select text refs by loading only materials named by the current FTS index."""

    if _search_refs_visual_query_enabled(query):
        return None
    try:
        chunk_store_version, hash_version = _rr._chunk_store_retrieval_contract(project_id)
        probe = search_chunk_fts_index(
            db_path=_chunk_fts_index_path(project_id),
            project_id=project_id,
            query=query,
            expected_chunk_store_version=chunk_store_version,
            limit=top_k,
        )
        if probe.status != "valid":
            return None
        if not probe.hits:
            return {}, [], []
        selected_material_ids = tuple(dict.fromkeys(hit.material_id for hit in probe.hits))
        chunk_store = _rr._load_chunk_store_materials_for_retrieval(
            project_id,
            selected_material_ids,
            expected_chunk_store_version=chunk_store_version,
        )
        all_chunks = _flatten_chunk_store_for_search_refs(chunk_store)
        top = _select_search_ref_chunks_via_gateway(
            project_id=project_id,
            chunk_store=chunk_store,
            all_chunks=all_chunks,
            query=query,
            top_k=top_k,
            chunk_store_version=chunk_store_version,
            hash_version=hash_version,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if top is None:
        return None
    return chunk_store, all_chunks, top


def _coerce_bbox(value: Any) -> list[float] | None:
    """Return a four-number bbox only when chunk metadata already provides one."""

    return coerce_pdf_bbox(value)


def _coerce_pdf_anchor_bbox(value: Any) -> list[float] | None:
    """Return a URL-compatible normalized-ratio PDF anchor bbox."""

    bbox = coerce_pdf_bbox(value)
    if bbox is None:
        return None
    return bbox if pdf_bbox_matches_unit(bbox, PdfBboxUnit.NORMALIZED_RATIO) else None


def _candidate_asset_reference(chunk: dict[str, Any]) -> tuple[str, str] | None:
    """Return an existing chunk-produced image reference and its source label."""

    if not isinstance(chunk, dict):
        return None
    for key, source in _CHUNK_ASSET_KEY_SOURCES.items():
        value = _normalize_candidate_text(chunk.get(key), max_chars=260)
        if value:
            return value, source
    for key, source in _CHUNK_ASSET_LIST_KEY_SOURCES.items():
        raw_values = chunk.get(key)
        if not isinstance(raw_values, list):
            continue
        for raw_value in raw_values:
            value = _normalize_candidate_text(raw_value, max_chars=260)
            if value:
                return value, source
    for nested_key in _CHUNK_NESTED_ASSET_KEYS:
        nested = chunk.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key, source in _CHUNK_ASSET_KEY_SOURCES.items():
            value = _normalize_candidate_text(nested.get(key), max_chars=260)
            if value:
                return value, f"{nested_key}_{source}"
        for key, source in _CHUNK_ASSET_LIST_KEY_SOURCES.items():
            raw_values = nested.get(key)
            if not isinstance(raw_values, list):
                continue
            for raw_value in raw_values:
                value = _normalize_candidate_text(raw_value, max_chars=260)
                if value:
                    return value, f"{nested_key}_{source}"
        for deep_key, source in _CHUNK_DEEP_IMAGE_KEY_SOURCES.items():
            deep_value = nested.get(deep_key)
            if not isinstance(deep_value, dict):
                continue
            for image_key in ("image_path", "asset_path"):
                value = _normalize_candidate_text(deep_value.get(image_key), max_chars=260)
                if value:
                    return value, f"{nested_key}_{source}"
    return None


def _candidate_asset_path(chunk: dict[str, Any]) -> str | None:
    """Return the first usable extracted asset reference already present on the chunk."""

    reference = _candidate_asset_reference(chunk)
    return reference[0] if reference is not None else None


def _is_external_candidate_asset_path(asset_path: str) -> bool:
    """Return whether an asset path is not inspectable under project data.

    Args:
        asset_path: Candidate asset reference from chunk metadata or project
            cache.

    Returns:
        True for URL-like and browser-managed image references. Relative
        project paths return False so stale text-line crops can be filtered.
    """

    value = str(asset_path or "").strip().lower()
    if not value:
        return False
    return (
        value.startswith("http://")
        or value.startswith("https://")
        or value.startswith("data:image:")
        or value.startswith("blob:")
        or value.startswith("candidate://")
    )


def _collect_existing_project_asset_paths(project_id: str) -> set[str]:
    """Return project-relative figure image paths already present on disk.

    Args:
        project_id: Non-empty project id used by ``project_data_path``.

    Returns:
        A set of POSIX-style paths relative to the project data root. Missing
        project asset directories return an empty set instead of failing loads.
    """

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return set()

    from project_paths import project_data_path

    try:
        project_root = project_data_path(normalized_project_id)
        asset_root = project_data_path(normalized_project_id, "figure_assets")
        if not asset_root.is_dir():
            return set()
        paths: set[str] = set()
        for path in asset_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in _FIGURE_ASSET_FILE_SUFFIXES:
                paths.add(path.relative_to(project_root).as_posix())
        return paths
    except (OSError, RuntimeError, ValueError):
        return set()


def _existing_candidate_project_asset_path(
    project_id: str,
    material_id: str,
    chunk_id: str,
    label: str,
    existing_project_asset_paths: set[str] | None = None,
) -> str | None:
    """Return a pre-existing project figure asset path without rendering new files.

    Args:
        project_id: Non-empty project id that owns the project data directory.
        material_id: Material id used by the stable crop path convention.
        chunk_id: Chunk id used by the stable crop path convention.
        label: Candidate label such as ``图 1`` or ``表 2``.

    Returns:
        A project-relative image path when the expected file already exists;
        otherwise ``None``. This is intentionally read-only so pixel-only loads
        can reuse existing project artifacts without producing PDF fallbacks.
    """

    normalized_project_id = str(project_id or "").strip()
    normalized_material_id = str(material_id or "").strip()
    normalized_chunk_id = str(chunk_id or "").strip()
    normalized_label = str(label or "").strip()
    if not normalized_project_id or not normalized_material_id or not normalized_chunk_id or not normalized_label:
        return None

    from project_paths import project_data_path

    relative_path = _candidate_crop_path(
        normalized_project_id,
        normalized_material_id,
        normalized_chunk_id,
        normalized_label,
    )
    if existing_project_asset_paths is not None:
        if relative_path not in existing_project_asset_paths:
            return None
        try:
            candidate_path = project_data_path(normalized_project_id, relative_path)
        except (OSError, RuntimeError, ValueError):
            return None
        return relative_path if _is_plausible_figure_preview_asset(candidate_path) else None

    try:
        candidate_path = project_data_path(normalized_project_id, relative_path)
        if candidate_path.is_file() and _is_plausible_figure_preview_asset(candidate_path):
            return relative_path
    except (OSError, RuntimeError, ValueError):
        return None
    return None


def _read_png_dimensions(path: Path) -> tuple[int, int] | None:
    """Return PNG pixel dimensions without importing image libraries.

    Args:
        path: Local PNG path to inspect.

    Returns:
        ``(width, height)`` when the file has a valid PNG signature and IHDR
        dimensions; otherwise ``None``.
    """

    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24 or not header.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    try:
        width, height = struct.unpack(">II", header[16:24])
    except struct.error:
        return None
    if width <= 0 or height <= 0:
        return None
    return int(width), int(height)


def _is_plausible_figure_preview_asset(path: Path) -> bool:
    """Return whether a cached PNG is plausible as a visual figure preview.

    Args:
        path: Existing generated preview path.

    Returns:
        True for image-sized previews. Very short or extremely wide crops are
        usually text-line snippets created from chunk locators and should be
        regenerated as page previews instead of shown as figure thumbnails.
    """

    dimensions = _read_png_dimensions(path)
    if dimensions is None:
        return True
    width, height = dimensions
    if width < 220 or height < 140:
        return False
    aspect = width / max(height, 1)
    if aspect > 5.0 or aspect < 0.12:
        return False
    return True


def _candidate_crop_path(project_id: str, material_id: str, chunk_id: str, label: str) -> str:
    """Return a stable relative path for a generated figure/table crop."""

    safe_material = "".join(c for c in material_id if c.isalnum() or c in "_-") or "material"
    safe_chunk = "".join(c for c in chunk_id if c.isalnum() or c in "_-") or "chunk"
    safe_label = "".join(c for c in label if c.isalnum() or c in "_-") or "figure"
    digest = hashlib.sha1(f"{project_id}|{material_id}|{chunk_id}|{label}".encode("utf-8")).hexdigest()[:16]
    return f"figure_assets/{safe_material}/{safe_chunk}-{safe_label}-{digest}{_CROPPED_IMAGE_SUFFIX}"


def _page_crop_target_rect(page: Any, bbox: list[float] | None) -> Any | None:
    """Convert a normalized bbox into a clipped PDF rect when available."""

    normalized_bbox = _coerce_pdf_anchor_bbox(bbox)
    if normalized_bbox is None:
        return None
    try:
        import pymupdf
    except ImportError:
        return None
    page_rect = getattr(page, "rect", None)
    if page_rect is None:
        return None
    try:
        width = float(getattr(page_rect, "width", 0.0) or 0.0)
        height = float(getattr(page_rect, "height", 0.0) or 0.0)
        if width <= 0 or height <= 0:
            return None
        x, y, w, h = normalized_bbox
        rect = pymupdf.Rect(x * width, y * height, (x + w) * width, (y + h) * height)
        if rect.get_area() <= 0:
            return None
        return rect
    except (TypeError, ValueError, AttributeError):
        return None


def _bbox_is_plausible_figure_region(bbox: list[float] | None) -> bool:
    """Return whether a normalized bbox is large enough for visual preview.

    Args:
        bbox: Candidate PDF bbox in normalized page coordinates.

    Returns:
        True when the bbox resembles a figure/table region. Text-line bboxes
        are intentionally rejected so PDF fallback renders the whole page.
    """

    normalized_bbox = _coerce_pdf_anchor_bbox(bbox)
    if normalized_bbox is None:
        return False
    _x, _y, width, height = normalized_bbox
    if _bbox_is_probable_page_screenshot(normalized_bbox):
        return False
    if width < 0.18 or height < 0.10:
        return False
    if width * height < 0.035:
        return False
    aspect = width / max(height, 1e-6)
    if aspect > 5.0 or aspect < 0.12:
        return False
    return True


def _bbox_is_probable_page_screenshot(bbox: list[float] | None) -> bool:
    """Return whether a bbox describes a whole-page capture, not a figure."""

    normalized_bbox = _coerce_pdf_anchor_bbox(bbox)
    if normalized_bbox is None:
        return False
    _x, _y, width, height = normalized_bbox
    return width >= 0.92 and height >= 0.88


def _pdf_preview_source_label(bbox: list[float] | None) -> str:
    """Return a bounded source label for PDF-generated figure previews."""

    return "pdf_crop" if _bbox_is_plausible_figure_region(bbox) else "pdf_page"


def _candidate_query_tokens(query: str) -> list[str]:
    """Return small query terms for deterministic figure-candidate ranking."""

    normalized = str(query or "").strip().lower()
    if not normalized:
        return []
    raw_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+-]*|[\u4e00-\u9fff]{2,}", normalized)
    return _dedupe_bounded_strings(raw_tokens, max_items=24, max_chars=80)


def _candidate_rank_text(candidate: FigureTableCandidatePayload) -> str:
    """Return normalized text used only for public query-scoped ranking."""

    return " ".join(
        part
        for part in (
            candidate.label,
            candidate.caption,
            candidate.material_title,
            candidate.asset_path or "",
            candidate.source,
        )
        if str(part or "").strip()
    ).lower()


def _candidate_query_score(candidate: FigureTableCandidatePayload, query: str) -> float:
    """Score one figure/table candidate against a visual query."""

    text = _candidate_rank_text(candidate)
    normalized_query = str(query or "").strip().lower()
    if not text or not normalized_query:
        return 0.0

    score = 0.0
    for token in _candidate_query_tokens(normalized_query):
        if token in text:
            score += 1.5

    surface_query = _VISUAL_SEARCH_SURFACE_QUERY_RE.search(normalized_query) is not None
    cross_query = _VISUAL_SEARCH_CROSS_SECTION_QUERY_RE.search(normalized_query) is not None
    if surface_query:
        score += 6.0 * sum(1 for term in _VISUAL_SEARCH_SURFACE_TERMS if term.lower() in text)
        score -= 8.0 * sum(1 for term in _VISUAL_SEARCH_CROSS_SECTION_TERMS if term.lower() in text)
    elif cross_query:
        score += 6.0 * sum(1 for term in _VISUAL_SEARCH_CROSS_SECTION_TERMS if term.lower() in text)
        score -= 4.0 * sum(1 for term in _VISUAL_SEARCH_SURFACE_TERMS if term.lower() in text)

    if any(term in normalized_query for term in _VISUAL_SEARCH_WELD_TERMS):
        score += 2.0 * sum(1 for term in _VISUAL_SEARCH_WELD_TERMS if term in text)
    if _VISUAL_SEARCH_INTENT_RE.search(normalized_query):
        score += 2.0 if candidate.kind == "figure" else 0.0
        score += 4.0 if candidate.asset_path else 0.0
        score -= 5.0 * sum(1 for term in _VISUAL_SEARCH_LOW_PRIORITY_TERMS if term.lower() in text)
    if candidate.source == "pdf_page":
        score -= 6.0
    return score


def _rank_figure_table_candidates_for_query(
    candidates: list[FigureTableCandidatePayload],
    query: str,
) -> list[FigureTableCandidatePayload]:
    """Return candidates sorted for a supplied visual/text query."""

    normalized_query = str(query or "").strip()
    if not normalized_query:
        return candidates
    indexed = list(enumerate(candidates))
    return [
        candidate
        for _index, candidate in sorted(
            indexed,
            key=lambda item: (
                -_candidate_query_score(item[1], normalized_query),
                item[0],
            ),
        )
    ]


def _render_pdf_crop(source_path: Path, page_number: int, bbox: list[float] | None, output_path: Path) -> str | None:
    """Render a PDF page or clipped region to a stable PNG asset."""

    try:
        import pymupdf
    except ImportError:
        return None
    if page_number < 1:
        return None

    try:
        with pymupdf.open(str(source_path)) as doc:
            if page_number > len(doc):
                return None
            page = doc[page_number - 1]
            clip_rect = _page_crop_target_rect(page, bbox) if _bbox_is_plausible_figure_region(bbox) else None
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False, clip=clip_rect)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(output_path))
            return str(output_path)
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError):
        return None


def _clamp_unit(value: float) -> float:
    """Clamp a finite float to the normalized PDF-page coordinate range."""

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0.0
    return min(1.0, max(0.0, float(value)))


def _strip_chunk_locator_prefix(value: Any) -> str:
    """Remove local chunk display prefixes before matching against PDF text."""

    text = str(value or "").strip()
    if text.startswith("[文献:") and "\n" in text:
        return text.split("\n", 1)[1].strip()
    return text


def _normalize_locator_text(value: Any) -> str:
    """Normalize extracted PDF/chunk text for fuzzy page and block matching."""

    text = str(value or "")
    text = text.replace("\u00ad", "")
    text = text.replace("-\n", "")
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def _chunk_locator_text(chunk: dict[str, Any]) -> str:
    """Return the best chunk text candidate for source-PDF reverse lookup."""

    for value in (
        chunk.get("raw_content"),
        _strip_chunk_locator_prefix(chunk.get("content")),
        chunk.get("text"),
    ):
        text = str(value or "").strip()
        if len(_normalize_locator_text(text)) >= _LOCATOR_MIN_TEXT_CHARS:
            return text
    return ""


def _locator_snippets(normalized_text: str) -> list[str]:
    """Return distinctive text windows used to locate a chunk in source PDF pages."""

    text = normalized_text.strip()
    if len(text) < _LOCATOR_MIN_TEXT_CHARS:
        return []
    bounded = text[:1200]
    starts = [0, max(0, len(bounded) // 3), max(0, len(bounded) // 2), max(0, len(bounded) - 180)]
    sizes = [180, 140, 96, 64, 40]
    snippets: list[str] = []
    seen: set[str] = set()
    for start in starts:
        for size in sizes:
            snippet = bounded[start : start + size].strip(" ,.;:，。；：")
            if len(snippet) < _LOCATOR_MIN_TEXT_CHARS:
                continue
            if not _LOCATOR_TOKEN_RE.search(snippet):
                continue
            if snippet in seen:
                continue
            seen.add(snippet)
            snippets.append(snippet)
    return snippets


def _locator_tokens(normalized_text: str) -> set[str]:
    """Tokenize locator text for bounded overlap scoring."""

    tokens = _LOCATOR_TOKEN_RE.findall(normalized_text)
    return {
        token
        for token in tokens
        if len(token) >= 3 or ("\u4e00" <= token <= "\u9fff")
    }


def _locator_text_score(target_text: str, candidate_text: str, snippets: list[str]) -> float:
    """Score whether one PDF page/block likely contains the target chunk."""

    if not target_text or not candidate_text:
        return 0.0
    score = 0.0
    if target_text in candidate_text:
        score += 12.0
    if candidate_text in target_text and len(candidate_text) >= _LOCATOR_MIN_TEXT_CHARS:
        score += 8.0
    for snippet in snippets:
        if snippet in candidate_text:
            score += 3.0 + min(len(snippet) / 80.0, 2.5)
    target_tokens = _locator_tokens(target_text)
    candidate_tokens = _locator_tokens(candidate_text)
    if target_tokens and candidate_tokens:
        shared = len(target_tokens & candidate_tokens)
        if shared > 0:
            score += min(shared / max(8.0, min(len(target_tokens), 80.0)), 1.0) * 3.0
    return score


def _find_chunk_record(
    chunk_store: dict[str, list[dict[str, Any]]],
    material_id: str,
    chunk_id: str,
) -> dict[str, Any] | None:
    """Find the chunk record backing a locator without mutating the store."""

    if not isinstance(chunk_store, dict):
        return None
    material_chunks = chunk_store.get(material_id)
    if isinstance(material_chunks, list):
        for chunk in material_chunks:
            if isinstance(chunk, dict) and chunk.get("chunk_id") == chunk_id:
                return chunk
    for chunks in chunk_store.values():
        if not isinstance(chunks, list):
            continue
        for chunk in chunks:
            if isinstance(chunk, dict) and chunk.get("chunk_id") == chunk_id:
                return chunk
    return None


def _path_is_inside(parent: Path, child: Path) -> bool:
    """Return true when child resolves under parent; resolution failures are unsafe."""

    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _resolve_source_file_under(root: Path, source_relative: str) -> Path | None:
    """Resolve a source-file reference only when it stays under an allowed root.

    Args:
        root: Directory that owns trusted source files for the project.
        source_relative: Stored source reference from project metadata. Absolute
            paths are accepted only when they still resolve under ``root``.

    Returns:
        The existing file path, or ``None`` when the reference is empty, missing,
        outside the root, or not a file.
    """

    normalized_source = str(source_relative or "").strip()
    if not normalized_source:
        return None
    try:
        root_path = root.expanduser().resolve()
        raw_path = Path(normalized_source).expanduser()
        candidate = raw_path.resolve() if raw_path.is_absolute() else (root_path / raw_path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if not _path_is_inside(root_path, candidate):
        return None
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _source_reference_candidates(
    doc_entry: Mapping[str, Any],
    material: Any | None,
) -> list[str]:
    """Return trusted source filename candidates from durable material metadata.

    Why:
        Older uploads can have the original file persisted under ``source_files``
        while the sidecar record lacks ``source_relative_path``. Candidate-based
        repair keeps the reader usable without accepting arbitrary paths.
    """

    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        candidates.append(text)

    source_relative = str(doc_entry.get("source_relative_path") or "").strip()
    if source_relative:
        return [source_relative]

    for key in ("title", "filename", "original_filename"):
        add(doc_entry.get(key))

    if material is not None:
        for attr in ("title", "title_en"):
            add(getattr(material, attr, ""))
        metadata = getattr(material, "metadata", None)
        if isinstance(metadata, Mapping):
            for key in ("source_relative_path", "source_file", "filename", "original_filename"):
                add(metadata.get(key))

    return candidates


def _project_source_roots(project_id: str) -> list[Path]:
    """Return ordered roots that are allowed to serve original source files."""

    roots: list[Path] = []
    source_folder = str(_rr._get_project_source_folder(project_id) or "").strip()
    if source_folder:
        roots.append(Path(source_folder).expanduser())

    from project_paths import project_data_path

    roots.append(project_data_path(project_id, "source_files"))
    return roots


def _relative_reference_for_root(root: Path, source_path: Path) -> str:
    """Return a stable relative source reference for a resolved trusted path."""

    try:
        return source_path.resolve().relative_to(root.expanduser().resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return source_path.name


def _repair_material_source_reference(
    project_id: str,
    material_id: str,
    source_relative: str,
) -> None:
    """Backfill missing ``source_relative_path`` after safe path recovery."""

    normalized = str(source_relative or "").strip()
    if not normalized:
        return
    try:
        def _repair_source_reference(
            doc_store: dict[str, dict[str, Any]],
        ) -> dict[str, dict[str, Any]]:
            record = doc_store.get(material_id)
            if not isinstance(record, dict):
                return doc_store
            if str(record.get("source_relative_path") or "").strip():
                return doc_store
            record["source_relative_path"] = normalized
            doc_store[material_id] = record
            return doc_store

        _rr._update_doc_store_atomic(project_id, _repair_source_reference)
    except (OSError, TypeError, ValueError) as exc:
        _rr.logger.warning(
            "source_reference_repair_failed project_id=%s material_id=%s err=%s",
            project_id,
            material_id,
            exc,
        )


def _resolve_material_source_path(
    project_id: str,
    material_id: str,
    *,
    repair_missing_reference: bool = True,
) -> Path | None:
    """Resolve a material source from trusted roots.

    Args:
        project_id: Project that owns the trusted source roots.
        material_id: Material whose original source is requested.
        repair_missing_reference: Preserve the legacy best-effort metadata
            repair for existing callers. Read-only endpoints pass ``False``.

    Returns:
        Existing project-owned source path, or ``None`` when unavailable.
    """

    normalized_project_id = str(project_id or "").strip()
    normalized_material_id = str(material_id or "").strip()
    if not normalized_project_id or not normalized_material_id:
        return None
    doc_store = _rr._load_doc_store(normalized_project_id)
    doc_entry = doc_store.get(normalized_material_id)
    if not isinstance(doc_entry, dict):
        doc_entry = {}
    material: Any | None = None
    try:
        material = _rr.get_writing_resource_store().get_material(normalized_material_id)
    except (AttributeError, RuntimeError, OSError, TypeError, ValueError):
        material = None
    source_references = _source_reference_candidates(doc_entry, material)
    if not source_references:
        return None

    for root in _project_source_roots(normalized_project_id):
        for source_reference in source_references:
            candidate = _resolve_source_file_under(root, source_reference)
            if candidate is not None:
                if (
                    repair_missing_reference
                    and not str(doc_entry.get("source_relative_path") or "").strip()
                ):
                    _repair_material_source_reference(
                        normalized_project_id,
                        normalized_material_id,
                        _relative_reference_for_root(root, candidate),
                    )
                return candidate
    return None


def _locator_cache_key(
    *,
    project_id: str,
    material_id: str,
    chunk_id: str,
    source_path: Path,
    chunk_text: str,
) -> str:
    """Build a cache key tied to source-file identity and chunk text."""

    try:
        stat = source_path.stat()
        source_sig = f"{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        source_sig = "missing"
    text_sig = hashlib.sha1(chunk_text[:2048].encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{project_id}|{material_id}|{chunk_id}|{source_path}|{source_sig}|{text_sig}"


def _remember_pdf_locator(key: str, value: dict[str, Any] | None) -> None:
    """Keep locator fallback cache bounded in process memory."""

    _pdf_locator_cache[key] = value
    while len(_pdf_locator_cache) > _LOCATOR_CACHE_MAX:
        oldest = next(iter(_pdf_locator_cache))
        del _pdf_locator_cache[oldest]


def _normalized_bbox_from_rect(rect: Any, page_rect: Any) -> list[float] | None:
    """Convert a PyMuPDF rect into [x, y, w, h] normalized page coordinates."""

    page_width = float(getattr(page_rect, "width", 0.0) or 0.0)
    page_height = float(getattr(page_rect, "height", 0.0) or 0.0)
    if page_width <= 0 or page_height <= 0:
        return None
    x0 = _clamp_unit(float(getattr(rect, "x0", 0.0) or 0.0) / page_width)
    y0 = _clamp_unit(float(getattr(rect, "y0", 0.0) or 0.0) / page_height)
    x1 = _clamp_unit(float(getattr(rect, "x1", 0.0) or 0.0) / page_width)
    y1 = _clamp_unit(float(getattr(rect, "y1", 0.0) or 0.0) / page_height)
    width = max(0.0, min(1.0 - x0, x1 - x0))
    height = max(0.0, min(1.0 - y0, y1 - y0))
    if width <= 0 or height <= 0:
        return None
    return [round(x0, 4), round(y0, 4), round(width, 4), round(height, 4)]


def _bbox_from_text_blocks(page: Any, target_text: str, snippets: list[str]) -> list[float] | None:
    """Find a paragraph-like PDF text block for the target chunk."""

    try:
        blocks = page.get_text("blocks", sort=True)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    best_rect: Any | None = None
    best_score = 0.0
    try:
        import pymupdf
    except ImportError:
        return None
    for block in blocks or []:
        if not isinstance(block, (list, tuple)) or len(block) < 5:
            continue
        block_text = _normalize_locator_text(block[4])
        if not block_text:
            continue
        score = _locator_text_score(target_text, block_text, snippets)
        if score <= best_score:
            continue
        try:
            best_rect = pymupdf.Rect(float(block[0]), float(block[1]), float(block[2]), float(block[3]))
            best_score = score
        except (TypeError, ValueError):
            continue
    if best_rect is None or best_score < 2.8:
        return None
    return _normalized_bbox_from_rect(best_rect, page.rect)


def _bbox_from_text_search(page: Any, snippets: list[str]) -> list[float] | None:
    """Use PyMuPDF text search as a precise fallback when block scoring misses."""

    try:
        import pymupdf
    except ImportError:
        return None
    for snippet in snippets:
        try:
            rects = page.search_for(snippet)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            rects = []
        if not rects:
            continue
        union = pymupdf.Rect(rects[0])
        for rect in rects[1:]:
            union.include_rect(rect)
        bbox = _normalized_bbox_from_rect(union, page.rect)
        if bbox is not None:
            return bbox
    return None


def _locate_chunk_text_in_pdf(
    source_path: Path,
    chunk_text: str,
    *,
    preferred_page: int | None = None,
) -> dict[str, Any] | None:
    """Locate chunk text in a PDF and return page plus normalized bbox."""

    normalized_text = _normalize_locator_text(chunk_text)
    snippets = _locator_snippets(normalized_text)
    if not snippets:
        return None
    try:
        import pymupdf
    except ImportError:
        return None

    try:
        with pymupdf.open(str(source_path)) as doc:
            page_count = len(doc)
            if page_count <= 0:
                return None
            ordered_indexes: list[int] = []
            if preferred_page is not None and 1 <= preferred_page <= page_count:
                ordered_indexes.append(preferred_page - 1)
            ordered_indexes.extend(index for index in range(page_count) if index not in ordered_indexes)

            best: tuple[float, int, Any] | None = None
            for page_index in ordered_indexes:
                page = doc[page_index]
                page_text = _normalize_locator_text(page.get_text("text"))
                score = _locator_text_score(normalized_text, page_text, snippets)
                if preferred_page is not None and page_index == preferred_page - 1 and score > 0:
                    score += 1.0
                if score <= 0:
                    continue
                if best is None or score > best[0]:
                    best = (score, page_index, page)
                if score >= 8.0:
                    break

            if best is None or best[0] < 2.8:
                return None
            _, page_index, page = best
            bbox = _bbox_from_text_blocks(page, normalized_text, snippets)
            if bbox is None:
                bbox = _bbox_from_text_search(page, snippets)
            return {
                "page": page_index + 1,
                **({"bbox": bbox} if bbox is not None else {}),
                **({"bbox_unit": PdfBboxUnit.NORMALIZED_RATIO.value} if bbox is not None else {}),
                "text_preview": _normalize_candidate_text(chunk_text, max_chars=180),
            }
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def enrich_chunk_locator_with_pdf(
    project_id: str,
    chunk_store: dict[str, list[dict[str, Any]]],
    locator: dict[str, Any],
) -> dict[str, Any]:
    """Enrich a chunk locator by reverse-locating its text in the source PDF.

    Args:
        project_id: Project owning the chunk and source file metadata.
        chunk_store: Already-loaded chunk store. This function never mutates it.
        locator: Base locator from ``find_chunk_locator``.

    Returns:
        The original locator or a shallow copy with inferred page, bbox, and
        text_preview. This is best-effort and read-only.
    """

    if not isinstance(locator, dict):
        raise ValueError("locator must be a dict")
    normalized_project_id = str(project_id or "").strip()
    material_id = str(locator.get("material_id") or "").strip()
    chunk_id = str(locator.get("chunk_id") or "").strip()
    if not normalized_project_id or not material_id or not chunk_id:
        return locator
    existing_page = _coerce_positive_int(locator.get("page"))
    existing_anchor = _coerce_declared_bbox_anchor(
        locator.get("bbox"),
        locator.get("bbox_unit"),
    )
    existing_bbox = existing_anchor[0] if existing_anchor is not None else None
    normalized_locator = dict(locator)
    if existing_anchor is None:
        normalized_locator.pop("bbox", None)
        normalized_locator.pop("bbox_unit", None)
    else:
        normalized_locator["bbox"] = existing_anchor[0]
        normalized_locator["bbox_unit"] = existing_anchor[1].value
    if existing_page is not None and existing_bbox is not None:
        return normalized_locator

    chunk = _find_chunk_record(chunk_store, material_id, chunk_id)
    if chunk is None:
        return normalized_locator
    chunk_text = _chunk_locator_text(chunk)
    if len(_normalize_locator_text(chunk_text)) < _LOCATOR_MIN_TEXT_CHARS:
        return normalized_locator
    source_path = _resolve_material_source_path(normalized_project_id, material_id)
    if source_path is None or source_path.suffix.lower() != ".pdf":
        return normalized_locator

    cache_key = _locator_cache_key(
        project_id=normalized_project_id,
        material_id=material_id,
        chunk_id=chunk_id,
        source_path=source_path,
        chunk_text=chunk_text,
    )
    if cache_key in _pdf_locator_cache:
        cached = _pdf_locator_cache[cache_key]
    else:
        cached = _locate_chunk_text_in_pdf(source_path, chunk_text, preferred_page=existing_page)
        _remember_pdf_locator(cache_key, cached)
    if not cached:
        return normalized_locator

    enriched = dict(normalized_locator)
    cached_page = _coerce_positive_int(cached.get("page"))
    cached_anchor = _coerce_declared_bbox_anchor(
        cached.get("bbox"),
        cached.get("bbox_unit"),
    )
    if existing_bbox is None and cached_anchor is not None and cached_page is not None:
        # A rectangle is only meaningful on the page whose viewport produced it.
        enriched["page"] = cached_page
        enriched["bbox"] = cached_anchor[0]
        enriched["bbox_unit"] = cached_anchor[1].value
    elif existing_page is None and cached_page is not None:
        enriched["page"] = cached_page
    if str(cached.get("text_preview") or "").strip():
        enriched["text_preview"] = str(cached["text_preview"])
    return enriched


def _candidate_kind(prefix: str) -> str:
    """Map a figure/table textual prefix to the public candidate kind."""

    lowered = prefix.strip().lower()
    if lowered in {"表", "table"}:
        return "table"
    return "figure"


def _candidate_label(kind: str, number: str) -> str:
    """Build a Chinese manuscript label while preserving source numbering."""

    normalized_number = number.strip().replace("–", "-").replace("—", "-")
    return f"{'表' if kind == 'table' else '图'} {normalized_number}"


def _candidate_label_from_asset_name(value: str) -> tuple[str, str]:
    """Return kind and display label parsed from a figure asset filename segment."""

    normalized = _normalize_candidate_text(value, max_chars=80).replace("圖", "图")
    if not normalized:
        return "figure", "图"
    match = _FIGURE_TABLE_PREFIX_RE.search(normalized)
    if match:
        kind = _candidate_kind(match.group("prefix"))
        return kind, _candidate_label(kind, match.group("number"))
    lowered = normalized.lower()
    kind = "table" if lowered.startswith("table") or normalized.startswith("表") else "figure"
    if kind == "figure" and normalized.startswith("图") and not normalized.startswith("图 "):
        return kind, f"图 {normalized[1:].strip() or ''}".strip()
    if kind == "table" and normalized.startswith("表") and not normalized.startswith("表 "):
        return kind, f"表 {normalized[1:].strip() or ''}".strip()
    return kind, normalized


def _candidate_caption(content: str, match: re.Match[str]) -> str:
    """Extract the nearest caption span from a chunk-level text match."""

    start = max(0, match.start() - 16)
    tail = content[match.start() : match.start() + 360]
    stop_match = _CAPTION_STOP_RE.search(tail, pos=max(1, match.end() - match.start()))
    if stop_match:
        tail = tail[: stop_match.start()]
    prefix = content[start : match.start()].strip(" \n\r\t:：;；,.，。")
    caption = f"{prefix} {tail}".strip() if prefix else tail
    return _normalize_candidate_text(caption) or "来自项目切块的图表候选"


def _candidate_caption_from_asset(label: str) -> str:
    """Return a caption that never exposes unrelated body text snippets."""

    normalized_label = _normalize_candidate_text(label, max_chars=80)
    return f"{normalized_label}（切块图片）" if normalized_label else "来自项目切块的图表候选"


def _candidate_id(
    *,
    project_id: str,
    kind: str,
    material_id: str,
    chunk_id: str,
    label: str,
) -> str:
    """Return a deterministic id so repeated refreshes do not reorder UI state."""

    payload = f"{project_id}|{kind}|{material_id}|{chunk_id}|{label}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"


def _chunk_record_index(
    chunk_store: dict[str, list[dict[str, Any]]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Index chunk records by material and chunk id for figure asset joins."""

    if not isinstance(chunk_store, dict):
        raise ValueError("chunk_store must be a dict")
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for material_id, chunks in chunk_store.items():
        if not isinstance(chunks, list):
            continue
        normalized_material_id = str(material_id or "").strip()
        if not normalized_material_id:
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            chunk_id = str(chunk.get("chunk_id") or "").strip()
            if chunk_id:
                index[(normalized_material_id, chunk_id)] = chunk
    return index


def _parse_project_figure_asset(
    project_root: Path,
    asset_path: Path,
) -> dict[str, str] | None:
    """Parse project-relative figure asset metadata from a stored image path."""

    if asset_path.suffix.lower() not in _FIGURE_ASSET_FILE_SUFFIXES:
        return None
    try:
        relative_path = asset_path.relative_to(project_root).as_posix()
    except ValueError:
        return None
    parts = relative_path.split("/")
    if len(parts) < 3 or parts[0] != "figure_assets":
        return None
    material_id = parts[1].strip()
    if not material_id:
        return None
    stem_parts = asset_path.stem.rsplit("-", 2)
    if len(stem_parts) < 3:
        return None
    chunk_id, raw_label, digest = (part.strip() for part in stem_parts)
    if not chunk_id or not raw_label or not digest:
        return None
    kind, label = _candidate_label_from_asset_name(raw_label)
    return {
        "relative_path": relative_path,
        "material_id": material_id,
        "chunk_id": chunk_id,
        "kind": kind,
        "label": label,
    }


def _chunk_index_from_id(chunk_id: str) -> int | None:
    """Return a chunk index parsed from the stable chunk id suffix."""

    match = re.search(r"_chunk_(\d+)$", chunk_id)
    if not match:
        return None
    return _coerce_non_negative_int(match.group(1))


def _derive_project_figure_asset_candidates(
    project_id: str,
    chunk_store: dict[str, list[dict[str, Any]]],
    *,
    limit: int,
) -> list[FigureTableCandidatePayload]:
    """Return candidates backed directly by files under project ``figure_assets``."""

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(limit, int) or limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")

    from project_paths import project_data_path

    project_root = project_data_path(normalized_project_id)
    asset_root = project_data_path(normalized_project_id, "figure_assets")
    if not asset_root.is_dir():
        return []

    chunk_index = _chunk_record_index(chunk_store)
    rows: list[tuple[str, int, str, str, FigureTableCandidatePayload]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for asset_path in asset_root.rglob("*"):
        if not asset_path.is_file():
            continue
        if not _is_plausible_figure_preview_asset(asset_path):
            continue
        parsed = _parse_project_figure_asset(project_root, asset_path)
        if parsed is None:
            continue
        material_id = parsed["material_id"]
        chunk_id = parsed["chunk_id"]
        kind = parsed["kind"]
        label = parsed["label"]
        dedupe_key = (kind, material_id, chunk_id, label.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        chunk = chunk_index.get((material_id, chunk_id), {})
        material_title = _normalize_candidate_text(
            chunk.get("title") or chunk.get("material_title") or material_id,
            max_chars=120,
        )
        chunk_index_value = (
            _coerce_non_negative_int(chunk.get("chunk_index"))
            if isinstance(chunk, dict)
            else None
        )
        bbox_anchor = (
            _coerce_declared_bbox_anchor(
                chunk.get("bbox"),
                chunk.get("bbox_unit"),
            )
            if isinstance(chunk, dict)
            else None
        )
        bbox = bbox_anchor[0] if bbox_anchor is not None else None
        bbox_unit = bbox_anchor[1] if bbox_anchor is not None else None
        if (
            bbox is not None
            and bbox_unit == PdfBboxUnit.NORMALIZED_RATIO
            and not _bbox_is_plausible_figure_region(bbox)
        ):
            continue
        if chunk_index_value is None:
            chunk_index_value = _chunk_index_from_id(chunk_id)
        payload = FigureTableCandidatePayload(
            id=_candidate_id(
                project_id=normalized_project_id,
                kind=kind,
                material_id=material_id,
                chunk_id=chunk_id,
                label=label,
            ),
            kind=kind,
            label=label,
            caption=_candidate_caption_from_asset(label),
            material_id=material_id,
            material_title=material_title or material_id,
            page=_coerce_positive_int(chunk.get("page")) if isinstance(chunk, dict) else None,
            chunk_id=chunk_id,
            chunk_index=chunk_index_value,
            bbox=bbox,
            bbox_unit=bbox_unit,
            asset_path=parsed["relative_path"],
            source="project_figure_asset",
        )
        rows.append((material_id, chunk_index_value if chunk_index_value is not None else 10**9, label, parsed["relative_path"], payload))

    rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return [payload for *_prefix, payload in rows[:limit]]


def _augment_chunks_with_project_figure_assets(
    project_id: str,
    chunk_store: dict[str, list[dict[str, Any]]],
    all_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return chunk clones with derived project figure assets attached.

    Args:
        project_id: Project that owns ``figure_assets`` and the chunk store.
        chunk_store: Truth chunk store used only for read-only asset joins.
        all_chunks: Flattened chunk records prepared for retrieval.

    Returns:
        A list suitable for search/evidence projection. Returned chunks may
        include derived ``image_paths`` and figure metadata, but the source
        ``chunk_store`` and supplied chunk dictionaries are never mutated.

    Raises:
        TypeError: If ``chunk_store`` or ``all_chunks`` have invalid shapes.
        ValueError: If ``project_id`` is empty.
    """

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(chunk_store, dict):
        raise TypeError("chunk_store must be a dictionary")
    if not isinstance(all_chunks, list):
        raise TypeError("all_chunks must be a list")

    candidates = _derive_project_figure_asset_candidates(
        normalized_project_id,
        chunk_store,
        limit=200,
    )
    if not candidates:
        return list(all_chunks)

    candidates_by_chunk: dict[tuple[str, str], list[FigureTableCandidatePayload]] = {}
    for candidate in candidates:
        material_id = _normalize_search_ref_text(candidate.material_id, max_chars=200)
        chunk_id = _normalize_search_ref_text(candidate.chunk_id, max_chars=200)
        asset_path = _normalize_search_ref_text(candidate.asset_path, max_chars=260)
        if not material_id or not chunk_id or not asset_path:
            continue
        candidates_by_chunk.setdefault((material_id, chunk_id), []).append(candidate)
    if not candidates_by_chunk:
        return list(all_chunks)

    augmented: list[dict[str, Any]] = []
    for chunk in all_chunks:
        if not isinstance(chunk, dict):
            continue
        material_id = _normalize_search_ref_text(chunk.get("material_id"), max_chars=200)
        chunk_id = _normalize_search_ref_text(chunk.get("chunk_id"), max_chars=200)
        chunk_candidates = candidates_by_chunk.get((material_id, chunk_id))
        if not chunk_candidates:
            augmented.append(chunk)
            continue

        clone = dict(chunk)
        derived_assets = [
            str(candidate.asset_path).strip()
            for candidate in chunk_candidates
            if isinstance(candidate.asset_path, str) and candidate.asset_path.strip()
        ]
        merged_assets = _dedupe_bounded_strings(
            [*_chunk_image_paths(clone, max_items=8), *derived_assets],
            max_items=8,
            max_chars=260,
        )
        if merged_assets:
            clone["image_paths"] = merged_assets

        labels = _chunk_source_labels(clone)
        if "visual_project_figure_asset" not in labels:
            clone["source_labels"] = [*labels, "visual_project_figure_asset"]
            labels = _chunk_source_labels(clone)
        if "visual_image_asset" not in labels:
            clone["source_labels"] = [*labels, "visual_image_asset"]

        primary = chunk_candidates[0]
        clone.setdefault("figure_candidate", primary.id)
        clone.setdefault("figure_asset_path", primary.asset_path)
        clone.setdefault("asset_path", primary.asset_path)
        clone.setdefault("figure_candidate_source", "project_figure_asset")
        augmented.append(clone)

    return augmented


def _visual_link_ids(chunk: Mapping[str, Any]) -> list[str]:
    """Return bounded figure/table ids that a narrative chunk references."""

    if not isinstance(chunk, Mapping):
        return []
    values: list[str] = []
    for key in ("linked_figure_ids", "linked_table_ids"):
        values.extend(_dedupe_bounded_strings(chunk.get(key), max_items=8, max_chars=260))
    return _dedupe_bounded_strings(values, max_items=8, max_chars=260)


def _chunk_primary_visual_id(chunk: Mapping[str, Any]) -> str:
    """Return this chunk's own caption/table id when it has primary pixels."""

    if not isinstance(chunk, Mapping):
        return ""
    for key in ("figure_id", "table_id"):
        value = _normalize_search_ref_text(chunk.get(key), max_chars=260)
        if value:
            return value
    return ""


def _visual_link_asset_index(chunk_store: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Index primary caption chunks by figure/table id for read-only joins."""

    if not isinstance(chunk_store, dict):
        raise TypeError("chunk_store must be a dictionary")
    by_id: dict[str, dict[str, Any]] = {}
    for material_id, chunks in chunk_store.items():
        if not isinstance(chunks, list):
            continue
        normalized_material_id = _normalize_search_ref_text(material_id, max_chars=200)
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            visual_id = _chunk_primary_visual_id(chunk)
            if not visual_id or visual_id in by_id or not _chunk_image_paths(chunk):
                continue
            clone = dict(chunk)
            if normalized_material_id:
                clone.setdefault("material_id", normalized_material_id)
            by_id[visual_id] = clone
    return by_id


def _augment_chunks_with_linked_visual_assets(
    chunk_store: dict[str, list[dict[str, Any]]],
    all_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach caption-bound pixels to narrative chunks that reference them.

    The persisted chunk store remains unchanged. This only helps retrieval and
    evidence payloads surface the existing caption asset when a body paragraph
    is the lexical hit.
    """

    if not isinstance(chunk_store, dict):
        raise TypeError("chunk_store must be a dictionary")
    if not isinstance(all_chunks, list):
        raise TypeError("all_chunks must be a list")
    primary_by_id = _visual_link_asset_index(chunk_store)
    if not primary_by_id:
        return list(all_chunks)

    augmented: list[dict[str, Any]] = []
    for chunk in all_chunks:
        if not isinstance(chunk, dict):
            continue
        linked_ids = _visual_link_ids(chunk)
        if not linked_ids:
            augmented.append(chunk)
            continue

        linked_chunks = [primary_by_id[visual_id] for visual_id in linked_ids if visual_id in primary_by_id]
        if not linked_chunks:
            augmented.append(chunk)
            continue

        clone = dict(chunk)
        derived_assets: list[str] = []
        for linked_chunk in linked_chunks:
            derived_assets.extend(_chunk_image_paths(linked_chunk, max_items=4))
        merged_assets = _dedupe_bounded_strings(
            [*_chunk_image_paths(clone, max_items=8), *derived_assets],
            max_items=8,
            max_chars=260,
        )
        if merged_assets:
            clone["image_paths"] = merged_assets

        primary = linked_chunks[0]
        clone.setdefault("figure_candidate", _chunk_figure_table_candidate(primary) or linked_ids[0])
        if not _normalize_search_ref_text(clone.get("figure_asset_path"), max_chars=260):
            linked_assets = _chunk_image_paths(primary, max_items=1)
            if linked_assets:
                clone["figure_asset_path"] = linked_assets[0]
                clone.setdefault("asset_path", linked_assets[0])
        clone.setdefault("figure_candidate_source", "linked_caption_chunk")

        labels = _chunk_source_labels(clone)
        if "visual_linked_caption_asset" not in labels:
            clone["source_labels"] = [*labels, "visual_linked_caption_asset"]
            labels = _chunk_source_labels(clone)
        if "visual_image_asset" not in labels:
            clone["source_labels"] = [*labels, "visual_image_asset"]
        augmented.append(clone)

    return augmented


def _enrich_candidate_layout(
    *,
    project_id: str,
    material_id: str,
    chunk_id: str,
    chunk_store: dict[str, list[dict[str, Any]]],
    chunk: dict[str, Any],
    label: str,
    existing_page: int | None,
    existing_bbox: list[float] | None,
    existing_bbox_unit: PdfBboxUnit | None,
    existing_asset_path: str | None,
    existing_asset_source: str = "chunk_asset",
    render_pdf_fallback: bool = True,
) -> tuple[int | None, list[float] | None, PdfBboxUnit | None, str | None, str]:
    """Return page, atomic bbox/unit, asset path, and source label."""

    from project_paths import project_data_path

    page = existing_page
    existing_anchor = _coerce_declared_bbox_anchor(
        existing_bbox,
        existing_bbox_unit,
    )
    bbox = existing_anchor[0] if existing_anchor is not None else None
    bbox_unit = existing_anchor[1] if existing_anchor is not None else None
    asset_path = existing_asset_path
    source = existing_asset_source if asset_path else "chunk_text"

    chunk_text = _chunk_locator_text(chunk)
    if (page is None or bbox is None) and len(_normalize_locator_text(chunk_text)) >= _LOCATOR_MIN_TEXT_CHARS:
        locator = enrich_chunk_locator_with_pdf(
            project_id,
            chunk_store,
            {
                "material_id": material_id,
                "chunk_id": chunk_id,
                **({"page": page} if page is not None else {}),
                **(
                    {"bbox": bbox, "bbox_unit": bbox_unit.value}
                    if bbox is not None and bbox_unit is not None
                    else {}
                ),
            },
        )
        page = _coerce_positive_int(locator.get("page")) or page
        locator_anchor = _coerce_declared_bbox_anchor(
            locator.get("bbox"),
            locator.get("bbox_unit"),
        )
        if locator_anchor is not None:
            bbox, bbox_unit = locator_anchor

    preview_bbox = (
        bbox if bbox_unit == PdfBboxUnit.NORMALIZED_RATIO else None
    )

    if asset_path:
        keep_existing_asset = True
        if source == "project_figure_asset" and not _is_external_candidate_asset_path(asset_path):
            try:
                existing_path = project_data_path(project_id, asset_path)
            except (OSError, RuntimeError, ValueError):
                existing_path = None
            region_is_visual = preview_bbox is None or _bbox_is_plausible_figure_region(preview_bbox)
            keep_existing_asset = bool(
                existing_path is not None
                and existing_path.is_file()
                and region_is_visual
                and _is_plausible_figure_preview_asset(existing_path)
            )
        if keep_existing_asset:
            return page, bbox, bbox_unit, asset_path, source
        asset_path = None
        source = "chunk_text"

    if not render_pdf_fallback:
        return page, bbox, bbox_unit, asset_path, source

    source_path = _resolve_material_source_path(project_id, material_id)
    if source_path is None or source_path.suffix.lower() != ".pdf" or page is None:
        return page, bbox, bbox_unit, asset_path, source

    relative_path = _candidate_crop_path(project_id, material_id, chunk_id, label)
    output_path = project_data_path(project_id, relative_path)
    if output_path.is_file() and _is_plausible_figure_preview_asset(output_path):
        return page, bbox, bbox_unit, relative_path, _pdf_preview_source_label(preview_bbox)

    rendered_path = _render_pdf_crop(source_path, page, preview_bbox, output_path)
    if rendered_path:
        source = _pdf_preview_source_label(preview_bbox)
        asset_path = relative_path
    return page, bbox, bbox_unit, asset_path, source


def derive_figure_table_candidates(
    project_id: str,
    chunk_store: dict[str, list[dict[str, Any]]],
    *,
    limit: int = _MAX_FIGURE_TABLE_CANDIDATES,
    pixel_only: bool = False,
    render_pdf_fallback: bool = True,
    query: str | None = None,
) -> list[FigureTableCandidatePayload]:
    """Derive stable figure/table candidates from already-indexed chunks.

    Args:
        project_id: Project identifier owning the chunks.
        chunk_store: Material-id keyed chunk store from ``_ensure_project_chunks``.
        limit: Positive upper bound for response size.
        pixel_only: When true, return only rows backed by an image path already
            recorded on the chunk data. This mode never reconnects old
            text-derived PDF crop caches and never renders new PDF crops.
        render_pdf_fallback: When true, missing image paths may be generated by
            rendering the source PDF. Disable this for user-facing chunk-asset
            loading so generic PDF page/crop substitutes never enter results.
        query: Optional user/retrieval query used only to rank candidates. It
            does not change the response model or create new assets.

    Returns:
        Candidate payloads sorted by material/chunk order.

    Raises:
        ValueError: If ``project_id`` is empty, ``chunk_store`` is not a dict,
            or ``limit`` is outside the accepted range.
    """

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(chunk_store, dict):
        raise ValueError("chunk_store must be a dict")
    if not isinstance(limit, int) or limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if not isinstance(pixel_only, bool):
        raise ValueError("pixel_only must be a bool")
    if not isinstance(render_pdf_fallback, bool):
        raise ValueError("render_pdf_fallback must be a bool")
    normalized_query = _normalize_search_ref_text(query, max_chars=4096) if query is not None else ""
    if normalized_query and (pixel_only or not render_pdf_fallback):
        collection_limit = 10000
    elif normalized_query:
        collection_limit = min(200, max(limit, _MAX_FIGURE_TABLE_CANDIDATES))
    else:
        collection_limit = limit

    candidates: list[FigureTableCandidatePayload] = []
    seen: set[tuple[str, str, str]] = set()
    existing_project_asset_paths = (
        set()
        if pixel_only or not render_pdf_fallback
        else _collect_existing_project_asset_paths(normalized_project_id)
    )
    for material_id in sorted(chunk_store):
        chunks = chunk_store.get(material_id) or []
        if not isinstance(chunks, list):
            continue
        sorted_chunks = sorted(
            (chunk for chunk in chunks if isinstance(chunk, dict)),
            key=lambda chunk: (
                _coerce_non_negative_int(chunk.get("chunk_index")) or 0,
                str(chunk.get("chunk_id") or ""),
            ),
        )
        for chunk in sorted_chunks:
            raw_content = str(chunk.get("raw_content") or "").strip()
            content = raw_content or str(chunk.get("content") or "").strip()
            if not content:
                continue
            chunk_id = str(chunk.get("chunk_id") or "").strip() or f"{material_id}_chunk_{len(candidates)}"
            material_title = _normalize_candidate_text(
                chunk.get("title") or chunk.get("material_title") or material_id,
                max_chars=120,
            )
            for match in _FIGURE_TABLE_PREFIX_RE.finditer(content):
                kind = _candidate_kind(match.group("prefix"))
                label = _candidate_label(kind, match.group("number"))
                dedupe_key = (kind, str(material_id), label.lower())
                if dedupe_key in seen:
                    continue
                page = _coerce_positive_int(chunk.get("page"))
                bbox_anchor = _coerce_declared_bbox_anchor(
                    chunk.get("bbox"),
                    chunk.get("bbox_unit"),
                )
                bbox = bbox_anchor[0] if bbox_anchor is not None else None
                bbox_unit = bbox_anchor[1] if bbox_anchor is not None else None
                preview_bbox = (
                    bbox if bbox_unit == PdfBboxUnit.NORMALIZED_RATIO else None
                )
                asset_reference = _candidate_asset_reference(chunk)
                asset_path = asset_reference[0] if asset_reference is not None else None
                asset_source = asset_reference[1] if asset_reference is not None else "chunk_text"
                if asset_path and _bbox_is_probable_page_screenshot(preview_bbox):
                    continue
                if not asset_path and not pixel_only and render_pdf_fallback:
                    existing_asset_path = _existing_candidate_project_asset_path(
                        normalized_project_id,
                        str(material_id),
                        chunk_id,
                        label,
                        existing_project_asset_paths,
                    )
                    if existing_asset_path:
                        asset_path = existing_asset_path
                        asset_source = "project_figure_asset"
                if pixel_only and not asset_path:
                    continue
                page, bbox, bbox_unit, asset_path, source = _enrich_candidate_layout(
                    project_id=normalized_project_id,
                    material_id=str(material_id),
                    chunk_id=chunk_id,
                    chunk_store=chunk_store,
                    chunk=chunk,
                    label=label,
                    existing_page=page,
                    existing_bbox=bbox,
                    existing_bbox_unit=bbox_unit,
                    existing_asset_path=asset_path,
                    existing_asset_source=asset_source,
                    render_pdf_fallback=render_pdf_fallback and not pixel_only,
                )
                if pixel_only and (not asset_path or source in {"pdf_crop", "pdf_page", "project_figure_asset"}):
                    continue
                seen.add(dedupe_key)
                candidates.append(
                    FigureTableCandidatePayload(
                        id=_candidate_id(
                            project_id=normalized_project_id,
                            kind=kind,
                            material_id=str(material_id),
                            chunk_id=chunk_id,
                            label=label,
                        ),
                        kind=kind,
                        label=label,
                        caption=_candidate_caption(content, match),
                        material_id=str(material_id),
                        material_title=material_title or str(material_id),
                        page=page,
                        chunk_id=chunk_id,
                        chunk_index=_coerce_non_negative_int(chunk.get("chunk_index")),
                        bbox=bbox,
                        bbox_unit=bbox_unit,
                        asset_path=asset_path,
                        source=source,
                    )
                )
                if len(candidates) >= collection_limit:
                    ranked = _rank_figure_table_candidates_for_query(candidates, normalized_query)
                    return ranked[:limit]
    ranked = _rank_figure_table_candidates_for_query(candidates, normalized_query)
    return ranked[:limit]


@_rr.router.get(
    "/material/{material_id}/formula-candidates",
    response_model=FormulaCandidatesResponse,
    tags=["Resources"],
)
def list_material_formula_candidates(
    material_id: str,
    project_id: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(200, ge=1, le=200),
) -> FormulaCandidatesResponse:
    """List atomic formula targets for one project-owned PDF material.

    This route is intentionally synchronous so FastAPI runs the bounded
    PyMuPDF text-layer scan in its worker threadpool instead of blocking the
    async event loop. It never repairs source metadata or persists candidates.
    Reliable structured formula chunks are merged with conservative line-level
    detection, preserving existing parser output while filling local gaps.
    """

    normalized_project_id = str(project_id or "").strip()
    normalized_material_id = str(material_id or "").strip()
    if not normalized_project_id or not normalized_material_id:
        raise HTTPException(status_code=422, detail="project_id and material_id must be non-empty")

    store = _rr._ensure_upload_project(normalized_project_id)
    material = store.get_material(normalized_material_id)
    if material is None:
        raise HTTPException(
            status_code=404,
            detail=f"Material not found in project: {normalized_material_id}",
        )
    if isinstance(material, Mapping):
        owner_project_id = str(material.get("project_id") or "").strip()
    else:
        owner_project_id = str(getattr(material, "project_id", "") or "").strip()
    if owner_project_id != normalized_project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Material not found in project: {normalized_material_id}",
        )

    try:
        chunk_store = _rr._load_chunk_store(normalized_project_id)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        _rr.logger.warning(
            "formula_candidate_chunk_store_unavailable project_id=%s material_id=%s err=%s",
            normalized_project_id,
            normalized_material_id,
            exc,
        )
        chunk_store = {}
    raw_chunks = (
        chunk_store.get(normalized_material_id, []) if isinstance(chunk_store, dict) else []
    )
    chunks = [chunk for chunk in raw_chunks if isinstance(chunk, Mapping)]
    persisted = _rr.formula_candidates_from_chunks(
        chunks,
        material_id=normalized_material_id,
        limit=200,
    )

    detected = []
    try:
        source_path = _resolve_material_source_path(
            normalized_project_id,
            normalized_material_id,
            repair_missing_reference=False,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        _rr.logger.warning(
            "formula_candidate_source_unavailable project_id=%s material_id=%s err=%s",
            normalized_project_id,
            normalized_material_id,
            exc,
        )
        source_path = None
    if source_path is not None and source_path.suffix.casefold() == ".pdf":
        detected = _rr.extract_pymupdf_formula_candidates(source_path, limit=200)
        detected = _rr.bind_pdf_formula_candidates_to_chunks(detected, chunks)

    candidates = _rr.merge_pdf_formula_candidates(persisted, detected, limit=limit)
    return FormulaCandidatesResponse(
        project_id=normalized_project_id,
        material_id=normalized_material_id,
        candidates=[
            FormulaCandidatePayload(
                candidate_id=candidate.candidate_id,
                page=candidate.page,
                bbox=list(candidate.bbox),
                bbox_unit="normalized_ratio",
                chunk_id=candidate.chunk_id,
                text=candidate.text,
            )
            for candidate in candidates
        ],
    )


@_rr.router.get("/figure-table-candidates", response_model=list[FigureTableCandidatePayload])
async def list_figure_table_candidates(
    project_id: str = Query(..., min_length=1),
    limit: int = Query(_MAX_FIGURE_TABLE_CANDIDATES, ge=1, le=200),
    pixel_only: bool = Query(False, description="Return only chunk records that already include image assets"),
    render_pdf_fallback: bool = Query(True, description="Allow PDF page/crop rendering when chunk assets are missing"),
    query: str | None = Query(None, max_length=4096, description="Optional query used to rank figure/table candidates"),
) -> list[FigureTableCandidatePayload]:
    """List figure/table candidates derived from project chunks.

    The endpoint starts from chunk text, then best-effort resolves PDF page
    layout and renders a preview crop under the project data workspace. When
    layout is unavailable it still returns the textual caption candidate.
    """

    store = _rr._ensure_upload_project(project_id)
    if not store.get_project(project_id):
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    chunk_store = _rr._ensure_project_chunks(project_id)
    return derive_figure_table_candidates(
        project_id,
        chunk_store,
        limit=limit,
        pixel_only=pixel_only,
        render_pdf_fallback=render_pdf_fallback,
        query=query,
    )


def find_chunk_locator(
    chunk_store: dict[str, list[dict[str, Any]]],
    chunk_id: str,
) -> dict[str, Any] | None:
    """Locate a chunk by id inside an already-loaded chunk store.

    Pure read; no chunk store mutation, no persistence call. Returns
    ``None`` when the chunk_id is not present in any material under the
    project, otherwise the locator dict the endpoint serializes.
    """
    if not isinstance(chunk_id, str) or not chunk_id:
        return None
    for material_id, chunks in chunk_store.items():
        if not isinstance(chunks, list):
            continue
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            if chunk.get("chunk_id") != chunk_id:
                continue
            page_value = chunk.get("page")
            page = int(page_value) if isinstance(page_value, int) and page_value >= 1 else None
            chunk_index_value = chunk.get("chunk_index")
            chunk_index = (
                int(chunk_index_value)
                if isinstance(chunk_index_value, int) and chunk_index_value >= 0
                else None
            )
            bbox_anchor = _coerce_declared_bbox_anchor(
                chunk.get("bbox"),
                chunk.get("bbox_unit"),
            )
            return {
                "material_id": material_id,
                "chunk_id": chunk_id,
                "page": page,
                "chunk_index": chunk_index,
                **(
                    {"bbox": bbox_anchor[0], "bbox_unit": bbox_anchor[1].value}
                    if bbox_anchor is not None and page is not None
                    else {}
                ),
            }
    return None


@_rr.router.get("/chunks/{chunk_id}/locator", tags=["Resources"])
async def locate_chunk(
    chunk_id: str,
    project_id: str = Query(..., min_length=1, description="Project that owns the chunk"),
) -> dict[str, Any]:
    """Resolve a chunk_id to {material_id, chunk_id, page, chunk_index}.

    Read-only over the existing chunk store. Returns:
      - 200 with the locator dict on success.
      - 404 when chunk_id is not present in the project chunk store.
      - 422 when project_id is missing or blank (FastAPI Query validation).
    """
    chunk_store = _rr._load_chunk_store(project_id)
    locator = find_chunk_locator(chunk_store, chunk_id)
    if locator is None:
        raise HTTPException(
            status_code=404,
            detail=f"chunk_id 未在项目 chunk store 中找到: {chunk_id}",
        )
    return enrich_chunk_locator_with_pdf(project_id, chunk_store, locator)


@_rr.router.get("/chunks/search-refs", response_model=ChunkSearchRefsResponse, tags=["Resources"])
async def search_chunk_refs(
    request: Request,
    project_id: str = Query(..., min_length=1),
    query: str = Query(..., min_length=1, description="搜索词"),
    top_k: int = Query(10, ge=1, le=50, description="返回最相关的引用数"),
) -> ChunkSearchRefsResponse:
    """Search existing project chunks and return refs without body content.

    Args:
        request: FastAPI request used to reject legacy side-effect flags.
        project_id: Project whose already-indexed chunk store is searched.
        query: Non-empty lexical query.
        top_k: Maximum number of positive-scoring refs returned.

    Returns:
        ``ChunkSearchRefsResponse`` with ref metadata only. The endpoint is
        pure read: it never calls ingestion helpers and rejects flags that
        imply write-through search behavior.
    """

    forbidden = sorted(_SEARCH_REF_FORBIDDEN_QUERY_PARAMS & set(request.query_params.keys()))
    if forbidden:
        raise HTTPException(
            status_code=400,
            detail=f"search-refs 不接受参数: {', '.join(forbidden)}",
        )

    fast_selection = _select_search_ref_chunks_fts_first(
        project_id=project_id,
        query=query,
        top_k=top_k,
    )
    if fast_selection is None:
        chunk_store = _rr._load_chunk_store(project_id)
        all_chunks = _flatten_chunk_store_for_search_refs(chunk_store)
        if _search_refs_visual_query_enabled(query):
            all_chunks = _augment_chunks_with_project_figure_assets(project_id, chunk_store, all_chunks)
            all_chunks = _augment_chunks_with_linked_visual_assets(chunk_store, all_chunks)
        top = _select_search_ref_chunks_via_gateway(
            project_id=project_id,
            chunk_store=chunk_store,
            all_chunks=all_chunks,
            query=query,
            top_k=top_k,
        )
        if top is None:
            top = _select_search_ref_chunks(all_chunks, query, top_k=top_k)
    else:
        chunk_store, all_chunks, top = fast_selection
    if not all_chunks:
        return ChunkSearchRefsResponse(
            project_id=project_id,
            query=query,
            total_refs=0,
            locator_coverage=build_locator_coverage([]),
            refs=[],
        )

    refs = [
        ref
        for score, chunk in top
        if score > 0
        and (
            ref := _chunk_to_search_ref(
                project_id,
                score,
                chunk,
                chunk_store=chunk_store,
                query=query,
            )
        )
        is not None
    ]
    return ChunkSearchRefsResponse(
        project_id=project_id,
        query=query,
        total_refs=len(refs),
        locator_coverage=build_locator_coverage(refs),
        refs=refs,
    )


@_rr.router.get("/chunks/search")
async def search_chunks(
    project_id: str = Query(...),
    query: str = Query(..., min_length=1, description="搜索词"),
    top_k: int = Query(10, ge=1, le=50, description="返回最相关的 N 个chunk"),
    ingest_mode: str = Query("none", description="提问前置入库模式：none/query/full"),
    ingest_limit: int = Query(8, ge=1, le=128, description="query 模式最多入库候选文件数"),
    scan_mode: str = Query("fast", description="入库执行模式：legacy/fast"),
    scan_batch_size: int = Query(24, ge=1, le=256, description="入库批大小"),
    scan_max_workers: int = Query(8, ge=1, le=64, description="入库并发 worker 数"),
) -> dict[str, Any]:
    """Chunk search with optional query-driven pre-ingestion.

    - ingest_mode=none: pure retrieval on existing chunks
    - ingest_mode=query: ingest only query-relevant pending files
    - ingest_mode=full: ingest all pending files before retrieval
    """
    # When called directly (not via FastAPI DI), Query params are descriptor objects
    if hasattr(ingest_mode, "default"):
        ingest_mode = ingest_mode.default
    normalized_ingest_mode = str(ingest_mode or "").strip().lower()
    if normalized_ingest_mode not in _rr._INGEST_MODES:
        raise HTTPException(status_code=400, detail=f"ingest_mode 不支持: {ingest_mode}，可选值: none, query, full")

    ingest_meta: dict[str, Any] = {
        "enabled": normalized_ingest_mode != "none",
        "mode": normalized_ingest_mode,
        "indexed": 0,
        "queued": 0,
        "failed": 0,
        "skipped": 0,
        "workers": 1,
    }

    if normalized_ingest_mode != "none":
        store = _rr._ensure_upload_project(project_id)
        project_obj = _rr.get_writing_resource_store().get_project(project_id)
        source_folder = str((project_obj.metadata.get("source_folder") if project_obj else "") or "").strip()

        if source_folder:
            folder_path = assert_safe_source_folder(Path(source_folder))
            ref = project_obj.metadata.get("source_folder_ref") if project_obj else None
            assert_bound_source_folder(folder_path, ref)
            if folder_path.is_dir():
                candidate_payload = _rr._collect_pending_scan_candidates(project_id, folder_path)
                pending_candidates = list(candidate_payload["pending"])
                pending_total = len(pending_candidates)
                ingest_meta["skipped"] = len(candidate_payload["skipped_results"])
                ingest_meta["failed"] = len(candidate_payload["failed_results"])
                ingest_meta["already_indexed"] = len(candidate_payload.get("existing_fingerprints") or [])

                zotero_title_map = _rr._load_zotero_title_map(folder_path)
                if normalized_ingest_mode == "query":
                    pending_candidates = _rr._select_query_pending_candidates(
                        pending_candidates,
                        query=query,
                        zotero_title_map=zotero_title_map,
                        ingest_limit=ingest_limit,
                    )

                ingest_meta["queued"] = len(pending_candidates)
                _rr.logger.info(
                    "chunks_search_ingest: project_id=%s mode=%s query=%r "
                    "pending_total=%d already_indexed=%d query_selected=%d "
                    "skipped=%d failed=%d source_folder=%s",
                    project_id, normalized_ingest_mode, query[:80],
                    pending_total, ingest_meta["already_indexed"], len(pending_candidates),
                    ingest_meta["skipped"], ingest_meta["failed"], folder_path,
                )
                if pending_candidates:
                    ingest_payload = _rr._ingest_pending_candidates(
                        project_id,
                        store=store,
                        pending_candidates=pending_candidates,
                        zotero_title_map=zotero_title_map,
                        scan_mode=scan_mode,
                        batch_size=scan_batch_size,
                        max_workers=scan_max_workers,
                        existing_titles=candidate_payload["existing_titles"],
                        existing_fingerprints=candidate_payload["existing_fingerprints"],
                    )
                    ingest_meta["indexed"] = int(ingest_payload["indexed"])
                    ingest_meta["failed"] = int(ingest_meta["failed"]) + int(ingest_payload["failed"])
                    ingest_meta["workers"] = int(ingest_payload["workers"])
                    _rr.logger.info(
                        "chunks_search_ingest_done: project_id=%s indexed=%d failed=%d workers=%d",
                        project_id, ingest_meta["indexed"], ingest_meta["failed"], ingest_meta["workers"],
                    )
            else:
                ingest_meta["error"] = f"source_folder 无法访问: {folder_path}"
                _rr.logger.warning(
                    "chunks_search_ingest_skip: project_id=%s reason=source_folder_unreachable path=%s",
                    project_id, folder_path,
                )
        else:
            ingest_meta["error"] = "项目未配置 source_folder，已跳过前置入库"
            _rr.logger.warning(
                "chunks_search_ingest_skip: project_id=%s reason=no_source_folder", project_id,
            )

    chunk_store = _rr._ensure_project_chunks(project_id)
    all_chunks: list[dict[str, Any]] = []
    for chunks in chunk_store.values():
        all_chunks.extend(chunks)

    if not all_chunks:
        return {"project_id": project_id, "query": query, "ingest": ingest_meta, "results": []}

    top = _rr._select_diverse_top_chunks(
        _rr._score_chunks_for_query(all_chunks, query),
        top_k=top_k,
    )
    return {
        "project_id": project_id,
        "query": query,
        "ingest": ingest_meta,
        "results": [{"score": round(s, 2), **c} for s, c in top if s > 0],
    }


# =========================================================================
# Document File Serving
# =========================================================================

@_rr.router.get("/document/{material_id}/file", tags=["Resources"])
async def serve_document_file(material_id: str, as_: str = Query("", alias="as")):
    """Serve the original file for a material (e.g. PDF for in-app viewing).

    ``?as=bin`` returns the bytes with media_type=application/octet-stream so
    browser download-manager extensions (IDM, FlashGet, 迅雷, etc.) don't
    recognise it as a PDF and divert the in-app reader's fetch into a save
    dialog. Used by the in-app PDF viewer; everything else (default) keeps
    the natural MIME so e.g. right-click "open in new tab" still works.

    ``?as=raw1`` (0.1.8.4 hardening): newer download-manager extensions are
    now aggressive enough to swallow even ``application/octet-stream`` GETs
    on large bodies, returning a synthetic ``204 No Content`` to the JS
    fetch. We hand back a fully private vendor MIME
    (``application/vnd.litassist.encoded``) plus ``X-Content-Type-Options:
    nosniff`` so extensions can't sniff PDF magic bytes either. The PDF
    bytes themselves are unchanged — pdf.js parses the body normally.
    """
    store = _rr.get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        _rr.logger.warning(
            "serve_document_file: material_not_found material_id=%s", material_id
        )
        raise HTTPException(status_code=404, detail=f"素材不存在: {material_id}")

    project_id = material.project_id
    doc_store = _rr._load_doc_store(project_id)
    doc_entry = doc_store.get(material_id, {})
    source_relative = doc_entry.get("source_relative_path", "")

    candidate = _resolve_material_source_path(project_id, material_id)
    if candidate is None:
        if not source_relative:
            _rr.logger.warning(
                "serve_document_file: no_source_path material_id=%s project_id=%s",
                material_id, project_id,
            )
            raise HTTPException(status_code=404, detail="未找到原始文件，请重新导入或从知识库补充文件路径")
        _rr.logger.warning(
            "serve_document_file: file_missing material_id=%s project_id=%s "
            "source_relative=%s",
            material_id, project_id, source_relative,
        )
        raise HTTPException(status_code=404, detail=f"文件不存在: {Path(source_relative).name}")

    from fastapi.responses import FileResponse

    media_types = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }
    ext = candidate.suffix.lower()
    # 0.1.8.4: vendor MIME for the in-app reader hardened path. Download
    # managers can't sniff it as PDF; pdf.js doesn't care about the
    # response Content-Type — it parses the body bytes directly.
    flag = as_.strip().lower()
    if flag == "raw1":
        media_type = "application/vnd.litassist.encoded"
    elif flag == "bin":
        # 0.1.8.1: legacy disguise — kept for back-compat with older
        # bundled installers that still send ?as=bin.
        media_type = "application/octet-stream"
    else:
        media_type = media_types.get(ext, "application/octet-stream")
    response = FileResponse(path=str(candidate), media_type=media_type)
    safe_name = candidate.name.encode("utf-8").decode("latin-1", errors="ignore")
    response.headers["Content-Disposition"] = f'inline; filename="{safe_name}"'
    if flag in ("raw1", "bin"):
        # Belt-and-suspenders: stop the browser (and well-behaved
        # extensions) from sniffing PDF magic bytes; force no-store so a
        # cached 204 from a prior interception can't poison a retry.
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
    return response


@_rr.router.get("/document/{material_id}/file_b64", tags=["Resources"])
async def serve_document_file_base64(material_id: str) -> dict[str, Any]:
    """Return small original files as base64 inside a JSON envelope.

    Why:
        This compatibility endpoint is memory-expensive because base64 in JSON
        expands payloads and requires whole-file reads. Large PDFs should use
        ``/file`` so Starlette can stream bytes and honor range requests.
    """
    store = _rr.get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        _rr.logger.warning(
            "serve_document_file_base64: material_not_found material_id=%s", material_id,
        )
        raise HTTPException(status_code=404, detail=f"素材不存在: {material_id}")

    project_id = material.project_id
    doc_store = _rr._load_doc_store(project_id)
    doc_entry = doc_store.get(material_id, {})
    source_relative = doc_entry.get("source_relative_path", "")

    target = _resolve_material_source_path(project_id, material_id)
    if target is None:
        if not source_relative:
            raise HTTPException(status_code=404, detail="未找到原始文件，请重新导入或从知识库补充文件路径")
        raise HTTPException(status_code=404, detail=f"文件不存在: {Path(source_relative).name}")

    max_b64_bytes = 8 * 1024 * 1024
    file_size = target.stat().st_size
    if file_size > max_b64_bytes:
        raise HTTPException(
            status_code=413,
            detail="文件过大，请使用 /file 流式端点读取。",
        )

    import base64
    raw = target.read_bytes()
    ext_l = target.suffix.lower()
    mime = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }.get(ext_l, "application/octet-stream")
    return {
        "data": base64.b64encode(raw).decode("ascii"),
        "size": len(raw),
        "mime": mime,
        "name": target.name,
    }
