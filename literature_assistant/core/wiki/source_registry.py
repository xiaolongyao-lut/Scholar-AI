from __future__ import annotations

import hashlib
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:  # pragma: no cover - package/flat import compatibility.
    from literature_assistant.core.source_vault import (
        SourceChunkInput as VaultChunkInput,
        SourceVault,
        derive_chunk_id as derive_vault_chunk_id,
        derive_source_id as derive_vault_source_id,
    )
except ImportError:  # pragma: no cover
    from source_vault import (
        SourceChunkInput as VaultChunkInput,
        SourceVault,
        derive_chunk_id as derive_vault_chunk_id,
        derive_source_id as derive_vault_source_id,
    )


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wiki_sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_vault_id TEXT,
    source_vault_status TEXT NOT NULL DEFAULT 'not_mirrored',
    source_vault_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wiki_chunks (
    chunk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    page TEXT,
    section TEXT,
    span_start INTEGER,
    span_end INTEGER,
    source_vault_chunk_id TEXT,
    source_vault_status TEXT NOT NULL DEFAULT 'not_mirrored',
    source_vault_error TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES wiki_sources(source_id)
);
CREATE INDEX IF NOT EXISTS idx_wiki_chunks_source_id ON wiki_chunks(source_id);
"""

WIKI_SOURCE_VAULT_PARSER_VERSION = "wiki-source-registry-v1"
WIKI_SOURCE_VAULT_CHUNKER_VERSION = "wiki-source-registry-v1"


def utc_now_iso() -> str:
    """Return a UTC timestamp for registry records."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class SourceRecord:
    """Legacy Wiki source record plus optional Source Vault mapping."""

    source_id: str
    source_type: str
    title: str
    source_hash: str
    source_path: Path
    source_vault_id: str | None = None


@dataclass(frozen=True)
class ChunkInput:
    """Legacy Wiki chunk input shape."""

    text: str
    chunk_index: int
    page: str | None = None
    section: str | None = None
    span_start: int | None = None
    span_end: int | None = None


@dataclass(frozen=True)
class SourceVaultReplayReport:
    """Replay summary for preexisting Wiki registry rows.

    The status maps are keyed by persisted Source Vault mirror statuses such as
    ``mirrored`` or ``blocked`` so callers can block on incomplete sync without
    inferring success from row counts alone.
    """

    source_count: int
    chunk_count: int
    source_status_counts: dict[str, int]
    chunk_status_counts: dict[str, int]


@dataclass(frozen=True)
class SourceVaultMirrorBacklogItem:
    """One Wiki registry row that is not currently mirrored into Source Vault."""

    record_type: str
    record_id: str
    source_id: str
    status: str
    error: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return a stable JSON-safe diagnostic shape."""

        return {
            "record_type": self.record_type,
            "record_id": self.record_id,
            "source_id": self.source_id,
            "status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True)
class SourceVaultMirrorBacklogReport:
    """Read-only Source Vault mirror backlog summary for Wiki registry rows."""

    source_count: int
    chunk_count: int
    source_status_counts: dict[str, int]
    chunk_status_counts: dict[str, int]
    pending_source_count: int
    pending_chunk_count: int
    samples: tuple[SourceVaultMirrorBacklogItem, ...]

    @property
    def needs_replay(self) -> bool:
        """Return whether any registry rows are not mirrored."""

        return self.pending_source_count > 0 or self.pending_chunk_count > 0

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-safe diagnostic shape."""

        return {
            "source_count": self.source_count,
            "chunk_count": self.chunk_count,
            "source_status_counts": self.source_status_counts,
            "chunk_status_counts": self.chunk_status_counts,
            "pending_source_count": self.pending_source_count,
            "pending_chunk_count": self.pending_chunk_count,
            "needs_replay": self.needs_replay,
            "samples": [sample.to_dict() for sample in self.samples],
        }


