"""Strict local PDF validation before artifact promotion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pypdf
from pypdf import PdfReader
from pypdf.errors import PdfReadError


MIN_PDF_BYTES = 4096
DEFAULT_MAX_PDF_BYTES = 100 * 1024 * 1024
PDF_VALIDATOR_ID = "scholar_ai_pdf"
PDF_VALIDATOR_VERSION = "1"
PDF_PARSER_ID = "pypdf"
PDF_PARSER_VERSION = pypdf.__version__
PDF_VALIDATION_CHECKS = (
    "size",
    "pdf_magic",
    "pdf_eof",
    "parser_readable",
    "sha256",
)
_HASH_CHUNK_BYTES = 1024 * 1024
_HEADER_SCAN_BYTES = 1024
_EOF_SCAN_BYTES = 4096


class PdfValidationError(ValueError):
    """Raised when a local artifact is not a structurally readable PDF."""


@dataclass(frozen=True, slots=True)
class PdfValidationResult:
    """Bounded evidence produced by strict PDF validation."""

    size_bytes: int
    sha256: str
    page_count: int


def validate_pdf_file(
    path: str | Path,
    *,
    max_bytes: int = DEFAULT_MAX_PDF_BYTES,
) -> PdfValidationResult:
    """Validate PDF size, header, EOF, page tree, content access, and SHA-256.

    Args:
        path: Existing regular file, commonly an adjacent ``.part`` file.
        max_bytes: Hard byte limit established before download.

    Returns:
        Size, lowercase SHA-256, and readable page count.

    Raises:
        PdfValidationError: If any structural or boundary check fails.
    """

    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file() or candidate.is_symlink():
        raise PdfValidationError("PDF artifact must be an existing regular file")
    if max_bytes < MIN_PDF_BYTES:
        raise ValueError(f"max_bytes must be at least {MIN_PDF_BYTES}")
    try:
        size_bytes = candidate.stat().st_size
    except OSError as exc:
        raise PdfValidationError("unable to inspect PDF artifact") from exc
    if size_bytes < MIN_PDF_BYTES:
        raise PdfValidationError(f"PDF artifact is smaller than {MIN_PDF_BYTES} bytes")
    if size_bytes > max_bytes:
        raise PdfValidationError("PDF artifact exceeds the configured byte limit")

    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as handle:
            prefix = handle.read(_HEADER_SCAN_BYTES)
            if b"%PDF-" not in prefix:
                raise PdfValidationError("PDF header is missing")
            digest.update(prefix)
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
            handle.seek(max(0, size_bytes - _EOF_SCAN_BYTES))
            tail = handle.read(_EOF_SCAN_BYTES)
    except PdfValidationError:
        raise
    except OSError as exc:
        raise PdfValidationError("unable to read PDF artifact") from exc
    if b"%%EOF" not in tail:
        raise PdfValidationError("PDF EOF marker is missing")

    try:
        reader = PdfReader(str(candidate), strict=True)
        if reader.is_encrypted:
            raise PdfValidationError("encrypted PDFs require manual review")
        page_count = len(reader.pages)
        if page_count < 1:
            raise PdfValidationError("PDF page tree is empty")
        for page in reader.pages:
            media_box = page.mediabox
            tuple(float(value) for value in (media_box.left, media_box.bottom, media_box.right, media_box.top))
            page.get_contents()
    except PdfValidationError:
        raise
    except (PdfReadError, OSError, TypeError, ValueError, KeyError) as exc:
        raise PdfValidationError("PDF parser could not expand the document structure") from exc

    return PdfValidationResult(
        size_bytes=size_bytes,
        sha256=digest.hexdigest(),
        page_count=page_count,
    )
