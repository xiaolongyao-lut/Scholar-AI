from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from literature_assistant.core.project_paths import (
    REPO_ROOT,
    WORKSPACE_ARTIFACTS_ROOT,
    WORKSPACE_REFERENCES_ROOT,
    output_path,
    wiki_generated_root,
    wiki_graph_db_path,
    wiki_graph_path,
    wiki_query_index_path,
    wiki_review_queue_path,
    wiki_runtime_db_path,
)
from literature_assistant.core.runtime_env import wiki_enabled
from literature_assistant.core.source_vault import (
    build_source_vault_chunk_read_endpoint,
    build_source_vault_chunk_ref_id,
)
from literature_assistant.core.wiki.compiler import WikiCompiler
from literature_assistant.core.wiki.doctor import WikiDoctor
from literature_assistant.core.wiki.graph import WikiGraphStore, build_wiki_graph
from literature_assistant.core.wiki.models import (
    WikiPageKind,
    WikiPageStatus,
    from_evidence_reference,
    make_stable_slug,
)
from literature_assistant.core.wiki.observability import default_wiki_observability_sink
from literature_assistant.core.wiki.page_store import (
    AUTO_END,
    AUTO_START,
    PageRevisionConflictError,
    WikiPageStore,
    atomic_write_text,
    render_frontmatter,
    stable_slug,
)
from literature_assistant.core.wiki.permissions import (
    DEFAULT_WIKI_OWNER,
    PERMISSIONS_KEY,
    WikiPagePermissions,
    WikiPageVisibility,
    can_read,
    can_write,
    get_permissions,
    normalize_shared_with,
    normalize_user_id,
    set_permissions,
)
from literature_assistant.core.wiki.query import (
    WikiQueryIndex,
    WikiSearchResult,
    build_source_manifest,
    build_wiki_index,
    build_knowledge_refs,
    wiki_query_with_fallback,
)
from literature_assistant.core.wiki.review_queue import (
    AnnotationNoteReviewTarget,
    ReviewItemKind,
    ReviewItemStatus,
    ReviewPromotionIntent,
    ReviewPromotionReceipt,
    ReviewPromotionWithdrawalReceipt,
    ReviewQueue,
    WikiPageRevisionReviewTarget,
    make_annotation_note_review_target,
    make_review_item,
    make_wiki_page_revision_review_target,
)
from literature_assistant.core.wiki.source_registry import (
    ChunkInput,
    SourceRecord,
    WikiRegistry,
    derive_chunk_id,
    derive_source_id,
    utc_now_iso,
)
if TYPE_CHECKING:
    from literature_assistant.core.harness_protocols import ArtifactType, JobKind, SessionMode
    from literature_assistant.core.writing_runtime import get_writing_runtime
else:
    from harness_protocols import ArtifactType, JobKind, SessionMode
    from writing_runtime import get_writing_runtime


router: APIRouter = APIRouter(prefix="/api/wiki", tags=["Wiki"])
_SAFE_FILTER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SAFE_EXPORT_ARCHIVE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.zip$")
_MAX_WIKI_IMPORT_FILES = 20
_MAX_WIKI_IMPORT_FILE_BYTES = 1_000_000
_MAX_WIKI_IMPORT_TOTAL_BYTES = 5_000_000


class WikiManifestDrilldownItemPayload(BaseModel):
    kind: str
    page_path: str
    source_hash: str | None = None
    indexed_hash: str | None = None
    redacted: bool = False


class WikiManifestDrilldownPayload(BaseModel):
    schema_version: str = "scholar-ai-wiki-manifest-drilldown/v1"
    status: str = "unknown"
    hash_algorithm: str = "sha256"
    limit: int = 10
    missing_count: int = 0
    extra_count: int = 0
    mismatched_count: int = 0
    truncated: bool = False
    missing_pages: list[WikiManifestDrilldownItemPayload] = Field(default_factory=list)
    extra_pages: list[WikiManifestDrilldownItemPayload] = Field(default_factory=list)
    mismatched_pages: list[WikiManifestDrilldownItemPayload] = Field(default_factory=list)


class WikiStatusResponse(BaseModel):
    enabled: bool
    page_count: int = 0
    stale: bool = False
    integrity_status: str = "unknown"
    index_hash: str = "none"
    source_manifest_hash: str = "unknown"
    indexed_source_manifest_hash: str = "unknown"
    indexed_page_count: int = 0
    source_page_count: int | None = None
    graph_json_exists: bool = False
    graph_db_exists: bool = False
    query_index_exists: bool = False
    review_queue_exists: bool = False
    paths: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    manifest_drilldown: WikiManifestDrilldownPayload = Field(default_factory=WikiManifestDrilldownPayload)


class WikiRevalidationApplyRequest(BaseModel):
    expected_source_manifest_hash: str = Field(min_length=1, max_length=128)
    confirm: bool = False


class WikiRevalidationResponse(BaseModel):
    enabled: bool
    stale: bool
    can_apply: bool
    applied: bool = False
    integrity_status: str
    source_manifest_hash: str
    indexed_source_manifest_hash: str
    source_page_count: int | None = None
    indexed_page_count: int = 0
    manifest_drilldown: WikiManifestDrilldownPayload = Field(default_factory=WikiManifestDrilldownPayload)
    warnings: list[str] = Field(default_factory=list)
    message: str = ""


class WikiPageSummaryPayload(BaseModel):
    path: str
    title: str
    kind: str
    status: str


class WikiPageListResponse(BaseModel):
    enabled: bool
    pages: list[WikiPageSummaryPayload] = Field(default_factory=list)


class WikiCategoryNodePayload(BaseModel):
    key: str
    label: str
    page_count: int = 0
    pages: list[WikiPageSummaryPayload] = Field(default_factory=list)
    children: list["WikiCategoryNodePayload"] = Field(default_factory=list)


class WikiCategoriesResponse(BaseModel):
    enabled: bool
    categories: list[WikiCategoryNodePayload] = Field(default_factory=list)


class WikiTagPayload(BaseModel):
    key: str
    label: str
    page_count: int = 0
    pages: list[WikiPageSummaryPayload] = Field(default_factory=list)


class WikiTagsResponse(BaseModel):
    enabled: bool
    tags: list[WikiTagPayload] = Field(default_factory=list)


class WikiPageReadResponse(BaseModel):
    enabled: bool
    path: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    body: str = ""


class WikiDoctorResponse(BaseModel):
    enabled: bool
    report: dict[str, Any] = Field(default_factory=dict)


class WikiGraphResponse(BaseModel):
    enabled: bool
    graph: dict[str, Any] = Field(default_factory=dict)


class WikiGraphReviewNodeInput(BaseModel):
    node_id: str
    page_path: str
    label: str | None = None
    disambiguation: str | None = None


class WikiGraphReviewEdgeInput(BaseModel):
    edge_id: str = ""
    source: str
    target: str
    relation: str
    source_path: str
    target_path: str | None = None
    frontmatter_field: str | None = None


class WikiGraphReviewApplyRequest(BaseModel):
    operation_kind: str
    review_item_key: str = ""
    keep_node_id: str | None = None
    merge_node_ids: list[str] = Field(default_factory=list)
    nodes: list[WikiGraphReviewNodeInput] = Field(default_factory=list)
    edges: list[WikiGraphReviewEdgeInput] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    decided_by: str = "user"


class WikiGraphReviewPageSnapshotPayload(BaseModel):
    page_path: str
    content: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_current_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class WikiGraphReviewApplyResponse(BaseModel):
    enabled: bool
    operation_id: str
    operation_kind: str
    updated_page_paths: list[str] = Field(default_factory=list)
    snapshots: list[WikiGraphReviewPageSnapshotPayload] = Field(default_factory=list)
    message: str = ""
    warnings: list[str] = Field(default_factory=list)


class WikiGraphReviewUndoRequest(BaseModel):
    operation_id: str
    operation_kind: str = "undo_graph_review"
    snapshots: list[WikiGraphReviewPageSnapshotPayload] = Field(default_factory=list)
    decided_by: str = "user"


class WikiPageRevisionReviewTargetPayload(BaseModel):
    schema_version: Literal[
        "scholar-ai-wiki-page-revision-target/v1",
        "scholar-ai-wiki-page-revision-target/v2",
    ]
    type: Literal["wiki_page_revision"]
    page_id: str
    page_path: str
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_status: Literal["draft", "review"]


class AnnotationNoteReviewTargetPayload(BaseModel):
    schema_version: Literal["scholar-ai-annotation-note-review-target/v1"]
    type: Literal["annotation_note"]
    project_id: str
    material_id: str
    note_id: str
    expected_updated_at: str
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_scope: Literal["wiki_review"]


class WikiReviewPromotionReceiptPayload(BaseModel):
    schema_version: Literal[
        "scholar-ai-wiki-promotion-receipt/v1",
        "scholar-ai-wiki-promotion-receipt/v2",
    ]
    receipt_id: str
    review_item_id: str
    request_id: str
    expected_item_revision: str
    request_fingerprint: str
    outcome: Literal["promoted"]
    target: WikiPageRevisionReviewTargetPayload
    before_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_status: Literal["draft", "review"]
    promoted_status: Literal["final"]
    promoted_at: str
    promoted_by: str


class WikiReviewPromotionWithdrawalReceiptPayload(BaseModel):
    schema_version: Literal["scholar-ai-wiki-promotion-withdrawal-receipt/v1"]
    receipt_id: str
    review_item_id: str
    promotion_operation_id: str
    promotion_request_id: str
    promotion_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_item_revision: str
    resulting_item_revision: str
    withdrawal_request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["withdrawn"]
    target: WikiPageRevisionReviewTargetPayload
    before_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    planned_after_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str
    withdrawn_at: str
    withdrawn_by: str


class WikiReviewPromotionIntentPayload(BaseModel):
    schema_version: Literal[
        "scholar-ai-wiki-promotion-intent/v1",
        "scholar-ai-wiki-promotion-intent/v2",
    ]
    operation_id: str
    review_item_id: str
    request_id: str
    expected_item_revision: str
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str
    target: WikiPageRevisionReviewTargetPayload
    before_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_status: Literal["draft", "review"]
    promoted_status: Literal["final"]
    promoted_at: str
    promoted_by: str


class WikiReviewDecisionPayload(BaseModel):
    status: Literal["approved", "rejected"]
    reason: str
    decided_at: str
    decided_by: str
    request_id: str = ""
    expected_item_revision: str = ""
    request_fingerprint: str = ""
    promotion_receipt: WikiReviewPromotionReceiptPayload | None = None


class WikiReviewItemPayload(BaseModel):
    item_id: str
    kind: str
    title: str
    page_path: str
    summary: str
    status: str
    created_at: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: int
    item_revision: str
    target: WikiPageRevisionReviewTargetPayload | AnnotationNoteReviewTargetPayload | None = None
    promotion_intent: WikiReviewPromotionIntentPayload | None = None
    promotion_withdrawal_receipts: list[WikiReviewPromotionWithdrawalReceiptPayload] = Field(
        default_factory=list
    )
    allowed_actions: list[Literal["approve", "reject", "withdraw"]] = Field(default_factory=list)
    decision: WikiReviewDecisionPayload | None = None


class WikiReviewListResponse(BaseModel):
    enabled: bool
    items: list[WikiReviewItemPayload] = Field(default_factory=list)


class WikiAnnotationReviewEnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=256)
    material_id: str = Field(min_length=1, max_length=256)
    note_id: str = Field(min_length=1, max_length=256)
    expected_updated_at: str = Field(min_length=1, max_length=64)
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(min_length=1, max_length=128)

    @field_validator("project_id", "material_id", "note_id")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not _SAFE_IDENTIFIER_RE.fullmatch(normalized):
            raise ValueError("annotation review identifier contains unsupported characters")
        return normalized

    @field_validator("expected_updated_at")
    @classmethod
    def validate_expected_updated_at(cls, value: str) -> str:
        normalized = value.strip()
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("expected_updated_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("expected_updated_at must include a timezone offset")
        return normalized

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ord(char) < 32 for char in normalized):
            raise ValueError("request_id contains unsupported characters")
        return normalized


class WikiReviewDecisionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    decided_by: str = "user"
    request_id: str = Field(default="", max_length=128)
    expected_item_revision: str = Field(min_length=1, max_length=128)
    expected_target_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("review reason cannot be empty")
        return normalized

    @field_validator("request_id")
    @classmethod
    def normalize_optional_cas_token(cls, value: str) -> str:
        normalized = value.strip()
        if any(ord(char) < 32 for char in normalized):
            raise ValueError("review CAS token contains control characters")
        return normalized

    @field_validator("expected_item_revision")
    @classmethod
    def normalize_required_item_revision(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("expected_item_revision cannot be empty")
        if any(ord(char) < 32 for char in normalized):
            raise ValueError("expected_item_revision contains control characters")
        return normalized


class WikiReviewPromotionWithdrawRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    expected_item_revision: str = Field(min_length=1, max_length=128)
    expected_promotion_operation_id: str = Field(min_length=1, max_length=128)

    @field_validator("reason", "expected_item_revision", "expected_promotion_operation_id")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("withdrawal field cannot be empty")
        if any(ord(char) < 32 for char in normalized):
            raise ValueError("withdrawal field contains control characters")
        return normalized


class WikiReviewPromotionWithdrawResponse(BaseModel):
    item: WikiReviewItemPayload
    withdrawal_receipt: WikiReviewPromotionWithdrawalReceiptPayload


class WikiCompileRequest(BaseModel):
    dry_run: bool = True
    allow_write: bool = False
    source_id: str | None = None
    project_id: str | None = None


class WikiCompileResponse(BaseModel):
    enabled: bool
    dry_run: bool
    created: int = 0
    updated: int = 0
    skipped: int = 0
    planned_paths: list[str] = Field(default_factory=list)
    written_paths: list[str] = Field(default_factory=list)
    budget_summary: dict[str, Any] = Field(default_factory=dict)
    budget_checks: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WikiQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    wiki_first: bool = False
    save: bool = False
    debug: bool = False


class WikiQueryResponse(BaseModel):
    enabled: bool
    fallback_required: bool
    answer: str = ""
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WikiPageCreateRequest(BaseModel):
    """Request to create a new wiki page (G2 2026-05-26)."""
    title: str
    kind: str
    body: str
    status: str = "draft"
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    source_hashes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class WikiPageUpdateRequest(BaseModel):
    """Request to update an existing wiki page (G2 2026-05-26)."""
    title: str | None = None
    body: str | None = None
    status: str | None = None
    evidence_refs: list[dict[str, Any]] | None = None
    source_hashes: list[str] | None = None
    extra: dict[str, Any] | None = None


class WikiPageMutationResponse(BaseModel):
    """Response for create/update/delete operations (G2 2026-05-26)."""
    success: bool
    slug: str
    message: str = ""
    status: str = ""
    receipt_id: str | None = None
    current_content_hash: str | None = None


class WikiPageRestoreRequest(BaseModel):
    """CAS and receipt preconditions for restoring an archived page."""

    archive_receipt_id: str = Field(min_length=1, max_length=128)
    expected_current_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class WikiPageVersionPayload(BaseModel):
    version: int
    action: str
    stable_slug: str
    kind: str
    status: str
    title: str
    body_hash: str
    created_at_iso: str
    updated_at_iso: str
    recorded_at_iso: str


class WikiPageVersionsResponse(BaseModel):
    enabled: bool
    slug: str
    versions: list[WikiPageVersionPayload] = Field(default_factory=list)


class WikiExportResponse(BaseModel):
    """Response for wiki export operation (G15 2026-05-26)."""
    success: bool
    page_count: int
    output_path: str
    errors: list[str] = Field(default_factory=list)


class WikiProjectOkfExportRequest(BaseModel):
    """Explicit process artifact records for a local project OKF bundle."""

    output_path: str | None = None
    project_id: str | None = None
    include_live_project_records: bool = False
    max_live_records: int = Field(default=200, ge=1, le=1000)
    materials: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    answers: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    reviews: list[dict[str, Any]] = Field(default_factory=list)
    exports: list[dict[str, Any]] = Field(default_factory=list)

    def records_by_group(self) -> dict[str, list[dict[str, Any]]]:
        """Return records in the Scholar AI process-artifact group order."""

        return {
            "materials": self.materials,
            "evidence": self.evidence,
            "answers": self.answers,
            "tasks": self.tasks,
            "reviews": self.reviews,
            "exports": self.exports,
        }


class WikiProjectOkfExportResponse(BaseModel):
    """Local project OKF export result for explicit process artifact records."""

    enabled: bool
    success: bool = False
    page_count: int = 0
    output_path: str = ""
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)


class WikiImportRequest(BaseModel):
    """Local Markdown import request for the wiki sidecar."""

    source_paths: list[str] = Field(default_factory=list)
    dry_run: bool = True
    confirm_write: bool = False
    overwrite: bool = False
    kind: str = WikiPageKind.synthesis.value
    status: str = WikiPageStatus.draft.value


class WikiImportItemPayload(BaseModel):
    """Per-source result for local Markdown import."""

    source_path: str
    source_registry_id: str = ""
    import_source_hash: str = ""
    source_hash: str = ""
    content_hash: str = ""
    ref_id: str = ""
    chunk_id: str = ""
    read_endpoint: str = ""
    source_vault_source_id: str = ""
    source_vault_chunk_id: str = ""
    source_vault_ref_id: str = ""
    source_vault_read_endpoint: str = ""
    source_vault_status: str = ""
    span_start: int | None = None
    span_end: int | None = None
    title: str = ""
    kind: str = ""
    status: str = ""
    slug: str = ""
    path: str = ""
    action: str
    review_item_id: str = ""
    runtime_session_id: str = ""
    runtime_job_id: str = ""
    runtime_approval_id: str = ""
    warnings: list[str] = Field(default_factory=list)
    error: str = ""


class WikiImportResponse(BaseModel):
    """Response for local Markdown wiki import."""

    enabled: bool
    dry_run: bool
    confirm_write: bool = False
    imported: int = 0
    skipped: int = 0
    errored: int = 0
    pages: list[WikiImportItemPayload] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WikiOkfInspectRequest(BaseModel):
    """Read-only request to inspect a local OKF zip archive."""

    archive_path: str = Field(min_length=1)


class WikiOkfInspectResponse(BaseModel):
    """Read-only OKF inspection response for future import planning."""

    enabled: bool
    dry_run: bool = True
    archive_path: str = ""
    inspection: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class WikiPagePermissionsRequest(BaseModel):
    """Page visibility update request for local wiki ACLs."""

    visibility: str = Field(default=WikiPageVisibility.PRIVATE.value)
    shared_with: list[str] = Field(default_factory=list)


class WikiPagePermissionsResponse(BaseModel):
    """Serialized local wiki ACL state."""

    owner: str
    visibility: str
    shared_with: list[str] = Field(default_factory=list)


def _page_store(*, create: bool = True) -> WikiPageStore:
    return WikiPageStore(wiki_generated_root(), create=create)


def _dry_run_page_store() -> WikiPageStore:
    return WikiPageStore(wiki_generated_root(), create=False)


def _doctor(page_store: WikiPageStore | None = None) -> WikiDoctor:
    store = page_store or _page_store(create=False)
    return WikiDoctor(
        store,
        registry=WikiRegistry(wiki_runtime_db_path()) if wiki_runtime_db_path().exists() else None,
        query_index=WikiQueryIndex(wiki_query_index_path()) if wiki_query_index_path().exists() else None,
        graph_store=WikiGraphStore.default(),
        observability_sink=default_wiki_observability_sink(),
    )


