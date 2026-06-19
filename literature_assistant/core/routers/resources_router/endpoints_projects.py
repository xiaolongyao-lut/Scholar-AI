# -*- coding: utf-8 -*-
"""Project / section / stats endpoints split out of resources_router.__init__.

All references to module-level helpers go through ``_rr.X`` (absolute import
of the package) so that pytest ``monkeypatch.setattr(rr, "X", ...)`` keeps
affecting the live endpoint behaviour.
"""

import asyncio
import inspect
from pathlib import Path
from time import perf_counter
from typing import Any
import os
import threading

from fastapi import HTTPException, Query

from datetime_utils import utc_now_iso_z
from models import (
    ProjectPayload,
    ProjectReasoningBiasOptimizeRequest,
    ProjectReasoningBiasOptimizeResponse,
    ProjectReasoningBiasOptimizeScope,
    ProjectReasoningBiasPayload,
    ProjectReasoningBiasUpdateRequest,
    SectionPayload,
    CreateProjectRequest,
    CreateSectionRequest,
    SourceFolderRefPayload,
)
from prompts.reasoning_bias_optimizer import (
    build_reasoning_bias_optimizer_prompt,
    deterministic_reasoning_bias_optimization,
    parse_reasoning_bias_optimizer_response,
    resolve_optimizer_language,
)

import routers.resources_router as _rr
from routers.resources_router.path_guard import (
    assert_bound_source_folder,
    assert_safe_source_folder,
    build_binding,
    binding_ref_payload,
)


def _coerce_runtime_job_bool(value: Any) -> bool:
    """Coerce common query truthy values for scan-folder job submission."""

    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on", "job", "async"}


# =========================================================================
# Project CRUD
# =========================================================================

def _project_payload_from_resource(project: Any) -> ProjectPayload:
    """Return a public project payload while preserving metadata extension keys."""
    if project is None:
        raise ValueError("project must not be None")
    metadata = getattr(project, "metadata", None)
    if metadata is not None and not isinstance(metadata, dict):
        raise HTTPException(status_code=500, detail="Project metadata must be an object")
    metadata_dict = dict(metadata or {})
    d = project.to_dict()
    d["source_folder"] = str(metadata_dict.get("source_folder", ""))
    raw_source_ref = metadata_dict.get("source_folder_ref")
    d["source_folder_ref"] = (
        SourceFolderRefPayload(
            display_name=str(raw_source_ref.get("display_name", "")),
            bound_at=str(raw_source_ref.get("bound_at", "")),
            bound_by=str(raw_source_ref.get("bound_by", "")),
        )
        if isinstance(raw_source_ref, dict)
        else None
    )
    raw_bias = metadata_dict.get("project_reasoning_bias")
    d["project_reasoning_bias"] = (
        ProjectReasoningBiasPayload.model_validate(raw_bias)
        if isinstance(raw_bias, dict)
        else None
    )
    return ProjectPayload(**d)


def _default_project_reasoning_bias() -> ProjectReasoningBiasPayload:
    """Return the API default for projects that have no saved reasoning bias."""
    return ProjectReasoningBiasPayload()


def _source_folder_metadata(project_id: str, source_folder: str, *, bound_by: str) -> dict[str, Any]:
    """Build guarded source-folder metadata for project writes.

    Args:
        project_id: Owning project identifier.
        source_folder: User-selected local source directory.
        bound_by: Auditable actor/source that confirmed the path.

    Returns:
        Metadata keys that must be persisted together.
    """

    if not project_id or not isinstance(project_id, str):
        raise ValueError("project_id must be a non-empty string")
    folder_raw = str(source_folder or "").strip()
    if not folder_raw:
        return {}
    real = assert_safe_source_folder(Path(folder_raw))
    binding = build_binding(project_id, real, bound_at=utc_now_iso_z())
    return {
        "source_folder": str(real),
        "source_folder_ref": binding_ref_payload(binding, bound_by=bound_by),
    }


