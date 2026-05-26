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
    roles: list[AgentRole] = Field(..., min_length=2, max_length=4)
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


# =========================================================================
# D10-D18: Discussion history endpoints
# =========================================================================

@router.get("/sessions", response_model=list[dict[str, Any]])
async def list_all_discussions(
    start_date: str | None = None,
    end_date: str | None = None,
    topic: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List all discussion sessions with optional filters."""
    sessions = list(_bus._sessions.values())

    # Apply filters
    if topic:
        sessions = [s for s in sessions if topic.lower() in s.topic.lower()]
    if status:
        sessions = [s for s in sessions if s.status == status]

    # Convert to list payload
    result = []
    for session in sessions:
        total_messages = sum(len(turn.messages) for turn in session.turns)
        result.append({
            "session_id": session.session_id,
            "topic": session.topic,
            "status": session.status,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.created_at.isoformat(),
            "turn_count": len(session.turns),
            "message_count": total_messages,
            "roles": [r.value for r in session.roles],
        })

    return result


@router.post("/{session_id}/export", response_model=dict[str, Any])
async def export_discussion(
    session_id: str,
    format: str = "json",
) -> dict[str, Any]:
    """Export discussion to JSON or Markdown."""
    session = _bus.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if format == "json":
        import json
        content = json.dumps(session.model_dump(), indent=2, default=str)
        filename = f"discussion_{session_id}.json"
    elif format == "markdown":
        lines = [f"# Discussion: {session.topic}\n"]
        lines.append(f"**Session ID**: {session_id}\n")
        lines.append(f"**Status**: {session.status}\n")
        lines.append(f"**Created**: {session.created_at}\n\n")

        for turn in session.turns:
            lines.append(f"## Turn {turn.turn_number}\n")
            for msg in turn.messages:
                lines.append(f"**{msg.role.value}**: {msg.content}\n\n")

        if session.synthesis:
            lines.append(f"## Synthesis\n\n{session.synthesis}\n")

        content = "".join(lines)
        filename = f"discussion_{session_id}.md"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    return {
        "session_id": session_id,
        "format": format,
        "content": content,
        "filename": filename,
    }


@router.delete("/{session_id}")
async def delete_discussion(session_id: str) -> dict[str, str]:
    """Delete a discussion session."""
    if session_id not in _bus._sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    del _bus._sessions[session_id]
    return {"message": f"Discussion {session_id} deleted"}


@router.put("/{session_id}/archive")
async def archive_discussion(session_id: str) -> dict[str, str]:
    """Archive a discussion session."""
    session = _bus.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session.status = "archived"
    return {"message": f"Discussion {session_id} archived"}


@router.get("/search", response_model=list[dict[str, Any]])
async def search_discussions(
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search discussions by content."""
    sessions = list(_bus._sessions.values())
    results = []

    query_lower = query.lower()
    for session in sessions:
        # Simple keyword search in topic and messages
        if query_lower in session.topic.lower():
            total_messages = sum(len(turn.messages) for turn in session.turns)
            results.append({
                "session_id": session.session_id,
                "topic": session.topic,
                "excerpt": session.topic[:200],
                "relevance_score": 1.0,
                "created_at": session.created_at.isoformat(),
                "turn_count": len(session.turns),
            })
            continue

        # Search in message content
        for turn in session.turns:
            for msg in turn.messages:
                if query_lower in msg.content.lower():
                    total_messages = sum(len(t.messages) for t in session.turns)
                    results.append({
                        "session_id": session.session_id,
                        "topic": session.topic,
                        "excerpt": msg.content[:200],
                        "relevance_score": 0.8,
                        "created_at": session.created_at.isoformat(),
                        "turn_count": len(session.turns),
                    })
                    break

    return results[:limit]


@router.get("/{session_id}/summary", response_model=dict[str, Any])
async def get_discussion_summary(session_id: str) -> dict[str, Any]:
    """Get discussion summary/synthesis."""
    session = _bus.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    total_messages = sum(len(turn.messages) for turn in session.turns)

    return {
        "session_id": session_id,
        "topic": session.topic,
        "status": session.status,
        "turn_count": len(session.turns),
        "message_count": total_messages,
        "synthesis": session.synthesis,
        "created_at": session.created_at.isoformat(),
    }


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
        from routers.chat_router import _resolve_chat_llm
        llm = _resolve_chat_llm(LLMConfig())
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