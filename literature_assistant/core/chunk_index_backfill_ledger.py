# -*- coding: utf-8 -*-
"""Backfill and quarantine ledger helpers for chunk derived indexes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, TypedDict

if TYPE_CHECKING:
    from literature_assistant.core.chunk_evidence_linter import ChunkEvidenceLintReport
    from literature_assistant.core.chunk_hashing import (
        CHUNK_HASH_VERSION,
        ChunkHashTransition,
        classify_chunk_hash_transition,
        compute_chunk_hashes,
    )
else:
    from chunk_evidence_linter import ChunkEvidenceLintReport
    from chunk_hashing import (
        CHUNK_HASH_VERSION,
        ChunkHashTransition,
        classify_chunk_hash_transition,
        compute_chunk_hashes,
    )


CHUNK_INDEX_BACKFILL_LEDGER_SCHEMA_VERSION = "scholar-ai-chunk-index-backfill-ledger/v1"

ChunkIndexBackfillStatus = Literal["pending", "running", "done", "failed", "quarantined"]
ChunkIndexBackfillReason = Literal[
    "truth_changed",
    "embedding_changed",
    "truth_changed_embedding_unchanged",
    "linter_error",
    "hash_unavailable",
    "oversize_quarantined",
]


_ALLOWED_STATUS_TRANSITIONS: dict[ChunkIndexBackfillStatus, set[ChunkIndexBackfillStatus]] = {
    "pending": {"running", "quarantined"},
    "running": {"done", "failed", "quarantined"},
    "failed": {"pending", "running", "quarantined"},
    "done": set(),
    "quarantined": {"pending"},
}


class ChunkIndexBackfillLedgerEntry(TypedDict):
    """Machine-readable derived-index state for one chunk."""

    schema_version: str
    project_id: str
    material_id: str
    chunk_id: str
    chunk_hash: str
    embedding_input_hash: str
    hash_version: str
    contract_hash: str
    status: ChunkIndexBackfillStatus
    reason: ChunkIndexBackfillReason
    transition: str
    lint_codes: list[str]
    attempts: int
    created_at: str
    updated_at: str
    last_error: str


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp for ledger records."""

    return datetime.now(timezone.utc).isoformat()


def _bounded_text(value: object, *, max_chars: int = 240) -> str:
    return str(value or "").strip()[:max_chars]


def _chunk_id(chunk: Mapping[str, Any]) -> str:
    return _bounded_text(chunk.get("chunk_id"))


def _chunk_hash_fields(chunk: Mapping[str, Any], *, material_id: str) -> tuple[str, str, str]:
    try:
        hashes = compute_chunk_hashes(chunk, material_id_hint=material_id)
    except (TypeError, ValueError):
        return "", "", ""
    return hashes["chunk_hash"], hashes["embedding_input_hash"], hashes["hash_version"]


def _entry_key(entry: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        _bounded_text(entry.get("project_id")),
        _bounded_text(entry.get("material_id")),
        _bounded_text(entry.get("chunk_id")),
        _bounded_text(entry.get("chunk_hash")),
        _bounded_text(entry.get("embedding_input_hash")),
        _bounded_text(entry.get("reason")),
    )


def make_chunk_index_backfill_entry(
    *,
    project_id: str,
    material_id: str,
    chunk: Mapping[str, Any],
    status: ChunkIndexBackfillStatus,
    reason: ChunkIndexBackfillReason,
    transition: str = "",
    lint_codes: Sequence[str] | None = None,
    timestamp: str | None = None,
) -> ChunkIndexBackfillLedgerEntry:
    """Build one normalized ledger entry without mutating the chunk.

    Args:
        project_id: Non-empty project id owning the chunk store.
        material_id: Non-empty material id owning the row.
        chunk: Chunk mapping from truth store or quarantine output.
        status: Current derived-index state.
        reason: Stable machine-readable cause.
        transition: Optional hash transition classifier.
        lint_codes: Optional deterministic lint error codes.
        timestamp: Optional precomputed UTC timestamp for deterministic batches.

    Returns:
        A JSON-serializable ledger entry.
    """

    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(material_id, str) or not material_id.strip():
        raise ValueError("material_id must be a non-empty string")
    if not isinstance(chunk, Mapping):
        raise TypeError("chunk must be a mapping")

    now = timestamp or utc_now_iso()
    chunk_hash, embedding_input_hash, hash_version = _chunk_hash_fields(chunk, material_id=material_id)
    if not hash_version:
        hash_version = CHUNK_HASH_VERSION
    normalized_codes = sorted({_bounded_text(code, max_chars=80) for code in (lint_codes or []) if code})
    return {
        "schema_version": CHUNK_INDEX_BACKFILL_LEDGER_SCHEMA_VERSION,
        "project_id": project_id.strip(),
        "material_id": material_id.strip(),
        "chunk_id": _chunk_id(chunk),
        "chunk_hash": chunk_hash,
        "embedding_input_hash": embedding_input_hash,
        "hash_version": hash_version,
        "contract_hash": "",
        "status": status,
        "reason": reason,
        "transition": _bounded_text(transition, max_chars=80),
        "lint_codes": normalized_codes,
        "attempts": 0,
        "created_at": now,
        "updated_at": now,
        "last_error": "",
    }


