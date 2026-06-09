"""Graph payload router for the viewer-only endpoint.

Exposes ``GET /api/graph/payload`` and the compatibility alias
``GET /api/kg/graph`` over the existing wiki graph
snapshot, mapped through :mod:`literature_assistant.core.graph_payload`
into the v0 envelope so the frontend can consume one shape regardless
of where the data originated. Legacy ``/api/wiki/graph`` is untouched.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from literature_assistant.core.graph_payload import (
    GraphPayloadV0,
    GraphScope,
    adapt_snapshot,
    empty_payload,
)
from literature_assistant.core.knowledge_graph.models import (
    EvidenceGraphPayload,
    EvidenceGraphScope,
)
from literature_assistant.core.knowledge_graph.projection import (
    build_evidence_graph_from_smart_read_session,
    build_evidence_graph_from_wiki_snapshot,
    empty_evidence_graph,
)

router = APIRouter(prefix="/api/graph", tags=["Graph"])
kg_router = APIRouter(prefix="/api/kg", tags=["Graph"])

ScopeKindQ = Literal["question", "material", "concept"]
EvidenceScopeKindQ = Literal["source", "knowledge_item", "insight", "smart_read_session", "question", "project"]


def _load_snapshot():
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


def _load_smart_read_session(session_id: str):
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
    scope_ref: str = Query("", description="Scope id, question text, or project id."),
    session_id: str | None = Query(
        default=None,
        description="SmartRead session id for smart_read_session or question scoped graphs.",
    ),
    filter: str | None = Query(
        default=None,
        description="Comma-separated node ids to keep; omit to use scope-driven projection.",
    ),
) -> EvidenceGraphPayload:
    """Return the reusable Evidence Graph v1 payload."""

    scope = EvidenceGraphScope(kind=scope_kind, ref=scope_ref)
    smart_read_session_id = (session_id or "").strip()
    if scope_kind == "smart_read_session":
        smart_read_session_id = smart_read_session_id or scope_ref.strip()
    if smart_read_session_id and scope_kind in {"smart_read_session", "question"}:
        session = _load_smart_read_session(smart_read_session_id)
        if session is None:
            return empty_evidence_graph(scope, warning=f"SmartRead session not found: {smart_read_session_id}")
        return build_evidence_graph_from_smart_read_session(session, scope=scope)

    snapshot = _load_snapshot()
    if snapshot is None:
        return empty_evidence_graph(scope, warning="Wiki graph snapshot is unavailable.")
    node_filter = None
    if filter:
        node_filter = {part.strip() for part in filter.split(",") if part.strip()}
        if not node_filter:
            node_filter = None
    return build_evidence_graph_from_wiki_snapshot(snapshot, scope=scope, node_filter=node_filter)


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
