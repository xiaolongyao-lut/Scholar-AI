# -*- coding: utf-8 -*-
"""Pipeline API Router - Manages synchronous and asynchronous pipeline execution."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from uuid import uuid4
from typing import Any, Mapping, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from models import (
    PipelineRequest,
    PipelineTaskSubmitResponse,
    PipelineTaskStatusResponse,
    TaskState,
)

logger = logging.getLogger("PipelineRouter")
router = APIRouter(tags=["Pipeline"])

# Global task cache (moved from main adapter)
TASKS: dict[str, dict[str, Any]] = {}
TASKS_LOCK = asyncio.Lock()
TASK_RETENTION_SECONDS = int(os.environ.get("PIPELINE_TASK_RETENTION_SECONDS", "1800"))
TASK_MAX_CACHE = int(os.environ.get("PIPELINE_TASK_MAX_CACHE", "200"))


def _now_ts() -> float:
    """Return current POSIX timestamp."""
    return time.time()


def _task_terminal(status: str) -> bool:
    """Return True when a task is no longer running."""
    return status in (TaskState.succeeded.value, TaskState.failed.value)


async def _cleanup_tasks_locked() -> None:
    """Purge expired terminal tasks and cap cache size."""
    now = _now_ts()
    removable: list[str] = []
    for task_id, item in TASKS.items():
        status = str(item.get("status", ""))
        updated_at = float(item.get("updated_at", 0.0) or 0.0)
        expired = (now - updated_at) > TASK_RETENTION_SECONDS if updated_at else False
        if _task_terminal(status) and expired:
            removable.append(task_id)

    for task_id in removable:
        TASKS.pop(task_id, None)

    if len(TASKS) <= TASK_MAX_CACHE:
        return

    terminal_items = sorted(
        (
            (task_id, float(item.get("updated_at", 0.0) or 0.0))
            for task_id, item in TASKS.items()
            if _task_terminal(str(item.get("status", "")))
        ),
        key=lambda entry: entry[1],
    )
    overflow = len(TASKS) - TASK_MAX_CACHE
    for task_id, _ in terminal_items[:overflow]:
        TASKS.pop(task_id, None)


def _run_pipeline_sync(request: PipelineRequest) -> dict[str, Any]:
    """Run the synchronous pipeline and enrich the result with optional association output."""
    result = _run_pipeline_core(request)
    return _augment_pipeline_result(result, request)


def _run_pipeline_core(request: PipelineRequest) -> dict[str, Any]:
    """Run the underlying pipeline core with validated request fields."""
    try:
        from integrated_pipeline import run_pipeline
        from python_adapter_server import get_pipeline_observer
    except ImportError:
        raise HTTPException(status_code=501, detail="Pipeline engine not available in this environment")

    input_path = str(request.input_path).strip()
    goal = str(request.goal).strip()
    if not input_path:
        raise ValueError("input_path must be non-empty")
    if not goal:
        raise ValueError("goal must be non-empty")

    observer = get_pipeline_observer()
    
    # Standard v4.0 pipeline expects (pdf_path, goal, output_dir, observer)
    return run_pipeline(
        pdf_path=input_path,
        goal=goal,
        output_dir=request.output_dir or "output",
        observer=observer
    )


def _read_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk when present, otherwise return an empty mapping."""
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load pipeline artifact %s: %s", path, exc)
        return {}


def _trim_text(value: Any, limit: int = 220) -> str:
    """Normalize a bounded preview string for runtime drafting context."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _collect_pipeline_retrieval_hits(output_dir: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Read retrieval artifacts emitted by the pipeline and normalize them for association use."""
    output_root = Path(output_dir)
    retrieval_payload = _read_json_file(output_root / "02_hybrid_retrieval.json")
    raw_focus_points = retrieval_payload.get("focus_points", [])
    focus_points = [
        str(item).strip()
        for item in raw_focus_points
        if isinstance(item, str) and item.strip()
    ]

    retrieval_hits: list[dict[str, Any]] = []
    raw_chunks = retrieval_payload.get("top_chunks", [])
    if isinstance(raw_chunks, list):
        for index, raw_chunk in enumerate(raw_chunks, start=1):
            if not isinstance(raw_chunk, Mapping):
                continue
            text = str(
                raw_chunk.get("text")
                or raw_chunk.get("claim")
                or raw_chunk.get("content")
                or ""
            ).strip()
            if not text:
                continue
            metadata = raw_chunk.get("metadata", {})
            if not isinstance(metadata, Mapping):
                metadata = {}
            retrieval_hits.append(
                {
                    "id": str(raw_chunk.get("id") or raw_chunk.get("source") or f"pipeline_hit_{index}").strip(),
                    "text": text,
                    "source": str(
                        raw_chunk.get("source")
                        or metadata.get("title")
                        or metadata.get("document_keyword")
                        or f"pipeline_hit_{index}"
                    ).strip(),
                    "score": raw_chunk.get("hybrid_score", raw_chunk.get("score", 0.0)),
                    "metadata": dict(metadata),
                }
            )
    return focus_points, retrieval_hits


