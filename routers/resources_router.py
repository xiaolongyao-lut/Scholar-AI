# -*- coding: utf-8 -*-
"""Resources API Router - Manages projects, sections, drafts, and associations."""

import asyncio
import logging
import os
from typing import Any, Mapping
from fastapi import APIRouter, HTTPException, Query
from models import (
    ProjectPayload,
    SectionPayload,
    DraftPayload,
    RevisionPayload,
    WritingAssociationPayload,
    CreateProjectRequest,
    CreateSectionRequest,
    CreateDraftRequest,
    SaveDraftRequest,
    BuildAssociationRequest,
)

logger = logging.getLogger("ResourcesRouter")
router = APIRouter(prefix="/resources", tags=["Resources"])
_ai_adapter_instance: Any | None = None


def get_writing_resource_store():
    """Import and return the writing resource store."""
    from writing_resources import get_writing_resource_store as get_store
    return get_store()


def get_memory_adapter():
    """Import and return the shared memory adapter when available."""
    from python_adapter_server import get_memory_adapter as get_adapter
    return get_adapter()


def get_ai_adapter() -> Any:
    """Import and return the shared AI adapter used by association AI mode."""
    global _ai_adapter_instance
    if _ai_adapter_instance is not None:
        return _ai_adapter_instance

    try:
        from layers.ai_adapter import AIAdapter

        _ai_adapter_instance = AIAdapter(
            api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("ARK_API_KEY") or os.environ.get("SILICONFLOW_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL") or os.environ.get("ARK_BASE_URL"),
            model=os.environ.get("OPENAI_MODEL") or os.environ.get("ARK_MODEL"),
        )
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("AI association adapter unavailable: %s", exc)
        _ai_adapter_instance = None
    return _ai_adapter_instance


def _memory_hit_to_dict(raw_hit: Any) -> dict[str, Any] | None:
    """Normalize a memory hit object into a plain mapping for the store layer."""
    if hasattr(raw_hit, "to_dict"):
        normalized = raw_hit.to_dict()
        return normalized if isinstance(normalized, dict) else None
    if isinstance(raw_hit, Mapping):
        return dict(raw_hit)
    return None


def _association_error_to_http_status(message: str) -> int:
    """Map association-layer validation failures to stable HTTP status codes."""
    lowered = message.lower()
    if "not found" in lowered:
        return 404
    return 400


def _clone_association_bundle(
    base_bundle: Any,
    *,
    mode: str,
    ai_enhanced: bool,
    association_angles: Any | None = None,
    continuation_prompts: Any | None = None,
    evidence_gaps: Any | None = None,
    recommended_memory_queries: Any | None = None,
) -> Any:
    """Rebuild a bundle while preserving the stable evidence ranking."""
    from writing_resources import WritingAssociationBundle

    return WritingAssociationBundle(
        project_id=base_bundle.project_id,
        query=base_bundle.query,
        generated_at=base_bundle.generated_at,
        draft_id=base_bundle.draft_id,
        section_id=base_bundle.section_id,
        mode=mode,
        ai_enhanced=ai_enhanced,
        focus_terms=list(base_bundle.focus_terms),
        memory_used=base_bundle.memory_used,
        memory_hit_count=base_bundle.memory_hit_count,
        related_signals=list(base_bundle.related_signals),
        association_angles=list(association_angles if association_angles is not None else base_bundle.association_angles),
        continuation_prompts=list(
            continuation_prompts if continuation_prompts is not None else base_bundle.continuation_prompts
        ),
        evidence_gaps=list(evidence_gaps if evidence_gaps is not None else base_bundle.evidence_gaps),
        recommended_memory_queries=list(
            recommended_memory_queries
            if recommended_memory_queries is not None
            else base_bundle.recommended_memory_queries
        ),
    )


async def _apply_association_mode(base_bundle: Any, mode: str, angle_limit: int) -> Any:
    """Apply AI or No-AI post-processing without mutating the evidence base."""
    adapter = get_ai_adapter()
    from writing_resources import apply_association_mode

    return await asyncio.to_thread(
        apply_association_mode,
        base_bundle,
        mode,
        adapter,
        angle_limit,
    )


@router.post("/project", response_model=ProjectPayload)
async def create_project(request: CreateProjectRequest) -> ProjectPayload:
    """Create a new writing project."""
    from writing_resources import ContentType
    store = get_writing_resource_store()
    try:
        content_type = ContentType(request.content_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid content_type: {request.content_type}")

    project = store.create_project(
        title=request.title,
        description=request.description,
        content_type=content_type,
        user_id=request.user_id,
        tags=request.tags,
    )
    return ProjectPayload(**project.to_dict())


@router.get("/project/{project_id}", response_model=ProjectPayload)
async def get_project(project_id: str) -> ProjectPayload:
    """Get a project by ID."""
    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return ProjectPayload(**project.to_dict())


@router.get("/projects", response_model=list[ProjectPayload])
async def list_projects(user_id: str | None = Query(None)) -> list[ProjectPayload]:
    """List all projects, optionally filtered by user."""
    store = get_writing_resource_store()
    projects = store.list_projects(user_id=user_id)
    return [ProjectPayload(**p.to_dict()) for p in projects]


@router.put("/project/{project_id}/status")
async def update_project_status(
    project_id: str,
    status: str = Query(..., description="New status"),
) -> ProjectPayload:
    """Update project status."""
    from writing_resources import ProjectStatus
    store = get_writing_resource_store()
    try:
        project_status = ProjectStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    project = store.update_project_status(project_id, project_status)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return ProjectPayload(**project.to_dict())


@router.post("/section", response_model=SectionPayload)
async def create_section(request: CreateSectionRequest) -> SectionPayload:
    """Create a section within a project."""
    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    section = store.create_section(
        project_id=request.project_id,
        title=request.title,
        order=request.order,
        description=request.description,
    )
    return SectionPayload(**section.to_dict())


@router.get("/section/{section_id}", response_model=SectionPayload)
async def get_section(section_id: str) -> SectionPayload:
    """Get a section by ID."""
    store = get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"Section not found: {section_id}")
    return SectionPayload(**section.to_dict())


