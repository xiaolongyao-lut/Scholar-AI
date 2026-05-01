# -*- coding: utf-8 -*-
"""Compatibility API for the frontend Intelligent Chat surface.

The current product UI calls ``/api/chat`` while the modular server exposes the
lower-level LLM proxy at ``/chat/ask``. This router keeps the UI contract alive
with typed FastAPI response models and a small local context retrieval layer.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from project_paths import REPO_ROOT, runtime_state_path
from routers.chat_router import ChatRequest, LLMConfig, chat_ask
from routers.llm_cost_router import _read_cost_aggregate
from routers.resources_router import search_project_chunks_for_query
from writing_resources import get_writing_resource_store


ContextTier = Literal["fast", "balanced", "thorough"]
MessageRole = Literal["user", "assistant"]

router = APIRouter(prefix="/api", tags=["Chat"])

_SESSION_STORE_PATH = runtime_state_path("intelligent_chat_sessions.json")
_SESSION_LOCK = threading.Lock()
_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".tex",
}
_TIER_LIMITS: dict[ContextTier, tuple[int, int]] = {
    "fast": (5, 2000),
    "balanced": (10, 6000),
    "thorough": (15, 12000),
}


class TokenUsagePayload(BaseModel):
    """Token usage payload consumed by the chat UI."""

    prompt: int = Field(0, ge=0)
    completion: int = Field(0, ge=0)
    total: int = Field(0, ge=0)


class ContextChunkPayload(BaseModel):
    """Single context chunk disclosed under an assistant message."""

    index: int = Field(..., ge=1)
    source: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    relevance_score: float | None = Field(default=None, ge=0.0)
    chunk_id: str | None = None
    material_id: str | None = None
    title: str | None = None
    section_title: str | None = None
    page: int | str | None = None
    source_labels: list[str] = Field(default_factory=list)
    source_hint: str | None = None


class ContextMetadataPayload(BaseModel):
    """Context metadata for progressive disclosure in the frontend."""

    chunks: list[ContextChunkPayload] = Field(default_factory=list)
    truncated: bool = False


class EvidenceReferencePayload(BaseModel):
    """Machine-readable provenance reference for context used in a response."""

    chunk_id: str
    material_id: str | None = None
    source: str
    text: str
    quote: str
    label: str = "context"
    score: float | None = None
    source_labels: list[str] = Field(default_factory=lambda: ["local_context"])
    page: int | str | None = None
    source_hint: str | None = None


class SamplingParamsPayload(BaseModel):
    """Actual generation sampling settings used for the backend call."""

    temperature: float
    top_p: float
    top_k: int
    max_tokens: int


class IntelligentChatRequest(BaseModel):
    """Request payload for the frontend Intelligent Chat endpoint."""

    query: str = Field(..., min_length=1, max_length=5000)
    session_id: str | None = None
    tier: ContextTier = "balanced"
    project_id: str | None = None
    source_paths: list[str] | None = None


class IntelligentChatResponse(BaseModel):
    """Typed Intelligent Chat response matching the frontend contract."""

    response: str
    session_id: str
    context_chunks_used: int = Field(..., ge=0)
    tokens_used: TokenUsagePayload
    tier_used: ContextTier
    context_metadata: ContextMetadataPayload | None = None
    actual_sampling_params: SamplingParamsPayload | None = None
    evidence_refs: list[EvidenceReferencePayload] = Field(default_factory=list)


class ChatSessionSummaryPayload(BaseModel):
    """Small session row for the history drawer."""

    session_id: str
    total_turns: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)
    created_at: str | None = None
    updated_at: str | None = None
    preview: str = ""


class ChatSessionListResponse(BaseModel):
    """List wrapper returned by ``GET /api/chat/sessions``."""

    sessions: list[ChatSessionSummaryPayload] = Field(default_factory=list)


class ChatResumeRequest(BaseModel):
    """Request body for restoring saved chat turns."""

    session_id: str = Field(..., min_length=1)
    limit: int = Field(100, ge=1, le=500)


class ChatResumeMessagePayload(BaseModel):
    """Saved chat message returned during session restore."""

    id: str
    role: MessageRole
    content: str
    timestamp: str
    tier_used: ContextTier | None = None
    context_metadata: ContextMetadataPayload | None = None
    tokens_used: TokenUsagePayload | None = None
    evidence_refs: list[EvidenceReferencePayload] = Field(default_factory=list)


class ChatResumeResponse(BaseModel):
    """Response for ``POST /api/chat/resume``."""

    session_id: str
    messages: list[ChatResumeMessagePayload]


class BudgetStatusPayload(BaseModel):
    """Budget status shape consumed by the frontend status bar."""

    call_count: int = Field(..., ge=0)
    call_cap: int = Field(..., ge=1)
    cost_usd: float = Field(..., ge=0.0)
    budget_usd: float = Field(..., ge=0.0)
    percent_calls: float = Field(..., ge=0.0)
    percent_usd: float = Field(..., ge=0.0)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _split_source_paths(raw_value: str) -> list[str]:
    normalized = raw_value.replace("\n", ";").replace(",", ";")
    return [item.strip() for item in normalized.split(";") if item.strip()]


def _resolve_source_paths(request_paths: list[str] | None) -> list[Path]:
    raw_paths = request_paths or _split_source_paths(os.getenv("LITERATURE_SOURCE_PATHS", ""))
    resolved: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = REPO_ROOT / path
        try:
            candidate = path.resolve()
        except OSError:
            continue
        if candidate.exists():
            resolved.append(candidate)
    return resolved


def _iter_source_files(paths: list[Path]) -> list[Path]:
    max_files = max(1, int(os.getenv("INTELLIGENT_CHAT_MAX_SOURCE_FILES", "200")))
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES:
            files.append(path)
        elif path.is_dir():
            for candidate in path.rglob("*"):
                if candidate.is_file() and candidate.suffix.lower() in _TEXT_SUFFIXES:
                    files.append(candidate)
                    if len(files) >= max_files:
                        return files
        if len(files) >= max_files:
            return files
    return files


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _read_text_file(path: Path) -> str:
    max_bytes = max(4096, int(os.getenv("INTELLIGENT_CHAT_MAX_FILE_BYTES", "65536")))
    try:
        payload = path.read_bytes()[:max_bytes]
    except OSError:
        return ""
    return payload.decode("utf-8", errors="ignore")


def _query_terms(query: str) -> set[str]:
    lowered = query.lower()
    terms = {term for term in re.findall(r"[a-zA-Z0-9_]{2,}", lowered) if len(term) >= 2}
    cjk_chars = {char for char in lowered if "\u4e00" <= char <= "\u9fff"}
    return terms | cjk_chars


def _score_text(query_terms: set[str], text: str) -> float:
    if not query_terms:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for term in query_terms if term in lowered)
    return hits / max(1, len(query_terms))


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_project_id(project_id: str | None) -> str | None:
    normalized = str(project_id or "").strip()
    if not normalized:
        return None
    try:
        store = get_writing_resource_store()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="Writing resource store is unavailable") from exc
    if store.get_project(normalized) is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {normalized}")
    return normalized


def _extract_project_chunk_content(chunk: dict[str, Any]) -> str:
    return str(
        chunk.get("content")
        or chunk.get("raw_content")
        or chunk.get("text")
        or chunk.get("source_text")
        or ""
    ).strip()


def _extract_project_chunk_source(chunk: dict[str, Any]) -> str:
    return str(
        chunk.get("title")
        or chunk.get("source_relative_path")
        or chunk.get("material_id")
        or chunk.get("chunk_id")
        or "project_chunk"
    ).strip()


def _extract_source_labels(chunk: dict[str, Any], fallback: str) -> list[str]:
    raw_labels = chunk.get("source_labels")
    labels: list[str] = []
    if isinstance(raw_labels, list):
        labels.extend(str(label).strip() for label in raw_labels if str(label).strip())
    raw_label = chunk.get("source_label")
    if raw_label is not None and str(raw_label).strip():
        labels.append(str(raw_label).strip())
    return labels or [fallback]


def _chunk_text(text: str, *, chunk_chars: int = 1200) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    for paragraph in paragraphs or [text.strip()]:
        if not paragraph:
            continue
        start = 0
        while start < len(paragraph):
            chunk = paragraph[start : start + chunk_chars].strip()
            if chunk:
                chunks.append(chunk)
            start += chunk_chars
    return chunks


def _build_context_chunks(query: str, source_paths: list[Path], tier: ContextTier) -> tuple[list[ContextChunkPayload], bool]:
    max_chunks, max_chars = _TIER_LIMITS[tier]
    terms = _query_terms(query)
    scored: list[tuple[float, str, str]] = []
    for file_path in _iter_source_files(source_paths):
        source = _display_path(file_path)
        for chunk in _chunk_text(_read_text_file(file_path)):
            score = _score_text(terms, chunk)
            if score > 0:
                scored.append((score, source, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)

    chunks: list[ContextChunkPayload] = []
    used_chars = 0
    truncated = False
    for score, source, chunk in scored:
        if len(chunks) >= max_chunks:
            truncated = True
            break
        remaining = max_chars - used_chars
        if remaining <= 0:
            truncated = True
            break
        content = chunk[:remaining].strip()
        if not content:
            continue
        chunks.append(
            ContextChunkPayload(
                index=len(chunks) + 1,
                source=source,
                content=content,
                relevance_score=round(float(score), 4),
            )
        )
        used_chars += len(content)
    return chunks, truncated


def _build_project_context_chunks(query: str, project_id: str, tier: ContextTier) -> tuple[list[ContextChunkPayload], bool]:
    max_chunks, max_chars = _TIER_LIMITS[tier]
    results = search_project_chunks_for_query(project_id=project_id, query=query, top_k=max_chunks)
    chunks: list[ContextChunkPayload] = []
    used_chars = 0
    truncated = False

    for result in results:
        remaining = max_chars - used_chars
        if len(chunks) >= max_chunks or remaining <= 0:
            truncated = True
            break

        full_content = _extract_project_chunk_content(result)
        if not full_content:
            continue
        content = full_content[:remaining].strip()
        if not content:
            continue
        if len(full_content) > len(content):
            truncated = True

        score = result.get("score")
        numeric_score = float(score) if isinstance(score, int | float) else None
        title = _clean_optional_text(result.get("title"))
        chunks.append(
            ContextChunkPayload(
                index=len(chunks) + 1,
                source=_extract_project_chunk_source(result),
                content=content,
                relevance_score=round(numeric_score, 4) if numeric_score is not None else None,
                chunk_id=_clean_optional_text(result.get("chunk_id")),
                material_id=_clean_optional_text(result.get("material_id")),
                title=title,
                section_title=_clean_optional_text(result.get("section_title")),
                page=result.get("page") if isinstance(result.get("page"), int | str) else None,
                source_labels=_extract_source_labels(result, "project_chunks"),
                source_hint=_clean_optional_text(result.get("source_hint")),
            )
        )
        used_chars += len(content)

    if len(results) > len(chunks):
        truncated = True
    return chunks, truncated


def _build_context_strings(chunks: list[ContextChunkPayload]) -> list[str]:
    context_strings: list[str] = []
    for chunk in chunks:
        meta_parts = [f"source={chunk.source}"]
        if chunk.chunk_id:
            meta_parts.append(f"chunk_id={chunk.chunk_id}")
        if chunk.material_id:
            meta_parts.append(f"material_id={chunk.material_id}")
        if chunk.section_title:
            meta_parts.append(f"section={chunk.section_title}")
        if chunk.page is not None:
            meta_parts.append(f"page={chunk.page}")
        context_strings.append(f"[{chunk.index}] {'; '.join(meta_parts)}\n{chunk.content}")
    return context_strings


def _build_evidence_refs(chunks: list[ContextChunkPayload]) -> list[EvidenceReferencePayload]:
    refs: list[EvidenceReferencePayload] = []
    for chunk in chunks:
        refs.append(
            EvidenceReferencePayload(
                chunk_id=chunk.chunk_id or f"local-{chunk.index}",
                material_id=chunk.material_id,
                source=chunk.source,
                text=chunk.content,
                quote=chunk.content[:300],
                label="project_chunk" if chunk.material_id else "local_context",
                score=chunk.relevance_score,
                source_labels=chunk.source_labels or (["project_chunks"] if chunk.material_id else ["local_context"]),
                page=chunk.page,
                source_hint=chunk.source_hint,
            )
        )
    return refs


def _load_default_llm_config() -> LLMConfig:
    if os.getenv("CHAT_BASE_URL") and os.getenv("CHAT_MODEL"):
        return LLMConfig(
            provider=os.getenv("CHAT_PROVIDER", "OpenAI"),
            api_key=os.getenv("OPENAI_API_KEY_CHAT", os.getenv("CHAT_API_KEY", "")),
            model=os.getenv("CHAT_MODEL", ""),
            base_url=os.getenv("CHAT_BASE_URL", ""),
            temperature=float(os.getenv("CHAT_TEMPERATURE", "0.7")),
            top_p=float(os.getenv("CHAT_TOP_P", "0.9")),
            top_k=int(os.getenv("CHAT_TOP_K", "50")),
            max_tokens=int(os.getenv("CHAT_MAX_TOKENS", "2048")),
            system_prompt=os.getenv("CHAT_SYSTEM_PROMPT", ""),
        )
    if os.getenv("ARK_BASE_URL") and os.getenv("ARK_MODEL"):
        return LLMConfig(
            provider="Doubao",
            api_key=os.getenv("ARK_API_KEY", os.getenv("VOLCANO_API_KEY", "")),
            model=os.getenv("ARK_MODEL", ""),
            base_url=os.getenv("ARK_BASE_URL", ""),
            temperature=float(os.getenv("CHAT_TEMPERATURE", "0.7")),
            top_p=float(os.getenv("CHAT_TOP_P", "0.9")),
            top_k=int(os.getenv("CHAT_TOP_K", "50")),
            max_tokens=int(os.getenv("CHAT_MAX_TOKENS", "2048")),
            system_prompt=os.getenv("CHAT_SYSTEM_PROMPT", ""),
        )
    if os.getenv("OPENAI_BASE_URL") and os.getenv("OPENAI_MODEL"):
        return LLMConfig(
            provider=os.getenv("OPENAI_PROVIDER", "OpenAI"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", ""),
            base_url=os.getenv("OPENAI_BASE_URL", ""),
            temperature=float(os.getenv("CHAT_TEMPERATURE", "0.7")),
            top_p=float(os.getenv("CHAT_TOP_P", "0.9")),
            top_k=int(os.getenv("CHAT_TOP_K", "50")),
            max_tokens=int(os.getenv("CHAT_MAX_TOKENS", "2048")),
            system_prompt=os.getenv("CHAT_SYSTEM_PROMPT", ""),
        )
    raise HTTPException(status_code=503, detail="No chat LLM is configured")


def _usage_from_mapping(usage: dict[str, Any] | None) -> TokenUsagePayload:
    usage = usage or {}
    prompt = int(usage.get("prompt_tokens", usage.get("prompt", 0)) or 0)
    completion = int(usage.get("completion_tokens", usage.get("completion", 0)) or 0)
    total = int(usage.get("total_tokens", usage.get("total", prompt + completion)) or 0)
    return TokenUsagePayload(prompt=prompt, completion=completion, total=total)


async def _call_llm_answer(query: str, context: list[str]) -> tuple[str, TokenUsagePayload, SamplingParamsPayload]:
    llm = _load_default_llm_config()
    response = await chat_ask(
        ChatRequest(
            query=query,
            context=context,
            history=[],
            llm=llm,
        )
    )
    return (
        response.answer,
        _usage_from_mapping(response.usage),
        SamplingParamsPayload(
            temperature=llm.temperature,
            top_p=llm.top_p,
            top_k=llm.top_k,
            max_tokens=llm.max_tokens,
        ),
    )


def _load_session_store() -> dict[str, Any]:
    if not _SESSION_STORE_PATH.exists():
        return {"sessions": {}}
    try:
        payload = json.loads(_SESSION_STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"sessions": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), dict):
        return {"sessions": {}}
    return payload


def _save_session_store(payload: dict[str, Any]) -> None:
    _SESSION_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=_SESSION_STORE_PATH.parent,
        prefix=f"{_SESSION_STORE_PATH.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp_path = Path(handle.name)
        handle.write(serialized)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, _SESSION_STORE_PATH)


def _persist_turns(
    *,
    session_id: str,
    query: str,
    response: IntelligentChatResponse,
) -> None:
    now = _now_iso()
    with _SESSION_LOCK:
        store = _load_session_store()
        sessions = store.setdefault("sessions", {})
        session = sessions.setdefault(
            session_id,
            {
                "session_id": session_id,
                "created_at": now,
                "updated_at": now,
                "messages": [],
            },
        )
        messages = session.setdefault("messages", [])
        messages.append(
            {
                "id": f"user-{uuid.uuid4().hex[:12]}",
                "role": "user",
                "content": query,
                "timestamp": now,
            }
        )
        messages.append(
            {
                "id": f"assistant-{uuid.uuid4().hex[:12]}",
                "role": "assistant",
                "content": response.response,
                "timestamp": now,
                "tier_used": response.tier_used,
                "context_metadata": (
                    response.context_metadata.model_dump() if response.context_metadata is not None else None
                ),
                "tokens_used": response.tokens_used.model_dump(),
                "evidence_refs": [ref.model_dump() for ref in response.evidence_refs],
            }
        )
        session["updated_at"] = now
        session["total_tokens"] = sum(
            int((message.get("tokens_used") or {}).get("total") or 0)
            for message in messages
            if isinstance(message, dict)
        )
        _save_session_store(store)


def _session_summary(session: dict[str, Any]) -> ChatSessionSummaryPayload:
    messages = session.get("messages") if isinstance(session.get("messages"), list) else []
    preview = ""
    for message in reversed(messages):
        if isinstance(message, dict) and str(message.get("role")) == "user":
            preview = str(message.get("content") or "")[:160]
            break
    return ChatSessionSummaryPayload(
        session_id=str(session.get("session_id") or ""),
        total_turns=len(messages),
        total_tokens=int(session.get("total_tokens") or 0),
        created_at=session.get("created_at"),
        updated_at=session.get("updated_at"),
        preview=preview,
    )


@router.post("/chat", response_model=IntelligentChatResponse)
async def intelligent_chat(req: IntelligentChatRequest) -> IntelligentChatResponse:
    """Answer a literature-grounded frontend chat request."""
    project_id = _validate_project_id(req.project_id)
    if project_id is not None:
        chunks, truncated = _build_project_context_chunks(req.query, project_id, req.tier)
    else:
        source_paths = _resolve_source_paths(req.source_paths)
        if not source_paths:
            raise HTTPException(status_code=400, detail="No literature source paths configured")
        chunks, truncated = _build_context_chunks(req.query, source_paths, req.tier)

    session_id = (req.session_id or "").strip() or f"session_{uuid.uuid4().hex[:12]}"
    context_metadata = ContextMetadataPayload(chunks=chunks, truncated=truncated)
    evidence_refs = _build_evidence_refs(chunks)

    if not chunks:
        response = IntelligentChatResponse(
            response="No relevant literature context was found for this query.",
            session_id=session_id,
            context_chunks_used=0,
            tokens_used=TokenUsagePayload(),
            tier_used=req.tier,
            context_metadata=ContextMetadataPayload(chunks=[], truncated=False),
            evidence_refs=[],
        )
        _persist_turns(session_id=session_id, query=req.query, response=response)
        return response

    answer, usage, sampling = await _call_llm_answer(req.query, _build_context_strings(chunks))
    response = IntelligentChatResponse(
        response=answer,
        session_id=session_id,
        context_chunks_used=len(chunks),
        tokens_used=usage,
        tier_used=req.tier,
        context_metadata=context_metadata,
        actual_sampling_params=sampling,
        evidence_refs=evidence_refs,
    )
    _persist_turns(session_id=session_id, query=req.query, response=response)
    return response


@router.get("/chat/sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions() -> ChatSessionListResponse:
    """Return saved Intelligent Chat sessions sorted by update time."""
    with _SESSION_LOCK:
        sessions = list(_load_session_store().get("sessions", {}).values())
    summaries = [
        _session_summary(session)
        for session in sessions
        if isinstance(session, dict) and str(session.get("session_id") or "").strip()
    ]
    summaries.sort(key=lambda item: item.updated_at or "", reverse=True)
    return ChatSessionListResponse(sessions=summaries)


@router.post("/chat/resume", response_model=ChatResumeResponse)
async def resume_chat_session(req: ChatResumeRequest) -> ChatResumeResponse:
    """Return the most recent saved turns for one Intelligent Chat session."""
    with _SESSION_LOCK:
        session = _load_session_store().get("sessions", {}).get(req.session_id)
    if not isinstance(session, dict):
        raise HTTPException(status_code=404, detail=f"Session not found: {req.session_id}")
    raw_messages = session.get("messages") if isinstance(session.get("messages"), list) else []
    recent = raw_messages[-req.limit :]
    return ChatResumeResponse(
        session_id=req.session_id,
        messages=[
            ChatResumeMessagePayload.model_validate(message)
            for message in recent
            if isinstance(message, dict)
        ],
    )


@router.get("/budget/status", response_model=BudgetStatusPayload)
async def get_budget_status() -> BudgetStatusPayload:
    """Return a lightweight daily LLM budget summary for the status bar."""
    aggregate = _read_cost_aggregate(date.today(), date.today())
    call_count = int(aggregate.get("total_calls") or 0)
    cost_usd = round(float(aggregate.get("total_cost_usd") or 0.0), 6)
    call_cap = max(1, int(os.getenv("INTELLIGENT_CHAT_DAILY_CALL_CAP", "200")))
    budget_usd = max(0.0, float(os.getenv("INTELLIGENT_CHAT_DAILY_BUDGET_USD", "5")))
    percent_calls = min(100.0, round(call_count / call_cap * 100, 2))
    percent_usd = 0.0 if budget_usd <= 0 else min(100.0, round(cost_usd / budget_usd * 100, 2))
    return BudgetStatusPayload(
        call_count=call_count,
        call_cap=call_cap,
        cost_usd=cost_usd,
        budget_usd=budget_usd,
        percent_calls=percent_calls,
        percent_usd=percent_usd,
    )
