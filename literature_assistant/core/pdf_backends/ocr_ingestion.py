# -*- coding: utf-8 -*-
"""OCR post-processing for PDF ingestion payloads."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Mapping,
    Protocol,
    Sequence,
    TypeGuard,
    runtime_checkable,
)

from .ocr_classifier import OCRNeedClassifier, PDFClassificationResult
from .ocr_engine import OcrImageResult
from .ocr_engine_registry import resolve_ocr_runtime_config, select_ocr_engine


__all__ = [
    "OcrIngestionReport",
    "apply_pdf_ocr_if_needed",
]


_LOGGER = logging.getLogger("OcrIngestion")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SECRET_CONFIG_KEYS = frozenset(
    {"api_key", "authorization", "password", "secret", "token"}
)


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
    engine_name: str | None = None
    engine_implementation_fingerprint: str | None = None
    config_fingerprint: str | None = None
    output_sha256: str | None = None

    def revision_payload(self) -> dict[str, object]:
        """Return bounded OCR provenance without warning text or secrets."""

        return {
            "strategy": str(self.strategy or "unknown")[:64],
            "candidate_pages": [int(page) for page in self.candidate_pages[:10_000]],
            "applied_pages": [int(page) for page in self.applied_pages[:10_000]],
            "engine_name": self.engine_name,
            "engine_implementation_fingerprint": self.engine_implementation_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "output_sha256": self.output_sha256,
        }


RenderPageFn = Callable[[Path, int], bytes]


@runtime_checkable
class ExtractionPayloadLike(Protocol):
    """Legacy three-field payload shape accepted by the OCR post-processor."""

    @property
    def content(self) -> str:
        """Return extracted document text."""
        ...

    @property
    def blocks(self) -> object:
        """Return optional structured document blocks."""
        ...

    @property
    def markdown_full(self) -> str | None:
        """Return optional full-document markdown."""
        ...


@runtime_checkable
class _ExtractionPayloadWithProvenance(ExtractionPayloadLike, Protocol):
    """Optional parser provenance carried by current extraction payloads."""

    @property
    def parser_provenance(self) -> object:
        """Return parser provenance when the payload supports it."""
        ...

    @property
    def parser_output_sha256(self) -> str | None:
        """Return the optional parser-output fingerprint."""
        ...


class _CloseableDocument(Protocol):
    """Minimum resource capability required after opening a PDF."""

    def close(self) -> None: ...


class _PageSequenceDocument(_CloseableDocument, Protocol):
    """PyMuPDF document capabilities used by one-page rendering."""

    def __len__(self) -> int: ...

    def __getitem__(self, index: int) -> object: ...


def _is_page_sequence_document(value: object) -> TypeGuard[_PageSequenceDocument]:
    """Narrow an opened value to the page sequence consumed below."""

    return (
        callable(getattr(value, "__len__", None))
        and callable(getattr(value, "__getitem__", None))
        and callable(getattr(value, "close", None))
    )


def _is_closeable_document(value: object) -> TypeGuard[_CloseableDocument]:
    """Narrow an opened value before validating page access."""

    return callable(getattr(value, "close", None))


def _call_runtime_method(
    target: object,
    method_name: str,
    *args: object,
    **kwargs: object,
) -> object:
    """Call one method exposed by PyMuPDF's partially typed runtime surface."""

    method = getattr(target, method_name, None)
    if not callable(method):
        raise TypeError(f"PyMuPDF object must expose callable {method_name}")
    result: object = method(*args, **kwargs)
    return result


def _validate_reconstructed_payload(
    value: object,
    *,
    require_provenance: bool,
) -> ExtractionPayloadLike:
    """Validate a dynamically reconstructed compatibility payload."""

    if not isinstance(value, ExtractionPayloadLike):
        raise TypeError("reconstructed OCR payload does not expose required fields")
    if not isinstance(value.content, str):
        raise TypeError("reconstructed OCR payload content must be a string")
    if value.markdown_full is not None and not isinstance(value.markdown_full, str):
        raise TypeError("reconstructed OCR payload markdown_full must be a string or None")
    if not isinstance(value, _ExtractionPayloadWithProvenance):
        if require_provenance:
            raise TypeError("reconstructed OCR payload lost parser provenance")
        return value
    if value.parser_output_sha256 is not None and not isinstance(
        value.parser_output_sha256,
        str,
    ):
        raise TypeError(
            "reconstructed OCR payload parser_output_sha256 must be a string or None"
        )
    return value


