# -*- coding: utf-8 -*-
"""Machine-readable safety policy for user Skill execution.

The policy is intentionally conservative: it classifies risky capabilities and
records future sandbox requirements without enabling script, network, or file
write execution in the current runtime.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping

from .models import SkillDescriptor, SkillSource


HIGH_RISK_PERMISSION_KEYS: frozenset[str] = frozenset({"network", "files.write", "script.execute"})

SCRIPT_SANDBOX_CONTROLS: tuple[str, ...] = (
    "argv_allowlist_no_shell",
    "fixed_working_directory_under_skill_root",
    "environment_allowlist_without_secrets",
    "read_roots_allowlist",
    "write_roots_allowlist",
    "network_deny_by_default",
    "wall_clock_timeout",
    "stdout_stderr_size_limits",
    "append_only_audit",
    "rollback_snapshot_before_write",
)


class SkillRiskLevel(str, Enum):
    """Risk level used by API and audit payloads."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuntimeGate(str, Enum):
    """Runtime decision for the current execution engine."""

    ALLOW_CONTROLLED_PROMPT = "allow_controlled_prompt"
    BLOCK_HIGH_RISK_PERMISSION = "block_high_risk_permission"
    BLOCK_SCRIPTED_EXECUTION = "block_scripted_execution"
    REFERENCE_ONLY = "reference_only"


