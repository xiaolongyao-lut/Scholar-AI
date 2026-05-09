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
from routers.resources_router import load_project_chunks_for_rag, search_project_chunks_for_query
from tolf_text_selector import select_tolf_context_chunks
from writing_resources import get_writing_resource_store
from agents.chart_agent import generate_chart_spec
from agents.intent_detector import detect_chart_intent
from dev_flags import is_chart_agent_enabled


ContextTier = Literal["fast", "balanced", "thorough"]
MessageRole = Literal["user", "assistant"]
ConfidenceLabel = Literal["high", "medium", "low", "very_low"]
ResponseType = Literal["text", "chart"]

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
    rank: int | None = None
    query_overlap_tokens: list[str] = Field(default_factory=list)


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
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_label: ConfidenceLabel | None = None
    response_type: ResponseType = "text"
    chart_spec: dict[str, Any] | None = None


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
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_label: ConfidenceLabel | None = None
    response_type: ResponseType = "text"
    chart_spec: dict[str, Any] | None = None


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


def _positive_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    """Resolve a positive integer env var without failing request handlers.

    Args:
        name: Environment variable name.
        default: Fallback value used when the env var is absent or invalid.
        minimum: Inclusive lower bound for the returned value.

    Returns:
        A value greater than or equal to ``minimum``.

    Raises:
        ValueError: If ``default`` or ``minimum`` cannot produce a positive value.
    """
    if not isinstance(default, int) or not isinstance(minimum, int):
        raise ValueError("default and minimum must be integers")
    if minimum < 1:
        raise ValueError("minimum must be positive")
    if default < minimum:
        raise ValueError("default must be greater than or equal to minimum")

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _non_negative_float_env(name: str, default: float) -> float:
    """Resolve a non-negative float env var without failing request handlers."""
    if not isinstance(default, int | float) or float(default) < 0.0:
        raise ValueError("default must be a non-negative number")
    raw_value = os.getenv(name)
    if raw_value is None:
        return float(default)
    try:
        parsed = float(str(raw_value).strip())
    except (TypeError, ValueError):
        return float(default)
    return max(0.0, parsed)


def _ragworkflow_chat_enabled() -> bool:
    return _truthy(os.getenv("INTELLIGENT_CHAT_RAGWORKFLOW_ENABLED"))


def _tolf_context_enabled() -> bool:
    val = os.getenv("INTELLIGENT_CHAT_TOLF_CONTEXT_ENABLED")
    if val is None:
        return True  # default-on after cross-lingual bridge expansion fix
    return _truthy(val)


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
    max_files = _positive_int_env("INTELLIGENT_CHAT_MAX_SOURCE_FILES", 200)
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
    max_bytes = _positive_int_env("INTELLIGENT_CHAT_MAX_FILE_BYTES", 65536, minimum=4096)
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


def _build_project_context_chunks(query: str, project_id: str, tier: ContextTier, boost_keywords: list[str] | None = None) -> tuple[list[ContextChunkPayload], bool]:
    max_chunks, max_chars = _TIER_LIMITS[tier]
    if _tolf_context_enabled():
        # TOLF needs full corpus — it has its own cosine prefilter internally.
        # Keyword-search top-k is too small for SA-RAG diffusion to work.
        all_chunks = load_project_chunks_for_rag(project_id)
        if all_chunks:
            try:
                tolfs = select_tolf_context_chunks(
                    query, all_chunks,
                    top_k=max_chunks,
                    max_candidates=_positive_int_env("INTELLIGENT_CHAT_TOLF_CONTEXT_CANDIDATES", 45),
                    boost_keywords=boost_keywords,
                )
            except (RuntimeError, TypeError, ValueError):
                tolfs = []
            if tolfs:
                results: list[dict[str, Any]] = tolfs
            else:
                results = search_project_chunks_for_query(project_id=project_id, query=query, top_k=max_chunks)
        else:
            results = search_project_chunks_for_query(project_id=project_id, query=query, top_k=max_chunks)
    else:
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
    for idx, chunk in enumerate(chunks):
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
                rank=idx,
            )
        )
    return refs


_CONFIDENCE_SATURATION_K = 5.0