def _collect_scoring_hits(scoring_payload: Mapping[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Convert scoring artifacts into retrieval-like hits for associative writing."""
    scoring_root = (
        scoring_payload.get("scoring")
        if isinstance(scoring_payload.get("scoring"), Mapping)
        else scoring_payload
    )
    if not isinstance(scoring_root, Mapping):
        return [], []

    focus_points: list[str] = []
    scoring_hits: list[dict[str, Any]] = []

    raw_themes = scoring_root.get("semantic_themes", [])
    if isinstance(raw_themes, list):
        for index, raw_theme in enumerate(raw_themes[:2], start=1):
            if not isinstance(raw_theme, Mapping):
                continue
            theme_title = str(raw_theme.get("theme_title", "")).strip()
            summary = str(raw_theme.get("summary", "")).strip()
            if theme_title:
                focus_points.append(theme_title)
            if not summary:
                continue
            scoring_hits.append(
                {
                    "id": f"theme_{index}_{theme_title or 'analysis'}",
                    "text": summary,
                    "source": f"Theme: {theme_title or 'analysis'}",
                    "score": 0.72,
                    "metadata": {
                        "analysis_origin": "academic_scoring",
                        "theme_title": theme_title,
                        "artifact": "03_academic_scoring.json",
                    },
                }
            )

    raw_points = scoring_root.get("selected_writing_points", [])
    if isinstance(raw_points, list):
        for index, raw_point in enumerate(raw_points[:4], start=1):
            if not isinstance(raw_point, Mapping):
                continue
            claim = str(raw_point.get("claim") or raw_point.get("source_text") or "").strip()
            if not claim:
                continue
            point_type = str(raw_point.get("point_type", "")).strip() or "analysis"
            scoring_hits.append(
                {
                    "id": str(raw_point.get("writing_point_id") or f"scoring_point_{index}").strip(),
                    "text": claim,
                    "source": f"Scoring: {point_type}",
                    "score": raw_point.get("relevance_score", 0.0),
                    "metadata": {
                        "analysis_origin": "academic_scoring",
                        "point_type": point_type,
                        "goal_hits": list(raw_point.get("goal_hits", []))
                        if isinstance(raw_point.get("goal_hits"), list)
                        else [],
                        "artifact": "03_academic_scoring.json",
                    },
                }
            )
    return focus_points, scoring_hits


def _collect_pipeline_analysis_payloads(output_dir: str) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Load optional analysis artifacts that can enrich writing association output."""
    output_root = Path(output_dir)
    analysis_payloads: list[dict[str, Any]] = []
    focus_points: list[str] = []
    retrieval_hits: list[dict[str, Any]] = []

    scoring_payload = _read_json_file(output_root / "03_academic_scoring.json")
    if scoring_payload:
        analysis_payloads.append(scoring_payload)
        scoring_focus, scoring_hits = _collect_scoring_hits(scoring_payload)
        focus_points.extend(scoring_focus)
        retrieval_hits.extend(scoring_hits)

    for filename in (
        "04_reasoning_chain.json",
        "04_association_output.json",
        "04_cross_paper_analysis.json",
        "05_reasoning_chain.json",
        "05_association_output.json",
        "05_cross_paper_analysis.json",
    ):
        payload = _read_json_file(output_root / filename)
        if payload:
            analysis_payloads.append(payload)

    return analysis_payloads, focus_points, retrieval_hits


def _merge_pipeline_hits(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge retrieval-like hit groups while preserving order and removing duplicates."""
    merged_hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for hit in group:
            if not isinstance(hit, Mapping):
                continue
            hit_id = str(hit.get("id", "")).strip()
            hit_text = _trim_text(hit.get("text", ""), 240)
            if not hit_text:
                continue
            key = (hit_id, hit_text)
            if key in seen:
                continue
            seen.add(key)
            merged_hits.append(dict(hit))
    return merged_hits


def _build_pipeline_draft_seed(goal: str, focus_points: list[str], retrieval_hits: list[dict[str, Any]]) -> str:
    """Create a bounded draft seed so the writing layer can attach association output."""
    focus_text = "、".join(point for point in focus_points[:4] if point)
    retrieval_preview = "\n".join(
        f"- {hit.get('source', 'retrieval')}: {_trim_text(hit.get('text', ''), 140)}"
        for hit in retrieval_hits[:3]
    )
    segments = [
        f"Pipeline goal: {goal.strip()}",
        f"Focus points: {focus_text}" if focus_text else "",
        f"Retrieved evidence:\n{retrieval_preview}" if retrieval_preview else "",
    ]
    return "\n".join(segment for segment in segments if segment).strip()


def _resolve_pipeline_memory_hits(request: PipelineRequest, association_query: str) -> list[dict[str, Any]]:
    """Optionally retrieve memory hits for pipeline association output."""
    if not request.association_use_memory:
        return []
    try:
        from python_adapter_server import get_memory_adapter
    except Exception as exc:
        logger.warning("Memory adapter unavailable for pipeline association: %s", exc)
        return []

    adapter = get_memory_adapter()
    if adapter is None:
        return []

    try:
        response = adapter.search(
            query=association_query,
            wing=request.association_wing,
            room=request.association_room,
            limit=request.association_memory_limit,
        )
    except Exception as exc:
        logger.warning("Pipeline association memory lookup failed: %s", exc)
        return []

    if response is None or not getattr(response, "available", False):
        return []

    normalized_hits: list[dict[str, Any]] = []
    for raw_hit in getattr(response, "results", []):
        if hasattr(raw_hit, "to_dict"):
            raw_payload = raw_hit.to_dict()
        elif isinstance(raw_hit, Mapping):
            raw_payload = dict(raw_hit)
        else:
            continue
        if isinstance(raw_payload, dict):
            normalized_hits.append(raw_payload)
    return normalized_hits


def _resolve_pipeline_ai_adapter() -> Any | None:
    """Reuse the association AI adapter strategy from the resources layer."""
    try:
        from routers.resources_router import get_ai_adapter

        return get_ai_adapter()
    except Exception as exc:
        logger.warning("Association AI adapter unavailable for pipeline: %s", exc)
        return None


def _build_pipeline_association_bundle(
    pipeline_result: dict[str, Any],
    request: PipelineRequest,
) -> dict[str, Any] | None:
    """Build an association bundle from pipeline artifacts without mutating core results."""
    if not request.include_association:
        return None

    output_dir = str(pipeline_result.get("output_dir", "")).strip()
    if not output_dir:
        return None

    try:
        from writing_resources import (
            build_association_bundle_from_runtime_context,
            apply_analysis_enrichment_to_bundle,
        )
    except Exception as exc:
        logger.warning("Writing resource layer unavailable for pipeline association: %s", exc)
        return None

    association_query = (
        request.association_query.strip()
        if isinstance(request.association_query, str) and request.association_query.strip()
        else request.goal.strip()
    )
    focus_points, retrieval_hits = _collect_pipeline_retrieval_hits(output_dir)
    analysis_payloads, analysis_focus_points, analysis_hits = _collect_pipeline_analysis_payloads(output_dir)
    merged_focus_points = list(
        dict.fromkeys([*focus_points, *[point for point in analysis_focus_points if point]])
    )
    merged_retrieval_hits = _merge_pipeline_hits(retrieval_hits, analysis_hits)
    draft_seed = _build_pipeline_draft_seed(request.goal, merged_focus_points, merged_retrieval_hits)
    memory_hits = _resolve_pipeline_memory_hits(request, association_query)

    try:
        # 1. Build base bundle WITHOUT analysis enrichment first
        base_bundle, ephemeral = build_association_bundle_from_runtime_context(
            query=association_query,
            draft_seed=draft_seed,
            focused_points=merged_focus_points,
            retrieval_hits=merged_retrieval_hits,
            memory_hits=memory_hits,
            analysis_payloads=None,  # Delayed
            mode=request.association_mode,
            project_id=request.association_project_id,
            draft_id=request.association_draft_id,
            section_id=request.association_section_id,
            ai_adapter=_resolve_pipeline_ai_adapter(),
        )

        # 2. Apply enrichment and detect actual increment using unified helper
        enriched_bundle, was_enriched = apply_analysis_enrichment_to_bundle(
            base_bundle, analysis_payloads=analysis_payloads
        )

    except Exception as exc:
        logger.warning("Pipeline association bundle build failed: %s", exc)
        return None

    payload = enriched_bundle.to_dict()
    payload["ephemeral_project"] = ephemeral
    payload["source"] = "pipeline"
    payload["analysis_enriched"] = was_enriched
    return payload


def _augment_pipeline_result(pipeline_result: dict[str, Any], request: PipelineRequest) -> dict[str, Any]:
    """Attach optional association output to the pipeline result envelope."""
    result = dict(pipeline_result)
    association_bundle = _build_pipeline_association_bundle(result, request)
    if association_bundle is not None:
        result["association_bundle"] = association_bundle
    return result


async def _run_pipeline_async(task_id: str, request: PipelineRequest) -> None:
    """Execute the pipeline in the background and persist terminal result."""
    async with TASKS_LOCK:
        TASKS[task_id]["status"] = TaskState.running.value
        TASKS[task_id]["progress"] = 0.1
        TASKS[task_id]["stage"] = "running"
        TASKS[task_id]["updated_at"] = _now_ts()

    try:
        result = await asyncio.to_thread(_run_pipeline_sync, request)
        async with TASKS_LOCK:
            TASKS[task_id]["status"] = TaskState.succeeded.value
            TASKS[task_id]["progress"] = 1.0
            TASKS[task_id]["stage"] = "completed"
            TASKS[task_id]["result"] = result
            TASKS[task_id]["error"] = None
            TASKS[task_id]["updated_at"] = _now_ts()
            await _cleanup_tasks_locked()
    except Exception as exc:
        logger.error("Async pipeline task failed: %s", exc, exc_info=True)
        async with TASKS_LOCK:
            TASKS[task_id]["status"] = TaskState.failed.value
            TASKS[task_id]["progress"] = 1.0
            TASKS[task_id]["stage"] = "failed"
            TASKS[task_id]["result"] = None
            TASKS[task_id]["error"] = str(exc)
            TASKS[task_id]["updated_at"] = _now_ts()
            await _cleanup_tasks_locked()


@router.post("/run")
async def run_pipeline_endpoint(request: PipelineRequest) -> dict[str, Any]:
    """Run the pipeline synchronously."""
    logger.info("Received pipeline request for %s", request.input_path)
    try:
        return await asyncio.to_thread(_run_pipeline_sync, request)
    except Exception as exc:
        logger.error("Pipeline execution failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/run_async", response_model=PipelineTaskSubmitResponse)
async def run_pipeline_async_endpoint(request: PipelineRequest) -> PipelineTaskSubmitResponse:
    """Submit an asynchronous pipeline job."""
    logger.info("Received async pipeline request for %s", request.input_path)
    task_id = uuid4().hex
    async with TASKS_LOCK:
        await _cleanup_tasks_locked()
        TASKS[task_id] = {
            "status": TaskState.queued.value,
            "progress": 0.0,
            "stage": "queued",
            "result": None,
            "error": None,
            "updated_at": _now_ts(),
        }
    asyncio.create_task(_run_pipeline_async(task_id, request))
    return PipelineTaskSubmitResponse(task_id=task_id, status=TaskState.queued.value)


@router.get("/task/{task_id}", response_model=PipelineTaskStatusResponse)
async def get_pipeline_task_status(task_id: str) -> PipelineTaskStatusResponse:
    """Return async task status by task ID."""
    async with TASKS_LOCK:
        await _cleanup_tasks_locked()
        task = TASKS.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
        task["updated_at"] = _now_ts()
        return PipelineTaskStatusResponse(
            task_id=task_id,
            status=str(task.get("status", TaskState.failed.value)),
            progress=float(task.get("progress", 0.0) or 0.0),
            stage=str(task.get("stage", "queued")),
            result=task.get("result"),
            error=task.get("error"),
        )
