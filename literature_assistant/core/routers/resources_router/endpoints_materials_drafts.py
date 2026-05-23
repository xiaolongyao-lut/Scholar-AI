# -*- coding: utf-8 -*-
"""Material / draft / revision / association endpoints split out of resources_router.__init__.

All references to module-level helpers go through ``_rr.X`` (absolute import
of the package) so that pytest ``monkeypatch.setattr(rr, "X", ...)`` keeps
affecting the live endpoint behaviour.
"""

from typing import Any

from fastapi import HTTPException, Query

from models import (
    MaterialPayload,
    DraftPayload,
    RevisionPayload,
    WritingAssociationPayload,
    CreateMaterialRequest,
    CreateDraftRequest,
    SaveDraftRequest,
    BuildAssociationRequest,
)

import routers.resources_router as _rr


# =========================================================================
# Material CRUD
# =========================================================================

@_rr.router.post("/material", response_model=MaterialPayload)
async def create_material(request: CreateMaterialRequest) -> MaterialPayload:
    """Create a project-scoped reference material."""
    store = _rr.get_writing_resource_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {request.project_id}")

    material = store.create_material(
        project_id=request.project_id,
        title=request.title,
        title_en=request.title_en,
        summary=request.summary,
        summary_en=request.summary_en,
        material_type=request.type,
        focus_points=request.focus_points,
        focus_points_en=request.focus_points_en,
    )
    return MaterialPayload(**material.to_dict())


@_rr.router.get("/material/{material_id}", response_model=MaterialPayload)
async def get_material(material_id: str) -> MaterialPayload:
    """Get a project-scoped material by ID."""
    store = _rr.get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail=f"Material not found: {material_id}")
    return MaterialPayload(**material.to_dict())


@_rr.router.get("/materials", response_model=list[MaterialPayload])
async def list_materials(project_id: str = Query(...)) -> list[MaterialPayload]:
    """List all materials attached to a project."""
    store = _rr.get_writing_resource_store()
    materials = store.list_materials(project_id)
    return [MaterialPayload(**material.to_dict()) for material in materials]


@_rr.router.get("/material/{material_id}/chunks")
async def get_material_chunks(
    material_id: str,
    project_id: str = Query(...),
) -> dict[str, Any]:
    """Get chunks for a specific material."""
    chunk_store = _rr._ensure_project_chunks(project_id, material_id=material_id)
    chunks = chunk_store.get(material_id, [])
    return {
        "material_id": material_id,
        "total_chunks": len(chunks),
        "chunks": chunks,
    }


@_rr.router.delete("/material/{material_id}", tags=["Resources"])
async def delete_material(material_id: str) -> dict[str, str]:
    """Delete a single material by ID."""
    store = _rr.get_writing_resource_store()
    material = store.get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail=f"素材不存在: {material_id}")

    project_id = material.project_id

    # 0.1.8.1 hotfix: also remove the persisted original file (when present)
    # so the user's "delete this paper" intent actually cleans disk, not just
    # the index entries. Best-effort — never blocks deletion.
    doc_store_before = _rr._load_doc_store(project_id)
    source_relative = (doc_store_before.get(material_id) or {}).get("source_relative_path", "")
    if source_relative:
        try:
            from project_paths import project_data_path
            from pathlib import Path
            candidate = project_data_path(project_id, "source_files", source_relative)
            if candidate.exists() and candidate.is_file():
                candidate.unlink()
        except OSError as exc:
            _rr.logger.warning(
                "delete_material: source_file_unlink_failed material_id=%s err=%s",
                material_id, exc,
            )

    store.delete_material(material_id)

    doc_store = _rr._load_doc_store(project_id)
    if material_id in doc_store:
        del doc_store[material_id]
        _rr._save_doc_store(project_id, doc_store)

    chunk_store = _rr._load_chunk_store(project_id)
    if material_id in chunk_store:
        del chunk_store[material_id]
        _rr._save_chunk_store(project_id, chunk_store)

    return {"status": "deleted", "material_id": material_id}


# =========================================================================
# Draft CRUD + Revisions
# =========================================================================

