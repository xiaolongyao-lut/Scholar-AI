#!/usr/bin/env python3
"""Quick validation test for Phase 3 writing resources."""

from writing_resources import WritingResourceStore, ProjectStatus, ContentType

def test_resources():
    """Run quick tests for writing resources."""
    store = WritingResourceStore()
    
    # Test 1: Create project
    project = store.create_project(
        title="Test Project",
        content_type=ContentType.ACADEMIC
    )
    print(f"OK: Created project: {project.project_id}")
    
    # Test 2: Create section
    section = store.create_section(project.project_id, "Introduction", 1)
    print(f"OK: Created section: {section.section_id}")
    
    # Test 3: Create draft
    draft = store.create_draft(
        project.project_id,
        "Draft 1",
        "Initial content",
        section_id=section.section_id
    )
    print(f"OK: Created draft: {draft.draft_id}")
    
    # Test 4: Save draft with revision
    store.save_draft(draft.draft_id, "Updated content", edited_by="user1")
    print("OK: Saved draft with revision")
    
    # Test 5: List revisions
    revisions = store.list_revisions(draft.draft_id)
    print(f"OK: Listed {len(revisions)} revision(s)")
    
    # Test 6: Restore revision
    restored = store.restore_revision(draft.draft_id, revisions[0].revision_id)
    print("OK: Restored revision")
    
    # Test 7: Export state
    state = store.export_state()
    print(f"OK: Exported state with {len(state['projects'])} projects, {len(state['sections'])} sections, {len(state['drafts'])} drafts")
    
    # Test 8: Update project status
    updated_proj = store.update_project_status(project.project_id, ProjectStatus.PUBLISHED)
    print(f"OK: Updated project status to {updated_proj.status.value}")
    
    print("\nSUCCESS: All Phase 3 resource tests passed!")

if __name__ == "__main__":
    test_resources()
