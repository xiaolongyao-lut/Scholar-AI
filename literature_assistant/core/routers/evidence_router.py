"""Evidence chain and source labels API router - /api/evidence_refs, /api/source_labels.

Provides independent evidence_refs API with source_labels filtering (A4/A5),
chunk locator bbox support (A7), discussion evidence_pack persistence (D5),
and citation overlap detection (D8).
"""

from fastapi import APIRouter, HTTPException, Query, Response
from typing import TYPE_CHECKING, Any, Callable, List, Literal, Optional
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError
import csv
import hashlib
import io
import json
import os
import re
import uuid

from literature_assistant.core.chunk_package_quality import (
    default_joint_recall_policy,
    weighted_rrf_fuse,
    write_chunk_goldset_review_bundle,
)
from literature_assistant.core.academic_english_resources import search_academic_english
from literature_assistant.core.config_knowledge import search_scoring_rules
from literature_assistant.core.product_docs_knowledge import search_product_docs
from literature_assistant.core.source_vault import (
    SourceVault,
    build_source_vault_chunk_read_endpoint,
    build_source_vault_chunk_ref_id,
    build_source_vault_search_metadata,
)
from literature_assistant.core.skill_package_knowledge import ACADEMIC_ENGLISH_SKILL_PACKAGE_ID, search_skill_package
from literature_assistant.core.project_paths import wiki_generated_root, wiki_query_index_path, wiki_review_queue_path
from literature_assistant.core.runtime_env import wiki_enabled
from literature_assistant.core.wiki.page_store import WikiPageStore
from literature_assistant.core.wiki.review_queue import ReviewItem, ReviewItemKind, ReviewQueue
from literature_assistant.core.wiki.graph import parse_wiki_page
from literature_assistant.core.wiki.query import WikiQueryIndex, build_knowledge_refs
if TYPE_CHECKING:
    from literature_assistant.core.models import (
        ChunkLocatorPayload,
        CitationOverlapPayload,
        CitationVerificationPayload,
        CitationVerificationRequest,
        CitationVerificationStatus,
        CitationVerificationsResponse,
        CreateSourceLabelRequest,
        DiscussionEvidencePackPayload,
        EvidencePackBuildRequest,
        EvidencePackBuildResponse,
        EvidencePackIntegrityCheckPayload,
        EvidencePackIntegrityGateRequest,
        EvidencePackIntegrityGateResponse,
        EvidencePackReferencePayload,
        EvidenceQrelsReviewBundleRequest,
        EvidenceQrelsReviewBundleResponse,
        EvidenceRefPayload,
        EvidenceRefsResponse,
        EvidenceRetrievalDiagnosticsPayload,
        PdfAnchorFields,
        RetrievalQrelsStatusPayload,
        SourceLabelPayload,
        ToolAttempt,
        ToolNextAction,
        ToolOutcome,
        UpdateSourceLabelRequest,
        coerce_pdf_bbox,
    )
    from literature_assistant.core.project_paths import project_data_path, runtime_state_path
    from literature_assistant.core.routers import resources_router as _resources_router
    from literature_assistant.core.routers.resources_router.endpoints_search_upload import (
        _augment_chunks_with_linked_visual_assets,
        _augment_chunks_with_project_figure_assets,
        _chunk_to_search_ref,
        _flatten_chunk_store_for_search_refs,
        _merge_visual_search_ref_chunks,
        _search_refs_visual_query_enabled,
        _select_search_ref_chunks,
        _select_search_ref_chunks_fts_first,
        build_locator_coverage,
        enrich_chunk_locator_with_pdf,
        find_chunk_locator,
    )
else:
    import routers.resources_router as _resources_router
    from models import (
        ChunkLocatorPayload,
        CitationOverlapPayload,
        CitationVerificationPayload,
        CitationVerificationRequest,
        CitationVerificationStatus,
        CitationVerificationsResponse,
        CreateSourceLabelRequest,
        DiscussionEvidencePackPayload,
        EvidencePackBuildRequest,
        EvidencePackBuildResponse,
        EvidencePackIntegrityCheckPayload,
        EvidencePackIntegrityGateRequest,
        EvidencePackIntegrityGateResponse,
        EvidencePackReferencePayload,
        EvidenceQrelsReviewBundleRequest,
        EvidenceQrelsReviewBundleResponse,
        EvidenceRefPayload,
        EvidenceRefsResponse,
        EvidenceRetrievalDiagnosticsPayload,
        PdfAnchorFields,
        RetrievalQrelsStatusPayload,
        SourceLabelPayload,
        ToolAttempt,
        ToolNextAction,
        ToolOutcome,
        UpdateSourceLabelRequest,
        coerce_pdf_bbox,
    )
    from project_paths import project_data_path, runtime_state_path
    from routers.resources_router.endpoints_search_upload import (
        _augment_chunks_with_linked_visual_assets,
        _augment_chunks_with_project_figure_assets,
        _chunk_to_search_ref,
        _flatten_chunk_store_for_search_refs,
        _merge_visual_search_ref_chunks,
        _search_refs_visual_query_enabled,
        _select_search_ref_chunks,
        _select_search_ref_chunks_fts_first,
        build_locator_coverage,
        enrich_chunk_locator_with_pdf,
        find_chunk_locator,
    )

router = APIRouter(tags=["Evidence"])


# In-memory stores (TODO: replace with persistent storage)
_source_labels_store: dict[str, SourceLabelPayload] = {}
_evidence_refs_store: dict[str, EvidenceRefPayload] = {}
_discussion_packs_store: dict[str, DiscussionEvidencePackPayload] = {}
_evidence_pack_builds_store: dict[str, EvidencePackBuildResponse] = {}
_citation_verifications_store: dict[str, CitationVerificationPayload] = {}
_SOURCE_LABELS_VERSION = 1
_EVIDENCE_REFS_VERSION = 1
_DISCUSSION_EVIDENCE_PACKS_VERSION = 1
_EVIDENCE_PACK_BUILDS_VERSION = 1
_EVIDENCE_PACK_BUILD_STORE_LIMIT = 128
_CITATION_VERIFICATIONS_VERSION = 1
_EVIDENCE_REFS_EXPORT_VERSION = 1
_EVIDENCE_PACK_SUMMARY_CHARS = 300
_EVIDENCE_REFS_EXPORT_CSV_FIELDS: tuple[str, ...] = (
    "ref_id",
    "chunk_id",
    "material_id",
    "page",
    "bbox",
    "bbox_unit",
    "source",
    "source_label",
    "source_labels",
    "label",
    "score",
    "rank",
    "source_hint",
    "text",
    "quote",
    "compressed_text",
    "created_at",
    "updated_at",
)
_EVIDENCE_PACK_VISUAL_TERMS: dict[str, tuple[str, ...]] = {
    "appearance": (
        "外观",
        "成形",
        "宏观形貌",
        "表面形貌",
        "上表面",
        "焊缝表面",
        "weld bead",
        "appearance",
        "surface morphology",
        "top surface",
        "macrograph",
        "macroscopic",
    ),
    "image": (
        "图片",
        "图像",
        "照片",
        "显微图",
        "形貌",
        "figure",
        "fig.",
        "image",
        "photo",
        "micrograph",
        "morphology",
    ),
}
_EVIDENCE_PACK_IMAGE_ASSET_KEYS: frozenset[str] = frozenset(
    {
        "image_path",
        "image_paths",
        "image_asset",
        "image_assets",
        "asset_path",
        "asset_paths",
        "crop_path",
        "crop_paths",
        "thumbnail_path",
        "thumbnail_paths",
    }
)
_EVIDENCE_PACK_INTEGRITY_GATE_POLICY_VERSION = "evidence-pack-integrity-gate-config/v1"
_CANDIDATE_QRELS_FILENAMES: tuple[str, ...] = (
    "qrels_candidate.trec",
    "candidate.qrels",
    "candidate_qrels.trec",
)
_REVIEWED_QRELS_FILENAMES: tuple[str, ...] = (
    "goldset_reviewed.jsonl",
    "reviewed.jsonl",
    "goldset_review_template.jsonl",
)
_CANONICAL_QRELS_FILENAMES: tuple[str, ...] = (
    "canonical.qrels",
    "canonical.trec",
    "qrels.trec",
    "goldset.qrels",
)
_CANDIDATE_QRELS_BUNDLE_DIR = "candidate_review_bundles"
_QRELS_BUNDLE_SCAN_LIMIT = 100
KnowledgeRefSourceType = Literal[
    "product_docs",
    "scoring_rules",
    "academic_english",
    "skill_package",
    "source_vault",
]

_EVIDENCE_PACK_KNOWLEDGE_REF_KINDS: tuple[KnowledgeRefSourceType, ...] = (
    "product_docs",
    "scoring_rules",
    "academic_english",
    "skill_package",
    "source_vault",
)


class _FinalWikiPageStore(WikiPageStore):
    """Read-only Wiki view for evidence-pack joint recall.

    Evidence packs are reusable citation inputs, so draft/review pages must not
    enter the pack just because a local FTS index can see them.
    """

    def read_page(self, relative_path: Path) -> str | None:
        content = super().read_page(relative_path)
        if content is None:
            return None
        try:
            parsed = parse_wiki_page(str(content))
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
        status = str(parsed.frontmatter.get("status") or "").strip().lower()
        if status != "final":
            return None
        return content

    def list_pages(self, kind_dir: str | None = None) -> list[Path]:
        return [page_path for page_path in super().list_pages(kind_dir) if self.read_page(page_path) is not None]
_EVIDENCE_PACK_MAX_KNOWLEDGE_REFS = len(_EVIDENCE_PACK_KNOWLEDGE_REF_KINDS)


def _count_trec_qrels_rows(path: Path) -> int:
    """Return non-comment TREC qrels row count from a bounded local file."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 4:
            count += 1
    return count


def _count_reviewed_qrels_rows(path: Path) -> int:
    """Return reviewed judgment rows that no longer carry an unknown label."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        judgment = str(row.get("judgment") or "").strip().lower()
        if judgment and judgment != "unknown":
            count += 1
    return count


def _sum_named_files(root: Path, filenames: tuple[str, ...], counter: Any) -> int:
    """Count rows from direct known files without recursive workspace scans."""

    total = 0
    for candidate in _iter_qrels_named_file_candidates(root, filenames):
        if candidate.is_file():
            total += int(counter(candidate))
    return total


def _iter_qrels_named_file_candidates(root: Path, filenames: tuple[str, ...]) -> list[Path]:
    """Return direct qrels files plus known candidate bundle files.

    The bundle scan is intentionally bounded to one controlled directory level
    so project qrels status can see generated review bundles without walking
    arbitrary runtime trees.
    """

    candidates = [root / filename for filename in filenames]
    bundle_root = root / _CANDIDATE_QRELS_BUNDLE_DIR
    try:
        bundle_dirs = [
            child
            for child in bundle_root.iterdir()
            if child.is_dir() and child.name == Path(child.name).name
        ]
    except OSError:
        bundle_dirs = []
    for bundle_dir in sorted(bundle_dirs, key=lambda item: item.name)[:_QRELS_BUNDLE_SCAN_LIMIT]:
        candidates.extend(bundle_dir / filename for filename in filenames)
    return candidates


def _hash_named_qrels_files(root: Path) -> str:
    """Return a content-derived hash for known project qrels sidecar files."""

    digest = hashlib.sha256()
    seen = False
    for filename in (
        *_CANDIDATE_QRELS_FILENAMES,
        *_REVIEWED_QRELS_FILENAMES,
        *_CANONICAL_QRELS_FILENAMES,
    ):
        for candidate in _iter_qrels_named_file_candidates(root, (filename,)):
            if not candidate.is_file():
                continue
            try:
                data = candidate.read_bytes()
            except OSError:
                continue
            seen = True
            try:
                path_key = candidate.relative_to(root).as_posix()
            except ValueError:
                path_key = candidate.name
            digest.update(path_key.encode("utf-8", errors="replace"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")
    if not seen:
        digest.update(b"")
    return f"sha256:{digest.hexdigest()}"


def _project_qrels_status(project_id: str) -> RetrievalQrelsStatusPayload:
    """Return the highest local qrels review state for evidence-pack claims.

    Args:
        project_id: Project id whose generated qrels sidecars are inspected.

    Returns:
        A quality-gate payload. It never creates, promotes, deletes, or mutates
        qrels artifacts; missing/malformed local files degrade to zero counts.
    """

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be non-empty")
    qrels_root = project_data_path(normalized_project_id, "qrels")
    qrels_content_hash = _hash_named_qrels_files(qrels_root)
    candidate_count = _sum_named_files(
        qrels_root,
        _CANDIDATE_QRELS_FILENAMES,
        _count_trec_qrels_rows,
    )
    reviewed_count = _sum_named_files(
        qrels_root,
        _REVIEWED_QRELS_FILENAMES,
        _count_reviewed_qrels_rows,
    )
    canonical_count = _sum_named_files(
        qrels_root,
        _CANONICAL_QRELS_FILENAMES,
        _count_trec_qrels_rows,
    )
    if canonical_count > 0:
        return RetrievalQrelsStatusPayload(
            status="canonical",
            candidate_qrels_count=candidate_count,
            reviewed_qrels_count=reviewed_count,
            canonical_qrels_count=canonical_count,
            qrels_content_hash=qrels_content_hash,
            semantic_quality_claim_allowed=True,
            quality_claim="canonical_qrels_available",
            notes=[
                "Canonical qrels are available for offline retrieval-quality evaluation.",
            ],
        )
    if reviewed_count > 0:
        return RetrievalQrelsStatusPayload(
            status="reviewed",
            candidate_qrels_count=candidate_count,
            reviewed_qrels_count=reviewed_count,
            canonical_qrels_count=0,
            qrels_content_hash=qrels_content_hash,
            semantic_quality_claim_allowed=False,
            quality_claim="reviewed_qrels_promotion_required",
            notes=[
                "Reviewed judgments exist but have not been promoted to canonical qrels.",
            ],
        )
    if candidate_count > 0:
        return RetrievalQrelsStatusPayload(
            status="candidate",
            candidate_qrels_count=candidate_count,
            reviewed_qrels_count=0,
            canonical_qrels_count=0,
            qrels_content_hash=qrels_content_hash,
            semantic_quality_claim_allowed=False,
            quality_claim="candidate_qrels_review_required",
            notes=[
                "Candidate qrels require human review before semantic quality claims.",
            ],
        )
    return RetrievalQrelsStatusPayload(
        status="missing",
        candidate_qrels_count=0,
        reviewed_qrels_count=0,
        canonical_qrels_count=0,
        qrels_content_hash=qrels_content_hash,
        semantic_quality_claim_allowed=False,
        quality_claim="no_qrels_available",
        notes=[
            "No project qrels were found; retrieval method is provenance, not semantic quality proof.",
        ],
    )


def _evidence_runtime_store_path(filename: str) -> Path:
    """Return one evidence runtime JSON path under workspace_artifacts.

    Args:
        filename: Plain JSON filename. Path separators are rejected because
            callers should not be able to escape the evidence runtime store.

    Returns:
        Runtime-state path for a durable evidence sidecar store.

    Raises:
        ValueError: If filename is empty or path-like.
    """

    normalized = str(filename or "").strip()
    if not normalized or normalized != Path(normalized).name:
        raise ValueError("evidence store filename must be a plain filename")
    return Path(runtime_state_path("evidence", normalized))


def _read_json_payload(path: Path) -> Any:
    """Read a JSON object or list; malformed stores degrade to an empty object."""

    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _json_object_or_empty(value: Any) -> dict[str, Any]:
    """Return the string-keyed portion of a JSON object or an empty mapping."""

    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str)
    }


def _write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    """Persist a runtime JSON payload with tmp+replace semantics."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Evidence runtime store write failed: {exc}") from exc


def _write_json_artifact(path: Path, payload: Any) -> None:
    """Write a JSON review artifact atomically under an already validated root."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Evidence artifact write failed: {exc}") from exc


def _load_source_labels() -> dict[str, SourceLabelPayload]:
    """Load durable source labels and skip malformed records."""

    payload = _read_json_payload(_evidence_runtime_store_path("source_labels.json"))
    raw_labels = payload.get("labels") if isinstance(payload, dict) else payload
    if not isinstance(raw_labels, list):
        return {}

    labels: dict[str, SourceLabelPayload] = {}
    for raw_label in raw_labels:
        if not isinstance(raw_label, dict):
            continue
        try:
            label = SourceLabelPayload(**raw_label)
        except ValidationError:
            continue
        if label.label_id.strip():
            labels[label.label_id] = label
    return labels


def _write_source_labels(labels: dict[str, SourceLabelPayload]) -> None:
    """Persist source labels so label filters survive process restarts."""

    payload = {
        "version": _SOURCE_LABELS_VERSION,
        "labels": [
            label.model_dump(mode="json")
            for label in sorted(labels.values(), key=lambda item: (item.name.lower(), item.label_id))
        ],
    }
    _write_json_payload(_evidence_runtime_store_path("source_labels.json"), payload)


def _refresh_source_labels_store() -> dict[str, SourceLabelPayload]:
    """Merge durable source labels into the process cache."""

    _source_labels_store.update(_load_source_labels())
    return _source_labels_store


def _load_evidence_refs() -> dict[str, EvidenceRefPayload]:
    """Load durable evidence refs and skip malformed records."""

    payload = _read_json_payload(_evidence_runtime_store_path("evidence_refs.json"))
    raw_refs = payload.get("refs") if isinstance(payload, dict) else payload
    if not isinstance(raw_refs, list):
        return {}

    refs: dict[str, EvidenceRefPayload] = {}
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, dict):
            continue
        try:
            ref = EvidenceRefPayload(**raw_ref)
        except ValidationError:
            continue
        if ref.ref_id.strip():
            refs[ref.ref_id] = ref
    return refs


def _write_evidence_refs(refs: dict[str, EvidenceRefPayload]) -> None:
    """Persist evidence refs with their source labels and PDF anchors."""

    payload = {
        "version": _EVIDENCE_REFS_VERSION,
        "refs": [
            ref.model_dump(mode="json")
            for ref in sorted(refs.values(), key=lambda item: (item.created_at, item.ref_id))
        ],
    }
    _write_json_payload(_evidence_runtime_store_path("evidence_refs.json"), payload)


