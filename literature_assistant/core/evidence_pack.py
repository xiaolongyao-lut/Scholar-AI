"""EvidencePack interface (Slice B / DEC-003a / DEC-003b / Hard Constraint #16).

A pure data-shaping layer over the existing project chunk retriever. Returns a
versioned, deterministic ``EvidencePack`` artifact for downstream consumers
(Slice C dispatcher, Slice D discussion orchestrator).

Hard guarantees (plan v2 §13.2 #16):
    - No LLM call inside this module.
    - No persistent reuse cache. Each ``build_evidence_pack`` call re-runs
      retrieval. ``dump_evidence_pack`` writes a debug/replay artifact only,
      never read back as a cache.
    - Versioned pack_id: changing ``EVIDENCE_PACK_VERSION`` intentionally
      invalidates every replay artifact.

Replay model:
    Two calls with the same ``(version, project_id, normalized_query, top_k,
    max_snippet_chars, deterministic retriever output)`` produce the same
    ``pack_id``. Production retrievers are not perfectly deterministic; the
    ``pack_id`` is therefore the **observed** identity of a returned pack, not
    a content-addressed cache key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from project_paths import runtime_state_path


logger = logging.getLogger("EvidencePack")


EVIDENCE_PACK_VERSION = "v1"
DEFAULT_TOP_K = 8
DEFAULT_MAX_SNIPPET_CHARS = 1200
EVIDENCE_PACK_DUMP_SUBDIR = "evidence_packs"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EvidencePackError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceSnippet:
    chunk_id: str
    content: str
    source: str
    score: float
    material_id: str = ""
    section_path: str = ""
    source_labels: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "source": self.source,
            "score": self.score,
            "material_id": self.material_id,
            "section_path": self.section_path,
            "source_labels": list(self.source_labels),
        }


@dataclass(frozen=True)
class EvidencePack:
    pack_id: str
    pack_version: str
    project_id: str
    query: str
    top_k_requested: int
    created_at: str
    snippets: tuple[EvidenceSnippet, ...]
    truncated: bool
    diagnostic: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "project_id": self.project_id,
            "query": self.query,
            "top_k_requested": self.top_k_requested,
            "created_at": self.created_at,
            "snippets": [s.as_dict() for s in self.snippets],
            "truncated": self.truncated,
            "diagnostic": dict(self.diagnostic),
        }

    def to_prompt_block(self) -> str:
        """Render snippets as a numbered evidence block suitable for prompts.

        No truncation here — caller chose ``max_snippet_chars`` at build time.
        """
        if not self.snippets:
            return "(no project evidence)"
        lines: list[str] = []
        for i, s in enumerate(self.snippets, start=1):
            header = f"[{i}] {s.source} (chunk={s.chunk_id} score={s.score:.3f})"
            lines.append(header)
            lines.append(s.content)
            lines.append("")
        return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_query(query: str) -> str:
    if not isinstance(query, str):
        raise EvidencePackError("query must be a string")
    cleaned = _WHITESPACE_RE.sub(" ", query.strip())
    if not cleaned:
        raise EvidencePackError("query must be a non-empty string")
    return cleaned


def _validate_project_id(project_id: str) -> str:
    if not isinstance(project_id, str) or not project_id.strip():
        raise EvidencePackError("project_id must be a non-empty string")
    return project_id.strip()


def _validate_top_k(top_k: int) -> int:
    if not isinstance(top_k, int) or top_k < 1:
        raise EvidencePackError("top_k must be a positive integer")
    if top_k > 200:
        raise EvidencePackError("top_k > 200 rejected as runaway request")
    return top_k


def _validate_max_chars(max_snippet_chars: int) -> int:
    if not isinstance(max_snippet_chars, int) or max_snippet_chars < 64:
        raise EvidencePackError("max_snippet_chars must be >= 64")
    return max_snippet_chars


def _extract_chunk_content(chunk: dict) -> str:
    return str(
        chunk.get("content")
        or chunk.get("raw_content")
        or chunk.get("text")
        or chunk.get("source_text")
        or ""
    ).strip()


def _extract_chunk_source(chunk: dict) -> str:
    return str(
        chunk.get("title")
        or chunk.get("source_relative_path")
        or chunk.get("material_id")
        or chunk.get("chunk_id")
        or "project_chunk"
    ).strip()


def _extract_chunk_id(chunk: dict, fallback_index: int) -> str:
    cid = chunk.get("chunk_id") or chunk.get("id")
    if cid:
        return str(cid)
    # Stable fallback so the same input order yields the same id.
    return f"anonymous_{fallback_index}"


def _extract_section_path(chunk: dict) -> str:
    return str(chunk.get("section_path") or chunk.get("section") or "").strip()


def _extract_source_labels(chunk: dict) -> tuple[str, ...]:
    raw = chunk.get("source_labels") or []
    if isinstance(raw, (list, tuple)):
        return tuple(str(x) for x in raw if x)
    return ()


def _extract_score(chunk: dict) -> float:
    raw = chunk.get("score")
    if raw is None:
        raw = chunk.get("hybrid_score") or chunk.get("rerank_score") or 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _default_retriever(project_id: str, query: str, top_k: int) -> list[dict]:
    """Lazy-import the project chunk retriever so this module stays cheap."""
    from routers.resources_router import search_project_chunks_for_query
    return search_project_chunks_for_query(
        project_id=project_id, query=query, top_k=top_k
    )


def _build_pack_id(
    *,
    version: str,
    project_id: str,
    normalized_query: str,
    top_k: int,
    max_snippet_chars: int,
    snippets: list[EvidenceSnippet],
) -> str:
    """Deterministic id over (version + retrieval params + observed content).

    Two calls returning the same ranked snippet contents produce the same id.
    """
    parts = [
        version,
        project_id,
        normalized_query,
        str(top_k),
        str(max_snippet_chars),
    ]
    for s in snippets:
        parts.append(s.chunk_id)
        parts.append(f"{s.score:.6f}")
        parts.append(hashlib.sha256(s.content.encode("utf-8")).hexdigest())
    material = "\x00".join(parts).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_evidence_pack(
    project_id: str,
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    max_snippet_chars: int = DEFAULT_MAX_SNIPPET_CHARS,
    retriever: Callable[[str, str, int], list[dict]] | None = None,
) -> EvidencePack:
    """Run project chunk retrieval and shape it into a versioned EvidencePack.

    No LLM call. No persistent reuse cache. ``retriever`` is a test seam — by
    default the project chunk retriever from ``resources_router`` is used.

    The returned snippets are sorted by descending score, then by ``chunk_id``
    ascending, so any tie-break is stable across runs.
    """
    project_id = _validate_project_id(project_id)
    normalized_query = _normalize_query(query)
    top_k = _validate_top_k(top_k)
    max_snippet_chars = _validate_max_chars(max_snippet_chars)

    fetch = retriever or _default_retriever
    raw = fetch(project_id, normalized_query, top_k)
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise EvidencePackError(
            f"retriever must return list[dict]; got {type(raw).__name__}"
        )

    snippets: list[EvidenceSnippet] = []
    truncated = False
    for idx, chunk in enumerate(raw):
        if not isinstance(chunk, dict):
            continue
        content = _extract_chunk_content(chunk)
        if not content:
            continue
        if len(content) > max_snippet_chars:
            content = content[:max_snippet_chars].rstrip() + "…"
            truncated = True
        snippets.append(
            EvidenceSnippet(
                chunk_id=_extract_chunk_id(chunk, idx),
                content=content,
                source=_extract_chunk_source(chunk),
                score=_extract_score(chunk),
                material_id=str(chunk.get("material_id") or "").strip(),
                section_path=_extract_section_path(chunk),
                source_labels=_extract_source_labels(chunk),
            )
        )

    snippets.sort(key=lambda s: (-s.score, s.chunk_id))
    if len(snippets) > top_k:
        snippets = snippets[:top_k]
        truncated = True

    pack_id = _build_pack_id(
        version=EVIDENCE_PACK_VERSION,
        project_id=project_id,
        normalized_query=normalized_query,
        top_k=top_k,
        max_snippet_chars=max_snippet_chars,
        snippets=snippets,
    )

    return EvidencePack(
        pack_id=pack_id,
        pack_version=EVIDENCE_PACK_VERSION,
        project_id=project_id,
        query=normalized_query,
        top_k_requested=top_k,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        snippets=tuple(snippets),
        truncated=truncated,
        diagnostic={
            "raw_chunk_count": len(raw),
            "kept_chunk_count": len(snippets),
            "max_snippet_chars": max_snippet_chars,
        },
    )


def dump_evidence_pack(pack: EvidencePack, dest: Path | None = None) -> Path:
    """Persist a pack as JSON for debug / replay only.

    Hard Constraint #16: this is NOT a reuse cache. ``build_evidence_pack``
    never reads these dumps back. Default location is
    ``runtime_state_path("evidence_packs", "<pack_id>.json")``.
    """
    if dest is None:
        dest = runtime_state_path(EVIDENCE_PACK_DUMP_SUBDIR, f"{pack.pack_id}.json")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(pack.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dest


__all__ = [
    "EVIDENCE_PACK_VERSION",
    "DEFAULT_TOP_K",
    "DEFAULT_MAX_SNIPPET_CHARS",
    "EvidencePack",
    "EvidencePackError",
    "EvidenceSnippet",
    "build_evidence_pack",
    "dump_evidence_pack",
]
