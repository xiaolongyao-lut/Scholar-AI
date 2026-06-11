from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EnrichedChunk:
    """Per-chunk record produced by the structure-aware chunker.

    Field stability contract (see docs/plans/active/2026-06-11-marker-pdf-rag-pipeline-plan.md §1.4):

    - Existing 12 fields (chunk_id through keywords) MUST NOT change type,
      default, or removal. ``page`` stays ``int = 0`` (not Optional) — some
      downstream code uses ``chunk.page > 0`` checks.
    - 5 new fields (bbox, section_path, image_paths, table_csv,
      equation_latex) are all Optional with default None. They are populated
      ONLY by the marker-backend chunking path; the legacy PyMuPDF path
      MUST NOT serialize them (see _chunk_text._chunk_document — default
      path's output dict key set is unchanged).
    - No ``from_dict`` / ``to_dict`` methods are added. The project's chunk
      JSONL roundtrip uses plain dicts: chunks are written as dict literals
      by ``_chunk_document`` and read back as dicts; downstream callers use
      ``chunk.get("bbox") -> None`` style access. Old chunks without the new
      keys keep working unchanged.
    """

    chunk_id: str
    material_id: str
    title: str
    section_title: str
    chunk_index: int
    content: str
    raw_content: str
    chunk_type: str
    char_count: int
    page: int = 0
    embedding: list[float] | None = None
    keywords: list[str] | None = None
    # New Optional fields (marker backend only — PyMuPDF path leaves these as
    # field defaults and does NOT serialize the keys; see plan §1.5).
    bbox: list[float] | None = None
    section_path: list[str] | None = None
    image_paths: list[str] | None = None
    table_csv: str | None = None
    equation_latex: str | None = None
