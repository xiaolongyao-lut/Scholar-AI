# -*- coding: utf-8 -*-
"""Inspiration API Router — 启发点生成与续写上下文"""

import json
import logging
import os
import re
import time
from collections.abc import Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from inspiration_store import InspirationStore, InspirationStoreError
from literature_assistant.core.graph_payload import GraphPayloadV0
from llm_cost_logger import log_llm_call
from llm_defaults import resolve_llm_params
from llm_pricing import usage_from_response
from models.project_reasoning_bias import ProjectReasoningBiasPayload
from prompts.project_reasoning_bias import (
    ProjectReasoningBiasContext,
    apply_project_reasoning_bias,
    load_project_reasoning_bias,
    render_project_reasoning_bias_block,
    should_apply_project_reasoning_bias,
)
from prompts.identity_renderer import render_identity_header  # 2026-05-18 identity injection plan
from project_paths import output_path
from sampling_storage import load_user_sampling

from routers.chat_router import (
    LLMConfig,
    _build_chat_request,
    _extract_chat_response,
    _validate_outbound_llm_base_url,
)

logger = logging.getLogger("InspirationRouter")
router = APIRouter(prefix="/inspiration", tags=["Inspiration"])

# Lazy singleton
_engine_instance = None
_inspiration_store_instance: InspirationStore | None = None

InspirationFrame = Literal["auto", "irac", "fincot"]
VALID_SPARK_TYPES = frozenset({
    "causal_extension",
    "conflict",
    "analogy",
    "gap",
    "synthesis",
    "memory_association",
})
PROMPT_TEMPLATE_PACKAGE = "literature_assistant.core.prompt_templates"
PROMPT_TEMPLATE_FILES: dict[Literal["irac", "fincot"], str] = {
    "irac": "inspiration_irac.txt",
    "fincot": "inspiration_fincot.txt",
}


def _get_engine():
    """延迟初始化 InspirationEngine，自动加载已有因果 DAG 和 MemPalace。"""
    global _engine_instance
    if _engine_instance is not None:
        return _engine_instance

    from inspiration_engine import InspirationEngine, load_causal_dags_from_output

    # 加载因果 DAG
    output_root = output_path()
    causal_dags = []
    if output_root.is_dir():
        causal_dags = load_causal_dags_from_output(output_root)

    # 加载 MemPalace（可选）
    mempalace = None
    try:
        from python_adapter_server import get_memory_adapter
        mem = get_memory_adapter()
        if mem is not None and mem.is_enabled():
            mempalace = mem
    except Exception as exc:
        logger.warning("MemPalace adapter unavailable for inspiration engine: %s", exc)

    # 加载冲突检测器（可选）
    conflict_detector = None
    try:
        from layers.w_layer_cross_paper_analysis import ConflictDetector
        conflict_detector = ConflictDetector()
    except Exception:
        logger.warning("ConflictDetector unavailable for inspiration engine", exc_info=True)

    _engine_instance = InspirationEngine(
        mempalace=mempalace,
        causal_dags=causal_dags,
        conflict_detector=conflict_detector,
    )
    return _engine_instance


def reload_engine():
    """外部调用以重新加载引擎（例如新论文入库后）。"""
    global _engine_instance
    _engine_instance = None


# --- Request / Response Models ---

class GenerateSparksRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="查询/主题")
    limit: int = Field(10, ge=1, le=50, description="最大返回数")
    project_id: str | None = Field(None, description="项目ID，用于从知识库生成启发点")
    project_reasoning_bias_enabled: bool | None = Field(
        default=None,
        description="Per-request toggle for applying saved project reasoning bias to inspiration prompts",
    )
    llm: LLMConfig | None = Field(None, description="Optional LLM config for real inspiration generation")
    sampling: dict[str, float | int] | None = Field(default=None, description="Per-task sampling overrides")
    frame: InspirationFrame = Field(
        default="auto",
        description="Prompt frame: auto keyword heuristic, IRAC, or FinCoT.",
    )


class AnalysisChainPayload(BaseModel):
    """LLM-emitted inner reasoning chain.

    Optional + tolerant: missing / wrong-shape fields fall back to empty
    strings or empty lists so the surrounding spark is preserved.
    """

    observation: str = ""
    mechanism: str = ""
    evidence: list[str] = []
    boundary: str = ""
    counter_evidence: list[str] = []
    next_action: str = ""


