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
            return await asyncio.to_thread(
                service.run_legacy_action,
                target_job.action_id,
                target_job.input_text,
                target_job.scope,
                target_job.output_mode,
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
    )
    return SessionPayload(**session.to_dict())


@router.get("/session/{session_id}", response_model=SessionPayload)
async def get_session(session_id: str) -> SessionPayload:
    """Get a session by ID."""
    runtime = get_runtime()
    session = runtime.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return SessionPayload(**session.to_dict())


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
    artifacts = runtime.get_job_artifacts(job_id)
    return [ArtifactPayload(**a.to_dict()) for a in artifacts]
