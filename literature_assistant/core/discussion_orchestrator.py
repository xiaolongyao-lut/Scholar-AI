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
from discussion_convergence import (
    EmbedFn,
    EmbeddingFailure,
    JudgeFailure,
    JudgeParseFailure,
    cosine_similarity,
    embed_turn_texts,
    format_turn_text,
    judge_convergence,
)
from discussion_evidence_trace import (
    CITATION_CONTRACT_SUFFIX,
    build_evidence_ids,
    parse_cited_evidence_ids,
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
    DiscussionConvergenceJudgeCall,
    DiscussionConvergenceJudgeError,
    DiscussionConvergenceTrace,
    DiscussionEvidenceMode,
    DiscussionEvidencePackPayload,
    DiscussionRunConfig,
    DiscussionRunResult,
    DiscussionSynthesis,
    DiscussionSynthesisStrategy,
    DiscussionTurnTrace,
)
from prompts.identity_renderer import render_identity_header  # 2026-05-18 identity injection plan


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
    # Fallback: use default chat config from runtime override + env
    try:
        from model_config_store import chat_store
        from runtime_env import env_value
        api_key = chat_store.get_resolved_field("api_key") or env_value("CHAT_API_KEY", "OPENAI_API_KEY_CHAT", "OPENAI_API_KEY", "ARK_API_KEY") or ""
        base_url = chat_store.get_resolved_field("base_url") or env_value("CHAT_BASE_URL", "OPENAI_BASE_URL", "ARK_BASE_URL") or ""
        model = chat_store.get_resolved_field("model") or env_value("CHAT_MODEL", "OPENAI_MODEL", "ARK_MODEL") or ""
        provider = chat_store.get_resolved_field("provider") or env_value("CHAT_PROVIDER", "OPENAI_PROVIDER", default="DeepSeek") or "DeepSeek"
        if api_key and base_url and model:
            return {
                "provider": provider,
                "model": model,
                "base_url": base_url,
                "api_key": api_key,
                "protocol": "openai_chat",
            }
    except ImportError:
        pass
    raise DiscussionOrchestratorError(
        f"agent {agent.agent_id!r} has neither inline llm nor credential_id, "
        f"and no default chat config is available"
    )