class SparkEvidenceRef(BaseModel):
    """Per-spark evidence anchor (mirror of GraphPayload v0 EvidenceRef).

    Track B (D-EVR-1..6). Strict additive shape kept local to inspiration_router
    to avoid an inspiration → graph_payload import cycle. The fields mirror
    `literature_assistant/core/graph_payload.py:EvidenceRef` so frontend
    pill renderers and KG embed adapters can consume both shapes
    interchangeably.
    """

    model_config = ConfigDict(extra="forbid")
    material_id: str = Field(..., min_length=1)
    page: int | None = Field(default=None, ge=1)
    chunk_id: str | None = Field(default=None, min_length=1)
    text: str = Field(default="", max_length=2000)
    score: float | None = None


class SparkResponse(BaseModel):
    id: str
    content: str
    spark_type: str
    source_papers: list[str] = []
    confidence: float = 0.0
    related_point_ids: list[str] = []
    actionable: bool = True
    analysis_chain: AnalysisChainPayload | None = None
    confidence_reason: str = ""
    temporal_sensitivity: float = 0.0
    evidence_refs: list[SparkEvidenceRef] = Field(default_factory=list)
    causal_dag: GraphPayloadV0 | None = None


def build_spark_evidence_refs(
    chunks: Sequence[Mapping[str, Any]] | None,
    *,
    max_refs: int = 3,
) -> list[SparkEvidenceRef]:
    """Materialize per-spark evidence anchors from already-retrieved chunks.

    Track B (D-EVR-3, D-EVR-4). Pure helper; no retrieval call, no LLM
    invocation, no provider touch. Caps to top max_refs by score so prompts
    and UI density stay bounded; the rest of the chunks remain in
    ``analysis_chain.evidence`` as free text.

    Inputs:
        chunks: any iterable of dict-shaped chunk records carrying at
            least ``material_id``. ``chunk_id``, ``page``, ``content`` /
            ``text`` / ``snippet``, and ``score`` are read when present.
            ``None`` or empty input returns ``[]`` — never fabricates.
        max_refs: positive cap on the number of refs returned. Values
            outside ``[1, 10]`` are clamped to keep abuse contained.

    Output:
        Up to ``max_refs`` ``SparkEvidenceRef`` instances, sorted by
        descending score (chunks without a numeric score sort last).
        Deduplicated by ``(material_id, chunk_id)``; entries without a
        non-empty ``material_id`` are skipped.
    """
    if not chunks:
        return []
    capped = max(1, min(int(max_refs) if isinstance(max_refs, int) else 3, 10))

    candidates: list[tuple[float, SparkEvidenceRef, tuple[str, str | None]]] = []
    seen: set[tuple[str, str | None]] = set()
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            continue
        material_id_raw = chunk.get("material_id")
        if not isinstance(material_id_raw, str) or not material_id_raw.strip():
            continue
        material_id = material_id_raw.strip()

        chunk_id_raw = chunk.get("chunk_id")
        chunk_id: str | None = None
        if isinstance(chunk_id_raw, str) and chunk_id_raw.strip():
            chunk_id = chunk_id_raw.strip()

        key = (material_id, chunk_id)
        if key in seen:
            continue

        page_raw = chunk.get("page")
        page: int | None = (
            int(page_raw) if isinstance(page_raw, int) and page_raw >= 1 else None
        )

        text_raw = chunk.get("content") or chunk.get("text") or chunk.get("snippet")
        text = str(text_raw).strip() if isinstance(text_raw, str) else ""
        if len(text) > 2000:
            text = text[:2000]

        score_raw = chunk.get("score")
        score: float | None = (
            float(score_raw)
            if isinstance(score_raw, (int, float)) and not isinstance(score_raw, bool)
            else None
        )

        try:
            ref = SparkEvidenceRef(
                material_id=material_id,
                page=page,
                chunk_id=chunk_id,
                text=text,
                score=score,
            )
        except Exception:  # pragma: no cover — defensive; SparkEvidenceRef validators are tight
            continue

        seen.add(key)
        # Sort key: higher score first; missing score → -infinity so it sorts last.
        sort_score = score if score is not None else float("-inf")
        candidates.append((sort_score, ref, key))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [ref for _, ref, _ in candidates[:capped]]


class GenerateSparksResponse(BaseModel):
    sparks: list[SparkResponse]
    total: int


class ContinuationResponse(BaseModel):
    spark: SparkResponse
    evidence_texts: list[str] = []
    causal_chain_summary: str = ""
    suggested_angles: list[str] = []
    related_figures: list[str] = []


InspirationStoreSource = Literal["generated", "manual", "imported"]


