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
    ArtifactPayload,
    TimelinePagePayload,
    CheckpointPayload,
    ResumeSessionPayload,
    RewindSessionRequest,
    ForkSessionRequest,
)

logger = logging.getLogger("RuntimeRouter")
router = APIRouter(prefix="/runtime", tags=["Runtime"])


def get_runtime():
    """Import and return the writing runtime service."""
    from writing_runtime import get_writing_runtime
    return get_writing_runtime()


def _build_job_executor(job):
    """Build an async executor for skill-backed jobs when references are available."""
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    
    return JobPayload(**job.to_dict())


@router.get("/job/{job_id}", response_model=JobPayload)
async def get_job(job_id: str) -> JobPayload:
    """Get a job by ID."""
    runtime = get_runtime()
    job = runtime.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return JobPayload(**job.to_dict())


@router.get("/job/{job_id}/status", response_model=JobStatusPayload)
async def get_job_status(job_id: str) -> JobStatusPayload:
    """Get detailed job status."""
    runtime = get_runtime()
    status = runtime.query_job_status(job_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
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
        limit=limit,
    )
    return [EventPayload(**e.to_dict()) for e in events]


@router.get("/job/{job_id}/artifacts", response_model=List[ArtifactPayload])
async def get_job_artifacts(job_id: str) -> List[ArtifactPayload]:
    """Get all artifacts for a job."""
    runtime = get_runtime()
    job = runtime.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    artifacts = runtime.get_job_artifacts(job_id)
    return [ArtifactPayload(**a.to_dict()) for a in artifacts]
