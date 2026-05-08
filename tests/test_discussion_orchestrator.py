"""Tests for discussion_orchestrator (Slice D / DEC-003a-c)."""

from __future__ import annotations

import asyncio

import pytest

from discussion_orchestrator import (
    DiscussionCredentialMissingError,
    DiscussionOrchestratorError,
    DiscussionUnsupportedStrategyError,
    run_discussion,
)
from models.discussion import (
    DiscussionAgentConfig,
    DiscussionAgentRole,
    DiscussionEvidenceMode,
    DiscussionLLMConfig,
    DiscussionRunConfig,
    DiscussionSynthesisStrategy,
)


DUMMY_LLM_KEY = "test-orch-key-1234567890ABCDEF"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm(provider: str = "OpenAI", model: str = "gpt-4o") -> DiscussionLLMConfig:
    return DiscussionLLMConfig(
        provider=provider,
        model=model,
        base_url="https://api.openai.com/v1",
        api_key=DUMMY_LLM_KEY,
        protocol="openai_chat_completions",
    )


def _agent(
    agent_id: str,
    *,
    role: DiscussionAgentRole = DiscussionAgentRole.PROPOSER,
    llm: DiscussionLLMConfig | None = None,
    credential_id: str | None = None,
    system_prompt: str = "",
    role_label: str = "",
    priority: int = 100,
) -> DiscussionAgentConfig:
    return DiscussionAgentConfig(
        agent_id=agent_id,
        role=role,
        role_label=role_label,
        system_prompt=system_prompt,
        credential_id=credential_id,
        llm=llm or (None if credential_id else _llm()),
        priority=priority,
    )