@dataclass(frozen=True)
class SkillSecurityAssessment:
    """Security assessment returned by service and router layers.

    Fields are stable, JSON-serializable primitives so frontend, tests, and
    audit pipelines can make decisions without parsing human-readable strings.
    """

    skill_id: str
    source: str
    risk_level: str
    runtime_gate: str
    runtime_executable: bool
    enable_requires_approval: bool
    high_risk_flags: list[str] = field(default_factory=list)
    denied_operations: list[str] = field(default_factory=list)
    allowed_operations: list[str] = field(default_factory=list)
    required_sandbox_controls: list[str] = field(default_factory=list)
    approval_reason: str | None = None
    block_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the policy to a stable API-safe dictionary."""
        return asdict(self)


class SkillSecurityPolicyError(PermissionError):
    """Raised when current runtime policy forbids a Skill operation."""

    def __init__(self, assessment: SkillSecurityAssessment):
        """Create an exception that carries the machine-readable assessment."""
        if assessment.runtime_executable:
            raise ValueError("SkillSecurityPolicyError requires a blocked assessment")
        self.assessment = assessment
        super().__init__(assessment.block_reason or "Skill execution is blocked by security policy")


def assess_skill_security(skill: SkillDescriptor) -> SkillSecurityAssessment:
    """Return the current safety policy for one Skill descriptor.

    Args:
        skill: Fully populated Skill descriptor from the registry.

    Returns:
        A machine-readable security assessment. Imported scripted, networked, or
        file-writing Skills remain blocked at runtime even after enable approval.
    """
    if not isinstance(skill, SkillDescriptor):
        raise TypeError(f"Expected SkillDescriptor, got {type(skill)}")

    if skill.source != SkillSource.IMPORTED:
        return SkillSecurityAssessment(
            skill_id=skill.id,
            source=skill.source.value,
            risk_level=SkillRiskLevel.LOW.value,
            runtime_gate=RuntimeGate.ALLOW_CONTROLLED_PROMPT.value,
            runtime_executable=True,
            enable_requires_approval=False,
            allowed_operations=["builtin_skill_runtime"],
        )

    try:
        permissions = normalize_permissions(skill.default_parameters.get("permissions", {}))
    except (TypeError, ValueError) as exc:
        return SkillSecurityAssessment(
            skill_id=skill.id,
            source=skill.source.value,
            risk_level=SkillRiskLevel.HIGH.value,
            runtime_gate=RuntimeGate.REFERENCE_ONLY.value,
            runtime_executable=False,
            enable_requires_approval=True,
            high_risk_flags=["permissions.invalid_shape"],
            denied_operations=["permissions.invalid_shape"],
            allowed_operations=["manifest_inspection", "rollback"],
            required_sandbox_controls=[],
            approval_reason="Review imported user Skill manifest permissions",
            block_reason=f"Invalid Skill permission declaration: {exc}",
        )
    high_risk_flags = sorted(
        key for key in HIGH_RISK_PERMISSION_KEYS if bool(permissions.get(key, False))
    )
    denied_operations = list(high_risk_flags)
    required_controls: list[str] = []

    if skill.script_policy.has_scripts:
        if "script_policy.has_scripts" not in denied_operations:
            denied_operations.append("script_policy.has_scripts")
        if "script.execute" not in denied_operations:
            denied_operations.append("script.execute")
        required_controls.extend(SCRIPT_SANDBOX_CONTROLS)
        return SkillSecurityAssessment(
            skill_id=skill.id,
            source=skill.source.value,
            risk_level=SkillRiskLevel.CRITICAL.value,
            runtime_gate=RuntimeGate.BLOCK_SCRIPTED_EXECUTION.value,
            runtime_executable=False,
            enable_requires_approval=True,
            high_risk_flags=high_risk_flags,
            denied_operations=denied_operations,
            allowed_operations=["manifest_inspection", "approval_request", "rollback"],
            required_sandbox_controls=required_controls,
            approval_reason=_format_approval_reason(denied_operations),
            block_reason="Scripted Skill execution is blocked until a separate sandbox runner is approved",
        )

    if high_risk_flags:
        if "network" in high_risk_flags:
            required_controls.append("network_allowlist_with_timeout")
        if "files.write" in high_risk_flags:
            required_controls.extend(("write_roots_allowlist", "rollback_snapshot_before_write"))
        if "script.execute" in high_risk_flags:
            required_controls.extend(SCRIPT_SANDBOX_CONTROLS)
        return SkillSecurityAssessment(
            skill_id=skill.id,
            source=skill.source.value,
            risk_level=SkillRiskLevel.HIGH.value,
            runtime_gate=RuntimeGate.BLOCK_HIGH_RISK_PERMISSION.value,
            runtime_executable=False,
            enable_requires_approval=True,
            high_risk_flags=high_risk_flags,
            denied_operations=denied_operations,
            allowed_operations=["manifest_inspection", "approval_request", "rollback"],
            required_sandbox_controls=_dedupe_preserving_order(required_controls),
            approval_reason=_format_approval_reason(denied_operations),
            block_reason="High-risk Skill permissions are blocked by the current runtime",
        )

    return SkillSecurityAssessment(
        skill_id=skill.id,
        source=skill.source.value,
        risk_level=SkillRiskLevel.LOW.value,
        runtime_gate=RuntimeGate.ALLOW_CONTROLLED_PROMPT.value,
        runtime_executable=True,
        enable_requires_approval=False,
        high_risk_flags=[],
        denied_operations=[],
        allowed_operations=["controlled_prompt_template_render", "audit_append", "rollback"],
        required_sandbox_controls=[],
    )


def normalize_permissions(raw_permissions: object) -> dict[str, bool]:
    """Normalize an arbitrary permissions payload to boolean permission keys."""
    if raw_permissions is None:
        return {}
    if not isinstance(raw_permissions, Mapping):
        raise TypeError("permissions must be a mapping when present")

    normalized: dict[str, bool] = {}
    for raw_key, raw_value in raw_permissions.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise ValueError("permission keys must be non-empty strings")
        normalized[raw_key.replace("-", ".").replace("_", ".")] = bool(raw_value)
    return normalized


def is_skill_safe_for_legacy_action(skill: SkillDescriptor) -> bool:
    """Return whether a Skill may appear in manual quick-action surfaces."""
    assessment = assess_skill_security(skill)
    return assessment.runtime_executable and assessment.runtime_gate == RuntimeGate.ALLOW_CONTROLLED_PROMPT.value


def _format_approval_reason(denied_operations: list[str]) -> str:
    """Build a stable human-readable approval reason from denied operations."""
    if not denied_operations:
        return "Enable imported user Skill"
    return f"Enable high-risk user Skill permissions: {', '.join(denied_operations)}"


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    """Return unique values while preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
