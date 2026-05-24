# -*- coding: utf-8 -*-
"""Advanced (RAG-aware multi-agent) discussion endpoint (Slice D / TASK-605).

Mounted alongside the existing ``/api/discussion/*`` endpoints (which are
preserved). This module adds:

    POST /api/discussion/runs

The endpoint accepts a ``DiscussionRunConfig`` and returns a
``DiscussionRunResult``, delegating execution to ``discussion_orchestrator``.

Default ``invoke_agent`` constructs a ``ChatRequest`` per candidate and calls
``chat_ask``, so behavior is consistent with the existing single-agent path.
Tests inject a stub via ``set_invoke_agent_factory`` so this router is also
unit-testable in isolation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from discussion_orchestrator import (
    DiscussionCredentialMissingError,
    DiscussionOrchestratorError,
    DiscussionUnsupportedStrategyError,
    run_discussion,
)
from model_dispatcher import DispatchCandidate
from models.discussion import DiscussionRunConfig, DiscussionRunResult


logger = logging.getLogger("DiscussionAdvancedRouter")
router = APIRouter(prefix="/api/discussion", tags=["DiscussionAdvanced"])


# ---------------------------------------------------------------------------
# Test-injectable invoke factory
# ---------------------------------------------------------------------------

InvokeAgentFn = Callable[[DispatchCandidate, str], Awaitable[str]]
InvokeAgentFactory = Callable[[DiscussionRunConfig], InvokeAgentFn]


_invoke_agent_factory: InvokeAgentFactory | None = None


def set_invoke_agent_factory(factory: InvokeAgentFactory | None) -> None:
    """Test hook: override the production invoke_agent factory.

    A factory takes the DiscussionRunConfig (so closures can pick up shared
    settings) and returns the actual ``invoke_agent`` async callable.
    """
    global _invoke_agent_factory
    _invoke_agent_factory = factory


# ---------------------------------------------------------------------------
# Discussion-scope evidence-as-context budget (FD-13 B1, 2026-05-21)
# ---------------------------------------------------------------------------
# The B-path refactor moves evidence snippets out of ``ChatRequest.query`` and
# into ``ChatRequest.context: list[str]``. We deliberately enforce the budget
# **here** (discussion call site) instead of on ``ChatRequest.context`` itself
# so that generic ``/chat/ask`` callers (Workbench inline chat, future skills)
# continue to accept arbitrary user-supplied document chunks per D-BP-4.
#
# Math (sized to mirror the FD-14 evidence-pack contract):
#   - MAX_DISCUSSION_CONTEXT_ITEMS = 50        -- matches DiscussionRunConfig.evidence_top_k ceiling.
#   - MAX_DISCUSSION_CONTEXT_ITEM_LENGTH = 1_400
#     -- evidence_pack.DEFAULT_MAX_SNIPPET_CHARS = 1_200 content
#     -- + ``[E1] source (chunk=… score=…)`` header ~100 chars
#     -- + ~100 chars buffer for framing
#
# Raising these requires a separate decision (and possibly a chat envelope
# raise) — they should stay aligned with ``evidence_pack`` upstream caps.
MAX_DISCUSSION_CONTEXT_ITEMS = 50
MAX_DISCUSSION_CONTEXT_ITEM_LENGTH = 1_400


class DiscussionContextBudgetError(DiscussionOrchestratorError):
    """Raised when a discussion-path ``context[]`` exceeds the local budget.

    Surfaced as 422 by the FastAPI handler (same shape as other
    DiscussionOrchestratorError subclasses); fail-fast here keeps oversized
    payloads from leaking into ``ChatRequest`` provider dispatch.
    """


def validate_discussion_context_items(items: list[str]) -> list[str]:
    """Enforce per-item char budget + max item count on a discussion context list.

    Returns the input list unchanged on success so callers can chain:
        ChatRequest(query=q, context=validate_discussion_context_items(ctx), ...)

    Raises ``DiscussionContextBudgetError`` on violation; the caller (orchestrator
    or invoke wrapper) is responsible for catching + downgrading to a trace error
    so the dispatcher records a clean failure instead of crashing the run.
    """
    if len(items) > MAX_DISCUSSION_CONTEXT_ITEMS:
        raise DiscussionContextBudgetError(
            f"discussion context has {len(items)} items, exceeds "
            f"MAX_DISCUSSION_CONTEXT_ITEMS={MAX_DISCUSSION_CONTEXT_ITEMS}"
        )
    for idx, item in enumerate(items):
        if len(item) > MAX_DISCUSSION_CONTEXT_ITEM_LENGTH:
            raise DiscussionContextBudgetError(
                f"discussion context item {idx} has {len(item)} chars, exceeds "
                f"MAX_DISCUSSION_CONTEXT_ITEM_LENGTH={MAX_DISCUSSION_CONTEXT_ITEM_LENGTH}"
            )
    return items


# ---------------------------------------------------------------------------
# Default invoke_agent: hits chat_ask
# ---------------------------------------------------------------------------


async def _default_invoke_agent(candidate: DispatchCandidate, prompt: str) -> str:
    """Invoke the existing chat_ask handler for one candidate.

    The candidate's ``base_url`` / ``provider`` / ``model`` are used directly
    so that per-agent credentials route correctly. The api_key is sourced
    from the DispatchCandidate.metadata['api_key'] which is set by the
    invoke factory below.

    FD-13 B4 (2026-05-21): when the orchestrator attaches
    ``context_items`` to ``candidate.metadata``, lift them into
    ``ChatRequest.context`` so the evidence rides the transport's
    document-context slot instead of being inlined in ``query``. The
    discussion-scope budget was already validated upstream.
    """
    api_key = candidate.metadata.get("api_key", "")
    if not api_key:
        raise DiscussionOrchestratorError(
            f"agent {candidate.agent_id!r}: no api_key on candidate metadata"
        )

    # Local import keeps router-level imports cheap at startup.
    from routers.chat_router import ChatRequest, LLMConfig, chat_ask

    llm = LLMConfig(
        provider=candidate.provider,
        api_key=api_key,
        model=candidate.model,
        base_url=candidate.base_url,
        temperature=float(candidate.metadata.get("temperature", 0.7)),
        max_tokens=int(candidate.metadata.get("max_tokens", 2048)),
    )
    context_items = list(candidate.metadata.get("_context_items") or [])
    req = ChatRequest(query=prompt, context=context_items, history=[], llm=llm)
    response = await chat_ask(req)
    return getattr(response, "answer", "") or ""


def _make_default_invoke_factory() -> InvokeAgentFactory:
    """Build a factory that augments DispatchCandidate metadata with the
    resolved api_key + temperature/max_tokens before each agent runs.

    The orchestrator builds candidates without secrets (DispatchCandidate is
    safe to log). For the chat_ask path we need the api_key plumbed through;
    we attach it via metadata which the wrapper reads.
    """
    def factory(config: DiscussionRunConfig) -> InvokeAgentFn:
        # Build a per-agent endpoint map: agent_id -> {api_key, temperature, max_tokens}.
        endpoint_extras: dict[str, dict[str, Any]] = {}
        for agent in config.agent_configs:
            if agent.llm is not None:
                endpoint_extras[agent.agent_id] = {
                    "api_key": agent.llm.api_key,
                    "temperature": agent.llm.temperature,
                    "max_tokens": agent.llm.max_tokens,
                }
            elif agent.credential_id:
                endpoint_extras[agent.agent_id] = {
                    "api_key": None,  # filled in by credential_resolver in orchestrator
                    "temperature": 0.7,
                    "max_tokens": 2048,
                }
            else:
                # No llm, no credential_id: use default chat config
                from model_config_store import chat_store
                from runtime_env import env_value
                default_key = chat_store.get_resolved_field("api_key") or env_value("CHAT_API_KEY", "OPENAI_API_KEY_CHAT", "OPENAI_API_KEY", "ARK_API_KEY") or ""
                endpoint_extras[agent.agent_id] = {
                    "api_key": default_key,
                    "temperature": 0.7,
                    "max_tokens": 2048,
                }

        async def invoke(candidate: DispatchCandidate, prompt: str) -> str:
            extras = endpoint_extras.get(candidate.agent_id, {})
            # Merge extras into candidate.metadata for the inner call.
            # DispatchCandidate is frozen, so we reconstruct with merged metadata.
            new_metadata = {**candidate.metadata, **{
                k: v for k, v in extras.items() if v is not None
            }}
            # If api_key still missing here (credential_id path), the
            # orchestrator's resolver should have populated metadata via the
            # candidate.api_key path. We surface a clear error.
            if not new_metadata.get("api_key") and candidate.metadata.get("_resolved_api_key"):
                new_metadata["api_key"] = candidate.metadata["_resolved_api_key"]
            from dataclasses import replace as dc_replace
            mutated = dc_replace(candidate, metadata=new_metadata)
            return await _default_invoke_agent(mutated, prompt)

        return invoke

    return factory


def make_mcp_enabled_invoke_factory(
    base_factory: InvokeAgentFactory | None = None,
) -> InvokeAgentFactory:
    """Wrap a base ``InvokeAgentFactory`` so each invocation routes through
    ``McpToolUseRunner`` when the run config carries ``mcp_overrides`` and
    the env flag ``LITERATURE_ENABLE_MCP_TOOLS=1`` is set.

    Phase 4 only honors the run-level ``server_ids`` list — it applies to
    every agent. ``per_agent`` is accepted by the model but ignored here
    (warning logged once per run); a follow-up slice will add per-agent
    enforcement after UX validation.

    Discussion orchestrator code is not modified — the MCP decision lives
    entirely inside the factory wrapper, preserving the orchestrator's
    generic ``invoke_agent`` seam (plan v0.3 §3.2 Q4 / TASK-402).
    """
    base = base_factory or _make_default_invoke_factory()

    def factory(config: DiscussionRunConfig) -> InvokeAgentFn:
        base_invoke = base(config)
        overrides = config.mcp_overrides
        # Local import keeps router-level import cost low when MCP is unused.
        from routers import chat_mcp_integration

        if overrides is None or not chat_mcp_integration.is_mcp_tools_enabled():
            return base_invoke

        if overrides.per_agent:
            logger.warning(
                "discussion mcp_overrides.per_agent supplied but ignored in "
                "Phase 4 (server_ids applies to all agents): %s",
                list(overrides.per_agent.keys()),
            )

        if not overrides.server_ids:
            # Empty list = audit-recorded zero-server run; same default behavior.
            return base_invoke

        async def invoke(candidate: DispatchCandidate, prompt: str) -> str:
            api_key = candidate.metadata.get("api_key") or candidate.metadata.get("_resolved_api_key", "")
            if not api_key:
                raise DiscussionOrchestratorError(
                    f"agent {candidate.agent_id!r}: no api_key on candidate metadata"
                )

            from routers.chat_router import ChatRequest, LLMConfig, chat_ask

            llm = LLMConfig(
                provider=candidate.provider,
                api_key=api_key,
                model=candidate.model,
                base_url=candidate.base_url,
                temperature=float(candidate.metadata.get("temperature", 0.7)),
                max_tokens=int(candidate.metadata.get("max_tokens", 2048)),
            )
            context_items = list(candidate.metadata.get("_context_items") or [])
            req = ChatRequest(
                query=prompt,
                context=context_items,
                history=[],
                llm=llm,
                mcp_server_ids=list(overrides.server_ids),
                mcp_allow_high_risk_tools=overrides.allow_high_risk_tools,
            )
            response = await chat_ask(req)
            return getattr(response, "answer", "") or ""

        return invoke

    return factory


def _get_invoke_factory() -> InvokeAgentFactory:
    if _invoke_agent_factory is not None:
        return _invoke_agent_factory
    # Always wrap the default factory so MCP can be opted in per-run via
    # DiscussionRunConfig.mcp_overrides — the wrapper is a no-op when the
    # env flag is off or the run config has no overrides.
    return make_mcp_enabled_invoke_factory(_make_default_invoke_factory())


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/runs", response_model=DiscussionRunResult)
async def post_discussion_run(config: DiscussionRunConfig) -> DiscussionRunResult:
    """Run a RAG-aware multi-agent discussion."""
    factory = _get_invoke_factory()
    invoke_agent = factory(config)

    try:
        result = await run_discussion(config, invoke_agent=invoke_agent)
    except DiscussionUnsupportedStrategyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DiscussionCredentialMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DiscussionContextBudgetError as exc:
        # FD-13.1 (2026-05-21): per-request budget violation is a 422
        # (Unprocessable Entity) — the client supplied a discussion context
        # that exceeds MAX_DISCUSSION_CONTEXT_ITEMS / MAX_DISCUSSION_CONTEXT_ITEM_LENGTH.
        # Must be caught BEFORE the generic DiscussionOrchestratorError handler
        # below (DiscussionContextBudgetError inherits from it).
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DiscussionOrchestratorError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _schedule_discussion_capture(result)
    return result


# ---------------------------------------------------------------------------
# Streaming endpoint (DSE-020 ~ DSE-026)
# ---------------------------------------------------------------------------


@router.post("/runs/stream")
async def post_discussion_run_stream(config: DiscussionRunConfig) -> StreamingResponse:
    """Stream a RAG-aware multi-agent discussion via SSE.

    Gated by feature flag ``discussion_streaming``. When the flag is off,
    callers should fall back to the non-streaming ``POST /runs`` endpoint
    (this endpoint returns 404).

    SSE events (one JSON object per ``data:`` line):

    - ``{"event": "started", "run_id": "disc_...", "stage": "retrieval", ...}``  (B7/B1)
    - ``{"event": "stage_progress", "stage": "agents_prep", ...}``               (B7)
    - ``{"event": "agent_done", "turn_index": N, "agent_id": "...", "trace": {...}}``
    - ``{"event": "turn_done", "turn_index": N, "agent_count": N}``
    - ``{"event": "synthesis_done", "synthesis": {...}}``
    - ``{"event": "done", "result": {...}}``  (full DiscussionRunResult)
    - ``{"event": "error", "status": <http-like>, "error": "..."}``

    B1 (0.1.8.2): the endpoint pre-registers a ``run_id`` with the task store
    before invoking the orchestrator. Every emitted event is mirrored to the
    store so a subsequent ``GET /runs/{run_id}`` or
    ``POST /runs/{run_id}/stream/resume`` can rehydrate the run state after a
    page reload.

    Discussion capture (evolution candidates) still fires off-path on the
    successful ``done`` event, identical to the non-streaming endpoint.
    """

    try:
        from feature_flags import is_enabled
    except ImportError:
        raise HTTPException(status_code=404, detail="discussion streaming not enabled")
    if not is_enabled("discussion_streaming"):
        raise HTTPException(status_code=404, detail="discussion streaming not enabled")

    # B1: pre-register run_id so events flow into the persistence store.
    import uuid as _uuid
    from discussion_task_store import (
        get_discussion_task_store,
        DiscussionTaskStoreFull,
    )

    run_id = f"disc_{_uuid.uuid4().hex[:16]}"
    store = get_discussion_task_store()
    try:
        store.register(run_id, config=config.model_dump(mode="json"))
    except DiscussionTaskStoreFull as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    factory = _get_invoke_factory()
    invoke_agent = factory(config)

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def _on_event(event: dict[str, Any]) -> None:
        # Mirror to store first so a concurrent GET sees the event even if
        # the SSE consumer disconnects before draining the queue.
        store.append_event(run_id, event)
        await queue.put(event)

    async def _run_task() -> None:
        try:
            result = await run_discussion(
                config,
                invoke_agent=invoke_agent,
                on_event=_on_event,
                run_id=run_id,
            )
            _schedule_discussion_capture(result)
            done_event = {"event": "done", "result": result.model_dump()}
            store.append_event(run_id, done_event)
            await queue.put(done_event)
        except DiscussionUnsupportedStrategyError as exc:
            err_event = {"event": "error", "status": 400, "error": str(exc)}
            store.append_event(run_id, err_event)
            await queue.put(err_event)
        except DiscussionCredentialMissingError as exc:
            err_event = {"event": "error", "status": 404, "error": str(exc)}
            store.append_event(run_id, err_event)
            await queue.put(err_event)
        except DiscussionContextBudgetError as exc:
            err_event = {"event": "error", "status": 422, "error": str(exc)}
            store.append_event(run_id, err_event)
            await queue.put(err_event)
        except DiscussionOrchestratorError as exc:
            err_event = {"event": "error", "status": 500, "error": str(exc)}
            store.append_event(run_id, err_event)
            await queue.put(err_event)
        except asyncio.CancelledError:
            err_event = {"event": "error", "status": 499, "error": "cancelled"}
            store.append_event(run_id, err_event)
            store.mark_terminal(run_id, "cancelled")
            await queue.put(err_event)
            raise
        except Exception as exc:  # noqa: BLE001 — endpoint-level safety net
            err_event = {
                "event": "error",
                "status": 500,
                "error": f"{type(exc).__name__}: {exc}",
            }
            store.append_event(run_id, err_event)
            await queue.put(err_event)
        finally:
            await queue.put(None)

    task = asyncio.create_task(_run_task())

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("event") in ("done", "error"):
                    # Drain remaining sentinel
                    while True:
                        tail = await queue.get()
                        if tail is None:
                            break
                    break
        except asyncio.CancelledError:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _schedule_discussion_capture(result: "DiscussionRunResult") -> None:
    """Opt §1: fire discussion capture off the request path."""

    try:
        from evolution import run_capture_in_background
    except Exception as exc:  # pragma: no cover - evolution package missing
        logger.debug("evolution package unavailable; discussion capture skipped: %s", exc)
        return
    run_capture_in_background(
        _capture_discussion_candidates, result, label="discussion"
    )


def _capture_discussion_candidates(result: "DiscussionRunResult") -> None:
    """Best-effort write of evolution candidates from a discussion run.

    Slice 4a contract:
      - never raises; capture failures degrade to a warning log
      - skipped entirely when evolution.candidate_capture_enabled = false
      - response shape unchanged regardless of outcome
    """

    try:
        from evolution import (
            extract_from_discussion_result,
            get_evolution_service,
            is_candidate_capture_enabled,
        )
    except Exception as exc:  # pragma: no cover - evolution package missing
        logger.debug("evolution package unavailable; discussion capture skipped: %s", exc)
        return

    if not is_candidate_capture_enabled():
        return

    try:
        args_list = extract_from_discussion_result(result)
    except Exception as exc:
        logger.warning("discussion capture extractor failed: %s", exc)
        return
    if not args_list:
        return

    try:
        service = get_evolution_service()
    except Exception as exc:
        logger.warning("evolution service unavailable; discussion capture skipped: %s", exc)
        return

    captured = 0
    for args in args_list:
        try:
            service.capture(
                workspace_id=args.workspace_id,
                source_type=args.source_type,
                source_id=args.source_id,
                source_summary=args.source_summary,
                memory_type=args.memory_type,
                title=args.title,
                claim=args.claim,
                future_use=args.future_use,
                confidence=args.confidence,
                project_id=args.project_id,
                source_route=args.source_route,
                evidence_refs=args.evidence_refs,
                risk_level=args.risk_level,
            )
            captured += 1
        except Exception as exc:
            logger.warning(
                "discussion capture write failed for source %s: %s",
                args.source_id, exc,
            )
    if captured:
        logger.debug(
            "discussion capture: wrote %d candidate(s) from %d eligible row(s)",
            captured, len(args_list),
        )


# ---------------------------------------------------------------------------
# Persistence endpoints (B1 / 0.1.8.2)
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}")
async def get_discussion_run(run_id: str) -> dict[str, Any]:
    """Return the current state for a previously-registered discussion run.

    Used by ``DiscussionContext`` on mount to decide whether to:
    - state in ("pending", "running") → call ``/stream/resume`` to reconnect
    - state in ("completed", "cancelled", "error") → restore from final state
    - 404 → drop any stored ``run_id`` and reset to idle (B1 happy-path on
      first launch / after server restart / after 24h TTL expiry)
    """
    from discussion_task_store import get_discussion_task_store

    snapshot = get_discussion_task_store().get(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return snapshot


@router.post("/runs/{run_id}/stream/resume")
async def resume_discussion_run_stream(run_id: str) -> StreamingResponse:
    """Reconnect to an existing discussion run's event stream.

    Replays all events from the store's event_log (so the client catches up
    on what was emitted while it was disconnected) and then either:
    - if the run is still pending/running: tails the store via polling
      (lightweight; events arrive ≤ ~250ms after they happen)
    - if the run is terminal: closes after replaying

    Replay-based design (vs. attaching to the original asyncio.Queue) keeps
    things simple: a fresh consumer always gets the full event sequence and
    multi-tab reconnect just works.

    Gated by the same ``discussion_streaming`` feature flag as the original
    POST /runs/stream endpoint.
    """
    try:
        from feature_flags import is_enabled
    except ImportError:
        raise HTTPException(status_code=404, detail="discussion streaming not enabled")
    if not is_enabled("discussion_streaming"):
        raise HTTPException(status_code=404, detail="discussion streaming not enabled")

    from discussion_task_store import get_discussion_task_store

    store = get_discussion_task_store()
    snapshot = store.get(run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")

    async def event_generator():
        last_index = 0
        # Backlog replay loop: drain store's event_log; then if still running,
        # keep polling for new appends.
        while True:
            events = store.get_event_log(run_id, from_index=last_index)
            for event in events:
                last_index += 1
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                kind = event.get("event")
                if kind in ("done", "error"):
                    return
            # Re-check run state; if terminal but no done/error emitted (edge
            # case: marked terminal via mark_terminal without event log), bail.
            current = store.get(run_id)
            if current is None:
                return
            if current["state"] in ("completed", "cancelled", "error"):
                # Synthesize a closing event if the event_log didn't end with one
                tail = {
                    "event": "error" if current["state"] == "error" else "done",
                    "status": 200 if current["state"] != "error" else 500,
                    "error": current.get("error") or "",
                    "final_state": current["state"],
                }
                yield f"data: {json.dumps(tail, ensure_ascii=False)}\n\n"
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = [
    "router",
    "set_invoke_agent_factory",
    "make_mcp_enabled_invoke_factory",
]
