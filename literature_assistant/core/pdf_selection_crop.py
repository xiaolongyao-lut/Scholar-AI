"""Bounded, source-addressed PDF crops for replaying visual selections.

The durable chat contract stores only source locators.  This module turns a
validated ``page + normalized bbox`` locator back into transient pixels without
placing image bytes or machine-local paths in conversation history.
"""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, Sequence, TypeGuard

if TYPE_CHECKING:
    from literature_assistant.core.models import PdfBboxUnit, coerce_pdf_bbox, pdf_bbox_matches_unit
    from literature_assistant.core.project_paths import project_data_path
else:
    from models import PdfBboxUnit, coerce_pdf_bbox, pdf_bbox_matches_unit
    from project_paths import project_data_path


PdfSelectionCropMime = Literal["image/png", "image/jpeg"]

_CROP_CACHE_VERSION = "scholar-ai-pdf-selection-crop/v1"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"


class _PdfRect(Protocol):
    """Rectangle capabilities consumed by crop geometry calculations."""

    @property
    def x0(self) -> float: ...

    @property
    def y0(self) -> float: ...

    @property
    def width(self) -> float: ...

    @property
    def height(self) -> float: ...

    @property
    def is_empty(self) -> bool: ...

    def __and__(self, other: _PdfRect) -> _PdfRect: ...


class _PdfPixmap(Protocol):
    """Pixmap capabilities used for bounded image encoding."""

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    def tobytes(
        self,
        output: str,
        *,
        jpg_quality: int = ...,
    ) -> object: ...


class _PdfPage(Protocol):
    """Page capabilities used by visual selection replay."""

    @property
    def rect(self) -> object: ...

    def get_pixmap(
        self,
        *,
        matrix: object,
        colorspace: object,
        alpha: bool,
        clip: object,
        annots: bool,
    ) -> object: ...


class _CloseableDocument(Protocol):
    """Minimum resource capability required after opening a PDF."""

    def close(self) -> None: ...


class _PdfPageSequence(Protocol):
    """Page sequence consumed by crop rendering."""

    def __len__(self) -> int: ...

    def __getitem__(self, index: int) -> object: ...


class _PdfDocument(_CloseableDocument, _PdfPageSequence, Protocol):
    """Context-managed page sequence returned by PyMuPDF."""

    def __enter__(self) -> _PdfPageSequence: ...

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> bool | None: ...


def _is_pdf_rect(value: object) -> TypeGuard[_PdfRect]:
    """Validate the numeric rectangle surface before geometry arithmetic."""

    coordinates = (
        getattr(value, "x0", None),
        getattr(value, "y0", None),
        getattr(value, "width", None),
        getattr(value, "height", None),
    )
    return (
        all(
            isinstance(coordinate, (int, float))
            and not isinstance(coordinate, bool)
            for coordinate in coordinates
        )
        and isinstance(getattr(value, "is_empty", None), bool)
        and callable(getattr(value, "__and__", None))
    )


def _is_pdf_pixmap(value: object) -> TypeGuard[_PdfPixmap]:
    """Validate the encoded-pixmap surface returned by a page."""

    width = getattr(value, "width", None)
    height = getattr(value, "height", None)
    return (
        isinstance(width, int)
        and not isinstance(width, bool)
        and isinstance(height, int)
        and not isinstance(height, bool)
        and callable(getattr(value, "tobytes", None))
    )


def _is_pdf_page(value: object) -> TypeGuard[_PdfPage]:
    """Validate the page surface required for crop rendering."""

    return getattr(value, "rect", None) is not None and callable(
        getattr(value, "get_pixmap", None)
    )


def _is_pdf_page_sequence(value: object) -> TypeGuard[_PdfPageSequence]:
    """Validate page access independently from resource ownership."""

    return callable(getattr(value, "__len__", None)) and callable(
        getattr(value, "__getitem__", None)
    )


