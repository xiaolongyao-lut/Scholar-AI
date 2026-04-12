# -*- coding: utf-8 -*-
"""Runtime API Router - Manages writing sessions, jobs, and execution control."""

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
    try:
        job = await runtime.start_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job.job_id, "status": job.status.value}


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
async def get_job_events(job_id: str) -> List[EventPayload]:
    """Get all events for a job."""
    runtime = get_runtime()
    events = runtime.get_job_events(job_id)
    return [EventPayload(**e.to_dict()) for e in events]


@router.get("/job/{job_id}/artifacts", response_model=List[ArtifactPayload])
async def get_job_artifacts(job_id: str) -> List[ArtifactPayload]:
    """Get all artifacts for a job."""
    runtime = get_runtime()
    artifacts = runtime.get_job_artifacts(job_id)
    return [ArtifactPayload(**a.to_dict()) for a in artifacts]