def _normalize_evidence_score(raw: float) -> float:
    """Map an unbounded retrieval score into [0, 1) via saturation.

    Why:
        ``evidence_refs[].score`` reflects whichever retriever produced the
        chunk — TOLF / hybrid BM25 / source-paths token overlap — none of
        which are normalized. Live smoke (2026-05-09) showed BM25 scores
        of 6.5–9.5 always clamping the raw 0.6·max + 0.4·avg blend to 1.0
        and tagging every successful match "high". The saturation curve
        ``s / (s + k)`` keeps zero at zero, smoothly approaches 1, and
        still ranks chunks by raw quality. ``k=5`` gives 0.55 at s=6 and
        0.66 at s=10 — useful spread for the high/medium/low thresholds.
    """
    if raw <= 0.0:
        return 0.0
    return raw / (raw + _CONFIDENCE_SATURATION_K)


def _compute_confidence(
    refs: list[EvidenceReferencePayload],
) -> tuple[float | None, ConfidenceLabel | None]:
    """Compute evidence-strength confidence from retrieval scores.

    Why:
        P2 borrowed pattern from RAG-Pro ConfidenceBadge (0.6*max + 0.4*avg).
        Backend produces label so frontend never re-interprets raw scores.
        This signals retrieval evidence strength, not answer truth.
    """
    raw_scores = [
        float(r.score) for r in refs if isinstance(r.score, int | float) and r.score >= 0.0
    ]
    if not raw_scores:
        return None, None
    normalized = [_normalize_evidence_score(s) for s in raw_scores]
    score_max = max(normalized)
    score_avg = sum(normalized) / len(normalized)
    confidence = round(0.6 * score_max + 0.4 * score_avg, 4)
    confidence = max(0.0, min(1.0, confidence))
    if confidence >= 0.8:
        label: ConfidenceLabel = "high"
    elif confidence >= 0.5:
        label = "medium"
    elif confidence >= 0.3:
        label = "low"
    else:
        label = "very_low"
    return confidence, label


def _coerce_evidence_refs(raw_refs: Any) -> list[EvidenceReferencePayload]:
    refs: list[EvidenceReferencePayload] = []
    if not isinstance(raw_refs, list):
        return refs
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, dict):
            continue
        text = str(raw_ref.get("text") or raw_ref.get("compressed_text") or raw_ref.get("quote") or "").strip()
        source = str(raw_ref.get("source") or raw_ref.get("material_id") or raw_ref.get("chunk_id") or "").strip()
        chunk_id = str(raw_ref.get("chunk_id") or "").strip()
        if not chunk_id or not source or not text:
            continue
        refs.append(
            EvidenceReferencePayload(
                chunk_id=chunk_id,
                material_id=_clean_optional_text(raw_ref.get("material_id")),
                source=source,
                text=text,
                quote=str(raw_ref.get("quote") or text[:300]).strip(),
                label=str(raw_ref.get("label") or "rag_workflow").strip() or "rag_workflow",
                score=float(raw_ref["score"]) if isinstance(raw_ref.get("score"), int | float) else None,
                source_labels=_extract_source_labels(raw_ref, "rag_workflow"),
                page=raw_ref.get("page") if isinstance(raw_ref.get("page"), int | str) else None,
                source_hint=_clean_optional_text(raw_ref.get("source_hint")),
                rank=raw_ref.get("rank") if isinstance(raw_ref.get("rank"), int) else None,
                query_overlap_tokens=[str(t) for t in raw_ref.get("query_overlap_tokens", []) if isinstance(t, str)],
            )
        )
    return refs


def _context_chunks_from_evidence_refs(refs: list[EvidenceReferencePayload], tier: ContextTier) -> tuple[list[ContextChunkPayload], bool]:
    max_chunks, max_chars = _TIER_LIMITS[tier]
    chunks: list[ContextChunkPayload] = []
    used_chars = 0
    truncated = False
    for ref in refs:
        if len(chunks) >= max_chunks:
            truncated = True
            break
        remaining = max_chars - used_chars
        if remaining <= 0:
            truncated = True
            break
        content = ref.text[:remaining].strip()
        if not content:
            continue
        if len(ref.text) > len(content):
            truncated = True
        chunks.append(
            ContextChunkPayload(
                index=len(chunks) + 1,
                source=ref.source,
                content=content,
                relevance_score=ref.score,
                chunk_id=ref.chunk_id,
                material_id=ref.material_id,
                page=ref.page,
                source_labels=ref.source_labels,
                source_hint=ref.source_hint,
            )
        )
        used_chars += len(content)
    return chunks, truncated


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


