# -*- coding: utf-8 -*-
"""PDF parser backend abstraction (marker-pdf-rag-pipeline-plan §1.2 + §1.3).

Provides a backend Protocol so PDF parsing can be swapped between PyMuPDF
(default, byte-level identical to previous behavior) and marker (optional,
structure-aware via `pip install marker-pdf` + env var). The active backend
is chosen by environment variable, not by changing any default caller code.

Public API:
    StructuredBlock         : structured block emitted by marker backend
    PDFParserBackend        : Protocol; .parse(path) -> (text, blocks?, md?)
    MarkerUnavailable       : raised when marker backend selected but marker-pdf
                              package is missing or fails to import
    get_pdf_backend(env=None): factory returning the active backend instance

Default behavior (env var unset / empty / "pymupdf" / "auto"):
    PyMuPDFBackend, byte-level identical to legacy
    ``_extract_document_content_from_path`` PDF branch.

Marker backend (env var "marker"):
    MarkerBackend; raises MarkerUnavailable inside parse() if the user has
    not yet `pip install marker-pdf`-ed it. Callers in upload layer must
    catch and fall back to PyMuPDFBackend (see plan §1.3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


__all__ = [
    "ENV_VAR",
    "MarkerUnavailable",
    "PDFParserBackend",
    "StructuredBlock",
    "get_pdf_backend",
]


# Environment variable name used to pick the active backend at runtime.
# Documented user contract — do not rename without an OPEN_THREADS entry.
ENV_VAR = "LITASSIST_PDF_PARSER"


class MarkerUnavailable(RuntimeError):
    """marker backend was selected but marker-pdf is not installed.

    Upload layer catches this and falls back to PyMuPDFBackend; warning is
    logged so operators know to install marker-pdf if they intended to enable
    structured parsing.
    """


@dataclass(frozen=True)
class StructuredBlock:
    """Single structural block emitted by a structure-aware backend (marker).

    Mirrors the shape marker's ``output_format='chunks'`` API gives per block,
    normalized to a stable dataclass our chunker can consume. PyMuPDFBackend
    never produces these (it returns ``blocks=None``).

    Attributes:
        block_id: Stable id within the source document (marker's chunk id).
        page: 1-indexed page number.
        bbox: [x0, y0, x1, y1] in PDF coordinates, or None when unknown.
        block_type: One of {"Text", "Paragraph", "Heading", "Table",
            "Equation", "FigureCaption", "Code", "ListItem", "Image"}.
            Unknown types fall back to "Text" downstream.
        markdown: Markdown-formatted content for this block (may contain
            LaTeX ``$...$$`` for equations, ``| col |`` for tables, etc.).
        html: Raw HTML for this block from marker (best for table
            preservation if downstream needs structure beyond markdown).
        image_paths: Relative paths to images marker extracted (figure_caption
            blocks point at the figure; image blocks point at themselves).
        table_csv: CSV serialization of the table content (table blocks only).
        equation_latex: LaTeX source of the equation (equation blocks only).
        section_heading: The most-recent heading block's text up to this block,
            used downstream to build ``section_path``.
    """

    block_id: str
    page: int
    bbox: list[float] | None
    block_type: str
    markdown: str
    html: str | None = None
    image_paths: list[str] = field(default_factory=list)
    table_csv: str | None = None
    equation_latex: str | None = None
    section_heading: str | None = None


class PDFParserBackend(Protocol):
    """Backend Protocol — implementations: PyMuPDFBackend, MarkerBackend."""

    name: str
    """Stable backend id used for logging and tests (``"pymupdf"`` /
    ``"marker"``)."""

    supports_blocks: bool
    """Whether this backend returns structured blocks. True for marker,
    False for pymupdf. Drives the chunker's ``blocks=...`` branch."""

    def parse(
        self,
        source_path: Path,
    ) -> tuple[str, list[StructuredBlock] | None, str | None]:
        """Parse a PDF file at ``source_path``.

        Returns:
            (text, blocks, markdown_full) where:
              - text: Plain text content (byte-level identical to legacy
                ``_extract_document_content_from_path`` for PyMuPDFBackend;
                a flat plain-text projection of marker's output for
                MarkerBackend).
              - blocks: list[StructuredBlock] for backends that support it;
                None otherwise. Chunker uses this to take the structured path.
              - markdown_full: Full-document markdown for sidecar writing;
                None for backends that cannot produce it.

        Raises:
            MarkerUnavailable: marker selected but marker-pdf not installed.
            OSError / RuntimeError / TypeError / ValueError: passed through;
                upload-layer catches and produces ``"[PDF 解析失败: ...]"``
                placeholder for PyMuPDFBackend per legacy behavior.
        """
        ...


def _normalize_env_choice(raw: str | None) -> str:
    """Pick canonical backend id from env var value.

    Default ("", None, "auto", "pymupdf", "pdfminer", arbitrary) → "pymupdf".
    Only the literal "marker" string opts into marker.
    """
    if not raw:
        return "pymupdf"
    choice = raw.strip().lower()
    if choice == "marker":
        return "marker"
    return "pymupdf"


def get_pdf_backend(env: str | None = None) -> PDFParserBackend:
    """Factory — pick backend instance from env var or feature flag.

    Resolution order(env 显式设值时尊重它,不再 fall back 到 feature flag):
      1. ``env`` argument(testing override)
      2. ``LITASSIST_PDF_PARSER`` env var(任何非空值 → 完全决定 backend)
      3. feature flag ``pdf_parser_marker``(Settings UI 持久化,仅在 env 未设/空时生效)
      4. default → PyMuPDFBackend

    Args:
        env: Explicit override for testing. If None, reads from env var
             and feature flag in that order.

    Returns:
        A backend instance ready to ``.parse(path)``.
    """
    raw = env if env is not None else os.environ.get(ENV_VAR)
    if raw is not None and raw.strip():
        # env var is explicitly set — it fully decides the backend, even when
        # the value points to PyMuPDF. Feature flag is ignored in this branch
        # so that ops can hard-pin backend via env without UI drift.
        choice = _normalize_env_choice(raw)
        if choice == "marker":
            from .marker_backend import MarkerBackend
            return MarkerBackend()
        from .pymupdf_backend import PyMuPDFBackend
        return PyMuPDFBackend()
    # env var not set → fall back to feature flag (Settings UI 持久化的开关).
    # Defensive import so packages with broken feature_flags loading still
    # get PyMuPDF fallback.
    try:
        from feature_flags import is_enabled
        if is_enabled("pdf_parser_marker"):
            from .marker_backend import MarkerBackend
            return MarkerBackend()
    except (ImportError, KeyError):
        pass
    from .pymupdf_backend import PyMuPDFBackend
    return PyMuPDFBackend()
