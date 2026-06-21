"""Shared outcome models for multi-step Scholar AI tools.

These models make tool results actionable for agents and UI surfaces without
turning every endpoint into a bespoke state machine. The envelope is additive:
callers keep their existing response fields and may attach ``ToolOutcome`` when
they can explain status, quality, attempts, and a safe next action.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


TOOL_OUTCOME_SCHEMA_VERSION = "scholar-ai-tool-outcome/v1"

OutcomeStatus = Literal[
    "success",
    "partial",
    "empty",
    "blocked",
    "config_needed",
    "auth_required",
    "degraded",
    "failed",
]

OutcomeQuality = Literal[
    "full",
    "partial",
    "refs_only",
    "metadata_only",
    "none",
    "unknown",
]

NextActionKind = Literal[
    "call_tool",
    "open_settings",
    "bind_source_folder",
    "scan_folder",
    "read_resource",
    "configure_provider",
    "configure_rerank",
    "obtain_full_text",
    "review_qrels",
    "retry_later",
    "none",
]

AttemptStatus = Literal["success", "skipped", "failed", "blocked", "degraded"]


def _clean_identifier(value: str, field_name: str, *, max_length: int) -> str:
    """Return a bounded identifier-like string for stable tool contracts."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")
    return cleaned


def _clean_optional_text(value: str | None, field_name: str, *, max_length: int) -> str | None:
    """Return a bounded optional string while preserving omitted fields."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")
    return cleaned


class ToolNextAction(BaseModel):
    """Machine-actionable next step for agents and UI.

    Args:
        kind: Closed action class. Use ``none`` when no follow-up is needed.
        message: Short user/agent visible explanation without secrets.
        tool_name: Optional MCP tool name to call next.
        endpoint: Optional backend endpoint for UI/developer follow-up.
        command_preview: Optional non-secret command preview.
        args: JSON-safe argument hints for the next action.
    """

    kind: NextActionKind = "none"
    message: str = Field(default="", max_length=500)
    tool_name: str | None = Field(default=None, max_length=160)
    endpoint: str | None = Field(default=None, max_length=260)
    command_preview: str | None = Field(default=None, max_length=500)
    args: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message", mode="before")
    @classmethod
    def _validate_message(cls, value: Any) -> str:
        """Normalize optional message text for consistent serialization."""

        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("message must be a string")
        return value.strip()

    @field_validator("tool_name", "endpoint", "command_preview", mode="before")
    @classmethod
    def _validate_optional_text(cls, value: Any, info: Any) -> str | None:
        """Trim optional text fields without inventing placeholder values."""

        return _clean_optional_text(value, str(info.field_name), max_length=500)

    @model_validator(mode="after")
    def _validate_action_shape(self) -> "ToolNextAction":
        """Require executable detail for action kinds that imply a call target."""

        if self.kind == "call_tool" and not self.tool_name:
            raise ValueError("call_tool next_action requires tool_name")
        if self.kind == "read_resource" and not (self.endpoint or self.tool_name):
            raise ValueError("read_resource next_action requires endpoint or tool_name")
        return self


class ToolAttempt(BaseModel):
    """One bounded execution step, safe for audit/UI display.

    Args:
        stage: Stable phase label such as ``chunk_load`` or ``rerank``.
        status: Step-level result.
        reason: Short non-secret explanation.
        duration_ms: Local elapsed duration in milliseconds.
        error_class: Optional shared diagnostic class.
        recommendation: Optional actionable hint.
        metadata: Bounded JSON-safe details; callers must not include secrets,
            raw provider payloads, cookies, or full document text.
    """

    stage: str = Field(min_length=1, max_length=120)
    status: AttemptStatus
    reason: str = Field(default="", max_length=240)
    duration_ms: int = Field(default=0, ge=0)
    error_class: str = Field(default="", max_length=120)
    recommendation: str = Field(default="", max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("stage", mode="before")
    @classmethod
    def _validate_stage(cls, value: Any) -> str:
        """Keep stage labels stable and non-empty for downstream filters."""

        return _clean_identifier(str(value) if value is not None else "", "stage", max_length=120)

    @field_validator("reason", "error_class", "recommendation", mode="before")
    @classmethod
    def _validate_text(cls, value: Any) -> str:
        """Normalize short text fields used in UI and logs."""

        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("attempt text fields must be strings")
        return value.strip()


class ToolOutcome(BaseModel):
    """Common agent-facing outcome envelope for multi-step tools.

    Args:
        status: Overall result state for the tool invocation.
        quality: Coarse usefulness of returned data.
        reason: Short non-secret explanation of the outcome.
        next_action: Suggested safe follow-up.
        attempts: Ordered step audit. Keep this concise; raw documents and
            provider payloads belong in bounded resources, not this envelope.
    """

    schema_version: Literal["scholar-ai-tool-outcome/v1"] = TOOL_OUTCOME_SCHEMA_VERSION
    status: OutcomeStatus
    quality: OutcomeQuality = "unknown"
    reason: str = Field(default="", max_length=500)
    next_action: ToolNextAction = Field(default_factory=ToolNextAction)
    attempts: list[ToolAttempt] = Field(default_factory=list, max_length=32)

    @field_validator("reason", mode="before")
    @classmethod
    def _validate_reason(cls, value: Any) -> str:
        """Normalize the top-level reason so empty reasons serialize stably."""

        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("reason must be a string")
        return value.strip()

    @model_validator(mode="after")
    def _validate_blocked_next_action(self) -> "ToolOutcome":
        """Make blocked outcomes actionable instead of dead-end status labels."""

        if self.status in {"blocked", "config_needed", "auth_required"} and self.next_action.kind == "none":
            raise ValueError("blocked/config/auth outcomes require a next_action")
        return self


__all__ = [
    "AttemptStatus",
    "NextActionKind",
    "OutcomeQuality",
    "OutcomeStatus",
    "TOOL_OUTCOME_SCHEMA_VERSION",
    "ToolAttempt",
    "ToolNextAction",
    "ToolOutcome",
]
