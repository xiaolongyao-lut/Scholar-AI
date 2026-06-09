"""Local source vault storage for deduped originals and searchable chunks."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypeAlias, cast

try:  # pragma: no cover - exercised by package imports outside flat test path.
    import project_paths as _project_paths
    from db import open_sqlite_connection
except ImportError:  # pragma: no cover
    from . import project_paths as _project_paths
    from .db import open_sqlite_connection


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]
SourceStorageStatus: TypeAlias = Literal["stored", "referenced", "missing"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SEARCH_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class SourceVaultError(RuntimeError):
    """Raised when vault persistence cannot preserve source/chunk integrity."""


@dataclass(frozen=True, slots=True)
class SourceAssetRecord:
    """Stored source metadata.

    Args:
        source_id: Stable id derived from the source content hash.
        source_hash: Lowercase SHA-256 hex digest of original bytes.
        stored_path: Repo/user-data local copy under ``source_vault/originals``.
        project_ids: Project memberships; source bytes are not duplicated per project.
    """

    source_id: str
    source_type: str
    title: str
    source_hash: str
    original_filename: str
    stored_path: Path
    file_size: int
    parser_version: str
    chunker_version: str
    storage_status: SourceStorageStatus
    first_seen_at: str
    last_indexed_at: str
    metadata: Mapping[str, JsonValue]
    project_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceChunkInput:
    """Input shape for one source chunk.

    Args:
        text: Non-empty chunk text.
        chunk_index: Zero-based order within a source and chunker version.
        page: Optional one-based page number when the parser provides it.
        bbox: Optional four-number box in parser-native coordinates.
        metadata: JSON-safe parser metadata for this chunk.
    """

    text: str
    chunk_index: int
    page: int | None = None
    span_start: int | None = None
    span_end: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    section: str | None = None
    metadata: Mapping[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True)
class SourceChunkRecord:
    """Persisted chunk plus source and anchor fields."""

    chunk_id: str
    source_id: str
    source_hash: str
    chunk_index: int
    chunker_version: str
    text_hash: str
    text: str
    page: int | None
    span_start: int | None
    span_end: int | None
    bbox: tuple[float, float, float, float] | None
    section: str | None
    metadata: Mapping[str, JsonValue]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SourceChunkSearchResult:
    """Search result returned from FTS or LIKE fallback."""

    chunk_id: str
    source_id: str
    source_hash: str
    title: str
    chunk_index: int
    text: str
    score: float | None


@dataclass(frozen=True, slots=True)
class SourceUpsertResult:
    """Result for an original source upsert."""

    source: SourceAssetRecord
    created: bool
    original_written: bool


def utc_now_iso() -> str:
    """Return a compact UTC timestamp for durable local records."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_source_vault_root() -> Path:
    """Return the canonical local source-vault root under workspace artifacts."""

    return (_project_paths.WORKSPACE_ARTIFACTS_ROOT / "source_vault").resolve()


def default_source_vault_db_path() -> Path:
    """Return the canonical Source Vault SQLite path."""

    return default_source_vault_root() / "source_vault.sqlite3"


def sha256_bytes(content: bytes) -> str:
    """Return the lowercase SHA-256 hex digest for non-empty bytes.

    Raises:
        TypeError: If ``content`` is not bytes.
        ValueError: If ``content`` is empty.
    """

    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not content:
        raise ValueError("content must not be empty")
    return hashlib.sha256(content).hexdigest()


def sha256_text(value: str) -> str:
    """Return the lowercase SHA-256 hex digest for non-empty UTF-8 text."""

    text = _require_non_empty_text(value, "value")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def derive_source_id(source_hash: str) -> str:
    """Derive a stable source id from a SHA-256 content hash."""

    normalized_hash = _normalize_sha256(source_hash, "source_hash")
    return f"src_{normalized_hash[:32]}"


def derive_chunk_id(source_hash: str, chunker_version: str, chunk_index: int) -> str:
    """Derive a stable chunk id for one source/chunker/index tuple."""

    normalized_hash = _normalize_sha256(source_hash, "source_hash")
    normalized_chunker = _require_non_empty_text(chunker_version, "chunker_version")
    if not isinstance(chunk_index, int):
        raise TypeError("chunk_index must be an integer")
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    digest = hashlib.sha256(f"{normalized_hash}:{normalized_chunker}:{chunk_index}".encode("utf-8")).hexdigest()
    return f"chk_{digest[:32]}"


