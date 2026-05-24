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
# History / answer budget (FD-14, 2026-05-21)
# ---------------------------------------------------------------------------
# The per-agent prompt that this orchestrator builds is passed downstream via
# ``ChatRequest.query``, whose hard cap is
# ``literature_assistant.core.routers.chat_router.MAX_CHAT_QUERY_LENGTH = 80_000``.
# That cap covers the **first-turn evidence envelope** only; ``_format_history``
# accumulates prior agent answers across every turn and would otherwise grow
# unbounded (``DISCUSSION_MAX_TURNS_LIMIT = 20`` × 8 agents × ~1 KB answers
# ≈ 160 KB worst case). The two constants below bound the history block so
# multi-turn Discussion never re-triggers the TG-1 ``string_too_long`` failure
# mid-run.
#
# ``MAX_HISTORY_LENGTH`` is a rolling-newest-turns window, not a coverage of
# the theoretical worst case. ``MAX_AGENT_ANSWER_LENGTH`` is enforced
# **write-only** in ``_result_to_trace`` so that legacy stored traces with
# longer answers still load (D-HC-5 backward compatibility); the schema
# ``DiscussionAgentTrace.answer`` field intentionally has no ``max_length``.
MAX_HISTORY_LENGTH = 8_000
MAX_AGENT_ANSWER_LENGTH = 4_000
# FD-14.1 (2026-05-21): cushion subtracted from the dynamic remaining budget
# before passing to _format_history, to absorb separator drift between the
# pre-build length estimate and the final "\n".join output. FD-14.2 adds a
# final assembled-prompt guard so oversized non-history sections fail here
# instead of leaking into ChatRequest validation.
_HISTORY_BUDGET_SAFETY_BUFFER = 500
_TRUNCATION_SUFFIX = "… [truncated]"
_HISTORY_TRUNCATED_NOTICE_TEMPLATE = "[history truncated: {n} earlier turns omitted]"


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


def _format_history(
    history: list[dict[str, Any]],
    max_length: int = MAX_HISTORY_LENGTH,
) -> str:
    # FD-14 (2026-05-21): newest-turns rolling window sized by max_length
    # (defaults to MAX_HISTORY_LENGTH; FD-14.1 allows the caller to pass a
    # tighter dynamic budget when the rest of the prompt is large).
    # The empty-history return is preserved verbatim — downstream prompt framing
    # depends on the "(no prior turns)" sentinel for no-history runs.
    if not history:
        return "(no prior turns)"

    # Floor the budget at 0; negative values (caller starved by a giant
    # non-history prompt) collapse to "truncate everything, keep notice only".
    if max_length < 0:
        max_length = 0

    separator = "\n\n"
    # Format each turn into a complete text block so windowing cuts at turn
    # boundaries (D-HC-1: keep newest complete turns, never mid-turn).
    turn_blocks: list[str] = []
    for turn in history:
        lines: list[str] = []
        for msg in turn.get("messages", []):
            lines.append(
                f"[turn {turn['turn_index']} | {msg['role']} {msg['agent_id']}] "
                f"{msg['content']}"
            )
        turn_blocks.append(separator.join(lines))

    # Accumulate from newest backward until the next turn would exceed budget.
    kept: list[str] = []
    used = 0
    for block in reversed(turn_blocks):
        added = len(block) + (len(separator) if kept else 0)
        if used + added > max_length:
            break
        kept.append(block)
        used += added
    kept.reverse()  # chronological order restored

    dropped = len(turn_blocks) - len(kept)
    if dropped == 0:
        # Non-truncated path is byte-identical to the pre-FD-14 output.
        return separator.join(turn_blocks)

    notice = _HISTORY_TRUNCATED_NOTICE_TEMPLATE.format(n=dropped)
    if kept:
        return notice + separator + separator.join(kept)
    # Every turn body was over budget; keep only the notice so the prompt
    # still signals that history existed (rare; only happens if a single
    # turn body alone exceeds the budget — or the dynamic remaining budget
    # collapsed to ~0 because the non-history prompt is unusually large).
    return notice


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
) -> tuple[str, list[str], list[str]]:
    """Render the evidence block with G2 citation ids and return query / context split.

    Returns ``(legacy_evidence_text_for_prompt, context_items, evidence_ids)``.

    Per FD-13 B2 (2026-05-21), the B-path refactor moves real evidence-pack
    snippets out of the assembled prompt body and into the ``ChatRequest.context``
    transport slot:

    - **Evidence pack present (non-empty snippets)**:
      Each snippet becomes one ``context_items[i]`` entry with its
      ``[E<n>] source (chunk=… score=…)`` header followed by the snippet
      content. The first tuple element is empty (``""``) so the caller knows
      the prompt's ``# Evidence`` section should render a placeholder like
      ``"(provided in context channel)"`` instead of inlining the evidence.
      ``evidence_ids`` mirrors ``build_evidence_ids(len(snippets))`` and is
      still used for the citation contract suffix + parser whitelist.

    - **Manual or empty evidence**:
      Returns ``(legacy_text, [], [])`` — the pre-B-path string-only shape is
      preserved so caller behavior is identical when the discussion has no
      per-snippet ids to thread through ``context[]``.
    """
    if evidence is not None and evidence.snippets:
        ids = build_evidence_ids(len(evidence.snippets))
        context_items: list[str] = []
        for eid, snippet in zip(ids, evidence.snippets):
            header = (
                f"[{eid}] {snippet.source} "
                f"(chunk={snippet.chunk_id} score={snippet.score:.3f})"
            )
            context_items.append(f"{header}\n{snippet.content}")
        return "", context_items, ids
    return _format_evidence(evidence, manual), [], []