def _refresh_evidence_refs_store() -> dict[str, EvidenceRefPayload]:
    """Merge durable evidence refs into the process cache."""

    _evidence_refs_store.update(_load_evidence_refs())
    return _evidence_refs_store


def _normalize_filter_values(values: Optional[List[str]]) -> list[str]:
    """Return stable non-empty filter values from repeated query params.

    Args:
        values: Query parameter values supplied by FastAPI.

    Returns:
        A deduplicated list preserving first-seen order.
    """

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values or []:
        value = str(raw_value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _select_evidence_refs(
    *,
    material_id: Optional[str],
    source_labels: Optional[List[str]],
) -> list[EvidenceRefPayload]:
    """Select evidence refs with the same local filters used by export endpoints.

    Args:
        material_id: Optional material identifier to match exactly.
        source_labels: Optional labels; a ref matches when it has any label.

    Returns:
        Sorted evidence refs ready for pagination or export.
    """

    refs = list(_refresh_evidence_refs_store().values())
    normalized_material_id = str(material_id or "").strip()
    normalized_source_labels = _normalize_filter_values(source_labels)

    if normalized_material_id:
        refs = [ref for ref in refs if ref.material_id == normalized_material_id]

    if normalized_source_labels:
        refs = [
            ref
            for ref in refs
            if any(label in ref.source_labels for label in normalized_source_labels)
        ]

    return sorted(refs, key=lambda ref: (ref.created_at, ref.ref_id))


def _evidence_ref_export_row(ref: EvidenceRefPayload) -> dict[str, Any]:
    """Convert one evidence ref to a JSON-serializable export row."""

    return _json_object_or_empty(ref.model_dump(mode="json"))


def _csv_cell(value: Any) -> str:
    """Serialize nested values without losing evidence anchor structure."""

    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _build_evidence_refs_export_payload(
    *,
    refs: list[EvidenceRefPayload],
    material_id: Optional[str],
    source_labels: Optional[List[str]],
) -> dict[str, Any]:
    """Build the deterministic JSON evidence refs export envelope.

    Args:
        refs: Filtered evidence refs to export.
        material_id: Material filter supplied by the caller.
        source_labels: Source-label filter supplied by the caller.

    Returns:
        JSON-compatible export envelope with filters and evidence refs.
    """

    return {
        "version": _EVIDENCE_REFS_EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "material_id": str(material_id or "").strip() or None,
            "source_labels": _normalize_filter_values(source_labels),
        },
        "total": len(refs),
        "refs": [_evidence_ref_export_row(ref) for ref in refs],
    }


def _build_evidence_refs_csv(refs: list[EvidenceRefPayload]) -> str:
    """Build a CSV export body with a stable schema and UTF-8 text."""

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(_EVIDENCE_REFS_EXPORT_CSV_FIELDS))
    writer.writeheader()
    for ref in refs:
        row = _evidence_ref_export_row(ref)
        writer.writerow(
            {
                field: _csv_cell(row.get(field))
                for field in _EVIDENCE_REFS_EXPORT_CSV_FIELDS
            }
        )
    return output.getvalue()


def _download_headers(filename: str) -> dict[str, str]:
    """Return attachment headers for a generated local export."""

    safe_filename = str(filename or "").strip()
    if not safe_filename or safe_filename != Path(safe_filename).name:
        raise HTTPException(status_code=500, detail="invalid evidence refs export filename")
    return {"Content-Disposition": f'attachment; filename="{safe_filename}"'}


def _load_citation_verifications() -> dict[str, CitationVerificationPayload]:
    """Load durable citation verification records and skip malformed rows."""

    payload = _read_json_payload(_evidence_runtime_store_path("citation_verifications.json"))
    raw_records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(raw_records, list):
        return {}

    records: dict[str, CitationVerificationPayload] = {}
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        try:
            record = CitationVerificationPayload(**raw_record)
        except ValidationError:
            continue
        if record.verification_id.strip():
            records[record.verification_id] = record
    return records


def _write_citation_verifications(records: dict[str, CitationVerificationPayload]) -> None:
    """Persist citation verification records for writing/review sidebars."""

    payload = {
        "version": _CITATION_VERIFICATIONS_VERSION,
        "records": [
            record.model_dump(mode="json")
            for record in sorted(records.values(), key=lambda item: (item.created_at, item.verification_id))
        ],
    }
    _write_json_payload(_evidence_runtime_store_path("citation_verifications.json"), payload)


def _refresh_citation_verifications_store() -> dict[str, CitationVerificationPayload]:
    """Merge durable citation verification records into the process cache."""

    _citation_verifications_store.update(_load_citation_verifications())
    return _citation_verifications_store


# =========================================================================
# A4: Independent evidence_refs API
# =========================================================================

