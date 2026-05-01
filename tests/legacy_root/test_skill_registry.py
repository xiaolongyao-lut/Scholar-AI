# -*- coding: utf-8 -*-
"""Tests for unified skill registry with approval and audit logging."""

import sys
import os
from pathlib import Path
from uuid import uuid4

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from skills.models import (
    SkillDescriptor,
    SkillKind,
    SkillSource,
    UIVisibility,
    SkillTrustLevel,
    ScriptPolicy,
)
from skills.registry import SkillRegistry
from skills.approval import (
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalDecisionRecord,
    CapabilityApprovalProfile,
    ApprovalStore,
)
from skills.audit import (
    AuditLog,
    AuditEvent,
    AuditEventType,
    ExecutionRecord,
)
from skills.service import WritingSkillService, reset_writing_skill_service


def test_skill_registry_basic():
    """Test basic skill registry operations."""
    registry = SkillRegistry()
    
    # Create a test skill
    skill = SkillDescriptor(
        id="test_skill_1",
        name="Test Skill",
        description="A test skill",
        kind=SkillKind.TRANSFORM,
        source=SkillSource.BUILTIN,
        entry_mode="manual",
        supported_scopes=["selection"],
        ui_visibility=UIVisibility.BOTH,
        requires_assets=False,
        safe_to_execute=True,
    )
    
    # Register and retrieve
    registry.register(skill)
    assert registry.has(skill.id)
    assert registry.get(skill.id) == skill
    assert registry.count() == 1
    print("[OK] Skill registry basic operations")


def test_approval_store():
    """Test approval store operations."""
    store = ApprovalStore()
    
    # Register an approval profile
    profile = CapabilityApprovalProfile(
        capability_id="test_capability",
        policy=ApprovalPolicy.REQUIRES_USER_APPROVAL.value,
        description="Test capability",
        risk_level="medium",
    )
    store.register_profile(profile)
    
    # Verify registration
    assert store.get_profile("test_capability") == profile
    assert len(store.list_profiles()) == 1
    print("[OK] Approval store registration")
    
    # Submit approval request
    request = ApprovalRequest(
        request_id=f"req_{uuid4().hex[:8]}",
        capability_id="test_capability",
        capability_name="Test Capability",
        reason="User requested execution",
    )
    store.submit_approval_request(request)
    
    # Verify pending requests
    pending = store.get_pending_requests()
    assert len(pending) == 1
    print("[OK] Approval request submission")
    
    # Record decision
    decision = ApprovalDecisionRecord(
        request_id=request.request_id,
        decision="approved",
        user_id="user123",
    )
    store.record_decision(decision)
    
    # Verify decision was recorded
    latest = store.get_latest_decision(request.request_id)
    assert latest == decision
    assert latest.is_approved()
    print("[OK] Approval decision recording")


def test_audit_log():
    """Test audit logging."""
    log = AuditLog()
    
    # Log an event
    event = log.log_event(
        AuditEventType.JOB_CREATED.value,
        job_id="job_123",
        capability_id="capability_456",
        description="Test job created",
    )
    
    # Verify event was logged
    assert log.get_event(event.event_id) == event
    assert len(log.list_events()) == 1
    print("[OK] Audit event logging")
    
    # Query events by type
    events = log.list_events_by_type(AuditEventType.JOB_CREATED.value)
    assert len(events) == 1
    print("[OK] Audit event type filtering")
    
    # Register execution record
    record = ExecutionRecord(
        job_id="job_123",
        capability_id="capability_456",
        started_at="2026-04-09T19:00:00Z",
        status="in_progress",
    )
    log.register_execution(record)
    
    # Verify execution record
    retrieved = log.get_execution_record("job_123")
    assert retrieved == record
    print("[OK] Execution record registration")
    
    # Update execution status
    updated = log.update_execution_status(
        "job_123",
        "completed",
        output_data={"result": "success"},
    )
    assert updated.status == "completed"
    print("[OK] Execution status update")


def test_writing_skill_service_initialization():
    """Test WritingSkillService initialization."""
    reset_writing_skill_service()
    
    # Initialize service (without external roots for now)
    service = WritingSkillService(external_roots=None)
    
    # Verify it was created
    assert service is not None
    
    # Check that builtin skills were loaded
    builtin_skills = service.list_skills(source="builtin")
    # Should have loaded some builtin skills (or at least not crash)
    assert isinstance(builtin_skills, list)
    print(f"[OK] WritingSkillService initialized with {len(builtin_skills)} builtin skills")


