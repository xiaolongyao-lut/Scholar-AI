# -*- coding: utf-8 -*-
"""Pure document-content extraction helpers."""

from __future__ import annotations

import json
import logging
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

try:
    from pdf_backends import (
        StructuredBlock,
        get_pdf_backend,
    )
    from pdf_backends.ocr_ingestion import apply_pdf_ocr_if_needed
    from pdf_backends.pymupdf_backend import PyMuPDFBackend
except ImportError:  # pragma: no cover — only triggered in misconfigured envs
    StructuredBlock = None  # type: ignore[assignment]
    get_pdf_backend = None  # type: ignore[assignment]
    apply_pdf_ocr_if_needed = None  # type: ignore[assignment]
    PyMuPDFBackend = None  # type: ignore[assignment]


__all__ = [
    "_extract_document_content",
    "_extract_document_content_from_path",
    "_extract_document_payload_from_path",
    "_truncate_document_content",
    "ExtractedDocumentPayload",
]


_LOGGER = logging.getLogger("DocumentExtraction")
_PDF_VISUAL_MIN_WIDTH = 96.0
_PDF_VISUAL_MIN_HEIGHT = 72.0
_PDF_VISUAL_MIN_AREA_RATIO = 0.01
_BROWSER_SAFE_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
_IMAGE_EXTENSION_ALIASES = {"jpe": "jpg", "jfif": "jpg"}
_PDF_CAPTION_RE = re.compile(
    r"^\s*(?:图|圖|表|fig(?:ure)?\.?|table)\s*[A-Za-z]?\d+(?:[.\-–—]\d+)*[A-Za-z]?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractedDocumentPayload:
    """Structured result of document extraction.

    Default PyMuPDF path returns ``ExtractedDocumentPayload(content=text)``
    with ``blocks`` and ``markdown_full`` both None — same caller-visible
    information as the legacy ``_extract_document_content_from_path``
    return value (a plain string).

    Optional external parser paths may add ``blocks`` (structured PDF blocks)
    and ``markdown_full`` (full-document markdown for sidecar writing). Upload
    layer routes these to the chunker (`blocks=`) and the sidecar writer.
    """

    content: str
    blocks: list[StructuredBlock] | None = None  # type: ignore[valid-type]
    markdown_full: str | None = None
    ocr_report: object | None = None


@dataclass(frozen=True)
class _PdfVisualImage:
    """Internal image block used to bind embedded PDF pixels to captions."""

    page: int
    bbox: list[float]
    path: str
    center_y: float


@dataclass(frozen=True)
class _BrowserImageAsset:
    """Browser-displayable bytes and extension for an extracted PDF image."""

    data: bytes
    extension: str


def _safe_asset_segment(value: str) -> str:
    """Return a path segment suitable for project-local extracted assets."""

    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return normalized.strip("._")[:80] or "document"


def _normalize_image_extension(value: Any) -> str:
    """Return a lowercase extension token without a leading dot."""

    ext = str(value or "").lower().strip().lstrip(".")
    return _IMAGE_EXTENSION_ALIASES.get(ext, ext)


def _convert_image_bytes_to_png(image_bytes: bytes) -> bytes | None:
    """Transcode arbitrary embedded image bytes to PNG for browser preview."""

    if not image_bytes:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.mode not in {"RGB", "RGBA", "L"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        _LOGGER.warning("pdf_visual_image_transcode_failed err=%s", exc)
        return None


def _browser_image_asset(image_bytes: bytes | bytearray, raw_ext: Any) -> _BrowserImageAsset | None:
    """Return browser-safe image bytes for a PyMuPDF image block.

    Args:
        image_bytes: Raw embedded PDF image bytes.
        raw_ext: Format token reported by PyMuPDF.

    Returns:
        Browser-displayable bytes plus an extension, or ``None`` when the image
        cannot be converted without producing a broken preview link.
    """

    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        return None
    image_data = bytes(image_bytes)
    ext = _normalize_image_extension(raw_ext)
    if ext in _BROWSER_SAFE_IMAGE_EXTENSIONS:
        return _BrowserImageAsset(data=image_data, extension=ext)
    converted = _convert_image_bytes_to_png(image_data)
    if converted is None:
        _LOGGER.warning("pdf_visual_image_unsupported_format ext=%s", ext or "<empty>")
        return None
    return _BrowserImageAsset(data=converted, extension="png")


def _normalized_bbox(rect: Any, page_rect: Any) -> list[float] | None:
    """Convert a PyMuPDF rectangle to normalized [x, y, width, height]."""

    try:
        page_width = float(getattr(page_rect, "width", 0.0) or 0.0)
        page_height = float(getattr(page_rect, "height", 0.0) or 0.0)
        if page_width <= 0.0 or page_height <= 0.0:
            return None
        x0 = max(0.0, float(rect[0])) / page_width
        y0 = max(0.0, float(rect[1])) / page_height
        x1 = min(page_width, float(rect[2])) / page_width
        y1 = min(page_height, float(rect[3])) / page_height
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
    except (TypeError, ValueError, AttributeError, IndexError):
        return None
    if width <= 0.0 or height <= 0.0:
        return None
    return [round(x0, 6), round(y0, 6), round(width, 6), round(height, 6)]


def _text_from_pymupdf_block(block: dict[str, Any]) -> str:
    """Extract readable text from a PyMuPDF dict text block."""

    lines: list[str] = []
    raw_lines = block.get("lines")
    if not isinstance(raw_lines, list):
        return ""
    for line in raw_lines:
        if not isinstance(line, dict):
            continue
        spans = line.get("spans")
        if not isinstance(spans, list):
            continue
        line_text = "".join(str(span.get("text") or "") for span in spans if isinstance(span, dict)).strip()
        if line_text:
            lines.append(line_text)
    return "\n".join(lines).strip()


def _is_plausible_visual_block(bbox: list[float], page_rect: Any) -> bool:
    """Filter icons, logos, and separators that should not become evidence."""

    try:
        page_width = float(getattr(page_rect, "width", 0.0) or 0.0)
        page_height = float(getattr(page_rect, "height", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    if page_width <= 0.0 or page_height <= 0.0:
        return False
    width_px = bbox[2] * page_width
    height_px = bbox[3] * page_height
    if width_px < _PDF_VISUAL_MIN_WIDTH or height_px < _PDF_VISUAL_MIN_HEIGHT:
        return False
    return bbox[2] * bbox[3] >= _PDF_VISUAL_MIN_AREA_RATIO


def _nearest_visual_for_caption(
    caption_bbox: list[float] | None,
    page_images: list[_PdfVisualImage],
) -> _PdfVisualImage | None:
    """Return the nearest adjacent image block above or below a caption."""

    if caption_bbox is None or not page_images:
        return None
    caption_left = caption_bbox[0]
    caption_top = caption_bbox[1]
    caption_right = caption_bbox[0] + caption_bbox[2]
    caption_bottom = caption_bbox[1] + caption_bbox[3]
    caption_center_x = caption_bbox[0] + caption_bbox[2] / 2.0
    max_vertical_gap = 0.075
    min_horizontal_overlap = 0.25
    best: tuple[float, _PdfVisualImage] | None = None
    for image in page_images:
        image_left = image.bbox[0]
        image_top = image.bbox[1]
        image_right = image.bbox[0] + image.bbox[2]
        image_bottom = image.bbox[1] + image.bbox[3]
        overlap = max(0.0, min(caption_right, image_right) - max(caption_left, image_left))
        narrow_width = max(0.0001, min(caption_bbox[2], image.bbox[2]))
        horizontal_overlap = overlap / narrow_width
        if horizontal_overlap < min_horizontal_overlap:
            continue
        if caption_bottom <= image_top:
            vertical_gap = image_top - caption_bottom
        elif image_bottom <= caption_top:
            vertical_gap = caption_top - image_bottom
        else:
            vertical_gap = 0.0
        if vertical_gap > max_vertical_gap:
            continue
        image_center_x = image.bbox[0] + image.bbox[2] / 2.0
        horizontal_distance = abs(caption_center_x - image_center_x)
        score = vertical_gap * 4.0 + horizontal_distance
        if best is None or score < best[0]:
            best = (score, image)
    return best[1] if best is not None else None


def _extract_pymupdf_visual_blocks(
    filename: str,
    source_path: Path,
    *,
    project_id: str | None = None,
    project_data_root: Path | None = None,
) -> list[StructuredBlock] | None:  # type: ignore[valid-type]
    """Extract text blocks and real embedded image assets from a PDF.

    Args:
        filename: Display filename used to build stable project asset paths.
        source_path: Existing PDF path.
        project_id: Project id whose data root owns extracted image files.
        project_data_root: Test hook or pre-resolved project data directory.

    Returns:
        Structured blocks when PyMuPDF can parse the PDF, otherwise ``None``.
        Image paths are project-relative and point to extracted embedded image
        bytes, never full-page preview screenshots.
    """

    if StructuredBlock is None:
        return None
    if not isinstance(source_path, Path) or not source_path.is_file():
        raise ValueError("source_path must be an existing file")
    if project_data_root is None and not str(project_id or "").strip():
        return None

    try:
        import pymupdf
    except ImportError:
        return None

    if project_data_root is None:
        try:
            from project_paths import project_data_path

            project_data_root = project_data_path(str(project_id))
        except (OSError, RuntimeError, ValueError) as exc:
            _LOGGER.warning("pdf_visual_asset_root_unavailable filename=%s err=%s", filename, exc)
            return None

    source_digest = hashlib.sha1(str(source_path.resolve()).encode("utf-8")).hexdigest()[:12]
    doc_segment = _safe_asset_segment(Path(filename).stem)
    relative_dir = Path("figure_assets") / "extracted" / f"{doc_segment}-{source_digest}"
    blocks: list[StructuredBlock] = []

    try:
        with pymupdf.open(str(source_path)) as doc:
            for page_index, page in enumerate(doc, start=1):
                page_dict = page.get_text("dict", sort=True)
                raw_blocks = page_dict.get("blocks") if isinstance(page_dict, dict) else None
                if not isinstance(raw_blocks, list):
                    continue

                page_images: list[_PdfVisualImage] = []
                text_candidates: list[tuple[dict[str, Any], str, list[float] | None]] = []
                image_index = 0

                for raw_block in raw_blocks:
                    if not isinstance(raw_block, dict):
                        continue
                    block_type = raw_block.get("type")
                    bbox = _normalized_bbox(raw_block.get("bbox"), page.rect)
                    if block_type == 1 and bbox is not None and _is_plausible_visual_block(bbox, page.rect):
                        image_bytes = raw_block.get("image")
                        asset = _browser_image_asset(image_bytes, raw_block.get("ext"))
                        if asset is None:
                            continue
                        image_index += 1
                        relative_path = (
                            relative_dir / f"p{page_index:04d}_img{image_index:03d}.{asset.extension}"
                        ).as_posix()
                        output_path = project_data_root / relative_path
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        if not output_path.exists():
                            output_path.write_bytes(asset.data)
                        page_images.append(
                            _PdfVisualImage(
                                page=page_index,
                                bbox=bbox,
                                path=relative_path,
                                center_y=bbox[1] + bbox[3] / 2.0,
                            )
                        )
                        continue

                    if block_type == 0:
                        text = _text_from_pymupdf_block(raw_block)
                        if text:
                            text_candidates.append((raw_block, text, bbox))

                for text_index, (_raw_block, text, bbox) in enumerate(text_candidates, start=1):
                    caption_match = _PDF_CAPTION_RE.search(text)
                    nearest = _nearest_visual_for_caption(bbox, page_images) if caption_match else None
                    blocks.append(
                        StructuredBlock(
                            block_id=f"p{page_index}_t{text_index}",
                            page=page_index,
                            bbox=nearest.bbox if nearest is not None else bbox,
                            block_type="FigureCaption" if nearest is not None else "Text",
                            markdown=text,
                            image_paths=[nearest.path] if nearest is not None else [],
                        )
                    )

                caption_paths = {
                    image.path
                    for _raw_block, text, bbox in text_candidates
                    for image in [_nearest_visual_for_caption(bbox, page_images) if _PDF_CAPTION_RE.search(text) else None]
                    if image is not None
                }
                for image_index, image in enumerate(page_images, start=1):
                    if image.path in caption_paths:
                        continue
                    blocks.append(
                        StructuredBlock(
                            block_id=f"p{page_index}_i{image_index}",
                            page=page_index,
                            bbox=image.bbox,
                            block_type="Image",
                            markdown=f"Image on page {page_index}",
                            image_paths=[image.path],
                        )
                    )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        _LOGGER.warning("pdf_visual_blocks_failed filename=%s err=%s", filename, exc)
        return None

    return blocks or None


def _extract_document_content(filename: str, raw: bytes) -> str:
    """Extract textual content from an uploaded document based on file type."""
    content = ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "txt" or ext == "md":
        for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                content = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
    elif ext == "bib":
        for enc in ("utf-8", "latin-1"):
            try:
                content = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
    elif ext == "ipynb":
        try:
            notebook = json.loads(raw.decode("utf-8"))
            cells = notebook.get("cells", []) if isinstance(notebook, dict) else []
            parts: list[str] = []

            for idx, cell in enumerate(cells, start=1):
                if not isinstance(cell, dict):
                    continue
                cell_type = str(cell.get("cell_type") or "").strip().lower()
                source = cell.get("source")
                if isinstance(source, list):
                    source_text = "".join(str(x) for x in source)
                else:
                    source_text = str(source or "")
                source_text = source_text.strip()
                if not source_text:
                    continue

                if cell_type == "markdown":
                    parts.append(f"[Notebook Markdown Cell {idx}]\n{source_text}")
                elif cell_type == "code":
                    code_lines = [ln for ln in source_text.splitlines() if ln.strip()][:80]
                    code_excerpt = "\n".join(code_lines)
                    if code_excerpt:
                        parts.append(f"[Notebook Code Cell {idx}]\n{code_excerpt}")

                    outputs = cell.get("outputs", [])
                    if isinstance(outputs, list):
                        output_snippets: list[str] = []
                        for output in outputs:
                            if not isinstance(output, dict):
                                continue
                            # stream output
                            if output.get("output_type") == "stream":
                                text = output.get("text")
                                if isinstance(text, list):
                                    text = "".join(str(x) for x in text)
                                text = str(text or "").strip()
                                if text:
                                    output_snippets.append(text)

                            # execute_result / display_data plain text
                            data = output.get("data")
                            if isinstance(data, dict):
                                plain = data.get("text/plain")
                                if isinstance(plain, list):
                                    plain = "".join(str(x) for x in plain)
                                plain = str(plain or "").strip()
                                if plain:
                                    output_snippets.append(plain)

                        if output_snippets:
                            merged_outputs = "\n".join(output_snippets[:20])
                            parts.append(f"[Notebook Output Cell {idx}]\n{merged_outputs}")

            content = "\n\n".join(parts)
            if not content.strip():
                content = f"[Notebook 文件: {filename}，未提取到可索引内容]"
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            content = f"[Notebook 解析失败: {exc}]"
    elif ext == "pdf":
        try:
            import io
            try:
                import pymupdf  # PyMuPDF (fitz)
                doc = pymupdf.open(stream=raw, filetype="pdf")
                pages = []
                for page in doc:
                    pages.append(page.get_text())
                content = "\n\n".join(pages)
                doc.close()
            except ImportError:
                try:
                    from PyPDF2 import PdfReader
                    reader = PdfReader(io.BytesIO(raw))
                    pages = [page.extract_text() or "" for page in reader.pages]
                    content = "\n\n".join(pages)
                except ImportError:
                    content = f"[PDF 文件: {filename}，需安装 pymupdf 或 PyPDF2 才能提取文本]"
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            content = f"[PDF 解析失败: {exc}]"
    elif ext in ("docx",):
        try:
            import io
            from docx import Document as DocxDocument
            doc = DocxDocument(io.BytesIO(raw))
            content = "\n".join(para.text for para in doc.paragraphs if para.text.strip())
        except ImportError:
            content = f"[DOCX 文件: {filename}，需安装 python-docx 才能提取文本]"
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            content = f"[DOCX 解析失败: {exc}]"
    else:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = f"[未知格式文件: {filename}]"

    return content


def _extract_document_payload_from_path(
    filename: str,
    source_path: Path,
    *,
    project_id: str | None = None,
    project_data_root: Path | None = None,
) -> ExtractedDocumentPayload:
    """Extract content + optional structured blocks + optional markdown_full.

    Replaces the legacy content-only return with a structured payload. For
    PDFs, the core backend is PyMuPDF (see ``pdf_backends.get_pdf_backend``):

      - ``PyMuPDFBackend`` — byte-level identical to legacy behavior;
        ``blocks`` and ``markdown_full`` are always None.

    Non-PDF formats (DOCX, plaintext, etc.) go through the legacy text-only
    paths; ``blocks`` / ``markdown_full`` are None for those.

    Args:
        filename: Display filename used to choose parser behavior.
        source_path: Existing local file path containing the uploaded bytes.

    Returns:
        ``ExtractedDocumentPayload`` — never raises for the PDF/DOCX branches
        (placeholders are returned as content instead).

    Raises:
        TypeError / ValueError: If ``source_path`` is not a Path / not a file.
    """

    if not isinstance(source_path, Path):
        raise TypeError("source_path must be a pathlib.Path")
    if not source_path.is_file():
        raise ValueError(f"source_path is not a file: {source_path}")

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # PDF: route through backend abstraction
    if ext == "pdf" and get_pdf_backend is not None:
        backend = get_pdf_backend()
        try:
            text, blocks, markdown_full = backend.parse(source_path)
            if blocks is None and isinstance(backend, PyMuPDFBackend):
                blocks = _extract_pymupdf_visual_blocks(
                    filename,
                    source_path,
                    project_id=project_id,
                    project_data_root=project_data_root,
                )
            payload = ExtractedDocumentPayload(
                content=text,
                blocks=blocks,
                markdown_full=markdown_full,
            )
            if apply_pdf_ocr_if_needed is None:
                return payload
            return cast(ExtractedDocumentPayload, apply_pdf_ocr_if_needed(filename, source_path, payload))
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            _LOGGER.warning(
                "PDF backend %r failed parsing %s: %s; "
                "falling back to PyMuPDF",
                getattr(backend, "name", "?"),
                filename,
                exc,
            )
            if PyMuPDFBackend is not None and not isinstance(
                backend, PyMuPDFBackend  # avoid re-entering same failing backend
            ):
                fallback_text, _, _ = PyMuPDFBackend().parse(source_path)
                return ExtractedDocumentPayload(content=fallback_text)
            return ExtractedDocumentPayload(content=f"[PDF 解析失败: {exc}]")

    # DOCX: legacy path, no structured output
    if ext == "docx":
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(str(source_path))
            text = "\n".join(para.text for para in doc.paragraphs if para.text.strip())
            return ExtractedDocumentPayload(content=text)
        except ImportError:
            return ExtractedDocumentPayload(
                content=f"[DOCX 文件: {filename}，需安装 python-docx 才能提取文本]"
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return ExtractedDocumentPayload(content=f"[DOCX 解析失败: {exc}]")

    # Other formats: delegate to byte-based helper
    return ExtractedDocumentPayload(
        content=_extract_document_content(filename, source_path.read_bytes())
    )


def _extract_document_content_from_path(filename: str, source_path: Path) -> str:
    """Extract textual content from a bounded local source file.

    LEGACY SIGNATURE — kept verbatim for all existing callers. New code
    should use ``_extract_document_payload_from_path`` to access the
    structured blocks and markdown_full produced by optional external parsers.

    Args:
        filename: Display filename used to choose parser behavior.
        source_path: Existing local file path containing the uploaded bytes.

    Returns:
        Extracted text or the same user-facing parser placeholder strings used
        by the byte-based compatibility helper.

    Raises:
        ValueError: If ``source_path`` is not an existing file.
    """

    return _extract_document_payload_from_path(filename, source_path).content


def _truncate_document_content(content: str) -> str:
    """Limit oversized extracted text so upload responses stay stable."""
    max_content_len = 200_000
    if len(content) <= max_content_len:
        return content
    return content[:max_content_len] + f"\n\n[...文档内容已截断，总长度 {len(content)} 字符]"
