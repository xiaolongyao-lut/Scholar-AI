# -*- coding: utf-8 -*-
"""
Test Writing Resources Layer - Phase 3

Comprehensive test suite for writing resource models, store operations, and API endpoints.
Ensures backend resource layer correctly replaces fabricated payloads.
"""

import pytest
from datetime import datetime

from writing_resources import (
    WritingProject,
    WritingSection,
    WritingDraft,
    WritingRevision,
    WritingAssociationAngle,
    WritingAssociationBundle,
    WritingAssociationSignal,
    WritingEvidenceGap,
    WritingResourceStore,
    ProjectStatus,
    ContentType,
    DraftStatus,
    enrich_association_bundle_with_analysis,
    check_association_enrichment_increment,
    get_writing_resource_store,
)


class TestWritingProject:
    """Tests for WritingProject model."""

    def test_create_project(self):
        """Test creating a project."""
        project = WritingProject.create(
            title="Test Project",
            description="A test project",
            content_type=ContentType.ACADEMIC,
        )
        assert project.title == "Test Project"
        assert project.description == "A test project"
        assert project.content_type == ContentType.ACADEMIC
        assert project.status == ProjectStatus.DRAFT
        assert project.project_id.startswith("proj_")

    def test_project_is_immutable(self):
        """Test that project is immutable."""
        project = WritingProject.create(title="Test")
        with pytest.raises(AttributeError):
            project.title = "Modified"

    def test_project_with_status(self):
        """Test updating project status returns new instance."""
        project = WritingProject.create(title="Test")
        updated = project.with_status(ProjectStatus.PUBLISHED)
        assert project.status == ProjectStatus.DRAFT
        assert updated.status == ProjectStatus.PUBLISHED
        assert project.project_id == updated.project_id

    def test_project_to_dict(self):
        """Test project serialization to dict."""
        project = WritingProject.create(
            title="Test",
            content_type=ContentType.TECHNICAL,
        )
        data = project.to_dict()
        assert data["title"] == "Test"
        assert data["status"] == "draft"
        assert data["content_type"] == "technical"


class TestWritingSection:
    """Tests for WritingSection model."""

    def test_create_section(self):
        """Test creating a section."""
        section = WritingSection.create(
            project_id="proj_123",
            title="Introduction",
            order=1,
        )
        assert section.title == "Introduction"
        assert section.order == 1
        assert section.project_id == "proj_123"
        assert section.section_id.startswith("sect_")

    def test_section_to_dict(self):
        """Test section serialization."""
        section = WritingSection.create(
            project_id="proj_123",
            title="Chapter 1",
            order=1,
        )
        data = section.to_dict()
        assert data["title"] == "Chapter 1"
        assert data["order"] == 1


class TestWritingDraft:
    """Tests for WritingDraft model."""

    def test_create_draft(self):
        """Test creating a draft."""
        draft = WritingDraft.create(
            project_id="proj_123",
            title="Initial Draft",
            content="Some content",
        )
        assert draft.title == "Initial Draft"
        assert draft.content == "Some content"
        assert draft.status == DraftStatus.CREATED
        assert draft.draft_id.startswith("draft_")

    def test_draft_with_content(self):
        """Test updating draft content."""
        draft = WritingDraft.create(
            project_id="proj_123",
            content="Original",
        )
        updated = draft.with_content("Updated content", edited_by="john")
        assert draft.content == "Original"
        assert updated.content == "Updated content"
        assert updated.status == DraftStatus.EDITING
        assert updated.last_edited_by == "john"
        assert draft.draft_id == updated.draft_id

    def test_draft_with_status(self):
        """Test updating draft status."""
        draft = WritingDraft.create(project_id="proj_123")
        updated = draft.with_status(DraftStatus.APPROVED)
        assert draft.status == DraftStatus.CREATED
        assert updated.status == DraftStatus.APPROVED

    def test_draft_to_dict(self):
        """Test draft serialization."""
        draft = WritingDraft.create(
            project_id="proj_123",
            title="Test",
            content="Content here",
        )
        data = draft.to_dict()
        assert data["title"] == "Test"
        assert data["content"] == "Content here"
        assert data["status"] == "created"


