# -*- coding: utf-8 -*-
"""Marker backend (marker-rag-pipeline-plan §1.2 — structured PDF parser).

Optional backend. Activated by ``LITASSIST_PDF_PARSER=marker`` env var.
Requires the user to ``pip install marker-pdf`` separately — marker is NOT
shipped in the onedir installer (license + size — see plan §6).

Pure parser:
  - Accepts a PDF path, returns (text, blocks, markdown_full).
  - DOES NOT write any files (sidecar I/O is upload-layer's job — plan §1.7).
  - DOES NOT know about project_id / material_id / chunk_store_dir.

When marker-pdf is not installed, ``parse()`` raises ``MarkerUnavailable``;
the upload layer catches and falls back to PyMuPDFBackend.

Block-type mapping (marker → our internal chunk_type — plan §1.5):
    Heading / SectionHeader      → heading
    Text / Paragraph / TextBlock → narrative
    Table                        → table
    Equation / Formula           → formula
    FigureCaption / Caption      → figure_caption
    ListItem / List              → list
    Code / CodeBlock             → code
    Image / Figure / Picture     → image_caption
    <unknown>                    → narrative  (logged for follow-up)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import MarkerUnavailable, PDFParserBackend, StructuredBlock  # noqa: F401


__all__ = ["MarkerBackend", "MARKER_BLOCK_TYPE_MAPPING", "map_marker_block_type"]


logger = logging.getLogger("MarkerBackend")


# Stable block-type → chunk_type mapping. Update when marker upstream adds
# new block types. ``map_marker_block_type`` falls back to "narrative" for
# any block type not in this table.
MARKER_BLOCK_TYPE_MAPPING: dict[str, str] = {
    "Heading": "heading",
    "SectionHeader": "heading",
    "PageHeader": "heading",
    "Text": "narrative",
    "Paragraph": "narrative",
    "TextBlock": "narrative",
    "Table": "table",
    "TableGroup": "table",
    "Equation": "formula",
    "Formula": "formula",
    "FigureCaption": "figure_caption",
    "Caption": "figure_caption",
    "TableCaption": "figure_caption",
    "List": "list",
    "ListItem": "list",
    "Code": "code",
    "CodeBlock": "code",
    "Image": "image_caption",
    "Figure": "image_caption",
    "Picture": "image_caption",
}


def map_marker_block_type(block_type: str | None) -> str:
    """Map marker block type → our internal chunk_type.

    Unknown types fall back to ``"narrative"`` and are logged once at warning
    level so operators can extend ``MARKER_BLOCK_TYPE_MAPPING`` in a future
    slice (plan §8 residual risk).
    """
    if not block_type:
        return "narrative"
    canonical = MARKER_BLOCK_TYPE_MAPPING.get(block_type)
    if canonical is not None:
        return canonical
    logger.warning(
        "marker_unknown_block_type type=%s — falling back to narrative",
        block_type,
    )
    return "narrative"


class MarkerBackend:
    """marker-pdf backend — structured chunks + full markdown.

    Calls marker's PdfConverter with ``output_format='chunks'`` to retrieve
    per-block metadata (page, bbox, type, html, markdown), then projects
    each block to our :class:`StructuredBlock`. The full markdown is also
    requested for sidecar output.

    Raises :class:`MarkerUnavailable` when ``import marker`` fails (user has
    not installed marker-pdf). The upload-layer catches and falls back to
    PyMuPDFBackend; a warning log makes the fallback visible to operators.
    """

    name = "marker"
    supports_blocks = True

    def parse(
        self,
        source_path: Path,
    ) -> tuple[str, list[StructuredBlock] | None, str | None]:
        """Parse with marker; returns (text, blocks, markdown_full).

        ``text`` is a flat plain-text projection (joined block markdowns
        stripped of formatting) so downstream legacy callers expecting plain
        text still get a usable string. ``markdown_full`` is the structured
        markdown for sidecar. ``blocks`` is the per-block StructuredBlock
        list our chunker consumes.
        """
        try:
            # Local import — keeps the package importable when marker-pdf
            # is not installed (env var unset / user opted out).
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
            from marker.output import text_from_rendered
        except ImportError as exc:
            raise MarkerUnavailable(
                "marker-pdf is not installed. Run `pip install marker-pdf` "
                "to enable structured PDF parsing. Falling back to PyMuPDF."
            ) from exc

        # marker's PdfConverter takes a model dict (lazy-loaded weights on
        # first use, then cached). The first call after install may take
        # ~30s while ~1.5GB of weights download — documented in plan §8.
        try:
            converter = PdfConverter(
                artifact_dict=create_model_dict(),
                config={"output_format": "chunks"},
            )
            rendered = converter(str(source_path))
        except (OSError, RuntimeError, ValueError, TypeError, ImportError) as exc:
            # Mirror PyMuPDFBackend's exception envelope — upload layer
            # treats marker failures the same as PyMuPDF failures (it
            # currently logs and falls back to placeholder). For now,
            # re-raise to let caller catch; future slice may wrap.
            logger.error("marker_parse_failed path=%s err=%s", source_path, exc)
            raise

        # marker's chunks output: each chunk is a dict with id/page/bbox/
        # block_type/html/markdown/metadata. Schema is checked defensively
        # so a future marker API change does not silently degrade.
        chunks_raw = self._extract_chunks(rendered)
        blocks: list[StructuredBlock] = []
        current_section: str | None = None
        for chunk in chunks_raw:
            block = self._chunk_to_block(chunk, current_section)
            if block.block_type in ("Heading", "SectionHeader", "PageHeader"):
                current_section = block.markdown.strip().lstrip("# ").strip() or current_section
            blocks.append(block)

        # Plain text projection — joined chunk markdowns, light cleanup.
        text = "\n\n".join(b.markdown.strip() for b in blocks if b.markdown and b.markdown.strip())

        # Full markdown for sidecar — try marker's text_from_rendered helper
        # first, fall back to text projection if it raises.
        try:
            markdown_full = text_from_rendered(rendered)[0]
        except (TypeError, ValueError, IndexError):
            markdown_full = text

        return text, blocks, markdown_full

    # ------------------------------------------------------------------ #
    # Internal helpers — defensive against marker upstream schema changes
    # ------------------------------------------------------------------ #

    def _extract_chunks(self, rendered: Any) -> list[dict[str, Any]]:
        """Extract the chunks list from marker's rendered output.

        marker upstream returns either a dict {"chunks": [...]} or a custom
        Pydantic model with .chunks. We tolerate both shapes.
        """
        if isinstance(rendered, dict) and "chunks" in rendered:
            return list(rendered["chunks"])
        chunks = getattr(rendered, "chunks", None)
        if chunks is not None:
            return list(chunks)
        # Fallback: rendered itself may be the list
        if isinstance(rendered, list):
            return rendered
        logger.warning(
            "marker_unexpected_render_shape type=%s — returning empty chunks",
            type(rendered).__name__,
        )
        return []

    def _chunk_to_block(
        self,
        chunk: Any,
        current_section: str | None,
    ) -> StructuredBlock:
        """Project one marker chunk dict to our StructuredBlock."""
        if isinstance(chunk, dict):
            getter = chunk.get
        else:
            # Pydantic model — wrap getattr
            def getter(key: str, default: Any = None) -> Any:
                return getattr(chunk, key, default)

        block_id = str(getter("id") or getter("block_id") or "")
        page_raw = getter("page") or getter("page_number") or 0
        try:
            page = int(page_raw)
        except (TypeError, ValueError):
            page = 0
        bbox_raw = getter("bbox") or getter("polygon")
        bbox = self._coerce_bbox(bbox_raw)
        block_type = str(getter("block_type") or getter("type") or "Text")
        markdown = str(getter("markdown") or getter("text") or "")
        html = getter("html")
        if html is not None:
            html = str(html)
        image_paths = self._coerce_image_paths(getter("images") or getter("image_paths"))
        table_csv = getter("table_csv") or getter("csv")
        if table_csv is not None:
            table_csv = str(table_csv)
        equation_latex = getter("latex") or getter("equation_latex")
        if equation_latex is not None:
            equation_latex = str(equation_latex)

        return StructuredBlock(
            block_id=block_id,
            page=page,
            bbox=bbox,
            block_type=block_type,
            markdown=markdown,
            html=html,
            image_paths=image_paths,
            table_csv=table_csv,
            equation_latex=equation_latex,
            section_heading=current_section,
        )

    @staticmethod
    def _coerce_bbox(value: Any) -> list[float] | None:
        """Normalize marker's bbox/polygon → [x0, y0, x1, y1] floats or None."""
        if value is None:
            return None
        try:
            if isinstance(value, dict):
                value = value.get("bbox") or value.get("polygon")
                if value is None:
                    return None
            if not isinstance(value, (list, tuple)) or len(value) < 4:
                return None
            coords = [float(v) for v in value[:4]]
            return coords
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_image_paths(value: Any) -> list[str]:
        """Normalize marker's images field → list[str]."""
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if v]
        if isinstance(value, dict):
            return [str(k) for k in value.keys()]
        return [str(value)]
