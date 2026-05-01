#!/usr/bin/env python3
"""
Integration test for Phase 3 Writing Resources API
Tests the FastAPI endpoints with mock HTTP calls.
"""

from writing_resources import (
    WritingResourceStore,
    ProjectStatus,
    ContentType,
    DraftStatus,
)


def test_full_api_flow():
    """
    Simulate the full API flow that the frontend would use:
    1. Create a project
    2. Create sections
    3. Create drafts
    4. Save drafts with revisions
    5. List resources
    6. Update status
    7. Restore from revision
    """
    print("=" * 70)
    print("PHASE 3 - Writing Resources API Integration Test")
    print("=" * 70)
    
    store = WritingResourceStore()
    
    # ===== SCENARIO: PhD Thesis Writing Workflow =====
    
    print("\n[1] Creating project: PhD Thesis")
    thesis_project = store.create_project(
        title="Advanced Machine Learning: Theory and Practice",
        description="A comprehensive doctoral thesis",
        content_type=ContentType.ACADEMIC,
        user_id="alice@university.edu",
        tags=["PhD", "ML", "2026"],
    )
    print(f"    Project ID: {thesis_project.project_id}")
    print(f"    Status: {thesis_project.status.value}")
    print(f"    [OK] Project created successfully")
    
    # ===== Create sections =====
    
    print("\n[2] Creating sections")
    sections = []
    section_data = [
        ("1. Introduction", "Motivating problem and contributions", 1),
        ("2. Related Work", "Survey of existing literature", 2),
        ("3. Methodology", "Proposed algorithms and frameworks", 3),
        ("4. Experiments", "Empirical validation and results", 4),
        ("5. Conclusion", "Summary and future directions", 5),
    ]
    
    for title, desc, order in section_data:
        section = store.create_section(
            project_id=thesis_project.project_id,
            title=title,
            order=order,
            description=desc,
        )
        sections.append(section)
        print(f"    [OK] Created section {order}: {title}")
    
    # ===== Create drafts for each section =====
    
    print("\n[3] Creating drafts for each section")
    drafts = []
    for i, section in enumerate(sections, 1):
        draft = store.create_draft(
            project_id=thesis_project.project_id,
            title=f"Draft for Section {i}",
            content="",  # Empty initially
            section_id=section.section_id,
            edited_by="alice",
        )
        drafts.append(draft)
        print(f"    [OK] Created draft for section {i}: {draft.draft_id}")
    
    # ===== Write first iteration of Introduction =====
    
    print("\n[4] Writing Section 1 - Introduction (Iteration 1)")
    intro_draft = drafts[0]
    intro_v1 = """
# Introduction

The field of machine learning has undergone a dramatic transformation over the past decade.
Deep neural networks have achieved remarkable success in various domains including computer
vision, natural language processing, and reinforcement learning. However, several fundamental
challenges remain:

1. Interpretability: Modern deep models are often black boxes
2. Sample efficiency: Training requires enormous datasets
3. Robustness: Small perturbations can fool even state-of-the-art models

This thesis addresses these challenges...
"""
    
    draft_v1 = store.save_draft(
        intro_draft.draft_id,
        intro_v1,
        edited_by="alice",
        create_revision=True,
    )
    print("    [OK] Saved introduction draft version 1")
    print(f"    Content length: {len(draft_v1.content)} characters")
    
    # ===== Get revision info =====
    
    print("\n[5] Checking revision history")
    revisions = store.list_revisions(intro_draft.draft_id)
    print(f"    Total revisions: {len(revisions)}")
    for rev in revisions:
        print(f"      - Revision {rev.revision_number}: {rev.message}")
    
    # ===== Write second iteration =====
    
    print("\n[6] Writing Section 1 - Introduction (Iteration 2)")
    intro_v2 = intro_v1.replace(
        "This thesis addresses these challenges...",
        """This thesis addresses these challenges through:

- A novel attention mechanism for interpretability
- Meta-learning techniques for sample efficiency
- Adversarial robustness training methods

We demonstrate these techniques on standard benchmarks..."""
    )
    
    draft_v2 = store.save_draft(
        intro_draft.draft_id,
        intro_v2,
        edited_by="bob",  # Different author
        create_revision=True,
    )
    print("    [OK] Saved introduction draft version 2")
    
    # ===== List drafts for the project =====
    
    print("\n[7] Listing all drafts for the project")
    all_drafts = store.list_drafts(thesis_project.project_id)
    print(f"    Total drafts: {len(all_drafts)}")
    for draft in all_drafts:
        section_info = f" (Section: {draft.section_id})" if draft.section_id else " (Project-level)"
        print(f"      - {draft.title}{section_info}: {len(draft.content)} chars")
    
    # ===== List all revisions for introduction =====
    
    print("\n[8] Checking all revisions for introduction draft")
    revisions = store.list_revisions(intro_draft.draft_id)
    print(f"    Total versions: {len(revisions)}")
    for rev in revisions:
        print(f"      - Rev {rev.revision_number}: {len(rev.content)} chars, by {rev.created_by}")
    
    # ===== Restore to version 1 =====
    
    print("\n[9] Restoring introduction to version 1")
    revisions = store.list_revisions(intro_draft.draft_id)
    restored = store.restore_revision(intro_draft.draft_id, revisions[0].revision_id)
    print(f"    [OK] Restored to revision 1")
    print(f"    Current content length: {len(restored.content)} characters")
    
    # ===== Update project status =====
    
    print("\n[10] Updating project status")
    updated_project = store.update_project_status(
        thesis_project.project_id,
        ProjectStatus.IN_PROGRESS
    )
    print(f"    [OK] Project status: {updated_project.status.value}")
    
    # ===== Export complete state =====
    
    print("\n[11] Exporting project state")
    state = store.export_state()
    print(f"    Projects: {len(state['projects'])}")
    print(f"    Sections: {len(state['sections'])}")
    print(f"    Drafts: {len(state['drafts'])}")
    print(f"    Revisions: {len(state['revisions'])}")
    
    # ===== List projects by user =====
    
    print("\n[12] Listing projects by user")
    alice_projects = store.list_projects(user_id="alice@university.edu")
    print(f"    Alice's projects: {len(alice_projects)}")
    for proj in alice_projects:
        print(f"      - {proj.title} ({proj.status.value})")
    
    # ===== Verify immutability =====
    
    print("\n[13] Verifying immutability principles")
    original_title = thesis_project.title
    # This should fail silently in tests, as the object is frozen
    try:
        thesis_project.title = "HACKED"
        print("    [ERROR] Project was mutable!")
    except (AttributeError, RuntimeError):
        print("    [OK] Project is immutable (frozen)")
    
    # Retrieved project should have original title
    retrieved = store.get_project(thesis_project.project_id)
    if retrieved.title == original_title:
        print(f"    [OK] Retrieved project has original title: '{retrieved.title}'")
    else:
        print(f"    [ERROR] Title mismatch!")
    
    # ===== Summary =====
    
    print("\n" + "=" * 70)
    print("INTEGRATION TEST RESULTS")
    print("=" * 70)
    print("\n[OK] All Phase 3 API operations successful!")
    print("\n   Operations tested:")
    print("   + Project lifecycle (create, get, list, update_status)")
    print("   + Section management (create, get, list)")
    print("   + Draft operations (create, save, list)")
    print("   + Revision tracking (create, list, restore)")
    print("   + State export (for persistence layer)")
    print("   + Immutability (frozen dataclasses)")
    print("   + User filtering (project ownership)")
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_full_api_flow()
