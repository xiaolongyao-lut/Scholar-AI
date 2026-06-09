# -*- coding: utf-8 -*-
"""Export / stats / maintenance / batch-delete endpoints split out of resources_router.__init__.

All references to module-level helpers go through _rr.X so that pytest
monkeypatch.setattr(rr, X, ...) keeps affecting the live endpoint behaviour.
"""

from typing import Any

from fastapi import HTTPException, Query
from pydantic import Field

from models import ProjectExportPayload

import routers.resources_router as _rr
from csl_style_store import csl_style_store


@_rr.router.get(
    "/project/{project_id}/export",
    tags=["Export"],
    response_model=ProjectExportPayload,
)
async def export_project(
    project_id: str,
    format: _rr.ProjectExportFormat = Query(_rr.ProjectExportFormat.MARKDOWN, description="导出格式"),
) -> dict[str, Any]:
    """Export a complete project with its sections, drafts, and materials."""
    store = _rr.get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    sections = store.list_sections(project_id)
    drafts = store.list_drafts(project_id)
    materials = store.list_materials(project_id)
    figure_assets = store.list_figure_assets(project_id) if hasattr(store, "list_figure_assets") else []
    doc_store = _rr._load_doc_store(project_id)
    chunk_store = _rr._load_chunk_store(project_id)
    academic_export = _rr._build_project_academic_export(
        sections,
        drafts,
        materials,
        project_id=project_id,
        chunk_store=chunk_store,
        figure_assets=figure_assets,
    )

    if format == _rr.ProjectExportFormat.JSON:
        return {
            "project_id": project_id,
            "format": "json",
            "filename": f"{_rr._safe_export_filename_stem(project.title)}.json",
            "project": project.to_dict(),
            "sections": [s.to_dict() for s in sections],
            "drafts": [d.to_dict() for d in drafts],
            "materials": [m.to_dict() for m in materials],
            "document_count": len(doc_store),
            **academic_export,
        }

    content = _rr._build_project_markdown_export(
        project,
        sections,
        drafts,
        materials,
        academic_export,
    )
    stem = _rr._safe_export_filename_stem(project.title)
    if format == _rr.ProjectExportFormat.LATEX:
        output_dir = _rr.output_path("writing_exports", project_id)
        path = _rr._unique_export_file(output_dir, stem, ".tex")
        try:
            style_xml = str(csl_style_store.get_active().get("csl_xml") or "")
        except Exception:
            style_xml = ""
        latex_content: str | None = None
        if style_xml:
            try:
                _rr._build_project_csl_latex_export(project, sections, drafts, materials, style_xml, path)
                latex_content = path.read_text(encoding="utf-8")
            except Exception as exc:
                # Fall back to the deterministic LaTeX builder when pandoc/CSL fails.
                _rr.logger.warning("CSL latex export via pandoc failed; falling back to builtin latex: %s", exc)
        if latex_content is None:
            latex_content = _rr._build_project_latex_export(
                project,
                sections,
                drafts,
                materials,
                academic_export,
            )
        return {
            "project_id": project_id,
            "format": "latex",
            "filename": f"{stem}.tex",
            "content": latex_content,
            **academic_export,
        }
    if format == _rr.ProjectExportFormat.WORD:
        output_dir = _rr.output_path("writing_exports", project_id)
        filename = f"{stem}.docx"
        path = _rr._unique_export_file(output_dir, stem, ".docx")
        try:
            style_xml = str(csl_style_store.get_active().get("csl_xml") or "")
        except Exception:
            style_xml = ""
        used_csl = False
        if style_xml:
            try:
                _rr._build_project_csl_docx_export(project, sections, drafts, materials, style_xml, path)
                used_csl = True
            except Exception as exc:
                # Graceful fallback to the deterministic python-docx builder when
                # pandoc is unavailable or the CSL conversion fails.
                _rr.logger.warning("CSL docx export via pandoc failed; falling back to python-docx: %s", exc)
        if not used_csl:
            _rr._build_project_docx_export(project, sections, drafts, materials, academic_export, path)
        return _rr._build_file_export_payload(
            project_id=project_id,
            format_name="word",
            filename=filename,
            file_path=path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            **academic_export,
        )
    if format == _rr.ProjectExportFormat.PDF:
        output_dir = _rr.output_path("writing_exports", project_id)
        filename = f"{stem}.pdf"
        path = _rr._unique_export_file(output_dir, stem, ".pdf")
        try:
            style_xml = str(csl_style_store.get_active().get("csl_xml") or "")
        except Exception:
            style_xml = ""
        used_csl = False
        if style_xml:
            try:
                _rr._build_project_csl_pdf_export(project, sections, drafts, materials, style_xml, path)
                used_csl = True
            except Exception as exc:
                # CSL PDF needs a (CJK-capable) PDF engine; fall back to the
                # PyMuPDF text PDF when pandoc/the engine is unavailable.
                _rr.logger.warning("CSL pdf export via pandoc failed; falling back to PyMuPDF: %s", exc)
        if not used_csl:
            _rr._build_project_pdf_export(content, path, str(project.title))
        return _rr._build_file_export_payload(
            project_id=project_id,
            format_name="pdf",
            filename=filename,
            file_path=path,
            media_type="application/pdf",
            content=content,
            **academic_export,
        )
    return {
        "project_id": project_id,
        "format": "markdown",
        "filename": f"{stem}.md",
        "content": content,
        **academic_export,
    }


