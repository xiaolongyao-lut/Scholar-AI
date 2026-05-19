# -*- coding: utf-8 -*-
"""Pure document-content extraction helpers (Phase 2)."""

from __future__ import annotations

import json


__all__ = [
    "_extract_document_content",
    "_truncate_document_content",
]


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


def _truncate_document_content(content: str) -> str:
    """Limit oversized extracted text so upload responses stay stable."""
    max_content_len = 200_000
    if len(content) <= max_content_len:
        return content
    return content[:max_content_len] + f"\n\n[...文档内容已截断，总长度 {len(content)} 字符]"