def _is_closeable_document(value: object) -> TypeGuard[_CloseableDocument]:
    """Narrow an opened value before validating context/page behavior."""

    return callable(getattr(value, "close", None))


def _is_pdf_document(value: object) -> TypeGuard[_PdfDocument]:
    """Validate the context-managed page sequence used by the open path."""

    return all(
        callable(getattr(value, method_name, None))
        for method_name in (
            "close",
            "__len__",
            "__getitem__",
            "__enter__",
            "__exit__",
        )
    )


def _call_runtime_method(
    target: object,
    method_name: str,
    *args: object,
    **kwargs: object,
) -> object:
    """Call a checked method on PyMuPDF's partially typed runtime surface."""

    method = getattr(target, method_name, None)
    if not callable(method):
        raise TypeError(f"PyMuPDF object must expose callable {method_name}")
    result: object = method(*args, **kwargs)
    return result


def _new_pymupdf_rect(module: object, *args: object) -> _PdfRect:
    """Create and validate one native PyMuPDF rectangle."""

    rect = _call_runtime_method(module, "Rect", *args)
    if not _is_pdf_rect(rect):
        raise TypeError("PyMuPDF Rect() returned an incompatible rectangle")
    return rect


def _new_pymupdf_matrix(module: object, *args: object) -> object:
    """Create an opaque matrix that is passed directly back to PyMuPDF."""

    return _call_runtime_method(module, "Matrix", *args)


def _open_pymupdf_document(module: object, source_path: str) -> _CloseableDocument:
    """Open a document and first establish its minimum release capability."""

    document = _call_runtime_method(module, "open", source_path)
    if not _is_closeable_document(document):
        raise TypeError("PyMuPDF open() must return a closeable document")
    return document


class PdfSelectionCropError(ValueError):
    """Raised when a PDF selection cannot be rendered within safe bounds."""

    def __init__(self, code: str, message: str) -> None:
        if not str(code or "").strip():
            raise ValueError("code must be non-empty")
        if not str(message or "").strip():
            raise ValueError("message must be non-empty")
        self.code = str(code).strip()
        super().__init__(str(message).strip())


@dataclass(frozen=True, slots=True)
class PdfSelectionCropSpec:
    """One project-owned PDF region requested by a replaying chat turn.

    Args:
        page: One-based PDF page number.
        bbox: ``(x, y, width, height)`` in normalized displayed-page ratios.
    """

    page: int
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class PdfSelectionCrop:
    """Transient encoded crop plus non-secret cache provenance.

    ``data`` is request-scoped and must not be serialized into a chat message.
    ``cache_key`` and ``content_sha256`` are safe deterministic digests suitable
    for later observation receipts and staleness checks.
    """

    data: bytes
    mime: PdfSelectionCropMime
    size: int
    cache_key: str
    content_sha256: str
    cache_hit: bool


def _normalized_spec(spec: PdfSelectionCropSpec) -> PdfSelectionCropSpec:
    if not isinstance(spec, PdfSelectionCropSpec):
        raise PdfSelectionCropError("invalid_spec", "crop spec must be PdfSelectionCropSpec")
    if isinstance(spec.page, bool) or not isinstance(spec.page, int) or spec.page < 1:
        raise PdfSelectionCropError("invalid_page", "page must be a positive integer")
    bbox = coerce_pdf_bbox(list(spec.bbox))
    if bbox is None or not pdf_bbox_matches_unit(bbox, PdfBboxUnit.NORMALIZED_RATIO):
        raise PdfSelectionCropError(
            "invalid_bbox",
            "bbox must be a positive normalized_ratio rectangle inside the page",
        )
    canonical = (
        round(float(bbox[0]), 6),
        round(float(bbox[1]), 6),
        round(float(bbox[2]), 6),
        round(float(bbox[3]), 6),
    )
    if not pdf_bbox_matches_unit(list(canonical), PdfBboxUnit.NORMALIZED_RATIO):
        raise PdfSelectionCropError("invalid_bbox", "bbox is too small after normalization")
    return PdfSelectionCropSpec(page=spec.page, bbox=canonical)


