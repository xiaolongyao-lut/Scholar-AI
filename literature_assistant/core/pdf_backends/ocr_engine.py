# -*- coding: utf-8 -*-
"""Typed OCR engine contracts for optional PDF image-to-text providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, runtime_checkable


OcrPolicy = Literal["auto", "none", "engine"]
OcrReadinessStatus = Literal[
    "ready",
    "dependency_missing",
    "configuration_required",
    "adapter_not_wired",
    "platform_unsupported",
    "unavailable",
]


@dataclass(frozen=True)
class OcrImageRegion:
    """Located OCR content within one rendered page image.

    Args:
        markdown: Non-empty searchable text or Markdown for the region.
        bbox: Normalized ``(x, y, width, height)`` rectangle. Coordinates are
            ratios of the rendered page dimensions and must remain inside it.
        block_type: Structural type projected to ``StructuredBlock``.
    """

    markdown: str
    bbox: tuple[float, float, float, float]
    block_type: str = "Text"

    def __post_init__(self) -> None:
        """Reject malformed region data before it reaches chunk locators."""

        if not isinstance(self.markdown, str):
            raise TypeError("markdown must be a string")
        if not self.markdown.strip():
            raise ValueError("markdown must be non-empty")
        if not isinstance(self.bbox, tuple) or len(self.bbox) != 4:
            raise TypeError("bbox must be a four-number tuple")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in self.bbox
        ):
            raise TypeError("bbox must contain only finite numbers")
        bbox = tuple(float(value) for value in self.bbox)
        if not all(isfinite(value) for value in bbox):
            raise ValueError("bbox must contain only finite numbers")
        x, y, width, height = bbox
        if (
            x < 0.0
            or y < 0.0
            or width <= 0.0
            or height <= 0.0
            or x > 1.0
            or y > 1.0
            or x + width > 1.0001
            or y + height > 1.0001
        ):
            raise ValueError("bbox must be a positive normalized rectangle inside the page")
        if not isinstance(self.block_type, str) or not self.block_type.strip():
            raise ValueError("block_type must be a non-empty string")
        if len(self.block_type.strip()) > 80:
            raise ValueError("block_type must be 80 characters or fewer")
        object.__setattr__(self, "bbox", bbox)


@dataclass(frozen=True)
class OcrImageResult:
    """Optional layout-aware result for one rendered page image.

    Args:
        text: Full searchable page text. Empty text is valid for blank pages.
        regions: Located page regions. Legacy engines may omit this capability
            and continue returning only text from ``ocr_image``.
    """

    text: str
    regions: tuple[OcrImageRegion, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate values crossing an OCR adapter boundary."""

        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not isinstance(self.regions, tuple):
            raise TypeError("regions must be a tuple")
        if not all(isinstance(region, OcrImageRegion) for region in self.regions):
            raise TypeError("regions must contain only OcrImageRegion values")


@dataclass(frozen=True)
class OcrEngineHealth:
    """Health-check result returned by an OCR engine.

    Args:
        ok: Whether the engine can be used for OCR with the supplied config.
        detail: Human-readable diagnostic without secrets or raw file paths.
        latency_ms: Optional local probe latency; absent when no probe ran.
        engine: Stable engine id.
        readiness_status: Machine-readable local readiness state.
        readiness_blockers: Bounded non-secret blockers for unavailable engines.
        next_safe_local_actions: Bounded recovery/proof actions safe to run
            locally without uploading documents or changing credentials.
    """

    ok: bool
    detail: str
    engine: str
    latency_ms: float | None = None
    readiness_status: OcrReadinessStatus = "ready"
    readiness_blockers: tuple[str, ...] = field(default_factory=tuple)
    next_safe_local_actions: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable health payload."""

        return {
            "ok": self.ok,
            "detail": self.detail,
            "engine": self.engine,
            "latency_ms": self.latency_ms,
            "readiness_status": self.readiness_status,
            "readiness_blockers": list(self.readiness_blockers),
            "next_safe_local_actions": list(self.next_safe_local_actions),
        }


@dataclass(frozen=True)
class OcrEngineInfo:
    """Public metadata for one registered OCR engine.

    Args:
        name: Stable engine id used by config and API payloads.
        display_name: User-facing short name.
        engine_type: ``local`` or ``remote``.
        available: Runtime availability after dependency/platform/key probes.
        requires_network: Whether OCR may upload image/PDF content.
        unavailable_reason: Bounded reason when ``available`` is false.
        readiness_status: Machine-readable local readiness state.
        readiness_blockers: Bounded non-secret blockers for unavailable engines.
        next_safe_local_actions: Bounded recovery/proof actions safe to run
            locally without uploading documents or changing credentials.
    """

    name: str
    display_name: str
    engine_type: Literal["local", "remote"]
    available: bool
    requires_network: bool
    unavailable_reason: str | None = None
    readiness_status: OcrReadinessStatus = "ready"
    readiness_blockers: tuple[str, ...] = field(default_factory=tuple)
    next_safe_local_actions: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable metadata payload."""

        return {
            "name": self.name,
            "display_name": self.display_name,
            "engine_type": self.engine_type,
            "available": self.available,
            "requires_network": self.requires_network,
            "unavailable_reason": self.unavailable_reason,
            "readiness_status": self.readiness_status,
            "readiness_blockers": list(self.readiness_blockers),
            "next_safe_local_actions": list(self.next_safe_local_actions),
        }


@dataclass(frozen=True)
class OcrRuntimeConfig:
    """Resolved OCR runtime selection.

    Args:
        policy: ``auto`` by default; ``none`` disables OCR; ``engine`` requires
            a concrete engine id.
        engine: Optional engine id selected by user/env/config.
        language: OCR language tag or engine-specific language code.
        source: Where the decisive selection came from.
        engine_config: Engine-specific options with secrets redacted at API
            boundaries.
    """

    policy: OcrPolicy = "auto"
    engine: str | None = None
    language: str = "en"
    source: Literal["default", "config", "env"] = "default"
    engine_config: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class OcrEngine(Protocol):
    """Protocol implemented by optional OCR providers.

    Engines receive rendered page images, not PDF files. PDF page
    classification and rendering stay in the ingestion layer so each provider
    remains a small image-to-text adapter.
    """

    name: str
    display_name: str
    engine_type: Literal["local", "remote"]
    requires_network: bool

    def is_available(self) -> bool:
        """Return whether dependencies, platform support, and config exist."""
        ...

    def unavailable_reason(self) -> str | None:
        """Return a bounded user-facing reason when unavailable."""
        ...

    def readiness_status(self) -> OcrReadinessStatus:
        """Return the engine readiness class without probing page content."""
        ...

    def readiness_blockers(self) -> tuple[str, ...]:
        """Return bounded blockers for unavailable engines."""
        ...

    def ocr_image(self, image: bytes | Path, *, language: str = "en") -> str:
        """Extract text from one rendered page image.

        Args:
            image: PNG/JPEG bytes or a local path to a rendered image.
            language: OCR language tag or engine-specific language string.

        Returns:
            Extracted text. Empty string is allowed for blank pages.
        """
        ...

    def health_check(self) -> OcrEngineHealth:
        """Return a lightweight readiness result without uploading content."""
        ...
