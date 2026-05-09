#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test UI/UX Pro Max skill integration with writing system."""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from harness_protocols import WritingJob, EventType, SessionMode, JobKind
from harness_adapters import SessionContextAdapter
from skills.registry import SkillRegistry
from skills.importers.ui_ux_pro_max_wrapper import (
    get_ui_ux_pro_max_descriptor,
    run_ui_ux_pro_max_transform,
)


def test_ui_ux_pro_max_integration():
    """Test UI/UX Pro Max skill integration."""
    print("\n" + "="*70)
    print("TEST: UI/UX Pro Max Skill Integration")
    print("="*70)
    
    tests_passed = 0
    tests_total = 0
    
    # Test 1: Registry lookup
    tests_total += 1
    try:
        registry = SkillRegistry()
        descriptor = get_ui_ux_pro_max_descriptor()
        registry.register(descriptor)
        
        found = registry.get(descriptor.id)
        assert found is not None, "Skill not found in registry"
        assert found.name == "UI/UX Pro Max", "Wrong skill name"
        assert found.version == "2.5.0", "Wrong version"
        print(f"✓ Test 1: Registry lookup - PASSED")
        tests_passed += 1
    except (AssertionError, KeyError) as e:
        print(f"✗ Test 1: Registry lookup - FAILED: {e}")
    
    # Test 2: Skill descriptor validation
    tests_total += 1
    try:
        descriptor = get_ui_ux_pro_max_descriptor()
        assert descriptor.id == "skill_ui_ux_pro_max", "Wrong ID"
        assert descriptor.safe_to_execute is True, "Not safe to execute"
        assert descriptor.kind.value == "domain", "Wrong kind"
        assert len(descriptor.capability_refs) == 3, "Missing capabilities"
        assert len(descriptor.tags) >= 8, "Missing tags"
        print(f"✓ Test 2: Descriptor validation - PASSED")
        tests_passed += 1
    except (AssertionError, AttributeError) as e:
        print(f"✗ Test 2: Descriptor validation - FAILED: {e}")
    
    # Test 3: Session context creation
    tests_total += 1
    try:
        adapter = SessionContextAdapter()
        session = adapter.create_or_get_session(SessionMode.SKILL)
        assert session is not None, "Session not created"
        assert session.mode == SessionMode.SKILL, "Wrong session mode"
        assert hasattr(session, 'session_id'), "Missing session_id"
        print(f"✓ Test 3: Session context - PASSED")
        tests_passed += 1
    except (AssertionError, AttributeError) as e:
        print(f"✗ Test 3: Session context - FAILED: {e}")
    
    # Test 4: Job creation for skill
    tests_total += 1
    try:
        session = SessionContextAdapter().create_or_get_session(SessionMode.SKILL)
        job = WritingJob.create(
            session_id=session.session_id,
            kind=JobKind.SKILL_ACTION,
            skill_id="skill_ui_ux_pro_max",
            input_text="E-commerce platform for luxury goods",
        )
        assert job is not None, "Job not created"
        assert job.job_id is not None, "Missing job_id"
        assert job.status.value == "created", f"Wrong status: {job.status.value}"
        print(f"✓ Test 4: Skill job creation - PASSED")
        tests_passed += 1
    except (AssertionError, AttributeError, ValueError) as e:
        print(f"✗ Test 4: Skill job creation - FAILED: {e}")
    
    # Test 5: Skill execution
    tests_total += 1
    try:
        import asyncio
        result = asyncio.run(
            run_ui_ux_pro_max_transform(
                "Mobile app for social networking",
                {"platform": "copilot", "include_reasoning": True},
            )
        )
        assert result is not None, "No result returned"
        assert len(result) > 0, "Empty result"
        result_obj = json.loads(result)
        assert isinstance(result_obj, dict), "Result is not a dict"
        print(f"✓ Test 5: Skill execution - PASSED")
        tests_passed += 1
    except (AssertionError, json.JSONDecodeError, OSError) as e:
        print(f"✗ Test 5: Skill execution - FAILED: {e}")
    
    # Test 6: UI mode filtering
    tests_total += 1
    try:
        registry = SkillRegistry()
        descriptor = get_ui_ux_pro_max_descriptor()
        registry.register(descriptor)
        
        # Should be visible in skill_assisted mode
        skill_assisted_skills = registry.list_by_ui_mode("skill_assisted")
        assert any(
            s.id == descriptor.id for s in skill_assisted_skills
        ), "Skill not in skill_assisted mode"
        print(f"✓ Test 6: UI mode filtering - PASSED")
        tests_passed += 1
    except (AssertionError, AttributeError) as e:
        print(f"✗ Test 6: UI mode filtering - FAILED: {e}")
    
    # Results
    print("\n" + "-"*70)
    print(f"RESULTS: {tests_passed}/{tests_total} tests passed")
    print("-"*70)
    
    return tests_passed == tests_total


if __name__ == "__main__":
    try:
        success = test_ui_ux_pro_max_integration()
        sys.exit(0 if success else 1)
    except (OSError, ValueError, KeyError, RuntimeError) as e:
        print(f"\n✗ Test execution error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