def _validated_source(source_path: Path) -> tuple[Path, os.stat_result]:
    if not isinstance(source_path, Path):
        raise PdfSelectionCropError("invalid_source", "source_path must be a Path")
    try:
        resolved = source_path.expanduser().resolve(strict=True)
        stat = resolved.stat()
    except (OSError, RuntimeError, ValueError) as exc:
        raise PdfSelectionCropError("source_missing", "source PDF is unavailable") from exc
    if not resolved.is_file() or resolved.suffix.casefold() != ".pdf":
        raise PdfSelectionCropError("source_not_pdf", "selection source must be an existing PDF")
    return resolved, stat


def _safe_material_segment(material_id: str) -> str:
    normalized = str(material_id or "").strip()
    if not normalized:
        raise PdfSelectionCropError("invalid_material", "material_id must be non-empty")
    safe = "".join(character for character in normalized if character.isalnum() or character in "_-")
    digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{safe[:48] or 'material'}-{digest}"


def _cache_key(
    *,
    project_id: str,
    material_id: str,
    source_path: Path,
    source_stat: os.stat_result,
    spec: PdfSelectionCropSpec,
    max_edge: int,
    max_bytes: int,
) -> str:
    bbox_text = ",".join(f"{value:.6f}" for value in spec.bbox)
    source_identity = str(source_path).casefold() if os.name == "nt" else str(source_path)
    material = "|".join(
        (
            _CROP_CACHE_VERSION,
            str(project_id),
            str(material_id),
            source_identity,
            str(source_stat.st_size),
            str(source_stat.st_mtime_ns),
            str(spec.page),
            bbox_text,
            str(max_edge),
            str(max_bytes),
            "matrix-max-2",
            "rgb-alpha-0-annots-0",
            "png-jpeg90",
        )
    )
    return hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()


def _cache_candidates(cache_root: Path, cache_key: str) -> tuple[tuple[Path, PdfSelectionCropMime], ...]:
    return (
        (cache_root / f"{cache_key}.png", "image/png"),
        (cache_root / f"{cache_key}.jpg", "image/jpeg"),
    )


def _bytes_match_mime(data: bytes, mime: PdfSelectionCropMime) -> bool:
    if mime == "image/png":
        return data.startswith(_PNG_SIGNATURE)
    return data.startswith(_JPEG_SIGNATURE)


