"""Tests for saved exploration page flow (LMWR-353).

Covers:
  - Exploration page creation with frontmatter
  - Citation validator accepts saved exploration (LMWR-357)
  - Slug generation from query
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from literature_assistant.core.wiki.models import WikiPageKind, WikiPageStatus
from literature_assistant.core.wiki.page_store import WikiPageStore
from literature_assistant.core.wiki.query import save_exploration


@pytest.fixture
def temp_wiki_root() -> Path:
    """Create temporary wiki root directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def page_store(temp_wiki_root: Path) -> WikiPageStore:
    """Create WikiPageStore instance."""
    return WikiPageStore(temp_wiki_root)


class TestExplorationPageCreation:
    """Test exploration page creation (LMWR-353)."""

    def test_save_exploration_creates_page(self, page_store: WikiPageStore) -> None:
        """Test that save_exploration creates exploration page with correct structure."""
        query = "What is machine learning?"
        answer = "Machine learning is a subset of AI that enables systems to learn from data."
        evidence_refs = [
            {
                "chunk_id": "chunk-001",
                "source_id": "source-001",
                "text": "ML is a field of study",
                "quote": "Machine learning enables systems to learn",
            }
        ]

        result = save_exploration(query, answer, evidence_refs, page_store)

        assert result.success
        assert result.relative_path == Path("exploration/what-is-machine-learning.md")
        assert result.content_hash is not None
        assert result.error is None

    def test_exploration_page_frontmatter(self, page_store: WikiPageStore) -> None:
        """Test that exploration page has correct frontmatter."""
        query = "How does neural networks work?"
        answer = "Neural networks are computational models inspired by biological neurons."
        evidence_refs = [
            {
                "chunk_id": "chunk-002",
                "source_id": "source-002",
                "text": "Neural networks are inspired by biology",
                "quote": "Networks inspired by neurons",
            }
        ]

        result = save_exploration(query, answer, evidence_refs, page_store)

        assert result.success
        assert result.relative_path is not None

        # Read the saved page
        content = page_store.read_page(result.relative_path)
        assert content is not None

        # Parse frontmatter
        lines = content.split("\n")
        assert lines[0] == "---json"
        fm_end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        fm_text = "\n".join(lines[1:fm_end])
        frontmatter = json.loads(fm_text)

        assert frontmatter["kind"] == WikiPageKind.exploration.value
        assert frontmatter["status"] == WikiPageStatus.draft.value
        assert frontmatter["title"] == query
        assert frontmatter["id"].startswith("exploration/")

    def test_exploration_save_never_auto_finalizes(self, page_store: WikiPageStore) -> None:
        """Test explicit save writes draft only, leaving finalization to review gates."""
        query = "Finalization policy"
        answer = "This answer remains a draft until review."
        evidence_refs = [
            {
                "chunk_id": "chunk-011",
                "source_id": "source-011",
                "text": "Draft evidence text",
                "quote": "Draft evidence text",
            }
        ]

        result = save_exploration(query, answer, evidence_refs, page_store)

        assert result.success
        assert result.relative_path is not None
        content = page_store.read_page(result.relative_path)
        assert content is not None
        lines = content.split("\n")
        fm_end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        frontmatter = json.loads("\n".join(lines[1:fm_end]))
        assert frontmatter["status"] == WikiPageStatus.draft.value

    def test_exploration_page_body(self, page_store: WikiPageStore) -> None:
        """Test that exploration page body contains question, answer, and evidence."""
        query = "What is deep learning?"
        answer = "Deep learning uses multiple layers of neural networks."
        evidence_refs = [
            {
                "chunk_id": "chunk-003",
                "source_id": "source-003",
                "text": "Deep learning uses multiple layers",
                "quote": "Multiple layers of networks",
            }
        ]

        result = save_exploration(query, answer, evidence_refs, page_store)

        assert result.success
        assert result.relative_path is not None

        content = page_store.read_page(result.relative_path)
        assert content is not None

        # Extract body (after frontmatter and auto markers)
        lines = content.split("\n")
        fm_end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        body_start = next(
            i for i, line in enumerate(lines[fm_end + 1 :], start=fm_end + 1)
            if "<!-- literature-assistant:auto:start -->" in line
        )
        body_lines = lines[body_start + 1 :]

        body_text = "\n".join(body_lines)
        assert f"# {query}" in body_text
        assert answer in body_text
        assert "## Evidence" in body_text
        assert "[[source-003]]" in body_text

    def test_exploration_with_source_ids(self, page_store: WikiPageStore) -> None:
        """Test that source_ids are included in frontmatter."""
        query = "Test query"
        answer = "Test answer"
        evidence_refs = [
            {
                "chunk_id": "chunk-004",
                "source_id": "source-004",
                "text": "Test text",
                "quote": "Test quote",
            }
        ]
        source_ids = ("source-001", "source-002")

        result = save_exploration(query, answer, evidence_refs, page_store, source_ids=source_ids)

        assert result.success
        assert result.relative_path is not None

        content = page_store.read_page(result.relative_path)
        assert content is not None

        lines = content.split("\n")
        fm_end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        fm_text = "\n".join(lines[1:fm_end])
        frontmatter = json.loads(fm_text)

        assert frontmatter.get("source_ids") == list(source_ids)


