#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VS Code Skill Loader - Load and register UI/UX Pro Max skill.

This script can be run to automatically register external skills
in VS Code and integrate them with the writing system.
"""

import sys
import json
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

from harness_protocols import SessionMode
from harness_adapters import SessionContextAdapter
from skills.registry import SkillRegistry
from skills.importers.ui_ux_pro_max_wrapper import get_ui_ux_pro_max_descriptor


def register_ui_ux_pro_max_in_vscode():
    """
    Register UI/UX Pro Max skill for VS Code integration.
    
    This function:
    1. Creates a writing session
    2. Instantiates the skill registry
    3. Registers the UI/UX Pro Max skill
    4. Outputs registration confirmation
    """
    print("\n" + "="*70)
    print("VS CODE SKILL LOADER - UI/UX Pro Max Integration")
    print("="*70)
    
    # Create session context
    session_ctx = SessionContextAdapter()
    session = session_ctx.create_or_get_session(SessionMode.SKILL)
    print(f"\n✓ Created writing session: {session.session_id}")
    print(f"  Mode: {session.mode.value}")
    
    # Initialize skill registry
    registry = SkillRegistry()
    print("\n✓ Initialized skill registry")
    
    # Get UI/UX Pro Max descriptor
    descriptor = get_ui_ux_pro_max_descriptor()
    print("\n✓ Loaded skill descriptor:")
    print(f"  ID: {descriptor.id}")
    print(f"  Name: {descriptor.name}")
    print(f"  Version: {descriptor.version}")
    print(f"  Source: {descriptor.source.value}")
    print(f"  Kind: {descriptor.kind.value}")
    
    # Register skill
    registry.register(descriptor)
    print("\n✓ Skill registered in registry")
    print(f"  Total skills in registry: {registry.count()}")
    
    # Verify registration
    retrieved = registry.get(descriptor.id)
    if retrieved:
        print("\n✓ Verification successful - skill accessible by ID")
        print(f"  UI Visibility: {retrieved.ui_visibility.value}")
        print(f"  Safe to execute: {retrieved.safe_to_execute}")
        print(f"  Trust level: {retrieved.trust_level.value}")
    else:
        print("\n✗ Verification failed - skill not found")
        return False
    
    # Output registration config
    config = {
        "session_id": session.session_id,
        "skill_id": descriptor.id,
        "skill_name": descriptor.name,
        "version": descriptor.version,
        "status": "registered",
        "vscode_integration": {
            "command": f"writing.skill.execute.{descriptor.id}",
            "title": f"Execute {descriptor.name}",
            "keybinding": "ctrl+alt+u",
            "when": "editorTextFocus",
        },
        "capabilities": descriptor.capability_refs,
        "supported_scopes": descriptor.supported_scopes,
    }
    
    print("\n" + "-"*70)
    print("VS CODE INTEGRATION CONFIG")
    print("-"*70)
    print(json.dumps(config, indent=2, ensure_ascii=False))
    
    print("\n" + "="*70)
    print("✓ UI/UX Pro Max Skill Ready for VS Code")
    print("="*70)
    print("\nNext steps:")
    print("1. The skill is now available in the writing system")
    print("2. Use command: 'writing.skill.execute.skill_ui_ux_pro_max'")
    print("3. Or access from: Skills → Design → UI/UX Pro Max")
    print("\nFeatures:")
    print("- 67 UI styles and design systems")
    print("- 161 color palettes")
    print("- 57 font pairings")
    print("- 99 UX guidelines")
    print("- 25+ chart types\n")
    
    return True


if __name__ == "__main__":
    try:
        success = register_ui_ux_pro_max_in_vscode()
        sys.exit(0 if success else 1)
    except (OSError, ValueError, KeyError) as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
