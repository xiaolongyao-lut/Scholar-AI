# -*- coding: utf-8 -*-
"""Runtime API Router - Manages writing sessions, jobs, and execution control."""

import asyncio
import logging
from typing import Any, List
from fastapi import APIRouter, HTTPException, Query
from models import (
    SessionPayload,
    CreateSessionRequest,
    JobPayload,
    CreateJobRequest,
    JobStatusPayload,
    EventPayload,
    JobEventSnapshotPayload,
    ArtifactPayload,
    TimelinePagePayload,
    CheckpointPayload,
    ResumeSessionPayload,
    RewindSessionRequest,
    ForkSessionRequest,
)

logger = logging.getLogger("RuntimeRouter")
router = APIRouter(prefix="/runtime", tags=["Runtime"])
_FIGURE_LOADER_VERSION = 3


def get_runtime():
    """Import and return the writing runtime service."""
    from writing_runtime import get_writing_runtime
    return get_writing_runtime()


def _normalize_metadata(job: Any) -> dict[str, Any]:
    """Return a mutable metadata mapping for job executors."""
    metadata = getattr(job, "metadata", None)
    return dict(metadata) if isinstance(metadata, dict) else {}


def _build_job_executor(job):
    """Build an async executor for runtime-backed jobs when references are available."""
    kind = str(getattr(getattr(job, "kind", None), "value", getattr(job, "kind", "")))
    if kind == "smart_read":
        return _build_smart_read_executor(job)
    if kind == "discussion":
        return _build_discussion_executor(job)
    if kind == "ai_review":
        return _build_ai_review_executor(job)
    if kind == "figure_load":
        return _build_figure_load_executor(job)
    if not getattr(job, "action_id", None) and not getattr(job, "skill_id", None):
        return None

    from skills.service import get_writing_skill_service

    service = get_writing_skill_service()

    async def _executor(current_job):
        target_job = current_job or job
        if getattr(target_job, "action_id", None):
            action_id = str(target_job.action_id)

            def _run_action_skill_result():
                actions = service.list_legacy_actions()
                action = next((item for item in actions if item.get("id") == action_id), None)
                if action is None:
                    raise ValueError(f"Action not found: {action_id}")
                skill_id = action.get("skillId")
                if not isinstance(skill_id, str) or not skill_id:
                    raise ValueError(f"Skill not found for action: {action_id}")
                return service.run_skill(
                    skill_id,
                    target_job.input_text,
                    target_job.scope,
                    target_job.output_mode,
                )

            return await asyncio.to_thread(
                _run_action_skill_result,
            )
        if getattr(target_job, "skill_id", None):
            return await asyncio.to_thread(
                service.run_skill,
                target_job.skill_id,
                target_job.input_text,
                target_job.scope,
                target_job.output_mode,
            )
        return None

    return _executor


def _model_to_dict(value: Any) -> dict[str, Any]:
    """Serialize a Pydantic/dataclass-like payload into a plain JSON mapping."""
    if hasattr(value, "model_dump") and callable(value.model_dump):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, "dict") and callable(value.dict):
        dumped = value.dict()
        if isinstance(dumped, dict):
            return dict(dumped)
    if isinstance(value, dict):
        return dict(value)
    raise TypeError("payload must serialize to a dict")


def _coerce_figure_load_limit(value: Any, default: int = 96) -> int:
    """Clamp figure-load limit values from job metadata to the public API range."""
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(200, parsed))


