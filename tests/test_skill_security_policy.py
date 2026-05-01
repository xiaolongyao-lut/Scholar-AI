# -*- coding: utf-8 -*-
"""Focused tests for user Skill safety policy classification."""

from __future__ import annotations

from skills.models import ScriptPolicy, SkillDescriptor, SkillKind, SkillSource, SkillTrustLevel, UIVisibility
from skills.security_policy import (
    RuntimeGate,
    SkillRiskLevel,
    assess_skill_security,
    is_skill_safe_for_legacy_action,
)


def _imported_skill(
    *,
    skill_id: str,
    permissions: dict[str, bool] | object | None = None,
    has_scripts: bool = False,
) -> SkillDescriptor:
    """Build a minimal imported Skill descriptor for policy tests."""
    parameters: dict[str, object] = {}
    if permissions is not None:
        parameters["permissions"] = permissions
    return SkillDescriptor(
        id=skill_id,
        name=skill_id,
        description="Security policy test skill.",
        kind=SkillKind.TRANSFORM,
        source=SkillSource.IMPORTED,
        entry_mode="manual",
        supported_scopes=["selection"],
        ui_visibility=UIVisibility.SKILL_ASSISTED,
        requires_assets=False,
        safe_to_execute=False,
        default_parameters=parameters,
        script_policy=ScriptPolicy(
            has_scripts=has_scripts,
            safe_to_execute=False,
            disabled_reason="Scripts blocked by default" if has_scripts else None,
        ),
        trust_level=SkillTrustLevel.UNTRUSTED,
    )


def test_prompt_only_imported_skill_is_controlled_prompt_executable() -> None:
    """Low-risk prompt Skills should be executable by the controlled renderer only."""
    skill = _imported_skill(skill_id="user.security.prompt", permissions={"draft.read": True})

    assessment = assess_skill_security(skill)

    assert assessment.risk_level == SkillRiskLevel.LOW.value
    assert assessment.runtime_gate == RuntimeGate.ALLOW_CONTROLLED_PROMPT.value
    assert assessment.runtime_executable is True
    assert assessment.enable_requires_approval is False
    assert is_skill_safe_for_legacy_action(skill) is True


def test_scripted_skill_is_critical_and_requires_future_sandbox_controls() -> None:
    """Scripted Skills should stay blocked and advertise required sandbox controls."""
    skill = _imported_skill(
        skill_id="user.security.scripted",
        permissions={"draft.read": True, "script.execute": True},
        has_scripts=True,
    )

    assessment = assess_skill_security(skill)

    assert assessment.risk_level == SkillRiskLevel.CRITICAL.value
    assert assessment.runtime_gate == RuntimeGate.BLOCK_SCRIPTED_EXECUTION.value
    assert assessment.runtime_executable is False
    assert assessment.enable_requires_approval is True
    assert "script_policy.has_scripts" in assessment.denied_operations
    assert "script.execute" in assessment.denied_operations
    assert "argv_allowlist_no_shell" in assessment.required_sandbox_controls
    assert "environment_allowlist_without_secrets" in assessment.required_sandbox_controls
    assert is_skill_safe_for_legacy_action(skill) is False


def test_invalid_permission_shape_fails_closed() -> None:
    """Malformed permission payloads should become reference-only instead of crashing lists."""
    skill = _imported_skill(skill_id="user.security.invalid", permissions=["network"])

    assessment = assess_skill_security(skill)

    assert assessment.runtime_gate == RuntimeGate.REFERENCE_ONLY.value
    assert assessment.runtime_executable is False
    assert assessment.enable_requires_approval is True
    assert assessment.high_risk_flags == ["permissions.invalid_shape"]
    assert "Invalid Skill permission declaration" in str(assessment.block_reason)
