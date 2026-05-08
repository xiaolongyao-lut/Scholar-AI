"""Discussion models (Slice D / DEC-003a / DEC-003b / DEC-003c / TASK-602).

RAG-aware multi-agent discussion request/trace/synthesis types.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DiscussionAgentRole(str, Enum):
    PROPOSER = "proposer"
    CRITIC = "critic"
    DEVIL_ADVOCATE = "devil_advocate"
    DOMAIN_EXPERT = "domain_expert"
    SYNTHESIZER = "synthesizer"
    CUSTOM = "custom"


class DiscussionSynthesisStrategy(str, Enum):
    SYNTHESIZE = "synthesize"
    VOTE = "vote"
    DEBATE = "debate"


class DiscussionEvidenceMode(str, Enum):
    FROM_PROJECT = "from_project"
    MANUAL_CHUNK_IDS = "manual_chunk_ids"
    NONE = "none"


class DiscussionLLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = Field(min_length=1, max_length=512)
    protocol: str = Field(default="openai_chat_completions", max_length=64)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=64, le=32_000)


class DiscussionAgentConfig(BaseModel):
    """One agent slot in a discussion.

    Per DEC-003c: agents bind to capability/model policy by default;
    ``credential_id`` is an explicit pin override only.

    Either ``credential_id`` or ``llm`` must be set; not both.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_id: str = Field(min_length=1, max_length=64)
    role: DiscussionAgentRole = DiscussionAgentRole.CUSTOM
    role_label: str = Field(default="", max_length=128)
    system_prompt: str = Field(default="", max_length=8192)
    credential_id: str | None = Field(default=None, max_length=64)
    llm: DiscussionLLMConfig | None = None
    strict_pin: bool = False
    priority: int = Field(default=100, ge=0, le=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_credential_xor_llm(self) -> "DiscussionAgentConfig":
        if self.credential_id and self.llm:
            raise ValueError(
                "agent must specify exactly one of credential_id or llm, not both"
            )
        if not self.credential_id and not self.llm:
            raise ValueError(
                "agent must specify either credential_id or inline llm config"
            )
        return self


class DiscussionRunConfig(BaseModel):
    """Top-level request shape for a RAG-aware discussion."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str | None = Field(default=None, max_length=128)
    query: str = Field(min_length=1, max_length=4096)
    agent_configs: list[DiscussionAgentConfig] = Field(min_length=1, max_length=8)
    synthesizer_agent_id: str | None = Field(default=None, max_length=64)
    max_turns: int = Field(default=1, ge=1, le=5)
    evidence_mode: DiscussionEvidenceMode = DiscussionEvidenceMode.FROM_PROJECT
    evidence_top_k: int = Field(default=8, ge=1, le=50)
    evidence_chunk_ids: list[str] = Field(default_factory=list, max_length=200)
    evidence_inline: list[str] = Field(default_factory=list, max_length=200)
    synthesis_strategy: DiscussionSynthesisStrategy = DiscussionSynthesisStrategy.SYNTHESIZE
    timeout_seconds: float = Field(default=60.0, gt=0.0, le=600.0)
    max_concurrency: int | None = Field(default=None, ge=1, le=16)

    @model_validator(mode="after")
    def _validate_run_shape(self) -> "DiscussionRunConfig":
        ids = [a.agent_id for a in self.agent_configs]
        if len(set(ids)) != len(ids):
            raise ValueError("agent_configs has duplicate agent_id")
        if self.synthesizer_agent_id and self.synthesizer_agent_id not in set(ids):
            raise ValueError(
                f"synthesizer_agent_id {self.synthesizer_agent_id!r} "
                "not found in agent_configs"
            )
        if (
            self.evidence_mode == DiscussionEvidenceMode.FROM_PROJECT
            and not self.project_id
        ):
            raise ValueError(
                "project_id is required when evidence_mode=from_project"
            )
        if (
            self.evidence_mode == DiscussionEvidenceMode.MANUAL_CHUNK_IDS
            and not (self.evidence_chunk_ids or self.evidence_inline)
        ):
            raise ValueError(
                "evidence_chunk_ids or evidence_inline required for manual mode"
            )
        return self


class DiscussionEvidencePackPayload(BaseModel):
    """Mirror of evidence_pack.EvidencePack as a transport object."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str
    pack_version: str
    project_id: str
    query: str
    snippets: list[dict[str, Any]]
    truncated: bool


class DiscussionAgentTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    role: str
    role_label: str = ""
    credential_id: str | None = None
    provider: str
    model: str
    latency_ms: float
    success: bool
    answer: str = ""
    error: dict[str, Any] | None = None


class DiscussionTurnTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_index: int
    agent_traces: list[DiscussionAgentTrace]


class DiscussionSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    strategy: str
    synthesizer_agent_id: str | None = None
    synthesizer_provider: str = ""
    synthesizer_model: str = ""
    success: bool
    error: dict[str, Any] | None = None


class DiscussionRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    project_id: str | None = None
    query: str
    evidence: DiscussionEvidencePackPayload | None = None
    turns: list[DiscussionTurnTrace]
    synthesis: DiscussionSynthesis
    elapsed_ms: float


__all__ = [
    "DiscussionAgentConfig",
    "DiscussionAgentRole",
    "DiscussionAgentTrace",
    "DiscussionEvidenceMode",
    "DiscussionEvidencePackPayload",
    "DiscussionLLMConfig",
    "DiscussionRunConfig",
    "DiscussionRunResult",
    "DiscussionSynthesis",
    "DiscussionSynthesisStrategy",
    "DiscussionTurnTrace",
]
