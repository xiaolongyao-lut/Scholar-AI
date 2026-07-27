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
from copy import deepcopy
from contextlib import contextmanager
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, TypeGuard

if TYPE_CHECKING:
    from literature_assistant.core._atomic_io import CrossProcessFileLock
    from literature_assistant.core.chunk_evidence_linter import ChunkEvidenceUnitLinter
    from literature_assistant.core.chunk_fts_index import (
        CHUNK_FTS_INDEX_SCHEMA_VERSION,
        rebuild_chunk_fts_index,
    )
    from literature_assistant.core.chunk_hashing import (
        CHUNK_HASH_VERSION,
        SUPPORTED_CHUNK_HASH_VERSIONS,
        classify_embedding_only_manifest_drift,
        compute_chunk_manifest_digest,
        compute_chunk_store_version,
        with_chunk_hashes,
    )
    from literature_assistant.core.chunk_index_backfill_ledger import (
        CHUNK_INDEX_BACKFILL_LEDGER_SCHEMA_VERSION,
        ChunkIndexBackfillLedgerEntry,
        ledger_status_counts,
        linter_entries_for_store,
        make_chunk_index_backfill_entry,
        merge_chunk_index_backfill_ledger_entries,
        transition_entries_for_material,
        utc_now_iso,
    )
    from literature_assistant.core.chunk_size_guard import (
        hard_max_chars,
        hard_max_tokens,
        inspect_chunk,
    )
    from literature_assistant.core.routers import resources_router as _rr
else:
    from _atomic_io import CrossProcessFileLock
    from chunk_evidence_linter import ChunkEvidenceUnitLinter
    from chunk_fts_index import CHUNK_FTS_INDEX_SCHEMA_VERSION, rebuild_chunk_fts_index
    from chunk_hashing import (
        CHUNK_HASH_VERSION,
        SUPPORTED_CHUNK_HASH_VERSIONS,
        classify_embedding_only_manifest_drift,
        compute_chunk_manifest_digest,
        compute_chunk_store_version,
        with_chunk_hashes,
    )
    from chunk_index_backfill_ledger import (
        CHUNK_INDEX_BACKFILL_LEDGER_SCHEMA_VERSION,
        ChunkIndexBackfillLedgerEntry,
        ledger_status_counts,
        linter_entries_for_store,
        make_chunk_index_backfill_entry,
        merge_chunk_index_backfill_ledger_entries,
        transition_entries_for_material,
        utc_now_iso,
    )
    from chunk_size_guard import hard_max_chars, hard_max_tokens, inspect_chunk

    import routers.resources_router as _rr


class ChunkStoreIntegrityError(ValueError):
    """Bounded failure for persisted chunk-store state that is not trustworthy."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize a stable machine code and path-safe diagnostic message."""

        safe_message = str(message or "Chunk-store integrity check failed").replace("\n", " ")[:500]
        super().__init__(safe_message)
        self.code = str(code or "chunk_store_integrity_error")[:80]
        self.safe_message = safe_message


def _integrity_error(code: str, message: str) -> ChunkStoreIntegrityError:
    return ChunkStoreIntegrityError(code, message)


class DocStoreIntegrityError(ValueError):
    """Bounded failure for persisted document state that is not trustworthy."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize a stable machine code and path-safe diagnostic message."""

        safe_message = str(message or "Document-store integrity check failed").replace("\n", " ")[:500]
        super().__init__(safe_message)
        self.code = str(code or "doc_store_integrity_error")[:80]
        self.safe_message = safe_message


DocStore = dict[str, dict[str, Any]]
ChunkStore = dict[str, list[dict[str, Any]]]
DocStoreUpdater = Callable[[DocStore], DocStore]
ChunkStoreUpdater = Callable[[ChunkStore], ChunkStore]
ProjectStoresUpdater = Callable[[DocStore, ChunkStore], tuple[DocStore, ChunkStore]]


def _resolve_project_data_dirs(project_id: str) -> tuple[Path, Path]:
    """Validate the dynamically dispatched project data-directory contract."""

    resolved: object = _rr._resolve_data_dir(project_id)
    if not isinstance(resolved, tuple) or len(resolved) != 2:
        raise TypeError("Project data directory resolver must return two paths")
    doc_dir, chunk_dir = resolved
    if not isinstance(doc_dir, Path) or not isinstance(chunk_dir, Path):
        raise TypeError("Project data directory resolver must return Path values")
    return doc_dir, chunk_dir


