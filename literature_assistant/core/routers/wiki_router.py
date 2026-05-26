from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from literature_assistant.core.project_paths import (
    wiki_generated_root,
    wiki_graph_db_path,
    wiki_graph_path,
    wiki_query_index_path,
    wiki_review_queue_path,
    wiki_runtime_db_path,
)
from literature_assistant.core.runtime_env import wiki_enabled
from literature_assistant.core.wiki.compiler import WikiCompiler
from literature_assistant.core.wiki.doctor import WikiDoctor
from literature_assistant.core.wiki.graph import WikiGraphStore, build_wiki_graph
from literature_assistant.core.wiki.observability import default_wiki_observability_sink
from literature_assistant.core.wiki.page_store import WikiPageStore, stable_slug
from literature_assistant.core.wiki.query import WikiQueryIndex, WikiSearchResult, wiki_query_with_fallback
from literature_assistant.core.wiki.review_queue import (
    ReviewItemKind,
    ReviewItemStatus,
    ReviewQueue,
)
from literature_assistant.core.wiki.source_registry import WikiRegistry


router = APIRouter(prefix="/api/wiki", tags=["Wiki"])
_SAFE_FILTER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class WikiStatusResponse(BaseModel):
    enabled: bool
    page_count: int = 0
    stale: bool = False
    graph_json_exists: bool = False
    graph_db_exists: bool = False
    query_index_exists: bool = False
    review_queue_exists: bool = False
    paths: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class WikiPageSummaryPayload(BaseModel):
    path: str
    title: str
    kind: str
    status: str


class WikiPageListResponse(BaseModel):
    enabled: bool
    pages: list[WikiPageSummaryPayload] = Field(default_factory=list)


class WikiPageReadResponse(BaseModel):
    enabled: bool
    path: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    body: str = ""


class WikiDoctorResponse(BaseModel):
    enabled: bool
    report: dict[str, Any] = Field(default_factory=dict)


class WikiGraphResponse(BaseModel):
    enabled: bool
    graph: dict[str, Any] = Field(default_factory=dict)


class WikiReviewItemPayload(BaseModel):
    item_id: str
    kind: str
    title: str
    page_path: str
    summary: str
    status: str
    created_at: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    decision: dict[str, Any] | None = None


class WikiReviewListResponse(BaseModel):
    enabled: bool
    items: list[WikiReviewItemPayload] = Field(default_factory=list)


class WikiReviewDecisionRequest(BaseModel):
    reason: str = ""
    decided_by: str = "user"


class WikiCompileRequest(BaseModel):
    dry_run: bool = True
    source_id: str | None = None
    project_id: str | None = None


class WikiCompileResponse(BaseModel):
    enabled: bool
    dry_run: bool
    created: int = 0
    updated: int = 0
    skipped: int = 0
    planned_paths: list[str] = Field(default_factory=list)
    written_paths: list[str] = Field(default_factory=list)
    budget_summary: dict[str, Any] = Field(default_factory=dict)
    budget_checks: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WikiQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    wiki_first: bool = False
    save: bool = False
    debug: bool = False


class WikiQueryResponse(BaseModel):
    enabled: bool
    fallback_required: bool
    answer: str = ""
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _page_store(*, create: bool = True) -> WikiPageStore:
    return WikiPageStore(wiki_generated_root(), create=create)


def _dry_run_page_store() -> WikiPageStore:
    return WikiPageStore(wiki_generated_root(), create=False)


def _doctor() -> WikiDoctor:
    return WikiDoctor(
        _page_store(create=False),
        registry=WikiRegistry(wiki_runtime_db_path()) if wiki_runtime_db_path().exists() else None,
        query_index=WikiQueryIndex(wiki_query_index_path()) if wiki_query_index_path().exists() else None,
        graph_store=WikiGraphStore.default(),
        observability_sink=default_wiki_observability_sink(),
    )


