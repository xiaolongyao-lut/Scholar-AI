"""Read-only graph controllers for Wiki, project, and exact answer scopes.

The v1 endpoints keep source stores and query permissions separate while the
legacy ``/api/graph/evidence`` dispatcher remains available. The older v0
viewer aliases are retained unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from fastapi import APIRouter, Query

from literature_assistant.core.graph_payload import (
    GraphPayloadV0,
    GraphScope,
    adapt_snapshot,
    empty_payload,
)
from literature_assistant.core.knowledge_graph.citation_models import CitesCandidate
from literature_assistant.core.knowledge_graph.citation_query import (
    ReadOnlyCitationCandidateStore,
)
from literature_assistant.core.knowledge_graph.citation_store import (
    CitationStoreError,
)
from literature_assistant.core.knowledge_graph.models import (
    EvidenceGraphPayload,
    EvidenceGraphScope,
)
from literature_assistant.core.knowledge_graph.projection import (
    MAX_ANSWER_CITATION_EDGES,
    build_evidence_graph_from_answer_turn,
    build_evidence_graph_from_smart_read_session,
    build_evidence_graph_from_wiki_snapshot,
    empty_evidence_graph,
)
from literature_assistant.core.knowledge_graph.project_literature_projection import (
    DEFAULT_MIN_SIMILARITY,
    DEFAULT_TOP_K,
    MAX_PROJECT_CITATION_EDGES,
    build_project_literature_graph,
)
from literature_assistant.core.project_paths import project_data_path
from literature_assistant.core.wiki.graph import WikiGraphSnapshot

router = APIRouter(prefix="/api/graph", tags=["Graph"])
kg_router = APIRouter(prefix="/api/kg", tags=["Graph"])
logger = logging.getLogger(__name__)

ScopeKindQ = Literal["question", "material", "concept"]
EvidenceScopeKindQ = Literal["source", "knowledge_item", "insight", "smart_read_session", "question", "project"]
WikiEvidenceScopeKindQ = Literal["source", "knowledge_item", "insight", "question", "project"]
_GRAPH_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$"


def _load_snapshot() -> WikiGraphSnapshot | None:
    """Return the current WikiGraphSnapshot, or None if wiki is disabled.

    Imports are deferred so the router stays importable in environments
    where the wiki module path is not on sys.path (e.g. some test
    bootstraps).
    """
    try:
        from literature_assistant.core.runtime_env import wiki_enabled
    except Exception:  # pragma: no cover — runtime_env shape varies
        def wiki_enabled() -> bool:
            return True
    if not wiki_enabled():
        return None
    try:
        from literature_assistant.core.wiki.graph import build_wiki_graph
        from literature_assistant.core.wiki.page_store import WikiPageStore
        from literature_assistant.core.project_paths import wiki_generated_root

        page_store = WikiPageStore(wiki_generated_root(), create=False)
        # Build from current pages so we always reflect on-disk state;
        # WikiGraphStore.load() would be cheaper but can return stale data
        # if no rebuild has happened yet.
        return build_wiki_graph(page_store)
    except Exception:
        # If anything in the wiki stack is missing, treat as empty.
        return None


def _load_smart_read_session(session_id: str) -> dict[str, object] | None:
    """Return one persisted SmartRead session mapping, or None when absent."""

    normalized = session_id.strip()
    if not normalized:
        return None
    try:
        from literature_assistant.core.chat.pipeline import load_session_store
        from literature_assistant.core.project_paths import runtime_state_path

        store = load_session_store(runtime_state_path("intelligent_chat_sessions.json"))
    except Exception:
        return None
    sessions = store.get("sessions")
    if not isinstance(sessions, dict):
        return None
    session = sessions.get(normalized)
    return session if isinstance(session, dict) else None


def _load_project_materials(project_id: str) -> Sequence[object] | None:
    """Return project materials, or ``None`` when the project is absent."""

    normalized = project_id.strip()
    if not normalized:
        return None
    try:
        from literature_assistant.core.writing_resources import get_writing_resource_store

        store = get_writing_resource_store()
        if store.get_project(normalized) is None:
            return None
        return store.list_materials(normalized)
    except Exception:
        logger.exception("Unable to load project materials for graph scope %s", normalized)
        return None


def _load_project_citation_candidates(
    project_id: str,
    *,
    limit: int,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> tuple[tuple[CitesCandidate, ...], str | None]:
    """Read bounded project or exact-turn candidates without creating a DB."""

    if not isinstance(limit, int) or limit < 1 or limit > 500:
        raise ValueError("citation candidate limit must be between 1 and 500")
    normalized = project_id.strip()
    if not normalized:
        raise ValueError("project_id must be non-empty")
    normalized_session = session_id.strip() if isinstance(session_id, str) else None
    normalized_turn = turn_id.strip() if isinstance(turn_id, str) else None
    if bool(normalized_session) != bool(normalized_turn):
        raise ValueError("session_id and turn_id citation filters must be supplied together")
    db_path = project_data_path(normalized, "citation_graph", "citation_graph.db")
    try:
        if not db_path.is_file():
            return (), None
        if db_path.stat().st_size == 0:
            return (), "Citation candidate store is empty or invalid."
        store = ReadOnlyCitationCandidateStore(db_path)
        return (
            store.list_candidates(
                project_id=normalized,
                session_id=normalized_session,
                turn_id=normalized_turn,
                limit=limit,
            ),
            None,
        )
    except (CitationStoreError, OSError, ValueError):
        logger.exception("Unable to read citation candidates for project %s", normalized)
        return (), "Citation candidate store is unavailable or invalid."


def _project_evidence_graph(
    project_id: str,
    *,
    top_k: int,
    min_similarity: float,
) -> EvidenceGraphPayload:
    """Serve the project domain without reading Wiki or answer state."""

    normalized = project_id.strip()
    scope = EvidenceGraphScope(kind="project", ref=normalized)
    if not normalized:
        return empty_evidence_graph(scope, warning="Project graph requires scope_ref project id.")
    materials = _load_project_materials(normalized)
    if materials is None:
        return empty_evidence_graph(scope, warning=f"Project not found or unavailable: {normalized}")
    candidates, citation_warning = _load_project_citation_candidates(
        normalized,
        limit=MAX_PROJECT_CITATION_EDGES + 1,
    )
    try:
        payload = build_project_literature_graph(
            materials,
            scope=scope,
            citation_candidates=candidates,
            top_k=top_k,
            min_similarity=min_similarity,
        )
    except (TypeError, ValueError):
        logger.exception("Unable to project project graph %s", normalized)
        return empty_evidence_graph(scope, warning="Project graph data is invalid or unavailable.")
    if citation_warning:
        payload.warnings.append(citation_warning)
    return payload


def _answer_evidence_graph(
    session_id: str,
    turn_id: str,
    *,
    scope: EvidenceGraphScope | None = None,
) -> EvidenceGraphPayload:
    """Serve one exact turn plus its citations without Wiki or TF-IDF reads."""

    normalized_session = session_id.strip()
    normalized_turn = turn_id.strip()
    answer_scope = scope or EvidenceGraphScope(kind="question", ref=normalized_turn)
    if not normalized_session or not normalized_turn:
        return empty_evidence_graph(
            answer_scope,
            warning="Answer graph requires both session_id and turn_id.",
        )
    session = _load_smart_read_session(normalized_session)
    if session is None:
        return empty_evidence_graph(
            answer_scope,
            warning=f"SmartRead session not found: {normalized_session}",
        )
    session_project_id = session.get("project_id")
    project_id = session_project_id.strip() if isinstance(session_project_id, str) else ""
    candidates: tuple[CitesCandidate, ...] = ()
    citation_warning: str | None = None
    if project_id:
        candidates, citation_warning = _load_project_citation_candidates(
            project_id,
            session_id=normalized_session,
            turn_id=normalized_turn,
            limit=MAX_ANSWER_CITATION_EDGES + 1,
        )
    try:
        payload = build_evidence_graph_from_answer_turn(
            session,
            session_id=normalized_session,
            turn_id=normalized_turn,
            scope=answer_scope,
            citation_candidates=candidates,
        )
    except (TypeError, ValueError):
        logger.exception(
            "Unable to project answer graph for session %s turn %s",
            normalized_session,
            normalized_turn,
        )
        return empty_evidence_graph(answer_scope, warning="Answer graph data is invalid or unavailable.")
    if citation_warning:
        payload.warnings.append(citation_warning)
    return payload


def _wiki_evidence_graph(
    scope: EvidenceGraphScope,
    *,
    node_filter: set[str] | None,
) -> EvidenceGraphPayload:
    """Serve the Wiki domain without reading project or answer stores."""

    snapshot = _load_snapshot()
    if snapshot is None:
        return empty_evidence_graph(scope, warning="Wiki graph snapshot is unavailable.")
    return build_evidence_graph_from_wiki_snapshot(
        snapshot,
        scope=scope,
        node_filter=node_filter,
    )


def _node_filter(value: str | None) -> set[str] | None:
    if not value:
        return None
    normalized = {part.strip() for part in value.split(",") if part.strip()}
    return normalized or None


def _graph_payload_for_query(
    scope_kind: ScopeKindQ = Query("question", description="What this subgraph is scoped to."),
    scope_ref: str = Query("", description="The question text, material_id, or concept id."),
    filter: str | None = Query(
        default=None,
        description="Comma-separated node ids to keep; omit for the full snapshot.",
    ),
) -> GraphPayloadV0:
    """Return a GraphPayload v0 response for canonical and alias routes."""

    scope = GraphScope(kind=scope_kind, ref=scope_ref)
    snapshot = _load_snapshot()
    if snapshot is None:
        return empty_payload(scope)
    node_filter = None
    if filter:
        node_filter = {part.strip() for part in filter.split(",") if part.strip()}
        if not node_filter:
            node_filter = None
    return adapt_snapshot(snapshot, scope=scope, node_filter=node_filter)


@router.get("/payload", response_model=GraphPayloadV0)
def graph_payload(
    scope_kind: ScopeKindQ = Query("question", description="What this subgraph is scoped to."),
    scope_ref: str = Query("", description="The question text, material_id, or concept id."),
    filter: str | None = Query(
        default=None,
        description="Comma-separated node ids to keep; omit for the full snapshot.",
    ),
) -> GraphPayloadV0:
    """Return the canonical KG viewer payload endpoint."""

    return _graph_payload_for_query(scope_kind=scope_kind, scope_ref=scope_ref, filter=filter)


@router.get("/evidence", response_model=EvidenceGraphPayload)
def evidence_graph_payload(
    scope_kind: EvidenceScopeKindQ = Query("question", description="Evidence graph scope kind."),
    scope_ref: str = Query(
        "",
        description="Scope id or project id. Answer graphs use turn_id as their key.",
    ),
    session_id: str | None = Query(
        default=None,
        description="SmartRead session id for smart_read_session or question scoped graphs.",
    ),
    turn_id: str | None = Query(
        default=None,
        description="Exact persisted answer-turn id. Required for question scoped answer graphs.",
    ),
    filter: str | None = Query(
        default=None,
        description="Comma-separated node ids to keep; omit to use scope-driven projection.",
    ),
    top_k: int = Query(DEFAULT_TOP_K, ge=1, le=5, description="Project graph neighbours per paper."),
    min_similarity: float = Query(
        DEFAULT_MIN_SIMILARITY,
        ge=0.0,
        le=1.0,
        description="Minimum project-paper lexical similarity.",
    ),
) -> EvidenceGraphPayload:
    """Return the reusable Evidence Graph v1 payload."""

    scope = EvidenceGraphScope(kind=scope_kind, ref=scope_ref)
    if scope_kind == "project":
        return _project_evidence_graph(
            scope_ref,
            top_k=top_k,
            min_similarity=min_similarity,
        )
    smart_read_session_id = (session_id or "").strip()
    if scope_kind == "smart_read_session":
        smart_read_session_id = smart_read_session_id or scope_ref.strip()
        if turn_id and turn_id.strip():
            return _answer_evidence_graph(
                smart_read_session_id,
                turn_id,
                scope=scope,
            )
    if scope_kind == "question":
        if not smart_read_session_id or not (turn_id or "").strip():
            return empty_evidence_graph(
                scope,
                warning="Answer graph requires both session_id and turn_id; question text is not a graph key.",
            )
        return _answer_evidence_graph(smart_read_session_id, turn_id or "")
    if smart_read_session_id and scope_kind == "smart_read_session":
        session = _load_smart_read_session(smart_read_session_id)
        if session is None:
            return empty_evidence_graph(scope, warning=f"SmartRead session not found: {smart_read_session_id}")
        return build_evidence_graph_from_smart_read_session(session, scope=scope)

    return _wiki_evidence_graph(scope, node_filter=_node_filter(filter))


@router.get("/evidence/project", response_model=EvidenceGraphPayload)
def project_evidence_graph_payload(
    project_id: str = Query(
        ...,
        min_length=1,
        max_length=256,
        pattern=_GRAPH_ID_PATTERN,
        description="Exact project id for the project-local graph projection.",
    ),
    top_k: int = Query(DEFAULT_TOP_K, ge=1, le=5, description="Project graph neighbours per paper."),
    min_similarity: float = Query(
        DEFAULT_MIN_SIMILARITY,
        ge=0.0,
        le=1.0,
        description="Minimum project-paper lexical similarity.",
    ),
) -> EvidenceGraphPayload:
    """Return project TF-IDF and citation candidates without Wiki mutation."""

    return _project_evidence_graph(
        project_id,
        top_k=top_k,
        min_similarity=min_similarity,
    )


@router.get("/evidence/answer", response_model=EvidenceGraphPayload)
def answer_evidence_graph_payload(
    session_id: str = Query(
        ...,
        min_length=1,
        max_length=256,
        pattern=_GRAPH_ID_PATTERN,
        description="Exact persisted SmartRead session id.",
    ),
    turn_id: str = Query(
        ...,
        min_length=1,
        max_length=256,
        pattern=_GRAPH_ID_PATTERN,
        description="Exact persisted answer-turn id; question text is not accepted as a key.",
    ),
) -> EvidenceGraphPayload:
    """Return one answer-turn graph isolated by session_id and turn_id."""

    return _answer_evidence_graph(session_id, turn_id)


@router.get("/evidence/wiki", response_model=EvidenceGraphPayload)
def wiki_evidence_graph_payload(
    scope_kind: WikiEvidenceScopeKindQ = Query("project", description="Wiki graph scope kind."),
    scope_ref: str = Query("", max_length=1_000, description="Wiki scope id or page identity."),
    filter: str | None = Query(
        default=None,
        max_length=20_000,
        description="Comma-separated Wiki node ids to keep.",
    ),
) -> EvidenceGraphPayload:
    """Return a Wiki-only graph projection with no project or answer access."""

    scope = EvidenceGraphScope(kind=scope_kind, ref=scope_ref)
    return _wiki_evidence_graph(scope, node_filter=_node_filter(filter))


@kg_router.get("/graph", response_model=GraphPayloadV0)
def kg_graph_payload(
    scope_kind: ScopeKindQ = Query("question", description="What this subgraph is scoped to."),
    scope_ref: str = Query("", description="The question text, material_id, or concept id."),
    filter: str | None = Query(
        default=None,
        description="Comma-separated node ids to keep; omit for the full snapshot.",
    ),
) -> GraphPayloadV0:
    """Compatibility alias for matrix-era KG clients expecting `/api/kg/graph`."""

    return _graph_payload_for_query(scope_kind=scope_kind, scope_ref=scope_ref, filter=filter)