def _chat_query_envelope_limit() -> int:
    # Local import keeps chat_router as the single source of truth without
    # creating a module-load dependency from orchestrator -> router.
    from routers.chat_router import MAX_CHAT_QUERY_LENGTH

    return MAX_CHAT_QUERY_LENGTH


def _chat_router_system_text_chars(context_items: list[str]) -> int:
    # FD-13.1 + FD-13.2 (2026-05-21): compute the **exact** size of the
    # system_text block that ``chat_router._build_system_text`` will compose
    # downstream from the env-resolved system_prompt + these context items,
    # so the orchestrator's envelope guard accounts for what the provider
    # actually receives — including any ``CHAT_SYSTEM_PROMPT`` env fallback
    # (codex 6th-pass High).
    #
    # The discussion path never sets ``LLMConfig.system_prompt`` (see
    # ``discussion_advanced_router._default_invoke_agent``), so we pass
    # ``llm=None`` to ``compose_provider_system_text`` — equivalent to the
    # env-fallback branch the chat_ask handler takes. Returning 0 for an
    # empty payload still requires running the resolver, because env may
    # contribute system_text even with empty context_items.
    from routers.chat_router import compose_provider_system_text
    return len(compose_provider_system_text(None, context_items))


def _ensure_payload_within_chat_envelope(
    prompt: str,
    context_items: list[str],
    *,
    prompt_kind: str,
) -> None:
    # FD-14.2 + FD-13.1: the chat envelope must cover **prompt + system_text**
    # because chat_router pushes ``context_items`` through
    # ``_build_system_text`` into the provider's system message. Guarding only
    # ``len(prompt)`` lets B-path payloads sneak past the cap (codex audit
    # 2026-05-21). Total budget is shared between the prompt body and the
    # rendered system_text; if either side is oversized, fail fast here
    # instead of leaking to ChatRequest validation or the provider.
    limit = _chat_query_envelope_limit()
    system_chars = _chat_router_system_text_chars(context_items)
    total = len(prompt) + system_chars
    if total <= limit:
        return
    raise DiscussionOrchestratorError(
        f"{prompt_kind} provider payload exceeds chat envelope: "
        f"prompt={len(prompt)} chars + system_text(context_items)={system_chars} "
        f"chars = {total} > {limit}. Reduce evidence, system prompt, query, "
        "or history before invoking the chat router."
    )