def _build_figure_load_executor(job):
    """Build a figure/table loader that only returns chunk-produced pixel assets."""
    metadata = _normalize_metadata(job)

    async def _executor(current_job):
        target_job = current_job or job
        runtime = get_runtime()
        project_id = str(metadata.get("project_id") or "").strip()
        if not project_id:
            raise ValueError("figure_load job metadata.project_id must not be empty")
        limit = _coerce_figure_load_limit(metadata.get("limit"))

        runtime.emit_job_progress(target_job.job_id, stage="prepare", message="正在读取项目图表库", progress=8)

        def _load_payload() -> dict[str, Any]:
            import routers.resources_router as resources_router
            from routers.resources_router.endpoints_search_upload import derive_figure_table_candidates
            from routers.writing_router import _figure_asset_payload

            store = resources_router._ensure_upload_project(project_id)
            assets = [
                _model_to_dict(_figure_asset_payload(asset))
                for asset in store.list_figure_assets(project_id)
            ]
            chunk_store = resources_router._ensure_project_chunks(project_id)
            candidates = [
                _model_to_dict(candidate)
                for candidate in derive_figure_table_candidates(
                    project_id,
                    chunk_store,
                    limit=limit,
                    pixel_only=True,
                    render_pdf_fallback=False,
                )
            ]
            return {
                "assets": assets,
                "candidates": candidates,
                "chunk_material_count": len(chunk_store),
            }

        runtime.emit_job_progress(target_job.job_id, stage="chunks", message="正在从切块数据读取像素级图表", progress=35)
        payload = _load_payload()
        runtime.emit_job_progress(
            target_job.job_id,
            stage="finalize",
            message="正在保存图表加载结果",
            progress=92,
            data={
                "asset_count": len(payload["assets"]),
                "candidate_count": len(payload["candidates"]),
            },
        )
        return {
            "status": "completed",
            "kind": "figure_load",
            "project_id": project_id,
            "asset_count": len(payload["assets"]),
            "candidate_count": len(payload["candidates"]),
            "assets": payload["assets"],
            "candidates": payload["candidates"],
            "chunk_material_count": payload["chunk_material_count"],
            "pixel_only": True,
            "render_pdf_fallback": False,
            "figure_loader_version": metadata.get("figure_loader_version") or _FIGURE_LOADER_VERSION,
        }

    return _executor


def _build_smart_read_executor(job):
    """Build a SmartRead executor that stores the final answer as a job artifact."""
    metadata = _normalize_metadata(job)

    async def _executor(current_job):
        target_job = current_job or job
        runtime = get_runtime()
        runtime.emit_job_progress(target_job.job_id, stage="prepare", message="正在准备智能研读上下文", progress=10)
        from routers.intelligent_chat_router import IntelligentChatRequest, intelligent_chat

        request_payload = {
            "query": target_job.input_text,
            "session_id": metadata.get("chat_session_id") or metadata.get("session_id"),
            "tier": metadata.get("tier") or "balanced",
            "project_id": metadata.get("project_id"),
            "material_id": metadata.get("material_id"),
            "source_paths": metadata.get("source_paths"),
            "mode": metadata.get("mode") or "literature_qa",
            "project_reasoning_bias_enabled": metadata.get("project_reasoning_bias_enabled"),
            "current_pdf_context": metadata.get("current_pdf_context"),
            "images": metadata.get("images") or [],
        }
        runtime.emit_job_progress(target_job.job_id, stage="running", message="AI 正在研读并生成回答", progress=35)
        response = await intelligent_chat(IntelligentChatRequest(**request_payload))
        runtime.emit_job_progress(target_job.job_id, stage="finalize", message="正在保存智能研读结果", progress=90)
        return {
            "status": "completed",
            "kind": "smart_read",
            "response": response.response,
            "text": response.response,
            "session_id": response.session_id,
            "context_chunks_used": response.context_chunks_used,
            "tokens_used": response.tokens_used.model_dump(),
            "tier_used": response.tier_used,
            "context_metadata": response.context_metadata.model_dump() if response.context_metadata else None,
            "evidence_refs": [item.model_dump() for item in response.evidence_refs or []],
            "actual_sampling_params": (
                response.actual_sampling_params.model_dump()
                if response.actual_sampling_params
                else None
            ),
        }

    return _executor


def _build_discussion_executor(job):
    """Build a discussion executor that writes the completed run to artifacts."""
    metadata = _normalize_metadata(job)

    async def _executor(current_job):
        target_job = current_job or job
        runtime = get_runtime()
        runtime.emit_job_progress(target_job.job_id, stage="prepare", message="正在准备多智能体讨论", progress=10)
        from models.discussion import DiscussionRunConfig
        from routers.discussion_advanced_router import post_discussion_run

        config_payload = metadata.get("config")
        if not isinstance(config_payload, dict):
            config_payload = {
                key: value
                for key, value in metadata.items()
                if key not in {"title", "source", "config"}
            }
        if "query" not in config_payload:
            config_payload["query"] = target_job.input_text
        runtime.emit_job_progress(target_job.job_id, stage="running", message="各角色正在生成观点", progress=35)
        result = await post_discussion_run(DiscussionRunConfig(**config_payload))
        runtime.emit_job_progress(target_job.job_id, stage="finalize", message="正在保存讨论结论", progress=90)
        payload = result.model_dump(mode="json")
        return {
            "status": "completed",
            "kind": "discussion",
            "run_id": payload.get("run_id"),
            "text": (payload.get("synthesis") or {}).get("text", ""),
            "result": payload,
        }

    return _executor


