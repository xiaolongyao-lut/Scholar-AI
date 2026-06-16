# -*- coding: utf-8 -*-
"""PyMuPDF backend — byte-level identical to the legacy parser.

This backend is the DEFAULT chosen by ``get_pdf_backend()`` when the env
var ``LITASSIST_PDF_PARSER`` is unset. It MUST behave byte-level identical to
the legacy ``_extract_document_content_from_path`` PDF branch in
``literature_assistant/core/routers/resources_router/_document_extraction.py``
(L158-180 at the time of this commit), including:

  1. ``import pymupdf; pymupdf.open(str(path)); page.get_text()`` main path
  2. ``ImportError`` → fallback to ``PyPDF2.PdfReader`` + ``extract_text()``
  3. Both libs missing → user-facing placeholder string with CHINESE comma
     ``，``: ``"[PDF 文件: {filename}，需安装 pymupdf 或 PyPDF2 才能提取文本]"``
  4. Parse failure (OSError / RuntimeError / TypeError / ValueError) →
     placeholder: ``"[PDF 解析失败: {exc}]"``

Returns ``(text, None, None)`` — no blocks, no full markdown.

The placeholder strings are byte-level locked by
``tests/test_pdf_backends.py::test_pymupdf_backend_returns_placeholder_*``
and any change to them is a contract break.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import PDFParserBackend, StructuredBlock  # noqa: F401  (Protocol attached)


__all__ = ["PyMuPDFBackend"]

logger = logging.getLogger("PyMuPDFBackend")


class PyMuPDFBackend:
    """PyMuPDF/PyPDF2 backend — default, byte-level identical to legacy."""

    name = "pymupdf"
    supports_blocks = False

    def parse(
        self,
        source_path: Path,
    ) -> tuple[str, list[StructuredBlock] | None, str | None]:
        """Extract plain text from ``source_path``.

        Returns ``(text, None, None)``. ``text`` follows the four-branch
        contract above; blocks and full markdown are always None for this
        backend.

        The filename used in placeholder strings is ``source_path.name`` —
        legacy ``_extract_document_content_from_path`` passes a separate
        ``filename`` argument, but at the backend layer the caller-facing
        identity is the file's basename. Upload layer's
        ``_extract_document_payload_from_path`` will forward ``filename``
        verbatim into legacy code paths where needed.
        """
        filename = source_path.name
        try:
            try:
                import pymupdf  # PyMuPDF (fitz)
                doc = pymupdf.open(str(source_path))
                try:
                    pages = [page.get_text() for page in doc]
                finally:
                    doc.close()
                text = "\n\n".join(pages)
            except ImportError:
                try:
                    from PyPDF2 import PdfReader
                    with source_path.open("rb") as fh:
                        reader = PdfReader(fh)
                        pages = [page.extract_text() or "" for page in reader.pages]
                    text = "\n\n".join(pages)
                except ImportError:
                    text = (
                        f"[PDF 文件: {filename}，需安装 pymupdf 或 PyPDF2 才能提取文本]"
                    )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            text = f"[PDF 解析失败: {exc}]"

        return text, None, None

    def parse_batch(
        self,
        source_paths: list[Path],
        max_workers: int | None = None,
    ) -> list[tuple[str, list[StructuredBlock] | None, str | None] | Exception]:
        """批量解析多个 PDF 文件（纯 CPU 并发）。

        使用 ThreadPoolExecutor 多线程并发处理，适合 I/O 密集型任务。

        Args:
            source_paths: PDF 文件路径列表
            max_workers: 并发工作线程数（默认 CPU 核心数，可通过 PYMUPDF_BATCH_MAX_WORKERS 环境变量覆盖）

        Returns:
            结果列表，成功返回 (text, None, None)，失败返回 Exception
        """
        import os

        if not source_paths:
            return []

        if max_workers is None:
            max_workers = int(
                os.environ.get("PYMUPDF_BATCH_MAX_WORKERS", str(os.cpu_count() or 4))
            )

        total = len(source_paths)
        logger.info(
            "pymupdf_batch_start total=%d max_workers=%d",
            total,
            max_workers,
        )

        results: list[
            tuple[str, list[StructuredBlock] | None, str | None] | Exception
        ] = [None] * total  # type: ignore
        completed = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(self.parse, path): idx
                for idx, path in enumerate(source_paths)
            }

            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                path = source_paths[idx]
                try:
                    result = future.result()
                    results[idx] = result
                    completed += 1
                    # 每 10% 输出进度
                    if (
                        completed == 1
                        or completed == total
                        or completed % max(1, total // 10) == 0
                    ):
                        logger.info(
                            "pymupdf_batch_progress completed=%d/%d",
                            completed,
                            total,
                        )
                except Exception as exc:
                    results[idx] = exc
                    completed += 1
                    logger.error(
                        "pymupdf_batch_failed completed=%d/%d path=%s err=%s",
                        completed,
                        total,
                        path.name,
                        exc,
                    )

        logger.info("pymupdf_batch_complete total=%d", total)
        return results
