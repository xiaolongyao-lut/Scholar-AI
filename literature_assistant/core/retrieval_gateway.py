# -*- coding: utf-8 -*-
"""Unified retrieval candidate gateway for chunk-store backed evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from chunk_chroma_index import ChunkChromaSearchResult, query_chunk_chroma_index
from chunk_fts_index import ChunkFtsHit, ChunkFtsSearchResult, search_chunk_fts_index
from chunk_hashing import CHUNK_HASH_VERSION, SUPPORTED_CHUNK_HASH_VERSIONS, compute_chunk_hashes
from chunk_index_consistency_gate import IndexedChunkRecord, build_chunk_truth_records


RetrievalCandidateSource = Literal["dense", "lexical", "visual"]

_VISUAL_INTENTS = {"visual", "figure", "table", "chart", "image", "appearance", "microstructure"}
_NON_VISUAL_INTENTS = {"exact", "parameter", "doi", "author", "material"}


@dataclass(frozen=True)
class RetrievalCandidate:
    """Normalized evidence candidate returned by the shared retrieval gateway.

    Args:
        project_id: Owning project id.
        material_id: Owning material id from chunk-store truth.
        chunk_id: Stable chunk id inside the material.
        score: Final gateway score; higher is better.
        sources: Retrieval sources that found the candidate.
        chunk_hash: Truth hash used to detect stale derived rows.
        embedding_input_hash: Hash of the text used for dense embedding.
        page: One-based source page when available.
        title: Source title when available.
        chunk_type: Bounded chunk type label.
        snippet: Bounded lexical or truth text excerpt.
        dense_score: Dense score when Chroma supplied the hit.
        lexical_score: Lexical score when FTS supplied the hit.
        visual_score: Visual boost score when figure/table evidence is protected.
        metadata: Bounded metadata safe for diagnostics.
    """

    project_id: str
    material_id: str
    chunk_id: str
    score: float
    sources: tuple[RetrievalCandidateSource, ...]
    chunk_hash: str
    embedding_input_hash: str
    page: int | None = None
    title: str = ""
    chunk_type: str = "unknown"
    snippet: str = ""
    dense_score: float | None = None
    lexical_score: float | None = None
    visual_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable candidate payload."""

        return {
            "project_id": self.project_id,
            "material_id": self.material_id,
            "chunk_id": self.chunk_id,
            "score": self.score,
            "sources": list(self.sources),
            "chunk_hash": self.chunk_hash,
            "embedding_input_hash": self.embedding_input_hash,
            "page": self.page,
            "title": self.title,
            "chunk_type": self.chunk_type,
            "snippet": self.snippet,
            "dense_score": self.dense_score,
            "lexical_score": self.lexical_score,
            "visual_score": self.visual_score,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RetrievalDiagnostics:
    """Machine-readable retrieval status shared by public RAG surfaces."""

    project_id: str
    intent: str
    material_id: str | None
    dense_hit_count: int
    lexical_hit_count: int
    visual_hit_count: int
    candidate_count: int
    dense_enabled: bool
    material_balancing_enabled: bool
    chroma_status: str
    fts_status: str
    fallback_reasons: tuple[str, ...] = field(default_factory=tuple)
    gate_status_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable diagnostics payload."""

        return {
            "project_id": self.project_id,
            "intent": self.intent,
            "material_id": self.material_id,
            "dense_hit_count": self.dense_hit_count,
            "lexical_hit_count": self.lexical_hit_count,
            "visual_hit_count": self.visual_hit_count,
            "candidate_count": self.candidate_count,
            "dense_enabled": self.dense_enabled,
            "material_balancing_enabled": self.material_balancing_enabled,
            "chroma_status": self.chroma_status,
            "fts_status": self.fts_status,
            "fallback_reasons": list(self.fallback_reasons),
            "gate_status_counts": dict(sorted(self.gate_status_counts.items())),
        }


@dataclass(frozen=True)
class RetrievalResult:
    """Gateway result containing normalized candidates and diagnostics."""

    candidates: tuple[RetrievalCandidate, ...]
    diagnostics: RetrievalDiagnostics

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable retrieval result."""

        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "diagnostics": self.diagnostics.to_dict(),
        }


