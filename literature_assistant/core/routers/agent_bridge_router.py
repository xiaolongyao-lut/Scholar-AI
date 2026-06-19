# -*- coding: utf-8 -*-
"""Agent bridge API backed by runtime sessions, jobs, events, and artifacts."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from harness_protocols import ArtifactType, JobKind, JobStatus
from models import ArtifactPayload, JobPayload, SessionPayload
from literature_assistant.core.project_paths import wiki_generated_root
from literature_assistant.core.wiki.page_store import AUTO_END, AUTO_START, WikiPageStore


router = APIRouter(prefix="/api/agent-bridge", tags=["Agent Bridge"])

MAX_USER_TEXT_CHARS = 8000
MAX_PROGRESS_MESSAGE_CHARS = 500
MAX_RESULT_TEXT_CHARS = 120000
MAX_RESOURCE_CHARS = 20000
DEFAULT_RESOURCE_CHARS = 6000
MAX_WIKI_CAPTURE_BODY_CHARS = 40000


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
    return JobPayload(**failed.to_dict())


def _request_title(envelope: AgentRequestEnvelope) -> str:
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
    if kind not in {"material", "chunk", "project", "draft", "wiki"}:
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
    text = _strip_wiki_resource_markers(str(content))
    return {
        "kind": "wiki",
        "project_id": None,
        "title": _wiki_resource_title(text, relative_path),
        "content": text,
        "metadata": {
            "page_path": relative_path.as_posix(),
            "source": "wiki",
        },
    }


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

    lines: list[str] = []
    in_frontmatter = False
    for index, line in enumerate(str(content or "").splitlines()):
        stripped = line.strip()
        if index == 0 and stripped == "---json":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        if stripped in {AUTO_START, AUTO_END}:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


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