def _construct_payload(
    payload: ExtractionPayloadLike,
    fields: Mapping[str, object],
    *,
    require_provenance: bool,
) -> ExtractionPayloadLike:
    """Reconstruct one payload through its checked dynamic class boundary."""

    constructor: object = type(payload)
    if not callable(constructor):
        raise TypeError("payload type must be callable")
    reconstructed: object = constructor(**dict(fields))
    return _validate_reconstructed_payload(
        reconstructed,
        require_provenance=require_provenance,
    )


def _select_payload_constructor_fields(
    payload: ExtractionPayloadLike,
    candidates: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    """Select compatible constructor fields without invoking the constructor."""

    constructor: object = type(payload)
    if not callable(constructor):
        raise TypeError("payload type must be callable")
    try:
        signature = inspect.signature(constructor)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            "payload constructor must expose an inspectable signature"
        ) from exc

    last_binding_error: TypeError | None = None
    for fields in candidates:
        try:
            signature.bind(**dict(fields))
        except TypeError as exc:
            last_binding_error = exc
            continue
        return fields

    if last_binding_error is not None:
        raise last_binding_error
    raise TypeError("no payload constructor field candidates were provided")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _engine_implementation_fingerprint(engine: object) -> str | None:
    """Hash the selected engine adapter source when it is locally inspectable."""

    try:
        source_path = inspect.getsourcefile(type(engine))
        if not source_path:
            return None
        path = Path(source_path).resolve()
        if not path.is_file():
            return None
        return _sha256_bytes(path.read_bytes())
    except (OSError, TypeError):
        return None


def _safe_config_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _safe_config_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).strip().lower() not in _SECRET_CONFIG_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe_config_value(item) for item in value]
    return type(value).__name__


def _ocr_config_fingerprint(runtime_config: object) -> str:
    """Hash behavior-relevant OCR config after removing secret-bearing keys."""

    engine_config = getattr(runtime_config, "engine_config", {})
    safe_engine_config = _safe_config_value(
        engine_config if isinstance(engine_config, Mapping) else {}
    )
    payload = {
        "policy": str(getattr(runtime_config, "policy", "unknown")),
        "engine": getattr(runtime_config, "engine", None),
        "language": str(getattr(runtime_config, "language", "unknown")),
        "engine_config": safe_engine_config,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


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
    config_fingerprint = _ocr_config_fingerprint(runtime_config)
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
                config_fingerprint=config_fingerprint,
            ),
        )

    renderer = render_page or _render_pdf_page_png
    ocr_sections: list[str] = []
    ocr_page_results: list[tuple[int, OcrImageResult]] = []
    applied_pages: list[int] = []
    failed_pages: list[str] = []
    for page_index in candidate_pages:
        try:
            image = renderer(source_path, page_index)
            page_result = _read_ocr_image_result(
                engine,
                image,
                language=runtime_config.language,
            )
            page_text = _ocr_result_text(page_result)
        except Exception as exc:  # noqa: BLE001 - per-page failure must not block ingest
            failed_pages.append(f"page {page_index + 1}: {exc}")
            continue
        if page_text:
            applied_pages.append(page_index)
            ocr_sections.append(f"[OCR Page {page_index + 1}]\n{page_text}")
            ocr_page_results.append((page_index, page_result))

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
            engine_name=str(getattr(engine, "name", "unknown"))[:80],
            engine_implementation_fingerprint=_engine_implementation_fingerprint(engine),
            config_fingerprint=config_fingerprint,
            output_sha256=(
                _sha256_bytes("\n\n".join(ocr_sections).encode("utf-8"))
                if ocr_sections
                else None
            ),
        ),
        blocks=_merge_ocr_page_blocks(payload.blocks, ocr_page_results),
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

    opened_document = _call_runtime_method(pymupdf, "open", str(source_path))
    if not _is_closeable_document(opened_document):
        raise TypeError("PyMuPDF open() must return a closeable document")
    document = opened_document
    try:
        if not _is_page_sequence_document(document):
            raise TypeError(
                "PyMuPDF open() must return a closeable page-sequence document"
            )
        if page_index >= len(document):
            raise ValueError(f"page_index out of range: {page_index}")
        page = document[page_index]
        pixmap = _call_runtime_method(
            page,
            "get_pixmap",
            matrix=_call_runtime_method(pymupdf, "Matrix", 2, 2),
            alpha=False,
        )
        image_bytes = _call_runtime_method(pixmap, "tobytes", "png")
        if not isinstance(image_bytes, bytes):
            raise TypeError("PyMuPDF Pixmap.tobytes() must return bytes")
        return image_bytes
    finally:
        document.close()


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


