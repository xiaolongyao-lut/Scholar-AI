# -*- coding: utf-8 -*-
"""SQLite FTS5 derived lexical index for project chunk stores."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from chunk_hashing import (
    CHUNK_HASH_VERSION,
    SUPPORTED_CHUNK_HASH_VERSIONS,
    compute_chunk_hashes,
)


CHUNK_FTS_INDEX_SCHEMA_VERSION = "scholar-ai-chunk-fts5-index/v1"

ChunkFtsIndexStatus = Literal["valid", "missing", "stale", "unavailable"]

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class ChunkFtsBuildReport:
    """Summary of a complete FTS5 rebuild."""

    schema_version: str
    project_id: str
    chunk_store_version: str
    indexed_count: int
    skipped_count: int
    db_path: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report payload."""

        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "chunk_store_version": self.chunk_store_version,
            "indexed_count": self.indexed_count,
            "skipped_count": self.skipped_count,
            "db_path": self.db_path,
        }


@dataclass(frozen=True)
class ChunkFtsHit:
    """One lexical hit returned from the derived FTS5 index."""

    project_id: str
    material_id: str
    chunk_id: str
    title: str
    page: int | None
    chunk_type: str
    chunk_hash: str
    embedding_input_hash: str
    score: float
    snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable search hit."""

        return {
            "project_id": self.project_id,
            "material_id": self.material_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "page": self.page,
            "chunk_type": self.chunk_type,
            "chunk_hash": self.chunk_hash,
            "embedding_input_hash": self.embedding_input_hash,
            "score": self.score,
            "snippet": self.snippet,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ChunkFtsSearchResult:
    """Bounded FTS5 search result with index consistency status."""

    status: ChunkFtsIndexStatus
    project_id: str
    query: str
    chunk_store_version: str
    expected_chunk_store_version: str
    hits: tuple[ChunkFtsHit, ...]
    fallback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result payload."""

        return {
            "status": self.status,
            "project_id": self.project_id,
            "query": self.query,
            "chunk_store_version": self.chunk_store_version,
            "expected_chunk_store_version": self.expected_chunk_store_version,
            "fallback_reason": self.fallback_reason,
            "hits": [hit.to_dict() for hit in self.hits],
        }


@dataclass(frozen=True)
class ChunkFtsIntegrityReport:
    """Strict proof that a derived FTS index matches chunk-store truth."""

    schema_version: str
    project_id: str
    chunk_store_version: str
    indexed_count: int
    skipped_count: int
    material_indexed_count: int
    db_path: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable integrity report."""

        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "chunk_store_version": self.chunk_store_version,
            "indexed_count": self.indexed_count,
            "skipped_count": self.skipped_count,
            "material_indexed_count": self.material_indexed_count,
            "db_path": self.db_path,
        }


class ChunkFtsIntegrityError(RuntimeError):
    """Bounded failure raised when FTS publication proof cannot be produced."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize a stable machine code and safe diagnostic message."""

        safe_message = str(message or "Chunk FTS integrity check failed").replace("\n", " ")[:500]
        super().__init__(safe_message)
        self.code = str(code or "fts_integrity_error")[:80]
        self.safe_message = safe_message


def _require_non_empty_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _bounded_text(value: object, *, max_chars: int = 5000) -> str:
    return str(value or "").replace("\x00", " ").strip()[:max_chars]


