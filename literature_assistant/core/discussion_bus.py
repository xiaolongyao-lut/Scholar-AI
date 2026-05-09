# -*- coding: utf-8 -*-
"""CCB (Conversation Communication Bus) for multi-agent discussion.

Implements a message bus where agents exchange structured messages in turns.
Each agent has a role (proponent/opponent/reviewer) and can access shared context.
"""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    PROPONENT = "proponent"
    OPPONENT = "opponent"
    REVIEWER = "reviewer"
    MODERATOR = "moderator"


class MessageType(str, Enum):
    STATEMENT = "statement"
    QUESTION = "question"
    RESPONSE = "response"
    SYNTHESIS = "synthesis"


class DiscussionMessage(BaseModel):
    """Single message in a discussion."""
    id: str = Field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:12]}")
    role: AgentRole
    message_type: MessageType
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscussionTurn(BaseModel):
    """One turn in the discussion (all agents speak once)."""
    turn_number: int
    messages: list[DiscussionMessage] = Field(default_factory=list)
    completed: bool = False


class DiscussionSession(BaseModel):
    """Complete discussion session state."""
    session_id: str = Field(default_factory=lambda: f"disc-{uuid.uuid4().hex[:12]}")
    topic: str
    roles: list[AgentRole]
    turns: list[DiscussionTurn] = Field(default_factory=list)
    max_turns: int = 5
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "active"
    synthesis: str | None = None


class ConversationBus:
    """Message bus for multi-agent discussion."""

    def __init__(self):
        self._sessions: dict[str, DiscussionSession] = {}

    def create_session(
        self,
        topic: str,
        roles: list[AgentRole],
        max_turns: int = 5,
    ) -> DiscussionSession:
        """Create a new discussion session."""
        if len(roles) < 2:
            raise ValueError("Discussion requires at least 2 roles")
        if max_turns < 1 or max_turns > 20:
            raise ValueError("max_turns must be between 1 and 20")

        session = DiscussionSession(
            topic=topic,
            roles=roles,
            max_turns=max_turns,
        )
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> DiscussionSession | None:
        """Retrieve a discussion session."""
        return self._sessions.get(session_id)

    def post_message(
        self,
        session_id: str,
        role: AgentRole,
        content: str,
        message_type: MessageType = MessageType.STATEMENT,
        metadata: dict[str, Any] | None = None,
    ) -> DiscussionMessage:
        """Post a message to the discussion."""
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        if session.status != "active":
            raise ValueError(f"Session {session_id} is not active")

        msg = DiscussionMessage(
            role=role,
            message_type=message_type,
            content=content,
            metadata=metadata or {},
        )

        # Add to current turn or create new turn
        if not session.turns or session.turns[-1].completed:
            session.turns.append(DiscussionTurn(turn_number=len(session.turns) + 1))

        session.turns[-1].messages.append(msg)
        return msg

    def complete_turn(self, session_id: str) -> bool:
        """Mark current turn as completed."""
        session = self._sessions.get(session_id)
        if session is None or not session.turns:
            return False

        current_turn = session.turns[-1]
        current_turn.completed = True

        # Check if max turns reached
        if len(session.turns) >= session.max_turns:
            session.status = "completed"

        return True

    def get_history(self, session_id: str, last_n_turns: int | None = None) -> list[DiscussionMessage]:
        """Get message history for context."""
        session = self._sessions.get(session_id)
        if session is None:
            return []

        all_messages: list[DiscussionMessage] = []
        turns_to_include = session.turns if last_n_turns is None else session.turns[-last_n_turns:]

        for turn in turns_to_include:
            all_messages.extend(turn.messages)

        return all_messages

    def set_synthesis(self, session_id: str, synthesis: str) -> bool:
        """Set final synthesis for the discussion."""
        session = self._sessions.get(session_id)
        if session is None:
            return False

        session.synthesis = synthesis
        session.status = "synthesized"
        return True