"""Bounded project-literature relationship projection.

The project graph combines deterministic local TF-IDF relatedness with
already-persisted, reviewable citation candidates. Opening the graph never
triggers a provider call, reparses a PDF, or promotes candidate data to Wiki.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from literature_assistant.core.knowledge_graph.citation_graph_projection import (
    build_citation_candidate_graph_edge,
)
from literature_assistant.core.knowledge_graph.citation_models import CitesCandidate
from literature_assistant.core.knowledge_graph.models import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceGraphPayload,
    EvidenceGraphProvenanceRef,
    EvidenceGraphScope,
)


MAX_PROJECT_GRAPH_NODES = 300
MAX_PROJECT_GRAPH_EDGES = 800
MAX_PROJECT_CITATION_EDGES = 200
DEFAULT_TOP_K = 4
DEFAULT_MIN_SIMILARITY = 0.08
_WORD_RE = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*", re.IGNORECASE)
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _tokens(value: str) -> list[str]:
    lowered = value.casefold()
    tokens = [match.group(0) for match in _WORD_RE.finditer(lowered)]
    for match in _CJK_RUN_RE.finditer(lowered):
        run = match.group(0)
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def _material_record(material: Mapping[str, Any] | object) -> tuple[str, str, str, str, str, str]:
    if isinstance(material, Mapping):
        get = material.get
    else:
        get = lambda key, default="": getattr(material, key, default)
    material_id = _text(get("material_id", ""))
    title = _text(get("title", ""))
    if not material_id or not title:
        raise ValueError("project graph materials require material_id and title")
    title_en = _text(get("title_en", ""))
    summary = _text(get("summary", ""))
    summary_en = _text(get("summary_en", ""))
    updated_at = _text(get("updated_at", ""))
    return material_id, title, title_en, summary, summary_en, updated_at


def _tfidf_vectors(records: Sequence[tuple[str, str, str, str, str, str]]) -> list[dict[str, float]]:
    counters: list[Counter[str]] = []
    document_frequency: Counter[str] = Counter()
    for _material_id, title, title_en, summary, summary_en, _updated_at in records:
        # Repeating titles gives concise bibliographic identity more influence
        # than a long abstract without introducing an external model call.
        counter = Counter(_tokens(f"{title} {title_en} {title} {title_en} {summary} {summary_en}"))
        counters.append(counter)
        document_frequency.update(counter.keys())
    count = max(1, len(records))
    vectors: list[dict[str, float]] = []
    for counter in counters:
        vector: dict[str, float] = {}
        for token, frequency in counter.items():
            inverse_frequency = math.log((count + 1) / (document_frequency[token] + 1)) + 1.0
            vector[token] = (1.0 + math.log(frequency)) * inverse_frequency
        norm = math.sqrt(sum(weight * weight for weight in vector.values()))
        vectors.append({token: weight / norm for token, weight in vector.items()} if norm else {})
    return vectors


def _cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(token, 0.0) for token, weight in left.items())


def _edge_id(left_id: str, right_id: str) -> str:
    pair = "\x00".join(sorted((left_id, right_id)))
    return f"project-related-{hashlib.sha256(pair.encode('utf-8')).hexdigest()[:20]}"


def _project_citation_edges(
    candidates: Sequence[CitesCandidate],
    *,
    project_id: str,
    node_ids: set[str],
) -> tuple[list[EvidenceGraphEdge], list[str]]:
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise TypeError("citation_candidates must be a sequence of CitesCandidate records")
    normalized = tuple(candidates)
    if any(not isinstance(candidate, CitesCandidate) for candidate in normalized):
        raise TypeError("citation_candidates must contain only CitesCandidate records")
    if any(candidate.project_id != project_id for candidate in normalized):
        raise ValueError("citation candidates must belong to the requested project")
    candidate_ids = [candidate.candidate_id for candidate in normalized]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("citation_candidates must not contain duplicate candidate ids")

    warnings: list[str] = []
    ranked = sorted(normalized, key=lambda item: (item.created_at, item.candidate_id))
    if len(ranked) > MAX_PROJECT_CITATION_EDGES:
        warnings.append(
            f"Citation candidate relationships were limited to {MAX_PROJECT_CITATION_EDGES} edges; "
            f"{len(ranked) - MAX_PROJECT_CITATION_EDGES} candidates were omitted."
        )
        ranked = ranked[:MAX_PROJECT_CITATION_EDGES]

    missing_endpoint_count = 0
    edges: list[EvidenceGraphEdge] = []
    for candidate in ranked:
        if (
            candidate.source_material_id not in node_ids
            or candidate.target_material_id not in node_ids
        ):
            missing_endpoint_count += 1
            continue
        edges.append(build_citation_candidate_graph_edge(candidate))
    if missing_endpoint_count:
        warnings.append(
            f"{missing_endpoint_count} citation candidate relationships were omitted because "
            "one or both project-paper nodes are outside the bounded projection."
        )
    return edges, warnings


@lru_cache(maxsize=64)
def _build_cached(
    project_id: str,
    records: tuple[tuple[str, str, str, str, str, str], ...],
    top_k: int,
    min_similarity: float,
) -> tuple[tuple[EvidenceGraphNode, ...], tuple[EvidenceGraphEdge, ...]]:
    vectors = _tfidf_vectors(records)
    nodes = tuple(
        EvidenceGraphNode(
            id=material_id,
            label=title,
            type="paper",
            status="trusted",
            provenance_refs=[EvidenceGraphProvenanceRef(material_id=material_id)],
            metadata={
                "project_id": project_id,
                "title_en": title_en,
                "summary": summary,
                "summary_en": summary_en,
                "updated_at": updated_at,
            },
        )
        for material_id, title, title_en, summary, summary_en, updated_at in records
    )

    selected_pairs: dict[tuple[int, int], float] = {}
    for left_index, left_vector in enumerate(vectors):
        candidates: list[tuple[float, int]] = []
        for right_index, right_vector in enumerate(vectors):
            if left_index == right_index:
                continue
            score = _cosine(left_vector, right_vector)
            if score >= min_similarity:
                candidates.append((score, right_index))
        candidates.sort(key=lambda item: (-item[0], records[item[1]][0]))
        for score, right_index in candidates[:top_k]:
            pair = tuple(sorted((left_index, right_index)))
            selected_pairs[pair] = max(score, selected_pairs.get(pair, 0.0))

    ranked_pairs = sorted(
        selected_pairs.items(),
        key=lambda item: (-item[1], records[item[0][0]][0], records[item[0][1]][0]),
    )[:MAX_PROJECT_GRAPH_EDGES]
    updated_at = _utc_now_iso()
    edges = tuple(
        EvidenceGraphEdge(
            id=_edge_id(records[left_index][0], records[right_index][0]),
            source=records[left_index][0],
            target=records[right_index][0],
            relation="related",
            direction="undirected",
            status="candidate",
            confidence=round(min(1.0, max(0.0, score)), 6),
            provenance_refs=[],
            created_by="runtime_capture",
            updated_at=updated_at,
            metadata={
                "project_id": project_id,
                "algorithm": "tfidf_cosine_v1",
                "similarity": round(score, 6),
                "undirected": True,
            },
        )
        for (left_index, right_index), score in ranked_pairs
    )
    return nodes, edges


def build_project_literature_graph(
    materials: Sequence[Mapping[str, Any] | object],
    *,
    scope: EvidenceGraphScope,
    citation_candidates: Sequence[CitesCandidate] = (),
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
) -> EvidenceGraphPayload:
    """Build a bounded project graph from material titles and summaries.

    Args:
        materials: Project material records or objects with stable ids/titles.
        scope: A non-empty ``project`` graph scope.
        citation_candidates: Bounded project-local ``cites`` candidates already
            persisted by the citation resolver. They remain candidate records
            and are never written to Wiki by this projector.
        top_k: Per-paper neighbour cap, clamped to 1..5.
        min_similarity: Cosine threshold, clamped to 0..1.

    Returns:
        Evidence Graph v1 with paper nodes, undirected ``related`` edges, and
        directed project-local ``cites`` candidate edges.
    """

    if scope.kind != "project" or not scope.ref.strip():
        raise ValueError("project literature graph requires a non-empty project scope")
    safe_top_k = min(5, max(1, int(top_k)))
    safe_threshold = min(1.0, max(0.0, float(min_similarity)))
    normalized = sorted((_material_record(material) for material in materials), key=lambda item: item[0])
    warnings: list[str] = []
    if len(normalized) > MAX_PROJECT_GRAPH_NODES:
        warnings.append(
            f"Project graph is limited to {MAX_PROJECT_GRAPH_NODES} papers; "
            f"{len(normalized) - MAX_PROJECT_GRAPH_NODES} papers were omitted. "
            "Community overview is not available in this projection yet."
        )
        normalized = normalized[:MAX_PROJECT_GRAPH_NODES]
    nodes, edges = _build_cached(scope.ref.strip(), tuple(normalized), safe_top_k, safe_threshold)
    if len(edges) >= MAX_PROJECT_GRAPH_EDGES:
        warnings.append(f"Project graph relationships were limited to {MAX_PROJECT_GRAPH_EDGES} edges.")
    citation_edges, citation_warnings = _project_citation_edges(
        citation_candidates,
        project_id=scope.ref.strip(),
        node_ids={node.id for node in nodes},
    )
    warnings.extend(citation_warnings)
    return EvidenceGraphPayload(
        scope=scope,
        updated_at=_utc_now_iso(),
        nodes=list(nodes),
        edges=[*edges, *citation_edges],
        warnings=warnings,
    )