class SourceVault:
    """SQLite-backed source vault for deduped originals and searchable chunks."""

    def __init__(self, db_path: str | Path | None = None, storage_root: str | Path | None = None) -> None:
        if db_path is not None and not isinstance(db_path, (str, Path)):
            raise TypeError("db_path must be a string, pathlib.Path, or None")
        if storage_root is not None and not isinstance(storage_root, (str, Path)):
            raise TypeError("storage_root must be a string, pathlib.Path, or None")

        self.storage_root = Path(storage_root).expanduser().resolve() if storage_root else default_source_vault_root()
        self.db_path = Path(db_path).expanduser().resolve() if db_path else self.storage_root / "source_vault.sqlite3"
        self.originals_root = self.storage_root / "originals"
        self.chunks_root = self.storage_root / "chunks"
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.originals_root.mkdir(parents=True, exist_ok=True)
        self.chunks_root.mkdir(parents=True, exist_ok=True)
        self._fts_enabled = self._ensure_schema()

    @property
    def fts_enabled(self) -> bool:
        """Return whether SQLite FTS5 indexing is available for this vault."""

        return self._fts_enabled

    def upsert_source_from_file(
        self,
        file_path: str | Path,
        *,
        source_type: str,
        title: str | None = None,
        parser_version: str,
        chunker_version: str,
        project_id: str | None = None,
        metadata: JsonObject | None = None,
        expected_source_hash: str | None = None,
        now_iso: str | None = None,
    ) -> SourceUpsertResult:
        """Store or reuse one original file by content hash.

        Raises:
            FileNotFoundError: If ``file_path`` is not an existing file.
            ValueError: If metadata, hash, or version inputs are invalid.
        """

        path = _require_file_path(file_path)
        source_hash, file_size = _hash_file(path)
        if expected_source_hash is not None:
            expected_hash = _normalize_sha256(expected_source_hash, "expected_source_hash")
            if source_hash != expected_hash:
                raise ValueError(f"source hash mismatch: expected {expected_hash}, got {source_hash}")
        if file_size <= 0:
            raise ValueError("source file must not be empty")

        return self._upsert_source(
            source_hash=source_hash,
            file_size=file_size,
            original_filename=path.name,
            source_type=source_type,
            title=title or path.stem or path.name,
            parser_version=parser_version,
            chunker_version=chunker_version,
            project_id=project_id,
            metadata=metadata,
            now_iso=now_iso or utc_now_iso(),
            copy_writer=lambda destination: _copy_file_atomic(path, destination),
        )

    def upsert_source_bytes(
        self,
        content: bytes,
        *,
        filename: str,
        source_type: str,
        title: str | None = None,
        parser_version: str,
        chunker_version: str,
        project_id: str | None = None,
        metadata: JsonObject | None = None,
        expected_source_hash: str | None = None,
        now_iso: str | None = None,
    ) -> SourceUpsertResult:
        """Store or reuse one original byte payload by content hash."""

        source_hash = sha256_bytes(content)
        if expected_source_hash is not None:
            expected_hash = _normalize_sha256(expected_source_hash, "expected_source_hash")
            if source_hash != expected_hash:
                raise ValueError(f"source hash mismatch: expected {expected_hash}, got {source_hash}")
        safe_filename = _require_non_empty_text(filename, "filename")

        return self._upsert_source(
            source_hash=source_hash,
            file_size=len(content),
            original_filename=safe_filename,
            source_type=source_type,
            title=title or Path(safe_filename).stem or safe_filename,
            parser_version=parser_version,
            chunker_version=chunker_version,
            project_id=project_id,
            metadata=metadata,
            now_iso=now_iso or utc_now_iso(),
            copy_writer=lambda destination: _write_bytes_atomic(destination, content),
        )

    def get_source(self, source_id: str) -> SourceAssetRecord | None:
        """Return one source record by id, or ``None`` when absent."""

        normalized_id = _require_non_empty_text(source_id, "source_id")
        with closing(open_sqlite_connection(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT source_id, source_type, title, source_hash, original_filename, stored_path,
                       file_size, parser_version, chunker_version, storage_status,
                       first_seen_at, last_indexed_at, metadata_json
                FROM source_assets
                WHERE source_id = ?
                """,
                (normalized_id,),
            ).fetchone()
            if row is None:
                return None
            return self._source_from_row(conn, row)

    def get_source_by_hash(self, source_hash: str) -> SourceAssetRecord | None:
        """Return one source record by SHA-256 content hash."""

        normalized_hash = _normalize_sha256(source_hash, "source_hash")
        with closing(open_sqlite_connection(self.db_path)) as conn:
            row = conn.execute(
                """
                SELECT source_id, source_type, title, source_hash, original_filename, stored_path,
                       file_size, parser_version, chunker_version, storage_status,
                       first_seen_at, last_indexed_at, metadata_json
                FROM source_assets
                WHERE source_hash = ?
                """,
                (normalized_hash,),
            ).fetchone()
            if row is None:
                return None
            return self._source_from_row(conn, row)

    def list_sources(self) -> list[SourceAssetRecord]:
        """List sources ordered by first-seen time."""

        with closing(open_sqlite_connection(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT source_id, source_type, title, source_hash, original_filename, stored_path,
                       file_size, parser_version, chunker_version, storage_status,
                       first_seen_at, last_indexed_at, metadata_json
                FROM source_assets
                ORDER BY first_seen_at, title, source_id
                """
            ).fetchall()
            return [self._source_from_row(conn, row) for row in rows]

    def link_source_to_project(
        self,
        source_id: str,
        project_id: str,
        *,
        metadata: JsonObject | None = None,
        now_iso: str | None = None,
    ) -> bool:
        """Link a deduped source to a project without copying source bytes."""

        normalized_source_id = _require_non_empty_text(source_id, "source_id")
        normalized_project_id = _require_non_empty_text(project_id, "project_id")
        metadata_json = _json_dumps_object(metadata)
        linked_at = now_iso or utc_now_iso()
        with closing(open_sqlite_connection(self.db_path)) as conn:
            if not self._source_exists(conn, normalized_source_id):
                raise ValueError(f"source not found: {normalized_source_id}")
            existing = conn.execute(
                """
                SELECT 1 FROM source_project_links
                WHERE source_id = ? AND project_id = ?
                """,
                (normalized_source_id, normalized_project_id),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO source_project_links (source_id, project_id, linked_at, metadata_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id, project_id) DO UPDATE SET
                    metadata_json = excluded.metadata_json
                """,
                (normalized_source_id, normalized_project_id, linked_at, metadata_json),
            )
            conn.commit()
            return existing is None

    def list_project_links(self, source_id: str) -> tuple[str, ...]:
        """Return project ids linked to one source."""

        normalized_source_id = _require_non_empty_text(source_id, "source_id")
        with closing(open_sqlite_connection(self.db_path)) as conn:
            if not self._source_exists(conn, normalized_source_id):
                raise ValueError(f"source not found: {normalized_source_id}")
            return self._project_ids_for_source(conn, normalized_source_id)

    def register_chunks(
        self,
        source_id: str,
        chunks: Iterable[SourceChunkInput],
        *,
        source_hash: str | None = None,
        parser_version: str | None = None,
        chunker_version: str | None = None,
        now_iso: str | None = None,
    ) -> int:
        """Register immutable chunks for a source and refresh the FTS index.

        Raises:
            ValueError: If source/hash inputs are mismatched or chunk indexes/text are invalid.
        """

        normalized_source_id = _require_non_empty_text(source_id, "source_id")
        chunk_list = list(chunks)
        if not chunk_list:
            raise ValueError("chunks must not be empty")

        seen_indexes: set[int] = set()
        for chunk in chunk_list:
            if not isinstance(chunk, SourceChunkInput):
                raise TypeError("chunks must contain SourceChunkInput records")
            _validate_chunk_input(chunk)
            if chunk.chunk_index in seen_indexes:
                raise ValueError(f"duplicate chunk_index in batch: {chunk.chunk_index}")
            seen_indexes.add(chunk.chunk_index)

        written_at = now_iso or utc_now_iso()
        with closing(open_sqlite_connection(self.db_path)) as conn:
            source_row = conn.execute(
                """
                SELECT source_id, source_hash, title, parser_version, chunker_version
                FROM source_assets
                WHERE source_id = ?
                """,
                (normalized_source_id,),
            ).fetchone()
            if source_row is None:
                raise ValueError(f"source not found: {normalized_source_id}")
            source_hash_value = _row_text(source_row, "source_hash")
            expected_hash = _normalize_sha256(source_hash, "source_hash") if source_hash else source_hash_value
            if expected_hash != source_hash_value:
                raise ValueError(f"source_hash mismatch for {normalized_source_id}: {expected_hash} != {source_hash_value}")

            effective_parser = (
                _require_non_empty_text(parser_version, "parser_version")
                if parser_version is not None
                else _row_text(source_row, "parser_version")
            )
            effective_chunker = (
                _require_non_empty_text(chunker_version, "chunker_version")
                if chunker_version is not None
                else _row_text(source_row, "chunker_version")
            )
            source_title = _row_text(source_row, "title")

            for chunk in chunk_list:
                text = _require_non_empty_text(chunk.text, "chunk.text")
                text_hash = sha256_text(text)
                chunk_id = derive_chunk_id(source_hash_value, effective_chunker, chunk.chunk_index)
                metadata_json = _json_dumps_object(chunk.metadata)
                bbox_json = _json_dumps_bbox(chunk.bbox)

                existing = conn.execute(
                    """
                    SELECT chunk_id, text_hash FROM source_chunks
                    WHERE source_id = ? AND chunker_version = ? AND chunk_index = ?
                    """,
                    (normalized_source_id, effective_chunker, chunk.chunk_index),
                ).fetchone()
                if existing is not None and _row_text(existing, "text_hash") != text_hash:
                    raise ValueError(
                        "chunk immutability violation for "
                        f"{normalized_source_id}/{effective_chunker}/{chunk.chunk_index}"
                    )

                conn.execute(
                    """
                    INSERT INTO source_chunks (
                        chunk_id, source_id, source_hash, chunk_index, chunker_version,
                        parser_version, text_hash, text, page, span_start, span_end,
                        bbox_json, section, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        parser_version = excluded.parser_version,
                        page = excluded.page,
                        span_start = excluded.span_start,
                        span_end = excluded.span_end,
                        bbox_json = excluded.bbox_json,
                        section = excluded.section,
                        metadata_json = excluded.metadata_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        chunk_id,
                        normalized_source_id,
                        source_hash_value,
                        chunk.chunk_index,
                        effective_chunker,
                        effective_parser,
                        text_hash,
                        text,
                        chunk.page,
                        chunk.span_start,
                        chunk.span_end,
                        bbox_json,
                        _normalize_optional_text(chunk.section),
                        metadata_json,
                        written_at,
                        written_at,
                    ),
                )
                if self._fts_enabled:
                    conn.execute("DELETE FROM source_chunks_fts WHERE chunk_id = ?", (chunk_id,))
                    conn.execute(
                        """
                        INSERT INTO source_chunks_fts (chunk_id, source_id, title, text)
                        VALUES (?, ?, ?, ?)
                        """,
                        (chunk_id, normalized_source_id, source_title, text),
                    )

            conn.execute(
                "UPDATE source_assets SET last_indexed_at = ? WHERE source_id = ?",
                (written_at, normalized_source_id),
            )
            conn.commit()

        self.write_chunks_sidecar(normalized_source_id)
        return len(chunk_list)

    def list_chunks(self, source_id: str) -> list[SourceChunkRecord]:
        """List chunks for one source ordered by chunk index."""

        normalized_source_id = _require_non_empty_text(source_id, "source_id")
        with closing(open_sqlite_connection(self.db_path)) as conn:
            if not self._source_exists(conn, normalized_source_id):
                raise ValueError(f"source not found: {normalized_source_id}")
            rows = conn.execute(
                """
                SELECT chunk_id, source_id, source_hash, chunk_index, chunker_version,
                       text_hash, text, page, span_start, span_end, bbox_json, section,
                       metadata_json, created_at, updated_at
                FROM source_chunks
                WHERE source_id = ?
                ORDER BY chunk_index
                """,
                (normalized_source_id,),
            ).fetchall()
            return [_chunk_from_row(row) for row in rows]

    def search_chunks(
        self,
        query: str,
        *,
        limit: int = 20,
        project_id: str | None = None,
    ) -> list[SourceChunkSearchResult]:
        """Search chunks by text/title, returning chunk and source ids."""

        normalized_query = _require_non_empty_text(query, "query")
        normalized_limit = _validate_limit(limit)
        normalized_project_id = _normalize_optional_text(project_id)
        if self._fts_enabled:
            try:
                return self._search_chunks_fts(normalized_query, normalized_limit, normalized_project_id)
            except sqlite3.Error:
                return self._search_chunks_like(normalized_query, normalized_limit, normalized_project_id)
        return self._search_chunks_like(normalized_query, normalized_limit, normalized_project_id)

    def chunks_sidecar_path(self, source_id: str) -> Path:
        """Return the JSONL sidecar path for one source's chunks."""

        normalized_source_id = _require_non_empty_text(source_id, "source_id")
        if "/" in normalized_source_id or "\\" in normalized_source_id:
            raise ValueError("source_id must not contain path separators")
        return self.chunks_root / f"{normalized_source_id}.jsonl"

    def write_chunks_sidecar(self, source_id: str) -> Path:
        """Write an atomic JSONL sidecar for one source's current chunks."""

        chunks = self.list_chunks(source_id)
        path = self.chunks_sidecar_path(source_id)
        lines = [_json_dumps_line(_chunk_to_sidecar_payload(chunk)) for chunk in chunks]
        _write_text_atomic(path, "".join(f"{line}\n" for line in lines))
        return path

    def _ensure_schema(self) -> bool:
        with closing(open_sqlite_connection(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_assets (
                    source_id TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL CHECK(file_size > 0),
                    parser_version TEXT NOT NULL,
                    chunker_version TEXT NOT NULL,
                    storage_status TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_indexed_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_project_links (
                    source_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    linked_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(source_id, project_id),
                    FOREIGN KEY(source_id) REFERENCES source_assets(source_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
                    chunker_version TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    text_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    page INTEGER,
                    span_start INTEGER,
                    span_end INTEGER,
                    bbox_json TEXT,
                    section TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_id, chunker_version, chunk_index),
                    FOREIGN KEY(source_id) REFERENCES source_assets(source_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_assets_hash ON source_assets(source_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_chunks_source ON source_chunks(source_id, chunk_index)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_links_project ON source_project_links(project_id)")

            fts_enabled = True
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS source_chunks_fts
                    USING fts5(chunk_id UNINDEXED, source_id UNINDEXED, title, text, tokenize='unicode61')
                    """
                )
            except sqlite3.Error:
                fts_enabled = False
            conn.commit()
            return fts_enabled

    def _upsert_source(
        self,
        *,
        source_hash: str,
        file_size: int,
        original_filename: str,
        source_type: str,
        title: str,
        parser_version: str,
        chunker_version: str,
        project_id: str | None,
        metadata: JsonObject | None,
        now_iso: str,
        copy_writer: "_CopyWriter",
    ) -> SourceUpsertResult:
        normalized_hash = _normalize_sha256(source_hash, "source_hash")
        if not isinstance(file_size, int):
            raise TypeError("file_size must be an integer")
        if file_size <= 0:
            raise ValueError("file_size must be positive")

        source_id = derive_source_id(normalized_hash)
        normalized_type = _require_non_empty_text(source_type, "source_type").lower()
        normalized_title = _require_non_empty_text(title, "title")
        normalized_parser = _require_non_empty_text(parser_version, "parser_version")
        normalized_chunker = _require_non_empty_text(chunker_version, "chunker_version")
        normalized_filename = _safe_filename(original_filename)
        metadata_json = _json_dumps_object(metadata)

        with closing(open_sqlite_connection(self.db_path)) as conn:
            existing = conn.execute(
                """
                SELECT source_id, file_size, stored_path
                FROM source_assets
                WHERE source_hash = ?
                """,
                (normalized_hash,),
            ).fetchone()
            if existing is not None:
                existing_id = _row_text(existing, "source_id")
                if existing_id != source_id:
                    raise SourceVaultError(f"source id/hash invariant failed for {normalized_hash}")
                existing_size = _row_int(existing, "file_size")
                if existing_size != file_size:
                    raise SourceVaultError(f"source size/hash invariant failed for {source_id}")
                stored_path = Path(_row_text(existing, "stored_path")).expanduser().resolve()
                created = False
            else:
                stored_path = self._original_path_for(normalized_hash, normalized_filename)
                created = True

            original_written = False
            if not stored_path.exists():
                copy_writer(stored_path)
                original_written = True
            elif _hash_existing_file(stored_path) != normalized_hash:
                raise SourceVaultError(f"stored original hash mismatch: {stored_path}")

            storage_status: SourceStorageStatus = "stored"
            conn.execute(
                """
                INSERT INTO source_assets (
                    source_id, source_hash, source_type, title, original_filename,
                    stored_path, file_size, parser_version, chunker_version,
                    storage_status, first_seen_at, last_indexed_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_hash) DO UPDATE SET
                    source_type = excluded.source_type,
                    title = excluded.title,
                    stored_path = excluded.stored_path,
                    file_size = excluded.file_size,
                    parser_version = excluded.parser_version,
                    chunker_version = excluded.chunker_version,
                    storage_status = excluded.storage_status,
                    last_indexed_at = excluded.last_indexed_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    source_id,
                    normalized_hash,
                    normalized_type,
                    normalized_title,
                    normalized_filename,
                    str(stored_path),
                    file_size,
                    normalized_parser,
                    normalized_chunker,
                    storage_status,
                    now_iso,
                    now_iso,
                    metadata_json,
                ),
            )
            if project_id is not None:
                normalized_project_id = _require_non_empty_text(project_id, "project_id")
                conn.execute(
                    """
                    INSERT INTO source_project_links (source_id, project_id, linked_at, metadata_json)
                    VALUES (?, ?, ?, '{}')
                    ON CONFLICT(source_id, project_id) DO NOTHING
                    """,
                    (source_id, normalized_project_id, now_iso),
                )
            conn.commit()

        source = self.get_source(source_id)
        if source is None:
            raise SourceVaultError(f"source upsert did not persist: {source_id}")
        return SourceUpsertResult(source=source, created=created, original_written=original_written)

    def _original_path_for(self, source_hash: str, original_filename: str) -> Path:
        normalized_hash = _normalize_sha256(source_hash, "source_hash")
        safe_filename = _safe_filename(original_filename)
        return self.originals_root / normalized_hash[:2] / f"{normalized_hash[:16]}-{safe_filename}"

    def _source_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> SourceAssetRecord:
        source_id = _row_text(row, "source_id")
        return SourceAssetRecord(
            source_id=source_id,
            source_type=_row_text(row, "source_type"),
            title=_row_text(row, "title"),
            source_hash=_row_text(row, "source_hash"),
            original_filename=_row_text(row, "original_filename"),
            stored_path=Path(_row_text(row, "stored_path")),
            file_size=_row_int(row, "file_size"),
            parser_version=_row_text(row, "parser_version"),
            chunker_version=_row_text(row, "chunker_version"),
            storage_status=cast(SourceStorageStatus, _row_text(row, "storage_status")),
            first_seen_at=_row_text(row, "first_seen_at"),
            last_indexed_at=_row_text(row, "last_indexed_at"),
            metadata=_json_loads_object(row["metadata_json"]),
            project_ids=self._project_ids_for_source(conn, source_id),
        )

    @staticmethod
    def _source_exists(conn: sqlite3.Connection, source_id: str) -> bool:
        row = conn.execute("SELECT 1 FROM source_assets WHERE source_id = ?", (source_id,)).fetchone()
        return row is not None

    @staticmethod
    def _project_ids_for_source(conn: sqlite3.Connection, source_id: str) -> tuple[str, ...]:
        rows = conn.execute(
            """
            SELECT project_id
            FROM source_project_links
            WHERE source_id = ?
            ORDER BY project_id
            """,
            (source_id,),
        ).fetchall()
        return tuple(_row_text(row, "project_id") for row in rows)

    def _search_chunks_fts(
        self,
        query: str,
        limit: int,
        project_id: str | None,
    ) -> list[SourceChunkSearchResult]:
        fts_query = _build_fts_query(query)
        with closing(open_sqlite_connection(self.db_path)) as conn:
            params: list[str | int] = [fts_query]
            project_join = ""
            project_where = ""
            if project_id is not None:
                project_join = "JOIN source_project_links l ON l.source_id = c.source_id"
                project_where = "AND l.project_id = ?"
                params.append(project_id)
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT c.chunk_id, c.source_id, c.source_hash, s.title, c.chunk_index, c.text,
                       bm25(source_chunks_fts) AS score
                FROM source_chunks_fts
                JOIN source_chunks c ON c.chunk_id = source_chunks_fts.chunk_id
                JOIN source_assets s ON s.source_id = c.source_id
                {project_join}
                WHERE source_chunks_fts MATCH ?
                {project_where}
                ORDER BY score, c.chunk_index
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            return [_search_result_from_row(row, include_score=True) for row in rows]

    def _search_chunks_like(
        self,
        query: str,
        limit: int,
        project_id: str | None,
    ) -> list[SourceChunkSearchResult]:
        like_value = f"%{_escape_like(query)}%"
        with closing(open_sqlite_connection(self.db_path)) as conn:
            params: list[str | int] = [like_value, like_value]
            project_join = ""
            project_where = ""
            if project_id is not None:
                project_join = "JOIN source_project_links l ON l.source_id = c.source_id"
                project_where = "AND l.project_id = ?"
                params.append(project_id)
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT c.chunk_id, c.source_id, c.source_hash, s.title, c.chunk_index, c.text
                FROM source_chunks c
                JOIN source_assets s ON s.source_id = c.source_id
                {project_join}
                WHERE (c.text LIKE ? ESCAPE '\\' OR s.title LIKE ? ESCAPE '\\')
                {project_where}
                ORDER BY c.chunk_index
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            return [_search_result_from_row(row, include_score=False) for row in rows]


_CopyWriter: TypeAlias = Callable[[Path], None]


def _require_non_empty_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _require_non_empty_text(value, "optional text")


def _normalize_sha256(value: object, field_name: str) -> str:
    text = _require_non_empty_text(value, field_name).lower()
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return text


def _require_file_path(file_path: str | Path) -> Path:
    if not isinstance(file_path, (str, Path)):
        raise TypeError("file_path must be a string or pathlib.Path")
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"source file not found: {path}")
    if not path.is_file():
        raise ValueError(f"source path must be a file: {path}")
    return path


def _hash_file(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            hasher.update(block)
    return hasher.hexdigest(), size


def _hash_existing_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"stored original is not a file: {path}")
    file_hash, file_size = _hash_file(path)
    if file_size <= 0:
        raise SourceVaultError(f"stored original is empty: {path}")
    return file_hash


def _safe_filename(filename: str) -> str:
    text = _require_non_empty_text(filename, "filename")
    basename = Path(text).name.strip()
    if not basename:
        raise ValueError("filename must include a basename")
    safe = _SAFE_FILENAME_RE.sub("-", basename).strip(".-")
    if not safe:
        safe = "source.bin"
    if len(safe) > 120:
        stem = Path(safe).stem[:96] or "source"
        suffix = Path(safe).suffix[:16]
        safe = f"{stem}{suffix}"
    return safe


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not content:
        raise ValueError("content must not be empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        _unlink_if_exists(tmp_name)


def _write_text_atomic(path: Path, content: str) -> None:
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        _unlink_if_exists(tmp_name)


def _copy_file_atomic(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"source file not found: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp_name, destination)
    finally:
        _unlink_if_exists(tmp_name)


def _unlink_if_exists(path_text: str) -> None:
    try:
        path = Path(path_text)
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _validate_chunk_input(chunk: SourceChunkInput) -> None:
    _require_non_empty_text(chunk.text, "chunk.text")
    if not isinstance(chunk.chunk_index, int):
        raise TypeError("chunk_index must be an integer")
    if chunk.chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    if chunk.page is not None and (not isinstance(chunk.page, int) or chunk.page <= 0):
        raise ValueError("page must be a positive integer when provided")
    if chunk.span_start is not None and (not isinstance(chunk.span_start, int) or chunk.span_start < 0):
        raise ValueError("span_start must be a non-negative integer when provided")
    if chunk.span_end is not None and (not isinstance(chunk.span_end, int) or chunk.span_end < 0):
        raise ValueError("span_end must be a non-negative integer when provided")
    if chunk.span_start is not None and chunk.span_end is not None and chunk.span_end < chunk.span_start:
        raise ValueError("span_end must be greater than or equal to span_start")
    if chunk.bbox is not None:
        _validate_bbox(chunk.bbox)
    if chunk.section is not None:
        _require_non_empty_text(chunk.section, "section")
    _json_dumps_object(chunk.metadata)


def _validate_bbox(value: Sequence[float]) -> None:
    if len(value) != 4:
        raise ValueError("bbox must contain exactly four numbers")
    for coordinate in value:
        if not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool):
            raise TypeError("bbox coordinates must be numbers")
        if not math.isfinite(float(coordinate)):
            raise ValueError("bbox coordinates must be finite")


def _json_dumps_object(value: JsonObject | None) -> str:
    if value is None:
        return "{}"
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping or None")
    converted: dict[str, JsonValue] = {}
    for key, entry in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError("metadata keys must be non-empty strings")
        converted[key] = _coerce_json_value(entry, f"metadata.{key}")
    return json.dumps(converted, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_dumps_bbox(value: tuple[float, float, float, float] | None) -> str | None:
    if value is None:
        return None
    _validate_bbox(value)
    return json.dumps([float(item) for item in value], separators=(",", ":"))


def _json_loads_object(value: object) -> dict[str, JsonValue]:
    if value in (None, ""):
        return {}
    if not isinstance(value, str):
        raise TypeError("JSON column must be a string")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("JSON column must contain an object")
    return {
        str(key): _coerce_json_value(entry, f"metadata.{key}")
        for key, entry in parsed.items()
        if isinstance(key, str)
    }


def _json_loads_bbox(value: object) -> tuple[float, float, float, float] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise TypeError("bbox JSON column must be a string or None")
    parsed = json.loads(value)
    if not isinstance(parsed, list) or len(parsed) != 4:
        raise ValueError("bbox JSON column must contain four numbers")
    bbox = tuple(float(item) for item in parsed)
    typed_bbox = cast(tuple[float, float, float, float], bbox)
    _validate_bbox(typed_bbox)
    return typed_bbox


def _coerce_json_value(value: object, field_name: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must be finite")
        return value
    if isinstance(value, Mapping):
        converted: dict[str, JsonValue] = {}
        for key, entry in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{field_name} keys must be non-empty strings")
            converted[key] = _coerce_json_value(entry, f"{field_name}.{key}")
        return converted
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_coerce_json_value(entry, f"{field_name}[]") for entry in value]
    raise TypeError(f"{field_name} must be JSON-serializable")


def _chunk_from_row(row: sqlite3.Row) -> SourceChunkRecord:
    return SourceChunkRecord(
        chunk_id=_row_text(row, "chunk_id"),
        source_id=_row_text(row, "source_id"),
        source_hash=_row_text(row, "source_hash"),
        chunk_index=_row_int(row, "chunk_index"),
        chunker_version=_row_text(row, "chunker_version"),
        text_hash=_row_text(row, "text_hash"),
        text=_row_text(row, "text"),
        page=_row_optional_int(row, "page"),
        span_start=_row_optional_int(row, "span_start"),
        span_end=_row_optional_int(row, "span_end"),
        bbox=_json_loads_bbox(row["bbox_json"]),
        section=_row_optional_text(row, "section"),
        metadata=_json_loads_object(row["metadata_json"]),
        created_at=_row_text(row, "created_at"),
        updated_at=_row_text(row, "updated_at"),
    )


def _chunk_to_sidecar_payload(chunk: SourceChunkRecord) -> dict[str, JsonValue]:
    return {
        "chunk_id": chunk.chunk_id,
        "source_id": chunk.source_id,
        "source_hash": chunk.source_hash,
        "chunk_index": chunk.chunk_index,
        "chunker_version": chunk.chunker_version,
        "text_hash": chunk.text_hash,
        "text": chunk.text,
        "page": chunk.page,
        "span_start": chunk.span_start,
        "span_end": chunk.span_end,
        "bbox": None if chunk.bbox is None else [float(item) for item in chunk.bbox],
        "section": chunk.section,
        "metadata": dict(chunk.metadata),
        "created_at": chunk.created_at,
        "updated_at": chunk.updated_at,
    }


def _json_dumps_line(value: Mapping[str, JsonValue]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _search_result_from_row(row: sqlite3.Row, *, include_score: bool) -> SourceChunkSearchResult:
    score: float | None = None
    if include_score and row["score"] is not None:
        score = float(row["score"])
    return SourceChunkSearchResult(
        chunk_id=_row_text(row, "chunk_id"),
        source_id=_row_text(row, "source_id"),
        source_hash=_row_text(row, "source_hash"),
        title=_row_text(row, "title"),
        chunk_index=_row_int(row, "chunk_index"),
        text=_row_text(row, "text"),
        score=score,
    )


def _row_text(row: sqlite3.Row, key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise TypeError(f"row[{key}] must be a string")
    return value


def _row_optional_text(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"row[{key}] must be a string or None")
    return value


def _row_int(row: sqlite3.Row, key: str) -> int:
    value = row[key]
    if not isinstance(value, int):
        raise TypeError(f"row[{key}] must be an integer")
    return value


def _row_optional_int(row: sqlite3.Row, key: str) -> int | None:
    value = row[key]
    if value is None:
        return None
    if not isinstance(value, int):
        raise TypeError(f"row[{key}] must be an integer or None")
    return value


def _validate_limit(limit: int) -> int:
    if not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    return limit


def _build_fts_query(query: str) -> str:
    tokens = [_escape_fts_phrase(token) for token in _SEARCH_TOKEN_RE.findall(query) if token.strip()]
    if not tokens:
        return _escape_fts_phrase(query)
    return " OR ".join(tokens[:12])


def _escape_fts_phrase(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = [
    "SourceAssetRecord",
    "SourceChunkInput",
    "SourceChunkRecord",
    "SourceChunkSearchResult",
    "SourceUpsertResult",
    "SourceVault",
    "SourceVaultError",
    "default_source_vault_db_path",
    "default_source_vault_root",
    "derive_chunk_id",
    "derive_source_id",
    "sha256_bytes",
    "sha256_text",
    "utc_now_iso",
]
