from __future__ import annotations

from pathlib import Path

import pytest

from literature_assistant.core.wiki.citation_validator import (
    ParsedCitation,
    ValidationLevel,
    ValidationMode,
    ValidationReport,
    calculate_citation_density,
    detect_claim_sentences,
    extract_citations,
    parse_citation,
    validate_citation_exists,
    validate_page,
    validate_quote_match,
)
from literature_assistant.core.wiki.source_registry import (
    ChunkInput,
    SourceRecord,
    WikiRegistry,
    utc_now_iso,
)


class TestParseCitation:
    def test_wikilink_with_chunk(self) -> None:
        result = parse_citation("[[sources/paper-123#abc123]]")
        assert result.source_id == "sources/paper-123"
        assert result.chunk_id == "abc123"

    def test_wikilink_without_chunk(self) -> None:
        result = parse_citation("[[sources/paper-123]]")
        assert result.source_id == "sources/paper-123"
        assert result.chunk_id is None

    def test_chunk_id_only(self) -> None:
        result = parse_citation("[abc123def4567890]")
        assert result.chunk_id == "abc123def4567890"
        assert result.source_id is None

    def test_no_match(self) -> None:
        result = parse_citation("plain text")
        assert result.source_id is None
        assert result.chunk_id is None
        assert result.raw == "plain text"

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a string"):
            parse_citation(123)  # type: ignore


class TestExtractCitations:
    def test_multiple_citations(self) -> None:
        text = "This [[sources/a]] and [[sources/b#chunk1]] are cited."
        result = extract_citations(text)
        assert len(result) == 2
        assert result[0].source_id == "sources/a"
        assert result[1].source_id == "sources/b"
        assert result[1].chunk_id == "chunk1"

    def test_no_citations(self) -> None:
        result = extract_citations("No citations here.")
        assert result == []

    def test_mixed_formats(self) -> None:
        text = "See [[sources/paper]] and [abc123def4567890]."
        result = extract_citations(text)
        assert len(result) == 2
        assert result[0].source_id == "sources/paper"
        assert result[1].chunk_id == "abc123def4567890"

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a string"):
            extract_citations(None)  # type: ignore


class TestDetectClaimSentences:
    def test_basic_claims(self) -> None:
        body = "This is a claim. Another claim here."
        result = detect_claim_sentences(body)
        assert len(result) == 2
        assert "This is a claim." in result[0]
        assert "Another claim here." in result[1]

    def test_skips_headers(self) -> None:
        body = "# Header\nThis is a claim."
        result = detect_claim_sentences(body)
        assert len(result) == 1
        assert "claim" in result[0].lower()

    def test_skips_code_blocks(self) -> None:
        body = "```\nThis is code.\n```\nThis is a claim."
        result = detect_claim_sentences(body)
        assert len(result) == 1
        assert "claim" in result[0].lower()

    def test_skips_list_items(self) -> None:
        body = "- List item\n* Another item\nThis is a claim."
        result = detect_claim_sentences(body)
        assert len(result) == 1
        assert "claim" in result[0].lower()

    def test_minimum_length(self) -> None:
        body = "Short. This is a longer claim sentence."
        result = detect_claim_sentences(body)
        assert len(result) == 1
        assert "longer" in result[0]

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError, match="must be a string"):
            detect_claim_sentences(123)  # type: ignore


class TestValidateCitationExists:
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
        from literature_assistant.core.wiki.source_registry import derive_chunk_id
        chunk_id = derive_chunk_id("hash1", 0)
        citation = ParsedCitation(raw="[chunk]", chunk_id=chunk_id)
        assert validate_citation_exists(citation, registry) is True

    def test_source_exists(self, registry: WikiRegistry) -> None:
        citation = ParsedCitation(raw="[[src1]]", source_id="src1")
        assert validate_citation_exists(citation, registry) is True

    def test_chunk_not_found(self, registry: WikiRegistry) -> None:
        citation = ParsedCitation(raw="[missing]", chunk_id="missing123456789")
        assert validate_citation_exists(citation, registry) is False

    def test_source_not_found(self, registry: WikiRegistry) -> None:
        citation = ParsedCitation(raw="[[missing]]", source_id="missing")
        assert validate_citation_exists(citation, registry) is False


