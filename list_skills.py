#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出所有已注册的skills。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from skills.registry import SkillRegistry
from skills.importers.ui_ux_pro_max_wrapper import get_ui_ux_pro_max_descriptor


def list_skills():
    """列出系统中所有已注册的skills."""
    registry = SkillRegistry()
    descriptor = get_ui_ux_pro_max_descriptor()
    registry.register(descriptor)

    print("\n" + "="*70)
    print("REGISTERED SKILLS")
    print("="*70)

    all_skills = registry.list_all()

    if not all_skills:
        print("\n⚠ No skills registered")
    else:
        for i, skill in enumerate(all_skills, 1):
            print(f"\n{i}. 📦 {skill.name}")
            print(f"   ID: {skill.id}")
            print(f"   Version: {skill.version}")
            print(f"   Kind: {skill.kind.value}")
            print(f"   Source: {skill.source.value}")
            print(f"   Safe to execute: {skill.safe_to_execute}")
            print(f"   UI Visibility: {skill.ui_visibility.value}")
            if skill.tags:
                tags_display = ", ".join(skill.tags[:4])
                if len(skill.tags) > 4:
                    tags_display += "..."
                print(f"   Tags: {tags_display}")
            if skill.capability_refs:
                print(f"   Capabilities: {', '.join(skill.capability_refs)}")

    print(f"\n{'='*70}")
    print(f"Total skills: {len(all_skills)}")
    print("="*70 + "\n")


if __name__ == "__main__":
    list_skills()
