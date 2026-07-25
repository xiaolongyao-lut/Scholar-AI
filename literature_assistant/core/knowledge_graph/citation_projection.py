"""Project one bounded local citation parse into durable candidate records.

This module is pure: it does not open SQLite, rebuild a graph, retrieve
secondary material, or write Wiki content. The same ``LocalCitationResolution``
objects used by immediate retrieval are converted into an auditable batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from literature_assistant.core.knowledge_graph.citation_models import (
    CitationMatchMethod,
    CitationMention,
    CitesCandidate,
    cites_candidate_from_mention,
)
from literature_assistant.core.local_citation_scope import (
    LocalCitationMatch,
    LocalCitationMention,
    LocalCitationResolution,
)
from literature_assistant.core.models.evidence import PdfAnchorFields


CITATION_EXTRACTOR_VERSION = "reference-section-v1"
CITATION_MARKER_PARSER_VERSION = "citation-marker-v1"
LOCAL_CITATION_RESOLVER_VERSION = "local-citation-v2"
CITATION_SOURCE_VERSION = "selection-source-v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_EXTRACTOR_FINGERPRINT = ""
_PARSER_FINGERPRINT = ""
_RESOLVER_FINGERPRINT = ""


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


_EXTRACTOR_FINGERPRINT = _sha256_json(
    {"component": "reference-section-extractor", "version": CITATION_EXTRACTOR_VERSION}
)
_PARSER_FINGERPRINT = _sha256_json(
    {"component": "citation-marker-parser", "version": CITATION_MARKER_PARSER_VERSION}
)
_RESOLVER_FINGERPRINT = _sha256_json(
    {"component": "local-citation-resolver", "version": LOCAL_CITATION_RESOLVER_VERSION}
)


class CitationSelectionLocator(PdfAnchorFields):
    """One pixel-free selection locator paired with a resolution."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    selection_id: str | None = Field(default=None, max_length=256)
    page: int = Field(ge=1)
    chunk_id: str | None = Field(default=None, max_length=256)

    @field_validator("selection_id", "chunk_id", mode="before")
    @classmethod
    def _trim_optional_id(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


@dataclass(frozen=True, slots=True)
class CitationProjectionBatch:
    """One deterministic batch ready for a transactional store write."""

    batch_id: str
    mentions: tuple[CitationMention, ...]
    candidates: tuple[CitesCandidate, ...]


def _stable_identifier(prefix: str, value: str) -> str:
    normalized = str(value or "").strip()
    if _ID_RE.fullmatch(normalized):
        return normalized
    if not normalized:
        raise ValueError(f"{prefix} identifier must be non-empty")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _match_method(value: str | None) -> CitationMatchMethod:
    normalized = str(value or "").strip()
    if normalized == "doi":
        return "doi"
    if normalized in {"title", "normalized_title"}:
        return "normalized_title"
    if normalized == "author_year":
        return "author_year"
    return "none"


def _source_fingerprint(
    *,
    source_material_id: str,
    locator: CitationSelectionLocator,
    resolution: LocalCitationResolution,
) -> str:
    window = resolution.window
    return _sha256_json(
        {
            "source_material_id": source_material_id,
            "selection_id": locator.selection_id,
            "page": locator.page,
            "chunk_id": locator.chunk_id or (window.anchor_chunk_id if window is not None else None),
            "bbox": locator.bbox,
            "bbox_unit": locator.bbox_unit.value if locator.bbox_unit is not None else None,
            "anchor_text": window.anchor_text if window is not None else None,
            "adjacent_text": window.adjacent_text if window is not None else None,
        }
    )


def _legacy_mentions(resolution: LocalCitationResolution) -> tuple[LocalCitationMention, ...]:
    """Adapt pre-v2 match-only resolutions used by compatibility callers."""

    if resolution.mentions:
        return resolution.mentions
    return tuple(
        LocalCitationMention(
            marker=match.marker,
            outcome="matched",
            reason="unique_project_material",
            reference_text=match.reference_text,
            reference_chunk_id=match.reference_chunk_id,
            reference_page=match.reference_page,
            reference_bbox=match.reference_bbox,
            reference_bbox_unit=match.reference_bbox_unit,
            target_material_id=match.material_id,
            target_material_title=match.material_title,
            match_reason=match.match_reason,
            confidence=match.confidence or 0.75,
            reference_fingerprint=match.reference_fingerprint,
            target_fingerprint=match.target_fingerprint,
        )
        for match in resolution.matches
    )


def _reference_fingerprint(mention: LocalCitationMention) -> str | None:
    if mention.reference_fingerprint:
        return mention.reference_fingerprint
    if not mention.reference_text:
        return None
    return _sha256_json(
        {
            "text": mention.reference_text,
            "page": mention.reference_page,
            "chunk_id": mention.reference_chunk_id,
            "bbox": mention.reference_bbox,
            "bbox_unit": (
                mention.reference_bbox_unit.value
                if mention.reference_bbox_unit is not None
                else None
            ),
        }
    )


def _target_fingerprint(mention: LocalCitationMention) -> str | None:
    if mention.target_fingerprint:
        return mention.target_fingerprint
    if not mention.target_material_id:
        return None
    return _sha256_json(
        {
            "material_id": mention.target_material_id,
            "title": mention.target_material_title,
        }
    )


def _batch_semantics(
    *,
    project_id: str,
    session_id: str,
    turn_id: str,
    source_material_id: str,
    resolutions: Sequence[LocalCitationResolution],
    locators: Sequence[CitationSelectionLocator],
) -> dict[str, object]:
    return {
        "project_id": project_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "source_material_id": source_material_id,
        "resolver_version": LOCAL_CITATION_RESOLVER_VERSION,
        "selections": [
            {
                "locator": locator.model_dump(mode="json"),
                "failure_reason": resolution.failure_reason,
                "window": (
                    {
                        "anchor": resolution.window.anchor_text,
                        "adjacent": resolution.window.adjacent_text,
                        "chunk_id": resolution.window.anchor_chunk_id,
                        "page": resolution.window.page,
                    }
                    if resolution.window is not None
                    else None
                ),
                "mentions": [
                    {
                        "marker": mention.marker,
                        "outcome": mention.outcome,
                        "reason": mention.reason,
                        "reference_text": mention.reference_text,
                        "reference_chunk_id": mention.reference_chunk_id,
                        "reference_page": mention.reference_page,
                        "target_material_id": mention.target_material_id,
                        "match_reason": mention.match_reason,
                    }
                    for mention in _legacy_mentions(resolution)
                ],
            }
            for resolution, locator in zip(resolutions, locators, strict=True)
        ],
    }


def build_citation_projection_batch(
    *,
    project_id: str,
    session_id: str,
    turn_id: str,
    source_material_id: str,
    resolutions: Sequence[LocalCitationResolution],
    locators: Sequence[CitationSelectionLocator],
    created_at: datetime | None = None,
) -> CitationProjectionBatch:
    """Build durable outcomes and directed candidates from one parse snapshot.

    Args:
        project_id: Owning Scholar AI project.
        session_id: SmartRead conversation identity.
        turn_id: Stable answer-turn identity.
        source_material_id: Citing PDF material.
        resolutions: Ordered local citation results already used by retrieval.
        locators: Ordered pixel-free selection locators paired with results.
        created_at: Optional aware timestamp for deterministic tests.

    Returns:
        A deterministic batch. It may contain no records when the bounded
        selection window contains no citation marker and no parser failure.
    """

    resolution_items = tuple(resolutions)
    locator_items = tuple(locators)
    if len(resolution_items) != len(locator_items):
        raise ValueError("resolutions and locators must have the same length")
    if len(resolution_items) > 64:
        raise ValueError("one citation projection accepts at most 64 selections")
    canonical_project_id = _stable_identifier("project", project_id)
    canonical_session_id = _stable_identifier("session", session_id)
    canonical_turn_id = _stable_identifier("turn", turn_id)
    canonical_source_id = _stable_identifier("material", source_material_id)
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must include a timezone")

    semantics = _batch_semantics(
        project_id=canonical_project_id,
        session_id=canonical_session_id,
        turn_id=canonical_turn_id,
        source_material_id=canonical_source_id,
        resolutions=resolution_items,
        locators=locator_items,
    )
    batch_digest = _sha256_json(semantics).removeprefix("sha256:")
    batch_id = f"citation-batch:{batch_digest[:32]}"
    records: list[CitationMention] = []
    candidates: list[CitesCandidate] = []

    for index, (resolution, locator) in enumerate(
        zip(resolution_items, locator_items, strict=True)
    ):
        selection_id = _stable_identifier(
            "selection",
            locator.selection_id or f"{canonical_turn_id}:selection:{index}",
        )
        source_chunk_id = locator.chunk_id or (
            resolution.window.anchor_chunk_id if resolution.window is not None else None
        )
        if source_chunk_id:
            source_chunk_id = _stable_identifier("chunk", source_chunk_id)
        source_fingerprint = _source_fingerprint(
            source_material_id=canonical_source_id,
            locator=locator,
            resolution=resolution,
        )
        local_mentions = list(_legacy_mentions(resolution))
        if resolution.failure_reason:
            local_mentions.append(
                LocalCitationMention(
                    marker="",
                    outcome="failed",
                    reason=resolution.failure_reason,
                )
            )

        for mention_index, local in enumerate(local_mentions):
            mention_digest = _sha256_json(
                {
                    "batch_id": batch_id,
                    "selection_id": selection_id,
                    "mention_index": mention_index,
                    "marker": local.marker,
                    "outcome": local.outcome,
                    "reason": local.reason,
                    "reference_text": local.reference_text,
                    "target_material_id": local.target_material_id,
                }
            ).removeprefix("sha256:")
            mention_id = f"citation-mention:{mention_digest[:32]}"
            matched_or_limited = local.outcome in {"matched", "over_limit"}
            match_method = _match_method(local.match_reason) if matched_or_limited else "none"
            target_material_id = (
                _stable_identifier("material", local.target_material_id)
                if matched_or_limited and local.target_material_id
                else None
            )
            mention = CitationMention(
                project_id=canonical_project_id,
                batch_id=batch_id,
                mention_id=mention_id,
                session_id=canonical_session_id,
                turn_id=canonical_turn_id,
                selection_id=selection_id,
                source_material_id=canonical_source_id,
                marker=local.marker,
                outcome=local.outcome,
                reason=local.reason,
                reference_text=local.reference_text,
                source_page=locator.page,
                source_chunk_id=source_chunk_id,
                source_bbox=locator.bbox,
                source_bbox_unit=locator.bbox_unit,
                reference_page=local.reference_page,
                reference_chunk_id=(
                    _stable_identifier("chunk", local.reference_chunk_id)
                    if local.reference_chunk_id
                    else None
                ),
                reference_number=local.reference_number,
                reference_bbox=(
                    list(local.reference_bbox)
                    if local.reference_bbox is not None
                    else None
                ),
                reference_bbox_unit=local.reference_bbox_unit,
                target_material_id=target_material_id,
                target_material_title=(
                    local.target_material_title if target_material_id is not None else None
                ),
                match_method=match_method,
                confidence=local.confidence if target_material_id is not None else None,
                candidate_material_ids=[
                    _stable_identifier("material", candidate_id)
                    for candidate_id in local.candidate_material_ids
                ],
                source_version=CITATION_SOURCE_VERSION,
                extractor_version=CITATION_EXTRACTOR_VERSION,
                parser_version=CITATION_MARKER_PARSER_VERSION,
                resolver_version=LOCAL_CITATION_RESOLVER_VERSION,
                source_fingerprint=source_fingerprint,
                reference_fingerprint=_reference_fingerprint(local),
                target_fingerprint=(
                    _target_fingerprint(local) if target_material_id is not None else None
                ),
                extractor_fingerprint=_EXTRACTOR_FINGERPRINT,
                parser_fingerprint=_PARSER_FINGERPRINT,
                resolver_fingerprint=_RESOLVER_FINGERPRINT,
                created_at=timestamp,
                updated_at=timestamp,
            )
            records.append(mention)
            if mention.outcome == "matched":
                candidate_digest = _sha256_json(
                    {"mention_id": mention_id, "relation": "cites", "direction": "directed"}
                ).removeprefix("sha256:")
                candidates.append(
                    cites_candidate_from_mention(
                        mention,
                        candidate_id=f"cites-candidate:{candidate_digest[:32]}",
                    )
                )

    return CitationProjectionBatch(
        batch_id=batch_id,
        mentions=tuple(records),
        candidates=tuple(candidates),
    )


__all__ = [
    "CITATION_EXTRACTOR_VERSION",
    "CITATION_MARKER_PARSER_VERSION",
    "CITATION_SOURCE_VERSION",
    "LOCAL_CITATION_RESOLVER_VERSION",
    "CitationProjectionBatch",
    "CitationSelectionLocator",
    "build_citation_projection_batch",
]
