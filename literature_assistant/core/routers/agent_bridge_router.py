# -*- coding: utf-8 -*-
"""Agent bridge API backed by runtime sessions, jobs, events, and artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from datetime_utils import utc_now_iso_z
from harness_protocols import ArtifactType, JobKind, JobStatus
from models import ArtifactPayload, JobPayload, SessionPayload, ToolAttempt, ToolNextAction, ToolOutcome
from literature_assistant.core.academic_english_resources import read_academic_english_resource
from literature_assistant.core.config_knowledge import read_scoring_rules_resource
from literature_assistant.core.product_docs_knowledge import read_product_docs_resource
from literature_assistant.core.tolf_bridge_lexicon_store import read_bridge_lexicon_resource
from literature_assistant.core.source_vault import (
    SourceVault,
    build_source_vault_chunk_metadata,
    build_source_vault_chunk_read_endpoint,
    build_source_vault_chunk_ref_id,
    bounded_text,
)
from literature_assistant.core.skill_package_knowledge import read_skill_package_resource
from literature_assistant.core.project_paths import wiki_generated_root
from literature_assistant.core.wiki.page_store import AUTO_END, AUTO_START, WikiPageStore
from literature_assistant.core.wiki.source_registry import derive_chunk_id


router = APIRouter(prefix="/api/agent-bridge", tags=["Agent Bridge"])

MAX_USER_TEXT_CHARS = 8000
MAX_PROGRESS_MESSAGE_CHARS = 500
MAX_RESULT_TEXT_CHARS = 120000
MAX_RESOURCE_CHARS = 20000
DEFAULT_RESOURCE_CHARS = 6000
MAX_WIKI_CAPTURE_BODY_CHARS = 40000
SINGLE_PAPER_TASK_SCHEMA_VERSION = "scholar-ai-single-paper-task/v1"
SINGLE_PAPER_COMPLETION_SCHEMA_VERSION = "scholar-ai-single-paper-completion-check/v1"
SINGLE_PAPER_TASK_SENTINEL = "待补充"


class AgentResourceRef(BaseModel):
    """Small reference to context an agent can fetch through bounded readers."""

    ref_id: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=80)
    project_id: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=2000)
    read_endpoint: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentContextBudget(BaseModel):
    """Token-control envelope for external agent requests."""

    max_chars: int = Field(default=12000, ge=100, le=40000)
    max_chunks: int = Field(default=12, ge=1, le=50)
    include_full_text: bool = False


class AgentOutputTargets(BaseModel):
    """Where an agent result should be surfaced after completion."""

    runtime_job: bool = True
    smart_read_conversation: bool = False
    agent_workspace: bool = True
    wiki_candidate: bool = False
    graph_candidate: bool = False
    evolution_capture: bool = True


class AgentRequestEnvelope(BaseModel):
    """Request shape for work delegated to Codex, Claude, or another agent."""

    source: str = Field(default="mcp", min_length=1, max_length=80)
    agent_host: str = Field(default="unknown", min_length=1, max_length=80)
    intent: str = Field(min_length=1, max_length=120)
    user_text: str = Field(default="", max_length=MAX_USER_TEXT_CHARS)
    project_id: str | None = Field(default=None, max_length=200)
    runtime_session_id: str | None = Field(default=None, max_length=120)
    chat_session_id: str | None = Field(default=None, max_length=200)
    route: str | None = Field(default=None, max_length=300)
    resource_refs: list[AgentResourceRef] = Field(default_factory=list, max_length=50)
    context_budget: AgentContextBudget = Field(default_factory=AgentContextBudget)
    output_targets: AgentOutputTargets = Field(default_factory=AgentOutputTargets)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("user_text")
    @classmethod
    def _validate_user_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if len(text) > MAX_USER_TEXT_CHARS:
            raise ValueError("user_text exceeds max length")
        return text


class AgentProgressRequest(BaseModel):
    """Progress delta written by an external agent."""

    stage: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=MAX_PROGRESS_MESSAGE_CHARS)
    progress: int | None = Field(default=None, ge=0, le=100)
    data: dict[str, Any] = Field(default_factory=dict)


class AgentResultRequest(BaseModel):
    """Final result payload written by an external agent."""

    text: str = Field(default="", max_length=MAX_RESULT_TEXT_CHARS)
    content: dict[str, Any] | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    wiki_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    graph_patch_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def _validate_result_text(cls, value: str) -> str:
        text = str(value or "")
        if len(text) > MAX_RESULT_TEXT_CHARS:
            raise ValueError("text exceeds max length")
        return text


class AgentFailRequest(BaseModel):
    """Failure payload written by an external agent."""

    error: str = Field(min_length=1, max_length=2000)


class AgentBridgeRequestPayload(BaseModel):
    """Public response for one agent bridge request."""

    request_id: str
    session: SessionPayload
    job: JobPayload
    poll: dict[str, str]
    envelope: AgentRequestEnvelope


class AgentBridgeStatusPayload(BaseModel):
    """Agent bridge status visible to MCP and frontend clients."""

    enabled: bool = True
    pending_count: int = Field(ge=0)
    running_count: int = Field(ge=0)
    recent: list[JobPayload] = Field(default_factory=list)


class AgentBridgeResultPayload(BaseModel):
    """Response after an agent writes a terminal result."""

    request_id: str
    job: JobPayload
    artifacts: list[ArtifactPayload] = Field(default_factory=list)


class AgentBridgeResourcePayload(BaseModel):
    """Bounded resource payload returned to external agents."""

    ref_id: str
    kind: str
    project_id: str | None = None
    title: str | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    truncated: bool
    cursor: str | None = None
    next_cursor: str | None = None
    max_chars: int = Field(ge=100, le=MAX_RESOURCE_CHARS)
    total_chars: int = Field(ge=0)


class SinglePaperTaskRequest(BaseModel):
    """Request one dynamic single-paper reading task instance.

    Args:
        project_id: Existing Scholar AI project id.
        material_id: Existing material id that belongs to the project.
        task_goal: User-facing goal statement embedded in the generated task.
        output_language: Expected answer language for the external agent.
        target_document: Intended downstream deliverable.
        create_agent_request: Whether to create a runtime-visible agent job.
        agent_host: External agent host label used for audit metadata.
        source: Invocation source label used for runtime filtering.
        max_chars: Bounded resource-read budget for the task envelope.
        max_chunks: Maximum indexed chunks attached as resource refs.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=200)
    material_id: str = Field(min_length=1, max_length=200)
    task_goal: str = Field(
        default="生成单篇论文深度精读、写作借鉴要点、可导出 Word 的结构化草稿",
        min_length=1,
        max_length=500,
    )
    output_language: Literal["zh", "en", "bilingual"] = "zh"
    target_document: Literal["deep_summary", "word_draft"] = "word_draft"
    create_agent_request: bool = True
    agent_host: str = Field(default="mcp", min_length=1, max_length=80)
    source: str = Field(default="mcp", min_length=1, max_length=80)
    max_chars: int = Field(default=12000, ge=100, le=40000)
    max_chunks: int = Field(default=12, ge=1, le=50)

    @field_validator("project_id", "material_id", "task_goal", "agent_host", "source")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        """Normalize public string inputs before they become job metadata."""

        text = str(value or "").strip()
        if not text:
            raise ValueError("field must be non-empty")
        return text


class SinglePaperTaskPayload(BaseModel):
    """Generated single-paper task instance plus optional runtime job binding."""

    schema_version: Literal["scholar-ai-single-paper-task/v1"] = SINGLE_PAPER_TASK_SCHEMA_VERSION
    task_id: str
    generated_at: str
    sentinel: str = SINGLE_PAPER_TASK_SENTINEL
    project_id: str
    material_id: str
    task_markdown: str
    task_manifest: dict[str, Any]
    resource_refs: list[AgentResourceRef] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    health_checks: dict[str, Any] = Field(default_factory=dict)
    outcome: ToolOutcome
    agent_request: AgentBridgeRequestPayload | None = None
    task_artifact: ArtifactPayload | None = None