def sha256_text(value: str) -> str:
    """Hash non-empty text with SHA-256."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if not value:
        raise ValueError("value cannot be empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def derive_source_id(source_type: str, title: str, source_hash: str) -> str:
    """Derive the legacy Wiki source id."""

    source_type = source_type.strip().lower()
    title = title.strip()
    if not source_type or not title or not source_hash:
        raise ValueError("source_type, title, and source_hash are required")
    readable = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
    readable = "-".join(part for part in readable.split("-") if part)[:64] or "source"
    return f"{source_type}-{readable}-{source_hash[:12]}"


def derive_chunk_id(source_hash: str, chunk_index: int) -> str:
    """Derive the legacy Wiki chunk id."""

    if not source_hash:
        raise ValueError("source_hash is required")
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    return hashlib.sha256(f"{source_hash}:{chunk_index}".encode("utf-8")).hexdigest()[:16]


class WikiRegistry:
    """Compatibility registry for Wiki sources mirrored into Source Vault."""

    def __init__(
        self,
        db_path: Path,
        *,
        source_vault: SourceVault | None = None,
        mirror_to_source_vault: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self._source_vault = source_vault
        self._mirror_to_source_vault = mirror_to_source_vault
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._ensure_compat_columns(conn)

    def connect(self) -> sqlite3.Connection:
        """Open a registry connection with row access and foreign keys."""

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def upsert_source(self, record: SourceRecord, *, now_iso: str) -> bool:
        """Upsert a legacy Wiki source and best-effort mirror it to Source Vault."""

        if not isinstance(record, SourceRecord):
            raise TypeError("record must be a SourceRecord")
        if not record.source_id or not record.source_hash:
            raise ValueError("source_id and source_hash are required")
        fallback_vault_id = _safe_vault_source_id(record.source_hash)
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT source_hash FROM wiki_sources WHERE source_id = ?",
                (record.source_id,),
            ).fetchone()
            if existing and existing["source_hash"] != record.source_hash:
                raise ValueError(
                    f"source immutability violation for {record.source_id}: "
                    f"{existing['source_hash']} != {record.source_hash}"
                )
            conn.execute(
                """
                INSERT INTO wiki_sources (
                    source_id, source_type, title, source_hash, source_path,
                    source_vault_id, source_vault_status, source_vault_error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title = excluded.title,
                    source_path = excluded.source_path,
                    source_vault_id = COALESCE(wiki_sources.source_vault_id, excluded.source_vault_id),
                    updated_at = excluded.updated_at
                """,
                (
                    record.source_id,
                    record.source_type,
                    record.title,
                    record.source_hash,
                    str(record.source_path),
                    fallback_vault_id,
                    "not_mirrored",
                    None,
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
            created = existing is None
        if self._mirror_to_source_vault:
            self._mirror_source_to_vault(record, now_iso=now_iso)
        return created

    def get_source(self, source_id: str) -> SourceRecord | None:
        """Return a legacy Wiki source by id."""

        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT source_id, source_type, title, source_hash, source_path, source_vault_id
                FROM wiki_sources
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
            if not row:
                return None
            return SourceRecord(
                source_id=row["source_id"],
                source_type=row["source_type"],
                title=row["title"],
                source_hash=row["source_hash"],
                source_path=Path(row["source_path"]),
                source_vault_id=row["source_vault_id"],
            )

    def list_sources(self) -> list[SourceRecord]:
        """List legacy Wiki sources with optional Source Vault ids."""

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT source_id, source_type, title, source_hash, source_path, source_vault_id
                FROM wiki_sources
                ORDER BY created_at
                """
            ).fetchall()
            return [
                SourceRecord(
                    source_id=row["source_id"],
                    source_type=row["source_type"],
                    title=row["title"],
                    source_hash=row["source_hash"],
                    source_path=Path(row["source_path"]),
                    source_vault_id=row["source_vault_id"],
                )
                for row in rows
            ]

    def register_chunks(self, source_id: str, source_hash: str, chunks: Iterable[ChunkInput], *, now_iso: str) -> int:
        """Register legacy Wiki chunks and best-effort mirror them to Source Vault."""

        if not source_id or not source_hash:
            raise ValueError("source_id and source_hash are required")
        chunk_list = list(chunks)
        if not chunk_list:
            raise ValueError("chunks cannot be empty")
        with self.connect() as conn:
            existing_source = conn.execute(
                """
                SELECT source_hash
                FROM wiki_sources
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
            if not existing_source:
                raise ValueError(f"source {source_id} not found; register source first")
            if existing_source["source_hash"] != source_hash:
                raise ValueError(
                    f"source_hash mismatch for {source_id}: "
                    f"{existing_source['source_hash']} != {source_hash}"
                )
            inserted = 0
            legacy_to_index: dict[str, int] = {}
            for chunk in chunk_list:
                if not isinstance(chunk, ChunkInput):
                    raise TypeError("chunks must contain ChunkInput records")
                chunk_id = derive_chunk_id(source_hash, chunk.chunk_index)
                text_hash = sha256_text(chunk.text)
                conn.execute(
                    """
                    INSERT INTO wiki_chunks (
                        chunk_id, source_id, source_hash, chunk_index, text_hash, text,
                        page, section, span_start, span_end, source_vault_chunk_id,
                        source_vault_status, source_vault_error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        text = excluded.text,
                        text_hash = excluded.text_hash,
                        page = excluded.page,
                        section = excluded.section,
                        span_start = excluded.span_start,
                        span_end = excluded.span_end,
                        source_vault_chunk_id = COALESCE(wiki_chunks.source_vault_chunk_id, excluded.source_vault_chunk_id)
                    """,
                    (
                        chunk_id,
                        source_id,
                        source_hash,
                        chunk.chunk_index,
                        text_hash,
                        chunk.text,
                        chunk.page,
                        chunk.section,
                        chunk.span_start,
                        chunk.span_end,
                        _safe_vault_chunk_id(source_hash, chunk.chunk_index),
                        "not_mirrored",
                        None,
                        now_iso,
                    ),
                )
                legacy_to_index[chunk_id] = chunk.chunk_index
                inserted += 1
            conn.commit()
        if self._mirror_to_source_vault:
            self._mirror_chunks_to_vault(source_id, source_hash, chunk_list, legacy_to_index, now_iso=now_iso)
        return inserted

    def replay_source_vault_mirror(
        self,
        *,
        source_ids: Iterable[str] | None = None,
        now_iso: str | None = None,
    ) -> SourceVaultReplayReport:
        """Replay existing Wiki registry rows into Source Vault.

        Args:
            source_ids: Optional explicit source ids. When omitted, all registry
                sources are replayed in registry order.
            now_iso: Optional stable timestamp used for deterministic tests.

        Returns:
            Counts for visited sources/chunks and their final mirror statuses.
        """

        replayed_at = now_iso or utc_now_iso()
        if not isinstance(replayed_at, str) or not replayed_at.strip():
            raise ValueError("now_iso cannot be empty")

        if source_ids is None:
            sources = self.list_sources()
        else:
            requested_ids = list(source_ids)
            if any(not isinstance(source_id, str) or not source_id.strip() for source_id in requested_ids):
                raise ValueError("source_ids must contain non-empty strings")
            sources = [source for source_id in requested_ids if (source := self.get_source(source_id)) is not None]

        source_status_counts: dict[str, int] = {}
        chunk_status_counts: dict[str, int] = {}
        chunk_count = 0
        for source in sources:
            self._mirror_source_to_vault(source, now_iso=replayed_at)
            source_status = self.get_source_vault_mirror_status(source.source_id)["status"]
            _increment_count(source_status_counts, source_status)

            chunk_rows = self.get_chunks_by_source(source.source_id)
            chunk_inputs: list[ChunkInput] = []
            legacy_to_index: dict[str, int] = {}
            for row in chunk_rows:
                chunk_index = int(row["chunk_index"])
                legacy_chunk_id = str(row["chunk_id"])
                chunk_inputs.append(
                    ChunkInput(
                        text=str(row["text"]),
                        chunk_index=chunk_index,
                        page=row["page"] if isinstance(row["page"], str) else None,
                        section=row["section"] if isinstance(row["section"], str) else None,
                        span_start=row["span_start"] if isinstance(row["span_start"], int) else None,
                        span_end=row["span_end"] if isinstance(row["span_end"], int) else None,
                    )
                )
                legacy_to_index[legacy_chunk_id] = chunk_index

            if chunk_inputs:
                self._mirror_chunks_to_vault(
                    source.source_id,
                    source.source_hash,
                    chunk_inputs,
                    legacy_to_index,
                    now_iso=replayed_at,
                )
            for legacy_chunk_id in legacy_to_index:
                chunk_status = self.get_source_vault_chunk_mirror_status(legacy_chunk_id)["status"]
                _increment_count(chunk_status_counts, chunk_status)
            chunk_count += len(chunk_inputs)

        return SourceVaultReplayReport(
            source_count=len(sources),
            chunk_count=chunk_count,
            source_status_counts=source_status_counts,
            chunk_status_counts=chunk_status_counts,
        )

    def source_vault_mirror_backlog(self, *, sample_limit: int = 10) -> SourceVaultMirrorBacklogReport:
        """Return a read-only Source Vault mirror backlog summary.

        Args:
            sample_limit: Maximum not-mirrored source/chunk samples to include.

        Returns:
            Counts and bounded sample rows for registry recovery diagnostics.
        """

        if not isinstance(sample_limit, int):
            raise TypeError("sample_limit must be an integer")
        if sample_limit < 0 or sample_limit > 100:
            raise ValueError("sample_limit must be between 0 and 100")

        with self.connect() as conn:
            source_status_counts = _status_counts(
                conn.execute(
                    """
                    SELECT COALESCE(source_vault_status, 'unknown') AS status, COUNT(*) AS count
                    FROM wiki_sources
                    GROUP BY COALESCE(source_vault_status, 'unknown')
                    """
                ).fetchall()
            )
            chunk_status_counts = _status_counts(
                conn.execute(
                    """
                    SELECT COALESCE(source_vault_status, 'unknown') AS status, COUNT(*) AS count
                    FROM wiki_chunks
                    GROUP BY COALESCE(source_vault_status, 'unknown')
                    """
                ).fetchall()
            )
            source_count = _row_count(conn, "wiki_sources")
            chunk_count = _row_count(conn, "wiki_chunks")
            pending_source_count = source_count - source_status_counts.get("mirrored", 0)
            pending_chunk_count = chunk_count - chunk_status_counts.get("mirrored", 0)
            sample_budget = sample_limit
            samples: list[SourceVaultMirrorBacklogItem] = []
            if sample_budget:
                for row in conn.execute(
                    """
                    SELECT source_id, COALESCE(source_vault_status, 'unknown') AS status,
                           COALESCE(source_vault_error, '') AS error
                    FROM wiki_sources
                    WHERE COALESCE(source_vault_status, 'unknown') != 'mirrored'
                    ORDER BY updated_at, source_id
                    LIMIT ?
                    """,
                    (sample_budget,),
                ).fetchall():
                    samples.append(
                        SourceVaultMirrorBacklogItem(
                            record_type="source",
                            record_id=str(row["source_id"]),
                            source_id=str(row["source_id"]),
                            status=str(row["status"]),
                            error=str(row["error"] or ""),
                        )
                    )
                sample_budget = sample_limit - len(samples)
            if sample_budget:
                for row in conn.execute(
                    """
                    SELECT chunk_id, source_id, COALESCE(source_vault_status, 'unknown') AS status,
                           COALESCE(source_vault_error, '') AS error
                    FROM wiki_chunks
                    WHERE COALESCE(source_vault_status, 'unknown') != 'mirrored'
                    ORDER BY created_at, chunk_index, chunk_id
                    LIMIT ?
                    """,
                    (sample_budget,),
                ).fetchall():
                    samples.append(
                        SourceVaultMirrorBacklogItem(
                            record_type="chunk",
                            record_id=str(row["chunk_id"]),
                            source_id=str(row["source_id"]),
                            status=str(row["status"]),
                            error=str(row["error"] or ""),
                        )
                    )

        return SourceVaultMirrorBacklogReport(
            source_count=source_count,
            chunk_count=chunk_count,
            source_status_counts=source_status_counts,
            chunk_status_counts=chunk_status_counts,
            pending_source_count=pending_source_count,
            pending_chunk_count=pending_chunk_count,
            samples=tuple(samples),
        )

    def get_chunks_by_source(self, source_id: str) -> list[dict[str, object]]:
        """Return legacy chunk rows, including Source Vault chunk ids when known."""

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, source_id, chunk_index, text, page, section, span_start, span_end,
                       source_vault_chunk_id
                FROM wiki_chunks
                WHERE source_id = ?
                ORDER BY chunk_index
                """,
                (source_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def verify_chunk_exists(self, chunk_id: str) -> bool:
        """Return whether a legacy Wiki chunk id exists."""

        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM wiki_chunks WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
            return row is not None

    def get_source_vault_id(self, source_id: str) -> str | None:
        """Return the Source Vault id associated with a legacy Wiki source."""

        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id cannot be empty")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT source_vault_id FROM wiki_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if row is None:
                return None
            value = row["source_vault_id"]
            return value if isinstance(value, str) and value.strip() else None

    def get_source_vault_chunk_id(self, chunk_id: str) -> str | None:
        """Return the Source Vault chunk id associated with a legacy Wiki chunk."""

        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError("chunk_id cannot be empty")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT source_vault_chunk_id FROM wiki_chunks WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
            if row is None:
                return None
            value = row["source_vault_chunk_id"]
            return value if isinstance(value, str) and value.strip() else None

    def get_source_vault_mirror_status(self, source_id: str) -> dict[str, str]:
        """Return Source Vault mirror status for one legacy Wiki source."""

        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id cannot be empty")
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT source_vault_status, source_vault_error
                FROM wiki_sources
                WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
            if row is None:
                return {"status": "missing_source", "error": ""}
            error = row["source_vault_error"]
            return {
                "status": str(row["source_vault_status"] or "unknown"),
                "error": error if isinstance(error, str) else "",
            }

    def get_source_vault_chunk_mirror_status(self, chunk_id: str) -> dict[str, str]:
        """Return Source Vault mirror status for one legacy Wiki chunk."""

        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise ValueError("chunk_id cannot be empty")
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT source_vault_status, source_vault_error
                FROM wiki_chunks
                WHERE chunk_id = ?
                """,
                (chunk_id,),
            ).fetchone()
            if row is None:
                return {"status": "missing_chunk", "error": ""}
            error = row["source_vault_error"]
            return {
                "status": str(row["source_vault_status"] or "unknown"),
                "error": error if isinstance(error, str) else "",
            }

    @staticmethod
    def _ensure_compat_columns(conn: sqlite3.Connection) -> None:
        source_columns = _table_columns(conn, "wiki_sources")
        if "source_vault_id" not in source_columns:
            conn.execute("ALTER TABLE wiki_sources ADD COLUMN source_vault_id TEXT")
        if "source_vault_status" not in source_columns:
            conn.execute("ALTER TABLE wiki_sources ADD COLUMN source_vault_status TEXT NOT NULL DEFAULT 'not_mirrored'")
        if "source_vault_error" not in source_columns:
            conn.execute("ALTER TABLE wiki_sources ADD COLUMN source_vault_error TEXT")

        chunk_columns = _table_columns(conn, "wiki_chunks")
        if "source_vault_chunk_id" not in chunk_columns:
            conn.execute("ALTER TABLE wiki_chunks ADD COLUMN source_vault_chunk_id TEXT")
        if "source_vault_status" not in chunk_columns:
            conn.execute("ALTER TABLE wiki_chunks ADD COLUMN source_vault_status TEXT NOT NULL DEFAULT 'not_mirrored'")
        if "source_vault_error" not in chunk_columns:
            conn.execute("ALTER TABLE wiki_chunks ADD COLUMN source_vault_error TEXT")
        conn.commit()

    def _vault(self) -> SourceVault:
        if self._source_vault is None:
            self._source_vault = SourceVault()
        return self._source_vault

    def _mirror_source_to_vault(self, record: SourceRecord, *, now_iso: str) -> None:
        fallback_vault_id = _safe_vault_source_id(record.source_hash)
        source_path = Path(record.source_path).expanduser()
        if not source_path.exists() or not source_path.is_file():
            self._mark_source_vault_status(record.source_id, fallback_vault_id, "missing_original", "source_path is not a readable file")
            return
        try:
            result = self._vault().upsert_source_from_file(
                source_path,
                source_type=record.source_type,
                title=record.title,
                parser_version=WIKI_SOURCE_VAULT_PARSER_VERSION,
                chunker_version=WIKI_SOURCE_VAULT_CHUNKER_VERSION,
                expected_source_hash=record.source_hash,
                now_iso=now_iso,
                metadata={
                    "legacy_store": "wiki_sources",
                    "legacy_source_id": record.source_id,
                },
            )
        except (OSError, TypeError, ValueError) as exc:
            self._mark_source_vault_status(record.source_id, fallback_vault_id, "blocked", str(exc))
            return
        self._mark_source_vault_status(record.source_id, result.source.source_id, "mirrored", None)

    def _mirror_chunks_to_vault(
        self,
        source_id: str,
        source_hash: str,
        chunks: list[ChunkInput],
        legacy_to_index: dict[str, int],
        *,
        now_iso: str,
    ) -> None:
        source = self.get_source(source_id)
        if source is None:
            return
        if source.source_vault_id is None:
            self._mirror_source_to_vault(source, now_iso=now_iso)
            source = self.get_source(source_id)
        if source is None or source.source_vault_id is None:
            self._mark_chunks_vault_status(legacy_to_index, source_hash, "missing_source_vault", "source is not mirrored to Source Vault")
            return

        try:
            vault = self._vault()
            vault_chunk_cls = _vault_chunk_input_class(vault)
            vault_chunks = [
                vault_chunk_cls(
                    text=chunk.text,
                    chunk_index=chunk.chunk_index,
                    page=_coerce_positive_int(chunk.page),
                    span_start=chunk.span_start,
                    span_end=chunk.span_end,
                    section=chunk.section,
                    metadata={
                        "legacy_store": "wiki_chunks",
                        "legacy_source_id": source_id,
                        "legacy_chunk_id": derive_chunk_id(source_hash, chunk.chunk_index),
                    },
                )
                for chunk in chunks
            ]
            vault.register_chunks(
                source.source_vault_id,
                vault_chunks,
                source_hash=source_hash,
                parser_version=WIKI_SOURCE_VAULT_PARSER_VERSION,
                chunker_version=WIKI_SOURCE_VAULT_CHUNKER_VERSION,
                now_iso=now_iso,
            )
        except (OSError, TypeError, ValueError) as exc:
            self._mark_chunks_vault_status(legacy_to_index, source_hash, "blocked", str(exc))
            return
        self._mark_chunks_vault_status(legacy_to_index, source_hash, "mirrored", None)

    def _mark_source_vault_status(
        self,
        source_id: str,
        source_vault_id: str | None,
        status: str,
        error: str | None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE wiki_sources
                SET source_vault_id = COALESCE(?, source_vault_id),
                    source_vault_status = ?,
                    source_vault_error = ?
                WHERE source_id = ?
                """,
                (source_vault_id, status, error, source_id),
            )
            conn.commit()

    def _mark_chunks_vault_status(
        self,
        legacy_to_index: dict[str, int],
        source_hash: str,
        status: str,
        error: str | None,
    ) -> None:
        with self.connect() as conn:
            for legacy_chunk_id, chunk_index in legacy_to_index.items():
                conn.execute(
                    """
                    UPDATE wiki_chunks
                    SET source_vault_chunk_id = COALESCE(?, source_vault_chunk_id),
                        source_vault_status = ?,
                        source_vault_error = ?
                    WHERE chunk_id = ?
                    """,
                    (_safe_vault_chunk_id(source_hash, chunk_index), status, error, legacy_chunk_id),
                )
            conn.commit()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _row_count(conn: sqlite3.Connection, table_name: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    if row is None:
        return 0
    return int(row["count"])


def _status_counts(rows: Iterable[sqlite3.Row]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"] or "unknown")
        counts[status] = int(row["count"])
    return counts


def _increment_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _safe_vault_source_id(source_hash: str) -> str | None:
    try:
        return derive_vault_source_id(source_hash)
    except (TypeError, ValueError):
        return None


def _safe_vault_chunk_id(source_hash: str, chunk_index: int) -> str | None:
    try:
        return derive_vault_chunk_id(source_hash, WIKI_SOURCE_VAULT_CHUNKER_VERSION, chunk_index)
    except (TypeError, ValueError):
        return None


def _coerce_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdigit():
            parsed = int(normalized)
            return parsed if parsed > 0 else None
    return None


def _vault_chunk_input_class(vault: SourceVault) -> type[VaultChunkInput]:
    module = sys.modules.get(type(vault).__module__)
    candidate = getattr(module, "SourceChunkInput", None) if module is not None else None
    if isinstance(candidate, type):
        return candidate
    return VaultChunkInput
