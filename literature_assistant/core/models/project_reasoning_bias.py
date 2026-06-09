"""Project-level reasoning bias API models."""

from __future__ import annotations

import re
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class ProjectReasoningBiasScopes(BaseModel):
    """Scope flags for applying a user-authored project reasoning bias.

    Args:
        analysis_chain: Applies the preference to six-field reasoning summaries.
        chat_generation: Applies the preference to chat and generation surfaces.
        project_wide: Applies the preference to every registered AI surface.
        discussion_agent_ids: Agent identifiers that opt into the preference.
    """

    model_config = ConfigDict(extra="forbid")

    analysis_chain: bool = True
    chat_generation: bool = False
    project_wide: bool = False
    discussion_agent_ids: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("discussion_agent_ids")
    @classmethod
    def _normalize_discussion_agent_ids(cls, value: list[str]) -> list[str]:
        """Return unique agent ids accepted by discussion request models."""
        if value is None:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_item in value:
            item = str(raw_item or "").strip()
            if not item:
                continue
            if not _AGENT_ID_RE.fullmatch(item):
                raise ValueError(
                    "discussion_agent_ids items must be 1-64 chars using letters, numbers, _, ., :, or -"
                )
            if item not in seen:
                normalized.append(item)
                seen.add(item)
        if len(normalized) > 16:
            raise ValueError("discussion_agent_ids must contain at most 16 unique ids")
        return normalized


class ProjectReasoningBiasPayload(BaseModel):
    """Persisted project reasoning bias payload stored in project metadata.

    Args:
        version: Schema version. Only version 1 is currently accepted.
        human_bias: User-authored preference text. Empty string disables injection.
        scopes: Surfaces where the preference may apply.
        language: Output language preference for rendering or optimization.
        updated_at: Server-maintained ISO timestamp, empty for defaults.
        updated_by: Actor that most recently saved the payload.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: Literal[1] = 1
    human_bias: str = Field(default="", max_length=4000)
    scopes: ProjectReasoningBiasScopes = Field(default_factory=ProjectReasoningBiasScopes)
    language: Literal["zh", "en", "auto"] = "auto"
    updated_at: str = ""
    updated_by: Literal["user", "ai_optimize", "migration"] = "user"


class ProjectReasoningBiasUpdateRequest(BaseModel):
    """Request body for replacing a project's reasoning bias metadata key.

    Args:
        human_bias: User-authored preference text. Empty string disables injection.
        scopes: Surfaces where the preference may apply.
        language: Output language preference for rendering or optimization.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    human_bias: str = Field(default="", max_length=4000)
    scopes: ProjectReasoningBiasScopes = Field(default_factory=ProjectReasoningBiasScopes)
    language: Literal["zh", "en", "auto"] = "auto"


ProjectReasoningBiasOptimizeScope = Literal[
    "analysis_chain",
    "chat_generation",
    "discussion_agent",
    "project_wide",
]


class ProjectReasoningBiasFieldSuggestions(BaseModel):
    """Six-field optimization suggestions aligned with AnalysisChain output.

    Args:
        observation: Preference for selecting observable issues or phenomena.
        mechanism: Preference for selecting causal mechanisms or rules.
        evidence: Preference for evidence selection and evidence quality.
        boundary: Preference for scope limits, methods, and uncertainty.
        counter_evidence: Preference for opposing evidence and falsification.
        next_action: Preference for follow-up writing, retrieval, or validation.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    observation: str = Field(default="", max_length=800)
    mechanism: str = Field(default="", max_length=800)
    evidence: str = Field(default="", max_length=800)
    boundary: str = Field(default="", max_length=800)
    counter_evidence: str = Field(default="", max_length=800)
    next_action: str = Field(default="", max_length=800)


class ProjectReasoningBiasOptimizeRequest(BaseModel):
    """Request body for optimizing a user-authored project reasoning bias.

    Args:
        human_bias: User draft to rewrite into a clearer project preference.
        language: Desired output language. Auto follows the input language.
        target_scopes: Surfaces the user intends to apply the preference to.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    human_bias: str = Field(default="", max_length=4000)
    language: Literal["zh", "en", "auto"] = "auto"
    target_scopes: list[ProjectReasoningBiasOptimizeScope] = Field(default_factory=list, max_length=8)

    @field_validator("target_scopes")
    @classmethod
    def _normalize_target_scopes(
        cls,
        value: list[ProjectReasoningBiasOptimizeScope],
    ) -> list[ProjectReasoningBiasOptimizeScope]:
        """Return unique target scopes while preserving user-supplied order."""
        normalized: list[ProjectReasoningBiasOptimizeScope] = []
        seen: set[str] = set()
        for raw_item in value or []:
            item = str(raw_item or "").strip()
            if item in seen:
                continue
            if item not in {"analysis_chain", "chat_generation", "discussion_agent", "project_wide"}:
                raise ValueError("target_scopes contains an unsupported scope")
            normalized.append(cast(ProjectReasoningBiasOptimizeScope, item))
            seen.add(item)
        return normalized


class ProjectReasoningBiasOptimizeResponse(BaseModel):
    """Structured optimizer output returned for manual user review only.

    Args:
        original_bias: The user draft submitted to the optimizer.
        optimized_bias: A safe rewritten preference that the UI may offer to adopt.
        field_suggestions: Six-field suggestions aligned with AnalysisChain.
        safety_notes: Short notes explaining safety and evidence boundaries.
        language: Language used by the optimized text.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    original_bias: str = Field(default="", max_length=4000)
    optimized_bias: str = Field(default="", max_length=4000)
    field_suggestions: ProjectReasoningBiasFieldSuggestions = Field(
        default_factory=ProjectReasoningBiasFieldSuggestions
    )
    safety_notes: list[str] = Field(default_factory=list, max_length=8)
    language: Literal["zh", "en"] = "zh"
