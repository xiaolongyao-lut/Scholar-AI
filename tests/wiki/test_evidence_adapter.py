from __future__ import annotations

from pathlib import Path

import pytest

from literature_assistant.core.wiki.evidence_adapter import (
    NormalizedEvidence,
    coerce_evidence_reference,
    evidence_to_wiki_citation,
    last_answer_to_synthesis_draft,
    lookup_source_for_evidence,
    normalize_evidence,
    parse_prompt_evidence,
    render_citation,
)
from literature_assistant.core.wiki.source_registry import (
    ChunkInput,
    SourceRecord,
    WikiRegistry,
    derive_chunk_id,
    utc_now_iso,
)


class TestCoerceEvidenceReference:
    def test_dict_passthrough(self) -> None:
        raw = {"chunk_id": "abc", "text": "test"}
        result = coerce_evidence_reference(raw)
        assert result == raw

    def test_object_with_dict(self) -> None:
        class Evidence:
            def __init__(self) -> None:
                self.chunk_id = "abc"
                self.text = "test"
        obj = Evidence()
        result = coerce_evidence_reference(obj)
        assert result["chunk_id"] == "abc"
        assert result["text"] == "test"

    def test_namedtuple(self) -> None:
        from collections import namedtuple
        Evidence = namedtuple("Evidence", ["chunk_id", "text"])
        obj = Evidence(chunk_id="abc", text="test")
        result = coerce_evidence_reference(obj)
        assert result["chunk_id"] == "abc"

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(TypeError, match="Cannot coerce"):
            coerce_evidence_reference("string")


class TestNormalizeEvidence:
    def test_full_fields(self) -> None:
        raw = {
            "chunk_id": "abc",
            "source_id": "src1",
            "text": "content",
            "quote": "quote",
            "page": "5",
            "rank": 1,
            "source_labels": ["bm25"],
            "query_overlap_tokens": 10,
        }
        result = normalize_evidence(raw)
        assert result.chunk_id == "abc"
        assert result.source_id == "src1"
        assert result.text == "content"
        assert result.quote == "quote"
        assert result.page == "5"
        assert result.rank == 1
        assert result.source_labels == ["bm25"]
        assert result.query_overlap_tokens == 10

    def test_material_id_fallback(self) -> None:
        raw = {"material_id": "mat123", "text": "content"}
        result = normalize_evidence(raw)
        assert result.chunk_id == "mat123"

    def test_compressed_fallback(self) -> None:
        raw = {"chunk_id": "abc", "compressed": "compressed text"}
        result = normalize_evidence(raw)
        assert result.text == "compressed text"

    def test_minimal_fields(self) -> None:
        raw = {"text": "content"}
        result = normalize_evidence(raw)
        assert result.chunk_id is None
        assert result.source_id is None
        assert result.text == "content"


class TestLookupSourceForEvidence:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> WikiRegistry:
        db_path = tmp_path / "test.db"
        reg = WikiRegistry(db_path)
        record = SourceRecord("src1", "paper", "Test", "hash1", Path("/test.pdf"))
        reg.upsert_source(record, now_iso=utc_now_iso())
        chunks = [ChunkInput(text="chunk text", chunk_index=0)]
        reg.register_chunks("src1", "hash1", chunks, now_iso=utc_now_iso())
        return reg

    def test_chunk_exists(self, registry: WikiRegistry) -> None:
        chunk_id = derive_chunk_id("hash1", 0)
        evidence = NormalizedEvidence(chunk_id=chunk_id, source_id=None, text="test")
        result = lookup_source_for_evidence(evidence, registry)
        assert result == chunk_id

    def test_source_exists(self, registry: WikiRegistry) -> None:
        evidence = NormalizedEvidence(chunk_id=None, source_id="src1", text="test")
        result = lookup_source_for_evidence(evidence, registry)
        assert result == "src1"

    def test_not_found(self, registry: WikiRegistry) -> None:
        evidence = NormalizedEvidence(chunk_id="missing", source_id=None, text="test")
        result = lookup_source_for_evidence(evidence, registry)
        assert result is None


class TestRenderCitation:
    def test_chunk_id(self) -> None:
        evidence = NormalizedEvidence(chunk_id="abc123", source_id=None, text="test")
        result = render_citation(evidence)
        assert result == "[abc123]"

    def test_source_id_with_page(self) -> None:
        evidence = NormalizedEvidence(chunk_id=None, source_id="src1", text="test", page="5")
        result = render_citation(evidence)
        assert result == "[[src1#page-5]]"

    def test_source_id_without_page(self) -> None:
        evidence = NormalizedEvidence(chunk_id=None, source_id="src1", text="test")
        result = render_citation(evidence)
        assert result == "[[src1]]"

    def test_no_identifiers(self) -> None:
        evidence = NormalizedEvidence(chunk_id=None, source_id=None, text="test")
        result = render_citation(evidence)
        assert result == ""