def _build_agent_prompt(
    agent: DiscussionAgentConfig,
    *,
    query: str,
    evidence_text: str,
    history: list[dict[str, Any]],
    turn_index: int,
    cite_evidence: bool = False,
    context_items: list[str] | None = None,
) -> str:
    role_label = agent.role_label or agent.role.value
    base_system = agent.system_prompt.strip() or "(no extra system prompt)"
    if cite_evidence:
        base_system = base_system + CITATION_CONTRACT_SUFFIX
    identity_header = render_identity_header(
        "discussion",
        context={"turn_index": turn_index},
    )
    # FD-14.1 + FD-13.1 (2026-05-21): compute the dynamic remaining budget
    # for the history block. The cap covers prompt **plus** the system_text
    # that chat_router will compose from context_items downstream; otherwise
    # B-path evidence (delivered via ChatRequest.context[]) silently bypasses
    # the FD-14.2 envelope guard.
    # Build the non-history sections first (with a placeholder marker for the
    # history slot), measure their length, and pass the remainder to
    # _format_history as max_length. The cap is also bounded above by
    # MAX_HISTORY_LENGTH so short non-history prompts do not balloon history.
    pre_sections: list[str] = []
    if identity_header:
        pre_sections.extend([identity_header, ""])
    pre_sections.extend([
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
    ])
    post_sections = [
        "",
        f"# Your turn ({turn_index + 1}) — respond as {role_label}.",
        "Be concise and ground claims in the evidence above when possible.",
    ]
    items = context_items or []
    system_text_chars = _chat_router_system_text_chars(items)
    non_history_len = len("\n".join(pre_sections + post_sections))
    remaining_for_history = (
        _chat_query_envelope_limit()
        - non_history_len
        - system_text_chars
        - _HISTORY_BUDGET_SAFETY_BUFFER
    )
    history_budget = max(0, min(MAX_HISTORY_LENGTH, remaining_for_history))
    history_block = _format_history(history, max_length=history_budget)
    sections = pre_sections + [history_block] + post_sections
    prompt = "\n".join(sections)
    _ensure_payload_within_chat_envelope(
        prompt, items, prompt_kind="discussion agent"
    )
    return prompt


def _build_synthesis_prompt(
    *,
    query: str,
    evidence_text: str,
    history: list[dict[str, Any]],
    strategy: str,
    context_items: list[str] | None = None,
) -> str:
    # FD-14.1 + FD-13.1 (2026-05-21): same dynamic-remaining-budget pattern as
    # _build_agent_prompt — synthesis is fed the entire discussion history,
    # which is the largest non-evidence contributor and most likely to push
    # the assembled prompt past the chat envelope. Cap also subtracts the
    # system_text size that chat_router will compose from context_items so
    # the B-path evidence stays inside the envelope.
    pre_sections = [
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
    ]
    post_sections = [
        "",
        "# Your task",
        "Synthesize the discussion into a single grounded answer. Highlight "
        "where agents agreed, where they disagreed, and what the evidence "
        "supports. Do not invent facts not in evidence or history.",
    ]
    items = context_items or []
    system_text_chars = _chat_router_system_text_chars(items)
    non_history_len = len("\n".join(pre_sections + post_sections))
    remaining_for_history = (
        _chat_query_envelope_limit()
        - non_history_len
        - system_text_chars
        - _HISTORY_BUDGET_SAFETY_BUFFER
    )
    history_budget = max(0, min(MAX_HISTORY_LENGTH, remaining_for_history))
    history_block = _format_history(history, max_length=history_budget)
    prompt = "\n".join(pre_sections + [history_block] + post_sections)
    _ensure_payload_within_chat_envelope(
        prompt, items, prompt_kind="discussion synthesis"
    )
    return prompt


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


def _truncate_answer_for_write(text: str) -> str:
    # FD-14 (2026-05-21): write-only cap for DiscussionAgentTrace.answer.
    # Enforced here (orchestrator) instead of as Pydantic Field(max_length=...)
    # on DiscussionAgentTrace.answer, so that legacy artifacts with answers
    # longer than MAX_AGENT_ANSWER_LENGTH still validate on load (D-HC-5).
    if len(text) <= MAX_AGENT_ANSWER_LENGTH:
        return text
    # Truncate to budget minus suffix so the final string is exactly the cap.
    head_len = MAX_AGENT_ANSWER_LENGTH - len(_TRUNCATION_SUFFIX)
    return text[:head_len] + _TRUNCATION_SUFFIX