@router.get("/api/evidence_refs", response_model=EvidenceRefsResponse)
async def get_evidence_refs(
    project_id: Optional[str] = Query(None, description="Filter by project"),
    material_id: Optional[str] = Query(None, description="Filter by material"),
    source_labels: List[str] = Query(None, description="Filter by source labels"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> EvidenceRefsResponse:
    """Get evidence references with optional source_labels filtering.

    Supports filtering by project_id, material_id, and source_labels.
    """
    refs = _select_evidence_refs(
        material_id=material_id,
        source_labels=source_labels,
    )

    # Pagination
    total = len(refs)
    start = (page - 1) * page_size
    end = start + page_size
    page_refs = refs[start:end]

    return EvidenceRefsResponse(
        refs=page_refs,
        total=total,
        filtered_by_labels=source_labels or [],
    )


@router.get("/api/evidence_refs/export")
async def export_evidence_refs(
    material_id: Optional[str] = Query(None, description="Filter by material"),
    source_labels: List[str] = Query(None, description="Filter by source labels"),
    export_format: Literal["json", "csv"] = Query("json", alias="format"),
) -> Response:
    """Export evidence references as a local JSON or CSV attachment.

    Args:
        material_id: Optional material identifier to match exactly.
        source_labels: Optional source labels; a ref matches any supplied label.
        export_format: Either ``json`` or ``csv``.

    Returns:
        Downloadable response preserving source labels and PDF anchor fields.
    """

    refs = _select_evidence_refs(
        material_id=material_id,
        source_labels=source_labels,
    )
    if export_format == "csv":
        return Response(
            content=_build_evidence_refs_csv(refs),
            media_type="text/csv",
            headers=_download_headers("evidence_refs_export.csv"),
        )

    payload = _build_evidence_refs_export_payload(
        refs=refs,
        material_id=material_id,
        source_labels=source_labels,
    )
    return Response(
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        media_type="application/json",
        headers=_download_headers("evidence_refs_export.json"),
    )


class CreateEvidenceRefRequest(PdfAnchorFields):
    """Request to create evidence reference."""
    chunk_id: str
    material_id: str
    text: str
    compressed_text: str = ""
    quote: str = ""
    label: str = ""
    score: Optional[float] = None
    page: Optional[int] = None
    source: Optional[str] = None
    source_label: Optional[str] = None
    source_labels: List[str] = Field(default_factory=list)


@router.post("/api/evidence_refs", response_model=EvidenceRefPayload)
async def create_evidence_ref(request: CreateEvidenceRefRequest) -> EvidenceRefPayload:
    """Create a new evidence reference with optional bbox."""
    ref_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    ref = EvidenceRefPayload(
        ref_id=ref_id,
        chunk_id=request.chunk_id,
        material_id=request.material_id,
        text=request.text,
        compressed_text=request.compressed_text,
        quote=request.quote,
        label=request.label,
        score=request.score,
        page=request.page,
        source=request.source,
        source_label=request.source_label,
        source_labels=request.source_labels,
        bbox=request.bbox,
        bbox_unit=request.bbox_unit,
        created_at=now,
        updated_at=now,
    )

    _refresh_evidence_refs_store()
    _evidence_refs_store[ref_id] = ref
    _write_evidence_refs(_evidence_refs_store)
    return ref


# =========================================================================
# A5: Source labels CRUD
# =========================================================================

@router.get("/api/source_labels", response_model=List[SourceLabelPayload])
async def list_source_labels() -> List[SourceLabelPayload]:
    """List all source labels."""
    return list(_refresh_source_labels_store().values())


@router.post("/api/source_labels", response_model=SourceLabelPayload)
async def create_source_label(request: CreateSourceLabelRequest) -> SourceLabelPayload:
    """Create a new source label."""
    if not request.name.strip():
        raise HTTPException(status_code=422, detail="source label name must be non-empty")
    label_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    label = SourceLabelPayload(
        label_id=label_id,
        name=request.name.strip(),
        description=request.description,
        color=request.color,
        created_at=now,
        updated_at=now,
    )

    _refresh_source_labels_store()
    _source_labels_store[label_id] = label
    _write_source_labels(_source_labels_store)
    return label


@router.get("/api/source_labels/{label_id}", response_model=SourceLabelPayload)
async def get_source_label(label_id: str) -> SourceLabelPayload:
    """Get a source label by ID."""
    label = _refresh_source_labels_store().get(label_id)
    if not label:
        raise HTTPException(status_code=404, detail=f"Source label not found: {label_id}")
    return label


@router.put("/api/source_labels/{label_id}", response_model=SourceLabelPayload)
async def update_source_label(
    label_id: str,
    request: UpdateSourceLabelRequest,
) -> SourceLabelPayload:
    """Update a source label."""
    label = _refresh_source_labels_store().get(label_id)
    if not label:
        raise HTTPException(status_code=404, detail=f"Source label not found: {label_id}")
    if request.name is not None and not request.name.strip():
        raise HTTPException(status_code=422, detail="source label name must be non-empty")

    now = datetime.now(timezone.utc).isoformat()

    updated = SourceLabelPayload(
        label_id=label.label_id,
        name=request.name.strip() if request.name is not None else label.name,
        description=request.description if request.description is not None else label.description,
        color=request.color if request.color is not None else label.color,
        created_at=label.created_at,
        updated_at=now,
    )

    _source_labels_store[label_id] = updated
    _write_source_labels(_source_labels_store)
    return updated


@router.delete("/api/source_labels/{label_id}")
async def delete_source_label(label_id: str) -> dict[str, str]:
    """Delete a source label."""
    _refresh_source_labels_store()
    if label_id not in _source_labels_store:
        raise HTTPException(status_code=404, detail=f"Source label not found: {label_id}")

    del _source_labels_store[label_id]
    _write_source_labels(_source_labels_store)
    return {"message": f"Source label {label_id} deleted"}


# =========================================================================
# A7: Chunk locator with bbox
# =========================================================================

def _chunk_locator_payload_from_store(project_id: str, chunk_id: str) -> ChunkLocatorPayload:
    """Resolve one chunk locator from the project chunk store.

    Args:
        project_id: Non-empty project identifier owning the chunk store.
        chunk_id: Non-empty chunk identifier to locate.

    Returns:
        Public locator payload with optional page and bbox metadata.

    Raises:
        HTTPException: 404 when the chunk is absent from the project store.
    """
    normalized_project_id = str(project_id or "").strip()
    normalized_chunk_id = str(chunk_id or "").strip()
    if not normalized_project_id:
        raise HTTPException(status_code=422, detail="project_id must be a non-empty string")
    if not normalized_chunk_id:
        raise HTTPException(status_code=422, detail="chunk_id must be a non-empty string")

    chunk_store = _resources_router._load_chunk_store(normalized_project_id)  # type: ignore[attr-defined]
    locator = find_chunk_locator(chunk_store, normalized_chunk_id)
    if locator is None:
        raise HTTPException(
            status_code=404,
            detail=f"chunk_id 未在项目 chunk store 中找到: {normalized_chunk_id}",
        )
    locator = enrich_chunk_locator_with_pdf(normalized_project_id, chunk_store, locator)

    page = locator.get("page")
    normalized_page = (
        page
        if isinstance(page, int) and not isinstance(page, bool) and page > 0
        else None
    )
    try:
        anchor = PdfAnchorFields.model_validate(
            {
                "bbox": locator.get("bbox") if normalized_page is not None else None,
                "bbox_unit": locator.get("bbox_unit") if normalized_page is not None else None,
            }
        )
    except ValidationError:
        anchor = PdfAnchorFields(bbox=None, bbox_unit=None)

    return ChunkLocatorPayload(
        chunk_id=str(locator["chunk_id"]),
        material_id=str(locator["material_id"]),
        page=normalized_page,
        chunk_index=locator.get("chunk_index") if isinstance(locator.get("chunk_index"), int) else None,
        bbox=anchor.bbox,
        bbox_unit=anchor.bbox_unit,
        text_preview=str(locator.get("text_preview") or ""),
    )


@router.get("/api/chunk_to_page", response_model=ChunkLocatorPayload)
async def chunk_to_page(
    chunk_id: str = Query(..., min_length=1),
    project_id: str = Query(..., min_length=1),
) -> ChunkLocatorPayload:
    """Resolve a chunk id to PDF page and optional bbox metadata."""
    return _chunk_locator_payload_from_store(project_id=project_id, chunk_id=chunk_id)


@router.get("/api/chunks/{chunk_id}/locator", response_model=ChunkLocatorPayload)
async def get_chunk_locator(
    chunk_id: str,
    project_id: Optional[str] = Query(None, min_length=1),
) -> ChunkLocatorPayload:
    """Get chunk locator with bbox information when a project id is provided."""
    if project_id is None:
        return ChunkLocatorPayload(
            chunk_id=chunk_id,
            material_id="",
            page=None,
            chunk_index=None,
            bbox=None,
            bbox_unit=None,
            text_preview="",
        )
    return _chunk_locator_payload_from_store(project_id=project_id, chunk_id=chunk_id)


# =========================================================================
# D5: Discussion evidence_pack persistence
# =========================================================================

def _discussion_evidence_pack_store_path() -> Path:
    """Return the durable D5 JSON store path under runtime state.

    Returns:
        A pathlib-compatible path with parent directories created by writers.
    """
    return Path(runtime_state_path("discussion", "evidence_packs.json"))


def _discussion_evidence_pack_from_raw(raw_pack: Any) -> DiscussionEvidencePackPayload | None:
    """Validate one persisted evidence pack record.

    Args:
        raw_pack: JSON-decoded object expected to match DiscussionEvidencePackPayload.

    Returns:
        Parsed payload, or None when the record is malformed.
    """
    if not isinstance(raw_pack, dict):
        return None
    try:
        return DiscussionEvidencePackPayload(**raw_pack)
    except ValidationError:
        return None


def _load_discussion_evidence_packs() -> dict[str, DiscussionEvidencePackPayload]:
    """Load the durable discussion evidence pack index.

    Returns:
        Mapping keyed by pack_id. Malformed records are skipped so one bad
        artifact cannot break the entire local evidence-pack registry.
    """
    path = _discussion_evidence_pack_store_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    raw_packs = payload.get("packs") if isinstance(payload, dict) else payload
    if not isinstance(raw_packs, list):
        return {}

    loaded: dict[str, DiscussionEvidencePackPayload] = {}
    for raw_pack in raw_packs:
        pack = _discussion_evidence_pack_from_raw(raw_pack)
        if pack is not None and pack.pack_id.strip():
            loaded[pack.pack_id] = pack
    return loaded


def _write_discussion_evidence_packs(
    packs: dict[str, DiscussionEvidencePackPayload],
) -> None:
    """Persist the evidence pack index with tmp+replace semantics.

    Args:
        packs: Mapping keyed by pack_id; values must be serializable Pydantic models.

    Raises:
        HTTPException: 500 when the runtime store cannot be written.
    """
    path = _discussion_evidence_pack_store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _DISCUSSION_EVIDENCE_PACKS_VERSION,
            "packs": [
                pack.model_dump(mode="json")
                for pack in sorted(packs.values(), key=lambda item: (item.created_at, item.pack_id))
            ],
        }
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Evidence pack store write failed: {exc}") from exc


def _refresh_discussion_evidence_pack_store() -> dict[str, DiscussionEvidencePackPayload]:
    """Merge durable D5 packs into the process cache and return the cache."""
    _discussion_packs_store.update(_load_discussion_evidence_packs())
    return _discussion_packs_store


def _bounded_evidence_pack_summary(value: str) -> str:
    """Return a citation-safe summary that cannot dominate model context."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return "Matched evidence chunk"
    if len(text) <= _EVIDENCE_PACK_SUMMARY_CHARS:
        return text
    return f"{text[: _EVIDENCE_PACK_SUMMARY_CHARS - 1].rstrip()}…"


def _citation_anchor_from_ref(ref_id: str, material_id: str, chunk_id: str) -> str:
    """Return a deterministic local citation anchor for evidence traceability."""

    source = f"{material_id}_{chunk_id}_{ref_id}"
    normalized = re.sub(r"[^A-Za-z0-9_\-]+", "_", source).strip("_")
    return normalized[:240] or f"chunk_{uuid.uuid4().hex[:12]}"


def _evidence_pack_ref(project_id: str, query: str, section_id: str | None) -> str:
    """Return a stable opaque pack id for one deterministic lexical build."""

    seed = json.dumps(
        {"project_id": project_id, "query": query, "section_id": section_id or ""},
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"evidence_pack:{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex}"


def _evidence_pack_build_store_path() -> Path:
    """Return the durable bounded evidence-pack build store path."""

    return Path(runtime_state_path("evidence_pack", "builds.json"))


def _evidence_pack_build_from_raw(raw_pack: Any) -> EvidencePackBuildResponse | None:
    """Validate one persisted bounded evidence-pack build response."""

    if not isinstance(raw_pack, dict):
        return None
    try:
        pack = EvidencePackBuildResponse(**raw_pack)
    except ValidationError:
        return None
    if not pack.evidence_pack_ref.strip():
        return None
    return pack


def _load_evidence_pack_builds() -> dict[str, EvidencePackBuildResponse]:
    """Load persisted bounded evidence-pack builds keyed by pack ref."""

    path = _evidence_pack_build_store_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    raw_packs = payload.get("packs") if isinstance(payload, dict) else payload
    if not isinstance(raw_packs, list):
        return {}

    loaded: dict[str, EvidencePackBuildResponse] = {}
    for raw_pack in raw_packs:
        pack = _evidence_pack_build_from_raw(raw_pack)
        if pack is not None:
            loaded[pack.evidence_pack_ref] = pack
    if len(loaded) <= _EVIDENCE_PACK_BUILD_STORE_LIMIT:
        return loaded
    return dict(list(loaded.items())[-_EVIDENCE_PACK_BUILD_STORE_LIMIT:])


def _write_evidence_pack_builds(packs: dict[str, EvidencePackBuildResponse]) -> None:
    """Persist bounded pack builds with tmp+replace semantics."""

    path = _evidence_pack_build_store_path()
    bounded_items = list(packs.items())[-_EVIDENCE_PACK_BUILD_STORE_LIMIT:]
    payload = {
        "version": _EVIDENCE_PACK_BUILDS_VERSION,
        "packs": [pack.model_dump(mode="json") for _pack_ref, pack in bounded_items],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def _remember_evidence_pack_build(pack: EvidencePackBuildResponse) -> None:
    """Remember the bounded build response so its pack ref can be rechecked."""

    pack_ref = pack.evidence_pack_ref.strip()
    if not pack_ref:
        return
    merged = _load_evidence_pack_builds()
    merged.update(_evidence_pack_builds_store)
    merged[pack_ref] = pack
    bounded = dict(list(merged.items())[-_EVIDENCE_PACK_BUILD_STORE_LIMIT:])
    _evidence_pack_builds_store.clear()
    _evidence_pack_builds_store.update(bounded)
    try:
        _write_evidence_pack_builds(bounded)
    except OSError:
        return


def _restore_evidence_pack_build(
    *,
    project_id: str,
    query: str,
    evidence_pack_ref: str | None,
) -> EvidencePackBuildResponse | None:
    """Restore a bounded build when project, query, and pack ref agree."""

    pack_ref = str(evidence_pack_ref or "").strip()
    normalized_project_id = str(project_id or "").strip()
    normalized_query = str(query or "").strip()
    if not pack_ref or not normalized_project_id:
        return None

    pack = _evidence_pack_builds_store.get(pack_ref)
    if pack is None:
        loaded = _load_evidence_pack_builds()
        _evidence_pack_builds_store.update(loaded)
        pack = loaded.get(pack_ref)
    if pack is None:
        return None
    if pack.project_id.strip() != normalized_project_id:
        return None
    if normalized_query and pack.query.strip() != normalized_query:
        return None
    return pack


def _ensure_child_path(parent: Path, child: Path, *, label: str) -> None:
    """Raise if a generated qrels path escapes the intended project root."""

    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if child_resolved == parent_resolved or parent_resolved in child_resolved.parents:
        return
    raise ValueError(f"{label} must stay under project qrels root")


def _qrels_review_bundle_id(project_id: str, evidence_pack_ref: str) -> str:
    """Return a filesystem-safe local id for one candidate review bundle."""

    seed = json.dumps(
        {"project_id": project_id, "evidence_pack_ref": evidence_pack_ref},
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"qrels_review_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"


def _qrels_review_bundle_paths(project_id: str, evidence_pack_ref: str) -> tuple[str, Path, Path]:
    """Return bundle id, source package dir, and review output dir."""

    bundle_id = _qrels_review_bundle_id(project_id, evidence_pack_ref)
    qrels_root = project_data_path(project_id, "qrels")
    output_dir = qrels_root / _CANDIDATE_QRELS_BUNDLE_DIR / bundle_id
    package_dir = output_dir / "source_chunk_package"
    _ensure_child_path(qrels_root, output_dir, label="qrels review output_dir")
    _ensure_child_path(qrels_root, package_dir, label="qrels review package_path")
    return bundle_id, package_dir, output_dir


def _bounded_qrels_review_text(value: Any, *, limit: int = 3000) -> str:
    """Return a bounded one-line text excerpt for manual qrels review."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _chunk_text_for_qrels_review(chunk: dict[str, Any], ref: dict[str, Any]) -> str:
    """Prefer indexed chunk text, falling back to bounded evidence summaries."""

    for key in ("content", "raw_content", "text", "summary"):
        text = _bounded_qrels_review_text(chunk.get(key))
        if text:
            return text
    return _bounded_qrels_review_text(ref.get("summary") or ref.get("title") or "Evidence ref")


def _source_chunk_for_evidence_ref(
    *,
    project_id: str,
    chunk_lookup: dict[tuple[str, str], dict[str, Any]],
    chunk_id_lookup: dict[str, dict[str, Any]],
    ref: EvidencePackReferencePayload,
) -> dict[str, Any] | None:
    """Return one chunk-package row for a selected evidence ref."""

    ref_payload = ref.model_dump(mode="json")
    chunk_id = str(ref_payload.get("chunk_id") or "").strip()
    if not chunk_id:
        return None
    material_id = str(ref_payload.get("material_id") or "").strip()
    source_chunk = chunk_lookup.get((material_id, chunk_id)) if material_id else None
    if source_chunk is None:
        source_chunk = chunk_id_lookup.get(chunk_id)
    if source_chunk is None:
        source_chunk = {}
    source_name = str(
        ref_payload.get("title")
        or source_chunk.get("source_name")
        or source_chunk.get("title")
        or material_id
        or project_id
    ).strip()
    page = ref_payload.get("page") if ref_payload.get("page") is not None else source_chunk.get("page")
    text = _chunk_text_for_qrels_review(source_chunk, ref_payload)
    return {
        "chunk_id": chunk_id,
        "source_id": material_id or str(source_chunk.get("material_id") or project_id),
        "material_id": material_id or str(source_chunk.get("material_id") or ""),
        "source_name": _bounded_qrels_review_text(source_name, limit=240),
        "title": _bounded_qrels_review_text(source_name, limit=240),
        "page": page,
        "page_start": source_chunk.get("page_start") or page,
        "page_end": source_chunk.get("page_end") or page,
        "chunk_type": str(source_chunk.get("chunk_type") or ref_payload.get("source_type") or "evidence")[:80],
        "text": text,
        "content": text,
        "metadata": {
            "project_id": project_id,
            "ref_id": ref_payload.get("ref_id"),
            "score": ref_payload.get("score"),
            "rank": ref_payload.get("rank"),
        },
    }


def _write_qrels_review_source_package(
    *,
    pack: EvidencePackBuildResponse,
    package_dir: Path,
) -> dict[str, Any]:
    """Materialize a minimal chunk package for the existing review toolchain."""

    chunk_store = _resources_router._load_chunk_store(pack.project_id)
    all_chunks = _flatten_chunk_store_for_search_refs(chunk_store)
    chunk_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    chunk_id_lookup: dict[str, dict[str, Any]] = {}
    for chunk in all_chunks:
        if not isinstance(chunk, dict):
            continue
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        material_id = str(chunk.get("material_id") or "").strip()
        if chunk_id:
            chunk_id_lookup.setdefault(chunk_id, chunk)
        if material_id and chunk_id:
            chunk_lookup.setdefault((material_id, chunk_id), chunk)

    package_chunks: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    for index, ref in enumerate(pack.evidence_refs, start=1):
        chunk_row = _source_chunk_for_evidence_ref(
            project_id=pack.project_id,
            chunk_lookup=chunk_lookup,
            chunk_id_lookup=chunk_id_lookup,
            ref=ref,
        )
        if chunk_row is None:
            continue
        chunk_id = str(chunk_row.get("chunk_id") or "").strip()
        ref_payload = ref.model_dump(mode="json")
        evidence_items.append(
            {
                "chunk_id": chunk_id,
                "material_id": chunk_row.get("material_id"),
                "ref_id": ref_payload.get("ref_id"),
                "rank": ref_payload.get("rank") or index,
                "score": ref_payload.get("score"),
                "title": ref_payload.get("title"),
                "page": ref_payload.get("page"),
            }
        )
        if chunk_id not in seen_chunk_ids:
            package_chunks.append(chunk_row)
            seen_chunk_ids.add(chunk_id)

    manifest_sources: dict[str, dict[str, Any]] = {}
    for chunk in package_chunks:
        source_id = str(chunk.get("source_id") or pack.project_id).strip()
        manifest_sources.setdefault(
            source_id,
            {
                "source_id": source_id,
                "source_name": chunk.get("source_name") or source_id,
                "project_id": pack.project_id,
                "evidence_pack_ref": pack.evidence_pack_ref,
            },
        )

    package_dir.mkdir(parents=True, exist_ok=True)
    _write_json_artifact(package_dir / "manifest.json", list(manifest_sources.values()))
    _write_json_artifact(package_dir / "chunks.json", package_chunks)
    _write_json_artifact(package_dir / "evidence.json", {pack.query or "evidence_pack": evidence_items})
    _write_json_artifact(
        package_dir / "review_content.json",
        {
            "sections": [
                {
                    "title": pack.query,
                    "text": _bounded_qrels_review_text(pack.query, limit=1000),
                }
            ],
            "references": [
                {
                    "ref_id": item.get("ref_id"),
                    "chunk_id": item.get("chunk_id"),
                    "title": item.get("title"),
                }
                for item in evidence_items
            ],
        },
    )
    return {
        "chunk_count": len(package_chunks),
        "evidence_item_count": len(evidence_items),
        "source_count": len(manifest_sources),
    }


def _upsert_qrels_review_queue_item(
    *,
    bundle_id: str,
    project_id: str,
    evidence_pack_ref: str,
    output_dir: Path,
    judgment_template_path: str,
    candidate_qrels_count: int,
) -> dict[str, Any]:
    """Attach candidate qrels review to the existing local review queue."""

    queue = ReviewQueue(wiki_review_queue_path())
    item_id = f"qrels_review:{bundle_id}"
    metadata = {
        "project_id": project_id,
        "evidence_pack_ref": evidence_pack_ref,
        "bundle_id": bundle_id,
        "output_dir": str(output_dir),
        "judgment_template_path": judgment_template_path,
        "candidate_qrels_count": candidate_qrels_count,
        "candidate_only": True,
        "allowed_judgments": ["relevant", "partial", "offtopic", "unknown"],
        "requires_human_review_before_promotion": True,
    }
    existing = queue.get(item_id)
    if existing is not None:
        return queue.update_metadata(item_id, metadata).to_dict()
    return queue.append(
        ReviewItem(
            item_id=item_id,
            kind=ReviewItemKind.manual_edit,
            title="Review candidate qrels",
            page_path=judgment_template_path,
            summary="Candidate qrels generated from a selected evidence pack; review before any canonical promotion.",
            source="qrels",
            metadata=metadata,
        )
    ).to_dict()


def _qrels_review_bundle_outcome(
    *,
    project_id: str,
    bundle_id: str,
    candidate_qrels_count: int,
    package_stats: dict[str, Any],
    review_queue_status: str,
) -> ToolOutcome:
    """Return the required candidate-only review_qrels next action."""

    status: Literal["success", "empty"] = "success" if candidate_qrels_count > 0 else "empty"
    return ToolOutcome(
        status=status,
        quality="metadata_only",
        reason=(
            "Candidate qrels review bundle generated; human review is required before promotion."
            if candidate_qrels_count > 0
            else "Review bundle generated, but no valid candidate qrels rows were found."
        ),
        next_action=ToolNextAction(
            kind="review_qrels",
            message="Review goldset_review_template.jsonl before any canonical qrels promotion.",
            tool_name="literature.qrels_review_bundle",
            endpoint="/api/evidence-pack/qrels-review-bundle",
            args={"project_id": project_id, "bundle_id": bundle_id},
        ),
        attempts=[
            ToolAttempt(
                stage="evidence_pack_restore",
                status="success",
                reason="Restored bounded evidence pack by evidence_pack_ref.",
                metadata={"bundle_id": bundle_id},
            ),
            ToolAttempt(
                stage="chunk_package_materialize",
                status="success" if package_stats.get("chunk_count") else "degraded",
                reason="Materialized a chunk package for qrels review.",
                metadata=dict(package_stats),
            ),
            ToolAttempt(
                stage="candidate_qrels_write",
                status="success" if candidate_qrels_count > 0 else "skipped",
                reason="Wrote candidate-only qrels review artifacts.",
                metadata={"candidate_qrels_count": candidate_qrels_count},
            ),
            ToolAttempt(
                stage="review_queue",
                status="success" if review_queue_status == "pending" else "degraded",
                reason="Attached the bundle to the local review queue.",
                metadata={"review_queue_status": review_queue_status},
            ),
        ],
    )


def _build_qrels_review_bundle_response(
    request: EvidenceQrelsReviewBundleRequest,
    pack: EvidencePackBuildResponse,
) -> EvidenceQrelsReviewBundleResponse:
    """Generate a candidate-only qrels review bundle from a restored pack."""

    bundle_id, package_dir, output_dir = _qrels_review_bundle_paths(pack.project_id, pack.evidence_pack_ref)
    package_stats = _write_qrels_review_source_package(pack=pack, package_dir=package_dir)
    bundle = write_chunk_goldset_review_bundle(
        package_dir,
        output_dir,
        max_chunks_per_section=request.max_chunks_per_section,
    )
    review_item = _upsert_qrels_review_queue_item(
        bundle_id=bundle_id,
        project_id=pack.project_id,
        evidence_pack_ref=pack.evidence_pack_ref,
        output_dir=output_dir,
        judgment_template_path=bundle.judgment_template_path,
        candidate_qrels_count=bundle.candidate_qrels_count,
    )
    qrels_status = _project_qrels_status(pack.project_id)
    outcome = _qrels_review_bundle_outcome(
        project_id=pack.project_id,
        bundle_id=bundle_id,
        candidate_qrels_count=bundle.candidate_qrels_count,
        package_stats=package_stats,
        review_queue_status=str(review_item.get("status") or ""),
    )
    return EvidenceQrelsReviewBundleResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        project_id=pack.project_id,
        evidence_pack_ref=pack.evidence_pack_ref,
        query=pack.query,
        bundle_id=bundle_id,
        candidate_only=True,
        output_dir=str(output_dir),
        package_path=str(package_dir),
        quality_report_path=bundle.quality_report_path,
        goldset_proposal_path=bundle.goldset_proposal_path,
        qrels_candidate_path=bundle.qrels_candidate_path,
        judgment_template_path=bundle.judgment_template_path,
        standards_markdown_path=bundle.standards_markdown_path,
        query_count=bundle.query_count,
        candidate_qrels_count=bundle.candidate_qrels_count,
        qrels_status=qrels_status,
        review_queue_item=review_item,
        outcome=outcome,
        provenance={
            "source": "/api/evidence-pack/build",
            "review_toolchain": "write_chunk_goldset_review_bundle",
            "candidate_only": True,
            "canonical_qrels_promoted": False,
            "max_chunks_per_section": request.max_chunks_per_section,
        },
    )


def _material_source_path_from_doc_store(project_id: str, material_id: str) -> str | None:
    """Return a bounded project-relative source path for a material.

    Args:
        project_id: Non-empty project identifier.
        material_id: Non-empty material identifier from a project chunk ref.

    Returns:
        A project-relative source path when the project's doc store preserves
        one, otherwise ``None``. Absolute filesystem paths are intentionally not
        synthesized here because evidence packs are MCP/user-facing output.
    """

    normalized_project_id = str(project_id or "").strip()
    normalized_material_id = str(material_id or "").strip()
    if not normalized_project_id or not normalized_material_id:
        return None
    try:
        doc_store = _resources_router._load_doc_store(normalized_project_id)  # type: ignore[attr-defined]
    except Exception:
        return None
    if not isinstance(doc_store, dict):
        return None
    record = doc_store.get(normalized_material_id)
    if not isinstance(record, dict):
        return None
    source_path = str(record.get("source_relative_path") or "").strip()
    return source_path[:240] or None


def _fallback_source_labels(raw_labels: Any, fallback_labels: list[str]) -> list[str]:
    """Return explicit source labels, or bounded deterministic fallback labels."""

    if isinstance(raw_labels, (list, tuple, set)):
        labels = [str(label).strip() for label in raw_labels if str(label).strip()]
    else:
        raw_label = str(raw_labels or "").strip()
        labels = [raw_label] if raw_label else []
    if labels:
        return _bounded_unique_strings(labels, max_items=16, max_chars=80)
    return _bounded_unique_strings(fallback_labels, max_items=16, max_chars=80)


def _search_ref_to_evidence_ref(project_id: str, ref: Any) -> EvidencePackReferencePayload | None:
    """Project one search ref into the evidence-pack contract.

    Args:
        project_id: Project searched by the evidence-pack builder.
        ref: ``ChunkSearchRefPayload`` returned by the backend search-ref helper.

    Returns:
        A validated evidence-pack ref, or ``None`` when the search ref is not
        safe enough for public MCP output.
    """

    if ref is None:
        return None
    material_id = str(getattr(ref.metadata, "material_id", "") or "").strip()
    chunk_id = str(getattr(ref, "chunk_id", "") or "").strip()
    ref_id = str(getattr(ref, "ref_id", "") or "").strip()
    read_endpoint = str(getattr(ref, "read_endpoint", "") or "").strip()
    if not project_id.strip() or not material_id or not chunk_id or not ref_id or not read_endpoint:
        return None

    summary = _bounded_evidence_pack_summary(str(getattr(ref, "summary", "") or ""))
    source_title = _bounded_evidence_pack_summary(str(getattr(ref.metadata, "title", "") or summary))[:160]
    source_path = str(getattr(ref.metadata, "source_relative_path", "") or "").strip()[:240] or None
    if source_path is None:
        source_path = _material_source_path_from_doc_store(project_id, material_id)
    locator = getattr(ref.metadata, "locator", None)
    if not isinstance(locator, dict):
        locator = None
    page = getattr(ref.metadata, "page", None)
    if not isinstance(page, int) or isinstance(page, bool) or page <= 0:
        locator_page = locator.get("page") if isinstance(locator, dict) else None
        page = (
            locator_page
            if isinstance(locator_page, int) and not isinstance(locator_page, bool) and locator_page > 0
            else None
        )
    source_labels = _fallback_source_labels(
        getattr(ref.metadata, "source_labels", []),
        ["lexical", "project_chunks"],
    )
    figure_candidate = getattr(ref.metadata, "figure_candidate", None)
    figure_candidate = str(figure_candidate).strip()[:260] if figure_candidate is not None else None
    figure_candidate_detail = getattr(ref.metadata, "figure_candidate_detail", None)
    if not isinstance(figure_candidate_detail, dict):
        figure_candidate_detail = None
    image_paths = getattr(ref.metadata, "image_paths", [])
    if not isinstance(image_paths, list):
        image_paths = []
    bounded_image_paths = [str(path).strip()[:260] for path in image_paths if str(path).strip()][:8]
    lexical_score = float(getattr(ref, "lexical_score", 0.0) or 0.0)
    rerank_score = getattr(ref, "rerank_score", None)
    evidence_ref = EvidencePackReferencePayload(
        project_id=project_id,
        ref_id=ref_id,
        read_endpoint=read_endpoint,
        chunk_id=chunk_id,
        material_id=material_id,
        page=page,
        locator=locator,
        lexical_score=lexical_score,
        rerank_score=rerank_score,
        citation_anchor=_citation_anchor_from_ref(ref_id, material_id, chunk_id),
        figure_candidate=figure_candidate or None,
        figure_candidate_detail=figure_candidate_detail,
        image_paths=bounded_image_paths,
        source_labels=source_labels,
        summary=summary,
        suitable_for_body=bool(summary.strip()),
        source_title=source_title or None,
        source_path=source_path,
        quote=getattr(ref.metadata, "quote", None),
        anchor_kind=getattr(ref.metadata, "anchor_kind", None),
        content_hash=getattr(ref.metadata, "content_hash", None),
        locator_hash=getattr(ref.metadata, "locator_hash", None),
        chunk_hash=getattr(ref.metadata, "chunk_hash", None),
        embedding_input_hash=getattr(ref.metadata, "embedding_input_hash", None),
        hash_version=getattr(ref.metadata, "hash_version", None),
    )
    locator_quality = getattr(ref, "_locator_quality", None)
    if isinstance(locator_quality, dict):
        evidence_ref._locator_quality = dict(locator_quality)
    return evidence_ref


