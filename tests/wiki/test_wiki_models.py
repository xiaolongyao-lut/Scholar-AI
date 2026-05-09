"""
Tests for literature_assistant.core.wiki.models (LMWR-246 · Wave 1 verification)
"""
from __future__ import annotations

import json

import pytest

from literature_assistant.core.wiki.models import (
    ClaimAuditResult,
    WikiClaimAuditLevel,
    WikiCompilationOptions,
    WikiPage,
    WikiPageKind,
    WikiPageStatus,
    WikiRegistryEntry,
    WikiSourceRef,
    from_evidence_reference,
    make_stable_slug,
    HUMAN_ONLY_TRANSITIONS,
)


# ---------------------------------------------------------------------------
# WikiPageKind
# ---------------------------------------------------------------------------


class TestWikiPageKind:
    def test_values_exist(self):
        assert WikiPageKind.synthesis.value == "synthesis"
        assert WikiPageKind.concept.value == "concept"
        assert WikiPageKind.paper.value == "paper"
        assert WikiPageKind.experiment.value == "experiment"
        assert WikiPageKind.question.value == "question"

    def test_from_value(self):
        assert WikiPageKind("synthesis") == WikiPageKind.synthesis


# ---------------------------------------------------------------------------
# WikiPageStatus
# ---------------------------------------------------------------------------


class TestWikiPageStatus:
    def test_values_exist(self):
        for v in ("draft", "review", "final", "deprecated", "archived"):
            assert WikiPageStatus(v).value == v

    def test_human_only_transitions_contain_review_to_final(self):
        assert (WikiPageStatus.review, WikiPageStatus.final) in HUMAN_ONLY_TRANSITIONS


# ---------------------------------------------------------------------------
# make_stable_slug
# ---------------------------------------------------------------------------


class TestMakeStableSlug:
    def test_basic(self):
        slug = make_stable_slug("What is RAG?", WikiPageKind.question)
        assert slug.startswith("question-")
        assert " " not in slug
        assert "?" not in slug

    def test_deterministic(self):
        slug1 = make_stable_slug("CRISPR mechanisms", WikiPageKind.concept)
        slug2 = make_stable_slug("CRISPR mechanisms", WikiPageKind.concept)
        assert slug1 == slug2

    def test_unicode_normalised(self):
        slug = make_stable_slug("Über alles", WikiPageKind.concept)
        assert "ü" not in slug
        assert "concept-" in slug

    def test_no_path_separators(self):
        slug = make_stable_slug("a/b\\c", WikiPageKind.synthesis)
        assert "/" not in slug
        assert "\\" not in slug

    def test_empty_title_fallback(self):
        slug = make_stable_slug("", WikiPageKind.paper)
        assert slug == "paper-untitled"


# ---------------------------------------------------------------------------
# from_evidence_reference
# ---------------------------------------------------------------------------


class TestFromEvidenceReference:
    def _make_er(self, **overrides):
        er = {
            "chunk_id": "c1",
            "material_id": "m1",
            "text": "some text",
            "compressed_text": "short",
            "quote": "verbatim",
            "label": "Author 2023",
        }
        er.update(overrides)
        return er

    def test_roundtrip_required_fields(self):
        ref = from_evidence_reference(self._make_er())
        assert ref["chunk_id"] == "c1"
        assert ref["material_id"] == "m1"
        assert ref["text"] == "some text"

    def test_optional_fields_passed_through(self):
        ref = from_evidence_reference(self._make_er(score=0.9, rank=1))
        assert ref["score"] == 0.9
        assert ref["rank"] == 1

    def test_wiki_extension_passed_through(self):
        ref = from_evidence_reference(self._make_er(citation_target="Smith, 2021"))
        assert ref["citation_target"] == "Smith, 2021"

    def test_missing_required_raises(self):
        with pytest.raises(ValueError, match="material_id"):
            from_evidence_reference({"chunk_id": "x", "text": "t", "compressed_text": "", "quote": "", "label": ""})