class TestSlugGeneration:
    """Test slug generation from query (LMWR-353)."""

    def test_slug_from_simple_query(self, page_store: WikiPageStore) -> None:
        """Test slug generation from simple query."""
        query = "What is AI?"
        answer = "AI is artificial intelligence."
        evidence_refs = [
            {
                "chunk_id": "chunk-005",
                "source_id": "source-005",
                "text": "AI definition",
                "quote": "Artificial intelligence",
            }
        ]

        result = save_exploration(query, answer, evidence_refs, page_store)

        assert result.success
        assert result.relative_path == Path("exploration/what-is-ai.md")

    def test_slug_from_complex_query(self, page_store: WikiPageStore) -> None:
        """Test slug generation from complex query with special characters."""
        query = "How do we implement ML models in production?"
        answer = "Production ML requires careful deployment strategies."
        evidence_refs = [
            {
                "chunk_id": "chunk-006",
                "source_id": "source-006",
                "text": "Production deployment",
                "quote": "Deploy ML models",
            }
        ]

        result = save_exploration(query, answer, evidence_refs, page_store)

        assert result.success
        assert result.relative_path is not None
        # Slug should be normalized
        assert result.relative_path.parent == Path("exploration")
        assert result.relative_path.suffix == ".md"

    def test_slug_deterministic(self, page_store: WikiPageStore) -> None:
        """Test that same query generates same slug."""
        query = "What is determinism?"
        answer = "Determinism is the philosophical view."
        evidence_refs = [
            {
                "chunk_id": "chunk-007",
                "source_id": "source-007",
                "text": "Determinism definition",
                "quote": "Philosophical view",
            }
        ]

        result1 = save_exploration(query, answer, evidence_refs, page_store)
        result2 = save_exploration(query, answer, evidence_refs, page_store)

        assert result1.relative_path == result2.relative_path


class TestErrorHandling:
    """Test error handling in save_exploration."""

    def test_empty_query_raises_error(self, page_store: WikiPageStore) -> None:
        """Test that empty query returns error result."""
        result = save_exploration(
            "",
            "Answer",
            [{"chunk_id": "c1", "source_id": "s1", "text": "t", "quote": "q"}],
            page_store,
        )

        assert not result.success
        assert result.error is not None
        assert "question cannot be empty" in result.error

    def test_unquotable_evidence_ref_is_rejected(self, page_store: WikiPageStore) -> None:
        """Test that exploration save requires citation-safe evidence text."""
        result = save_exploration(
            "Query",
            "Answer",
            [{"chunk_id": "chunk-no-text", "source_id": "source-no-text", "text": "", "quote": ""}],
            page_store,
        )

        assert not result.success
        assert result.error is not None
        assert "no quotable text" in result.error

    def test_empty_answer_raises_error(self, page_store: WikiPageStore) -> None:
        """Test that empty answer returns error result."""
        result = save_exploration(
            "Query",
            "",
            [{"chunk_id": "c1", "source_id": "s1", "text": "t", "quote": "q"}],
            page_store,
        )

        assert not result.success
        assert result.error is not None
        assert "answer cannot be empty" in result.error

    def test_no_evidence_refs_raises_error(self, page_store: WikiPageStore) -> None:
        """Test that no evidence refs returns error result."""
        result = save_exploration("Query", "Answer", [], page_store)

        assert not result.success
        assert result.error is not None
        assert "at least one evidence reference is required" in result.error

    def test_invalid_evidence_ref_raises_error(self, page_store: WikiPageStore) -> None:
        """Test that invalid evidence ref returns error result."""
        result = save_exploration(
            "Query",
            "Answer",
            [{"invalid": "ref"}],  # Missing required fields
            page_store,
        )

        assert not result.success
        assert result.error is not None


class TestCitationValidation:
    """Test citation validator accepts saved exploration (LMWR-357)."""

    def test_exploration_page_has_citations(self, page_store: WikiPageStore) -> None:
        """Test that exploration page includes citations in evidence section."""
        query = "Test query"
        answer = "Test answer"
        evidence_refs = [
            {
                "chunk_id": "chunk-008",
                "source_id": "source-008",
                "text": "Evidence text",
                "quote": "Evidence quote",
            },
            {
                "chunk_id": "chunk-009",
                "source_id": "source-009",
                "text": "More evidence",
                "quote": "More quote",
            },
        ]

        result = save_exploration(query, answer, evidence_refs, page_store)

        assert result.success
        assert result.relative_path is not None

        content = page_store.read_page(result.relative_path)
        assert content is not None

        # Check that both citations are present
        assert "[[source-008]]" in content
        assert "[[source-009]]" in content

    def test_exploration_page_structure_for_validator(self, page_store: WikiPageStore) -> None:
        """Test that exploration page structure is compatible with citation validator."""
        query = "Validator test"
        answer = "This is a test answer with claims."
        evidence_refs = [
            {
                "chunk_id": "chunk-010",
                "source_id": "source-010",
                "text": "Supporting evidence",
                "quote": "This supports the claim",
            }
        ]

        result = save_exploration(query, answer, evidence_refs, page_store)

        assert result.success
        assert result.relative_path is not None

        content = page_store.read_page(result.relative_path)
        assert content is not None

        # Verify structure for validator
        lines = content.split("\n")

        # Has frontmatter
        assert lines[0] == "---json"
        fm_end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        assert fm_end > 1

        # Has auto markers
        assert "<!-- literature-assistant:auto:start -->" in content
        assert "<!-- literature-assistant:auto:end -->" in content

        # Has evidence section with citations
        assert "## Evidence" in content
        assert "[[source-010]]" in content