@router.get("/sections", response_model=list[SectionPayload])
async def list_sections(project_id: str = Query(...)) -> list[SectionPayload]:
    """List all sections in a project."""
    store = get_writing_resource_store()
    sections = store.list_sections(project_id)
    return [SectionPayload(**s.to_dict()) for s in sections]


@router.post("/draft", response_model=DraftPayload)
async def create_draft(request: CreateDraftRequest) -> DraftPayload:
    """Create a new draft."""
    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    if request.section_id:
        section = store.get_section(request.section_id)
        if not section:
            raise HTTPException(status_code=404, detail=f"Section not found: {request.section_id}")

    draft = store.create_draft(
        project_id=request.project_id,
        title=request.title,
        content=request.content,
        section_id=request.section_id,
        edited_by=request.edited_by,
    )
    return DraftPayload(**draft.to_dict())


@router.get("/draft/{draft_id}", response_model=DraftPayload)
async def get_draft(draft_id: str) -> DraftPayload:
    """Get a draft by ID."""
    store = get_writing_resource_store()
    draft = store.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")
    return DraftPayload(**draft.to_dict())


@router.get("/drafts", response_model=list[DraftPayload])
async def list_drafts(
    project_id: str = Query(...),
    section_id: str | None = Query(None),
) -> list[DraftPayload]:
    """List all drafts, optionally filtered by section."""
    store = get_writing_resource_store()
    drafts = store.list_drafts(project_id, section_id=section_id)
    return [DraftPayload(**d.to_dict()) for d in drafts]


@router.put("/draft/{draft_id}")
async def save_draft(draft_id: str, request: SaveDraftRequest) -> DraftPayload:
    """Save draft content."""
    store = get_writing_resource_store()
    draft = store.save_draft(
        draft_id,
        request.content,
        edited_by=request.edited_by,
        create_revision=True,
    )
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")
    return DraftPayload(**draft.to_dict())


@router.get("/revision/{revision_id}", response_model=RevisionPayload)
async def get_revision(revision_id: str) -> RevisionPayload:
    """Get a revision by ID."""
    store = get_writing_resource_store()
    revision = store.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail=f"Revision not found: {revision_id}")
    return RevisionPayload(**revision.to_dict())


@router.get("/revisions", response_model=list[RevisionPayload])
async def list_revisions(draft_id: str = Query(...)) -> list[RevisionPayload]:
    """List all revisions for a draft."""
    store = get_writing_resource_store()
    revisions = store.list_revisions(draft_id)
    return [RevisionPayload(**r.to_dict()) for r in revisions]


@router.post("/draft/{draft_id}/restore")
async def restore_revision(
    draft_id: str,
    revision_id: str = Query(...),
) -> DraftPayload:
    """Restore a draft from a revision."""
    store = get_writing_resource_store()
    draft = store.restore_revision(draft_id, revision_id)
    if not draft:
        raise HTTPException(
            status_code=404,
            detail=f"Draft {draft_id} or revision {revision_id} not found",
        )
    return DraftPayload(**draft.to_dict())


@router.post("/association", response_model=WritingAssociationPayload)
async def build_writing_association(
    request: BuildAssociationRequest,
) -> WritingAssociationPayload:
    """Build associative writing guidance from project state, retrieval evidence, and mode."""
    store = get_writing_resource_store()
    memory_hits: list[dict[str, Any]] = []

    if request.use_memory:
        adapter = get_memory_adapter()
        if adapter is not None:
            memory_query = request.memory_query.strip() if request.memory_query else request.query
            try:
                memory_response = adapter.search(
                    query=memory_query,
                    wing=request.wing,
                    room=request.room,
                    limit=request.memory_limit,
                )
            except Exception as exc:  # pragma: no cover - optional dependency path
                logger.warning("Memory association lookup failed: %s", exc)
                memory_response = None

            if memory_response is not None and getattr(memory_response, "available", False):
                raw_results = getattr(memory_response, "results", [])
                for raw_hit in raw_results:
                    normalized_hit = _memory_hit_to_dict(raw_hit)
                    if normalized_hit is not None:
                        memory_hits.append(normalized_hit)

    try:
        bundle = store.build_association_bundle(
            project_id=request.project_id,
            query=request.query,
            draft_id=request.draft_id,
            section_id=request.section_id,
            memory_hits=memory_hits,
            retrieval_hits=request.retrieval_hits,
            signal_limit=request.signal_limit,
            angle_limit=request.angle_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_association_error_to_http_status(str(exc)),
            detail=str(exc),
        ) from exc

    bundle = await _apply_association_mode(bundle, request.mode, request.angle_limit)
    return WritingAssociationPayload(**bundle.to_dict())