@_rr.router.post("/draft", response_model=DraftPayload)
async def create_draft(request: CreateDraftRequest) -> DraftPayload:
    """Create a new draft."""
    store = _rr.get_writing_resource_store()
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
        citation_anchors=[anchor.model_dump() for anchor in request.citation_anchors],
    )
    return DraftPayload(**draft.to_dict())


@_rr.router.get("/draft/{draft_id}", response_model=DraftPayload)
async def get_draft(draft_id: str) -> DraftPayload:
    """Get a draft by ID."""
    store = _rr.get_writing_resource_store()
    draft = store.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")
    return DraftPayload(**draft.to_dict())


@_rr.router.get("/drafts", response_model=list[DraftPayload])
async def list_drafts(
    project_id: str = Query(...),
    section_id: str | None = Query(None),
) -> list[DraftPayload]:
    """List all drafts, optionally filtered by section."""
    store = _rr.get_writing_resource_store()
    drafts = store.list_drafts(project_id, section_id=section_id)
    return [DraftPayload(**d.to_dict()) for d in drafts]


@_rr.router.put("/draft/{draft_id}")
async def save_draft(draft_id: str, request: SaveDraftRequest) -> DraftPayload:
    """Save draft content."""
    store = _rr.get_writing_resource_store()
    draft = store.save_draft(
        draft_id,
        request.content,
        edited_by=request.edited_by,
        citation_anchors=[anchor.model_dump() for anchor in request.citation_anchors],
        create_revision=True,
    )
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")
    return DraftPayload(**draft.to_dict())


@_rr.router.get("/revision/{revision_id}", response_model=RevisionPayload)
async def get_revision(revision_id: str) -> RevisionPayload:
    """Get a revision by ID."""
    store = _rr.get_writing_resource_store()
    revision = store.get_revision(revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail=f"Revision not found: {revision_id}")
    return RevisionPayload(**revision.to_dict())


@_rr.router.get("/revisions", response_model=list[RevisionPayload])
async def list_revisions(draft_id: str = Query(...)) -> list[RevisionPayload]:
    """List all revisions for a draft."""
    store = _rr.get_writing_resource_store()
    revisions = store.list_revisions(draft_id)
    return [RevisionPayload(**r.to_dict()) for r in revisions]


@_rr.router.post("/draft/{draft_id}/restore")
async def restore_revision(
    draft_id: str,
    revision_id: str = Query(...),
) -> DraftPayload:
    """Restore a draft from a revision."""
    store = _rr.get_writing_resource_store()
    draft = store.restore_revision(draft_id, revision_id)
    if not draft:
        raise HTTPException(
            status_code=404,
            detail=f"Draft {draft_id} or revision {revision_id} not found",
        )
    return DraftPayload(**draft.to_dict())


@_rr.router.delete("/draft/{draft_id}", tags=["Resources"])
async def delete_draft(draft_id: str) -> dict[str, str]:
    """Delete a draft by ID."""
    store = _rr.get_writing_resource_store()
    draft = store.get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"草稿不存在: {draft_id}")
    store.delete_draft(draft_id)
    return {"status": "deleted", "draft_id": draft_id}


# =========================================================================
# Writing Association
# =========================================================================

@_rr.router.post("/association", response_model=WritingAssociationPayload)
async def build_writing_association(
    request: BuildAssociationRequest,
) -> WritingAssociationPayload:
    """Build associative writing guidance from project state, retrieval evidence, and mode."""
    store = _rr.get_writing_resource_store()
    memory_hits: list[dict[str, Any]] = []

    if request.use_memory:
        adapter = _rr.get_memory_adapter()
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
                _rr.logger.warning("Memory association lookup failed: %s", exc)
                memory_response = None

            if memory_response is not None and getattr(memory_response, "available", False):
                raw_results = getattr(memory_response, "results", [])
                for raw_hit in raw_results:
                    normalized_hit = _rr._memory_hit_to_dict(raw_hit)
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
            status_code=_rr._association_error_to_http_status(str(exc)),
            detail=str(exc),
        ) from exc

    bundle = await _rr._apply_association_mode(bundle, request.mode, request.angle_limit)
    return WritingAssociationPayload(**bundle.to_dict())
