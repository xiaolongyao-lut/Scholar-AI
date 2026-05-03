from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wiki.source_registry import (
    ChunkInput,
    SourceRecord,
    WikiRegistry,
    derive_chunk_id,
    derive_source_id,
    sha256_text,
    utc_now_iso,
)


class TestSha256Text:
    def test_basic(self) -> None:
        result = sha256_text("hello")
        assert len(result) == 64
        assert result == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_deterministic(self) -> None:
        assert sha256_text("test") == sha256_text("test")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            sha256_text("")

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a string"):
            sha256_text(123)  # type: ignore


class TestDeriveSourceId:
    def test_basic(self) -> None:
        result = derive_source_id("paper", "Test Paper", "abc123def456")
        assert result.startswith("paper-test-paper-")
        assert result.endswith("abc123def456"[:12])

    def test_deterministic(self) -> None:
        result1 = derive_source_id("paper", "Title", "hash123")
        result2 = derive_source_id("paper", "Title", "hash123")
        assert result1 == result2

    def test_normalizes_type(self) -> None:
        result = derive_source_id("PAPER", "Title", "hash123")
        assert result.startswith("paper-")

    def test_sanitizes_title(self) -> None:
        result = derive_source_id("paper", "Test / Paper: 2024", "hash123")
        assert "test-paper-2024" in result
        assert "/" not in result
        assert ":" not in result

    def test_empty_type_raises(self) -> None:
        with pytest.raises(ValueError, match="required"):
            derive_source_id("", "Title", "hash123")

    def test_empty_title_raises(self) -> None:
        with pytest.raises(ValueError, match="required"):
            derive_source_id("paper", "", "hash123")


class TestDeriveChunkId:
    def test_basic(self) -> None:
        result = derive_chunk_id("source_hash_123", 0)
        assert len(result) == 16
        assert result.isalnum()

    def test_deterministic(self) -> None:
        result1 = derive_chunk_id("hash", 5)
        result2 = derive_chunk_id("hash", 5)
        assert result1 == result2

    def test_different_index_different_id(self) -> None:
        id1 = derive_chunk_id("hash", 0)
        id2 = derive_chunk_id("hash", 1)
        assert id1 != id2

    def test_negative_index_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            derive_chunk_id("hash", -1)


