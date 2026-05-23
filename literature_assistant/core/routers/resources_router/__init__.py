# -*- coding: utf-8 -*-
"""Resources API Router - Manages projects, sections, drafts, and associations."""

import asyncio
import concurrent.futures as futures
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Callable
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from chunk_size_guard import hard_max_chars, hard_max_tokens, inspect_chunk
from chunk_models import EnrichedChunk
from project_paths import output_path, project_data_path
from models import (
    ProjectPayload,
    SectionPayload,
    MaterialPayload,
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

# Document content store — default location (overridden when project has source_folder)
_DOC_STORE_DIR = output_path("doc_store")
_DOC_STORE_DIR.mkdir(parents=True, exist_ok=True)

# Chunk store — default location (overridden when project has source_folder)
_CHUNK_STORE_DIR = output_path("chunk_store")
_CHUNK_STORE_DIR.mkdir(parents=True, exist_ok=True)
_CHUNK_QUARANTINE_LOG_PATH = output_path("chunk_quarantine.jsonl")

# Thread safety lock for chunk store read-modify-write operations
_CHUNK_STORE_LOCK = threading.Lock()

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


# --- Phase 1 split (2026-05-07): pure helpers extracted to sub-modules ---
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
    _extract_document_content,
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
    _markdown_table_cell,
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
    doc_store = _load_doc_store(project_id)
    chunk_store = _load_chunk_store(project_id)
    material_ids = {material_id} if material_id else set(doc_store.keys()) | set(chunk_store.keys())
    updated = False

    for mid in list(material_ids):
        document = doc_store.get(mid)
        if document is None:
            if mid in chunk_store:
                del chunk_store[mid]
                updated = True
            continue

        title = str(document.get("title") or mid)
        content = str(document.get("content") or "")
        existing_chunks = [chunk for chunk in (chunk_store.get(mid) or []) if str(chunk.get("content") or "").strip()]

        if not content.strip():
            if mid in chunk_store:
                del chunk_store[mid]
                updated = True
            continue

        if not existing_chunks:
            chunk_store[mid] = _chunk_document(mid, title, content)
            updated = True
            continue

        normalized_chunks: list[dict[str, Any]] = []
        for idx, chunk in enumerate(existing_chunks):
            normalized_chunk = dict(chunk)
            changed = False
            if normalized_chunk.get("material_id") != mid:
                normalized_chunk["material_id"] = mid
                changed = True
            if normalized_chunk.get("title") != title:
                normalized_chunk["title"] = title
                changed = True
            if normalized_chunk.get("chunk_index") != idx:
                normalized_chunk["chunk_index"] = idx
                changed = True
            expected_chunk_id = f"{mid}_chunk_{idx}"
            if normalized_chunk.get("chunk_id") != expected_chunk_id:
                normalized_chunk["chunk_id"] = expected_chunk_id
                changed = True
            char_count = len(str(normalized_chunk.get("content") or ""))
            if normalized_chunk.get("char_count") != char_count:
                normalized_chunk["char_count"] = char_count
                changed = True
            normalized_chunks.append(normalized_chunk)
            if changed:
                updated = True

        chunk_store[mid] = normalized_chunks

    if updated:
        _save_chunk_store(project_id, chunk_store)

    return chunk_store


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
    candidates = _iter_scan_files(folder_path)
    existing_doc_store = _load_doc_store(project_id)
    existing_titles = {str(v.get("title") or "") for v in existing_doc_store.values()}
    existing_fingerprints = {
        str(v.get("source_fingerprint") or "")
        for v in existing_doc_store.values()
        if str(v.get("source_fingerprint") or "")
    }

    pending_candidates: list[dict[str, Any]] = []
    skipped_results: list[dict[str, Any]] = []
    failed_results: list[dict[str, Any]] = []

    for file_path in candidates:
        filename = file_path.name
        relative_path = file_path.resolve().relative_to(folder_path.resolve())
        relative_posix = relative_path.as_posix()

        try:
            stat = file_path.stat()
            fingerprint = f"{relative_posix}|{stat.st_size}|{int(stat.st_mtime_ns)}"
        except OSError as exc:
            failed_results.append({"title": relative_posix, "status": "error", "reason": str(exc)})
            continue

        if fingerprint in existing_fingerprints:
            skipped_results.append({"title": relative_posix, "status": "skipped", "reason": "已索引（指纹匹配）"})
            continue

        if relative_posix in existing_titles or filename in existing_titles:
            skipped_results.append({"title": relative_posix, "status": "skipped", "reason": "已索引（路径/文件名匹配）"})
            continue

        pending_candidates.append(
            {
                "path": file_path,
                "relative_path": relative_path,
                "relative_posix": relative_posix,
                "fingerprint": fingerprint,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )

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
                    executor.submit(_extract_scan_candidate_content, item["path"]): item
                    for item in batch
                }
                for future in futures.as_completed(future_map):
                    item = future_map[future]
                    relative_posix = str(item["relative_posix"])
                    relative_path = item["relative_path"]
                    fingerprint = str(item["fingerprint"])

                    content, error_reason = future.result()
                    if error_reason or not content:
                        failed += 1
                        results.append({"title": relative_posix, "status": "error", "reason": error_reason or "无法提取文本"})
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

            content, error_reason = _extract_scan_candidate_content(item["path"])
            if error_reason or not content:
                failed += 1
                results.append({"title": relative_posix, "status": "error", "reason": error_reason or "无法提取文本"})
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
) -> dict[str, Any]:
    """Create a material entry and persist its document/chunk payload."""
    summary = content[:200].replace("\n", " ").strip() if content else f"从文件 {filename} 导入"
    material = store.create_material(
        project_id=project_id,
        title=filename,
        title_en=filename,
        summary=summary,
        summary_en="",
        material_type="reference",
    )

    doc_store = _load_doc_store(project_id)
    doc_store[material.material_id] = {
        "title": filename,
        "content": content,
        "source_relative_path": source_relative_path or filename,
        "source_fingerprint": source_fingerprint or "",
        "source_size": int(source_size or 0),
        "source_mtime": float(source_mtime or 0.0),
    }
    _save_doc_store(project_id, doc_store)

    chunks = _chunk_document(material.material_id, filename, content)
    chunk_store = _load_chunk_store(project_id)
    chunk_store[material.material_id] = chunks
    _save_chunk_store(project_id, chunk_store)

    return {
        "material_id": material.material_id,
        "title": filename,
        "content_length": len(content),
        "chunks": len(chunks),
        "status": "ok",
    }