def _create_legacy_source_index_dir(source_folder: str) -> None:
    """Create the opt-in legacy sidecar index directory for a guarded path."""

    if not source_folder or os.environ.get("LITASSIST_USE_SOURCE_FOLDER_INDEX", "").strip() != "1":
        return
    try:
        (Path(source_folder) / _rr._SCHOLAR_SUBDIR).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _rr.logger.warning("Could not create .scholarai dir in source_folder: %s", exc)


def _bias_scopes_to_optimizer_scopes(
    bias: ProjectReasoningBiasPayload | None,
) -> list[ProjectReasoningBiasOptimizeScope]:
    """Map stored bias scopes into optimizer target scope names."""
    if bias is None:
        return []
    scopes: list[ProjectReasoningBiasOptimizeScope] = []
    if bias.scopes.analysis_chain:
        scopes.append("analysis_chain")
    if bias.scopes.chat_generation:
        scopes.append("chat_generation")
    if bias.scopes.discussion_agent_ids:
        scopes.append("discussion_agent")
    if bias.scopes.project_wide:
        scopes.append("project_wide")
    return scopes


def _extract_ai_text(response: Any) -> str:
    """Read text content from common OpenAI-compatible response shapes."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    return str(message.get("content") or "")
                return str(first_choice.get("text") or "")
        return str(response.get("content") or response.get("text") or "")
    choices = getattr(response, "choices", None)
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        if message is not None:
            return str(getattr(message, "content", "") or "")
        return str(getattr(first_choice, "text", "") or "")
    return ""


async def _generate_reasoning_bias_optimization_text(adapter: Any, prompt: str) -> str:
    """Call the configured AI adapter when it exposes a supported generation API."""
    if adapter is None:
        return ""

    generate_text = getattr(adapter, "generate_text", None)
    if callable(generate_text):
        response = generate_text(prompt=prompt, max_tokens=1200, temperature=0.2)
        if inspect.isawaitable(response):
            response = await response
        return _extract_ai_text(response)

    if getattr(adapter, "enabled", False):
        chat = getattr(adapter, "_chat", None)
        if callable(chat):
            response = await asyncio.to_thread(
                chat,
                prompt,
                task="generation",
                overrides={"temperature": 0.2, "max_tokens": 1200},
                response_format={"type": "json_object"},
            )
            return _extract_ai_text(response)
    return ""


@_rr.router.post("/project", response_model=ProjectPayload)
async def create_project(request: CreateProjectRequest) -> ProjectPayload:
    """Create a new writing project."""
    from writing_resources import ContentType
    store = _rr.get_writing_resource_store()
    try:
        content_type = ContentType(request.content_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid content_type: {request.content_type}")

    folder_raw = str(request.source_folder or "").strip()
    if folder_raw:
        assert_safe_source_folder(Path(folder_raw))
    project = store.create_project(
        title=request.title,
        description=request.description,
        content_type=content_type,
        user_id=request.user_id,
        tags=request.tags,
        metadata={},
    )
    if folder_raw:
        guarded_metadata = {
            **dict(project.metadata or {}),
            **_source_folder_metadata(project.project_id, folder_raw, bound_by="project_create"),
        }
        updated_project = store.update_project(project.project_id, metadata=guarded_metadata)
        if not updated_project:
            store.delete_project(project.project_id)
            raise HTTPException(status_code=500, detail="Failed to bind project source folder")
        project = updated_project
        _create_legacy_source_index_dir(str(project.metadata["source_folder"]))
    return _project_payload_from_resource(project)


@_rr.router.get("/project/{project_id}", response_model=ProjectPayload)
async def get_project(project_id: str) -> ProjectPayload:
    """Get a project by ID."""
    store = _rr.get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return _project_payload_from_resource(project)


@_rr.router.get("/projects", response_model=list[ProjectPayload])
async def list_projects(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
) -> list[ProjectPayload]:
    """List all projects, optionally filtered by user. Supports pagination via query params."""
    store = _rr.get_writing_resource_store()
    projects = store.list_projects(user_id=user_id)
    all_payloads = []
    for p in projects:
        all_payloads.append(_project_payload_from_resource(p))
    return all_payloads


@_rr.router.put("/project/{project_id}/status")
async def update_project_status(
    project_id: str,
    status: str = Query(..., description="New status"),
) -> ProjectPayload:
    """Update project status."""
    from writing_resources import ProjectStatus
    store = _rr.get_writing_resource_store()
    try:
        project_status = ProjectStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    project = store.update_project_status(project_id, project_status)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return _project_payload_from_resource(project)


@_rr.router.put("/project/{project_id}/source-folder")
async def update_project_source_folder(
    project_id: str,
    source_folder: str = Query(..., description="绝对路径，留空则恢复默认存储位置"),
) -> ProjectPayload:
    """Update the source_folder of a project.

    When set, chunk / doc store JSON files will be saved inside
    ``{source_folder}/.scholarai/`` alongside the user's literature files.
    """
    store = _rr.get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    new_metadata = dict(project.metadata)
    folder_raw = source_folder.strip()
    if folder_raw:
        # Binding mode: validate + persist a project-scoped source_folder_ref so
        # scan-folder can later enforce "scan only what was bound" (plan §7).
        new_metadata.update(_source_folder_metadata(project_id, folder_raw, bound_by="desktop_picker"))
    else:
        # Empty path = revert to default storage; clear both the legacy key and the ref.
        new_metadata.pop("source_folder", None)
        new_metadata.pop("source_folder_ref", None)
    updated = store.update_project(project_id, metadata=new_metadata)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update project metadata")
    if folder_raw:
        _create_legacy_source_index_dir(str(new_metadata["source_folder"]))
    return _project_payload_from_resource(updated)


@_rr.router.get("/project/{project_id}/reasoning-bias", response_model=ProjectReasoningBiasPayload)
async def get_project_reasoning_bias(project_id: str) -> ProjectReasoningBiasPayload:
    """Return the project-level user reasoning bias or the empty default."""
    store = _rr.get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    metadata = project.metadata
    if metadata is not None and not isinstance(metadata, dict):
        raise HTTPException(status_code=500, detail="Project metadata must be an object")
    raw_bias = dict(metadata or {}).get("project_reasoning_bias")
    if raw_bias is None:
        return _default_project_reasoning_bias()
    if not isinstance(raw_bias, dict):
        raise HTTPException(status_code=500, detail="Stored project_reasoning_bias must be an object")
    return ProjectReasoningBiasPayload.model_validate(raw_bias)


@_rr.router.put("/project/{project_id}/reasoning-bias", response_model=ProjectReasoningBiasPayload)
async def update_project_reasoning_bias(
    project_id: str,
    request: ProjectReasoningBiasUpdateRequest,
) -> ProjectReasoningBiasPayload:
    """Replace only the project_reasoning_bias key inside project metadata."""
    store = _rr.get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    if project.metadata is not None and not isinstance(project.metadata, dict):
        raise HTTPException(status_code=500, detail="Project metadata must be an object")

    payload = ProjectReasoningBiasPayload(
        human_bias=request.human_bias,
        scopes=request.scopes,
        language=request.language,
        updated_at=utc_now_iso_z(),
        updated_by="user",
    )
    new_metadata = dict(project.metadata or {})
    new_metadata["project_reasoning_bias"] = payload.model_dump(mode="json")
    updated = store.update_project(project_id, metadata=new_metadata)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update project metadata")
    return payload


@_rr.router.post("/project/{project_id}/reasoning-bias/optimize", response_model=ProjectReasoningBiasOptimizeResponse)
async def optimize_project_reasoning_bias(
    project_id: str,
    request: ProjectReasoningBiasOptimizeRequest,
) -> ProjectReasoningBiasOptimizeResponse:
    """Return a structured optimization suggestion without persisting anything."""
    store = _rr.get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    if project.metadata is not None and not isinstance(project.metadata, dict):
        raise HTTPException(status_code=500, detail="Project metadata must be an object")

    metadata = dict(project.metadata or {})
    stored_raw_bias = metadata.get("project_reasoning_bias")
    stored_bias = ProjectReasoningBiasPayload.model_validate(stored_raw_bias) if isinstance(stored_raw_bias, dict) else None

    source_bias = str(request.human_bias or "").strip() or str(stored_bias.human_bias if stored_bias else "").strip()
    target_scopes = list(request.target_scopes) or _bias_scopes_to_optimizer_scopes(stored_bias)
    language = resolve_optimizer_language(source_bias, request.language)
    prompt = build_reasoning_bias_optimizer_prompt(
        human_bias=source_bias,
        language=language,
        target_scopes=target_scopes,
    )

    adapter = _rr.get_ai_adapter()
    try:
        raw_text = await _generate_reasoning_bias_optimization_text(adapter, prompt)
    except Exception as exc:  # pragma: no cover - adapter failures are environment-specific
        _rr.logger.warning("Reasoning bias optimizer unavailable; using deterministic fallback: %s", exc)
        raw_text = ""

    if raw_text.strip():
        return parse_reasoning_bias_optimizer_response(
            original_bias=source_bias,
            raw_text=raw_text,
            language=language,
            target_scopes=target_scopes,
        )
    return deterministic_reasoning_bias_optimization(
        human_bias=source_bias,
        language=language,
        target_scopes=target_scopes,
    )


@_rr.router.delete("/project/{project_id}")
async def delete_project(project_id: str) -> dict[str, str]:
    """Delete a project and all its associated resources."""
    store = _rr.get_writing_resource_store()
    deleted = store.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    doc_store_path = _rr._get_doc_store_path(project_id)
    if doc_store_path.exists():
        try:
            doc_store_path.unlink()
        except OSError:
            _rr.logger.warning("Failed to remove doc_store file: %s", doc_store_path)
    chunk_store_path = _rr._get_chunk_store_path(project_id)
    if chunk_store_path.exists():
        try:
            chunk_store_path.unlink()
        except OSError:
            _rr.logger.warning("Failed to remove chunk_store file: %s", chunk_store_path)
    try:
        _rr._remove_project_workspace_dir(project_id)
    except OSError as exc:
        _rr.logger.warning("Failed to remove project workspace dir: project=%s err=%s", project_id, exc)
    return {"status": "deleted", "project_id": project_id}


def _run_scan_folder_payload(
    project_id: str,
    *,
    scan_mode: str,
    batch_size: int,
    max_workers: int,
    runtime_job_id: str | None = None,
) -> dict[str, Any]:
    """Run the guarded source-folder scan and return the stable manifest.

    Args:
        project_id: Project whose bound ``source_folder`` is scanned.
        scan_mode: ``legacy`` or ``fast``.
        batch_size: Positive batch size for fast scan mode.
        max_workers: Positive worker count for fast scan mode.
        runtime_job_id: Optional owning runtime job id for audit metadata.

    Returns:
        Scan manifest with indexed/skipped/failed counts and per-file results.
    """

    if not str(project_id or "").strip():
        raise ValueError("project_id must be a non-empty string")
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    if not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")
    store = _rr._ensure_upload_project(project_id)
    project_obj = _rr.get_writing_resource_store().get_project(project_id)
    if not project_obj:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    source_folder = str(project_obj.metadata.get("source_folder", "")).strip()
    if not source_folder:
        raise HTTPException(
            status_code=400,
            detail="该项目没有设置文献文件夹（source_folder）。请先在项目设置中指定文件夹路径。",
        )
    # Check mode: re-validate safety (reparse/sensitive) and enforce that the
    # folder matches the project's bound source_folder_ref (plan §7).
    folder_path = assert_safe_source_folder(Path(source_folder))
    assert_bound_source_folder(folder_path, project_obj.metadata.get("source_folder_ref"))

    normalized_mode = str(scan_mode or "").strip().lower()
    if normalized_mode not in _rr._SCAN_MODES:
        raise HTTPException(status_code=400, detail=f"scan_mode 不支持: {scan_mode}，可选值: legacy, fast")

    t_total = perf_counter()
    t_collect = perf_counter()
    candidate_payload = _rr._collect_pending_scan_candidates(project_id, folder_path)
    collect_ms = (perf_counter() - t_collect) * 1000.0
    candidates = candidate_payload["candidates"]
    pending_candidates = candidate_payload["pending"]
    existing_titles = candidate_payload["existing_titles"]
    existing_fingerprints = candidate_payload["existing_fingerprints"]
    skipped_results = list(candidate_payload["skipped_results"])
    failed_results = list(candidate_payload["failed_results"])

    _rr.logger.info(
        "scan_folder.collect project=%s total=%d pending=%d skipped=%d failed=%d collect_ms=%.1f folder=%s",
        project_id,
        len(candidates),
        len(pending_candidates),
        len(skipped_results),
        len(failed_results),
        collect_ms,
        folder_path,
    )

    t_zotero = perf_counter()
    zotero_title_map = _rr._load_zotero_title_map(folder_path)
    zotero_ms = (perf_counter() - t_zotero) * 1000.0

    t_ingest = perf_counter()
    ingest_payload = _rr._ingest_pending_candidates(
        project_id,
        store=store,
        pending_candidates=pending_candidates,
        zotero_title_map=zotero_title_map,
        scan_mode=normalized_mode,
        batch_size=batch_size,
        max_workers=max_workers,
        existing_titles=existing_titles,
        existing_fingerprints=existing_fingerprints,
    )
    ingest_ms = (perf_counter() - t_ingest) * 1000.0
    total_ms = (perf_counter() - t_total) * 1000.0

    _rr.logger.info(
        "scan_folder.done project=%s total=%dms collect=%.1fms zotero=%.1fms ingest=%.1fms indexed=%d failed=%d chunks=%d",
        project_id,
        int(total_ms),
        collect_ms,
        zotero_ms,
        ingest_ms,
        int(ingest_payload["indexed"]),
        int(ingest_payload["failed"]),
        int(ingest_payload["total_chunks"]),
    )

    results = [*skipped_results, *failed_results, *list(ingest_payload["results"])]
    skipped = len(skipped_results)
    failed = len(failed_results) + int(ingest_payload["failed"])

    return {
        "project_id": project_id,
        "folder": str(folder_path),
        "scan_mode": str(ingest_payload["scan_mode"]),
        "batch_size": batch_size,
        "workers": int(ingest_payload["workers"]),
        "total_files": len(candidates),
        "queued": len(pending_candidates),
        "indexed": int(ingest_payload["indexed"]),
        "skipped": skipped,
        "failed": failed,
        "total_chunks": int(ingest_payload["total_chunks"]),
        "timing_ms": {
            "total": int(total_ms),
            "collect": int(collect_ms),
            "zotero": int(zotero_ms),
            "ingest": int(ingest_ms),
        },
        "results": results,
        **({"runtime_job_id": runtime_job_id} if runtime_job_id else {}),
    }


async def _start_scan_folder_runtime_job(
    project_id: str,
    *,
    scan_mode: str,
    batch_size: int,
    max_workers: int,
) -> dict[str, Any]:
    """Create and start a runtime-visible resource-ingest job for scan-folder."""

    from harness_protocols import JobKind, SessionMode
    from writing_runtime import get_writing_runtime

    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        raise ValueError("project_id must be a non-empty string")
    normalized_mode = str(scan_mode or "").strip().lower()
    if normalized_mode not in _rr._SCAN_MODES:
        raise HTTPException(status_code=400, detail=f"scan_mode 不支持: {scan_mode}，可选值: legacy, fast")

    runtime = get_writing_runtime()
    session = runtime.create_session(
        mode=SessionMode.PROMPT,
        tags=["resource_ingest", "scan_folder"],
        metadata={
            "source": "resource_ingest",
            "title": "文献文件夹入库",
            "project_id": normalized_project_id,
        },
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text=f"扫描项目文献文件夹: {normalized_project_id}",
        tags=["resource_ingest", "scan_folder"],
        metadata={
            "source": "resource_ingest",
            "project_id": normalized_project_id,
            "scan_mode": normalized_mode,
            "batch_size": batch_size,
            "max_workers": max_workers,
            "progress_stage": "queued",
            "progress_message": "文献文件夹扫描已排队",
            "progress": 1,
        },
    )
    runtime.update_job_metadata(
        job.job_id,
        {
            "status_url": f"/runtime/job/{job.job_id}/snapshot",
            "artifacts_url": f"/runtime/job/{job.job_id}/artifacts",
        },
    )

    async def _executor(current_job: Any) -> dict[str, Any]:
        target_job = current_job or job
        runtime.emit_job_progress(target_job.job_id, stage="prepare", message="正在校验项目文献文件夹", progress=8)

        def _scan() -> dict[str, Any]:
            return _run_scan_folder_payload(
                normalized_project_id,
                scan_mode=normalized_mode,
                batch_size=batch_size,
                max_workers=max_workers,
                runtime_job_id=target_job.job_id,
            )

        runtime.emit_job_progress(target_job.job_id, stage="ingest", message="正在扫描并写入项目库", progress=35)
        payload = await asyncio.to_thread(_scan)
        runtime.emit_job_progress(
            target_job.job_id,
            stage="finalize",
            message="正在保存文献入库结果",
            progress=94,
            data={
                "indexed": int(payload.get("indexed") or 0),
                "failed": int(payload.get("failed") or 0),
                "total_chunks": int(payload.get("total_chunks") or 0),
            },
        )
        return {
            "status": "completed",
            "kind": JobKind.RESOURCE_INGEST.value,
            **payload,
        }

    async def _run_job_thread_async() -> None:
        await runtime.start_job(job.job_id, executor=_executor)
        task = getattr(runtime, "_job_tasks", {}).get(job.job_id)
        if task is not None:
            await task

    def _run_job_thread() -> None:
        try:
            asyncio.run(_run_job_thread_async())
        except BaseException as exc:  # noqa: BLE001 - background thread must fail the runtime job, not vanish.
            async def _mark_failed() -> None:
                current = runtime.get_job(job.job_id)
                if current is not None and str(getattr(current.status, "value", current.status)) != "cancelled":
                    await runtime.fail_job(job.job_id, str(exc))

            asyncio.run(_mark_failed())

    thread = threading.Thread(
        target=_run_job_thread,
        name=f"resource-ingest-{job.job_id}",
        daemon=True,
    )
    thread.start()
    current_job = runtime.get_job(job.job_id) or job
    return {
        "project_id": normalized_project_id,
        "runtime_job_ref": {
            "session_id": session.session_id,
            "job_id": current_job.job_id,
            "kind": JobKind.RESOURCE_INGEST.value,
            "status": current_job.status.value,
        },
        "status_url": f"/runtime/job/{current_job.job_id}/snapshot",
        "job_url": f"/runtime/job/{current_job.job_id}",
        "artifacts_url": f"/runtime/job/{current_job.job_id}/artifacts",
    }


@_rr.router.post("/project/{project_id}/scan-folder")
async def scan_project_folder(
    project_id: str,
    scan_mode: str = Query(
        "fast",
        description="扫描模式：legacy（串行兼容）/ fast（元数据预扫 + 分批并发解析）",
    ),
    batch_size: int = Query(
        24,
        ge=1,
        le=256,
        description="fast 模式下每批处理文件数",
    ),
    max_workers: int = Query(
        8,
        ge=1,
        le=64,
        description="fast 模式下并发 worker 数（建议 4-16）",
    ),
    async_job: bool = Query(False, description="为 MCP/任务中心提交 runtime job，而不是同步等待扫描完成"),
) -> dict[str, Any]:
    """Scan the project's source_folder and ingest all literature files.

    Reads all supported files (.pdf, .docx, .doc, .txt, .md) from the project's
    source_folder and indexes them into the knowledge base. Already-indexed
    files are skipped. Set ``async_job=true`` to submit the scan as a runtime
    job that can be polled through ``/runtime/job/{id}/snapshot``.
    """

    if _coerce_runtime_job_bool(async_job):
        return await _start_scan_folder_runtime_job(
            project_id,
            scan_mode=scan_mode,
            batch_size=batch_size,
            max_workers=max_workers,
        )
    return _run_scan_folder_payload(
        project_id,
        scan_mode=scan_mode,
        batch_size=batch_size,
        max_workers=max_workers,
    )


# =========================================================================
# Section CRUD
# =========================================================================

@_rr.router.post("/section", response_model=SectionPayload)
async def create_section(request: CreateSectionRequest) -> SectionPayload:
    """Create a section within a project."""
    store = _rr.get_writing_resource_store()
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


@_rr.router.get("/section/{section_id}", response_model=SectionPayload)
async def get_section(section_id: str) -> SectionPayload:
    """Get a section by ID."""
    store = _rr.get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"Section not found: {section_id}")
    return SectionPayload(**section.to_dict())


@_rr.router.get("/sections", response_model=list[SectionPayload])
async def list_sections(project_id: str = Query(...)) -> list[SectionPayload]:
    """List all sections in a project."""
    store = _rr.get_writing_resource_store()
    sections = store.list_sections(project_id)
    return [SectionPayload(**s.to_dict()) for s in sections]


@_rr.router.delete("/section/{section_id}", tags=["Resources"])
async def delete_section(section_id: str) -> dict[str, str]:
    """Delete a section by ID."""
    store = _rr.get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"章节不存在: {section_id}")
    store.delete_section(section_id)
    return {"status": "deleted", "section_id": section_id}


# =========================================================================
# Section / Project Update Endpoints (RESTful completeness)
# =========================================================================

class UpdateSectionRequest(__import__("pydantic").BaseModel):
    title: str | None = None
    description: str | None = None
    order: int | None = None


@_rr.router.put("/section/{section_id}", tags=["Resources"])
async def update_section(section_id: str, request: UpdateSectionRequest) -> SectionPayload:
    """Update section title, description, or order."""
    store = _rr.get_writing_resource_store()
    section = store.get_section(section_id)
    if not section:
        raise HTTPException(status_code=404, detail=f"章节不存在: {section_id}")

    updates: dict[str, Any] = {}
    if request.title is not None:
        updates["title"] = request.title
    if request.description is not None:
        updates["description"] = request.description
    if request.order is not None:
        updates["order"] = request.order

    if updates:
        updated = store.update_section(section_id, **updates)
        if updated:
            return SectionPayload(**updated.to_dict())

    return SectionPayload(**section.to_dict())


class UpdateProjectRequest(__import__("pydantic").BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None


@_rr.router.put("/project/{project_id}", tags=["Resources"])
async def update_project(project_id: str, request: UpdateProjectRequest) -> ProjectPayload:
    """Update project title, description, or tags."""
    store = _rr.get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    updates: dict[str, Any] = {}
    if request.title is not None:
        updates["title"] = request.title
    if request.description is not None:
        updates["description"] = request.description
    if request.tags is not None:
        updates["tags"] = request.tags

    if updates:
        updated = store.update_project(project_id, **updates)
        if updated:
            return _project_payload_from_resource(updated)

    return _project_payload_from_resource(project)


# =========================================================================
# Project Stats
# =========================================================================

@_rr.router.get("/project/{project_id}/stats", tags=["Statistics"])
async def get_project_stats(project_id: str) -> dict[str, Any]:
    """Get comprehensive statistics for a project."""
    store = _rr.get_writing_resource_store()
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    sections = store.list_sections(project_id)
    drafts = store.list_drafts(project_id)
    materials = store.list_materials(project_id)
    doc_store = _rr._load_doc_store(project_id)

    total_words = sum(len(d.content) for d in drafts if hasattr(d, "content") and d.content)
    total_revisions = sum(
        len(store.list_revisions(d.draft_id)) for d in drafts
    )

    return {
        "project_id": project_id,
        "title": project.title,
        "status": project.status,
        "section_count": len(sections),
        "draft_count": len(drafts),
        "material_count": len(materials),
        "document_count": len(doc_store),
        "total_characters": total_words,
        "total_revisions": total_revisions,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }
