# -*- coding: utf-8 -*-
"""Merged-project resource endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

import routers.resources_router as _rr


class CreateMergedProjectRequest(BaseModel):
    """Request body for creating a merged literature project."""

    title: str = Field(min_length=1)
    description: str = ""
    source_projects: list[str] = Field(min_length=1)
    auto_cross_analysis: bool = False


class UpdateMergedProjectSourcesRequest(BaseModel):
    """Request body for replacing merged-project sources."""

    source_projects: list[str] = Field(min_length=1)


class MultiProjectSearchRequest(BaseModel):
    """Request body for searching standard and merged projects together."""

    project_ids: list[str] = Field(min_length=1)
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)


def _normalize_project_ids(values: Sequence[str], *, field_name: str) -> list[str]:
    """Normalize project id lists while preserving caller order."""

    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"{field_name} entries must be strings")
        project_id = value.strip()
        if not project_id:
            raise HTTPException(status_code=400, detail=f"{field_name} entries must be non-empty")
        if project_id in seen:
            continue
        normalized.append(project_id)
        seen.add(project_id)
    if not normalized:
        raise HTTPException(status_code=400, detail=f"{field_name} must contain at least one project id")
    return normalized


def _get_project_or_404(store: Any, project_id: str) -> Any:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


def _project_metadata(project: Any) -> dict[str, Any]:
    metadata = getattr(project, "metadata", None)
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=500, detail="Project metadata must be an object")
    return dict(metadata)


def _project_type(project: Any) -> str:
    return str(_project_metadata(project).get("project_type") or "standard")


def _source_projects(project: Any) -> list[str]:
    metadata = _project_metadata(project)
    raw_sources = metadata.get("source_projects")
    if raw_sources is None:
        return []
    if not isinstance(raw_sources, list):
        raise HTTPException(status_code=500, detail="Merged project source_projects must be a list")
    return _normalize_project_ids(raw_sources, field_name="source_projects")


def _ensure_sources_exist(store: Any, source_project_ids: list[str]) -> None:
    for source_project_id in source_project_ids:
        _get_project_or_404(store, source_project_id)


def _expand_project_ids(
    store: Any,
    project_ids: list[str],
    *,
    visiting: set[str] | None = None,
) -> list[str]:
    """Expand merged project ids into leaf source projects."""

    active = set(visiting or set())
    expanded: list[str] = []
    seen: set[str] = set()
    for project_id in project_ids:
        if project_id in active:
            raise HTTPException(status_code=400, detail=f"Merged project cycle detected at {project_id}")
        project = _get_project_or_404(store, project_id)
        if _project_type(project) == "merged":
            active.add(project_id)
            child_ids = _expand_project_ids(store, _source_projects(project), visiting=active)
            active.remove(project_id)
        else:
            child_ids = [project_id]
        for child_id in child_ids:
            if child_id in seen:
                continue
            expanded.append(child_id)
            seen.add(child_id)
    return expanded


def _merged_project_payload(project: Any) -> dict[str, Any]:
    """Return a public payload for merged-project endpoints."""

    data = project.to_dict()
    metadata = _project_metadata(project)
    source_projects = _normalize_project_ids(
        metadata.get("source_projects") if isinstance(metadata.get("source_projects"), list) else [],
        field_name="source_projects",
    )
    data["project_type"] = str(metadata.get("project_type") or "merged")
    data["source_projects"] = source_projects
    data["auto_cross_analysis"] = bool(metadata.get("auto_cross_analysis") or False)
    return data


def _sources_payload(store: Any, project_id: str) -> dict[str, Any]:
    project = _get_project_or_404(store, project_id)
    source_projects = _source_projects(project) if _project_type(project) == "merged" else [project_id]
    expanded_source_projects = _expand_project_ids(store, source_projects)
    return {
        "project_id": project_id,
        "project_type": _project_type(project),
        "source_projects": source_projects,
        "expanded_source_projects": expanded_source_projects,
    }


@_rr.router.post("/projects/merged")
async def create_merged_project(request: CreateMergedProjectRequest) -> dict[str, Any]:
    """Create a project that references existing literature projects."""

    store = _rr.get_writing_resource_store()
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title must be non-empty")
    source_projects = _normalize_project_ids(request.source_projects, field_name="source_projects")
    _ensure_sources_exist(store, source_projects)
    project = store.create_project(
        title=title,
        description=request.description,
        metadata={
            "project_type": "merged",
            "source_projects": source_projects,
            "auto_cross_analysis": bool(request.auto_cross_analysis),
        },
    )
    return _merged_project_payload(project)


@_rr.router.get("/projects/{project_id}/sources")
async def get_project_sources(project_id: str) -> dict[str, Any]:
    """Return direct and expanded source projects for one project."""

    if not project_id.strip():
        raise HTTPException(status_code=400, detail="project_id must be non-empty")
    store = _rr.get_writing_resource_store()
    return _sources_payload(store, project_id.strip())


@_rr.router.put("/projects/{project_id}/sources")
async def update_project_sources(
    project_id: str,
    request: UpdateMergedProjectSourcesRequest,
) -> dict[str, Any]:
    """Replace the direct source projects for a merged project."""

    normalized_project_id = project_id.strip()
    if not normalized_project_id:
        raise HTTPException(status_code=400, detail="project_id must be non-empty")
    source_projects = _normalize_project_ids(request.source_projects, field_name="source_projects")
    if normalized_project_id in source_projects:
        raise HTTPException(status_code=400, detail="Merged project cannot include itself")

    store = _rr.get_writing_resource_store()
    project = _get_project_or_404(store, normalized_project_id)
    _ensure_sources_exist(store, source_projects)
    metadata = _project_metadata(project)
    metadata["project_type"] = "merged"
    metadata["source_projects"] = source_projects
    updated = store.update_project(normalized_project_id, metadata=metadata)
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to update merged project sources")
    return _sources_payload(store, normalized_project_id)


@_rr.router.post("/search/multi")
async def search_multi_projects(request: MultiProjectSearchRequest) -> dict[str, Any]:
    """Search across standard projects and merged-project sources."""

    requested_project_ids = _normalize_project_ids(request.project_ids, field_name="project_ids")
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must be non-empty")

    store = _rr.get_writing_resource_store()
    expanded_project_ids = _expand_project_ids(store, requested_project_ids)

    scored_chunks: list[tuple[float, dict[str, Any]]] = []
    sources: list[dict[str, Any]] = []
    for source_project_id in expanded_project_ids:
        project = _get_project_or_404(store, source_project_id)
        sources.append(
            {
                "project_id": source_project_id,
                "title": str(getattr(project, "title", "") or source_project_id),
                "project_type": _project_type(project),
            }
        )
        chunk_store = _rr._load_chunk_store(source_project_id)
        chunks: list[dict[str, Any]] = []
        for material_chunks in chunk_store.values():
            chunks.extend(dict(chunk) for chunk in material_chunks if isinstance(chunk, dict))
        for score, chunk in _rr._score_chunks_for_query(chunks, query):
            enriched = dict(chunk)
            enriched["source_project_id"] = source_project_id
            scored_chunks.append((score, enriched))

    top = _rr._select_diverse_top_chunks(scored_chunks, request.top_k)
    return {
        "requested_project_ids": requested_project_ids,
        "expanded_project_ids": expanded_project_ids,
        "query": query,
        "top_k": request.top_k,
        "results": [{"score": round(score, 2), **chunk} for score, chunk in top if score > 0],
        "sources": sources,
    }