@dataclass
class _CandidateState:
    project_id: str
    material_id: str
    chunk_id: str
    chunk_hash: str
    embedding_input_hash: str
    page: int | None
    title: str
    chunk_type: str
    snippet: str
    dense_score: float | None = None
    lexical_score: float | None = None
    visual_score: float | None = None
    sources: list[RetrievalCandidateSource] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> float:
        """Return a stable combined score without making source-specific scores incomparable."""

        base = max(self.dense_score or 0.0, self.lexical_score or 0.0, self.visual_score or 0.0)
        source_bonus = 0.04 * max(len(self.sources) - 1, 0)
        return round(base + source_bonus, 6)

    def add_source(self, source: RetrievalCandidateSource) -> None:
        if source not in self.sources:
            self.sources.append(source)

    def to_candidate(self) -> RetrievalCandidate:
        return RetrievalCandidate(
            project_id=self.project_id,
            material_id=self.material_id,
            chunk_id=self.chunk_id,
            score=self.score,
            sources=tuple(self.sources),
            chunk_hash=self.chunk_hash,
            embedding_input_hash=self.embedding_input_hash,
            page=self.page,
            title=self.title,
            chunk_type=self.chunk_type,
            snippet=self.snippet,
            dense_score=self.dense_score,
            lexical_score=self.lexical_score,
            visual_score=self.visual_score,
            metadata=dict(self.metadata),
        )


def _require_non_empty_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _bounded_text(value: object, *, max_chars: int = 1000) -> str:
    return str(value or "").replace("\x00", " ").strip()[:max_chars]


def _coerce_limit(value: int, *, name: str) -> int:
    if not isinstance(value, int) or value < 1 or value > 100:
        raise ValueError(f"{name} must be between 1 and 100")
    return value


