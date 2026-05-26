"""Writing API router - /api/writing/* aliases and extensions.

Provides user-friendly /api/writing/* endpoints that alias or extend
the existing /resources/* endpoints for writing projects, outlines,
citations, figures, and submissions.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Any
from datetime import datetime, timezone

from models import (
    ProjectPayload,
    CreateProjectRequest,
    OutlineItemPayload,
    OutlinePayload,
    GenerateOutlineRequest,
    CitationSourcePayload,
    CitationSuggestionPayload,
    SuggestCitationsRequest,
    FigureAssetPayload,
    CreateFigureAssetRequest,
    FigureTableCandidatePayload,
    SubmitForReviewRequest,
    SubmissionResponsePayload,
    ExportProjectRequest,
    ProjectExportPayload,
)

# Import resources router to reuse logic
import routers.resources_router as resources_router

router = APIRouter(prefix="/api/writing", tags=["Writing"])


# =========================================================================
# Project aliases - H1
# =========================================================================

@router.get("/projects", response_model=list[ProjectPayload])
async def list_projects_alias(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
) -> list[ProjectPayload]:
    """List all writing projects (alias to /resources/projects)."""
    from routers.resources_router.endpoints_projects import list_projects
    return await list_projects(user_id=user_id, page=page, page_size=page_size)


@router.get("/projects/{project_id}", response_model=ProjectPayload)
async def get_project_alias(project_id: str) -> ProjectPayload:
    """Get a writing project by ID (alias to /resources/project/{id})."""
    from routers.resources_router.endpoints_projects import get_project
    return await get_project(project_id)


@router.post("/projects", response_model=ProjectPayload)
async def create_project_alias(request: CreateProjectRequest) -> ProjectPayload:
    """Create a new writing project (alias to /resources/project)."""
    from routers.resources_router.endpoints_projects import create_project
    return await create_project(request)


@router.put("/projects/{project_id}/status", response_model=ProjectPayload)
async def update_project_status_alias(
    project_id: str,
    status: str = Query(..., description="New status"),
) -> ProjectPayload:
    """Update project status (alias to /resources/project/{id}/status)."""
    from routers.resources_router.endpoints_projects import update_project_status
    return await update_project_status(project_id, status)


@router.delete("/projects/{project_id}")
async def delete_project_alias(project_id: str) -> dict[str, str]:
    """Delete a writing project (alias to /resources/project/{id})."""
    from routers.resources_router.endpoints_projects import delete_project
    return await delete_project(project_id)


# =========================================================================
# Outline CRUD - H2
# =========================================================================

@router.get("/outline", response_model=OutlinePayload)
async def get_outline(
    project_id: str = Query(..., description="Project ID"),
) -> OutlinePayload:
    """Get outline for a project.

    Returns hierarchical outline structure. Currently maps to sections.
    """
    from routers.resources_router.endpoints_projects import list_sections
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    sections = await list_sections(project_id=project_id)

    # Convert sections to outline items
    items = []
    for section in sections:
        items.append(OutlineItemPayload(
            item_id=section.section_id,
            project_id=section.project_id,
            parent_id=None,
            title=section.title,
            level=1,
            order=section.order,
            description=section.description,
            section_id=section.section_id,
            created_at=section.created_at,
            updated_at=section.updated_at,
        ))

    return OutlinePayload(
        project_id=project_id,
        items=items,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.put("/outline", response_model=OutlinePayload)
async def update_outline(
    project_id: str = Query(..., description="Project ID"),
    items: list[OutlineItemPayload] = [],
) -> OutlinePayload:
    """Update outline structure.

    Currently updates sections. Full hierarchical outline support pending.
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    # Update sections based on outline items
    for item in items:
        if item.section_id:
            store.update_section(
                item.section_id,
                title=item.title,
                order=item.order,
                description=item.description,
            )

    # Return updated outline
    return await get_outline(project_id=project_id)


@router.delete("/outline/{item_id}")
async def delete_outline_item(item_id: str) -> dict[str, str]:
    """Delete an outline item.

    Currently deletes the corresponding section.
    """
    from routers.resources_router.endpoints_projects import delete_section
    return await delete_section(item_id)


# =========================================================================
# Outline generation - H7
# =========================================================================

