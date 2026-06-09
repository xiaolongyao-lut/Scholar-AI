"""Compatibility facade for FinCoT Inspiration generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from inspiration_generator import InspirationGenerator, build_inspiration_generator
from routers.inspiration_router import GenerateSparksRequest, SparkResponse


FinCoTFrame = Literal["fincot"]
FINCOT_FRAME: FinCoTFrame = "fincot"


def coerce_fincot_request(request: GenerateSparksRequest) -> GenerateSparksRequest:
    """Return a request copy pinned to the FinCoT frame.

    Args:
        request: Existing Inspiration generation request.

    Returns:
        A request with ``frame="fincot"`` while preserving query, limit,
        project, LLM config, sampling, and project-bias toggle.

    Raises:
        TypeError: If the caller passes a non-request object.
    """

    if not isinstance(request, GenerateSparksRequest):
        raise TypeError("request must be GenerateSparksRequest")
    return request.model_copy(update={"frame": FINCOT_FRAME})


@dataclass(frozen=True, slots=True)
class FinCoTInspirationGenerator:
    """Stable entry point for FinCoT-shaped Inspiration prompts and local sparks."""

    delegate: InspirationGenerator = field(default_factory=lambda: build_inspiration_generator(FINCOT_FRAME))

    def build_prompt(self, query: str, limit: int = 10) -> str:
        """Build the active FinCoT JSON-only Inspiration prompt."""

        return self.delegate.build_prompt(query=query, limit=limit, frame=FINCOT_FRAME)

    def generate_local(self, request: GenerateSparksRequest) -> list[SparkResponse]:
        """Generate local sparks through the active engine with FinCoT frame intent."""

        return self.delegate.generate_local(coerce_fincot_request(request))


def build_fincot_generator() -> FinCoTInspirationGenerator:
    """Return the FinCoT compatibility generator."""

    return FinCoTInspirationGenerator()


def build_fincot_prompt(query: str, limit: int = 10) -> str:
    """Build a FinCoT prompt without exposing the shared facade object."""

    return build_fincot_generator().build_prompt(query=query, limit=limit)


__all__ = [
    "FINCOT_FRAME",
    "FinCoTFrame",
    "FinCoTInspirationGenerator",
    "build_fincot_generator",
    "build_fincot_prompt",
    "coerce_fincot_request",
]