def _status_stale(page_count: int, *, enabled: bool) -> tuple[bool, list[str]]:
    if not enabled:
        return False, []

    index_path = wiki_query_index_path()
    if not index_path.exists():
        return page_count > 0, []

    index = WikiQueryIndex(index_path)
    try:
        status = index.get_status()
    except Exception:
        return True, ["Wiki query index status could not be read; marking wiki status as stale."]
    finally:
        index.close()

    return status.stale or status.page_count != page_count, []


def _disabled_warning() -> list[str]:
    return ["Wiki integration is disabled. Set LITERATURE_ASSISTANT_WIKI_ENABLED=1 to enable wiki APIs."]


def _sanitize_status_path(path: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(Path(__file__).resolve().parents[3]).as_posix()
    except ValueError:
        return f"<external>/{resolved.name}" if resolved.name else "<external>"


def _normalize_filter_token(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not _SAFE_FILTER_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a simple lowercase token")
    return normalized


def _singularize_kind(value: str) -> str:
    if value.endswith("ies") and len(value) > 3:
        return f"{value[:-3]}y"
    if value.endswith("s") and len(value) > 1:
        return value[:-1]
    return value


def _kind_matches_filter(summary: WikiPageSummaryPayload, kind_filter: str) -> bool:
    candidates = {
        summary.kind.strip().lower(),
        _singularize_kind(summary.kind.strip().lower()),
        Path(summary.path).parts[0].strip().lower() if Path(summary.path).parts else "",
        _singularize_kind(Path(summary.path).parts[0].strip().lower()) if Path(summary.path).parts else "",
    }
    return kind_filter in candidates or _singularize_kind(kind_filter) in candidates


def _normalize_identifier(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not _SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise HTTPException(status_code=400, detail=f"{field_name} contains unsupported characters")
    return normalized


def _query_evidence_ref(result: WikiSearchResult) -> dict[str, Any]:
    return {
        "page_path": result.page_path.as_posix(),
        "title": result.title,
        "score": result.score,
        "snippet": result.snippet,
        "source": result.source,
        "source_labels": ["wiki_first", result.source],
    }


def _normalize_page_path(page_path: str) -> Path:
    normalized = page_path.strip().replace("\\", "/")
    if not normalized:
        raise HTTPException(status_code=400, detail="page_path cannot be empty")
    if any(ord(char) < 32 for char in normalized):
        raise HTTPException(status_code=400, detail="page_path contains control characters")
    relative_path = Path(normalized)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise HTTPException(status_code=400, detail="page_path must stay inside the wiki root")
    if relative_path.suffix and relative_path.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="page_path must target a markdown page")
    if not relative_path.suffix:
        relative_path = relative_path.with_suffix(".md")
    return relative_path


def _empty_compile_budget_summary() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "input_cost_usd": 0.0,
        "output_cost_usd": 0.0,
        "estimated_cost_usd": 0.0,
        "pricing_configured": False,
        "pricing_source": "not_configured",
        "currency": "USD",
    }


def _planned_paths_for_source(registry: WikiRegistry, source_id: str) -> list[str]:
    source = registry.get_source(source_id)
    if source is None:
        return []
    slug = stable_slug(source.title)
    planned = [Path("sources") / f"{slug}.md"]
    if source.source_type == "paper":
        planned.append(Path("papers") / f"{slug}.md")
    return [path.as_posix() for path in planned]


def _planned_paths_for_project(compiler: WikiCompiler) -> list[str]:
    plan = compiler.plan_compile()
    paths = [*plan.pages_to_create, *plan.pages_to_update]
    return [path.as_posix() for path in paths]


def _parse_page_content(path: Path, content: str) -> WikiPageSummaryPayload:
    frontmatter, _body = _split_frontmatter(content)
    return WikiPageSummaryPayload(
        path=path.as_posix(),
        title=str(frontmatter.get("title") or path.stem),
        kind=str(frontmatter.get("kind") or path.parent.as_posix() or "unknown"),
        status=str(frontmatter.get("status") or "draft"),
    )


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    lines = content.split("\n")
    if lines and lines[0].strip() == "---json":
        frontmatter_lines: list[str] = []
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                try:
                    payload = json.loads("\n".join(frontmatter_lines))
                    frontmatter = payload if isinstance(payload, dict) else {}
                except json.JSONDecodeError:
                    frontmatter = {}
                return frontmatter, "\n".join(lines[index + 1 :])
            frontmatter_lines.append(line)
    return {}, content


@router.get("/status", response_model=WikiStatusResponse)
def wiki_status() -> WikiStatusResponse:
    enabled = wiki_enabled()
    store = _page_store(create=False)
    pages = store.list_pages() if store.wiki_root.exists() else []
    page_count = len(pages) if enabled else 0
    stale, stale_warnings = _status_stale(page_count, enabled=enabled)
    warnings = stale_warnings if enabled else _disabled_warning()
    return WikiStatusResponse(
        enabled=enabled,
        page_count=page_count,
        stale=stale,
        graph_json_exists=wiki_graph_path().exists(),
        graph_db_exists=wiki_graph_db_path().exists(),
        query_index_exists=wiki_query_index_path().exists(),
        review_queue_exists=wiki_review_queue_path().exists(),
        paths={
            "wiki_root": _sanitize_status_path(store.wiki_root),
            "graph_json": _sanitize_status_path(wiki_graph_path()),
            "graph_db": _sanitize_status_path(wiki_graph_db_path()),
            "query_index": _sanitize_status_path(wiki_query_index_path()),
            "review_queue": _sanitize_status_path(wiki_review_queue_path()),
        },
        warnings=warnings,
    )


@router.post("/compile", response_model=WikiCompileResponse)
def wiki_compile(request: WikiCompileRequest) -> WikiCompileResponse:
    if not wiki_enabled():
        return WikiCompileResponse(
            enabled=False,
            dry_run=request.dry_run,
            budget_summary=_empty_compile_budget_summary(),
            warnings=_disabled_warning(),
        )
    source_id = _normalize_identifier(request.source_id, "source_id")
    project_id = _normalize_identifier(request.project_id, "project_id")
    if not request.dry_run:
        raise HTTPException(status_code=400, detail="Non-dry-run wiki compile is not enabled in this contract slice")
    registry_path = wiki_runtime_db_path()
    if not registry_path.exists():
        return WikiCompileResponse(
            enabled=True,
            dry_run=True,
            budget_summary=_empty_compile_budget_summary(),
            warnings=[
                "Wiki registry database is not available; run source registration or migration dry-run before compile planning."
            ],
        )
    registry = WikiRegistry(registry_path)
    compiler = WikiCompiler(registry, _dry_run_page_store(), observability_sink=default_wiki_observability_sink())
    if source_id:
        result = compiler.compile_source(source_id, dry_run=True)
        planned_paths = _planned_paths_for_source(registry, source_id)
    else:
        result = compiler.compile_project(dry_run=True)
        planned_paths = _planned_paths_for_project(compiler)
    warnings = ["Compile dry-run completed without writing wiki pages."]
    if project_id:
        warnings.append("project_id is accepted for forward compatibility; current compile planning is registry/source based.")
    warnings.extend(result.errors)
    return WikiCompileResponse(
        enabled=True,
        dry_run=True,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        planned_paths=planned_paths,
        budget_summary=result.cost_estimate.to_dict(),
        budget_checks=[check.to_dict() for check in result.budget_checks],
        errors=list(result.errors),
        warnings=warnings,
    )


@router.post("/query", response_model=WikiQueryResponse)
def wiki_query(request: WikiQueryRequest) -> WikiQueryResponse:
    if not wiki_enabled():
        return WikiQueryResponse(
            enabled=False,
            fallback_required=True,
            warnings=_disabled_warning(),
        )
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query cannot be empty")
    if request.save:
        raise HTTPException(status_code=400, detail="Saved exploration API requires explicit service integration")
    index_path = wiki_query_index_path()
    sink = default_wiki_observability_sink()
    if not index_path.exists():
        sink.emit_event("wiki.query.fallback_required", {"reason": "missing_index", "query": query})
        return WikiQueryResponse(
            enabled=True,
            fallback_required=True,
            warnings=["Wiki query index is not available; call the main RAG chain for raw-corpus fallback."],
        )
    index = WikiQueryIndex(index_path, observability_sink=sink)
    try:
        with sink.start_span("wiki.router.query", {"wiki_first": request.wiki_first, "debug": request.debug}):
            result = wiki_query_with_fallback(
                query,
                index,
                _page_store(create=False),
                enabled=True,
                limit=5,
                expand_links=True,
                max_linked=3,
            )
        hits = [*result.wiki_hits, *result.linked_hits]
        sink.emit_event(
            "wiki.query.completed",
            {
                "query": query,
                "wiki_hits": len(result.wiki_hits),
                "linked_hits": len(result.linked_hits),
                "fallback_required": result.fallback_used,
                "fallback_reason": result.fallback_reason,
            },
            status="warning" if result.fallback_used else "ok",
        )
        sink.record_metric("wiki.query.router.evidence_refs", len(hits), {"fallback_required": result.fallback_used})
        warnings: list[str] = []
        if result.fallback_used:
            warnings.append(f"Wiki query returned no usable hits: {result.fallback_reason}.")
            warnings.append("Call the main RAG chain for raw-corpus fallback.")
        return WikiQueryResponse(
            enabled=True,
            fallback_required=result.fallback_used,
            answer="" if result.fallback_used else "Wiki evidence is available; use evidence_refs for grounded context.",
            evidence_refs=[_query_evidence_ref(hit) for hit in hits],
            warnings=warnings,
        )
    except Exception as exc:
        sink.emit_event("wiki.query.failed", {"query": query, "error": type(exc).__name__}, status="error")
        return WikiQueryResponse(
            enabled=True,
            fallback_required=True,
            warnings=[f"Wiki query failed; call the main RAG chain for raw-corpus fallback: {type(exc).__name__}"],
        )
    finally:
        index.close()


@router.get("/pages", response_model=WikiPageListResponse)
def wiki_pages(kind: str | None = Query(default=None), status: str | None = Query(default=None)) -> WikiPageListResponse:
    if not wiki_enabled():
        return WikiPageListResponse(enabled=False, pages=[])
    store = _page_store(create=False)
    kind_filter = _normalize_filter_token(kind, "kind")
    status_filter = _normalize_filter_token(status, "status")
    pages: list[WikiPageSummaryPayload] = []
    for page_path in store.list_pages():
        content = store.read_page(page_path)
        if not content:
            continue
        summary = _parse_page_content(page_path, content)
        if kind_filter is not None and not _kind_matches_filter(summary, kind_filter):
            continue
        if status_filter is not None and summary.status.strip().lower() != status_filter:
            continue
        pages.append(summary)
    return WikiPageListResponse(enabled=True, pages=pages)


@router.get("/pages/{slug}/permissions")
def get_wiki_page_permissions(slug: str, user_id: str | None = Query(default=None)) -> dict[str, Any]:
    """Get permissions for a wiki page (G14 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from wiki.permissions import get_permissions, can_read
    from wiki.service import get_wiki_service

    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    if not can_read(page.extra, user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    perms = get_permissions(page.extra, default_owner="system")
    return {
        "owner": perms.owner,
        "visibility": perms.visibility.value,
        "shared_with": list(perms.shared_with),
    }


@router.put("/pages/{slug}/permissions")
def update_wiki_page_permissions(
    slug: str,
    request: dict[str, Any],
    user_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Update permissions for a wiki page (G14 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from wiki.permissions import (
        WikiPagePermissions,
        WikiPageVisibility,
        get_permissions,
        set_permissions,
        can_write,
    )
    from wiki.service import get_wiki_service

    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    if not can_write(page.extra, user_id):
        raise HTTPException(status_code=403, detail="Only owner can update permissions")

    try:
        visibility = WikiPageVisibility(request.get("visibility", "public"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid visibility: {request.get('visibility')}") from exc

    shared_with = request.get("shared_with", [])
    if not isinstance(shared_with, list):
        raise HTTPException(status_code=400, detail="shared_with must be a list")

    current_perms = get_permissions(page.extra, default_owner="system")
    new_perms = WikiPagePermissions(
        owner=current_perms.owner,
        visibility=visibility,
        shared_with=tuple(str(u) for u in shared_with),
    )

    new_extra = set_permissions(page.extra, new_perms)
    service.update_page_extra(slug, new_extra)

    return {
        "owner": new_perms.owner,
        "visibility": new_perms.visibility.value,
        "shared_with": list(new_perms.shared_with),
    }


@router.get("/pages/{page_path:path}", response_model=WikiPageReadResponse)
def wiki_page_read(page_path: str) -> WikiPageReadResponse:
    if not wiki_enabled():
        return WikiPageReadResponse(enabled=False, path=page_path)
    relative_path = _normalize_page_path(page_path)
    content = _page_store(create=False).read_page(relative_path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {page_path}")
    frontmatter, body = _split_frontmatter(content)
    return WikiPageReadResponse(
        enabled=True,
        path=relative_path.as_posix(),
        frontmatter=frontmatter,
        body=body,
    )


@router.get("/doctor", response_model=WikiDoctorResponse)
def wiki_doctor() -> WikiDoctorResponse:
    if not wiki_enabled():
        return WikiDoctorResponse(enabled=False, report={"warnings": _disabled_warning()})
    return WikiDoctorResponse(enabled=True, report=_doctor().run().to_dict())


@router.get("/graph", response_model=WikiGraphResponse)
def wiki_graph() -> WikiGraphResponse:
    if not wiki_enabled():
        return WikiGraphResponse(enabled=False, graph={})
    snapshot = build_wiki_graph(_page_store(create=False))
    return WikiGraphResponse(enabled=True, graph=snapshot.to_dict())


@router.get("/review", response_model=WikiReviewListResponse)
def wiki_review_list(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
) -> WikiReviewListResponse:
    if not wiki_enabled():
        return WikiReviewListResponse(enabled=False, items=[])
    normalized_status = _normalize_filter_token(status, "status")
    normalized_kind = _normalize_filter_token(kind, "kind")
    try:
        parsed_status = ReviewItemStatus(normalized_status) if normalized_status else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unsupported review status: {normalized_status}") from exc
    try:
        parsed_kind = ReviewItemKind(normalized_kind) if normalized_kind else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unsupported review kind: {normalized_kind}") from exc
    queue = ReviewQueue(wiki_review_queue_path())
    return WikiReviewListResponse(
        enabled=True,
        items=[WikiReviewItemPayload(**item.to_dict()) for item in queue.list_items(status=parsed_status, kind=parsed_kind)],
    )


@router.post("/review/{item_id}/approve", response_model=WikiReviewItemPayload)
def wiki_review_approve(item_id: str, request: WikiReviewDecisionRequest) -> WikiReviewItemPayload:
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")
    try:
        item = ReviewQueue(wiki_review_queue_path()).approve(
            item_id,
            reason=request.reason,
            decided_by=request.decided_by,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Review item not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WikiReviewItemPayload(**item.to_dict())


@router.post("/review/{item_id}/reject", response_model=WikiReviewItemPayload)
def wiki_review_reject(item_id: str, request: WikiReviewDecisionRequest) -> WikiReviewItemPayload:
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")
    try:
        item = ReviewQueue(wiki_review_queue_path()).reject(
            item_id,
            reason=request.reason,
            decided_by=request.decided_by,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Review item not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WikiReviewItemPayload(**item.to_dict())

