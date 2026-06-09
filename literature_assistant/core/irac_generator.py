"""Compatibility facade for IRAC Inspiration generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from inspiration_generator import InspirationGenerator, build_inspiration_generator
from routers.inspiration_router import GenerateSparksRequest, SparkResponse


IRACFrame = Literal["irac"]
IRAC_FRAME: IRACFrame = "irac"


def coerce_irac_request(request: GenerateSparksRequest) -> GenerateSparksRequest:
    """Return a request copy pinned to the IRAC frame.

    Args:
        request: Existing Inspiration generation request.

    Returns:
        A request with ``frame="irac"`` while preserving query, limit, project,
        LLM config, sampling, and project-bias toggle.

    Raises:
        TypeError: If the caller passes a non-request object.
    """

    if not isinstance(request, GenerateSparksRequest):
        raise TypeError("request must be GenerateSparksRequest")
    return request.model_copy(update={"frame": IRAC_FRAME})


@dataclass(frozen=True, slots=True)
class IracInspirationGenerator:
    """Stable entry point for IRAC-shaped Inspiration prompts and local sparks."""

    delegate: InspirationGenerator = field(default_factory=lambda: build_inspiration_generator(IRAC_FRAME))

    def build_prompt(self, query: str, limit: int = 10) -> str:
        """Build the active IRAC JSON-only Inspiration prompt."""

        return self.delegate.build_prompt(query=query, limit=limit, frame=IRAC_FRAME)

    def generate_local(self, request: GenerateSparksRequest) -> list[SparkResponse]:
        """Generate local sparks through the active engine with IRAC frame intent."""

        return self.delegate.generate_local(coerce_irac_request(request))


def build_irac_generator() -> IracInspirationGenerator:
    """Return the IRAC compatibility generator."""

    return IracInspirationGenerator()


def build_irac_prompt(query: str, limit: int = 10) -> str:
    """Build an IRAC prompt without exposing the shared facade object."""

    return build_irac_generator().build_prompt(query=query, limit=limit)


__all__ = [
    "IRAC_FRAME",
    "IRACFrame",
    "IracInspirationGenerator",
    "build_irac_generator",
    "build_irac_prompt",
    "coerce_irac_request",
]
