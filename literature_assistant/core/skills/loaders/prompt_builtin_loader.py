# -*- coding: utf-8 -*-
"""Loaders for builtin prompt-backed skills and action mappings."""

from __future__ import annotations

from typing import Any
from typing import Protocol

from ..models import (
    SkillDescriptor,
    SkillKind,
    SkillSource,
    UIVisibility,
    SkillTrustLevel,
    ScriptPolicy,
)


class PromptManagerProtocol(Protocol):
    """Structural placeholder for optional prompt manager integrations."""


def load_builtin_prompt_skills(prompt_manager: PromptManagerProtocol | None) -> list[SkillDescriptor]:
    """
    Load builtin skills backed by prompt templates.
    
    These are the core writing capabilities shipped with the application.
    """
    _ = prompt_manager
    skills: list[SkillDescriptor] = []
    
    # Example: Grammar and style skills
    skills.append(
        SkillDescriptor(
            id="grammar_checker",
            name="Grammar Checker",
            description="Check and improve grammar in the selected text",
            kind=SkillKind.VALIDATOR,
            source=SkillSource.BUILTIN,
            entry_mode="manual",
            supported_scopes=["selection", "section"],
            ui_visibility=UIVisibility.BOTH,
            requires_assets=False,
            prompt_template_refs=["grammar_check"],
            safe_to_execute=True,
            trust_level=SkillTrustLevel.TRUSTED,
            script_policy=ScriptPolicy(has_scripts=False, safe_to_execute=True),
            tags=["grammar", "validation", "builtin"],
        )
    )
    
    # Example: Rewrite/Paraphrase skill
    skills.append(
        SkillDescriptor(
            id="paraphrase",
            name="Paraphrase",
            description="Rewrite selected text with alternative phrasing",
            kind=SkillKind.TRANSFORM,
            source=SkillSource.BUILTIN,
            entry_mode="manual",
            supported_scopes=["selection", "section"],
            ui_visibility=UIVisibility.BOTH,
            requires_assets=False,
            prompt_template_refs=["paraphrase_prompt"],
            safe_to_execute=True,
            trust_level=SkillTrustLevel.TRUSTED,
            script_policy=ScriptPolicy(has_scripts=False, safe_to_execute=True),
            tags=["rewrite", "transform", "builtin"],
        )
    )
    
    # Example: Tone adjustment skill
    skills.append(
        SkillDescriptor(
            id="tone_adjuster",
            name="Tone Adjuster",
            description="Adjust the tone of selected text (formal, casual, etc)",
            kind=SkillKind.TRANSFORM,
            source=SkillSource.BUILTIN,
            entry_mode="manual",
            supported_scopes=["selection", "section"],
            ui_visibility=UIVisibility.SKILL_ASSISTED,
            requires_assets=False,
            prompt_template_refs=["tone_adjustment"],
            safe_to_execute=True,
            default_parameters={"tone": "formal"},
            trust_level=SkillTrustLevel.TRUSTED,
            script_policy=ScriptPolicy(has_scripts=False, safe_to_execute=True),
            tags=["tone", "style", "builtin"],
        )
    )
    
    # Example: Summarize skill
    skills.append(
        SkillDescriptor(
            id="summarize",
            name="Summarize",
            description="Generate a concise summary of the selected text",
            kind=SkillKind.TRANSFORM,
            source=SkillSource.BUILTIN,
            entry_mode="assistant",
            supported_scopes=["selection", "section", "full_draft"],
            ui_visibility=UIVisibility.SKILL_ASSISTED,
            requires_assets=False,
            prompt_template_refs=["summarize_section"],
            safe_to_execute=True,
            trust_level=SkillTrustLevel.TRUSTED,
            script_policy=ScriptPolicy(has_scripts=False, safe_to_execute=True),
            tags=["summary", "compression", "builtin"],
        )
    )
    
    # Example: Expand with details
    skills.append(
        SkillDescriptor(
            id="expand_details",
            name="Expand with Details",
            description="Expand selected text with additional context and examples",
            kind=SkillKind.TRANSFORM,
            source=SkillSource.BUILTIN,
            entry_mode="assistant",
            supported_scopes=["selection", "section"],
            ui_visibility=UIVisibility.SKILL_ASSISTED,
            requires_assets=False,
            prompt_template_refs=["expand_section"],
            safe_to_execute=True,
            trust_level=SkillTrustLevel.TRUSTED,
            script_policy=ScriptPolicy(has_scripts=False, safe_to_execute=True),
            tags=["expansion", "detail", "builtin"],
        )
    )
    
    # Example: Translation skill
    skills.append(
        SkillDescriptor(
            id="translate",
            name="Translate",
            description="Translate selected text to another language",
            kind=SkillKind.TRANSFORM,
            source=SkillSource.BUILTIN,
            entry_mode="manual",
            supported_scopes=["selection", "section"],
            ui_visibility=UIVisibility.BOTH,
            requires_assets=False,
            prompt_template_refs=["translate_text"],
            safe_to_execute=True,
            default_parameters={"language": "Chinese"},
            trust_level=SkillTrustLevel.TRUSTED,
            script_policy=ScriptPolicy(has_scripts=False, safe_to_execute=True),
            tags=["translation", "language", "builtin"],
        )
    )
    
    return skills


def build_action_skill_index(all_skills: list[SkillDescriptor]) -> dict[str, str]:
    """
    Build a mapping from legacy action IDs to skill IDs.
    
    Enables backward compatibility with existing action-based interfaces.
    """
    index: dict[str, str] = {}
    
    # Map builtin skills to action IDs for compatibility
    for skill in all_skills:
        if skill.source == SkillSource.BUILTIN and skill.compatibility.fallback_action_id:
            index[skill.compatibility.fallback_action_id] = skill.id
    
    return index


def get_builtin_action_descriptors() -> list[dict[str, Any]]:
    """
    Get legacy action descriptors for backward compatibility.
    
    These are exposed through the /actions endpoint for older interfaces.
    """
    actions: list[dict[str, Any]] = []
    
    # Map builtin skills to legacy action format
    actions.extend([
        {
            "id": "grammar_check_action",
            "nameZh": "检查语法",
            "nameEn": "Check Grammar",
            "descriptionZh": "检查并改进选定文本的语法",
            "descriptionEn": "Check and improve grammar in selected text",
            "category": "validation",
            "supportedScopes": ["selection", "section"],
            "icon": "grammar",
            "skillId": "grammar_checker",
        },
        {
            "id": "paraphrase_action",
            "nameZh": "改写",
            "nameEn": "Paraphrase",
            "descriptionZh": "用替代措辞改写选定的文本",
            "descriptionEn": "Rewrite selected text with alternative phrasing",
            "category": "transform",
            "supportedScopes": ["selection", "section"],
            "icon": "edit",
            "skillId": "paraphrase",
        },
        {
            "id": "summarize_action",
            "nameZh": "总结",
            "nameEn": "Summarize",
            "descriptionZh": "生成选定文本的简明摘要",
            "descriptionEn": "Generate a concise summary of selected text",
            "category": "transform",
            "supportedScopes": ["selection", "section", "full_draft"],
            "icon": "summary",
            "skillId": "summarize",
        },
    ])
    
    return actions
