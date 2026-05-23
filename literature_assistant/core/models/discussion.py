"""Discussion models (Slice D / DEC-003a / DEC-003b / DEC-003c / TASK-602).

RAG-aware multi-agent discussion request/trace/synthesis types.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.analysis_chain import AnalysisChainPayload

DISCUSSION_MAX_TURNS_LIMIT = 20


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


class DiscussionMcpOverrides(BaseModel):
    """Run-level MCP scope for a discussion (Phase 4 / TASK-401).

    Per plan v0.3 §4.6 option (b): a sibling block on
    ``DiscussionRunConfig`` — the shipped ``DiscussionAgentConfig`` is
    intentionally not modified to keep Slice D's regression boundary.

    Phase 4 only honors ``server_ids`` (applies to all agents in the run).
    ``per_agent`` is accepted but ignored — a follow-up slice will add
    per-agent enforcement once the UX is grilled.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    server_ids: list[str] = Field(default_factory=list, max_length=16)
    allow_high_risk_tools: bool = Field(default=False)
    per_agent: dict[str, list[str]] = Field(default_factory=dict)


class DiscussionAgentConfig(BaseModel):
    """One agent slot in a discussion.

    Per DEC-003c: agents bind to capability/model policy by default;
    ``credential_id`` is an explicit pin override only.

    ``credential_id`` and ``llm`` are mutually exclusive but both optional —
    when neither is set the orchestrator falls back to the runtime default
    chat config (see ``_resolve_agent_endpoint``). This keeps the frontend
    request shape secret-free.
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
                "agent must specify at most one of credential_id or llm, not both"
            )
        return self


class DiscussionRunConfig(BaseModel):
    """Top-level request shape for a RAG-aware discussion."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: str | None = Field(default=None, max_length=128)
    query: str = Field(min_length=1, max_length=4096)
    agent_configs: list[DiscussionAgentConfig] = Field(min_length=1, max_length=8)
    synthesizer_agent_id: str | None = Field(default=None, max_length=64)
    max_turns: int = Field(default=1, ge=1, le=DISCUSSION_MAX_TURNS_LIMIT)
    evidence_mode: DiscussionEvidenceMode = DiscussionEvidenceMode.FROM_PROJECT
    evidence_top_k: int = Field(default=8, ge=1, le=50)
    evidence_chunk_ids: list[str] = Field(default_factory=list, max_length=200)
    evidence_inline: list[str] = Field(default_factory=list, max_length=200)
    synthesis_strategy: DiscussionSynthesisStrategy = DiscussionSynthesisStrategy.SYNTHESIZE
    timeout_seconds: float = Field(default=60.0, gt=0.0, le=600.0)
    max_concurrency: int | None = Field(default=None, ge=1, le=16)
    mcp_overrides: DiscussionMcpOverrides | None = Field(
        default=None,
        description=(
            "Optional MCP scope for this run. When set AND env "
            "LITERATURE_ENABLE_MCP_TOOLS=1, the discussion router wraps "
            "invoke_agent with McpToolUseRunner. None = no MCP."
        ),
    )
    auto_stop: bool = False
    min_turns: int = Field(default=2, ge=1, le=DISCUSSION_MAX_TURNS_LIMIT)
    convergence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    convergence_judge_agent_id: str | None = Field(default=None, max_length=64)

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
        if self.auto_stop:
            if self.min_turns > self.max_turns:
                raise ValueError(
                    "min_turns must be <= max_turns when auto_stop=True"
                )
            if (
                self.convergence_judge_agent_id
                and self.convergence_judge_agent_id not in set(ids)
            ):
                raise ValueError(
                    f"convergence_judge_agent_id "
                    f"{self.convergence_judge_agent_id!r} not found in agent_configs"
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
    evidence_ids: list[str] = Field(default_factory=list)


class DiscussionConvergenceJudgeCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(ge=0)
    similarity: float = Field(ge=0.0, le=1.0)
    done: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=512)


class DiscussionConvergenceJudgeError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_index: int = Field(ge=0)
    stage: Literal["embedding", "judge", "parse"]
    error_class: str = Field(max_length=128)
    message: str = Field(max_length=512)


class DiscussionConvergenceTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_turn_similarity: list[float] = Field(default_factory=list, max_length=10)
    judge_calls: list[DiscussionConvergenceJudgeCall] = Field(
        default_factory=list, max_length=10
    )
    judge_errors: list[DiscussionConvergenceJudgeError] = Field(
        default_factory=list, max_length=20
    )
    decision_turn_index: int | None = Field(default=None, ge=0)


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
    cited_evidence_ids: list[str] = Field(default_factory=list)
    analysis_chain: AnalysisChainPayload | None = Field(
        default=None,
        description=(
            "Optional 6-field reasoning chain attached to this agent's "
            "answer when feature flag ``analysis_chain_discussion`` is on. "
            "ACR-030 ~ ACR-034."
        ),
    )


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
    stopped_early: bool = False
    stop_reason: Literal["max_turns", "converged", "error"] = "max_turns"
    convergence: DiscussionConvergenceTrace | None = None


__all__ = [
    "DiscussionAgentConfig",
    "DiscussionAgentRole",
    "DiscussionAgentTrace",
    "DiscussionConvergenceJudgeCall",
    "DiscussionConvergenceJudgeError",
    "DiscussionConvergenceTrace",
    "DiscussionEvidenceMode",
    "DiscussionEvidencePackPayload",
    "DiscussionLLMConfig",
    "DiscussionRunConfig",
    "DiscussionRunResult",
    "DiscussionSynthesis",
    "DiscussionSynthesisStrategy",
    "DiscussionTurnTrace",
]
