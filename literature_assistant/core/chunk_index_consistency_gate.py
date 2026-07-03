# -*- coding: utf-8 -*-
"""Consistency gate for derived chunk indexes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from chunk_hashing import compute_chunk_hashes


IndexConsistencyStatus = Literal[
    "valid",
    "stale",
    "pending_index",
    "corrupt_missing_truth",
    "corrupt_missing_index",
    "contract_mismatch",
    "split_brain",
]

IndexCandidateSource = Literal["dense", "lexical", "visual", "unknown"]

_ACTIVE_BACKFILL_STATUSES = {"pending", "running", "failed"}


@dataclass(frozen=True)
class ChunkTruthRecord:
    """Current truth-store identity and hashes for one chunk."""

    project_id: str
    material_id: str
    chunk_id: str
    chunk_hash: str
    embedding_input_hash: str
    hash_version: str

    @property
    def key(self) -> tuple[str, str]:
        """Return the material/chunk key used by derived indexes."""

        return (self.material_id, self.chunk_id)

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serializable truth record."""

        return {
            "project_id": self.project_id,
            "material_id": self.material_id,
            "chunk_id": self.chunk_id,
            "chunk_hash": self.chunk_hash,
            "embedding_input_hash": self.embedding_input_hash,
            "hash_version": self.hash_version,
        }


@dataclass(frozen=True)
class IndexedChunkRecord:
    """Derived-index metadata for one retrieved or indexed chunk row."""

    project_id: str
    material_id: str
    chunk_id: str
    chunk_hash: str
    embedding_input_hash: str
    contract_hash: str
    source: IndexCandidateSource = "dense"
    score: float | None = None

    @property
    def key(self) -> tuple[str, str]:
        """Return the material/chunk key used by truth lookup."""

        return (self.material_id, self.chunk_id)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable index record."""

        return {
            "project_id": self.project_id,
            "material_id": self.material_id,
            "chunk_id": self.chunk_id,
            "chunk_hash": self.chunk_hash,
            "embedding_input_hash": self.embedding_input_hash,
            "contract_hash": self.contract_hash,
            "source": self.source,
            "score": self.score,
        }


@dataclass(frozen=True)
class IndexConsistencyFinding:
    """Per-chunk gate decision for a truth row or derived-index row."""

    status: IndexConsistencyStatus
    project_id: str
    material_id: str
    chunk_id: str
    source: IndexCandidateSource
    reason: str
    truth: ChunkTruthRecord | None = None
    index: IndexedChunkRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a bounded, machine-readable gate finding."""

        return {
            "status": self.status,
            "project_id": self.project_id,
            "material_id": self.material_id,
            "chunk_id": self.chunk_id,
            "source": self.source,
            "reason": self.reason,
            "truth": self.truth.to_dict() if self.truth is not None else None,
            "index": self.index.to_dict() if self.index is not None else None,
        }