class TestEvidenceToWikiCitation:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> WikiRegistry:
        db_path = tmp_path / "test.db"
        reg = WikiRegistry(db_path)
        record = SourceRecord("src1", "paper", "Test", "hash1", Path("/test.pdf"))
        reg.upsert_source(record, now_iso=utc_now_iso())
        chunks = [ChunkInput(text="chunk text", chunk_index=0)]
        reg.register_chunks("src1", "hash1", chunks, now_iso=utc_now_iso())
        return reg

    def test_valid_chunk(self, registry: WikiRegistry) -> None:
        chunk_id = derive_chunk_id("hash1", 0)
        raw = {"chunk_id": chunk_id, "text": "test"}
        citation, found = evidence_to_wiki_citation(raw, registry)
        assert found is True
        assert citation == f"[{chunk_id}]"

    def test_valid_source(self, registry: WikiRegistry) -> None:
        raw = {"source_id": "src1", "text": "test"}
        citation, found = evidence_to_wiki_citation(raw, registry)
        assert found is True
        assert citation == "[[src1]]"

    def test_missing_draft_mode(self, registry: WikiRegistry) -> None:
        raw = {"chunk_id": "missing", "text": "test"}
        citation, found = evidence_to_wiki_citation(raw, registry, fallback_mode="draft")
        assert found is False
        assert citation == ""

    def test_missing_strict_mode_raises(self, registry: WikiRegistry) -> None:
        raw = {"chunk_id": "missing", "text": "test"}
        with pytest.raises(ValueError, match="not found in registry"):
            evidence_to_wiki_citation(raw, registry, fallback_mode="strict")


class TestParsePromptEvidence:
    def test_basic_format(self) -> None:
        line = "src1 / MATERIAL: mat123 / QUOTE: test quote / BODY: body text"
        result = parse_prompt_evidence(line)
        assert result["source_id"] == "src1"
        assert result["material_id"] == "mat123"
        assert result["quote"] == "test quote"
        assert result["body"] == "body text"

    def test_minimal_format(self) -> None:
        line = "src1 / MATERIAL: mat123"
        result = parse_prompt_evidence(line)
        assert result["source_id"] == "src1"
        assert result["material_id"] == "mat123"

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid prompt evidence format"):
            parse_prompt_evidence("invalid")

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a string"):
            parse_prompt_evidence(123)  # type: ignore


class TestLastAnswerToSynthesisDraft:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> WikiRegistry:
        db_path = tmp_path / "test.db"
        reg = WikiRegistry(db_path)
        record = SourceRecord("src1", "paper", "Test", "hash1", Path("/test.pdf"))
        reg.upsert_source(record, now_iso=utc_now_iso())
        chunks = [ChunkInput(text="chunk text", chunk_index=0)]
        reg.register_chunks("src1", "hash1", chunks, now_iso=utc_now_iso())
        return reg

    def test_basic_conversion(self, registry: WikiRegistry) -> None:
        chunk_id = derive_chunk_id("hash1", 0)
        last_answer = {
            "query": "What is X?",
            "answer": "X is Y.",
            "evidence_refs": [
                {"chunk_id": chunk_id, "text": "evidence"}
            ],
        }
        result = last_answer_to_synthesis_draft(last_answer, registry)
        assert result["frontmatter"]["kind"] == "synthesis"
        assert result["frontmatter"]["status"] == "draft"
        assert "What is X?" in result["frontmatter"]["title"]
        assert "X is Y." in result["body"]
        assert f"[{chunk_id}]" in result["body"]

    def test_missing_evidence_skipped(self, registry: WikiRegistry) -> None:
        last_answer = {
            "query": "What is X?",
            "answer": "X is Y.",
            "evidence_refs": [
                {"chunk_id": "missing", "text": "evidence"}
            ],
        }
        result = last_answer_to_synthesis_draft(last_answer, registry)
        assert "## Evidence" in result["body"]
        assert "[missing]" not in result["body"]

    def test_non_mapping_raises(self, registry: WikiRegistry) -> None:
        with pytest.raises(TypeError, match="must be a mapping"):
            last_answer_to_synthesis_draft("not a dict", registry)  # type: ignore