def _coerce_page(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        page = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _tokenize_query(query: str) -> list[str]:
    tokens = [_bounded_text(token, max_chars=80).lower() for token in _TOKEN_RE.findall(query)]
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not token or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped[:16]


def _fts_match_query(query: str) -> str:
    tokens = _tokenize_query(query)
    return " AND ".join(f'"{token.replace(chr(34), chr(34) + chr(34))}"' for token in tokens)


def _fts_relaxed_match_query(query: str) -> str:
    tokens = _tokenize_query(query)
    if len(tokens) < 2:
        return ""
    return " OR ".join(f'"{token.replace(chr(34), chr(34) + chr(34))}"' for token in tokens)


def _chunk_index_text(chunk: Mapping[str, Any]) -> str:
    fields = [
        chunk.get("title"),
        chunk.get("content"),
        chunk.get("raw_content"),
        chunk.get("summary"),
        chunk.get("caption"),
        chunk.get("doi"),
        chunk.get("source_relative_path"),
        chunk.get("figure_candidate"),
        chunk.get("table_csv"),
        chunk.get("equation_latex"),
    ]
    locator = chunk.get("locator")
    if isinstance(locator, Mapping):
        fields.extend(locator.values())
    return "\n".join(_bounded_text(field) for field in fields if _bounded_text(field))


def _chunk_metadata_json(chunk: Mapping[str, Any]) -> str:
    metadata = {
        "source_relative_path": _bounded_text(chunk.get("source_relative_path"), max_chars=500),
        "section_title": _bounded_text(chunk.get("section_title"), max_chars=300),
        "chunk_index": chunk.get("chunk_index") if isinstance(chunk.get("chunk_index"), int) else None,
        "locator_quality": _bounded_text(chunk.get("locator_quality"), max_chars=80),
        "has_image": bool(chunk.get("image_paths") or chunk.get("figure_image_paths")),
        "has_table": bool(_bounded_text(chunk.get("table_csv"))),
        "has_equation": bool(_bounded_text(chunk.get("equation_latex"))),
    }
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iter_indexable_chunks(
    store: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    hash_version: str = CHUNK_HASH_VERSION,
) -> tuple[list[tuple[Any, ...]], int]:
    if not isinstance(store, Mapping):
        raise TypeError("store must be a mapping of material ids to chunk sequences")
    if hash_version not in SUPPORTED_CHUNK_HASH_VERSIONS:
        raise ValueError("unsupported chunk hash version")

    rows: list[tuple[Any, ...]] = []
    skipped = 0
    for raw_material_id, chunks in sorted(store.items(), key=lambda item: str(item[0])):
        material_id = _require_non_empty_string(str(raw_material_id), name="material_id")
        if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
            raise TypeError("store material values must be chunk sequences")
        for chunk in chunks:
            if not isinstance(chunk, Mapping):
                skipped += 1
                continue
            chunk_id = _bounded_text(chunk.get("chunk_id"), max_chars=240)
            content = _chunk_index_text(chunk)
            if not chunk_id or not content:
                skipped += 1
                continue
            try:
                hashes = compute_chunk_hashes(
                    chunk,
                    material_id_hint=material_id,
                    hash_version=hash_version,
                )
            except (TypeError, ValueError):
                skipped += 1
                continue
            rows.append(
                (
                    material_id,
                    chunk_id,
                    _bounded_text(chunk.get("title"), max_chars=500),
                    _coerce_page(chunk.get("page")),
                    _bounded_text(chunk.get("chunk_type"), max_chars=80) or "unknown",
                    hashes["chunk_hash"],
                    hashes["embedding_input_hash"],
                    content,
                    _chunk_metadata_json(chunk),
                )
            )
    return rows, skipped


def _open_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _open_sqlite_read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro",
        timeout=30.0,
        uri=True,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _assert_fts5_available(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__fts5_probe USING fts5(value)")
        conn.execute("DROP TABLE temp.__fts5_probe")
    except sqlite3.Error as exc:
        raise RuntimeError("SQLite FTS5 is not available in this Python runtime") from exc


def _initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = DELETE;
        PRAGMA synchronous = FULL;
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            project_id TEXT NOT NULL,
            material_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            title TEXT NOT NULL,
            page INTEGER,
            chunk_type TEXT NOT NULL,
            chunk_hash TEXT NOT NULL,
            embedding_input_hash TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            UNIQUE(project_id, material_id, chunk_id)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            project_id UNINDEXED,
            material_id,
            chunk_id UNINDEXED,
            title,
            content,
            tokenize = 'unicode61'
        );
        """
    )


def rebuild_chunk_fts_index(
    *,
    db_path: Path,
    project_id: str,
    store: Mapping[str, Sequence[Mapping[str, Any]]],
    chunk_store_version: str,
    hash_version: str = CHUNK_HASH_VERSION,
) -> ChunkFtsBuildReport:
    """Rebuild a project FTS5 index from chunk-store truth.

    Args:
        db_path: Target SQLite database path for the derived index.
        project_id: Project id isolated in this database.
        store: Current chunk-store truth mapping.
        chunk_store_version: Content-derived version from the chunk manifest.
        hash_version: Supported hash contract used by ``chunk_store_version``.

    Returns:
        Build report with indexed and skipped row counts.
    """

    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    normalized_version = _require_non_empty_string(chunk_store_version, name="chunk_store_version")
    if not isinstance(db_path, Path):
        raise TypeError("db_path must be a pathlib.Path")
    if hash_version not in SUPPORTED_CHUNK_HASH_VERSIONS:
        raise ValueError("unsupported chunk hash version")

    rows, skipped_count = _iter_indexable_chunks(
        store,
        hash_version=hash_version,
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    conn: sqlite3.Connection | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=db_path.parent,
            prefix=f"{db_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
        conn = _open_sqlite(temp_path)
        _assert_fts5_available(conn)
        _initialize_schema(conn)
        conn.execute("BEGIN")
        conn.executemany(
            """
            INSERT INTO chunks (
                project_id, material_id, chunk_id, title, page, chunk_type,
                chunk_hash, embedding_input_hash, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    normalized_project_id,
                    material_id,
                    chunk_id,
                    title,
                    page,
                    chunk_type,
                    chunk_hash,
                    embedding_input_hash,
                    metadata_json,
                )
                for (
                    material_id,
                    chunk_id,
                    title,
                    page,
                    chunk_type,
                    chunk_hash,
                    embedding_input_hash,
                    _content,
                    metadata_json,
                ) in rows
            ],
        )
        conn.executemany(
            """
            INSERT INTO chunks_fts(rowid, project_id, material_id, chunk_id, title, content)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    index + 1,
                    normalized_project_id,
                    material_id,
                    chunk_id,
                    title,
                    content,
                )
                for index, (material_id, chunk_id, title, _page, _chunk_type, _chunk_hash, _embedding_hash, content, _metadata) in enumerate(rows)
            ],
        )
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            [
                ("schema_version", CHUNK_FTS_INDEX_SCHEMA_VERSION),
                ("project_id", normalized_project_id),
                ("chunk_store_version", normalized_version),
                ("indexed_count", str(len(rows))),
                ("skipped_count", str(skipped_count)),
            ],
        )
        conn.commit()
        conn.close()
        conn = None
        os.replace(temp_path, db_path)
        temp_path = None
    except (OSError, sqlite3.Error):
        if conn is not None:
            conn.close()
        raise
    finally:
        if conn is not None:
            conn.close()
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    return ChunkFtsBuildReport(
        schema_version=CHUNK_FTS_INDEX_SCHEMA_VERSION,
        project_id=normalized_project_id,
        chunk_store_version=normalized_version,
        indexed_count=len(rows),
        skipped_count=skipped_count,
        db_path=str(db_path),
    )


def _read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.Error:
        return {}
    return {str(row["key"]): str(row["value"]) for row in rows}


def inspect_chunk_fts_index(
    *,
    db_path: Path,
    project_id: str,
    material_id: str,
    store: Mapping[str, Sequence[Mapping[str, Any]]],
    expected_chunk_store_version: str,
    hash_version: str = CHUNK_HASH_VERSION,
) -> ChunkFtsIntegrityReport:
    """Verify that every persisted FTS row matches the supplied chunk snapshot.

    Args:
        db_path: Existing SQLite FTS database to inspect without rebuilding it.
        project_id: Project that exclusively owns the database.
        material_id: Material whose chunks must all be retrieval-visible.
        store: Complete project chunk-store snapshot protected by the caller's
            chunk-store lock.
        expected_chunk_store_version: Content-derived version of ``store``.
        hash_version: Supported hash contract used by the persisted index.

    Returns:
        Counts and version metadata from the verified persisted index.

    Raises:
        ChunkFtsIntegrityError: If metadata, table rows, hashes, FTS content,
            or target-material coverage differs from the supplied snapshot.
        TypeError: If ``db_path`` or ``store`` has an unsupported shape.
        ValueError: If an identifier or expected version is empty.
    """

    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    normalized_material_id = _require_non_empty_string(material_id, name="material_id")
    expected_version = _require_non_empty_string(
        expected_chunk_store_version,
        name="expected_chunk_store_version",
    )
    if not re.fullmatch(r"[0-9a-f]{64}", expected_version):
        raise ValueError("expected_chunk_store_version must be a lowercase SHA-256 digest")
    if not isinstance(db_path, Path):
        raise TypeError("db_path must be a pathlib.Path")
    if not isinstance(store, Mapping):
        raise TypeError("store must be a mapping of material ids to chunk sequences")
    if hash_version not in SUPPORTED_CHUNK_HASH_VERSIONS:
        raise ValueError("unsupported chunk hash version")
    target_chunks = store.get(normalized_material_id)
    if target_chunks is None:
        raise ChunkFtsIntegrityError(
            "fts_material_missing",
            "Target material is absent from the chunk-store snapshot",
        )
    if isinstance(target_chunks, (str, bytes)) or not isinstance(target_chunks, Sequence):
        raise TypeError("target material chunks must be a sequence")
    if not target_chunks:
        raise ChunkFtsIntegrityError(
            "fts_material_chunks_missing",
            "Target material must contain at least one retrieval-visible chunk",
        )

    try:
        expected_rows, expected_skipped_count = _iter_indexable_chunks(
            store,
            hash_version=hash_version,
        )
    except (TypeError, ValueError) as exc:
        raise ChunkFtsIntegrityError(
            "fts_expected_store_invalid",
            "Chunk-store snapshot cannot produce deterministic FTS rows",
        ) from exc

    expected_by_key: dict[tuple[str, str], tuple[Any, ...]] = {}
    for expected_row in expected_rows:
        key = (str(expected_row[0]), str(expected_row[1]))
        if key in expected_by_key:
            raise ChunkFtsIntegrityError(
                "fts_expected_row_duplicate",
                "Chunk-store snapshot contains duplicate material/chunk identifiers",
            )
        expected_by_key[key] = expected_row
    material_indexed_count = sum(
        1 for row in expected_rows if str(row[0]) == normalized_material_id
    )
    if material_indexed_count != len(target_chunks):
        raise ChunkFtsIntegrityError(
            "fts_material_not_indexable",
            "Every target material chunk must contain an indexable id and text",
        )
    if not db_path.is_file():
        raise ChunkFtsIntegrityError("fts_index_missing", "Chunk FTS index file is missing")

    try:
        with _open_sqlite_read_only(db_path) as conn:
            quick_check = conn.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                raise ChunkFtsIntegrityError(
                    "fts_index_corrupt",
                    "SQLite quick_check did not validate the chunk FTS index",
                )

            meta_rows = conn.execute("SELECT key, value FROM meta").fetchall()
            meta = {str(row["key"]): str(row["value"]) for row in meta_rows}
            if (
                meta.get("schema_version") != CHUNK_FTS_INDEX_SCHEMA_VERSION
                or meta.get("project_id") != normalized_project_id
            ):
                raise ChunkFtsIntegrityError(
                    "fts_index_contract_mismatch",
                    "Chunk FTS schema or project metadata does not match",
                )
            if meta.get("chunk_store_version") != expected_version:
                raise ChunkFtsIntegrityError(
                    "fts_index_stale",
                    "Chunk FTS index is not bound to the current chunk-store version",
                )

            count_values: dict[str, int] = {}
            for key in ("indexed_count", "skipped_count"):
                raw_value = meta.get(key, "")
                if not re.fullmatch(r"0|[1-9][0-9]*", raw_value):
                    raise ChunkFtsIntegrityError(
                        "fts_index_metadata_invalid",
                        f"Chunk FTS metadata field {key} is invalid",
                    )
                count_values[key] = int(raw_value)
            if (
                count_values["indexed_count"] != len(expected_rows)
                or count_values["skipped_count"] != expected_skipped_count
            ):
                raise ChunkFtsIntegrityError(
                    "fts_index_count_mismatch",
                    "Chunk FTS metadata counts do not match the chunk-store snapshot",
                )

            chunk_rows = conn.execute(
                """
                SELECT id, project_id, material_id, chunk_id, title, page,
                       chunk_type, chunk_hash, embedding_input_hash, metadata_json
                FROM chunks
                ORDER BY id
                """
            ).fetchall()
            if len(chunk_rows) != len(expected_rows):
                raise ChunkFtsIntegrityError(
                    "fts_index_row_count_mismatch",
                    "Persisted chunk row count does not match chunk-store truth",
                )

            persisted_ids: set[int] = set()
            for row in chunk_rows:
                row_id = int(row["id"])
                key = (str(row["material_id"]), str(row["chunk_id"]))
                expected = expected_by_key.get(key)
                if row_id in persisted_ids or expected is None:
                    raise ChunkFtsIntegrityError(
                        "fts_index_row_mismatch",
                        "Persisted chunk identity is duplicate or absent from chunk-store truth",
                    )
                persisted_ids.add(row_id)
                actual_contract = (
                    str(row["project_id"]),
                    str(row["title"]),
                    row["page"],
                    str(row["chunk_type"]),
                    str(row["chunk_hash"]),
                    str(row["embedding_input_hash"]),
                    str(row["metadata_json"]),
                )
                expected_contract = (
                    normalized_project_id,
                    expected[2],
                    expected[3],
                    expected[4],
                    expected[5],
                    expected[6],
                    expected[8],
                )
                if actual_contract != expected_contract:
                    raise ChunkFtsIntegrityError(
                        "fts_index_row_mismatch",
                        "Persisted chunk metadata or hashes differ from chunk-store truth",
                    )

            fts_rows = conn.execute(
                """
                SELECT rowid, project_id, material_id, chunk_id, title, content
                FROM chunks_fts
                ORDER BY rowid
                """
            ).fetchall()
            fts_by_row_id = {int(row["rowid"]): row for row in fts_rows}
            if len(fts_by_row_id) != len(chunk_rows) or len(fts_rows) != len(chunk_rows):
                raise ChunkFtsIntegrityError(
                    "fts_virtual_row_count_mismatch",
                    "FTS virtual rows do not cover every persisted chunk row",
                )
            for row in chunk_rows:
                row_id = int(row["id"])
                fts_row = fts_by_row_id.get(row_id)
                key = (str(row["material_id"]), str(row["chunk_id"]))
                expected = expected_by_key[key]
                if fts_row is None or (
                    str(fts_row["project_id"]),
                    str(fts_row["material_id"]),
                    str(fts_row["chunk_id"]),
                    str(fts_row["title"]),
                    str(fts_row["content"]),
                ) != (
                    normalized_project_id,
                    expected[0],
                    expected[1],
                    expected[2],
                    expected[7],
                ):
                    raise ChunkFtsIntegrityError(
                        "fts_virtual_row_mismatch",
                        "FTS virtual row content differs from chunk-store truth",
                    )
    except ChunkFtsIntegrityError:
        raise
    except sqlite3.Error as exc:
        raise ChunkFtsIntegrityError(
            "fts_index_unreadable",
            "Chunk FTS index could not be read as the expected SQLite schema",
        ) from exc

    return ChunkFtsIntegrityReport(
        schema_version=CHUNK_FTS_INDEX_SCHEMA_VERSION,
        project_id=normalized_project_id,
        chunk_store_version=expected_version,
        indexed_count=len(expected_rows),
        skipped_count=expected_skipped_count,
        material_indexed_count=material_indexed_count,
        db_path=str(db_path),
    )


def search_chunk_fts_index(
    *,
    db_path: Path,
    project_id: str,
    query: str,
    expected_chunk_store_version: str,
    limit: int = 10,
) -> ChunkFtsSearchResult:
    """Search a derived FTS5 index after chunk-store version validation.

    Args:
        db_path: SQLite FTS database built by ``rebuild_chunk_fts_index``.
        project_id: Project id expected in the index metadata.
        query: Non-empty lexical query.
        expected_chunk_store_version: Current truth-store version.
        limit: Maximum hits to return, from 1 to 100.

    Returns:
        Search result. Non-``valid`` status means callers must use fallback.
    """

    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    normalized_query = _require_non_empty_string(query, name="query")
    expected_version = _require_non_empty_string(expected_chunk_store_version, name="expected_chunk_store_version")
    if not isinstance(db_path, Path):
        raise TypeError("db_path must be a pathlib.Path")
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    if not db_path.exists():
        return ChunkFtsSearchResult(
            status="missing",
            project_id=normalized_project_id,
            query=normalized_query,
            chunk_store_version="",
            expected_chunk_store_version=expected_version,
            hits=(),
            fallback_reason="fts_index_missing",
        )

    match_query = _fts_match_query(normalized_query)
    if not match_query:
        return ChunkFtsSearchResult(
            status="valid",
            project_id=normalized_project_id,
            query=normalized_query,
            chunk_store_version=expected_version,
            expected_chunk_store_version=expected_version,
            hits=(),
        )

    try:
        with _open_sqlite(db_path) as conn:
            meta = _read_meta(conn)
            actual_project_id = meta.get("project_id", "")
            actual_version = meta.get("chunk_store_version", "")
            if meta.get("schema_version") != CHUNK_FTS_INDEX_SCHEMA_VERSION or actual_project_id != normalized_project_id:
                return ChunkFtsSearchResult(
                    status="unavailable",
                    project_id=normalized_project_id,
                    query=normalized_query,
                    chunk_store_version=actual_version,
                    expected_chunk_store_version=expected_version,
                    hits=(),
                    fallback_reason="fts_index_contract_mismatch",
                )
            if actual_version != expected_version:
                return ChunkFtsSearchResult(
                    status="stale",
                    project_id=normalized_project_id,
                    query=normalized_query,
                    chunk_store_version=actual_version,
                    expected_chunk_store_version=expected_version,
                    hits=(),
                    fallback_reason="fts_index_stale",
                )
            rows = conn.execute(
                """
                SELECT
                    chunks.project_id,
                    chunks.material_id,
                    chunks.chunk_id,
                    chunks.title,
                    chunks.page,
                    chunks.chunk_type,
                    chunks.chunk_hash,
                    chunks.embedding_input_hash,
                    chunks.metadata_json,
                    bm25(chunks_fts) AS rank,
                    snippet(chunks_fts, 4, '', '', ' … ', 20) AS snippet
                FROM chunks_fts
                JOIN chunks ON chunks.id = chunks_fts.rowid
                WHERE chunks_fts MATCH ? AND chunks.project_id = ?
                ORDER BY rank ASC, chunks.material_id ASC, chunks.chunk_id ASC
                LIMIT ?
                """,
                (match_query, normalized_project_id, limit),
            ).fetchall()
            query_fallback_reason = ""
            relaxed_match_query = _fts_relaxed_match_query(normalized_query)
            if not rows and relaxed_match_query and relaxed_match_query != match_query:
                rows = conn.execute(
                    """
                    SELECT
                        chunks.project_id,
                        chunks.material_id,
                        chunks.chunk_id,
                        chunks.title,
                        chunks.page,
                        chunks.chunk_type,
                        chunks.chunk_hash,
                        chunks.embedding_input_hash,
                        chunks.metadata_json,
                        bm25(chunks_fts) AS rank,
                        snippet(chunks_fts, 4, '', '', ' … ', 20) AS snippet
                    FROM chunks_fts
                    JOIN chunks ON chunks.id = chunks_fts.rowid
                    WHERE chunks_fts MATCH ? AND chunks.project_id = ?
                    ORDER BY rank ASC, chunks.material_id ASC, chunks.chunk_id ASC
                    LIMIT ?
                    """,
                    (relaxed_match_query, normalized_project_id, limit),
                ).fetchall()
                if rows:
                    query_fallback_reason = "fts_relaxed_or"
    except sqlite3.Error:
        return ChunkFtsSearchResult(
            status="unavailable",
            project_id=normalized_project_id,
            query=normalized_query,
            chunk_store_version="",
            expected_chunk_store_version=expected_version,
            hits=(),
            fallback_reason="fts_index_query_error",
        )

    hits: list[ChunkFtsHit] = []
    for row in rows:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        hits.append(
            ChunkFtsHit(
                project_id=str(row["project_id"]),
                material_id=str(row["material_id"]),
                chunk_id=str(row["chunk_id"]),
                title=str(row["title"]),
                page=row["page"] if isinstance(row["page"], int) else None,
                chunk_type=str(row["chunk_type"]),
                chunk_hash=str(row["chunk_hash"]),
                embedding_input_hash=str(row["embedding_input_hash"]),
                score=round(abs(float(row["rank"] or 0.0)), 6),
                snippet=_bounded_text(row["snippet"], max_chars=500),
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        )
    return ChunkFtsSearchResult(
        status="valid",
        project_id=normalized_project_id,
        query=normalized_query,
        chunk_store_version=expected_version,
        expected_chunk_store_version=expected_version,
        hits=tuple(hits),
        fallback_reason=query_fallback_reason,
    )
