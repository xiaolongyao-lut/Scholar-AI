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


class SkillSecurityAssessmentPayload(BaseModel):
    """Machine-readable Skill safety assessment for UI and audit gates."""

    skill_id: str
    source: str
    risk_level: str
    runtime_gate: str
    runtime_executable: bool
    enable_requires_approval: bool
    high_risk_flags: List[str] = Field(default_factory=list)
    denied_operations: List[str] = Field(default_factory=list)
    allowed_operations: List[str] = Field(default_factory=list)
    required_sandbox_controls: List[str] = Field(default_factory=list)
    approval_reason: Optional[str] = None
    block_reason: Optional[str] = None


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


class ImportUserSkillRequest(BaseModel):
    """Request to import a local user skill directory or zip package into the managed root."""

    source_path: str
    managed_root: Optional[str] = None
    origin: str = "user_import"


class ImportUserSkillManifestPayload(BaseModel):
    """Minimal manifest summary returned after importing a user skill."""

    id: str
    name: str
    version: str
    kind: str
    high_risk_flags: List[str] = Field(default_factory=list)


class ImportUserSkillResponse(BaseModel):
    """Result of importing a user skill package."""

    success: bool
    skill_id: str = ""
    installed_path: str = ""
    content_hash: str = ""
    origin: str = ""
    installed_at: str = ""
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    manifest: Optional[ImportUserSkillManifestPayload] = None


class SkillToggleResponse(BaseModel):
    """Response returned after enabling or disabling a user skill."""

    skill_id: str
    enabled: bool
    reason: Optional[str] = None


class SkillTestRunResponse(BaseModel):
    """Structured result returned by user skill test-run execution."""

    job_id: str
    skill_id: str
    status: str
    input_text: str
    output_text: str = ""
    timestamp: str
    execution_time_ms: int = 0
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    structured_output: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    audit_id: Optional[str] = None


class SkillApprovalRequestCreate(BaseModel):
    """Request body for creating a persistent skill approval request."""

    capability_id: str
    capability_name: str
    reason: str
    context: Dict[str, Any] = Field(default_factory=dict)


class SkillApprovalRequestPayload(BaseModel):
    """Persistent approval request payload returned by the Skills API."""

    request_id: str
    capability_id: str
    capability_name: str
    reason: str
    timestamp: str
    context: Dict[str, Any] = Field(default_factory=dict)


class SkillApprovalDecisionCreate(BaseModel):
    """Request body for recording a user decision on an approval request."""

    decision: str
    user_id: Optional[str] = None
    reason: Optional[str] = None


class SkillApprovalDecisionPayload(BaseModel):
    """Persistent approval decision payload returned by the Skills API."""

    request_id: str
    decision: str
    user_id: Optional[str] = None
    timestamp: str
    reason: Optional[str] = None


class SkillApprovalDetailPayload(BaseModel):
    """Approval request with its latest decision and decision history."""

    request: SkillApprovalRequestPayload
    latest_decision: Optional[SkillApprovalDecisionPayload] = None
    decisions: List[SkillApprovalDecisionPayload] = Field(default_factory=list)


class SkillUninstallResponse(BaseModel):
    """Response returned after uninstalling a managed user skill."""

    skill_id: str
    uninstalled: bool
    dry_run: bool = False
    backup_path: Optional[str] = None
    removed_path: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class SkillRollbackRequest(BaseModel):
    """Request body for restoring a managed user skill from a rollback snapshot."""

    backup_path: Optional[str] = None


class SkillRollbackResponse(BaseModel):
    """Response returned after restoring a managed user skill snapshot."""

    skill_id: str
    rolled_back: bool
    restored_path: str
    backup_path: str
    warnings: List[str] = Field(default_factory=list)


class SkillExportResponse(BaseModel):
    """Response returned after exporting a user skill to zip archive.

    J11 (2026-05-26): Skill export endpoint response.
    """

    success: bool
    skill_id: str
    export_path: str
    errors: List[str] = Field(default_factory=list)