def _build_ai_review_executor(job):
    """Build an AI-review executor using the configured chat model."""
    metadata = _normalize_metadata(job)

    async def _executor(current_job):
        target_job = current_job or job
        runtime = get_runtime()
        runtime.emit_job_progress(target_job.job_id, stage="prepare", message="正在整理手稿、引用和图表", progress=10)
        from routers.intelligent_chat_router import IntelligentChatRequest, intelligent_chat

        query = str(metadata.get("prompt") or target_job.input_text or "").strip()
        if not query:
            raise ValueError("AI review prompt must not be empty")
        review_model = _describe_current_chat_model()
        runtime.emit_job_progress(target_job.job_id, stage="running", message="AI 正在按审稿清单审核手稿", progress=40)
        response = await intelligent_chat(
            IntelligentChatRequest(
                query=query,
                project_id=metadata.get("project_id"),
                tier=metadata.get("tier") or "thorough",
                mode="literature_qa",
                project_reasoning_bias_enabled=metadata.get("project_reasoning_bias_enabled"),
            )
        )
        runtime.emit_job_progress(target_job.job_id, stage="finalize", message="正在保存 AI 审稿报告", progress=90)
        return {
            "status": "completed",
            "kind": "ai_review",
            "response": response.response,
            "text": response.response,
            "review_model": review_model,
            "session_id": response.session_id,
            "tokens_used": response.tokens_used.model_dump(),
            "context_metadata": response.context_metadata.model_dump() if response.context_metadata else None,
            "evidence_refs": [item.model_dump() for item in response.evidence_refs or []],
        }

    return _executor


def _describe_current_chat_model() -> str:
    """Return the configured chat provider/model without exposing secrets."""
    try:
        from routers.intelligent_chat_router import _load_default_llm_config

        llm = _load_default_llm_config()
        provider = str(getattr(llm, "provider", "") or "").strip()
        model = str(getattr(llm, "model", "") or "").strip()
        if provider and model:
            return f"{provider} / {model}"
        if model:
            return model
        if provider:
            return provider
    except Exception as exc:  # pragma: no cover - display hint only
        logger.debug("Unable to describe current chat model: %s", exc)
    return "当前聊天模型"


@router.post("/session", response_model=SessionPayload)
async def create_session(request: CreateSessionRequest) -> SessionPayload:
    """Create a new writing session."""
    from writing_runtime import SessionMode
    runtime = get_runtime()
    try:
        mode = SessionMode(request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}") from exc
    
    session = runtime.create_session(
        mode=mode,
        user_id=request.user_id,
        settings=request.settings,
        tags=request.tags,
        metadata={
            **dict(request.metadata),
            **({"workspace_root": request.workspace_root} if request.workspace_root else {}),
            **({"entry_cwd": request.entry_cwd} if request.entry_cwd else {}),
            **({"title": request.title} if request.title else {}),
        },
    )
    return SessionPayload(**session.to_dict())


@router.get("/sessions", response_model=List[SessionPayload])
async def list_sessions(
    workspace_root: str | None = Query(default=None),
    workspace_key: str | None = Query(default=None),
) -> List[SessionPayload]:
    """List sessions scoped to a workspace binding."""
    runtime = get_runtime()
    resolved_workspace_key = workspace_key
    if resolved_workspace_key is None and workspace_root is not None:
        from writing_runtime import _stable_workspace_key
        from pathlib import Path

        resolved_workspace_key = _stable_workspace_key(Path(workspace_root).expanduser().resolve())
    sessions = runtime.list_sessions(workspace_key=resolved_workspace_key)
    return [SessionPayload(**session.to_dict()) for session in sessions]


