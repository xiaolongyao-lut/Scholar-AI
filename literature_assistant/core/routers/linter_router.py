# -*- coding: utf-8 -*-
"""元数据 Linter API 路由：检查和修复文献元数据。"""

from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from literature_assistant.core.metadata_linter import (
        CaseStyle,
        LinterResult,
        apply_linter_fixes,
        lint_material_metadata,
    )
    from literature_assistant.core.linter_adapter import lint_materials_with_new_engine
    from literature_assistant.core.terminal_logger import linter_logger
except ModuleNotFoundError:
    from metadata_linter import (  # type: ignore[no-redef]
        CaseStyle,
        LinterResult,
        apply_linter_fixes,
        lint_material_metadata,
    )
    from linter_adapter import lint_materials_with_new_engine  # type: ignore[no-redef]
    from terminal_logger import linter_logger  # type: ignore[no-redef]

router = APIRouter(prefix="/api/linter", tags=["Linter"])


class LintRequest(BaseModel):
    """单个文献 lint 请求。"""
    material_id: str
    title: str
    title_en: str | None = None
    authors: list[str] | None = None
    publication_date: str | None = None
    journal: str | None = None
    doi: str | None = None
    preferred_case: CaseStyle = Field(default="title", description="英文标题大小写风格")


class BatchLintRequest(BaseModel):
    """批量 lint 请求。"""
    project_id: str
    material_ids: list[str] | None = Field(default=None, description="指定文献 ID 列表，为空则检查整个项目")
    preferred_case: CaseStyle = Field(default="title")


class ApplyFixesRequest(BaseModel):
    """应用修复请求。"""
    material_id: str
    fixes: list[str] = Field(description="要修复的字段列表，如 ['title', 'title_en', 'authors']")
    preferred_case: CaseStyle = Field(default="title")


def _get_writing_store() -> Any:
    """Resolve the active writing store through the existing resource router seam."""
    try:
        from routers.resources_router import get_writing_resource_store
    except ModuleNotFoundError:
        from literature_assistant.core.routers.resources_router import get_writing_resource_store
    return get_writing_resource_store()