class TestWritingRevision:
    """Tests for WritingRevision model."""

    def test_create_revision(self):
        """Test creating a revision."""
        revision = WritingRevision.create(
            draft_id="draft_123",
            project_id="proj_123",
            content="Revision content",
            revision_number=1,
            created_by="user1",
            message="Initial revision",
        )
        assert revision.content == "Revision content"
        assert revision.revision_number == 1
        assert revision.created_by == "user1"
        assert revision.message == "Initial revision"

    def test_revision_to_dict(self):
        """Test revision serialization."""
        revision = WritingRevision.create(
            draft_id="draft_123",
            project_id="proj_123",
            content="Test",
            revision_number=1,
        )
        data = revision.to_dict()
        assert data["content"] == "Test"
        assert data["revision_number"] == 1


class TestWritingResourceStore:
    """Tests for WritingResourceStore."""

    def test_create_and_get_project(self):
        """Test creating and retrieving a project."""
        store = WritingResourceStore()
        project = store.create_project(
            title="Test Project",
            description="A test project",
        )
        retrieved = store.get_project(project.project_id)
        assert retrieved is not None
        assert retrieved.title == "Test Project"

    def test_list_projects(self):
        """Test listing projects."""
        store = WritingResourceStore()
        p1 = store.create_project(title="Project 1")
        p2 = store.create_project(title="Project 2")
        
        projects = store.list_projects()
        assert len(projects) >= 2
        titles = [p.title for p in projects]
        assert "Project 1" in titles
        assert "Project 2" in titles

    def test_list_projects_by_user(self):
        """Test listing projects filtered by user."""
        store = WritingResourceStore()
        store.create_project(title="User 1 Project", user_id="user1")
        store.create_project(title="User 2 Project", user_id="user2")
        
        user1_projects = store.list_projects(user_id="user1")
        assert len(user1_projects) == 1
        assert user1_projects[0].title == "User 1 Project"

    def test_update_project_status(self):
        """Test updating project status."""
        store = WritingResourceStore()
        project = store.create_project(title="Test")
        
        updated = store.update_project_status(
            project.project_id,
            ProjectStatus.PUBLISHED
        )
        assert updated.status == ProjectStatus.PUBLISHED
        
        retrieved = store.get_project(project.project_id)
        assert retrieved.status == ProjectStatus.PUBLISHED

    def test_create_and_list_sections(self):
        """Test creating and listing sections."""
        store = WritingResourceStore()
        project = store.create_project(title="Test")
        
        s1 = store.create_section(project.project_id, "Section 1", order=1)
        s2 = store.create_section(project.project_id, "Section 2", order=2)
        
        sections = store.list_sections(project.project_id)
        assert len(sections) == 2
        assert sections[0].order == 1
        assert sections[1].order == 2

    def test_create_and_get_draft(self):
        """Test creating and retrieving a draft."""
        store = WritingResourceStore()
        project = store.create_project(title="Test")
        
        draft = store.create_draft(
            project.project_id,
            title="Draft 1",
            content="Initial content",
        )
        retrieved = store.get_draft(draft.draft_id)
        assert retrieved is not None
        assert retrieved.title == "Draft 1"
        assert retrieved.content == "Initial content"

    def test_save_draft_creates_revision(self):
        """Test that saving a draft auto-creates a revision."""
        store = WritingResourceStore()
        project = store.create_project(title="Test")
        draft = store.create_draft(project.project_id, content="Original")
        
        updated_draft = store.save_draft(
            draft.draft_id,
            "Updated content",
            edited_by="user1",
            create_revision=True,
        )
        assert updated_draft.content == "Updated content"
        
        revisions = store.list_revisions(draft.draft_id)
        assert len(revisions) == 1
        assert revisions[0].content == "Updated content"
        assert revisions[0].created_by == "user1"

    def test_list_drafts_by_section(self):
        """Test listing drafts filtered by section."""
        store = WritingResourceStore()
        project = store.create_project(title="Test")
        s1 = store.create_section(project.project_id, "Section 1", order=1)
        
        d1 = store.create_draft(project.project_id, section_id=s1.section_id)
        d2 = store.create_draft(project.project_id)  # No section
        
        section_drafts = store.list_drafts(project.project_id, section_id=s1.section_id)
        assert len(section_drafts) == 1
        assert section_drafts[0].draft_id == d1.draft_id

    def test_restore_revision(self):
        """Test restoring a draft from a revision."""
        store = WritingResourceStore()
        project = store.create_project(title="Test")
        draft = store.create_draft(project.project_id, content="V1")
        
        # Create multiple revisions
        store.save_draft(draft.draft_id, "V2", edited_by="user1")
        store.save_draft(draft.draft_id, "V3", edited_by="user2")
        
        revisions = store.list_revisions(draft.draft_id)
        assert len(revisions) == 2  # V2 and V3
        
        # Restore to V2
        restored = store.restore_revision(draft.draft_id, revisions[0].revision_id)
        assert restored.content == "V2"
        
        # Check that a new revision was created for the restore
        new_revisions = store.list_revisions(draft.draft_id)
        assert len(new_revisions) == 3  # V2, V3, and restore

    def test_export_state(self):
        """Test exporting resource state."""
        store = WritingResourceStore()
        
        project = store.create_project(title="Test")
        section = store.create_section(project.project_id, "Sec1", order=1)
        draft = store.create_draft(project.project_id, section_id=section.section_id)
        store.save_draft(draft.draft_id, "Content")
        
        state = store.export_state()
        assert "projects" in state
        assert "sections" in state
        assert "drafts" in state
        assert "revisions" in state
        assert "draft_revisions" in state
        
        assert len(state["projects"]) == 1
        assert len(state["sections"]) == 1
        assert len(state["drafts"]) == 1
        assert len(state["revisions"]) == 1

    def test_build_association_bundle_uses_project_drafts_and_memory(self):
        """Association bundle should rank local and memory evidence together."""
        store = WritingResourceStore()
        project = store.create_project(
            title="Memory-Augmented Literature Review",
            description="Connect long-term notes with current drafting goals.",
            content_type=ContentType.ACADEMIC,
        )
        section = store.create_section(
            project.project_id,
            title="Related Work",
            order=1,
            description="Summarize retrieval and writing support methods.",
        )
        draft = store.create_draft(
            project.project_id,
            section_id=section.section_id,
            title="Review Draft",
            content="Contextual retrieval improves literature review writing quality.",
        )
        store.create_section(
            project.project_id,
            title="Discussion",
            order=2,
            description="Interpret retrieval signals for final drafting decisions.",
        )
        store.create_draft(
            project.project_id,
            title="Method Notes",
            content="Graph retrieval can surface complementary evidence for writing transitions.",
        )

        bundle = store.build_association_bundle(
            project_id=project.project_id,
            query="contextual retrieval writing transitions",
            draft_id=draft.draft_id,
            section_id=section.section_id,
            memory_hits=[
                {
                    "text": "Contextual retrieval can recover related notes that support stronger review transitions.",
                    "wing": "writing",
                    "room": "retrieval",
                    "source_file": "memory_notes.md",
                    "similarity": 0.92,
                }
            ],
        )

        assert isinstance(bundle, WritingAssociationBundle)
        assert bundle.project_id == project.project_id
        assert bundle.memory_used is True
        assert bundle.memory_hit_count == 1
        assert bundle.focus_terms
        assert bundle.related_signals
        assert any(signal.source_type == "memory" for signal in bundle.related_signals)
        assert bundle.association_angles
        assert bundle.continuation_prompts
        assert bundle.recommended_memory_queries

    def test_build_association_bundle_reports_missing_memory_evidence(self):
        """Association bundle should expose a gap when memory evidence is absent."""
        store = WritingResourceStore()
        project = store.create_project(title="Sparse Project")
        store.create_section(project.project_id, "Intro", order=1, description="Sparse intro")

        bundle = store.build_association_bundle(
            project_id=project.project_id,
            query="novel synthesis pathway",
            signal_limit=3,
            angle_limit=2,
        )

        assert any(
            gap.gap == "No long-term memory evidence was incorporated"
            for gap in bundle.evidence_gaps
        )

    def test_build_association_bundle_rejects_draft_from_other_project(self):
        """Association builder should reject cross-project draft references."""
        store = WritingResourceStore()
        project_a = store.create_project(title="Project A")
        project_b = store.create_project(title="Project B")
        foreign_draft = store.create_draft(project_b.project_id, title="Foreign")

        with pytest.raises(ValueError, match="does not belong to project"):
            store.build_association_bundle(
                project_id=project_a.project_id,
                query="association test",
                draft_id=foreign_draft.draft_id,
            )

    def test_enrich_association_bundle_with_reasoning_conflicts(self):
        """Reasoning conflicts should become additional writing gaps and bridge angles."""
        base_bundle = WritingAssociationBundle(
            project_id="proj_demo",
            query="improve literature review transitions",
            focus_terms=["retrieval", "transition", "grounding"],
            related_signals=[
                WritingAssociationSignal(
                    source_type="retrieval",
                    source_id="chunk_1",
                    title="Retrieved evidence",
                    excerpt="Grounded retrieval improves transition quality.",
                    score=0.92,
                    shared_terms=["retrieval", "transition", "grounding"],
                    rationale="Shared focus: retrieval, transition",
                )
            ],
            association_angles=[
                WritingAssociationAngle(
                    angle_id="angle_1",
                    title="Bridge around 'transition'",
                    prompt="Connect the retrieved evidence back to the current section.",
                    supporting_source_ids=["chunk_1"],
                    shared_terms=["transition"],
                    confidence=0.81,
                )
            ],
            continuation_prompts=["Use the current evidence to transition into the next paragraph."],
            evidence_gaps=[
                WritingEvidenceGap(
                    gap="No long-term memory evidence was incorporated",
                    severity="medium",
                    recommendation="Search memory before drafting the next revision.",
                )
            ],
            recommended_memory_queries=["improve literature review transitions"],
        )

        enriched = enrich_association_bundle_with_analysis(
            base_bundle,
            analysis_payloads=[
                {
                    "final_conclusion": "Transition claims should be bounded by explicit evidence and limitations.",
                    "conflicts": [
                        {
                            "severity_level": 3,
                            "interpretation": "Two sources disagree on whether stronger transitions require explicit grounding.",
                            "authority_summary": "paper_a and paper_b disagree on the required grounding strength.",
                            "resolution_path": ["State whether the cited evidence is explicit or implied."],
                            "claims_involved": [
                                {
                                    "subject": "transition quality",
                                    "predicate": "improves",
                                    "object": "literature review coherence",
                                }
                            ],
                        }
                    ],
                }
            ],
        )

        assert len(enriched.association_angles) > len(base_bundle.association_angles)
        assert any(
            angle.title == "Resolve conflict on 'transition quality'"
            for angle in enriched.association_angles
        )
        assert any(
            gap.gap == "Conflicting evidence around 'transition quality' is not yet resolved"
            for gap in enriched.evidence_gaps
        )
        assert any(
            "transition quality consensus review" == query
            for query in enriched.recommended_memory_queries
        )


