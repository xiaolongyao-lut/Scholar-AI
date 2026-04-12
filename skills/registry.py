# -*- coding: utf-8 -*-
"""Skills registry - In-memory storage and querying of skill descriptors."""

from __future__ import annotations

from .models import SkillDescriptor, UIVisibility


class SkillRegistry:
    """
    In-memory registry for skill descriptors.
    
    Provides O(1) lookup by ID, filtered queries by mode/kind/source,
    and safe concurrent access patterns.
    """

    def __init__(self):
        """Initialize empty registry."""
        self._skills: dict[str, SkillDescriptor] = {}

    def register(self, descriptor: SkillDescriptor) -> None:
        """Register a single skill descriptor."""
        if not isinstance(descriptor, SkillDescriptor):
            raise TypeError(f"Expected SkillDescriptor, got {type(descriptor)}")
        self._skills[descriptor.id] = descriptor

    def register_many(self, descriptors: list[SkillDescriptor]) -> None:
        """Register multiple skill descriptors."""
        for desc in descriptors:
            self.register(desc)

    def get(self, skill_id: str) -> SkillDescriptor | None:
        """Get a skill descriptor by ID."""
        return self._skills.get(skill_id)

    def has(self, skill_id: str) -> bool:
        """Check if a skill exists."""
        return skill_id in self._skills

    def list_all(self) -> list[SkillDescriptor]:
        """Return all registered skills."""
        return list(self._skills.values())

    def list_by_kind(self, kind_str: str) -> list[SkillDescriptor]:
        """Filter skills by kind."""
        kind_lower = kind_str.lower()
        return [s for s in self._skills.values() if s.kind.value == kind_lower]

    def list_by_source(self, source_str: str) -> list[SkillDescriptor]:
        """Filter skills by source."""
        source_lower = source_str.lower()
        return [s for s in self._skills.values() if s.source.value == source_lower]

    def list_by_ui_mode(self, ui_mode: str) -> list[SkillDescriptor]:
        """Filter skills by UI visibility mode."""
        if ui_mode == "simple_prompt":
            return [
                s for s in self._skills.values()
                if s.ui_visibility in (UIVisibility.SIMPLE_PROMPT, UIVisibility.BOTH)
                and not s.disabled_reason
            ]
        elif ui_mode == "skill_assisted":
            return [
                s for s in self._skills.values()
                if s.ui_visibility in (UIVisibility.SKILL_ASSISTED, UIVisibility.BOTH)
                and not s.disabled_reason
            ]
        else:
            # Return all non-hidden
            return [s for s in self._skills.values() if s.ui_visibility != UIVisibility.HIDDEN]

    def count(self) -> int:
        """Return total registered skills."""
        return len(self._skills)

    def clear(self) -> None:
        """Clear all skills (for testing)."""
        self._skills.clear()
