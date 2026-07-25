# -*- coding: utf-8 -*-
"""Resources API Router - Manages projects, sections, drafts, and associations."""

import asyncio
import concurrent.futures as futures
import hashlib
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Callable
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from chunk_size_guard import hard_max_chars, hard_max_tokens, inspect_chunk
from chunk_hashing import compute_chunk_hashes, compute_chunk_store_version
from chunk_models import EnrichedChunk
from material_revision_sync import (
    build_material_revision_identity,
    serialize_ocr_revision_report,
    serialize_parser_provenance,
    synchronize_material_revision,
)
from pdf_backends import PDFParserProvenance
from pdf_backends.ocr_ingestion import OcrIngestionReport
from project_paths import output_path, project_data_path
from retrieval_gateway import retrieve_candidates
from models import (
    ProjectPayload,
    SectionPayload,
    MaterialPayload,
    FigureTableCandidatePayload,
    DraftPayload,
    RevisionPayload,
    ProjectExportPayload,
    WritingAssociationPayload,
    CreateProjectRequest,
    CreateSectionRequest,
    CreateMaterialRequest,
    CreateDraftRequest,
    SaveDraftRequest,
    BuildAssociationRequest,
    PaginatedResponse,
    PaginationMeta,
    paginate,
    MessageResponse,
)

logger = logging.getLogger("ResourcesRouter")
router = APIRouter(prefix="/resources", tags=["Resources"])
_ai_adapter_instance: Any | None = None
_ASYNC_UPLOAD_EXTENSIONS = {".pdf"}
_DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_MAX_UPLOAD_BYTES_ENV = "LITASSIST_MAX_UPLOAD_BYTES"
_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
_UPLOAD_MAGIC_PREFIX_BYTES = 4096
_ALLOWED_UPLOAD_EXTENSIONS = {
    ".bib",
    ".csv",
    ".docx",
    ".enw",
    ".ipynb",
    ".json",
    ".md",
    ".pdf",
    ".ris",
    ".txt",
}
_GENERIC_UPLOAD_MIME_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
}
_ALLOWED_UPLOAD_MIME_TYPES_BY_EXTENSION = {
    ".bib": {"application/x-bibtex", "text/plain", "text/x-bibtex"},
    ".csv": {"application/csv", "application/vnd.ms-excel", "text/csv", "text/plain"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
    ".enw": {"application/x-endnote-refer", "text/plain"},
    ".ipynb": {"application/json", "application/x-ipynb+json", "text/plain"},
    ".json": {"application/json", "text/json", "text/plain"},
    ".md": {"text/markdown", "text/plain", "text/x-markdown"},
    ".pdf": {"application/pdf", "application/x-pdf"},
    ".ris": {"application/x-research-info-systems", "text/plain"},
    ".txt": {"text/plain"},
}

# Document content store — default location (overridden when project has source_folder)
_DOC_STORE_DIR = output_path("doc_store")
_DOC_STORE_DIR.mkdir(parents=True, exist_ok=True)

# Chunk store — default location (overridden when project has source_folder)
_CHUNK_STORE_DIR = output_path("chunk_store")
_CHUNK_STORE_DIR.mkdir(parents=True, exist_ok=True)
_CHUNK_QUARANTINE_LOG_PATH = output_path("chunk_quarantine.jsonl")

# One re-entrant in-process lock guards doc/chunk publication. Cross-process
# serialization is added by the persistence helpers beside each project store.
_CHUNK_STORE_LOCK = threading.RLock()

# Sub-directory name used when storing data alongside literature files
_SCHOLAR_SUBDIR = ".scholarai"

# Chunking settings (learned from open-webui / quivr-core)
CHUNK_SIZE = 800       # chars per chunk
CHUNK_OVERLAP = 150    # overlap chars between adjacent chunks (reverted from 200 due to canary30 regression)
MAX_CHUNKS_PER_MATERIAL = 5  # max chunks returned per document in RAG search (reverted from 8 due to canary30 regression)

# Supported file extensions for folder scanning
_SCAN_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".bib", ".ipynb"}
_SCAN_SKIP_DIRS = {".scholarai", ".git", "node_modules", "__pycache__"}
_SCAN_MODES = {"legacy", "fast"}
_INGEST_MODES = {"none", "query", "full"}

_PROJECTS_DATA_ROOT = project_data_path("_anchor").parent
_TEST_PROJECT_TITLES = {
    "project chat grounding",
    "ragworkflow chat",
    "tolf bad env",
    "tolf chat grounding",
    "tolf fallback",
}


