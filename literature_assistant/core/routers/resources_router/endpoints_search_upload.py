# -*- coding: utf-8 -*-
"""Upload / search / document-serving endpoints split out of resources_router.__init__.

All references to module-level helpers go through ``_rr.X`` (absolute import
of the package) so that pytest ``monkeypatch.setattr(rr, "X", ...)`` keeps
affecting the live endpoint behaviour.
"""

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Query, UploadFile, File, Form

from models import (
    FigureTableCandidatePayload,
    PdfBboxUnit,
    coerce_pdf_bbox,
    pdf_bbox_matches_unit,
)

import routers.resources_router as _rr


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
_CROPPED_IMAGE_SUFFIX = ".png"
_FIGURE_ASSET_FILE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_CHUNK_ASSET_KEY_SOURCES: dict[str, str] = {
    "asset_path": "chunk_asset",
    "image_path": "chunk_image",
    "raw_image_path": "chunk_raw_image",
    "page_crop_path": "chunk_page_crop",
    "figure_asset_path": "chunk_figure_asset",
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

    store = _rr._ensure_upload_project(project_id)
    results: list[dict[str, Any]] = []
    total_chunks = 0
    successful_files = 0
    failed_files = 0
    duplicate_files = 0
    queued_files = 0

    for upload in files:
        filename = upload.filename or "unnamed"
        try:
            result = await _rr._ingest_uploaded_document(project_id, upload, store=store)
            if result.get("status") == "duplicate":
                duplicate_files += 1
            elif result.get("status") == "queued":
                queued_files += 1
                successful_files += 1
            else:
                total_chunks += int(result.get("chunks") or 0)
                successful_files += 1
            results.append(result)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            failed_files += 1
            results.append({
                "title": filename,
                "status": "error",
                "error": str(exc),
            })

    return {
        "project_id": project_id,
        "total_files": len(files),
        "successful_files": successful_files,
        "duplicate_files": duplicate_files,
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
    for nested_key in _CHUNK_NESTED_ASSET_KEYS:
        nested = chunk.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key, source in _CHUNK_ASSET_KEY_SOURCES.items():
            value = _normalize_candidate_text(nested.get(key), max_chars=260)
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
        return relative_path if relative_path in existing_project_asset_paths else None

    try:
        candidate_path = project_data_path(normalized_project_id, relative_path)
        if candidate_path.is_file():
            return relative_path
    except (OSError, RuntimeError, ValueError):
        return None
    return None


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
            clip_rect = _page_crop_target_rect(page, bbox)
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
        doc_store = _rr._load_doc_store(project_id)
        record = doc_store.get(material_id)
        if not isinstance(record, dict):
            record = {}
        if str(record.get("source_relative_path") or "").strip():
            return
        record["source_relative_path"] = normalized
        doc_store[material_id] = record
        _rr._save_doc_store(project_id, doc_store)
    except (OSError, TypeError, ValueError) as exc:
        _rr.logger.warning(
            "source_reference_repair_failed project_id=%s material_id=%s err=%s",
            project_id,
            material_id,
            exc,
        )


def _resolve_material_source_path(project_id: str, material_id: str) -> Path | None:
    """Resolve the original source file for a material from trusted project roots."""

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
                if not str(doc_entry.get("source_relative_path") or "").strip():
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
    existing_bbox = _coerce_pdf_anchor_bbox(locator.get("bbox"))
    normalized_locator = locator
    if existing_bbox is not None and locator.get("bbox_unit") != PdfBboxUnit.NORMALIZED_RATIO.value:
        normalized_locator = dict(locator)
        normalized_locator["bbox"] = existing_bbox
        normalized_locator["bbox_unit"] = PdfBboxUnit.NORMALIZED_RATIO.value
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
    if existing_page is None and _coerce_positive_int(cached.get("page")) is not None:
        enriched["page"] = int(cached["page"])
    if existing_bbox is None and (bbox := _coerce_pdf_anchor_bbox(cached.get("bbox"))) is not None:
        enriched["bbox"] = bbox
        enriched["bbox_unit"] = PdfBboxUnit.NORMALIZED_RATIO.value
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
            bbox=_coerce_bbox(chunk.get("bbox")) if isinstance(chunk, dict) else None,
            asset_path=parsed["relative_path"],
            source="project_figure_asset",
        )
        rows.append((material_id, chunk_index_value if chunk_index_value is not None else 10**9, label, parsed["relative_path"], payload))

    rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return [payload for *_prefix, payload in rows[:limit]]


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
    existing_asset_path: str | None,
    existing_asset_source: str = "chunk_asset",
    render_pdf_fallback: bool = True,
) -> tuple[int | None, list[float] | None, str | None, str]:
    """Return page, bbox, asset path, and source label for a candidate row."""

    page = existing_page
    bbox = existing_bbox
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
                **({"bbox": bbox} if bbox is not None else {}),
            },
        )
        page = _coerce_positive_int(locator.get("page")) or page
        bbox = _coerce_bbox(locator.get("bbox")) or bbox

    if asset_path:
        return page, bbox, asset_path, source

    if not render_pdf_fallback:
        return page, bbox, asset_path, source

    source_path = _resolve_material_source_path(project_id, material_id)
    if source_path is None or source_path.suffix.lower() != ".pdf" or page is None:
        return page, bbox, asset_path, source

    from project_paths import project_data_path

    relative_path = _candidate_crop_path(project_id, material_id, chunk_id, label)
    output_path = project_data_path(project_id, relative_path)
    if output_path.is_file():
        return page, bbox, relative_path, "pdf_crop"

    rendered_path = _render_pdf_crop(source_path, page, bbox, output_path)
    if rendered_path:
        source = "pdf_crop"
        asset_path = relative_path
    return page, bbox, asset_path, source


