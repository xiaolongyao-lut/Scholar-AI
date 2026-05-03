"""
Wiki data models.

All models are frozen dataclasses or TypedDict subclasses to ensure
immutability and JSON-serialisability.  No external runtime dependencies
beyond the standard library.

References:
  - docs/plans/specs/llmwiki-integration-spec.md (LMWR-228..237)
  - docs/plans/specs/llmwiki-evidence-contract-snapshot.md (LMWR-226)
  - OmegaWiki-main: typed entity model (research/concept/claim/experiment)
  - WikiLoom-main: stable_slug + chunk_id idempotency
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Union

try:
    from typing import NotRequired, TypedDict
except ImportError:  # Python 3.8 fallback
    from typing_extensions import NotRequired, TypedDict


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class WikiPageKind(str, Enum):
    """Taxonomy of wiki page types (LMWR-239)."""

    synthesis = "synthesis"    # answer/synthesis page for a query
    concept = "concept"        # background concept / definition
    paper = "paper"            # per-paper summary
    experiment = "experiment"  # experimental result
    question = "question"      # open question / research gap


class WikiPageStatus(str, Enum):
    """Lifecycle states for a wiki page (LMWR-232).

    Allowed transitions (forward only except human-driven):
      draft -> review -> final -> deprecated -> archived
    Also: any state -> archived (by human only).
    """

    draft = "draft"
    review = "review"
    final = "final"
    deprecated = "deprecated"
    archived = "archived"


# Legal forward transitions (auto-allowed)
_AUTO_TRANSITIONS: dict[WikiPageStatus, frozenset[WikiPageStatus]] = {
    WikiPageStatus.draft: frozenset({WikiPageStatus.review}),
    WikiPageStatus.review: frozenset({WikiPageStatus.draft}),  # back to draft allowed
    WikiPageStatus.final: frozenset(),
    WikiPageStatus.deprecated: frozenset(),
    WikiPageStatus.archived: frozenset(),
}

# Transitions that require human confirmation (not enforceable at model layer,
# but documented here for router/service validation)
HUMAN_ONLY_TRANSITIONS: frozenset[tuple[WikiPageStatus, WikiPageStatus]] = frozenset({
    (WikiPageStatus.review, WikiPageStatus.final),
    (WikiPageStatus.final, WikiPageStatus.deprecated),
    (WikiPageStatus.deprecated, WikiPageStatus.archived),
    (WikiPageStatus.draft, WikiPageStatus.archived),
    (WikiPageStatus.review, WikiPageStatus.archived),
    (WikiPageStatus.final, WikiPageStatus.archived),
})


class WikiClaimAuditLevel(str, Enum):
    """Per-claim audit result (LMWR-233)."""

    passed = "passed"
    warning = "warning"
    failed = "failed"
    draft_only = "draft_only"


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9\-]")


def make_stable_slug(title: str, kind: WikiPageKind) -> str:
    """Derive a stable, URL-safe slug from *title* + *kind* (LMWR-240).

    Deterministic: given the same title + kind, always returns the same slug.
    Never includes path separators.
    """
    normalised = unicodedata.normalize("NFKD", title.lower())
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    dash_separated = re.sub(r"[\s_]+", "-", ascii_only)
    slug = _SLUG_RE.sub("", dash_separated).strip("-")
    if not slug:
        slug = "untitled"
    return f"{kind.value}-{slug}"


# ---------------------------------------------------------------------------
# Source reference (wiki-aware extension of EvidenceReference)
# ---------------------------------------------------------------------------


class WikiSourceRef(TypedDict):
    """Wiki-aware evidence reference (LMWR-241).

    Must be convertible from :class:`EvidenceReference` without data loss.
    New wiki-specific fields are ``NotRequired`` to preserve backward compat.
    """

    # ---- required (mirror EvidenceReference) ----
    chunk_id: str
    material_id: str
    text: str
    compressed_text: str
    quote: str
    label: str

    # ---- optional EvidenceReference fields ----
    score: NotRequired[Union[float, str]]
    page: NotRequired[Union[int, str]]
    source: NotRequired[str]
    source_label: NotRequired[str]
    source_labels: NotRequired[list[str]]
    source_hint: NotRequired[str]
    rank: NotRequired[int]
    query_overlap_tokens: NotRequired[list[str]]

    # ---- wiki-specific extensions ----
    citation_target: NotRequired[str]   # e.g. "Author, 2023"
    page_store_path: NotRequired[str]   # relative path in page store


def from_evidence_reference(er: dict[str, Any]) -> WikiSourceRef:
    """Convert an EvidenceReference dict to WikiSourceRef.

    Raises ValueError for any missing required field.
    """
    required = ("chunk_id", "material_id", "text", "compressed_text", "quote", "label")
    missing = [f for f in required if f not in er]
    if missing:
        raise ValueError(f"EvidenceReference missing required fields: {missing}")
    result: WikiSourceRef = {
        "chunk_id": str(er["chunk_id"]),
        "material_id": str(er["material_id"]),
        "text": str(er["text"]),
        "compressed_text": str(er.get("compressed_text") or ""),
        "quote": str(er.get("quote") or ""),
        "label": str(er.get("label") or ""),
    }
    for optional in (
        "score", "page", "source", "source_label", "source_labels",
        "source_hint", "rank", "query_overlap_tokens",
        "citation_target", "page_store_path",
    ):
        if optional in er:
            result[optional] = er[optional]  # type: ignore[literal-required]
    return result


# ---------------------------------------------------------------------------
# Wiki page
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WikiPage:
    """Immutable snapshot of a wiki page (LMWR-242).

    Updating state requires constructing a new instance via :meth:`evolve`.
    """

    stable_slug: str
    kind: WikiPageKind
    status: WikiPageStatus
    title: str
    body: str
    evidence_refs: tuple[WikiSourceRef, ...]  # tuple for hashability / immutability
    source_hashes: tuple[str, ...]            # SHA-256 hashes of source chunks
    created_at_iso: str                        # ISO-8601 UTC
    updated_at_iso: str                        # ISO-8601 UTC
    schema_version: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    def evolve(self, **changes: Any) -> "WikiPage":
        """Return a new WikiPage with *changes* applied (LMWR-243)."""
        current = {
            f.name: getattr(self, f.name)
            for f in self.__dataclass_fields__.values()  # type: ignore[attr-defined]
        }
        current.update(changes)
        return WikiPage(**current)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-roundtrippable dict."""
        return {
            "stable_slug": self.stable_slug,
            "kind": self.kind.value,
            "status": self.status.value,
            "title": self.title,
            "body": self.body,
            "evidence_refs": list(self.evidence_refs),
            "source_hashes": list(self.source_hashes),
            "created_at_iso": self.created_at_iso,
            "updated_at_iso": self.updated_at_iso,
            "schema_version": self.schema_version,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WikiPage":
        """Deserialise from a dict produced by :meth:`to_dict`."""
        return cls(
            stable_slug=d["stable_slug"],
            kind=WikiPageKind(d["kind"]),
            status=WikiPageStatus(d["status"]),
            title=d["title"],
            body=d["body"],
            evidence_refs=tuple(d.get("evidence_refs") or []),
            source_hashes=tuple(d.get("source_hashes") or []),
            created_at_iso=d.get("created_at_iso", ""),
            updated_at_iso=d.get("updated_at_iso", ""),
            schema_version=int(d.get("schema_version", 1)),
            extra=dict(d.get("extra") or {}),
        )


# ---------------------------------------------------------------------------
# Compilation options
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WikiCompilationOptions:
    """Options for the wiki compiler (LMWR-244).

    These are passed per-request; never persisted to disk.
    """

    kind: WikiPageKind
    query: str
    max_source_chunks: int = 10
    min_citation_density: float = 0.95
    dry_run: bool = True             # default: dry run only (no LLM calls)
    force_recompile: bool = False    # skip hash-based skip logic


# ---------------------------------------------------------------------------
# Claim audit result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimAuditResult:
    """Per-claim audit result (LMWR-233)."""

    claim_text: str
    level: WikiClaimAuditLevel
    reason: str
    chunk_ids: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Registry entry (lightweight, not full WikiPage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WikiRegistryEntry:
    """Index row stored in the wiki source/chunk registry (LMWR-245).

    Allows fast lookup of which slugs reference a given chunk_id / material_id.
    """

    stable_slug: str
    kind: str                   # WikiPageKind.value
    status: str                 # WikiPageStatus.value
    title: str
    source_hash: str            # combined SHA-256 of all source_hashes
    updated_at_iso: str
    chunk_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_slug": self.stable_slug,
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "source_hash": self.source_hash,
            "updated_at_iso": self.updated_at_iso,
            "chunk_ids": list(self.chunk_ids),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WikiRegistryEntry":
        return cls(
            stable_slug=d["stable_slug"],
            kind=d["kind"],
            status=d["status"],
            title=d["title"],
            source_hash=d.get("source_hash", ""),
            updated_at_iso=d.get("updated_at_iso", ""),
            chunk_ids=tuple(d.get("chunk_ids") or []),
        )