async def _ingest_uploaded_document(
    project_id: str,
    upload: UploadFile,
    *,
    store: Any,
) -> dict[str, Any]:
    """Read one uploaded file and persist it into the project knowledge base."""
    filename = upload.filename or "unnamed"
    raw = await upload.read()
    content = _truncate_document_content(_extract_document_content(filename, raw))

    normalized = str(content or "").strip()
    known_extract_failures = (
        normalized.startswith("[PDF 文件:"),
        normalized.startswith("[PDF 解析失败:"),
        normalized.startswith("[DOCX 文件:"),
        normalized.startswith("[DOCX 解析失败:"),
        normalized.startswith("[未知格式文件:"),
    )
    if (not normalized) or any(known_extract_failures):
        raise ValueError(
            f"文件“{filename}”未提取到可检索文本。可能是扫描版 PDF、加密文件或解析依赖缺失（建议安装 pymupdf / PyPDF2 / python-docx）"
        )

    return _persist_uploaded_document(project_id, filename, content, store=store)


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


# Phase 4 (2026-05-07): chunk-store / doc-store internals extracted to ._chunk_store_internals
# Re-export so external imports (),
# endpoint sub-modules (), and tests
# () all keep working.
from ._chunk_store_internals import (  # noqa: E402,F401
    _safe_project_id,
    _get_chunk_store_path,
    _get_doc_store_path,
    _chunk_store_dir,
    _chunk_quarantine_dir,
    _sanitize_chunk_filename_stem,
    _material_filename,
    _hash_chunks,
    _atomic_write_text,
    _read_material_jsonl,
    _write_material_jsonl_atomic,
    _load_manifest,
    _load_doc_store,
    _save_doc_store,
    _load_chunk_store,
    _save_chunk_store,
    _update_chunk_store_atomic,
    _load_chunk_store_unlocked,
    _save_chunk_store_unlocked,
    _partition_quarantined_chunks,
    _append_chunk_quarantine_log,
)

# Endpoint sub-modules (Phase 3 split). Imported here so their @router decorators
# register against the live router instance, and so the endpoint functions remain
# callable as ``resources_router.X`` (legacy direct-call tests rely on this).
from .endpoints_projects import (  # noqa: E402,F401
    create_project,
    get_project,
    list_projects,
    update_project_status,
    update_project_source_folder,
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
    search_chunks,
    serve_document_file,
)
from .endpoints_export_stats import (  # noqa: E402,F401
    export_project,
    get_global_stats,
    cleanup_historical_dirty_data,
    batch_delete_materials,
    BatchDeleteRequest,
    CleanupRequest,
)