class SavedInspirationCreateRequest(BaseModel):
    """Request body for saving one generated or manually curated spark."""

    model_config = ConfigDict(extra="forbid")

    spark: SparkResponse
    project_id: str | None = Field(default=None, max_length=160)
    query: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=2000)
    source: InspirationStoreSource = "generated"
    tags: list[str] = Field(default_factory=list, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("project_id")
    @classmethod
    def _trim_project_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("query", "notes")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            if not isinstance(tag, str):
                raise ValueError("tags must contain only strings")
            clean = tag.strip()
            if not clean:
                continue
            if len(clean) > 80:
                raise ValueError("tags must be at most 80 characters each")
            if clean not in seen:
                normalized.append(clean)
                seen.add(clean)
        return normalized


class SavedInspirationUpdateRequest(BaseModel):
    """Request body for updating one saved Inspiration spark."""

    model_config = ConfigDict(extra="forbid")

    spark: SparkResponse | None = None
    project_id: str | None = Field(default=None, max_length=160)
    clear_project_id: bool = False
    query: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    source: InspirationStoreSource | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] | None = None

    @field_validator("project_id")
    @classmethod
    def _trim_optional_project_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("query", "notes")
    @classmethod
    def _trim_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("tags")
    @classmethod
    def _normalize_optional_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return SavedInspirationCreateRequest._normalize_tags(value)


class SavedInspirationResponse(BaseModel):
    """Public payload for one saved Inspiration spark."""

    saved_id: str
    project_id: str | None = None
    query: str
    spark: SparkResponse
    notes: str
    source: InspirationStoreSource
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    version: int


class SavedInspirationListResponse(BaseModel):
    """Paginated saved Inspiration list response."""

    items: list[SavedInspirationResponse]
    total: int
    page: int
    page_size: int


class DeleteSavedInspirationResponse(BaseModel):
    """Delete result for a saved Inspiration row."""

    saved_id: str
    deleted: bool


def get_inspiration_store() -> InspirationStore:
    """Return the process-local Inspiration store singleton."""

    global _inspiration_store_instance
    if _inspiration_store_instance is None:
        _inspiration_store_instance = InspirationStore()
    return _inspiration_store_instance


def reset_inspiration_store_for_tests(store: InspirationStore | None = None) -> None:
    """Replace the store singleton for deterministic local tests."""

    global _inspiration_store_instance
    _inspiration_store_instance = store


def _saved_record_response(record: Any) -> SavedInspirationResponse:
    payload = record.to_dict()
    return SavedInspirationResponse(**payload)


def _store_http_error(exc: Exception) -> HTTPException:
    status_code = 400 if isinstance(exc, ValueError) else 500
    return HTTPException(status_code=status_code, detail=str(exc))


def _resolve_inspiration_llm_config(
    llm: LLMConfig,
    sampling: dict[str, float | int] | None,
) -> LLMConfig:
    file_overrides = (load_user_sampling() or {}).get("inspiration", {})
    merged: dict[str, float | int] = {}
    if isinstance(file_overrides, dict):
        merged.update(file_overrides)
    if sampling:
        merged.update(sampling)
    resolved = resolve_llm_params("inspiration", merged or None)
    return llm.model_copy(
        update={
            "temperature": float(resolved["temperature"]),
            "top_p": float(resolved["top_p"]),
            "top_k": int(resolved["top_k"]),
            "max_tokens": int(resolved["max_tokens"]),
        }
    )