def transition_to_backfill_reason(transition: ChunkHashTransition) -> ChunkIndexBackfillReason | None:
    """Return the ledger reason required by a hash transition."""

    if transition == "truth_changed_embedding_unchanged":
        return "truth_changed_embedding_unchanged"
    if transition == "truth_changed":
        return "truth_changed"
    if transition == "embedding_changed":
        return "embedding_changed"
    return None


def transition_entries_for_material(
    *,
    project_id: str,
    material_id: str,
    previous_chunks: Sequence[Mapping[str, Any]],
    current_chunks: Sequence[Mapping[str, Any]],
    timestamp: str | None = None,
) -> list[ChunkIndexBackfillLedgerEntry]:
    """Return pending ledger entries for changed chunks in one material.

    Previous and current rows are matched by ``chunk_id``. Rows without stable
    ids are handled by linter/hash policy instead of positional matching.
    """

    if isinstance(previous_chunks, (str, bytes)) or not isinstance(previous_chunks, Sequence):
        raise TypeError("previous_chunks must be a sequence of mappings")
    if isinstance(current_chunks, (str, bytes)) or not isinstance(current_chunks, Sequence):
        raise TypeError("current_chunks must be a sequence of mappings")

    previous_by_id: dict[str, Mapping[str, Any]] = {}
    for chunk in previous_chunks:
        if isinstance(chunk, Mapping):
            chunk_id = _chunk_id(chunk)
            if chunk_id:
                previous_by_id[chunk_id] = chunk

    entries: list[ChunkIndexBackfillLedgerEntry] = []
    for chunk in current_chunks:
        if not isinstance(chunk, Mapping):
            continue
        chunk_id = _chunk_id(chunk)
        previous = previous_by_id.get(chunk_id)
        if previous is None:
            continue
        transition = classify_chunk_hash_transition(previous, chunk, material_id_hint=material_id)
        reason = transition_to_backfill_reason(transition)
        if reason is None:
            continue
        entries.append(
            make_chunk_index_backfill_entry(
                project_id=project_id,
                material_id=material_id,
                chunk=chunk,
                status="pending",
                reason=reason,
                transition=transition,
                timestamp=timestamp,
            )
        )
    return entries


def linter_entries_for_store(
    *,
    project_id: str,
    store: Mapping[str, Sequence[Mapping[str, Any]]],
    report: ChunkEvidenceLintReport,
    timestamp: str | None = None,
) -> list[ChunkIndexBackfillLedgerEntry]:
    """Return quarantined ledger entries for chunks with deterministic errors."""

    if not isinstance(store, Mapping):
        raise TypeError("store must be a mapping of material ids to chunk sequences")

    error_codes_by_key: dict[tuple[str, str], set[str]] = {}
    for issue in report.issues:
        if issue.severity != "error":
            continue
        key = (_bounded_text(issue.material_id), _bounded_text(issue.chunk_id))
        error_codes_by_key.setdefault(key, set()).add(issue.code)

    entries: list[ChunkIndexBackfillLedgerEntry] = []
    for raw_material_id, chunks in sorted(store.items(), key=lambda item: str(item[0])):
        material_id = _bounded_text(raw_material_id)
        if not material_id or isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
            continue
        for chunk in chunks:
            if not isinstance(chunk, Mapping):
                continue
            key = (material_id, _chunk_id(chunk))
            lint_codes = sorted(error_codes_by_key.get(key, set()))
            if not lint_codes:
                continue
            reason: ChunkIndexBackfillReason = "hash_unavailable" if "hash_unavailable" in lint_codes else "linter_error"
            entries.append(
                make_chunk_index_backfill_entry(
                    project_id=project_id,
                    material_id=material_id,
                    chunk=chunk,
                    status="quarantined",
                    reason=reason,
                    lint_codes=lint_codes,
                    timestamp=timestamp,
                )
            )
    return entries