class TestWikiRegistry:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> WikiRegistry:
        db_path = tmp_path / "test_registry.db"
        return WikiRegistry(db_path)

    def test_creates_schema(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        registry = WikiRegistry(db_path)
        assert db_path.exists()
        with registry.connect() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {row["name"] for row in tables}
            assert "wiki_sources" in table_names
            assert "wiki_chunks" in table_names

    def test_upsert_source_creates_new(self, registry: WikiRegistry) -> None:
        record = SourceRecord(
            source_id="paper-test-abc123",
            source_type="paper",
            title="Test Paper",
            source_hash="abc123",
            source_path=Path("/test/paper.pdf"),
        )
        now = utc_now_iso()
        is_new = registry.upsert_source(record, now_iso=now)
        assert is_new is True
        retrieved = registry.get_source("paper-test-abc123")
        assert retrieved is not None
        assert retrieved.title == "Test Paper"
        assert retrieved.source_hash == "abc123"

    def test_upsert_source_updates_existing(self, registry: WikiRegistry) -> None:
        record1 = SourceRecord(
            source_id="paper-test-abc123",
            source_type="paper",
            title="Old Title",
            source_hash="abc123",
            source_path=Path("/old/path.pdf"),
        )
        now1 = utc_now_iso()
        registry.upsert_source(record1, now_iso=now1)
        record2 = SourceRecord(
            source_id="paper-test-abc123",
            source_type="paper",
            title="New Title",
            source_hash="abc123",
            source_path=Path("/new/path.pdf"),
        )
        now2 = utc_now_iso()
        is_new = registry.upsert_source(record2, now_iso=now2)
        assert is_new is False
        retrieved = registry.get_source("paper-test-abc123")
        assert retrieved is not None
        assert retrieved.title == "New Title"
        assert retrieved.source_path == Path("/new/path.pdf")

    def test_upsert_source_rejects_hash_change(self, registry: WikiRegistry) -> None:
        record1 = SourceRecord(
            source_id="paper-test-abc123",
            source_type="paper",
            title="Title",
            source_hash="hash1",
            source_path=Path("/test.pdf"),
        )
        registry.upsert_source(record1, now_iso=utc_now_iso())
        record2 = SourceRecord(
            source_id="paper-test-abc123",
            source_type="paper",
            title="Title",
            source_hash="hash2",
            source_path=Path("/test.pdf"),
        )
        with pytest.raises(ValueError, match="immutability violation"):
            registry.upsert_source(record2, now_iso=utc_now_iso())

    def test_get_source_returns_none_when_not_found(self, registry: WikiRegistry) -> None:
        result = registry.get_source("nonexistent")
        assert result is None

    def test_list_sources_empty(self, registry: WikiRegistry) -> None:
        result = registry.list_sources()
        assert result == []

    def test_list_sources_returns_all(self, registry: WikiRegistry) -> None:
        record1 = SourceRecord("id1", "paper", "Paper 1", "hash1", Path("/p1.pdf"))
        record2 = SourceRecord("id2", "paper", "Paper 2", "hash2", Path("/p2.pdf"))
        now = utc_now_iso()
        registry.upsert_source(record1, now_iso=now)
        registry.upsert_source(record2, now_iso=now)
        result = registry.list_sources()
        assert len(result) == 2
        assert {r.source_id for r in result} == {"id1", "id2"}

    def test_register_chunks_requires_existing_source(self, registry: WikiRegistry) -> None:
        chunks = [ChunkInput(text="chunk 0", chunk_index=0)]
        with pytest.raises(ValueError, match="not found"):
            registry.register_chunks("nonexistent", "hash", chunks, now_iso=utc_now_iso())

    def test_register_chunks_inserts_new(self, registry: WikiRegistry) -> None:
        record = SourceRecord("src1", "paper", "Paper", "hash1", Path("/p.pdf"))
        registry.upsert_source(record, now_iso=utc_now_iso())
        chunks = [
            ChunkInput(text="chunk 0", chunk_index=0, page="1"),
            ChunkInput(text="chunk 1", chunk_index=1, page="2"),
        ]
        count = registry.register_chunks("src1", "hash1", chunks, now_iso=utc_now_iso())
        assert count == 2
        retrieved = registry.get_chunks_by_source("src1")
        assert len(retrieved) == 2
        assert retrieved[0]["text"] == "chunk 0"
        assert retrieved[1]["text"] == "chunk 1"

    def test_register_chunks_rejects_hash_mismatch(self, registry: WikiRegistry) -> None:
        record = SourceRecord("src1", "paper", "Paper", "hash1", Path("/p.pdf"))
        registry.upsert_source(record, now_iso=utc_now_iso())
        chunks = [ChunkInput(text="chunk 0", chunk_index=0)]
        with pytest.raises(ValueError, match="mismatch"):
            registry.register_chunks("src1", "wrong_hash", chunks, now_iso=utc_now_iso())

    def test_get_chunks_by_source_empty(self, registry: WikiRegistry) -> None:
        record = SourceRecord("src1", "paper", "Paper", "hash1", Path("/p.pdf"))
        registry.upsert_source(record, now_iso=utc_now_iso())
        result = registry.get_chunks_by_source("src1")
        assert result == []

    def test_verify_chunk_exists_true(self, registry: WikiRegistry) -> None:
        record = SourceRecord("src1", "paper", "Paper", "hash1", Path("/p.pdf"))
        registry.upsert_source(record, now_iso=utc_now_iso())
        chunks = [ChunkInput(text="chunk 0", chunk_index=0)]
        registry.register_chunks("src1", "hash1", chunks, now_iso=utc_now_iso())
        chunk_id = derive_chunk_id("hash1", 0)
        assert registry.verify_chunk_exists(chunk_id) is True

    def test_verify_chunk_exists_false(self, registry: WikiRegistry) -> None:
        assert registry.verify_chunk_exists("nonexistent") is False
