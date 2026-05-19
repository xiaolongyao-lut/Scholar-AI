"""Graph payload router — plan §4.11 KG-1 viewer-only endpoint.

Exposes ``GET /api/graph/payload`` over the existing wiki graph
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

router = APIRouter(prefix="/api/graph", tags=["Graph"])

ScopeKindQ = Literal["question", "material", "concept"]


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


@router.get("/payload", response_model=GraphPayloadV0)
def graph_payload(
    scope_kind: ScopeKindQ = Query("question", description="What this subgraph is scoped to."),
    scope_ref: str = Query("", description="The question text, material_id, or concept id."),
    filter: str | None = Query(
        default=None,
        description="Comma-separated node ids to keep; omit for the full snapshot.",
    ),
) -> GraphPayloadV0:
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