# ---------------------------------------------------------------------------
# WikiPage
# ---------------------------------------------------------------------------


class TestWikiPage:
    def _make_page(self, **overrides):
        defaults = dict(
            stable_slug="synthesis-what-is-rag",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="What is RAG?",
            body="# What is RAG?\n\nRetrieval augmented generation ...",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-03T00:00:00Z",
            updated_at_iso="2026-05-03T00:00:00Z",
        )
        defaults.update(overrides)
        return WikiPage(**defaults)

    def test_frozen(self):
        page = self._make_page()
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            page.status = WikiPageStatus.final  # type: ignore[misc]

    def test_evolve_returns_new_instance(self):
        page = self._make_page()
        updated = page.evolve(status=WikiPageStatus.review, updated_at_iso="2026-05-04T00:00:00Z")
        assert updated.status == WikiPageStatus.review
        assert page.status == WikiPageStatus.draft  # original unchanged

    def test_to_dict_from_dict_roundtrip(self):
        ref: WikiSourceRef = {
            "chunk_id": "c1", "material_id": "m1", "text": "t",
            "compressed_text": "", "quote": "", "label": "L",
        }
        page = self._make_page(
            evidence_refs=(ref,),
            source_hashes=("abc123",),
        )
        d = page.to_dict()
        restored = WikiPage.from_dict(d)
        assert restored.stable_slug == page.stable_slug
        assert restored.kind == page.kind
        assert restored.status == page.status
        assert len(restored.evidence_refs) == 1
        assert restored.evidence_refs[0]["chunk_id"] == "c1"

    def test_json_serialisable(self):
        page = self._make_page()
        # Should not raise
        json.dumps(page.to_dict())

    def test_evolve_preserves_other_fields(self):
        page = self._make_page(title="Original Title")
        updated = page.evolve(status=WikiPageStatus.review)
        assert updated.title == "Original Title"
        assert updated.kind == WikiPageKind.synthesis


# ---------------------------------------------------------------------------
# WikiCompilationOptions
# ---------------------------------------------------------------------------


class TestWikiCompilationOptions:
    def test_defaults(self):
        opts = WikiCompilationOptions(kind=WikiPageKind.synthesis, query="What is RAG?")
        assert opts.dry_run is True
        assert opts.force_recompile is False
        assert opts.min_citation_density == 0.95

    def test_custom(self):
        opts = WikiCompilationOptions(
            kind=WikiPageKind.concept,
            query="CRISPR",
            dry_run=False,
            max_source_chunks=5,
        )
        assert opts.dry_run is False
        assert opts.max_source_chunks == 5


# ---------------------------------------------------------------------------
# ClaimAuditResult
# ---------------------------------------------------------------------------


class TestClaimAuditResult:
    def test_passed(self):
        r = ClaimAuditResult(
            claim_text="RAG improves accuracy",
            level=WikiClaimAuditLevel.passed,
            reason="chunk c1 cited",
            chunk_ids=("c1",),
        )
        assert r.level == WikiClaimAuditLevel.passed

    def test_frozen(self):
        r = ClaimAuditResult("t", WikiClaimAuditLevel.failed, "no citation")
        with pytest.raises(Exception):
            r.level = WikiClaimAuditLevel.passed  # type: ignore[misc]


# ---------------------------------------------------------------------------
# WikiRegistryEntry
# ---------------------------------------------------------------------------


class TestWikiRegistryEntry:
    def test_roundtrip(self):
        entry = WikiRegistryEntry(
            stable_slug="synthesis-what-is-rag",
            kind="synthesis",
            status="draft",
            title="What is RAG?",
            source_hash="deadbeef",
            updated_at_iso="2026-05-03T00:00:00Z",
            chunk_ids=("c1", "c2"),
        )
        d = entry.to_dict()
        restored = WikiRegistryEntry.from_dict(d)
        assert restored.stable_slug == entry.stable_slug
        assert restored.chunk_ids == entry.chunk_ids