def _read_cached_crop(
    cache_root: Path,
    cache_key: str,
    *,
    max_bytes: int,
) -> PdfSelectionCrop | None:
    for path, mime in _cache_candidates(cache_root, cache_key):
        try:
            if path.is_symlink():
                continue
            path.resolve(strict=True).relative_to(cache_root.resolve())
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            continue
        if not data or len(data) > max_bytes or not _bytes_match_mime(data, mime):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        return PdfSelectionCrop(
            data=data,
            mime=mime,
            size=len(data),
            cache_key=cache_key,
            content_sha256=hashlib.sha256(data).hexdigest(),
            cache_hit=True,
        )
    return None


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def _render_crop(
    document: object,
    spec: PdfSelectionCropSpec,
    *,
    max_edge: int,
    max_bytes: int,
) -> tuple[bytes, PdfSelectionCropMime]:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - required project dependency.
        raise PdfSelectionCropError("renderer_unavailable", "PyMuPDF is unavailable") from exc

    if not _is_pdf_page_sequence(document):
        raise PdfSelectionCropError(
            "invalid_document",
            "PDF document handle is invalid",
        )
    try:
        page_count = len(document)
    except (TypeError, AttributeError) as exc:
        raise PdfSelectionCropError("invalid_document", "PDF document handle is invalid") from exc
    if spec.page > page_count:
        raise PdfSelectionCropError("page_out_of_range", "selection page is outside the PDF")

    try:
        page_value = document[spec.page - 1]
        if not _is_pdf_page(page_value):
            raise TypeError("PyMuPDF document returned an incompatible page")
        page = page_value
        page_rect = _new_pymupdf_rect(pymupdf, page.rect)
        if page_rect.width <= 0 or page_rect.height <= 0:
            raise PdfSelectionCropError("invalid_page_geometry", "PDF page geometry is invalid")
        x, y, width, height = spec.bbox
        clip = _new_pymupdf_rect(
            pymupdf,
            page_rect.x0 + x * page_rect.width,
            page_rect.y0 + y * page_rect.height,
            page_rect.x0 + (x + width) * page_rect.width,
            page_rect.y0 + (y + height) * page_rect.height,
        )
        clip = clip & page_rect
        if clip.is_empty or clip.width <= 0 or clip.height <= 0:
            raise PdfSelectionCropError("empty_crop", "selection crop is empty")
        scale = min(2.0, max_edge / max(float(clip.width), float(clip.height)))
        if not math.isfinite(scale) or scale <= 0:
            raise PdfSelectionCropError("invalid_scale", "selection crop scale is invalid")
        colorspace = getattr(pymupdf, "csRGB", None)
        if colorspace is None:
            raise TypeError("PyMuPDF csRGB colorspace is unavailable")
        pixmap_value = page.get_pixmap(
            matrix=_new_pymupdf_matrix(pymupdf, scale, scale),
            colorspace=colorspace,
            alpha=False,
            clip=clip,
            annots=False,
        )
        if not _is_pdf_pixmap(pixmap_value):
            raise TypeError("PyMuPDF Page.get_pixmap() returned an incompatible pixmap")
        pixmap = pixmap_value
        if pixmap.width < 1 or pixmap.height < 1:
            raise PdfSelectionCropError("empty_crop", "selection crop has no pixels")
        if max(pixmap.width, pixmap.height) > max_edge + 1:
            raise PdfSelectionCropError("render_bounds", "selection crop exceeded the pixel bound")
        data = pixmap.tobytes("png")
        if not isinstance(data, bytes):
            raise TypeError("PyMuPDF Pixmap.tobytes() must return bytes")
        mime: PdfSelectionCropMime = "image/png"
        if len(data) > max_bytes:
            data = pixmap.tobytes("jpeg", jpg_quality=90)
            if not isinstance(data, bytes):
                raise TypeError("PyMuPDF Pixmap.tobytes() must return bytes")
            mime = "image/jpeg"
    except PdfSelectionCropError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
        raise PdfSelectionCropError("render_failed", "PDF selection crop failed") from exc

    if not data or len(data) > max_bytes:
        raise PdfSelectionCropError("crop_too_large", "selection crop exceeds the image byte limit")
    if not _bytes_match_mime(data, mime):
        raise PdfSelectionCropError("invalid_encoding", "selection crop encoding is invalid")
    return data, mime


