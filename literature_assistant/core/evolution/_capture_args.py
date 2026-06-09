"""
Shared dataclass for capture extractors across inspiration, discussion, and runtime capture.

Defines the kwargs payload that extractor modules return and capture-site
hooks splat into EvolutionService.capture(). Centralizing the shape avoids
each extractor declaring a structurally identical dataclass under a different
name (which would block re-exporting via the evolution package facade).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from models.evolution import (
    CandidateMemoryType,
    CandidateRiskLevel,
    CandidateSourceType,
)


@dataclass(frozen=True)
class CaptureCandidateArgs:
    """Kwargs payload ready to splat into EvolutionService.capture()."""

    workspace_id: str
    source_type: CandidateSourceType
    source_id: str
    source_summary: str
    memory_type: CandidateMemoryType
    title: str
    claim: str
    future_use: str
    confidence: float
    project_id: Optional[str]
    source_route: Optional[str]
    evidence_refs: List[Dict[str, Any]]
    risk_level: CandidateRiskLevel