def _validated_scored_chunks(
    value: Any,
    *,
    source: str,
) -> list[tuple[float, dict[str, Any]]]:
    """Validate scored chunks returned through legacy untyped router imports."""

    if not isinstance(value, list):
        raise TypeError(f"{source} must return a list of scored chunks")
    validated: list[tuple[float, dict[str, Any]]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError(f"{source} returned a malformed scored chunk")
        score, chunk = item
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise TypeError(f"{source} returned a non-numeric score")
        if not isinstance(chunk, dict):
            raise TypeError(f"{source} returned a non-object chunk")
        validated.append((float(score), _json_object_or_empty(chunk)))
    return validated


def _select_project_evidence_chunks(
    *,
    project_id: str,
    all_chunks: list[dict[str, Any]],
    query: str,
    top_k: int,
) -> list[tuple[float, dict[str, Any]]]:
    """Return project evidence chunks through Gateway when its FTS gate is valid.

    Args:
        project_id: Project owning the chunk store.
        all_chunks: Flattened chunk-store truth already loaded by the caller.
        query: Non-empty evidence-pack query.
        top_k: Positive maximum chunks to return.

    Returns:
        Score/chunk pairs ready for evidence-pack ref projection.
    """

    normalized_project_id = str(project_id or "").strip()
    normalized_query = str(query or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be non-empty")
    if not isinstance(all_chunks, list):
        raise TypeError("all_chunks must be a list")
    if not normalized_query:
        raise ValueError("query must be non-empty")
    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be positive")

    try:
        gateway_hits = _resources_router._search_chunks_via_gateway(  # type: ignore[attr-defined]
            project_id=normalized_project_id,
            query=normalized_query,
            top_k=top_k,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        gateway_hits = None
    if gateway_hits:
        chunks_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for chunk in all_chunks:
            if not isinstance(chunk, dict):
                continue
            material_id = str(chunk.get("material_id") or "").strip()
            chunk_id = str(chunk.get("chunk_id") or "").strip()
            if material_id and chunk_id:
                chunks_by_key[(material_id, chunk_id)] = chunk
        selected: list[tuple[float, dict[str, Any]]] = []
        for hit in gateway_hits:
            if not isinstance(hit, dict):
                continue
            try:
                score = float(hit.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            material_id = str(hit.get("material_id") or "").strip()
            chunk_id = str(hit.get("chunk_id") or "").strip()
            selected_chunk = dict(chunks_by_key.get((material_id, chunk_id), hit))
            for key in ("score", "retrieval_sources", "retrieval_diagnostics"):
                if key in hit and key not in selected_chunk:
                    selected_chunk[key] = hit[key]
            selected.append((score, selected_chunk))
            if len(selected) >= top_k:
                break
        if selected:
            if _search_refs_visual_query_enabled(normalized_query):
                scored = _resources_router._score_chunks_for_query(all_chunks, normalized_query)
                return _validated_scored_chunks(
                    _merge_visual_search_ref_chunks(
                        normalized_query,
                        selected,
                        scored,
                        top_k=top_k,
                    ),
                    source="_merge_visual_search_ref_chunks",
                )
            if len(selected) < top_k:
                seen_keys = {
                    (
                        str(chunk.get("material_id") or "").strip(),
                        str(chunk.get("chunk_id") or "").strip(),
                    )
                    for _score, chunk in selected
                    if isinstance(chunk, dict)
                }
                fallback_chunks = _validated_scored_chunks(
                    _select_search_ref_chunks(
                        all_chunks,
                        normalized_query,
                        top_k=top_k,
                    ),
                    source="_select_search_ref_chunks",
                )
                for fallback_score, fallback_chunk in fallback_chunks:
                    fallback_key = (
                        str(fallback_chunk.get("material_id") or "").strip(),
                        str(fallback_chunk.get("chunk_id") or "").strip(),
                    )
                    if not fallback_key[1] or fallback_key in seen_keys:
                        continue
                    selected.append((fallback_score, fallback_chunk))
                    seen_keys.add(fallback_key)
                    if len(selected) >= top_k:
                        break
            return selected

    return _validated_scored_chunks(
        _select_search_ref_chunks(all_chunks, normalized_query, top_k=top_k),
        source="_select_search_ref_chunks",
    )


def _resolve_hybrid_retriever_class() -> Any | None:
    """Return the existing hybrid retriever class, or ``None`` if unavailable."""

    try:
        if TYPE_CHECKING:
            from literature_assistant.core.layers.r_layer_hybrid_retriever import HybridRetrieverWithRerank
        else:
            from layers.r_layer_hybrid_retriever import HybridRetrieverWithRerank
    except ImportError:
        return None
    return HybridRetrieverWithRerank


def _resolve_wiki_joint_recall_searcher() -> Any | None:
    """Return a bounded wiki searcher for joint recall diagnostics.

    The searcher returns wiki-ranked bounded refs. Wiki refs remain outside the
    project chunk store, but use the same agent resource reader contract as
    project chunks.
    """

    if not wiki_enabled():
        return None
    index_path = wiki_query_index_path()
    if not index_path.exists():
        return None
    integrity_gate = _wiki_joint_recall_integrity_gate()

    def _search(query: str, limit: int) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        index = WikiQueryIndex(index_path)
        store = _FinalWikiPageStore(wiki_generated_root(), create=False)
        try:
            results = index.search(query, limit=limit)
            refs = build_knowledge_refs(results, store, max_summary_chars=300)
            return [ref.to_hit(include_content=False) for ref in refs]
        finally:
            index.close()

    setattr(_search, "_wiki_integrity_gate", integrity_gate)
    return _search


def _wiki_joint_recall_integrity_gate() -> dict[str, Any]:
    """Return a read-only integrity gate for wiki joint recall."""

    if not wiki_enabled():
        return {
            "enabled": False,
            "allowed": False,
            "status": "disabled",
            "reason": "Wiki integration is disabled.",
            "error_class": "wiki_disabled",
        }
    index_path = wiki_query_index_path()
    if not index_path.exists():
        return {
            "enabled": True,
            "allowed": False,
            "status": "missing_index",
            "reason": "Wiki query index is missing; rebuild before using wiki refs in evidence packs.",
            "error_class": "wiki_index_missing",
            "indexed_page_count": 0,
            "source_page_count": None,
            "index_hash": "none",
            "source_manifest_hash": "unknown",
            "indexed_source_manifest_hash": "unknown",
        }
    index = WikiQueryIndex(index_path)
    store = WikiPageStore(wiki_generated_root(), create=False)
    try:
        status = index.get_status(store)
    except Exception as exc:
        return {
            "enabled": True,
            "allowed": False,
            "status": "unreadable_index",
            "reason": f"Wiki query index integrity could not be read: {type(exc).__name__}.",
            "error_class": "wiki_index_unreadable",
            "index_hash": "unknown",
            "source_manifest_hash": "unknown",
            "indexed_source_manifest_hash": "unknown",
        }
    finally:
        index.close()

    allowed = not status.stale and status.integrity_status == "aligned"
    error_class = "" if allowed else f"wiki_{status.integrity_status}"
    reason = (
        "Wiki query index is aligned with generated wiki pages."
        if allowed
        else "Wiki query index is not aligned with generated wiki pages; wiki refs are excluded from this evidence pack."
    )
    return {
        "enabled": True,
        "allowed": allowed,
        "status": status.integrity_status,
        "reason": reason,
        "error_class": error_class[:120],
        "warnings": list(status.warnings),
        "indexed_page_count": status.page_count,
        "source_page_count": status.source_page_count,
        "index_hash": status.index_hash,
        "source_manifest_hash": status.source_manifest_hash,
        "indexed_source_manifest_hash": status.indexed_source_manifest_hash,
        "last_indexed": status.last_indexed,
    }


def _blocked_wiki_joint_recall_result(
    *,
    policy: dict[str, Any],
    project_refs: list[EvidencePackReferencePayload],
    top_k: int,
    gate: dict[str, Any],
) -> tuple[dict[str, Any], list[EvidencePackReferencePayload]]:
    """Return project-only refs plus a blocked wiki integrity diagnostic."""

    return (
        {
            "enabled": bool(gate.get("enabled")),
            "status": "blocked",
            "reason": str(gate.get("reason") or "Wiki integrity gate blocked joint recall."),
            "fusion_method": policy["fusion"],
            "project_weight": float(policy["project_weight"]),
            "wiki_weight": float(policy["wiki_weight"]),
            "project_hit_count": len(project_refs),
            "wiki_hit_count": 0,
            "wiki_share_after_fusion": 0.0,
            "source_counts": {"project": min(len(project_refs), top_k), "wiki": 0},
            "integrity_gate": gate,
            "wiki_summaries": [],
        },
        project_refs[:top_k],
    )


def _project_hits_for_joint_recall(
    evidence_refs: list[EvidencePackReferencePayload],
) -> list[dict[str, Any]]:
    """Convert evidence refs into ranked project hits for fusion diagnostics."""

    hits: list[dict[str, Any]] = []
    for ref in evidence_refs:
        hits.append(
            {
                "doc_id": ref.ref_id,
                "chunk_id": ref.chunk_id,
                "title": ref.material_id,
                "summary": ref.summary,
                "source": "project",
            }
        )
    return hits


def _wiki_hit_to_evidence_ref(project_id: str, hit: dict[str, Any]) -> EvidencePackReferencePayload | None:
    """Project one bounded wiki hit into the evidence-pack ref contract.

    Wiki refs stay as agent-bridge resources and are not copied into project
    chunk stores. The project_id only scopes the evidence-pack build that
    selected the wiki evidence.
    """

    if not project_id.strip() or not isinstance(hit, dict):
        return None
    ref_id = str(hit.get("ref_id") or hit.get("doc_id") or "").strip()
    read_endpoint = str(hit.get("read_endpoint") or "").strip()
    summary = _bounded_evidence_pack_summary(str(hit.get("summary") or ""))
    if not ref_id.startswith("wiki:") or not read_endpoint or not summary.strip():
        return None
    source_path = str(hit.get("page_path") or ref_id.removeprefix("wiki:")).strip()[:240]
    stable_id = ref_id.removeprefix("wiki:").strip() or source_path or ref_id
    hit_chunk_id = str(hit.get("chunk_id") or "").strip()
    chunk_id = hit_chunk_id if hit_chunk_id.startswith("wiki:") else f"wiki:{stable_id}"
    return EvidencePackReferencePayload(
        project_id=project_id,
        source_type="wiki",
        ref_id=ref_id,
        read_endpoint=read_endpoint[:300],
        chunk_id=chunk_id[:260],
        material_id="wiki",
        page=None,
        lexical_score=0.0,
        rerank_score=None,
        citation_anchor=_citation_anchor_from_ref(ref_id, "wiki", stable_id),
        figure_candidate=None,
        source_labels=_fallback_source_labels(hit.get("source_labels"), ["wiki_joint_recall"]),
        summary=summary,
        suitable_for_body=True,
        source_title=str(hit.get("title") or "")[:160] or None,
        source_path=source_path or None,
    )


def _knowledge_hit_to_evidence_ref(
    project_id: str,
    hit: dict[str, Any],
    *,
    source_type: KnowledgeRefSourceType,
) -> EvidencePackReferencePayload | None:
    """Project one knowledge-package hit into the evidence-pack ref contract."""

    if not project_id.strip() or not isinstance(hit, dict):
        return None
    ref_id = str(hit.get("ref_id") or "").strip()
    read_endpoint = str(hit.get("read_endpoint") or "").strip()
    metadata = _json_object_or_empty(hit.get("metadata"))
    summary = _bounded_evidence_pack_summary(str(hit.get("summary") or ""))
    expected_read_endpoint = f"/api/agent-bridge/resource/{ref_id}"
    chunk_id = _knowledge_chunk_id_from_ref(ref_id, source_type)
    source_path = str(metadata.get("source_path") or "").strip()[:240]
    content_hash = str(metadata.get("content_hash") or "").strip()
    source_hash = str(metadata.get("source_hash") or "").strip()
    span_start = metadata.get("span_start")
    span_end = metadata.get("span_end")
    if (
        not chunk_id
        or read_endpoint != expected_read_endpoint
        or str(hit.get("kind") or "").strip() != source_type
        or not summary.strip()
        or not source_path
        or not content_hash
        or not source_hash
        or not isinstance(span_start, int)
        or not isinstance(span_end, int)
        or span_end < span_start
    ):
        return None
    lexical_score = float(hit.get("score") or 0.0)
    return EvidencePackReferencePayload(
        project_id=project_id,
        source_type=source_type,
        ref_id=ref_id,
        read_endpoint=read_endpoint[:300],
        chunk_id=f"{source_type}:{chunk_id}"[:260],
        material_id=source_type,
        page=None,
        locator=None,
        lexical_score=max(0.0, lexical_score),
        rerank_score=None,
        citation_anchor=_citation_anchor_from_ref(ref_id, source_type, chunk_id),
        figure_candidate=None,
        source_labels=_fallback_source_labels(
            metadata.get("source_labels"),
            ["knowledge_resource", source_type],
        ),
        summary=summary,
        suitable_for_body=True,
        source_title=str(hit.get("title") or "")[:160] or None,
        source_path=source_path or None,
    )


def _knowledge_chunk_id_from_ref(ref_id: str, source_type: KnowledgeRefSourceType) -> str:
    """Return a stable evidence-pack chunk id suffix from a knowledge ref."""

    if source_type == "product_docs" and ref_id.startswith("product_docs:chunk:"):
        return ref_id.removeprefix("product_docs:chunk:").strip()
    if source_type == "scoring_rules" and ref_id.startswith("scoring_rules:section:"):
        section_id = ref_id.removeprefix("scoring_rules:section:").strip()
        return f"section:{section_id}" if section_id else ""
    if source_type == "academic_english" and ref_id.startswith("academic_english:"):
        if ref_id == "academic_english:habits":
            return "habits:habits"
        parts = ref_id.split(":")
        if len(parts) == 3 and parts[1] in {"habits", "chunk", "phrase"}:
            resource_kind = parts[1].strip()
            item_id = parts[2].strip()
            if resource_kind and item_id:
                return f"{resource_kind}:{item_id}"
    if source_type == "skill_package" and ref_id.startswith("skill_package:"):
        parts = ref_id.split(":")
        if len(parts) == 4 and parts[2] == "chunk":
            package_id = parts[1].strip()
            chunk_id = parts[3].strip()
            if package_id and chunk_id:
                return f"{package_id}:chunk:{chunk_id}"
    if source_type == "source_vault" and ref_id.startswith("source_vault:chunk:"):
        return ref_id.removeprefix("source_vault:chunk:").strip()
    return ""


def _knowledge_summaries(
    hits: list[dict[str, Any]],
    top_k: int,
    *,
    source_type: KnowledgeRefSourceType,
) -> list[dict[str, Any]]:
    """Return bounded knowledge-package provenance summaries for diagnostics."""

    summaries: list[dict[str, Any]] = []
    for hit in hits[: max(0, min(top_k, _EVIDENCE_PACK_MAX_KNOWLEDGE_REFS))]:
        if not isinstance(hit, dict):
            continue
        metadata = _json_object_or_empty(hit.get("metadata"))
        summaries.append(
            {
                "ref_id": str(hit.get("ref_id") or ""),
                "read_endpoint": str(hit.get("read_endpoint") or "")[:300],
                "title": str(hit.get("title") or "")[:160],
                "summary": _bounded_evidence_pack_summary(str(hit.get("summary") or "")),
                "source_path": str(metadata.get("source_path") or "")[:240],
                "source_hash": str(metadata.get("source_hash") or "")[:80],
                "content_hash": str(metadata.get("content_hash") or "")[:80],
                "package_content_hash": str(metadata.get("package_content_hash") or "")[:80],
                "span_start": metadata.get("span_start"),
                "span_end": metadata.get("span_end"),
            }
        )
        if source_type == "scoring_rules":
            summaries[-1]["section_id"] = str(metadata.get("section_id") or "")[:120]
        if source_type == "academic_english":
            summaries[-1]["resource_kind"] = str(metadata.get("resource_kind") or "")[:80]
            summaries[-1]["policy_content_hash"] = str(metadata.get("policy_content_hash") or "")[:80]
            summaries[-1]["built_at"] = str(metadata.get("built_at") or "")[:120]
        if source_type == "skill_package":
            summaries[-1]["package_id"] = str(metadata.get("package_id") or "")[:120]
            summaries[-1]["source_role"] = str(metadata.get("source_role") or "")[:80]
        if source_type == "source_vault":
            summaries[-1]["source_id"] = str(metadata.get("source_id") or "")[:120]
            summaries[-1]["chunk_id"] = str(metadata.get("chunk_id") or "")[:160]
            summaries[-1]["chunker_version"] = str(metadata.get("chunker_version") or "")[:80]
    return summaries


def _search_source_vault_knowledge_refs(project_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
    """Return project-scoped Source Vault refs without copying chunk text into evidence packs."""

    if not project_id.strip() or not query.strip() or top_k < 1:
        return []
    hits: list[dict[str, Any]] = []
    for result in SourceVault().search_chunks(query, limit=top_k, project_id=project_id):
        ref_id = build_source_vault_chunk_ref_id(result.chunk_id)
        metadata = build_source_vault_search_metadata(result)
        hits.append(
            {
                "kind": "source_vault",
                "ref_id": ref_id,
                "read_endpoint": build_source_vault_chunk_read_endpoint(result.chunk_id),
                "title": result.title,
                "summary": _source_vault_provenance_summary(result),
                "score": abs(float(result.score)) if result.score is not None else 0.0,
                "metadata": metadata,
            }
        )
    return hits


def _source_vault_provenance_summary(result: Any) -> str:
    """Return a context-safe Source Vault summary that keeps raw chunk text behind resource_read."""

    title = str(getattr(result, "title", "") or "Source Vault source").strip()
    chunk_index = getattr(result, "chunk_index", None)
    page = getattr(result, "page", None)
    section = str(getattr(result, "section", "") or "").strip()
    details: list[str] = []
    if isinstance(chunk_index, int):
        details.append(f"chunk {chunk_index}")
    if isinstance(page, int) and page > 0:
        details.append(f"page {page}")
    if section:
        details.append(f"section {section[:80]}")
    suffix = f" ({', '.join(details)})" if details else ""
    return _bounded_evidence_pack_summary(f"Source Vault bounded ref from {title[:160]}{suffix}.")


def _knowledge_ref_providers() -> tuple[
    tuple[KnowledgeRefSourceType, Callable[[str, str, int], list[dict[str, Any]]]],
    ...,
]:
    """Return evidence-pack knowledge providers in deterministic priority order."""

    return (
        ("product_docs", lambda project_id, query, limit: search_product_docs(query, top_k=limit)),
        ("scoring_rules", lambda project_id, query, limit: search_scoring_rules(query, top_k=limit)),
        ("academic_english", lambda project_id, query, limit: search_academic_english(query, top_k=limit)),
        (
            "skill_package",
            lambda project_id, query, limit: search_skill_package(ACADEMIC_ENGLISH_SKILL_PACKAGE_ID, query, top_k=limit),
        ),
        ("source_vault", _search_source_vault_knowledge_refs),
    )


def _knowledge_ref_provider_enabled(query: str, source_type: KnowledgeRefSourceType) -> bool:
    """Return True when the query explicitly asks for a non-project knowledge domain.

    Args:
        query: User evidence-pack query text.
        source_type: Bounded knowledge provider kind.

    Returns:
        Whether the provider may contribute refs to this evidence pack.
    """

    normalized = re.sub(r"\s+", " ", str(query or "").strip().lower())
    if not normalized:
        return False
    triggers: dict[KnowledgeRefSourceType, tuple[str, ...]] = {
        "product_docs": (
            "scholar ai",
            "文献助手",
            "knowledge runtime",
            "agent resource",
            "product_docs",
            "mcp",
        ),
        "scoring_rules": (
            "direct_evidence",
            "high_quality",
            "scoring rule",
            "scoring_rules",
            "qrels",
            "rerank",
        ),
        "academic_english": (
            "academic english",
            "evidence-bound",
            "claim scope",
            "hedging",
            "rhetorical move",
        ),
        "skill_package": (
            "skill package",
            "academic-english-discourse",
            "discourse move",
            "evidence-bound",
        ),
        "source_vault": (
            "source vault",
            "source_vault",
        ),
    }
    return any(trigger in normalized for trigger in triggers[source_type])


def _attach_knowledge_refs(
    diagnostics: EvidenceRetrievalDiagnosticsPayload,
    *,
    project_id: str,
    query: str,
    evidence_refs: list[EvidencePackReferencePayload],
    top_k: int,
) -> tuple[EvidenceRetrievalDiagnosticsPayload, list[EvidencePackReferencePayload]]:
    """Attach bounded knowledge-package refs after project/wiki retrieval."""

    if not project_id.strip() or not query.strip() or top_k < 1:
        return diagnostics, evidence_refs
    if not evidence_refs:
        diagnostics.joint_recall["knowledge_refs"] = {
            "enabled": True,
            "status": "skipped",
            "reason": "Project evidence refs are required before knowledge refs are attached.",
            "source_counts": {kind: 0 for kind in _EVIDENCE_PACK_KNOWLEDGE_REF_KINDS},
            "product_docs_summaries": [],
            "scoring_rules_summaries": [],
        }
        return diagnostics, evidence_refs
    remaining = max(0, min(_EVIDENCE_PACK_MAX_KNOWLEDGE_REFS, top_k - len(evidence_refs)))
    if remaining <= 0:
        diagnostics.joint_recall["knowledge_refs"] = {
            "enabled": True,
            "status": "skipped",
            "reason": "Evidence pack top_k was already filled before knowledge refs were considered.",
            "source_counts": {kind: 0 for kind in _EVIDENCE_PACK_KNOWLEDGE_REF_KINDS},
            "product_docs_summaries": [],
            "scoring_rules_summaries": [],
        }
        return diagnostics, evidence_refs

    refs: list[EvidencePackReferencePayload] = []
    seen = {ref.ref_id for ref in evidence_refs}
    source_counts = {kind: 0 for kind in _EVIDENCE_PACK_KNOWLEDGE_REF_KINDS}
    summaries: dict[str, list[dict[str, Any]]] = {f"{kind}_summaries": [] for kind in _EVIDENCE_PACK_KNOWLEDGE_REF_KINDS}
    blocked: list[str] = []
    skipped: list[str] = []
    for source_type, searcher in _knowledge_ref_providers():
        if len(refs) >= remaining:
            break
        if not _knowledge_ref_provider_enabled(query, source_type):
            skipped.append(source_type)
            continue
        provider_limit = 1
        try:
            hits = searcher(project_id, query, provider_limit)
        except Exception as exc:
            blocked.append(source_type)
            diagnostics.notes = [
                *diagnostics.notes,
                f"{source_type} knowledge refs were blocked before entering this evidence pack.",
            ][:12]
            continue
        summaries[f"{source_type}_summaries"] = _knowledge_summaries(hits, top_k, source_type=source_type)
        for hit in hits:
            ref = _knowledge_hit_to_evidence_ref(project_id, hit, source_type=source_type)
            if ref is None or ref.ref_id in seen:
                continue
            refs.append(ref)
            seen.add(ref.ref_id)
            source_counts[source_type] += 1
            if len(refs) >= remaining:
                break

    status = "active" if refs else "blocked" if blocked else "empty"
    diagnostics.joint_recall["knowledge_refs"] = {
        "enabled": True,
        "status": status,
        "reason": (
            "Attached bounded knowledge refs that share agent resource ids with knowledge search."
            if refs
            else f"Knowledge ref providers were blocked: {', '.join(blocked)}."
            if blocked
            else "Knowledge package searches returned no bounded refs for this query."
        ),
        "source_counts": source_counts,
        "blocked_sources": blocked,
        "skipped_sources": skipped,
        **summaries,
    }
    if refs:
        diagnostics.reasoning_trace = [
            *diagnostics.reasoning_trace,
            "Attached knowledge refs through the same bounded agent resource protocol used by knowledge search.",
        ][:16]
        diagnostics.notes = [
            *diagnostics.notes,
            "knowledge_refs may include non-project bounded refs; raw knowledge content stays behind resource_read.",
        ][:12]
    return diagnostics, [*evidence_refs, *refs]


def _evidence_refs_from_fused_joint_hits(
    *,
    project_id: str,
    fused_hits: list[dict[str, Any]],
    project_refs: list[EvidencePackReferencePayload],
    top_k: int,
) -> list[EvidencePackReferencePayload]:
    """Return project+wiki evidence refs in weighted-RRF order."""

    if top_k < 1:
        raise ValueError("top_k must be positive")
    project_by_ref_id = {ref.ref_id: ref for ref in project_refs}
    output: list[EvidencePackReferencePayload] = []
    seen: set[str] = set()
    for fused in fused_hits:
        if not isinstance(fused, dict):
            continue
        doc_id = str(fused.get("doc_id") or "").strip()
        payload = _json_object_or_empty(fused.get("payload"))
        ref: EvidencePackReferencePayload | None = None
        if doc_id in project_by_ref_id:
            ref = project_by_ref_id[doc_id]
        elif str(fused.get("dominant_source") or "") == "wiki":
            ref = _wiki_hit_to_evidence_ref(project_id, payload)
        if ref is None or ref.ref_id in seen:
            continue
        ref.joint_score = float(fused.get("joint_score") or 0.0)
        output.append(ref)
        seen.add(ref.ref_id)
        if len(output) >= top_k:
            break
    if len(output) < top_k:
        for ref in project_refs:
            if ref.ref_id in seen:
                continue
            output.append(ref)
            seen.add(ref.ref_id)
            if len(output) >= top_k:
                break
    return output


def _joint_recall_diagnostics(
    *,
    project_id: str,
    query: str,
    project_refs: list[EvidencePackReferencePayload],
    top_k: int,
) -> tuple[dict[str, Any], list[EvidencePackReferencePayload]]:
    """Return wiki+project fusion diagnostics and fused evidence refs."""

    policy = default_joint_recall_policy()
    if not project_refs:
        return (
            {
                "enabled": True,
                "status": "empty",
                "reason": "Project evidence refs are required before wiki joint recall is attached.",
                "fusion_method": policy["fusion"],
                "project_weight": 1.0,
                "wiki_weight": 0.0,
                "project_hit_count": 0,
                "wiki_hit_count": 0,
                "wiki_share_after_fusion": 0.0,
                "source_counts": {"project": 0, "wiki": 0},
                "integrity_gate": {"status": "skipped", "reason": "no_project_refs"},
                "top_doc_ids": [],
                "wiki_summaries": [],
            },
            [],
        )
    searcher = _resolve_wiki_joint_recall_searcher()
    if searcher is None:
        gate = _wiki_joint_recall_integrity_gate()
        if gate.get("enabled") and not gate.get("allowed"):
            return _blocked_wiki_joint_recall_result(
                policy=policy,
                project_refs=project_refs,
                top_k=top_k,
                gate=gate,
            )
        return (
            {
                "enabled": False,
                "status": "unavailable",
                "reason": "wiki disabled or query index unavailable",
                "fusion_method": policy["fusion"],
                "project_weight": float(policy["project_weight"]),
                "wiki_weight": float(policy["wiki_weight"]),
                "project_hit_count": len(project_refs),
                "wiki_hit_count": 0,
                "wiki_share_after_fusion": 0.0,
                "source_counts": {"project": min(len(project_refs), top_k), "wiki": 0},
            },
            project_refs[:top_k],
        )
    raw_searcher_gate = getattr(searcher, "_wiki_integrity_gate", None)
    searcher_gate = (
        _json_object_or_empty(raw_searcher_gate)
        if isinstance(raw_searcher_gate, dict)
        else None
    )
    if searcher_gate is not None and not searcher_gate.get("allowed", False):
        return _blocked_wiki_joint_recall_result(
            policy=policy,
            project_refs=project_refs,
            top_k=top_k,
            gate=searcher_gate,
        )
    wiki_hits = searcher(query, max(top_k, int(policy.get("per_source_caps", {}).get("wiki", top_k))))
    if not isinstance(wiki_hits, list):
        wiki_hits = []
    if not wiki_hits:
        return (
            {
                "enabled": True,
                "status": "empty",
                "fusion_method": policy["fusion"],
                "project_weight": 1.0,
                "wiki_weight": 0.0,
                "project_hit_count": len(project_refs),
                "wiki_hit_count": 0,
                "wiki_share_after_fusion": 0.0,
                "source_counts": {"project": min(len(project_refs), top_k), "wiki": 0},
                "integrity_gate": searcher_gate if searcher_gate is not None else {"status": "unchecked"},
                "top_doc_ids": [ref.ref_id for ref in project_refs[: min(5, top_k)]],
                "wiki_summaries": [],
            },
            project_refs[:top_k],
        )
    fused = weighted_rrf_fuse(
        project_hits=_project_hits_for_joint_recall(project_refs),
        wiki_hits=[hit for hit in wiki_hits if isinstance(hit, dict)],
        top_k=top_k,
        policy=policy,
    )
    source_counts = {
        "project": sum(1 for hit in fused["hits"] if hit.get("dominant_source") == "project"),
        "wiki": sum(1 for hit in fused["hits"] if hit.get("dominant_source") == "wiki"),
    }
    evidence_refs = _evidence_refs_from_fused_joint_hits(
        project_id=project_id,
        fused_hits=fused["hits"],
        project_refs=project_refs,
        top_k=top_k,
    )
    return (
        {
            "enabled": True,
            "status": "active" if wiki_hits else "empty",
            "fusion_method": fused["fusion_method"],
            "project_weight": fused["project_weight"],
            "wiki_weight": fused["wiki_weight"],
            "project_hit_count": fused["project_hit_count"],
            "wiki_hit_count": fused["wiki_hit_count"],
            "wiki_share_after_fusion": fused["wiki_share_after_fusion"],
            "source_counts": source_counts,
            "integrity_gate": searcher_gate if searcher_gate is not None else {"status": "unchecked"},
            "top_doc_ids": [str(hit.get("doc_id") or "") for hit in fused["hits"][: min(5, top_k)]],
            "wiki_summaries": [
                {
                    "doc_id": str(hit.get("doc_id") or ""),
                    "ref_id": str(hit.get("ref_id") or hit.get("doc_id") or ""),
                    "read_endpoint": str(hit.get("read_endpoint") or "")[:300],
                    "title": str(hit.get("title") or "")[:160],
                    "summary": _bounded_evidence_pack_summary(str(hit.get("summary") or "")),
                    "page_path": str(hit.get("page_path") or "")[:240],
                    "source": str(hit.get("source") or "wiki")[:80],
                    "chunk_id": str(hit.get("chunk_id") or "")[:260],
                    "source_hash": str(hit.get("source_hash") or "")[:80],
                    "content_hash": str(hit.get("content_hash") or "")[:80],
                    "span_start": hit.get("span_start"),
                    "span_end": hit.get("span_end"),
                }
                for hit in wiki_hits[: min(3, top_k)]
                if isinstance(hit, dict)
            ],
        },
        evidence_refs,
    )


def _attach_joint_recall_diagnostics(
    diagnostics: EvidenceRetrievalDiagnosticsPayload,
    *,
    project_id: str,
    query: str,
    evidence_refs: list[EvidencePackReferencePayload],
    top_k: int,
) -> tuple[EvidenceRetrievalDiagnosticsPayload, list[EvidencePackReferencePayload]]:
    """Attach wiki+project recall diagnostics to an existing provenance payload."""

    joint, fused_refs = _joint_recall_diagnostics(
        project_id=project_id,
        query=query,
        project_refs=evidence_refs,
        top_k=top_k,
    )
    diagnostics.joint_recall = joint
    joint_status = str(joint.get("status") or "")
    if joint.get("enabled") and joint_status == "active":
        diagnostics.project_weight = float(joint.get("project_weight", diagnostics.project_weight))
        diagnostics.wiki_weight = float(joint.get("wiki_weight", diagnostics.wiki_weight))
        diagnostics.reasoning_trace = [
            *diagnostics.reasoning_trace,
            "Computed wiki+project weighted RRF and projected bounded wiki refs without adding wiki pages to project chunks.",
        ][:16]
        diagnostics.notes = [
            *diagnostics.notes,
            "joint_recall evidence_refs may include source_type=wiki bounded refs alongside project chunk refs.",
        ][:12]
    elif joint_status == "blocked":
        diagnostics.reasoning_trace = [
            *diagnostics.reasoning_trace,
            "Skipped wiki joint recall because the wiki integrity gate blocked stale or unproven wiki refs.",
        ][:16]
        diagnostics.notes = [
            *diagnostics.notes,
            "wiki_integrity_gate blocked wiki refs from entering this evidence pack.",
        ][:12]
    return diagnostics, fused_refs


async def _build_hybrid_evidence_refs(
    *,
    project_id: str,
    query: str,
    top_k: int,
    all_chunks: list[dict[str, Any]],
    chunk_store: dict[str, list[dict[str, Any]]],
) -> tuple[list[EvidencePackReferencePayload], EvidenceRetrievalDiagnosticsPayload] | None:
    """Try the existing hybrid retriever and return refs plus diagnostics.

    Args:
        project_id: Project owning the chunk store.
        query: Section/query text.
        top_k: Maximum evidence refs requested.
        all_chunks: Flattened project chunks already loaded by the caller.

    Returns:
        ``None`` when hybrid retrieval is unavailable or yields no usable refs;
        otherwise MCP-safe refs and an explicit diagnostic payload.
    """

    if not project_id.strip() or not query.strip() or top_k < 1 or not all_chunks:
        return None
    retriever_class = _resolve_hybrid_retriever_class()
    if retriever_class is None:
        return None

    retriever = retriever_class(use_reranker=None)
    try:
        hits = await retriever.search(
            {"chunks": all_chunks, "claim_index": all_chunks},
            query=query,
            top_k=top_k,
            focus_keywords=None,
        )
    except Exception:
        return None
    if not hits:
        return None

    evidence_refs: list[EvidencePackReferencePayload] = []
    dense_used = False
    rerank_active = False
    rerank_fallback = False
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        labels = [str(label).lower() for label in hit.get("source_labels", []) if isinstance(label, str)]
        dense_used = dense_used or "dense" in labels
        rerank_active = rerank_active or "rerank" in labels or hit.get("rerank_score") is not None
        rerank_fallback = rerank_fallback or "rerank_fallback" in labels
        score = float(hit.get("hybrid_score") or hit.get("rerank_score") or 0.0)
        search_ref = _chunk_to_search_ref(
            project_id,
            score,
            hit,
            chunk_store=chunk_store,
            query=query,
        )
        evidence_ref = _search_ref_to_evidence_ref(project_id, search_ref)
        if evidence_ref is None:
            continue
        if hit.get("rerank_score") is not None:
            evidence_ref.rerank_score = float(hit.get("rerank_score") or 0.0)
        evidence_refs.append(evidence_ref)
        if len(evidence_refs) >= top_k:
            break
    if not evidence_refs or not (dense_used or rerank_active or rerank_fallback):
        return None

    retrieval_method: Literal["hybrid", "hybrid_rerank"] = "hybrid_rerank" if rerank_active else "hybrid"
    embedding_status: Literal["active", "skipped", "unavailable"] = "active" if dense_used else "skipped"
    rerank_status: Literal["active", "skipped", "unavailable"] = (
        "active" if rerank_active and not rerank_fallback else "skipped"
    )
    fallback_reason = ""
    if rerank_fallback:
        fallback_reason = "Hybrid retrieval returned refs from rerank fallback; no active rerank model result was available."
    elif rerank_status != "active":
        fallback_reason = "Hybrid retrieval ran without an active rerank result."
    diagnostics = EvidenceRetrievalDiagnosticsPayload(
        retrieval_method=retrieval_method,
        embedding_status=embedding_status,
        rerank_status=rerank_status,
        fallback_reason=fallback_reason,
        project_weight=1.0,
        wiki_weight=0.0,
        reasoning_trace=[
            "Loaded persisted project chunk store.",
            "Ran existing ContextAwareRetriever/HybridRetrieverWithRerank over project chunks.",
            "Projected hybrid hits into MCP-safe evidence refs without raw content.",
            "Recorded dense/rerank provenance from retriever source labels and score fields.",
        ],
        notes=[
            "embedding_status=active requires chunk embeddings and query embedding success.",
            "rerank_status=active requires a returned rerank_score or rerank provenance label.",
        ],
    )
    return evidence_refs, diagnostics


def _protect_visual_evidence_refs(
    *,
    project_id: str,
    query: str,
    top_k: int,
    all_chunks: list[dict[str, Any]],
    chunk_store: dict[str, list[dict[str, Any]]],
    evidence_refs: list[EvidencePackReferencePayload],
    diagnostics: EvidenceRetrievalDiagnosticsPayload,
) -> list[EvidencePackReferencePayload]:
    """Ensure visual evidence packs keep at least one pixel-backed ref."""

    if (
        not _search_refs_visual_query_enabled(query)
        or top_k < 1
        or not all_chunks
        or any(_evidence_ref_image_assets(ref) for ref in evidence_refs)
    ):
        return evidence_refs[:top_k]

    selected = _select_search_ref_chunks(all_chunks, query, top_k=max(top_k, 5))
    protected_refs: list[EvidencePackReferencePayload] = []
    seen_ref_ids = {ref.ref_id for ref in evidence_refs}
    for score, chunk in selected:
        search_ref = _chunk_to_search_ref(
            project_id,
            score,
            chunk,
            chunk_store=chunk_store,
            query=query,
        )
        visual_ref = _search_ref_to_evidence_ref(project_id, search_ref)
        if visual_ref is None or visual_ref.ref_id in seen_ref_ids:
            continue
        if not _evidence_ref_image_assets(visual_ref):
            continue
        if "visual_image_asset" not in visual_ref.source_labels:
            visual_ref.source_labels = [*visual_ref.source_labels, "visual_image_asset"][:16]
        protected_refs.append(visual_ref)
        seen_ref_ids.add(visual_ref.ref_id)
        break
    if not protected_refs:
        return evidence_refs[:top_k]

    merged: list[EvidencePackReferencePayload] = []
    protected_ref_ids = {ref.ref_id for ref in protected_refs}
    for ref in evidence_refs:
        if ref.ref_id in protected_ref_ids:
            continue
        if len(merged) >= max(top_k - len(protected_refs), 0):
            break
        merged.append(ref)
    merged.extend(protected_refs)
    for ref in evidence_refs:
        if len(merged) >= top_k:
            break
        if ref.ref_id in {item.ref_id for item in merged}:
            continue
        merged.append(ref)

    diagnostics.reasoning_trace = [
        *diagnostics.reasoning_trace,
        "Protected one pixel-backed visual ref for an image/appearance evidence query.",
    ][:16]
    diagnostics.notes = [
        *diagnostics.notes,
        "Visual protected refs come from chunk/figure assets and do not imply rerank ran on that ref.",
    ][:12]
    return merged[:top_k]


def _lexical_evidence_diagnostics() -> EvidenceRetrievalDiagnosticsPayload:
    """Return the explicit lexical fallback diagnostics used by evidence packs."""

    return EvidenceRetrievalDiagnosticsPayload(
        retrieval_method="lexical",
        embedding_status="unavailable",
        rerank_status="unavailable",
        fallback_reason=(
            "Evidence-pack builder used the MCP-safe lexical fallback; "
            "dense embedding and local/API rerank were not invoked for this result."
        ),
        project_weight=1.0,
        wiki_weight=0.0,
        reasoning_trace=[
            "Loaded persisted project chunk store.",
            "Applied lexical token/sub-string scoring to existing chunks.",
            "Projected hits into MCP-safe evidence refs without raw content.",
            "Marked embedding/rerank unavailable because hybrid evidence-pack retrieval did not produce usable refs.",
        ],
        notes=[
            "Use retrieval_method/rerank_status to audit whether embedding or rerank participated.",
            "Hybrid/rerank evidence-pack retrieval runs only when existing retriever returns usable hits.",
        ],
    )


def _evidence_pack_qrels_attempt(qrels_status: RetrievalQrelsStatusPayload) -> ToolAttempt:
    """Return a bounded qrels quality-gate attempt for the outcome envelope."""

    if qrels_status.status == "canonical":
        return ToolAttempt(
            stage="qrels_quality_gate",
            status="success",
            reason="Canonical qrels are available for retrieval-quality evaluation.",
            metadata={
                "status": qrels_status.status,
                "canonical_qrels_count": qrels_status.canonical_qrels_count,
                "quality_claim": qrels_status.quality_claim,
            },
        )
    if qrels_status.status in {"candidate", "reviewed"}:
        return ToolAttempt(
            stage="qrels_quality_gate",
            status="blocked",
            reason="Retrieval quality claims require canonical qrels.",
            error_class="qrels_review_needed",
            recommendation="Review or promote qrels before making semantic retrieval-quality claims.",
            metadata={
                "status": qrels_status.status,
                "candidate_qrels_count": qrels_status.candidate_qrels_count,
                "reviewed_qrels_count": qrels_status.reviewed_qrels_count,
                "quality_claim": qrels_status.quality_claim,
            },
        )
    return ToolAttempt(
        stage="qrels_quality_gate",
        status="skipped",
        reason="No qrels were found; retrieval method is provenance, not semantic quality proof.",
        error_class="qrels_missing",
        metadata={
            "status": qrels_status.status,
            "quality_claim": qrels_status.quality_claim,
        },
    )


def _evidence_pack_locator_attempt(diagnostics: EvidenceRetrievalDiagnosticsPayload) -> ToolAttempt:
    """Return a locator-coverage attempt for workflow and integrity gates."""

    coverage = diagnostics.locator_coverage
    status: Literal["success", "blocked", "degraded"]
    if coverage.risk_level == "none":
        status = "success"
    elif coverage.risk_level == "block":
        status = "blocked"
    else:
        status = "degraded"
    reason_by_state: dict[str, str] = {
        "no_refs": "No project refs were returned for source locator coverage.",
        "missing": "Returned project refs are missing material/chunk locators.",
        "material_only": "Returned project refs identify chunks but lack source pages.",
        "page_located": "Returned project refs can jump to pages but not exact layout boxes.",
        "layout_partial": "Some returned project refs include page+bbox locators.",
        "layout_complete": "Every returned project ref includes material, page, and bbox locators.",
    }
    recommendation = ""
    if coverage.risk_level == "block":
        recommendation = "Run or repair material processing before treating these refs as fully auditable evidence."
    elif coverage.risk_level == "warn":
        recommendation = "Use page locators for review and add bbox-capable extraction before layout-sensitive claims."
    return ToolAttempt(
        stage="locator_coverage",
        status=status,
        reason=reason_by_state.get(coverage.coverage_state, "Locator coverage was computed."),
        error_class="" if coverage.risk_level == "none" else f"locator_coverage_{coverage.coverage_state}",
        recommendation=recommendation,
        metadata=coverage.model_dump(mode="json"),
    )


def _evidence_pack_wiki_integrity_attempt(diagnostics: EvidenceRetrievalDiagnosticsPayload) -> ToolAttempt:
    """Return a wiki integrity gate attempt for joint recall provenance."""

    joint = diagnostics.joint_recall if isinstance(diagnostics.joint_recall, dict) else {}
    gate = joint.get("integrity_gate") if isinstance(joint.get("integrity_gate"), dict) else {}
    if not gate:
        return ToolAttempt(
            stage="wiki_integrity_gate",
            status="skipped",
            reason="Wiki integrity gate was not evaluated for this evidence pack.",
            error_class="wiki_gate_unavailable",
            metadata={"joint_recall_status": str(joint.get("status") or "disabled")},
        )
    gate_status = str(gate.get("status") or "unknown")
    if gate.get("allowed") is True and gate_status == "aligned":
        return ToolAttempt(
            stage="wiki_integrity_gate",
            status="success",
            reason="Wiki query index is aligned with generated wiki pages.",
            metadata={
                "status": gate_status,
                "indexed_page_count": gate.get("indexed_page_count"),
                "source_page_count": gate.get("source_page_count"),
                "index_hash": gate.get("index_hash"),
                "source_manifest_hash": gate.get("source_manifest_hash"),
            },
        )
    if gate.get("enabled") is False:
        return ToolAttempt(
            stage="wiki_integrity_gate",
            status="skipped",
            reason=str(gate.get("reason") or "Wiki integration is disabled."),
            error_class=str(gate.get("error_class") or "wiki_disabled")[:120],
            metadata={"status": gate_status},
        )
    return ToolAttempt(
        stage="wiki_integrity_gate",
        status="blocked",
        reason=str(gate.get("reason") or "Wiki query index integrity blocked wiki refs.")[:240],
        error_class=str(gate.get("error_class") or f"wiki_{gate_status}")[:120],
        recommendation="Rebuild the wiki query index before using wiki refs in evidence-pack context.",
        metadata={
            "status": gate_status,
            "warnings": list(gate.get("warnings") or [])[:8],
            "indexed_page_count": gate.get("indexed_page_count"),
            "source_page_count": gate.get("source_page_count"),
            "index_hash": gate.get("index_hash"),
            "source_manifest_hash": gate.get("source_manifest_hash"),
            "indexed_source_manifest_hash": gate.get("indexed_source_manifest_hash"),
        },
    )


def _evidence_pack_knowledge_refs_attempt(diagnostics: EvidenceRetrievalDiagnosticsPayload) -> ToolAttempt:
    """Return a bounded knowledge-ref attempt for non-project context sources."""

    joint = _json_object_or_empty(diagnostics.joint_recall)
    knowledge_refs = _json_object_or_empty(joint.get("knowledge_refs"))
    if not knowledge_refs:
        return ToolAttempt(
            stage="knowledge_refs",
            status="skipped",
            reason="No non-project knowledge refs were evaluated for this evidence pack.",
            metadata={"enabled": False, "source_counts": {}},
        )
    status = str(knowledge_refs.get("status") or "skipped")
    source_counts = _json_object_or_empty(knowledge_refs.get("source_counts"))
    if status == "active":
        return ToolAttempt(
            stage="knowledge_refs",
            status="success",
            reason="Non-project knowledge refs contributed bounded agent resources.",
            metadata={"enabled": True, "status": status, "source_counts": dict(source_counts)},
        )
    if status == "blocked":
        return ToolAttempt(
            stage="knowledge_refs",
            status="blocked",
            reason=str(knowledge_refs.get("reason") or "Knowledge refs were blocked.")[:240],
            error_class=str(knowledge_refs.get("error_class") or "knowledge_refs_blocked")[:120],
            recommendation="Repair the knowledge package manifest/search path before loading these refs into model context.",
            metadata={"enabled": True, "status": status, "source_counts": dict(source_counts)},
        )
    return ToolAttempt(
        stage="knowledge_refs",
        status="skipped",
        reason=str(knowledge_refs.get("reason") or "No non-project knowledge refs contributed.")[:240],
        metadata={"enabled": True, "status": status, "source_counts": dict(source_counts)},
    )


def _evidence_pack_next_action(
    *,
    project_id: str,
    evidence_refs: list[EvidencePackReferencePayload],
    qrels_status: RetrievalQrelsStatusPayload,
) -> ToolNextAction:
    """Choose the safest follow-up that does not mutate project state implicitly."""

    if evidence_refs:
        first_ref = evidence_refs[0]
        return ToolNextAction(
            kind="read_resource",
            message="Read the top evidence resource before using the pack in prose.",
            endpoint=first_ref.read_endpoint,
            args={"project_id": project_id, "ref_id": first_ref.ref_id},
        )
    if qrels_status.status in {"candidate", "reviewed"}:
        return ToolNextAction(
            kind="review_qrels",
            message="Review or promote qrels before claiming semantic retrieval quality.",
            args={"project_id": project_id, "qrels_status": qrels_status.status},
        )
    return ToolNextAction(
        kind="scan_folder",
        message="No evidence refs were found; scan the project source folder after adding PDFs/full text.",
        tool_name="literature.project_scan_folder",
        args={"project_id": project_id},
    )


def _evidence_pack_outcome(
    *,
    project_id: str,
    all_chunks: list[dict[str, Any]],
    evidence_refs: list[EvidencePackReferencePayload],
    diagnostics: EvidenceRetrievalDiagnosticsPayload,
    positive_hit_count: int,
    qrels_status: RetrievalQrelsStatusPayload,
) -> ToolOutcome:
    """Build a ScanSci-style outcome envelope without changing legacy fields."""

    attempts: list[ToolAttempt] = [
        ToolAttempt(
            stage="chunk_load",
            status="success" if all_chunks else "skipped",
            reason=(
                "Loaded indexed project chunks."
                if all_chunks
                else "No indexed project chunks were found for this project."
            ),
            error_class="" if all_chunks else "ingest_needed",
            recommendation="" if all_chunks else "Add PDFs/full text and run literature.project_scan_folder.",
            metadata={"chunk_count": len(all_chunks)},
        )
    ]
    if all_chunks:
        attempts.append(
            ToolAttempt(
                stage="retrieval",
                status="success" if evidence_refs else "skipped",
                reason=(
                    f"Used {diagnostics.retrieval_method} retrieval and returned evidence refs."
                    if evidence_refs
                    else "Indexed chunks existed, but no positive lexical or hybrid hits were returned."
                ),
                error_class="" if evidence_refs else "retrieval_empty",
                metadata={
                    "retrieval_method": diagnostics.retrieval_method,
                    "positive_hit_count": positive_hit_count,
                    "returned_ref_count": len(evidence_refs),
                },
            )
        )
    attempts.append(
        ToolAttempt(
            stage="rerank",
            status="success" if diagnostics.rerank_status == "active" else "skipped",
            reason=(
                "Rerank participated in the evidence-pack result."
                if diagnostics.rerank_status == "active"
                else "Rerank did not participate in this evidence-pack result."
            ),
            error_class="" if diagnostics.rerank_status == "active" else "rerank_unavailable",
            recommendation=(
                ""
                if diagnostics.rerank_status == "active"
                else "Configure rerank or embeddings only if semantic reranking is required."
            ),
            metadata={
                "rerank_status": diagnostics.rerank_status,
                "embedding_status": diagnostics.embedding_status,
            },
        )
    )
    joint_status = str(diagnostics.joint_recall.get("status") or "disabled")
    attempts.append(
        ToolAttempt(
            stage="joint_recall",
            status="success" if joint_status == "active" else "blocked" if joint_status == "blocked" else "skipped",
            reason=(
                "Wiki+project joint recall contributed bounded refs."
                if joint_status == "active"
                else "Wiki+project joint recall was blocked by the wiki integrity gate."
                if joint_status == "blocked"
                else "Wiki+project joint recall did not contribute refs."
            ),
            error_class="wiki_integrity_blocked" if joint_status == "blocked" else "",
            metadata={
                "enabled": bool(diagnostics.joint_recall.get("enabled")),
                "status": joint_status,
                "project_weight": diagnostics.project_weight,
                "wiki_weight": diagnostics.wiki_weight,
            },
        )
    )
    attempts.append(_evidence_pack_wiki_integrity_attempt(diagnostics))
    attempts.append(_evidence_pack_knowledge_refs_attempt(diagnostics))
    attempts.append(_evidence_pack_locator_attempt(diagnostics))
    attempts.append(_evidence_pack_qrels_attempt(qrels_status))

    if evidence_refs:
        outcome_status: Literal["success", "degraded", "empty"] = (
            "success" if diagnostics.rerank_status == "active" else "degraded"
        )
        reason = (
            "Evidence refs returned with active rerank provenance."
            if diagnostics.rerank_status == "active"
            else "Evidence refs returned without active rerank provenance."
        )
    elif all_chunks:
        outcome_status = "empty"
        reason = "Project chunks were indexed, but this query returned no evidence refs."
    else:
        outcome_status = "empty"
        reason = "No indexed project chunks were available for evidence-pack retrieval."

    return ToolOutcome(
        status=outcome_status,
        quality="refs_only" if evidence_refs else "none",
        reason=reason,
        next_action=_evidence_pack_next_action(
            project_id=project_id,
            evidence_refs=evidence_refs,
            qrels_status=qrels_status,
        ),
        attempts=attempts,
    )


def _evidence_pack_visual_intent(query: str) -> dict[str, Any]:
    """Return a bounded visual-intent signal from the public query text."""

    text = str(query or "").strip().lower()
    matched_terms: list[str] = []
    categories: list[str] = []
    for category, terms in _EVIDENCE_PACK_VISUAL_TERMS.items():
        category_matches = [term for term in terms if term.lower() in text]
        if category_matches:
            categories.append(category)
            matched_terms.extend(category_matches)
    unique_terms = list(dict.fromkeys(matched_terms))[:12]
    return {
        "requires_image_evidence": bool(unique_terms),
        "categories": categories[:8],
        "matched_terms": unique_terms,
    }


def _evidence_pack_gate_config_hash() -> str:
    """Return the content-derived identifier for the integrity-gate policy."""

    policy = {
        "schema_version": "scholar_ai_evidence_pack_integrity_gate_v1",
        "policy_version": _EVIDENCE_PACK_INTEGRITY_GATE_POLICY_VERSION,
        "checks": [
            "refs_present",
            "source_locators",
            "citation_identity",
            "visual_image_evidence",
            "image_asset_quality",
        ],
        "visual_terms": {
            key: list(values)
            for key, values in sorted(_EVIDENCE_PACK_VISUAL_TERMS.items())
        },
        "image_asset_keys": sorted(_EVIDENCE_PACK_IMAGE_ASSET_KEYS),
        "whole_page_asset_patterns": [
            "screenshot",
            "whole_page",
            "full_page",
            "page_<number>.<image>",
            "p<number>_page.<image>",
        ],
    }
    serialized = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def _looks_like_image_asset_key(key: str) -> bool:
    """Return whether a metadata key is allowed to contribute image paths."""

    normalized = str(key or "").strip().lower()
    if not normalized:
        return False
    if normalized in _EVIDENCE_PACK_IMAGE_ASSET_KEYS:
        return True
    return (
        ("image" in normalized and ("path" in normalized or "asset" in normalized or "url" in normalized))
        or ("asset" in normalized and "path" in normalized)
        or ("crop" in normalized and "path" in normalized)
    )


def _bounded_unique_strings(values: list[str], *, max_items: int, max_chars: int) -> list[str]:
    """Return stable bounded strings for MCP-safe diagnostics."""

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text[:max_chars])
        if len(output) >= max_items:
            break
    return output


def _image_assets_from_detail(value: Any, *, key_hint: str = "", depth: int = 0) -> list[str]:
    """Extract image asset strings only from explicit image/path metadata keys."""

    if depth > 4:
        return []
    if isinstance(value, str):
        return [value] if _looks_like_image_asset_key(key_hint) else []
    if isinstance(value, list):
        list_assets: list[str] = []
        for item in value[:20]:
            if isinstance(item, str) and _looks_like_image_asset_key(key_hint):
                list_assets.append(item)
            elif isinstance(item, (dict, list)):
                list_assets.extend(_image_assets_from_detail(item, key_hint=key_hint, depth=depth + 1))
        return list_assets
    if isinstance(value, dict):
        mapping_assets: list[str] = []
        for key, item in list(value.items())[:40]:
            mapping_assets.extend(_image_assets_from_detail(item, key_hint=str(key), depth=depth + 1))
        return mapping_assets
    return []


def _evidence_ref_image_assets(ref: EvidencePackReferencePayload) -> list[str]:
    """Return bounded image assets linked to one evidence ref."""

    assets = [str(path) for path in ref.image_paths if str(path or "").strip()]
    if isinstance(ref.figure_candidate_detail, dict):
        assets.extend(_image_assets_from_detail(ref.figure_candidate_detail))
    return _bounded_unique_strings(assets, max_items=8, max_chars=260)


def _is_whole_page_image_asset(path: str) -> bool:
    """Return whether an asset name looks like a whole-page render."""

    filename = str(path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not filename:
        return False
    if "screenshot" in filename:
        return True
    if "whole" in filename and "page" in filename:
        return True
    if "full" in filename and "page" in filename:
        return True
    if re.search(r"(?:^|[_-])page[_-]?\d{1,5}\.(?:png|jpe?g|webp)$", filename):
        return True
    if re.search(r"(?:^|[_-])p\d{1,5}[_-]?page\.(?:png|jpe?g|webp)$", filename):
        return True
    return False


def _evidence_ref_page(ref: EvidencePackReferencePayload) -> int | None:
    """Return the best available one-based page for an evidence ref."""

    if isinstance(ref.page, int) and not isinstance(ref.page, bool) and ref.page > 0:
        return ref.page
    locator = ref.locator if isinstance(ref.locator, dict) else {}
    page = locator.get("page")
    if isinstance(page, int) and not isinstance(page, bool) and page > 0:
        return page
    return None


def _evidence_ref_has_bbox(ref: EvidencePackReferencePayload) -> bool:
    """Return whether a project ref carries a valid layout bbox."""

    locator = ref.locator if isinstance(ref.locator, dict) else {}
    for key in ("bbox", "pdf_bbox", "normalized_bbox"):
        if coerce_pdf_bbox(locator.get(key)) is not None:
            return True
    return False


def _evidence_pack_sample_refs(refs: list[EvidencePackReferencePayload]) -> list[dict[str, Any]]:
    """Return top refs with enough fields for human/agent evidence judgment."""

    samples: list[dict[str, Any]] = []
    for ref in refs[:12]:
        image_assets = _evidence_ref_image_assets(ref)
        item: dict[str, Any] = {
            "ref_id": ref.ref_id,
            "source_type": ref.source_type,
            "source_title": ref.source_title,
            "source_path": ref.source_path,
            "material_id": ref.material_id,
            "chunk_id": ref.chunk_id,
            "page": _evidence_ref_page(ref),
            "lexical_score": round(float(ref.lexical_score or 0.0), 6),
            "rerank_score": round(float(ref.rerank_score), 6) if ref.rerank_score is not None else None,
            "citation_anchor": ref.citation_anchor,
            "figure_candidate": ref.figure_candidate,
            "has_image": bool(image_assets),
            "image_asset_count": len(image_assets),
            "image_assets": image_assets[:3],
            "source_labels": ref.source_labels[:8],
            "summary": ref.summary,
        }
        samples.append(item)
    return samples


def _evidence_pack_check(
    check_id: str,
    status: Literal["passed", "warning", "blocked", "unresolved"],
    severity: Literal["none", "note", "warn", "block"],
    reason: str,
    *,
    recommendation: str = "",
    metadata: dict[str, Any] | None = None,
) -> EvidencePackIntegrityCheckPayload:
    """Create one validated integrity check row."""

    return EvidencePackIntegrityCheckPayload(
        check_id=check_id,
        status=status,
        severity=severity,
        reason=reason[:500],
        recommendation=recommendation[:500],
        metadata=dict(metadata or {}),
    )


def _aggregate_evidence_pack_gate_status(
    checks: list[EvidencePackIntegrityCheckPayload],
) -> Literal["passed", "warning", "blocked", "unresolved"]:
    """Return the aggregate status without treating unresolved as passed."""

    if not checks:
        return "unresolved"
    statuses = {check.status for check in checks}
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    if "unresolved" in statuses:
        return "unresolved"
    return "passed"


def _evidence_pack_next_actions(
    *,
    summary: dict[str, Any],
    visual_intent: dict[str, Any],
    status: str,
) -> list[str]:
    """Return bounded repair/review actions for the evidence-pack gate."""

    actions: list[str] = []
    if int(summary.get("evidence_ref_count") or 0) == 0:
        actions.append("Build an evidence pack with literature.evidence_pack_build before using this gate.")
    if visual_intent.get("requires_image_evidence") and int(summary.get("image_ref_count") or 0) == 0:
        actions.append("Retry retrieval with appearance/surface/image terms and require pixel-backed figure candidates.")
    if int(summary.get("whole_page_image_ref_count") or 0) > 0:
        actions.append("Use pixel-level figure/table crops instead of whole-page PDF renders for visual evidence.")
    if int(summary.get("missing_page_count") or 0) > 0:
        actions.append("Review material processing locator coverage before citing page-specific claims.")
    if int(summary.get("missing_source_title_count") or 0) > 0:
        actions.append("Repair source-title metadata so citation links identify the exact literature item.")
    if not actions and status == "passed":
        actions.append("Read the top evidence refs, then cite only claims directly supported by those refs.")
    return actions[:12]


def _build_evidence_pack_integrity_gate(
    request: EvidencePackIntegrityGateRequest,
) -> EvidencePackIntegrityGateResponse:
    """Build a read-only integrity gate over one supplied evidence pack."""

    project_id = request.project_id.strip()
    if not project_id:
        raise ValueError("project_id must be non-empty")
    query = request.query.strip()
    refs = list(request.evidence_refs)
    retrieval_diagnostics = request.retrieval_diagnostics
    restored_pack: EvidencePackBuildResponse | None = None
    restore_status = "not_requested"
    if request.evidence_pack_ref:
        restore_status = "supplied_refs" if refs else "not_found"
    if not refs and request.evidence_pack_ref:
        restored_pack = _restore_evidence_pack_build(
            project_id=project_id,
            query=query,
            evidence_pack_ref=request.evidence_pack_ref,
        )
        if restored_pack is not None:
            refs = list(restored_pack.evidence_refs)
            query = query or restored_pack.query
            if retrieval_diagnostics is None:
                retrieval_diagnostics = restored_pack.retrieval_diagnostics
            restore_status = "restored"
    visual_intent = _evidence_pack_visual_intent(query)

    image_assets_by_ref: dict[str, list[str]] = {
        ref.ref_id: _evidence_ref_image_assets(ref)
        for ref in refs
    }
    all_image_assets = [
        asset
        for assets in image_assets_by_ref.values()
        for asset in assets
    ]
    duplicate_image_assets = sorted(
        asset
        for asset in set(all_image_assets)
        if all_image_assets.count(asset) > 1
    )[:8]
    whole_page_ref_ids = [
        ref.ref_id
        for ref in refs
        if any(_is_whole_page_image_asset(asset) for asset in image_assets_by_ref.get(ref.ref_id, []))
    ]
    project_refs = [ref for ref in refs if ref.source_type == "project"]
    page_refs = [ref for ref in project_refs if _evidence_ref_page(ref) is not None]
    bbox_refs = [ref for ref in project_refs if _evidence_ref_has_bbox(ref)]
    title_refs = [ref for ref in refs if str(ref.source_title or ref.source_path or "").strip()]
    citation_anchor_refs = [ref for ref in refs if str(ref.citation_anchor or "").strip()]
    image_refs = [ref for ref in refs if image_assets_by_ref.get(ref.ref_id)]

    summary: dict[str, Any] = {
        "evidence_ref_count": len(refs),
        "project_ref_count": len(project_refs),
        "non_project_ref_count": len(refs) - len(project_refs),
        "page_locator_count": len(page_refs),
        "bbox_locator_count": len(bbox_refs),
        "source_title_count": len(title_refs),
        "citation_anchor_count": len(citation_anchor_refs),
        "image_ref_count": len(image_refs),
        "image_asset_count": len(_bounded_unique_strings(all_image_assets, max_items=100, max_chars=260)),
        "duplicate_image_asset_count": len(duplicate_image_assets),
        "whole_page_image_ref_count": len(whole_page_ref_ids),
        "missing_page_count": max(0, len(project_refs) - len(page_refs)),
        "missing_bbox_count": max(0, len(project_refs) - len(bbox_refs)),
        "missing_source_title_count": max(0, len(refs) - len(title_refs)),
        "missing_citation_anchor_count": max(0, len(refs) - len(citation_anchor_refs)),
        "sample_missing_page_ref_ids": [
            ref.ref_id for ref in project_refs if _evidence_ref_page(ref) is None
        ][:8],
        "sample_missing_source_title_ref_ids": [
            ref.ref_id for ref in refs if not str(ref.source_title or ref.source_path or "").strip()
        ][:8],
        "sample_duplicate_image_assets": duplicate_image_assets,
        "sample_whole_page_image_ref_ids": whole_page_ref_ids[:8],
    }
    if request.evidence_pack_ref:
        summary["evidence_pack_restore_status"] = restore_status
    if retrieval_diagnostics is not None:
        summary["retrieval_method"] = retrieval_diagnostics.retrieval_method
        summary["rerank_status"] = retrieval_diagnostics.rerank_status
        summary["embedding_status"] = retrieval_diagnostics.embedding_status
    gate_config_hash = _evidence_pack_gate_config_hash()
    summary["gate_config_hash"] = gate_config_hash

    checks: list[EvidencePackIntegrityCheckPayload] = []
    checks.append(
        _evidence_pack_check(
            "refs_present",
            "passed" if refs else "blocked",
            "none" if refs else "block",
            "Evidence refs are present for this query." if refs else "No evidence refs were supplied to this gate.",
            recommendation="" if refs else "Run literature.evidence_pack_build and pass its evidence_refs into this gate.",
            metadata={"evidence_ref_count": len(refs)},
        )
    )

    locator_status: Literal["passed", "warning", "blocked", "unresolved"] = "passed"
    locator_severity: Literal["none", "note", "warn", "block"] = "none"
    locator_reason = "Project refs include page locators for citation review."
    locator_recommendation = ""
    if project_refs and not page_refs:
        locator_status = "warning"
        locator_severity = "warn"
        locator_reason = "Project refs identify chunks but do not include page locators."
        locator_recommendation = "Refresh material processing with locator extraction before page-specific citation."
    elif project_refs and len(page_refs) < len(project_refs):
        locator_status = "warning"
        locator_severity = "warn"
        locator_reason = "Some project refs are missing page locators."
        locator_recommendation = "Review missing locator refs before relying on exact source navigation."
    elif not project_refs and refs:
        locator_status = "warning"
        locator_severity = "warn"
        locator_reason = "This pack contains no project-local refs, so local PDF locator coverage cannot be proven."
    checks.append(
        _evidence_pack_check(
            "source_locators",
            locator_status,
            locator_severity,
            locator_reason,
            recommendation=locator_recommendation,
            metadata={
                "project_ref_count": len(project_refs),
                "page_locator_count": len(page_refs),
                "bbox_locator_count": len(bbox_refs),
                "missing_page_count": summary["missing_page_count"],
                "missing_bbox_count": summary["missing_bbox_count"],
            },
        )
    )

    citation_status: Literal["passed", "warning", "blocked", "unresolved"] = "passed"
    citation_severity: Literal["none", "note", "warn", "block"] = "none"
    citation_reason = "Refs include citation anchors and source labels/titles for user-facing identification."
    citation_recommendation = ""
    if refs and (len(title_refs) < len(refs) or len(citation_anchor_refs) < len(refs)):
        citation_status = "warning"
        citation_severity = "warn"
        citation_reason = "Some refs are missing source titles or citation anchors."
        citation_recommendation = "Repair source metadata before rendering citation links for users."
    checks.append(
        _evidence_pack_check(
            "citation_identity",
            citation_status,
            citation_severity,
            citation_reason,
            recommendation=citation_recommendation,
            metadata={
                "source_title_count": len(title_refs),
                "citation_anchor_count": len(citation_anchor_refs),
                "missing_source_title_count": summary["missing_source_title_count"],
                "missing_citation_anchor_count": summary["missing_citation_anchor_count"],
            },
        )
    )

    visual_required = bool(visual_intent.get("requires_image_evidence"))
    visual_status: Literal["passed", "warning", "blocked", "unresolved"] = "passed"
    visual_severity: Literal["none", "note", "warn", "block"] = "none"
    visual_reason = "This query does not require image-backed evidence."
    visual_recommendation = ""
    if visual_required and not image_refs:
        visual_status = "blocked"
        visual_severity = "block"
        visual_reason = "The query asks for visual/appearance evidence, but no returned ref has pixel-backed image assets."
        visual_recommendation = "Retry evidence retrieval with appearance, surface morphology, figure, and image terms."
    elif visual_required:
        visual_reason = "The visual query has at least one pixel-backed evidence ref."
    checks.append(
        _evidence_pack_check(
            "visual_image_evidence",
            visual_status,
            visual_severity,
            visual_reason,
            recommendation=visual_recommendation,
            metadata={
                "requires_image_evidence": visual_required,
                "image_ref_count": len(image_refs),
                "image_asset_count": summary["image_asset_count"],
                "matched_terms": visual_intent.get("matched_terms", []),
            },
        )
    )

    asset_quality_status: Literal["passed", "warning", "blocked", "unresolved"] = "passed"
    asset_quality_severity: Literal["none", "note", "warn", "block"] = "none"
    asset_quality_reason = "Image assets do not look like duplicate or whole-page substitutes."
    asset_quality_recommendation = ""
    if visual_required and image_refs and len(whole_page_ref_ids) == len(image_refs):
        asset_quality_status = "blocked"
        asset_quality_severity = "block"
        asset_quality_reason = "All image-backed refs look like whole-page renders rather than figure/table crops."
        asset_quality_recommendation = "Use extracted figure/table image assets, not rendered PDF pages."
    elif duplicate_image_assets or whole_page_ref_ids:
        asset_quality_status = "warning"
        asset_quality_severity = "warn"
        asset_quality_reason = "Some image assets are duplicated or look like whole-page renders."
        asset_quality_recommendation = "Prefer unique pixel-level figure/table crops for visual answers."
    checks.append(
        _evidence_pack_check(
            "image_asset_quality",
            asset_quality_status,
            asset_quality_severity,
            asset_quality_reason,
            recommendation=asset_quality_recommendation,
            metadata={
                "duplicate_image_asset_count": len(duplicate_image_assets),
                "whole_page_image_ref_count": len(whole_page_ref_ids),
                "sample_duplicate_image_assets": duplicate_image_assets,
                "sample_whole_page_image_ref_ids": whole_page_ref_ids[:8],
            },
        )
    )

    status = _aggregate_evidence_pack_gate_status(checks)
    next_actions = _evidence_pack_next_actions(
        summary=summary,
        visual_intent=visual_intent,
        status=status,
    )
    return EvidencePackIntegrityGateResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        gate_config_hash=gate_config_hash,
        project_id=project_id,
        evidence_pack_ref=request.evidence_pack_ref,
        query=query,
        status=status,
        visual_intent=visual_intent,
        summary=summary,
        checks=checks,
        sample_refs=_evidence_pack_sample_refs(refs),
        next_actions=next_actions,
        provenance={
            "derived_from": [
                "/api/evidence-pack/build.evidence_refs",
                "/api/evidence-pack/integrity-gate",
            ],
            "read_only": True,
            "gate_config_hash": gate_config_hash,
            "restored_from_persisted_build": restored_pack is not None,
            "raw_chunk_text_exposed": False,
            "private_chain_of_thought_exposed": False,
            "policy": "Validate the supplied evidence pack, not workflow export readiness.",
        },
    )


@router.post("/api/evidence-pack/build", response_model=EvidencePackBuildResponse)
async def build_evidence_pack(request: EvidencePackBuildRequest) -> EvidencePackBuildResponse:
    """Build a query-scoped evidence pack from existing project chunks.

    The current production-safe implementation is explicit lexical fallback:
    it reuses the same white-listed search-ref projection as MCP retrieval and
    reports rerank as unavailable rather than implying hybrid retrieval ran.
    """

    project_id = request.project_id.strip()
    query = request.query.strip()
    section_id = request.section_id.strip() if isinstance(request.section_id, str) and request.section_id.strip() else None
    if not project_id:
        raise HTTPException(status_code=422, detail="project_id must be non-empty")
    if not query:
        raise HTTPException(status_code=422, detail="query must be non-empty")

    visual_query = _search_refs_visual_query_enabled(query)
    fast_selection = None if visual_query else _select_search_ref_chunks_fts_first(
        project_id=project_id,
        query=query,
        top_k=request.top_k,
    )
    preselected_chunks: list[tuple[float, dict[str, Any]]] | None = None
    if fast_selection is None or not fast_selection[1]:
        # A valid FTS index can legitimately return no rows. The evidence-pack
        # contract still needs to distinguish "no query hit" from "no chunks";
        # rescan the truth store once so lexical fallback and outcome metadata
        # remain accurate. Query hits keep the bounded material-only path.
        chunk_store = _resources_router._load_chunk_store(project_id)
        all_chunks = _flatten_chunk_store_for_search_refs(chunk_store)
    else:
        chunk_store, all_chunks, preselected_chunks = fast_selection
    if visual_query:
        all_chunks = _augment_chunks_with_project_figure_assets(project_id, chunk_store, all_chunks)
        all_chunks = _augment_chunks_with_linked_visual_assets(chunk_store, all_chunks)
    evidence_refs: list[EvidencePackReferencePayload] = []
    positive_hit_count = 0
    retrieval_method: Literal["lexical", "hybrid", "hybrid_rerank"] = "lexical"
    rerank_status: Literal["active", "skipped", "unavailable"] = "unavailable"
    diagnostics = _lexical_evidence_diagnostics()
    if all_chunks:
        hybrid_result = await _build_hybrid_evidence_refs(
            project_id=project_id,
            query=query,
            top_k=request.top_k,
            all_chunks=all_chunks,
            chunk_store=chunk_store,
        )
        if hybrid_result is not None:
            evidence_refs, diagnostics = hybrid_result
            evidence_refs = _protect_visual_evidence_refs(
                project_id=project_id,
                query=query,
                top_k=request.top_k,
                all_chunks=all_chunks,
                chunk_store=chunk_store,
                evidence_refs=evidence_refs,
                diagnostics=diagnostics,
            )
            retrieval_method = diagnostics.retrieval_method
            rerank_status = diagnostics.rerank_status
            positive_hit_count = len(evidence_refs)
        else:
            scored = _resources_router._score_chunks_for_query(all_chunks, query)
            positive_hit_count = len([score for score, _chunk in scored if score > 0])
            selected_chunks = preselected_chunks
            if selected_chunks is None:
                selected_chunks = _select_project_evidence_chunks(
                    project_id=project_id,
                    all_chunks=all_chunks,
                    query=query,
                    top_k=request.top_k,
                )
            positive_hit_count = max(positive_hit_count, len(selected_chunks))
            for score, chunk in selected_chunks:
                search_ref = _chunk_to_search_ref(
                    project_id,
                    score,
                    chunk,
                    chunk_store=chunk_store,
                    query=query,
                )
                evidence_ref = _search_ref_to_evidence_ref(project_id, search_ref)
                if evidence_ref is not None:
                    evidence_refs.append(evidence_ref)

    diagnostics, evidence_refs = _attach_joint_recall_diagnostics(
        diagnostics,
        project_id=project_id,
        query=query,
        evidence_refs=evidence_refs,
        top_k=request.top_k,
    )
    diagnostics, evidence_refs = _attach_knowledge_refs(
        diagnostics,
        project_id=project_id,
        query=query,
        evidence_refs=evidence_refs,
        top_k=request.top_k,
    )
    diagnostics.locator_coverage = build_locator_coverage(evidence_refs)
    qrels_status = _project_qrels_status(project_id)
    diagnostics.qrels_status = qrels_status
    outcome = _evidence_pack_outcome(
        project_id=project_id,
        all_chunks=all_chunks,
        evidence_refs=evidence_refs,
        diagnostics=diagnostics,
        positive_hit_count=positive_hit_count,
        qrels_status=qrels_status,
    )

    response = EvidencePackBuildResponse(
        evidence_pack_ref=_evidence_pack_ref(project_id, query, section_id),
        project_id=project_id,
        query=query,
        section_id=section_id,
        retrieval_method=retrieval_method,
        rerank_status=rerank_status,
        total=len(evidence_refs),
        truncated=positive_hit_count > len(evidence_refs),
        retrieval_diagnostics=diagnostics,
        outcome=outcome,
        evidence_refs=evidence_refs,
    )
    _remember_evidence_pack_build(response)
    return response


@router.post("/api/evidence-pack/qrels-review-bundle", response_model=EvidenceQrelsReviewBundleResponse)
async def build_evidence_pack_qrels_review_bundle(
    request: EvidenceQrelsReviewBundleRequest,
) -> EvidenceQrelsReviewBundleResponse:
    """Generate a candidate-only qrels review bundle from a selected pack."""

    pack = _restore_evidence_pack_build(
        project_id=request.project_id,
        query=request.query,
        evidence_pack_ref=request.evidence_pack_ref,
    )
    if pack is None:
        raise HTTPException(status_code=404, detail="evidence_pack_ref could not be restored for this project/query")
    try:
        return _build_qrels_review_bundle_response(request, pack)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/evidence-pack/integrity-gate", response_model=EvidencePackIntegrityGateResponse)
async def build_evidence_pack_integrity_gate(
    request: EvidencePackIntegrityGateRequest,
) -> EvidencePackIntegrityGateResponse:
    """Validate a supplied evidence pack instead of workflow/export readiness."""

    try:
        return _build_evidence_pack_integrity_gate(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class SaveEvidencePackRequest(BaseModel):
    """Request to save discussion evidence pack.

    Args:
        project_id: Non-empty project identifier for the discussion.
        query: Non-empty discussion prompt or research question.
        snippets: JSON-serializable evidence snippets captured for the run.
        source_labels: Optional source labels attached to the pack.
    """

    project_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=4096)
    snippets: List[dict[str, Any]] = Field(default_factory=list)
    source_labels: List[str] = Field(default_factory=list)


@router.post("/api/discussions/{discussion_id}/evidence_pack", response_model=DiscussionEvidencePackPayload)
async def save_discussion_evidence_pack(
    discussion_id: str,
    request: SaveEvidencePackRequest,
) -> DiscussionEvidencePackPayload:
    """Save evidence pack for a discussion session."""
    normalized_discussion_id = discussion_id.strip()
    if not normalized_discussion_id:
        raise HTTPException(status_code=422, detail="discussion_id must be non-empty")

    pack_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    pack = DiscussionEvidencePackPayload(
        pack_id=pack_id,
        discussion_id=normalized_discussion_id,
        project_id=request.project_id.strip(),
        query=request.query.strip(),
        created_at=now,
        snippets=request.snippets,
        source_labels=request.source_labels,
    )

    _refresh_discussion_evidence_pack_store()
    _discussion_packs_store[pack_id] = pack
    _write_discussion_evidence_packs(_discussion_packs_store)
    return pack


@router.get("/api/discussions/{discussion_id}/evidence_pack", response_model=DiscussionEvidencePackPayload)
async def get_discussion_evidence_pack(discussion_id: str) -> DiscussionEvidencePackPayload:
    """Get evidence pack for a discussion session."""
    normalized_discussion_id = discussion_id.strip()
    if not normalized_discussion_id:
        raise HTTPException(status_code=422, detail="discussion_id must be non-empty")

    matching = [
        pack
        for pack in _refresh_discussion_evidence_pack_store().values()
        if pack.discussion_id == normalized_discussion_id
    ]
    if matching:
        return max(matching, key=lambda pack: (pack.created_at, pack.pack_id))

    raise HTTPException(status_code=404, detail=f"Evidence pack not found for discussion: {normalized_discussion_id}")


# =========================================================================
# D8: Citation overlap detector
# =========================================================================

class DetectOverlapAnchor(BaseModel):
    """Citation anchor candidate supplied by the caller for D8 overlap checks."""

    anchor_id: str = Field(min_length=1, max_length=128)
    material_id: str = Field(default="", max_length=128)
    chunk_id: str = Field(default="", max_length=128)
    text: str = Field(default="", max_length=4096)


class DetectOverlapRequest(BaseModel):
    """Request to detect citation overlap."""

    project_id: str
    draft_id: Optional[str] = None
    threshold: float = Field(0.7, ge=0.0, le=1.0, description="Overlap threshold")
    anchors: List[DetectOverlapAnchor] = Field(default_factory=list)


_OVERLAP_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def _citation_overlap_tokens(value: str) -> set[str]:
    """Return normalized tokens used for bounded citation text overlap."""
    if not isinstance(value, str):
        return set()
    return {token.lower() for token in _OVERLAP_TOKEN_RE.findall(value) if token.strip()}


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    """Return set Jaccard similarity; empty pairs are not evidence overlap."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _anchor_overlap_score(left: DetectOverlapAnchor, right: DetectOverlapAnchor) -> float:
    """Score exact chunk reuse first, then text-token Jaccard similarity."""
    left_chunk = left.chunk_id.strip()
    right_chunk = right.chunk_id.strip()
    if left_chunk and left_chunk == right_chunk:
        left_material = left.material_id.strip()
        right_material = right.material_id.strip()
        if not left_material or not right_material or left_material == right_material:
            return 1.0
    return _jaccard_similarity(
        _citation_overlap_tokens(left.text),
        _citation_overlap_tokens(right.text),
    )


def _overlap_recommendation(score: float, overlapping_count: int) -> str:
    """Return a deterministic reviewer hint for overlapping citation anchors."""
    if score >= 1.0:
        return "多个 citation anchor 指向同一证据块，请确认是否需要合并引用或补充独立证据。"
    if overlapping_count > 1:
        return "多个 citation anchor 与其他引用高度相似，请检查证据是否过度集中。"
    return "该 citation anchor 与另一引用高度相似，请检查是否需要补充独立证据。"


@router.post("/api/citations/detect_overlap", response_model=List[CitationOverlapPayload])
async def detect_citation_overlap(request: DetectOverlapRequest) -> List[CitationOverlapPayload]:
    """Detect overlapping citations in a project or draft.

    Identifies citation anchors that reference the same or highly similar chunks.
    """
    if not request.project_id.strip():
        raise HTTPException(status_code=422, detail="project_id must be non-empty")
    if len(request.anchors) < 2:
        return []

    overlap_by_anchor: dict[str, dict[str, Any]] = {}
    for index, left in enumerate(request.anchors):
        for right in request.anchors[index + 1:]:
            if left.anchor_id == right.anchor_id:
                continue
            score = _anchor_overlap_score(left, right)
            if score <= 0.0 or score < request.threshold:
                continue
            for current, other in ((left, right), (right, left)):
                existing = overlap_by_anchor.setdefault(
                    current.anchor_id,
                    {
                        "anchor": current,
                        "score": score,
                        "overlapping": set(),
                    },
                )
                existing["score"] = max(float(existing["score"]), score)
                existing["overlapping"].add(other.anchor_id)

    results: list[CitationOverlapPayload] = []
    for anchor_id in sorted(overlap_by_anchor):
        record = overlap_by_anchor[anchor_id]
        anchor = record["anchor"]
        overlapping = sorted(record["overlapping"])
        score = round(float(record["score"]), 4)
        results.append(
            CitationOverlapPayload(
                anchor_id=anchor.anchor_id,
                material_id=anchor.material_id,
                chunk_id=anchor.chunk_id,
                overlap_score=score,
                overlapping_anchors=overlapping,
                recommendation=_overlap_recommendation(score, len(overlapping)),
            )
        )
    return results


# =========================================================================
# S5: Citation source-anchor verification
# =========================================================================

_GENERATED_CITATION_SOURCE_KINDS = {
    "generated_description",
    "generated_figure_description",
    "generated_table_description",
    "generated_equation_description",
    "figure_description",
    "table_description",
    "equation_description",
}


def _normalize_source_kind(value: str) -> str:
    """Normalize source-kind values for deterministic trust rules."""

    return str(value or "local").strip().lower() or "local"


def _dedupe_source_labels(labels: list[str]) -> list[str]:
    """Return stable, non-empty labels while preserving first-seen order."""

    deduped: list[str] = []
    seen: set[str] = set()
    for raw_label in labels:
        label = str(raw_label or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        deduped.append(label)
    return deduped


def _citation_anchor_is_concrete(request: CitationVerificationRequest) -> bool:
    """Return true when a citation can jump to a concrete PDF/material anchor."""

    anchor = request.source_anchor
    if anchor is None:
        return False
    if not str(anchor.material_id or "").strip():
        return False
    if str(anchor.chunk_id or "").strip():
        return True
    if anchor.page is not None:
        return True
    return anchor.bbox is not None


def _citation_text_support_score(request: CitationVerificationRequest) -> float:
    """Score deterministic text overlap between citation/claim text and evidence."""

    evidence_tokens = _citation_overlap_tokens(request.evidence_text)
    candidate_text = " ".join(
        part.strip()
        for part in (request.citation_text, request.claim_text)
        if isinstance(part, str) and part.strip()
    )
    candidate_tokens = _citation_overlap_tokens(candidate_text)
    if not evidence_tokens or not candidate_tokens:
        return 0.0
    return _jaccard_similarity(candidate_tokens, evidence_tokens)


def _citation_verification_status(
    request: CitationVerificationRequest,
) -> tuple[CitationVerificationStatus, str]:
    """Classify citation support without trusting generated descriptions alone."""

    source_kind = _normalize_source_kind(request.source_kind)
    has_anchor = _citation_anchor_is_concrete(request)
    if not has_anchor:
        if source_kind in _GENERATED_CITATION_SOURCE_KINDS:
            return (
                CitationVerificationStatus.UNSUPPORTED,
                "图表/公式等生成描述不能单独作为可信引用；需要 material_id + page/chunk/bbox 指向原始 PDF。",
            )
        return (
            CitationVerificationStatus.UNSUPPORTED,
            "引用缺少可跳回原始 PDF 的 source anchor。",
        )

    support_score = _citation_text_support_score(request)
    if support_score >= 0.2:
        return (
            CitationVerificationStatus.VERIFIED,
            f"引用文本与锚点证据文本存在可复核重叠，overlap={support_score:.2f}。",
        )
    if source_kind in _GENERATED_CITATION_SOURCE_KINDS:
        return (
            CitationVerificationStatus.NEEDS_REVIEW,
            "生成描述已绑定原始 PDF anchor，但仍需要人工或后续语义核验确认描述是否忠实于原文。",
        )
    return (
        CitationVerificationStatus.NEEDS_REVIEW,
        "引用已绑定原始 PDF anchor，但缺少足够的证据文本重叠；需要复核。",
    )


@router.post("/api/citations/verify", response_model=CitationVerificationPayload)
async def verify_citation_source(
    request: CitationVerificationRequest,
) -> CitationVerificationPayload:
    """Verify one citation against a concrete PDF source anchor and persist it."""

    normalized_project_id = request.project_id.strip()
    normalized_citation_id = request.citation_id.strip()
    if not normalized_project_id:
        raise HTTPException(status_code=422, detail="project_id must be non-empty")
    if not normalized_citation_id:
        raise HTTPException(status_code=422, detail="citation_id must be non-empty")

    status, rationale = _citation_verification_status(request)
    anchor_labels = request.source_anchor.source_labels if request.source_anchor is not None else []
    labels = _dedupe_source_labels([*request.source_labels, *anchor_labels])
    verification_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    record = CitationVerificationPayload(
        verification_id=verification_id,
        project_id=normalized_project_id,
        citation_id=normalized_citation_id,
        status=status,
        rationale=rationale,
        source_kind=_normalize_source_kind(request.source_kind),
        source_anchor=request.source_anchor,
        source_labels=labels,
        created_at=now,
        updated_at=now,
    )

    _refresh_citation_verifications_store()
    _citation_verifications_store[verification_id] = record
    _write_citation_verifications(_citation_verifications_store)
    return record


def _record_has_any_source_label(record: CitationVerificationPayload, labels: list[str]) -> bool:
    """Return true when a verification record carries any requested label."""

    if not labels:
        return True
    anchor_labels = record.source_anchor.source_labels if record.source_anchor is not None else []
    all_labels = set(_dedupe_source_labels([*record.source_labels, *anchor_labels]))
    return any(label in all_labels for label in labels)


@router.get("/api/citations/verifications", response_model=CitationVerificationsResponse)
async def list_citation_verifications(
    project_id: str = Query(..., min_length=1),
    citation_id: Optional[str] = Query(None, min_length=1),
    status: Optional[CitationVerificationStatus] = Query(None),
    source_labels: List[str] = Query(None, description="Filter by source labels"),
    material_id: Optional[str] = Query(None, min_length=1),
) -> CitationVerificationsResponse:
    """List persisted citation verification records for a project."""

    records = [
        record
        for record in _refresh_citation_verifications_store().values()
        if record.project_id == project_id
    ]
    if citation_id is not None:
        records = [record for record in records if record.citation_id == citation_id]
    if status is not None:
        records = [record for record in records if record.status == status]
    if material_id is not None:
        records = [
            record
            for record in records
            if record.source_anchor is not None and record.source_anchor.material_id == material_id
        ]
    normalized_labels = _dedupe_source_labels(source_labels or [])
    if normalized_labels:
        records = [
            record
            for record in records
            if _record_has_any_source_label(record, normalized_labels)
        ]

    sorted_records = sorted(records, key=lambda item: (item.created_at, item.verification_id))
    return CitationVerificationsResponse(records=sorted_records, total=len(sorted_records))


# =========================================================================
# E6: Inspiration evidence_refs with source_labels filter
# =========================================================================

@router.get("/api/inspiration/evidence_refs", response_model=EvidenceRefsResponse)
async def get_inspiration_evidence_refs(
    source_labels: List[str] = Query(None, description="Filter by source labels"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> EvidenceRefsResponse:
    """Get inspiration evidence references with source_labels filtering.

    Alias to /api/evidence_refs with inspiration-specific context.
    """
    return await get_evidence_refs(
        project_id=None,
        material_id=None,
        source_labels=source_labels,
        page=page,
        page_size=page_size,
    )