def _log_inspiration_telemetry(
    *,
    model: str | None,
    started_at: float,
    usage: dict[str, Any] | None = None,
    response: Any = None,
    status: str = "ok",
) -> None:
    try:
        usage_row = usage or usage_from_response(response)
        log_llm_call(
            model=model,
            task="inspiration",
            prompt_tokens=int(usage_row.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_row.get("completion_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - started_at) * 1000,
            status=status,
            cache_status="miss",
            decision="invoke",
        )
    except Exception:
        logger.debug("Inspiration telemetry logging failed", exc_info=True)


def _select_inspiration_frame(
    query: str,
    frame: InspirationFrame = "auto",
) -> Literal["irac", "fincot"]:
    """Choose a prompt frame without spending a model call.

    Args:
        query: User topic. Empty values default to IRAC.
        frame: Explicit frame override, or ``auto`` for keyword heuristics.

    Returns:
        ``"irac"`` for argument/boundary work, ``"fincot"`` for
        mechanism/metric/causal-chain work.
    """
    if frame in {"irac", "fincot"}:
        return frame
    normalized = str(query or "").strip().lower()
    irac_keywords = (
        "论证", "边界", "反例", "反驳", "争议", "支持", "假设", "问题",
        "argument", "counter", "boundary", "claim", "issue", "rule",
        "evidence gap",
    )
    fincot_keywords = (
        "因果", "机制", "机理", "指标", "变量", "效应", "中介", "路径", "量化",
        "causal", "mechanism", "mediator", "driver", "outcome", "metric",
        "measure", "effect", "variable",
    )
    if any(keyword in normalized for keyword in irac_keywords):
        return "irac"
    if any(keyword in normalized for keyword in fincot_keywords):
        return "fincot"
    return "irac"


def _read_prompt_template(frame: Literal["irac", "fincot"]) -> str:
    """Read a bundled prompt template in source and frozen builds.

    Args:
        frame: Template family to read.

    Returns:
        UTF-8 template text with ``{query}`` and ``{limit}`` placeholders.

    Raises:
        OSError: If neither package resources nor source-tree fallback exists.
    """
    filename = PROMPT_TEMPLATE_FILES[frame]
    try:
        template = resources.files(PROMPT_TEMPLATE_PACKAGE).joinpath(filename)
        return template.read_text(encoding="utf-8")
    except (AttributeError, FileNotFoundError, ModuleNotFoundError, OSError):
        fallback = Path(__file__).resolve().parents[1] / "prompt_templates" / filename
        return fallback.read_text(encoding="utf-8")


def _inline_inspiration_prompt(query: str, limit: int) -> str:
    return (
        f"请围绕研究主题“{query}”生成 {limit} 条中文写作启发点。\n"
        "只返回 JSON 对象，不要 Markdown。\n"
        "格式：{\"sparks\":[{\"content\":\"1-2 句启发\",\"spark_type\":\"causal_extension|conflict|analogy|gap|synthesis|memory_association\","
        "\"source_papers\":[\"若未知则空数组\"],\"confidence\":0.0,\"related_point_ids\":[],\"actionable\":true}]}"
    )


def _build_inspiration_prompt(
    query: str,
    limit: int,
    frame: InspirationFrame = "auto",
    project_reasoning_bias: ProjectReasoningBiasPayload | None = None,
) -> str:
    selected = _select_inspiration_frame(query, frame)
    try:
        template = _read_prompt_template(selected)
        body = template.format(query=query, limit=limit)
    except Exception as exc:  # noqa: BLE001 - prompt templates are runtime resources; keep local fallback alive.
        logger.warning(
            "Inspiration prompt template unavailable for frame=%s; using inline fallback: %s",
            selected,
            exc,
        )
        body = _inline_inspiration_prompt(query, limit)

    identity_header = render_identity_header(f"inspiration_{selected}")
    if project_reasoning_bias is None:
        return f"{identity_header}\n\n{body}" if identity_header else body

    bias_block = render_project_reasoning_bias_block(
        project_reasoning_bias,
        locale=project_reasoning_bias.language,
    )
    body_with_bias = apply_project_reasoning_bias(body, bias_block)
    return f"{identity_header}\n\n{body_with_bias}" if identity_header else body_with_bias




def _supports_structured_outputs(provider: str, model: str) -> bool:
    """Check if provider/model supports OpenAI structured outputs (response_format with json_schema).

    C5: Structured outputs routing. Returns True for known-good combinations.
    Fallback to json_mode when False.
    """
    provider_key = provider.strip().lower()
    model_lower = model.strip().lower()

    # OpenAI gpt-4o and newer support structured outputs
    if provider_key == "openai":
        if any(m in model_lower for m in ["gpt-4o", "gpt-4.1", "o1", "o3"]):
            return True

    # Claude, Gemini, and most other providers do not support json_schema yet
    # (they support json_mode but not strict schema validation)
    return False


def _spark_response_json_schema() -> dict[str, Any]:
    """Return the strict JSON schema used for OpenAI Structured Outputs.

    Returns:
        OpenAI-compatible ``response_format.json_schema.schema`` object.
    """
    analysis_chain_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "observation": {"type": "string"},
            "mechanism": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "boundary": {"type": "string"},
            "counter_evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "next_action": {"type": "string"},
        },
        "required": [
            "observation",
            "mechanism",
            "evidence",
            "boundary",
            "counter_evidence",
            "next_action",
        ],
    }
    spark_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "content": {"type": "string"},
            "spark_type": {"type": "string", "enum": sorted(VALID_SPARK_TYPES)},
            "source_papers": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "related_point_ids": {"type": "array", "items": {"type": "string"}},
            "actionable": {"type": "boolean"},
            "analysis_chain": analysis_chain_schema,
            "confidence_reason": {"type": "string"},
            "temporal_sensitivity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": [
            "content",
            "spark_type",
            "source_papers",
            "confidence",
            "related_point_ids",
            "actionable",
            "analysis_chain",
            "confidence_reason",
            "temporal_sensitivity",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sparks": {
                "type": "array",
                "items": spark_schema,
            }
        },
        "required": ["sparks"],
    }


