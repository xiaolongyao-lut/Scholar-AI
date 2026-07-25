"""Authoritative material revision construction and downstream synchronization.

The revision ledger remains independent from each downstream database. This
module is the explicit coordinator used only by real material persistence and
in-place mutation paths. It never promotes candidates or writes Wiki pages.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from literature_assistant.core.chat.history_store import (
    ChatHistoryStore,
    default_chat_history_db_path,
)
from literature_assistant.core.chat.visual_observation import (
    VisualObservationSourceRevisionApplyRequest,
    VisualObservationSourceRevisionIdentity,
    visual_material_source_binding_fingerprint,
)
from literature_assistant.core.chunk_hashing import (
    CHUNK_HASH_VERSION,
    compute_chunk_store_version,
)
from literature_assistant.core.chunk_size_guard import hard_max_chars, hard_max_tokens
from literature_assistant.core.knowledge_graph.citation_lifecycle import (
    CitationSourceRevisionIdentity,
)
from literature_assistant.core.knowledge_graph.citation_store import (
    CitationCandidateStore,
)
from literature_assistant.core.knowledge_graph.reviewed_knowledge_source_sync import (
    mark_material_revision_changed,
)
from literature_assistant.core.material_revision import (
    MATERIAL_SYNC_COMPONENTS,
    MaterialComponentRevision,
    MaterialRevisionHead,
    MaterialRevisionIdentity,
    MaterialRevisionStore,
    MaterialRevisionSyncReceipt,
    MaterialRevisionValueState,
    MaterialSyncComponent,
    MaterialSyncProgressOutcome,
)
from literature_assistant.core.pdf_backends import PDFParserProvenance
from literature_assistant.core.pdf_backends.ocr_ingestion import OcrIngestionReport
from literature_assistant.core.project_paths import project_data_path

MATERIAL_REVISION_SYNC_ACTOR = "system:material-revision"
MATERIAL_REVISION_SYNC_REASON = (
    "The authoritative material processing revision changed; derived records "
    "require revalidation."
)

_CORE_DIR = Path(__file__).resolve().parent
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_OCR_REVISION_FIELDS = frozenset(
    {
        "strategy",
        "candidate_pages",
        "applied_pages",
        "engine_name",
        "engine_implementation_fingerprint",
        "config_fingerprint",
        "output_sha256",
    }
)


class _ParserProvenanceLike(Protocol):
    def to_dict(self) -> Mapping[str, object]: ...


class _OcrRevisionReportLike(Protocol):
    def revision_payload(self) -> Mapping[str, object]: ...


class MaterialRevisionSyncError(RuntimeError):
    """Raised after a downstream failure has been recorded on the receipt."""

    def __init__(self, component: MaterialSyncComponent, error_code: str) -> None:
        self.component = component
        self.error_code = error_code
        super().__init__(f"{component} material revision synchronization failed")


class MaterialRevisionUnavailableError(ValueError):
    """Raised when a real revision identity cannot be built without guessing."""


class MaterialFanoutResult(BaseModel):
    """Bounded evidence returned by one downstream stale fan-out."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    component: MaterialSyncComponent
    operation_id: str = Field(min_length=1, max_length=256)
    outcome: MaterialSyncProgressOutcome
    impact_count: int = Field(ge=0, le=1_000_000)
    result_fingerprint: str = Field(min_length=71, max_length=71)

    @field_validator("operation_id")
    @classmethod
    def _operation_id(cls, value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError("operation_id has an unsupported identifier shape")
        return value

    @field_validator("result_fingerprint")
    @classmethod
    def _result_fingerprint(cls, value: str) -> str:
        normalized = value.lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("result_fingerprint must use sha256:<64 lowercase hex>")
        return normalized

    @field_validator("impact_count")
    @classmethod
    def _impact_matches_outcome(cls, value: int) -> int:
        return value

    def model_post_init(self, __context: object) -> None:
        if self.outcome == "no_op" and self.impact_count != 0:
            raise ValueError("no_op fan-out results require impact_count=0")
        if self.outcome == "applied" and self.impact_count < 1:
            raise ValueError("applied fan-out results require a positive impact_count")


class MaterialRevisionSyncResult(BaseModel):
    """Current head and durable receipt after one synchronization attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: MaterialRevisionIdentity
    receipt: MaterialRevisionSyncReceipt
    head: MaterialRevisionHead
    replayed: bool


MaterialFanoutHandler = Callable[[MaterialRevisionSyncReceipt], MaterialFanoutResult]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _validated_sha256(value: object, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise MaterialRevisionUnavailableError(
            f"{field_name} must use sha256:<64 lowercase hex>"
        )
    return normalized


def _source_file_fingerprint(relative_path: str) -> tuple[MaterialRevisionValueState, str | None]:
    path = (_CORE_DIR / relative_path).resolve()
    if _CORE_DIR not in path.parents or not path.is_file():
        return "unavailable", None
    try:
        return "known", _sha256_bytes(path.read_bytes())
    except OSError:
        return "unavailable", None


def _component_identity_fingerprint(component: MaterialComponentRevision) -> str:
    return _canonical_sha256(component.fingerprint_payload())


def serialize_parser_provenance(
    provenance: PDFParserProvenance | Mapping[str, object] | _ParserProvenanceLike | None,
) -> dict[str, object] | None:
    """Return strict JSON-safe parser provenance for the document store."""

    normalized = _coerce_parser_provenance(provenance)
    return normalized.to_dict() if normalized is not None else None


def serialize_ocr_revision_report(
    report: OcrIngestionReport | Mapping[str, object] | _OcrRevisionReportLike | None,
) -> dict[str, object] | None:
    """Return safe OCR revision evidence without warnings or credentials."""

    if report is None:
        return None
    if isinstance(report, OcrIngestionReport):
        payload = report.revision_payload()
    elif isinstance(report, Mapping):
        payload = dict(report)
    else:
        serializer = getattr(report, "revision_payload", None)
        if not callable(serializer):
            raise TypeError("ocr_report must be OcrIngestionReport, mapping, or None")
        serialized = serializer()
        if not isinstance(serialized, Mapping):
            raise TypeError("ocr_report revision_payload must return a mapping")
        payload = dict(serialized)
    return _validate_ocr_revision_payload(payload)


def _coerce_parser_provenance(
    provenance: PDFParserProvenance | Mapping[str, object] | _ParserProvenanceLike | None,
) -> PDFParserProvenance | None:
    if provenance is None:
        return None
    if isinstance(provenance, PDFParserProvenance):
        return provenance
    if isinstance(provenance, Mapping):
        return PDFParserProvenance.from_mapping(provenance)
    serializer = getattr(provenance, "to_dict", None)
    if not callable(serializer):
        raise TypeError("parser_provenance must be PDFParserProvenance, mapping, or None")
    serialized = serializer()
    if not isinstance(serialized, Mapping):
        raise TypeError("parser_provenance to_dict must return a mapping")
    return PDFParserProvenance.from_mapping(serialized)


def _validate_page_indexes(value: object, field_name: str) -> list[int]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be a sequence")
    pages: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ValueError(f"{field_name} must contain non-negative integers")
        if item not in pages:
            pages.append(item)
    return pages


def _validate_ocr_revision_payload(value: Mapping[str, object]) -> dict[str, object]:
    if set(value) != _OCR_REVISION_FIELDS:
        raise ValueError("OCR revision fields do not match the v1 contract")
    strategy = str(value.get("strategy") or "").strip()
    if not strategy or len(strategy) > 64:
        raise ValueError("OCR strategy must be a bounded identifier")
    engine_name_raw = value.get("engine_name")
    engine_name = None if engine_name_raw is None else str(engine_name_raw).strip()
    if engine_name is not None and (not engine_name or len(engine_name) > 80):
        raise ValueError("OCR engine_name must be bounded")
    hashes: dict[str, str | None] = {}
    for field_name in (
        "engine_implementation_fingerprint",
        "config_fingerprint",
        "output_sha256",
    ):
        raw = value.get(field_name)
        hashes[field_name] = None if raw is None else _validated_sha256(raw, field_name)
    return {
        "strategy": strategy,
        "candidate_pages": _validate_page_indexes(
            value.get("candidate_pages"),
            "candidate_pages",
        ),
        "applied_pages": _validate_page_indexes(
            value.get("applied_pages"),
            "applied_pages",
        ),
        "engine_name": engine_name,
        **hashes,
    }


def _parser_component(
    *,
    source_name: str,
    provenance: PDFParserProvenance | None,
    parser_output_sha256: str | None,
) -> MaterialComponentRevision:
    is_pdf = Path(source_name).suffix.lower() == ".pdf"
    if not is_pdf:
        return MaterialComponentRevision(
            component_kind="parser",
            component_name="pdf-parser-not-applicable",
            implementation_fingerprint_state="not_applicable",
            implementation_fingerprint=None,
            runtime_version_state="not_applicable",
            config_fingerprint_state="not_applicable",
            output_fingerprint_state="not_applicable",
        )
    if provenance is None:
        return MaterialComponentRevision(
            component_kind="parser",
            component_name="pdf-parser-unknown",
            implementation_fingerprint_state="unknown",
            implementation_fingerprint=None,
            runtime_version_state="unknown",
            config_fingerprint_state="unknown",
            output_fingerprint_state=("known" if parser_output_sha256 else "unknown"),
            output_fingerprint=(
                _validated_sha256(parser_output_sha256, "parser_output_sha256")
                if parser_output_sha256
                else None
            ),
        )

    implementation_state: MaterialRevisionValueState
    implementation_fingerprint: str | None
    if provenance.backend_fingerprint == "unavailable":
        implementation_state = (
            "unavailable" if provenance.parser_version_source == "unavailable" else "unknown"
        )
        implementation_fingerprint = None
    else:
        implementation_state = "known"
        implementation_fingerprint = _validated_sha256(
            provenance.backend_fingerprint,
            "backend_fingerprint",
        )
    runtime_state: MaterialRevisionValueState = cast(
        MaterialRevisionValueState,
        provenance.parser_version_source
        if provenance.parser_version_source in {"unknown", "unavailable"}
        else "known",
    )
    runtime_version = (
        provenance.parser_version if runtime_state == "known" else None
    )
    config_fingerprint = _canonical_sha256(
        {
            "backend_name": provenance.backend_name,
            "parser_name": provenance.parser_name,
            "backend_contract": provenance.backend_contract,
            "outcome": provenance.outcome,
            "attempted_parsers": list(provenance.attempted_parsers),
        }
    )
    output_fingerprint = (
        _validated_sha256(parser_output_sha256, "parser_output_sha256")
        if parser_output_sha256
        else None
    )
    return MaterialComponentRevision(
        component_kind="parser",
        component_name=f"pdf-parser:{provenance.parser_name}",
        implementation_fingerprint_state=implementation_state,
        implementation_fingerprint=implementation_fingerprint,
        runtime_version_state=runtime_state,
        runtime_version=runtime_version,
        config_fingerprint_state="known",
        config_fingerprint=config_fingerprint,
        output_fingerprint_state="known" if output_fingerprint else "unknown",
        output_fingerprint=output_fingerprint,
    )


def _extractor_component(
    *,
    extracted_text_sha256: str,
    structured_chunks: bool,
) -> MaterialComponentRevision:
    implementation_state, implementation_fingerprint = _source_file_fingerprint(
        "routers/resources_router/_document_extraction.py"
    )
    return MaterialComponentRevision(
        component_kind="extractor",
        component_name="document-extractor",
        implementation_fingerprint_state=implementation_state,
        implementation_fingerprint=implementation_fingerprint,
        runtime_version_state="known",
        runtime_version="scholar-ai-document-extraction-v1",
        config_fingerprint_state="known",
        config_fingerprint=_canonical_sha256(
            {
                "max_persisted_text_chars": 200_000,
                "structured_blocks_projected": structured_chunks,
            }
        ),
        output_fingerprint_state="known",
        output_fingerprint=extracted_text_sha256,
    )


def _ocr_component(
    *,
    is_pdf: bool,
    report: dict[str, object] | None,
) -> MaterialComponentRevision:
    if not is_pdf:
        return MaterialComponentRevision(
            component_kind="ocr",
            component_name="ocr-not-applicable",
            implementation_fingerprint_state="not_applicable",
            implementation_fingerprint=None,
            runtime_version_state="not_applicable",
            config_fingerprint_state="not_applicable",
            output_fingerprint_state="not_applicable",
        )
    if report is None:
        return MaterialComponentRevision(
            component_kind="ocr",
            component_name="ocr-unknown",
            implementation_fingerprint_state="unknown",
            implementation_fingerprint=None,
            runtime_version_state="unknown",
            config_fingerprint_state="unknown",
            output_fingerprint_state="unknown",
        )
    candidate_pages = cast(list[int], report["candidate_pages"])
    engine_name = cast(str | None, report["engine_name"])
    controller_state, controller_fingerprint = _source_file_fingerprint(
        "pdf_backends/ocr_ingestion.py"
    )
    if not candidate_pages:
        return MaterialComponentRevision(
            component_kind="ocr",
            component_name="ocr-not-applied",
            implementation_fingerprint_state=controller_state,
            implementation_fingerprint=controller_fingerprint,
            runtime_version_state="known",
            runtime_version="scholar-ai-ocr-ingestion-v1",
            config_fingerprint_state="not_applicable",
            output_fingerprint_state="not_applicable",
        )
    engine_fingerprint = cast(
        str | None,
        report["engine_implementation_fingerprint"],
    )
    config_fingerprint = cast(str | None, report["config_fingerprint"])
    output_fingerprint = cast(str | None, report["output_sha256"])
    if engine_name is None:
        return MaterialComponentRevision(
            component_kind="ocr",
            component_name="ocr-unavailable",
            implementation_fingerprint_state=controller_state,
            implementation_fingerprint=controller_fingerprint,
            runtime_version_state="unavailable",
            config_fingerprint_state="known" if config_fingerprint else "unknown",
            config_fingerprint=config_fingerprint,
            output_fingerprint_state="unavailable",
        )
    return MaterialComponentRevision(
        component_kind="ocr",
        component_name=f"ocr:{engine_name}",
        implementation_fingerprint_state="known" if engine_fingerprint else "unavailable",
        implementation_fingerprint=engine_fingerprint,
        runtime_version_state="unknown",
        config_fingerprint_state="known" if config_fingerprint else "unknown",
        config_fingerprint=config_fingerprint,
        output_fingerprint_state="known" if output_fingerprint else "unavailable",
        output_fingerprint=output_fingerprint,
    )


def _chunk_root(
    material_id: str,
    chunks: Sequence[Mapping[str, object]],
) -> tuple[str, bool]:
    if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
        raise TypeError("chunks must be a sequence of mappings")
    if not chunks:
        raise MaterialRevisionUnavailableError("material chunks must be non-empty")
    normalized: list[Mapping[str, object]] = []
    chunk_ids: set[str] = set()
    structured = False
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            raise TypeError("chunks must contain mappings")
        chunk_material = str(chunk.get("material_id") or "").strip()
        if chunk_material != material_id:
            raise ValueError("chunk material_id does not match the revision material")
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id or chunk_id in chunk_ids:
            raise ValueError("chunk_id values must be non-empty and unique")
        chunk_ids.add(chunk_id)
        structured = structured or any(
            field in chunk
            for field in (
                "bbox",
                "section_path",
                "image_paths",
                "figure_id",
                "table_id",
                "equation_latex",
            )
        )
        normalized.append(chunk)
    root = compute_chunk_store_version({material_id: normalized})
    return _validated_sha256(f"sha256:{root}", "material_chunk_root_sha256"), structured


def _chunker_component(
    *,
    material_chunk_root_sha256: str,
    structured_chunks: bool,
) -> MaterialComponentRevision:
    implementation_state, implementation_fingerprint = _source_file_fingerprint(
        "routers/resources_router/_chunk_text.py"
    )
    return MaterialComponentRevision(
        component_kind="chunker",
        component_name="resource-chunker",
        implementation_fingerprint_state=implementation_state,
        implementation_fingerprint=implementation_fingerprint,
        runtime_version_state="known",
        runtime_version="scholar-ai-resource-chunker-v1",
        config_fingerprint_state="known",
        config_fingerprint=_canonical_sha256(
            {
                "chunk_size": 800,
                "chunk_overlap": 150,
                "hard_max_chars": hard_max_chars(),
                "hard_max_tokens": hard_max_tokens(),
                "structured_chunks": structured_chunks,
                "chunk_hash_version": CHUNK_HASH_VERSION,
            }
        ),
        output_fingerprint_state="known",
        output_fingerprint=material_chunk_root_sha256,
    )


def build_material_revision_identity(
    *,
    project_id: str,
    material_id: str,
    source_name: str,
    raw_source_sha256: str,
    raw_source_size_bytes: int,
    extracted_text: str,
    chunks: Sequence[Mapping[str, object]],
    parser_provenance: (
        PDFParserProvenance | Mapping[str, object] | _ParserProvenanceLike | None
    ) = None,
    parser_output_sha256: str | None = None,
    ocr_report: (
        OcrIngestionReport | Mapping[str, object] | _OcrRevisionReportLike | None
    ) = None,
    observed_at: datetime | None = None,
) -> MaterialRevisionIdentity:
    """Build one deterministic identity from the final persisted material state.

    Args:
        project_id: Owning project identifier.
        material_id: Stable material identifier within the project.
        source_name: Bounded display/source name used only to classify PDF input.
        raw_source_sha256: Exact raw source byte fingerprint from ingestion.
        raw_source_size_bytes: Exact raw source byte count.
        extracted_text: Final text written to the document store.
        chunks: Final accepted chunks reloaded after persistence/quarantine.
        parser_provenance: Typed or JSON-restored actual PDF parser provenance.
        parser_output_sha256: Parser text hash captured before OCR post-processing.
        ocr_report: Safe OCR revision report without warning text or credentials.
        observed_at: Optional aware UTC audit time.

    Returns:
        Strict deterministic material revision identity.

    Raises:
        MaterialRevisionUnavailableError: If an authoritative source identity
            is missing and would otherwise need to be guessed.
        TypeError: If text, chunks, or provenance shapes are invalid.
        ValueError: If chunk ownership or hashes are inconsistent.
    """

    if not isinstance(extracted_text, str):
        raise TypeError("extracted_text must be a string")
    if not extracted_text:
        raise MaterialRevisionUnavailableError("extracted_text must be non-empty")
    if isinstance(raw_source_size_bytes, bool) or not isinstance(raw_source_size_bytes, int):
        raise TypeError("raw_source_size_bytes must be an integer")
    if raw_source_size_bytes < 1:
        raise MaterialRevisionUnavailableError("raw_source_size_bytes must be positive")
    normalized_source_hash = _validated_sha256(raw_source_sha256, "raw_source_sha256")
    material_chunk_root, structured_chunks = _chunk_root(material_id, chunks)
    extracted_hash = _sha256_bytes(extracted_text.encode("utf-8"))
    normalized_parser = _coerce_parser_provenance(parser_provenance)
    normalized_ocr = serialize_ocr_revision_report(ocr_report)
    timestamp = observed_at or _utc_now()
    return MaterialRevisionIdentity(
        project_id=project_id,
        material_id=material_id,
        raw_source_sha256=normalized_source_hash,
        raw_source_size_bytes=raw_source_size_bytes,
        parser=_parser_component(
            source_name=source_name,
            provenance=normalized_parser,
            parser_output_sha256=parser_output_sha256,
        ),
        extractor=_extractor_component(
            extracted_text_sha256=extracted_hash,
            structured_chunks=structured_chunks,
        ),
        ocr=_ocr_component(
            is_pdf=Path(source_name).suffix.lower() == ".pdf",
            report=normalized_ocr,
        ),
        chunker=_chunker_component(
            material_chunk_root_sha256=material_chunk_root,
            structured_chunks=structured_chunks,
        ),
        extracted_text_sha256=extracted_hash,
        material_chunk_root_sha256=material_chunk_root,
        observed_at=timestamp,
    )


def build_material_revision_from_document(
    *,
    project_id: str,
    material_id: str,
    document: Mapping[str, object],
    chunks: Sequence[Mapping[str, object]],
    observed_at: datetime | None = None,
) -> MaterialRevisionIdentity:
    """Build an identity from one validated persisted doc/chunk snapshot."""

    if not isinstance(document, Mapping):
        raise TypeError("document must be a mapping")
    source_hash = str(document.get("source_fingerprint") or "").strip()
    if not _SHA256_RE.fullmatch(source_hash.lower()):
        raise MaterialRevisionUnavailableError(
            "persisted material has no authoritative raw source SHA-256"
        )
    source_size = document.get("source_size")
    if isinstance(source_size, bool) or not isinstance(source_size, int):
        raise MaterialRevisionUnavailableError(
            "persisted material has no authoritative raw source size"
        )
    persisted_parser = document.get("parser_provenance")
    if persisted_parser is not None and not isinstance(persisted_parser, Mapping):
        raise TypeError("persisted parser_provenance must be a mapping")
    persisted_ocr = document.get("ocr_revision")
    if persisted_ocr is not None and not isinstance(persisted_ocr, Mapping):
        raise TypeError("persisted ocr_revision must be a mapping")
    return build_material_revision_identity(
        project_id=project_id,
        material_id=material_id,
        source_name=str(
            document.get("source_relative_path")
            or document.get("title")
            or material_id
        ),
        raw_source_sha256=source_hash,
        raw_source_size_bytes=source_size,
        extracted_text=str(document.get("content") or ""),
        chunks=chunks,
        parser_provenance=persisted_parser,
        parser_output_sha256=(
            str(document["parser_output_sha256"])
            if document.get("parser_output_sha256") is not None
            else None
        ),
        ocr_report=persisted_ocr,
        observed_at=observed_at,
    )


def material_revision_db_path(project_id: str) -> Path:
    """Return the canonical project-scoped material revision ledger path."""

    if not isinstance(project_id, str) or not _ID_RE.fullmatch(project_id.strip()):
        raise ValueError("project_id has an unsupported identifier shape")
    return project_data_path(
        project_id.strip(),
        "material_revision",
        "material_revision.db",
    )


def _operation_id(receipt: MaterialRevisionSyncReceipt, component: MaterialSyncComponent) -> str:
    return f"{receipt.receipt_id}:{component}:mark-stale"


def _fanout_result(
    *,
    receipt: MaterialRevisionSyncReceipt,
    component: MaterialSyncComponent,
    impact_ids: Sequence[str],
    downstream_receipt_ids: Sequence[str] = (),
) -> MaterialFanoutResult:
    normalized_impacts = tuple(sorted({str(item) for item in impact_ids if str(item)}))
    operation_id = _operation_id(receipt, component)
    payload = {
        "schema_version": "scholar-ai-material-fanout-result/v1",
        "operation_id": operation_id,
        "component": component,
        "revision_fingerprint": receipt.current_identity.revision_fingerprint,
        "impact_ids": list(normalized_impacts),
        "downstream_receipt_ids": sorted(
            {str(item) for item in downstream_receipt_ids if str(item)}
        ),
    }
    return MaterialFanoutResult(
        component=component,
        operation_id=operation_id,
        outcome="applied" if normalized_impacts else "no_op",
        impact_count=len(normalized_impacts),
        result_fingerprint=_canonical_sha256(payload),
    )


def _citation_identity(identity: MaterialRevisionIdentity) -> CitationSourceRevisionIdentity:
    return CitationSourceRevisionIdentity(
        material_id=identity.material_id,
        source_fingerprint=identity.revision_fingerprint,
        source_version=identity.raw_source_sha256,
        extractor_version=_component_identity_fingerprint(identity.extractor),
        parser_version=_component_identity_fingerprint(identity.parser),
    )


def _sync_citation(receipt: MaterialRevisionSyncReceipt) -> MaterialFanoutResult:
    db_path = project_data_path(
        receipt.project_id,
        "citation_graph",
        "citation_graph.db",
    )
    if not db_path.is_file() or db_path.stat().st_size <= 0:
        return _fanout_result(receipt=receipt, component="citation", impact_ids=())
    store = CitationCandidateStore(db_path)
    current_identity = _citation_identity(receipt.current_identity)
    preflight = store.preflight_source_revision(
        project_id=receipt.project_id,
        operation="mark_stale",
        current_identity=current_identity,
    )
    if not preflight.impacts:
        return _fanout_result(receipt=receipt, component="citation", impact_ids=())
    downstream = store.apply_source_revision(
        project_id=receipt.project_id,
        operation="mark_stale",
        current_identity=current_identity,
        expected_impact_fingerprint=preflight.impact_fingerprint,
        reason=MATERIAL_REVISION_SYNC_REASON,
        changed_by=MATERIAL_REVISION_SYNC_ACTOR,
    )
    return _fanout_result(
        receipt=receipt,
        component="citation",
        impact_ids=downstream.candidate_ids,
        downstream_receipt_ids=(downstream.receipt_id,),
    )


def _sync_visual(receipt: MaterialRevisionSyncReceipt) -> MaterialFanoutResult:
    previous = receipt.previous_identity
    current = receipt.current_identity
    if previous is None or previous.raw_source_sha256 == current.raw_source_sha256:
        return _fanout_result(receipt=receipt, component="visual", impact_ids=())
    db_path = default_chat_history_db_path()
    if not db_path.is_file() or db_path.stat().st_size <= 0:
        return _fanout_result(receipt=receipt, component="visual", impact_ids=())
    source_revision = VisualObservationSourceRevisionIdentity(
        previous_source_fingerprint=visual_material_source_binding_fingerprint(
            project_id=receipt.project_id,
            material_id=receipt.material_id,
            raw_source_sha256=previous.raw_source_sha256,
        ),
        current_source_fingerprint=visual_material_source_binding_fingerprint(
            project_id=receipt.project_id,
            material_id=receipt.material_id,
            raw_source_sha256=current.raw_source_sha256,
        ),
    )
    store = ChatHistoryStore(db_path)
    preflight = store.preflight_visual_observation_source_revision(
        project_id=receipt.project_id,
        operation="mark_stale",
        source_revision=source_revision,
    )
    candidate_ids = tuple(impact.candidate_id for impact in preflight.impacts)
    if not candidate_ids:
        return _fanout_result(receipt=receipt, component="visual", impact_ids=())
    downstream = store.apply_visual_observation_source_revision(
        VisualObservationSourceRevisionApplyRequest(
            operation_id=_operation_id(receipt, "visual"),
            project_id=receipt.project_id,
            operation="mark_stale",
            source_revision=source_revision,
            expected_impact_fingerprint=preflight.impact_fingerprint,
            validated_candidate_ids=candidate_ids,
            reason=MATERIAL_REVISION_SYNC_REASON,
            changed_by=MATERIAL_REVISION_SYNC_ACTOR,
        )
    )
    return _fanout_result(
        receipt=receipt,
        component="visual",
        impact_ids=downstream.receipt.candidate_ids,
        downstream_receipt_ids=(downstream.receipt.receipt_id,),
    )


def _sync_reviewed(receipt: MaterialRevisionSyncReceipt) -> MaterialFanoutResult:
    current = receipt.current_identity
    results = mark_material_revision_changed(
        project_id=receipt.project_id,
        material_id=receipt.material_id,
        source_fingerprint=current.revision_fingerprint,
        source_version=current.raw_source_sha256,
        extractor_version=_component_identity_fingerprint(current.extractor),
        parser_version=_component_identity_fingerprint(current.parser),
        reason=MATERIAL_REVISION_SYNC_REASON,
        changed_by=MATERIAL_REVISION_SYNC_ACTOR,
        occurred_at=_utc_now(),
    )
    return _fanout_result(
        receipt=receipt,
        component="reviewed",
        impact_ids=tuple(result.fact.fact_id for result in results),
        downstream_receipt_ids=tuple(result.receipt.receipt_id for result in results),
    )


def default_material_revision_fanout_handlers() -> dict[
    MaterialSyncComponent,
    MaterialFanoutHandler,
]:
    """Return the production stale-only fan-out handlers in canonical order."""

    return {
        "citation": _sync_citation,
        "visual": _sync_visual,
        "reviewed": _sync_reviewed,
    }


def synchronize_material_revision(
    identity: MaterialRevisionIdentity,
    *,
    store: MaterialRevisionStore | None = None,
    fanout_handlers: Mapping[MaterialSyncComponent, MaterialFanoutHandler] | None = None,
) -> MaterialRevisionSyncResult:
    """Stage, resume, and complete one material revision synchronization.

    Args:
        identity: Authoritative final material identity.
        store: Optional injected ledger for focused tests.
        fanout_handlers: Optional complete injected handler mapping.

    Returns:
        Applied receipt and current head. Initial revisions return immediately
        because no prior derived state can be stale.

    Raises:
        MaterialRevisionSyncError: If a downstream handler fails after the
            receipt has been durably marked failed with a safe error code.
        MaterialRevisionStoreError: For ledger CAS or persistence failures.
    """

    if not isinstance(identity, MaterialRevisionIdentity):
        raise TypeError("identity must be a MaterialRevisionIdentity")
    ledger = store or MaterialRevisionStore(
        material_revision_db_path(identity.project_id),
        identity.project_id,
    )
    handlers = dict(
        default_material_revision_fanout_handlers()
        if fanout_handlers is None
        else fanout_handlers
    )
    if set(handlers) != set(MATERIAL_SYNC_COMPONENTS) or any(
        not callable(handler) for handler in handlers.values()
    ):
        raise ValueError("fanout_handlers must provide citation, visual, and reviewed")

    staged = ledger.stage_revision(identity)
    receipt = staged.receipt
    if receipt.status == "applied":
        return MaterialRevisionSyncResult(
            identity=identity,
            receipt=receipt,
            head=staged.head,
            replayed=staged.replayed,
        )
    if receipt.status == "failed":
        receipt = ledger.retry_receipt(
            receipt_id=receipt.receipt_id,
            expected_version=receipt.version,
        )

    error_codes: dict[MaterialSyncComponent, str] = {
        "citation": "CITATION_SYNC_FAILED",
        "visual": "VISUAL_SYNC_FAILED",
        "reviewed": "REVIEWED_SYNC_FAILED",
    }
    for progress in receipt.component_progress:
        if progress.status == "applied":
            continue
        component = progress.component
        try:
            fanout = handlers[component](receipt)
            if fanout.component != component:
                raise ValueError("fanout result component does not match its handler")
        except Exception as exc:
            code = error_codes[component]
            ledger.fail_receipt(
                receipt_id=receipt.receipt_id,
                component=component,
                expected_version=receipt.version,
                error_code=code,
            )
            raise MaterialRevisionSyncError(component, code) from exc
        receipt = ledger.mark_component_applied(
            receipt_id=receipt.receipt_id,
            component=component,
            expected_version=receipt.version,
            outcome=fanout.outcome,
            operation_id=fanout.operation_id,
            result_fingerprint=fanout.result_fingerprint,
            impact_count=fanout.impact_count,
        )

    receipt = ledger.complete_receipt(
        receipt_id=receipt.receipt_id,
        expected_version=receipt.version,
    )
    head = ledger.get_current_head(identity.material_id)
    if head is None or head.identity.revision_fingerprint != identity.revision_fingerprint:
        raise RuntimeError("material revision completed without advancing its head")
    return MaterialRevisionSyncResult(
        identity=identity,
        receipt=receipt,
        head=head,
        replayed=staged.replayed,
    )


__all__ = [
    "MATERIAL_REVISION_SYNC_ACTOR",
    "MATERIAL_REVISION_SYNC_REASON",
    "MaterialFanoutHandler",
    "MaterialFanoutResult",
    "MaterialRevisionSyncError",
    "MaterialRevisionSyncResult",
    "MaterialRevisionUnavailableError",
    "build_material_revision_from_document",
    "build_material_revision_identity",
    "default_material_revision_fanout_handlers",
    "material_revision_db_path",
    "serialize_ocr_revision_report",
    "serialize_parser_provenance",
    "synchronize_material_revision",
]