def merge_chunk_index_backfill_ledger_entries(
    *,
    existing_entries: Sequence[Mapping[str, Any]],
    current_entries: Sequence[ChunkIndexBackfillLedgerEntry],
    timestamp: str | None = None,
) -> list[ChunkIndexBackfillLedgerEntry]:
    """Preserve worker state for unchanged ledger keys.

    Existing ``attempts``, ``created_at``, ``last_error`` and terminal status
    remain attached to identical chunk/hash/reason keys so a chunk-store save
    does not erase Phase 2 worker progress.
    """

    if isinstance(existing_entries, (str, bytes)) or not isinstance(existing_entries, Sequence):
        raise TypeError("existing_entries must be a sequence of mappings")
    if isinstance(current_entries, (str, bytes)) or not isinstance(current_entries, Sequence):
        raise TypeError("current_entries must be a sequence of ledger entries")

    existing_by_key = {
        _entry_key(entry): entry
        for entry in existing_entries
        if isinstance(entry, Mapping) and _bounded_text(entry.get("schema_version")) == CHUNK_INDEX_BACKFILL_LEDGER_SCHEMA_VERSION
    }
    now = timestamp or utc_now_iso()
    merged: list[ChunkIndexBackfillLedgerEntry] = []
    for entry in current_entries:
        existing = existing_by_key.get(_entry_key(entry))
        next_entry: ChunkIndexBackfillLedgerEntry = dict(entry)  # type: ignore[assignment]
        if existing is not None:
            previous_status = _bounded_text(existing.get("status"), max_chars=32)
            if previous_status in {"running", "done", "failed", "quarantined"}:
                next_entry["status"] = previous_status  # type: ignore[typeddict-item]
            next_entry["attempts"] = int(existing.get("attempts") or 0)
            next_entry["created_at"] = _bounded_text(existing.get("created_at")) or entry["created_at"]
            next_entry["last_error"] = _bounded_text(existing.get("last_error"))
        next_entry["updated_at"] = now
        merged.append(next_entry)

    merged.sort(key=lambda item: (item["status"], item["reason"], item["material_id"], item["chunk_id"], item["chunk_hash"]))
    return merged


def ledger_status_counts(entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Return stable status counts for a ledger entry sequence."""

    if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
        raise TypeError("entries must be a sequence of mappings")
    counts: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        status = _bounded_text(entry.get("status"), max_chars=32) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def update_chunk_index_backfill_status(
    entry: Mapping[str, Any],
    *,
    status: ChunkIndexBackfillStatus,
    last_error: str = "",
    timestamp: str | None = None,
) -> ChunkIndexBackfillLedgerEntry:
    """Return a ledger entry with a validated worker state transition.

    Args:
        entry: Existing ledger entry under the current schema.
        status: Target state. Illegal transitions raise instead of silently
            corrupting the backfill ledger.
        last_error: Required for ``failed`` and cleared for ``running``/``done``.
        timestamp: Optional precomputed UTC timestamp for deterministic tests.

    Returns:
        A new ledger entry preserving all identity and hash fields.
    """

    if not isinstance(entry, Mapping):
        raise TypeError("entry must be a mapping")
    if _bounded_text(entry.get("schema_version")) != CHUNK_INDEX_BACKFILL_LEDGER_SCHEMA_VERSION:
        raise ValueError("entry schema_version is not supported")

    current_status = _bounded_text(entry.get("status"), max_chars=32)
    if current_status not in _ALLOWED_STATUS_TRANSITIONS:
        raise ValueError(f"entry status is not supported: {current_status}")
    if status != current_status and status not in _ALLOWED_STATUS_TRANSITIONS[current_status]:  # type: ignore[index]
        raise ValueError(f"illegal backfill status transition: {current_status} -> {status}")
    if status == "failed" and not _bounded_text(last_error):
        raise ValueError("last_error is required when status is failed")

    now = timestamp or utc_now_iso()
    updated: ChunkIndexBackfillLedgerEntry = {
        "schema_version": CHUNK_INDEX_BACKFILL_LEDGER_SCHEMA_VERSION,
        "project_id": _bounded_text(entry.get("project_id")),
        "material_id": _bounded_text(entry.get("material_id")),
        "chunk_id": _bounded_text(entry.get("chunk_id")),
        "chunk_hash": _bounded_text(entry.get("chunk_hash"), max_chars=64),
        "embedding_input_hash": _bounded_text(entry.get("embedding_input_hash"), max_chars=64),
        "hash_version": _bounded_text(entry.get("hash_version"), max_chars=80) or CHUNK_HASH_VERSION,
        "contract_hash": _bounded_text(entry.get("contract_hash"), max_chars=120),
        "status": status,
        "reason": _bounded_text(entry.get("reason"), max_chars=80),  # type: ignore[typeddict-item]
        "transition": _bounded_text(entry.get("transition"), max_chars=80),
        "lint_codes": [
            _bounded_text(code, max_chars=80)
            for code in entry.get("lint_codes", [])
            if _bounded_text(code, max_chars=80)
        ]
        if isinstance(entry.get("lint_codes"), Sequence) and not isinstance(entry.get("lint_codes"), (str, bytes))
        else [],
        "attempts": int(entry.get("attempts") or 0),
        "created_at": _bounded_text(entry.get("created_at")) or now,
        "updated_at": now,
        "last_error": _bounded_text(last_error) if status == "failed" else "",
    }
    if status == "running" and current_status != "running":
        updated["attempts"] += 1
    return updated
