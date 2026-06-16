# -*- coding: utf-8 -*-
"""PDF parser backend abstraction.

Provides a backend Protocol for the active PyMuPDF parser. Heavy document
parsers with third-party model runtimes must live outside the core source tree
as optional plugins or workspace references.

Public API:
    PDFParserBackend        : Protocol; .parse(path) -> (text, blocks?, md?)
    get_pdf_backend(env=None): factory returning the active backend instance

Default behavior:
    PyMuPDFBackend, byte-level compatible with the legacy PDF branch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


__all__ = [
    "ENV_VAR",
    "PDFParserBackend",
    "StructuredBlock",
    "get_pdf_backend",
]


# Environment variable name used to pick the active backend at runtime.
# Documented user contract — do not rename without an OPEN_THREADS entry.
ENV_VAR = "LITASSIST_PDF_PARSER"


@dataclass(frozen=True)
class StructuredBlock:
    """Single structural block emitted by a structure-aware optional backend.

    PyMuPDFBackend never produces these and returns ``blocks=None``. Optional
    external parsers may adapt their output to this shape before entering the
    chunking pipeline.

    Attributes:
        block_id: Stable id within the source document.
        page: 1-indexed page number.
        bbox: [x0, y0, x1, y1] in PDF coordinates, or None when unknown.
        block_type: One of {"Text", "Paragraph", "Heading", "Table",
            "Equation", "FigureCaption", "Code", "ListItem", "Image"}.
            Unknown types fall back to "Text" downstream.
        markdown: Markdown-formatted content for this block (may contain
            LaTeX ``$...$$`` for equations, ``| col |`` for tables, etc.).
        html: Raw HTML for this block from a structured parser (best for table
            preservation if downstream needs structure beyond markdown).
        image_paths: Relative paths to images extracted by a structured parser (figure_caption
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
    """Backend Protocol for core and optional external PDF parsers."""

    name: str
    """Stable backend id used for logging and tests."""

    supports_blocks: bool
    """Whether this backend returns structured blocks."""

    def parse(
        self,
        source_path: Path,
    ) -> tuple[str, list[StructuredBlock] | None, str | None]:
        """Parse a PDF file at ``source_path``.

        Returns:
            (text, blocks, markdown_full) where:
              - text: Plain text content (byte-level identical to legacy
                ``_extract_document_content_from_path`` for PyMuPDFBackend).
              - blocks: list[StructuredBlock] for backends that support it;
                None otherwise. Chunker uses this to take the structured path.
              - markdown_full: Full-document markdown for sidecar writing;
                None for backends that cannot produce it.

        Raises:
            OSError / RuntimeError / TypeError / ValueError: passed through;
                upload-layer catches and produces ``"[PDF 解析失败: ...]"``
                placeholder for PyMuPDFBackend per legacy behavior.
        """
        ...


def get_pdf_backend(env: str | None = None) -> PDFParserBackend:
    """Return the active core PDF backend.

    The ``env`` parameter is retained for backward-compatible call sites, but
    core no longer selects heavyweight parser runtimes from environment state.
    External OCR/parser plugins should be resolved outside this factory.

    Args:
        env: Ignored compatibility argument.

    Returns:
        PyMuPDFBackend instance ready to ``.parse(path)``.
    """
    from .pymupdf_backend import PyMuPDFBackend

    return PyMuPDFBackend()