def _build_candidate(
    agent: DiscussionAgentConfig,
    endpoint: dict[str, Any],
) -> DispatchCandidate:
    metadata = {
        "role": agent.role.value,
        "role_label": agent.role_label,
        "strict_pin": agent.strict_pin,
        **dict(agent.metadata or {}),
    }
    # The dispatcher result never serializes metadata; this private field lets
    # router-level invoke factories keep credential_id agents on the same path
    # as inline-LLM agents without leaking secrets to traces.
    if endpoint.get("api_key"):
        metadata["_resolved_api_key"] = str(endpoint["api_key"])
    if endpoint.get("temperature") is not None:
        metadata["temperature"] = endpoint["temperature"]
    if endpoint.get("max_tokens") is not None:
        metadata["max_tokens"] = endpoint["max_tokens"]

    return DispatchCandidate(
        candidate_id=f"agent_{agent.agent_id}",
        provider=str(endpoint.get("provider") or "unknown"),
        model=str(endpoint.get("model") or "unknown"),
        base_url=str(endpoint.get("base_url") or ""),
        credential_id=agent.credential_id,
        priority=agent.priority,
        metadata=metadata,
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


def _format_evidence_with_ids(
    evidence: EvidencePack | None,
    manual: list[str],
) -> tuple[str, list[str]]:
    """Render the evidence block with G2 citation ids and return both.

    When `evidence` is non-empty, snippets are tagged `[E1]`, `[E2]`, ...
    so the per-agent prompt can teach the agent which id to cite. The
    returned `evidence_ids` mirrors `build_evidence_ids(len(snippets))`
    and feeds both the citation contract suffix and the trace payload.

    Manual / empty paths fall back to `_format_evidence` and return an
    empty `evidence_ids` (no citation contract is appended in those
    cases — agents have nothing to cite by id).
    """
    if evidence is not None and evidence.snippets:
        ids = build_evidence_ids(len(evidence.snippets))
        lines: list[str] = []
        for eid, snippet in zip(ids, evidence.snippets):
            header = (
                f"[{eid}] {snippet.source} "
                f"(chunk={snippet.chunk_id} score={snippet.score:.3f})"
            )
            lines.append(header)
            lines.append(snippet.content)
            lines.append("")
        return "\n".join(lines).rstrip(), ids
    return _format_evidence(evidence, manual), []


def _build_agent_prompt(
    agent: DiscussionAgentConfig,
    *,
    query: str,
    evidence_text: str,
    history: list[dict[str, Any]],
    turn_index: int,
    cite_evidence: bool = False,
) -> str:
    role_label = agent.role_label or agent.role.value
    base_system = agent.system_prompt.strip() or "(no extra system prompt)"
    if cite_evidence:
        base_system = base_system + CITATION_CONTRACT_SUFFIX
    identity_header = render_identity_header(
        "discussion",
        context={"turn_index": turn_index},
    )
    sections: list[str] = []
    if identity_header:
        sections.extend([identity_header, ""])
    sections.extend([
        f"# Role: {role_label}",
        base_system,
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
    ])
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


def _evidence_to_payload(
    pack: EvidencePack,
    evidence_ids: list[str],
) -> DiscussionEvidencePackPayload:
    return DiscussionEvidencePackPayload(
        pack_id=pack.pack_id,
        pack_version=pack.pack_version,
        project_id=pack.project_id,
        query=pack.query,
        snippets=[s.as_dict() for s in pack.snippets],
        truncated=pack.truncated,
        evidence_ids=list(evidence_ids),
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
    embed_fn: EmbedFn | None = None,
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
    evidence_text, evidence_ids = _format_evidence_with_ids(
        evidence_pack,
        list(config.evidence_inline),
    )
    cite_evidence = bool(evidence_ids)

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

    # ---------- Auto-stop bookkeeping (Plan D3) ----------------------------
    per_turn_similarity: list[float] = []
    judge_calls: list[DiscussionConvergenceJudgeCall] = []
    judge_errors: list[DiscussionConvergenceJudgeError] = []
    decision_turn_index: int | None = None
    stopped_early = False
    stop_reason: str = "max_turns"
    prev_embedding: list[float] | None = None
    judge_cand: DispatchCandidate | None = None
    if config.auto_stop:
        judge_id = config.convergence_judge_agent_id or synth_id
        judge_agent = next(
            a for a in config.agent_configs if a.agent_id == judge_id
        )
        judge_cand = _build_candidate(judge_agent, endpoints[judge_id])
        if embed_fn is None:
            from chunk_vector_store import batch_embed_texts as _real_embed

            embed_fn = _real_embed

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
                cite_evidence=cite_evidence,
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
            if trace.success and evidence_ids:
                try:
                    trace.cited_evidence_ids = parse_cited_evidence_ids(
                        trace.answer, evidence_ids
                    )
                except Exception:  # noqa: BLE001 — parser is best-effort; never block trace emission on a regex failure.
                    trace.cited_evidence_ids = []
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

        # ----- Auto-stop check (Plan D3) -------------------------------------
        # Skip if disabled OR this is already the final turn (nothing to save).
        if not config.auto_stop or turn_index >= config.max_turns - 1:
            continue
        current_text = format_turn_text(turn_messages)
        current_emb: list[float] | None = None
        if current_text:
            try:
                embedded = await embed_turn_texts(
                    [current_text], embed_fn=embed_fn
                )
                current_emb = embedded[0] if embedded else None
            except EmbeddingFailure as exc:
                cause = exc.__cause__
                judge_errors.append(
                    DiscussionConvergenceJudgeError(
                        turn_index=turn_index,
                        stage="embedding",
                        error_class=type(cause).__name__ if cause else "EmbeddingFailure",
                        message=str(exc)[:512],
                    )
                )
        need_at_least = max(1, config.min_turns - 1)
        if (
            current_emb is not None
            and prev_embedding is not None
            and turn_index >= need_at_least
        ):
            try:
                sim_raw = cosine_similarity(current_emb, prev_embedding)
            except ValueError as exc:
                judge_errors.append(
                    DiscussionConvergenceJudgeError(
                        turn_index=turn_index,
                        stage="embedding",
                        error_class="ValueError",
                        message=str(exc)[:512],
                    )
                )
            else:
                sim = max(0.0, min(1.0, sim_raw))
                per_turn_similarity.append(sim)
                if sim >= config.convergence_threshold and judge_cand is not None:
                    try:
                        outcome = await judge_convergence(
                            history=history,
                            judge_cand=judge_cand,
                            invoke_agent=invoke_agent,
                        )
                        judge_calls.append(
                            DiscussionConvergenceJudgeCall(
                                turn_index=turn_index,
                                similarity=sim,
                                done=outcome.done,
                                confidence=outcome.confidence,
                                reason=outcome.reason,
                            )
                        )
                        if outcome.done:
                            stopped_early = True
                            decision_turn_index = turn_index
                            stop_reason = "converged"
                            break
                    except JudgeFailure as exc:
                        cause = exc.__cause__
                        judge_errors.append(
                            DiscussionConvergenceJudgeError(
                                turn_index=turn_index,
                                stage="judge",
                                error_class=type(cause).__name__ if cause else "JudgeFailure",
                                message=str(exc)[:512],
                            )
                        )
                    except JudgeParseFailure as exc:
                        judge_errors.append(
                            DiscussionConvergenceJudgeError(
                                turn_index=turn_index,
                                stage="parse",
                                error_class="JudgeParseFailure",
                                message=str(exc)[:512],
                            )
                        )
        if current_emb is not None:
            prev_embedding = current_emb

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

    convergence_trace: DiscussionConvergenceTrace | None = None
    if config.auto_stop:
        convergence_trace = DiscussionConvergenceTrace(
            per_turn_similarity=per_turn_similarity,
            judge_calls=judge_calls,
            judge_errors=judge_errors,
            decision_turn_index=decision_turn_index,
        )

    return DiscussionRunResult(
        run_id=run_id,
        project_id=config.project_id,
        query=config.query,
        evidence=(
            _evidence_to_payload(evidence_pack, evidence_ids)
            if evidence_pack
            else None
        ),
        turns=turns,
        synthesis=synthesis,
        elapsed_ms=elapsed_ms,
        stopped_early=stopped_early,
        stop_reason=stop_reason,
        convergence=convergence_trace,
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
