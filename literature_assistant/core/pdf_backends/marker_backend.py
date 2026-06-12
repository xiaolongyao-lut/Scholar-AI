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
    "Footnote": "narrative",  # 2026-06-12 真实 reparse 实测出现,语义同正文
    "PageFooter": "narrative",  # 页脚噪声较大,但映射给 narrative,后续 retriever 加权阶段可降权
    "Table": "table",
    "TableGroup": "table",  # marker 1.10.2 实际产出
    "Equation": "formula",
    "Formula": "formula",
    "FigureCaption": "figure_caption",
    "Caption": "figure_caption",
    "TableCaption": "figure_caption",
    "FigureGroup": "figure_caption",  # 2026-06-12 真实 reparse 实测,图组的语义代理
    "PictureGroup": "figure_caption",  # 同上
    "List": "list",
    "ListItem": "list",
    "ListGroup": "list",  # 2026-06-12 真实 reparse 实测,列表组
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

        # marker 1.10.2: PdfConverter accepts ``renderer`` as a fully-qualified
        # class path (resolved via ``strings_to_classes``). The default is
        # ``MarkdownRenderer`` which returns a ``MarkdownOutput`` pydantic
        # model — we want ``ChunkRenderer`` which returns ``ChunkOutput`` with
        # a ``blocks`` list of ``FlatBlockOutput`` (id/block_type/html/page/
        # bbox/section_hierarchy/images). The model dict is lazy-loaded on
        # first use (~30s while ~1.5GB of weights download — documented in
        # plan §8).
        # Also fetch a markdown-rendered version separately for the sidecar
        # (chunks renderer outputs HTML per block but no full markdown).
        try:
            chunk_converter = PdfConverter(
                artifact_dict=create_model_dict(),
                renderer="marker.renderers.chunk.ChunkRenderer",
            )
            chunk_rendered = chunk_converter(str(source_path))

            md_converter = PdfConverter(
                artifact_dict=create_model_dict(),
                # MarkdownRenderer is the default — passing None preserves it
            )
            md_rendered = md_converter(str(source_path))
        except (OSError, RuntimeError, ValueError, TypeError, ImportError) as exc:
            # Mirror PyMuPDFBackend's exception envelope — upload layer
            # treats marker failures the same as PyMuPDF failures (it
            # currently logs and falls back to placeholder). For now,
            # re-raise to let caller catch; future slice may wrap.
            logger.error("marker_parse_failed path=%s err=%s", source_path, exc)
            raise

        # marker's chunks output: ChunkOutput.blocks is a list of
        # FlatBlockOutput pydantic models with fields
        # ``id / block_type / html / page / polygon / bbox /
        # section_hierarchy / images``. There is no per-block markdown —
        # we derive it from html via a light bs4-free strip for now.
        # Future slice may render block markdown via marker's renderer
        # registry when blocks are needed for downstream LLM context.
        chunks_raw = self._extract_chunks(chunk_rendered)
        blocks: list[StructuredBlock] = []
        current_section: str | None = None
        for chunk in chunks_raw:
            block = self._chunk_to_block(chunk, current_section)
            if block.block_type in ("Heading", "SectionHeader", "PageHeader"):
                current_section = block.markdown.strip().lstrip("# ").strip() or current_section
            blocks.append(block)

        # Plain text projection — joined chunk markdowns, light cleanup.
        text = "\n\n".join(b.markdown.strip() for b in blocks if b.markdown and b.markdown.strip())

        # Full markdown for sidecar — from the MarkdownRenderer-driven pass.
        try:
            markdown_full = text_from_rendered(md_rendered)[0]
        except (TypeError, ValueError, IndexError):
            markdown_full = text

        return text, blocks, markdown_full

    # ------------------------------------------------------------------ #
    # Internal helpers — defensive against marker upstream schema changes
    # ------------------------------------------------------------------ #

    def _extract_chunks(self, rendered: Any) -> list[Any]:
        """Extract the per-block list from marker's ChunkRenderer output.

        marker 1.10.2 returns ``ChunkOutput(blocks=List[FlatBlockOutput],
        page_info, metadata)``. We tolerate both:
          - the Pydantic ``ChunkOutput`` (preferred — has ``.blocks``)
          - a raw dict with ``"blocks"`` key
          - a raw list of blocks (defensive)
        Falls back to empty list with a warning if shape is unexpected so a
        future upstream rename does not silently degrade downstream chunking.
        """
        blocks_attr = getattr(rendered, "blocks", None)
        if blocks_attr is not None:
            return list(blocks_attr)
        if isinstance(rendered, dict) and "blocks" in rendered:
            return list(rendered["blocks"])
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
        """Project one marker FlatBlockOutput to our StructuredBlock.

        marker 1.10.2 ``FlatBlockOutput`` fields:
          - id: str (e.g. "/page/0/Block/12")
          - block_type: str (e.g. "Text", "Heading", "Table", "Equation", ...)
          - html: str (HTML for the block; for blocks with children it's
            the recursively-assembled HTML)
          - page: int
          - polygon: List[List[float]] (4 corner points)
          - bbox: List[float] ([x0,y0,x1,y1])
          - section_hierarchy: Dict[int, str] | None
          - images: dict | None

        Since FlatBlockOutput has no ``markdown`` field, we derive a markdown-
        ish text from html (strip tags). For richer markdown semantics
        downstream callers should consult ``markdown_full`` (sidecar).
        """
        # Pydantic models: use getattr; dicts: use .get
        if isinstance(chunk, dict):
            getter = chunk.get
        else:
            def getter(key: str, default: Any = None) -> Any:
                return getattr(chunk, key, default)

        block_id = str(getter("id") or "")
        page_raw = getter("page") or 0
        try:
            page = int(page_raw)
        except (TypeError, ValueError):
            page = 0
        bbox = self._coerce_bbox(getter("bbox") or getter("polygon"))
        block_type = str(getter("block_type") or "Text")
        html_str = getter("html") or ""
        if html_str is not None:
            html_str = str(html_str)
        # Derive plain markdown from html (light strip — preserves text but
        # drops tag noise). Full structural markdown is in markdown_full.
        markdown_text = self._html_to_markdown_lite(html_str)
        image_paths = self._coerce_image_paths(getter("images"))
        # section_hierarchy is dict[int, str] of (level → heading). Pick the
        # most-recent-level heading as the running section name.
        section_hierarchy = getter("section_hierarchy")
        if isinstance(section_hierarchy, dict) and section_hierarchy:
            try:
                highest_level = max(section_hierarchy.keys())
                section_heading = str(section_hierarchy[highest_level])
            except (ValueError, TypeError):
                section_heading = current_section
        else:
            section_heading = current_section

        return StructuredBlock(
            block_id=block_id,
            page=page,
            bbox=bbox,
            block_type=block_type,
            markdown=markdown_text,
            html=html_str,
            image_paths=image_paths,
            table_csv=None,  # FlatBlockOutput has no table_csv field
            equation_latex=None,  # FlatBlockOutput has no equation_latex field
            section_heading=section_heading,
        )

    @staticmethod
    def _html_to_markdown_lite(html_str: str) -> str:
        """Light HTML → markdown-ish text strip.

        Not a full HTML→MD converter — strips tags and preserves text. For
        full markdown (with table/equation formatting) the upload layer
        falls back to ``markdown_full`` (from MarkdownRenderer).
        """
        if not html_str:
            return ""
        import re

        # Preserve heading marker, line breaks, list bullets — minimal.
        text = re.sub(r"<br\s*/?>", "\n", html_str)
        text = re.sub(r"</p>", "\n\n", text)
        text = re.sub(r"</li>", "\n", text)
        text = re.sub(r"<li[^>]*>", "- ", text)
        text = re.sub(r"<[^>]+>", "", text)
        # Unescape common HTML entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'")
        return text.strip()

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