def _read_ocr_image_result(
    engine: object,
    image: bytes | Path,
    *,
    language: str,
) -> OcrImageResult:
    """Prefer an engine's optional structured result and adapt legacy text."""

    structured_method = getattr(engine, "ocr_image_result", None)
    if callable(structured_method):
        result = structured_method(image, language=language)
        if not isinstance(result, OcrImageResult):
            raise TypeError("ocr_image_result must return OcrImageResult")
        return result

    legacy_method = getattr(engine, "ocr_image", None)
    if not callable(legacy_method):
        raise TypeError("OCR engine must expose callable ocr_image")
    text = legacy_method(image, language=language)
    if not isinstance(text, str):
        raise TypeError("ocr_image must return a string")
    return OcrImageResult(text=text)


def _ocr_result_text(result: OcrImageResult) -> str:
    """Return searchable page text, falling back to located region content."""

    normalized = result.text.strip()
    if normalized:
        return normalized
    return "\n".join(
        region.markdown.strip()
        for region in result.regions
        if region.markdown.strip()
    )


def _merge_ocr_page_blocks(
    blocks: Any,
    ocr_page_results: Sequence[tuple[int, OcrImageResult]],
) -> Any:
    """Append located OCR regions or one legacy page-addressable text block.

    The full-text field remains useful for readers and exports, while these
    blocks keep OCR-only evidence visible to the structured chunk path.
    """

    if not ocr_page_results:
        return blocks

    from . import StructuredBlock

    merged = list(blocks) if isinstance(blocks, (list, tuple)) else []
    existing_ids = {
        str(getattr(block, "block_id", "") or "")
        for block in merged
    }
    for page_index, page_result in ocr_page_results:
        if page_result.regions:
            for region_index, region in enumerate(page_result.regions, start=1):
                normalized_text = region.markdown.strip()
                digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:16]
                block_id = f"ocr_p{page_index + 1}_r{region_index}_{digest}"
                if block_id in existing_ids:
                    continue
                merged.append(
                    StructuredBlock(
                        block_id=block_id,
                        page=page_index + 1,
                        bbox=list(region.bbox),
                        bbox_unit="normalized_ratio",
                        block_type=region.block_type.strip(),
                        markdown=normalized_text,
                    )
                )
                existing_ids.add(block_id)
            continue

        normalized_text = _ocr_result_text(page_result)
        if not normalized_text:
            continue
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:16]
        block_id = f"ocr_p{page_index + 1}_{digest}"
        if block_id in existing_ids:
            continue
        merged.append(
            StructuredBlock(
                block_id=block_id,
                page=page_index + 1,
                bbox=None,
                block_type="Text",
                markdown=normalized_text,
            )
        )
        existing_ids.add(block_id)
    return merged


def _copy_payload_with_content_and_report(
    payload: ExtractionPayloadLike,
    content: str,
    report: OcrIngestionReport,
    *,
    blocks: Any | None = None,
) -> ExtractionPayloadLike:
    copied_blocks = payload.blocks if blocks is None else blocks
    base_fields: dict[str, object] = {
        "content": content,
        "blocks": copied_blocks,
        "markdown_full": payload.markdown_full,
    }
    provenance_payload: _ExtractionPayloadWithProvenance | None = None
    if isinstance(payload, _ExtractionPayloadWithProvenance):
        provenance_payload = payload
    require_provenance = provenance_payload is not None
    preferred_fields = dict(base_fields)
    if provenance_payload is not None:
        preferred_fields.update(
            {
                "parser_provenance": provenance_payload.parser_provenance,
                "parser_output_sha256": provenance_payload.parser_output_sha256,
            }
        )
    preferred_with_report = dict(preferred_fields)
    preferred_with_report["ocr_report"] = report
    base_with_report = dict(base_fields)
    base_with_report["ocr_report"] = report
    candidates: list[Mapping[str, object]]
    if provenance_payload is not None:
        candidates = [
            preferred_with_report,
            preferred_fields,
            base_with_report,
            base_fields,
        ]
    else:
        candidates = [base_with_report, base_fields]
    selected_fields = _select_payload_constructor_fields(payload, candidates)
    return _construct_payload(
        payload,
        selected_fields,
        require_provenance=require_provenance,
    )


def _copy_payload_with_ocr_report(
    payload: ExtractionPayloadLike,
    report: OcrIngestionReport,
) -> ExtractionPayloadLike:
    return _copy_payload_with_content_and_report(payload, payload.content, report)
