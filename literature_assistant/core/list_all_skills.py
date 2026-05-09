#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出所有已注册的 skills。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from skills.registry import SkillRegistry
from skills.importers.ui_ux_pro_max_wrapper import get_ui_ux_pro_max_descriptor
from skills.importers.skill_flow_wrapper import get_skill_flow_descriptor


def list_all_skills():
    """列出系统中所有已注册的 skills."""
    registry = SkillRegistry()
    registry.register(get_ui_ux_pro_max_descriptor())
    registry.register(get_skill_flow_descriptor())

    print("\n" + "="*70)
    print("ALL REGISTERED SKILLS IN VS CODE")
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
                tags_display = ", ".join(skill.tags[:3])
                if len(skill.tags) > 3:
                    tags_display += "..."
                print(f"   Tags: {tags_display}")
            if skill.capability_refs:
                caps_display = ", ".join(skill.capability_refs[:2])
                if len(skill.capability_refs) > 2:
                    caps_display += "..."
                print(f"   Capabilities: {caps_display}")

    print(f"\n{'='*70}")
    print(f"Total skills: {len(all_skills)}")
    print("="*70 + "\n")


if __name__ == "__main__":
    list_all_skills()