# =========================================================================
# Statistics Endpoints (learned from open-webui analytics & openhanako diary)
# =========================================================================


@_rr.router.get("/stats/overview", tags=["Statistics"])
async def get_global_stats() -> dict[str, Any]:
    """Get global statistics across all projects."""
    store = _rr.get_writing_resource_store()
    projects = store.list_projects()
    total_drafts = 0
    total_materials = 0
    total_chars = 0
    status_counts: dict[str, int] = {}

    for p in projects:
        drafts = store.list_drafts(p.project_id)
        materials = store.list_materials(p.project_id)
        total_drafts += len(drafts)
        total_materials += len(materials)
        total_chars += sum(len(d.content) for d in drafts if hasattr(d, "content") and d.content)
        status = p.status if isinstance(p.status, str) else p.status.value
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "project_count": len(projects),
        "draft_count": total_drafts,
        "material_count": total_materials,
        "total_characters": total_chars,
        "projects_by_status": status_counts,
    }


# =========================================================================
# Batch Operations (learned from openhanako / open-webui bulk endpoints)
# =========================================================================

class BatchDeleteRequest(__import__("pydantic").BaseModel):
    material_ids: list[str] = __import__("pydantic").Field(..., min_length=1, max_length=50, description="要删除的素材 ID 列表")


class CleanupRequest(__import__("pydantic").BaseModel):
    dry_run: bool = True
    include_test_fixture_projects: bool = False
    remove_orphan_project_dirs: bool = False
    keep_project_ids: list[str] = Field(default_factory=list)