def _config(
    agents: list[DiscussionAgentConfig],
    *,
    query: str = "What is the role of attention in transformers?",
    project_id: str | None = None,
    evidence_mode: DiscussionEvidenceMode = DiscussionEvidenceMode.NONE,
    evidence_chunk_ids: list[str] | None = None,
    evidence_inline: list[str] | None = None,
    max_turns: int = 1,
    synthesizer_agent_id: str | None = None,
    synthesis_strategy: DiscussionSynthesisStrategy = DiscussionSynthesisStrategy.SYNTHESIZE,
    timeout_seconds: float = 5.0,
) -> DiscussionRunConfig:
    return DiscussionRunConfig(
        project_id=project_id,
        query=query,
        agent_configs=agents,
        synthesizer_agent_id=synthesizer_agent_id,
        max_turns=max_turns,
        evidence_mode=evidence_mode,
        evidence_chunk_ids=evidence_chunk_ids or [],
        evidence_inline=evidence_inline or [],
        synthesis_strategy=synthesis_strategy,
        timeout_seconds=timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


def test_agent_config_xor_credential_or_llm() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        DiscussionAgentConfig(
            agent_id="a1",
            role=DiscussionAgentRole.PROPOSER,
            credential_id="cred_x",
            llm=_llm(),
        )


def test_agent_config_requires_credential_or_llm() -> None:
    with pytest.raises(ValueError, match="either credential_id or inline llm"):
        DiscussionAgentConfig(
            agent_id="a1",
            role=DiscussionAgentRole.PROPOSER,
        )


def test_run_config_rejects_duplicate_agent_id() -> None:
    with pytest.raises(ValueError, match="duplicate agent_id"):
        _config([_agent("a"), _agent("a")])


def test_run_config_rejects_unknown_synthesizer() -> None:
    with pytest.raises(ValueError, match="synthesizer_agent_id"):
        _config([_agent("a")], synthesizer_agent_id="ghost")


def test_run_config_requires_project_id_for_from_project_evidence() -> None:
    with pytest.raises(ValueError, match="project_id is required"):
        _config(
            [_agent("a")],
            evidence_mode=DiscussionEvidenceMode.FROM_PROJECT,
        )


def test_run_config_requires_chunks_for_manual_mode() -> None:
    with pytest.raises(ValueError, match="evidence_chunk_ids or evidence_inline"):
        _config(
            [_agent("a")],
            evidence_mode=DiscussionEvidenceMode.MANUAL_CHUNK_IDS,
        )


# ---------------------------------------------------------------------------
# Orchestrator: end-to-end happy path (no evidence)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_agent_single_turn_with_inline_llm() -> None:
    captured: list[tuple[str, str]] = []  # (agent_id, prompt)

    async def invoke(candidate, prompt):
        captured.append((candidate.agent_id, prompt))
        return f"answer-from-{candidate.agent_id}"

    cfg = _config(
        agents=[
            _agent("proposer", role=DiscussionAgentRole.PROPOSER),
            _agent("critic", role=DiscussionAgentRole.CRITIC),
        ],
        synthesizer_agent_id="proposer",
    )
    result = await run_discussion(cfg, invoke_agent=invoke)

    assert result.run_id.startswith("disc_")
    assert len(result.turns) == 1
    assert {t.agent_id for t in result.turns[0].agent_traces} == {"proposer", "critic"}
    assert all(t.success for t in result.turns[0].agent_traces)

    # Synthesizer ran AFTER turn (one extra invocation)
    agent_calls = [a for a, _ in captured if a == "proposer"]
    assert len(agent_calls) == 2  # once in turn, once for synthesis
    assert result.synthesis.success is True
    assert result.synthesis.synthesizer_agent_id == "proposer"
    # Secret must never appear in the result envelope
    assert DUMMY_LLM_KEY not in result.model_dump_json()


@pytest.mark.asyncio
async def test_two_turns_history_passed_to_each_round() -> None:
    captured: list[tuple[int, str, str]] = []

    async def invoke(candidate, prompt):
        captured.append((len(captured), candidate.agent_id, prompt))
        return f"turn-{candidate.agent_id}"

    cfg = _config(
        agents=[_agent("p"), _agent("c", role=DiscussionAgentRole.CRITIC)],
        max_turns=2,
        synthesizer_agent_id="p",
    )
    result = await run_discussion(cfg, invoke_agent=invoke)

    # Round 1 prompts contain "(no prior turns)"; round 2 prompts contain
    # turn-0 history with both agents quoted.
    round1 = [p for _, _, p in captured[:2]]
    round2 = [p for _, _, p in captured[2:4]]
    assert all("(no prior turns)" in p for p in round1)
    assert all("turn-p" in p and "turn-c" in p for p in round2)
    assert len(result.turns) == 2


# ---------------------------------------------------------------------------
# Evidence wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_built_from_project_and_inserted_into_prompts() -> None:
    captured: list[str] = []

    async def invoke(candidate, prompt):
        captured.append(prompt)
        return "ack"

    def fake_retriever(project_id, query, top_k):
        return [
            {
                "chunk_id": "ck1",
                "content": "Attention is all you need.",
                "score": 0.95,
                "title": "Vaswani 2017",
            }
        ]

    cfg = _config(
        agents=[_agent("a")],
        project_id="proj1",
        evidence_mode=DiscussionEvidenceMode.FROM_PROJECT,
    )
    result = await run_discussion(cfg, invoke_agent=invoke, retriever=fake_retriever)
    assert result.evidence is not None
    assert result.evidence.snippets[0]["chunk_id"] == "ck1"
    assert any("Attention is all you need" in p for p in captured)


@pytest.mark.asyncio
async def test_evidence_inline_manual_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Manual chunk override (DEC-003b) replaces project retrieval."""
    captured: list[str] = []

    async def invoke(candidate, prompt):
        captured.append(prompt)
        return "ack"

    cfg = _config(
        agents=[_agent("a")],
        evidence_mode=DiscussionEvidenceMode.MANUAL_CHUNK_IDS,
        evidence_inline=["Manually pasted snippet about transformers."],
    )
    result = await run_discussion(cfg, invoke_agent=invoke)
    assert result.evidence is None  # no pack built
    assert any("Manually pasted snippet" in p for p in captured)


@pytest.mark.asyncio
async def test_evidence_none_yields_no_pack() -> None:
    async def invoke(candidate, prompt):
        return "ack"

    cfg = _config(
        agents=[_agent("a")],
        evidence_mode=DiscussionEvidenceMode.NONE,
    )
    result = await run_discussion(cfg, invoke_agent=invoke)
    assert result.evidence is None


# ---------------------------------------------------------------------------
# Per-agent isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_agent_failing_does_not_break_others() -> None:
    async def invoke(candidate, prompt):
        if candidate.agent_id == "broken":
            raise RuntimeError("agent broke")
        return "ok"

    cfg = _config(
        agents=[
            _agent("ok"),
            _agent("broken", role=DiscussionAgentRole.CRITIC),
        ],
        synthesizer_agent_id="ok",
    )
    result = await run_discussion(cfg, invoke_agent=invoke)
    by_id = {t.agent_id: t for t in result.turns[0].agent_traces}
    assert by_id["ok"].success is True
    assert by_id["broken"].success is False
    assert by_id["broken"].error["error_class"] == "RuntimeError"
    # Synthesis still proceeds because synthesizer agent ("ok") didn't break
    assert result.synthesis.success is True


@pytest.mark.asyncio
async def test_synthesizer_failure_marks_synthesis_failed() -> None:
    async def invoke(candidate, prompt):
        # Synthesis prompt is identifiable by "# Role: Synthesizer"
        if "# Role: Synthesizer" in prompt:
            raise RuntimeError("synth bombed")
        return "ok"

    cfg = _config(
        agents=[_agent("a"), _agent("b", role=DiscussionAgentRole.CRITIC)],
        synthesizer_agent_id="a",
    )
    result = await run_discussion(cfg, invoke_agent=invoke)
    assert result.synthesis.success is False
    assert result.synthesis.error["error_class"] == "RuntimeError"
    assert result.synthesis.text == ""


# ---------------------------------------------------------------------------
# Strategy enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_synthesis_strategy_rejected() -> None:
    async def invoke(candidate, prompt):
        return "x"

    cfg = _config(
        agents=[_agent("a")],
        synthesis_strategy=DiscussionSynthesisStrategy.VOTE,
    )
    with pytest.raises(DiscussionUnsupportedStrategyError):
        await run_discussion(cfg, invoke_agent=invoke)


# ---------------------------------------------------------------------------
# Credential resolver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_resolver_called_for_pinned_agent() -> None:
    captured = {}

    def resolver(cred_id):
        captured["cred_id"] = cred_id
        return {
            "provider": "Anthropic",
            "model": "claude-opus-4-7",
            "base_url": "https://api.anthropic.com",
            "api_key": DUMMY_LLM_KEY,
            "protocol": "anthropic_messages",
        }

    async def invoke(candidate, prompt):
        return f"from-{candidate.provider}"

    cfg = _config(
        agents=[
            DiscussionAgentConfig(
                agent_id="claude",
                role=DiscussionAgentRole.PROPOSER,
                credential_id="cred_xyz",
            )
        ],
    )
    result = await run_discussion(
        cfg, invoke_agent=invoke, credential_resolver=resolver
    )
    assert captured["cred_id"] == "cred_xyz"
    trace = result.turns[0].agent_traces[0]
    assert trace.provider == "Anthropic"
    assert trace.model == "claude-opus-4-7"
    assert trace.credential_id == "cred_xyz"
    # Secret never leaks to the response envelope
    assert DUMMY_LLM_KEY not in result.model_dump_json()


@pytest.mark.asyncio
async def test_credential_missing_raises_typed_error() -> None:
    def resolver(cred_id):
        raise DiscussionCredentialMissingError(f"missing: {cred_id}")

    async def invoke(candidate, prompt):
        return "x"

    cfg = _config(
        agents=[
            DiscussionAgentConfig(
                agent_id="ghost",
                role=DiscussionAgentRole.PROPOSER,
                credential_id="cred_missing",
            )
        ],
    )
    with pytest.raises(DiscussionCredentialMissingError):
        await run_discussion(cfg, invoke_agent=invoke, credential_resolver=resolver)


# ---------------------------------------------------------------------------
# Concurrency / timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agents_run_in_parallel() -> None:
    started: list[float] = []
    finished: list[float] = []

    async def invoke(candidate, prompt):
        started.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.05)
        finished.append(asyncio.get_event_loop().time())
        return "ok"

    cfg = _config(
        agents=[_agent(f"a{i}") for i in range(4)],
        synthesizer_agent_id="a0",
    )
    result = await run_discussion(cfg, invoke_agent=invoke)
    # All 4 turn agents should start within a small window of each other
    # (true parallelism). The spread of starts must be smaller than the per-
    # call sleep.
    turn_starts = started[:4]
    spread = max(turn_starts) - min(turn_starts)
    assert spread < 0.05, f"agents not parallel; spread={spread}"
    assert len(result.turns[0].agent_traces) == 4


@pytest.mark.asyncio
async def test_agent_timeout_marks_failure_without_breaking_run() -> None:
    async def invoke(candidate, prompt):
        if candidate.agent_id == "slow":
            await asyncio.sleep(2.0)
            return "should_not_reach"
        return "fast"

    cfg = _config(
        agents=[_agent("fast"), _agent("slow", role=DiscussionAgentRole.CRITIC)],
        synthesizer_agent_id="fast",
        timeout_seconds=0.05,
    )
    result = await run_discussion(cfg, invoke_agent=invoke)
    by_id = {t.agent_id: t for t in result.turns[0].agent_traces}
    assert by_id["slow"].success is False
    assert by_id["slow"].error["error_class"] in {"TimeoutError", "CancelledError"}