def _result_to_trace(
    result: DispatchResult,
    agent: DiscussionAgentConfig,
) -> DiscussionAgentTrace:
    answer = ""
    error: dict[str, Any] | None = None
    if result.success:
        answer = _truncate_answer_for_write(str(result.output or ""))
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
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> DiscussionRunResult:
    """Execute a RAG-aware multi-agent discussion.

    ``invoke_agent`` is REQUIRED — production code passes a chat-router-backed
    callable; tests pass a stub. The orchestrator never reaches into the
    chat layer itself, so this module stays cheap to test in isolation.

    ``on_event`` (DSE-021): optional async observer invoked at agent-done,
    turn-done, and synthesis-done milestones. Default None preserves the
    existing single-return contract. Observer exceptions are swallowed and
    logged so a faulty SSE client cannot break the orchestrator.
    """
    _check_strategy(config.synthesis_strategy)
    started = time.perf_counter()
    run_id = f"disc_{uuid.uuid4().hex[:16]}"
    resolver = credential_resolver or _default_credential_resolver

    async def _emit(event: dict[str, Any]) -> None:
        if on_event is None:
            return
        try:
            await on_event(event)
        except Exception:  # noqa: BLE001 — observer must never crash orchestrator
            logger.exception("on_event observer failed for %s", event.get("event"))

    # ---------- Evidence ----------------------------------------------------
    # B7 (0.1.8.2): emit early "started" event so the SSE client can render a
    # progress indicator within ~100ms instead of staring at a blank screen for
    # the full retrieval+first-LLM latency (~5–15s). This event carries run_id
    # for the persistence layer (B1) and the current stage label for the UI.
    await _emit({
        "event": "started",
        "run_id": run_id,
        "stage": "retrieval",
        "agent_count": len(config.agent_configs),
        "max_turns": config.max_turns,
    })

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

    # B7: signal retrieval completion so UI flips from "正在检索证据" to
    # "agent 准备中" before the first LLM call starts.
    await _emit({
        "event": "stage_progress",
        "stage": "agents_prep",
        "evidence_chunk_count": len(evidence_pack.snippets) if evidence_pack else 0,
    })
    evidence_text, context_items, evidence_ids = _format_evidence_with_ids(
        evidence_pack,
        list(config.evidence_inline),
    )
    cite_evidence = bool(evidence_ids)

    # FD-13 B3 (2026-05-21): when evidence pack snippets are present, they
    # ride in ``ChatRequest.context[]`` instead of being inlined into the
    # prompt body. ``evidence_text`` from the formatter is empty in that
    # case; substitute a short placeholder so the prompt's ``# Evidence``
    # section still signals to the agent where the snippets came from.
    if context_items:
        # Local import avoids a circular dep (router imports orchestrator
        # at module load; orchestrator only needs the validator at runtime).
        from routers.discussion_advanced_router import (
            validate_discussion_context_items,
        )
        validate_discussion_context_items(context_items)
        prompt_evidence_text = (
            "(evidence provided via API context channel; "
            "cite by [E:E<n>])"
        )
    else:
        prompt_evidence_text = evidence_text

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
    # ACR-040 ~ ACR-044: accumulator for prior agents' reasoning chains, used
    # to inject a carry-over block into the next agent's prompt when feature
    # flag ``analysis_chain_carryover`` is enabled.
    prior_chain_dicts: list[dict[str, Any]] = []
    carryover_block = ""

    for turn_index in range(config.max_turns):
        slots: list[DispatchCandidate] = []
        prompt_for: dict[str, str] = {}
        for agent in debate_agents:
            ep = endpoints[agent.agent_id]
            cand = _build_candidate(agent, ep)
            # FD-13 B4 (2026-05-21): attach evidence-as-context items to the
            # candidate's metadata so downstream invoke wrappers can lift them
            # into ``ChatRequest.context[]`` without changing the InvokeAgentFn
            # 2-arg signature (avoids breaking ~20 test mocks).
            # FD-13.2 (codex 6th-pass Low, 2026-05-21): underscore-prefix marks
            # this as a private transport payload — model_dispatcher's
            # ``dump_metadata_safe_to_log`` helper strips it before any log /
            # trace dump so evidence text never leaks into operator surfaces.
            if context_items:
                from dataclasses import replace as _dc_replace
                cand = _dc_replace(
                    cand,
                    metadata={**cand.metadata, "_context_items": list(context_items)},
                )
            slots.append(cand)
            base_prompt = _build_agent_prompt(
                agent,
                query=config.query,
                evidence_text=prompt_evidence_text,
                history=history,
                turn_index=turn_index,
                cite_evidence=cite_evidence,
                context_items=context_items,
            )
            if carryover_block:
                # Prepend carry-over reference; budget guard is applied inside
                # the helper (max 3 chains × 600 chars). Heading separator
                # keeps the prior block visually distinct from the live prompt.
                prompt_for[agent.agent_id] = f"{carryover_block}\n\n{base_prompt}"
            else:
                prompt_for[agent.agent_id] = base_prompt

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
            # ACR-030 ~ ACR-034: optionally attach a 6-field reasoning chain
            # per agent. Default off via feature flag — when off, attribute
            # stays None and the trace is byte-identical to today.
            if trace.success:
                trace.analysis_chain = _maybe_build_agent_chain(
                    query=config.query,
                    answer=trace.answer,
                    evidence_text=evidence_text,
                )
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

        # ACR-040 ~ ACR-044: refresh the carry-over block for the next turn.
        # We collect any analysis_chain values produced this turn and let the
        # helper render a compact block; gating is per-flag so default-off
        # callers see an empty string and the prompt path is byte-identical.
        for trace in agent_traces:
            if trace.success and trace.analysis_chain is not None:
                prior_chain_dicts.append(trace.analysis_chain.model_dump())
        carryover_block = _maybe_render_carryover(prior_chain_dicts)

        # DSE-022: emit per-agent events + turn boundary so SSE clients can render progressively.
        for trace in agent_traces:
            await _emit({
                "event": "agent_done",
                "turn_index": turn_index,
                "agent_id": trace.agent_id,
                "trace": trace.model_dump(),
            })
        await _emit({
            "event": "turn_done",
            "turn_index": turn_index,
            "agent_count": len(agent_traces),
        })

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
    # FD-13 B4: same context-items injection as the debate path so the
    # synthesizer also receives evidence via ChatRequest.context[].
    # FD-13.2: same underscore-prefix redaction marker as debate path.
    if context_items:
        from dataclasses import replace as _dc_replace
        synth_cand = _dc_replace(
            synth_cand,
            metadata={**synth_cand.metadata, "_context_items": list(context_items)},
        )
    synth_prompt = _build_synthesis_prompt(
        query=config.query,
        evidence_text=prompt_evidence_text,
        history=history,
        strategy=config.synthesis_strategy.value,
        context_items=context_items,
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

    # DSE-023: emit synthesis milestone (regardless of success/failure).
    await _emit({
        "event": "synthesis_done",
        "synthesis": synthesis.model_dump(),
    })

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


def _maybe_render_carryover(prior_chains: list[dict[str, Any]]) -> str:
    """ACR-040 ~ ACR-044: render carry-over block when flag on, else empty.

    Returns an empty string in three cases (all treated as "no carry-over"):
    - feature flag ``analysis_chain_carryover`` is off
    - helper module is unavailable
    - prior_chains list is empty
    """

    if not prior_chains:
        return ""
    try:
        from feature_flags import is_enabled
    except ImportError:
        return ""
    if not is_enabled("analysis_chain_carryover"):
        return ""
    try:
        from prompts.analysis_chain_helpers import render_carryover_block
    except ImportError:
        return ""
    try:
        return render_carryover_block(prior_chains)
    except Exception:  # noqa: BLE001 — carry-over rendering must never block orchestrator
        logger.exception("analysis_chain_carryover render failed")
        return ""


def _maybe_build_agent_chain(
    *, query: str, answer: str, evidence_text: str
) -> "AnalysisChainPayload | None":
    """ACR-030 ~ ACR-034: optionally attach a reasoning chain per agent trace.

    Returns None when ``analysis_chain_discussion`` feature flag is off so
    callers see byte-identical behavior. Uses the deterministic RAG builder
    (same module that powers ACR Slice 1) — role-aware bias is a TODO for
    the next slice.
    """

    try:
        from feature_flags import is_enabled
    except ImportError:
        return None
    if not is_enabled("analysis_chain_discussion"):
        return None
    try:
        from analysis_chain_rag_builder import build_deterministic
    except ImportError:
        return None
    snippets = [evidence_text] if evidence_text else []
    try:
        return build_deterministic(
            query=query, answer=answer, evidence_snippets=snippets
        )
    except Exception:  # noqa: BLE001 — chain builder must never block trace emission
        logger.exception("analysis_chain_discussion deterministic builder failed")
        return None
