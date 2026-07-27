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

``parse()`` returns ``(text, None, None)``; ``parse_with_provenance()`` carries
the same values beside the actual dependency branch and version.

The placeholder strings are byte-level locked by
``tests/test_pdf_backends.py::test_pymupdf_backend_returns_placeholder_*``
and any change to them is a contract break.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from functools import lru_cache
from importlib import metadata as importlib_metadata
from pathlib import Path
from types import ModuleType
from typing import Protocol, TypeGuard

from . import (
    PDFParseResult,
    PDFParserOutcome,
    PDFParserProvenance,
    PDFParserVersionSource,
    StructuredBlock,
)


__all__ = ["PyMuPDFBackend"]

logger = logging.getLogger("PyMuPDFBackend")
_BACKEND_CONTRACT = "scholar-ai.pdf-parser.pymupdf-fallback-compat/v1"
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}$")


class _TextPage(Protocol):
    def get_text(self) -> object: ...


class _CloseableDocument(Protocol):
    def close(self) -> None: ...


class _PageIterable(Protocol):
    def __iter__(self) -> Iterator[object]: ...


class _PageSequence(Protocol):
    def __len__(self) -> int: ...

    def __getitem__(self, index: int) -> object: ...


class _PageCountLoader(Protocol):
    @property
    def page_count(self) -> int: ...

    def load_page(self, index: int) -> object: ...


def _has_page_iterator(value: object) -> TypeGuard[_PageIterable]:
    return callable(getattr(value, "__iter__", None))


def _has_page_sequence(value: object) -> TypeGuard[_PageSequence]:
    return callable(getattr(value, "__len__", None)) and callable(
        getattr(value, "__getitem__", None)
    )


def _has_page_count_loader(value: object) -> TypeGuard[_PageCountLoader]:
    page_count = getattr(value, "page_count", None)
    return (
        isinstance(page_count, int)
        and not isinstance(page_count, bool)
        and page_count >= 0
        and callable(getattr(value, "load_page", None))
    )


def _is_closeable_document(value: object) -> TypeGuard[_CloseableDocument]:
    return callable(getattr(value, "close", None))


def _is_text_page(value: object) -> TypeGuard[_TextPage]:
    return callable(getattr(value, "get_text", None))


def _read_page_text(page: object) -> str:
    """Read one page through a checked text-extraction boundary."""

    if not _is_text_page(page):
        raise TypeError("PyMuPDF page must expose callable get_text")
    text = page.get_text()
    if not isinstance(text, str):
        raise TypeError("PyMuPDF Page.get_text() must return a string")
    return text


def _call_runtime_method(
    target: object,
    method_name: str,
    *args: object,
    **kwargs: object,
) -> object:
    """Call one checked method on a partially typed dependency surface."""

    method = getattr(target, method_name, None)
    if not callable(method):
        raise TypeError(f"PyMuPDF object must expose callable {method_name}")
    result: object = method(*args, **kwargs)
    return result


def _iter_document_pages(document: object) -> Iterator[object]:
    """Preserve supported PyMuPDF iterable, sequence, and page APIs."""

    if _has_page_count_loader(document):
        for index in range(document.page_count):
            yield document.load_page(index)
        return
    if _has_page_sequence(document):
        for index in range(len(document)):
            yield document[index]
        return
    if _has_page_iterator(document):
        yield from document
        return
    raise TypeError("PyMuPDF document does not expose a supported page contract")