def _get_doc_store_path(project_id: str) -> Path:
    """Return the JSON doc store path for a given project."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in "_-")
    doc_dir, _ = _resolve_project_data_dirs(project_id)
    return doc_dir / f"{safe_id}.json"


def _project_store_lock_path(project_id: str) -> Path:
    """Return the project-local cross-process publication lock path."""

    return _chunk_store_dir(project_id) / ".publication.lock"


@contextmanager
def _project_store_write_lock(project_id: str) -> Iterator[None]:
    """Serialize one project publication across threads and app processes."""

    with _rr._CHUNK_STORE_LOCK:
        with CrossProcessFileLock(_project_store_lock_path(project_id)):
            yield


def _validate_doc_store_payload(payload: object) -> DocStore:
    """Validate and copy the persisted material-to-document mapping."""

    if not isinstance(payload, dict):
        raise DocStoreIntegrityError("doc_store_invalid", "Document store must be a JSON object")
    validated: DocStore = {}
    for material_id, raw_record in payload.items():
        if not isinstance(material_id, str) or not material_id.strip():
            raise DocStoreIntegrityError(
                "doc_store_material_id_invalid",
                "Document store material ids must be non-empty strings",
            )
        if not isinstance(raw_record, dict):
            raise DocStoreIntegrityError(
                "doc_store_record_invalid",
                "Document store material records must be JSON objects",
            )
        validated[material_id] = dict(raw_record)
    return validated


def _read_doc_store_path(path: Path) -> DocStore:
    """Read one authoritative document-store file or fail closed."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise DocStoreIntegrityError(
            "doc_store_invalid",
            f"Document store is unreadable or contains invalid JSON: {path.name}",
        ) from exc
    return _validate_doc_store_payload(payload)


def _load_doc_store(project_id: str) -> DocStore:
    """Load and strictly validate a project's authoritative document store."""

    with _rr._CHUNK_STORE_LOCK:
        return _load_doc_store_unlocked(project_id)


def _load_doc_store_unlocked(project_id: str) -> DocStore:
    """Load a document store while the caller owns the project lock."""

    path = _get_doc_store_path(project_id)
    if path.exists():
        return _read_doc_store_path(path)
    # Fallback: check default location (in case project was migrated)
    fallback = _rr._DOC_STORE_DIR / f"{''.join(c for c in project_id if c.isalnum() or c in '_-')}.json"
    if fallback.exists() and fallback != path:
        return _read_doc_store_path(fallback)
    return {}


def _save_doc_store(project_id: str, store: DocStore) -> None:
    """Atomically persist a complete document-store snapshot."""

    with _project_store_write_lock(project_id):
        _save_doc_store_unlocked(project_id, store)


def _save_doc_store_unlocked(project_id: str, store: DocStore) -> None:
    """Persist a validated document store while the caller owns the lock."""

    validated = _validate_doc_store_payload(store)
    path = _get_doc_store_path(project_id)
    _atomic_write_text(path, json.dumps(validated, ensure_ascii=False, indent=2))


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
    _, chunk_dir = _resolve_project_data_dirs(project_id)
    return chunk_dir / f"{_safe_project_id(project_id)}_chunks.json"


def _chunk_store_dir(project_id: str) -> Path:
    _, chunk_dir = _resolve_project_data_dirs(project_id)
    return chunk_dir / _safe_project_id(project_id)


def _chunk_quarantine_dir(project_id: str) -> Path:
    return _chunk_store_dir(project_id) / "_quarantine"


def _chunk_index_backfill_ledger_path(project_id: str) -> Path:
    return _chunk_store_dir(project_id) / "index_backfill_ledger.jsonl"


def _chunk_fts_index_path(project_id: str) -> Path:
    return _chunk_store_dir(project_id) / "chunk_lexical_fts.sqlite3"


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
    material_digest = hashlib.md5(material_id.encode("utf-8")).hexdigest()[:8]
    content_digest = compute_chunk_manifest_digest(chunks)[:12]
    return f"{stem}_{material_digest}_{content_digest}.jsonl"


def _hash_chunks(chunks: list[dict[str, Any]]) -> str:
    digest: object = compute_chunk_manifest_digest(chunks)
    if not isinstance(digest, str):
        raise TypeError("Chunk manifest digest must be a string")
    return digest