class TestWritingResourceGlobalStore:
    """Tests for global resource store singleton."""

    def test_get_store_creates_singleton(self):
        """Test that get_writing_resource_store returns a singleton."""
        store1 = get_writing_resource_store()
        store2 = get_writing_resource_store()
        assert store1 is store2


    def test_get_store_creates_singleton(self):
        """Test that get_writing_resource_store returns a singleton."""
        store1 = get_writing_resource_store()
        store2 = get_writing_resource_store()
        assert store1 is store2

    def test_global_store_persists_data(self):
        """Test that global store retains data across calls."""
        store = get_writing_resource_store()
        project = store.create_project(title="Test")
        
        store2 = get_writing_resource_store()
        retrieved = store2.get_project(project.project_id)
        assert retrieved is not None
        assert retrieved.title == "Test"


class TestWritingAssociationContentAware:
    """Tests for content-aware enrichment increment detection."""

    @pytest.fixture
    def base_bundle(self):
        return WritingAssociationBundle(
            project_id="proj_123",
            query="test query",
            association_angles=[
                WritingAssociationAngle(
                    angle_id="a1",
                    title="Old Title",
                    prompt="Old Prompt",
                    supporting_source_ids=["src1"],
                    shared_terms=["term1"],
                )
            ],
            continuation_prompts=["Prompt 1"],
            evidence_gaps=[
                WritingEvidenceGap(gap="Gap 1", severity="low", recommendation="Rec 1")
            ],
            recommended_memory_queries=["Query 1"],
        )

    def test_increment_count_increase(self, base_bundle):
        """Should detect increment if count increases."""
        enriched = WritingAssociationBundle(
            **{**base_bundle.__dict__, "continuation_prompts": ["Prompt 1", "Prompt 2"]}
        )
        assert check_association_enrichment_increment(base_bundle, enriched) is True

    def test_increment_content_change_same_count(self, base_bundle):
        """Should detect increment if content changes even if count remains same."""
        # Change angle title
        enriched_angle = WritingAssociationBundle(
            **{
                **base_bundle.__dict__,
                "association_angles": [
                    WritingAssociationAngle(
                        angle_id="a1",
                        title="NEW Title",
                        prompt="Old Prompt",
                        supporting_source_ids=["src1"],
                        shared_terms=["term1"],
                    )
                ],
            }
        )
        assert check_association_enrichment_increment(base_bundle, enriched_angle) is True

        # Change gap severity
        enriched_gap = WritingAssociationBundle(
            **{
                **base_bundle.__dict__,
                "evidence_gaps": [
                    WritingEvidenceGap(gap="Gap 1", severity="HIGH", recommendation="Rec 1")
                ],
            }
        )
        assert check_association_enrichment_increment(base_bundle, enriched_gap) is True

        # Change prompt text
        enriched_prompt = WritingAssociationBundle(
            **{**base_bundle.__dict__, "continuation_prompts": ["NEW Prompt"]}
        )
        assert check_association_enrichment_increment(base_bundle, enriched_prompt) is True

    def test_no_increment_same_content(self, base_bundle):
        """Should not detect increment if content is identical (ignoring case/whitespace where normalized)."""
        # Exactly the same
        assert check_association_enrichment_increment(base_bundle, base_bundle) is False

        # Same content, different casing/whitespace (normalized by signatures)
        normalized_angle = WritingAssociationAngle(
            angle_id="a1",
            title="  old title  ",
            prompt="OLD PROMPT",
            supporting_source_ids=["src1"],
            shared_terms=["TERM1"],
        )
        enriched = WritingAssociationBundle(
            **{**base_bundle.__dict__, "association_angles": [normalized_angle]}
        )
        assert check_association_enrichment_increment(base_bundle, enriched) is False

    def test_order_insensitivity(self, base_bundle):
        """Should be insensitive to order in supporting_sources and shared_terms."""
        base_reorder = WritingAssociationBundle(
            **{
                **base_bundle.__dict__,
                "association_angles": [
                    WritingAssociationAngle(
                        angle_id="a1",
                        title="T",
                        prompt="P",
                        supporting_source_ids=["A", "B"],
                        shared_terms=["X", "Y"],
                    )
                ],
            }
        )
        enriched_reorder = WritingAssociationBundle(
            **{
                **base_bundle.__dict__,
                "association_angles": [
                    WritingAssociationAngle(
                        angle_id="a1",
                        title="T",
                        prompt="P",
                        supporting_source_ids=["B", "A"],
                        shared_terms=["Y", "X"],
                    )
                ],
            }
        )
        assert check_association_enrichment_increment(base_reorder, enriched_reorder) is False

    def test_multiplicity_change_detected(self, base_bundle):
        """Should detect changes when repeated prompts are redistributed across the bundle."""
        base_duplicate_prompts = WritingAssociationBundle(
            **{**base_bundle.__dict__, "continuation_prompts": ["Prompt 1", "Prompt 1", "Prompt 2"]}
        )
        enriched_duplicate_prompts = WritingAssociationBundle(
            **{**base_bundle.__dict__, "continuation_prompts": ["Prompt 1", "Prompt 2", "Prompt 2"]}
        )

        assert check_association_enrichment_increment(base_duplicate_prompts, enriched_duplicate_prompts) is True


