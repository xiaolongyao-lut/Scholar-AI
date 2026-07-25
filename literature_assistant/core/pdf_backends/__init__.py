# -*- coding: utf-8 -*-
"""PDF parser backend abstraction.

Provides a backend Protocol for the active PyMuPDF parser and lightweight
contracts for optional OCR engines. Heavy OCR runtimes are discovered lazily
and do not participate in the default get_pdf_backend() flow.

Public API:
    PDFParserBackend        : Protocol; .parse(path) -> (text, blocks?, md?)
    PDFParseResult          : typed values plus actual parser provenance
    parse_pdf_with_provenance: compatibility adapter for typed/legacy backends
    get_pdf_backend(env=None): factory returning the active backend instance
    RemoteDocumentParseBackend: remote document parse backend
    DocumentParseProvider: provider config for remote backends

Default behavior:
    PyMuPDFBackend, byte-level compatible with the legacy PDF branch.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Protocol, cast


__all__ = [
    "ENV_VAR",
    "PDFParseResult",
    "PDFParserBackend",
    "PDFParserBackendWithProvenance",
    "PDFParserOutcome",
    "PDFParserProvenance",
    "PDFParserVersionSource",
    "StructuredBlock",
    "get_pdf_backend",
    "parse_pdf_with_provenance",
    "RemoteDocumentParseBackend",
    "DocumentParseProvider",
    "create_mineru_provider",
    "create_mistral_provider",
    "OCR_POLICY_ENV_VAR",
    "OCR_ENGINE_ENV_VAR",
    "OCR_LANGUAGE_ENV_VAR",
    "OcrEngine",
    "OcrEngineHealth",
    "OcrEngineInfo",
    "OcrIngestionReport",
    "OcrReadinessStatus",
    "OcrRuntimeConfig",
    "apply_pdf_ocr_if_needed",
    "build_ocr_engine",
    "clear_ocr_engines_for_tests",
    "list_ocr_engine_info",
    "list_ocr_engine_names",
    "load_builtin_ocr_engines",
    "infer_remote_ocr_provider",
    "ocr_engine_next_safe_local_actions",
    "public_ocr_status",
    "register_ocr_engine",
    "remote_ocr_endpoint_path",
    "resolve_ocr_runtime_config",
    "select_ocr_engine",
    "write_ocr_runtime_config",
]


# Environment variable name used to pick the active backend at runtime.
# Documented user contract — do not rename without an OPEN_THREADS entry.
ENV_VAR = "LITASSIST_PDF_PARSER"

_LEGACY_BACKEND_CONTRACT = "scholar-ai.pdf-parser.legacy-three-tuple/v1"
_PROVENANCE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,79}$")
_PROVENANCE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}$")
_PROVENANCE_CONTRACT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,159}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

PDFParserVersionSource = Literal["module", "distribution", "unknown", "unavailable"]
PDFParserOutcome = Literal["succeeded", "failed", "unknown", "unavailable"]


@dataclass(frozen=True)
class StructuredBlock:
    """Single structural block emitted by a structure-aware optional backend.

    PyMuPDFBackend never produces these and returns ``blocks=None``. Optional
    external parsers may adapt their output to this shape before entering the
    chunking pipeline.

    Attributes:
        block_id: Stable id within the source document.
        page: 1-indexed page number.
        bbox: Four coordinates in the parser's declared coordinate system, or
            None when unknown. ``bbox_unit`` is required before consumers may
            use the rectangle for an exact jump.
        bbox_unit: Explicit coordinate unit for ``bbox``. ``None`` means the
            parser did not establish a safe unit and downstream must degrade
            to page/chunk identity.
        block_type: One of {"Text", "Paragraph", "Heading", "Table",
            "Equation", "FigureCaption", "Code", "ListItem", "Image"}.
            Unknown types fall back to "Text" downstream.
        markdown: Markdown-formatted content for this block (may contain
            LaTeX ``$...$$`` for equations, ``| col |`` for tables, etc.).
        html: Raw HTML for this block from a structured parser (best for table
            preservation if downstream needs structure beyond markdown).
        image_paths: Relative paths to images extracted by a structured parser (figure_caption
            blocks point at the figure; image blocks point at themselves).
        figure_id: Stable figure identifier for caption blocks.
        table_id: Stable table identifier for table/caption blocks.
        linked_figure_ids: Stable figure identifiers mentioned by this block.
            Narrative blocks use these as retrieval/context links only.
        linked_table_ids: Stable table identifiers mentioned by this block.
            Narrative blocks use these as retrieval/context links only.
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
    figure_id: str | None = None
    table_id: str | None = None
    linked_figure_ids: list[str] = field(default_factory=list)
    linked_table_ids: list[str] = field(default_factory=list)
    table_csv: str | None = None
    equation_latex: str | None = None
    section_heading: str | None = None
    bbox_unit: str | None = None