def _is_plain_sha256(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _material_jsonl_path(project_dir: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise _integrity_error(
            "chunk_manifest_material_path_invalid",
            "Chunk manifest material path must be non-empty",
        )
    normalized = relative_path.strip()
    relative = Path(normalized)
    if (
        relative.is_absolute()
        or relative.name != normalized
        or relative.suffix.lower() != ".jsonl"
        or "_quarantine" in relative.parts
    ):
        raise _integrity_error(
            "chunk_manifest_material_path_invalid",
            "Chunk manifest material path must be one project-local JSONL filename",
        )
    candidate = (project_dir / relative).resolve()
    if candidate.parent != project_dir.resolve():
        raise _integrity_error(
            "chunk_manifest_material_path_invalid",
            "Chunk manifest material path escapes the project chunk directory",
        )
    return candidate


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


def _read_material_jsonl(
    path: Path,
    *,
    material_id: str | None = None,
) -> list[dict[str, Any]]:
    if not path.is_file():
        raise _integrity_error(
            "material_chunk_file_missing",
            f"Manifest-bound material chunk file is missing: {path.name}",
        )
    chunks: list[dict[str, Any]] = []
    chunk_ids: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise _integrity_error(
                        "material_chunk_json_invalid",
                        f"Material chunk JSONL contains invalid JSON at line {line_number}",
                    ) from exc
                if not isinstance(chunk, dict):
                    raise _integrity_error(
                        "material_chunk_row_invalid",
                        f"Material chunk JSONL line {line_number} must be an object",
                    )
                if material_id is not None and chunk.get("material_id") != material_id:
                    raise _integrity_error(
                        "material_chunk_identity_mismatch",
                        "Persisted chunk material identity differs from its manifest owner",
                    )
                raw_chunk_id = chunk.get("chunk_id")
                if not isinstance(raw_chunk_id, str) or not raw_chunk_id.strip():
                    raise _integrity_error(
                        "material_chunk_id_invalid",
                        "Persisted chunk id must be a non-empty string",
                    )
                chunk_id = raw_chunk_id.strip()
                if chunk_id in chunk_ids:
                    raise _integrity_error(
                        "material_chunk_id_duplicate",
                        "Persisted chunk ids must be unique within one material",
                    )
                chunk_ids.add(chunk_id)
                chunks.append(chunk)
    except (OSError, UnicodeDecodeError) as exc:
        raise _integrity_error(
            "material_chunk_file_unreadable",
            f"Material chunk file is unreadable: {path.name}",
        ) from exc
    return chunks


def _write_material_jsonl_atomic(path: Path, chunks: list[dict[str, Any]]) -> None:
    lines = "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks)
    _atomic_write_text(path, lines + ("\n" if lines else ""))


def _read_chunk_index_backfill_ledger(project_id: str) -> list[dict[str, Any]]:
    """Return existing derived-index ledger entries for state preservation."""

    path = _chunk_index_backfill_ledger_path(project_id)
    entries: list[dict[str, Any]] = []
    if not path.exists():
        return entries
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError:
        return []
    return entries


def _write_chunk_index_backfill_ledger(
    project_id: str,
    entries: list[ChunkIndexBackfillLedgerEntry],
) -> None:
    """Persist the derived-index ledger without mutating chunk truth rows."""

    path = _chunk_index_backfill_ledger_path(project_id)
    lines = "\n".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) for entry in entries)
    _atomic_write_text(path, lines + ("\n" if lines else ""))


def _chunk_index_backfill_manifest_payload(
    project_id: str,
    entries: list[ChunkIndexBackfillLedgerEntry],
) -> dict[str, Any]:
    """Return manifest fields for the current derived-index ledger snapshot."""

    return {
        "index_backfill_ledger_schema_version": CHUNK_INDEX_BACKFILL_LEDGER_SCHEMA_VERSION,
        "index_backfill_ledger_relative_path": _chunk_index_backfill_ledger_path(project_id).name,
        "index_backfill_ledger_entry_count": len(entries),
        "index_backfill_ledger_status_counts": ledger_status_counts(entries),
    }


