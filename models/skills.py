"""
Skills-related Pydantic models for REST API.

Includes models for skill descriptors, actions, and compatibility.
"""

from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field


class SkillCompatibilityPayload(BaseModel):
    """Compatibility payload for frontend action/skill bridges."""

    fallback_action_id: Optional[str] = None
    min_app_version: Optional[str] = None
    max_app_version: Optional[str] = None


class ScriptPolicyPayload(BaseModel):
    """Script safety payload for imported skills."""

    has_scripts: bool
    safe_to_execute: bool
    disabled_reason: Optional[str] = None


class SkillDescriptorPayload(BaseModel):
    """Typed skill response payload."""

    id: str
    name: str
    description: str
    kind: str
    source: str
    entry_mode: str
    supported_scopes: List[str]
    ui_visibility: str
    requires_assets: bool
    prompt_template_refs: List[str]
    script_refs: List[str]
    reference_refs: List[str]
    tags: List[str]
    version: str = "1.0.0"
    display_group: str = "general"
    experimental: bool = False
    safe_to_execute: bool = False
    capability_refs: List[str] = Field(default_factory=list)
    default_parameters: Dict[str, Any] = Field(default_factory=dict)
    import_origin: Optional[str] = None
    summary_hint: Optional[str] = None
    compatibility: SkillCompatibilityPayload
    disabled_reason: Optional[str] = None
    script_policy: ScriptPolicyPayload
    trust_level: str


class SkillPackPayload(BaseModel):
    """Skill pack payload for advanced UI grouping."""

    id: str
    name: str
    description: str
    skillIds: List[str]


class CapabilityPayload(BaseModel):
    """Capability payload advertised to the frontend."""

    id: str
    name: str
    description: str


class WritingActionPayload(BaseModel):
    """Legacy-compatible writing action payload."""

    id: str
    nameZh: str
    nameEn: str
    descriptionZh: str
    descriptionEn: str
    category: str
    supportedScopes: List[str]
    icon: str
    skillId: str


class RunActionRequest(BaseModel):
    """Request payload for action execution through the skill runtime."""

    action_id: str
    input_text: str = ""
    scope: Optional[str] = None  # 'selection', 'section', 'full_draft'
    output_mode: Optional[str] = None  # 'latex', 'word_safe', 'plain'


class RunActionAcceptedPayload(BaseModel):
    """Accepted job payload for legacy action execution."""

    jobId: str
    status: str
    kind: str = "writing_transform"
    message: str = "accepted"
