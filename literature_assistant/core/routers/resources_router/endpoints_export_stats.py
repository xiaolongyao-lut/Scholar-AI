# -*- coding: utf-8 -*-
"""Export / stats / maintenance / batch-delete endpoints split out of resources_router.__init__.

All references to module-level helpers go through _rr.X so that pytest
monkeypatch.setattr(rr, X, ...) keeps affecting the live endpoint behaviour.
"""

from typing import Any

from fastapi import HTTPException, Query

from models import ProjectExportPayload

import routers.resources_router as _rr


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
    doc_store = _rr._load_doc_store(project_id)
    academic_export = _rr._build_project_academic_export(sections, drafts, materials)

    if format == _rr.ProjectExportFormat.JSON:
        return {
            "project_id": project_id,
            "format": "json",
            "project": project.to_dict(),
            "sections": [s.to_dict() for s in sections],
            "drafts": [d.to_dict() for d in drafts],
            "materials": [m.to_dict() for m in materials],
            "document_count": len(doc_store),
            **academic_export,
        }

    # Markdown export
    lines = [f"# {project.title}\n"]
    if project.description:
        lines.append(f"> {project.description}\n")
    lines.append(f"状态: {project.status} | 创建: {project.created_at}\n")

    # Sort sections by order
    sorted_sections = sorted(sections, key=lambda s: s.order)
    section_map = {s.section_id: s for s in sorted_sections}
    material_map = {m.material_id: m for m in materials}

    for section in sorted_sections:
        lines.append(f"\n## {section.title}\n")
        if section.description:
            lines.append(f"{section.description}\n")
        section_drafts = [d for d in drafts if getattr(d, "section_id", None) == section.section_id]
        for draft in section_drafts:
            lines.append(f"\n### {draft.title}\n")
            lines.append(f"{draft.content}\n")

    # Orphan drafts (no section)
    orphans = [d for d in drafts if not getattr(d, "section_id", None)]
    if orphans:
        lines.append("\n## 未分类草稿\n")
        for draft in orphans:
            lines.append(f"\n### {draft.title}\n")
            lines.append(f"{draft.content}\n")

    if academic_export["evidence_rows"]:
        lines.append("\n## 证据表\n")
        lines.append("| Evidence ID | Material | Status | Anchors | Excerpt |")
        lines.append("|---|---|---|---|---|")
        for row in academic_export["evidence_rows"]:
            anchors = ", ".join(row["anchor_ids"])
            material_title = row["provenance"]["material_title"]
            lines.append(
                "| "
                + " | ".join(
                    [
                        _rr._markdown_table_cell(row["evidence_id"]),
                        _rr._markdown_table_cell(material_title),
                        _rr._markdown_table_cell(row["status"]),
                        _rr._markdown_table_cell(anchors),
                        _rr._markdown_table_cell(row["excerpt"]),
                    ]
                )
                + " |"
            )

    if academic_export["citation_chain"]:
        lines.append("\n## 引用链\n")
        lines.append("| Anchor | Section | Paragraph | Material | Claim | Source |")
        lines.append("|---|---|---|---|---|---|")
        for row in academic_export["citation_chain"]:
            section = section_map.get(row["section_id"])
            material = material_map.get(row["material_id"])
            lines.append(
                "| "
                + " | ".join(
                    [
                        _rr._markdown_table_cell(row["anchor_id"]),
                        _rr._markdown_table_cell(section.title if section else ""),
                        _rr._markdown_table_cell(row["paragraph_index"]),
                        _rr._markdown_table_cell(
                            material.title if material else row["material_id"]
                        ),
                        _rr._markdown_table_cell(row["claim_excerpt"]),
                        _rr._markdown_table_cell(row["source_excerpt"]),
                    ]
                )
                + " |"
            )

    if academic_export["review_findings"]:
        lines.append("\n## 审计提示\n")
        for finding in academic_export["review_findings"]:
            lines.append(f"- {finding['message']}")

    # References
    if materials:
        lines.append("\n## 参考文献\n")
        for i, mat in enumerate(materials, 1):
            title = mat.title or mat.title_en or "无标题"
            lines.append(f"{i}. {title}")
            if mat.summary:
                lines.append(f"   摘要: {mat.summary[:100]}...")
            lines.append("")

    return {
        "project_id": project_id,
        "format": "markdown",
        "filename": f"{project.title}.md",
        "content": "\n".join(lines),
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


@_rr.router.post("/maintenance/cleanup", tags=["Resources"])
async def cleanup_historical_dirty_data(request: CleanupRequest) -> dict[str, Any]:
    """Preview or execute cleanup for duplicate projects and non-extractable materials."""
    store = _rr.get_writing_resource_store()
    duplicate_projects, empty_materials = _rr._analyze_cleanup_candidates(store)

    preview = {
        "duplicate_project_count": len(duplicate_projects),
        "empty_material_count": len(empty_materials),
        "duplicate_projects": duplicate_projects,
        "empty_materials": empty_materials,
    }

    if request.dry_run:
        return {
            "dry_run": True,
            "preview": preview,
            "deleted": {
                "duplicate_project_count": 0,
                "empty_material_count": 0,
                "duplicate_projects": [],
                "empty_materials": [],
            },
        }

    deleted_duplicate_projects: list[str] = []
    deleted_empty_materials: list[str] = []

    for item in duplicate_projects:
        project_id = str(item.get("project_id") or "")
        if not project_id:
            continue
        if store.delete_project(project_id):
            deleted_duplicate_projects.append(project_id)
            doc_store_path = _rr._get_doc_store_path(project_id)
            if doc_store_path.exists():
                try:
                    doc_store_path.unlink()
                except OSError:
                    _rr.logger.warning("Failed to remove doc_store file during cleanup: %s", doc_store_path)
            chunk_store_path = _rr._get_chunk_store_path(project_id)
            if chunk_store_path.exists():
                try:
                    chunk_store_path.unlink()
                except OSError:
                    _rr.logger.warning("Failed to remove chunk_store file during cleanup: %s", chunk_store_path)

    for item in empty_materials:
        project_id = str(item.get("project_id") or "")
        material_id = str(item.get("material_id") or "")
        if not material_id or not project_id:
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
            "duplicate_projects": deleted_duplicate_projects,
            "empty_materials": deleted_empty_materials,
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
