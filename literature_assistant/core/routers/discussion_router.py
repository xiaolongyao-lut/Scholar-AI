# -*- coding: utf-8 -*-
"""Discussion API router for multi-agent discussion."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from discussion_bus import (
    ConversationBus,
    AgentRole,
    MessageType,
    DiscussionSession,
    DiscussionMessage,
)
from agent_roles import get_role_prompt, format_discussion_context
from routers.chat_router import ChatRequest, LLMConfig, chat_ask

router = APIRouter(prefix="/api/discussion", tags=["discussion"])

# Global bus instance
_bus = ConversationBus()


class CreateDiscussionRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    roles: list[AgentRole] = Field(..., min_items=2, max_items=4)
    max_turns: int = Field(default=5, ge=1, le=20)
    llm: LLMConfig | None = None


class CreateDiscussionResponse(BaseModel):
    session_id: str
    topic: str
    roles: list[AgentRole]
    max_turns: int


class DiscussionStatusResponse(BaseModel):
    session_id: str
    topic: str
    status: str
    current_turn: int
    total_messages: int
    synthesis: str | None = None


class DiscussionHistoryResponse(BaseModel):
    session_id: str
    messages: list[dict[str, Any]]


@router.post("/create", response_model=CreateDiscussionResponse)
async def create_discussion(req: CreateDiscussionRequest) -> CreateDiscussionResponse:
    """Create a new multi-agent discussion session."""
    session = _bus.create_session(
        topic=req.topic,
        roles=req.roles,
        max_turns=req.max_turns,
    )
    return CreateDiscussionResponse(
        session_id=session.session_id,
        topic=session.topic,
        roles=session.roles,
        max_turns=session.max_turns,
    )


@router.get("/{session_id}/status", response_model=DiscussionStatusResponse)
async def get_discussion_status(session_id: str) -> DiscussionStatusResponse:
    """Get current status of a discussion session."""
    session = _bus.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    total_messages = sum(len(turn.messages) for turn in session.turns)
    return DiscussionStatusResponse(
        session_id=session.session_id,
        topic=session.topic,
        status=session.status,
        current_turn=len(session.turns),
        total_messages=total_messages,
        synthesis=session.synthesis,
    )


@router.get("/{session_id}/history", response_model=DiscussionHistoryResponse)
async def get_discussion_history(session_id: str) -> DiscussionHistoryResponse:
    """Get message history for a discussion session."""
    session = _bus.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = _bus.get_history(session_id)
    return DiscussionHistoryResponse(
        session_id=session_id,
        messages=[msg.model_dump() for msg in messages],
    )


@router.post("/{session_id}/run")
async def run_discussion_turn(session_id: str) -> dict[str, Any]:
    """Run one turn of discussion (all agents speak once)."""
    session = _bus.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=400, detail="Session is not active")

    history = _bus.get_history(session_id)
    turn_messages: list[DiscussionMessage] = []

    for role in session.roles:
        # Build context for this agent
        system_prompt = get_role_prompt(role)
        context_str = format_discussion_context(
            topic=session.topic,
            history=[{"role": m.role, "content": m.content} for m in history],
            current_role=role,
        )

        # Call LLM
        llm = LLMConfig()  # Use default config
        response = await chat_ask(
            ChatRequest(
                query=f"请根据讨论历史发表你的观点。\n\n{context_str}",
                context=[system_prompt],
                history=[],
                llm=llm,
            )
        )

        # Post message to bus
        msg = _bus.post_message(
            session_id=session_id,
            role=role,
            content=response.answer,
            message_type=MessageType.STATEMENT,
        )
        turn_messages.append(msg)

    # Complete turn
    _bus.complete_turn(session_id)

    return {
        "session_id": session_id,
        "turn_number": len(session.turns),
        "messages": [msg.model_dump() for msg in turn_messages],
        "status": session.status,
    }