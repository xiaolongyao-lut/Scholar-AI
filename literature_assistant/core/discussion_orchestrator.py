"""Discussion Orchestrator (Slice D / DEC-003a / DEC-003b / DEC-003c).

RAG-aware multi-agent discussion runner. Pipeline:

    1. Build EvidencePack via Slice B (or accept manual chunk_ids per DEC-003b)
    2. For each turn 0..max_turns-1:
         a. Compose per-agent prompt = system + role + evidence + running history
         b. arun_parallel_round (Slice C) executes all agents concurrently
         c. Append agent answers to running history
    3. Synthesizer agent (single invocation) consolidates the final history
    4. Return ``DiscussionRunResult`` with full trace + synthesis

Hard guarantees (plan v2 §13.2 #12 #16 #17):
    #12 max_concurrency is per-call; cross-call discussion concurrency cap
        belongs to a separate orchestrator-level semaphore (deferred until
        ``DISCUSSION_AGENT_MAX_CONCURRENCY`` ships)
    #16 EvidencePack is built fresh each call (no reuse cache)
    #17 Agents bind to model/capability policy by default; ``credential_id``
        only takes priority when explicitly pinned
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from evidence_pack import (
    EvidencePack,
    EvidencePackError,
    build_evidence_pack,
)
from model_dispatcher import (
    DispatchCandidate,
    DispatchResult,
    DispatcherError,
    arun_parallel_round,
)
from models.discussion import (
    DiscussionAgentConfig,
    DiscussionAgentTrace,
    DiscussionEvidenceMode,
    DiscussionEvidencePackPayload,
    DiscussionRunConfig,
    DiscussionRunResult,
    DiscussionSynthesis,
    DiscussionSynthesisStrategy,
    DiscussionTurnTrace,
)


logger = logging.getLogger("DiscussionOrchestrator")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DiscussionOrchestratorError(RuntimeError):
    pass


class DiscussionUnsupportedStrategyError(DiscussionOrchestratorError):
    pass


class DiscussionCredentialMissingError(DiscussionOrchestratorError):
    pass


# ---------------------------------------------------------------------------
# Type seams
# ---------------------------------------------------------------------------

# invoke_agent(candidate, prompt) -> answer
InvokeAgentFn = Callable[[DispatchCandidate, str], Awaitable[str]]

# credential_resolver(credential_id) -> dict with provider/model/base_url/api_key/...
CredentialResolverFn = Callable[[str], dict[str, Any]]

# retriever(project_id, query, top_k) -> list[dict]
RetrieverFn = Callable[[str, str, int], list[dict]]


# ---------------------------------------------------------------------------
# Default credential resolver
# ---------------------------------------------------------------------------


def _default_credential_resolver(credential_id: str) -> dict[str, Any]:
    """Resolve a credential_id via RuntimeCredentialStore (Slice A1).

    Returns a dict with provider/model/base_url/api_key/protocol fields.
    """
    from credential_store import (
        CredentialNotFoundError,
        RuntimeCredentialStore,
    )
    store = RuntimeCredentialStore()
    try:
        cred = store.get_internal(credential_id)
    except CredentialNotFoundError as exc:
        raise DiscussionCredentialMissingError(
            f"credential not found: {credential_id}"
        ) from exc
    return {
        "provider": cred.provider,
        "model": cred.model,
        "base_url": cred.base_url,
        "api_key": cred.api_key,
        "protocol": cred.protocol.value,
    }


# ---------------------------------------------------------------------------
# Slot construction
# ---------------------------------------------------------------------------


def _resolve_agent_endpoint(
    agent: DiscussionAgentConfig,
    resolver: CredentialResolverFn,
) -> dict[str, Any]:
    """Resolve provider / model / base_url / api_key for one agent."""
    if agent.llm is not None:
        return {
            "provider": agent.llm.provider,
            "model": agent.llm.model,
            "base_url": agent.llm.base_url,
            "api_key": agent.llm.api_key,
            "protocol": agent.llm.protocol,
        }
    if agent.credential_id:
        return resolver(agent.credential_id)
    raise DiscussionOrchestratorError(
        f"agent {agent.agent_id!r} has neither inline llm nor credential_id"
    )


def _build_candidate(
    agent: DiscussionAgentConfig,
    endpoint: dict[str, Any],
) -> DispatchCandidate:
    return DispatchCandidate(
        candidate_id=f"agent_{agent.agent_id}",
        provider=str(endpoint.get("provider") or "unknown"),
        model=str(endpoint.get("model") or "unknown"),
        base_url=str(endpoint.get("base_url") or ""),
        credential_id=agent.credential_id,
        priority=agent.priority,
        metadata={
            "role": agent.role.value,
            "role_label": agent.role_label,
            "strict_pin": agent.strict_pin,
            **dict(agent.metadata or {}),
        },
        agent_id=agent.agent_id,
        role=agent.role.value,
    )


# ---------------------------------------------------------------------------
# Prompt composition
# ---------------------------------------------------------------------------


def _format_history(history: list[dict[str, Any]]) -> str:
    if not history:
        return "(no prior turns)"
    lines: list[str] = []
    for turn in history:
        for msg in turn.get("messages", []):
            lines.append(
                f"[turn {turn['turn_index']} | {msg['role']} {msg['agent_id']}] "
                f"{msg['content']}"
            )
    return "\n\n".join(lines)


def _format_evidence(evidence: EvidencePack | None, manual: list[str]) -> str:
    if evidence is not None and evidence.snippets:
        return evidence.to_prompt_block()
    if manual:
        joined = "\n\n".join(f"[manual {i+1}] {s}" for i, s in enumerate(manual))
        return joined
    return "(no project evidence)"


def _build_agent_prompt(
    agent: DiscussionAgentConfig,
    *,
    query: str,
    evidence_text: str,
    history: list[dict[str, Any]],
    turn_index: int,
) -> str:
    role_label = agent.role_label or agent.role.value
    sections = [
        f"# Role: {role_label}",
        agent.system_prompt.strip() or "(no extra system prompt)",
        "",
        "# User question",
        query.strip(),
        "",
        "# Evidence",
        evidence_text,
        "",
        "# Discussion history",
        _format_history(history),
        "",
        f"# Your turn ({turn_index + 1}) — respond as {role_label}.",
        "Be concise and ground claims in the evidence above when possible.",
    ]
    return "\n".join(sections)


def _build_synthesis_prompt(
    *,
    query: str,
    evidence_text: str,
    history: list[dict[str, Any]],
    strategy: str,
) -> str:
    return "\n".join([
        "# Role: Synthesizer",
        f"Strategy: {strategy}",
        "",
        "# Original question",
        query.strip(),
        "",
        "# Evidence",
        evidence_text,
        "",
        "# Discussion to synthesize",
        _format_history(history),
        "",
        "# Your task",
        "Synthesize the discussion into a single grounded answer. Highlight "
        "where agents agreed, where they disagreed, and what the evidence "
        "supports. Do not invent facts not in evidence or history.",
    ])


# ---------------------------------------------------------------------------
# Strategy enforcement (TASK-607)
# ---------------------------------------------------------------------------


_ALLOWED_STRATEGIES = {DiscussionSynthesisStrategy.SYNTHESIZE.value}


def _check_strategy(strategy: DiscussionSynthesisStrategy) -> None:
    if strategy.value not in _ALLOWED_STRATEGIES:
        raise DiscussionUnsupportedStrategyError(
            f"synthesis_strategy={strategy.value!r} is modelled but not "
            f"implemented in MVP; supported: {sorted(_ALLOWED_STRATEGIES)}"
        )


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------


def _result_to_trace(
    result: DispatchResult,
    agent: DiscussionAgentConfig,
) -> DiscussionAgentTrace:
    answer = ""
    error: dict[str, Any] | None = None
    if result.success:
        answer = str(result.output or "")
    elif result.error is not None:
        error = result.error.as_dict()
    return DiscussionAgentTrace(
        agent_id=agent.agent_id,
        role=agent.role.value,
        role_label=agent.role_label,
        credential_id=agent.credential_id,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        success=result.success,
        answer=answer,
        error=error,
    )


def _evidence_to_payload(pack: EvidencePack) -> DiscussionEvidencePackPayload:
    return DiscussionEvidencePackPayload(
        pack_id=pack.pack_id,
        pack_version=pack.pack_version,
        project_id=pack.project_id,
        query=pack.query,
        snippets=[s.as_dict() for s in pack.snippets],
        truncated=pack.truncated,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_discussion(
    config: DiscussionRunConfig,
    *,
    invoke_agent: InvokeAgentFn,
    credential_resolver: CredentialResolverFn | None = None,
    retriever: RetrieverFn | None = None,
) -> DiscussionRunResult:
    """Execute a RAG-aware multi-agent discussion.

    ``invoke_agent`` is REQUIRED — production code passes a chat-router-backed
    callable; tests pass a stub. The orchestrator never reaches into the
    chat layer itself, so this module stays cheap to test in isolation.
    """
    _check_strategy(config.synthesis_strategy)
    started = time.perf_counter()
    run_id = f"disc_{uuid.uuid4().hex[:16]}"
    resolver = credential_resolver or _default_credential_resolver

    # ---------- Evidence ----------------------------------------------------
    evidence_pack: EvidencePack | None = None
    if config.evidence_mode == DiscussionEvidenceMode.FROM_PROJECT:
        try:
            evidence_pack = build_evidence_pack(
                config.project_id,
                config.query,
                top_k=config.evidence_top_k,
                retriever=retriever,
            )
        except EvidencePackError as exc:
            raise DiscussionOrchestratorError(
                f"evidence pack build failed: {exc}"
            ) from exc
    evidence_text = _format_evidence(
        evidence_pack,
        list(config.evidence_inline),
    )

    # ---------- Agent slot prep --------------------------------------------
    endpoints: dict[str, dict[str, Any]] = {}
    for agent in config.agent_configs:
        endpoints[agent.agent_id] = _resolve_agent_endpoint(agent, resolver)

    # ---------- Synthesizer pick ------------------------------------------
    synth_id = config.synthesizer_agent_id or config.agent_configs[0].agent_id
    synth_agent = next(a for a in config.agent_configs if a.agent_id == synth_id)
    # All configured agents participate in each debate turn; the synthesizer
    # then runs once more after the final turn to produce the synthesis.
    debate_agents = list(config.agent_configs)

    # ---------- Turns ------------------------------------------------------
    turns: list[DiscussionTurnTrace] = []
    history: list[dict[str, Any]] = []

    for turn_index in range(config.max_turns):
        slots: list[DispatchCandidate] = []
        prompt_for: dict[str, str] = {}
        for agent in debate_agents:
            ep = endpoints[agent.agent_id]
            cand = _build_candidate(agent, ep)
            slots.append(cand)
            prompt_for[agent.agent_id] = _build_agent_prompt(
                agent,
                query=config.query,
                evidence_text=evidence_text,
                history=history,
                turn_index=turn_index,
            )

        async def _wrapped(c: DispatchCandidate) -> str:
            return await invoke_agent(c, prompt_for[c.agent_id])

        try:
            batch = await arun_parallel_round(
                slots,
                _wrapped,
                timeout_seconds=config.timeout_seconds,
                max_concurrency=config.max_concurrency,
            )
        except DispatcherError as exc:
            raise DiscussionOrchestratorError(
                f"dispatcher failure during turn {turn_index}: {exc}"
            ) from exc

        # Map dispatcher results back to agent traces (preserve config order).
        result_by_agent = {r.agent_id: r for r in batch.results}
        agent_traces: list[DiscussionAgentTrace] = []
        turn_messages: list[dict[str, Any]] = []
        for agent in debate_agents:
            r = result_by_agent.get(agent.agent_id)
            if r is None:
                # Should not happen — defensive: synthesize a failure trace.
                agent_traces.append(
                    DiscussionAgentTrace(
                        agent_id=agent.agent_id,
                        role=agent.role.value,
                        role_label=agent.role_label,
                        credential_id=agent.credential_id,
                        provider=endpoints[agent.agent_id].get("provider", ""),
                        model=endpoints[agent.agent_id].get("model", ""),
                        latency_ms=0.0,
                        success=False,
                        error={
                            "error_class": "MissingResult",
                            "message": "dispatcher dropped this agent",
                            "retry_recommended": False,
                        },
                    )
                )
                continue
            trace = _result_to_trace(r, agent)
            agent_traces.append(trace)
            if trace.success:
                turn_messages.append({
                    "agent_id": agent.agent_id,
                    "role": agent.role.value,
                    "content": trace.answer,
                })
        turns.append(DiscussionTurnTrace(
            turn_index=turn_index,
            agent_traces=agent_traces,
        ))
        history.append({"turn_index": turn_index, "messages": turn_messages})

    # ---------- Synthesis -------------------------------------------------
    synth_endpoint = endpoints[synth_id]
    synth_cand = _build_candidate(synth_agent, synth_endpoint)
    synth_prompt = _build_synthesis_prompt(
        query=config.query,
        evidence_text=evidence_text,
        history=history,
        strategy=config.synthesis_strategy.value,
    )
    try:
        synth_text = await asyncio.wait_for(
            invoke_agent(synth_cand, synth_prompt),
            timeout=config.timeout_seconds,
        )
        synthesis = DiscussionSynthesis(
            text=synth_text,
            strategy=config.synthesis_strategy.value,
            synthesizer_agent_id=synth_id,
            synthesizer_provider=synth_cand.provider,
            synthesizer_model=synth_cand.model,
            success=True,
        )
    except Exception as exc:  # noqa: BLE001 — synthesizer is one provider call; any failure (timeout, network, provider-specific exc) must be captured into DiscussionSynthesis.error so the rest of the discussion trace still surfaces to the caller. Re-raising would discard the per-agent traces above.
        synth_msg = str(exc)
        if len(synth_msg) > 256:
            synth_msg = synth_msg[:253] + "..."
        synthesis = DiscussionSynthesis(
            text="",
            strategy=config.synthesis_strategy.value,
            synthesizer_agent_id=synth_id,
            synthesizer_provider=synth_cand.provider,
            synthesizer_model=synth_cand.model,
            success=False,
            error={
                "error_class": type(exc).__name__,
                "message": synth_msg,
                "retry_recommended": isinstance(exc, asyncio.TimeoutError),
            },
        )

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return DiscussionRunResult(
        run_id=run_id,
        project_id=config.project_id,
        query=config.query,
        evidence=_evidence_to_payload(evidence_pack) if evidence_pack else None,
        turns=turns,
        synthesis=synthesis,
        elapsed_ms=elapsed_ms,
    )


__all__ = [
    "CredentialResolverFn",
    "DiscussionCredentialMissingError",
    "DiscussionOrchestratorError",
    "DiscussionUnsupportedStrategyError",
    "InvokeAgentFn",
    "RetrieverFn",
    "run_discussion",
]
