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
from typing import Any, Mapping
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from chunk_size_guard import hard_max_chars, hard_max_tokens, inspect_chunk
from chunk_models import EnrichedChunk
from project_paths import output_path
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
CHUNK_OVERLAP = 150    # overlap chars between adjacent chunks
MAX_CHUNKS_PER_MATERIAL = 5  # max chunks returned per document in RAG search (was 2)

# Supported file extensions for folder scanning
_SCAN_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".bib", ".ipynb"}
_SCAN_SKIP_DIRS = {".scholarai", ".git", "node_modules", "__pycache__"}
_SCAN_MODES = {"legacy", "fast"}
_INGEST_MODES = {"none", "query", "full"}


def _iter_scan_files(root: Path) -> list[Path]:
    """Recursively collect supported files under root while skipping internal dirs."""
    candidates: list[Path] = []
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SCAN_SKIP_DIRS]
        current = Path(current_root)
        for filename in files:
            path = current / filename
            if path.suffix.lower() in _SCAN_EXTENSIONS:
                candidates.append(path)
    return candidates


def _build_source_fingerprint(root: Path, path: Path) -> str:
    """Build a stable-ish fingerprint for dedupe across nested folders."""
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    stat = path.stat()
    return f"{rel}|{stat.st_size}|{int(stat.st_mtime_ns)}"


def _extract_zotero_item_key(relative_path: Path) -> str | None:
    """Infer Zotero item key from storage relative path (usually first segment)."""
    if not relative_path.parts:
        return None
    first = str(relative_path.parts[0]).strip()
    if len(first) == 8 and first.isalnum():
        return first.upper()
    return None


def _load_zotero_title_map(storage_root: Path) -> dict[str, str]:
    """Load itemKey -> title from zotero.sqlite when available.

    Zotero commonly stores `storage/` under the same parent as `zotero.sqlite`.
    This is optional; failures should not block ingestion.
    """
    db_path = storage_root.parent / "zotero.sqlite"
    if not db_path.exists():
        return {}

    title_map: dict[str, str] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            cursor = conn.cursor()
            queries = [
                """
                SELECT items.key, itemDataValues.value
                FROM items
                JOIN itemData ON itemData.itemID = items.itemID
                JOIN fields ON fields.fieldID = itemData.fieldID
                JOIN itemDataValues ON itemDataValues.valueID = itemData.valueID
                WHERE fields.fieldName = 'title'
                """,
                """
                SELECT items.key, itemDataValues.value
                FROM items
                JOIN itemData ON itemData.itemID = items.itemID
                JOIN fieldsCombined ON fieldsCombined.fieldID = itemData.fieldID
                JOIN itemDataValues ON itemDataValues.valueID = itemData.valueID
                WHERE fieldsCombined.fieldName = 'title'
                """,
            ]

            for query in queries:
                try:
                    cursor.execute(query)
                except sqlite3.Error:
                    continue
                for key, value in cursor.fetchall():
                    item_key = str(key or "").strip().upper()
                    title = str(value or "").strip()
                    if item_key and title and item_key not in title_map:
                        title_map[item_key] = title
        finally:
            conn.close()
    except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError):
        return {}

    return title_map


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

    When a project has a source_folder, both stores are placed in
    ``{source_folder}/.scholarai/`` so the index lives alongside
    the literature files and can be moved/backed-up with them.
    """
    source_folder = _get_project_source_folder(project_id)
    if source_folder:
        base = Path(source_folder).expanduser().resolve() / _SCHOLAR_SUBDIR
        base.mkdir(parents=True, exist_ok=True)
        return base, base
    return _DOC_STORE_DIR, _CHUNK_STORE_DIR


def _get_doc_store_path(project_id: str) -> Path:
    """Return the JSON doc store path for a given project."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in "_-")
    doc_dir, _ = _resolve_data_dir(project_id)
    return doc_dir / f"{safe_id}.json"


