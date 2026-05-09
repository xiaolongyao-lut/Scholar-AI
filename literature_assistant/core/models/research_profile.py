# -*- coding: utf-8 -*-
"""Pydantic models for user research profile (per-user, persistent)."""

from __future__ import annotations

from datetime import datetime, UTC
from pydantic import BaseModel, Field


class ResearchDirection(BaseModel):
    """L1: research direction index entry (≤50 lines total)."""
    keyword: str = Field(..., max_length=100)
    weight: float = Field(default=1.0, ge=0.1, le=5.0)
    description: str = Field("", max_length=300)
    last_used: datetime | None = None


class ResearchFact(BaseModel):
    """L2: domain entities, terminology, preferences."""
    category: str = Field(..., max_length=50)
    value: str = Field(..., max_length=500)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = Field("user", max_length=50)


class InteractionSOP(BaseModel):
    """L3: user-interaction SOPs (only written when user asks)."""
    name: str = Field(..., max_length=100)
    trigger: str = Field("", max_length=200)
    steps: str = Field("", max_length=2000)
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResearchProfile(BaseModel):
    """Top-level research profile for a single user."""
    directions: list[ResearchDirection] = Field(default_factory=list)
    facts: list[ResearchFact] = Field(default_factory=list)
    sops: list[InteractionSOP] = Field(default_factory=list)
    updated: datetime = Field(default_factory=lambda: datetime.now(UTC))