def _response_format_for_llm(llm: LLMConfig) -> dict[str, Any]:
    """Choose strict schema for supported models, JSON mode otherwise."""
    if _supports_structured_outputs(llm.provider, llm.model):
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "inspiration_sparks",
                "strict": True,
                "schema": _spark_response_json_schema(),
            },
        }
    return {"type": "json_object"}


def _structured_outputs_unsupported(exc: Exception) -> bool:
    """Return True when a provider rejects the json_schema response_format."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    if exc.response.status_code not in {400, 404, 422}:
        return False
    detail = exc.response.text.lower()
    return "response_format" in detail or "json_schema" in detail or "structured" in detail

def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


def _coerce_analysis_chain(raw: Any) -> AnalysisChainPayload | None:
    """Parse the analysis_chain JSON block tolerantly.

    Missing / wrong-shape fields set the chain to None,
    do NOT drop the surrounding spark. evidence + counter_evidence
    truncated to 3 items each and 200 chars per item.
    """
    if raw is None or not isinstance(raw, dict):
        return None

    def _str(name: str) -> str:
        v = raw.get(name)
        return str(v).strip() if isinstance(v, (str, int, float)) and v is not None else ""

    def _str_list(name: str, max_items: int = 3, max_chars: int = 200) -> list[str]:
        v = raw.get(name)
        if not isinstance(v, list):
            return []
        out: list[str] = []
        for item in v[:max_items]:
            if not isinstance(item, (str, int, float)):
                continue
            s = str(item).strip()
            if not s:
                continue
            out.append(s[:max_chars])
        return out

    observation = _str("observation")
    mechanism = _str("mechanism")
    evidence = _str_list("evidence")
    boundary = _str("boundary")
    counter_evidence = _str_list("counter_evidence")
    next_action = _str("next_action")
    # If literally all six fields are empty, treat as missing chain.
    if not any([observation, mechanism, evidence, boundary, counter_evidence, next_action]):
        return None
    return AnalysisChainPayload(
        observation=observation,
        mechanism=mechanism,
        evidence=evidence,
        boundary=boundary,
        counter_evidence=counter_evidence,
        next_action=next_action,
    )


def _coerce_llm_sparks(answer: str, limit: int) -> list[SparkResponse]:
    from inspiration_engine import _spark_id

    payload = json.loads(answer)
    items = payload.get("sparks") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("missing sparks list")

    sparks: list[SparkResponse] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            raise ValueError("invalid spark item")
        content = str(item.get("content") or "").strip()
        if not content:
            raise ValueError("spark content required")
        raw_sources = item.get("source_papers") or []
        source_papers = [str(source).strip() for source in raw_sources if str(source).strip()] if isinstance(raw_sources, list) else []
        raw_related = item.get("related_point_ids") or []
        related_point_ids = [str(value).strip() for value in raw_related if str(value).strip()] if isinstance(raw_related, list) else []
        confidence = _clamp01(item.get("confidence", 0.6), default=0.6)
        analysis_chain = _coerce_analysis_chain(item.get("analysis_chain"))
        confidence_reason = str(item.get("confidence_reason") or "").strip()
        temporal_sensitivity = _clamp01(item.get("temporal_sensitivity", 0.0), default=0.0)
        spark_type = str(item.get("spark_type") or "analogy").strip()
        if spark_type not in VALID_SPARK_TYPES:
            logger.warning("Invalid inspiration spark_type=%r; falling back to analogy", spark_type)
            spark_type = "analogy"
        sparks.append(
            SparkResponse(
                id=str(item.get("id") or _spark_id(content)),
                content=content,
                spark_type=spark_type,
                source_papers=source_papers,
                confidence=confidence,
                related_point_ids=related_point_ids,
                actionable=bool(item.get("actionable", True)),
                analysis_chain=analysis_chain,
                confidence_reason=confidence_reason,
                temporal_sensitivity=temporal_sensitivity,
            )
        )
    return sparks


def _generate_local_sparks(req: GenerateSparksRequest, engine) -> list[Any]:
    sparks = engine.generate_sparks(req.query, limit=req.limit)

    if not sparks and req.project_id:
        try:
            from routers.resources_router import _ensure_project_chunks  # noqa: PLC0415
            chunk_store = _ensure_project_chunks(req.project_id)
            all_chunks = [c for chunks in chunk_store.values() for c in chunks]
            if all_chunks:
                sparks = engine.generate_sparks_from_chunks(req.query, all_chunks, limit=req.limit)
        except Exception:  # noqa: BLE001
            logger.warning("从项目知识库生成启发点失败，跳过", exc_info=True)
    return sparks


def _resolve_inspiration_project_reasoning_bias(req: GenerateSparksRequest) -> ProjectReasoningBiasPayload | None:
    """Return project bias for inspiration LLM prompts when analysis-chain scope applies."""
    normalized_project_id = str(req.project_id or "").strip()
    if not normalized_project_id:
        return None
    if req.project_reasoning_bias_enabled is False:
        return None
    selected_frame = _select_inspiration_frame(req.query, req.frame)
    try:
        bias = load_project_reasoning_bias(normalized_project_id)
        if should_apply_project_reasoning_bias(
            bias,
            ProjectReasoningBiasContext(surface=f"inspiration_{selected_frame}"),
        ):
            return bias
    except Exception as exc:  # noqa: BLE001 - local inspiration fallback must remain available.
        logger.warning(
            "project_reasoning_bias resolution skipped for inspiration: project=%s err=%s",
            normalized_project_id,
            exc,
        )
    return None


async def _generate_llm_sparks(req: GenerateSparksRequest) -> list[SparkResponse] | None:
    from routers.chat_router import _resolve_chat_llm

    try:
        resolved_llm = _resolve_chat_llm(req.llm)
    except HTTPException as exc:
        if exc.status_code == 503:
            logger.info("No default inspiration LLM configured; falling back to local engine")
            return None
        raise
    except Exception as exc:  # noqa: BLE001 - invalid runtime LLM config should not break local inspiration.
        logger.warning("Could not resolve inspiration LLM; falling back to local engine: %s", exc)
        return None

    llm = _resolve_inspiration_llm_config(resolved_llm, req.sampling)
    prompt = _build_inspiration_prompt(
        req.query,
        req.limit,
        req.frame,
        project_reasoning_bias=_resolve_inspiration_project_reasoning_bias(req),
    )
    response_format = _response_format_for_llm(llm)
    try:
        _validate_outbound_llm_base_url(llm.base_url, llm.provider)
        url, headers, payload = _build_chat_request(
            prompt,
            [],
            llm,
            response_format=response_format,
        )
    except ValueError as exc:
        logger.warning("Unsafe inspiration LLM endpoint rejected; falling back to local engine: %s", exc)
        return None
    telemetry_model = str(payload.get("model", llm.model))
    started_at = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if response_format.get("type") == "json_schema" and _structured_outputs_unsupported(exc):
                    url, headers, payload = _build_chat_request(
                        prompt,
                        [],
                        llm,
                        response_format={"type": "json_object"},
                    )
                    telemetry_model = str(payload.get("model", llm.model))
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                else:
                    raise
            data = resp.json()
        answer, usage, model_used = _extract_chat_response(data, llm.provider, telemetry_model)
        sparks = _coerce_llm_sparks(answer, req.limit)
        _log_inspiration_telemetry(
            model=model_used or telemetry_model,
            started_at=started_at,
            usage=usage,
            status="ok",
        )
        return sparks
    except Exception as exc:
        _log_inspiration_telemetry(
            model=telemetry_model,
            started_at=started_at,
            status="error",
        )
        logger.warning("LLM inspiration failed, falling back to local engine: %s", exc)
        return None


# --- Validation gates ---


def _has_year_token(text: str) -> bool:
    return bool(re.search(r"(?:19|20)\d{2}", text or ""))


def _validation_strict() -> bool:
    """``INSPIRATION_VALIDATION_STRICT`` defaults to 1 (D-IR-2).

    When env=0 we still attach ``confidence_reason`` but do not multiply
    the confidence. Set to "0" / "false" / "off" / "no" to relax.
    """
    raw = os.environ.get("INSPIRATION_VALIDATION_STRICT", "1").strip().lower()
    return raw not in {"0", "false", "off", "no", ""}


def _apply_validation_gates(spark: SparkResponse) -> SparkResponse:
    """Run the three weak validation gates.

    Chunk_id / page anchors are still out of scope. Gates here only check field shape and
    obvious signals; failure subtracts 0.10..0.15 from confidence and
    records why in ``confidence_reason``. Returns a NEW SparkResponse;
    never mutates the input.
    """
    reasons: list[str] = []
    confidence = float(spark.confidence)
    strict = _validation_strict()

    # Gate 1: locatability — at least one of analysis_chain.evidence,
    # source_papers, related_point_ids, causal_context.chain_nodes is
    # populated. Without any of those the spark is floating and we
    # downgrade.
    has_evidence_texts = bool(spark.analysis_chain and spark.analysis_chain.evidence)
    has_sources = bool(spark.source_papers) or bool(spark.related_point_ids)
    if not (has_evidence_texts or has_sources):
        reasons.append("证据定位弱")
        if strict:
            confidence *= 0.85

    # Gate 2: conflict — conflict sparks need at least one counter
    # evidence line to be useful. Non-conflict sparks are exempt.
    if spark.spark_type == "conflict":
        has_counter = bool(spark.analysis_chain and spark.analysis_chain.counter_evidence)
        if not has_counter:
            reasons.append("冲突归因未完整")
            if strict:
                confidence *= 0.90

    # Gate 3: freshness — when temporal_sensitivity ≥ 0.7 we expect
    # at least one year token in source_papers or evidence texts.
    if spark.temporal_sensitivity >= 0.7:
        text_blob = " ".join(spark.source_papers)
        if spark.analysis_chain:
            text_blob += " " + " ".join(spark.analysis_chain.evidence)
            text_blob += " " + spark.analysis_chain.boundary
        if not _has_year_token(text_blob):
            reasons.append("时效敏感但缺少时间锚")
            if strict:
                confidence *= 0.90

    # Always clamp to [0, 1] (defensive — should already be there)
    confidence = max(0.0, min(1.0, confidence))

    if not reasons:
        return spark

    merged_reason = (spark.confidence_reason + ("; " if spark.confidence_reason else "")) + "；".join(reasons)
    return spark.model_copy(
        update={
            "confidence": confidence,
            "confidence_reason": merged_reason,
        }
    )


def _gate_sparks(sparks: list[SparkResponse]) -> list[SparkResponse]:
    return [_apply_validation_gates(s) for s in sparks]


# --- Endpoints ---

@router.post("/generate", response_model=GenerateSparksResponse)
async def generate_inspirations(req: GenerateSparksRequest):
    """基于查询生成启发点列表。"""
    engine = _get_engine()
    llm_sparks = await _generate_llm_sparks(req)
    if llm_sparks is not None:
        gated = _gate_sparks(llm_sparks)
        _schedule_inspiration_capture(req, gated)
        return GenerateSparksResponse(sparks=gated, total=len(gated))

    sparks = _generate_local_sparks(req, engine)
    gated = _gate_sparks([_local_spark_to_response(s) for s in sparks])
    _schedule_inspiration_capture(req, gated)

    return GenerateSparksResponse(
        sparks=gated,
        total=len(gated),
    )


@router.post("/store", response_model=SavedInspirationResponse, status_code=201)
async def create_saved_inspiration(req: SavedInspirationCreateRequest) -> SavedInspirationResponse:
    """Persist one Inspiration spark for local reuse."""

    try:
        record = get_inspiration_store().create(
            spark=req.spark.model_dump(mode="json"),
            project_id=req.project_id,
            query=req.query,
            notes=req.notes,
            source=req.source,
            tags=req.tags,
            metadata=req.metadata,
        )
    except (ValueError, InspirationStoreError) as exc:
        raise _store_http_error(exc) from exc
    return _saved_record_response(record)


@router.get("/store", response_model=SavedInspirationListResponse)
async def list_saved_inspirations(
    project_id: str | None = Query(default=None, max_length=160),
    source: InspirationStoreSource | None = Query(default=None),
    tag: str | None = Query(default=None, max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> SavedInspirationListResponse:
    """List saved Inspiration sparks from the local store."""

    try:
        result = get_inspiration_store().list(
            project_id=project_id,
            source=source,
            tag=tag,
            page=page,
            page_size=page_size,
        )
    except (ValueError, InspirationStoreError) as exc:
        raise _store_http_error(exc) from exc
    return SavedInspirationListResponse(
        items=[_saved_record_response(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/store/{saved_id}", response_model=SavedInspirationResponse)
async def get_saved_inspiration(saved_id: str) -> SavedInspirationResponse:
    """Read one saved Inspiration spark."""

    try:
        record = get_inspiration_store().get(saved_id)
    except (ValueError, InspirationStoreError) as exc:
        raise _store_http_error(exc) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"saved inspiration not found: {saved_id}")
    return _saved_record_response(record)


@router.put("/store/{saved_id}", response_model=SavedInspirationResponse)
async def update_saved_inspiration(
    saved_id: str,
    req: SavedInspirationUpdateRequest,
) -> SavedInspirationResponse:
    """Update one saved Inspiration spark."""

    try:
        record = get_inspiration_store().update(
            saved_id,
            spark=req.spark.model_dump(mode="json") if req.spark is not None else None,
            project_id=req.project_id,
            clear_project_id=req.clear_project_id,
            query=req.query,
            notes=req.notes,
            source=req.source,
            tags=req.tags,
            metadata=req.metadata,
        )
    except (ValueError, InspirationStoreError) as exc:
        raise _store_http_error(exc) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"saved inspiration not found: {saved_id}")
    return _saved_record_response(record)


@router.delete("/store/{saved_id}", response_model=DeleteSavedInspirationResponse)
async def delete_saved_inspiration(saved_id: str) -> DeleteSavedInspirationResponse:
    """Delete one saved Inspiration spark."""

    try:
        deleted = get_inspiration_store().delete(saved_id)
    except (ValueError, InspirationStoreError) as exc:
        raise _store_http_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"saved inspiration not found: {saved_id}")
    return DeleteSavedInspirationResponse(saved_id=saved_id, deleted=True)


def _schedule_inspiration_capture(
    req: "GenerateSparksRequest",
    gated: list["SparkResponse"],
) -> None:
    """Fire capture off the request path. See evolution/background.py."""

    try:
        from evolution import run_capture_in_background
    except Exception as exc:  # pragma: no cover - evolution package missing
        logger.debug("evolution package unavailable; capture skipped: %s", exc)
        return
    run_capture_in_background(
        _capture_inspiration_candidates, req, gated, label="inspiration"
    )


def _capture_inspiration_candidates(
    req: "GenerateSparksRequest",
    gated: list["SparkResponse"],
) -> None:
    """Best-effort write of evolution candidates from gated sparks.

    Capture contract:
      - never raises; capture failures degrade to a warning log
      - skipped entirely when evolution.candidate_capture_enabled = false
      - response shape unchanged regardless of outcome
    """

    try:
        from evolution import (
            extract_from_sparks,
            get_evolution_service,
            is_candidate_capture_enabled,
        )
    except Exception as exc:  # pragma: no cover - evolution package missing
        logger.debug("evolution package unavailable; capture skipped: %s", exc)
        return

    if not is_candidate_capture_enabled():
        return

    try:
        args_list = extract_from_sparks(
            gated,
            query=req.query,
            project_id=req.project_id,
        )
    except Exception as exc:
        logger.warning("inspiration capture extractor failed: %s", exc, exc_info=True)
        return
    if not args_list:
        return

    try:
        service = get_evolution_service()
    except Exception as exc:
        logger.warning("evolution service unavailable; capture skipped: %s", exc, exc_info=True)
        return

    captured = 0
    for args in args_list:
        try:
            service.capture(
                workspace_id=args.workspace_id,
                source_type=args.source_type,
                source_id=args.source_id,
                source_summary=args.source_summary,
                memory_type=args.memory_type,
                title=args.title,
                claim=args.claim,
                future_use=args.future_use,
                confidence=args.confidence,
                project_id=args.project_id,
                source_route=args.source_route,
                evidence_refs=args.evidence_refs,
                risk_level=args.risk_level,
            )
            captured += 1
        except Exception as exc:
            logger.warning(
                "inspiration capture write failed for spark %s: %s",
                args.source_id, exc,
                exc_info=True,
            )
    if captured:
        logger.debug("inspiration capture: wrote %d candidate(s) from %d eligible spark(s)",
                     captured, len(args_list))


def _local_spark_to_response(spark: "InspirationSpark") -> SparkResponse:
    """Convert an engine-side InspirationSpark dataclass to the public
    SparkResponse, materializing evidence_refs from evidence_chunks
    (Track B E2 wiring). Per D-EVR-4 never fabricates: when the
    engine spark carries no chunk metadata, evidence_refs stays empty.
    """
    payload = spark.to_dict()
    chunks = payload.pop("evidence_chunks", None)
    response = SparkResponse(**payload)
    if isinstance(chunks, list) and chunks:
        response.evidence_refs = build_spark_evidence_refs(chunks)
    return response


@router.get("/{spark_id}/context", response_model=ContinuationResponse)
async def get_spark_context(spark_id: str):
    """获取启发点的续写上下文。"""
    engine = _get_engine()
    ctx = engine.get_continuation_context(spark_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"启发点不存在或已过期: {spark_id}")
    d = ctx.to_dict()
    return ContinuationResponse(
        spark=SparkResponse(**d["spark"]),
        evidence_texts=d["evidence_texts"],
        causal_chain_summary=d["causal_chain_summary"],
        suggested_angles=d["suggested_angles"],
        related_figures=d["related_figures"],
    )


@router.post("/reload")
async def reload_inspiration_engine():
    """重新加载启发引擎（例如新论文入库后调用）。"""
    reload_engine()
    return {"status": "ok", "message": "InspirationEngine 已重新加载"}