class SinglePaperCompletionCheckRequest(BaseModel):
    """Validate a completed single-paper deep-read draft against its task manifest.

    Args:
        output_text: Final Markdown/plain-text draft generated from the task.
        task_manifest: Manifest returned by ``single-paper-task``.
        required_output_sections: Optional override for manifest sections.
        evidence_refs: Evidence anchors used by the draft.
        figure_table_refs: Figure/table anchors used by the draft.
        lint_passed: Whether ``literature.academic_writing_lint`` has passed.
        docx_artifact_path: Optional local DOCX artifact path after export.
        sentinel: Placeholder token that must not remain in final output.
    """

    model_config = ConfigDict(extra="forbid")

    output_text: str = Field(min_length=1, max_length=MAX_RESULT_TEXT_CHARS)
    task_manifest: dict[str, Any]
    required_output_sections: list[str] | None = Field(default=None, max_length=30)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    figure_table_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    lint_passed: bool = False
    docx_artifact_path: str | None = Field(default=None, max_length=1000)
    sentinel: str = Field(default=SINGLE_PAPER_TASK_SENTINEL, min_length=1, max_length=40)

    @field_validator("output_text", "sentinel", "docx_artifact_path")
    @classmethod
    def _validate_completion_text(cls, value: str | None) -> str | None:
        """Trim bounded public text while preserving omitted optional fields."""

        if value is None:
            return None
        text = str(value or "").strip()
        if not text:
            raise ValueError("field must be non-empty")
        return text

    @field_validator("task_manifest")
    @classmethod
    def _validate_task_manifest(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Require a non-empty manifest object from the task-generation step."""

        if not isinstance(value, dict) or not value:
            raise ValueError("task_manifest must be a non-empty object")
        return dict(value)


class SinglePaperCompletionCheckPayload(BaseModel):
    """Machine-checkable completion report for a single-paper deep-read draft."""

    schema_version: Literal["scholar-ai-single-paper-completion-check/v1"] = (
        SINGLE_PAPER_COMPLETION_SCHEMA_VERSION
    )
    task_id: str | None = None
    sentinel: str = SINGLE_PAPER_TASK_SENTINEL
    completion_state: Literal["complete", "incomplete"]
    required_output_sections: list[str] = Field(default_factory=list)
    present_sections: list[str] = Field(default_factory=list)
    missing_sections: list[str] = Field(default_factory=list)
    sentinel_count: int = Field(ge=0)
    sentinel_contexts: list[str] = Field(default_factory=list)
    evidence_ref_count: int = Field(ge=0)
    figure_table_ref_count: int = Field(ge=0)
    lint_passed: bool
    docx_export_ready: bool
    outcome: ToolOutcome


def get_runtime():
    """Import and return the writing runtime service."""

    from writing_runtime import SessionMode, get_writing_runtime

    return get_writing_runtime(), SessionMode


def get_resource_store():
    """Import and return the writing resource store."""

    from writing_resources import get_writing_resource_store

    return get_writing_resource_store()


@router.get("/status", response_model=AgentBridgeStatusPayload)
async def get_agent_bridge_status(limit: int = Query(default=20, ge=1, le=100)) -> AgentBridgeStatusPayload:
    """Return a small runtime-backed agent bridge status."""

    runtime, _ = get_runtime()
    jobs = _agent_jobs(runtime, limit=limit)
    pending = [job for job in jobs if job.status in {JobStatus.CREATED, JobStatus.QUEUED, JobStatus.APPROVAL_PENDING}]
    running = [job for job in jobs if job.status in {JobStatus.STARTED, JobStatus.IN_PROGRESS, JobStatus.PAUSED}]
    return AgentBridgeStatusPayload(
        pending_count=len(pending),
        running_count=len(running),
        recent=[JobPayload(**job.to_dict()) for job in jobs],
    )


@router.post("/request", response_model=AgentBridgeRequestPayload)
async def create_agent_request(envelope: AgentRequestEnvelope) -> AgentBridgeRequestPayload:
    """Create a runtime-visible job for external agent work."""

    runtime, SessionMode = get_runtime()
    request_id = f"agentreq_{uuid4().hex[:16]}"
    session = None
    if envelope.runtime_session_id:
        session = runtime.get_session(envelope.runtime_session_id)
    if session is None:
        session = runtime.create_session(
            mode=SessionMode.PROMPT,
            tags=["agent_bridge"],
            metadata={
                "title": _request_title(envelope),
                "source": "agent_bridge",
                "agent_request_id": request_id,
                "agent_host": envelope.agent_host,
                "intent": envelope.intent,
                **({"project_id": envelope.project_id} if envelope.project_id else {}),
                **({"route": envelope.route} if envelope.route else {}),
            },
        )
    metadata = _agent_job_metadata(request_id, envelope)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text=envelope.user_text,
        tags=["agent_bridge", envelope.source, envelope.agent_host],
        metadata=metadata,
    )
    await runtime.start_job(job.job_id)
    runtime.emit_job_progress(
        job.job_id,
        stage="queued",
        message="智能体任务已创建，等待外部智能体处理",
        progress=5,
        data={"request_id": request_id, "intent": envelope.intent},
    )
    current_job = runtime.get_job(job.job_id) or job
    return AgentBridgeRequestPayload(
        request_id=request_id,
        session=SessionPayload(**session.to_dict()),
        job=JobPayload(**current_job.to_dict()),
        poll={
            "job": f"/runtime/job/{job.job_id}",
            "snapshot": f"/runtime/job/{job.job_id}/snapshot",
            "artifacts": f"/runtime/job/{job.job_id}/artifacts",
        },
        envelope=envelope,
    )


@router.post("/single-paper-task", response_model=SinglePaperTaskPayload)
async def create_single_paper_task(request: SinglePaperTaskRequest) -> SinglePaperTaskPayload:
    """Create a Scholar AI dynamic task instance for one paper.

    Args:
        request: Task-generation request. It must target a real project material.

    Returns:
        A Markdown task, machine-readable manifest, resource refs, outcome, and
        optional runtime agent request. This route never creates external skill
        packages or external uploads.
    """

    payload = _build_single_paper_task_payload(request)
    if not request.create_agent_request:
        return payload

    envelope = AgentRequestEnvelope(
        source=request.source,
        agent_host=request.agent_host,
        intent="single_paper_deep_read",
        user_text=payload.task_markdown,
        project_id=request.project_id,
        resource_refs=payload.resource_refs,
        context_budget=AgentContextBudget(
            max_chars=request.max_chars,
            max_chunks=request.max_chunks,
            include_full_text=False,
        ),
        output_targets=AgentOutputTargets(
            runtime_job=True,
            smart_read_conversation=False,
            agent_workspace=True,
            wiki_candidate=False,
            graph_candidate=False,
            evolution_capture=True,
        ),
        metadata={
            "task_id": payload.task_id,
            "task_schema_version": payload.schema_version,
            "task_title": str(payload.task_manifest.get("paper", {}).get("title") or "single paper"),
            "task_manifest": payload.task_manifest,
            "missing_fields": list(payload.missing_fields),
            "sentinel": payload.sentinel,
        },
    )
    agent_request = await create_agent_request(envelope)
    runtime, _ = get_runtime()
    artifact = runtime.add_job_artifact(
        agent_request.job.job_id,
        artifact_type=ArtifactType.METADATA,
        content=payload.task_markdown,
        created_by="agent_bridge",
        metadata={
            "kind": "single_paper_task_markdown",
            "task_id": payload.task_id,
            "schema_version": payload.schema_version,
            "project_id": request.project_id,
            "material_id": request.material_id,
            "sentinel": payload.sentinel,
        },
        mime_type="text/markdown",
    )
    return payload.model_copy(
        update={
            "agent_request": agent_request,
            "task_artifact": ArtifactPayload(**artifact.to_dict()),
            "outcome": _single_paper_outcome(
                manifest=payload.task_manifest,
                missing_fields=payload.missing_fields,
                chunk_count=int(payload.health_checks.get("indexed_chunk_count") or 0),
                request_created=True,
                request_id=agent_request.request_id,
            ),
        }
    )


@router.post("/single-paper-task/completion-check", response_model=SinglePaperCompletionCheckPayload)
def check_single_paper_completion(
    request: SinglePaperCompletionCheckRequest,
) -> SinglePaperCompletionCheckPayload:
    """Validate a generated single-paper deep-read draft without external calls.

    Args:
        request: Completed draft text and the manifest from task generation.

    Returns:
        A deterministic completion report with a ToolOutcome next action.
    """

    return _single_paper_completion_check(request)


@router.get("/requests", response_model=list[JobPayload])
async def list_agent_requests(
    status: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[JobPayload]:
    """List runtime jobs created through the agent bridge."""

    runtime, _ = get_runtime()
    parsed_status = _parse_status(status)
    jobs = _agent_jobs(runtime, limit=limit * 2)
    if parsed_status is not None:
        jobs = [job for job in jobs if job.status == parsed_status]
    if project_id:
        jobs = [job for job in jobs if str(job.metadata.get("project_id") or "") == project_id]
    if source:
        jobs = [
            job
            for job in jobs
            if source in {str(job.metadata.get("source") or ""), str(job.metadata.get("agent_source") or "")}
        ]
    return [JobPayload(**job.to_dict()) for job in jobs[:limit]]


@router.get("/request/{request_id}", response_model=JobPayload)
async def get_agent_request(request_id: str) -> JobPayload:
    """Return the runtime job linked to an agent request id."""

    runtime, _ = get_runtime()
    job = _find_request_job(runtime, request_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Agent request not found: {request_id}")
    return JobPayload(**job.to_dict())


@router.get("/resource/{ref_id:path}", response_model=AgentBridgeResourcePayload)
async def read_agent_resource(
    ref_id: str,
    project_id: str | None = Query(default=None, max_length=200),
    max_chars: int = Query(default=DEFAULT_RESOURCE_CHARS, ge=100, le=MAX_RESOURCE_CHARS),
    cursor: str | None = Query(default=None, max_length=80),
) -> AgentBridgeResourcePayload:
    """Resolve a stable resource ref into a hard-bounded text payload."""

    normalized_ref = _require_ref_id(ref_id)
    offset = _parse_cursor(cursor)
    kind, raw_id = _split_ref_id(normalized_ref)
    resource = _resolve_resource(kind, raw_id, project_id=project_id)
    text = resource["content"]
    total = len(text)
    chunk = text[offset : offset + max_chars]
    next_offset = offset + len(chunk)
    truncated = next_offset < total
    return AgentBridgeResourcePayload(
        ref_id=normalized_ref,
        kind=kind,
        project_id=resource.get("project_id"),
        title=resource.get("title"),
        content=chunk,
        metadata={
            **dict(resource.get("metadata") or {}),
            "offset": offset,
            "returned_chars": len(chunk),
        },
        truncated=truncated,
        cursor=str(offset),
        next_cursor=str(next_offset) if truncated else None,
        max_chars=max_chars,
        total_chars=total,
    )


@router.post("/request/{request_id}/progress", response_model=JobPayload)
async def write_agent_progress(request_id: str, request: AgentProgressRequest) -> JobPayload:
    """Write a progress event into the linked runtime job."""

    runtime, _ = get_runtime()
    job = _require_request_job(runtime, request_id)
    runtime.emit_job_progress(
        job.job_id,
        stage=request.stage,
        message=request.message,
        progress=request.progress,
        data={"request_id": request_id, **dict(request.data)},
    )
    current_job = runtime.get_job(job.job_id) or job
    return JobPayload(**current_job.to_dict())


@router.post("/request/{request_id}/result", response_model=AgentBridgeResultPayload)
async def write_agent_result(request_id: str, request: AgentResultRequest) -> AgentBridgeResultPayload:
    """Store final agent output as runtime artifacts and complete the job."""

    runtime, _ = get_runtime()
    job = _require_request_job(runtime, request_id)
    if not request.text and not request.content:
        raise HTTPException(status_code=400, detail="result text or content is required")
    content: dict[str, Any] = request.content or {"text": request.text}
    content.setdefault("text", request.text)
    content.setdefault("kind", "agent_result")
    content.setdefault("request_id", request_id)
    content.setdefault("evidence_refs", request.evidence_refs)
    content.setdefault("wiki_refs", request.wiki_refs)
    content.setdefault("graph_patch_refs", request.graph_patch_refs)
    content.setdefault("metadata", request.metadata)
    routing_metadata = _agent_result_metadata(request_id, job, request, content)
    runtime.update_job_metadata(job.job_id, routing_metadata)
    await runtime.complete_job(job.job_id, result=content, artifact_metadata=routing_metadata)
    consumer_metadata = _consume_agent_result(request_id, runtime, job.job_id, routing_metadata, content)
    if consumer_metadata:
        runtime.update_job_metadata(job.job_id, {"knowledge_consumers": consumer_metadata})
    try:
        runtime.build_agent_handoff_card(job.job_id, persist=True)
    except ValueError:
        logger.exception("Failed to persist agent handoff card for request %s", request_id)
    current_job = runtime.get_job(job.job_id) or job
    artifacts = runtime.get_job_artifacts(job.job_id)
    return AgentBridgeResultPayload(
        request_id=request_id,
        job=JobPayload(**current_job.to_dict()),
        artifacts=[ArtifactPayload(**artifact.to_dict()) for artifact in artifacts],
    )


@router.post("/request/{request_id}/fail", response_model=JobPayload)
async def fail_agent_request(request_id: str, request: AgentFailRequest) -> JobPayload:
    """Mark a linked runtime job as failed."""

    runtime, _ = get_runtime()
    job = _require_request_job(runtime, request_id)
    failed = await runtime.fail_job(job.job_id, request.error)
    try:
        runtime.build_agent_handoff_card(job.job_id, persist=True)
    except ValueError:
        logger.exception("Failed to persist failed-agent handoff card for request %s", request_id)
    failed = runtime.get_job(job.job_id) or failed
    return JobPayload(**failed.to_dict())


def _request_title(envelope: AgentRequestEnvelope) -> str:
    metadata = envelope.metadata if isinstance(envelope.metadata, dict) else {}
    task_title = str(metadata.get("task_title") or "").strip()
    if envelope.intent == "single_paper_deep_read" and task_title:
        return f"单篇精读: {task_title[:40]}"
    intent = envelope.intent.strip() or "agent_request"
    if envelope.user_text:
        return f"智能体任务: {envelope.user_text[:40]}"
    return f"智能体任务: {intent}"


def _agent_job_metadata(request_id: str, envelope: AgentRequestEnvelope) -> dict[str, Any]:
    return {
        "source": envelope.source,
        "agent_bridge": True,
        "agent_request_id": request_id,
        "agent_host": envelope.agent_host,
        "intent": envelope.intent,
        "chat_session_id": envelope.chat_session_id,
        "project_id": envelope.project_id,
        "route": envelope.route,
        "resource_refs": [item.model_dump(mode="json") for item in envelope.resource_refs],
        "context_budget": envelope.context_budget.model_dump(mode="json"),
        "output_targets": envelope.output_targets.model_dump(mode="json"),
        "metadata": envelope.metadata,
    }


def _build_single_paper_task_payload(request: SinglePaperTaskRequest) -> SinglePaperTaskPayload:
    """Build a dynamic single-paper task from current project evidence.

    Args:
        request: Validated generation request.

    Returns:
        A bounded task payload with resource refs and explicit missing fields.

    Raises:
        HTTPException: If the project/material pair does not exist or is invalid.
    """

    project, material = _single_paper_project_material(request.project_id, request.material_id)
    chunks = _single_paper_chunks(
        project_id=request.project_id,
        material_id=request.material_id,
        limit=request.max_chunks,
    )
    generated_at = utc_now_iso_z()
    task_id = f"paper_task_{uuid4().hex[:16]}"
    metadata = dict(getattr(material, "metadata", {}) or {})
    source_label = _single_paper_source_label(metadata=metadata, chunks=chunks)
    resource_refs = _single_paper_resource_refs(
        request=request,
        material=material,
        chunks=chunks,
    )
    missing_fields = _single_paper_missing_fields(
        request=request,
        metadata=metadata,
        source_label=source_label,
        chunk_count=len(chunks),
    )
    health_checks = {
        "project_exists": True,
        "material_exists": True,
        "material_belongs_to_project": True,
        "indexed_chunk_count": len(chunks),
        "full_text_status": "ready" if chunks else SINGLE_PAPER_TASK_SENTINEL,
        "attachment_or_source": source_label or SINGLE_PAPER_TASK_SENTINEL,
        "doi_present": bool(_metadata_text(metadata, ("doi", "DOI"))),
    }
    manifest = _single_paper_manifest(
        task_id=task_id,
        generated_at=generated_at,
        request=request,
        project=project,
        material=material,
        metadata=metadata,
        source_label=source_label,
        chunks=chunks,
        resource_refs=resource_refs,
        missing_fields=missing_fields,
        health_checks=health_checks,
    )
    task_markdown = _single_paper_task_markdown(manifest)
    return SinglePaperTaskPayload(
        task_id=task_id,
        generated_at=generated_at,
        project_id=request.project_id,
        material_id=request.material_id,
        task_markdown=task_markdown,
        task_manifest=manifest,
        resource_refs=resource_refs,
        missing_fields=missing_fields,
        health_checks=health_checks,
        outcome=_single_paper_outcome(
            manifest=manifest,
            missing_fields=missing_fields,
            chunk_count=len(chunks),
            request_created=False,
            request_id=None,
        ),
    )


def _single_paper_project_material(project_id: str, material_id: str) -> tuple[Any, Any]:
    """Return a project/material pair after ownership validation."""

    store = get_resource_store()
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    material = store.get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail=f"Material not found: {material_id}")
    if str(getattr(material, "project_id", "") or "") != project_id:
        raise HTTPException(status_code=400, detail="material does not belong to project")
    return project, material


def _single_paper_chunks(*, project_id: str, material_id: str, limit: int) -> list[dict[str, Any]]:
    """Return bounded indexed chunks for one material without reading raw files."""

    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")
    try:
        import routers.resources_router as resources_router

        chunk_store = resources_router._load_chunk_store(project_id)
    except (ImportError, AttributeError, OSError, ValueError):
        return []
    raw_chunks = chunk_store.get(material_id, [])
    if not isinstance(raw_chunks, list):
        return []
    chunks: list[dict[str, Any]] = []
    for raw_chunk in raw_chunks:
        if not isinstance(raw_chunk, dict):
            continue
        chunk_id = str(raw_chunk.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        chunks.append(dict(raw_chunk))
        if len(chunks) >= limit:
            break
    return chunks


def _single_paper_resource_refs(
    *,
    request: SinglePaperTaskRequest,
    material: Any,
    chunks: list[dict[str, Any]],
) -> list[AgentResourceRef]:
    """Build bounded refs that an external agent can fetch on demand."""

    refs = [
        AgentResourceRef(
            ref_id=f"material:{request.material_id}",
            kind="material",
            project_id=request.project_id,
            title=str(getattr(material, "title", "") or request.material_id)[:500],
            summary=_material_summary(material),
            read_endpoint=f"/api/agent-bridge/resource/material:{request.material_id}",
        )
    ]
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        refs.append(
            AgentResourceRef(
                ref_id=f"chunk:{chunk_id}",
                kind="chunk",
                project_id=request.project_id,
                title=str(chunk.get("title") or getattr(material, "title", "") or request.material_id)[:500],
                summary=_bounded_inline_text(
                    str(chunk.get("summary") or chunk.get("content") or ""),
                    limit=300,
                ),
                read_endpoint=f"/api/agent-bridge/resource/chunk:{chunk_id}?project_id={request.project_id}",
                metadata={
                    key: chunk[key]
                    for key in ("material_id", "page", "chunk_index", "chunk_type", "source_relative_path")
                    if chunk.get(key) is not None
                },
            )
        )
    return refs


def _single_paper_manifest(
    *,
    task_id: str,
    generated_at: str,
    request: SinglePaperTaskRequest,
    project: Any,
    material: Any,
    metadata: dict[str, Any],
    source_label: str | None,
    chunks: list[dict[str, Any]],
    resource_refs: list[AgentResourceRef],
    missing_fields: list[str],
    health_checks: dict[str, Any],
) -> dict[str, Any]:
    """Return a JSON-safe task manifest that mirrors the Markdown task."""

    paper_title = str(getattr(material, "title", "") or request.material_id).strip()
    authors = _metadata_authors(metadata)
    doi = _metadata_text(metadata, ("doi", "DOI"))
    publication = _metadata_text(metadata, ("journal", "publicationTitle", "venue", "container-title"))
    publication_date = _metadata_text(metadata, ("publication_date", "date", "year"))
    return {
        "schema_version": SINGLE_PAPER_TASK_SCHEMA_VERSION,
        "task_id": task_id,
        "generated_at": generated_at,
        "sentinel": SINGLE_PAPER_TASK_SENTINEL,
        "task_goal": request.task_goal,
        "output_language": request.output_language,
        "target_document": request.target_document,
        "project": {
            "project_id": request.project_id,
            "title": str(getattr(project, "title", "") or request.project_id),
        },
        "paper": {
            "material_id": request.material_id,
            "title": paper_title or SINGLE_PAPER_TASK_SENTINEL,
            "authors": authors or [SINGLE_PAPER_TASK_SENTINEL],
            "doi": doi or SINGLE_PAPER_TASK_SENTINEL,
            "publication": publication or SINGLE_PAPER_TASK_SENTINEL,
            "publication_date": publication_date or SINGLE_PAPER_TASK_SENTINEL,
            "attachment_or_source": source_label or SINGLE_PAPER_TASK_SENTINEL,
            "indexed_chunk_count": len(chunks),
        },
        "resource_refs": [ref.model_dump(mode="json") for ref in resource_refs],
        "missing_fields": list(missing_fields),
        "health_checks": dict(health_checks),
        "required_output_sections": [
            "论文元数据与附件健康检查",
            "研究问题、动机、核心贡献",
            "方法与实验设计拆解",
            "关键图表/表格候选与写作价值",
            "可借鉴写法：引言、方法、实验、图表说明",
            "局限性、可复现实验线索、可迁移到本项目的写作模板",
            "Word 草稿结构与导出准备",
        ],
    }


def _single_paper_task_markdown(manifest: dict[str, Any]) -> str:
    """Render the dynamic task as Markdown for an external agent job."""

    paper = dict(manifest.get("paper") or {})
    project = dict(manifest.get("project") or {})
    resource_refs = [
        item
        for item in manifest.get("resource_refs", [])
        if isinstance(item, dict)
    ]
    missing_fields = [str(item) for item in manifest.get("missing_fields", [])]
    output_sections = [str(item) for item in manifest.get("required_output_sections", [])]
    resource_lines = [
        f"- `{ref.get('ref_id')}` ({ref.get('kind')}): {ref.get('read_endpoint') or SINGLE_PAPER_TASK_SENTINEL}"
        for ref in resource_refs[:30]
    ]
    missing_lines = [f"- {item}: {SINGLE_PAPER_TASK_SENTINEL}" for item in missing_fields] or [
        f"- 无显式缺失字段: {SINGLE_PAPER_TASK_SENTINEL} 不应出现在最终交付中"
    ]
    section_lines = [f"{index}. {title}" for index, title in enumerate(output_sections, start=1)]
    return "\n".join(
        [
            "# Scholar AI 单篇论文深度精读任务",
            "",
            "## 任务边界",
            f"- Task ID: `{manifest['task_id']}`",
            f"- Generated at: `{manifest['generated_at']}`",
            f"- Project: `{project.get('project_id')}` / {project.get('title')}",
            f"- Material: `{paper.get('material_id')}`",
            f"- Goal: {manifest.get('task_goal')}",
            f"- Output language: `{manifest.get('output_language')}`",
            f"- Target document: `{manifest.get('target_document')}`",
            "",
            "## 论文线索",
            f"- Title: {paper.get('title')}",
            f"- Authors: {', '.join(str(item) for item in paper.get('authors', []))}",
            f"- DOI: {paper.get('doi')}",
            f"- Publication: {paper.get('publication')}",
            f"- Publication date: {paper.get('publication_date')}",
            f"- Attachment/source: {paper.get('attachment_or_source')}",
            f"- Indexed chunks: {paper.get('indexed_chunk_count')}",
            "",
            "## 可读取资源",
            *(resource_lines or [f"- {SINGLE_PAPER_TASK_SENTINEL}: 当前没有可读取资源，请先扫描项目文件夹。"]),
            "",
            "## 缺失字段哨兵",
            *missing_lines,
            "",
            "## 执行步骤",
            "1. 先用 `literature.agent_resource_read` 读取 material ref；chunk refs 只按需分批读取。",
            "2. 如果 indexed chunks 为 0，先调用 `literature.project_scan_folder`，不要凭标题臆造全文内容。",
            "3. 用 `literature.evidence_pack_build` 针对研究问题、方法、实验、图表写法分别取证。",
            "4. 用 `literature.figures_candidates` / `literature.figures_generate` 只挑能支撑正文论点的图表。",
            "5. 产出单篇深度总结，所有未知项必须保留 `待补充`，不得静默省略。",
            "6. Word 前先跑 `literature.academic_writing_lint`；需要 Word 时再调用 `literature.export_docx`。",
            "7. 只产出 Scholar AI 本地任务、草稿、证据与导出准备，不创建外部 agent skill 包，也不执行外部上传。",
            "",
            "## 必交付结构",
            *section_lines,
            "",
            "## 写作约束",
            "- 引言写法要提炼问题铺垫、研究空白、贡献递进三段。",
            "- 方法写法要提炼变量、对照组、评价指标、可复现实验条件。",
            "- 实验写法要区分观察事实、作者解释、你可借鉴的表述模式。",
            "- 图表写法要说明每张图/表承担的论证功能，而不是只复述标题。",
            "- 所有引用必须落到 resource ref、page/chunk、figure/table candidate 或明确 `待补充`。",
        ]
    )


def _single_paper_missing_fields(
    *,
    request: SinglePaperTaskRequest,
    metadata: dict[str, Any],
    source_label: str | None,
    chunk_count: int,
) -> list[str]:
    """Return explicit missing-field names for sentinel-driven completion."""

    missing: list[str] = []
    if not _metadata_text(metadata, ("doi", "DOI")):
        missing.append("paper.doi")
    if not _metadata_authors(metadata):
        missing.append("paper.authors")
    if not source_label:
        missing.append("paper.attachment_or_source")
    if chunk_count <= 0:
        missing.append("paper.indexed_chunks")
    return missing


def _single_paper_source_label(*, metadata: dict[str, Any], chunks: list[dict[str, Any]]) -> str | None:
    """Return a non-secret attachment/source label for task context."""

    direct = _metadata_text(
        metadata,
        (
            "source_relative_path",
            "source_path",
            "attachment_path",
            "pdf_path",
            "path",
            "filename",
            "file",
        ),
    )
    if direct:
        return _safe_path_label(direct)
    for chunk in chunks:
        source_relative_path = str(chunk.get("source_relative_path") or "").strip()
        if source_relative_path:
            return _safe_path_label(source_relative_path)
    return None


def _single_paper_outcome(
    *,
    manifest: dict[str, Any],
    missing_fields: list[str],
    chunk_count: int,
    request_created: bool,
    request_id: str | None,
) -> ToolOutcome:
    """Return an actionable outcome for task creation."""

    attempts = [
        ToolAttempt(
            stage="material_lookup",
            status="success",
            reason="Project material exists and belongs to the selected project.",
            metadata={
                "project_id": manifest.get("project", {}).get("project_id"),
                "material_id": manifest.get("paper", {}).get("material_id"),
            },
        ),
        ToolAttempt(
            stage="indexed_full_text_check",
            status="success" if chunk_count > 0 else "blocked",
            reason=(
                "Indexed chunks are available for bounded reading."
                if chunk_count > 0
                else "No indexed chunks were found for this paper."
            ),
            error_class="" if chunk_count > 0 else "ingest_needed",
            recommendation="" if chunk_count > 0 else "Run literature.project_scan_folder after adding the paper PDF/full text.",
            metadata={"indexed_chunk_count": chunk_count},
        ),
        ToolAttempt(
            stage="sentinel_check",
            status="success" if not missing_fields else "degraded",
            reason=(
                "No explicit missing fields were detected."
                if not missing_fields
                else "Missing fields are exposed with the 待补充 sentinel."
            ),
            metadata={"missing_fields": list(missing_fields)},
        ),
        ToolAttempt(
            stage="agent_request",
            status="success" if request_created else "skipped",
            reason=(
                "Runtime-visible agent request was created."
                if request_created
                else "Task markdown was generated without creating a runtime job."
            ),
            metadata={"request_id": request_id},
        ),
    ]
    if chunk_count <= 0:
        next_action = ToolNextAction(
            kind="scan_folder",
            message="No indexed chunks were found; scan the project source folder after adding the PDF/full text.",
            tool_name="literature.project_scan_folder",
            args={"project_id": manifest.get("project", {}).get("project_id")},
        )
        status = "blocked"
        quality = "metadata_only"
        reason = "Task generated, but full-text reading is blocked until the paper is indexed."
    elif request_created and request_id:
        next_action = ToolNextAction(
            kind="call_tool",
            message="Poll the runtime-visible agent request in Agent Workspace.",
            tool_name="literature.agent_request_read",
            args={"request_id": request_id},
        )
        status = "partial" if missing_fields else "success"
        quality = "partial" if missing_fields else "full"
        reason = "Task generated and queued as a runtime-visible agent request."
    else:
        next_action = ToolNextAction(
            kind="call_tool",
            message="Create an agent request from the generated task markdown when ready.",
            tool_name="literature.agent_request_create",
            args={"intent": "single_paper_deep_read"},
        )
        status = "partial" if missing_fields else "success"
        quality = "partial" if missing_fields else "full"
        reason = "Task markdown generated; no runtime agent request was created."
    return ToolOutcome(
        status=status,
        quality=quality,
        reason=reason,
        next_action=next_action,
        attempts=attempts,
    )


def _single_paper_completion_check(
    request: SinglePaperCompletionCheckRequest,
) -> SinglePaperCompletionCheckPayload:
    """Return deterministic completion diagnostics for a single-paper draft."""

    manifest = dict(request.task_manifest)
    task_id = str(manifest.get("task_id") or "").strip() or None
    required_sections = _single_paper_required_sections(
        manifest=manifest,
        override=request.required_output_sections,
    )
    present_sections = _single_paper_present_sections(
        output_text=request.output_text,
        required_sections=required_sections,
    )
    missing_sections = [section for section in required_sections if section not in present_sections]
    sentinel_count = request.output_text.count(request.sentinel)
    evidence_ref_count = _single_paper_count_refs(request.evidence_refs)
    figure_table_ref_count = _single_paper_count_refs(request.figure_table_refs)
    target_document = str(manifest.get("target_document") or "").strip()
    docx_export_ready = bool(request.docx_artifact_path)
    outcome = _single_paper_completion_outcome(
        manifest=manifest,
        missing_sections=missing_sections,
        sentinel_count=sentinel_count,
        evidence_ref_count=evidence_ref_count,
        figure_table_ref_count=figure_table_ref_count,
        lint_passed=request.lint_passed,
        target_document=target_document,
        docx_export_ready=docx_export_ready,
    )
    complete = (
        not missing_sections
        and sentinel_count == 0
        and evidence_ref_count > 0
        and request.lint_passed
    )
    return SinglePaperCompletionCheckPayload(
        task_id=task_id,
        sentinel=request.sentinel,
        completion_state="complete" if complete else "incomplete",
        required_output_sections=required_sections,
        present_sections=present_sections,
        missing_sections=missing_sections,
        sentinel_count=sentinel_count,
        sentinel_contexts=_single_paper_sentinel_contexts(request.output_text, request.sentinel),
        evidence_ref_count=evidence_ref_count,
        figure_table_ref_count=figure_table_ref_count,
        lint_passed=request.lint_passed,
        docx_export_ready=docx_export_ready,
        outcome=outcome,
    )


def _single_paper_required_sections(
    *,
    manifest: dict[str, Any],
    override: list[str] | None,
) -> list[str]:
    """Return bounded, de-duplicated required output sections."""

    raw_sections = override if override is not None else manifest.get("required_output_sections", [])
    if not isinstance(raw_sections, list):
        raise ValueError("required_output_sections must be a list")
    sections: list[str] = []
    seen: set[str] = set()
    for raw_section in raw_sections:
        section = _bounded_inline_text(str(raw_section or ""), limit=160)
        if not section:
            continue
        normalized = _single_paper_normalize_heading(section)
        if normalized in seen:
            continue
        seen.add(normalized)
        sections.append(section)
        if len(sections) >= 30:
            break
    if not sections:
        raise ValueError("at least one required output section is required")
    return sections


def _single_paper_present_sections(
    *,
    output_text: str,
    required_sections: list[str],
) -> list[str]:
    """Return required sections found as Markdown headings or numbered labels."""

    required_by_norm = {
        _single_paper_normalize_heading(section): section
        for section in required_sections
    }
    present: list[str] = []
    seen: set[str] = set()
    for line in output_text.splitlines():
        candidate = _single_paper_heading_candidate(line)
        if not candidate:
            continue
        normalized = _single_paper_normalize_heading(candidate)
        for required_norm, section in required_by_norm.items():
            if required_norm in seen:
                continue
            if normalized == required_norm or normalized.startswith(required_norm):
                seen.add(required_norm)
                present.append(section)
                break
    return present


def _single_paper_heading_candidate(line: str) -> str | None:
    """Return a possible section title from common Markdown/list line shapes."""

    text = str(line or "").strip()
    if not text:
        return None
    match = re.match(r"^(?:#{1,6}\s+|\d+[.)、]\s+|[-*]\s+)(?P<title>.+?)\s*$", text)
    if not match:
        return None
    title = match.group("title").strip().strip("#").strip()
    title = re.sub(r"^`+|`+$", "", title).strip()
    title = re.sub(r"^\*\*|\*\*$", "", title).strip()
    return title or None


def _single_paper_normalize_heading(value: str) -> str:
    """Normalize section headings without losing Chinese title text."""

    text = re.sub(r"\s+", "", str(value or "").strip().lower())
    text = re.sub(r"^[`*_#]+|[`*_#]+$", "", text)
    text = re.sub(r"[:：。.;；]+$", "", text)
    return text


def _single_paper_count_refs(refs: list[dict[str, Any]]) -> int:
    """Count bounded ref objects that contain a usable identifier or title."""

    count = 0
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if str(ref.get("ref_id") or ref.get("id") or ref.get("title") or "").strip():
            count += 1
    return count


def _single_paper_sentinel_contexts(output_text: str, sentinel: str) -> list[str]:
    """Return short lines that still contain the completion sentinel."""

    contexts: list[str] = []
    for line in output_text.splitlines():
        if sentinel not in line:
            continue
        contexts.append(_bounded_inline_text(line, limit=240))
        if len(contexts) >= 10:
            break
    return contexts


def _single_paper_completion_outcome(
    *,
    manifest: dict[str, Any],
    missing_sections: list[str],
    sentinel_count: int,
    evidence_ref_count: int,
    figure_table_ref_count: int,
    lint_passed: bool,
    target_document: str,
    docx_export_ready: bool,
) -> ToolOutcome:
    """Return an actionable outcome for draft-completion validation."""

    project_id = str(dict(manifest.get("project") or {}).get("project_id") or "").strip()
    attempts = [
        ToolAttempt(
            stage="required_sections_check",
            status="blocked" if missing_sections else "success",
            reason=(
                "Required output sections are present."
                if not missing_sections
                else "Required output sections are missing."
            ),
            error_class="missing_required_sections" if missing_sections else "",
            recommendation=(
                "Revise the draft to add every missing section title."
                if missing_sections
                else ""
            ),
            metadata={"missing_sections": list(missing_sections)},
        ),
        ToolAttempt(
            stage="sentinel_check",
            status="degraded" if sentinel_count else "success",
            reason=(
                "No completion sentinel remains in the draft."
                if sentinel_count == 0
                else "The draft still contains 待补充 placeholders."
            ),
            error_class="sentinel_remaining" if sentinel_count else "",
            recommendation=(
                "Resolve each 待补充 placeholder with evidence or keep the draft marked incomplete."
                if sentinel_count
                else ""
            ),
            metadata={"sentinel_count": sentinel_count},
        ),
        ToolAttempt(
            stage="evidence_refs_check",
            status="success" if evidence_ref_count > 0 else "degraded",
            reason=(
                "Evidence refs were supplied for the draft."
                if evidence_ref_count > 0
                else "No evidence refs were supplied for the draft."
            ),
            error_class="" if evidence_ref_count > 0 else "evidence_refs_missing",
            recommendation=(
                "Run literature.evidence_pack_build and attach refs before final export."
                if evidence_ref_count == 0
                else ""
            ),
            metadata={"evidence_ref_count": evidence_ref_count},
        ),
        ToolAttempt(
            stage="figure_table_refs_check",
            status="success" if figure_table_ref_count > 0 else "skipped",
            reason=(
                "Figure/table refs were supplied."
                if figure_table_ref_count > 0
                else "No figure/table refs were supplied; this is acceptable only when the paper has no useful figure/table candidate."
            ),
            metadata={"figure_table_ref_count": figure_table_ref_count},
        ),
        ToolAttempt(
            stage="academic_writing_lint_check",
            status="success" if lint_passed else "skipped",
            reason=(
                "Academic writing lint was marked as passed."
                if lint_passed
                else "Academic writing lint has not been marked as passed."
            ),
            error_class="" if lint_passed else "lint_not_run",
            recommendation=(
                "Run literature.academic_writing_lint before final Word export."
                if not lint_passed
                else ""
            ),
        ),
        ToolAttempt(
            stage="docx_export_check",
            status="success" if docx_export_ready else "skipped",
            reason=(
                "A DOCX export artifact path was supplied."
                if docx_export_ready
                else "No DOCX artifact path was supplied."
            ),
            metadata={"target_document": target_document},
        ),
    ]
    if missing_sections:
        return ToolOutcome(
            status="blocked",
            quality="partial",
            reason="Draft is missing required single-paper deep-read sections.",
            next_action=ToolNextAction(
                kind="call_tool",
                message="Build evidence for the first missing section, then revise the draft.",
                tool_name="literature.evidence_pack_build",
                args={"project_id": project_id, "query": missing_sections[0]},
            ),
            attempts=attempts,
        )
    if sentinel_count > 0:
        return ToolOutcome(
            status="partial",
            quality="partial",
            reason="Draft structure is present, but 待补充 placeholders remain.",
            next_action=ToolNextAction(
                kind="call_tool",
                message="Fetch evidence for unresolved placeholders before finalizing the draft.",
                tool_name="literature.evidence_pack_build",
                args={"project_id": project_id, "query": SINGLE_PAPER_TASK_SENTINEL},
            ),
            attempts=attempts,
        )
    if evidence_ref_count == 0:
        return ToolOutcome(
            status="partial",
            quality="refs_only",
            reason="Draft has no attached evidence refs.",
            next_action=ToolNextAction(
                kind="call_tool",
                message="Attach evidence refs before treating the draft as final.",
                tool_name="literature.evidence_pack_build",
                args={"project_id": project_id, "query": "single paper deep read evidence"},
            ),
            attempts=attempts,
        )
    if not lint_passed:
        return ToolOutcome(
            status="partial",
            quality="partial",
            reason="Draft needs academic writing lint before export.",
            next_action=ToolNextAction(
                kind="call_tool",
                message="Run the academic writing linter before final export.",
                tool_name="literature.academic_writing_lint",
                args={"content_type": "single_paper_deep_read"},
            ),
            attempts=attempts,
        )
    if target_document == "word_draft" and not docx_export_ready:
        return ToolOutcome(
            status="success",
            quality="full",
            reason="Draft passed completion checks and is ready for optional DOCX export.",
            next_action=ToolNextAction(
                kind="call_tool",
                message="Export DOCX locally if a Word artifact is needed.",
                tool_name="literature.export_docx",
                args={"style_profile": "academic"},
            ),
            attempts=attempts,
        )
    return ToolOutcome(
        status="success",
        quality="full",
        reason="Draft passed completion checks.",
        attempts=attempts,
    )


def _material_summary(material: Any) -> str:
    """Return a compact material summary for resource refs."""

    parts = [
        str(getattr(material, "summary", "") or "").strip(),
        str(getattr(material, "summary_en", "") or "").strip(),
    ]
    focus_points = getattr(material, "focus_points", None)
    if isinstance(focus_points, list):
        parts.extend(str(item).strip() for item in focus_points if str(item).strip())
    text = " | ".join(part for part in parts if part)
    return _bounded_inline_text(text, limit=2000)


def _metadata_text(metadata: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    """Return the first non-empty metadata value for known aliases."""

    for alias in aliases:
        value = metadata.get(alias)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            text = ", ".join(str(item).strip() for item in value if str(item).strip())
        else:
            text = str(value).strip()
        if text:
            return _bounded_inline_text(text, limit=500)
    return None


def _metadata_authors(metadata: dict[str, Any]) -> list[str]:
    """Return bounded author labels from Zotero/CSL-style metadata."""

    raw = metadata.get("authors")
    if raw is None:
        raw = metadata.get("creators")
    if isinstance(raw, list):
        authors: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                name = str(
                    item.get("name")
                    or " ".join(
                        part
                        for part in [str(item.get("firstName") or "").strip(), str(item.get("lastName") or "").strip()]
                        if part
                    )
                    or item.get("lastName")
                    or ""
                ).strip()
            else:
                name = str(item or "").strip()
            if name:
                authors.append(_bounded_inline_text(name, limit=120))
            if len(authors) >= 20:
                break
        return authors
    if isinstance(raw, str) and raw.strip():
        return [_bounded_inline_text(part, limit=120) for part in re.split(r";|,", raw) if part.strip()][:20]
    return []


def _safe_path_label(value: str) -> str:
    """Return a path label without exposing absolute machine-local roots."""

    text = str(value or "").strip()
    if not text:
        return ""
    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith(("/", "\\")):
        return Path(text).name[:240]
    return text.replace("\\", "/")[:240]


def _bounded_inline_text(value: str, *, limit: int) -> str:
    """Return single-line bounded text for task manifests and metadata."""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _agent_result_metadata(
    request_id: str,
    job: Any,
    request: AgentResultRequest,
    content: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(getattr(job, "metadata", {}) or {})
    output_targets = dict(metadata.get("output_targets") or {})
    knowledge_capture = {
        "eligible": bool(output_targets.get("evolution_capture", True)),
        "kind": "smart_read_agent_result",
        "wiki_candidate": bool(output_targets.get("wiki_candidate", False)),
        "graph_candidate": bool(output_targets.get("graph_candidate", False)),
        "smart_read_conversation": bool(output_targets.get("smart_read_conversation", False)),
    }
    result_text = str(content.get("text") or request.text or "").strip()
    return {
        "source": "agent_bridge",
        "agent_source": metadata.get("source") or "mcp",
        "agent_bridge": True,
        "agent_result_ready": True,
        "agent_request_id": request_id,
        "agent_host": metadata.get("agent_host"),
        "intent": metadata.get("intent"),
        "project_id": metadata.get("project_id"),
        "route": metadata.get("route"),
        "chat_session_id": metadata.get("chat_session_id"),
        "resource_refs": list(metadata.get("resource_refs") or []),
        "context_budget": dict(metadata.get("context_budget") or {}),
        "output_targets": output_targets,
        "evidence_refs": [dict(item) for item in request.evidence_refs],
        "wiki_refs": [dict(item) for item in request.wiki_refs],
        "graph_patch_refs": [dict(item) for item in request.graph_patch_refs],
        "knowledge_capture": knowledge_capture,
        "agent_result": {
            "text": result_text[:4000],
            "content_kind": str(content.get("kind") or "agent_result"),
            "metadata": dict(request.metadata),
        },
    }


def _consume_agent_result(
    request_id: str,
    runtime: Any,
    job_id: str,
    routing_metadata: dict[str, Any],
    content: dict[str, Any],
) -> dict[str, Any]:
    """Route completed agent results into local knowledge consumers.

    Args:
        request_id: Agent bridge request id used as a stable source ref.
        runtime: Writing runtime that owns the completed job.
        job_id: Runtime job id linked to the request.
        routing_metadata: Metadata already persisted on the runtime job.
        content: Final result content written by the external agent.

    Returns:
        A compact status object safe to store in runtime job metadata.
    """

    if not isinstance(routing_metadata, dict):
        raise TypeError("routing_metadata must be a dictionary")
    if not isinstance(content, dict):
        raise TypeError("content must be a dictionary")

    knowledge_capture = dict(routing_metadata.get("knowledge_capture") or {})
    result: dict[str, Any] = {
        "request_id": request_id,
        "wiki": {"status": "skipped"},
        "graph": {"status": "skipped"},
        "evolution": {"status": "scheduled" if knowledge_capture.get("eligible") else "skipped"},
    }
    if knowledge_capture.get("wiki_candidate"):
        result["wiki"] = _create_wiki_candidate_from_agent_result(
            request_id=request_id,
            routing_metadata=routing_metadata,
            content=content,
        )
    if knowledge_capture.get("graph_candidate"):
        graph_refs = [dict(item) for item in routing_metadata.get("graph_patch_refs", []) if isinstance(item, dict)]
        result["graph"] = {
            "status": "attached_to_wiki_candidate" if result["wiki"].get("status") == "created" else "metadata_only",
            "graph_patch_ref_count": len(graph_refs),
            "wiki_slug": result["wiki"].get("slug"),
        }
    if knowledge_capture.get("eligible"):
        result["evolution"] = {"status": "scheduled", "source": "runtime_job"}
    return result


def _create_wiki_candidate_from_agent_result(
    *,
    request_id: str,
    routing_metadata: dict[str, Any],
    content: dict[str, Any],
) -> dict[str, Any]:
    """Create a draft wiki page plus review item for an agent result."""

    try:
        import routers.wiki_router as wiki_router
        from wiki.models import WikiPageKind, WikiPageStatus
        from wiki.permissions import DEFAULT_WIKI_OWNER, WikiPagePermissions, WikiPageVisibility, set_permissions
        from wiki.review_queue import ReviewItemKind, ReviewQueue, make_review_item
        from wiki.service import get_wiki_service
    except ImportError as exc:
        return {"status": "unavailable", "error": _bounded_text(str(exc), 300)}

    result_text = str(content.get("text") or routing_metadata.get("agent_result", {}).get("text") or "").strip()
    if not result_text:
        return {"status": "skipped", "reason": "empty_result_text"}

    intent = str(routing_metadata.get("intent") or "agent result").strip()
    title = _wiki_title_from_agent_result(intent=intent, request_id=request_id)
    body = _wiki_body_from_agent_result(
        request_id=request_id,
        routing_metadata=routing_metadata,
        result_text=result_text,
    )
    extra = set_permissions(
        {
            "entry_source": "agent_bridge",
            "agent_request_id": request_id,
            "runtime_job_id": str(routing_metadata.get("job_id") or ""),
            "project_id": routing_metadata.get("project_id"),
            "intent": intent,
            "graph_candidate": bool(routing_metadata.get("knowledge_capture", {}).get("graph_candidate")),
            "graph_patch_refs": [dict(item) for item in routing_metadata.get("graph_patch_refs", []) if isinstance(item, dict)],
            "wiki_refs": [dict(item) for item in routing_metadata.get("wiki_refs", []) if isinstance(item, dict)],
        },
        WikiPagePermissions(owner=DEFAULT_WIKI_OWNER, visibility=WikiPageVisibility.PRIVATE),
    )
    try:
        service = get_wiki_service()
        page = service.create_page(
            title=title,
            kind=WikiPageKind.synthesis.value,
            body=body,
            status=WikiPageStatus.draft.value,
            evidence_refs=[dict(item) for item in routing_metadata.get("evidence_refs", []) if isinstance(item, dict)],
            source_hashes=[],
            extra=extra,
        )
    except ValueError as exc:
        return {"status": "skipped", "reason": _bounded_text(str(exc), 300)}
    except OSError as exc:
        return {"status": "failed", "error": _bounded_text(str(exc), 300)}

    page_relative_path = f"{page.kind.value}/{page.stable_slug}.md"
    try:
        queue = ReviewQueue(_wiki_review_queue_path(wiki_router))
        existing_ids = {item.item_id for item in queue.list_items()}
        candidate_id = f"agent-capture-{page.stable_slug}"
        suffix = 1
        while candidate_id in existing_ids:
            suffix += 1
            candidate_id = f"agent-capture-{page.stable_slug}-{suffix}"
        queue.append(
            make_review_item(
                item_id=candidate_id,
                kind=ReviewItemKind.draft,
                title=page.title,
                page_path=page_relative_path,
                summary=result_text.splitlines()[0][:200],
                source="agent_bridge",
                metadata={
                    "entry_source": "agent_bridge",
                    "agent_request_id": request_id,
                    "requested_status": "review",
                    "kind": page.kind.value,
                    "graph_candidate": bool(extra.get("graph_candidate")),
                },
            )
        )
    except (ValueError, OSError) as exc:
        try:
            service.delete_page(page.stable_slug)
        except (ValueError, OSError):
            pass
        return {"status": "failed", "error": _bounded_text(str(exc), 300)}

    return {
        "status": "created",
        "slug": page.stable_slug,
        "page_path": page_relative_path,
        "review_item_id": candidate_id,
    }


def _wiki_review_queue_path(wiki_router_module: Any) -> Path:
    """Return the wiki-router-owned review queue path.

    Args:
        wiki_router_module: Imported wiki router module exposing
            ``wiki_review_queue_path``. Tests and runtime routing patch this
            module, so agent capture must share that authority.

    Returns:
        Absolute or configured path for the review queue JSONL file.
    """

    if not hasattr(wiki_router_module, "wiki_review_queue_path"):
        raise ValueError("wiki_router_module must expose wiki_review_queue_path")
    raw_path = wiki_router_module.wiki_review_queue_path()
    if raw_path is None:
        raise ValueError("wiki_review_queue_path returned None")
    return Path(raw_path)


def _wiki_title_from_agent_result(*, intent: str, request_id: str) -> str:
    """Return a deterministic title for agent-result capture pages."""

    cleaned = re.sub(r"\s+", " ", intent).strip() or "agent result"
    return f"Agent result: {cleaned[:80]} ({request_id[-8:]})"


def _wiki_body_from_agent_result(
    *,
    request_id: str,
    routing_metadata: dict[str, Any],
    result_text: str,
) -> str:
    """Render a reviewable wiki draft body from one agent result."""

    lines = [
        f"Source request: `{request_id}`",
        "",
        result_text.strip(),
    ]
    evidence_refs = [dict(item) for item in routing_metadata.get("evidence_refs", []) if isinstance(item, dict)]
    if evidence_refs:
        lines.extend(["", "## Evidence refs"])
        for ref in evidence_refs[:50]:
            ref_id = str(ref.get("ref_id") or ref.get("chunk_id") or "").strip()
            summary = str(ref.get("summary") or "").strip()
            if ref_id and summary:
                lines.append(f"- `{ref_id}`: {summary}")
            elif ref_id:
                lines.append(f"- `{ref_id}`")
    return _bounded_text("\n".join(lines), MAX_WIKI_CAPTURE_BODY_CHARS)


def _bounded_text(value: str, limit: int) -> str:
    """Return a hard-bounded text value for metadata and wiki capture."""

    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _require_ref_id(ref_id: str) -> str:
    normalized = str(ref_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="ref_id is required")
    if len(normalized) > 240:
        raise HTTPException(status_code=400, detail="ref_id is too long")
    return normalized


def _parse_cursor(cursor: str | None) -> int:
    if cursor is None or not str(cursor).strip():
        return 0
    try:
        value = int(str(cursor).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="cursor must be a non-negative integer offset") from exc
    if value < 0:
        raise HTTPException(status_code=400, detail="cursor must be a non-negative integer offset")
    return value


def _split_ref_id(ref_id: str) -> tuple[str, str]:
    if ":" not in ref_id:
        raise HTTPException(status_code=400, detail="ref_id must use kind:id form")
    kind, raw_id = ref_id.split(":", 1)
    kind = kind.strip().lower()
    raw_id = raw_id.strip()
    if kind not in {
        "material",
        "chunk",
        "project",
        "draft",
        "wiki",
        "academic_english",
        "bridge_lexicon",
        "source_vault",
        "skill_package",
        "scoring_rules",
        "product_docs",
    }:
        raise HTTPException(status_code=400, detail=f"unsupported resource kind: {kind}")
    if not raw_id:
        raise HTTPException(status_code=400, detail="resource id is required")
    return kind, raw_id


def _resolve_resource(kind: str, raw_id: str, *, project_id: str | None) -> dict[str, Any]:
    if kind == "material":
        return _material_resource(raw_id)
    if kind == "chunk":
        return _chunk_resource(raw_id, project_id=project_id)
    if kind == "project":
        return _project_resource(raw_id)
    if kind == "draft":
        return _draft_resource(raw_id)
    if kind == "wiki":
        return _wiki_resource(raw_id)
    if kind == "academic_english":
        return _academic_english_resource(raw_id)
    if kind == "bridge_lexicon":
        return _bridge_lexicon_resource(raw_id)
    if kind == "source_vault":
        return _source_vault_resource(raw_id, project_id=project_id)
    if kind == "skill_package":
        return _skill_package_resource(raw_id)
    if kind == "scoring_rules":
        return _scoring_rules_resource(raw_id)
    if kind == "product_docs":
        return _product_docs_resource(raw_id)
    raise HTTPException(status_code=400, detail=f"unsupported resource kind: {kind}")


def _material_resource(material_id: str) -> dict[str, Any]:
    store = get_resource_store()
    material = store.get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail=f"Material not found: {material_id}")
    content = "\n\n".join(
        item for item in [material.summary, material.summary_en, *material.focus_points, *material.focus_points_en] if item
    )
    return {
        "kind": "material",
        "project_id": material.project_id,
        "title": material.title,
        "content": content or material.title,
        "metadata": {"material_id": material.material_id, "type": material.type},
    }


def _chunk_resource(chunk_id: str, *, project_id: str | None) -> dict[str, Any]:
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required for chunk refs")
    import routers.resources_router as resources_router

    # ``search-refs`` returns refs from the persisted chunk store. Read that
    # store first so the bounded reader does not prune refs that are already
    # valid but do not need doc-store backfill in tests or imported packs.
    chunk_store = resources_router._load_chunk_store(project_id)
    if not any(
        isinstance(chunk, dict) and str(chunk.get("chunk_id") or "") == chunk_id
        for chunks in chunk_store.values()
        for chunk in chunks
    ):
        chunk_store = resources_router._ensure_project_chunks(project_id)
    for material_id, chunks in chunk_store.items():
        for chunk in chunks:
            if isinstance(chunk, dict) and str(chunk.get("chunk_id") or "") == chunk_id:
                locator = chunk.get("locator") if isinstance(chunk.get("locator"), dict) else None
                safe_locator = (
                    {
                        key: locator[key]
                        for key in ("material_id", "chunk_id", "page", "chunk_index", "bbox")
                        if key in locator
                    }
                    if locator is not None
                    else None
                )
                metadata = {
                    "chunk_id": str(chunk.get("chunk_id") or chunk_id),
                    "material_id": str(chunk.get("material_id") or material_id),
                    "page": chunk.get("page"),
                    "chunk_type": chunk.get("chunk_type"),
                    "source_relative_path": chunk.get("source_relative_path"),
                    "locator": safe_locator,
                }
                return {
                    "kind": "chunk",
                    "project_id": project_id,
                    "title": str(chunk.get("title") or material_id),
                    "content": str(chunk.get("content") or ""),
                    "metadata": {key: value for key, value in metadata.items() if value is not None},
                }
    raise HTTPException(status_code=404, detail=f"Chunk not found: {chunk_id}")


def _project_resource(project_id: str) -> dict[str, Any]:
    store = get_resource_store()
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    materials = store.list_materials(project_id)
    material_lines = [f"- {item.title}: {item.summary}" for item in materials[:20]]
    content = "\n".join([project.title, project.description, *material_lines]).strip()
    return {
        "kind": "project",
        "project_id": project.project_id,
        "title": project.title,
        "content": content or project.title,
        "metadata": {"material_count": len(materials), "status": project.status.value},
    }


def _draft_resource(draft_id: str) -> dict[str, Any]:
    store = get_resource_store()
    draft = store.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"Draft not found: {draft_id}")
    return {
        "kind": "draft",
        "project_id": draft.project_id,
        "title": draft.title,
        "content": draft.content,
        "metadata": {"draft_id": draft.draft_id, "section_id": draft.section_id},
    }


def _wiki_resource(raw_page_path: str) -> dict[str, Any]:
    """Return one generated wiki page as a bounded agent resource."""

    relative_path = _normalize_wiki_resource_path(raw_page_path)
    store = WikiPageStore(wiki_generated_root(), create=False)
    content = store.read_page(relative_path)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Wiki page not found: {relative_path.as_posix()}")
    frontmatter, _body = _split_wiki_resource_frontmatter(str(content))
    text = _strip_wiki_resource_markers(str(content))
    page_path = relative_path.as_posix()
    ref_id = f"wiki:{page_path}"
    source_hash = hashlib.sha256(str(content).encode("utf-8")).hexdigest()
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    chunk_id = f"{ref_id}#{derive_chunk_id(source_hash, 0)}"
    metadata = {
        "knowledge_ref_schema_version": "scholar-ai-wiki-knowledge-ref/v1",
        "ref_id": ref_id,
        "chunk_id": chunk_id,
        "page_path": page_path,
        "source_path": page_path,
        "source": "wiki",
        "source_type": "wiki",
        "resource_kind": "chunk",
        "source_hash": source_hash,
        "content_hash": content_hash,
        "span_start": 0,
        "span_end": len(text),
        "read_endpoint": f"/api/agent-bridge/resource/{ref_id}",
    }
    metadata.update(_wiki_import_source_metadata(frontmatter))
    return {
        "kind": "wiki",
        "project_id": None,
        "title": _wiki_resource_title(text, relative_path),
        "content": text,
        "metadata": metadata,
    }


def _academic_english_resource(raw_ref: str) -> dict[str, Any]:
    """Return one generated academic-English ref as a bounded resource."""

    try:
        return read_academic_english_resource(raw_ref)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _bridge_lexicon_resource(raw_ref: str) -> dict[str, Any]:
    """Return one bridge-lexicon entry as a bounded resource."""

    try:
        return read_bridge_lexicon_resource(raw_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _source_vault_resource(raw_ref: str, *, project_id: str | None) -> dict[str, Any]:
    """Return one Source Vault chunk as a bounded resource."""

    normalized_ref = str(raw_ref or "").strip()
    if not normalized_ref:
        raise HTTPException(status_code=400, detail="source vault ref is required")
    if not normalized_ref.startswith("chunk:"):
        raise HTTPException(status_code=400, detail="source vault refs must use chunk:<chunk_id>")
    chunk_id = normalized_ref.split(":", 1)[1].strip()
    if not chunk_id:
        raise HTTPException(status_code=400, detail="source vault chunk id is required")
    vault = SourceVault()
    chunk = vault.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail=f"Source Vault chunk not found: {chunk_id}")
    source = vault.get_source(chunk.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Source Vault source not found: {chunk.source_id}")
    ref_id = build_source_vault_chunk_ref_id(chunk.chunk_id)
    metadata = build_source_vault_chunk_metadata(source, chunk)
    if project_id:
        metadata["project_id"] = project_id
    metadata["read_endpoint"] = build_source_vault_chunk_read_endpoint(chunk.chunk_id)
    return {
        "kind": "source_vault",
        "project_id": project_id,
        "title": source.title,
        "content": chunk.text,
        "metadata": metadata,
        "ref_id": ref_id,
    }


def _skill_package_resource(raw_ref: str) -> dict[str, Any]:
    """Return one repo-local Skill package chunk as a bounded resource."""

    try:
        return read_skill_package_resource(raw_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _scoring_rules_resource(raw_ref: str) -> dict[str, Any]:
    """Return one scoring-rules config section as a bounded resource."""

    try:
        return read_scoring_rules_resource(raw_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _product_docs_resource(raw_ref: str) -> dict[str, Any]:
    """Return one repo-local product-doc chunk as a bounded resource."""

    try:
        return read_product_docs_resource(raw_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _normalize_wiki_resource_path(raw_page_path: str) -> Path:
    """Normalize a wiki ref path without allowing escapes or non-Markdown refs."""

    normalized = str(raw_page_path or "").strip().replace("\\", "/")
    if not normalized:
        raise HTTPException(status_code=400, detail="wiki page path is required")
    if any(ord(char) < 32 for char in normalized):
        raise HTTPException(status_code=400, detail="wiki page path contains control characters")
    relative_path = Path(normalized)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise HTTPException(status_code=400, detail="wiki page path must stay inside the wiki root")
    if relative_path.suffix and relative_path.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="wiki page path must target a markdown page")
    if not relative_path.suffix:
        relative_path = relative_path.with_suffix(".md")
    return relative_path


def _strip_wiki_resource_markers(content: str) -> str:
    """Return readable wiki body text while preserving page frontmatter context."""

    _frontmatter, body = _split_wiki_resource_frontmatter(content)
    lines: list[str] = []
    for line in str(body or "").splitlines():
        stripped = line.strip()
        if stripped in {AUTO_START, AUTO_END}:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _split_wiki_resource_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split JSON frontmatter from a generated wiki page."""

    text = str(content or "")
    lines = text.splitlines()
    if lines and lines[0].strip() == "---json":
        frontmatter_lines: list[str] = []
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                try:
                    payload = json.loads("\n".join(frontmatter_lines))
                except json.JSONDecodeError:
                    payload = {}
                frontmatter = payload if isinstance(payload, dict) else {}
                return frontmatter, "\n".join(lines[index + 1 :])
            frontmatter_lines.append(line)
    return {}, text


def _wiki_import_source_metadata(frontmatter: dict[str, Any]) -> dict[str, str]:
    """Return safe local-import provenance fields stored in wiki frontmatter."""

    if not isinstance(frontmatter, dict):
        return {}
    extra = frontmatter.get("extra")
    if not isinstance(extra, dict):
        return {}
    import_source = extra.get("import_source")
    if not isinstance(import_source, dict):
        return {}
    metadata: dict[str, str] = {}
    source_hash = str(import_source.get("sha256") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", source_hash):
        metadata["import_source_hash"] = source_hash
    source_path = str(import_source.get("path") or "").strip()
    if source_path:
        metadata["import_source_path"] = source_path[:500]
    source_type = str(import_source.get("type") or "").strip()
    if source_type:
        metadata["import_source_type"] = source_type[:80]
    entry_source = str(extra.get("entry_source") or "").strip()
    if entry_source:
        metadata["entry_source"] = entry_source[:80]
    return metadata


def _wiki_resource_title(content: str, relative_path: Path) -> str:
    """Return the first Markdown H1 or a readable title from page path."""

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title[:300]
    return relative_path.stem.replace("-", " ").replace("_", " ").strip() or relative_path.as_posix()


def _agent_jobs(runtime: Any, *, limit: int) -> list[Any]:
    jobs: list[Any] = []
    for session in runtime.list_sessions(include_archived=True):
        jobs.extend(
            job
            for job in runtime.list_jobs(session_id=session.session_id)
            if getattr(job, "kind", None) == JobKind.AGENT_REQUEST
            or str(getattr(getattr(job, "kind", None), "value", getattr(job, "kind", ""))) == JobKind.AGENT_REQUEST.value
        )
    jobs.sort(key=lambda item: item.created_at, reverse=True)
    return jobs[:limit]


def _find_request_job(runtime: Any, request_id: str) -> Any | None:
    normalized = str(request_id or "").strip()
    if not normalized:
        return None
    for job in _agent_jobs(runtime, limit=1000):
        if str(job.metadata.get("agent_request_id") or "") == normalized:
            return job
    return None


def _require_request_job(runtime: Any, request_id: str) -> Any:
    job = _find_request_job(runtime, request_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Agent request not found: {request_id}")
    return job


def _parse_status(status: str | None) -> JobStatus | None:
    if status is None or not status.strip():
        return None
    try:
        return JobStatus(status.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid job status: {status}") from exc
