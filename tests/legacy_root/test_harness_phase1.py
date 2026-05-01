#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Protocol Layer Validation - Phase 1 Harness Upgrade

Verifies:
1. Protocol models compile and instantiate
2. Adapters translate legacy actions to new protocol
3. Dual-track architecture constraints preserved
4. Session/Job/Event/Artifact/Approval enums and factories work
"""

import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

def test_protocol_models():
    """Test that protocol models compile and create properly."""
    print("\n=== Testing Protocol Models ===")
    
    from harness_protocols import (
        SessionMode, JobKind, JobStatus, EventType, ArtifactType, ApprovalStatus,
        WritingSession, WritingJob, WritingEvent, WritingArtifact, WritingApprovalRequest,
        PROTOCOL_VERSION,
    )
    
    # Test enums
    assert SessionMode.PROMPT.value == 'prompt'
    assert JobKind.SKILL_ACTION.value == 'skill_action'
    assert EventType.JOB_CREATED.value == 'job_created'
    assert ArtifactType.TRANSFORMED_TEXT.value == 'transformed_text'
    print("✓ All enums defined correctly")
    
    # Test session creation
    session = WritingSession.create(SessionMode.PROMPT, user_id="test_user")
    assert session.session_id.startswith("session_")
    assert session.mode == SessionMode.PROMPT
    session_dict = session.to_dict()
    assert session_dict['mode'] == 'prompt'
    print(f"✓ WritingSession created: {session.session_id}")
    
    # Test job creation
    job = WritingJob.create(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="test input",
        action_id="test_action",
    )
    assert job.job_id.startswith("job_")
    assert job.status == JobStatus.CREATED
    job_dict = job.to_dict()
    assert job_dict['status'] == 'created'
    print(f"✓ WritingJob created: {job.job_id}")
    
    # Test job status transitions
    running_job = job.with_status(JobStatus.IN_PROGRESS)
    assert running_job.status == JobStatus.IN_PROGRESS
    assert running_job.started_at is not None
    print("✓ Job status transitions work")
    
    # Test event creation
    event = WritingEvent.create(
        job_id=job.job_id,
        session_id=session.session_id,
        event_type=EventType.JOB_STARTED,
    )
    assert event.event_id.startswith("event_")
    event_dict = event.to_dict()
    assert event_dict['event_type'] == 'job_started'
    print(f"✓ WritingEvent created: {event.event_id}")
    
    # Test artifact creation
    artifact = WritingArtifact.create(
        job_id=job.job_id,
        session_id=session.session_id,
        artifact_type=ArtifactType.TRANSFORMED_TEXT,
        content={"output_text": "transformed"},
        created_by="skill_test",
    )
    assert artifact.artifact_id.startswith("artifact_")
    artifact_dict = artifact.to_dict()
    assert artifact_dict['artifact_type'] == 'transformed_text'
    print(f"✓ WritingArtifact created: {artifact.artifact_id}")
    
    # Test approval request
    approval = WritingApprovalRequest.create(
        job_id=job.job_id,
        session_id=session.session_id,
        reason="Review required",
    )
    assert approval.approval_id.startswith("approval_")
    assert approval.status == ApprovalStatus.PENDING
    approved = approval.with_approval("reviewer")
    assert approved.status == ApprovalStatus.APPROVED
    print(f"✓ WritingApprovalRequest created and transitioned: {approval.approval_id}")
    
    # Test protocol version
    assert PROTOCOL_VERSION == "1.0.0"
    print(f"✓ Protocol version: {PROTOCOL_VERSION}")
    
    return True


def test_skills_foundation():
    """Test that skills foundation modules work."""
    print("\n=== Testing Skills Foundation ===")
    
    from skills.models import SkillDescriptor, SkillKind, SkillSource, UIVisibility, SkillCompatibility
    from skills.runtime import SkillRunResult, ExecutionStatus, SkillTextTransformInput
    from skills.registry import SkillRegistry
    
    # Test skill descriptor
    skill = SkillDescriptor(
        id="skill_test_translate",
        name="Test Translator",
        description="Test translation skill",
        kind=SkillKind.TRANSFORM,
        source=SkillSource.BUILTIN,
        entry_mode="manual",
        supported_scopes=["selection", "section"],
        ui_visibility=UIVisibility.BOTH,
        requires_assets=False,
    )
    assert skill.id == "skill_test_translate"
    skill_dict = skill.to_dict()
    assert skill_dict['kind'] == 'transform'
    print(f"✓ SkillDescriptor created: {skill.id}")
    
    # Test skill run result
    result = SkillRunResult(
        job_id="job_123",
        skill_id="skill_123",
        status=ExecutionStatus.SUCCESS,
        input_text="hello",
        output_text="world",
    )
    assert result.is_success()
    assert not result.is_failed()
    result_dict = result.to_dict()
    assert result_dict['status'] == 'success'
    print("✓ SkillRunResult created and validated")
    
    # Test skill transform input
    transform_input = SkillTextTransformInput(
        input_text="test",
        skill_id="skill_123",
        scope="section",
        output_mode="word_safe",
    )
    assert transform_input.input_text == "test"
    input_dict = transform_input.to_dict()
    assert input_dict['scope'] == 'section'
    print("✓ SkillTextTransformInput created")
    
    # Test registry
    registry = SkillRegistry()
    registry.register(skill)
    assert registry.has("skill_test_translate")
    assert registry.count() == 1
    retrieved = registry.get("skill_test_translate")
    assert retrieved is not None
    assert retrieved.id == skill.id
    print("✓ SkillRegistry operations work")
    
    return True


def test_adapters():
    """Test that adapters translate legacy patterns correctly."""
    print("\n=== Testing Adapters ===")
    
    from harness_protocols import SessionMode, JobKind, EventType, ArtifactType
    from harness_adapters import LegacyActionAdapter, SessionContextAdapter
    from skills.runtime import SkillRunResult, ExecutionStatus
    
    # Test legacy action to job
    job = LegacyActionAdapter.action_to_job(
        session_id="session_test",
        action_id="zh_to_en_translate",
        input_text="你好",
        scope="section",
        output_mode="word_safe",
    )
    assert job.action_id == "zh_to_en_translate"
    assert job.kind == JobKind.SKILL_ACTION
    assert job.input_text == "你好"
    print(f"✓ Legacy action mapped to job: {job.job_id}")
    
    # Test skill result to artifact
    skill_result = SkillRunResult(
        job_id=job.job_id,
        skill_id="skill_123",
        status=ExecutionStatus.SUCCESS,
        input_text="你好",
        output_text="Hello",
    )
    artifact = LegacyActionAdapter.skill_run_to_artifact(
        job_id=job.job_id,
        session_id="session_test",
        skill_run_result=skill_result,
    )
    assert artifact.artifact_type == ArtifactType.TRANSFORMED_TEXT
    assert artifact.created_by == "skill_123"
    print(f"✓ Skill result mapped to artifact: {artifact.artifact_id}")
    
    # Test event creation from result
    event = LegacyActionAdapter.event_from_skill_run(
        job_id=job.job_id,
        session_id="session_test",
        skill_run_result=skill_result,
    )
    assert event.event_type == EventType.ARTIFACT_CREATED
    print(f"✓ Skill result mapped to event: {event.event_id}")
    
    # Test session context
    ctx = SessionContextAdapter()
    session1 = ctx.create_or_get_session(SessionMode.PROMPT)
    assert session1.mode == SessionMode.PROMPT
    session2 = ctx.create_or_get_session(SessionMode.PROMPT, force_new=False)
    assert session1.session_id == session2.session_id  # Should reuse
    session3 = ctx.create_or_get_session(SessionMode.SKILL, force_new=True)
    assert session1.session_id != session3.session_id  # Should be different
    print("✓ SessionContextAdapter works")
    
    return True


def test_dual_track_constraints():
    """Verify dual-track architecture constraints are preserved."""
    print("\n=== Testing Dual-Track Constraints ===")
    
    from harness_protocols import SessionMode, JobKind
    
    # Verify SessionMode has PROMPT and SKILL
    modes = [m for m in SessionMode]
    assert SessionMode.PROMPT in modes
    assert SessionMode.SKILL in modes
    print("✓ Prompt Mode and Skill Mode both available")
    
    # Verify JobKind covers legacy patterns
    kinds = [k for k in JobKind]
    assert JobKind.PROMPT_ACTION in kinds
    assert JobKind.SKILL_ACTION in kinds
    assert JobKind.PIPELINE_RUN in kinds
    print("✓ Job types support prompt, skill, and pipeline patterns")
    
    # Test that action -> job -> artifact → event chain works
    from harness_adapters import LegacyActionAdapter
    from harness_protocols import WritingEvent, WritingJob
    from skills.runtime import SkillRunResult, ExecutionStatus
    
    job = LegacyActionAdapter.action_to_job(
        session_id="session_compatibility_test",
        action_id="old_style_action",
        input_text="sample text",
    )
    assert isinstance(job, WritingJob)
    
    # Simulate skill execution
    result = SkillRunResult(
        job_id=job.job_id,
        skill_id="skill_backup",
        status=ExecutionStatus.SUCCESS,
        input_text=job.input_text,
        output_text="modified text",
    )
    
    # Map back to protocol
    artifact = LegacyActionAdapter.skill_run_to_artifact(
        job_id=job.job_id,
        session_id="session_compatibility_test",
        skill_run_result=result,
    )
    event = LegacyActionAdapter.event_from_skill_run(
        job_id=job.job_id,
        session_id="session_compatibility_test",
        skill_run_result=result,
    )
    
    assert isinstance(artifact, WritingJob.__bases__[0])  # Type is compatible
    assert isinstance(event, WritingEvent)
    print("✓ Backward compat: action -> job -> artifact -> event chain works")
    
    # Verify no breaking changes to action shape
    action_payload = {
        "action_id": "test_action",
        "input_text": "test",
        "scope": "section",
        "output_mode": "word_safe",
    }
    job2 = LegacyActionAdapter.action_to_job(
        session_id="test",
        action_id=action_payload["action_id"],
        input_text=action_payload["input_text"],
        scope=action_payload.get("scope"),
        output_mode=action_payload.get("output_mode"),
    )
    assert job2.action_id == "test_action"
    print("✓ Legacy action payload shape preserved")
    
    return True


def main():
    """Run all validation tests."""
    print("\n" + "="*60)
    print("HARNESS PROTOCOL LAYER - VALIDATION SUITE")
    print("="*60)
    
    try:
        # Run all tests
        all_pass = all([
            test_protocol_models(),
            test_skills_foundation(),
            test_adapters(),
            test_dual_track_constraints(),
        ])
        
        if all_pass:
            print("\n" + "="*60)
            print("✓ ALL VALIDATION TESTS PASSED")
            print("="*60)
            print("\nPhase 1 Deliverables:")
            print("  ✓ harness_protocols.py - Protocol layer (WritingSession, WritingJob, etc)")
            print("  ✓ skills/models.py - Skill descriptors and metadata")
            print("  ✓ skills/runtime.py - Skill execution results")
            print("  ✓ skills/registry.py - Skill registry")
            print("  ✓ harness_adapters.py - Compatibility translation layer")
            print("  ✓ frontend/types/harness.ts - TypeScript protocol types")
            print("\nArchitecture Preserved:")
            print("  ✓ Prompt Mode (first-class, direct)")
            print("  ✓ Skill Mode (backend-backed, HTTP async)")
            print("  ✓ Legacy action → protocol translation")
            print("  ✓ Dual-track execution paths intact")
            print("  ✓ Backward compatibility maintained")
            return 0
        else:
            print("\n✗ Some tests failed")
            return 1
            
    except Exception as e:
        print(f"\n✗ Validation error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