def derive_figure_table_candidates(
    project_id: str,
    chunk_store: dict[str, list[dict[str, Any]]],
    *,
    limit: int = _MAX_FIGURE_TABLE_CANDIDATES,
    pixel_only: bool = False,
    render_pdf_fallback: bool = True,
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

    candidates: list[FigureTableCandidatePayload] = (
        _derive_project_figure_asset_candidates(
            normalized_project_id,
            chunk_store,
            limit=limit,
        )
        if pixel_only
        else []
    )
    if len(candidates) >= limit:
        return candidates[:limit]
    seen: set[tuple[str, str, str]] = {
        (candidate.kind, candidate.material_id, candidate.label.lower())
        for candidate in candidates
    }
    existing_project_asset_paths = (
        set()
        if pixel_only
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
                seen.add(dedupe_key)
                page = _coerce_positive_int(chunk.get("page"))
                bbox = _coerce_bbox(chunk.get("bbox"))
                asset_reference = _candidate_asset_reference(chunk)
                asset_path = asset_reference[0] if asset_reference is not None else None
                asset_source = asset_reference[1] if asset_reference is not None else "chunk_text"
                if not asset_path and not pixel_only:
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
                page, bbox, asset_path, source = _enrich_candidate_layout(
                    project_id=normalized_project_id,
                    material_id=str(material_id),
                    chunk_id=chunk_id,
                    chunk_store=chunk_store,
                    chunk=chunk,
                    label=label,
                    existing_page=page,
                    existing_bbox=bbox,
                    existing_asset_path=asset_path,
                    existing_asset_source=asset_source,
                    render_pdf_fallback=render_pdf_fallback and not pixel_only,
                )
                if pixel_only and (not asset_path or source == "pdf_crop"):
                    continue
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
                        asset_path=asset_path,
                        source=source,
                    )
                )
                if len(candidates) >= limit:
                    return candidates
    return candidates


@_rr.router.get("/figure-table-candidates", response_model=list[FigureTableCandidatePayload])
async def list_figure_table_candidates(
    project_id: str = Query(..., min_length=1),
    limit: int = Query(_MAX_FIGURE_TABLE_CANDIDATES, ge=1, le=200),
    pixel_only: bool = Query(False, description="Return only chunk records that already include image assets"),
    render_pdf_fallback: bool = Query(True, description="Allow PDF page/crop rendering when chunk assets are missing"),
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
            return {
                "material_id": material_id,
                "chunk_id": chunk_id,
                "page": page,
                "chunk_index": chunk_index,
                **(
                    {"bbox": bbox, "bbox_unit": PdfBboxUnit.NORMALIZED_RATIO.value}
                    if (bbox := _coerce_pdf_anchor_bbox(chunk.get("bbox"))) is not None
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
            folder_path = Path(source_folder).expanduser().resolve()
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
