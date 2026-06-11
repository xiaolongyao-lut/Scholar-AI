# -*- coding: utf-8 -*-
"""Chunk-store and doc-store internals split out of resources_router.__init__.

All references to module-level monkeypatch targets (_resolve_data_dir,
_DOC_STORE_DIR, _CHUNK_STORE_DIR, _CHUNK_QUARANTINE_LOG_PATH,
_CHUNK_STORE_LOCK) go through _rr.X (absolute import) so pytest
monkeypatch.setattr(rr, X, ...) keeps affecting the live behaviour.
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from chunk_size_guard import hard_max_chars, hard_max_tokens, inspect_chunk

import routers.resources_router as _rr


def _get_doc_store_path(project_id: str) -> Path:
    """Return the JSON doc store path for a given project."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in "_-")
    doc_dir, _ = _rr._resolve_data_dir(project_id)
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
    fallback = _rr._DOC_STORE_DIR / f"{''.join(c for c in project_id if c.isalnum() or c in '_-')}.json"
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

def _safe_project_id(project_id: str) -> str:
    return "".join(c for c in project_id if c.isalnum() or c in "_-")


def _get_chunk_store_path(project_id: str) -> Path:
    """Return the **legacy v1** JSON chunk store path. Kept for backward
    compatibility (callers still use this for existence checks/migration).
    The active v2 layout lives under :func:`_chunk_store_dir`.
    """
    _, chunk_dir = _rr._resolve_data_dir(project_id)
    return chunk_dir / f"{_safe_project_id(project_id)}_chunks.json"


def _chunk_store_dir(project_id: str) -> Path:
    _, chunk_dir = _rr._resolve_data_dir(project_id)
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
    digest = hashlib.md5(material_id.encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}.jsonl"


def _hash_chunks(chunks: list[dict[str, Any]]) -> str:
    payload = json.dumps(chunks, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    """Atomic write_text — text/utf-8 + ``os.replace``.

    Uses NamedTemporaryFile (delete=False) in the SAME directory as the
    target so ``os.replace`` is a same-filesystem rename (POSIX guarantee
    + Windows behavior). The tmp file always lands in ``path.parent`` so
    concurrent writers can never collide on a single fixed tmp name (A18
    contract).

    Failure-cleanup contract (added 2026-06-12, A18 fix):
      - If ``os.replace`` raises (e.g. Windows file-lock contention, EACCES,
        ENOSPC mid-replace), the orphan tmp file is removed in ``finally`` so
        the directory never accumulates ``*.tmp`` residue.
      - If the write itself raises, the tmp file (already created by
        NamedTemporaryFile) is also unlinked.
      - The exception is re-raised — callers must continue to see write
        failures, not silent success.

    The TARGET file remains atomically replaced or untouched on failure;
    user data is never corrupted regardless of which branch trips.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
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
        # os.replace consumed the tmp path; mark as such so the finally
        # block does not try to unlink an entry that no longer exists.
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            except OSError:
                # Best-effort cleanup — leaving the tmp is acceptable since
                # the TARGET file's atomicity is already guaranteed by
                # os.replace having either succeeded or never run.
                pass


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
    with _rr._CHUNK_STORE_LOCK:
        return _load_chunk_store_unlocked(project_id)


def _save_chunk_store(project_id: str, store: dict[str, list[dict[str, Any]]]) -> None:
    """Persist chunk store using v2 incremental layout.

    Only materials whose sha256 differs from the existing manifest are
    rewritten; orphaned per-material files are removed. Any legacy v1 file
    is renamed to ``*.legacy.bak`` after a successful migration write.
    
    Thread-safe: uses module-level lock to prevent concurrent read-modify-write races.
    """
    with _rr._CHUNK_STORE_LOCK:
        _save_chunk_store_unlocked(project_id, store)


def _update_chunk_store_atomic(
    project_id: str,
    updater: Callable[[dict[str, list[dict[str, Any]]]], dict[str, list[dict[str, Any]]]]
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
    with _rr._CHUNK_STORE_LOCK:
        # Call unlocked versions since we already hold the lock
        store = _load_chunk_store_unlocked(project_id)
        updated_store = updater(store)
        _save_chunk_store_unlocked(project_id, updated_store)


def _load_chunk_store_unlocked(project_id: str) -> dict[str, list[dict[str, Any]]]:
    """Internal: Load chunk store WITHOUT acquiring lock.
    
    Only call from within _rr._CHUNK_STORE_LOCK context or via public _load_chunk_store.
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
    older = _rr._CHUNK_STORE_DIR / f"{safe_id}.json"
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
    
    Only call from within _rr._CHUNK_STORE_LOCK context or via public _save_chunk_store.
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
    digest = hashlib.md5(material_id.encode("utf-8")).hexdigest()[:8]
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
    _rr._CHUNK_QUARANTINE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
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
    with _rr._CHUNK_QUARANTINE_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
