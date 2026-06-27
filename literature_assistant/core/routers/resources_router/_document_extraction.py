# -*- coding: utf-8 -*-
"""Pure document-content extraction helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import cast

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