def derive_pdf_selection_crops(
    *,
    project_id: str,
    material_id: str,
    source_path: Path,
    specs: Sequence[PdfSelectionCropSpec],
    max_edge: int = 1600,
    max_bytes: int = 4 * 1024 * 1024,
) -> list[PdfSelectionCrop]:
    """Render or reuse bounded crops for ordered PDF visual selections.

    Args:
        project_id: Existing project that owns the material and cache root.
        material_id: Existing project material identifier. It is sanitized before
            becoming a cache directory segment.
        source_path: Already-authorized source PDF path. Callers must resolve it
            through the project material resolver rather than user input.
        specs: Ordered one-based page and normalized-ratio bbox requests.
        max_edge: Maximum encoded image width or height in pixels.
        max_bytes: Maximum encoded bytes per crop.

    Returns:
        Crops in exactly the same order as ``specs``. Pixel bytes are transient;
        only the cache and content digests are durable identifiers.

    Raises:
        PdfSelectionCropError: If input, source, page geometry, rendering, or
            output bounds are invalid.
    """

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise PdfSelectionCropError("invalid_project", "project_id must be non-empty")
    if isinstance(max_edge, bool) or not isinstance(max_edge, int) or not 64 <= max_edge <= 4096:
        raise PdfSelectionCropError("invalid_limit", "max_edge must be between 64 and 4096")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1024 <= max_bytes <= 32 * 1024 * 1024:
        raise PdfSelectionCropError("invalid_limit", "max_bytes must be between 1024 and 32 MiB")
    if not isinstance(specs, Sequence) or isinstance(specs, (str, bytes, bytearray)):
        raise PdfSelectionCropError("invalid_specs", "specs must be an ordered sequence")
    if not specs:
        return []
    if len(specs) > 6:
        raise PdfSelectionCropError("too_many_crops", "at most six visual crops are allowed")

    normalized_specs = [_normalized_spec(spec) for spec in specs]
    resolved_source, source_stat = _validated_source(source_path)
    project_root = project_data_path(normalized_project_id)
    cache_root = project_data_path(
        normalized_project_id,
        "visual_selection_crops",
        _safe_material_segment(material_id),
    )
    try:
        cache_root.resolve().relative_to(project_root.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise PdfSelectionCropError(
            "invalid_cache_root",
            "selection crop cache escaped the project workspace",
        ) from exc
    keys = [
        _cache_key(
            project_id=normalized_project_id,
            material_id=material_id,
            source_path=resolved_source,
            source_stat=source_stat,
            spec=spec,
            max_edge=max_edge,
            max_bytes=max_bytes,
        )
        for spec in normalized_specs
    ]
    results: list[PdfSelectionCrop | None] = [
        _read_cached_crop(cache_root, key, max_bytes=max_bytes)
        for key in keys
    ]
    if all(result is not None for result in results):
        return [result for result in results if result is not None]

    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - required project dependency.
        raise PdfSelectionCropError("renderer_unavailable", "PyMuPDF is unavailable") from exc

    try:
        opened_document = _open_pymupdf_document(pymupdf, str(resolved_source))
        context_entered = False
        try:
            if not _is_pdf_document(opened_document):
                raise TypeError(
                    "PyMuPDF open() must return a context-managed page sequence"
                )
            with opened_document as document:
                context_entered = True
                for index, (spec, key) in enumerate(
                    zip(normalized_specs, keys, strict=True)
                ):
                    if results[index] is not None:
                        continue
                    # A duplicate selection earlier in this batch may have populated
                    # the deterministic cache file after the initial cache scan.
                    cached = _read_cached_crop(cache_root, key, max_bytes=max_bytes)
                    if cached is not None:
                        results[index] = cached
                        continue
                    data, mime = _render_crop(
                        document,
                        spec,
                        max_edge=max_edge,
                        max_bytes=max_bytes,
                    )
                    suffix = ".png" if mime == "image/png" else ".jpg"
                    cache_path = cache_root / f"{key}{suffix}"
                    _atomic_write_bytes(cache_path, data)
                    results[index] = PdfSelectionCrop(
                        data=data,
                        mime=mime,
                        size=len(data),
                        cache_key=key,
                        content_sha256=hashlib.sha256(data).hexdigest(),
                        cache_hit=False,
                    )
        finally:
            if not context_entered:
                opened_document.close()
    except PdfSelectionCropError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PdfSelectionCropError("pdf_open_failed", "source PDF cannot be opened") from exc

    if any(result is None for result in results):
        raise PdfSelectionCropError("render_incomplete", "not all PDF crops were produced")
    return [result for result in results if result is not None]


__all__ = [
    "PdfSelectionCrop",
    "PdfSelectionCropError",
    "PdfSelectionCropMime",
    "PdfSelectionCropSpec",
    "derive_pdf_selection_crops",
]