def _load_doc_store(project_id: str) -> dict[str, dict[str, str]]:
    """Load document content store for a project."""
    path = _get_doc_store_path(project_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    # Fallback: check default location (in case project was migrated)
    fallback = _DOC_STORE_DIR / f"{''.join(c for c in project_id if c.isalnum() or c in '_-')}.json"
    if fallback.exists() and fallback != path:
        try:
            return json.loads(fallback.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_doc_store(project_id: str, store: dict[str, dict[str, str]]) -> None:
    """Persist document content store."""
    path = _get_doc_store_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Chunk store helpers — splits documents into overlapping chunks for RAG
# ---------------------------------------------------------------------------
# Layout v2 (per-material JSONL + manifest):
#   {chunk_dir}/{safe_id}/
#       manifest.json            -> {"materials": {mat_id: {"file": "...", "sha256": "...", "count": N}}}
#       {md5(mat_id)[:12]}.jsonl -> one chunk per line (json)
#
# Layout v1 (legacy single JSON):
#   {chunk_dir}/{safe_id}_chunks.json -> {mat_id: [chunk_dicts]}
#
# `_load_chunk_store` reads v2 if present; else v1; else returns {}.
# `_save_chunk_store` always writes v2 incrementally (only changed materials
# are rewritten) and renames any legacy v1 file to ``*.legacy.bak`` on first
# successful migration. The public dict-shaped API is unchanged.

import hashlib as _hashlib  # local alias to avoid touching top-of-file imports


def _safe_project_id(project_id: str) -> str:
    return "".join(c for c in project_id if c.isalnum() or c in "_-")


def _get_chunk_store_path(project_id: str) -> Path:
    """Return the **legacy v1** JSON chunk store path. Kept for backward
    compatibility (callers still use this for existence checks/migration).
    The active v2 layout lives under :func:`_chunk_store_dir`.
    """
    _, chunk_dir = _resolve_data_dir(project_id)
    return chunk_dir / f"{_safe_project_id(project_id)}_chunks.json"


def _chunk_store_dir(project_id: str) -> Path:
    _, chunk_dir = _resolve_data_dir(project_id)
    return chunk_dir / _safe_project_id(project_id)


def _chunk_quarantine_dir(project_id: str) -> Path:
    return _chunk_store_dir(project_id) / "_quarantine"


def _sanitize_chunk_filename_stem(value: str) -> str:
    stem = Path(str(value or "").strip()).stem
    if not stem:
        stem = str(value or "").strip()
    sanitized: list[str] = []
    dash_pending = False
    for ch in stem.lower():
        if ch.isalnum():
            if dash_pending and sanitized:
                sanitized.append("-")
            sanitized.append(ch)
            dash_pending = False
        else:
            dash_pending = True
    normalized = "".join(sanitized).strip("-")
    if not normalized:
        normalized = "material"
    return normalized[:48]


def _material_filename(material_id: str, chunks: list[dict[str, Any]]) -> str:
    title = ""
    for chunk in chunks:
        title = str(
            chunk.get("title")
            or chunk.get("material_title")
            or chunk.get("source_relative_path")
            or ""
        ).strip()
        if title:
            break
    stem = _sanitize_chunk_filename_stem(title or material_id)
    digest = _hashlib.md5(material_id.encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}.jsonl"


def _hash_chunks(chunks: list[dict[str, Any]]) -> str:
    payload = json.dumps(chunks, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return _hashlib.sha256(payload).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as fh:
        tmp = Path(fh.name)
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_material_jsonl(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError:
                    # Tolerate single-line corruption; surrounding lines survive.
                    continue
    except OSError:
        return []
    return chunks


def _write_material_jsonl_atomic(path: Path, chunks: list[dict[str, Any]]) -> None:
    lines = "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks)
    _atomic_write_text(path, lines + ("\n" if lines else ""))


def _load_manifest(project_dir: Path) -> dict[str, Any]:
    manifest_path = project_dir / "manifest.json"
    if not manifest_path.exists():
        return {"version": 2, "materials": {}}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("materials"), dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"version": 2, "materials": {}}


def _load_chunk_store(project_id: str) -> dict[str, list[dict[str, Any]]]:
    """Load chunk store for a project: { material_id: [chunk_dicts] }.

    Reads v2 layout if present; else falls back to v1 (legacy) single file.
    Thread-safe: uses module-level lock to prevent concurrent read-modify-write races.
    """
    with _CHUNK_STORE_LOCK:
        return _load_chunk_store_unlocked(project_id)


def _save_chunk_store(project_id: str, store: dict[str, list[dict[str, Any]]]) -> None:
    """Persist chunk store using v2 incremental layout.

    Only materials whose sha256 differs from the existing manifest are
    rewritten; orphaned per-material files are removed. Any legacy v1 file
    is renamed to ``*.legacy.bak`` after a successful migration write.
    
    Thread-safe: uses module-level lock to prevent concurrent read-modify-write races.
    """
    with _CHUNK_STORE_LOCK:
        _save_chunk_store_unlocked(project_id, store)


def _update_chunk_store_atomic(
    project_id: str,
    updater: callable[[dict[str, list[dict[str, Any]]]], dict[str, list[dict[str, Any]]]]
) -> None:
    """Atomically update chunk store with a user-provided updater function.
    
    This helper ensures the entire read-modify-write sequence is protected by
    the lock, preventing races when multiple threads modify the same project.
    
    Args:
        project_id: The project identifier
        updater: Function that takes the current store dict and returns the
                 updated store dict. Called while holding the lock.
    
    Example:
        def add_chunks(store):
            store[material_id] = new_chunks
            return store
        _update_chunk_store_atomic(project_id, add_chunks)
    """
    with _CHUNK_STORE_LOCK:
        # Call unlocked versions since we already hold the lock
        store = _load_chunk_store_unlocked(project_id)
        updated_store = updater(store)
        _save_chunk_store_unlocked(project_id, updated_store)


def _load_chunk_store_unlocked(project_id: str) -> dict[str, list[dict[str, Any]]]:
    """Internal: Load chunk store WITHOUT acquiring lock.
    
    Only call from within _CHUNK_STORE_LOCK context or via public _load_chunk_store.
    Reads v2 layout if present; else falls back to v1 (legacy) single file.
    """
    project_dir = _chunk_store_dir(project_id)
    manifest_path = project_dir / "manifest.json"
    if manifest_path.exists():
        manifest = _load_manifest(project_dir)
        result: dict[str, list[dict[str, Any]]] = {}
        for material_id, entry in manifest.get("materials", {}).items():
            relative_path = entry.get("relative_path") or entry.get("file")
            if not relative_path:
                continue
            if "_quarantine" in Path(str(relative_path)).parts:
                continue
            result[material_id] = _read_material_jsonl(project_dir / relative_path)
        return result
    # Legacy v1 fallback
    legacy = _get_chunk_store_path(project_id)
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    # Older legacy: chunk_dir / "{safe_id}.json"
    safe_id = _safe_project_id(project_id)
    older = _CHUNK_STORE_DIR / f"{safe_id}.json"
    if older.exists() and older != legacy:
        try:
            data = json.loads(older.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_chunk_store_unlocked(project_id: str, store: dict[str, list[dict[str, Any]]]) -> None:
    """Internal: Persist chunk store WITHOUT acquiring lock.
    
    Only call from within _CHUNK_STORE_LOCK context or via public _save_chunk_store.
    Uses v2 incremental layout; only changed materials are rewritten.
    """
    project_dir = _chunk_store_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    old_manifest = _load_manifest(project_dir)
    old_materials: dict[str, dict[str, Any]] = old_manifest.get("materials", {}) or {}
    new_materials: dict[str, dict[str, Any]] = {}
    used_filenames: set[str] = set()

    for material_id, chunks in store.items():
        chunks_list, quarantined_chunks = _partition_quarantined_chunks(project_id, material_id, list(chunks or []))
        if not chunks_list and quarantined_chunks:
            continue
        chunk_hash = _hash_chunks(chunks_list)
        file_name = _material_filename(material_id, chunks_list)
        # Defensive: collision (extremely unlikely with md5[:8]) — extend.
        suffix = 0
        base = file_name
        while file_name in used_filenames:
            suffix += 1
            file_name = base.replace(".jsonl", f"_{suffix}.jsonl")
        used_filenames.add(file_name)

        target = project_dir / file_name
        prev = old_materials.get(material_id)
        prev_path = ""
        if isinstance(prev, dict):
            prev_path = str(prev.get("relative_path") or prev.get("file") or "")
        needs_write = (
            prev is None
            or prev.get("sha256") != chunk_hash
            or prev_path != file_name
            or not target.exists()
        )
        if needs_write:
            _write_material_jsonl_atomic(target, chunks_list)

        new_materials[material_id] = {
            "relative_path": file_name,
            "sha256": chunk_hash,
            "total_chunks": len(chunks_list),
        }

    # Clean up orphan files (materials removed from store, or renamed).
    keep_files = {entry["relative_path"] for entry in new_materials.values()}
    for entry in old_materials.values():
        old_file = entry.get("relative_path") or entry.get("file")
        if not old_file or old_file in keep_files:
            continue
        orphan = project_dir / old_file
        if orphan.exists():
            try:
                orphan.unlink()
            except OSError:
                pass

    manifest_payload = {"version": 2, "materials": new_materials}
    _atomic_write_text(
        project_dir / "manifest.json",
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
    )

    # One-shot legacy migration: rename v1 file out of the way after first
    # successful v2 write so future loads use v2 directly.
    legacy = _get_chunk_store_path(project_id)
    if legacy.exists():
        backup = legacy.with_suffix(legacy.suffix + ".legacy.bak")
        try:
            os.replace(legacy, backup)
        except OSError:
            pass


def _partition_quarantined_chunks(
    project_id: str,
    material_id: str,
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    rejected_metrics: list[dict[str, Any]] = []
    for chunk in chunks:
        metrics = inspect_chunk(chunk)
        if metrics["is_oversize"]:
            rejected.append(chunk)
            rejected_metrics.append(metrics)
        else:
            accepted.append(chunk)

    quarantine_dir = _chunk_quarantine_dir(project_id)
    digest = _hashlib.md5(material_id.encode("utf-8")).hexdigest()[:8]
    for path in quarantine_dir.glob(f"*_{digest}.jsonl"):
        try:
            path.unlink()
        except OSError:
            pass

    if not rejected:
        return accepted, rejected

    quarantine_dir.mkdir(parents=True, exist_ok=True)
    quarantine_name = _material_filename(material_id, rejected)
    quarantine_path = quarantine_dir / quarantine_name
    _write_material_jsonl_atomic(quarantine_path, rejected)
    _append_chunk_quarantine_log(
        project_id=project_id,
        material_id=material_id,
        rejected_metrics=rejected_metrics,
        quarantine_path=quarantine_path,
    )
    return accepted, rejected


def _append_chunk_quarantine_log(
    *,
    project_id: str,
    material_id: str,
    rejected_metrics: list[dict[str, Any]],
    quarantine_path: Path,
) -> None:
    if not rejected_metrics:
        return
    _CHUNK_QUARANTINE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "material_id": material_id,
        "event": "chunk_quarantined",
        "quarantined_chunk_count": len(rejected_metrics),
        "max_char_count": max(int(item["char_count"]) for item in rejected_metrics),
        "max_token_count": max(int(item["token_count"]) for item in rejected_metrics),
        "chunk_hard_max_chars": hard_max_chars(),
        "chunk_hard_max_tokens": hard_max_tokens(),
        "quarantine_relative_path": str(quarantine_path.relative_to(_chunk_store_dir(project_id))),
    }
    with _CHUNK_QUARANTINE_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _tokenize_search_text(text: str) -> set[str]:
    """Tokenize mixed Chinese/English text for lightweight keyword retrieval."""
    normalized = text.lower().strip()
    if not normalized:
        return set()

    latin_tokens = re.findall(r"[a-z0-9_]+", normalized)
    cjk_chars = [ch for ch in normalized if "\u4e00" <= ch <= "\u9fff"]
    cjk_bigrams = ["".join(cjk_chars[idx:idx + 2]) for idx in range(len(cjk_chars) - 1)]
    cjk_tokens = cjk_bigrams or cjk_chars
    return set(latin_tokens + cjk_tokens)


def _normalize_chunk_dedup_key(content: str) -> str:
    """Create a lightweight dedupe key for near-identical chunk content."""
    normalized = re.sub(r"\s+", " ", content).strip().lower()
    return normalized[:300]


def _select_diverse_top_chunks(
    scored_chunks: list[tuple[float, dict[str, Any]]],
    top_k: int,
    max_chunks_per_material: int = MAX_CHUNKS_PER_MATERIAL,
) -> list[tuple[float, dict[str, Any]]]:
    """Select top chunks while preserving material diversity for RAG context.

    The first pass prefers the strongest chunk from each material so the LLM sees
    broader evidence coverage. Later passes add additional chunks from the same
    material only when there is still room.
    """
    positive_chunks = [(score, chunk) for score, chunk in scored_chunks if score > 0]
    if not positive_chunks:
        return []

    grouped: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    material_order: list[str] = []
    for score, chunk in positive_chunks:
        material_key = str(chunk.get("material_id") or "")
        if material_key not in grouped:
            grouped[material_key] = []
            material_order.append(material_key)
        grouped[material_key].append((score, chunk))

    selected: list[tuple[float, dict[str, Any]]] = []
    seen_content_keys: set[tuple[str, str]] = set()

    for rank in range(max_chunks_per_material):
        added_this_round = False
        for material_key in material_order:
            material_chunks = grouped.get(material_key, [])
            if rank >= len(material_chunks):
                continue

            score, chunk = material_chunks[rank]
            content_key = _normalize_chunk_dedup_key(str(chunk.get("content") or ""))
            dedupe_key = (material_key, content_key)
            if dedupe_key in seen_content_keys:
                continue

            selected.append((score, chunk))
            seen_content_keys.add(dedupe_key)
            added_this_round = True

            if len(selected) >= top_k:
                return selected

        if not added_this_round:
            break

    return selected


def _score_chunks_for_query(
    chunks: list[dict[str, Any]],
    query: str,
) -> list[tuple[float, dict[str, Any]]]:
    """Score chunk dictionaries for a keyword-style RAG query.

    Args:
        chunks: List of chunk payload dictionaries. Non-dict items are ignored
            to keep legacy stores readable after partial migrations.
        query: Non-empty user query text.

    Returns:
        A descending score/chunk list suitable for diversity selection.
    """
    if not isinstance(chunks, list):
        raise TypeError("chunks must be a list of chunk dictionaries")

    query_text = str(query or "").lower().strip()
    if not query_text:
        return []

    query_tokens = _tokenize_search_text(query_text)
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue

        title = str(chunk.get("title", "")).lower()
        text = str(chunk.get("content", "")).lower()
        combined = f"{title}\n{text}".strip()
        chunk_tokens = _tokenize_search_text(combined)

        score = 0.0
        if query_text in combined:
            score += 12.0
        if query_text in title:
            score += 4.0

        matched_tokens = query_tokens & chunk_tokens
        score += len(matched_tokens) * 2.0
        if query_tokens:
            score += (len(matched_tokens) / len(query_tokens)) * 4.0

        for token in query_tokens:
            if len(token) > 1 and token in title:
                score += 1.5

        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


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


def _split_text_into_chunks(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks using recursive separators.

    Uses paragraph → sentence → word boundaries, similar to
    LangChain RecursiveCharacterTextSplitter but without the dependency.
    """
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    separators = ["\n\n", "\n", "。", ".", "！", "!", "？", "?", "；", ";", " "]
    return _recursive_split(text, separators, chunk_size, chunk_overlap)


def _recursive_split(
    text: str,
    separators: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Recursively split text by trying each separator in order."""
    if len(text) <= chunk_size:
        return [text]

    # Find best separator for this text
    best_sep = ""
    for sep in separators:
        if sep in text:
            best_sep = sep
            break

    if not best_sep:
        # No separator found — force split by character
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            start = end - chunk_overlap if end < len(text) else end
        return chunks

    # Split by separator and merge into chunks
    parts = text.split(best_sep)
    chunks = []
    current = ""

    for part in parts:
        test = current + best_sep + part if current else part
        if len(test) <= chunk_size:
            current = test
        else:
            if current:
                chunks.append(current)
            if len(part) > chunk_size:
                # Part itself is too long — recurse with next separator
                sub_chunks = _recursive_split(
                    part, separators[separators.index(best_sep) + 1:] if best_sep in separators else [],
                    chunk_size, chunk_overlap,
                )
                chunks.extend(sub_chunks)
                current = ""
            else:
                current = part

    if current:
        chunks.append(current)

    # Apply overlap between chunks
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            overlap_text = prev[-chunk_overlap:] if len(prev) > chunk_overlap else prev
            overlapped.append(overlap_text + chunks[i])
        chunks = overlapped

    return chunks


def _detect_chunk_type(block: str) -> str:
    """Classify one text block into narrative/list/table/formula."""
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return "narrative"

    table_like_lines = sum(1 for line in lines if "|" in line)
    if table_like_lines >= max(2, len(lines) // 2):
        return "table"

    list_like_lines = sum(1 for line in lines if re.match(r"^([\-\*\u2022]|\d+[\.)])\s+", line))
    if list_like_lines >= max(1, len(lines) // 2):
        return "list"

    formula_like_lines = sum(1 for line in lines if re.search(r"[=+\-*/^]|\\\(|\\\)|∑|∫", line))
    if formula_like_lines >= max(1, len(lines) // 2):
        return "formula"

    return "narrative"


def _extract_section_title_from_line(line: str) -> str | None:
    """Extract section title from common heading patterns."""
    stripped = line.strip()
    if not stripped:
        return None

    markdown_match = re.match(r"^#+\s+(.+)$", stripped)
    if markdown_match:
        return markdown_match.group(1).strip()

    cjk_heading_match = re.match(r"^第[一二三四五六七八九十百千0-9]+[章节部分]\s*(.+)?$", stripped)
    if cjk_heading_match:
        suffix = (cjk_heading_match.group(1) or "").strip()
        return suffix or stripped

    return None


def structure_aware_chunk(
    text: str,
    material_id: str,
    title: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[EnrichedChunk]:
    """Generate enriched chunks with section + block-type awareness."""
    if not text.strip():
        return []

    chunks: list[EnrichedChunk] = []
    section_title = "正文"
    chunk_index = 0

    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        maybe_heading = _extract_section_title_from_line(lines[0])
        content_lines = lines
        if maybe_heading:
            section_title = maybe_heading
            content_lines = lines[1:] if len(lines) > 1 else []

        block_content = "\n".join(content_lines).strip()
        if not block_content:
            continue

        chunk_type = _detect_chunk_type(block_content)
        raw_segments = [block_content]
        if chunk_type == "narrative":
            raw_segments = _split_text_into_chunks(block_content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        for raw_segment in raw_segments:
            raw_text = str(raw_segment or "").strip()
            if not raw_text:
                continue

            prefixed_content = f"[文献: {title}][章节: {section_title}][类型: {chunk_type}]\n{raw_text}"
            chunks.append(
                EnrichedChunk(
                    chunk_id=f"{material_id}_chunk_{chunk_index}",
                    material_id=material_id,
                    title=title,
                    section_title=section_title,
                    chunk_index=chunk_index,
                    content=prefixed_content,
                    raw_content=raw_text,
                    chunk_type=chunk_type,
                    char_count=len(prefixed_content),
                )
            )
            chunk_index += 1

    return chunks


def _chunk_document(
    material_id: str,
    title: str,
    content: str,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """Chunk a document and return chunk metadata list."""
    enriched_chunks = structure_aware_chunk(
        text=content,
        material_id=material_id,
        title=title,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return [
        {
            "chunk_id": chunk.chunk_id,
            "material_id": chunk.material_id,
            "title": chunk.title,
            "section_title": chunk.section_title,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "raw_content": chunk.raw_content,
            "chunk_type": chunk.chunk_type,
            "char_count": chunk.char_count,
            "page": chunk.page,
            "embedding": chunk.embedding,
            "keywords": chunk.keywords,
        }
        for chunk in enriched_chunks
    ]


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


def _resolve_scan_workers(requested_workers: int | None) -> int:
    """Resolve scan worker count for I/O-bound extraction tasks.

    Uses a conservative upper bound to avoid exhausting descriptors/memory when
    indexing very large Zotero folders.
    """
    process_cpu_count = getattr(os, "process_cpu_count", None)
    process_cpu = process_cpu_count() if callable(process_cpu_count) else None
    default_workers = min(32, (process_cpu or os.cpu_count() or 1) + 4)
    if requested_workers is None:
        return default_workers
    return max(1, min(int(requested_workers), 64))


def _iter_scan_batches(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    """Split scan workload into fixed-size batches."""
    if batch_size <= 0:
        return [items]
    return [items[idx: idx + batch_size] for idx in range(0, len(items), batch_size)]


def _extract_scan_candidate_content(file_path: Path) -> tuple[str | None, str | None]:
    """Extract candidate text for scan-folder ingestion.

    Returns:
        (content, None) on success, or (None, reason) on failure.
    """
    try:
        raw = file_path.read_bytes()
        content = _truncate_document_content(_extract_document_content(file_path.name, raw))
        normalized = str(content or "").strip()
        if not normalized or _is_extraction_failure_placeholder(normalized):
            return None, "无法提取文本"
        return content, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


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


def _score_pending_candidate_for_query(
    query_tokens: set[str],
    relative_posix: str,
    zotero_title: str,
) -> float:
    """Score an unindexed file candidate using filename/path/title signals."""
    query_text = " ".join(sorted(query_tokens))
    normalized_path = re.sub(r"[_\-./\\]+", " ", relative_posix.lower())
    relative_tokens = _tokenize_search_text(normalized_path)
    title_tokens = _tokenize_search_text(zotero_title.lower()) if zotero_title else set()
    matched = query_tokens & (relative_tokens | title_tokens)

    score = float(len(matched) * 3)
    if query_text and query_text in normalized_path:
        score += 6.0
    if query_text and zotero_title and query_text in zotero_title.lower():
        score += 8.0

    if query_tokens:
        score += (len(matched) / len(query_tokens)) * 5.0

    return score


def _select_query_pending_candidates(
    pending_candidates: list[dict[str, Any]],
    query: str,
    zotero_title_map: dict[str, str],
    ingest_limit: int,
) -> list[dict[str, Any]]:
    """Select query-relevant subset from pending candidates."""
    query_tokens = _tokenize_search_text(str(query or "").lower())
    if not query_tokens:
        return pending_candidates[:ingest_limit]

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in pending_candidates:
        relative_path = item["relative_path"]
        zotero_key = _extract_zotero_item_key(relative_path)
        zotero_title = zotero_title_map.get(zotero_key, "") if zotero_key else ""
        score = _score_pending_candidate_for_query(query_tokens, str(item["relative_posix"]), zotero_title)
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:ingest_limit]]


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


def _normalize_project_title_for_cleanup(title: str) -> str:
    """Normalize project title for duplicate detection in maintenance cleanup."""
    normalized = re.sub(r"\s+", " ", str(title or "").strip()).lower()
    return normalized


def _is_extraction_failure_placeholder(content: str) -> bool:
    """Check whether a stored document content is an extraction placeholder."""
    normalized = str(content or "").strip()
    if not normalized:
        return True
    return any(
        normalized.startswith(prefix)
        for prefix in (
            "[PDF 文件:",
            "[PDF 解析失败:",
            "[DOCX 文件:",
            "[DOCX 解析失败:",
            "[未知格式文件:",
        )
    )


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


@router.post("/project", response_model=ProjectPayload)
async def create_project(request: CreateProjectRequest) -> ProjectPayload:
    """Create a new writing project."""
    from writing_resources import ContentType
    store = get_writing_resource_store()
    try:
        content_type = ContentType(request.content_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid content_type: {request.content_type}")

    project = store.create_project(
        title=request.title,
        description=request.description,
        content_type=content_type,
        user_id=request.user_id,
        tags=request.tags,
        metadata={"source_folder": request.source_folder} if request.source_folder else {},
    )
    d = project.to_dict()
    d["source_folder"] = str(project.metadata.get("source_folder", ""))
    # If a source_folder is provided, create the .scholarai subdirectory upfront
    if request.source_folder:
        try:
            (Path(request.source_folder).expanduser().resolve() / _SCHOLAR_SUBDIR).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create .scholarai dir in source_folder: %s", exc)
    return ProjectPayload(**d)


@router.get("/project/{project_id}", response_model=ProjectPayload)
async def get_project(project_id: str) -> ProjectPayload:
    """Get a project by ID."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    d = project.to_dict()
    d["source_folder"] = str(project.metadata.get("source_folder", ""))
    return ProjectPayload(**d)


@router.get("/projects", response_model=list[ProjectPayload])
async def list_projects(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
) -> list[ProjectPayload]:
    """List all projects, optionally filtered by user. Supports pagination via query params."""
    store = get_writing_resource_store()
    projects = store.list_projects(user_id=user_id)
    all_payloads = []
    for p in projects:
        d = p.to_dict()
        d["source_folder"] = str(p.metadata.get("source_folder", ""))
        all_payloads.append(ProjectPayload(**d))
    # Pagination is opt-in: if caller doesn't pass page/page_size, returns full list
    return all_payloads


@router.put("/project/{project_id}/status")
async def update_project_status(
    project_id: str,
    status: str = Query(..., description="New status"),
) -> ProjectPayload:
    """Update project status."""
    from writing_resources import ProjectStatus
    store = get_writing_resource_store()
    try:
        project_status = ProjectStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    project = store.update_project_status(project_id, project_status)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    d = project.to_dict()
    d["source_folder"] = str(project.metadata.get("source_folder", ""))
    return ProjectPayload(**d)


@router.put("/project/{project_id}/source-folder")
async def update_project_source_folder(
    project_id: str,
    source_folder: str = Query(..., description="绝对路径，留空则恢复默认存储位置"),
) -> ProjectPayload:
    """Update the source_folder of a project.

    When set, chunk / doc store JSON files will be saved inside
    ``{source_folder}/.scholarai/`` alongside the user's literature files.
    """
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    new_metadata = dict(project.metadata)
    new_metadata["source_folder"] = source_folder.strip()
    updated = store.update_project(project_id, metadata=new_metadata)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update project metadata")
    if source_folder.strip():
        try:
            (Path(source_folder.strip()).expanduser().resolve() / _SCHOLAR_SUBDIR).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create .scholarai dir: %s", exc)
    d = updated.to_dict()
    d["source_folder"] = str(updated.metadata.get("source_folder", ""))
    return ProjectPayload(**d)


@router.delete("/project/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    """Delete a project and all its associated resources."""
    store = get_writing_resource_store()
    deleted = store.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    # Clean up doc_store JSON for this project
    doc_store_path = _get_doc_store_path(project_id)
    if doc_store_path.exists():
        try:
            doc_store_path.unlink()
        except OSError:
            logger.warning("Failed to remove doc_store file: %s", doc_store_path)
    chunk_store_path = _get_chunk_store_path(project_id)
    if chunk_store_path.exists():
        try:
            chunk_store_path.unlink()
        except OSError:
            logger.warning("Failed to remove chunk_store file: %s", chunk_store_path)
    return {"status": "deleted", "project_id": project_id}


@router.post("/project/{project_id}/scan-folder")
async def scan_project_folder(
    project_id: str,
    scan_mode: str = Query(
        "fast",
        description="扫描模式：legacy（串行兼容）/ fast（元数据预扫 + 分批并发解析）",
    ),
    batch_size: int = Query(
        24,
        ge=1,
        le=256,
        description="fast 模式下每批处理文件数",
    ),
    max_workers: int = Query(
        8,
        ge=1,
        le=64,
        description="fast 模式下并发 worker 数（建议 4-16）",
    ),
) -> dict[str, Any]:
    """Scan the project's source_folder and ingest all literature files.

    Reads all supported files (.pdf, .docx, .doc, .txt, .md) from the project's
    source_folder and indexes them into the knowledge base.  Already-indexed
    files (same filename) are skipped.  Returns a summary of what was processed.
    """
    store = _ensure_upload_project(project_id)
    project_obj = get_writing_resource_store().get_project(project_id)
    if not project_obj:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    source_folder = str(project_obj.metadata.get("source_folder", "")).strip()
    if not source_folder:
        raise HTTPException(
            status_code=400,
            detail="该项目没有设置文献文件夹（source_folder）。请先在项目设置中指定文件夹路径。",
        )
    folder_path = Path(source_folder).expanduser().resolve()
    if not folder_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"文件夹不存在或无法访问：{folder_path}",
        )

    normalized_mode = str(scan_mode or "").strip().lower()
    if normalized_mode not in _SCAN_MODES:
        raise HTTPException(status_code=400, detail=f"scan_mode 不支持: {scan_mode}，可选值: legacy, fast")

    # Collect candidate files recursively (Zotero storage often has hundreds of subfolders)
    candidate_payload = _collect_pending_scan_candidates(project_id, folder_path)
    candidates = candidate_payload["candidates"]
    pending_candidates = candidate_payload["pending"]
    existing_titles = candidate_payload["existing_titles"]
    existing_fingerprints = candidate_payload["existing_fingerprints"]
    skipped_results = list(candidate_payload["skipped_results"])
    failed_results = list(candidate_payload["failed_results"])

    zotero_title_map = _load_zotero_title_map(folder_path)
    ingest_payload = _ingest_pending_candidates(
        project_id,
        store=store,
        pending_candidates=pending_candidates,
        zotero_title_map=zotero_title_map,
        scan_mode=normalized_mode,
        batch_size=batch_size,
        max_workers=max_workers,
        existing_titles=existing_titles,
        existing_fingerprints=existing_fingerprints,
    )

    results = [*skipped_results, *failed_results, *list(ingest_payload["results"])]
    skipped = len(skipped_results)
    failed = len(failed_results) + int(ingest_payload["failed"])

    return {
        "project_id": project_id,
        "folder": str(folder_path),
        "scan_mode": str(ingest_payload["scan_mode"]),
        "batch_size": batch_size,
        "workers": int(ingest_payload["workers"]),
        "total_files": len(candidates),
        "queued": len(pending_candidates),
        "indexed": int(ingest_payload["indexed"]),
        "skipped": skipped,
        "failed": failed,
        "total_chunks": int(ingest_payload["total_chunks"]),
        "results": results,
    }


@router.post("/section", response_model=SectionPayload)
async def create_section(request: CreateSectionRequest) -> SectionPayload:
    """Create a section within a project."""
    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    section = store.create_section(
        project_id=request.project_id,
        title=request.title,
        order=request.order,
        description=request.description,
    )
    return SectionPayload(**section.to_dict())


@router.get("/section/{section_id}", response_model=SectionPayload)
async def get_section(section_id: str) -> SectionPayload:
    """Get a section by ID."""
    store = get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"Section not found: {section_id}")
    return SectionPayload(**section.to_dict())


@router.get("/sections", response_model=list[SectionPayload])
async def list_sections(project_id: str = Query(...)) -> list[SectionPayload]:
    """List all sections in a project."""
    store = get_writing_resource_store()
    sections = store.list_sections(project_id)
    return [SectionPayload(**s.to_dict()) for s in sections]


@router.post("/material", response_model=MaterialPayload)
async def create_material(request: CreateMaterialRequest) -> MaterialPayload:
    """Create a project-scoped reference material."""
    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    material = store.create_material(
        project_id=request.project_id,
        title=request.title,
        title_en=request.title_en,
        summary=request.summary,
        summary_en=request.summary_en,
        material_type=request.type,
        focus_points=request.focus_points,
        focus_points_en=request.focus_points_en,
    )
    return MaterialPayload(**material.to_dict())


@router.get("/material/{material_id}", response_model=MaterialPayload)
async def get_material(material_id: str) -> MaterialPayload:
    """Get a project-scoped material by ID."""
    store = get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail=f"Material not found: {material_id}")
    return MaterialPayload(**material.to_dict())


@router.get("/materials", response_model=list[MaterialPayload])
async def list_materials(project_id: str = Query(...)) -> list[MaterialPayload]:
    """List all materials attached to a project."""
    store = get_writing_resource_store()
    materials = store.list_materials(project_id)
    return [MaterialPayload(**material.to_dict()) for material in materials]


@router.post("/upload")
async def upload_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a document file, extract text content, and store as a material."""
    store = _ensure_upload_project(project_id)
    try:
        return await _ingest_uploaded_document(project_id, file, store=store)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/upload/batch")
async def upload_documents_batch(
    project_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """Upload multiple knowledge-base documents in one request and summarize outcomes."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    store = _ensure_upload_project(project_id)
    results: list[dict[str, Any]] = []
    total_chunks = 0
    successful_files = 0
    failed_files = 0

    for upload in files:
        filename = upload.filename or "unnamed"
        try:
            result = await _ingest_uploaded_document(project_id, upload, store=store)
            total_chunks += int(result.get("chunks") or 0)
            successful_files += 1
            results.append(result)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            failed_files += 1
            results.append({
                "title": filename,
                "status": "error",
                "error": str(exc),
            })

    return {
        "project_id": project_id,
        "total_files": len(files),
        "successful_files": successful_files,
        "failed_files": failed_files,
        "total_chunks": total_chunks,
        "results": results,
    }


@router.get("/documents")
async def get_project_documents(project_id: str = Query(...)) -> list[dict[str, str]]:
    """Get all document contents for a project (for RAG context)."""
    doc_store = _load_doc_store(project_id)
    return [
        {"material_id": mid, "title": doc["title"], "content": doc["content"]}
        for mid, doc in doc_store.items()
    ]


@router.get("/chunks")
async def get_project_chunks(
    project_id: str = Query(...),
    material_id: str | None = Query(None, description="Filter by material"),
) -> dict[str, Any]:
    """Get chunked document content for a project (for smarter RAG context).

    Returns chunks instead of full documents, allowing the frontend to
    send only relevant chunks to the LLM.
    """
    chunk_store = _ensure_project_chunks(project_id, material_id=material_id)
    all_chunks: list[dict[str, Any]] = []
    for mid, chunks in chunk_store.items():
        if material_id and mid != material_id:
            continue
        all_chunks.extend(chunks)
    return {
        "project_id": project_id,
        "total_chunks": len(all_chunks),
        "chunks": all_chunks,
    }


@router.get("/chunks/search")
async def search_chunks(
    project_id: str = Query(...),
    query: str = Query(..., min_length=1, description="搜索词"),
    top_k: int = Query(10, ge=1, le=50, description="返回最相关的 N 个chunk"),
    ingest_mode: str = Query("none", description="提问前置入库模式：none/query/full"),
    ingest_limit: int = Query(8, ge=1, le=128, description="query 模式最多入库候选文件数"),
    scan_mode: str = Query("fast", description="入库执行模式：legacy/fast"),
    scan_batch_size: int = Query(24, ge=1, le=256, description="入库批大小"),
    scan_max_workers: int = Query(8, ge=1, le=64, description="入库并发 worker 数"),
) -> dict[str, Any]:
    """Chunk search with optional query-driven pre-ingestion.

    - ingest_mode=none: pure retrieval on existing chunks
    - ingest_mode=query: ingest only query-relevant pending files
    - ingest_mode=full: ingest all pending files before retrieval
    """
    normalized_ingest_mode = str(ingest_mode or "").strip().lower()
    if normalized_ingest_mode not in _INGEST_MODES:
        raise HTTPException(status_code=400, detail=f"ingest_mode 不支持: {ingest_mode}，可选值: none, query, full")

    ingest_meta: dict[str, Any] = {
        "enabled": normalized_ingest_mode != "none",
        "mode": normalized_ingest_mode,
        "indexed": 0,
        "queued": 0,
        "failed": 0,
        "skipped": 0,
        "workers": 1,
    }

    if normalized_ingest_mode != "none":
        store = _ensure_upload_project(project_id)
        project_obj = get_writing_resource_store().get_project(project_id)
        source_folder = str((project_obj.metadata.get("source_folder") if project_obj else "") or "").strip()

        if source_folder:
            folder_path = Path(source_folder).expanduser().resolve()
            if folder_path.is_dir():
                candidate_payload = _collect_pending_scan_candidates(project_id, folder_path)
                pending_candidates = list(candidate_payload["pending"])
                ingest_meta["skipped"] = len(candidate_payload["skipped_results"])
                ingest_meta["failed"] = len(candidate_payload["failed_results"])

                zotero_title_map = _load_zotero_title_map(folder_path)
                if normalized_ingest_mode == "query":
                    pending_candidates = _select_query_pending_candidates(
                        pending_candidates,
                        query=query,
                        zotero_title_map=zotero_title_map,
                        ingest_limit=ingest_limit,
                    )

                ingest_meta["queued"] = len(pending_candidates)
                if pending_candidates:
                    ingest_payload = _ingest_pending_candidates(
                        project_id,
                        store=store,
                        pending_candidates=pending_candidates,
                        zotero_title_map=zotero_title_map,
                        scan_mode=scan_mode,
                        batch_size=scan_batch_size,
                        max_workers=scan_max_workers,
                        existing_titles=candidate_payload["existing_titles"],
                        existing_fingerprints=candidate_payload["existing_fingerprints"],
                    )
                    ingest_meta["indexed"] = int(ingest_payload["indexed"])
                    ingest_meta["failed"] = int(ingest_meta["failed"]) + int(ingest_payload["failed"])
                    ingest_meta["workers"] = int(ingest_payload["workers"])
            else:
                ingest_meta["error"] = f"source_folder 无法访问: {folder_path}"
        else:
            ingest_meta["error"] = "项目未配置 source_folder，已跳过前置入库"

    chunk_store = _ensure_project_chunks(project_id)
    all_chunks: list[dict[str, Any]] = []
    for chunks in chunk_store.values():
        all_chunks.extend(chunks)

    if not all_chunks:
        return {"project_id": project_id, "query": query, "ingest": ingest_meta, "results": []}

    top = _select_diverse_top_chunks(
        _score_chunks_for_query(all_chunks, query),
        top_k=top_k,
    )
    return {
        "project_id": project_id,
        "query": query,
        "ingest": ingest_meta,
        "results": [{"score": round(s, 2), **c} for s, c in top if s > 0],
    }


@router.get("/material/{material_id}/chunks")
async def get_material_chunks(
    material_id: str,
    project_id: str = Query(...),
) -> dict[str, Any]:
    """Get chunks for a specific material."""
    chunk_store = _ensure_project_chunks(project_id, material_id=material_id)
    chunks = chunk_store.get(material_id, [])
    return {
        "material_id": material_id,
        "total_chunks": len(chunks),
        "chunks": chunks,
    }


@router.post("/draft", response_model=DraftPayload)
async def create_draft(request: CreateDraftRequest) -> DraftPayload:
    """Create a new draft."""
    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    if request.section_id:
        section = store.get_section(request.section_id)
        if not section:
            raise HTTPException(status_code=404, detail=f"Section not found: {request.section_id}")

    draft = store.create_draft(
        project_id=request.project_id,
        title=request.title,
        content=request.content,
        section_id=request.section_id,
        edited_by=request.edited_by,
        citation_anchors=[anchor.model_dump() for anchor in request.citation_anchors],
    )
    return DraftPayload(**draft.to_dict())


@router.get("/draft/{draft_id}", response_model=DraftPayload)
async def get_draft(draft_id: str) -> DraftPayload:
    """Get a draft by ID."""
    store = get_writing_resource_store()
    draft = store.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")
    return DraftPayload(**draft.to_dict())


@router.get("/drafts", response_model=list[DraftPayload])
async def list_drafts(
    project_id: str = Query(...),
    section_id: str | None = Query(None),
) -> list[DraftPayload]:
    """List all drafts, optionally filtered by section."""
    store = get_writing_resource_store()
    drafts = store.list_drafts(project_id, section_id=section_id)
    return [DraftPayload(**d.to_dict()) for d in drafts]


@router.put("/draft/{draft_id}")
async def save_draft(draft_id: str, request: SaveDraftRequest) -> DraftPayload:
    """Save draft content."""
    store = get_writing_resource_store()
    draft = store.save_draft(
        draft_id,
        request.content,
        edited_by=request.edited_by,
        citation_anchors=[anchor.model_dump() for anchor in request.citation_anchors],
        create_revision=True,
    )
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")
    return DraftPayload(**draft.to_dict())


@router.get("/revision/{revision_id}", response_model=RevisionPayload)
async def get_revision(revision_id: str) -> RevisionPayload:
    """Get a revision by ID."""
    store = get_writing_resource_store()
    revision = store.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail=f"Revision not found: {revision_id}")
    return RevisionPayload(**revision.to_dict())


@router.get("/revisions", response_model=list[RevisionPayload])
async def list_revisions(draft_id: str = Query(...)) -> list[RevisionPayload]:
    """List all revisions for a draft."""
    store = get_writing_resource_store()
    revisions = store.list_revisions(draft_id)
    return [RevisionPayload(**r.to_dict()) for r in revisions]


@router.post("/draft/{draft_id}/restore")
async def restore_revision(
    draft_id: str,
    revision_id: str = Query(...),
) -> DraftPayload:
    """Restore a draft from a revision."""
    store = get_writing_resource_store()
    draft = store.restore_revision(draft_id, revision_id)
    if not draft:
        raise HTTPException(
            status_code=404,
            detail=f"Draft {draft_id} or revision {revision_id} not found",
        )
    return DraftPayload(**draft.to_dict())


@router.post("/association", response_model=WritingAssociationPayload)
async def build_writing_association(
    request: BuildAssociationRequest,
) -> WritingAssociationPayload:
    """Build associative writing guidance from project state, retrieval evidence, and mode."""
    store = get_writing_resource_store()
    memory_hits: list[dict[str, Any]] = []

    if request.use_memory:
        adapter = get_memory_adapter()
        if adapter is not None:
            memory_query = request.memory_query.strip() if request.memory_query else request.query
            try:
                memory_response = adapter.search(
                    query=memory_query,
                    wing=request.wing,
                    room=request.room,
                    limit=request.memory_limit,
                )
            except Exception as exc:  # pragma: no cover - optional dependency path
                logger.warning("Memory association lookup failed: %s", exc)
                memory_response = None

            if memory_response is not None and getattr(memory_response, "available", False):
                raw_results = getattr(memory_response, "results", [])
                for raw_hit in raw_results:
                    normalized_hit = _memory_hit_to_dict(raw_hit)
                    if normalized_hit is not None:
                        memory_hits.append(normalized_hit)

    try:
        bundle = store.build_association_bundle(
            project_id=request.project_id,
            query=request.query,
            draft_id=request.draft_id,
            section_id=request.section_id,
            memory_hits=memory_hits,
            retrieval_hits=request.retrieval_hits,
            signal_limit=request.signal_limit,
            angle_limit=request.angle_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_association_error_to_http_status(str(exc)),
            detail=str(exc),
        ) from exc

    bundle = await _apply_association_mode(bundle, request.mode, request.angle_limit)
    return WritingAssociationPayload(**bundle.to_dict())


# =========================================================================
# Export Endpoints (learned from openhanako desk.js + open-webui export patterns)
# =========================================================================

class ProjectExportFormat(str, __import__("enum").Enum):
    MARKDOWN = "markdown"
    JSON = "json"


def _strip_citation_tokens(value: str) -> str:
    return re.sub(r"\[\^([^\]]+)\]", "", value).replace("\n", " ").strip()


def _shorten_export_text(value: str, max_length: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1].rstrip()}…"


def _material_excerpt(material: Any) -> str:
    focus_points = getattr(material, "focus_points", None) or []
    return str(
        getattr(material, "summary", "")
        or (focus_points[0] if focus_points else "")
        or getattr(material, "title", "")
    ).strip()


def _paragraphs_with_offsets(content: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    separator = re.compile(r"\n\s*\n+")
    last_index = 0

    def push(raw_segment: str, raw_start: int, raw_end: int) -> None:
        if not raw_segment.strip():
            return
        leading = len(raw_segment) - len(raw_segment.lstrip())
        trailing = len(raw_segment) - len(raw_segment.rstrip())
        start_offset = raw_start + leading
        end_offset = max(start_offset, raw_end - trailing)
        records.append(
            {
                "index": len(records) + 1,
                "text": raw_segment.strip(),
                "start_offset": start_offset,
                "end_offset": end_offset,
            }
        )

    for match in separator.finditer(content):
        push(content[last_index:match.start()], last_index, match.start())
        last_index = match.end()
    push(content[last_index:], last_index, len(content))
    return records


def _build_project_academic_export(
    sections: list[Any],
    drafts: list[Any],
    materials: list[Any],
) -> dict[str, list[dict[str, Any]]]:
    """Derive academic evidence view-models from existing materials and anchors."""
    material_lookup = {material.material_id: material for material in materials}
    anchors_by_material: dict[str, list[dict[str, Any]]] = {}
    citation_chain: list[dict[str, Any]] = []
    review_findings: list[dict[str, Any]] = []
    section_ids = {section.section_id for section in sections}

    for draft in drafts:
        draft_payload = draft.to_dict()
        anchors = draft_payload.get("citation_anchors", [])
        paragraphs = _paragraphs_with_offsets(str(getattr(draft, "content", "")))
        for anchor in anchors:
            if not isinstance(anchor, Mapping):
                continue
            material_id = anchor.get("materialId")
            anchor_id = str(anchor.get("id", "")).strip()
            if material_id:
                anchors_by_material.setdefault(str(material_id), []).append(anchor)
            paragraph = next(
                (
                    item
                    for item in paragraphs
                    if int(anchor.get("startOffset", -1)) >= item["start_offset"]
                    and int(anchor.get("endOffset", -1)) <= item["end_offset"]
                ),
                None,
            )
            material = material_lookup.get(str(material_id)) if material_id else None
            excerpt = _material_excerpt(material) if material else ""
            citation_chain.append(
                {
                    "anchor_id": anchor_id,
                    "section_id": draft.section_id if draft.section_id in section_ids else None,
                    "paragraph_index": paragraph["index"] if paragraph else None,
                    "material_id": material.material_id if material else material_id,
                    "evidence_id": f"evidence:{material.material_id}" if material else None,
                    "claim_excerpt": (
                        _shorten_export_text(_strip_citation_tokens(paragraph["text"]))
                        if paragraph
                        else ""
                    ),
                    "source_excerpt": _shorten_export_text(excerpt) if excerpt else "",
                    "page": None,
                    "confidence": None,
                }
            )

        uncited_long = [
            paragraph
            for paragraph in paragraphs
            if len(_strip_citation_tokens(paragraph["text"])) >= 80
            and not any(
                int(anchor.get("startOffset", -1)) >= paragraph["start_offset"]
                and int(anchor.get("endOffset", -1)) <= paragraph["end_offset"]
                for anchor in anchors
                if isinstance(anchor, Mapping)
            )
        ]
        if uncited_long:
            review_findings.append(
                {
                    "id": f"uncited-paragraphs:{draft.draft_id}",
                    "severity": "warning",
                    "message": f"{len(uncited_long)} long paragraph(s) have no citation anchors.",
                    "draft_id": draft.draft_id,
                    "section_id": draft.section_id,
                }
            )

    for material_id in sorted(anchors_by_material):
        if material_id not in material_lookup:
            review_findings.append(
                {
                    "id": f"dangling-material:{material_id}",
                    "severity": "warning",
                    "message": "Citation anchor points to a material that is not in this project export.",
                    "material_id": material_id,
                }
            )

    evidence_rows: list[dict[str, Any]] = []
    for material in materials:
        excerpt = _material_excerpt(material)
        anchor_ids = [
            str(anchor.get("id", ""))
            for anchor in anchors_by_material.get(material.material_id, [])
        ]
        status = "unused"
        if anchor_ids:
            status = "used" if excerpt else "weak"
        evidence_rows.append(
            {
                "evidence_id": f"evidence:{material.material_id}",
                "material_id": material.material_id,
                "chunk_id": None,
                "page": None,
                "excerpt": _shorten_export_text(excerpt),
                "score": None,
                "provenance": {
                    "material_title": material.title,
                    "material_type": material.type,
                },
                "anchor_ids": anchor_ids,
                "status": status,
            }
        )

    return {
        "evidence_rows": evidence_rows,
        "citation_chain": citation_chain,
        "review_findings": review_findings,
    }


def _markdown_table_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


@router.get(
    "/project/{project_id}/export",
    tags=["Export"],
    response_model=ProjectExportPayload,
)
async def export_project(
    project_id: str,
    format: ProjectExportFormat = Query(ProjectExportFormat.MARKDOWN, description="导出格式"),
) -> dict[str, Any]:
    """Export a complete project with its sections, drafts, and materials."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    sections = store.list_sections(project_id)
    drafts = store.list_drafts(project_id)
    materials = store.list_materials(project_id)
    doc_store = _load_doc_store(project_id)
    academic_export = _build_project_academic_export(sections, drafts, materials)

    if format == ProjectExportFormat.JSON:
        return {
            "project_id": project_id,
            "format": "json",
            "project": project.to_dict(),
            "sections": [s.to_dict() for s in sections],
            "drafts": [d.to_dict() for d in drafts],
            "materials": [m.to_dict() for m in materials],
            "document_count": len(doc_store),
            **academic_export,
        }

    # Markdown export
    lines = [f"# {project.title}\n"]
    if project.description:
        lines.append(f"> {project.description}\n")
    lines.append(f"状态: {project.status} | 创建: {project.created_at}\n")

    # Sort sections by order
    sorted_sections = sorted(sections, key=lambda s: s.order)
    section_map = {s.section_id: s for s in sorted_sections}
    material_map = {m.material_id: m for m in materials}

    for section in sorted_sections:
        lines.append(f"\n## {section.title}\n")
        if section.description:
            lines.append(f"{section.description}\n")
        section_drafts = [d for d in drafts if getattr(d, "section_id", None) == section.section_id]
        for draft in section_drafts:
            lines.append(f"\n### {draft.title}\n")
            lines.append(f"{draft.content}\n")

    # Orphan drafts (no section)
    orphans = [d for d in drafts if not getattr(d, "section_id", None)]
    if orphans:
        lines.append("\n## 未分类草稿\n")
        for draft in orphans:
            lines.append(f"\n### {draft.title}\n")
            lines.append(f"{draft.content}\n")

    if academic_export["evidence_rows"]:
        lines.append("\n## 证据表\n")
        lines.append("| Evidence ID | Material | Status | Anchors | Excerpt |")
        lines.append("|---|---|---|---|---|")
        for row in academic_export["evidence_rows"]:
            anchors = ", ".join(row["anchor_ids"])
            material_title = row["provenance"]["material_title"]
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_table_cell(row["evidence_id"]),
                        _markdown_table_cell(material_title),
                        _markdown_table_cell(row["status"]),
                        _markdown_table_cell(anchors),
                        _markdown_table_cell(row["excerpt"]),
                    ]
                )
                + " |"
            )

    if academic_export["citation_chain"]:
        lines.append("\n## 引用链\n")
        lines.append("| Anchor | Section | Paragraph | Material | Claim | Source |")
        lines.append("|---|---|---|---|---|---|")
        for row in academic_export["citation_chain"]:
            section = section_map.get(row["section_id"])
            material = material_map.get(row["material_id"])
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_table_cell(row["anchor_id"]),
                        _markdown_table_cell(section.title if section else ""),
                        _markdown_table_cell(row["paragraph_index"]),
                        _markdown_table_cell(
                            material.title if material else row["material_id"]
                        ),
                        _markdown_table_cell(row["claim_excerpt"]),
                        _markdown_table_cell(row["source_excerpt"]),
                    ]
                )
                + " |"
            )

    if academic_export["review_findings"]:
        lines.append("\n## 审计提示\n")
        for finding in academic_export["review_findings"]:
            lines.append(f"- {finding['message']}")

    # References
    if materials:
        lines.append("\n## 参考文献\n")
        for i, mat in enumerate(materials, 1):
            title = mat.title or mat.title_en or "无标题"
            lines.append(f"{i}. {title}")
            if mat.summary:
                lines.append(f"   摘要: {mat.summary[:100]}...")
            lines.append("")

    return {
        "project_id": project_id,
        "format": "markdown",
        "filename": f"{project.title}.md",
        "content": "\n".join(lines),
    }


# =========================================================================
# Statistics Endpoints (learned from open-webui analytics & openhanako diary)
# =========================================================================

@router.get("/project/{project_id}/stats", tags=["Statistics"])
async def get_project_stats(project_id: str) -> dict[str, Any]:
    """Get comprehensive statistics for a project."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    sections = store.list_sections(project_id)
    drafts = store.list_drafts(project_id)
    materials = store.list_materials(project_id)
    doc_store = _load_doc_store(project_id)

    # Word count across all drafts
    total_words = sum(len(d.content) for d in drafts if hasattr(d, "content") and d.content)

    # Revision count
    total_revisions = sum(
        len(store.list_revisions(d.draft_id)) for d in drafts
    )

    return {
        "project_id": project_id,
        "title": project.title,
        "status": project.status,
        "section_count": len(sections),
        "draft_count": len(drafts),
        "material_count": len(materials),
        "document_count": len(doc_store),
        "total_characters": total_words,
        "total_revisions": total_revisions,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


@router.get("/stats/overview", tags=["Statistics"])
async def get_global_stats() -> dict[str, Any]:
    """Get global statistics across all projects."""
    store = get_writing_resource_store()
    projects = store.list_projects()
    total_drafts = 0
    total_materials = 0
    total_chars = 0
    status_counts: dict[str, int] = {}

    for p in projects:
        drafts = store.list_drafts(p.project_id)
        materials = store.list_materials(p.project_id)
        total_drafts += len(drafts)
        total_materials += len(materials)
        total_chars += sum(len(d.content) for d in drafts if hasattr(d, "content") and d.content)
        status = p.status if isinstance(p.status, str) else p.status.value
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "project_count": len(projects),
        "draft_count": total_drafts,
        "material_count": total_materials,
        "total_characters": total_chars,
        "projects_by_status": status_counts,
    }


# =========================================================================
# Batch Operations (learned from openhanako / open-webui bulk endpoints)
# =========================================================================

class BatchDeleteRequest(__import__("pydantic").BaseModel):
    material_ids: list[str] = __import__("pydantic").Field(..., min_length=1, max_length=50, description="要删除的素材 ID 列表")


class CleanupRequest(__import__("pydantic").BaseModel):
    dry_run: bool = True


@router.post("/maintenance/cleanup", tags=["Resources"])
async def cleanup_historical_dirty_data(request: CleanupRequest) -> dict[str, Any]:
    """Preview or execute cleanup for duplicate projects and non-extractable materials."""
    store = get_writing_resource_store()
    duplicate_projects, empty_materials = _analyze_cleanup_candidates(store)

    preview = {
        "duplicate_project_count": len(duplicate_projects),
        "empty_material_count": len(empty_materials),
        "duplicate_projects": duplicate_projects,
        "empty_materials": empty_materials,
    }

    if request.dry_run:
        return {
            "dry_run": True,
            "preview": preview,
            "deleted": {
                "duplicate_project_count": 0,
                "empty_material_count": 0,
                "duplicate_projects": [],
                "empty_materials": [],
            },
        }

    deleted_duplicate_projects: list[str] = []
    deleted_empty_materials: list[str] = []

    for item in duplicate_projects:
        project_id = str(item.get("project_id") or "")
        if not project_id:
            continue
        if store.delete_project(project_id):
            deleted_duplicate_projects.append(project_id)
            doc_store_path = _get_doc_store_path(project_id)
            if doc_store_path.exists():
                try:
                    doc_store_path.unlink()
                except OSError:
                    logger.warning("Failed to remove doc_store file during cleanup: %s", doc_store_path)
            chunk_store_path = _get_chunk_store_path(project_id)
            if chunk_store_path.exists():
                try:
                    chunk_store_path.unlink()
                except OSError:
                    logger.warning("Failed to remove chunk_store file during cleanup: %s", chunk_store_path)

    for item in empty_materials:
        project_id = str(item.get("project_id") or "")
        material_id = str(item.get("material_id") or "")
        if not material_id or not project_id:
            continue
        if store.delete_material(material_id):
            deleted_empty_materials.append(material_id)
            doc_store = _load_doc_store(project_id)
            if material_id in doc_store:
                del doc_store[material_id]
                _save_doc_store(project_id, doc_store)
            chunk_store = _load_chunk_store(project_id)
            if material_id in chunk_store:
                del chunk_store[material_id]
                _save_chunk_store(project_id, chunk_store)

    return {
        "dry_run": False,
        "preview": preview,
        "deleted": {
            "duplicate_project_count": len(deleted_duplicate_projects),
            "empty_material_count": len(deleted_empty_materials),
            "duplicate_projects": deleted_duplicate_projects,
            "empty_materials": deleted_empty_materials,
        },
    }


@router.post("/materials/batch-delete", tags=["Resources"])
async def batch_delete_materials(request: BatchDeleteRequest) -> dict[str, Any]:
    """Batch delete materials from a project."""
    store = get_writing_resource_store()
    deleted = []
    not_found = []
    for mid in request.material_ids:
        material = store.get_material(mid)
        if material:
            project_id = material.project_id
            store.delete_material(mid)

            doc_store = _load_doc_store(project_id)
            if mid in doc_store:
                del doc_store[mid]
                _save_doc_store(project_id, doc_store)

            chunk_store = _load_chunk_store(project_id)
            if mid in chunk_store:
                del chunk_store[mid]
                _save_chunk_store(project_id, chunk_store)

            deleted.append(mid)
        else:
            not_found.append(mid)
    return {
        "deleted": deleted,
        "not_found": not_found,
        "deleted_count": len(deleted),
    }


@router.delete("/material/{material_id}", tags=["Resources"])
async def delete_material(material_id: str) -> dict[str, str]:
    """Delete a single material by ID."""
    store = get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail=f"素材不存在: {material_id}")

    # Also clean doc_store entry if exists
    project_id = material.project_id
    store.delete_material(material_id)

    doc_store = _load_doc_store(project_id)
    if material_id in doc_store:
        del doc_store[material_id]
        _save_doc_store(project_id, doc_store)

    chunk_store = _load_chunk_store(project_id)
    if material_id in chunk_store:
        del chunk_store[material_id]
        _save_chunk_store(project_id, chunk_store)

    return {"status": "deleted", "material_id": material_id}


@router.delete("/draft/{draft_id}", tags=["Resources"])
async def delete_draft(draft_id: str) -> dict[str, str]:
    """Delete a draft by ID."""
    store = get_writing_resource_store()
    draft = store.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"草稿不存在: {draft_id}")
    store.delete_draft(draft_id)
    return {"status": "deleted", "draft_id": draft_id}


@router.delete("/section/{section_id}", tags=["Resources"])
async def delete_section(section_id: str) -> dict[str, str]:
    """Delete a section by ID."""
    store = get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"章节不存在: {section_id}")
    store.delete_section(section_id)
    return {"status": "deleted", "section_id": section_id}


# =========================================================================
# Section / Draft Update Endpoints (RESTful completeness)
# =========================================================================

class UpdateSectionRequest(__import__("pydantic").BaseModel):
    title: str | None = None
    description: str | None = None
    order: int | None = None


@router.put("/section/{section_id}", tags=["Resources"])
async def update_section(section_id: str, request: UpdateSectionRequest) -> SectionPayload:
    """Update section title, description, or order."""
    store = get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"章节不存在: {section_id}")

    updates: dict[str, Any] = {}
    if request.title is not None:
        updates["title"] = request.title
    if request.description is not None:
        updates["description"] = request.description
    if request.order is not None:
        updates["order"] = request.order

    if updates:
        updated = store.update_section(section_id, **updates)
        if updated:
            return SectionPayload(**updated.to_dict())

    return SectionPayload(**section.to_dict())


class UpdateProjectRequest(__import__("pydantic").BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None


@router.put("/project/{project_id}", tags=["Resources"])
async def update_project(project_id: str, request: UpdateProjectRequest) -> ProjectPayload:
    """Update project title, description, or tags."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    updates: dict[str, Any] = {}
    if request.title is not None:
        updates["title"] = request.title
    if request.description is not None:
        updates["description"] = request.description
    if request.tags is not None:
        updates["tags"] = request.tags

    if updates:
        updated = store.update_project(project_id, **updates)
        if updated:
            return ProjectPayload(**updated.to_dict())

    return ProjectPayload(**project.to_dict())