# Integration test with full workflow
@pytest.fixture
def fresh_store():
    """Provide a fresh resource store for each test."""
    return WritingResourceStore()


def test_full_writing_workflow(fresh_store):
    """Test complete writing workflow: project -> sections -> drafts -> revisions."""
    # Create project
    project = fresh_store.create_project(
        title="PhD Thesis",
        description="My doctoral research",
        content_type=ContentType.ACADEMIC,
    )
    assert project.status == ProjectStatus.DRAFT
    
    # Create sections
    intro = fresh_store.create_section(project.project_id, "Introduction", order=1)
    lit_review = fresh_store.create_section(project.project_id, "Literature Review", order=2)
    conclusion = fresh_store.create_section(project.project_id, "Conclusion", order=3)
    
    # Verify sections are ordered
    sections = fresh_store.list_sections(project.project_id)
    assert len(sections) == 3
    assert sections[0].title == "Introduction"
    
    # Create drafts for each section
    intro_draft = fresh_store.create_draft(
        project.project_id,
        title="Intro Draft",
        section_id=intro.section_id,
    )
    
    # Save draft with revisions
    fresh_store.save_draft(intro_draft.draft_id, "First version of intro", edited_by="alice")
    fresh_store.save_draft(intro_draft.draft_id, "Second version of intro", edited_by="bob")
    
    # Check revision history
    revisions = fresh_store.list_revisions(intro_draft.draft_id)
    assert len(revisions) == 2
    assert revisions[0].message == "Manual save"
    assert revisions[1].message == "Manual save"
    
    # Restore to first version
    restored = fresh_store.restore_revision(intro_draft.draft_id, revisions[0].revision_id)
    assert restored.content == "First version of intro"
    
    # Check project state can be exported
    state = fresh_store.export_state()
    assert len(state["projects"]) == 1
    assert len(state["sections"]) == 3
    assert len(state["drafts"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