def _metadata_dict(material_dict: dict[str, Any]) -> dict[str, Any]:
    metadata = material_dict.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _first_text(material_dict: dict[str, Any], metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = material_dict.get(key)
        if value is None:
            value = metadata.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _authors_from_metadata(material_dict: dict[str, Any], metadata: dict[str, Any]) -> list[str] | None:
    value = material_dict.get("authors")
    if value is None:
        value = metadata.get("authors")
    if not isinstance(value, list):
        return None
    return [str(author).strip() for author in value if str(author).strip()]


def _material_linter_payload(material: Any) -> dict[str, Any]:
    """Flatten top-level material fields and Zotero/CSL metadata aliases for linting."""
    material_dict = material.to_dict()
    if not isinstance(material_dict, dict):
        raise TypeError("material.to_dict() must return a dictionary")
    metadata = _metadata_dict(material_dict)
    publication_date = _first_text(material_dict, metadata, "publication_date", "date")
    if publication_date is None:
        publication_date = _first_text(material_dict, metadata, "year")
    return {
        "material_id": str(material.material_id),
        "title": str(material_dict.get("title") or ""),
        "title_en": _first_text(material_dict, metadata, "title_en"),
        "authors": _authors_from_metadata(material_dict, metadata),
        "publication_date": publication_date,
        "journal": _first_text(material_dict, metadata, "journal", "publicationTitle", "venue"),
        "doi": _first_text(material_dict, metadata, "doi", "DOI"),
    }


def _lint_material(material: Any, preferred_case: CaseStyle) -> LinterResult:
    payload = _material_linter_payload(material)
    return lint_material_metadata(
        material_id=payload["material_id"],
        title=payload["title"],
        title_en=payload["title_en"],
        authors=payload["authors"],
        publication_date=payload["publication_date"],
        journal=payload["journal"],
        doi=payload["doi"],
        preferred_case=preferred_case,
    )


@router.post("/lint", response_model=LinterResult)
async def lint_single_material(request: LintRequest) -> LinterResult:
    """检查单个文献的元数据规范性。"""
    try:
        return lint_material_metadata(
            material_id=request.material_id,
            title=request.title,
            title_en=request.title_en,
            authors=request.authors,
            publication_date=request.publication_date,
            journal=request.journal,
            doi=request.doi,
            preferred_case=request.preferred_case,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/lint/batch", response_model=list[LinterResult])
async def lint_batch(request: BatchLintRequest) -> list[LinterResult]:
    """批量检查项目中的文献元数据（使用新 linter 引擎）。"""
    store = _get_writing_store()
    project = store.get_project(request.project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {request.project_id}")

    materials = store.list_materials(request.project_id)

    # 过滤指定的 material_ids
    if request.material_ids:
        materials = [m for m in materials if m.material_id in request.material_ids]

    # 准备材料数据
    material_payloads = [_material_linter_payload(m) for m in materials]

    # 使用新 linter 引擎
    try:
        results = await lint_materials_with_new_engine(
            material_payloads,
            preferred_case=request.preferred_case,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return results


@router.post("/apply-fixes")
async def apply_fixes(request: ApplyFixesRequest) -> dict[str, Any]:
    """应用 linter 修复建议并保存到数据库（使用新 linter 引擎）。"""
    linter_logger.info("收到修复请求",
                       material_id=request.material_id,
                       fixes=", ".join(request.fixes))

    store = _get_writing_store()
    material = store.get_material(request.material_id)
    if not material:
        linter_logger.error("文献不存在", material_id=request.material_id)
        raise HTTPException(status_code=404, detail=f"文献不存在: {request.material_id}")

    # 准备材料数据
    material_payload = _material_linter_payload(material)
    linter_logger.debug("材料数据",
                        title=material_payload.get('title', '')[:50],
                        title_en=material_payload.get('title_en', '')[:50])

    # 使用新 linter 引擎执行修复（这会修改 material_payload）
    try:
        from literature_assistant.core.linter import lint_materials as new_lint_materials

        # lint_materials 会就地修改材料数据
        fixed_materials = await new_lint_materials([material_payload], debug=False)

        if not fixed_materials:
            linter_logger.error("Linter 返回空结果")
            raise ValueError("Linter 返回空结果")

        # fixed_materials[0] 包含修复后的数据
        fixed_dict = fixed_materials[0]
        linter_logger.debug("修复完成",
                           title_en_after=str(fixed_dict.get('title_en', ''))[:50])

    except (TypeError, ValueError) as exc:
        linter_logger.error("修复失败", reason=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 更新数据库（只更新用户请求修复的字段）
    updates = {}
    for field in request.fixes:
        # 从修复后的数据中获取
        if field in fixed_dict:
            updates[field] = fixed_dict[field]

    if updates:
        linter_logger.info("准备更新数据库", fields=", ".join(updates.keys()))

    # 如果没有需要更新的字段，说明已经是清洁状态
    if not updates:
        linter_logger.info("文献已清洁，无需更新数据库")
        # 返回当前状态，不报错
        result_payload = _material_linter_payload(material)
        new_results = await lint_materials_with_new_engine(
            [result_payload],
            preferred_case=request.preferred_case,
        )
        result = new_results[0] if new_results else None
        issue_count = len(result.get('issues', [])) if result else 0
        linter_logger.success("修复完成", 剩余问题=issue_count)
        return {
            "ok": True,
            "result": result,
        }

    updated = store.update_material(
        material_id=request.material_id,
        **updates
    )
    if updated is None:
        linter_logger.error("更新失败：文献不存在", material_id=request.material_id)
        raise HTTPException(status_code=404, detail=f"文献不存在: {request.material_id}")

    linter_logger.success("数据库更新成功")

    # 返回修复后的 linter 结果
    result_payload = _material_linter_payload(updated)
    new_results = await lint_materials_with_new_engine(
        [result_payload],
        preferred_case=request.preferred_case,
    )

    result = new_results[0] if new_results else None
    issue_count = len(result.get('issues', [])) if result else 0
    linter_logger.success("修复完成", 剩余问题=issue_count)

    return {
        "ok": True,
        "result": result,
    }


@router.get("/project/{project_id}/summary")
async def get_project_linter_summary(
    project_id: str,
    preferred_case: CaseStyle = Query(default="title"),
) -> dict:
    """获取项目级 linter 摘要：有多少文献有问题。"""
    store = _get_writing_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    materials = store.list_materials(project_id)
    total = len(materials)
    with_errors = 0
    with_warnings = 0
    with_info = 0
    with_issues = 0

    for material in materials:
        try:
            result = _lint_material(material, preferred_case)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result["has_errors"]:
            with_errors += 1
        if result["has_warnings"]:
            with_warnings += 1
        if any(issue["severity"] == "info" for issue in result["issues"]):
            with_info += 1
        if result["issues"]:
            with_issues += 1

    return {
        "project_id": project_id,
        "total_materials": total,
        "with_errors": with_errors,
        "with_warnings": with_warnings,
        "with_info_suggestions": with_info,
        "with_issues": with_issues,
        "clean_materials": total - with_issues,
    }


# ============================================================================
# 异步任务端点（任务中心集成）
# ============================================================================

_active_linter_tasks: dict[str, Any] = {}  # task_id -> LinterTask


@router.post("/lint/batch/async")
async def lint_batch_async(request: BatchLintRequest) -> dict[str, Any]:
    """异步批量检查（后台任务）

    Returns:
        {"task_id": "linter_xxx", "status": "created"}
    """
    import uuid
    from literature_assistant.core.linter_task import LinterTask

    task_id = f"linter_{uuid.uuid4().hex[:12]}"

    # 创建任务
    task = LinterTask(
        task_id=task_id,
        project_id=request.project_id,
        material_ids=request.material_ids,
    )

    _active_linter_tasks[task_id] = {
        "task": task,
        "status": "created",
        "progress": {"current": 0, "total": 0, "message": ""},
        "result": None,
        "error": None,
    }

    linter_logger.info("创建 Linter 任务", task_id=task_id, project_id=request.project_id)

    # 启动后台任务
    import asyncio
    asyncio.create_task(_run_linter_task(task_id, task, request.preferred_case))

    return {
        "task_id": task_id,
        "status": "created",
    }


async def _run_linter_task(task_id: str, task: Any, preferred_case: str):
    """运行 Linter 任务（后台）"""
    try:
        _active_linter_tasks[task_id]["status"] = "running"

        def update_progress(current: int, total: int, message: str):
            _active_linter_tasks[task_id]["progress"] = {
                "current": current,
                "total": total,
                "message": message,
            }

        result = await task.execute(update_progress)

        _active_linter_tasks[task_id]["status"] = "completed"
        _active_linter_tasks[task_id]["result"] = result

    except Exception as e:
        linter_logger.error("Linter 任务失败", task_id=task_id, error=str(e))
        _active_linter_tasks[task_id]["status"] = "failed"
        _active_linter_tasks[task_id]["error"] = str(e)


@router.get("/tasks/{task_id}")
async def get_linter_task_status(task_id: str) -> dict[str, Any]:
    """获取 Linter 任务状态"""
    if task_id not in _active_linter_tasks:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    task_data = _active_linter_tasks[task_id]

    return {
        "task_id": task_id,
        "status": task_data["status"],
        "progress": task_data["progress"],
        "result": task_data["result"],
        "error": task_data["error"],
    }


@router.get("/tasks/list")
async def list_linter_tasks() -> list[dict[str, Any]]:
    """列出所有 Linter 任务"""
    tasks = []
    for task_id, task_data in _active_linter_tasks.items():
        tasks.append({
            "task_id": task_id,
            "status": task_data["status"],
            "progress": task_data["progress"],
            "result": task_data["result"],
            "error": task_data["error"],
            "created_at": None,  # TODO: 添加创建时间
        })
    return tasks


@router.post("/tasks/{task_id}/cancel")
async def cancel_linter_task(task_id: str) -> dict[str, Any]:
    """取消 Linter 任务"""
    if task_id not in _active_linter_tasks:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    task_data = _active_linter_tasks[task_id]
    task = task_data["task"]
    task.cancel()

    linter_logger.info("取消 Linter 任务", task_id=task_id)

    return {
        "task_id": task_id,
        "status": "cancelled",
    }