def _load_skill_tool_schemas() -> list[dict[str, Any]] | None:
    """Get OpenAI-compatible tool schemas for enabled non-experimental skills."""
    try:
        from skills.service import get_writing_skill_service
        from skill_executor import get_active_skill_tool_schemas
        svc = get_writing_skill_service()
        schemas = get_active_skill_tool_schemas(svc._registry)
        return schemas if schemas else None
    except Exception:
        return None


def _execute_skill_tool_calls(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Execute skills requested by LLM tool_calls, return result strings."""
    results: list[str] = []
    try:
        from skills.service import get_writing_skill_service
        from skill_executor import execute_skill
        svc = get_writing_skill_service()
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            args_raw = func.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except (json.JSONDecodeError, TypeError):
                args = {}

            skill = svc._registry.get(name) or svc._registry.get(name.replace("_", "-"))
            if skill is not None:
                result = execute_skill(skill, args)
                tag = f"[{skill.name}]"
                results.append(
                    f"{tag}: {result.output[:800]}" if result.success
                    else f"{tag} 失败: {result.error}"
                )
    except Exception as exc:
        results.append(f"[技能执行异常]: {exc}")
    return results


async def _call_llm_answer(query: str, context: list[str]) -> tuple[str, TokenUsagePayload, SamplingParamsPayload]:
    llm = _load_default_llm_config()
    tool_schemas = _load_skill_tool_schemas()
    response = await chat_ask(
        ChatRequest(
            query=query,
            context=context,
            history=[],
            llm=llm,
            tools=tool_schemas,
        )
    )

    tool_calls = getattr(response, "tool_calls", None) or []
    if tool_calls:
        tool_results = _execute_skill_tool_calls(tool_calls)
        if tool_results:
            followup_context = list(context) + [
                f"[技能执行结果]\n{r}" for r in tool_results
            ]
            response = await chat_ask(
                ChatRequest(
                    query=query,
                    context=followup_context,
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


async def _chart_chat_caller(prompt: str, context: list[str]) -> str:
    """Adapter passed to chart_agent so it reuses this module's chat_ask.

    Why:
        chart_agent must hit the same provider / cost / retry chain as
        ``_call_llm_answer``. Routing through this module's ``chat_ask``
        symbol also lets test fixtures monkeypatch ``chat_ask`` once and
        intercept both the main LLM call and the chart-spec call.
    """
    llm = _load_default_llm_config()
    response = await chat_ask(
        ChatRequest(
            query=prompt,
            context=context,
            history=[],
            llm=llm,
        )
    )
    return getattr(response, "answer", "") or ""


async def _call_project_ragworkflow_answer(
    *,
    query: str,
    project_id: str,
    tier: ContextTier,
) -> tuple[str, list[ContextChunkPayload], bool, list[EvidenceReferencePayload], SamplingParamsPayload | None]:
    from main_rag_workflow import RAGWorkflow

    class _NoopSemanticRouter:
        async def route_query(self, user_query: str, top_k: int = 3) -> list[str]:
            del top_k
            return [user_query]

    local_chunks = load_project_chunks_for_rag(project_id)
    if not local_chunks:
        return (
            "No relevant literature context was found for this query.",
            [],
            False,
            [],
            None,
        )

    llm = _load_default_llm_config()
    workflow = RAGWorkflow(
        semantic_router=_NoopSemanticRouter(),
        local_data={"chunks": local_chunks},
        api_key=llm.api_key,
        base_url=llm.base_url,
        model=llm.model,
        enable_requests_fallback=False,
        memory_adapter=None,
    )
    try:
        result = await workflow.ask_my_literature(
            query,
            top_k_points=1,
            top_k_evidence=_TIER_LIMITS[tier][0],
            include_association=False,
            association_project_id=project_id,
        )
    finally:
        await workflow.close()

    refs = _coerce_evidence_refs(list(result.evidence_refs))
    chunks, truncated = _context_chunks_from_evidence_refs(refs, tier)
    if "error" in result.trace:
        raise HTTPException(status_code=502, detail=f"RAGWorkflow failed: {result.trace['error']}")
    return (
        result.generated_answer,
        chunks,
        truncated,
        refs,
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
                "confidence_score": response.confidence_score,
                "confidence_label": response.confidence_label,
                "response_type": response.response_type,
                "chart_spec": response.chart_spec,
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
    ragworkflow_answer: str | None = None
    ragworkflow_sampling: SamplingParamsPayload | None = None
    evidence_refs: list[EvidenceReferencePayload]

    # Load user research profile for retrieval boost
    from user_research_profile import load_profile, get_boost_keywords, extract_keywords, add_direction, save_profile
    profile = load_profile(runtime_state_path())
    boost_keywords = get_boost_keywords(profile)

    if project_id is not None and _ragworkflow_chat_enabled():
        ragworkflow_answer, chunks, truncated, evidence_refs, ragworkflow_sampling = await _call_project_ragworkflow_answer(
            query=req.query,
            project_id=project_id,
            tier=req.tier,
        )
    elif project_id is not None:
        chunks, truncated = _build_project_context_chunks(req.query, project_id, req.tier, boost_keywords=boost_keywords)
        evidence_refs = _build_evidence_refs(chunks)
    else:
        source_paths = _resolve_source_paths(req.source_paths)
        if not source_paths:
            raise HTTPException(status_code=400, detail="No literature source paths configured")
        chunks, truncated = _build_context_chunks(req.query, source_paths, req.tier)
        evidence_refs = _build_evidence_refs(chunks)

    session_id = (req.session_id or "").strip() or f"session_{uuid.uuid4().hex[:12]}"
    context_metadata = ContextMetadataPayload(chunks=chunks, truncated=truncated)

    if not chunks:
        response = IntelligentChatResponse(
            response=ragworkflow_answer or "No relevant literature context was found for this query.",
            session_id=session_id,
            context_chunks_used=0,
            tokens_used=TokenUsagePayload(),
            tier_used=req.tier,
            context_metadata=ContextMetadataPayload(chunks=[], truncated=False),
            evidence_refs=[],
            actual_sampling_params=ragworkflow_sampling,
        )
        _persist_turns(session_id=session_id, query=req.query, response=response)
        return response

    if ragworkflow_answer is not None:
        answer = ragworkflow_answer
        usage = TokenUsagePayload()
        sampling = ragworkflow_sampling
    else:
        answer, usage, sampling = await _call_llm_answer(req.query, _build_context_strings(chunks))

    response_type: ResponseType = "text"
    chart_spec: dict[str, Any] | None = None
    if is_chart_agent_enabled() and detect_chart_intent(req.query) == "chart":
        candidate_spec = await generate_chart_spec(
            req.query,
            [chunk.model_dump() for chunk in chunks],
            chat_caller=_chart_chat_caller,
        )
        if candidate_spec is not None:
            response_type = "chart"
            chart_spec = candidate_spec

    response = IntelligentChatResponse(
        response=answer,
        session_id=session_id,
        context_chunks_used=len(chunks),
        tokens_used=usage,
        tier_used=req.tier,
        context_metadata=context_metadata,
        actual_sampling_params=sampling,
        evidence_refs=evidence_refs,
        confidence_score=None,
        confidence_label=None,
        response_type=response_type,
        chart_spec=chart_spec,
    )
    confidence_score, confidence_label = _compute_confidence(evidence_refs)
    response.confidence_score = confidence_score
    response.confidence_label = confidence_label
    _persist_turns(session_id=session_id, query=req.query, response=response)

    # Update research profile after conversation turn
    detected = extract_keywords(req.query, profile)
    for kw in detected:
        add_direction(profile, kw, weight=0.2)
    if detected:
        save_profile(profile, runtime_state_path())

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
    call_cap = _positive_int_env("INTELLIGENT_CHAT_DAILY_CALL_CAP", 200)
    budget_usd = _non_negative_float_env("INTELLIGENT_CHAT_DAILY_BUDGET_USD", 5.0)
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
