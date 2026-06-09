from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from literature_assistant.core.project_paths import (
    REPO_ROOT,
    WORKSPACE_ARTIFACTS_ROOT,
    WORKSPACE_REFERENCES_ROOT,
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
from literature_assistant.core.wiki.models import WikiPageKind, WikiPageStatus, make_stable_slug
from literature_assistant.core.wiki.observability import default_wiki_observability_sink
from literature_assistant.core.wiki.page_store import AUTO_END, AUTO_START, WikiPageStore, stable_slug
from literature_assistant.core.wiki.permissions import (
    DEFAULT_WIKI_OWNER,
    PERMISSIONS_KEY,
    WikiPagePermissions,
    WikiPageVisibility,
    can_read,
    can_write,
    get_permissions,
    normalize_shared_with,
    normalize_user_id,
    set_permissions,
)
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
_SAFE_EXPORT_ARCHIVE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.zip$")
_MAX_WIKI_IMPORT_FILES = 20
_MAX_WIKI_IMPORT_FILE_BYTES = 1_000_000
_MAX_WIKI_IMPORT_TOTAL_BYTES = 5_000_000


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


class WikiCategoryNodePayload(BaseModel):
    key: str
    label: str
    page_count: int = 0
    pages: list[WikiPageSummaryPayload] = Field(default_factory=list)
    children: list["WikiCategoryNodePayload"] = Field(default_factory=list)


class WikiCategoriesResponse(BaseModel):
    enabled: bool
    categories: list[WikiCategoryNodePayload] = Field(default_factory=list)


class WikiTagPayload(BaseModel):
    key: str
    label: str
    page_count: int = 0
    pages: list[WikiPageSummaryPayload] = Field(default_factory=list)


class WikiTagsResponse(BaseModel):
    enabled: bool
    tags: list[WikiTagPayload] = Field(default_factory=list)


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
    allow_write: bool = False
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


class WikiPageCreateRequest(BaseModel):
    """Request to create a new wiki page (G2 2026-05-26)."""
    title: str
    kind: str
    body: str
    status: str = "draft"
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    source_hashes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class WikiPageUpdateRequest(BaseModel):
    """Request to update an existing wiki page (G2 2026-05-26)."""
    title: str | None = None
    body: str | None = None
    status: str | None = None
    evidence_refs: list[dict[str, Any]] | None = None
    source_hashes: list[str] | None = None
    extra: dict[str, Any] | None = None


class WikiPageMutationResponse(BaseModel):
    """Response for create/update/delete operations (G2 2026-05-26)."""
    success: bool
    slug: str
    message: str = ""


class WikiPageVersionPayload(BaseModel):
    version: int
    action: str
    stable_slug: str
    kind: str
    status: str
    title: str
    body_hash: str
    created_at_iso: str
    updated_at_iso: str
    recorded_at_iso: str


class WikiPageVersionsResponse(BaseModel):
    enabled: bool
    slug: str
    versions: list[WikiPageVersionPayload] = Field(default_factory=list)


class WikiExportResponse(BaseModel):
    """Response for wiki export operation (G15 2026-05-26)."""
    success: bool
    page_count: int
    output_path: str
    errors: list[str] = Field(default_factory=list)


class WikiImportRequest(BaseModel):
    """Local Markdown import request for the wiki sidecar."""

    source_paths: list[str] = Field(default_factory=list)
    dry_run: bool = True
    overwrite: bool = False
    kind: str = WikiPageKind.synthesis.value
    status: str = WikiPageStatus.draft.value


class WikiImportItemPayload(BaseModel):
    """Per-source result for local Markdown import."""

    source_path: str
    title: str = ""
    kind: str = ""
    status: str = ""
    slug: str = ""
    path: str = ""
    action: str
    warnings: list[str] = Field(default_factory=list)
    error: str = ""


class WikiImportResponse(BaseModel):
    """Response for local Markdown wiki import."""

    enabled: bool
    dry_run: bool
    imported: int = 0
    skipped: int = 0
    errored: int = 0
    pages: list[WikiImportItemPayload] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WikiPagePermissionsRequest(BaseModel):
    """Page visibility update request for local wiki ACLs."""

    visibility: str = Field(default=WikiPageVisibility.PRIVATE.value)
    shared_with: list[str] = Field(default_factory=list)


class WikiPagePermissionsResponse(BaseModel):
    """Serialized local wiki ACL state."""

    owner: str
    visibility: str
    shared_with: list[str] = Field(default_factory=list)


def _page_store(*, create: bool = True) -> WikiPageStore:
    return WikiPageStore(wiki_generated_root(), create=create)


def _dry_run_page_store() -> WikiPageStore:
    return WikiPageStore(wiki_generated_root(), create=False)


def _doctor(page_store: WikiPageStore | None = None) -> WikiDoctor:
    store = page_store or _page_store(create=False)
    return WikiDoctor(
        store,
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


def _wiki_import_allowed_roots() -> tuple[Path, ...]:
    return (
        REPO_ROOT,
        WORKSPACE_ARTIFACTS_ROOT,
        WORKSPACE_REFERENCES_ROOT,
    )


def _wiki_import_forbidden_roots() -> tuple[Path, ...]:
    return (
        REPO_ROOT / ".git",
        REPO_ROOT / ".rollback_snapshots",
        REPO_ROOT / "github",
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_wiki_export_path(raw_output_path: str | None) -> Path:
    """Return a zip export path under the canonical wiki export root.

    Args:
        raw_output_path: Optional user-provided archive filename. It must be a
            filename only; absolute paths, parent directories, and alternate
            suffixes are rejected.

    Returns:
        Resolved path inside ``workspace_artifacts/wiki_exports``.
    """
    from datetime import datetime, timezone

    export_dir = (WORKSPACE_ARTIFACTS_ROOT / "wiki_exports").resolve()
    export_dir.mkdir(parents=True, exist_ok=True)

    if raw_output_path is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"wiki_export_{timestamp}.zip"
    else:
        filename = str(raw_output_path or "").strip()
        if not filename:
            raise HTTPException(status_code=400, detail="output_path must be a non-empty zip filename")
        candidate = Path(filename)
        if candidate.is_absolute() or filename != candidate.name or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="output_path must be a filename under wiki_exports")
        if not filename.lower().endswith(".zip"):
            filename = f"{filename}.zip"
        if not _SAFE_EXPORT_ARCHIVE_RE.fullmatch(filename):
            raise HTTPException(status_code=400, detail="output_path must be a safe .zip filename")

    resolved = (export_dir / filename).resolve()
    if not _is_relative_to(resolved, export_dir):
        raise HTTPException(status_code=400, detail="output_path escapes wiki export root")
    return resolved


def _safe_import_source_label(path: Path) -> str:
    resolved = path.resolve()
    for root in (REPO_ROOT, WORKSPACE_ARTIFACTS_ROOT, WORKSPACE_REFERENCES_ROOT):
        root_resolved = root.resolve()
        if _is_relative_to(resolved, root_resolved):
            return resolved.relative_to(root_resolved).as_posix()
    return resolved.name


def _resolve_wiki_import_source(raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("source_path cannot be empty")
    candidate = Path(raw_path.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    resolved = candidate.resolve()
    if resolved.suffix.lower() != ".md":
        raise ValueError("source_path must point to a Markdown .md file")
    if not any(_is_relative_to(resolved, root) for root in _wiki_import_allowed_roots()):
        raise ValueError("source_path must stay inside an allowed local workspace root")
    if any(_is_relative_to(resolved, root) for root in _wiki_import_forbidden_roots()):
        raise ValueError("source_path points to a protected workspace area")
    if not resolved.is_file():
        raise FileNotFoundError(f"Markdown source not found: {_safe_import_source_label(resolved)}")
    size = resolved.stat().st_size
    if size > _MAX_WIKI_IMPORT_FILE_BYTES:
        raise ValueError(f"Markdown source exceeds {_MAX_WIKI_IMPORT_FILE_BYTES} bytes")
    return resolved


def _markdown_import_title(path: Path, frontmatter: dict[str, Any], body: str) -> str:
    raw_title = frontmatter.get("title")
    if isinstance(raw_title, str) and raw_title.strip():
        return raw_title.strip()
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return path.stem.replace("_", " ").replace("-", " ").strip() or "Imported Markdown"


def _strip_wiki_auto_markers(body: str) -> str:
    kept_lines = [
        line
        for line in body.splitlines()
        if line.strip() not in {AUTO_START, AUTO_END}
    ]
    return "\n".join(kept_lines).strip()


def _wiki_import_extra(source_path: Path, content_hash: str, owner: str) -> dict[str, Any]:
    return set_permissions(
        {
            "import_source": {
                "type": "local_markdown",
                "path": _safe_import_source_label(source_path),
                "sha256": content_hash,
            }
        },
        WikiPagePermissions(owner=owner, visibility=WikiPageVisibility.PRIVATE),
    )


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


def _written_paths_for_compile(planned_paths: list[str], dry_run: bool) -> list[str]:
    if dry_run:
        return []
    store = _page_store(create=False)
    return [path for path in planned_paths if store.read_page(Path(path)) is not None]


def _parse_page_content(path: Path, content: str) -> WikiPageSummaryPayload:
    frontmatter, _body = _split_frontmatter(content)
    return WikiPageSummaryPayload(
        path=path.as_posix(),
        title=str(frontmatter.get("title") or path.stem),
        kind=str(frontmatter.get("kind") or path.parent.as_posix() or "unknown"),
        status=str(frontmatter.get("status") or "draft"),
    )


def _category_values(frontmatter: dict[str, Any], summary: WikiPageSummaryPayload) -> list[str]:
    values: list[str] = []
    for key in ("category", "categories"):
        raw_value = frontmatter.get(key)
        if isinstance(raw_value, str):
            values.extend(part.strip() for part in raw_value.split("/") if part.strip())
        elif isinstance(raw_value, list):
            values.extend(str(item).strip() for item in raw_value if str(item).strip())
    if not values:
        kind = summary.kind.strip() or Path(summary.path).parts[0]
        values.append(kind)
    return values


def _category_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return normalized[:64] or "uncategorized"


def _tag_values(frontmatter: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("tags", "labels", "category", "categories"):
        raw_value = frontmatter.get(key)
        if isinstance(raw_value, str):
            values.extend(part.strip() for part in re.split(r"[,/]", raw_value) if part.strip())
        elif isinstance(raw_value, list):
            values.extend(str(item).strip() for item in raw_value if str(item).strip())
    deduped: dict[str, str] = {}
    for value in values:
        deduped.setdefault(_category_key(value), value)
    return list(deduped.values())


def _build_tag_index(entries: list[tuple[list[str], WikiPageSummaryPayload]]) -> list[WikiTagPayload]:
    tags: dict[str, WikiTagPayload] = {}
    for tag_values, summary in entries:
        for label in tag_values:
            key = _category_key(label)
            payload = tags.get(key)
            if payload is None:
                payload = WikiTagPayload(key=key, label=label, page_count=0)
                tags[key] = payload
            payload.page_count += 1
            payload.pages.append(summary)
    return sorted(tags.values(), key=lambda item: (item.label.lower(), item.key))


def _build_category_tree(entries: list[tuple[list[str], WikiPageSummaryPayload]]) -> list[WikiCategoryNodePayload]:
    nodes_by_key: dict[str, WikiCategoryNodePayload] = {}
    root_order: list[str] = []

    for category_path, summary in entries:
        parent_children: list[WikiCategoryNodePayload] | None = None
        compound_key = ""
        for label in category_path:
            node_key = _category_key(label)
            compound_key = f"{compound_key}/{node_key}" if compound_key else node_key
            node = nodes_by_key.get(compound_key)
            if node is None:
                node = WikiCategoryNodePayload(key=compound_key, label=label.strip(), page_count=0)
                nodes_by_key[compound_key] = node
                if parent_children is None:
                    root_order.append(compound_key)
                else:
                    parent_children.append(node)
            node.page_count += 1
            parent_children = node.children
        if category_path:
            nodes_by_key[compound_key].pages.append(summary)

    return [nodes_by_key[key] for key in root_order]


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


def _current_wiki_user(user_id: str | None) -> str:
    try:
        return normalize_user_id(user_id, default=DEFAULT_WIKI_OWNER)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _frontmatter_extra(frontmatter: dict[str, Any]) -> dict[str, Any]:
    extra = frontmatter.get("extra")
    return dict(extra) if isinstance(extra, dict) else {}


def _ensure_can_read_extra(extra: dict[str, Any], user_id: str) -> None:
    if not can_read(extra, user_id, default_owner=DEFAULT_WIKI_OWNER):
        raise HTTPException(status_code=403, detail="Access denied")


def _ensure_can_write_extra(extra: dict[str, Any], user_id: str) -> None:
    if not can_write(extra, user_id, default_owner=DEFAULT_WIKI_OWNER):
        raise HTTPException(status_code=403, detail="Only owner can update this wiki page")


def _permissions_response(permissions: WikiPagePermissions) -> WikiPagePermissionsResponse:
    return WikiPagePermissionsResponse(
        owner=permissions.owner,
        visibility=permissions.visibility.value,
        shared_with=list(permissions.shared_with),
    )


class _AuthorizedWikiPageStore(WikiPageStore):
    """Read-only page store view that hides pages the current user cannot read."""

    def __init__(self, page_store: WikiPageStore, user_id: str) -> None:
        super().__init__(page_store.wiki_root, create=False)
        self._user_id = user_id

    def read_page(self, relative_path: Path) -> str | None:
        content = super().read_page(relative_path)
        if content is None:
            return None
        frontmatter, _body = _split_frontmatter(str(content))
        if not can_read(_frontmatter_extra(frontmatter), self._user_id, default_owner=DEFAULT_WIKI_OWNER):
            return None
        return content

    def list_pages(self, kind_dir: str | None = None) -> list[Path]:
        return [page_path for page_path in super().list_pages(kind_dir) if self.read_page(page_path) is not None]


def _authorized_page_store(user_id: str) -> WikiPageStore:
    return _AuthorizedWikiPageStore(_page_store(create=False), user_id)


@router.post("/import", response_model=WikiImportResponse)
def wiki_import(
    request: WikiImportRequest,
    user_id: str | None = Query(default=None),
) -> WikiImportResponse:
    """Import local Markdown files into private wiki pages.

    The endpoint accepts only local `.md` paths inside the configured workspace
    roots so a browser caller cannot use the API as a general filesystem reader.
    """
    if not wiki_enabled():
        return WikiImportResponse(enabled=False, dry_run=request.dry_run, warnings=_disabled_warning())

    if not request.source_paths:
        raise HTTPException(status_code=400, detail="source_paths cannot be empty")
    if len(request.source_paths) > _MAX_WIKI_IMPORT_FILES:
        raise HTTPException(status_code=400, detail=f"source_paths cannot contain more than {_MAX_WIKI_IMPORT_FILES} files")

    current_user = _current_wiki_user(user_id)
    try:
        page_kind = WikiPageKind(request.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid wiki page kind: {request.kind}") from exc
    try:
        page_status = WikiPageStatus(request.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid wiki page status: {request.status}") from exc

    from wiki.service import get_wiki_service

    service = get_wiki_service()
    pages: list[WikiImportItemPayload] = []
    imported = 0
    skipped = 0
    errored = 0
    total_bytes = 0

    for raw_path in request.source_paths:
        source_label = str(raw_path)
        try:
            source_path = _resolve_wiki_import_source(raw_path)
            source_label = _safe_import_source_label(source_path)
            source_bytes = source_path.read_bytes()
            total_bytes += len(source_bytes)
            if total_bytes > _MAX_WIKI_IMPORT_TOTAL_BYTES:
                raise ValueError(f"Markdown import batch exceeds {_MAX_WIKI_IMPORT_TOTAL_BYTES} bytes")
            content = source_bytes.decode("utf-8")
            frontmatter, raw_body = _split_frontmatter(content)
            body = _strip_wiki_auto_markers(raw_body)
            if not body:
                raise ValueError("Markdown source body cannot be empty")
            title = _markdown_import_title(source_path, frontmatter, body)
            slug = make_stable_slug(title, page_kind)
            relative_path = (Path(page_kind.value) / f"{slug}.md").as_posix()
            existing_page = service.get_page(slug)
            if existing_page is not None and not request.overwrite:
                skipped += 1
                pages.append(
                    WikiImportItemPayload(
                        source_path=source_label,
                        title=title,
                        kind=page_kind.value,
                        status=page_status.value,
                        slug=slug,
                        path=relative_path,
                        action="skipped_exists",
                        warnings=["A wiki page with this slug already exists; set overwrite=true to update it."],
                    )
                )
                continue
            if request.dry_run:
                skipped += 1
                pages.append(
                    WikiImportItemPayload(
                        source_path=source_label,
                        title=title,
                        kind=page_kind.value,
                        status=page_status.value,
                        slug=slug,
                        path=relative_path,
                        action="planned_update" if existing_page is not None else "planned_create",
                    )
                )
                continue
            content_hash = hashlib.sha256(source_bytes).hexdigest()
            extra = _wiki_import_extra(source_path, content_hash, current_user)
            if existing_page is None:
                page = service.create_page(
                    title=title,
                    kind=page_kind.value,
                    body=body,
                    status=page_status.value,
                    source_hashes=[content_hash],
                    extra=extra,
                )
                action = "created"
            else:
                _ensure_can_write_extra(existing_page.extra, current_user)
                page = service.update_page(
                    slug=slug,
                    title=title,
                    body=body,
                    status=page_status.value,
                    source_hashes=[content_hash],
                    extra=extra,
                )
                action = "updated"
            imported += 1
            pages.append(
                WikiImportItemPayload(
                    source_path=source_label,
                    title=title,
                    kind=page.kind.value,
                    status=page.status.value,
                    slug=page.stable_slug,
                    path=(Path(page.kind.value) / f"{page.stable_slug}.md").as_posix(),
                    action=action,
                )
            )
        except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError) as exc:
            errored += 1
            pages.append(WikiImportItemPayload(source_path=source_label, action="error", error=str(exc)))

    return WikiImportResponse(
        enabled=True,
        dry_run=request.dry_run,
        imported=imported,
        skipped=skipped,
        errored=errored,
        pages=pages,
    )


@router.get("/status", response_model=WikiStatusResponse)
def wiki_status(user_id: str | None = Query(default=None)) -> WikiStatusResponse:
    enabled = wiki_enabled()
    current_user = _current_wiki_user(user_id)
    store = _authorized_page_store(current_user)
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
    if not request.dry_run and not request.allow_write:
        raise HTTPException(status_code=400, detail="Non-dry-run wiki compile requires allow_write=true")
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
        result = compiler.compile_source(source_id, dry_run=request.dry_run)
        planned_paths = _planned_paths_for_source(registry, source_id)
    else:
        result = compiler.compile_project(dry_run=request.dry_run)
        planned_paths = _planned_paths_for_project(compiler)
    warnings = [
        "Compile dry-run completed without writing wiki pages."
        if request.dry_run
        else "Compile write completed; generated wiki pages were written to the workspace wiki root."
    ]
    if project_id:
        warnings.append("project_id is accepted for forward compatibility; current compile planning is registry/source based.")
    warnings.extend(result.errors)
    return WikiCompileResponse(
        enabled=True,
        dry_run=request.dry_run,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        planned_paths=planned_paths,
        written_paths=_written_paths_for_compile(planned_paths, request.dry_run),
        budget_summary=result.cost_estimate.to_dict(),
        budget_checks=[check.to_dict() for check in result.budget_checks],
        errors=list(result.errors),
        warnings=warnings,
    )


@router.post("/query", response_model=WikiQueryResponse)
def wiki_query(request: WikiQueryRequest, user_id: str | None = Query(default=None)) -> WikiQueryResponse:
    """Wiki query endpoint (legacy name, use /search instead)."""
    return _wiki_search_impl(request, _current_wiki_user(user_id))


@router.post("/search", response_model=WikiQueryResponse)
def wiki_search(request: WikiQueryRequest, user_id: str | None = Query(default=None)) -> WikiQueryResponse:
    """Wiki search endpoint (G5 2026-05-26, canonical name for /query)."""
    return _wiki_search_impl(request, _current_wiki_user(user_id))


def _wiki_search_impl(request: WikiQueryRequest, user_id: str) -> WikiQueryResponse:
    """Shared implementation for /query and /search endpoints."""
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
    readable_store = _authorized_page_store(user_id)
    try:
        with sink.start_span("wiki.router.query", {"wiki_first": request.wiki_first, "debug": request.debug}):
            result = wiki_query_with_fallback(
                query,
                index,
                readable_store,
                enabled=True,
                limit=5,
                expand_links=True,
                max_linked=3,
            )
        hits = [
            hit
            for hit in [*result.wiki_hits, *result.linked_hits]
            if readable_store.read_page(hit.page_path) is not None
        ]
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
        fallback_required = result.fallback_used or not hits
        if result.fallback_used:
            warnings.append(f"Wiki query returned no usable hits: {result.fallback_reason}.")
            warnings.append("Call the main RAG chain for raw-corpus fallback.")
        elif not hits:
            warnings.append("Wiki query returned only pages outside the current user's permissions.")
            warnings.append("Call the main RAG chain for raw-corpus fallback.")
        return WikiQueryResponse(
            enabled=True,
            fallback_required=fallback_required,
            answer="" if fallback_required else "Wiki evidence is available; use evidence_refs for grounded context.",
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
def wiki_pages(
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
) -> WikiPageListResponse:
    if not wiki_enabled():
        return WikiPageListResponse(enabled=False, pages=[])
    current_user = _current_wiki_user(user_id)
    store = _authorized_page_store(current_user)
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


@router.get("/categories", response_model=WikiCategoriesResponse)
def wiki_categories(user_id: str | None = Query(default=None)) -> WikiCategoriesResponse:
    """Return a read-only category tree derived from readable wiki pages."""
    if not wiki_enabled():
        return WikiCategoriesResponse(enabled=False, categories=[])
    current_user = _current_wiki_user(user_id)
    store = _authorized_page_store(current_user)
    entries: list[tuple[list[str], WikiPageSummaryPayload]] = []
    for page_path in store.list_pages():
        content = store.read_page(page_path)
        if not content:
            continue
        frontmatter, _body = _split_frontmatter(content)
        summary = _parse_page_content(page_path, content)
        entries.append((_category_values(frontmatter, summary), summary))
    return WikiCategoriesResponse(enabled=True, categories=_build_category_tree(entries))


@router.get("/tags", response_model=WikiTagsResponse)
def wiki_tags(user_id: str | None = Query(default=None)) -> WikiTagsResponse:
    """Return a read-only tag index derived from readable wiki pages."""
    if not wiki_enabled():
        return WikiTagsResponse(enabled=False, tags=[])
    current_user = _current_wiki_user(user_id)
    store = _authorized_page_store(current_user)
    entries: list[tuple[list[str], WikiPageSummaryPayload]] = []
    for page_path in store.list_pages():
        content = store.read_page(page_path)
        if not content:
            continue
        frontmatter, _body = _split_frontmatter(content)
        tag_values = _tag_values(frontmatter)
        if not tag_values:
            continue
        entries.append((tag_values, _parse_page_content(page_path, content)))
    return WikiTagsResponse(enabled=True, tags=_build_tag_index(entries))


@router.get("/pages/{slug}/permissions", response_model=WikiPagePermissionsResponse)
def get_wiki_page_permissions(slug: str, user_id: str | None = Query(default=None)) -> WikiPagePermissionsResponse:
    """Get permissions for a wiki page (G14 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    _ensure_can_read_extra(page.extra, current_user)
    return _permissions_response(get_permissions(page.extra, default_owner=DEFAULT_WIKI_OWNER))


@router.put("/pages/{slug}/permissions", response_model=WikiPagePermissionsResponse)
def update_wiki_page_permissions(
    slug: str,
    request: WikiPagePermissionsRequest,
    user_id: str | None = Query(default=None),
) -> WikiPagePermissionsResponse:
    """Update permissions for a wiki page (G14 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")

    _ensure_can_write_extra(page.extra, current_user)

    try:
        visibility = WikiPageVisibility(request.visibility)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid visibility: {request.visibility}") from exc
    try:
        shared_with = normalize_shared_with(request.shared_with)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    current_perms = get_permissions(page.extra, default_owner=DEFAULT_WIKI_OWNER)
    new_perms = WikiPagePermissions(
        owner=current_perms.owner,
        visibility=visibility,
        shared_with=shared_with,
    )

    new_extra = set_permissions(page.extra, new_perms)
    service.update_page_extra(slug, new_extra)
    return _permissions_response(new_perms)


@router.get("/pages/{slug}/versions", response_model=WikiPageVersionsResponse)
def wiki_page_versions(slug: str, user_id: str | None = Query(default=None)) -> WikiPageVersionsResponse:
    """Return local version metadata for one wiki page."""
    if not wiki_enabled():
        return WikiPageVersionsResponse(enabled=False, slug=slug, versions=[])

    from wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    page = service.get_page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {slug}")
    _ensure_can_read_extra(page.extra, current_user)
    return WikiPageVersionsResponse(
        enabled=True,
        slug=slug,
        versions=[WikiPageVersionPayload(**item) for item in service.list_page_versions(slug)],
    )


@router.get("/pages/{page_path:path}", response_model=WikiPageReadResponse)
def wiki_page_read(page_path: str, user_id: str | None = Query(default=None)) -> WikiPageReadResponse:
    if not wiki_enabled():
        return WikiPageReadResponse(enabled=False, path=page_path)
    current_user = _current_wiki_user(user_id)
    relative_path = _normalize_page_path(page_path)
    content = _page_store(create=False).read_page(relative_path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {page_path}")
    frontmatter, body = _split_frontmatter(content)
    _ensure_can_read_extra(_frontmatter_extra(frontmatter), current_user)
    return WikiPageReadResponse(
        enabled=True,
        path=relative_path.as_posix(),
        frontmatter=frontmatter,
        body=body,
    )


@router.post("/pages", response_model=WikiPageMutationResponse)
def wiki_page_create(
    request: WikiPageCreateRequest,
    user_id: str | None = Query(default=None),
) -> WikiPageMutationResponse:
    """Create a new wiki page (G2 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    page_extra = set_permissions(
        {key: value for key, value in request.extra.items() if key != PERMISSIONS_KEY},
        WikiPagePermissions(owner=current_user, visibility=WikiPageVisibility.PRIVATE),
    )
    service = get_wiki_service()
    try:
        page = service.create_page(
            title=request.title,
            kind=request.kind,
            body=request.body,
            status=request.status,
            evidence_refs=request.evidence_refs,
            source_hashes=request.source_hashes,
            extra=page_extra,
        )
    except ValueError as exc:
        detail = str(exc)
        if "already exists" in detail:
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return WikiPageMutationResponse(
        success=True,
        slug=page.stable_slug,
        message=f"Page created: {page.stable_slug}",
    )


@router.put("/pages/{slug}", response_model=WikiPageMutationResponse)
def wiki_page_update(
    slug: str,
    request: WikiPageUpdateRequest,
    user_id: str | None = Query(default=None),
) -> WikiPageMutationResponse:
    """Update an existing wiki page (G2 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    try:
        existing_page = service.get_page(slug)
        if existing_page is None:
            raise ValueError(f"Page not found: {slug}")
        _ensure_can_write_extra(existing_page.extra, current_user)
        merged_extra = None
        if request.extra is not None:
            current_permissions = get_permissions(existing_page.extra, default_owner=DEFAULT_WIKI_OWNER)
            merged_extra = dict(existing_page.extra)
            merged_extra.update({key: value for key, value in request.extra.items() if key != PERMISSIONS_KEY})
            merged_extra = set_permissions(merged_extra, current_permissions)
        page = service.update_page(
            slug=slug,
            title=request.title,
            body=request.body,
            status=request.status,
            evidence_refs=request.evidence_refs,
            source_hashes=request.source_hashes,
            extra=merged_extra,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return WikiPageMutationResponse(
        success=True,
        slug=page.stable_slug,
        message=f"Page updated: {page.stable_slug}",
    )


@router.delete("/pages/{slug}", response_model=WikiPageMutationResponse)
def wiki_page_delete(slug: str, user_id: str | None = Query(default=None)) -> WikiPageMutationResponse:
    """Delete a wiki page (G2 2026-05-26)."""
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from wiki.service import get_wiki_service

    current_user = _current_wiki_user(user_id)
    service = get_wiki_service()
    try:
        existing_page = service.get_page(slug)
        if existing_page is None:
            raise ValueError(f"Page not found: {slug}")
        _ensure_can_write_extra(existing_page.extra, current_user)
        service.delete_page(slug)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return WikiPageMutationResponse(
        success=True,
        slug=slug,
        message=f"Page deleted: {slug}",
    )


@router.get("/doctor", response_model=WikiDoctorResponse)
def wiki_doctor(user_id: str | None = Query(default=None)) -> WikiDoctorResponse:
    if not wiki_enabled():
        return WikiDoctorResponse(enabled=False, report={"warnings": _disabled_warning()})
    current_user = _current_wiki_user(user_id)
    return WikiDoctorResponse(enabled=True, report=_doctor(_authorized_page_store(current_user)).run().to_dict())


@router.post("/export", response_model=WikiExportResponse)
def wiki_export(
    output_path: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
) -> WikiExportResponse:
    """Export all wiki pages as Markdown zip archive (G15 2026-05-26).

    Args:
        output_path: Optional output zip filename under workspace_artifacts/wiki_exports.

    Returns:
        WikiExportResponse with success/page_count/output_path/errors
    """
    if not wiki_enabled():
        raise HTTPException(status_code=404, detail="Wiki integration is disabled")

    from wiki.export import export_wiki_markdown

    current_user = _current_wiki_user(user_id)
    resolved_output_path = _resolve_wiki_export_path(output_path)

    result = export_wiki_markdown(_authorized_page_store(current_user), resolved_output_path)

    if not result["success"]:
        raise HTTPException(status_code=500, detail={"errors": result["errors"]})

    return WikiExportResponse(**result)


@router.get("/graph", response_model=WikiGraphResponse)
def wiki_graph(user_id: str | None = Query(default=None)) -> WikiGraphResponse:
    if not wiki_enabled():
        return WikiGraphResponse(enabled=False, graph={})
    current_user = _current_wiki_user(user_id)
    snapshot = build_wiki_graph(_authorized_page_store(current_user))
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
