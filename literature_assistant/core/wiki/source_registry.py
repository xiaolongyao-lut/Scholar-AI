from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wiki_sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    source_path TEXT NOT NULL,
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
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES wiki_sources(source_id)
);
CREATE INDEX IF NOT EXISTS idx_wiki_chunks_source_id ON wiki_chunks(source_id);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    source_type: str
    title: str
    source_hash: str
    source_path: Path


@dataclass(frozen=True)
class ChunkInput:
    text: str
    chunk_index: int
    page: str | None = None
    section: str | None = None
    span_start: int | None = None
    span_end: int | None = None


def sha256_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if not value:
        raise ValueError("value cannot be empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def derive_source_id(source_type: str, title: str, source_hash: str) -> str:
    source_type = source_type.strip().lower()
    title = title.strip()
    if not source_type or not title or not source_hash:
        raise ValueError("source_type, title, and source_hash are required")
    readable = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
    readable = "-".join(part for part in readable.split("-") if part)[:64] or "source"
    return f"{source_type}-{readable}-{source_hash[:12]}"


def derive_chunk_id(source_hash: str, chunk_index: int) -> str:
    if not source_hash:
        raise ValueError("source_hash is required")
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    return hashlib.sha256(f"{source_hash}:{chunk_index}".encode("utf-8")).hexdigest()[:16]


class WikiRegistry:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_source(self, record: SourceRecord, *, now_iso: str) -> bool:
        if not record.source_id or not record.source_hash:
            raise ValueError("source_id and source_hash are required")
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
                    source_id, source_type, title, source_hash, source_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title = excluded.title,
                    source_path = excluded.source_path,
                    updated_at = excluded.updated_at
                """,
                (
                    record.source_id,
                    record.source_type,
                    record.title,
                    record.source_hash,
                    str(record.source_path),
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
            return existing is None

    def get_source(self, source_id: str) -> SourceRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT source_id, source_type, title, source_hash, source_path FROM wiki_sources WHERE source_id = ?",
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
            )

    def list_sources(self) -> list[SourceRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT source_id, source_type, title, source_hash, source_path FROM wiki_sources ORDER BY created_at"
            ).fetchall()
            return [
                SourceRecord(
                    source_id=row["source_id"],
                    source_type=row["source_type"],
                    title=row["title"],
                    source_hash=row["source_hash"],
                    source_path=Path(row["source_path"]),
                )
                for row in rows
            ]

    def register_chunks(self, source_id: str, source_hash: str, chunks: Iterable[ChunkInput], *, now_iso: str) -> int:
        if not source_id or not source_hash:
            raise ValueError("source_id and source_hash are required")
        with self.connect() as conn:
            existing_source = conn.execute(
                "SELECT source_hash FROM wiki_sources WHERE source_id = ?",
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
            for chunk in chunks:
                chunk_id = derive_chunk_id(source_hash, chunk.chunk_index)
                text_hash = sha256_text(chunk.text)
                conn.execute(
                    """
                    INSERT INTO wiki_chunks (
                        chunk_id, source_id, source_hash, chunk_index, text_hash, text,
                        page, section, span_start, span_end, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        text = excluded.text,
                        text_hash = excluded.text_hash,
                        page = excluded.page,
                        section = excluded.section,
                        span_start = excluded.span_start,
                        span_end = excluded.span_end
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
                        now_iso,
                    ),
                )
                inserted += 1
            conn.commit()
            return inserted

    def get_chunks_by_source(self, source_id: str) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, source_id, chunk_index, text, page, section, span_start, span_end
                FROM wiki_chunks
                WHERE source_id = ?
                ORDER BY chunk_index
                """,
                (source_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def verify_chunk_exists(self, chunk_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM wiki_chunks WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
            return row is not None