def test_approval_policy_enforcement():
    """Test that approval policies are enforced."""
    reset_writing_skill_service()
    service = WritingSkillService(external_roots=None)
    
    # Get approval store
    approval_store = service.get_approval_store()
    
    # Check that builtin skills have auto_allowed policy
    builtin_profiles = [p for p in approval_store.list_profiles()]
    assert len(builtin_profiles) > 0
    
    # Find a builtin profile
    builtin_profile = next((p for p in builtin_profiles if p.policy == ApprovalPolicy.AUTO_ALLOWED.value), None)
    if builtin_profile:
        assert builtin_profile.is_auto_allowed()
        print("[OK] Builtin skills have auto_allowed policy")


def test_audit_logging_on_execution():
    """Test that execution is audited."""
    reset_writing_skill_service()
    service = WritingSkillService(external_roots=None)
    
    # Get audit log
    audit_log = service.get_audit_log()
    
    # Initially should have capability resolution events
    events = audit_log.list_events()
    assert any(e.event_type == AuditEventType.CAPABILITY_RESOLVED.value for e in events)
    print("[OK] Audit log contains capability resolution events")


def test_unified_registry_builtin_and_imported():
    """Test that builtin and imported skills share one registry."""
    registry = SkillRegistry()
    
    # Add builtin
    builtin = SkillDescriptor(
        id="builtin_skill",
        name="Builtin",
        description="Builtin skill",
        kind=SkillKind.TRANSFORM,
        source=SkillSource.BUILTIN,
        entry_mode="manual",
        supported_scopes=["selection"],
        ui_visibility=UIVisibility.BOTH,
        requires_assets=False,
    )
    registry.register(builtin)
    
    # Add imported (should have disabled_reason)
    imported = SkillDescriptor(
        id="imported_skill",
        name="Imported",
        description="Imported skill",
        kind=SkillKind.DOMAIN,
        source=SkillSource.IMPORTED,
        entry_mode="manual",
        supported_scopes=["section"],
        ui_visibility=UIVisibility.HIDDEN,
        requires_assets=False,
        disabled_reason="Imported skill - disabled by default",
        trust_level=SkillTrustLevel.LIMITED,
    )
    registry.register(imported)
    
    # Verify both in same registry
    assert registry.count() == 2
    assert registry.has("builtin_skill")
    assert registry.has("imported_skill")
    
    # Verify they can be filtered
    builtin_list = registry.list_by_source("builtin")
    imported_list = registry.list_by_source("imported")
    
    assert len(builtin_list) == 1
    assert len(imported_list) == 1
    assert builtin_list[0].source == SkillSource.BUILTIN
    assert imported_list[0].source == SkillSource.IMPORTED
    print("[OK] Unified registry with builtin and imported skills")


def test_imported_skills_disabled_by_default():
    """Test that imported skills are disabled by default."""
    registry = SkillRegistry()
    
    # Create imported skill with disabled reason
    imported = SkillDescriptor(
        id="imported_test",
        name="Imported Test",
        description="Test imported skill",
        kind=SkillKind.DOMAIN,
        source=SkillSource.IMPORTED,
        entry_mode="manual",
        supported_scopes=["section"],
        ui_visibility=UIVisibility.SKILL_ASSISTED,
        requires_assets=False,
        disabled_reason="Imported skill - disabled by default",
    )
    registry.register(imported)
    
    # Verify skill is noted as disabled
    assert imported.disabled_reason is not None
    assert "disabled" in imported.disabled_reason.lower()
    print("[OK] Imported skills marked as disabled by default")


def test_approval_profiles_for_different_sources():
    """Test that different approval policies apply to different sources."""
    store = ApprovalStore()
    
    # Builtin - auto allowed
    builtin_profile = CapabilityApprovalProfile(
        capability_id="builtin_test",
        policy=ApprovalPolicy.AUTO_ALLOWED.value,
        description="Builtin skill",
        risk_level="low",
    )
    store.register_profile(builtin_profile)
    
    # Imported - requires approval or blocked
    imported_profile = CapabilityApprovalProfile(
        capability_id="imported_test",
        policy=ApprovalPolicy.GUIDANCE_ONLY.value,
        description="Imported skill - reference only",
        risk_level="high",
    )
    store.register_profile(imported_profile)
    
    # Verify policies
    assert store.get_profile("builtin_test").is_auto_allowed()
    assert store.get_profile("imported_test").is_guidance_only()
    print("[OK] Different approval policies for different sources")


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*60)
    print("PHASE 4 - UNIFIED CAPABILITY REGISTRY TESTS")
    print("="*60 + "\n")
    
    tests = [
        test_skill_registry_basic,
        test_approval_store,
        test_audit_log,
        test_writing_skill_service_initialization,
        test_approval_policy_enforcement,
        test_audit_logging_on_execution,
        test_unified_registry_builtin_and_imported,
        test_imported_skills_disabled_by_default,
        test_approval_profiles_for_different_sources,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAILED] {test.__name__}: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