@router.post("/outline/generate", response_model=OutlinePayload)
async def generate_outline(request: GenerateOutlineRequest) -> OutlinePayload:
    """Generate outline via AI based on topic and materials.

    Uses project materials and focus areas to generate structured outline.
    """
    from routers.resources_router import get_writing_resource_store
    from layers.ai_adapter import get_ai_adapter

    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    # Build context from existing materials
    context_parts = [f"Topic: {request.topic}"]
    if request.focus_areas:
        context_parts.append(f"Focus areas: {', '.join(request.focus_areas)}")
    if request.target_length:
        context_parts.append(f"Target length: ~{request.target_length} words")

    # TODO: Fetch material summaries if existing_materials provided

    prompt = f"""Generate a structured outline for a {request.content_type} writing project.

{chr(10).join(context_parts)}

Generate a hierarchical outline with:
- 3-5 main sections (level 1)
- 2-4 subsections per main section (level 2)
- Brief description for each section

Format as JSON array of outline items with: title, level, order, description"""

    # Call AI adapter
    ai_adapter = get_ai_adapter()
    response = await ai_adapter.generate_text(
        prompt=prompt,
        max_tokens=2000,
        temperature=0.7,
    )

    # Parse AI response and create outline items
    # For now, return empty outline (full AI parsing implementation pending)
    items = []

    return OutlinePayload(
        project_id=request.project_id,
        items=items,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


# =========================================================================
# Citation source metadata - H3
# =========================================================================

@router.get("/citations/sources", response_model=list[CitationSourcePayload])
async def get_citation_sources(
    project_id: str = Query(..., description="Project ID"),
) -> list[CitationSourcePayload]:
    """Get citation source metadata for a project.

    Returns source metadata for materials cited in project drafts.
    This is NOT Word-style bibliography generation.
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    # Get all materials for the project
    materials = store.list_materials(project_id=project_id)

    # Convert materials to citation sources
    sources = []
    for material in materials:
        # Count citations in drafts (simplified - full implementation pending)
        citation_count = 0

        sources.append(CitationSourcePayload(
            source_id=material.material_id,
            material_id=material.material_id,
            project_id=material.project_id,
            title=material.title,
            authors=[],  # TODO: Extract from material metadata
            year=None,
            publication=None,
            doi=None,
            url=None,
            citation_count=citation_count,
            created_at=material.created_at,
            updated_at=material.updated_at,
        ))

    return sources


@router.put("/citations/sources/{source_id}", response_model=CitationSourcePayload)
async def update_citation_source(
    source_id: str,
    title: str = Query(None),
    authors: list[str] = Query(None),
    year: int = Query(None),
    publication: str = Query(None),
    doi: str = Query(None),
    url: str = Query(None),
) -> CitationSourcePayload:
    """Update citation source metadata.

    Updates bibliographic metadata for a source material.
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    material = store.get_material(source_id)
    if not material:
        raise HTTPException(status_code=404, detail=f"Source not found: {source_id}")

    # Update material metadata (simplified - full metadata storage pending)
    # For now, return current state
    return CitationSourcePayload(
        source_id=material.material_id,
        material_id=material.material_id,
        project_id=material.project_id,
        title=title or material.title,
        authors=authors or [],
        year=year,
        publication=publication,
        doi=doi,
        url=url,
        citation_count=0,
        created_at=material.created_at,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


# =========================================================================
# Citation AI suggestion - H8
# =========================================================================

@router.post("/citations/suggest", response_model=list[CitationSuggestionPayload])
async def suggest_citations(request: SuggestCitationsRequest) -> list[CitationSuggestionPayload]:
    """Suggest relevant citations for draft context via AI.

    Analyzes draft text and recommends materials to cite.
    """
    from routers.resources_router import get_writing_resource_store
    from main_rag_workflow import search_chunks

    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    draft = store.get_draft(request.draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {request.draft_id}")

    # Search for relevant chunks based on context
    try:
        search_results = search_chunks(
            query=request.context,
            project_id=request.project_id,
            top_k=request.max_suggestions,
        )
    except Exception:
        # Fallback if search fails
        search_results = []

    # Convert search results to citation suggestions
    suggestions = []
    for idx, result in enumerate(search_results[:request.max_suggestions]):
        suggestions.append(CitationSuggestionPayload(
            material_id=result.get("material_id", ""),
            title=result.get("material_title", "Unknown"),
            excerpt=result.get("text", "")[:200],
            relevance_score=result.get("score", 0.5),
            rationale=f"Relevant to: {request.context[:100]}...",
            suggested_position=None,
        ))

    return suggestions


# =========================================================================
# Figure/table assets - H4
# =========================================================================

@router.get("/figures", response_model=list[FigureAssetPayload])
async def list_figure_assets(
    project_id: str = Query(..., description="Project ID"),
) -> list[FigureAssetPayload]:
    """List real figure/table assets for a project.

    Returns actual extracted/uploaded figures with asset files.
    Distinct from text-derived candidates.
    """
    from routers.resources_router import get_writing_resource_store

    store = get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    # TODO: Implement figure asset storage
    # For now, return empty list (full implementation pending)
    return []


@router.post("/figures", response_model=FigureAssetPayload)
async def create_figure_asset(request: CreateFigureAssetRequest) -> FigureAssetPayload:
    """Create a figure/table asset.

    Registers an extracted or uploaded figure/table with asset file.
    """
    from routers.resources_router import get_writing_resource_store
    import uuid

    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    # TODO: Implement figure asset storage
    # For now, return mock asset
    asset_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    return FigureAssetPayload(
        asset_id=asset_id,
        project_id=request.project_id,
        kind=request.kind,
        caption=request.caption,
        numbering=request.numbering,
        material_id=request.material_id,
        source_page=request.source_page,
        bbox=request.bbox,
        asset_path=request.asset_path,
        width=request.width,
        height=request.height,
        format=request.format,
        created_at=now,
        updated_at=now,
    )


@router.put("/figures/{asset_id}", response_model=FigureAssetPayload)
async def update_figure_asset(
    asset_id: str,
    caption: str = Query(None),
    numbering: str = Query(None),
) -> FigureAssetPayload:
    """Update figure/table asset metadata."""
    # TODO: Implement figure asset storage
    raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")


@router.delete("/figures/{asset_id}")
async def delete_figure_asset(asset_id: str) -> dict[str, str]:
    """Delete a figure/table asset."""
    # TODO: Implement figure asset storage
    raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id}")


@router.get("/figures/candidates", response_model=list[FigureTableCandidatePayload])
async def list_figure_candidates_alias(
    project_id: str = Query(..., description="Project ID"),
) -> list[FigureTableCandidatePayload]:
    """List text-derived figure/table candidates (alias to /resources/figure-table-candidates).

    Returns candidates extracted from chunk text, not real assets.
    """
    from routers.resources_router.endpoints_search_upload import list_figure_table_candidates
    return await list_figure_table_candidates(project_id=project_id)


# =========================================================================
# Reviewer submission - H5
# =========================================================================

@router.post("/submit", response_model=SubmissionResponsePayload)
async def submit_for_review(request: SubmitForReviewRequest) -> SubmissionResponsePayload:
    """Submit project for review.

    Packages project content for reviewer access.
    """
    from routers.resources_router import get_writing_resource_store
    import uuid

    store = get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    # TODO: Implement submission packaging and notification
    # For now, return mock submission
    submission_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    return SubmissionResponsePayload(
        submission_id=submission_id,
        project_id=request.project_id,
        status="submitted",
        submitted_at=now,
        reviewer_email=request.reviewer_email,
        package_path=None,
    )


# =========================================================================
# Project export - H10
# =========================================================================

@router.post("/export", response_model=ProjectExportPayload)
async def export_project(request: ExportProjectRequest) -> ProjectExportPayload:
    """Export project in specified format.

    Supports JSON, Markdown, Word, LaTeX, PDF formats.
    Currently implements JSON and Markdown (Word/LaTeX/PDF pending).
    """
    if request.format in ("json", "markdown"):
        # Delegate to existing export endpoint
        from routers.resources_router.endpoints_export_stats import export_project_academic
        return await export_project_academic(
            project_id=request.project_id,
            format=request.format,
        )
    else:
        # Word/LaTeX/PDF export pending
        raise HTTPException(
            status_code=501,
            detail=f"Export format '{request.format}' not yet implemented. Supported: json, markdown",
        )