class TestValidateQuoteMatch:
    def test_exact_match(self) -> None:
        assert validate_quote_match("exact text", "This is exact text here.") is True

    def test_no_match(self) -> None:
        assert validate_quote_match("missing", "This is some text.") is False

    def test_fuzzy_match(self) -> None:
        assert validate_quote_match("Exact  Text", "this is exact text here.", fuzzy=True) is True

    def test_fuzzy_no_match(self) -> None:
        assert validate_quote_match("missing", "This is some text.", fuzzy=True) is False

    def test_non_string_raises(self) -> None:
        with pytest.raises(TypeError, match="must be strings"):
            validate_quote_match(123, "text")  # type: ignore


class TestCalculateCitationDensity:
    def test_full_coverage(self) -> None:
        assert calculate_citation_density(10, 10) == 1.0

    def test_partial_coverage(self) -> None:
        assert calculate_citation_density(10, 5) == 0.5

    def test_zero_claims(self) -> None:
        assert calculate_citation_density(0, 0) == 1.0


class TestValidatePage:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> WikiRegistry:
        db_path = tmp_path / "test.db"
        reg = WikiRegistry(db_path)
        record = SourceRecord("src1", "paper", "Test", "hash1", Path("/test.pdf"))
        reg.upsert_source(record, now_iso=utc_now_iso())
        chunks = [ChunkInput(text="chunk text", chunk_index=0)]
        reg.register_chunks("src1", "hash1", chunks, now_iso=utc_now_iso())
        return reg

    def test_draft_mode_allows_missing_citations(self, registry: WikiRegistry) -> None:
        body = "This is a claim without citation."
        fm = {"id": "test", "kind": "paper", "title": "Test"}
        report = validate_page(body, fm, registry, mode=ValidationMode.DRAFT)
        assert report.passed is True
        assert report.total_claims == 1
        assert report.cited_claims == 0

    def test_final_mode_rejects_missing_citations(self, registry: WikiRegistry) -> None:
        body = "This is a claim without citation."
        fm = {"id": "test", "kind": "paper", "title": "Test"}
        report = validate_page(body, fm, registry, mode=ValidationMode.FINAL)
        assert report.passed is False
        assert any(issue.level == ValidationLevel.FAILED for issue in report.issues)

    def test_valid_citations_pass(self, registry: WikiRegistry) -> None:
        body = "This is a claim [[src1]]."
        fm = {"id": "test", "kind": "paper", "title": "Test"}
        report = validate_page(body, fm, registry, mode=ValidationMode.FINAL)
        assert report.passed is True
        assert report.cited_claims == 1

    def test_missing_citation_target_fails_final(self, registry: WikiRegistry) -> None:
        body = "This is a claim [[missing]]."
        fm = {"id": "test", "kind": "paper", "title": "Test"}
        report = validate_page(body, fm, registry, mode=ValidationMode.FINAL)
        assert report.passed is False
        assert any("not found" in issue.message for issue in report.issues)

    def test_missing_citation_target_warns_draft(self, registry: WikiRegistry) -> None:
        body = "This is a claim [[missing]]."
        fm = {"id": "test", "kind": "paper", "title": "Test"}
        report = validate_page(body, fm, registry, mode=ValidationMode.DRAFT)
        assert report.passed is True
        assert any(issue.level == ValidationLevel.WARNING for issue in report.issues)

    def test_citation_density_calculated(self, registry: WikiRegistry) -> None:
        body = "Claim one [[src1]]. Claim two here. Claim three [[src1]]."
        fm = {"id": "test", "kind": "paper", "title": "Test"}
        report = validate_page(body, fm, registry, mode=ValidationMode.DRAFT)
        assert report.total_claims == 3
        assert report.cited_claims == 2
        assert abs(report.citation_density - 0.666) < 0.01

    def test_non_string_body_raises(self, registry: WikiRegistry) -> None:
        fm = {"id": "test", "kind": "paper", "title": "Test"}
        with pytest.raises(TypeError, match="must be a string"):
            validate_page(123, fm, registry)  # type: ignore

    def test_non_mapping_frontmatter_raises(self, registry: WikiRegistry) -> None:
        with pytest.raises(TypeError, match="must be a mapping"):
            validate_page("body", "not a dict", registry)  # type: ignore
