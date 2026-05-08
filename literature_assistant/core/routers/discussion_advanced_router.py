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

import logging
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException

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
# Default invoke_agent: hits chat_ask
# ---------------------------------------------------------------------------


async def _default_invoke_agent(candidate: DispatchCandidate, prompt: str) -> str:
    """Invoke the existing chat_ask handler for one candidate.

    The candidate's ``base_url`` / ``provider`` / ``model`` are used directly
    so that per-agent credentials route correctly. The api_key is sourced
    from the DispatchCandidate.metadata['api_key'] which is set by the
    invoke factory below.
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
    req = ChatRequest(query=prompt, context=[], history=[], llm=llm)
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
        # For credential_id agents, the orchestrator's credential_resolver provides
        # api_key on the resolved endpoint dict. For inline LLM agents the api_key
        # is on the agent.llm.
        endpoint_extras: dict[str, dict[str, Any]] = {}
        for agent in config.agent_configs:
            if agent.llm is not None:
                endpoint_extras[agent.agent_id] = {
                    "api_key": agent.llm.api_key,
                    "temperature": agent.llm.temperature,
                    "max_tokens": agent.llm.max_tokens,
                }
            else:
                endpoint_extras[agent.agent_id] = {
                    "api_key": None,  # filled in by credential_resolver in orchestrator
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


def _get_invoke_factory() -> InvokeAgentFactory:
    return _invoke_agent_factory or _make_default_invoke_factory()


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
    except DiscussionOrchestratorError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result


__all__ = ["router", "set_invoke_agent_factory"]