def _safe_dependency_version(value: object) -> str | None:
    """Return a bounded dependency version or None for unsafe free text."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if _VERSION_RE.fullmatch(normalized) is None:
        return None
    return normalized


def _resolve_dependency_version(
    module: ModuleType,
    *,
    distribution_name: str,
    module_attributes: tuple[str, ...],
) -> tuple[str, PDFParserVersionSource]:
    """Resolve a parser version from its loaded module then package metadata.

    Args:
        module: Actual module used by the parser branch.
        distribution_name: Installed distribution queried via
            ``importlib.metadata.version``.
        module_attributes: Ordered trusted module attributes that may expose a
            version string.

    Returns:
        Bounded version and its source. Missing or unsafe values return the
        explicit ``("unknown", "unknown")`` sentinel pair.
    """

    for attribute in module_attributes:
        try:
            version = _safe_dependency_version(getattr(module, attribute, None))
        except Exception:  # noqa: BLE001 - provenance must not alter parse behavior
            version = None
        if version is not None:
            return version, "module"
    try:
        version = _safe_dependency_version(importlib_metadata.version(distribution_name))
    except Exception:  # noqa: BLE001 - absent/corrupt metadata is explicitly unknown
        version = None
    if version is not None:
        return version, "distribution"
    return "unknown", "unknown"


@lru_cache(maxsize=1)
def _backend_implementation_fingerprint() -> str:
    """Hash this backend module without exposing its local source path."""

    try:
        source = Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    except OSError:
        return "unavailable"
    return f"sha256:{hashlib.sha256(source).hexdigest()}"


def _parser_provenance(
    *,
    parser_name: str,
    module: ModuleType | None,
    distribution_name: str | None,
    module_attributes: tuple[str, ...] = (),
    outcome: PDFParserOutcome,
    attempted_parsers: tuple[str, ...],
) -> PDFParserProvenance:
    """Build bounded provenance for one concrete parser branch."""

    if module is None or distribution_name is None:
        parser_version = "unavailable"
        version_source: PDFParserVersionSource = "unavailable"
    else:
        parser_version, version_source = _resolve_dependency_version(
            module,
            distribution_name=distribution_name,
            module_attributes=module_attributes,
        )
    return PDFParserProvenance(
        backend_name="pymupdf",
        parser_name=parser_name,
        parser_version=parser_version,
        parser_version_source=version_source,
        backend_contract=_BACKEND_CONTRACT,
        backend_fingerprint=_backend_implementation_fingerprint(),
        outcome=outcome,
        attempted_parsers=attempted_parsers,
    )


def _with_outcome(
    provenance: PDFParserProvenance,
    outcome: PDFParserOutcome,
) -> PDFParserProvenance:
    """Copy provenance while changing only its execution outcome."""

    return replace(provenance, outcome=outcome)


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
        return self.parse_with_provenance(source_path).legacy_tuple()

    def parse_with_provenance(self, source_path: Path) -> PDFParseResult:
        """Extract text and identify the actual dependency branch used.

        Args:
            source_path: Local PDF path. Its basename is retained only for the
                existing user-visible placeholder strings.

        Returns:
            Typed result whose text/blocks/markdown values exactly match
            ``parse()`` and whose provenance records PyMuPDF, the PyPDF2
            fallback, or the explicit unavailable branch.
        """

        filename = source_path.name
        provenance = _parser_provenance(
            parser_name="unavailable",
            module=None,
            distribution_name=None,
            outcome="unavailable",
            attempted_parsers=("pymupdf", "pypdf2"),
        )
        try:
            try:
                import pymupdf  # PyMuPDF (fitz)
                provenance = _parser_provenance(
                    parser_name="pymupdf",
                    module=pymupdf,
                    distribution_name="PyMuPDF",
                    module_attributes=("__version__", "VersionBind"),
                    outcome="succeeded",
                    attempted_parsers=("pymupdf",),
                )
                document = _call_runtime_method(pymupdf, "open", str(source_path))
                if not _is_closeable_document(document):
                    raise TypeError(
                        "PyMuPDF open() must return a closeable document"
                    )
                try:
                    pages = [
                        _read_page_text(page)
                        for page in _iter_document_pages(document)
                    ]
                finally:
                    document.close()
                text = "\n\n".join(pages)
            except ImportError:
                pypdf2_loaded = False
                try:
                    import PyPDF2
                    from PyPDF2 import PdfReader
                    pypdf2_loaded = True
                    provenance = _parser_provenance(
                        parser_name="pypdf2",
                        module=PyPDF2,
                        distribution_name="PyPDF2",
                        module_attributes=("__version__",),
                        outcome="succeeded",
                        attempted_parsers=("pymupdf", "pypdf2"),
                    )
                    with source_path.open("rb") as fh:
                        reader = PdfReader(fh)
                        pages = [page.extract_text() or "" for page in reader.pages]
                    text = "\n\n".join(pages)
                except ImportError:
                    if pypdf2_loaded:
                        provenance = _with_outcome(provenance, "failed")
                    else:
                        provenance = _parser_provenance(
                            parser_name="unavailable",
                            module=None,
                            distribution_name=None,
                            outcome="unavailable",
                            attempted_parsers=("pymupdf", "pypdf2"),
                        )
                    text = (
                        f"[PDF 文件: {filename}，需安装 pymupdf 或 PyPDF2 才能提取文本]"
                    )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            text = f"[PDF 解析失败: {exc}]"
            provenance = _with_outcome(provenance, "failed")

        return PDFParseResult(
            text=text,
            blocks=None,
            markdown_full=None,
            provenance=provenance,
        )

    def parse_batch_with_provenance(
        self,
        source_paths: list[Path],
        max_workers: int | None = None,
    ) -> list[PDFParseResult | Exception]:
        """Parse several PDFs concurrently while preserving provenance.

        使用 ThreadPoolExecutor 多线程并发处理，适合 I/O 密集型任务。

        Args:
            source_paths: PDF 文件路径列表
            max_workers: 并发工作线程数（默认 CPU 核心数，可通过 PYMUPDF_BATCH_MAX_WORKERS 环境变量覆盖）

        Returns:
            Ordered typed parse results, or the per-file exception.
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

        results: list[PDFParseResult | Exception] = [
            RuntimeError("PDF batch result was not populated") for _ in range(total)
        ]
        completed = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(self.parse_with_provenance, path): idx
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

    def parse_batch(
        self,
        source_paths: list[Path],
        max_workers: int | None = None,
    ) -> list[tuple[str, list[StructuredBlock] | None, str | None] | Exception]:
        """Return the legacy batch three-tuples without dropping typed support."""

        return [
            item.legacy_tuple() if isinstance(item, PDFParseResult) else item
            for item in self.parse_batch_with_provenance(
                source_paths,
                max_workers=max_workers,
            )
        ]