@router.get("/session/current", response_model=SessionPayload)
async def get_current_session(
    workspace_root: str | None = Query(default=None),
    workspace_key: str | None = Query(default=None),
    entry_cwd: str | None = Query(default=None),
) -> SessionPayload:
    """Get the latest active session for the current workspace binding."""
    runtime = get_runtime()
    session = runtime.get_current_session(
        workspace_root=workspace_root,
        workspace_key=workspace_key,
        entry_cwd=entry_cwd,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="No current session found")
    return SessionPayload(**session.to_dict())


@router.get("/session/{session_id}", response_model=SessionPayload)
async def get_session(session_id: str) -> SessionPayload:
    """Get a session by ID."""
    runtime = get_runtime()
    session = runtime.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return SessionPayload(**session.to_dict())


@router.delete("/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    """Delete a persisted runtime session and its owned records."""
    runtime = get_runtime()
    try:
        deleted = runtime.delete_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"session_id": session_id, "deleted": True}


@router.post("/session/{session_id}/resume", response_model=ResumeSessionPayload)
async def resume_session(session_id: str) -> ResumeSessionPayload:
    """Resume a persisted session and return its current transcript head."""
    runtime = get_runtime()
    try:
        resumed = runtime.resume_session(session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ResumeSessionPayload(**resumed)


@router.get("/session/{session_id}/timeline", response_model=TimelinePagePayload)
async def get_session_timeline(
    session_id: str,
    after_event_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> TimelinePagePayload:
    """Fetch the active transcript lineage for a session."""
    runtime = get_runtime()
    session = runtime.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return TimelinePagePayload(**runtime.get_session_timeline(session_id, after_event_id=after_event_id, limit=limit))


@router.get("/session/{session_id}/checkpoints", response_model=List[CheckpointPayload])
async def list_checkpoints(session_id: str) -> List[CheckpointPayload]:
    """List rewind/fork checkpoints for a session."""
    runtime = get_runtime()
    session = runtime.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return [CheckpointPayload(**checkpoint) for checkpoint in runtime.list_checkpoints(session_id)]


@router.post("/session/{session_id}/rewind", response_model=ResumeSessionPayload)
async def rewind_session(session_id: str, request: RewindSessionRequest) -> ResumeSessionPayload:
    """Rewind a session back to a checkpoint."""
    runtime = get_runtime()
    try:
        rewound = runtime.rewind_session(session_id, request.checkpoint_id, mode=request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ResumeSessionPayload(**rewound)


@router.post("/session/{session_id}/fork", response_model=ResumeSessionPayload)
async def fork_session(session_id: str, request: ForkSessionRequest) -> ResumeSessionPayload:
    """Fork a new session branch from a checkpoint."""
    runtime = get_runtime()
    try:
        forked = runtime.fork_session(session_id, request.checkpoint_id, title=request.title)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ResumeSessionPayload(**forked)


@router.post("/job", response_model=JobPayload)
async def create_job(request: CreateJobRequest) -> JobPayload:
    """Create a new job in a session."""
    from writing_runtime import JobKind
    runtime = get_runtime()
    try:
        kind = JobKind(request.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid job kind: {request.kind}") from exc
    
    try:
        job = runtime.create_job(
            session_id=request.session_id,
            kind=kind,
            input_text=request.input_text,
            action_id=request.action_id,
            skill_id=request.skill_id,
            scope=request.scope,
            output_mode=request.output_mode,
            tags=request.tags,
            metadata=request.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    
    return JobPayload(**job.to_dict())


@router.get("/jobs", response_model=List[JobPayload])
async def list_jobs(
    session_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> List[JobPayload]:
    """List runtime jobs for the task center.

    Args:
        session_id: Optional session filter. When omitted, jobs across active
            runtime sessions are returned.
        status: Optional raw job status value.
        limit: Maximum number of newest jobs to return.

    Returns:
        Newest jobs first, serialized through the public job payload model.

    Raises:
        HTTPException: If ``status`` is not a known runtime job status.
    """
    from writing_runtime import JobStatus

    runtime = get_runtime()
    parsed_status = None
    if status is not None and status.strip():
        try:
            parsed_status = JobStatus(status.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid job status: {status}") from exc

    if session_id:
        if runtime.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        jobs = runtime.list_jobs(session_id=session_id, status=parsed_status)
    else:
        jobs = []
        for session in runtime.list_sessions(include_archived=True):
            jobs.extend(runtime.list_jobs(session_id=session.session_id, status=parsed_status))

    jobs.sort(key=lambda job: job.created_at, reverse=True)
    return [JobPayload(**job.to_dict()) for job in jobs[:limit]]


@router.get("/job/{job_id}", response_model=JobPayload)
async def get_job(job_id: str) -> JobPayload:
    """Get a job by ID."""
    runtime = get_runtime()
    job = runtime.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return JobPayload(**job.to_dict())


@router.delete("/job/{job_id}")
async def delete_job(job_id: str) -> dict[str, Any]:
    """Delete a job and clear its events, artifacts, approvals, and queue state."""
    runtime = get_runtime()
    try:
        deleted = runtime.delete_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return {"job_id": job_id, "deleted": True}


@router.get("/job/{job_id}/status", response_model=JobStatusPayload)
async def get_job_status(job_id: str) -> JobStatusPayload:
    """Get detailed job status."""
    runtime = get_runtime()
    job = runtime.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    status = runtime.query_job_status(job_id)
    return JobStatusPayload(**status)


@router.post("/job/{job_id}/start")
async def start_job(job_id: str) -> dict[str, Any]:
    """Start executing a job."""
    runtime = get_runtime()
    job = runtime.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    executor = _build_job_executor(job)
    try:
        await runtime.start_job(job_id, executor=executor)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    current_job = runtime.get_job(job_id) or job
    return {"job_id": current_job.job_id, "status": current_job.status.value}


@router.post("/job/{job_id}/pause")
async def pause_job(job_id: str) -> dict[str, Any]:
    """Pause a running job."""
    runtime = get_runtime()
    try:
        job = await runtime.pause_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job_id": job.job_id, "status": job.status.value}


@router.post("/job/{job_id}/resume")
async def resume_job(job_id: str) -> dict[str, Any]:
    """Resume a paused job."""
    runtime = get_runtime()
    try:
        job = await runtime.resume_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job_id": job.job_id, "status": job.status.value}


@router.post("/job/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel a job."""
    runtime = get_runtime()
    try:
        job = await runtime.cancel_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job_id": job.job_id, "status": job.status.value}


@router.get("/job/{job_id}/events", response_model=List[EventPayload])
async def get_job_events(
    job_id: str,
    since_timestamp: str | None = Query(default=None),
    after_event_id: str | None = Query(default=None),
    after_sequence: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> List[EventPayload]:
    """Get all events for a job, optionally filtered for polling."""
    runtime = get_runtime()
    job = runtime.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    events = runtime.get_job_events(
        job_id,
        since_timestamp=since_timestamp,
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return [EventPayload(**e.to_dict()) for e in events]


@router.get("/job/{job_id}/snapshot", response_model=JobEventSnapshotPayload)
async def get_job_event_snapshot(
    job_id: str,
    since_timestamp: str | None = Query(default=None),
    after_event_id: str | None = Query(default=None),
    after_sequence: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> JobEventSnapshotPayload:
    """Return current job state and one sequenced event page."""
    runtime = get_runtime()
    job = runtime.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    events = runtime.get_job_events(
        job_id,
        since_timestamp=since_timestamp,
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit + 1,
    )
    has_more = len(events) > limit
    page_events = events[:limit]
    next_after_sequence = page_events[-1].sequence if page_events else after_sequence
    status = runtime.query_job_status(job_id)

    return JobEventSnapshotPayload(
        job_id=job.job_id,
        session_id=job.session_id,
        job=JobPayload(**job.to_dict()),
        status=JobStatusPayload(**status),
        events=[EventPayload(**event.to_dict()) for event in page_events],
        next_after_sequence=next_after_sequence,
        latest_sequence=runtime.get_job_event_head_sequence(job_id),
        has_more=has_more,
    )


@router.get("/job/{job_id}/artifacts", response_model=List[ArtifactPayload])
async def get_job_artifacts(job_id: str) -> List[ArtifactPayload]:
    """Get all artifacts for a job."""
    runtime = get_runtime()
    job = runtime.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    artifacts = runtime.get_job_artifacts(job_id)
    return [ArtifactPayload(**a.to_dict()) for a in artifacts]