def _status_integrity(
    page_store: WikiPageStore,
    page_count: int,
    *,
    enabled: bool,
    integrity_store: WikiPageStore | None = None,
) -> tuple[bool, list[str], dict[str, Any]]:
    if not isinstance(page_store, WikiPageStore):
        raise TypeError("page_store must be a WikiPageStore")
    source_store = integrity_store or page_store
    if not isinstance(source_store, WikiPageStore):
        raise TypeError("integrity_store must be a WikiPageStore")
    if not enabled:
        return False, [], {
            "integrity_status": "disabled",
            "index_hash": "none",
            "source_manifest_hash": "unknown",
            "indexed_source_manifest_hash": "unknown",
            "indexed_page_count": 0,
            "source_page_count": None,
            "manifest_drilldown": WikiManifestDrilldownPayload(status="disabled").model_dump(),
        }

    index_path = wiki_query_index_path()
    if not index_path.exists():
        manifest = build_source_manifest(source_store)
        has_source_pages = manifest.page_count > 0
        return has_source_pages, [], {
            "integrity_status": "missing_index" if has_source_pages else "empty_no_index",
            "index_hash": "none",
            "source_manifest_hash": manifest.source_manifest_hash,
            "indexed_source_manifest_hash": "unknown",
            "indexed_page_count": 0,
            "source_page_count": manifest.page_count,
            "manifest_drilldown": WikiManifestDrilldownPayload(
                status="missing_index" if page_count > 0 else "empty_no_index"
            ).model_dump(),
        }

    index = WikiQueryIndex(index_path)
    try:
        status = index.get_status(source_store)
    except Exception:
        return True, ["Wiki query index status could not be read; marking wiki status as stale."], {
            "integrity_status": "unreadable_index",
            "index_hash": "unknown",
            "source_manifest_hash": "unknown",
            "indexed_source_manifest_hash": "unknown",
            "indexed_page_count": 0,
            "source_page_count": page_count,
            "manifest_drilldown": WikiManifestDrilldownPayload(status="unreadable_index").model_dump(),
        }
    finally:
        index.close()

    source_page_count = status.source_page_count if isinstance(status.source_page_count, int) else len(source_store.list_pages())
    stale = status.stale or status.page_count != source_page_count
    warnings = list(status.warnings)
    if status.page_count != source_page_count:
        warnings.append("Wiki query index page count differs from generated wiki source page count.")
    return stale, list(dict.fromkeys(warnings)), {
        "integrity_status": status.integrity_status,
        "index_hash": status.index_hash,
        "source_manifest_hash": status.source_manifest_hash,
        "indexed_source_manifest_hash": status.indexed_source_manifest_hash,
        "indexed_page_count": status.page_count,
        "source_page_count": status.source_page_count,
        "manifest_drilldown": status.manifest_drilldown.to_dict(redact_extra_pages=True),
    }


def _disabled_warning() -> list[str]:
    return ["Wiki integration is disabled. Set LITERATURE_ASSISTANT_WIKI_ENABLED=1 to enable wiki APIs."]


def _sanitize_status_path(path: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(Path(__file__).resolve().parents[3]).as_posix()
    except ValueError:
        return f"<external>/{resolved.name}" if resolved.name else "<external>"


def _normalize_filter_token(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not _SAFE_FILTER_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a simple lowercase token")
    return normalized


def _singularize_kind(value: str) -> str:
    if value.endswith("ies") and len(value) > 3:
        return f"{value[:-3]}y"
    if value.endswith("s") and len(value) > 1:
        return value[:-1]
    return value


def _kind_matches_filter(summary: WikiPageSummaryPayload, kind_filter: str) -> bool:
    candidates = {
        summary.kind.strip().lower(),
        _singularize_kind(summary.kind.strip().lower()),
        Path(summary.path).parts[0].strip().lower() if Path(summary.path).parts else "",
        _singularize_kind(Path(summary.path).parts[0].strip().lower()) if Path(summary.path).parts else "",
    }
    return kind_filter in candidates or _singularize_kind(kind_filter) in candidates


def _normalize_identifier(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not _SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail=f"{field_name} contains unsupported characters")
    return normalized


def _wiki_import_allowed_roots() -> tuple[Path, ...]:
    return (
        REPO_ROOT,
        WORKSPACE_ARTIFACTS_ROOT,
        WORKSPACE_REFERENCES_ROOT,
    )


def _wiki_import_forbidden_roots() -> tuple[Path, ...]:
    return (
        REPO_ROOT / ".git",
        REPO_ROOT / ".rollback_snapshots",
        REPO_ROOT / "github",
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_safe_export_archive_path(
    raw_output_path: str | None,
    *,
    export_dir: Path,
    default_prefix: str,
    root_label: str,
) -> Path:
    """Return a safe archive filename under one local export directory.

    Args:
        raw_output_path: Optional user-provided archive filename. It must be a
            filename only; absolute paths, parent directories, and alternate
            suffixes are rejected.
        export_dir: Canonical local directory where the archive will be written.
        default_prefix: Prefix used for timestamped default filenames.
        root_label: Human-readable root label for HTTP 400 messages.

    Returns:
        Resolved path inside ``export_dir``.
    """
    from datetime import datetime, timezone

    if not isinstance(export_dir, Path):
        raise TypeError("export_dir must be a pathlib.Path")
    if not isinstance(default_prefix, str) or not default_prefix.strip():
        raise ValueError("default_prefix must be non-empty")
    if not isinstance(root_label, str) or not root_label.strip():
        raise ValueError("root_label must be non-empty")

    resolved_export_dir = export_dir.resolve()
    resolved_export_dir.mkdir(parents=True, exist_ok=True)

    if raw_output_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{default_prefix.strip()}_{timestamp}.zip"
    else:
        filename = str(raw_output_path or "").strip()
        if not filename:
            raise HTTPException(status_code=400, detail="output_path must be a non-empty zip filename")
        candidate = Path(filename)
        if candidate.is_absolute() or filename != candidate.name or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail=f"output_path must be a filename under {root_label.strip()}")
        if not filename.lower().endswith(".zip"):
            filename = f"{filename}.zip"
        if not _SAFE_EXPORT_ARCHIVE_RE.fullmatch(filename):
            raise HTTPException(status_code=400, detail="output_path must be a safe .zip filename")

    resolved = (resolved_export_dir / filename).resolve()
    if not _is_relative_to(resolved, resolved_export_dir):
        raise HTTPException(status_code=400, detail="output_path escapes wiki export root")
    return resolved


def _resolve_wiki_export_path(raw_output_path: str | None) -> Path:
    """Return a legacy Markdown zip export path under ``workspace_artifacts/wiki_exports``."""

    return _resolve_safe_export_archive_path(
        raw_output_path,
        export_dir=WORKSPACE_ARTIFACTS_ROOT / "wiki_exports",
        default_prefix="wiki_export",
        root_label="wiki_exports",
    )


def _resolve_wiki_okf_export_path(raw_output_path: str | None) -> Path:
    """Return an OKF zip export path under the canonical generated-output root."""

    return _resolve_safe_export_archive_path(
        raw_output_path,
        export_dir=output_path("wiki-okf"),
        default_prefix="wiki_okf_export",
        root_label="workspace_artifacts/generated/output/wiki-okf",
    )


def _resolve_project_okf_export_path(raw_output_path: str | None) -> Path:
    """Return a project artifact OKF zip export path under generated output."""

    return _resolve_safe_export_archive_path(
        raw_output_path,
        export_dir=output_path("project-okf"),
        default_prefix="project_okf_export",
        root_label="workspace_artifacts/generated/output/project-okf",
    )


def _resource_to_dict(resource: Any, *, resource_name: str) -> dict[str, Any]:
    """Return a plain mapping from a local resource object.

    Args:
        resource: Store resource object or mapping.
        resource_name: Name used in validation errors.

    Returns:
        A shallow copy of the resource mapping.
    """

    if not isinstance(resource_name, str) or not resource_name.strip():
        raise ValueError("resource_name must be non-empty")
    if isinstance(resource, Mapping):
        return dict(resource)
    to_dict = getattr(resource, "to_dict", None)
    if not callable(to_dict):
        raise TypeError(f"{resource_name} must expose to_dict() or be a mapping")
    payload = to_dict()
    if not isinstance(payload, Mapping):
        raise TypeError(f"{resource_name}.to_dict() must return a mapping")
    return dict(payload)


def _citation_anchor_count(payload: Mapping[str, Any]) -> int:
    """Return the number of citation anchors without exporting draft content."""

    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    raw_direct = payload.get("citation_anchors")
    if isinstance(raw_direct, list):
        return len(raw_direct)
    raw_metadata = payload.get("metadata")
    if isinstance(raw_metadata, Mapping):
        raw_nested = raw_metadata.get("citation_anchors")
        if isinstance(raw_nested, list):
            return len(raw_nested)
    return 0


def _live_project_review_records(project_id: str, remaining: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect project-scoped Wiki ReviewQueue records without changing decisions."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-empty")
    if remaining <= 0:
        return [], ["live review collection skipped because max_live_records was exhausted"]
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    try:
        items = ReviewQueue(wiki_review_queue_path()).list_items()
    except Exception as exc:
        return [], [f"live review collection skipped: {exc}"]
    for item in items:
        payload = item.to_dict()
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("project_id") != project_id:
            continue
        if not isinstance(metadata, Mapping):
            continue
        records.append(payload)
        if len(records) >= remaining:
            warnings.append("live review collection truncated by max_live_records")
            break
    return records, warnings


def _live_project_chat_answer_records(project_id: str, remaining: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect project chat-history metadata without exporting transcript text."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-empty")
    if remaining <= 0:
        return [], ["live chat-history collection skipped because max_live_records was exhausted"]
    if TYPE_CHECKING:
        from literature_assistant.core.chat.history_store import ChatHistoryStore, default_chat_history_db_path
    else:
        try:
            from literature_assistant.core.chat.history_store import ChatHistoryStore, default_chat_history_db_path
        except ImportError:
            try:
                from chat.history_store import ChatHistoryStore, default_chat_history_db_path
            except ImportError as exc:
                return [], [f"live chat-history collection skipped: {exc}"]

    db_path = default_chat_history_db_path()
    if not db_path.exists():
        return [], ["live chat-history collection skipped: chat history database is not initialized"]
    try:
        store = ChatHistoryStore(db_path)
        summaries = store.list_project_conversation_summaries(project_id, limit=remaining)
    except Exception as exc:
        return [], [f"live chat-history collection skipped: {exc}"]

    records: list[dict[str, Any]] = []
    for summary in summaries:
        records.append(
            {
                "conversation_id": str(summary.get("conversation_id") or ""),
                "project_id": project_id,
                "title": str(summary.get("title") or "Untitled conversation"),
                "mode": str(summary.get("mode") or ""),
                "status": "archived" if summary.get("archived") else "active",
                "created_at": str(summary.get("created_at") or ""),
                "updated_at": str(summary.get("updated_at") or ""),
                "node_count": int(summary.get("node_count") or 0),
                "evidence_ref_count": int(summary.get("evidence_ref_count") or 0),
                "agent_count": int(summary.get("agent_count") or 0),
                "agent_run_count": int(summary.get("agent_run_count") or 0),
                "compression_snapshot_count": int(summary.get("compression_snapshot_count") or 0),
                "has_private_transcript": True,
                "summary": "Chat history metadata collected from the local history store. Transcript text omitted.",
            }
        )
    warnings: list[str] = []
    if len(records) >= remaining:
        warnings.append("live chat-history collection truncated by max_live_records")
    return records, warnings


def _enum_value(value: Any) -> str:
    """Return a string value for runtime enum-like fields."""

    raw_value = getattr(value, "value", value)
    return str(raw_value or "")


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    """Return a mapping view for optional runtime metadata."""

    return value if isinstance(value, Mapping) else {}


def _live_project_runtime_records(
    project_id: str,
    remaining: int,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Collect agent request/result and single-paper task metadata only."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-empty")
    records: dict[str, list[dict[str, Any]]] = {"answers": [], "tasks": []}
    if remaining <= 0:
        return records, ["live agent-runtime collection skipped because max_live_records was exhausted"]
    if TYPE_CHECKING:
        from literature_assistant.core.routers import agent_bridge_router
    else:
        try:
            import routers.agent_bridge_router as agent_bridge_router
        except ImportError:
            try:
                from literature_assistant.core.routers import agent_bridge_router
            except ImportError as exc:
                return records, [f"live agent-runtime collection skipped: {exc}"]
    try:
        runtime, _session_mode = agent_bridge_router.get_runtime()
        sessions = runtime.list_sessions(include_archived=True)
    except Exception as exc:
        return records, [f"live agent-runtime collection skipped: {exc}"]

    warnings: list[str] = []
    budget = remaining
    for session in sessions:
        if budget <= 0:
            break
        session_id = str(getattr(session, "session_id", "") or "")
        if not session_id:
            continue
        session_metadata = _mapping_or_empty(getattr(session, "metadata", {}))
        try:
            jobs = runtime.list_jobs(session_id=session_id)
        except Exception as exc:
            warnings.append(f"live agent-runtime jobs skipped for session {session_id}: {exc}")
            continue
        for job in jobs:
            if budget <= 0:
                warnings.append("live agent-runtime collection truncated by max_live_records")
                break
            job_metadata = _mapping_or_empty(getattr(job, "metadata", {}))
            job_project_id = str(job_metadata.get("project_id") or session_metadata.get("project_id") or "")
            if job_project_id != project_id:
                continue
            request_id = str(job_metadata.get("agent_request_id") or "").strip()
            job_id = str(getattr(job, "job_id", "") or "").strip()
            if not request_id and not job_id:
                continue
            artifact_count = 0
            artifact_kinds: list[str] = []
            try:
                artifacts = runtime.get_job_artifacts(job_id) if job_id else []
            except Exception as exc:
                artifacts = []
                warnings.append(f"live agent-runtime artifact metadata skipped for job {job_id}: {exc}")
            for artifact in artifacts:
                artifact_count += 1
                artifact_kind = _enum_value(getattr(artifact, "artifact_type", ""))
                if artifact_kind and artifact_kind not in artifact_kinds:
                    artifact_kinds.append(artifact_kind)

            resource_refs = job_metadata.get("resource_refs")
            evidence_refs = job_metadata.get("evidence_refs")
            wiki_refs = job_metadata.get("wiki_refs")
            graph_patch_refs = job_metadata.get("graph_patch_refs")
            nested_metadata = _mapping_or_empty(job_metadata.get("metadata"))
            task_manifest = _mapping_or_empty(nested_metadata.get("task_manifest"))
            paper = _mapping_or_empty(task_manifest.get("paper"))
            missing_fields = nested_metadata.get("missing_fields")
            task_id = str(nested_metadata.get("task_id") or task_manifest.get("task_id") or request_id or job_id)
            task_record = {
                "task_id": task_id,
                "request_id": request_id,
                "job_id": job_id,
                "project_id": project_id,
                "intent": str(job_metadata.get("intent") or ""),
                "status": _enum_value(getattr(job, "status", "")),
                "kind": _enum_value(getattr(job, "kind", "")),
                "created_at": str(getattr(job, "created_at", "") or ""),
                "started_at": str(getattr(job, "started_at", "") or ""),
                "completed_at": str(getattr(job, "completed_at", "") or ""),
                "agent_host": str(job_metadata.get("agent_host") or ""),
                "source": str(job_metadata.get("source") or ""),
                "resource_ref_count": len(resource_refs) if isinstance(resource_refs, list) else 0,
                "artifact_count": artifact_count,
                "artifact_kinds": artifact_kinds,
                "single_paper_task": str(nested_metadata.get("task_schema_version") or "") == "scholar-ai-single-paper-task/v1",
                "paper_title": str(paper.get("title") or nested_metadata.get("task_title") or ""),
                "missing_field_count": len(missing_fields) if isinstance(missing_fields, list) else 0,
                "has_private_input_text": bool(str(getattr(job, "input_text", "") or "").strip()),
                "summary": "Agent request/task metadata collected from the local runtime. Prompt and artifact content omitted.",
            }
            records["tasks"].append(task_record)
            budget -= 1
            if budget <= 0:
                warnings.append("live agent-runtime collection truncated by max_live_records")
                break

            if bool(job_metadata.get("agent_result_ready")):
                consumer_metadata = _mapping_or_empty(job_metadata.get("knowledge_consumers"))
                answer_record = {
                    "request_id": request_id,
                    "run_id": job_id,
                    "job_id": job_id,
                    "project_id": project_id,
                    "title": f"Agent result: {job_metadata.get('intent') or request_id or job_id}",
                    "status": _enum_value(getattr(job, "status", "")),
                    "created_at": str(getattr(job, "created_at", "") or ""),
                    "updated_at": str(getattr(job, "completed_at", "") or getattr(job, "created_at", "") or ""),
                    "intent": str(job_metadata.get("intent") or ""),
                    "evidence_ref_count": len(evidence_refs) if isinstance(evidence_refs, list) else 0,
                    "wiki_ref_count": len(wiki_refs) if isinstance(wiki_refs, list) else 0,
                    "graph_patch_ref_count": len(graph_patch_refs) if isinstance(graph_patch_refs, list) else 0,
                    "artifact_count": artifact_count,
                    "wiki_consumer_status": str(_mapping_or_empty(consumer_metadata.get("wiki")).get("status") or ""),
                    "graph_consumer_status": str(_mapping_or_empty(consumer_metadata.get("graph")).get("status") or ""),
                    "evolution_consumer_status": str(_mapping_or_empty(consumer_metadata.get("evolution")).get("status") or ""),
                    "has_private_result_text": True,
                    "summary": "Agent result metadata collected from the local runtime. Result text omitted.",
                }
                records["answers"].append(answer_record)
                budget -= 1
    return records, warnings


def _live_project_discussion_records(project_id: str, remaining: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect discussion run metadata without exporting traces or answers."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-empty")
    if remaining <= 0:
        return [], ["live discussion-run collection skipped because max_live_records was exhausted"]
    if TYPE_CHECKING:
        from literature_assistant.core.discussion_task_store import get_discussion_task_store
    else:
        try:
            from discussion_task_store import get_discussion_task_store
        except ImportError:
            try:
                from literature_assistant.core.discussion_task_store import get_discussion_task_store
            except ImportError as exc:
                return [], [f"live discussion-run collection skipped: {exc}"]
    try:
        summaries = get_discussion_task_store().list_project_run_summaries(project_id, limit=remaining)
    except Exception as exc:
        return [], [f"live discussion-run collection skipped: {exc}"]

    records: list[dict[str, Any]] = []
    for summary in summaries:
        records.append(
            {
                "run_id": str(summary.get("run_id") or ""),
                "project_id": project_id,
                "title": f"Discussion run: {summary.get('query') or summary.get('run_id')}",
                "query": str(summary.get("query") or ""),
                "status": str(summary.get("state") or ""),
                "current_stage": str(summary.get("current_stage") or ""),
                "current_turn_index": int(summary.get("current_turn_index") or 0),
                "created_at_epoch": summary.get("created_at_epoch"),
                "updated_at_epoch": summary.get("updated_at_epoch"),
                "agent_count": int(summary.get("agent_count") or 0),
                "evidence_mode": str(summary.get("evidence_mode") or ""),
                "evidence_top_k": int(summary.get("evidence_top_k") or 0),
                "live_trace_count": int(summary.get("live_trace_count") or 0),
                "event_log_length": int(summary.get("event_log_length") or 0),
                "has_synthesis": bool(summary.get("has_synthesis")),
                "has_final_result": bool(summary.get("has_final_result")),
                "has_error": bool(summary.get("has_error")),
                "archived": bool(summary.get("archived")),
                "has_private_trace_or_answer_text": True,
                "summary": "Discussion run metadata collected from the local task store. Traces, synthesis, final answers, and event payloads omitted.",
            }
        )
    warnings: list[str] = []
    if len(records) >= remaining:
        warnings.append("live discussion-run collection truncated by max_live_records")
    return records, warnings


def _collect_live_project_okf_records(
    project_id: str,
    *,
    max_records: int,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Collect bounded local process-artifact records for a project OKF export.

    Args:
        project_id: Existing Scholar AI project id.
        max_records: Total live records to collect across groups.

    Returns:
        Process-artifact records grouped for ``export_project_artifact_okf_bundle``
        plus warnings about skipped or truncated stores.

    Raises:
        KeyError: If the project does not exist.
        ValueError: If inputs are outside the endpoint contract.
    """

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id is required when include_live_project_records is true")
    if max_records < 1:
        raise ValueError("max_records must be positive")

    if TYPE_CHECKING:
        from literature_assistant.core.routers import resources_router
    else:
        import routers.resources_router as resources_router

    store = resources_router.get_writing_resource_store()
    project = store.get_project(normalized_project_id)
    if project is None:
        raise KeyError(normalized_project_id)

    records: dict[str, list[dict[str, Any]]] = {
        "materials": [],
        "evidence": [],
        "answers": [],
        "tasks": [],
        "reviews": [],
        "exports": [],
    }
    warnings: list[str] = []
    remaining = max_records

    def append_record(group: str, record: dict[str, Any]) -> bool:
        nonlocal remaining
        if remaining <= 0:
            return False
        records[group].append(record)
        remaining -= 1
        return True

    for material in store.list_materials(normalized_project_id):
        if not append_record("materials", _resource_to_dict(material, resource_name="material")):
            warnings.append("live material collection truncated by max_live_records")
            break

    if remaining > 0:
        try:
            chunk_store = resources_router._load_chunk_store(normalized_project_id)
        except Exception as exc:
            warnings.append(f"live evidence chunk-ref collection skipped: {exc}")
            chunk_store = {}
        if isinstance(chunk_store, Mapping):
            for material_id, chunks in sorted(chunk_store.items(), key=lambda item: str(item[0])):
                if not isinstance(chunks, list):
                    continue
                for index, chunk in enumerate(chunks):
                    if not isinstance(chunk, Mapping):
                        continue
                    chunk_id = str(chunk.get("chunk_id") or f"{material_id}-chunk-{index + 1}").strip()
                    record = {
                        "evidence_ref": chunk_id,
                        "chunk_id": chunk_id,
                        "material_id": str(chunk.get("material_id") or material_id),
                        "title": str(chunk.get("title") or ""),
                        "page": chunk.get("page"),
                        "chunk_type": str(chunk.get("chunk_type") or "unknown"),
                        "source_relative_path": str(chunk.get("source_relative_path") or ""),
                        "summary": f"Bounded chunk reference for {chunk_id}. Full text omitted.",
                        "has_private_text": bool(chunk.get("text")),
                    }
                    if not append_record("evidence", record):
                        warnings.append("live evidence chunk-ref collection truncated by max_live_records")
                        break
                if remaining <= 0:
                    break
        else:
            warnings.append("live evidence chunk-ref collection skipped: chunk store was not a mapping")

    for draft in store.list_drafts(normalized_project_id):
        payload = _resource_to_dict(draft, resource_name="draft")
        record = {
            "conversation_id": str(payload.get("draft_id") or ""),
            "draft_id": str(payload.get("draft_id") or ""),
            "project_id": normalized_project_id,
            "title": str(payload.get("title") or "Untitled draft"),
            "section_id": str(payload.get("section_id") or ""),
            "status": str(payload.get("status") or ""),
            "created_at": str(payload.get("created_at") or ""),
            "updated_at": str(payload.get("updated_at") or ""),
            "last_edited_by": str(payload.get("last_edited_by") or ""),
            "citation_anchor_count": _citation_anchor_count(payload),
            "summary": "Draft/answer metadata collected from the local project store. Content omitted.",
        }
        if not append_record("answers", record):
            warnings.append("live answer/draft collection truncated by max_live_records")
            break

    if remaining > 0:
        chat_records, chat_warnings = _live_project_chat_answer_records(normalized_project_id, remaining)
        warnings.extend(chat_warnings)
        for record in chat_records:
            if not append_record("answers", record):
                warnings.append("live chat-history collection truncated by max_live_records")
                break

    if remaining > 0:
        runtime_records, runtime_warnings = _live_project_runtime_records(normalized_project_id, remaining)
        warnings.extend(runtime_warnings)
        for group in ("tasks", "answers"):
            for record in runtime_records[group]:
                if not append_record(group, record):
                    warnings.append("live agent-runtime collection truncated by max_live_records")
                    break
            if remaining <= 0:
                break

    if remaining > 0:
        discussion_records, discussion_warnings = _live_project_discussion_records(normalized_project_id, remaining)
        warnings.extend(discussion_warnings)
        for record in discussion_records:
            if not append_record("answers", record):
                warnings.append("live discussion-run collection truncated by max_live_records")
                break

    if hasattr(store, "list_figure_assets"):
        for asset in store.list_figure_assets(normalized_project_id):
            payload = _resource_to_dict(asset, resource_name="figure_asset")
            record = {
                "export_id": str(payload.get("asset_id") or ""),
                "artifact_id": str(payload.get("asset_id") or ""),
                "artifact_kind": "figure_table_asset",
                "project_id": normalized_project_id,
                "kind": str(payload.get("kind") or ""),
                "caption": str(payload.get("caption") or ""),
                "numbering": str(payload.get("numbering") or ""),
                "material_id": str(payload.get("material_id") or ""),
                "source_page": payload.get("source_page"),
                "bbox": payload.get("bbox"),
                "width": payload.get("width"),
                "height": payload.get("height"),
                "format": payload.get("format"),
                "has_private_asset_path": bool(payload.get("asset_path")),
                "description": "Figure/table asset metadata collected from the local project store. Private asset path omitted.",
            }
            if not append_record("exports", record):
                warnings.append("live figure/export collection truncated by max_live_records")
                break

    if remaining > 0:
        review_records, review_warnings = _live_project_review_records(normalized_project_id, remaining)
        warnings.extend(review_warnings)
        for record in review_records:
            if not append_record("reviews", record):
                break

    total = sum(len(group_records) for group_records in records.values())
    warnings.append(f"collected {total} live project records for local OKF export")
    return records, warnings


def _safe_import_source_label(path: Path) -> str:
    resolved = path.resolve()
    for root in (REPO_ROOT, WORKSPACE_ARTIFACTS_ROOT, WORKSPACE_REFERENCES_ROOT):
        root_resolved = root.resolve()
        if _is_relative_to(resolved, root_resolved):
            return resolved.relative_to(root_resolved).as_posix()
    return resolved.name


def _resolve_wiki_import_source(raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("source_path cannot be empty")
    candidate = Path(raw_path.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    resolved = candidate.resolve()
    if resolved.suffix.lower() != ".md":
        raise ValueError("source_path must point to a Markdown .md file")
    if not any(_is_relative_to(resolved, root) for root in _wiki_import_allowed_roots()):
        raise ValueError("source_path must stay inside an allowed local workspace root")
    if any(_is_relative_to(resolved, root) for root in _wiki_import_forbidden_roots()):
        raise ValueError("source_path points to a protected workspace area")
    if not resolved.is_file():
        raise FileNotFoundError(f"Markdown source not found: {_safe_import_source_label(resolved)}")
    size = resolved.stat().st_size
    if size > _MAX_WIKI_IMPORT_FILE_BYTES:
        raise ValueError(f"Markdown source exceeds {_MAX_WIKI_IMPORT_FILE_BYTES} bytes")
    return resolved


def _resolve_wiki_import_archive(raw_path: str) -> Path:
    """Resolve a local OKF archive path without granting general file reads."""

    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("archive_path cannot be empty")
    candidate = Path(raw_path.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    resolved = candidate.resolve()
    if resolved.suffix.lower() != ".zip":
        raise ValueError("archive_path must point to a .zip archive")
    if not any(_is_relative_to(resolved, root) for root in _wiki_import_allowed_roots()):
        raise ValueError("archive_path must stay inside an allowed local workspace root")
    if any(_is_relative_to(resolved, root) for root in _wiki_import_forbidden_roots()):
        raise ValueError("archive_path points to a protected workspace area")
    if not resolved.is_file():
        raise FileNotFoundError(f"OKF archive not found: {_safe_import_source_label(resolved)}")
    size = resolved.stat().st_size
    if size > _MAX_WIKI_IMPORT_TOTAL_BYTES:
        raise ValueError(f"OKF archive exceeds {_MAX_WIKI_IMPORT_TOTAL_BYTES} bytes")
    return resolved


def _markdown_import_title(path: Path, frontmatter: dict[str, Any], body: str) -> str:
    raw_title = frontmatter.get("title")
    if isinstance(raw_title, str) and raw_title.strip():
        return raw_title.strip()
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return path.stem.replace("_", " ").replace("-", " ").strip() or "Imported Markdown"


def _strip_wiki_auto_markers(body: str) -> str:
    kept_lines = [
        line
        for line in body.splitlines()
        if line.strip() not in {AUTO_START, AUTO_END}
    ]
    return "\n".join(kept_lines).strip()


def _wiki_import_extra(source_path: Path, content_hash: str, owner: str) -> dict[str, Any]:
    return set_permissions(
        {
            "entry_source": "local_markdown_import",
            "import_source": {
                "type": "local_markdown",
                "path": _safe_import_source_label(source_path),
                "sha256": content_hash,
            }
        },
        WikiPagePermissions(owner=owner, visibility=WikiPageVisibility.PRIVATE),
    )


def _wiki_knowledge_ref_payload(
    *,
    page_path: str,
    source_hash: str,
    content: str,
    import_source_hash: str = "",
) -> dict[str, Any]:
    """Return the shared wiki knowledge-ref shape for search, import, and agent reads."""

    normalized_page_path = str(page_path or "").strip().replace("\\", "/")
    normalized_source_hash = str(source_hash or "").strip().lower()
    normalized_import_source_hash = str(import_source_hash or "").strip().lower()
    if not normalized_page_path:
        raise ValueError("page_path is required")
    if not re.fullmatch(r"[0-9a-f]{64}", normalized_source_hash):
        raise ValueError("source_hash must be a lowercase sha256 hex digest")
    if normalized_import_source_hash and not re.fullmatch(r"[0-9a-f]{64}", normalized_import_source_hash):
        raise ValueError("import_source_hash must be a lowercase sha256 hex digest")
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    ref_id = f"wiki:{normalized_page_path}"
    payload = {
        "source_hash": normalized_source_hash,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "ref_id": ref_id,
        "chunk_id": f"{ref_id}#{derive_chunk_id(normalized_source_hash, 0)}",
        "read_endpoint": f"/api/agent-bridge/resource/{ref_id}",
        "span_start": 0,
        "span_end": len(content),
    }
    if normalized_import_source_hash:
        payload["import_source_hash"] = normalized_import_source_hash
    return payload


def _wiki_import_registry() -> WikiRegistry:
    """Return the registry that mirrors accepted local Markdown into Source Vault."""

    return WikiRegistry(wiki_runtime_db_path())


def _source_text_span(source_text: str, chunk_text: str) -> tuple[int, int]:
    """Return a best-effort character span for imported Markdown body text."""

    if not isinstance(source_text, str) or not isinstance(chunk_text, str):
        raise TypeError("source_text and chunk_text must be strings")
    if not chunk_text:
        raise ValueError("chunk_text cannot be empty")
    start = source_text.find(chunk_text)
    if start < 0:
        start = 0
    return start, start + len(chunk_text)


def _registry_record_class(registry: WikiRegistry) -> type[SourceRecord]:
    """Return the SourceRecord class used by a package or legacy flat registry."""

    module = sys.modules.get(type(registry).__module__)
    candidate = getattr(module, "SourceRecord", None) if module is not None else None
    if isinstance(candidate, type):
        return candidate
    return SourceRecord


def _registry_chunk_input_class(registry: WikiRegistry) -> type[ChunkInput]:
    """Return the ChunkInput class used by a package or legacy flat registry."""

    module = sys.modules.get(type(registry).__module__)
    candidate = getattr(module, "ChunkInput", None) if module is not None else None
    if isinstance(candidate, type):
        return candidate
    return ChunkInput


def _source_vault_sync_from_import(
    *,
    source_path: Path,
    source_label: str,
    source_hash: str,
    source_text: str,
    chunk_text: str,
    title: str,
    page_path: str,
) -> dict[str, str]:
    """Register one imported Markdown source and expose mirrored Source Vault refs."""

    if not isinstance(source_path, Path):
        raise TypeError("source_path must be a Path")
    if not source_label.strip():
        raise ValueError("source_label cannot be empty")
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise ValueError("source_hash must be a lowercase sha256 hex digest")
    if not chunk_text.strip():
        raise ValueError("chunk_text cannot be empty")

    registry = _wiki_import_registry()
    now_iso = utc_now_iso()
    source_id = derive_source_id("local_markdown_import", title, source_hash)
    span_start, span_end = _source_text_span(source_text, chunk_text)
    legacy_chunk_id = derive_chunk_id(source_hash, 0)
    source_record_cls = _registry_record_class(registry)
    chunk_input_cls = _registry_chunk_input_class(registry)
    registry.upsert_source(
        source_record_cls(
            source_id=source_id,
            source_type="local_markdown_import",
            title=title,
            source_hash=source_hash,
            source_path=source_path,
        ),
        now_iso=now_iso,
    )
    registry.register_chunks(
        source_id,
        source_hash,
        [
            chunk_input_cls(
                text=chunk_text,
                chunk_index=0,
                section=page_path,
                span_start=span_start,
                span_end=span_end,
            )
        ],
        now_iso=now_iso,
    )
    source_status = registry.get_source_vault_mirror_status(source_id)
    chunk_status = registry.get_source_vault_chunk_mirror_status(legacy_chunk_id)
    source_vault_status = (
        "mirrored"
        if source_status["status"] == "mirrored" and chunk_status["status"] == "mirrored"
        else f"{source_status['status']}:{chunk_status['status']}"
    )
    source_vault_source_id = (
        registry.get_source_vault_id(source_id) or ""
        if source_status["status"] == "mirrored"
        else ""
    )
    source_vault_chunk_id = (
        registry.get_source_vault_chunk_id(legacy_chunk_id) or ""
        if chunk_status["status"] == "mirrored"
        else ""
    )
    source_vault_ref_id = build_source_vault_chunk_ref_id(source_vault_chunk_id) if source_vault_chunk_id else ""
    source_vault_read_endpoint = (
        build_source_vault_chunk_read_endpoint(source_vault_chunk_id)
        if source_vault_chunk_id
        else ""
    )
    return {
        "source_registry_id": source_id,
        "source_vault_source_id": source_vault_source_id,
        "source_vault_chunk_id": source_vault_chunk_id,
        "source_vault_ref_id": source_vault_ref_id,
        "source_vault_read_endpoint": source_vault_read_endpoint,
        "source_vault_status": source_vault_status,
        "source_vault_error": source_status["error"] or chunk_status["error"],
    }


def _append_wiki_draft_review_item(
    *,
    item_prefix: str,
    page_slug: str,
    page_kind: str,
    title: str,
    body: str,
    source: str,
    metadata: Mapping[str, Any],
) -> str:
    """Append a pending review item for a newly written private wiki draft.

    Args:
        item_prefix: Stable review item namespace for the capture source.
        page_slug: Wiki page stable slug.
        page_kind: Wiki page kind directory.
        title: Human-readable page title.
        body: Markdown body used only for a short review summary.
        source: Review source label.
        metadata: Bounded provenance and approval facts for the review item.

    Returns:
        Created review item id.
    """

    if not item_prefix.strip():
        raise ValueError("item_prefix cannot be empty")
    if not page_slug.strip():
        raise ValueError("page_slug cannot be empty")
    if not page_kind.strip():
        raise ValueError("page_kind cannot be empty")
    queue = ReviewQueue(wiki_review_queue_path())
    existing_ids = {item.item_id for item in queue.list_items()}
    candidate_id = f"{item_prefix.strip()}-{page_slug.strip()}"
    suffix = 1
    while candidate_id in existing_ids:
        suffix += 1
        candidate_id = f"{item_prefix.strip()}-{page_slug.strip()}-{suffix}"
    page_relative_path = f"{page_kind.strip()}/{page_slug.strip()}.md"
    page_content = _page_store(create=False).read_page(Path(page_relative_path))
    if page_content is None:
        raise ValueError(f"review target page not found: {page_relative_path}")
    queue.append(
        make_review_item(
            item_id=candidate_id,
            kind=ReviewItemKind.draft,
            title=title,
            page_path=page_relative_path,
            summary=body.strip().splitlines()[0][:200] if body.strip() else "",
            source=source,
            metadata=metadata,
            target=make_wiki_page_revision_review_target(
                page_id=page_slug,
                page_path=page_relative_path,
                expected_content_hash=_wiki_content_hash(str(page_content)),
                expected_status=WikiPageStatus.draft.value,
            ),
        )
    )
    return candidate_id


def _remove_wiki_draft_review_item(item_id: str) -> None:
    """Remove a same-transaction import review item during rollback."""

    if item_id.strip():
        ReviewQueue(wiki_review_queue_path()).remove(item_id)


def _restore_wiki_import_page(
    *,
    service: Any,
    action: str,
    page: Any,
    existing_page: Any | None,
) -> None:
    """Restore wiki page state when import governance recording fails."""

    if action == "created":
        service.purge_page(page.stable_slug)
        return
    if existing_page is None:
        return
    service.update_page(
        slug=existing_page.stable_slug,
        title=existing_page.title,
        body=existing_page.body,
        status=existing_page.status.value,
        evidence_refs=list(existing_page.evidence_refs),
        source_hashes=list(existing_page.source_hashes),
        extra=dict(existing_page.extra),
    )


def _rollback_wiki_import_governance(
    *,
    service: Any,
    action: str,
    page: Any,
    existing_page: Any | None,
    review_item_id: str = "",
) -> Exception | None:
    """Best-effort rollback for page and review item mutations."""

    rollback_error: Exception | None = None
    if review_item_id:
        try:
            _remove_wiki_draft_review_item(review_item_id)
        except (KeyError, ValueError, OSError) as exc:
            rollback_error = exc
    try:
        _restore_wiki_import_page(
            service=service,
            action=action,
            page=page,
            existing_page=existing_page,
        )
    except (ValueError, OSError) as exc:
        rollback_error = exc
    return rollback_error


def _record_wiki_import_runtime_action(
    *,
    page: Any,
    review_item_id: str,
    source_label: str,
    content_hash: str,
    action: str,
    owner: str,
    requested_status: str,
) -> dict[str, str]:
    """Create runtime-visible action refs for a local Markdown wiki import.

    Args:
        page: WikiPage-like page snapshot that was written as a private draft.
        review_item_id: Pending wiki review queue item id.
        source_label: Safe local source label, never an arbitrary absolute path.
        content_hash: SHA-256 of the imported Markdown source.
        action: Import mutation action, ``created`` or ``updated``.
        owner: Local wiki owner id.
        requested_status: Status requested by the caller before draft forcing.

    Returns:
        Runtime session, job, and approval identifiers for recovery probes.

    Raises:
        ValueError: If any required runtime/review metadata cannot be recorded.
    """

    if not str(review_item_id or "").strip():
        raise ValueError("review_item_id cannot be empty")
    if not str(content_hash or "").strip():
        raise ValueError("content_hash cannot be empty")
    if action not in {"created", "updated"}:
        raise ValueError("action must be created or updated")

    runtime = get_writing_runtime()
    page_path = (Path(page.kind.value) / f"{page.stable_slug}.md").as_posix()
    request_id = f"wikiimport_{uuid4().hex[:16]}"
    session = runtime.create_session(
        mode=SessionMode.PROMPT,
        user_id=owner,
        tags=["wiki_import", "local_markdown_import"],
        metadata={
            "title": f"Wiki import review: {page.title}",
            "source": "local_markdown_import",
            "agent_request_id": request_id,
            "intent": "wiki_import_review_candidate",
            "review_item_id": review_item_id,
            "wiki_page_path": page_path,
        },
    )
    try:
        metadata: dict[str, Any] = {
            "source": "local_markdown_import",
            "manual_wiki_import": True,
            "agent_request_id": request_id,
            "agent_host": "local_runtime",
            "intent": "wiki_import_review_candidate",
            "review_item_id": review_item_id,
            "approval_surface": "wiki_review_queue",
            "runtime_action_family": "wiki_candidate",
            "requested_status": requested_status,
            "wiki_page_path": page_path,
            "wiki_page_slug": page.stable_slug,
            "output_targets": {
                "runtime_job": True,
                "wiki_candidate": True,
                "graph_candidate": False,
                "smart_read_conversation": False,
                "evolution_capture": False,
            },
            "knowledge_capture": {
                "eligible": True,
                "wiki_candidate": True,
                "graph_candidate": False,
                "requires_review_queue_approval": True,
            },
            "wiki_refs": [
                {
                    "ref_id": f"wiki:{page_path}",
                    "slug": page.stable_slug,
                    "wiki_slug": page.stable_slug,
                    "page_path": page_path,
                    "kind": page.kind.value,
                    "status": page.status.value,
                    "review_item_id": review_item_id,
                }
            ],
            "resource_refs": [
                {
                    "resource_type": "local_markdown_source",
                    "ref_id": f"sha256:{content_hash[:16]}",
                    "source_path": source_label,
                    "sha256": content_hash,
                }
            ],
            "agent_result_consumers": {
                "wiki": {
                    "status": "private_draft_review_pending",
                    "slug": page.stable_slug,
                    "wiki_slug": page.stable_slug,
                    "review_item_id": review_item_id,
                }
            },
            "evidence_integrity_gate": {
                "status": "block",
                "blocking_claim_id": "wiki_import_review_approval",
                "requires_user_confirmation": True,
            },
            "forbidden_actions": [
                "direct_zotero_db_write",
                "external_upload",
                "auto_approve_import",
            ],
        }
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.AGENT_REQUEST,
            input_text="Local Markdown wiki import pending review.",
            tags=["wiki_import", "local_markdown_import", "requires_approval"],
            metadata=metadata,
        )
        runtime.add_job_artifact(
            job.job_id,
            artifact_type=ArtifactType.METADATA,
            content={
                "kind": "wiki_import_runtime_action",
                "schema_version": "scholar_ai_wiki_import_runtime_action_v1",
                "review_item_id": review_item_id,
                "wiki_page_path": page_path,
                "source_path": source_label,
                "source_sha256": content_hash,
                "action": action,
                "requires_user_confirmation": True,
                "external_mutation": False,
                "source_material_mutation": False,
            },
            created_by="wiki_router",
            metadata={
                "kind": "wiki_import_runtime_action",
                "schema_version": "scholar_ai_wiki_import_runtime_action_v1",
                "output_target": "wiki_candidate",
                "review_item_id": review_item_id,
                "status": "pending_review",
            },
        )
        approval = runtime.request_approval(
            job_id=job.job_id,
            session_id=session.session_id,
            reason="Review imported wiki draft before finalizing it as knowledge.",
            content_preview=f"{page.title} ({page_path})",
            metadata={
                "approval_surface": "wiki_review_queue",
                "review_item_id": review_item_id,
                "wiki_page_path": page_path,
                "requested_status": requested_status,
                "requires_user_confirmation": True,
            },
        )
        runtime.update_job_metadata(
            job.job_id,
            {
                "runtime_approval_id": approval.approval_id,
                "wiki_import": {
                    "review_item_id": review_item_id,
                    "wiki_page_path": page_path,
                    "approval_id": approval.approval_id,
                    "status": "pending_review",
                },
            },
        )
        runtime.build_action_preflight(
            action_id="agent.wiki_candidate",
            required_claim_id="handoff_readiness",
            session_id=session.session_id,
            job_id=job.job_id,
            require_ready=False,
            persist_refresh_receipt=True,
        )
        runtime.persist_agent_handoff_card(job.job_id)
        ReviewQueue(wiki_review_queue_path()).update_metadata(
            review_item_id,
            {
                "runtime_session_id": session.session_id,
                "runtime_job_id": job.job_id,
                "runtime_approval_id": approval.approval_id,
                "runtime_recovery": {
                    "research_action_lifecycle": f"/runtime/research-action-lifecycle?job_id={job.job_id}",
                    "workflow_passport": f"/runtime/workflow-passport?job_id={job.job_id}",
                    "evidence_integrity_gate": f"/runtime/evidence-integrity-gate?job_id={job.job_id}",
                    "agent_handoff_card": f"/runtime/job/{job.job_id}/agent-handoff-card",
                },
            },
        )
        return {
            "runtime_session_id": session.session_id,
            "runtime_job_id": job.job_id,
            "runtime_approval_id": approval.approval_id,
        }
    except Exception:
        runtime.delete_session(session.session_id)
        raise


def _query_evidence_ref(result: WikiSearchResult) -> dict[str, Any]:
    return {
        "page_path": result.page_path.as_posix(),
        "title": result.title,
        "score": result.score,
        "snippet": result.snippet,
        "source": result.source,
        "source_labels": ["wiki_first", result.source],
    }


def _normalize_page_path(page_path: str) -> Path:
    normalized = page_path.strip().replace("\\", "/")
    if not normalized:
        raise HTTPException(status_code=400, detail="page_path cannot be empty")
    if any(ord(char) < 32 for char in normalized):
        raise HTTPException(status_code=400, detail="page_path contains control characters")
    relative_path = Path(normalized)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise HTTPException(status_code=400, detail="page_path must stay inside the wiki root")
    if relative_path.suffix and relative_path.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="page_path must target a markdown page")
    if not relative_path.suffix:
        relative_path = relative_path.with_suffix(".md")
    return relative_path


def _empty_compile_budget_summary() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "input_cost_usd": 0.0,
        "output_cost_usd": 0.0,
        "estimated_cost_usd": 0.0,
        "pricing_configured": False,
        "pricing_source": "not_configured",
        "currency": "USD",
    }


def _planned_paths_for_source(registry: WikiRegistry, source_id: str) -> list[str]:
    source = registry.get_source(source_id)
    if source is None:
        return []
    slug = stable_slug(source.title)
    planned = [Path("sources") / f"{slug}.md"]
    if source.source_type == "paper":
        planned.append(Path("papers") / f"{slug}.md")
    return [path.as_posix() for path in planned]


def _planned_paths_for_project(compiler: WikiCompiler) -> list[str]:
    plan = compiler.plan_compile()
    paths = [*plan.pages_to_create, *plan.pages_to_update]
    return [path.as_posix() for path in paths]


def _written_paths_for_compile(planned_paths: list[str], dry_run: bool) -> list[str]:
    if dry_run:
        return []
    store = _page_store(create=False)
    return [path for path in planned_paths if store.read_page(Path(path)) is not None]


def _parse_page_content(path: Path, content: str) -> WikiPageSummaryPayload:
    frontmatter, _body = _split_frontmatter(content)
    return WikiPageSummaryPayload(
        path=path.as_posix(),
        title=str(frontmatter.get("title") or path.stem),
        kind=str(frontmatter.get("kind") or path.parent.as_posix() or "unknown"),
        status=str(frontmatter.get("status") or "draft"),
    )


def _category_values(frontmatter: dict[str, Any], summary: WikiPageSummaryPayload) -> list[str]:
    values: list[str] = []
    for key in ("category", "categories"):
        raw_value = frontmatter.get(key)
        if isinstance(raw_value, str):
            values.extend(part.strip() for part in raw_value.split("/") if part.strip())
        elif isinstance(raw_value, list):
            values.extend(str(item).strip() for item in raw_value if str(item).strip())
    if not values:
        kind = summary.kind.strip() or Path(summary.path).parts[0]
        values.append(kind)
    return values


def _category_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return normalized[:64] or "uncategorized"


def _tag_values(frontmatter: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("tags", "labels", "category", "categories"):
        raw_value = frontmatter.get(key)
        if isinstance(raw_value, str):
            values.extend(part.strip() for part in re.split(r"[,/]", raw_value) if part.strip())
        elif isinstance(raw_value, list):
            values.extend(str(item).strip() for item in raw_value if str(item).strip())
    deduped: dict[str, str] = {}
    for value in values:
        deduped.setdefault(_category_key(value), value)
    return list(deduped.values())


def _build_tag_index(entries: list[tuple[list[str], WikiPageSummaryPayload]]) -> list[WikiTagPayload]:
    tags: dict[str, WikiTagPayload] = {}
    for tag_values, summary in entries:
        for label in tag_values:
            key = _category_key(label)
            payload = tags.get(key)
            if payload is None:
                payload = WikiTagPayload(key=key, label=label, page_count=0)
                tags[key] = payload
            payload.page_count += 1
            payload.pages.append(summary)
    return sorted(tags.values(), key=lambda item: (item.label.lower(), item.key))


def _build_category_tree(entries: list[tuple[list[str], WikiPageSummaryPayload]]) -> list[WikiCategoryNodePayload]:
    nodes_by_key: dict[str, WikiCategoryNodePayload] = {}
    root_order: list[str] = []

    for category_path, summary in entries:
        parent_children: list[WikiCategoryNodePayload] | None = None
        compound_key = ""
        for label in category_path:
            node_key = _category_key(label)
            compound_key = f"{compound_key}/{node_key}" if compound_key else node_key
            node = nodes_by_key.get(compound_key)
            if node is None:
                node = WikiCategoryNodePayload(key=compound_key, label=label.strip(), page_count=0)
                nodes_by_key[compound_key] = node
                if parent_children is None:
                    root_order.append(compound_key)
                else:
                    parent_children.append(node)
            node.page_count += 1
            parent_children = node.children
        if category_path:
            nodes_by_key[compound_key].pages.append(summary)

    return [nodes_by_key[key] for key in root_order]


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    lines = content.split("\n")
    if lines and lines[0].strip() == "---json":
        frontmatter_lines: list[str] = []
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                try:
                    payload = json.loads("\n".join(frontmatter_lines))
                    frontmatter = payload if isinstance(payload, dict) else {}
                except json.JSONDecodeError:
                    frontmatter = {}
                return frontmatter, "\n".join(lines[index + 1 :])
            frontmatter_lines.append(line)
    return {}, content


def _current_wiki_user(user_id: str | None) -> str:
    try:
        return normalize_user_id(user_id, default=DEFAULT_WIKI_OWNER)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _frontmatter_extra(frontmatter: dict[str, Any]) -> dict[str, Any]:
    extra = frontmatter.get("extra")
    return dict(extra) if isinstance(extra, dict) else {}


def _wiki_content_hash(content: str) -> str:
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _wiki_review_request_fingerprint(
    *,
    action: str,
    item_id: str,
    reason: str,
    decided_by: str,
    request_id: str,
    expected_item_revision: str,
    expected_target_content_hash: str | None,
) -> str:
    """Hash canonical review request details for idempotent replay checks."""

    payload = {
        "action": action.strip(),
        "item_id": item_id.strip(),
        "reason": reason.strip(),
        "decided_by": decided_by.strip(),
        "request_id": request_id.strip(),
        "expected_item_revision": expected_item_revision.strip(),
        "expected_target_content_hash": str(expected_target_content_hash or "").strip().lower(),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _annotation_review_enqueue_fingerprint(
    request: WikiAnnotationReviewEnqueueRequest,
) -> str:
    """Hash the complete annotation enqueue request for durable replay."""

    canonical = json.dumps(
        {
            "schema_version": "scholar-ai-annotation-review-enqueue/v1",
            "project_id": request.project_id,
            "material_id": request.material_id,
            "note_id": request.note_id,
            "expected_updated_at": request.expected_updated_at,
            "expected_content_hash": request.expected_content_hash.lower(),
            "request_id": request.request_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _annotation_review_project_material(project_id: str, material_id: str) -> tuple[Any, Any]:
    """Resolve an exact project/material pair from the canonical resource store."""

    normalized_project_id = _normalize_identifier(project_id, "project_id")
    normalized_material_id = _normalize_identifier(material_id, "material_id")
    if normalized_project_id is None or normalized_material_id is None:
        raise HTTPException(status_code=400, detail="project_id and material_id are required")

    if TYPE_CHECKING:
        from literature_assistant.core.routers import resources_router
    else:
        import routers.resources_router as resources_router

    store = resources_router.get_writing_resource_store()
    project = store.get_project(normalized_project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {normalized_project_id}")
    material = store.get_material(normalized_material_id)
    if material is None:
        raise HTTPException(status_code=404, detail=f"Material not found: {normalized_material_id}")
    if str(getattr(material, "project_id", "") or "") != normalized_project_id:
        raise HTTPException(status_code=400, detail="material does not belong to project")
    return project, material


def _annotation_review_note_snapshot(material_id: str, note_id: str) -> dict[str, Any] | None:
    """Read a strict annotation note through its owning router module."""

    if TYPE_CHECKING:
        from literature_assistant.core.routers import annotation_router
    else:
        import routers.annotation_router as annotation_router

    raw_snapshot: object = annotation_router.get_annotation_note_snapshot(material_id, note_id)
    if raw_snapshot is None:
        return None
    if not isinstance(raw_snapshot, dict):
        raise TypeError("annotation note snapshot must be a mapping")
    snapshot: dict[str, Any] = {}
    for key, value in raw_snapshot.items():
        if not isinstance(key, str):
            raise TypeError("annotation note snapshot keys must be strings")
        snapshot[key] = value
    return snapshot


def _validate_live_annotation_review_target(
    target: AnnotationNoteReviewTarget,
    *,
    decision: bool,
) -> dict[str, Any]:
    """Revalidate project ownership, opt-in, and exact note snapshot CAS."""

    try:
        _annotation_review_project_material(target.project_id, target.material_id)
    except HTTPException as exc:
        if decision:
            raise ValueError(f"annotation review source is no longer eligible: {exc.detail}") from exc
        raise

    try:
        snapshot = _annotation_review_note_snapshot(target.material_id, target.note_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("annotation note schema is not eligible for Wiki review") from exc
    if snapshot is None:
        if decision:
            raise ValueError("annotation review note no longer exists")
        raise HTTPException(status_code=404, detail=f"Annotation note not found: {target.note_id}")
    note = snapshot.get("note")
    if not isinstance(note, Mapping):
        raise ValueError("annotation note snapshot is invalid")
    enabled_scopes = note.get("enabled_scopes")
    scopes = {
        str(scope.value if hasattr(scope, "value") else scope)
        for scope in enabled_scopes
    } if isinstance(enabled_scopes, list) else set()
    if target.required_scope not in scopes:
        raise ValueError("annotation note is not enabled for wiki_review")
    if str(note.get("updated_at") or "") != target.expected_updated_at:
        raise ValueError("annotation note changed; refresh and enqueue a new review item")
    content_hash = str(snapshot.get("content_hash") or "").lower()
    if content_hash != target.expected_content_hash:
        raise ValueError("annotation note content changed; refresh and enqueue a new review item")
    return snapshot


def _validate_review_node_id(node_id: str, field_name: str = "node_id") -> str:
    value = str(node_id or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")
    if len(value) > 512:
        raise HTTPException(status_code=400, detail=f"{field_name} is too long")
    if any(ord(char) < 32 for char in value):
        raise HTTPException(status_code=400, detail=f"{field_name} contains control characters")
    return value


def _normalize_review_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")
        return None
    normalized = value.strip()
    if required and not normalized:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")
    if len(normalized) > max_length:
        raise HTTPException(status_code=400, detail=f"{field_name} is too long")
    return normalized or None


def _snapshot_page(
    path: Path,
    content: str,
    *,
    expected_current_content: str,
) -> WikiGraphReviewPageSnapshotPayload:
    return WikiGraphReviewPageSnapshotPayload(
        page_path=path.as_posix(),
        content=content,
        content_hash=_wiki_content_hash(content),
        expected_current_hash=_wiki_content_hash(expected_current_content),
    )


def _graph_review_undo_snapshots(
    store: WikiPageStore,
    pages: dict[str, tuple[Path, str, dict[str, Any], str]],
) -> list[WikiGraphReviewPageSnapshotPayload]:
    """Build undo snapshots after apply writes have reached durable storage."""

    snapshots: list[WikiGraphReviewPageSnapshotPayload] = []
    for page_key in sorted(pages):
        relative_path, original_content, _frontmatter, _body = pages[page_key]
        current_content = store.read_page(relative_path)
        if current_content is None:
            raise HTTPException(
                status_code=500,
                detail=f"graph review page disappeared after apply: {page_key}",
            )
        snapshots.append(
            _snapshot_page(
                relative_path,
                original_content,
                expected_current_content=str(current_content),
            )
        )
    return snapshots


def _stable_json_key(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return repr(value)


def _as_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _dedupe_json_values(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        key = _stable_json_key(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _merge_frontmatter_list(frontmatter: dict[str, Any], key: str, additions: list[Any]) -> None:
    merged = _dedupe_json_values([*_as_json_list(frontmatter.get(key)), *additions])
    if merged:
        frontmatter[key] = merged


def _graph_review_extra(frontmatter: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    extra = _frontmatter_extra(frontmatter)
    raw_review = extra.get("graph_review")
    review = dict(raw_review) if isinstance(raw_review, dict) else {}
    return extra, review


def _write_frontmatter_preserving_body(
    store: WikiPageStore,
    relative_path: Path,
    frontmatter: dict[str, Any],
    body: str,
) -> None:
    next_frontmatter = dict(frontmatter)
    next_frontmatter.setdefault("id", relative_path.with_suffix("").as_posix())
    next_frontmatter.setdefault("kind", relative_path.parts[0].rstrip("s") if relative_path.parts else "unknown")
    next_frontmatter.setdefault("title", relative_path.stem)
    atomic_write_text(store.resolve(relative_path), f"{render_frontmatter(next_frontmatter)}{body}")


def _read_graph_review_pages(
    store: WikiPageStore,
    nodes: list[WikiGraphReviewNodeInput],
    current_user: str,
) -> dict[str, tuple[Path, str, dict[str, Any], str]]:
    pages: dict[str, tuple[Path, str, dict[str, Any], str]] = {}
    if not nodes:
        raise HTTPException(status_code=400, detail="nodes cannot be empty")
    for node in nodes:
        _validate_review_node_id(node.node_id)
        relative_path = _normalize_page_path(node.page_path)
        key = relative_path.as_posix()
        if key in pages:
            continue
        content = store.read_page(relative_path)
        if content is None:
            raise HTTPException(status_code=404, detail=f"Wiki page not found: {key}")
        frontmatter, body = _split_frontmatter(str(content))
        _ensure_can_write_extra(_frontmatter_extra(frontmatter), current_user)
        pages[key] = (relative_path, str(content), dict(frontmatter), body)
    return pages


def _rebuild_review_graph(current_user: str) -> None:
    WikiGraphStore.default().rebuild_from_page_store(_reviewed_page_store(current_user))


def _ensure_can_read_extra(extra: dict[str, Any], user_id: str) -> None:
    if not can_read(extra, user_id, default_owner=DEFAULT_WIKI_OWNER):
        raise HTTPException(status_code=403, detail="Access denied")


def _ensure_can_write_extra(extra: dict[str, Any], user_id: str) -> None:
    if not can_write(extra, user_id, default_owner=DEFAULT_WIKI_OWNER):
        raise HTTPException(status_code=403, detail="Only owner can update this wiki page")


def _review_page_path(item: Any) -> Path:
    target = getattr(item, "target", None)
    target_path = target.page_path if isinstance(target, WikiPageRevisionReviewTarget) else ""
    item_path = str(getattr(item, "page_path", "") or "")
    if target_path and item_path.replace("\\", "/") != target_path:
        raise ValueError("review item target path does not match its page path")
    page_path = Path(target_path or item_path)
    if not page_path.as_posix() or page_path.is_absolute() or ".." in page_path.parts:
        raise ValueError("review item has no valid wiki page bound")
    return page_path


def _ensure_review_item_permission(item: Any, current_user: str) -> None:
    target = getattr(item, "target", None)
    if not isinstance(target, WikiPageRevisionReviewTarget):
        if getattr(item, "kind", None) == ReviewItemKind.draft:
            raise ValueError("legacy draft review item has no version-bound target; recreate the candidate")
        if current_user != DEFAULT_WIKI_OWNER:
            raise HTTPException(status_code=403, detail="Only the local owner can decide this review item")
        return
    if not target.page_id:
        raise ValueError("legacy page review target has no stable page identity; recreate the candidate")

    page_path = _review_page_path(item)
    slug = page_path.stem
    from literature_assistant.core.wiki.service import get_wiki_service

    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise ValueError(f"target page not found: {slug}")
    expected_path = Path(page.kind.value) / f"{page.stable_slug}.md"
    if expected_path.as_posix() != page_path.as_posix():
        raise ValueError("review item page path does not match the target page")
    if page.stable_slug != target.page_id:
        raise ValueError("review item stable page identity does not match the target page")
    _ensure_can_write_extra(page.extra, current_user)


def _prepare_review_promotion_intent(
    item: Any,
    current_user: str,
    *,
    request_id: str,
    expected_item_revision: str,
    request_fingerprint: str,
    reason: str,
) -> ReviewPromotionIntent | None:
    """Build a deterministic page-promotion intent without writing the page.

    Raises:
        ValueError: If the review item points at a page that cannot be promoted.
    """
    target = getattr(item, "target", None)
    if not isinstance(target, WikiPageRevisionReviewTarget):
        if getattr(item, "kind", None) == ReviewItemKind.draft:
            raise ValueError("legacy draft review item has no version-bound target; recreate the candidate")
        return None
    if not target.page_id:
        raise ValueError("legacy page review target has no stable page identity; recreate the candidate")
    page_path = _review_page_path(item)
    slug = page_path.stem
    from literature_assistant.core.wiki.service import get_wiki_service

    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise ValueError(f"target page not found: {slug}")
    expected_path = Path(page.kind.value) / f"{page.stable_slug}.md"
    if expected_path.as_posix() != page_path.as_posix():
        raise ValueError("review item page path does not match the target page")
    if page.stable_slug != target.page_id:
        raise ValueError("review target stable page identity changed; recreate the candidate")
    _ensure_can_write_extra(page.extra, current_user)
    original_content = service.page_store.read_page(page_path)
    if original_content is None:
        raise ValueError(f"target page not found: {page_path.as_posix()}")
    before_content_hash = _wiki_content_hash(str(original_content))
    if before_content_hash != target.expected_content_hash:
        raise ValueError("review target page revision changed; refresh and recreate the candidate")
    if page.status.value != target.expected_status:
        raise ValueError("review target page status changed; refresh and recreate the candidate")
    promoted_at = utc_now_iso()
    try:
        _updated_page, replacement = service.preview_page_status_update_by_path(
            page_path,
            expected_page_id=target.page_id,
            expected_status=target.expected_status,
            status=WikiPageStatus.final.value,
            expected_current_hash=target.expected_content_hash,
            updated_at_iso=promoted_at,
        )
    except ValueError as exc:
        raise ValueError(f"promotion planning failed: {exc}") from exc
    return ReviewPromotionIntent(
        operation_id=uuid4().hex,
        review_item_id=str(getattr(item, "item_id", "") or ""),
        request_id=request_id,
        expected_item_revision=expected_item_revision,
        request_fingerprint=request_fingerprint,
        reason=reason.strip(),
        target=target,
        before_content_hash=before_content_hash,
        after_content_hash=_wiki_content_hash(replacement),
        previous_status=page.status.value,
        promoted_status=WikiPageStatus.final.value,
        promoted_at=promoted_at,
        promoted_by=current_user,
    )


def _promote_review_target_to_final(
    item: Any,
    current_user: str,
    *,
    intent: ReviewPromotionIntent,
) -> ReviewPromotionReceipt:
    """Apply or resume a durable promotion intent and repair its version audit."""

    target = getattr(item, "target", None)
    if not isinstance(target, WikiPageRevisionReviewTarget):
        raise ValueError("review item has no page revision target to promote")
    if getattr(item, "promotion_intent", None) != intent:
        raise ValueError("review item promotion intent changed; refresh before deciding")
    if intent.review_item_id != str(getattr(item, "item_id", "") or ""):
        raise ValueError("promotion intent review item does not match")
    if intent.target != target:
        raise ValueError("promotion intent target does not match the queued candidate")
    if intent.promoted_by != current_user:
        raise ValueError("promotion intent belongs to a different reviewer")

    page_path = _review_page_path(item)
    from literature_assistant.core.wiki.service import get_wiki_service

    service = get_wiki_service()
    page = service.get_page(target.page_id)
    if page is None:
        raise ValueError(f"target page not found: {target.page_id}")
    expected_path = Path(page.kind.value) / f"{page.stable_slug}.md"
    if expected_path.as_posix() != page_path.as_posix():
        raise ValueError("review item page path does not match the target page")
    _ensure_can_write_extra(page.extra, current_user)
    current_content = service.page_store.read_page(page_path)
    if current_content is None:
        raise ValueError(f"target page not found: {page_path.as_posix()}")
    current_hash = _wiki_content_hash(str(current_content))

    if current_hash == intent.before_content_hash:
        try:
            service.update_page_status_by_path(
                page_path,
                expected_page_id=target.page_id,
                expected_status=intent.previous_status,
                status=intent.promoted_status,
                action="review_promote",
                expected_current_hash=intent.before_content_hash,
                updated_at_iso=intent.promoted_at,
                operation_id=intent.operation_id,
            )
        except ValueError as exc:
            raise ValueError(f"promotion to final failed: {exc}") from exc
        current_content = service.page_store.read_page(page_path)
        if current_content is None:
            raise ValueError(f"promoted page could not be read: {page_path.as_posix()}")
        current_hash = _wiki_content_hash(str(current_content))

    if current_hash != intent.after_content_hash:
        raise ValueError("review target page changed outside the pending promotion")
    try:
        service.ensure_page_version_by_path(
            page_path,
            expected_page_id=target.page_id,
            expected_status=intent.promoted_status,
            expected_current_hash=intent.after_content_hash,
            action="review_promote",
            operation_id=intent.operation_id,
        )
    except ValueError as exc:
        raise ValueError(f"promotion version repair failed: {exc}") from exc
    return intent.to_receipt()


def _review_item_allowed_actions(
    item: Any,
) -> list[Literal["approve", "reject", "withdraw"]]:
    if getattr(item, "status", None) != ReviewItemStatus.pending:
        return []
    if getattr(item, "promotion_intent", None) is not None:
        return ["approve", "withdraw"]
    target = getattr(item, "target", None)
    if getattr(item, "kind", None) == ReviewItemKind.draft and not isinstance(
        target,
        WikiPageRevisionReviewTarget,
    ):
        return ["reject"]
    if isinstance(target, WikiPageRevisionReviewTarget) and not target.page_id:
        return ["reject"]
    return ["approve", "reject"]


def _wiki_review_item_payload(item: Any) -> WikiReviewItemPayload:
    payload = dict(item.to_dict())
    payload["allowed_actions"] = _review_item_allowed_actions(item)
    return WikiReviewItemPayload(**payload)


def _decide_annotation_review_item(
    queue: ReviewQueue,
    item: Any,
    request: WikiReviewDecisionRequest,
    current_user: str,
    *,
    status: ReviewItemStatus,
) -> Any:
    """CAS-revalidate and record an annotation-only review decision."""

    target = getattr(item, "target", None)
    if not isinstance(target, AnnotationNoteReviewTarget):
        raise TypeError("item must have an annotation note review target")
    if not request.request_id:
        raise HTTPException(
            status_code=422,
            detail="review request_id is required for an annotation note",
        )
    if request.expected_target_content_hash is None:
        raise HTTPException(
            status_code=422,
            detail="expected_target_content_hash is required for an annotation note",
        )
    if request.expected_target_content_hash != target.expected_content_hash:
        raise ValueError("review target revision does not match the queued annotation note")
    action = "approve" if status == ReviewItemStatus.approved else "reject"
    request_fingerprint = _wiki_review_request_fingerprint(
        action=action,
        item_id=str(getattr(item, "item_id", "") or ""),
        reason=request.reason,
        decided_by=current_user,
        request_id=request.request_id,
        expected_item_revision=request.expected_item_revision,
        expected_target_content_hash=request.expected_target_content_hash,
    )
    if getattr(item, "status", None) == ReviewItemStatus.pending:
        if request.expected_item_revision != getattr(item, "item_revision", None):
            raise ValueError("review item revision changed; refresh before deciding")
        _validate_live_annotation_review_target(target, decision=True)
    return queue.decide_once(
        str(getattr(item, "item_id", "") or ""),
        status=status,
        reason=request.reason,
        decided_by=current_user,
        request_id=request.request_id,
        expected_item_revision=request.expected_item_revision,
        request_fingerprint=request_fingerprint,
    )


def _permissions_response(permissions: WikiPagePermissions) -> WikiPagePermissionsResponse:
    return WikiPagePermissionsResponse(
        owner=permissions.owner,
        visibility=permissions.visibility.value,
        shared_with=list(permissions.shared_with),
    )


class _AuthorizedWikiPageStore(WikiPageStore):
    """Read-only page store view that hides pages the current user cannot read."""

    def __init__(self, page_store: WikiPageStore, user_id: str) -> None:
        super().__init__(page_store.wiki_root, create=False)
        self._user_id = user_id

    def read_page(self, relative_path: Path) -> str | None:
        content = super().read_page(relative_path)
        if content is None:
            return None
        frontmatter, _body = _split_frontmatter(str(content))
        if not can_read(_frontmatter_extra(frontmatter), self._user_id, default_owner=DEFAULT_WIKI_OWNER):
            return None
        return content

    def list_pages(self, kind_dir: str | None = None) -> list[Path]:
        return [page_path for page_path in super().list_pages(kind_dir) if self.read_page(page_path) is not None]


class _ReviewedWikiPageStore(_AuthorizedWikiPageStore):
    """Read-only page store view for published knowledge surfaces.

    Drafts that still wait in the human review queue are hidden from page
    lists, search indexes, graph exports, and Markdown exports.
    """

    def read_page(self, relative_path: Path) -> str | None:
        content = super().read_page(relative_path)
        if content is None:
            return None
        frontmatter, _body = _split_frontmatter(str(content))
        if str(frontmatter.get("status") or "").strip().lower() == WikiPageStatus.archived.value:
            return None
        if _is_unfinalized_review_draft(frontmatter):
            return None
        return content


def _authorized_page_store(user_id: str) -> WikiPageStore:
    return _AuthorizedWikiPageStore(_page_store(create=False), user_id)


def _reviewed_page_store(user_id: str) -> WikiPageStore:
    return _ReviewedWikiPageStore(_page_store(create=False), user_id)


def _is_unfinalized_review_draft(frontmatter: dict[str, Any]) -> bool:
    """Return true for draft pages that must stay hidden until review approval."""

    if not isinstance(frontmatter, dict):
        return False
    if str(frontmatter.get("status") or "").strip().lower() != WikiPageStatus.draft.value:
        return False
    extra = _frontmatter_extra(frontmatter)
    return str(extra.get("entry_source") or "").strip() in {"manual_frontend", "local_markdown_import"}


@router.post("/import", response_model=WikiImportResponse)
def wiki_import(
    request: WikiImportRequest,
    user_id: str | None = Query(default=None),
) -> WikiImportResponse:
    """Import local Markdown files into private wiki pages.

    The endpoint accepts only local `.md` paths inside the configured workspace
    roots so a browser caller cannot use the API as a general filesystem reader.
    """
    if not wiki_enabled():
        return WikiImportResponse(
            enabled=False,
            dry_run=request.dry_run,
            confirm_write=request.confirm_write,
            warnings=_disabled_warning(),
        )

    if not request.source_paths:
        raise HTTPException(status_code=400, detail="source_paths cannot be empty")
    if len(request.source_paths) > _MAX_WIKI_IMPORT_FILES:
        raise HTTPException(status_code=400, detail=f"source_paths cannot contain more than {_MAX_WIKI_IMPORT_FILES} files")
    if not request.dry_run and not request.confirm_write:
        raise HTTPException(
            status_code=400,
            detail="confirm_write=true is required when dry_run=false for local wiki import",
        )

    current_user = _current_wiki_user(user_id)
    try:
        page_kind = WikiPageKind(request.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid wiki page kind: {request.kind}") from exc
    try:
        page_status = WikiPageStatus(request.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid wiki page status: {request.status}") from exc

    from literature_assistant.core.wiki.service import get_wiki_service

    service = get_wiki_service()
    pages: list[WikiImportItemPayload] = []
    imported = 0
    skipped = 0
    errored = 0
    total_bytes = 0

    for raw_path in request.source_paths:
        source_label = str(raw_path)
        review_item_id = ""
        runtime_refs: dict[str, str] = {}
        try:
            source_path = _resolve_wiki_import_source(raw_path)
            source_label = _safe_import_source_label(source_path)
            source_bytes = source_path.read_bytes()
            total_bytes += len(source_bytes)
            if total_bytes > _MAX_WIKI_IMPORT_TOTAL_BYTES:
                raise ValueError(f"Markdown import batch exceeds {_MAX_WIKI_IMPORT_TOTAL_BYTES} bytes")
            content = source_bytes.decode("utf-8")
            frontmatter, raw_body = _split_frontmatter(content)
            body = _strip_wiki_auto_markers(raw_body)
            if not body:
                raise ValueError("Markdown source body cannot be empty")
            title = _markdown_import_title(source_path, frontmatter, body)
            slug = make_stable_slug(title, page_kind)
            relative_path = (Path(page_kind.value) / f"{slug}.md").as_posix()
            existing_page = service.get_page(slug)
            if existing_page is not None and not request.overwrite:
                skipped += 1
                pages.append(
                    WikiImportItemPayload(
                        source_path=source_label,
                        title=title,
                        kind=page_kind.value,
                        status=page_status.value,
                        slug=slug,
                        path=relative_path,
                        action="skipped_exists",
                        warnings=["A wiki page with this slug already exists; set overwrite=true to update it."],
                    )
                )
                continue
            if request.dry_run:
                skipped += 1
                pages.append(
                    WikiImportItemPayload(
                        source_path=source_label,
                        title=title,
                        kind=page_kind.value,
                        status=page_status.value,
                        slug=slug,
                        path=relative_path,
                        action="planned_update" if existing_page is not None else "planned_create",
                    )
                )
                continue
            content_hash = hashlib.sha256(source_bytes).hexdigest()
            extra = _wiki_import_extra(source_path, content_hash, current_user)
            forced_status = WikiPageStatus.draft.value
            requested_status = page_status.value
            if existing_page is None:
                page = service.create_page(
                    title=title,
                    kind=page_kind.value,
                    body=body,
                    status=forced_status,
                    source_hashes=[content_hash],
                    extra=extra,
                )
                action = "created"
            else:
                _ensure_can_write_extra(existing_page.extra, current_user)
                page = service.update_page(
                    slug=slug,
                    title=title,
                    body=body,
                    status=forced_status,
                    source_hashes=[content_hash],
                    extra=extra,
                )
                action = "updated"
            page_path = (Path(page.kind.value) / f"{page.stable_slug}.md").as_posix()
            rendered_content = WikiPageStore(wiki_generated_root(), create=False).read_page(Path(page_path))
            if rendered_content is not None:
                _frontmatter, rendered_body = _split_frontmatter(str(rendered_content))
                ref_content = _strip_wiki_auto_markers(rendered_body)
                knowledge_ref = _wiki_knowledge_ref_payload(
                    page_path=page_path,
                    source_hash=hashlib.sha256(str(rendered_content).encode("utf-8")).hexdigest(),
                    content=ref_content,
                    import_source_hash=content_hash,
                )
            else:
                knowledge_ref = {
                    "import_source_hash": content_hash,
                    "source_hash": "",
                    "content_hash": hashlib.sha256((page.body or body).encode("utf-8")).hexdigest(),
                    "ref_id": f"wiki:{page_path}",
                    "chunk_id": "",
                    "read_endpoint": f"/api/agent-bridge/resource/wiki:{page_path}",
                    "span_start": 0,
                    "span_end": len(page.body or body),
                }
            source_vault_sync: dict[str, str] = {
                "source_registry_id": "",
                "source_vault_source_id": "",
                "source_vault_chunk_id": "",
                "source_vault_ref_id": "",
                "source_vault_read_endpoint": "",
                "source_vault_status": "",
                "source_vault_error": "",
            }
            try:
                review_item_id = _append_wiki_draft_review_item(
                    item_prefix="import",
                    page_slug=page.stable_slug,
                    page_kind=page.kind.value,
                    title=page.title,
                    body=page.body or "",
                    source="local_markdown_import",
                    metadata={
                        "entry_source": "local_markdown_import",
                        "requested_status": requested_status,
                        "kind": page.kind.value,
                        "owner": current_user,
                        "source_path": source_label,
                        "sha256": content_hash,
                        "action": action,
                        "dry_run_required_first": True,
                        "approval_surface": "wiki_review_queue",
                        "runtime_action_family": "wiki_candidate",
                        "workflow_passport": {
                            "stage_id": "wiki_candidate",
                            "requires_user_confirmation": True,
                            "source_ref": {
                                "source_kind": "wiki_page_draft",
                                "source_id": f"{page.kind.value}/{page.stable_slug}.md",
                            },
                        },
                        "evidence_integrity_gate": {
                            "status": "block",
                            "blocking_claim_id": "wiki_import_review_approval",
                            "requires_user_confirmation": True,
                            "safe_probe": "/api/wiki/review?status=pending&kind=draft",
                        },
                        "agent_handoff_recovery": {
                            "resume_tool": "literature.wiki_import",
                            "review_queue_probe": "/api/wiki/review?status=pending&kind=draft",
                            "forbidden_actions": [
                                "direct_zotero_db_write",
                                "external_upload",
                                "auto_approve_import",
                            ],
                        },
                    },
                )
            except (ValueError, OSError) as exc:
                rollback_error = _rollback_wiki_import_governance(
                    service=service,
                    action=action,
                    page=page,
                    existing_page=existing_page,
                )
                rollback_status = "rollback attempt failed" if rollback_error is not None else "wiki page mutation was rolled back"
                raise ValueError(f"Failed to create pending import review entry; {rollback_status}: {exc}") from exc
            try:
                runtime_refs = _record_wiki_import_runtime_action(
                    page=page,
                    review_item_id=review_item_id,
                    source_label=source_label,
                    content_hash=content_hash,
                    action=action,
                    owner=current_user,
                    requested_status=requested_status,
                )
            except (ValueError, OSError, TypeError, RuntimeError) as exc:
                rollback_error = _rollback_wiki_import_governance(
                    service=service,
                    action=action,
                    page=page,
                    existing_page=existing_page,
                    review_item_id=review_item_id,
                )
                rollback_status = "rollback attempt failed" if rollback_error is not None else "wiki page mutation was rolled back"
                raise ValueError(f"Failed to create pending import runtime action; {rollback_status}: {exc}") from exc
            if rendered_content is not None:
                try:
                    source_vault_sync = _source_vault_sync_from_import(
                        source_path=source_path,
                        source_label=source_label,
                        source_hash=content_hash,
                        source_text=content,
                        chunk_text=ref_content,
                        title=title,
                        page_path=page_path,
                    )
                except (ValueError, OSError, TypeError, RuntimeError) as exc:
                    rollback_error = _rollback_wiki_import_governance(
                        service=service,
                        action=action,
                        page=page,
                        existing_page=existing_page,
                        review_item_id=review_item_id,
                    )
                    rollback_status = "rollback attempt failed" if rollback_error is not None else "wiki page mutation was rolled back"
                    raise ValueError(f"Failed to sync import into Source Vault; {rollback_status}: {exc}") from exc
                if source_vault_sync["source_vault_status"] != "mirrored":
                    rollback_error = _rollback_wiki_import_governance(
                        service=service,
                        action=action,
                        page=page,
                        existing_page=existing_page,
                        review_item_id=review_item_id,
                    )
                    rollback_status = "rollback attempt failed" if rollback_error is not None else "wiki page mutation was rolled back"
                    detail = source_vault_sync["source_vault_error"] or source_vault_sync["source_vault_status"]
                    raise ValueError(f"Failed to sync import into Source Vault; {rollback_status}: {detail}") from None
            imported += 1
            pages.append(
                WikiImportItemPayload(
                    source_path=source_label,
                    source_registry_id=source_vault_sync["source_registry_id"],
                    import_source_hash=content_hash,
                    source_hash=str(knowledge_ref["source_hash"]),
                    content_hash=str(knowledge_ref["content_hash"]),
                    ref_id=str(knowledge_ref["ref_id"]),
                    chunk_id=str(knowledge_ref["chunk_id"]),
                    read_endpoint=str(knowledge_ref["read_endpoint"]),
                    source_vault_source_id=source_vault_sync["source_vault_source_id"],
                    source_vault_chunk_id=source_vault_sync["source_vault_chunk_id"],
                    source_vault_ref_id=source_vault_sync["source_vault_ref_id"],
                    source_vault_read_endpoint=source_vault_sync["source_vault_read_endpoint"],
                    source_vault_status=source_vault_sync["source_vault_status"],
                    span_start=int(knowledge_ref["span_start"]),
                    span_end=int(knowledge_ref["span_end"]),
                    title=title,
                    kind=page.kind.value,
                    status=page.status.value,
                    slug=page.stable_slug,
                    path=page_path,
                    action=action,
                    review_item_id=review_item_id,
                    runtime_session_id=runtime_refs["runtime_session_id"],
                    runtime_job_id=runtime_refs["runtime_job_id"],
                    runtime_approval_id=runtime_refs["runtime_approval_id"],
                )
            )
        except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError, RuntimeError) as exc:
            errored += 1
            pages.append(WikiImportItemPayload(source_path=source_label, action="error", error=str(exc)))

    return WikiImportResponse(
        enabled=True,
        dry_run=request.dry_run,
        confirm_write=request.confirm_write,
        imported=imported,
        skipped=skipped,
        errored=errored,
        pages=pages,
    )


@router.post("/import/okf/inspect", response_model=WikiOkfInspectResponse)
def wiki_okf_import_inspect(request: WikiOkfInspectRequest) -> WikiOkfInspectResponse:
    """Inspect a local OKF zip archive without importing or mutating wiki pages."""

    if not wiki_enabled():
        return WikiOkfInspectResponse(enabled=False, warnings=_disabled_warning())

    from literature_assistant.core.wiki.export import inspect_okf_bundle_archive

    try:
        archive_path = _resolve_wiki_import_archive(request.archive_path)
        source_label = _safe_import_source_label(archive_path)
        inspection = dict(inspect_okf_bundle_archive(archive_path))
        inspection["archive_path"] = source_label
        return WikiOkfInspectResponse(
            enabled=True,
            dry_run=True,
            archive_path=source_label,
            inspection=inspection,
            warnings=["Read-only inspection completed; no wiki pages, Zotero data, or external services were modified."],
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status", response_model=WikiStatusResponse)
def wiki_status(user_id: str | None = Query(default=None)) -> WikiStatusResponse:
    enabled = wiki_enabled()
    current_user = _current_wiki_user(user_id)
    store = _reviewed_page_store(current_user)
    pages = store.list_pages() if store.wiki_root.exists() else []
    page_count = len(pages) if enabled else 0
    # The query index is rebuilt from the full generated wiki source set. The
    # user-facing page_count remains permission/review-filtered, but integrity
    # must use the same full source set as rebuilds and doctor diagnostics.
    stale, stale_warnings, integrity = _status_integrity(
        store,
        page_count,
        enabled=enabled,
        integrity_store=_page_store(create=False),
    )
    warnings = stale_warnings if enabled else _disabled_warning()
    return WikiStatusResponse(
        enabled=enabled,
        page_count=page_count,
        stale=stale,
        integrity_status=str(integrity["integrity_status"]),
        index_hash=str(integrity["index_hash"]),
        source_manifest_hash=str(integrity["source_manifest_hash"]),
        indexed_source_manifest_hash=str(integrity["indexed_source_manifest_hash"]),
        indexed_page_count=int(integrity["indexed_page_count"]),
        source_page_count=integrity["source_page_count"] if isinstance(integrity["source_page_count"], int) else None,
        manifest_drilldown=WikiManifestDrilldownPayload(**integrity["manifest_drilldown"]),
        graph_json_exists=wiki_graph_path().exists(),
        graph_db_exists=wiki_graph_db_path().exists(),
        query_index_exists=wiki_query_index_path().exists(),
        review_queue_exists=wiki_review_queue_path().exists(),
        paths={
            "wiki_root": _sanitize_status_path(store.wiki_root),
            "graph_json": _sanitize_status_path(wiki_graph_path()),
            "graph_db": _sanitize_status_path(wiki_graph_db_path()),
            "query_index": _sanitize_status_path(wiki_query_index_path()),
            "review_queue": _sanitize_status_path(wiki_review_queue_path()),
        },
        warnings=warnings,
    )


def _wiki_revalidation_response(
    status: WikiStatusResponse,
    *,
    applied: bool = False,
    message: str = "",
) -> WikiRevalidationResponse:
    can_apply = bool(
        status.enabled
        and status.stale
        and status.source_manifest_hash not in {"", "none", "unknown"}
    )
    return WikiRevalidationResponse(
        enabled=status.enabled,
        stale=status.stale,
        can_apply=can_apply,
        applied=applied,
        integrity_status=status.integrity_status,
        source_manifest_hash=status.source_manifest_hash,
        indexed_source_manifest_hash=status.indexed_source_manifest_hash,
        source_page_count=status.source_page_count,
        indexed_page_count=status.indexed_page_count,
        manifest_drilldown=status.manifest_drilldown,
        warnings=list(status.warnings),
        message=message,
    )


@router.post("/revalidation/preflight", response_model=WikiRevalidationResponse)
def wiki_revalidation_preflight(
    user_id: str | None = Query(default=None),
) -> WikiRevalidationResponse:
    """Inspect Wiki source/index drift without writing pages or index state."""

    return _wiki_revalidation_response(
        wiki_status(user_id),
        message="Revalidation preflight completed without writes.",
    )


@router.post("/revalidation/apply", response_model=WikiRevalidationResponse)
def wiki_revalidation_apply(
    request: WikiRevalidationApplyRequest,
    user_id: str | None = Query(default=None),
) -> WikiRevalidationResponse:
    """Rebuild the query index after an explicit manifest-hash CAS check."""

    status_before = wiki_status(user_id)
    if not status_before.enabled:
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Revalidation apply requires explicit confirmation")
    expected_hash = request.expected_source_manifest_hash.strip()
    if expected_hash != status_before.source_manifest_hash:
        raise HTTPException(status_code=409, detail="Wiki source manifest changed after preflight")
    if not status_before.stale:
        return _wiki_revalidation_response(
            status_before,
            message="Wiki query index is already aligned; no rebuild was needed.",
        )

    source_store = _page_store(create=False)
    index = WikiQueryIndex(wiki_query_index_path())
    try:
        build_wiki_index(source_store, index)
    finally:
        index.close()
    status_after = wiki_status(user_id)
    if status_after.stale:
        raise HTTPException(status_code=409, detail="Wiki query index remained stale after rebuild")
    return _wiki_revalidation_response(
        status_after,
        applied=True,
        message="Wiki query index revalidated against the current source manifest.",
    )


@router.post("/compile", response_model=WikiCompileResponse)
def wiki_compile(request: WikiCompileRequest) -> WikiCompileResponse:
    if not wiki_enabled():
        return WikiCompileResponse(
            enabled=False,
            dry_run=request.dry_run,
            budget_summary=_empty_compile_budget_summary(),
            warnings=_disabled_warning(),
        )
    source_id = _normalize_identifier(request.source_id, "source_id")
    project_id = _normalize_identifier(request.project_id, "project_id")
    if not request.dry_run and not request.allow_write:
        raise HTTPException(status_code=400, detail="Non-dry-run wiki compile requires allow_write=true")
    registry_path = wiki_runtime_db_path()
    if not registry_path.exists():
        return WikiCompileResponse(
            enabled=True,
            dry_run=True,
            budget_summary=_empty_compile_budget_summary(),
            warnings=[
                "Wiki registry database is not available; run source registration or migration dry-run before compile planning."
            ],
        )
    registry = WikiRegistry(registry_path)
    compiler = WikiCompiler(registry, _dry_run_page_store(), observability_sink=default_wiki_observability_sink())
    if source_id:
        result = compiler.compile_source(source_id, dry_run=request.dry_run)
        planned_paths = _planned_paths_for_source(registry, source_id)
    else:
        result = compiler.compile_project(dry_run=request.dry_run)
        planned_paths = _planned_paths_for_project(compiler)
    warnings = [
        "Compile dry-run completed without writing wiki pages."
        if request.dry_run
        else "Compile write completed; generated wiki pages were written to the workspace wiki root."
    ]
    if project_id:
        warnings.append("project_id is accepted for forward compatibility; current compile planning is registry/source based.")
    warnings.extend(result.errors)
    return WikiCompileResponse(
        enabled=True,
        dry_run=request.dry_run,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        planned_paths=planned_paths,
        written_paths=_written_paths_for_compile(planned_paths, request.dry_run),
        budget_summary=result.cost_estimate.to_dict(),
        budget_checks=[check.to_dict() for check in result.budget_checks],
        errors=list(result.errors),
        warnings=warnings,
    )


@router.post("/query", response_model=WikiQueryResponse)
def wiki_query(request: WikiQueryRequest, user_id: str | None = Query(default=None)) -> WikiQueryResponse:
    """Wiki query endpoint (legacy name, use /search instead)."""
    return _wiki_search_impl(request, _current_wiki_user(user_id))


@router.post("/search", response_model=WikiQueryResponse)
def wiki_search(request: WikiQueryRequest, user_id: str | None = Query(default=None)) -> WikiQueryResponse:
    """Wiki search endpoint (G5 2026-05-26, canonical name for /query)."""
    return _wiki_search_impl(request, _current_wiki_user(user_id))


def _wiki_search_impl(request: WikiQueryRequest, user_id: str) -> WikiQueryResponse:
    """Shared implementation for /query and /search endpoints."""
    if not wiki_enabled():
        return WikiQueryResponse(
            enabled=False,
            fallback_required=True,
            warnings=_disabled_warning(),
        )
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query cannot be empty")
    if request.save:
        raise HTTPException(status_code=400, detail="Saved exploration API requires explicit service integration")
    index_path = wiki_query_index_path()
    sink = default_wiki_observability_sink()
    if not index_path.exists():
        sink.emit_event("wiki.query.fallback_required", {"reason": "missing_index", "query": query})
        return WikiQueryResponse(
            enabled=True,
            fallback_required=True,
            warnings=["Wiki query index is not available; call the main RAG chain for raw-corpus fallback."],
        )
    index = WikiQueryIndex(index_path, observability_sink=sink)
    readable_store = _reviewed_page_store(user_id)
    try:
        with sink.start_span("wiki.router.query", {"wiki_first": request.wiki_first, "debug": request.debug}):
            result = wiki_query_with_fallback(
                query,
                index,
                readable_store,
                enabled=True,
                limit=5,
                expand_links=True,
                max_linked=3,
            )
        hits = [
            hit
            for hit in [*result.wiki_hits, *result.linked_hits]
            if readable_store.read_page(hit.page_path) is not None
        ]
        sink.emit_event(
            "wiki.query.completed",
            {
                "query": query,
                "wiki_hits": len(result.wiki_hits),
                "linked_hits": len(result.linked_hits),
                "fallback_required": result.fallback_used,
                "fallback_reason": result.fallback_reason,
            },
            status="warning" if result.fallback_used else "ok",
        )
        sink.record_metric("wiki.query.router.evidence_refs", len(hits), {"fallback_required": result.fallback_used})
        warnings: list[str] = []
        fallback_required = result.fallback_used or not hits
        if result.fallback_used:
            warnings.append(f"Wiki query returned no usable hits: {result.fallback_reason}.")
            warnings.append("Call the main RAG chain for raw-corpus fallback.")
        elif not hits:
            warnings.append("Wiki query returned only pages outside the current user's permissions.")
            warnings.append("Call the main RAG chain for raw-corpus fallback.")
        knowledge_refs = build_knowledge_refs(hits, readable_store)
        return WikiQueryResponse(
            enabled=True,
            fallback_required=fallback_required,
            answer="" if fallback_required else "Wiki evidence is available; use evidence_refs for grounded context.",
            evidence_refs=[ref.to_hit(include_content=False) for ref in knowledge_refs],
            warnings=warnings,
        )
    except Exception as exc:
        sink.emit_event("wiki.query.failed", {"query": query, "error": type(exc).__name__}, status="error")
        return WikiQueryResponse(
            enabled=True,
            fallback_required=True,
            warnings=[f"Wiki query failed; call the main RAG chain for raw-corpus fallback: {type(exc).__name__}"],
        )
    finally:
        index.close()


@router.get("/pages", response_model=WikiPageListResponse)
def wiki_pages(
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
) -> WikiPageListResponse:
    if not wiki_enabled():
        return WikiPageListResponse(enabled=False, pages=[])
    current_user = _current_wiki_user(user_id)
    store = _reviewed_page_store(current_user)
    kind_filter = _normalize_filter_token(kind, "kind")
    status_filter = _normalize_filter_token(status, "status")
    pages: list[WikiPageSummaryPayload] = []
    for page_path in store.list_pages():
        content = store.read_page(page_path)
        if not content:
            continue
        summary = _parse_page_content(page_path, content)
        if kind_filter is not None and not _kind_matches_filter(summary, kind_filter):
            continue
        if status_filter is not None and summary.status.strip().lower() != status_filter:
            continue
        pages.append(summary)
    return WikiPageListResponse(enabled=True, pages=pages)


@router.get("/categories", response_model=WikiCategoriesResponse)
def wiki_categories(user_id: str | None = Query(default=None)) -> WikiCategoriesResponse:
    """Return a read-only category tree derived from readable wiki pages."""
    if not wiki_enabled():
        return WikiCategoriesResponse(enabled=False, categories=[])
    current_user = _current_wiki_user(user_id)
    store = _reviewed_page_store(current_user)
    entries: list[tuple[list[str], WikiPageSummaryPayload]] = []
    for page_path in store.list_pages():
        content = store.read_page(page_path)
        if not content:
            continue
        frontmatter, _body = _split_frontmatter(content)
        summary = _parse_page_content(page_path, content)
        entries.append((_category_values(frontmatter, summary), summary))
    return WikiCategoriesResponse(enabled=True, categories=_build_category_tree(entries))


@router.get("/tags", response_model=WikiTagsResponse)
def wiki_tags(user_id: str | None = Query(default=None)) -> WikiTagsResponse:
    """Return a read-only tag index derived from readable wiki pages."""
    if not wiki_enabled():
        return WikiTagsResponse(enabled=False, tags=[])
    current_user = _current_wiki_user(user_id)
    store = _reviewed_page_store(current_user)
    entries: list[tuple[list[str], WikiPageSummaryPayload]] = []
    for page_path in store.list_pages():
        content = store.read_page(page_path)
        if not content:
            continue
        frontmatter, _body = _split_frontmatter(content)
        tag_values = _tag_values(frontmatter)
        if not tag_values:
            continue
        entries.append((tag_values, _parse_page_content(page_path, content)))
    return WikiTagsResponse(enabled=True, tags=_build_tag_index(entries))


@router.get("/pages/{slug}/permissions", response_model=WikiPagePermissionsResponse)
def get_wiki_page_permissions(slug: str, user_id: str | None = Query(default=None)) -> WikiPagePermissionsResponse:
    """Get permissions for a wiki page (G14 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from literature_assistant.core.wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    _ensure_can_read_extra(page.extra, current_user)
    return _permissions_response(get_permissions(page.extra, default_owner=DEFAULT_WIKI_OWNER))


@router.put("/pages/{slug}/permissions", response_model=WikiPagePermissionsResponse)
def update_wiki_page_permissions(
    slug: str,
    request: WikiPagePermissionsRequest,
    user_id: str | None = Query(default=None),
) -> WikiPagePermissionsResponse:
    """Update permissions for a wiki page (G14 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from literature_assistant.core.wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    _ensure_can_write_extra(page.extra, current_user)

    try:
        visibility = WikiPageVisibility(request.visibility)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid visibility: {request.visibility}") from exc
    try:
        shared_with = normalize_shared_with(request.shared_with)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    current_perms = get_permissions(page.extra, default_owner=DEFAULT_WIKI_OWNER)
    new_perms = WikiPagePermissions(
        owner=current_perms.owner,
        visibility=visibility,
        shared_with=shared_with,
    )

    new_extra = set_permissions(page.extra, new_perms)
    service.update_page_extra(slug, new_extra)
    return _permissions_response(new_perms)


@router.get("/pages/{slug}/versions", response_model=WikiPageVersionsResponse)
def wiki_page_versions(slug: str, user_id: str | None = Query(default=None)) -> WikiPageVersionsResponse:
    """Return local version metadata for one wiki page."""
    if not wiki_enabled():
        return WikiPageVersionsResponse(enabled=False, slug=slug, versions=[])

    from literature_assistant.core.wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")
    _ensure_can_read_extra(page.extra, current_user)
    return WikiPageVersionsResponse(
        enabled=True,
        slug=slug,
        versions=[WikiPageVersionPayload(**item) for item in service.list_page_versions(slug)],
    )


@router.get("/pages/{slug}/retention")
def wiki_page_retention(slug: str, user_id: str | None = Query(default=None)) -> dict[str, Any]:
    """Read a page's persisted archive/restore receipt and current CAS hash."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from literature_assistant.core.wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    page = service.get_page(slug, include_archived=True)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")
    _ensure_can_read_extra(page.extra, current_user)
    retention = service.get_page_retention(slug)
    if not isinstance(retention, dict):
        raise HTTPException(status_code=404, detail=f"Page has no retention receipt: {slug}")
    return retention


@router.post("/pages/{slug}/restore", response_model=WikiPageMutationResponse)
def wiki_page_restore(
    slug: str,
    request: WikiPageRestoreRequest,
    user_id: str | None = Query(default=None),
) -> WikiPageMutationResponse:
    """Restore an archived page with explicit receipt and content CAS."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from literature_assistant.core.wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    try:
        page = service.get_page(slug, include_archived=True)
        if page is None:
            raise ValueError(f"Page not found: {slug}")
        _ensure_can_write_extra(page.extra, current_user)
        restored = service.restore_page(
            slug,
            expected_archive_receipt_id=request.archive_receipt_id,
            expected_current_hash=request.expected_current_hash,
            restored_by=current_user,
        )
    except PageRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    retention = service.get_page_retention(slug)
    restore_receipt = retention.get("restore_receipt") if isinstance(retention, dict) else None
    receipt_id = restore_receipt.get("receipt_id") if isinstance(restore_receipt, dict) else None
    current_hash = retention.get("current_content_hash") if isinstance(retention, dict) else None
    return WikiPageMutationResponse(
        success=True,
        slug=restored.stable_slug,
        status=restored.status.value,
        receipt_id=str(receipt_id) if receipt_id else None,
        current_content_hash=str(current_hash) if current_hash else None,
        message=f"Page restored: {restored.stable_slug}",
    )


@router.get("/pages/{page_path:path}", response_model=WikiPageReadResponse)
def wiki_page_read(page_path: str, user_id: str | None = Query(default=None)) -> WikiPageReadResponse:
    if not wiki_enabled():
        return WikiPageReadResponse(enabled=False, path=page_path)
    current_user = _current_wiki_user(user_id)
    relative_path = _normalize_page_path(page_path)
    content = _page_store(create=False).read_page(relative_path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {page_path}")
    frontmatter, body = _split_frontmatter(content)
    if str(frontmatter.get("status") or "").strip().lower() == WikiPageStatus.archived.value:
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {page_path}")
    _ensure_can_read_extra(_frontmatter_extra(frontmatter), current_user)
    return WikiPageReadResponse(
        enabled=True,
        path=relative_path.as_posix(),
        frontmatter=frontmatter,
        body=body,
    )


@router.post("/pages", response_model=WikiPageMutationResponse)
def wiki_page_create(
    request: WikiPageCreateRequest,
    user_id: str | None = Query(default=None),
) -> WikiPageMutationResponse:
    """Create a new wiki page (G2 2026-05-26).

    Capture flow (2026-06-14): every page created through this endpoint is
    forced to ``draft`` status and surfaced as a pending review-queue item.
    Final pages can only be produced by approving the review item, never by
    the capture caller asking for ``status=final`` directly.
    """
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from literature_assistant.core.wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    capture_extra = {key: value for key, value in request.extra.items() if key != PERMISSIONS_KEY}
    capture_extra.setdefault("entry_source", "manual_frontend")
    page_extra = set_permissions(
        capture_extra,
        WikiPagePermissions(owner=current_user, visibility=WikiPageVisibility.PRIVATE),
    )
    # 捕获入口不再相信 caller 提的 status：所有从 /pages POST 来的写入都先落 draft。
    # 真正升级到 final 必须通过 /review/{id}/approve。requested_status 留存在 review
    # metadata 里，供审核界面区分用户是「随手记」还是「想直接沉淀」。
    requested_status = request.status
    forced_status = WikiPageStatus.draft.value

    service = get_wiki_service()
    try:
        evidence_refs = [from_evidence_reference(ref) for ref in request.evidence_refs]
        page = service.create_page(
            title=request.title,
            kind=request.kind,
            body=request.body,
            status=forced_status,
            evidence_refs=evidence_refs,
            source_hashes=request.source_hashes,
            extra=page_extra,
        )
    except ValueError as exc:
        detail = str(exc)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    # 把这条草稿挂到 ReviewQueue 当待确认条目。失败就回滚刚创建的 page，
    # 避免「页面有了但收件箱没有」的半成功状态。
    try:
        capture_metadata: dict[str, Any] = {
            "entry_source": request.extra.get("entry_source") or "manual_frontend",
            "requested_status": requested_status,
            "kind": page.kind.value,
            "owner": current_user,
        }
        _append_wiki_draft_review_item(
            item_prefix="capture",
            page_slug=page.stable_slug,
            page_kind=page.kind.value,
            title=page.title,
            body=page.body or "",
            source="capture",
            metadata=capture_metadata,
        )
    except (ValueError, OSError) as exc:
        try:
            service.purge_page(page.stable_slug)
        except (ValueError, OSError):
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create pending review entry; draft was rolled back: {exc}",
        ) from exc

    return WikiPageMutationResponse(
        success=True,
        slug=page.stable_slug,
        message=f"Page saved as draft pending review: {page.stable_slug}",
    )


@router.put("/pages/{slug}", response_model=WikiPageMutationResponse)
def wiki_page_update(
    slug: str,
    request: WikiPageUpdateRequest,
    user_id: str | None = Query(default=None),
) -> WikiPageMutationResponse:
    """Update an existing wiki page (G2 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from literature_assistant.core.wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    try:
        existing_page = service.get_page(slug)
        if existing_page is None:
            raise ValueError(f"Page not found: {slug}")
        _ensure_can_write_extra(existing_page.extra, current_user)
        if request.status == WikiPageStatus.final.value:
            raise HTTPException(
                status_code=409,
                detail="Page status can become final only through an explicit review approval.",
            )
        merged_extra = None
        if request.extra is not None:
            current_permissions = get_permissions(existing_page.extra, default_owner=DEFAULT_WIKI_OWNER)
            merged_extra = dict(existing_page.extra)
            merged_extra.update({key: value for key, value in request.extra.items() if key != PERMISSIONS_KEY})
            merged_extra = set_permissions(merged_extra, current_permissions)
        evidence_refs = (
            [from_evidence_reference(ref) for ref in request.evidence_refs]
            if request.evidence_refs is not None
            else None
        )
        page = service.update_page(
            slug=slug,
            title=request.title,
            body=request.body,
            status=request.status,
            evidence_refs=evidence_refs,
            source_hashes=request.source_hashes,
            extra=merged_extra,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return WikiPageMutationResponse(
        success=True,
        slug=page.stable_slug,
        message=f"Page updated: {page.stable_slug}",
    )


@router.delete("/pages/{slug}", response_model=WikiPageMutationResponse)
def wiki_page_delete(
    slug: str,
    expected_current_hash: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
) -> WikiPageMutationResponse:
    """Archive a wiki page while retaining its file and receipt."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from literature_assistant.core.wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    try:
        existing_page = service.get_page(slug)
        if existing_page is None:
            raise ValueError(f"Page not found: {slug}")
        _ensure_can_write_extra(existing_page.extra, current_user)
        if expected_current_hash is None and user_id is None:
            archived = service.delete_page(slug)
        else:
            archived = service.delete_page(
                slug,
                expected_current_hash=expected_current_hash,
                archived_by=current_user,
            )
    except PageRevisionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    retention = service.get_page_retention(slug)
    archive_receipt = retention.get("archive_receipt") if isinstance(retention, dict) else None
    receipt_id = archive_receipt.get("receipt_id") if isinstance(archive_receipt, dict) else None
    current_hash = retention.get("current_content_hash") if isinstance(retention, dict) else None
    return WikiPageMutationResponse(
        success=True,
        slug=slug,
        status=archived.status.value if hasattr(archived, "status") else WikiPageStatus.archived.value,
        receipt_id=str(receipt_id) if receipt_id else None,
        current_content_hash=str(current_hash) if current_hash else None,
        message=f"Page archived: {slug}",
    )


@router.get("/doctor", response_model=WikiDoctorResponse)
def wiki_doctor(user_id: str | None = Query(default=None)) -> WikiDoctorResponse:
    if not wiki_enabled():
        return WikiDoctorResponse(enabled=False, report={"warnings": _disabled_warning()})
    current_user = _current_wiki_user(user_id)
    return WikiDoctorResponse(enabled=True, report=_doctor(_authorized_page_store(current_user)).run().to_dict())


@router.post("/export", response_model=WikiExportResponse)
def wiki_export(
    output_path: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    format: str = Query(default="markdown"),
) -> WikiExportResponse:
    """Export wiki pages as a local Markdown or OKF-compatible zip archive.

    Args:
        output_path: Optional safe output zip filename. Markdown exports use
            ``workspace_artifacts/wiki_exports`` for compatibility; OKF exports
            use ``workspace_artifacts/generated/output/wiki-okf``.
        user_id: Local wiki user whose readable pages are exported.
        format: ``markdown`` for the existing raw page archive or ``okf`` for
            Scholar AI's OKF-compatible profile bundle.

    Returns:
        WikiExportResponse with success/page_count/output_path/errors
    """
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from literature_assistant.core.wiki.export import export_wiki_markdown, export_wiki_okf_bundle

    current_user = _current_wiki_user(user_id)
    normalized_format = str(format or "markdown").strip().lower()
    if normalized_format not in {"markdown", "okf"}:
        raise HTTPException(status_code=400, detail="format must be markdown or okf")
    resolved_output_path = (
        _resolve_wiki_okf_export_path(output_path)
        if normalized_format == "okf"
        else _resolve_wiki_export_path(output_path)
    )

    page_store = _reviewed_page_store(current_user)
    if normalized_format == "okf":
        result = export_wiki_okf_bundle(page_store, resolved_output_path)
    else:
        result = export_wiki_markdown(page_store, resolved_output_path)

    if not result["success"]:
        raise HTTPException(status_code=500, detail={"errors": result["errors"]})

    return WikiExportResponse(**result)


@router.post("/export/project-okf", response_model=WikiProjectOkfExportResponse)
def wiki_project_okf_export(request: WikiProjectOkfExportRequest) -> WikiProjectOkfExportResponse:
    """Export explicit process artifact records into a local OKF zip bundle."""

    if not wiki_enabled():
        return WikiProjectOkfExportResponse(enabled=False, warnings=_disabled_warning())

    from literature_assistant.core.wiki.export import export_project_artifact_okf_bundle

    resolved_output_path = _resolve_project_okf_export_path(request.output_path)
    records_by_group = request.records_by_group()
    pre_export_warnings: list[str] = []
    if request.include_live_project_records:
        try:
            live_records, live_warnings = _collect_live_project_okf_records(
                request.project_id or "",
                max_records=request.max_live_records,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Project not found: {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        pre_export_warnings.extend(live_warnings)
        for group, records in live_records.items():
            records_by_group[group] = [*records_by_group[group], *records]

    export_records_by_group: Mapping[
        str,
        list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    ] = {
        group: list(records)
        for group, records in records_by_group.items()
    }
    try:
        result = export_project_artifact_okf_bundle(
            export_records_by_group,
            resolved_output_path,
            project_id=request.project_id,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result["success"]:
        raise HTTPException(status_code=500, detail={"errors": result["errors"]})

    result = dict(result)
    result["warnings"] = [*pre_export_warnings, *list(result.get("warnings", []))]
    return WikiProjectOkfExportResponse(enabled=True, **result)


@router.get("/graph", response_model=WikiGraphResponse)
def wiki_graph(user_id: str | None = Query(default=None)) -> WikiGraphResponse:
    if not wiki_enabled():
        return WikiGraphResponse(enabled=False, graph={})
    current_user = _current_wiki_user(user_id)
    snapshot = build_wiki_graph(_reviewed_page_store(current_user))
    return WikiGraphResponse(enabled=True, graph=snapshot.to_dict())


_GRAPH_REVIEW_RELATION_FIELDS = (
    "related",
    "related_to",
    "related_pages",
    "links",
    "concepts",
    "claims",
    "sources",
    "source_pages",
    "source_ids",
    "source_papers",
    "key_papers",
    "derived_from",
    "depends_on",
    "supports",
    "contradicts",
    "extends",
    "cites",
)
_GRAPH_REVIEW_EVIDENCE_TEXT_KEYS = ("text", "quote", "compressed_text", "content", "source")


def _normalize_graph_review_evidence_refs(raw_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    if not isinstance(raw_refs, list):
        raise HTTPException(status_code=400, detail="evidence_refs must be a list")
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, Mapping):
            raise HTTPException(status_code=400, detail="evidence_refs must contain objects")
        ref: dict[str, Any] = {}
        material_id = _normalize_review_text(
            str(raw_ref.get("material_id") or ""),
            field_name="material_id",
            max_length=240,
        )
        if material_id and material_id.startswith("<"):
            material_id = None
        if material_id:
            ref["material_id"] = material_id
        chunk_id = _normalize_review_text(
            str(raw_ref.get("chunk_id") or ""),
            field_name="chunk_id",
            max_length=240,
        )
        if chunk_id and chunk_id.startswith("<"):
            chunk_id = None
        if chunk_id:
            ref["chunk_id"] = chunk_id
        page = raw_ref.get("page")
        if isinstance(page, bool):
            page = None
        if isinstance(page, int) and page > 0:
            ref["page"] = page
        elif isinstance(page, str) and page.strip().isdigit() and int(page.strip()) > 0:
            ref["page"] = int(page.strip())
        elif isinstance(page, str) and page.strip():
            ref["page"] = _normalize_review_text(page, field_name="page", max_length=80)
        for key in _GRAPH_REVIEW_EVIDENCE_TEXT_KEYS:
            value = _normalize_review_text(
                str(raw_ref.get(key) or ""),
                field_name=key,
                max_length=2_000,
            )
            if value and not value.startswith("<"):
                ref[key] = value
        source_labels = raw_ref.get("source_labels")
        if isinstance(source_labels, list):
            labels: list[str] = []
            for raw_label in source_labels:
                label = _normalize_review_text(
                    str(raw_label or ""),
                    field_name="source_labels",
                    max_length=80,
                )
                if label and label not in labels:
                    labels.append(label)
            if labels:
                ref["source_labels"] = labels[:8]
        bbox = raw_ref.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            numeric_bbox = [float(value) for value in bbox[:4] if isinstance(value, (int, float)) and not isinstance(value, bool)]
            if len(numeric_bbox) == 4:
                ref["bbox"] = numeric_bbox
                bbox_unit = _normalize_review_text(
                    str(raw_ref.get("bbox_unit") or ""),
                    field_name="bbox_unit",
                    max_length=40,
                )
                if bbox_unit:
                    ref["bbox_unit"] = bbox_unit
        if not any(ref.get(key) for key in ("material_id", "chunk_id", "text", "quote", "source")):
            raise HTTPException(status_code=400, detail="evidence_refs must include material_id, chunk_id, text, quote, or source")
        refs.append(ref)
    if not refs:
        raise HTTPException(status_code=400, detail="evidence_refs cannot be empty")
    return [dict(item) for item in _dedupe_json_values(refs) if isinstance(item, Mapping)]


def _source_ref_from_review_evidence(ref: Mapping[str, Any]) -> dict[str, Any] | None:
    material_id = str(ref.get("material_id") or "").strip()
    if not material_id:
        return None
    source_ref: dict[str, Any] = {"material_id": material_id}
    if ref.get("page") is not None:
        source_ref["page"] = ref.get("page")
    if str(ref.get("chunk_id") or "").strip():
        source_ref["chunk_id"] = str(ref.get("chunk_id") or "").strip()
    if ref.get("bbox") is not None and ref.get("bbox_unit") is not None:
        source_ref["bbox"] = ref.get("bbox")
        source_ref["bbox_unit"] = ref.get("bbox_unit")
    return source_ref


def _first_review_source_ref(refs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ref in refs:
        source_ref = _source_ref_from_review_evidence(ref)
        if source_ref is not None:
            return source_ref
    return None


def _edge_review_field(edge: WikiGraphReviewEdgeInput) -> str:
    raw_field = str(edge.frontmatter_field or "").strip()
    if raw_field in _GRAPH_REVIEW_RELATION_FIELDS:
        return raw_field
    relation = str(edge.relation or "").strip()
    if relation in _GRAPH_REVIEW_RELATION_FIELDS:
        return relation
    return "related"


def _strip_wikilink_target(value: str) -> str:
    text = value.strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2].split("|", 1)[0].strip()
    return text


def _target_candidates(value: str, target_path: str | None = None) -> set[str]:
    text = _strip_wikilink_target(value)
    path_text = _strip_wikilink_target(target_path or "")
    candidates = {item for item in {text, path_text} if item}
    for item in list(candidates):
        path = Path(item)
        candidates.add(path.with_suffix("").as_posix())
        candidates.add(path.name)
        candidates.add(path.with_suffix("").name)
        if not item.endswith(".md"):
            candidates.add(f"{item}.md")
    return {item.strip() for item in candidates if item.strip()}


def _relation_item_target(raw_item: Any) -> str | None:
    if isinstance(raw_item, Mapping):
        raw_target = raw_item.get("target") or raw_item.get("to") or raw_item.get("id") or raw_item.get("page")
        return str(raw_target).strip() if raw_target is not None else None
    if isinstance(raw_item, str):
        return _strip_wikilink_target(raw_item)
    return None


def _relation_item_matches_edge(raw_item: Any, edge: WikiGraphReviewEdgeInput) -> bool:
    target = _relation_item_target(raw_item)
    if not target:
        return False
    return bool(_target_candidates(target) & _target_candidates(edge.target, edge.target_path))


def _relation_evidence_text(refs: list[dict[str, Any]]) -> str:
    for ref in refs:
        for key in ("text", "quote", "source"):
            value = str(ref.get(key) or "").strip()
            if value:
                return value[:500]
    return "graph_review_evidence"


def _relation_item_with_evidence(
    raw_item: Any,
    edge: WikiGraphReviewEdgeInput,
    evidence_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(raw_item, Mapping):
        item = dict(raw_item)
    else:
        item = {
            "target": _relation_item_target(raw_item) or edge.target,
            "type": str(edge.relation or "related_to").strip() or "related_to",
        }
    item.setdefault("target", edge.target)
    item.setdefault("type", str(edge.relation or "related_to").strip() or "related_to")
    _merge_frontmatter_list(item, "evidence_refs", evidence_refs)
    source_ref = _first_review_source_ref(evidence_refs)
    if source_ref is not None:
        item["source_ref"] = source_ref
        item.setdefault("material_id", source_ref["material_id"])
        if source_ref.get("page") is not None:
            item.setdefault("page", source_ref.get("page"))
        if source_ref.get("chunk_id") is not None:
            item.setdefault("chunk_id", source_ref.get("chunk_id"))
    if not str(item.get("evidence") or "").strip():
        item["evidence"] = _relation_evidence_text(evidence_refs)
    return item


def _apply_graph_review_disambiguation(
    request: WikiGraphReviewApplyRequest,
    *,
    current_user: str,
) -> WikiGraphReviewApplyResponse:
    operation_id = uuid4().hex
    updated_at = utc_now_iso()
    store = _page_store(create=False)
    pages = _read_graph_review_pages(store, request.nodes, current_user)
    changed_paths: set[str] = set()

    for node in request.nodes:
        node_id = _validate_review_node_id(node.node_id)
        relative_path = _normalize_page_path(node.page_path)
        page_key = relative_path.as_posix()
        page_path, _content, frontmatter, _body = pages[page_key]
        label = _normalize_review_text(node.label, field_name="label", max_length=240)
        disambiguation = _normalize_review_text(
            node.disambiguation,
            field_name="disambiguation",
            max_length=2_000,
        )
        if label is None and disambiguation is None:
            continue
        if label is not None:
            frontmatter["title"] = label
        extra, review = _graph_review_extra(frontmatter)
        if disambiguation is not None:
            extra["disambiguation"] = disambiguation
        review.update(
            {
                "last_operation_id": operation_id,
                "last_operation_kind": "disambiguate_nodes",
                "disambiguated_at": updated_at,
                "disambiguated_node_id": node_id,
                "disambiguated_page_path": page_path.as_posix(),
                "decided_by": request.decided_by.strip() or "user",
            }
        )
        extra["graph_review"] = review
        frontmatter["extra"] = extra
        frontmatter["updated_at_iso"] = updated_at
        changed_paths.add(page_key)

    if not changed_paths:
        raise HTTPException(status_code=400, detail="no disambiguation changes were provided")

    for page_key in sorted(changed_paths):
        relative_path, _content, frontmatter, body = pages[page_key]
        _write_frontmatter_preserving_body(store, relative_path, frontmatter, body)

    snapshots = _graph_review_undo_snapshots(store, pages)
    _rebuild_review_graph(current_user)
    return WikiGraphReviewApplyResponse(
        enabled=True,
        operation_id=operation_id,
        operation_kind="disambiguate_nodes",
        updated_page_paths=sorted(changed_paths),
        snapshots=snapshots,
        message=f"已保存 {len(changed_paths)} 个节点的消歧信息。",
    )


def _apply_graph_review_merge(
    request: WikiGraphReviewApplyRequest,
    *,
    current_user: str,
) -> WikiGraphReviewApplyResponse:
    operation_id = uuid4().hex
    updated_at = utc_now_iso()
    keep_node_id = _validate_review_node_id(request.keep_node_id or "", "keep_node_id")
    merge_node_ids = [
        _validate_review_node_id(node_id, "merge_node_ids")
        for node_id in request.merge_node_ids
    ]
    merge_node_ids = [node_id for node_id in dict.fromkeys(merge_node_ids) if node_id != keep_node_id]
    if not merge_node_ids:
        raise HTTPException(status_code=400, detail="merge_node_ids must include at least one node different from keep_node_id")

    node_by_id = {_validate_review_node_id(node.node_id): node for node in request.nodes}
    missing = [node_id for node_id in [keep_node_id, *merge_node_ids] if node_id not in node_by_id]
    if missing:
        raise HTTPException(status_code=400, detail=f"nodes are missing page_path for: {', '.join(missing)}")

    store = _page_store(create=False)
    pages = _read_graph_review_pages(
        store,
        [node_by_id[node_id] for node_id in [keep_node_id, *merge_node_ids]],
        current_user,
    )

    keep_path = _normalize_page_path(node_by_id[keep_node_id].page_path)
    keep_key = keep_path.as_posix()
    _keep_relative_path, _keep_content, keep_frontmatter, _keep_body = pages[keep_key]
    merged_page_paths: list[str] = []
    merged_titles: list[str] = []
    merged_ids: list[str] = []

    for node_id in merge_node_ids:
        node = node_by_id[node_id]
        merge_path = _normalize_page_path(node.page_path)
        merge_key = merge_path.as_posix()
        if merge_key == keep_key:
            continue
        _merge_relative_path, _merge_content, merge_frontmatter, _merge_body = pages[merge_key]
        merged_page_paths.append(merge_key)
        merged_ids.append(node_id)
        title = str(merge_frontmatter.get("title") or node.label or node_id).strip()
        if title:
            merged_titles.append(title)
        _merge_frontmatter_list(keep_frontmatter, "evidence_refs", _as_json_list(merge_frontmatter.get("evidence_refs")))
        _merge_frontmatter_list(keep_frontmatter, "source_hashes", _as_json_list(merge_frontmatter.get("source_hashes")))
        for field_name in _GRAPH_REVIEW_RELATION_FIELDS:
            _merge_frontmatter_list(keep_frontmatter, field_name, _as_json_list(merge_frontmatter.get(field_name)))

        merge_extra, merge_review = _graph_review_extra(merge_frontmatter)
        merge_review.update(
            {
                "last_operation_id": operation_id,
                "last_operation_kind": "merge_duplicate_nodes",
                "merged_at": updated_at,
                "merged_into": keep_key,
                "merged_into_node_id": keep_node_id,
                "merged_node_id": node_id,
                "decided_by": request.decided_by.strip() or "user",
            }
        )
        merge_extra["graph_review"] = merge_review
        merge_frontmatter["extra"] = merge_extra
        merge_frontmatter["updated_at_iso"] = updated_at

    if not merged_page_paths:
        raise HTTPException(status_code=400, detail="merge_node_ids do not resolve to distinct wiki pages")

    keep_extra, keep_review = _graph_review_extra(keep_frontmatter)
    keep_review.update(
        {
            "last_operation_id": operation_id,
            "last_operation_kind": "merge_duplicate_nodes",
            "merged_at": updated_at,
            "keep_node_id": keep_node_id,
            "merged_node_ids": _dedupe_json_values([*_as_json_list(keep_review.get("merged_node_ids")), *merged_ids]),
            "merged_page_paths": _dedupe_json_values([*_as_json_list(keep_review.get("merged_page_paths")), *merged_page_paths]),
            "decided_by": request.decided_by.strip() or "user",
        }
    )
    keep_extra["graph_review"] = keep_review
    keep_extra["aliases"] = _dedupe_json_values([*_as_json_list(keep_extra.get("aliases")), *merged_titles, *merged_ids])
    keep_frontmatter["extra"] = keep_extra
    _merge_frontmatter_list(keep_frontmatter, "aliases", [*merged_titles, *merged_ids])
    keep_frontmatter["updated_at_iso"] = updated_at

    changed_paths = {keep_key, *merged_page_paths}
    for page_key in sorted(changed_paths):
        relative_path, _content, frontmatter, body = pages[page_key]
        _write_frontmatter_preserving_body(store, relative_path, frontmatter, body)

    snapshots = _graph_review_undo_snapshots(store, pages)
    _rebuild_review_graph(current_user)
    return WikiGraphReviewApplyResponse(
        enabled=True,
        operation_id=operation_id,
        operation_kind="merge_duplicate_nodes",
        updated_page_paths=sorted(changed_paths),
        snapshots=snapshots,
        message=f"已合并 {len(merged_page_paths)} 个重复节点。",
    )


def _apply_graph_review_node_evidence(
    request: WikiGraphReviewApplyRequest,
    *,
    current_user: str,
) -> WikiGraphReviewApplyResponse:
    operation_id = uuid4().hex
    updated_at = utc_now_iso()
    evidence_refs = _normalize_graph_review_evidence_refs(request.evidence_refs)
    store = _page_store(create=False)
    pages = _read_graph_review_pages(store, request.nodes, current_user)
    changed_paths: set[str] = set()
    source_ref = _first_review_source_ref(evidence_refs)

    for node in request.nodes:
        node_id = _validate_review_node_id(node.node_id)
        relative_path = _normalize_page_path(node.page_path)
        page_key = relative_path.as_posix()
        page_path, _content, frontmatter, _body = pages[page_key]
        _merge_frontmatter_list(frontmatter, "evidence_refs", evidence_refs)
        if source_ref is not None:
            frontmatter["source_ref"] = source_ref
        extra, review = _graph_review_extra(frontmatter)
        review.update(
            {
                "last_operation_id": operation_id,
                "last_operation_kind": "add_node_evidence",
                "evidence_added_at": updated_at,
                "node_id": node_id,
                "page_path": page_path.as_posix(),
                "evidence_ref_count": len(evidence_refs),
                "decided_by": request.decided_by.strip() or "user",
            }
        )
        extra["graph_review"] = review
        frontmatter["extra"] = extra
        frontmatter["updated_at_iso"] = updated_at
        changed_paths.add(page_key)

    if not changed_paths:
        raise HTTPException(status_code=400, detail="nodes cannot be empty")

    for page_key in sorted(changed_paths):
        relative_path, _content, frontmatter, body = pages[page_key]
        _write_frontmatter_preserving_body(store, relative_path, frontmatter, body)

    snapshots = _graph_review_undo_snapshots(store, pages)
    _rebuild_review_graph(current_user)
    return WikiGraphReviewApplyResponse(
        enabled=True,
        operation_id=operation_id,
        operation_kind="add_node_evidence",
        updated_page_paths=sorted(changed_paths),
        snapshots=snapshots,
        message=f"已给 {len(changed_paths)} 个节点补充证据。",
    )


def _apply_graph_review_relation_evidence(
    request: WikiGraphReviewApplyRequest,
    *,
    current_user: str,
) -> WikiGraphReviewApplyResponse:
    operation_id = uuid4().hex
    updated_at = utc_now_iso()
    evidence_refs = _normalize_graph_review_evidence_refs(request.evidence_refs)
    if not request.edges:
        raise HTTPException(status_code=400, detail="edges cannot be empty")
    store = _page_store(create=False)
    changed_paths: set[str] = set()
    pages: dict[str, tuple[Path, str, dict[str, Any], str]] = {}

    for edge in request.edges:
        _validate_review_node_id(edge.source, "source")
        _validate_review_node_id(edge.target, "target")
        relative_path = _normalize_page_path(edge.source_path)
        page_key = relative_path.as_posix()
        if page_key not in pages:
            content = store.read_page(relative_path)
            if content is None:
                raise HTTPException(status_code=404, detail=f"Wiki page not found: {page_key}")
            frontmatter, body = _split_frontmatter(str(content))
            _ensure_can_write_extra(_frontmatter_extra(frontmatter), current_user)
            pages[page_key] = (relative_path, str(content), dict(frontmatter), body)

        page_path, _content, frontmatter, _body = pages[page_key]
        field_name = _edge_review_field(edge)
        raw_value = frontmatter.get(field_name)
        raw_items = _as_json_list(raw_value)
        changed = False
        next_items: list[Any] = []
        for raw_item in raw_items:
            if _relation_item_matches_edge(raw_item, edge):
                next_items.append(_relation_item_with_evidence(raw_item, edge, evidence_refs))
                changed = True
            else:
                next_items.append(raw_item)
        if not changed:
            next_items.append(_relation_item_with_evidence({}, edge, evidence_refs))
        frontmatter[field_name] = next_items
        extra, review = _graph_review_extra(frontmatter)
        review.update(
            {
                "last_operation_id": operation_id,
                "last_operation_kind": "add_relation_evidence",
                "evidence_added_at": updated_at,
                "edge_id": edge.edge_id,
                "source": edge.source,
                "target": edge.target,
                "relation": edge.relation,
                "source_path": page_path.as_posix(),
                "frontmatter_field": field_name,
                "evidence_ref_count": len(evidence_refs),
                "decided_by": request.decided_by.strip() or "user",
            }
        )
        extra["graph_review"] = review
        frontmatter["extra"] = extra
        frontmatter["updated_at_iso"] = updated_at
        changed_paths.add(page_key)

    for page_key in sorted(changed_paths):
        relative_path, _content, frontmatter, body = pages[page_key]
        _write_frontmatter_preserving_body(store, relative_path, frontmatter, body)

    snapshots = _graph_review_undo_snapshots(store, pages)
    _rebuild_review_graph(current_user)
    return WikiGraphReviewApplyResponse(
        enabled=True,
        operation_id=operation_id,
        operation_kind="add_relation_evidence",
        updated_page_paths=sorted(changed_paths),
        snapshots=snapshots,
        message=f"已给 {len(request.edges)} 条关系补充证据。",
    )


@router.post("/graph/review/apply", response_model=WikiGraphReviewApplyResponse)
def wiki_graph_review_apply(
    request: WikiGraphReviewApplyRequest,
    user_id: str | None = Query(default=None),
) -> WikiGraphReviewApplyResponse:
    """Apply a graph review operation to wiki page frontmatter with snapshots."""

    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")
    operation_kind = request.operation_kind.strip()
    current_user = _current_wiki_user(user_id)
    if operation_kind == "disambiguate_nodes":
        return _apply_graph_review_disambiguation(request, current_user=current_user)
    if operation_kind == "merge_duplicate_nodes":
        return _apply_graph_review_merge(request, current_user=current_user)
    if operation_kind == "add_node_evidence":
        return _apply_graph_review_node_evidence(request, current_user=current_user)
    if operation_kind == "add_relation_evidence":
        return _apply_graph_review_relation_evidence(request, current_user=current_user)
    raise HTTPException(status_code=400, detail=f"unsupported graph review operation: {operation_kind}")


@router.post("/graph/review/undo", response_model=WikiGraphReviewApplyResponse)
def wiki_graph_review_undo(
    request: WikiGraphReviewUndoRequest,
    user_id: str | None = Query(default=None),
) -> WikiGraphReviewApplyResponse:
    """Restore exact page snapshots returned by graph review apply."""

    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")
    operation_id = _normalize_review_text(
        request.operation_id,
        field_name="operation_id",
        max_length=128,
        required=True,
    )
    if not request.snapshots:
        raise HTTPException(status_code=400, detail="snapshots cannot be empty")
    current_user = _current_wiki_user(user_id)
    store = _page_store(create=False)
    restore_plan: list[tuple[Path, str, str]] = []
    restored_paths: list[str] = []
    seen_paths: set[str] = set()

    # Validate the complete restore set before touching any page so a single
    # stale page cannot leave a partially undone graph review operation.
    for snapshot in request.snapshots:
        relative_path = _normalize_page_path(snapshot.page_path)
        page_key = relative_path.as_posix()
        if page_key in seen_paths:
            raise HTTPException(status_code=400, detail=f"duplicate snapshot page: {page_key}")
        seen_paths.add(page_key)
        if _wiki_content_hash(snapshot.content) != snapshot.content_hash:
            raise HTTPException(status_code=400, detail=f"snapshot hash mismatch: {page_key}")
        frontmatter, _body = _split_frontmatter(snapshot.content)
        if not frontmatter:
            raise HTTPException(status_code=400, detail=f"snapshot is missing JSON frontmatter: {page_key}")
        _ensure_can_write_extra(_frontmatter_extra(frontmatter), current_user)
        current_content = store.read_page(relative_path)
        if current_content is None:
            raise HTTPException(status_code=409, detail=f"graph review page drifted or was removed: {page_key}")
        current_text = str(current_content)
        current_frontmatter, _current_body = _split_frontmatter(current_text)
        _ensure_can_write_extra(_frontmatter_extra(current_frontmatter), current_user)
        if _wiki_content_hash(current_text) != snapshot.expected_current_hash:
            raise HTTPException(status_code=409, detail=f"graph review page changed after apply: {page_key}")
        restore_plan.append((relative_path, snapshot.content, current_text))

    for relative_path, restore_content, _current_text in restore_plan:
        page_key = relative_path.as_posix()
        atomic_write_text(store.resolve(relative_path), restore_content)
        restored_paths.append(page_key)

    before_restore = [
        _snapshot_page(
            relative_path,
            current_text,
            expected_current_content=restore_content,
        )
        for relative_path, restore_content, current_text in restore_plan
    ]
    _rebuild_review_graph(current_user)
    return WikiGraphReviewApplyResponse(
        enabled=True,
        operation_id=operation_id or "",
        operation_kind=request.operation_kind.strip() or "undo_graph_review",
        updated_page_paths=sorted(dict.fromkeys(restored_paths)),
        snapshots=before_restore,
        message=f"已撤回 {len(restored_paths)} 个页面的图谱复审修改。",
    )


@router.get("/review", response_model=WikiReviewListResponse)
def wiki_review_list(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
) -> WikiReviewListResponse:
    if not wiki_enabled():
        return WikiReviewListResponse(enabled=False, items=[])
    normalized_status = _normalize_filter_token(status, "status")
    normalized_kind = _normalize_filter_token(kind, "kind")
    try:
        parsed_status = ReviewItemStatus(normalized_status) if normalized_status else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unsupported review status: {normalized_status}") from exc
    try:
        parsed_kind = ReviewItemKind(normalized_kind) if normalized_kind else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unsupported review kind: {normalized_kind}") from exc
    queue = ReviewQueue(wiki_review_queue_path())
    return WikiReviewListResponse(
        enabled=True,
        items=[_wiki_review_item_payload(item) for item in queue.list_items(status=parsed_status, kind=parsed_kind)],
    )


@router.post(
    "/review/annotations/enqueue",
    response_model=WikiReviewItemPayload,
)
def wiki_annotation_review_enqueue(
    request: WikiAnnotationReviewEnqueueRequest,
) -> WikiReviewItemPayload:
    """Submit one exact, explicitly authorized annotation note for review."""

    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")
    try:
        target = make_annotation_note_review_target(
            project_id=request.project_id,
            material_id=request.material_id,
            note_id=request.note_id,
            expected_updated_at=request.expected_updated_at,
            expected_content_hash=request.expected_content_hash,
        )
        enqueue_fingerprint = _annotation_review_enqueue_fingerprint(request)
        queue = ReviewQueue(wiki_review_queue_path())
        with queue.locked():
            for queued_item in queue.list_items():
                prior_request_id = str(
                    queued_item.metadata.get("annotation_enqueue_request_id") or ""
                )
                if prior_request_id != request.request_id:
                    continue
                prior_fingerprint = str(
                    queued_item.metadata.get("annotation_enqueue_request_fingerprint") or ""
                )
                if (
                    prior_fingerprint == enqueue_fingerprint
                    and queued_item.target == target
                    and queued_item.kind == ReviewItemKind.annotation_note
                ):
                    return _wiki_review_item_payload(queued_item)
                raise ValueError("annotation enqueue request_id was already used with different parameters")

            snapshot = _validate_live_annotation_review_target(target, decision=False)
            note = snapshot.get("note")
            if not isinstance(note, Mapping):
                raise ValueError("annotation note snapshot is invalid")
            page = note.get("page")
            summary_source = str(note.get("body") or note.get("anchor_text") or "").strip()
            summary = summary_source[:500]
            item = queue.append(
                make_review_item(
                    item_id=f"annotation-note-{uuid4().hex}",
                    kind=ReviewItemKind.annotation_note,
                    title=f"Annotation note · page {page}",
                    page_path=f"annotations/{target.material_id}/{target.note_id}",
                    summary=summary,
                    source="annotation",
                    metadata={
                        "annotation_enqueue_request_id": request.request_id,
                        "annotation_enqueue_request_fingerprint": enqueue_fingerprint,
                        "source_ref": f"annotation:{target.material_id}:{target.note_id}",
                    },
                    target=target,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _wiki_review_item_payload(item)


@router.post("/review/{item_id}/approve", response_model=WikiReviewItemPayload)
def wiki_review_approve(
    item_id: str,
    request: WikiReviewDecisionRequest,
    user_id: str | None = Query(default=None),
) -> WikiReviewItemPayload:
    """Approve a pending review item.

    Page approvals first persist a deterministic promotion intent. Replaying
    the same request can then finish either the page write or the queue commit
    after a process interruption without letting read-only routes mutate Wiki.
    """
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")
    current_user = _current_wiki_user(user_id)
    queue = ReviewQueue(wiki_review_queue_path())
    try:
        with queue.locked():
            existing = queue.get(item_id)
            if existing is None:
                raise KeyError(item_id)
            _ensure_review_item_permission(existing, current_user)
            target = existing.target
            if isinstance(target, AnnotationNoteReviewTarget):
                item = _decide_annotation_review_item(
                    queue,
                    existing,
                    request,
                    current_user,
                    status=ReviewItemStatus.approved,
                )
                return _wiki_review_item_payload(item)
            request_fingerprint = ""
            if isinstance(target, WikiPageRevisionReviewTarget):
                if not request.request_id:
                    raise HTTPException(status_code=422, detail="review request_id is required for a page revision")
                if request.expected_target_content_hash is None:
                    raise HTTPException(
                        status_code=422,
                        detail="expected_target_content_hash is required for a page revision",
                    )
                request_fingerprint = _wiki_review_request_fingerprint(
                    action="approve",
                    item_id=existing.item_id,
                    reason=request.reason,
                    decided_by=current_user,
                    request_id=request.request_id,
                    expected_item_revision=request.expected_item_revision,
                    expected_target_content_hash=request.expected_target_content_hash,
                )
                for queued_item in queue.list_items():
                    queued_receipt = (
                        queued_item.decision.promotion_receipt
                        if queued_item.decision is not None
                        else None
                    )
                    queued_intent = queued_item.promotion_intent
                    prior_request_id = (
                        queued_receipt.request_id
                        if queued_receipt is not None
                        else queued_intent.request_id if queued_intent is not None else ""
                    )
                    if prior_request_id != request.request_id:
                        continue
                    prior_fingerprint = (
                        queued_receipt.request_fingerprint
                        if queued_receipt is not None
                        else queued_intent.request_fingerprint if queued_intent is not None else ""
                    )
                    if (
                        queued_item.item_id == existing.item_id
                        and queued_item.status == ReviewItemStatus.approved
                        and prior_fingerprint == request_fingerprint
                    ):
                        return _wiki_review_item_payload(queued_item)
                    if (
                        queued_item.item_id == existing.item_id
                        and queued_item.status == ReviewItemStatus.pending
                        and queued_intent is not None
                        and prior_fingerprint == request_fingerprint
                    ):
                        continue
                    raise ValueError("review request_id was already used with different parameters")

            if request.expected_item_revision != existing.item_revision:
                raise ValueError("review item revision changed; refresh before deciding")

            if existing.status != ReviewItemStatus.pending:
                raise ValueError(f"review item is already decided: {existing.status.value}")

            if isinstance(target, WikiPageRevisionReviewTarget):
                if request.expected_target_content_hash != target.expected_content_hash:
                    raise ValueError("review target revision does not match the queued candidate")

                promotion_intent = existing.promotion_intent
                if promotion_intent is not None:
                    if (
                        promotion_intent.request_id != request.request_id
                        or promotion_intent.request_fingerprint != request_fingerprint
                        or promotion_intent.expected_item_revision != request.expected_item_revision
                    ):
                        raise ValueError("review item already has a different promotion request in progress")
                else:
                    promotion_intent = _prepare_review_promotion_intent(
                        existing,
                        current_user,
                        request_id=request.request_id,
                        expected_item_revision=request.expected_item_revision,
                        request_fingerprint=request_fingerprint,
                        reason=request.reason,
                    )
                    if promotion_intent is None:
                        raise ValueError("page revision review item could not create a promotion intent")
                    existing = queue.begin_or_resume_promotion(item_id, promotion_intent)
                    promotion_intent = existing.promotion_intent
                    if promotion_intent is None:
                        raise ValueError("promotion intent was not persisted")

                promotion_receipt = _promote_review_target_to_final(
                    existing,
                    current_user,
                    intent=promotion_intent,
                )
                item = queue.finalize_promotion(
                    item_id,
                    reason=request.reason,
                    decided_by=current_user,
                    receipt=promotion_receipt,
                )
            else:
                item = queue.approve(
                    item_id,
                    reason=request.reason,
                    decided_by=current_user,
                    promotion_receipt=None,
                )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Review item not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _wiki_review_item_payload(item)


@router.post(
    "/review/{item_id}/withdraw",
    response_model=WikiReviewPromotionWithdrawResponse,
)
def wiki_review_withdraw_promotion(
    item_id: str,
    request: WikiReviewPromotionWithdrawRequest,
    user_id: str | None = Query(default=None),
) -> WikiReviewPromotionWithdrawResponse:
    """Withdraw an unapplied page promotion without rejecting its candidate."""

    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")
    current_user = _current_wiki_user(user_id)
    queue = ReviewQueue(wiki_review_queue_path())
    try:
        with queue.locked():
            existing = queue.get(item_id)
            if existing is None:
                raise KeyError(item_id)

            prior_receipt = next(
                (
                    receipt
                    for receipt in existing.promotion_withdrawal_receipts
                    if receipt.expected_item_revision == request.expected_item_revision
                    and receipt.promotion_operation_id
                    == request.expected_promotion_operation_id
                ),
                None,
            )
            if prior_receipt is not None:
                replay_fingerprint = _wiki_review_request_fingerprint(
                    action="withdraw",
                    item_id=existing.item_id,
                    reason=request.reason,
                    decided_by=current_user,
                    request_id=request.expected_promotion_operation_id,
                    expected_item_revision=request.expected_item_revision,
                    expected_target_content_hash=prior_receipt.before_content_hash,
                )
                if replay_fingerprint != prior_receipt.withdrawal_request_fingerprint:
                    raise ValueError(
                        "promotion withdrawal was already completed with different parameters"
                    )
                if (
                    existing.status != ReviewItemStatus.pending
                    or existing.item_revision != prior_receipt.resulting_item_revision
                    or existing.promotion_intent is not None
                ):
                    raise ValueError(
                        "review item changed after the promotion withdrawal; refresh before continuing"
                    )
                _ensure_review_item_permission(existing, current_user)
                return WikiReviewPromotionWithdrawResponse(
                    item=_wiki_review_item_payload(existing),
                    withdrawal_receipt=WikiReviewPromotionWithdrawalReceiptPayload(
                        **prior_receipt.to_dict()
                    ),
                )

            _ensure_review_item_permission(existing, current_user)
            if existing.status != ReviewItemStatus.pending:
                raise ValueError(f"review item is already decided: {existing.status.value}")
            intent = existing.promotion_intent
            if intent is None:
                raise ValueError("review item has no promotion request to withdraw")
            if existing.item_revision != request.expected_item_revision:
                raise ValueError("review item revision changed; refresh before withdrawing")
            if intent.operation_id != request.expected_promotion_operation_id:
                raise ValueError("promotion operation changed; refresh before withdrawing")

            page_path = _review_page_path(existing)
            from literature_assistant.core.wiki.service import get_wiki_service

            service = get_wiki_service()
            current_content = service.page_store.read_page(page_path)
            if current_content is None:
                raise ValueError(f"target page not found: {page_path.as_posix()}")
            current_hash = _wiki_content_hash(str(current_content))
            if current_hash == intent.after_content_hash:
                raise ValueError(
                    "promotion was already applied to the page; retry the original approval"
                )
            if current_hash != intent.before_content_hash:
                raise ValueError(
                    "review target page changed outside the pending promotion withdrawal"
                )
            withdrawal_fingerprint = _wiki_review_request_fingerprint(
                action="withdraw",
                item_id=existing.item_id,
                reason=request.reason,
                decided_by=current_user,
                request_id=request.expected_promotion_operation_id,
                expected_item_revision=request.expected_item_revision,
                expected_target_content_hash=intent.before_content_hash,
            )
            item, receipt = queue.withdraw_promotion(
                item_id,
                expected_item_revision=request.expected_item_revision,
                expected_promotion_operation_id=request.expected_promotion_operation_id,
                observed_page_content_hash=current_hash,
                withdrawal_request_fingerprint=withdrawal_fingerprint,
                reason=request.reason,
                withdrawn_by=current_user,
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Review item not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WikiReviewPromotionWithdrawResponse(
        item=_wiki_review_item_payload(item),
        withdrawal_receipt=WikiReviewPromotionWithdrawalReceiptPayload(**receipt.to_dict()),
    )


@router.post("/review/{item_id}/reject", response_model=WikiReviewItemPayload)
def wiki_review_reject(
    item_id: str,
    request: WikiReviewDecisionRequest,
    user_id: str | None = Query(default=None),
) -> WikiReviewItemPayload:
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")
    current_user = _current_wiki_user(user_id)
    queue = ReviewQueue(wiki_review_queue_path())
    try:
        with queue.locked():
            existing = queue.get(item_id)
            if existing is None:
                raise KeyError(item_id)
            _ensure_review_item_permission(existing, current_user)
            if isinstance(existing.target, AnnotationNoteReviewTarget):
                item = _decide_annotation_review_item(
                    queue,
                    existing,
                    request,
                    current_user,
                    status=ReviewItemStatus.rejected,
                )
                return _wiki_review_item_payload(item)
            if request.expected_item_revision != existing.item_revision:
                raise ValueError("review item revision changed; refresh before deciding")
            if existing.promotion_intent is not None:
                raise ValueError(
                    "review item promotion request is in progress; retry the original approval"
                )
            item = queue.reject(
                item_id,
                reason=request.reason,
                decided_by=current_user,
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Review item not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _wiki_review_item_payload(item)