def _with_chunk_hashes_for_store(material_id: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return chunk copies with truth-hash fields populated when possible.

    Legacy stores can contain partially malformed rows. Invalid rows are kept
    untouched so a save operation does not become a destructive migration.
    """

    if not isinstance(material_id, str) or not material_id.strip():
        raise ValueError("material_id must be a non-empty string")

    migrated: list[dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        normalized_chunk = dict(chunk)
        if not str(normalized_chunk.get("material_id") or "").strip():
            normalized_chunk["material_id"] = material_id
        try:
            migrated.append(
                with_chunk_hashes(
                    normalized_chunk,
                    material_id_hint=material_id,
                    overwrite=True,
                )
            )
        except (TypeError, ValueError):
            migrated.append(normalized_chunk)
    return migrated


def _chunk_store_version_payload(store: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return manifest fields for the current content-derived store version."""

    try:
        chunk_store_version = compute_chunk_store_version(store)
    except (TypeError, ValueError):
        return {
            "chunk_hash_version": CHUNK_HASH_VERSION,
            "chunk_store_version": None,
            "chunk_store_version_status": "unavailable",
        }
    return {
        "chunk_hash_version": CHUNK_HASH_VERSION,
        "chunk_store_version": chunk_store_version,
        "chunk_store_version_status": "valid",
    }


def _chunk_fts_index_manifest_payload(
    *,
    project_id: str,
    store: dict[str, list[dict[str, Any]]],
    chunk_store_version: str | None,
    chunk_store_version_status: str,
) -> dict[str, Any]:
    """Return manifest fields for the rebuildable SQLite FTS5 index."""

    base = {
        "fts_index_schema_version": CHUNK_FTS_INDEX_SCHEMA_VERSION,
        "fts_index_relative_path": _chunk_fts_index_path(project_id).name,
    }
    if chunk_store_version_status != "valid" or not chunk_store_version:
        return {
            **base,
            "fts_index_status": "skipped",
            "fts_index_fallback_reason": "chunk_store_version_unavailable",
            "fts_index_chunk_store_version": None,
            "fts_index_indexed_count": 0,
            "fts_index_skipped_count": 0,
        }
    try:
        report = rebuild_chunk_fts_index(
            db_path=_chunk_fts_index_path(project_id),
            project_id=project_id,
            store=store,
            chunk_store_version=chunk_store_version,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return {
            **base,
            "fts_index_status": "unavailable",
            "fts_index_fallback_reason": "fts_index_rebuild_failed",
            "fts_index_chunk_store_version": chunk_store_version,
            "fts_index_indexed_count": 0,
            "fts_index_skipped_count": 0,
        }
    return {
        **base,
        "fts_index_status": "valid",
        "fts_index_fallback_reason": "",
        "fts_index_chunk_store_version": report.chunk_store_version,
        "fts_index_indexed_count": report.indexed_count,
        "fts_index_skipped_count": report.skipped_count,
    }


def _chunk_store_linter_payload(store: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return bounded linter manifest fields without mutating chunks."""

    chunks: list[dict[str, Any]] = []
    for material_chunks in store.values():
        chunks.extend(dict(chunk) for chunk in material_chunks if isinstance(chunk, dict))
    try:
        report = ChunkEvidenceUnitLinter().lint_chunks(chunks)
    except (TypeError, ValueError) as exc:
        return {
            "linter_schema_version": "scholar-ai-chunk-evidence-linter/v1",
            "linter_status": "unavailable",
            "linter_error": str(exc)[:240],
        }

    issue_counts: dict[str, int] = {}
    for issue in report.issues:
        issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1
    linter_status = "passed"
    if not report.passed:
        linter_status = "failed"
    elif report.warning_count:
        linter_status = "warning"
    return {
        "linter_schema_version": report.schema_version,
        "linter_status": linter_status,
        "linter_error_count": report.error_count,
        "linter_warning_count": report.warning_count,
        "linter_issue_counts": dict(sorted(issue_counts.items())),
        "linter_sample_issues": [issue.to_dict() for issue in report.issues[:20]],
    }


def _load_previous_material_chunks(
    project_dir: Path,
    old_materials: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return previous accepted chunks keyed by material id for transition checks."""

    previous: dict[str, list[dict[str, Any]]] = {}
    for material_id, entry in old_materials.items():
        if not isinstance(entry, dict):
            continue
        relative_path = str(entry.get("relative_path") or entry.get("file") or "")
        if not relative_path:
            continue
        relative_parts = Path(relative_path).parts
        if "_quarantine" in relative_parts:
            continue
        previous[material_id] = _read_material_jsonl(project_dir / relative_path)
    return previous


def _reusable_unchanged_material_entry(
    *,
    project_dir: Path,
    incoming_chunks: list[dict[str, Any]],
    previous_chunks: list[dict[str, Any]],
    previous_entry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a reusable manifest entry for a byte-stable material.

    An accepted-only read/save cycle must not rewrite legacy rows merely to
    add derived hash fields, and it must not delete a sibling quarantine file.
    Reuse is allowed only when the incoming structure equals the verified
    previous JSONL content and the manifest count/hash still agree.
    """

    if incoming_chunks != previous_chunks:
        return None
    if previous_entry is None:
        return None
    if not isinstance(previous_entry, dict):
        raise ValueError("chunk store integrity mismatch: manifest entry missing for unchanged material")
    relative_path = str(previous_entry.get("relative_path") or previous_entry.get("file") or "")
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or ".." in relative.parts or "_quarantine" in relative.parts:
        raise ValueError("chunk store integrity mismatch: invalid material path in manifest")
    target = project_dir / relative
    if not target.is_file():
        raise ValueError("chunk store integrity mismatch: material file missing")
    expected_hash = str(previous_entry.get("sha256") or "")
    if not expected_hash:
        raise ValueError("chunk store integrity mismatch: manifest sha256 missing")
    raw_count: object = previous_entry.get("total_chunks", previous_entry.get("count"))
    if not isinstance(raw_count, (str, bytes, bytearray, int, float)):
        raise ValueError("chunk store count mismatch: manifest count is invalid")
    try:
        expected_count = int(raw_count)
    except (TypeError, ValueError):
        raise ValueError("chunk store count mismatch: manifest count is invalid") from None
    if expected_count != len(previous_chunks):
        raise ValueError(
            "chunk store count mismatch: "
            f"manifest={expected_count} actual={len(previous_chunks)}"
        )

    actual_hash = _hash_chunks(previous_chunks)
    if actual_hash != expected_hash:
        raise _integrity_error(
            "chunk_manifest_sha_mismatch",
            "Chunk manifest digest changed after strict load validation",
        )

    reused = dict(previous_entry)
    reused["relative_path"] = relative_path
    reused["sha256"] = actual_hash
    reused["total_chunks"] = expected_count
    reused.pop("file", None)
    reused.pop("count", None)
    return reused


def _load_manifest(project_dir: Path) -> dict[str, Any]:
    manifest_path = project_dir / "manifest.json"
    if not manifest_path.exists():
        return {"version": 2, "materials": {}}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise _integrity_error(
            "chunk_manifest_invalid",
            "Chunk manifest is unreadable or contains invalid JSON",
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("materials"), dict):
        raise _integrity_error(
            "chunk_manifest_invalid",
            "Chunk manifest must be an object with a materials object",
        )
    if data.get("version") != 2:
        raise _integrity_error(
            "chunk_manifest_version_unsupported",
            "Chunk manifest version must be 2",
        )
    return data


def _chunk_store_hash_version(project_id: str) -> str:
    """Return the persisted project hash contract used by its derived index."""

    manifest_path = _chunk_store_dir(project_id) / "manifest.json"
    if not manifest_path.is_file():
        return str(CHUNK_HASH_VERSION)
    manifest = _load_manifest(manifest_path.parent)
    hash_version = str(manifest.get("chunk_hash_version") or "").strip()
    if hash_version not in SUPPORTED_CHUNK_HASH_VERSIONS:
        raise _integrity_error(
            "chunk_hash_version_unsupported",
            "Chunk manifest uses an unsupported hash contract",
        )
    return hash_version


def _chunk_store_retrieval_contract(project_id: str) -> tuple[str, str]:
    """Read the manifest contract needed for an FTS-first retrieval pass.

    Returns:
        ``(chunk_store_version, hash_version)`` from a healthy manifest.

    Raises:
        ChunkStoreIntegrityError: If the project has no manifest-bound,
            current FTS contract. Callers may fall back to the full loader.
    """

    with _project_store_write_lock(project_id):
        project_dir = _chunk_store_dir(project_id)
        manifest = _load_manifest(project_dir)
        chunk_store_version = str(manifest.get("chunk_store_version") or "").strip()
        if (
            manifest.get("chunk_store_version_status") != "valid"
            or len(chunk_store_version) != 64
            or not _is_plain_sha256(chunk_store_version)
        ):
            raise _integrity_error(
                "chunk_store_version_unavailable",
                "Chunk manifest does not expose a valid content-derived version",
            )
        hash_version = str(manifest.get("chunk_hash_version") or "").strip()
        if hash_version not in SUPPORTED_CHUNK_HASH_VERSIONS:
            raise _integrity_error(
                "chunk_hash_version_unsupported",
                "Chunk manifest uses an unsupported hash contract",
            )
        if (
            manifest.get("fts_index_status") != "valid"
            or manifest.get("fts_index_schema_version") != CHUNK_FTS_INDEX_SCHEMA_VERSION
            or manifest.get("fts_index_chunk_store_version") != chunk_store_version
            or manifest.get("fts_index_relative_path") != _chunk_fts_index_path(project_id).name
        ):
            raise _integrity_error(
                "fts_index_contract_unavailable",
                "Chunk manifest does not prove a current lexical index",
            )
        return chunk_store_version, hash_version


def _load_chunk_store_materials_for_retrieval(
    project_id: str,
    material_ids: Sequence[str],
    *,
    expected_chunk_store_version: str,
) -> ChunkStore:
    """Load only manifest-bound materials selected by a current FTS query.

    The manifest and each selected JSONL generation are checked while the
    publication lock is held. A changed generation fails closed so the caller
    can retry through the established full-store compatibility path.
    """

    if isinstance(material_ids, (str, bytes)) or not isinstance(material_ids, Sequence):
        raise TypeError("material_ids must be a sequence of strings")
    normalized_version = str(expected_chunk_store_version or "").strip()
    if not _is_plain_sha256(normalized_version):
        raise ValueError("expected_chunk_store_version must be a lowercase SHA-256 digest")
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for raw_material_id in material_ids:
        material_id = str(raw_material_id or "").strip()
        if not material_id or material_id in seen:
            continue
        seen.add(material_id)
        normalized_ids.append(material_id)
    if len(normalized_ids) > 100:
        raise ValueError("material_ids must contain at most 100 ids")

    with _project_store_write_lock(project_id):
        project_dir = _chunk_store_dir(project_id)
        manifest = _load_manifest(project_dir)
        if (
            manifest.get("chunk_store_version_status") != "valid"
            or manifest.get("chunk_store_version") != normalized_version
        ):
            raise _integrity_error(
                "chunk_store_version_changed",
                "Chunk manifest changed during selective retrieval",
            )
        materials = manifest.get("materials")
        if not isinstance(materials, dict):
            raise _integrity_error(
                "chunk_manifest_invalid",
                "Chunk manifest materials must be an object",
            )
        result: ChunkStore = {}
        for material_id in normalized_ids:
            entry = materials.get(material_id)
            if not isinstance(entry, dict):
                raise _integrity_error(
                    "material_chunks_missing",
                    "FTS selected material is absent from the chunk manifest",
                )
            material_path = _material_jsonl_path(
                project_dir,
                entry.get("relative_path") or entry.get("file"),
            )
            chunks = _read_material_jsonl(material_path, material_id=material_id)
            expected_count = entry.get("total_chunks", entry.get("count"))
            if (
                isinstance(expected_count, bool)
                or not isinstance(expected_count, int)
                or expected_count < 0
                or expected_count != len(chunks)
            ):
                raise _integrity_error(
                    "chunk_manifest_count_mismatch",
                    "Selected material chunk count differs from its manifest",
                )
            expected_sha256 = entry.get("sha256")
            if not _is_plain_sha256(expected_sha256) or _hash_chunks(chunks) != expected_sha256:
                raise _integrity_error(
                    "chunk_manifest_sha_mismatch",
                    "Selected material chunk digest differs from its manifest",
                )
            result[material_id] = chunks
        return result


def _load_chunk_store(project_id: str) -> dict[str, list[dict[str, Any]]]:
    """Load chunk store for a project: { material_id: [chunk_dicts] }.

    Reads v2 layout if present; else falls back to v1 (legacy) single file.
    Serializes with cross-process publication so a manifest-bound generation
    cannot be reclaimed between manifest and JSONL reads.
    """
    with _project_store_write_lock(project_id):
        return _load_chunk_store_unlocked(project_id)


def _save_chunk_store(project_id: str, store: dict[str, list[dict[str, Any]]]) -> None:
    """Persist chunk store using v2 incremental layout.

    Only materials whose sha256 differs from the existing manifest are
    rewritten; orphaned per-material files are removed. Any legacy v1 file
    is renamed to ``*.legacy.bak`` after a successful migration write.
    
    Thread-safe: uses module-level lock to prevent concurrent read-modify-write races.
    """
    with _project_store_write_lock(project_id):
        _save_chunk_store_unlocked(project_id, store)


def _update_doc_store_atomic(project_id: str, updater: DocStoreUpdater) -> DocStore:
    """Apply one document-store read-modify-write while holding its project lock."""

    if not callable(updater):
        raise TypeError("updater must be callable")
    with _project_store_write_lock(project_id):
        store = _load_doc_store_unlocked(project_id)
        original_store = deepcopy(store)
        updated_store = updater(store)
        if updated_store == original_store:
            return original_store
        _save_doc_store_unlocked(project_id, updated_store)
        return _load_doc_store_unlocked(project_id)


def _update_chunk_store_atomic(
    project_id: str,
    updater: Callable[[dict[str, list[dict[str, Any]]]], dict[str, list[dict[str, Any]]]]
) -> ChunkStore:
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
    if not callable(updater):
        raise TypeError("updater must be callable")
    with _project_store_write_lock(project_id):
        store = _load_chunk_store_unlocked(project_id)
        original_store = deepcopy(store)
        updated_store = updater(store)
        if updated_store == original_store:
            return original_store
        _save_chunk_store_unlocked(project_id, updated_store)
        return _load_chunk_store_unlocked(project_id)


def _update_project_stores_atomic(
    project_id: str,
    updater: ProjectStoresUpdater,
) -> tuple[DocStore, ChunkStore]:
    """Serialize a coordinated document/chunk read-modify-write publication."""

    if not callable(updater):
        raise TypeError("updater must be callable")
    with _project_store_write_lock(project_id):
        doc_store = _load_doc_store_unlocked(project_id)
        chunk_store = _load_chunk_store_unlocked(project_id)
        original_doc_store = deepcopy(doc_store)
        original_chunk_store = deepcopy(chunk_store)
        updated_doc_store, updated_chunk_store = updater(doc_store, chunk_store)
        chunks_changed = updated_chunk_store != original_chunk_store
        docs_changed = updated_doc_store != original_doc_store
        if chunks_changed:
            _save_chunk_store_unlocked(project_id, updated_chunk_store)
        if docs_changed:
            try:
                _save_doc_store_unlocked(project_id, updated_doc_store)
            except Exception:
                if chunks_changed:
                    try:
                        _save_chunk_store_unlocked(project_id, original_chunk_store)
                    except Exception as rollback_exc:
                        raise _integrity_error(
                            "project_store_rollback_failed",
                            "Document publication failed and chunk rollback did not complete",
                        ) from rollback_exc
                raise
        return (
            _load_doc_store_unlocked(project_id) if docs_changed else original_doc_store,
            _load_chunk_store_unlocked(project_id) if chunks_changed else original_chunk_store,
        )


def _read_legacy_chunk_store(path: Path) -> ChunkStore:
    """Read one legacy whole-project store without accepting partial failure."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise _integrity_error(
            "legacy_chunk_store_invalid",
            f"Legacy chunk store is unreadable or contains invalid JSON: {path.name}",
        ) from exc
    if not isinstance(payload, dict):
        raise _integrity_error(
            "legacy_chunk_store_invalid",
            "Legacy chunk store must be a JSON object",
        )
    return payload


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
        manifest_changed = False
        for material_id, entry in manifest.get("materials", {}).items():
            if not isinstance(entry, dict):
                raise _integrity_error(
                    "chunk_manifest_entry_invalid",
                    "Chunk manifest material entry must be an object",
                )
            relative_path = entry.get("relative_path") or entry.get("file")
            material_path = _material_jsonl_path(project_dir, relative_path)
            chunks = _read_material_jsonl(material_path, material_id=material_id)
            expected_count = entry.get("total_chunks", entry.get("count"))
            if (
                isinstance(expected_count, bool)
                or not isinstance(expected_count, int)
                or expected_count < 0
            ):
                raise _integrity_error(
                    "chunk_manifest_count_invalid",
                    "Chunk manifest material count must be a non-negative integer",
                )
            if expected_count != len(chunks):
                raise _integrity_error(
                    "chunk_manifest_count_mismatch",
                    f"Chunk manifest count differs for material {material_id}",
                )
            expected_sha256 = entry.get("sha256")
            if not _is_plain_sha256(expected_sha256):
                raise _integrity_error(
                    "chunk_manifest_sha_invalid",
                    "Chunk manifest material sha256 must be 64 lowercase hexadecimal characters",
                )
            actual_sha256 = _hash_chunks(chunks)
            if expected_sha256 != actual_sha256:
                drift = classify_embedding_only_manifest_drift(chunks, expected_sha256)
                if drift is None:
                    raise _integrity_error(
                        "chunk_manifest_sha_mismatch",
                        f"Chunk manifest digest differs for material {material_id}",
                    )
                entry["sha256"] = actual_sha256
                manifest_changed = True
            result[material_id] = chunks
        if manifest_changed:
            try:
                _atomic_write_text(
                    manifest_path,
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
            except OSError as exc:
                raise _integrity_error(
                    "chunk_manifest_migration_write_failed",
                    "Embedding-only manifest migration could not be persisted",
                ) from exc
        return result
    # Legacy v1 fallback
    legacy = _get_chunk_store_path(project_id)
    if legacy.exists():
        return _read_legacy_chunk_store(legacy)
    # Older legacy: chunk_dir / "{safe_id}.json"
    safe_id = _safe_project_id(project_id)
    older = _rr._CHUNK_STORE_DIR / f"{safe_id}.json"
    if older.exists() and older != legacy:
        return _read_legacy_chunk_store(older)
    return {}


def _validate_chunk_store_candidate(store: object) -> ChunkStore:
    """Validate store ownership before any truth-store file is published."""

    if not isinstance(store, dict):
        raise _integrity_error("chunk_store_invalid", "Chunk store must be a mapping")
    validated: ChunkStore = {}
    chunk_ids: set[str] = set()
    for material_id, raw_chunks in store.items():
        if not isinstance(material_id, str) or not material_id.strip():
            raise _integrity_error(
                "chunk_store_material_id_invalid",
                "Chunk store material ids must be non-empty strings",
            )
        if not isinstance(raw_chunks, list):
            raise _integrity_error(
                "chunk_store_material_rows_invalid",
                "Chunk store material rows must be a list",
            )
        chunks: list[dict[str, Any]] = []
        for raw_chunk in raw_chunks:
            if not isinstance(raw_chunk, dict):
                raise _integrity_error(
                    "material_chunk_row_invalid",
                    "Chunk store rows must be JSON objects",
                )
            chunk = dict(raw_chunk)
            explicit_material_id = str(chunk.get("material_id") or "").strip()
            if explicit_material_id and explicit_material_id != material_id:
                raise _integrity_error(
                    "material_chunk_identity_mismatch",
                    "Chunk material identity differs from its store owner",
                )
            raw_chunk_id = chunk.get("chunk_id")
            if not isinstance(raw_chunk_id, str) or not raw_chunk_id.strip():
                raise _integrity_error(
                    "material_chunk_id_invalid",
                    "Chunk ids must be non-empty strings",
                )
            chunk_id = raw_chunk_id.strip()
            if chunk_id in chunk_ids:
                raise _integrity_error(
                    "material_chunk_id_duplicate",
                    "Chunk ids must be unique within a project",
                )
            chunk_ids.add(chunk_id)
            chunks.append(chunk)
        validated[material_id] = chunks
    return validated


def _save_chunk_store_unlocked(project_id: str, store: dict[str, list[dict[str, Any]]]) -> None:
    """Internal: Persist chunk store WITHOUT acquiring lock.
    
    Only call from within _rr._CHUNK_STORE_LOCK context or via public _save_chunk_store.
    Uses v2 incremental layout; only changed materials are rewritten.
    """
    store = _validate_chunk_store_candidate(store)
    project_dir = _chunk_store_dir(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = project_dir / "manifest.json"
    if manifest_path.exists():
        previous_store = _load_chunk_store_unlocked(project_id)
        old_manifest = _load_manifest(project_dir)
    else:
        previous_store = {}
        old_manifest = {"version": 2, "materials": {}}
    old_materials: dict[str, dict[str, Any]] = old_manifest.get("materials", {}) or {}
    new_materials: dict[str, dict[str, Any]] = {}
    accepted_store: dict[str, list[dict[str, Any]]] = {}
    ledger_entries: list[ChunkIndexBackfillLedgerEntry] = []
    ledger_timestamp = utc_now_iso()
    used_filenames: set[str] = set()

    for material_id, chunks in store.items():
        incoming_chunks = list(chunks or [])
        previous_chunks = previous_store.get(material_id, [])
        prev = old_materials.get(material_id)
        reusable_entry = _reusable_unchanged_material_entry(
            project_dir=project_dir,
            incoming_chunks=incoming_chunks,
            previous_chunks=previous_chunks,
            previous_entry=prev if isinstance(prev, dict) else None,
        )
        if reusable_entry is not None:
            relative_path = str(reusable_entry["relative_path"])
            if relative_path not in used_filenames:
                used_filenames.add(relative_path)
                new_materials[material_id] = reusable_entry
                accepted_store[material_id] = previous_chunks
                ledger_entries.extend(
                    transition_entries_for_material(
                        project_id=project_id,
                        material_id=material_id,
                        previous_chunks=previous_chunks,
                        current_chunks=previous_chunks,
                        timestamp=ledger_timestamp,
                    )
                )
                continue

        chunks_with_hashes = _with_chunk_hashes_for_store(material_id, incoming_chunks)
        chunks_list, quarantined_chunks = _partition_quarantined_chunks(project_id, material_id, chunks_with_hashes)
        for chunk in quarantined_chunks:
            ledger_entries.append(
                make_chunk_index_backfill_entry(
                    project_id=project_id,
                    material_id=material_id,
                    chunk=chunk,
                    status="quarantined",
                    reason="oversize_quarantined",
                    timestamp=ledger_timestamp,
                )
            )
        if not chunks_list and quarantined_chunks:
            continue
        ledger_entries.extend(
            transition_entries_for_material(
                project_id=project_id,
                material_id=material_id,
                previous_chunks=previous_store.get(material_id, []),
                current_chunks=chunks_list,
                timestamp=ledger_timestamp,
            )
        )
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

        persisted_chunks = _read_material_jsonl(target, material_id=material_id)
        if len(persisted_chunks) != len(chunks_list) or _hash_chunks(persisted_chunks) != chunk_hash:
            raise _integrity_error(
                "material_chunk_generation_mismatch",
                "Published chunk generation differs from the validated candidate",
            )

        new_materials[material_id] = {
            "relative_path": file_name,
            "sha256": chunk_hash,
            "total_chunks": len(chunks_list),
        }
        accepted_store[material_id] = persisted_chunks

    try:
        linter_report = ChunkEvidenceUnitLinter().lint_chunks(
            [dict(chunk) for material_chunks in accepted_store.values() for chunk in material_chunks if isinstance(chunk, dict)]
        )
        ledger_entries.extend(
            linter_entries_for_store(
                project_id=project_id,
                store=accepted_store,
                report=linter_report,
                timestamp=ledger_timestamp,
            )
        )
    except (TypeError, ValueError):
        pass
    ledger_entries = merge_chunk_index_backfill_ledger_entries(
        existing_entries=_read_chunk_index_backfill_ledger(project_id),
        current_entries=ledger_entries,
        timestamp=ledger_timestamp,
    )
    _write_chunk_index_backfill_ledger(project_id, ledger_entries)

    chunk_store_version_fields = _chunk_store_version_payload(accepted_store)
    manifest_payload = {
        "version": 2,
        "materials": new_materials,
        **chunk_store_version_fields,
        **_chunk_store_linter_payload(accepted_store),
        **_chunk_index_backfill_manifest_payload(project_id, ledger_entries),
        **_chunk_fts_index_manifest_payload(
            project_id=project_id,
            store=accepted_store,
            chunk_store_version=chunk_store_version_fields.get("chunk_store_version"),
            chunk_store_version_status=str(chunk_store_version_fields.get("chunk_store_version_status") or ""),
        ),
    }
    _atomic_write_text(
        project_dir / "manifest.json",
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
    )

    # A generation remains reachable until the new manifest is durable.
    keep_files = {
        str(entry.get("relative_path") or entry.get("file") or "")
        for entry in new_materials.values()
        if str(entry.get("relative_path") or entry.get("file") or "")
    }
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

    if not rejected:
        return accepted, rejected

    quarantine_dir = _chunk_quarantine_dir(project_id)
    digest = hashlib.md5(material_id.encode("utf-8")).hexdigest()[:8]
    for path in quarantine_dir.glob(f"*_{digest}.jsonl"):
        try:
            path.unlink()
        except OSError:
            pass

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
