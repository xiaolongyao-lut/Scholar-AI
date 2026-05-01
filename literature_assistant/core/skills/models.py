# -*- coding: utf-8 -*-
"""Skills data models - Typed descriptors and metadata for writing skills."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class SkillKind(str, Enum):
    """Classification of skill purpose."""
    TRANSFORM = "transform"      # Text transformation (rewrite, translate, etc)
    VALIDATOR = "validator"      # Text validation and checking
    WORKFLOW = "workflow"        # Multi-step workflow coordinator
    DOMAIN = "domain"            # Domain-specific expertise
    STYLE = "style"              # Styling and formatting


class SkillSource(str, Enum):
    """Origin of skill definition."""
    BUILTIN = "builtin"          # Shipped with application
    IMPORTED = "imported"        # User-imported external skill
    EXPERIMENTAL = "experimental"  # Experimental/unstable


class SkillTrustLevel(str, Enum):
    """Security trust classification."""
    TRUSTED = "trusted"          # Safe to execute
    LIMITED = "limited"          # Limited resource access
    UNTRUSTED = "untrusted"      # Potentially unsafe, scripts disabled


class UIVisibility(str, Enum):
    """Where skill appears in frontend UI."""
    SIMPLE_PROMPT = "simple_prompt"    # Simple prompt mode only
    SKILL_ASSISTED = "skill_assisted"  # Skill-assisted mode only
    BOTH = "both"                      # Both modes
    HIDDEN = "hidden"                  # Admin/developer only


@dataclass(frozen=True)
class SkillCompatibility:
    """Compatibility mapping for legacy action systems."""
    fallback_action_id: str | None = None
    min_app_version: str | None = None
    max_app_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)


@dataclass(frozen=True)
class ScriptPolicy:
    """Security policy for skill scripts."""
    has_scripts: bool
    safe_to_execute: bool
    disabled_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)


@dataclass(frozen=True)
class SkillDescriptor:
    """
    Immutable metadata descriptor for a writing skill.
    
    Fully describes a skill's capabilities, safety profile, and UI integration.
    Used for skill discovery, validation, and UI presentation.
    """
    id: str
    name: str
    description: str
    kind: SkillKind
    source: SkillSource
    entry_mode: str  # 'manual', 'assistant', 'hidden'
    supported_scopes: list[str]  # ['selection', 'section', 'full_draft']
    ui_visibility: UIVisibility
    requires_assets: bool
    prompt_template_refs: list[str] = field(default_factory=list)
    script_refs: list[str] = field(default_factory=list)
    reference_refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    display_group: str = "general"
    experimental: bool = False
    safe_to_execute: bool = False
    capability_refs: list[str] = field(default_factory=list)
    default_parameters: dict[str, Any] = field(default_factory=dict)
    import_origin: str | None = None
    summary_hint: str | None = None
    compatibility: SkillCompatibility = field(default_factory=SkillCompatibility)
    disabled_reason: str | None = None
    script_policy: ScriptPolicy = field(default_factory=lambda: ScriptPolicy(False, False))
    trust_level: SkillTrustLevel = SkillTrustLevel.TRUSTED

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API responses."""
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "kind": self.kind.value,
            "source": self.source.value,
            "entry_mode": self.entry_mode,
            "supported_scopes": self.supported_scopes,
            "ui_visibility": self.ui_visibility.value,
            "requires_assets": self.requires_assets,
            "prompt_template_refs": self.prompt_template_refs,
            "script_refs": self.script_refs,
            "reference_refs": self.reference_refs,
            "tags": self.tags,
            "version": self.version,
            "display_group": self.display_group,
            "experimental": self.experimental,
            "safe_to_execute": self.safe_to_execute,
            "capability_refs": self.capability_refs,
            "default_parameters": self.default_parameters,
            "import_origin": self.import_origin,
            "summary_hint": self.summary_hint,
            "compatibility": self.compatibility.to_dict(),
            "disabled_reason": self.disabled_reason,
            "script_policy": self.script_policy.to_dict(),
            "trust_level": self.trust_level.value,
        }
        return data


@dataclass
class SkillPack:
    """Grouped collection of skills for UI presentation."""
    id: str
    name: str
    description: str
    skill_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "skillIds": self.skill_ids,
        }


@dataclass
class Capability:
    """Advertised capability provided to frontend."""
    id: str
    name: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)