@dataclass(frozen=True)
class _UploadBatchContext:
    """Bounded correlation data shared by one upload request's file results."""

    batch_id: str
    submitted_at: str
    batch_index: int
    batch_total: int

    def __post_init__(self) -> None:
        if not isinstance(self.batch_id, str) or not re.fullmatch(
            r"batch_[A-Za-z0-9_-]{8,64}", self.batch_id
        ):
            raise ValueError("batch_id must use the bounded batch_<opaque> format")
        if not isinstance(self.submitted_at, str) or len(self.submitted_at) > 40:
            raise ValueError("submitted_at must be a bounded ISO-8601 string")
        try:
            parsed = datetime.fromisoformat(self.submitted_at)
        except ValueError as exc:
            raise ValueError("submitted_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError("submitted_at must be an explicit UTC timestamp")
        if isinstance(self.batch_index, bool) or not isinstance(self.batch_index, int):
            raise ValueError("batch_index must be an integer")
        if isinstance(self.batch_total, bool) or not isinstance(self.batch_total, int):
            raise ValueError("batch_total must be an integer")
        if self.batch_total < 1 or self.batch_total > 10000:
            raise ValueError("batch_total is out of bounds")
        if self.batch_index < 1 or self.batch_index > self.batch_total:
            raise ValueError("batch_index must be within batch_total")

    def to_result_fields(self) -> dict[str, Any]:
        """Return only safe correlation fields for a per-file response."""

        return {
            "batch_id": self.batch_id,
            "batch_index": self.batch_index,
            "batch_total": self.batch_total,
        }

    def to_job_metadata(self) -> dict[str, Any]:
        """Return safe correlation fields persisted on a runtime job."""

        return {
            **self.to_result_fields(),
            "submitted_at": self.submitted_at,
        }


def _validate_upload_batch_context(
    batch_context: _UploadBatchContext | None,
) -> _UploadBatchContext | None:
    """Reject unvalidated correlation objects before they reach response or job state."""

    if batch_context is not None and not isinstance(batch_context, _UploadBatchContext):
        raise TypeError("batch_context must be _UploadBatchContext")
    return batch_context


def _with_upload_batch_context(
    result: Mapping[str, Any],
    batch_context: _UploadBatchContext | None,
) -> dict[str, Any]:
    """Attach validated batch correlation fields when called from a batch route."""

    batch_context = _validate_upload_batch_context(batch_context)
    payload = dict(result)
    if batch_context is not None:
        payload.update(batch_context.to_result_fields())
    return payload


def _new_upload_batch_identity() -> tuple[str, str]:
    """Create one opaque identifier and UTC submission time for a batch request."""

    return f"batch_{uuid4().hex}", datetime.now(timezone.utc).isoformat()


def _get_project_source_folder(project_id: str) -> str:
    """Return the source_folder stored in the project's metadata (or empty string)."""
    try:
        from writing_resources import get_writing_resource_store
        store = get_writing_resource_store()
        project = store.get_project(project_id)
        if project:
            return str(project.metadata.get("source_folder", "")).strip()
    except Exception:
        pass
    return ""


def _resolve_data_dir(project_id: str) -> tuple[Path, Path]:
    """Return (doc_store_dir, chunk_store_dir) for a project.

    Default (post-0.1.8.1): one unified tree under
    ``<user_root>/projects/{safe_id}/{doc_store,chunk_store}/`` so every
    knowledge base lives in the same installed-app folder regardless of
    where the user's PDFs sit on disk. The previous layout, which scattered
    indexes into ``{source_folder}/.scholarai/`` alongside each library,
    is preserved behind ``LITASSIST_USE_SOURCE_FOLDER_INDEX=1`` for users
    who relied on that move-with-the-folder behaviour.

    Upgrading from <=0.1.8-alpha: see CHANGELOG 0.1.8.1 for the one-time
    manual move (``{source_folder}/.scholarai/*`` →
    ``<user_root>/projects/{safe_id}/``). The app does not auto-migrate.
    """
    use_legacy = os.environ.get("LITASSIST_USE_SOURCE_FOLDER_INDEX", "").strip() == "1"
    if use_legacy:
        source_folder = _get_project_source_folder(project_id)
        if source_folder:
            base = Path(source_folder).expanduser().resolve() / _SCHOLAR_SUBDIR
            base.mkdir(parents=True, exist_ok=True)
            return base, base
        return _DOC_STORE_DIR, _CHUNK_STORE_DIR

    doc_dir = project_data_path(project_id, "doc_store")
    chunk_dir = project_data_path(project_id, "chunk_store")
    doc_dir.mkdir(parents=True, exist_ok=True)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    return doc_dir, chunk_dir


def _project_workspace_dir(project_id: str) -> Path:
    """Return the canonical workspace data directory for one project."""

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be a non-empty string")
    return project_data_path(normalized_project_id)


def _remove_project_workspace_dir(project_id: str) -> bool:
    """Best-effort removal for project-scoped runtime files.

    Why:
        Deleting a project should remove the uploaded originals, doc store, and
        chunk store that belong only to that project. The path guard prevents a
        bad project id or future path override from deleting outside the
        workspace projects root.
    """

    try:
        target = _project_workspace_dir(project_id).resolve()
        root = _PROJECTS_DATA_ROOT.resolve()
    except (OSError, ValueError) as exc:
        logger.warning("project_workspace_cleanup.resolve_failed project=%s err=%s", project_id, exc)
        return False

    if target == root or root not in target.parents:
        logger.warning("project_workspace_cleanup.refused project=%s target=%s root=%s", project_id, target, root)
        return False
    if not target.exists():
        return False
    if not target.is_dir():
        logger.warning("project_workspace_cleanup.refused_non_dir project=%s target=%s", project_id, target)
        return False

    shutil.rmtree(target)
    return True


def _is_test_fixture_project_title(title: str) -> bool:
    """Return True for known backend test fixture project titles."""

    normalized = re.sub(r"\s+", " ", str(title or "").strip().lower())
    return normalized in _TEST_PROJECT_TITLES


# --- Pure helpers extracted to sub-modules ---
# Re-exported here so external imports of routers.resources_router.<name> keep working.
from ._search_helpers import (
    _tokenize_search_text,
    _normalize_chunk_dedup_key,
    _select_diverse_top_chunks as _select_diverse_top_chunks_impl,
    _score_chunks_for_query,
)
from ._chunk_text import (
    _split_text_into_chunks,
    _recursive_split,
    _detect_chunk_type,
    _extract_section_title_from_line,
    structure_aware_chunk,
    _chunk_document,
)
from ._document_extraction import (
    ExtractedDocumentPayload,
    PdfFormulaCandidate,
    bind_pdf_formula_candidates_to_chunks,
    extract_pymupdf_formula_candidates,
    formula_candidates_from_chunks,
    merge_pdf_formula_candidates,
    _extract_document_content,
    _extract_document_content_from_path,
    _extract_document_payload_from_path,
    _reconcile_document_blocks,
    _truncate_document_content,
)
from ._scan_helpers import (
    _iter_scan_files,
    _build_source_fingerprint,
    _extract_zotero_item_key,
    _load_zotero_title_map,
    _resolve_scan_workers,
    _iter_scan_batches,
    _extract_scan_candidate_content,
    _extract_scan_candidate_payload,
    _build_scan_dedupe_key,
    _is_translated_scan_derivative,
    _is_probable_non_literature_scan_artifact,
    _score_pending_candidate_for_query,
    _select_query_pending_candidates,
    _normalize_project_title_for_cleanup,
    _is_extraction_failure_placeholder,
)
from ._export_helpers import (
    ProjectExportFormat,
    _strip_citation_tokens,
    _shorten_export_text,
    _material_excerpt,
    _paragraphs_with_offsets,
    _build_project_academic_export,
    _build_project_manuscript_markdown,
    _build_project_markdown_export,
    _build_project_latex_export,
    _build_project_docx_export,
    _build_project_pdf_export,
    _material_to_csl_json,
    _citation_tokens_to_pandoc,
    _build_project_csl_markdown,
    _build_project_csl_export,
    _build_project_csl_docx_export,
    _build_project_csl_latex_export,
    _build_project_csl_pdf_export,
    _build_file_export_payload,
    _markdown_table_cell,
    _safe_export_filename_stem,
    _unique_export_file,
)

# Wrapper to inject MAX_CHUNKS_PER_MATERIAL (defined later in this module)
def _select_diverse_top_chunks(scored_chunks, top_k, max_chunks_per_material=None):
    if max_chunks_per_material is None:
        max_chunks_per_material = MAX_CHUNKS_PER_MATERIAL
    return _select_diverse_top_chunks_impl(scored_chunks, top_k, max_chunks_per_material)


def _search_chunks_hybrid(query: str, project_id: str, top_k: int = 10) -> list[dict[str, Any]]:
    """Legacy synchronous chunk-search helper kept for old smoke tests.

    Args:
        query: Non-empty query text.
        project_id: Project identifier resolved through the chunk store.
        top_k: Maximum number of positive-scoring chunks to return.

    Returns:
        Search result dictionaries with the score field merged into each chunk.
    """
    normalized_project_id = str(project_id or "").strip()
    normalized_query = str(query or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be a non-empty string")
    if not normalized_query:
        raise ValueError("query must be a non-empty string")
    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")

    chunk_store = _ensure_project_chunks(normalized_project_id)
    all_chunks: list[dict[str, Any]] = []
    for chunks in chunk_store.values():
        all_chunks.extend(chunks)

    top = _select_diverse_top_chunks(
        _score_chunks_for_query(all_chunks, normalized_query),
        top_k=top_k,
    )
    return [{"score": round(score, 2), **chunk} for score, chunk in top if score > 0]


def _search_chunks_via_gateway(project_id: str, query: str, top_k: int = 10) -> list[dict[str, Any]] | None:
    """Return Gateway-ranked chunks when the derived lexical index is valid.

    Args:
        project_id: Existing writing project identifier.
        query: Non-empty retrieval query.
        top_k: Positive maximum number of chunks to return.

    Returns:
        Ranked chunk dictionaries, or ``None`` when the caller must use the
        legacy scorer because the derived index is unavailable or stale.
    """

    normalized_project_id = str(project_id or "").strip()
    normalized_query = str(query or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be a non-empty string")
    if not normalized_query:
        raise ValueError("query must be a non-empty string")
    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")

    try:
        chunk_store = _ensure_project_chunks(normalized_project_id)
        hash_version = _chunk_store_hash_version(normalized_project_id)
        chunk_store_version = compute_chunk_store_version(
            chunk_store,
            hash_version=hash_version,
        )
        gateway_result = retrieve_candidates(
            normalized_project_id,
            normalized_query,
            "general",
            store=chunk_store,
            chunk_store_version=chunk_store_version,
            hash_version=hash_version,
            fts_db_path=_chunk_fts_index_path(normalized_project_id),
            limit=top_k,
            lexical_limit=top_k,
            visual_budget_floor=2,
            visual_budget_intent=max(3, min(12, top_k)),
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    if gateway_result.diagnostics.fts_status != "valid" or not gateway_result.candidates:
        return None

    chunk_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for chunks in chunk_store.values():
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            material_id = str(chunk.get("material_id") or "").strip()
            chunk_id = str(chunk.get("chunk_id") or "").strip()
            if material_id and chunk_id:
                chunk_by_key[(material_id, chunk_id)] = chunk

    results: list[dict[str, Any]] = []
    diagnostics = gateway_result.diagnostics.to_dict()
    for candidate in gateway_result.candidates:
        chunk = chunk_by_key.get((candidate.material_id, candidate.chunk_id))
        if chunk is None:
            continue
        enriched = dict(chunk)
        enriched["score"] = round(candidate.score, 6)
        enriched["retrieval_sources"] = list(candidate.sources)
        enriched["retrieval_gateway_diagnostics"] = diagnostics
        results.append(enriched)
        if len(results) >= top_k:
            break
    return results or None


def search_project_chunks_for_query(project_id: str, query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """Return ranked project chunks for API consumers that need local RAG context.

    Args:
        project_id: Existing writing project identifier.
        query: Non-empty retrieval query.
        top_k: Positive maximum number of chunks to return.

    Returns:
        Ranked chunk dictionaries with a numeric ``score`` field and original
        chunk provenance preserved.
    """
    gateway_hits = _search_chunks_via_gateway(project_id=project_id, query=query, top_k=top_k)
    if gateway_hits is not None:
        return gateway_hits
    return _search_chunks_hybrid(query=query, project_id=project_id, top_k=top_k)


def load_project_chunks_for_rag(project_id: str) -> list[dict[str, Any]]:
    """Return all normalized project chunks for local RAG workflow consumers.

    Args:
        project_id: Existing writing project identifier.

    Returns:
        A flat list of chunk dictionaries with project chunk-store provenance.
    """
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be a non-empty string")

    chunk_store = _ensure_project_chunks(normalized_project_id)
    chunks: list[dict[str, Any]] = []
    for material_chunks in chunk_store.values():
        chunks.extend(dict(chunk) for chunk in material_chunks if isinstance(chunk, dict))
    return chunks


def _ensure_project_chunks(
    project_id: str,
    material_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Backfill missing chunks from doc_store and prune stale chunk entries."""
    def _reconcile_stores(
        doc_store: dict[str, dict[str, Any]],
        chunk_store: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        material_ids = (
            {material_id}
            if material_id
            else set(doc_store.keys()) | set(chunk_store.keys())
        )

        for mid in list(material_ids):
            document = doc_store.get(mid)
            if document is None:
                if mid in chunk_store and (material_id or doc_store):
                    del chunk_store[mid]
                continue

            title = str(document.get("title") or mid)
            content = str(document.get("content") or "")
            existing_chunks = [
                chunk
                for chunk in (chunk_store.get(mid) or [])
                if str(chunk.get("content") or chunk.get("raw_content") or "").strip()
            ]

            if not content.strip():
                chunk_store.pop(mid, None)
                continue

            if not existing_chunks:
                chunk_store[mid] = _chunk_document(mid, title, content)
                continue

            normalized_chunks: list[dict[str, Any]] = []
            for idx, chunk in enumerate(existing_chunks):
                normalized_chunk = dict(chunk)
                if normalized_chunk.get("material_id") != mid:
                    normalized_chunk["material_id"] = mid
                if normalized_chunk.get("title") != title:
                    normalized_chunk["title"] = title
                if normalized_chunk.get("chunk_index") != idx:
                    normalized_chunk["chunk_index"] = idx
                expected_chunk_id = f"{mid}_chunk_{idx}"
                if not str(normalized_chunk.get("chunk_id") or "").strip():
                    normalized_chunk["chunk_id"] = expected_chunk_id
                char_count = len(
                    str(
                        normalized_chunk.get("content")
                        or normalized_chunk.get("raw_content")
                        or ""
                    )
                )
                if normalized_chunk.get("char_count") != char_count:
                    normalized_chunk["char_count"] = char_count
                normalized_chunks.append(normalized_chunk)

            chunk_store[mid] = normalized_chunks

        return doc_store, chunk_store

    _committed_docs, committed_chunks = _update_project_stores_atomic(
        project_id,
        _reconcile_stores,
    )
    return committed_chunks


def get_writing_resource_store():
    """Import and return the writing resource store."""
    from writing_resources import get_writing_resource_store as get_store
    return get_store()


def _ensure_upload_project(project_id: str) -> Any:
    """Validate that the target project exists before ingesting uploaded files."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return store


def _collect_pending_scan_candidates(
    project_id: str,
    folder_path: Path,
) -> dict[str, Any]:
    """Collect non-indexed candidates from a folder for a project.

    This is a reusable metadata stage shared by both full-folder scan and
    query-driven on-demand ingestion.
    """
    root_resolved = folder_path.resolve()
    candidates = sorted(
        _iter_scan_files(folder_path),
        key=lambda path: (
            _build_scan_dedupe_key(path.resolve().relative_to(root_resolved).as_posix()),
            _is_translated_scan_derivative(path.name),
            len(path.name),
            path.name.lower(),
        ),
    )
    existing_doc_store = _load_doc_store(project_id)
    existing_titles = {str(v.get("title") or "") for v in existing_doc_store.values()}
    existing_fingerprints = {
        str(v.get("source_fingerprint") or "")
        for v in existing_doc_store.values()
        if str(v.get("source_fingerprint") or "")
    }
    existing_dedupe_keys: set[str] = set()
    for existing_doc in existing_doc_store.values():
        if not isinstance(existing_doc, dict):
            continue
        for raw_value in (
            existing_doc.get("source_relative_path"),
            existing_doc.get("title"),
        ):
            raw_text = str(raw_value or "").strip()
            if not raw_text:
                continue
            try:
                existing_dedupe_keys.add(_build_scan_dedupe_key(raw_text))
            except (TypeError, ValueError):
                continue

    pending_candidates: list[dict[str, Any]] = []
    skipped_results: list[dict[str, Any]] = []
    failed_results: list[dict[str, Any]] = []
    seen_dedupe_keys = set(existing_dedupe_keys)

    for file_path in candidates:
        filename = file_path.name
        relative_path = file_path.resolve().relative_to(root_resolved)
        relative_posix = relative_path.as_posix()
        dedupe_key = _build_scan_dedupe_key(relative_posix)

        if _is_translated_scan_derivative(relative_posix):
            skipped_results.append(
                {
                    "title": relative_posix,
                    "status": "skipped",
                    "reason": "翻译副本（mono/dual/zh-CN），保留原文材料",
                    "decision": "translated_duplicate",
                    "dedupe_key": dedupe_key,
                }
            )
            continue

        if _is_probable_non_literature_scan_artifact(relative_posix):
            skipped_results.append(
                {
                    "title": relative_posix,
                    "status": "skipped",
                    "reason": "疑似非论文 PDF（文件名含 PnP/cutlines 等制图标记）",
                    "decision": "non_literature_artifact",
                    "dedupe_key": dedupe_key,
                }
            )
            continue

        if dedupe_key in seen_dedupe_keys:
            skipped_results.append(
                {
                    "title": relative_posix,
                    "status": "skipped",
                    "reason": "重复文献（规范化标题匹配）",
                    "decision": "scan_duplicate",
                    "dedupe_key": dedupe_key,
                }
            )
            continue

        try:
            stat = file_path.stat()
            fingerprint = _build_source_fingerprint(root_resolved, file_path)
        except OSError as exc:
            failed_results.append({"title": relative_posix, "status": "error", "reason": str(exc)})
            continue

        if fingerprint in existing_fingerprints:
            skipped_results.append({"title": relative_posix, "status": "skipped", "reason": "已索引（指纹匹配）"})
            seen_dedupe_keys.add(dedupe_key)
            continue

        if relative_posix in existing_titles or filename in existing_titles:
            skipped_results.append({"title": relative_posix, "status": "skipped", "reason": "已索引（路径/文件名匹配）"})
            seen_dedupe_keys.add(dedupe_key)
            continue

        pending_candidates.append(
            {
                "path": file_path,
                "relative_path": relative_path,
                "relative_posix": relative_posix,
                "fingerprint": fingerprint,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "scan_root": root_resolved,
                "dedupe_key": dedupe_key,
            }
        )
        seen_dedupe_keys.add(dedupe_key)

    return {
        "candidates": candidates,
        "pending": pending_candidates,
        "existing_titles": existing_titles,
        "existing_fingerprints": existing_fingerprints,
        "skipped_results": skipped_results,
        "failed_results": failed_results,
    }


def _ingest_pending_candidates(
    project_id: str,
    *,
    store: Any,
    pending_candidates: list[dict[str, Any]],
    zotero_title_map: dict[str, str],
    scan_mode: str,
    batch_size: int,
    max_workers: int,
    existing_titles: set[str],
    existing_fingerprints: set[str],
) -> dict[str, Any]:
    """Persist pending candidates into doc/chunk stores.

    This function is intentionally reusable by both full scan and on-demand ingest.
    """
    results: list[dict[str, Any]] = []
    total_chunks = 0
    failed = 0
    worker_count = 1

    normalized_mode = str(scan_mode or "").strip().lower()
    if normalized_mode not in _SCAN_MODES:
        normalized_mode = "fast"

    if normalized_mode == "fast" and pending_candidates:
        worker_count = _resolve_scan_workers(max_workers)
        for batch in _iter_scan_batches(pending_candidates, batch_size):
            with futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {
                    executor.submit(_extract_scan_candidate_payload, item["path"], project_id=project_id): item
                    for item in batch
                }
                for future in futures.as_completed(future_map):
                    item = future_map[future]
                    relative_posix = str(item["relative_posix"])
                    relative_path = item["relative_path"]
                    fingerprint = str(item["fingerprint"])

                    extraction = future.result()
                    content = extraction.content
                    error_reason = extraction.error_reason
                    if error_reason or not content:
                        failed += 1
                        results.append({"title": relative_posix, "status": "error", "reason": error_reason or "无法提取文本"})
                        continue
                    try:
                        current_fingerprint = _build_source_fingerprint(
                            item["scan_root"],
                            item["path"],
                        )
                    except (OSError, ValueError) as exc:
                        failed += 1
                        results.append(
                            {
                                "title": relative_posix,
                                "status": "error",
                                "reason": str(exc),
                            }
                        )
                        continue
                    if current_fingerprint != fingerprint:
                        failed += 1
                        results.append(
                            {
                                "title": relative_posix,
                                "status": "error",
                                "reason": "source changed during extraction",
                            }
                        )
                        continue

                    zotero_key = _extract_zotero_item_key(relative_path)
                    zotero_title = zotero_title_map.get(zotero_key, "") if zotero_key else ""
                    material_title = f"{zotero_title} [{relative_posix}]" if zotero_title else relative_posix

                    result = _persist_uploaded_document(
                        project_id,
                        material_title,
                        content,
                        store=store,
                        source_relative_path=relative_posix,
                        source_fingerprint=fingerprint,
                        source_size=int(item["size"]),
                        source_mtime=float(item["mtime"]),
                        blocks=extraction.blocks,
                        markdown_full=extraction.markdown_full,
                        parser_provenance=extraction.parser_provenance,
                        parser_output_sha256=extraction.parser_output_sha256,
                        ocr_report=extraction.ocr_report,
                    )
                    total_chunks += int(result.get("chunks") or 0)
                    existing_fingerprints.add(fingerprint)
                    existing_titles.add(material_title)
                    results.append({"title": material_title, "status": "ok", "chunks": result.get("chunks")})
    else:
        for item in pending_candidates:
            relative_posix = str(item["relative_posix"])
            relative_path = item["relative_path"]
            fingerprint = str(item["fingerprint"])

            extraction = _extract_scan_candidate_payload(item["path"], project_id=project_id)
            content = extraction.content
            error_reason = extraction.error_reason
            if error_reason or not content:
                failed += 1
                results.append({"title": relative_posix, "status": "error", "reason": error_reason or "无法提取文本"})
                continue
            try:
                current_fingerprint = _build_source_fingerprint(
                    item["scan_root"],
                    item["path"],
                )
            except (OSError, ValueError) as exc:
                failed += 1
                results.append(
                    {
                        "title": relative_posix,
                        "status": "error",
                        "reason": str(exc),
                    }
                )
                continue
            if current_fingerprint != fingerprint:
                failed += 1
                results.append(
                    {
                        "title": relative_posix,
                        "status": "error",
                        "reason": "source changed during extraction",
                    }
                )
                continue

            zotero_key = _extract_zotero_item_key(relative_path)
            zotero_title = zotero_title_map.get(zotero_key, "") if zotero_key else ""
            material_title = f"{zotero_title} [{relative_posix}]" if zotero_title else relative_posix

            result = _persist_uploaded_document(
                project_id,
                material_title,
                content,
                store=store,
                source_relative_path=relative_posix,
                source_fingerprint=fingerprint,
                source_size=int(item["size"]),
                source_mtime=float(item["mtime"]),
                blocks=extraction.blocks,
                markdown_full=extraction.markdown_full,
                parser_provenance=extraction.parser_provenance,
                parser_output_sha256=extraction.parser_output_sha256,
                ocr_report=extraction.ocr_report,
            )
            total_chunks += int(result.get("chunks") or 0)
            existing_fingerprints.add(fingerprint)
            existing_titles.add(material_title)
            results.append({"title": material_title, "status": "ok", "chunks": result.get("chunks")})

    return {
        "results": results,
        "failed": failed,
        "total_chunks": total_chunks,
        "workers": worker_count,
        "scan_mode": normalized_mode,
        "indexed": len(pending_candidates) - failed,
    }


def _resource_richness_score(store: Any, project_id: str) -> tuple[int, int, int]:
    """Return a tuple score to keep the most valuable project in duplicate groups."""
    section_count = len(store.list_sections(project_id))
    draft_count = len(store.list_drafts(project_id))
    material_count = len(store.list_materials(project_id))
    return (material_count, draft_count, section_count)


def _analyze_cleanup_candidates(store: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect duplicate project and empty material cleanup candidates."""
    projects = store.list_projects()
    grouped_by_title: dict[str, list[Any]] = {}
    for project in projects:
        key = _normalize_project_title_for_cleanup(getattr(project, "title", ""))
        if not key:
            continue
        grouped_by_title.setdefault(key, []).append(project)

    duplicate_projects: list[dict[str, Any]] = []
    duplicate_project_ids: set[str] = set()
    for normalized_title, grouped_projects in grouped_by_title.items():
        if len(grouped_projects) <= 1:
            continue
        # Keep the project with richest content first; tie-breaker by updated_at desc.
        sorted_group = sorted(
            grouped_projects,
            key=lambda project: (
                _resource_richness_score(store, project.project_id),
                str(getattr(project, "updated_at", "")),
            ),
            reverse=True,
        )
        keeper = sorted_group[0]
        for project in sorted_group[1:]:
            duplicate_project_ids.add(project.project_id)
            duplicate_projects.append(
                {
                    "project_id": project.project_id,
                    "title": getattr(project, "title", ""),
                    "normalized_title": normalized_title,
                    "keep_project_id": keeper.project_id,
                    "keep_project_title": getattr(keeper, "title", ""),
                }
            )

    empty_materials: list[dict[str, Any]] = []
    for project in projects:
        if project.project_id in duplicate_project_ids:
            continue
        doc_store = _load_doc_store(project.project_id)
        chunk_store = _load_chunk_store(project.project_id)
        for material in store.list_materials(project.project_id):
            material_id = material.material_id
            doc_record = doc_store.get(material_id, {})
            content = str(doc_record.get("content") or "")
            chunks = chunk_store.get(material_id) or []
            has_non_empty_chunk = any(str(chunk.get("content") or "").strip() for chunk in chunks)

            if _is_extraction_failure_placeholder(content) or not has_non_empty_chunk:
                empty_materials.append(
                    {
                        "project_id": project.project_id,
                        "project_title": getattr(project, "title", ""),
                        "material_id": material_id,
                        "material_title": getattr(material, "title", ""),
                        "reason": "no_extracted_text",
                    }
                )

    return duplicate_projects, empty_materials


@dataclass(frozen=True)
class _UploadedSourceFile:
    path: Path
    fingerprint: str
    size: int
    created: bool = True


def _safe_upload_filename(filename: str) -> str:
    """Return a storage-safe upload filename while preserving display intent."""

    safe_name = Path(str(filename or "unnamed")).name.strip()
    return safe_name or "unnamed"


def _uploaded_source_matches(
    source_path: Path,
    *,
    fingerprint: str,
    size: int,
) -> bool:
    """Return whether one source file still has the expected byte identity."""

    try:
        stat = source_path.stat()
    except OSError:
        return False
    if not source_path.is_file() or stat.st_size != size:
        return False
    digest = hashlib.sha256()
    try:
        with source_path.open("rb") as source:
            while True:
                chunk = source.read(_UPLOAD_READ_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return False
    return f"sha256:{digest.hexdigest()}" == fingerprint


def _collision_safe_upload_filename(filename: str, fingerprint: str) -> str:
    """Return a deterministic sibling filename containing the source digest."""

    digest = str(fingerprint or "").removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("upload fingerprint must be a lowercase SHA-256 digest")
    safe_filename = _safe_upload_filename(filename)
    suffix = Path(safe_filename).suffix
    stem = Path(safe_filename).stem or "upload"
    max_stem_length = max(1, 240 - len(suffix) - len(digest) - 1)
    return f"{stem[:max_stem_length]}-{digest}{suffix}"


def _max_upload_bytes() -> int:
    """Return the per-file upload cap in bytes.

    The optional environment override is intended for local tests and tightly
    controlled desktop deployments; invalid values fall back to the product
    default so the boundary cannot be accidentally disabled.
    """

    raw_limit = os.environ.get(_MAX_UPLOAD_BYTES_ENV, "").strip()
    if not raw_limit:
        return _DEFAULT_MAX_UPLOAD_BYTES
    try:
        parsed = int(raw_limit)
    except ValueError:
        logger.warning("invalid_upload_size_limit: env=%s value=%r", _MAX_UPLOAD_BYTES_ENV, raw_limit)
        return _DEFAULT_MAX_UPLOAD_BYTES
    if parsed < 1:
        logger.warning("invalid_upload_size_limit: env=%s value=%r", _MAX_UPLOAD_BYTES_ENV, raw_limit)
        return _DEFAULT_MAX_UPLOAD_BYTES
    return parsed


def _format_upload_size_limit(limit_bytes: int) -> str:
    """Return a compact size label for upload validation messages."""

    if limit_bytes < 1024 * 1024:
        return f"{limit_bytes} bytes"
    mib = limit_bytes / (1024 * 1024)
    return f"{mib:.0f} MiB" if mib.is_integer() else f"{mib:.1f} MiB"


def _upload_extension(filename: str) -> str:
    """Return a normalized supported-document suffix for an upload name."""

    suffix = Path(filename).suffix.lower().strip()
    if not suffix:
        raise ValueError("上传文件必须包含受支持的扩展名")
    if suffix not in _ALLOWED_UPLOAD_EXTENSIONS:
        supported = ", ".join(sorted(_ALLOWED_UPLOAD_EXTENSIONS))
        raise ValueError(f"不支持的上传文件类型：{suffix}。支持类型：{supported}")
    return suffix


def _validate_upload_content_type(filename: str, content_type: str | None) -> None:
    """Validate best-effort MIME metadata without trusting it as authority."""

    suffix = _upload_extension(filename)
    normalized = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized in _GENERIC_UPLOAD_MIME_TYPES:
        return
    allowed = _ALLOWED_UPLOAD_MIME_TYPES_BY_EXTENSION.get(suffix, set())
    if normalized not in allowed:
        raise ValueError(f"文件“{filename}”的 Content-Type 与扩展名不匹配：{normalized}")


def _validate_upload_magic(filename: str, raw: bytes) -> None:
    """Validate cheap file signatures for binary formats with known parsers."""

    suffix = _upload_extension(filename)
    if suffix == ".pdf" and not raw.lstrip().startswith(b"%PDF-"):
        raise ValueError(f"文件“{filename}”不是有效的 PDF 文件")
    if suffix == ".docx" and not raw.startswith(b"PK\x03\x04"):
        raise ValueError(f"文件“{filename}”不是有效的 DOCX 文件")


async def _persist_upload_to_source_file(
    project_id: str,
    filename: str,
    upload: UploadFile,
) -> _UploadedSourceFile:
    """Stream one upload into the project source-file store.

    Args:
        project_id: Existing project id that owns the uploaded source file.
        filename: Storage-safe filename already chosen by the caller.
        upload: FastAPI upload stream.

    Returns:
        Persisted source path, SHA-256 fingerprint, and byte count.

    Raises:
        ValueError: If the filename/type is unsupported, the stream is empty,
            or the actual byte count exceeds the configured limit.
        OSError: If the source file cannot be written atomically.
    """

    if upload is None:
        raise ValueError("上传文件不能为空")
    safe_filename = _safe_upload_filename(filename)
    max_bytes = _max_upload_bytes()
    _validate_upload_content_type(safe_filename, getattr(upload, "content_type", None))

    source_files_dir = project_data_path(project_id, "source_files")
    source_files_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total_bytes = 0
    magic_prefix = bytearray()
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=source_files_dir,
            prefix=".upload-",
            suffix=".part",
        ) as tmp:
            temp_path = Path(tmp.name)
            while True:
                chunk = await upload.read(_UPLOAD_READ_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise ValueError(f"文件“{safe_filename}”超过大小上限 {_format_upload_size_limit(max_bytes)}")
                digest.update(chunk)
                if len(magic_prefix) < _UPLOAD_MAGIC_PREFIX_BYTES:
                    remaining = _UPLOAD_MAGIC_PREFIX_BYTES - len(magic_prefix)
                    magic_prefix.extend(chunk[:remaining])
                tmp.write(chunk)

        if total_bytes == 0:
            raise ValueError(f"文件“{safe_filename}”为空")
        _validate_upload_magic(safe_filename, bytes(magic_prefix))
        fingerprint = f"sha256:{digest.hexdigest()}"
        committed_path: Path | None = None
        created = False

        def _commit_source(
            doc_store: dict[str, dict[str, Any]],
            chunk_store: dict[str, list[dict[str, Any]]],
        ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
            nonlocal committed_path, created
            preferred_path = source_files_dir / safe_filename
            destination = preferred_path
            if preferred_path.exists():
                if _uploaded_source_matches(
                    preferred_path,
                    fingerprint=fingerprint,
                    size=total_bytes,
                ):
                    committed_path = preferred_path
                    return doc_store, chunk_store
                destination = source_files_dir / _collision_safe_upload_filename(
                    safe_filename,
                    fingerprint,
                )
                if destination.exists():
                    if _uploaded_source_matches(
                        destination,
                        fingerprint=fingerprint,
                        size=total_bytes,
                    ):
                        committed_path = destination
                        return doc_store, chunk_store
                    raise FileExistsError(
                        "collision-safe upload destination contains different bytes"
                    )
            os.replace(temp_path, destination)
            committed_path = destination
            created = True
            return doc_store, chunk_store

        _update_project_stores_atomic(project_id, _commit_source)
        if committed_path is None:
            raise OSError("upload source commit did not produce a destination")
        if created:
            temp_path = None
        return _UploadedSourceFile(
            path=committed_path,
            fingerprint=fingerprint,
            size=total_bytes,
            created=created,
        )
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                logger.warning("upload_temp_cleanup_failed: path=%s", temp_path)


def _known_extraction_failure(content: str) -> bool:
    """Return true for placeholder text emitted by lightweight extractors."""

    normalized = str(content or "").strip()
    if not normalized:
        return True
    known_extract_failures = (
        normalized.startswith("[PDF 文件:"),
        normalized.startswith("[PDF 解析失败:"),
        normalized.startswith("[DOCX 文件:"),
        normalized.startswith("[DOCX 解析失败:"),
        normalized.startswith("[未知格式文件:"),
    )
    return any(known_extract_failures)


def _ensure_extracted_text(filename: str, content: str) -> str:
    """Return non-empty extracted text or raise a user-safe failure."""

    normalized = str(content or "").strip()
    if _known_extraction_failure(normalized):
        raise ValueError(
            f"文件“{filename}”未提取到可检索文本。可能是扫描版 PDF、加密文件或解析依赖缺失（建议安装 pymupdf / PyPDF2 / python-docx）"
        )
    return normalized


def _safe_sidecar_filename(material_id: str) -> str:
    """Safe filename for markdown sidecar (plan §1.7).

    Sanitizes ``material_id`` to ``[A-Za-z0-9_-]`` only, truncates to 48
    chars, then appends ``_<sha1(material_id)[:12]>.md`` so future
    material_id schemes that share a 48-char prefix do not collide.

    Current material_id format ``mat_<12hex>`` is already safe; this is
    defensive for future material_id changes (GPT #5).
    """
    safe_stem = re.sub(r"[^A-Za-z0-9_\-]", "_", material_id)[:48] or "material"
    digest = hashlib.sha1(material_id.encode("utf-8")).hexdigest()[:12]
    return f"{safe_stem}_{digest}.md"


def _markdown_sidecar_path(project_id: str, material_id: str) -> Path:
    """Return the canonical sidecar path for a project/material combo."""
    _, chunk_dir = _resolve_data_dir(project_id)
    return chunk_dir / _safe_project_id(project_id) / "markdown" / _safe_sidecar_filename(material_id)


def _write_markdown_sidecar(
    project_id: str,
    material_id: str,
    markdown: str | None,
) -> Path | None:
    """Persist full markdown for a material as a sidecar file.

    Atomic write (project's ``_atomic_write_text`` helper — NamedTemporaryFile
    + os.replace, plan §1.7). Concurrent writes are safe: each writer creates
    a unique tmp file under the same directory and atomically replaces the
    target. There is NO race that can leave a half-written file.

    Returns None when ``markdown`` is empty / None (default PyMuPDF path
    never produces markdown, so this is the common case).
    """
    if not markdown:
        return None
    target = _markdown_sidecar_path(project_id, material_id)
    _atomic_write_text(target, markdown)
    return target


def _coerce_reusable_embedding(value: object) -> list[float] | None:
    """Return a finite numeric embedding vector or ``None``."""

    if not isinstance(value, list) or not value:
        return None
    normalized: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        number = float(item)
        if not math.isfinite(number):
            return None
        normalized.append(number)
    return normalized


def _reuse_compatible_chunk_embeddings(
    *,
    material_id: str,
    previous_chunks: list[dict[str, Any]],
    current_chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Reuse unambiguous embeddings whose canonical input text is unchanged.

    Matching is deliberately independent of ``chunk_id`` because inserting a
    newly recovered segment can shift every later chunk index. Conflicting
    vectors for the same input hash are treated as ambiguous and not reused.
    """

    candidates: dict[str, dict[tuple[float, ...], list[float]]] = {}
    for previous in previous_chunks:
        if not isinstance(previous, dict):
            continue
        embedding = _coerce_reusable_embedding(previous.get("embedding"))
        if embedding is None:
            continue
        try:
            embedding_input_hash = compute_chunk_hashes(
                previous,
                material_id_hint=material_id,
            )["embedding_input_hash"]
        except (TypeError, ValueError):
            continue
        candidates.setdefault(embedding_input_hash, {})[tuple(embedding)] = embedding

    reused = 0
    output: list[dict[str, Any]] = []
    for current in current_chunks:
        cloned = dict(current)
        if _coerce_reusable_embedding(cloned.get("embedding")) is not None:
            output.append(cloned)
            continue
        try:
            embedding_input_hash = compute_chunk_hashes(
                cloned,
                material_id_hint=material_id,
            )["embedding_input_hash"]
        except (TypeError, ValueError):
            output.append(cloned)
            continue
        matching_vectors = candidates.get(embedding_input_hash, {})
        if len(matching_vectors) == 1:
            cloned["embedding"] = list(next(iter(matching_vectors.values())))
            reused += 1
        output.append(cloned)
    return output, reused


def _write_material_document_content(
    project_id: str,
    material_id: str,
    filename: str,
    content: str,
    *,
    source_relative_path: str | None = None,
    source_fingerprint: str | None = None,
    source_size: int | None = None,
    source_mtime: float | None = None,
    blocks: list[Any] | None = None,
    markdown_full: str | None = None,
    parser_provenance: PDFParserProvenance | Mapping[str, object] | None = None,
    parser_output_sha256: str | None = None,
    ocr_report: OcrIngestionReport | Mapping[str, object] | None = None,
    require_existing_material: bool = False,
) -> dict[str, Any]:
    """Persist extracted text, optional sidecar markdown, and chunks.

    Payload-aware callers may pass ``blocks`` and ``markdown_full`` here so that:
      - The markdown sidecar is written (atomic, sha1-suffixed filename)
      - The chunker receives ``blocks=...`` and produces structure-aware
        chunks with the 5 new metadata keys.

    When ``blocks`` / ``markdown_full`` are both None (default PyMuPDF path
    AND all legacy callers), behavior is byte-level identical to the
    legacy implementation: doc_store row identical, chunk_store entries
    identical, no sidecar written.
    """

    if not str(project_id or "").strip():
        raise ValueError("project_id must be non-empty")
    if not str(material_id or "").strip():
        raise ValueError("material_id must be non-empty")
    extracted = _ensure_extracted_text(filename, content)
    parser_revision = serialize_parser_provenance(parser_provenance)
    ocr_revision = serialize_ocr_revision_report(ocr_report)

    # Sidecar: only when caller passed markdown_full; default
    # path leaves it None and we skip the write entirely.
    sidecar_path = _write_markdown_sidecar(project_id, material_id, markdown_full)

    reconciled_blocks = _reconcile_document_blocks(extracted, blocks)

    # Chunker dispatch: blocks=None routes to legacy text chunker
    # (byte-level identical); blocks=[...] routes to structured chunker.
    generated_chunks = _chunk_document(
        material_id,
        filename,
        extracted,
        blocks=reconciled_blocks,
    )
    candidate_chunks = generated_chunks
    reused_embeddings = 0

    def _publish_material(
        doc_store: dict[str, dict[str, Any]],
        chunk_store: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        nonlocal candidate_chunks, reused_embeddings

        current_record = doc_store.get(material_id)
        if require_existing_material and (
            not isinstance(current_record, dict)
            or str(current_record.get("source_fingerprint") or "").strip()
            != str(source_fingerprint or "").strip()
        ):
            raise ValueError("material was deleted or changed before extraction commit")
        previous = current_record if isinstance(current_record, dict) else {}
        doc_store[material_id] = {
            **previous,
            "title": filename,
            "content": extracted,
            "source_relative_path": (
                source_relative_path or previous.get("source_relative_path") or filename
            ),
            "source_fingerprint": (
                source_fingerprint or previous.get("source_fingerprint") or ""
            ),
            "source_size": int(source_size or previous.get("source_size") or 0),
            "source_mtime": float(source_mtime or previous.get("source_mtime") or 0.0),
            "extraction_status": "succeeded",
            "extraction_error": "",
            "parser_provenance": parser_revision,
            "parser_output_sha256": parser_output_sha256,
            "ocr_revision": ocr_revision,
        }
        previous_chunks = chunk_store.get(material_id, [])
        candidate_chunks, reused_embeddings = _reuse_compatible_chunk_embeddings(
            material_id=material_id,
            previous_chunks=(
                previous_chunks if isinstance(previous_chunks, list) else []
            ),
            current_chunks=generated_chunks,
        )
        chunk_store[material_id] = candidate_chunks
        return doc_store, chunk_store

    _committed_docs, committed_chunks = _update_project_stores_atomic(
        project_id,
        _publish_material,
    )
    accepted_chunks = committed_chunks.get(material_id, [])
    generated_chunk_count = len(candidate_chunks)
    accepted_chunk_count = len(accepted_chunks)

    result: dict[str, Any] = {
        "material_id": material_id,
        "title": filename,
        "content_length": len(extracted),
        "chunks": accepted_chunk_count,
        "generated_chunks": generated_chunk_count,
        "quarantined_chunks": max(0, generated_chunk_count - accepted_chunk_count),
        "reused_embeddings": reused_embeddings,
        "status": "ok",
    }
    if sidecar_path is not None:
        result["sidecar_markdown_path"] = str(sidecar_path)
    normalized_source_fingerprint = str(source_fingerprint or "").strip().lower()
    normalized_source_size = int(source_size or 0)
    if re.fullmatch(r"sha256:[0-9a-f]{64}", normalized_source_fingerprint) and normalized_source_size > 0:
        identity = build_material_revision_identity(
            project_id=project_id,
            material_id=material_id,
            source_name=source_relative_path or filename,
            raw_source_sha256=normalized_source_fingerprint,
            raw_source_size_bytes=normalized_source_size,
            extracted_text=extracted,
            chunks=accepted_chunks,
            parser_provenance=parser_revision,
            parser_output_sha256=parser_output_sha256,
            ocr_report=ocr_revision,
        )
        sync_result = synchronize_material_revision(identity)
        result.update(
            {
                "material_revision_status": sync_result.receipt.status,
                "material_revision_receipt_id": sync_result.receipt.receipt_id,
                "material_revision_fingerprint": identity.revision_fingerprint,
            }
        )
    else:
        result.update(
            {
                "material_revision_status": "unavailable",
                "material_revision_reason": "authoritative_source_sha256_unavailable",
            }
        )
    return result


def _create_pending_uploaded_document(
    project_id: str,
    filename: str,
    *,
    store: Any,
    source_relative_path: str,
    source_fingerprint: str,
    source_size: int,
) -> dict[str, Any]:
    """Atomically reserve one PDF fingerprint and create its pending shell."""

    if not str(project_id or "").strip():
        raise ValueError("project_id must be non-empty")
    safe_filename = _safe_upload_filename(filename)
    safe_source_name = _safe_upload_filename(source_relative_path)
    if safe_source_name != source_relative_path:
        raise ValueError("source_relative_path must be one safe filename")
    normalized_fingerprint = str(source_fingerprint or "").strip().lower()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", normalized_fingerprint):
        raise ValueError("source_fingerprint must be a SHA-256 fingerprint")
    if isinstance(source_size, bool) or not isinstance(source_size, int) or source_size < 1:
        raise ValueError("source_size must be a positive integer")
    source_root = project_data_path(project_id, "source_files").resolve()
    source_path = (source_root / safe_source_name).resolve()
    if source_path.parent != source_root:
        raise ValueError("uploaded source escaped the project source_files directory")
    reservation: dict[str, Any] = {}

    def _queue_material(
        doc_store: dict[str, dict[str, Any]],
        chunk_store: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        nonlocal reservation
        if not _uploaded_source_matches(
            source_path,
            fingerprint=normalized_fingerprint,
            size=source_size,
        ):
            raise ValueError("uploaded PDF source changed before fingerprint reservation")
        for existing_material_id, existing_doc in doc_store.items():
            if not isinstance(existing_doc, dict):
                continue
            if str(existing_doc.get("source_fingerprint") or "").strip().lower() != normalized_fingerprint:
                continue
            if not str(existing_doc.get("source_relative_path") or "").strip():
                existing_doc["source_relative_path"] = safe_source_name
                existing_doc["source_size"] = int(existing_doc.get("source_size") or source_size)
                doc_store[existing_material_id] = existing_doc
            reservation = {
                "material_id": existing_material_id,
                "title": str(existing_doc.get("title") or safe_filename),
                "content_length": len(str(existing_doc.get("content") or "")),
                "chunks": len(chunk_store.get(existing_material_id, [])),
                "status": "duplicate",
            }
            return doc_store, chunk_store

        material = store.create_material(
            project_id=project_id,
            title=safe_filename,
            title_en=safe_filename,
            summary=f"PDF 已导入，正在后台提取文本：{safe_filename}",
            summary_en="",
            material_type="reference",
        )
        doc_store[material.material_id] = {
            "title": safe_filename,
            "content": "",
            "source_relative_path": safe_source_name,
            "source_fingerprint": normalized_fingerprint,
            "source_size": int(source_size),
            "source_mtime": 0.0,
            "extraction_status": "queued",
            "extraction_error": "",
        }
        chunk_store[material.material_id] = []
        reservation = {
            "material_id": material.material_id,
            "title": safe_filename,
            "content_length": 0,
            "chunks": 0,
            "status": "queued",
        }
        return doc_store, chunk_store

    _update_project_stores_atomic(project_id, _queue_material)
    if not reservation:
        raise RuntimeError("uploaded PDF fingerprint reservation returned no result")
    return reservation


def _remove_unreferenced_uploaded_source(
    project_id: str,
    uploaded: _UploadedSourceFile,
) -> bool:
    """Remove only a newly-created source that no document record references."""

    if not uploaded.created:
        return False
    source_root = project_data_path(project_id, "source_files").resolve()
    candidate = uploaded.path.resolve()
    if candidate.parent != source_root:
        raise ValueError("uploaded source escaped the project source_files directory")
    removed = False

    def _references_candidate(record: object) -> bool:
        if not isinstance(record, dict):
            return False
        source_reference = str(record.get("source_relative_path") or "").strip()
        if not source_reference:
            return False
        try:
            raw_reference = Path(source_reference).expanduser()
            referenced_path = (
                raw_reference.resolve()
                if raw_reference.is_absolute()
                else (source_root / raw_reference).resolve()
            )
        except (OSError, RuntimeError, ValueError):
            return False
        if referenced_path == source_root or source_root not in referenced_path.parents:
            return False
        return os.path.normcase(str(referenced_path)) == os.path.normcase(str(candidate))

    def _remove_if_unreferenced(
        doc_store: dict[str, dict[str, Any]],
        chunk_store: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        nonlocal removed
        referenced = any(_references_candidate(record) for record in doc_store.values())
        if referenced or not _uploaded_source_matches(
            candidate,
            fingerprint=uploaded.fingerprint,
            size=uploaded.size,
        ):
            return doc_store, chunk_store
        try:
            candidate.unlink()
        except FileNotFoundError:
            return doc_store, chunk_store
        except OSError as exc:
            logger.warning("duplicate_upload_source_cleanup_failed: file=%s error=%s", candidate.name, exc)
            return doc_store, chunk_store
        removed = True
        return doc_store, chunk_store

    _update_project_stores_atomic(project_id, _remove_if_unreferenced)
    return removed


def _mark_uploaded_document_extraction_failed(
    project_id: str,
    material_id: str,
    error: str,
    *,
    expected_source_fingerprint: str | None = None,
) -> None:
    """Record recoverable extraction failure state on the material sidecar."""

    def _mark_failed(doc_store: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        record = doc_store.get(material_id)
        if not isinstance(record, dict):
            return doc_store
        if expected_source_fingerprint is not None and (
            str(record.get("source_fingerprint") or "").strip()
            != str(expected_source_fingerprint or "").strip()
        ):
            return doc_store
        record.update(
            {
                "extraction_status": "failed",
                "extraction_error": str(error or "extraction failed")[:1000],
            }
        )
        doc_store[material_id] = record
        return doc_store

    _update_doc_store_atomic(project_id, _mark_failed)


def _build_uploaded_document_processing_request(
    *,
    project_id: str,
    material_id: str,
    filename: str,
    source_relative_path: str | None = None,
    source_fingerprint: str,
    source_size: int,
) -> dict[str, Any]:
    """Build the explicit task contract for background upload extraction."""

    safe_filename = _safe_upload_filename(filename)
    safe_source_name = _safe_upload_filename(source_relative_path or safe_filename)
    if source_relative_path is not None and safe_source_name != source_relative_path:
        raise ValueError("source_relative_path must be one safe filename")
    return {
        "schema_version": "material_processing_task_v1",
        "project_id": project_id,
        "material_id": material_id,
        "input_ref": {
            "ref_type": "uploaded_source_file",
            "material_id": material_id,
            "source_path_label": safe_source_name,
            "content_digest": source_fingerprint,
            "size_bytes": int(source_size),
        },
        "page_range": {"mode": "all"},
        "processing_mode": "fast_text",
        "language_in": None,
        "language_out": None,
        "preserve": {
            "formulas": True,
            "tables": True,
            "figures": True,
            "citations": True,
            "annotations": True,
        },
        "provider_ref": None,
        "cache": {
            "policy": "use",
            "content_digest": source_fingerprint,
            "decision": "pending",
        },
        "output_targets": ["chunks", "locators", "text_sidecar"],
        "metadata": {
            "source": "resource_upload",
            "filename": safe_filename,
            "extension": Path(safe_filename).suffix.lower(),
        },
    }


def _uploaded_document_processing_artifacts(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return typed artifact summaries for upload extraction results."""

    chunks = int(result.get("chunks") or 0)
    content_length = int(result.get("content_length") or 0)
    artifacts: list[dict[str, Any]] = [
        {
            "artifact_type": "chunk_index",
            "output_target": "chunks",
            "count": chunks,
            "metadata": {"chunk_count": chunks},
        },
        {
            "artifact_type": "extracted_text_record",
            "output_target": "text_sidecar",
            "count": 1 if content_length else 0,
            "metadata": {"content_length": content_length},
        },
        {
            "artifact_type": "locator_metadata",
            "output_target": "locators",
            "count": chunks,
            "metadata": {"source": "chunk_metadata"},
        },
    ]
    sidecar_path = str(result.get("sidecar_markdown_path") or "").strip()
    if sidecar_path:
        artifacts.append(
            {
                "artifact_type": "markdown_sidecar",
                "output_target": "text_sidecar",
                "count": 1,
                "path": sidecar_path,
                "metadata": {"format": "markdown"},
            }
        )
    return artifacts


@dataclass(frozen=True)
class _UploadedDocumentExtractionContract:
    """Durable source identity needed to rebuild one PDF executor."""

    project_id: str
    material_id: str
    filename: str
    source_relative_path: str
    source_path: Path
    source_fingerprint: str
    source_size: int


def _resolve_uploaded_document_extraction_contract(
    runtime: Any,
    job_id: str,
) -> _UploadedDocumentExtractionContract:
    """Resolve and validate one executor contract from persisted task state."""

    task = runtime.get_material_processing_task(job_id)
    if not isinstance(task, dict):
        raise ValueError(f"Material processing task not found: {job_id}")
    request = task.get("request")
    if not isinstance(request, dict):
        raise ValueError("material processing request must be an object")
    input_ref = request.get("input_ref")
    if not isinstance(input_ref, dict):
        raise ValueError("material processing input_ref must be an object")
    if str(input_ref.get("ref_type") or "").strip() != "uploaded_source_file":
        raise ValueError("material processing task is not an uploaded source file")

    project_id = str(request.get("project_id") or "").strip()
    material_id = str(request.get("material_id") or "").strip()
    ref_material_id = str(input_ref.get("material_id") or "").strip()
    source_label = str(input_ref.get("source_path_label") or "").strip()
    source_fingerprint = str(input_ref.get("content_digest") or "").strip().lower()
    source_size_raw = input_ref.get("size_bytes")
    if not project_id or not material_id or ref_material_id != material_id:
        raise ValueError("material processing source identity is incomplete")
    source_relative_path = _safe_upload_filename(source_label)
    if not source_label or source_relative_path != source_label:
        raise ValueError("uploaded source path label must be one safe filename")
    metadata = request.get("metadata")
    display_label = (
        str(metadata.get("filename") or "").strip()
        if isinstance(metadata, dict)
        else ""
    )
    filename = _safe_upload_filename(display_label or source_relative_path)
    if display_label and filename != display_label:
        raise ValueError("uploaded display filename must be one safe filename")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", source_fingerprint):
        raise ValueError("uploaded source content_digest must be a SHA-256 fingerprint")
    if isinstance(source_size_raw, bool) or not isinstance(source_size_raw, int) or source_size_raw < 1:
        raise ValueError("uploaded source size_bytes must be a positive integer")

    source_root = project_data_path(project_id, "source_files").resolve()
    source_path = (source_root / source_relative_path).resolve()
    if source_path.parent != source_root:
        raise ValueError("uploaded source path escaped the project source_files directory")
    return _UploadedDocumentExtractionContract(
        project_id=project_id,
        material_id=material_id,
        filename=filename,
        source_relative_path=source_relative_path,
        source_path=source_path,
        source_fingerprint=source_fingerprint,
        source_size=source_size_raw,
    )


def _verify_uploaded_document_extraction_source(
    contract: _UploadedDocumentExtractionContract,
) -> None:
    """Verify the persisted source still matches its exact size and digest."""

    try:
        stat = contract.source_path.stat()
    except OSError as exc:
        raise ValueError("uploaded PDF source is missing or unreadable") from exc
    if not contract.source_path.is_file() or stat.st_size != contract.source_size:
        raise ValueError("uploaded PDF source size changed before extraction")
    digest = hashlib.sha256()
    with contract.source_path.open("rb") as source:
        while True:
            chunk = source.read(_UPLOAD_READ_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    actual_fingerprint = f"sha256:{digest.hexdigest()}"
    if actual_fingerprint != contract.source_fingerprint:
        raise ValueError("uploaded PDF source fingerprint changed before extraction")


def _is_uploaded_document_extraction_task(task: Mapping[str, Any] | None) -> bool:
    """Return whether a persisted material task owns the upload executor."""

    if not isinstance(task, Mapping):
        return False
    request = task.get("request")
    if not isinstance(request, Mapping):
        return False
    input_ref = request.get("input_ref")
    return isinstance(input_ref, Mapping) and input_ref.get("ref_type") == "uploaded_source_file"


def _build_uploaded_document_extraction_executor(runtime: Any, job_id: str) -> Callable[[Any], Any]:
    """Rebuild an upload executor using only persisted, validated identity."""

    async def _executor(current_job: Any) -> dict[str, Any]:
        target_job = current_job or runtime.get_job(job_id)
        if target_job is None:
            raise ValueError(f"Job {job_id} not found")
        contract: _UploadedDocumentExtractionContract | None = None
        try:
            contract = _resolve_uploaded_document_extraction_contract(runtime, target_job.job_id)
            await runtime.wait_for_job_ready(target_job.job_id)
            _verify_uploaded_document_extraction_source(contract)
            runtime.record_material_processing_task_result(
                target_job.job_id,
                status="running",
                result={
                    "status": "running",
                    "stage": "read_source",
                    "route": f"/workbench/paper/{contract.material_id}",
                },
                artifacts=[],
                warnings=[],
                provenance={"source": "resources_router.upload_executor"},
            )
            runtime.emit_job_progress(
                target_job.job_id,
                stage="read_source",
                message="正在读取已保存的 PDF",
                progress=12,
            )
            await runtime.wait_for_job_ready(target_job.job_id)
            runtime.emit_job_progress(
                target_job.job_id,
                stage="extract",
                message="正在后台提取 PDF 文本",
                progress=35,
            )

            def _extract() -> ExtractedDocumentPayload:
                return _extract_document_payload_from_path(
                    contract.filename,
                    contract.source_path,
                    project_id=contract.project_id,
                )

            payload = await asyncio.to_thread(_extract)
            content = _truncate_document_content(payload.content)
            await runtime.wait_for_job_ready(target_job.job_id)
            runtime.begin_job_commit(target_job.job_id)
            try:
                commit_task = asyncio.create_task(
                    asyncio.to_thread(
                        _write_material_document_content,
                        contract.project_id,
                        contract.material_id,
                        contract.filename,
                        content,
                        source_relative_path=contract.source_relative_path,
                        source_fingerprint=contract.source_fingerprint,
                        source_size=contract.source_size,
                        blocks=payload.blocks,
                        markdown_full=payload.markdown_full,
                        parser_provenance=payload.parser_provenance,
                        parser_output_sha256=payload.parser_output_sha256,
                        ocr_report=payload.ocr_report,
                        require_existing_material=True,
                    )
                )
                try:
                    result = await asyncio.shield(commit_task)
                except asyncio.CancelledError:
                    logger.warning(
                        "upload_commit_cancellation_deferred: job_id=%s material_id=%s",
                        target_job.job_id,
                        contract.material_id,
                    )
                    result = await commit_task
            finally:
                runtime.end_job_commit(target_job.job_id)
        except asyncio.CancelledError:
            current = runtime.get_job(target_job.job_id)
            if current is not None and current.status.value == "cancelled":
                if contract is not None:
                    _mark_uploaded_document_extraction_failed(
                        contract.project_id,
                        contract.material_id,
                        "用户已取消 PDF 文本提取",
                        expected_source_fingerprint=contract.source_fingerprint,
                    )
                runtime.record_material_processing_task_result(
                    target_job.job_id,
                    status="cancelled",
                    result={"status": "cancelled", "stage": "cancelled"},
                    artifacts=[],
                    warnings=["用户已取消 PDF 文本提取"],
                    provenance={"source": "resources_router.upload_executor"},
                )
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            if contract is not None:
                _mark_uploaded_document_extraction_failed(
                    contract.project_id,
                    contract.material_id,
                    str(exc),
                    expected_source_fingerprint=contract.source_fingerprint,
                )
            runtime.record_material_processing_task_result(
                target_job.job_id,
                status="failed",
                result={
                    "status": "failed",
                    "stage": "extract",
                    "error": str(exc)[:1000],
                    **(
                        {"route": f"/workbench/paper/{contract.material_id}"}
                        if contract is not None
                        else {}
                    ),
                },
                artifacts=[],
                warnings=[str(exc)[:1000]],
                cache_decision="miss",
                provenance={"source": "resources_router.upload_executor"},
            )
            raise

        runtime.emit_job_progress(
            target_job.job_id,
            stage="index",
            message="正在写入检索切块",
            progress=86,
            data={"chunks": int(result.get("chunks") or 0)},
        )
        result_summary = {
            "status": "completed",
            "kind": "resource_ingest",
            "project_id": contract.project_id,
            "material_id": contract.material_id,
            "title": contract.filename,
            "chunks": int(result.get("chunks") or 0),
            "content_length": int(result.get("content_length") or 0),
            "route": f"/workbench/paper/{contract.material_id}",
        }
        runtime.record_material_processing_task_result(
            target_job.job_id,
            status="completed",
            result=result_summary,
            artifacts=_uploaded_document_processing_artifacts(result),
            warnings=[],
            cache_decision="miss",
            provenance={"source": "resources_router.upload_executor"},
        )
        return result_summary

    return _executor


async def _start_uploaded_document_extraction_job(
    project_id: str,
    material_id: str,
    filename: str,
    source_path: Path,
    *,
    source_fingerprint: str,
    source_size: int,
    source_relative_path: str | None = None,
    batch_context: _UploadBatchContext | None = None,
) -> tuple[str, str]:
    """Start a runtime-visible extraction/indexing job for one uploaded PDF."""

    batch_context = _validate_upload_batch_context(batch_context)
    from harness_protocols import JobKind, SessionMode
    from writing_runtime import get_writing_runtime

    runtime = get_writing_runtime()
    safe_filename = _safe_upload_filename(filename)
    safe_source_name = _safe_upload_filename(source_relative_path or source_path.name)
    if source_relative_path is not None and safe_source_name != source_relative_path:
        raise ValueError("source_relative_path must be one safe filename")
    source_root = project_data_path(project_id, "source_files").resolve()
    expected_source_path = (source_root / safe_source_name).resolve()
    if expected_source_path.parent != source_root or source_path.resolve() != expected_source_path:
        raise ValueError("uploaded PDF source must use its persisted project source path")
    processing_request = _build_uploaded_document_processing_request(
        project_id=project_id,
        material_id=material_id,
        filename=safe_filename,
        source_relative_path=safe_source_name,
        source_fingerprint=source_fingerprint,
        source_size=source_size,
    )
    session = runtime.create_session(
        mode=SessionMode.PROMPT,
        tags=["resource_ingest", "pdf"],
        metadata={
            "source": "resource_ingest",
            "title": "PDF 后台提取",
            "project_id": project_id,
            "material_id": material_id,
        },
    )
    job_metadata: dict[str, Any] = {
        "source": "resource_ingest",
        "project_id": project_id,
        "material_id": material_id,
        "filename": safe_filename,
        "route": f"/workbench/paper/{material_id}",
        "progress_stage": "queued",
        "progress_message": "PDF 已可阅读，文本提取正在排队",
        "progress": 1,
    }
    if batch_context is not None:
        job_metadata.update(batch_context.to_job_metadata())
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PIPELINE_RUN,
        input_text=f"提取 {safe_filename}",
        tags=["resource_ingest", "pdf"],
        metadata=job_metadata,
    )
    runtime.update_material_processing_task(
        job.job_id,
        request=processing_request,
        status="queued",
        provenance={"source": "resources_router.upload_queue"},
    )

    await runtime.start_job(
        job.job_id,
        executor=_build_uploaded_document_extraction_executor(runtime, job.job_id),
    )
    return session.session_id, job.job_id


async def recover_uploaded_document_extraction_jobs(runtime: Any | None = None) -> dict[str, int]:
    """Reattach upload executors for persisted non-terminal material tasks."""

    if runtime is None:
        from writing_runtime import get_writing_runtime

        runtime = get_writing_runtime()
    counts = {"scanned": 0, "recovered": 0, "paused": 0, "skipped": 0}
    for session in runtime.list_sessions(include_archived=True):
        for job in runtime.list_jobs(session.session_id):
            task = runtime.get_material_processing_task(job.job_id)
            if not _is_uploaded_document_extraction_task(task):
                continue
            counts["scanned"] += 1
            if runtime.has_active_job_executor(job.job_id):
                counts["skipped"] += 1
                continue
            task_status = str(task.get("status") or "").strip().lower()
            if task_status in {"completed", "failed", "cancelled"} or job.status.value in {
                "completed",
                "failed",
                "cancelled",
            }:
                counts["skipped"] += 1
                continue
            if job.status.value == "paused":
                runtime.record_material_processing_task_result(
                    job.job_id,
                    status="paused",
                    result={"status": "paused", "stage": "recovery"},
                    artifacts=list(task.get("artifacts") or []),
                    warnings=list(task.get("warnings") or []),
                    provenance={"source": "resources_router.startup_recovery"},
                )
                counts["paused"] += 1
            else:
                runtime.record_material_processing_task_result(
                    job.job_id,
                    status="queued",
                    result={"status": "queued", "stage": "recovery"},
                    artifacts=list(task.get("artifacts") or []),
                    warnings=list(task.get("warnings") or []),
                    provenance={"source": "resources_router.startup_recovery"},
                )
                counts["recovered"] += 1
            await runtime.recover_job_executor(
                job.job_id,
                _build_uploaded_document_extraction_executor(runtime, job.job_id),
            )
    return counts


async def shutdown_uploaded_document_extraction_jobs(runtime: Any | None = None) -> dict[str, int]:
    """Persist recoverable upload state and stop process-owned executors."""

    if runtime is None:
        from writing_runtime import get_writing_runtime

        runtime = get_writing_runtime()
    counts = {"scanned": 0, "interrupted": 0, "completed_commit": 0}
    for session in runtime.list_sessions(include_archived=True):
        for job in runtime.list_jobs(session.session_id):
            task = runtime.get_material_processing_task(job.job_id)
            if not _is_uploaded_document_extraction_task(task) or not runtime.has_active_job_executor(job.job_id):
                continue
            counts["scanned"] += 1
            if runtime.is_job_commit_in_progress(job.job_id):
                await runtime.interrupt_job_for_shutdown(job.job_id)
                counts["completed_commit"] += 1
                continue
            preserve_pause = job.status.value == "paused"
            runtime.record_material_processing_task_result(
                job.job_id,
                status="paused" if preserve_pause else "queued",
                result={
                    "status": "paused" if preserve_pause else "queued",
                    "stage": "shutdown_interrupted",
                },
                artifacts=list(task.get("artifacts") or []),
                warnings=list(task.get("warnings") or []),
                provenance={"source": "resources_router.shutdown"},
            )
            await runtime.interrupt_job_for_shutdown(job.job_id)
            counts["interrupted"] += 1
    return counts


def _persist_uploaded_document(
    project_id: str,
    filename: str,
    content: str,
    *,
    store: Any,
    source_relative_path: str | None = None,
    source_fingerprint: str | None = None,
    source_size: int | None = None,
    source_mtime: float | None = None,
    blocks: list[Any] | None = None,
    markdown_full: str | None = None,
    parser_provenance: PDFParserProvenance | Mapping[str, object] | None = None,
    parser_output_sha256: str | None = None,
    ocr_report: OcrIngestionReport | Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Create a material entry and persist its document/chunk payload.

    ``blocks`` / ``markdown_full`` are forwarded to
    ``_write_material_document_content`` so the marker-backend structured
    output (when enabled) reaches the chunker and the sidecar writer. Both
    default to None — legacy callers that have not adopted the payload
    helper still trigger the legacy PyMuPDF chunking path verbatim.
    """
    safe_filename = _safe_upload_filename(filename)
    extracted = _ensure_extracted_text(safe_filename, content)
    # 智能摘要提取（优先 Abstract 章节）
    if extracted:
        try:
            from services.abstract_extractor import extract_abstract
            summary = extract_abstract(extracted, max_length=500).strip()
        except Exception:  # noqa: BLE001 - fallback to simple truncate
            summary = extracted[:200].replace("\n", " ").strip()
    else:
        summary = f"从文件 {safe_filename} 导入"
    material = store.create_material(
        project_id=project_id,
        title=safe_filename,
        title_en=safe_filename,
        summary=summary,
        summary_en="",
        material_type="reference",
    )

    return _write_material_document_content(
        project_id,
        material.material_id,
        safe_filename,
        extracted,
        source_relative_path=source_relative_path or safe_filename,
        source_fingerprint=source_fingerprint,
        source_size=source_size,
        source_mtime=source_mtime,
        blocks=blocks,
        markdown_full=markdown_full,
        parser_provenance=parser_provenance,
        parser_output_sha256=parser_output_sha256,
        ocr_report=ocr_report,
    )


async def _ingest_uploaded_document(
    project_id: str,
    upload: UploadFile,
    *,
    store: Any,
    batch_context: _UploadBatchContext | None = None,
) -> dict[str, Any]:
    """Read one uploaded file and persist it into the project knowledge base."""
    batch_context = _validate_upload_batch_context(batch_context)
    filename = _safe_upload_filename(upload.filename or "unnamed")
    dedupe_key = _build_scan_dedupe_key(filename)

    if _is_translated_scan_derivative(filename):
        return _with_upload_batch_context({
            "title": filename,
            "chunks": 0,
            "status": "skipped",
            "reason": "翻译副本（mono/dual/zh-CN），保留原文材料",
            "decision": "translated_duplicate",
            "dedupe_key": dedupe_key,
        }, batch_context)

    if _is_probable_non_literature_scan_artifact(filename):
        return _with_upload_batch_context({
            "title": filename,
            "chunks": 0,
            "status": "skipped",
            "reason": "疑似非论文 PDF（文件名含 PnP/cutlines 等制图标记）",
            "decision": "non_literature_artifact",
            "dedupe_key": dedupe_key,
        }, batch_context)

    uploaded = await _persist_upload_to_source_file(project_id, filename, upload)
    content_fingerprint = uploaded.fingerprint

    if Path(filename).suffix.lower() in _ASYNC_UPLOAD_EXTENSIONS:
        try:
            pending = _create_pending_uploaded_document(
                project_id,
                filename,
                store=store,
                source_relative_path=uploaded.path.name,
                source_fingerprint=content_fingerprint,
                source_size=uploaded.size,
            )
        except Exception:
            _remove_unreferenced_uploaded_source(project_id, uploaded)
            raise
        if str(pending.get("status") or "") != "queued":
            _remove_unreferenced_uploaded_source(project_id, uploaded)
            material_id = str(pending.get("material_id") or "")
            return _with_upload_batch_context({
                **pending,
                **(
                    {"open_url": f"/workbench/paper/{material_id}"}
                    if material_id
                    else {}
                ),
            }, batch_context)
        start_job_kwargs: dict[str, Any] = {
            "source_fingerprint": content_fingerprint,
            "source_size": uploaded.size,
            "source_relative_path": uploaded.path.name,
        }
        if batch_context is not None:
            start_job_kwargs["batch_context"] = batch_context
        session_id, job_id = await _start_uploaded_document_extraction_job(
            project_id,
            str(pending["material_id"]),
            filename,
            uploaded.path,
            **start_job_kwargs,
        )
        return _with_upload_batch_context({
            **pending,
            "job_id": job_id,
            "session_id": session_id,
            "open_url": f"/workbench/paper/{pending['material_id']}",
            "message": "PDF 已可阅读，文本提取将在后台完成。",
        }, batch_context)

    # Content-hash dedup: a paper uploaded twice (whether under the same or a
    # different filename) collapses into one material. Cheaper than re-running
    # extraction + chunking, and prevents the symptom where a batch upload
    # creates two rows for the same PDF.
    existing_doc_store = _load_doc_store(project_id)
    for existing_mid, existing_doc in existing_doc_store.items():
        if str(existing_doc.get("source_fingerprint") or "") == content_fingerprint:
            if not str(existing_doc.get("source_relative_path") or "").strip():
                def _repair_duplicate_source(
                    doc_store: dict[str, dict[str, Any]],
                ) -> dict[str, dict[str, Any]]:
                    current = doc_store.get(existing_mid)
                    if not isinstance(current, dict):
                        return doc_store
                    if str(current.get("source_fingerprint") or "") != content_fingerprint:
                        return doc_store
                    if str(current.get("source_relative_path") or "").strip():
                        return doc_store
                    current["source_relative_path"] = uploaded.path.name
                    current["source_size"] = int(current.get("source_size") or uploaded.size)
                    doc_store[existing_mid] = current
                    return doc_store

                _update_doc_store_atomic(project_id, _repair_duplicate_source)
            _remove_unreferenced_uploaded_source(project_id, uploaded)
            return _with_upload_batch_context({
                "material_id": existing_mid,
                "title": str(existing_doc.get("title") or filename),
                "content_length": len(str(existing_doc.get("content") or "")),
                "chunks": len(_load_chunk_store(project_id).get(existing_mid, [])),
                "status": "duplicate",
            }, batch_context)

    payload = _extract_document_payload_from_path(
        filename,
        uploaded.path,
        project_id=project_id,
    )
    content = _truncate_document_content(payload.content)
    result = _persist_uploaded_document(
        project_id,
        filename,
        content,
        store=store,
        source_relative_path=uploaded.path.name,
        source_fingerprint=content_fingerprint,
        source_size=uploaded.size,
        blocks=payload.blocks,
        markdown_full=payload.markdown_full,
        parser_provenance=payload.parser_provenance,
        parser_output_sha256=payload.parser_output_sha256,
        ocr_report=payload.ocr_report,
    )
    return _with_upload_batch_context(result, batch_context)


async def ingest_validated_pdf_path(
    project_id: str,
    source_path: Path,
    *,
    expected_sha256: str,
    expected_size: int,
) -> dict[str, Any]:
    """Queue an already validated project-local PDF through normal ingestion.

    Args:
        project_id: Existing project that owns the acquired artifact.
        source_path: PDF path below that project's canonical ``source_files``.
        expected_sha256: Lowercase SHA-256 recorded by acquisition validation.
        expected_size: Exact byte size recorded by acquisition validation.

    Returns:
        Existing resource-ingestion result, including material and runtime job
        identifiers when background extraction is queued.

    Raises:
        ValueError: If the project, path, digest, size, or PDF structure is
            invalid, or if the file changed after acquisition validation.
    """

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be non-empty")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256 or "")):
        raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 4096:
        raise ValueError("expected_size must be an integer of at least 4096 bytes")

    from acquisition.validator import validate_pdf_file

    store = _ensure_upload_project(normalized_project_id)
    source_root = project_data_path(normalized_project_id, "source_files").resolve()
    candidate = Path(source_path).resolve()
    if source_root != candidate.parent and source_root not in candidate.parents:
        raise ValueError("validated PDF must be inside the project source_files directory")
    if candidate.suffix.lower() != ".pdf":
        raise ValueError("validated artifact must use the .pdf extension")

    validation = validate_pdf_file(candidate, max_bytes=max(expected_size, 4096))
    if validation.size_bytes != expected_size or validation.sha256 != expected_sha256:
        raise ValueError("validated PDF changed before ingestion")

    fingerprint = f"sha256:{validation.sha256}"
    filename = _safe_upload_filename(candidate.name)
    pending = _create_pending_uploaded_document(
        normalized_project_id,
        filename,
        store=store,
        source_relative_path=candidate.name,
        source_fingerprint=fingerprint,
        source_size=validation.size_bytes,
    )
    if str(pending.get("status") or "") != "queued":
        material_id = str(pending.get("material_id") or "")
        return {
            **pending,
            **(
                {"open_url": f"/workbench/paper/{material_id}"}
                if material_id
                else {}
            ),
        }
    session_id, job_id = await _start_uploaded_document_extraction_job(
        normalized_project_id,
        str(pending["material_id"]),
        filename,
        candidate,
        source_fingerprint=fingerprint,
        source_size=validation.size_bytes,
        source_relative_path=candidate.name,
    )
    return {
        **pending,
        "job_id": job_id,
        "session_id": session_id,
        "open_url": f"/workbench/paper/{pending['material_id']}",
        "message": "PDF 已可阅读，文本提取将在后台完成。",
    }


def _build_unified_batch_upload_service(filter_engine: Any | None = None) -> Any:
    """Build the shared batch ingestion service from router-local helpers.

    Why:
        Upload and source-folder scan endpoints must share the same parsing,
        dedupe, summary, and chunk persistence contracts while preserving the
        existing monkeypatchable helper boundary used by tests.
    """

    from services.unified_batch_upload_service import UnifiedBatchUploadService

    return UnifiedBatchUploadService(
        persist_upload=_persist_upload_to_source_file,
        load_doc_store=_load_doc_store,
        update_doc_store=_update_doc_store_atomic,
        extract_payload=_extract_document_payload_from_path,
        truncate_content=_truncate_document_content,
        ensure_extracted_text=_ensure_extracted_text,
        write_material_document_content=_write_material_document_content,
        safe_upload_filename=_safe_upload_filename,
        cleanup_uploaded_source=_remove_unreferenced_uploaded_source,
        filter_engine=filter_engine,
    )


def get_memory_adapter():
    """Import and return the shared memory adapter when available."""
    from python_adapter_server import get_memory_adapter as get_adapter
    return get_adapter()


def get_ai_adapter() -> Any:
    """Import and return the shared AI adapter used by association AI mode."""
    global _ai_adapter_instance
    if _ai_adapter_instance is not None:
        return _ai_adapter_instance

    try:
        from layers.ai_adapter import AIAdapter

        _ai_adapter_instance = AIAdapter(
            api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("ARK_API_KEY") or os.environ.get("SILICONFLOW_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL") or os.environ.get("ARK_BASE_URL"),
            model=os.environ.get("OPENAI_MODEL") or os.environ.get("ARK_MODEL"),
        )
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("AI association adapter unavailable: %s", exc)
        _ai_adapter_instance = None
    return _ai_adapter_instance


def _memory_hit_to_dict(raw_hit: Any) -> dict[str, Any] | None:
    """Normalize a memory hit object into a plain mapping for the store layer."""
    if hasattr(raw_hit, "to_dict"):
        normalized = raw_hit.to_dict()
        return normalized if isinstance(normalized, dict) else None
    if isinstance(raw_hit, Mapping):
        return dict(raw_hit)
    return None


def _association_error_to_http_status(message: str) -> int:
    """Map association-layer validation failures to stable HTTP status codes."""
    lowered = message.lower()
    if "not found" in lowered:
        return 404
    return 400


def _clone_association_bundle(
    base_bundle: Any,
    *,
    mode: str,
    ai_enhanced: bool,
    association_angles: Any | None = None,
    continuation_prompts: Any | None = None,
    evidence_gaps: Any | None = None,
    recommended_memory_queries: Any | None = None,
) -> Any:
    """Rebuild a bundle while preserving the stable evidence ranking."""
    from writing_resources import WritingAssociationBundle

    return WritingAssociationBundle(
        project_id=base_bundle.project_id,
        query=base_bundle.query,
        generated_at=base_bundle.generated_at,
        draft_id=base_bundle.draft_id,
        section_id=base_bundle.section_id,
        mode=mode,
        ai_enhanced=ai_enhanced,
        focus_terms=list(base_bundle.focus_terms),
        memory_used=base_bundle.memory_used,
        memory_hit_count=base_bundle.memory_hit_count,
        related_signals=list(base_bundle.related_signals),
        association_angles=list(association_angles if association_angles is not None else base_bundle.association_angles),
        continuation_prompts=list(
            continuation_prompts if continuation_prompts is not None else base_bundle.continuation_prompts
        ),
        evidence_gaps=list(evidence_gaps if evidence_gaps is not None else base_bundle.evidence_gaps),
        recommended_memory_queries=list(
            recommended_memory_queries
            if recommended_memory_queries is not None
            else base_bundle.recommended_memory_queries
        ),
    )


async def _apply_association_mode(base_bundle: Any, mode: str, angle_limit: int) -> Any:
    """Apply AI or No-AI post-processing without mutating the evidence base."""
    adapter = get_ai_adapter()
    from writing_resources import apply_association_mode

    return await asyncio.to_thread(
        apply_association_mode,
        base_bundle,
        mode,
        adapter,
        angle_limit,
    )


# Chunk-store / doc-store internals extracted to ._chunk_store_internals
# Re-export so external imports (),
# endpoint sub-modules (), and tests
# () all keep working.
from ._chunk_store_internals import (  # noqa: E402,F401
    _safe_project_id,
    _get_chunk_store_path,
    _get_doc_store_path,
    _chunk_store_dir,
    _chunk_quarantine_dir,
    _chunk_fts_index_path,
    _sanitize_chunk_filename_stem,
    _material_filename,
    _hash_chunks,
    _atomic_write_text,
    _read_material_jsonl,
    _write_material_jsonl_atomic,
    _load_manifest,
    _chunk_store_hash_version,
    _chunk_store_retrieval_contract,
    _load_chunk_store_materials_for_retrieval,
    _load_doc_store,
    _save_doc_store,
    _update_doc_store_atomic,
    _load_chunk_store,
    _save_chunk_store,
    _update_chunk_store_atomic,
    _update_project_stores_atomic,
    _load_chunk_store_unlocked,
    _save_chunk_store_unlocked,
    _partition_quarantined_chunks,
    _append_chunk_quarantine_log,
)

from ._publication_integrity import (  # noqa: E402,F401
    MaterialPublicationIntegrityError,
    verify_material_publication,
)

# Endpoint sub-modules. Imported here so their @router decorators
# register against the live router instance, and so the endpoint functions remain
# callable as ``resources_router.X`` (legacy direct-call tests rely on this).
from .endpoints_projects import (  # noqa: E402,F401
    create_project,
    get_project,
    list_projects,
    update_project_status,
    update_project_source_folder,
    get_project_reasoning_bias,
    update_project_reasoning_bias,
    optimize_project_reasoning_bias,
    delete_project,
    scan_project_folder,
    create_section,
    get_section,
    list_sections,
    delete_section,
    update_section,
    update_project,
    get_project_stats,
    UpdateSectionRequest,
    UpdateProjectRequest,
)
from .endpoints_materials_drafts import (  # noqa: E402,F401
    create_material,
    get_material,
    list_materials,
    get_material_chunks,
    get_material_suggested_questions,
    delete_material,
    create_draft,
    get_draft,
    list_drafts,
    save_draft,
    get_revision,
    list_revisions,
    restore_revision,
    delete_draft,
    build_writing_association,
)
from .endpoints_search_upload import (  # noqa: E402,F401
    upload_document,
    upload_documents_batch,
    get_project_documents,
    get_project_chunks,
    derive_figure_table_candidates,
    list_material_formula_candidates,
    list_figure_table_candidates,
    search_chunk_refs,
    search_chunks,
    serve_document_file,
    FormulaCandidatePayload,
    FormulaCandidatesResponse,
)
from .endpoints_merged_projects import (  # noqa: E402,F401
    create_merged_project,
    get_project_sources,
    update_project_sources,
    search_multi_projects,
)
from .endpoints_export_stats import (  # noqa: E402,F401
    export_project,
    get_global_stats,
    cleanup_historical_dirty_data,
    batch_delete_materials,
    BatchDeleteRequest,
    CleanupRequest,
)