def _coerce_page(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        page = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _store_chunk_lookup(
    store: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if not isinstance(store, Mapping):
        raise TypeError("store must be a mapping of material ids to chunk sequences")
    lookup: dict[tuple[str, str], Mapping[str, Any]] = {}
    for raw_material_id, chunks in store.items():
        material_id = _require_non_empty_string(str(raw_material_id), name="material_id")
        if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
            raise TypeError("store material values must be chunk sequences")
        for chunk in chunks:
            if not isinstance(chunk, Mapping):
                raise TypeError("store chunks must be mappings")
            chunk_id = _require_non_empty_string(_bounded_text(chunk.get("chunk_id"), max_chars=240), name="chunk_id")
            lookup[(material_id, chunk_id)] = chunk
    return lookup


def _add_count(counts: dict[str, int], status: str) -> None:
    counts[status] = counts.get(status, 0) + 1


def _unique_reasons(reasons: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for reason in reasons:
        if not reason or reason in seen:
            continue
        seen.add(reason)
        result.append(reason)
    return tuple(result)


def _matches_material(candidate_material_id: str, material_id: str | None) -> bool:
    return material_id is None or candidate_material_id == material_id


def _truth_metadata(chunk: Mapping[str, Any], *, snippet: str = "") -> tuple[int | None, str, str, str, dict[str, Any]]:
    text = snippet or _bounded_text(chunk.get("content") or chunk.get("raw_content"), max_chars=500)
    metadata = {
        "section_title": _bounded_text(chunk.get("section_title"), max_chars=300),
        "locator_quality": _bounded_text(chunk.get("locator_quality"), max_chars=80),
        "has_image": bool(chunk.get("image_paths") or chunk.get("figure_image_paths")),
        "has_table": bool(_bounded_text(chunk.get("table_csv"))),
        "has_equation": bool(_bounded_text(chunk.get("equation_latex"))),
    }
    return (
        _coerce_page(chunk.get("page")),
        _bounded_text(chunk.get("title"), max_chars=500),
        _bounded_text(chunk.get("chunk_type"), max_chars=80) or "unknown",
        text,
        metadata,
    )


def _dense_status_from_chroma(result: ChunkChromaSearchResult | None) -> str:
    if result is None:
        return "not_requested"
    return result.diagnostics.status


def _lexical_status_from_fts(result: ChunkFtsSearchResult | None) -> str:
    if result is None:
        return "not_requested"
    return result.status


def _validate_dense_hit(
    *,
    hit: IndexedChunkRecord,
    project_id: str,
    expected_contract_hash: str,
    hash_version: str,
    chunk_lookup: Mapping[tuple[str, str], Mapping[str, Any]],
    counts: dict[str, int],
) -> bool:
    if hit.project_id != project_id:
        _add_count(counts, "corrupt_wrong_project")
        return False
    chunk = chunk_lookup.get(hit.key)
    if chunk is None:
        _add_count(counts, "corrupt_missing_truth")
        return False
    if hit.contract_hash != expected_contract_hash:
        _add_count(counts, "contract_mismatch")
        return False
    hashes = compute_chunk_hashes(
        chunk,
        material_id_hint=hit.material_id,
        hash_version=hash_version,
    )
    if hit.chunk_hash != hashes["chunk_hash"] or hit.embedding_input_hash != hashes["embedding_input_hash"]:
        _add_count(counts, "stale")
        return False
    _add_count(counts, "valid")
    return True


def _validate_lexical_hit(
    *,
    hit: ChunkFtsHit,
    hash_version: str,
    chunk_lookup: Mapping[tuple[str, str], Mapping[str, Any]],
    counts: dict[str, int],
) -> bool:
    chunk = chunk_lookup.get((hit.material_id, hit.chunk_id))
    if chunk is None:
        _add_count(counts, "corrupt_missing_truth")
        return False
    hashes = compute_chunk_hashes(
        chunk,
        material_id_hint=hit.material_id,
        hash_version=hash_version,
    )
    if hit.chunk_hash != hashes["chunk_hash"] or hit.embedding_input_hash != hashes["embedding_input_hash"]:
        _add_count(counts, "stale")
        return False
    _add_count(counts, "valid")
    return True


def _merge_candidate(
    candidates: dict[tuple[str, str], _CandidateState],
    *,
    source: RetrievalCandidateSource,
    project_id: str,
    material_id: str,
    chunk_id: str,
    chunk_hash: str,
    embedding_input_hash: str,
    page: int | None,
    title: str,
    chunk_type: str,
    snippet: str,
    score: float,
    metadata: Mapping[str, Any],
) -> None:
    key = (material_id, chunk_id)
    state = candidates.get(key)
    if state is None:
        state = _CandidateState(
            project_id=project_id,
            material_id=material_id,
            chunk_id=chunk_id,
            chunk_hash=chunk_hash,
            embedding_input_hash=embedding_input_hash,
            page=page,
            title=title,
            chunk_type=chunk_type,
            snippet=snippet,
            metadata=dict(metadata),
        )
        candidates[key] = state
    state.add_source(source)
    if source == "dense":
        state.dense_score = max(state.dense_score or 0.0, score)
    elif source == "lexical":
        state.lexical_score = max(state.lexical_score or 0.0, score)
    else:
        state.visual_score = max(state.visual_score or 0.0, score)
    if not state.snippet and snippet:
        state.snippet = snippet
    state.metadata.update(dict(metadata))


def _lexical_score(raw_score: float) -> float:
    if raw_score < 0:
        raw_score = abs(raw_score)
    return round(1.0 / (1.0 + raw_score), 6)


def _is_visual_candidate(candidate: _CandidateState) -> bool:
    return bool(
        candidate.metadata.get("has_image")
        or candidate.metadata.get("has_table")
        or candidate.metadata.get("has_equation")
        or candidate.chunk_type in {"figure", "table", "equation", "caption"}
    )


def _visual_budget(*, intent: str, query: str, visual_budget_floor: int, visual_budget_intent: int) -> int:
    normalized_intent = intent.lower()
    normalized_query = query.lower()
    if normalized_intent in _VISUAL_INTENTS or any(token in normalized_query for token in _VISUAL_INTENTS):
        return visual_budget_intent
    if normalized_intent in _NON_VISUAL_INTENTS:
        return 0
    return visual_budget_floor


def _apply_visual_protection(
    candidates: dict[tuple[str, str], _CandidateState],
    *,
    budget: int,
) -> int:
    if budget <= 0:
        return 0
    protected = 0
    ranked = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
    for candidate in ranked:
        if protected >= budget:
            break
        if not _is_visual_candidate(candidate):
            continue
        candidate.add_source("visual")
        candidate.visual_score = max(candidate.visual_score or 0.0, 0.2)
        protected += 1
    return protected


def retrieve_candidates(
    project_id: str,
    query: str,
    intent: str,
    material_id: str | None = None,
    *,
    store: Mapping[str, Sequence[Mapping[str, Any]]],
    chunk_store_version: str,
    hash_version: str = CHUNK_HASH_VERSION,
    fts_db_path: Path,
    chroma_persist_dir: Path | None = None,
    query_embedding: Sequence[float] | None = None,
    expected_contract_hash: str | None = None,
    ledger_entries: Sequence[Mapping[str, Any]] = (),
    limit: int = 20,
    dense_limit: int = 20,
    lexical_limit: int = 20,
    embedding_dim: int = 1024,
    visual_budget_floor: int = 2,
    visual_budget_intent: int = 12,
) -> RetrievalResult:
    """Retrieve normalized candidates through dense, lexical, and visual paths.

    Args:
        project_id: Non-empty project id.
        query: Non-empty user query.
        intent: Bounded retrieval intent label used only for diagnostics and visual budget.
        material_id: Optional explicit material scope. When set, material balancing is disabled.
        store: Current chunk-store truth mapping.
        chunk_store_version: Content-derived truth-store version.
        hash_version: Canonical hash contract used by the owning manifest.
        fts_db_path: SQLite FTS5 derived index path.
        chroma_persist_dir: Optional Chroma derived index directory.
        query_embedding: Optional dense query embedding; Gateway never calls provider APIs.
        expected_contract_hash: Required when dense recall is requested.
        ledger_entries: Backfill ledger entries reserved for diagnostics-compatible call sites.
        limit: Maximum normalized candidates to return.
        dense_limit: Maximum Chroma hits to inspect.
        lexical_limit: Maximum FTS hits to inspect.
        embedding_dim: Expected query embedding width for dense recall.
        visual_budget_floor: Protected visual candidate budget for general intents.
        visual_budget_intent: Protected visual candidate budget for visual intents.

    Returns:
        Retrieval result with deduped candidates and gateway diagnostics.
    """

    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    normalized_query = _require_non_empty_string(query, name="query")
    normalized_intent = _require_non_empty_string(intent, name="intent")
    normalized_material_id = None if material_id is None else _require_non_empty_string(material_id, name="material_id")
    normalized_version = _require_non_empty_string(chunk_store_version, name="chunk_store_version")
    if hash_version not in SUPPORTED_CHUNK_HASH_VERSIONS:
        raise ValueError("unsupported chunk hash version")
    _coerce_limit(limit, name="limit")
    _coerce_limit(dense_limit, name="dense_limit")
    _coerce_limit(lexical_limit, name="lexical_limit")
    if not isinstance(fts_db_path, Path):
        raise TypeError("fts_db_path must be a pathlib.Path")
    if chroma_persist_dir is not None and not isinstance(chroma_persist_dir, Path):
        raise TypeError("chroma_persist_dir must be a pathlib.Path or None")
    if isinstance(ledger_entries, (str, bytes)) or not isinstance(ledger_entries, Sequence):
        raise TypeError("ledger_entries must be a sequence of mappings")
    if not isinstance(visual_budget_floor, int) or visual_budget_floor < 0:
        raise ValueError("visual_budget_floor must be a non-negative integer")
    if not isinstance(visual_budget_intent, int) or visual_budget_intent < 0:
        raise ValueError("visual_budget_intent must be a non-negative integer")

    build_chunk_truth_records(
        project_id=normalized_project_id,
        store=store,
        hash_version=hash_version,
    )
    chunk_lookup = _store_chunk_lookup(store)
    candidates: dict[tuple[str, str], _CandidateState] = {}
    fallback_reasons: list[str] = []
    gate_status_counts: dict[str, int] = {}
    dense_result: ChunkChromaSearchResult | None = None
    lexical_result: ChunkFtsSearchResult | None = None
    dense_seen = 0
    lexical_seen = 0

    dense_requested = chroma_persist_dir is not None and query_embedding is not None and expected_contract_hash is not None
    if dense_requested:
        normalized_contract = _require_non_empty_string(expected_contract_hash, name="expected_contract_hash")
        dense_result = query_chunk_chroma_index(
            persist_dir=chroma_persist_dir,
            project_id=normalized_project_id,
            query_embedding=query_embedding,
            expected_chunk_store_version=normalized_version,
            expected_contract_hash=normalized_contract,
            limit=dense_limit,
            embedding_dim=embedding_dim,
        )
        if dense_result.diagnostics.fallback_reason:
            fallback_reasons.append(dense_result.diagnostics.fallback_reason)
        for hit in dense_result.hits:
            if not _matches_material(hit.material_id, normalized_material_id):
                continue
            if not _validate_dense_hit(
                hit=hit,
                project_id=normalized_project_id,
                expected_contract_hash=normalized_contract,
                hash_version=hash_version,
                chunk_lookup=chunk_lookup,
                counts=gate_status_counts,
            ):
                continue
            chunk = chunk_lookup[hit.key]
            page, title, chunk_type, snippet, metadata = _truth_metadata(chunk)
            dense_seen += 1
            _merge_candidate(
                candidates,
                source="dense",
                project_id=normalized_project_id,
                material_id=hit.material_id,
                chunk_id=hit.chunk_id,
                chunk_hash=hit.chunk_hash,
                embedding_input_hash=hit.embedding_input_hash,
                page=page,
                title=title,
                chunk_type=chunk_type,
                snippet=snippet,
                score=hit.score if hit.score is not None else 0.0,
                metadata=metadata,
            )
    elif chroma_persist_dir is not None or query_embedding is not None:
        fallback_reasons.append("dense_recall_missing_contract_or_embedding")

    lexical_result = search_chunk_fts_index(
        db_path=fts_db_path,
        project_id=normalized_project_id,
        query=normalized_query,
        expected_chunk_store_version=normalized_version,
        limit=lexical_limit,
    )
    if lexical_result.fallback_reason:
        fallback_reasons.append(lexical_result.fallback_reason)
    if lexical_result.status == "valid":
        for hit in lexical_result.hits:
            if not _matches_material(hit.material_id, normalized_material_id):
                continue
            if not _validate_lexical_hit(
                hit=hit,
                hash_version=hash_version,
                chunk_lookup=chunk_lookup,
                counts=gate_status_counts,
            ):
                continue
            chunk = chunk_lookup[(hit.material_id, hit.chunk_id)]
            page, title, chunk_type, snippet, metadata = _truth_metadata(chunk, snippet=hit.snippet)
            metadata.update(hit.metadata)
            lexical_seen += 1
            _merge_candidate(
                candidates,
                source="lexical",
                project_id=normalized_project_id,
                material_id=hit.material_id,
                chunk_id=hit.chunk_id,
                chunk_hash=hit.chunk_hash,
                embedding_input_hash=hit.embedding_input_hash,
                page=page if page is not None else hit.page,
                title=title or hit.title,
                chunk_type=chunk_type or hit.chunk_type,
                snippet=snippet,
                score=_lexical_score(hit.score),
                metadata=metadata,
            )

    visual_count = _apply_visual_protection(
        candidates,
        budget=_visual_budget(
            intent=normalized_intent,
            query=normalized_query,
            visual_budget_floor=visual_budget_floor,
            visual_budget_intent=visual_budget_intent,
        ),
    )
    ranked = tuple(
        sorted(
            (state.to_candidate() for state in candidates.values()),
            key=lambda candidate: (
                candidate.score,
                "lexical" in candidate.sources,
                "dense" in candidate.sources,
                candidate.material_id,
                candidate.chunk_id,
            ),
            reverse=True,
        )[:limit]
    )

    diagnostics = RetrievalDiagnostics(
        project_id=normalized_project_id,
        intent=normalized_intent,
        material_id=normalized_material_id,
        dense_hit_count=dense_seen,
        lexical_hit_count=lexical_seen,
        visual_hit_count=visual_count,
        candidate_count=len(ranked),
        dense_enabled=dense_result is not None and dense_result.diagnostics.status == "valid",
        material_balancing_enabled=normalized_material_id is None,
        chroma_status=_dense_status_from_chroma(dense_result),
        fts_status=_lexical_status_from_fts(lexical_result),
        fallback_reasons=_unique_reasons(fallback_reasons),
        gate_status_counts=dict(sorted(gate_status_counts.items())),
    )
    return RetrievalResult(candidates=ranked, diagnostics=diagnostics)