@_rr.router.post("/maintenance/cleanup", tags=["Resources"])
async def cleanup_historical_dirty_data(request: CleanupRequest) -> dict[str, Any]:
    """Preview or execute cleanup for duplicate projects and non-extractable materials."""
    store = _rr.get_writing_resource_store()
    duplicate_projects, empty_materials = _rr._analyze_cleanup_candidates(store)
    keep_project_ids = {str(project_id).strip() for project_id in request.keep_project_ids if str(project_id).strip()}
    known_project_ids = {project.project_id for project in store.list_projects()}

    test_fixture_projects: list[dict[str, Any]] = []
    if request.include_test_fixture_projects:
        duplicate_project_ids = {str(item.get("project_id") or "") for item in duplicate_projects}
        for project in store.list_projects():
            if project.project_id in keep_project_ids:
                continue
            if project.project_id in duplicate_project_ids:
                continue
            if _rr._is_test_fixture_project_title(getattr(project, "title", "")):
                test_fixture_projects.append(
                    {
                        "project_id": project.project_id,
                        "title": getattr(project, "title", ""),
                        "reason": "test_fixture_project_title",
                    }
                )

    orphan_project_dirs: list[dict[str, str]] = []
    if request.remove_orphan_project_dirs:
        projects_root = _rr._PROJECTS_DATA_ROOT
        try:
            if projects_root.exists():
                for child in projects_root.iterdir():
                    if not child.is_dir():
                        continue
                    if child.name in known_project_ids or child.name in keep_project_ids:
                        continue
                    orphan_project_dirs.append(
                        {
                            "project_id": child.name,
                            "path": str(child),
                            "reason": "no_project_record",
                        }
                    )
        except OSError as exc:
            _rr.logger.warning("Failed to scan orphan project dirs: %s", exc)

    preview = {
        "duplicate_project_count": len(duplicate_projects),
        "empty_material_count": len(empty_materials),
        "test_fixture_project_count": len(test_fixture_projects),
        "orphan_project_dir_count": len(orphan_project_dirs),
        "duplicate_projects": duplicate_projects,
        "empty_materials": empty_materials,
        "test_fixture_projects": test_fixture_projects,
        "orphan_project_dirs": orphan_project_dirs,
    }

    if request.dry_run:
        return {
            "dry_run": True,
            "preview": preview,
            "deleted": {
                "duplicate_project_count": 0,
                "empty_material_count": 0,
                "test_fixture_project_count": 0,
                "orphan_project_dir_count": 0,
                "duplicate_projects": [],
                "empty_materials": [],
                "test_fixture_projects": [],
                "orphan_project_dirs": [],
            },
        }

    deleted_duplicate_projects: list[str] = []
    deleted_empty_materials: list[str] = []
    deleted_test_fixture_projects: list[str] = []
    deleted_orphan_project_dirs: list[str] = []

    for item in duplicate_projects:
        project_id = str(item.get("project_id") or "")
        if not project_id or project_id in keep_project_ids:
            continue
        if store.delete_project(project_id):
            deleted_duplicate_projects.append(project_id)
            try:
                _rr._remove_project_workspace_dir(project_id)
            except OSError as exc:
                _rr.logger.warning("Failed to remove project workspace dir during cleanup: project=%s err=%s", project_id, exc)

    for item in test_fixture_projects:
        project_id = str(item.get("project_id") or "")
        if not project_id or project_id in keep_project_ids:
            continue
        if store.delete_project(project_id):
            deleted_test_fixture_projects.append(project_id)
            try:
                _rr._remove_project_workspace_dir(project_id)
            except OSError as exc:
                _rr.logger.warning("Failed to remove test project workspace dir during cleanup: project=%s err=%s", project_id, exc)

    if request.remove_orphan_project_dirs:
        for item in orphan_project_dirs:
            project_id = str(item.get("project_id") or "")
            if not project_id or project_id in keep_project_ids:
                continue
            try:
                if _rr._remove_project_workspace_dir(project_id):
                    deleted_orphan_project_dirs.append(project_id)
            except OSError as exc:
                _rr.logger.warning("Failed to remove orphan project dir during cleanup: project=%s err=%s", project_id, exc)

    for item in empty_materials:
        project_id = str(item.get("project_id") or "")
        material_id = str(item.get("material_id") or "")
        if not material_id or not project_id or project_id in keep_project_ids:
            continue
        if store.delete_material(material_id):
            deleted_empty_materials.append(material_id)
            doc_store = _rr._load_doc_store(project_id)
            if material_id in doc_store:
                del doc_store[material_id]
                _rr._save_doc_store(project_id, doc_store)
            chunk_store = _rr._load_chunk_store(project_id)
            if material_id in chunk_store:
                del chunk_store[material_id]
                _rr._save_chunk_store(project_id, chunk_store)

    return {
        "dry_run": False,
        "preview": preview,
        "deleted": {
            "duplicate_project_count": len(deleted_duplicate_projects),
            "empty_material_count": len(deleted_empty_materials),
            "test_fixture_project_count": len(deleted_test_fixture_projects),
            "orphan_project_dir_count": len(deleted_orphan_project_dirs),
            "duplicate_projects": deleted_duplicate_projects,
            "empty_materials": deleted_empty_materials,
            "test_fixture_projects": deleted_test_fixture_projects,
            "orphan_project_dirs": deleted_orphan_project_dirs,
        },
    }


@_rr.router.post("/materials/batch-delete", tags=["Resources"])
async def batch_delete_materials(request: BatchDeleteRequest) -> dict[str, Any]:
    """Batch delete materials from a project."""
    store = _rr.get_writing_resource_store()
    deleted = []
    not_found = []
    for mid in request.material_ids:
        material = store.get_material(mid)
        if material:
            project_id = material.project_id
            store.delete_material(mid)

            doc_store = _rr._load_doc_store(project_id)
            if mid in doc_store:
                del doc_store[mid]
                _rr._save_doc_store(project_id, doc_store)

            chunk_store = _rr._load_chunk_store(project_id)
            if mid in chunk_store:
                del chunk_store[mid]
                _rr._save_chunk_store(project_id, chunk_store)

            deleted.append(mid)
        else:
            not_found.append(mid)
    return {
        "deleted": deleted,
        "not_found": not_found,
        "deleted_count": len(deleted),
    }
