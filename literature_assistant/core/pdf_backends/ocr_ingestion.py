# -*- coding: utf-8 -*-
"""OCR post-processing for PDF ingestion payloads."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from .ocr_classifier import OCRNeedClassifier, PDFClassificationResult
from .ocr_engine_registry import resolve_ocr_runtime_config, select_ocr_engine


__all__ = [
    "OcrIngestionReport",
    "apply_pdf_ocr_if_needed",
]


_LOGGER = logging.getLogger("OcrIngestion")


@dataclass(frozen=True)
class OcrIngestionReport:
    """Observable OCR decision attached to an extraction payload.

    Args:
        strategy: Classifier strategy: text_only, ocr_only, hybrid, or unknown.
        candidate_pages: Zero-based page indexes requiring OCR.
        applied_pages: Zero-based page indexes that produced OCR text.
        warning: User-visible bounded warning when OCR was skipped or failed.
    """

    strategy: str
    candidate_pages: list[int]
    applied_pages: list[int]
    warning: str | None = None


RenderPageFn = Callable[[Path, int], bytes]


class ExtractionPayloadLike(Protocol):
    """Minimal payload shape accepted by the OCR post-processor."""

    content: str
    blocks: Any
    markdown_full: str | None


def apply_pdf_ocr_if_needed(
    filename: str,
    source_path: Path,
    payload: ExtractionPayloadLike,
    *,
    classifier: OCRNeedClassifier | None = None,
    render_page: RenderPageFn | None = None,
) -> ExtractionPayloadLike:
    """Merge OCR text into a PDF extraction payload when pages need it.

    Args:
        filename: Display filename used in visible diagnostics.
        source_path: Existing local PDF file path.
        payload: Current parser payload; content and structured fields are
            preserved and OCR text is appended only when required.
        classifier: Optional classifier override for deterministic tests.
        render_page: Optional page renderer override for deterministic tests.

    Returns:
        New payload when OCR text or warning was appended; otherwise the input
        payload unchanged.

    Raises:
        TypeError / ValueError: For invalid input shapes.
    """

    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("filename must be a non-empty string")
    if not isinstance(source_path, Path):
        raise TypeError("source_path must be a pathlib.Path")
    if not source_path.is_file():
        raise ValueError(f"source_path is not a file: {source_path}")
    if not hasattr(payload, "content") or not isinstance(payload.content, str):
        raise TypeError("payload must expose string content")

    pdf_classifier = classifier or OCRNeedClassifier()
    try:
        classification = pdf_classifier.classify_pdf(source_path)
    except Exception as exc:  # noqa: BLE001 - OCR is optional post-processing
        _LOGGER.warning("ocr_classification_failed file=%s err=%s", filename, exc)
        return payload

    candidate_pages = _candidate_ocr_pages(classification)
    if not candidate_pages:
        return _copy_payload_with_ocr_report(
            payload,
            OcrIngestionReport(
                strategy=classification.strategy,
                candidate_pages=[],
                applied_pages=[],
            ),
        )

    runtime_config = resolve_ocr_runtime_config()
    engine, warning = select_ocr_engine(runtime_config)
    if engine is None:
        visible_warning = _format_ocr_warning(filename, classification, candidate_pages, warning)
        return _copy_payload_with_content_and_report(
            payload,
            _append_section(payload.content, visible_warning),
            OcrIngestionReport(
                strategy=classification.strategy,
                candidate_pages=candidate_pages,
                applied_pages=[],
                warning=warning,
            ),
        )

    renderer = render_page or _render_pdf_page_png
    ocr_sections: list[str] = []
    applied_pages: list[int] = []
    failed_pages: list[str] = []
    for page_index in candidate_pages:
        try:
            image = renderer(source_path, page_index)
            page_text = engine.ocr_image(image, language=runtime_config.language).strip()
        except Exception as exc:  # noqa: BLE001 - per-page failure must not block ingest
            failed_pages.append(f"page {page_index + 1}: {exc}")
            continue
        if page_text:
            applied_pages.append(page_index)
            ocr_sections.append(f"[OCR Page {page_index + 1}]\n{page_text}")

    warning_text = None
    if failed_pages:
        warning_text = "; ".join(failed_pages[:5])
    if not ocr_sections and warning_text is None:
        warning_text = "OCR engine returned no text"

    merged = payload.content
    if ocr_sections:
        merged = _append_section(merged, "[OCR Extracted Text]\n" + "\n\n".join(ocr_sections))
    if warning_text:
        merged = _append_section(
            merged,
            _format_ocr_warning(filename, classification, candidate_pages, warning_text),
        )

    return _copy_payload_with_content_and_report(
        payload,
        merged,
        OcrIngestionReport(
            strategy=classification.strategy,
            candidate_pages=candidate_pages,
            applied_pages=applied_pages,
            warning=warning_text,
        ),
    )


def _candidate_ocr_pages(classification: PDFClassificationResult) -> list[int]:
    pages = [*classification.ocr_pages, *classification.mixed_pages]
    normalized: list[int] = []
    for page in pages:
        if isinstance(page, bool) or not isinstance(page, int) or page < 0:
            continue
        if page not in normalized:
            normalized.append(page)
    return normalized


def _render_pdf_page_png(source_path: Path, page_index: int) -> bytes:
    if not isinstance(source_path, Path):
        raise TypeError("source_path must be a pathlib.Path")
    if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
        raise ValueError("page_index must be a non-negative integer")

    import pymupdf

    doc = pymupdf.open(str(source_path))
    try:
        if page_index >= len(doc):
            raise ValueError(f"page_index out of range: {page_index}")
        page = doc[page_index]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        return pixmap.tobytes("png")
    finally:
        doc.close()


def _format_ocr_warning(
    filename: str,
    classification: PDFClassificationResult,
    candidate_pages: Sequence[int],
    warning: str | None,
) -> str:
    page_list = ", ".join(str(page + 1) for page in candidate_pages)
    detail = warning or "no OCR engine selected"
    return (
        f"[OCR not executed for {filename}: strategy={classification.strategy}; "
        f"pages={page_list}; reason={detail}]"
    )


def _append_section(content: str, section: str) -> str:
    base = str(content or "").strip()
    addition = str(section or "").strip()
    if not addition:
        return base
    if not base:
        return addition
    return f"{base}\n\n{addition}"


def _copy_payload_with_content_and_report(
    payload: ExtractionPayloadLike,
    content: str,
    report: OcrIngestionReport,
) -> ExtractionPayloadLike:
    payload_type = type(payload)
    kwargs = {
        "content": content,
        "blocks": payload.blocks,
        "markdown_full": payload.markdown_full,
    }
    try:
        return payload_type(**kwargs, ocr_report=report)
    except TypeError:
        return payload_type(**kwargs)


def _copy_payload_with_ocr_report(
    payload: ExtractionPayloadLike,
    report: OcrIngestionReport,
) -> ExtractionPayloadLike:
    return _copy_payload_with_content_and_report(payload, payload.content, report)