@dataclass(frozen=True)
class IndexConsistencyReport:
    """Aggregate gate output for a derived-index consistency check."""

    project_id: str
    expected_contract_hash: str
    dense_enabled: bool
    fallback_reason: str
    findings: tuple[IndexConsistencyFinding, ...] = field(default_factory=tuple)

    @property
    def status_counts(self) -> dict[str, int]:
        """Return stable counts by gate status."""

        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.status] = counts.get(finding.status, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def valid_indexes(self) -> tuple[IndexedChunkRecord, ...]:
        """Return index rows that are safe to enter a candidate pool."""

        return tuple(
            finding.index
            for finding in self.findings
            if finding.status == "valid" and finding.index is not None
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report payload."""

        return {
            "project_id": self.project_id,
            "expected_contract_hash": self.expected_contract_hash,
            "dense_enabled": self.dense_enabled,
            "fallback_reason": self.fallback_reason,
            "status_counts": self.status_counts,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def _require_non_empty_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _bounded_text(value: object, *, max_chars: int = 240) -> str:
    return str(value or "").strip()[:max_chars]


def _coerce_source(value: object) -> IndexCandidateSource:
    source = _bounded_text(value, max_chars=32)
    if source in {"dense", "lexical", "visual"}:
        return source  # type: ignore[return-value]
    return "unknown"


def _coerce_score(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def build_chunk_truth_records(
    *,
    project_id: str,
    store: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[tuple[str, str], ChunkTruthRecord]:
    """Build truth records from the current chunk store.

    Args:
        project_id: Non-empty project id owning the chunk store.
        store: Mapping of material ids to chunk mappings.

    Returns:
        Truth records keyed by ``(material_id, chunk_id)``.

    Raises:
        TypeError: If the store shape is not mapping -> sequence -> mapping.
        ValueError: If required identities are missing or duplicated.
    """

    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    if not isinstance(store, Mapping):
        raise TypeError("store must be a mapping of material ids to chunk sequences")

    records: dict[tuple[str, str], ChunkTruthRecord] = {}
    for raw_material_id, chunks in sorted(store.items(), key=lambda item: str(item[0])):
        material_id = _require_non_empty_string(str(raw_material_id), name="material_id")
        if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
            raise TypeError("store material values must be chunk sequences")
        for chunk in chunks:
            if not isinstance(chunk, Mapping):
                raise TypeError("store chunks must be mappings")
            chunk_id = _require_non_empty_string(_bounded_text(chunk.get("chunk_id")), name="chunk_id")
            hashes = compute_chunk_hashes(chunk, material_id_hint=material_id)
            record = ChunkTruthRecord(
                project_id=normalized_project_id,
                material_id=material_id,
                chunk_id=chunk_id,
                chunk_hash=hashes["chunk_hash"],
                embedding_input_hash=hashes["embedding_input_hash"],
                hash_version=hashes["hash_version"],
            )
            if record.key in records:
                raise ValueError(f"duplicate truth chunk key: {material_id}/{chunk_id}")
            records[record.key] = record
    return records


def indexed_chunk_record_from_mapping(
    row: Mapping[str, Any],
    *,
    project_id: str,
) -> IndexedChunkRecord:
    """Normalize one derived-index metadata row.

    Args:
        row: Mapping containing material/chunk id, hashes, and contract hash.
        project_id: Expected owning project id.

    Returns:
        A typed index row suitable for gate evaluation.
    """

    if not isinstance(row, Mapping):
        raise TypeError("row must be a mapping")
    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    row_project_id = _bounded_text(row.get("project_id")) or normalized_project_id
    if row_project_id != normalized_project_id:
        raise ValueError("index row project_id does not match gate project_id")
    return IndexedChunkRecord(
        project_id=normalized_project_id,
        material_id=_require_non_empty_string(_bounded_text(row.get("material_id")), name="material_id"),
        chunk_id=_require_non_empty_string(_bounded_text(row.get("chunk_id")), name="chunk_id"),
        chunk_hash=_require_non_empty_string(_bounded_text(row.get("chunk_hash"), max_chars=64), name="chunk_hash"),
        embedding_input_hash=_require_non_empty_string(
            _bounded_text(row.get("embedding_input_hash"), max_chars=64),
            name="embedding_input_hash",
        ),
        contract_hash=_require_non_empty_string(_bounded_text(row.get("contract_hash"), max_chars=120), name="contract_hash"),
        source=_coerce_source(row.get("source")),
        score=_coerce_score(row.get("score")),
    )


def _ledger_has_active_backfill(
    *,
    ledger_entries: Sequence[Mapping[str, Any]],
    truth: ChunkTruthRecord,
    expected_contract_hash: str,
) -> bool:
    if isinstance(ledger_entries, (str, bytes)) or not isinstance(ledger_entries, Sequence):
        raise TypeError("ledger_entries must be a sequence of mappings")
    for entry in ledger_entries:
        if not isinstance(entry, Mapping):
            continue
        if _bounded_text(entry.get("status"), max_chars=32) not in _ACTIVE_BACKFILL_STATUSES:
            continue
        if _bounded_text(entry.get("project_id")) != truth.project_id:
            continue
        if _bounded_text(entry.get("material_id")) != truth.material_id:
            continue
        if _bounded_text(entry.get("chunk_id")) != truth.chunk_id:
            continue
        entry_chunk_hash = _bounded_text(entry.get("chunk_hash"), max_chars=64)
        if entry_chunk_hash and entry_chunk_hash != truth.chunk_hash:
            continue
        entry_embedding_hash = _bounded_text(entry.get("embedding_input_hash"), max_chars=64)
        if entry_embedding_hash and entry_embedding_hash != truth.embedding_input_hash:
            continue
        entry_contract_hash = _bounded_text(entry.get("contract_hash"), max_chars=120)
        if entry_contract_hash and entry_contract_hash != expected_contract_hash:
            continue
        return True
    return False


def _fallback_reason(findings: Sequence[IndexConsistencyFinding]) -> str:
    statuses = {finding.status for finding in findings}
    if "split_brain" in statuses:
        return "dense_index_split_brain"
    if "contract_mismatch" in statuses:
        return "dense_index_contract_mismatch"
    if "stale" in statuses:
        return "dense_index_stale"
    if "corrupt_missing_truth" in statuses or "corrupt_missing_index" in statuses:
        return "dense_index_corrupt"
    if "pending_index" in statuses:
        return "dense_index_pending"
    return ""


def gate_chunk_index_consistency(
    *,
    project_id: str,
    store: Mapping[str, Sequence[Mapping[str, Any]]],
    index_records: Sequence[Mapping[str, Any] | IndexedChunkRecord],
    ledger_entries: Sequence[Mapping[str, Any]],
    expected_contract_hash: str,
) -> IndexConsistencyReport:
    """Validate derived-index rows against chunk-store truth and ledger state.

    Args:
        project_id: Non-empty project id being checked.
        store: Current chunk-store truth.
        index_records: Derived-index metadata rows or typed records.
        ledger_entries: Backfill ledger rows for the same project.
        expected_contract_hash: Current embedding contract hash for dense rows.

    Returns:
        A report whose ``valid_indexes`` are the only safe rows for recall.
    """

    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    normalized_contract_hash = _require_non_empty_string(expected_contract_hash, name="expected_contract_hash")
    if isinstance(index_records, (str, bytes)) or not isinstance(index_records, Sequence):
        raise TypeError("index_records must be a sequence")

    truth_by_key = build_chunk_truth_records(project_id=normalized_project_id, store=store)
    normalized_indexes = tuple(
        row
        if isinstance(row, IndexedChunkRecord)
        else indexed_chunk_record_from_mapping(row, project_id=normalized_project_id)
        for row in index_records
    )
    contract_hashes = {row.contract_hash for row in normalized_indexes}

    findings: list[IndexConsistencyFinding] = []
    if len(contract_hashes) > 1:
        for row in normalized_indexes:
            findings.append(
                IndexConsistencyFinding(
                    status="split_brain",
                    project_id=normalized_project_id,
                    material_id=row.material_id,
                    chunk_id=row.chunk_id,
                    source=row.source,
                    reason="index_contains_multiple_contract_hashes",
                    truth=truth_by_key.get(row.key),
                    index=row,
                )
            )
        return IndexConsistencyReport(
            project_id=normalized_project_id,
            expected_contract_hash=normalized_contract_hash,
            dense_enabled=False,
            fallback_reason="dense_index_split_brain",
            findings=tuple(findings),
        )

    indexed_keys: set[tuple[str, str]] = set()
    for row in normalized_indexes:
        indexed_keys.add(row.key)
        truth = truth_by_key.get(row.key)
        if truth is None:
            findings.append(
                IndexConsistencyFinding(
                    status="corrupt_missing_truth",
                    project_id=normalized_project_id,
                    material_id=row.material_id,
                    chunk_id=row.chunk_id,
                    source=row.source,
                    reason="index_row_missing_from_chunk_store",
                    index=row,
                )
            )
            continue
        if row.contract_hash != normalized_contract_hash:
            findings.append(
                IndexConsistencyFinding(
                    status="contract_mismatch",
                    project_id=normalized_project_id,
                    material_id=row.material_id,
                    chunk_id=row.chunk_id,
                    source=row.source,
                    reason="index_contract_hash_does_not_match_current_contract",
                    truth=truth,
                    index=row,
                )
            )
            continue
        if row.chunk_hash != truth.chunk_hash or row.embedding_input_hash != truth.embedding_input_hash:
            findings.append(
                IndexConsistencyFinding(
                    status="stale",
                    project_id=normalized_project_id,
                    material_id=row.material_id,
                    chunk_id=row.chunk_id,
                    source=row.source,
                    reason="index_hashes_do_not_match_chunk_store_truth",
                    truth=truth,
                    index=row,
                )
            )
            continue
        findings.append(
            IndexConsistencyFinding(
                status="valid",
                project_id=normalized_project_id,
                material_id=row.material_id,
                chunk_id=row.chunk_id,
                source=row.source,
                reason="index_matches_chunk_store_truth",
                truth=truth,
                index=row,
            )
        )

    for key, truth in sorted(truth_by_key.items()):
        if key in indexed_keys:
            continue
        if _ledger_has_active_backfill(
            ledger_entries=ledger_entries,
            truth=truth,
            expected_contract_hash=normalized_contract_hash,
        ):
            findings.append(
                IndexConsistencyFinding(
                    status="pending_index",
                    project_id=normalized_project_id,
                    material_id=truth.material_id,
                    chunk_id=truth.chunk_id,
                    source="dense",
                    reason="truth_row_has_active_backfill_ledger_entry",
                    truth=truth,
                )
            )
            continue
        findings.append(
            IndexConsistencyFinding(
                status="corrupt_missing_index",
                project_id=normalized_project_id,
                material_id=truth.material_id,
                chunk_id=truth.chunk_id,
                source="dense",
                reason="truth_row_missing_from_index_without_active_backfill",
                truth=truth,
            )
        )

    fallback_reason = _fallback_reason(findings)
    return IndexConsistencyReport(
        project_id=normalized_project_id,
        expected_contract_hash=normalized_contract_hash,
        dense_enabled=fallback_reason not in {"dense_index_split_brain", "dense_index_contract_mismatch"},
        fallback_reason=fallback_reason,
        findings=tuple(findings),
    )