@dataclass(frozen=True)
class PDFParserProvenance:
    """Bounded identity of the parser implementation used for one PDF parse.

    Attributes:
        backend_name: Stable backend wrapper name selected by the caller.
        parser_name: Actual dependency branch that produced the result, such as
            ``pymupdf`` or ``pypdf2``; ``unknown`` and ``unavailable`` are
            explicit sentinels rather than inferred versions.
        parser_version: Dependency version from the loaded module or installed
            distribution metadata, or the explicit ``unknown`` / ``unavailable``
            sentinel when no reliable value exists.
        parser_version_source: Trusted source used for ``parser_version``.
        backend_contract: Versioned behavioral contract implemented by the
            backend wrapper. This is not a dependency version.
        backend_fingerprint: SHA-256 of the backend implementation source, or
            ``unavailable`` when a legacy third-party backend cannot expose one.
        outcome: Whether the selected parser succeeded, failed, was unavailable,
            or cannot be determined for a legacy backend.
        attempted_parsers: Ordered, bounded parser/backend names attempted for
            this result, including fallback paths.
    """

    backend_name: str
    parser_name: str
    parser_version: str
    parser_version_source: PDFParserVersionSource
    backend_contract: str
    backend_fingerprint: str
    outcome: PDFParserOutcome
    attempted_parsers: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject malformed or potentially sensitive provenance values."""

        for field_name, value in (
            ("backend_name", self.backend_name),
            ("parser_name", self.parser_name),
        ):
            if not isinstance(value, str) or _PROVENANCE_TOKEN_RE.fullmatch(value) is None:
                raise ValueError(f"{field_name} must be a bounded parser identifier")
        if (
            not isinstance(self.parser_version, str)
            or _PROVENANCE_VERSION_RE.fullmatch(self.parser_version) is None
        ):
            raise ValueError("parser_version must be a bounded version identifier")
        if self.parser_version_source not in (
            "module",
            "distribution",
            "unknown",
            "unavailable",
        ):
            raise ValueError("unsupported parser_version_source")
        if self.parser_version_source == "unknown" and self.parser_version != "unknown":
            raise ValueError("unknown parser versions must use the explicit unknown sentinel")
        if (
            self.parser_version_source == "unavailable"
            and self.parser_version != "unavailable"
        ):
            raise ValueError(
                "unavailable parser versions must use the explicit unavailable sentinel"
            )
        if self.parser_version_source in ("module", "distribution") and self.parser_version in (
            "unknown",
            "unavailable",
        ):
            raise ValueError("trusted parser version sources require a real version")
        if (
            not isinstance(self.backend_contract, str)
            or _PROVENANCE_CONTRACT_RE.fullmatch(self.backend_contract) is None
        ):
            raise ValueError("backend_contract must be a bounded contract identifier")
        if self.backend_fingerprint != "unavailable" and (
            not isinstance(self.backend_fingerprint, str)
            or _SHA256_RE.fullmatch(self.backend_fingerprint) is None
        ):
            raise ValueError("backend_fingerprint must be sha256:<64 lowercase hex>")
        if self.outcome not in ("succeeded", "failed", "unknown", "unavailable"):
            raise ValueError("unsupported parser outcome")
        if not isinstance(self.attempted_parsers, tuple) or not (
            1 <= len(self.attempted_parsers) <= 8
        ):
            raise ValueError("attempted_parsers must contain between one and eight entries")
        if any(
            not isinstance(value, str) or _PROVENANCE_TOKEN_RE.fullmatch(value) is None
            for value in self.attempted_parsers
        ):
            raise ValueError("attempted_parsers contains an invalid parser identifier")

    def with_prior_attempt(self, parser_name: object) -> "PDFParserProvenance":
        """Return a copy that records one earlier failed backend attempt.

        Args:
            parser_name: Untrusted backend name. Values outside the bounded
                identifier grammar are replaced with ``unknown`` so diagnostics,
                paths, credentials, and other free text cannot enter provenance.

        Returns:
            New immutable provenance with the prior attempt prepended once.
        """

        normalized = _safe_provenance_token(parser_name)
        attempts = self.attempted_parsers
        if attempts[0] != normalized:
            attempts = (normalized, *attempts[:7])
        return replace(self, attempted_parsers=attempts)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe provenance payload for durable material state."""

        return {
            "backend_name": self.backend_name,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "parser_version_source": self.parser_version_source,
            "backend_contract": self.backend_contract,
            "backend_fingerprint": self.backend_fingerprint,
            "outcome": self.outcome,
            "attempted_parsers": list(self.attempted_parsers),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "PDFParserProvenance":
        """Validate a provenance payload read from a durable document store.

        Args:
            value: Mapping previously produced by :meth:`to_dict`.

        Returns:
            Strict immutable parser provenance.

        Raises:
            TypeError: If the input is not mapping-like.
            ValueError: If fields are missing, extra, or malformed.
        """

        if not isinstance(value, Mapping):
            raise TypeError("parser provenance must be a mapping")
        expected = {
            "backend_name",
            "parser_name",
            "parser_version",
            "parser_version_source",
            "backend_contract",
            "backend_fingerprint",
            "outcome",
            "attempted_parsers",
        }
        if set(value) != expected:
            raise ValueError("parser provenance fields do not match the v1 contract")
        attempted = value["attempted_parsers"]
        if isinstance(attempted, (str, bytes)) or not isinstance(attempted, (list, tuple)):
            raise ValueError("attempted_parsers must be a sequence")
        return cls(
            backend_name=str(value["backend_name"]),
            parser_name=str(value["parser_name"]),
            parser_version=str(value["parser_version"]),
            parser_version_source=cast(
                PDFParserVersionSource,
                str(value["parser_version_source"]),
            ),
            backend_contract=str(value["backend_contract"]),
            backend_fingerprint=str(value["backend_fingerprint"]),
            outcome=cast(PDFParserOutcome, str(value["outcome"])),
            attempted_parsers=tuple(str(item) for item in attempted),
        )


@dataclass(frozen=True)
class PDFParseResult:
    """Typed PDF parse result with provenance beside the legacy three-tuple.

    Attributes:
        text: Plain text content with the legacy backend's exact byte behavior.
        blocks: Optional structured blocks.
        markdown_full: Optional full-document markdown.
        provenance: Actual parser branch and backend implementation identity.
    """

    text: str
    blocks: list[StructuredBlock] | None
    markdown_full: str | None
    provenance: PDFParserProvenance

    def __post_init__(self) -> None:
        """Validate values crossing the backend boundary."""

        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if self.blocks is not None and not isinstance(self.blocks, list):
            raise TypeError("blocks must be a list or None")
        if self.markdown_full is not None and not isinstance(self.markdown_full, str):
            raise TypeError("markdown_full must be a string or None")
        if not isinstance(self.provenance, PDFParserProvenance):
            raise TypeError("provenance must be PDFParserProvenance")

    def legacy_tuple(self) -> tuple[str, list[StructuredBlock] | None, str | None]:
        """Return the existing ``parse()`` contract without provenance.

        Returns:
            ``(text, blocks, markdown_full)`` with values unchanged.
        """

        return self.text, self.blocks, self.markdown_full


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


class PDFParserBackendWithProvenance(PDFParserBackend, Protocol):
    """Optional extension for backends that can report reliable provenance."""

    def parse_with_provenance(self, source_path: Path) -> PDFParseResult:
        """Parse ``source_path`` and report the actual implementation used.

        Args:
            source_path: Local PDF path accepted by the backend.

        Returns:
            Typed result containing the legacy values and bounded provenance.
        """
        ...


def _safe_provenance_token(value: object) -> str:
    """Normalize an untrusted backend label without retaining free text."""

    if not isinstance(value, str):
        return "unknown"
    normalized = value.strip()
    if _PROVENANCE_TOKEN_RE.fullmatch(normalized) is None:
        return "unknown"
    return normalized


def parse_pdf_with_provenance(
    backend: PDFParserBackend,
    source_path: Path,
) -> PDFParseResult:
    """Invoke a PDF backend through the typed provenance extension when present.

    Legacy third-party backends remain usable. Because their dependency version
    and implementation fingerprint cannot be established reliably from the
    three-tuple contract, those fields are explicitly ``unknown`` and
    ``unavailable`` instead of being guessed from arbitrary object attributes.

    Args:
        backend: Selected PDF backend instance.
        source_path: Local PDF path passed through unchanged.

    Returns:
        Typed parse result. Its legacy values are exactly those emitted by the
        selected backend.

    Raises:
        TypeError: If inputs or an advertised typed result are invalid.
        OSError: Propagated when the selected backend does not handle it.
        RuntimeError: Propagated when the selected backend does not handle it.
        ValueError: Propagated when the selected backend does not handle it.
    """

    if not isinstance(source_path, Path):
        raise TypeError("source_path must be a pathlib.Path")
    typed_parse = getattr(backend, "parse_with_provenance", None)
    if callable(typed_parse):
        result = typed_parse(source_path)
        if not isinstance(result, PDFParseResult):
            raise TypeError("parse_with_provenance must return PDFParseResult")
        return result

    text, blocks, markdown_full = backend.parse(source_path)
    backend_name = _safe_provenance_token(getattr(backend, "name", "unknown"))
    return PDFParseResult(
        text=text,
        blocks=blocks,
        markdown_full=markdown_full,
        provenance=PDFParserProvenance(
            backend_name=backend_name,
            parser_name=backend_name,
            parser_version="unknown",
            parser_version_source="unknown",
            backend_contract=_LEGACY_BACKEND_CONTRACT,
            backend_fingerprint="unavailable",
            outcome="unknown",
            attempted_parsers=(backend_name,),
        ),
    )


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


# 导入远程文档解析后端（不参与默认 factory）
from .remote_document_parse_backend import (
    RemoteDocumentParseBackend,
    DocumentParseProvider,
    create_mineru_provider,
    create_mistral_provider,
)
from .ocr_engine import (
    OcrEngine,
    OcrEngineHealth,
    OcrEngineInfo,
    OcrReadinessStatus,
    OcrRuntimeConfig,
)
from .ocr_ingestion import OcrIngestionReport, apply_pdf_ocr_if_needed
from .ocr_credential_config import (
    infer_remote_ocr_provider,
    remote_ocr_endpoint_path,
)
from .ocr_engine_registry import (
    OCR_ENGINE_ENV_VAR,
    OCR_LANGUAGE_ENV_VAR,
    OCR_POLICY_ENV_VAR,
    build_ocr_engine,
    clear_ocr_engines_for_tests,
    list_ocr_engine_info,
    list_ocr_engine_names,
    load_builtin_ocr_engines,
    ocr_engine_next_safe_local_actions,
    public_ocr_status,
    register_ocr_engine,
    resolve_ocr_runtime_config,
    select_ocr_engine,
    write_ocr_runtime_config,
)
