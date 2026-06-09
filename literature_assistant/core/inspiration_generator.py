"""Compatibility facade for IRAC/FinCoT inspiration generation.

The active implementation lives in ``routers.inspiration_router`` and
``inspiration_engine``. This module preserves the historical E1 entrypoint name
without duplicating prompt-frame selection, local generation, or LLM parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from routers.inspiration_router import (
    GenerateSparksRequest,
    InspirationFrame,
    SparkResponse,
    _build_inspiration_prompt,
    _select_inspiration_frame,
    _generate_local_sparks,
    _get_engine,
    _local_spark_to_response,
)

ResolvedInspirationFrame = Literal["irac", "fincot"]


@dataclass(frozen=True, slots=True)
class InspirationGenerator:
    """Stable E1 facade for IRAC/FinCoT inspiration generation.

    Args:
        default_frame: Prompt frame used when callers do not request a frame.
    """

    default_frame: InspirationFrame = "auto"

    def select_frame(self, query: str, frame: InspirationFrame | None = None) -> ResolvedInspirationFrame:
        """Return the resolved IRAC or FinCoT frame for one query."""
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        selected = frame if frame is not None else self.default_frame
        return _select_inspiration_frame(query, selected)

    def build_prompt(self, query: str, limit: int = 10, frame: InspirationFrame | None = None) -> str:
        """Build the JSON-only inspiration prompt for one query.

        Args:
            query: Non-empty research question or topic.
            limit: Maximum spark count, clamped by GenerateSparksRequest.
            frame: Optional explicit frame; ``auto`` selects IRAC/FinCoT by query.

        Returns:
            Prompt text containing the selected IRAC/FinCoT instructions.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        request = GenerateSparksRequest(query=query, limit=limit, frame=frame or self.default_frame)
        return _build_inspiration_prompt(request.query, request.limit, request.frame)

    def generate_local(self, request: GenerateSparksRequest) -> list[SparkResponse]:
        """Generate local non-LLM sparks through the active InspirationEngine."""
        if not isinstance(request, GenerateSparksRequest):
            raise TypeError("request must be GenerateSparksRequest")
        engine = _get_engine()
        return [_local_spark_to_response(spark) for spark in _generate_local_sparks(request, engine)]


def build_inspiration_generator(default_frame: InspirationFrame = "auto") -> InspirationGenerator:
    """Return the stable E1 entrypoint for IRAC/FinCoT inspiration generation."""
    return InspirationGenerator(default_frame=default_frame)

