# -*- coding: utf-8 -*-
"""Pipeline API Router - Manages synchronous and asynchronous pipeline execution."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from uuid import uuid4
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException
from project_paths import output_path
from models import (
    PipelineRequest,
    PipelineTaskSubmitResponse,
    PipelineTaskStatusResponse,
    TaskState,
    BatchProcessRequest,
)

logger = logging.getLogger("PipelineRouter")
router = APIRouter(tags=["Pipeline"], prefix="/pipeline")

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
    except ImportError as exc:
        raise HTTPException(status_code=501, detail="Pipeline engine not available in this environment") from exc

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
        output_dir=request.output_dir or str(output_path()),
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
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load pipeline artifact %s: %s", path, exc)
        return {}


def _trim_text(value: Any, limit: int = 220) -> str:
    """Normalize a bounded preview string for runtime drafting context."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _extract_pipeline_artifacts(pipeline_result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a shallow copy of any in-memory pipeline artifacts."""
    if not isinstance(pipeline_result, Mapping):
        return {}

    artifacts: dict[str, Any] = {}
    raw_artifacts = pipeline_result.get("artifacts")
    if isinstance(raw_artifacts, Mapping):
        artifacts.update(dict(raw_artifacts))

    for key in ("retrieval_payload", "scoring_payload", "analysis_payloads", "focus_points"):
        value = pipeline_result.get(key)
        if value is not None and key not in artifacts:
            artifacts[key] = value

    return artifacts


def _normalize_retrieval_payload(retrieval_payload: Mapping[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Normalize retrieval payload fields into focus points and hits."""
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


def _collect_pipeline_retrieval_hits(
    output_dir: str,
    pipeline_result: Mapping[str, Any] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Read retrieval artifacts emitted by the pipeline and normalize them for association use."""
    artifacts = _extract_pipeline_artifacts(pipeline_result)
    retrieval_payload = artifacts.get("retrieval_payload")
    if isinstance(retrieval_payload, Mapping):
        return _normalize_retrieval_payload(retrieval_payload)

    output_root = Path(output_dir)
    retrieval_payload = _read_json_file(output_root / "02_hybrid_retrieval.json")
    return _normalize_retrieval_payload(retrieval_payload)


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


def _collect_pipeline_analysis_payloads(
    output_dir: str,
    pipeline_result: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Load optional analysis artifacts that can enrich writing association output."""
    output_root = Path(output_dir)
    analysis_payloads: list[dict[str, Any]] = []
    focus_points: list[str] = []
    retrieval_hits: list[dict[str, Any]] = []

    artifacts = _extract_pipeline_artifacts(pipeline_result)
    raw_analysis_payloads = artifacts.get("analysis_payloads")
    if isinstance(raw_analysis_payloads, list):
        for payload in raw_analysis_payloads:
            if not isinstance(payload, Mapping):
                continue
            payload_dict = dict(payload)
            analysis_payloads.append(payload_dict)
            scoring_focus, scoring_hits = _collect_scoring_hits(payload_dict)
            focus_points.extend(scoring_focus)
            retrieval_hits.extend(scoring_hits)
    else:
        scoring_payload = artifacts.get("scoring_payload")
        if not isinstance(scoring_payload, Mapping):
            scoring_payload = _read_json_file(output_root / "03_academic_scoring.json")
        if scoring_payload:
            payload_dict = dict(scoring_payload)
            analysis_payloads.append(payload_dict)
            scoring_focus, scoring_hits = _collect_scoring_hits(payload_dict)
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
    except ImportError as exc:
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
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
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
    except ImportError as exc:
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
    except ImportError as exc:
        logger.warning("Writing resource layer unavailable for pipeline association: %s", exc)
        return None

    association_query = (
        request.association_query.strip()
        if isinstance(request.association_query, str) and request.association_query.strip()
        else request.goal.strip()
    )
    focus_points, retrieval_hits = _collect_pipeline_retrieval_hits(output_dir, pipeline_result)
    analysis_payloads, analysis_focus_points, analysis_hits = _collect_pipeline_analysis_payloads(output_dir, pipeline_result)
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

    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
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
    except HTTPException as exc:
        logger.error("Async pipeline task failed with HTTPException: %s", exc, exc_info=True)
        async with TASKS_LOCK:
            TASKS[task_id]["status"] = TaskState.failed.value
            TASKS[task_id]["progress"] = 1.0
            TASKS[task_id]["stage"] = "failed"
            TASKS[task_id]["result"] = None
            TASKS[task_id]["error"] = str(exc.detail)
            TASKS[task_id]["updated_at"] = _now_ts()
            await _cleanup_tasks_locked()
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.error("Async pipeline task failed: %s", exc, exc_info=True)
        async with TASKS_LOCK:
            TASKS[task_id]["status"] = TaskState.failed.value
            TASKS[task_id]["progress"] = 1.0
            TASKS[task_id]["stage"] = "failed"
            TASKS[task_id]["result"] = None
            TASKS[task_id]["error"] = str(exc)
            TASKS[task_id]["updated_at"] = _now_ts()
            await _cleanup_tasks_locked()


# ---------------------------------------------------------------------------
# Plan v2 §13.1d.1 / §13.1d.2 — keypool health snapshot endpoint.
# Read-only; never returns api_key. Returns disabled marker when KeyPool is
# disabled via LITERATURE_DISABLE_KEY_POOL=1 (orthogonal disable flag).

def _safe_get_pool_stats() -> dict[str, Any]:
    """Return ``key_pool.get_pool().stats()`` if the pool is reachable,
    otherwise a structured ``disabled`` marker. Never raises."""
    if os.environ.get("LITERATURE_DISABLE_KEY_POOL") == "1":
        return {"disabled": True, "reason": "LITERATURE_DISABLE_KEY_POOL=1"}
    try:
        from key_pool import get_pool
        return get_pool().stats()
    except FileNotFoundError:
        return {"disabled": True, "reason": "no .env found"}
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("pipeline/status: keypool stats unreachable: %s", exc)
        return {"disabled": True, "reason": f"{type(exc).__name__}: {exc}"}


@router.get("/status")
async def get_pipeline_status() -> dict[str, Any]:
    """Read-only health snapshot for pipeline-adjacent state.

    Plan v2 §13.1d.1: exposes generation pool's ``primary_key_active``,
    ``credentials_in_cooldown``, ``last_failure_class`` so a release gate
    or monitoring view can flag a degraded run without reading log files.

    Plan v2 §13.1d.2: includes ``exhausted_count`` per category — any
    value >0 in a single eval run is a release-blocker signal upstream.

    Response shape::

        {
          "keypool": {"pools": [{"category": "generation", ...}, ...]},
          "task_cache": {"size": N, "retention_seconds": ..., "max_cache": ...}
        }

    No secrets in the response. Endpoint never raises; failure to read
    the pool is encoded as ``keypool.disabled`` with a reason field.
    """
    async with TASKS_LOCK:
        task_cache_size = len(TASKS)
    return {
        "keypool": _safe_get_pool_stats(),
        "task_cache": {
            "size": task_cache_size,
            "retention_seconds": TASK_RETENTION_SECONDS,
            "max_cache": TASK_MAX_CACHE,
        },
    }


@router.post("/run")
async def run_pipeline_endpoint(request: PipelineRequest) -> dict[str, Any]:
    """Run the pipeline synchronously."""
    logger.info("Received pipeline request for %s", request.input_path)
    try:
        return await asyncio.to_thread(_run_pipeline_sync, request)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
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


async def _update_batch_task_progress(task_id: str, progress: float, stage: str) -> None:
    """Update batch task progress from controller callbacks."""
    async with TASKS_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        if str(task.get("status")) != TaskState.running.value:
            return
        task["progress"] = max(0.0, min(100.0, float(progress)))
        if stage:
            task["stage"] = stage
        task["updated_at"] = _now_ts()


async def _run_batch_processing_task(task_id: str, pdf_folder: str, output_root: str, 
                                      goal: str, batch_size: int = 13) -> None:
    """Execute batch processing in async context and update task state."""
    try:
        async with TASKS_LOCK:
            TASKS[task_id]["status"] = TaskState.running.value
            TASKS[task_id]["stage"] = "Processing PDFs"
            TASKS[task_id]["progress"] = 0.0
            TASKS[task_id]["updated_at"] = _now_ts()
        
        # Import batch controller
        from batch_controller import BatchProcessController

        loop = asyncio.get_running_loop()

        def _progress_callback(raw_progress: float, stage: str) -> None:
            value = float(raw_progress)
            normalized = value * 100.0 if 0.0 <= value <= 1.0 else value
            loop.call_soon_threadsafe(
                asyncio.create_task,
                _update_batch_task_progress(task_id, normalized, stage),
            )
        
        # Run batch processing in thread pool
        def _batch_sync():
            controller = BatchProcessController(
                pdf_folder=pdf_folder,
                output_root=output_root,
                goal=goal,
                batch_size=batch_size,
                enable_llm=True,
                progress_callback=_progress_callback,
            )
            report = controller.process_batch()
            return report
        
        report = await asyncio.to_thread(_batch_sync)
        
        async with TASKS_LOCK:
            TASKS[task_id]["status"] = TaskState.succeeded.value
            TASKS[task_id]["stage"] = "Completed"
            TASKS[task_id]["progress"] = 100.0
            TASKS[task_id]["result"] = {
                "batch_report": report,
                "message": "Batch processing completed successfully"
            }
            TASKS[task_id]["updated_at"] = _now_ts()
            await _cleanup_tasks_locked()
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.error("Batch processing task %s failed: %s", task_id, exc, exc_info=True)
        async with TASKS_LOCK:
            TASKS[task_id]["status"] = TaskState.failed.value
            TASKS[task_id]["stage"] = "Failed"
            TASKS[task_id]["error"] = str(exc)
            TASKS[task_id]["updated_at"] = _now_ts()
            await _cleanup_tasks_locked()


@router.post("/batch/submit", response_model=PipelineTaskSubmitResponse)
async def submit_batch_processing(request: BatchProcessRequest) -> PipelineTaskSubmitResponse:
    """Submit a batch PDF processing job."""
    logger.info("Received batch processing request for folder %s", request.pdf_folder)
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
            "task_type": "batch_processing",
            "pdf_folder": request.pdf_folder,
            "output_root": request.output_root,
        }
    asyncio.create_task(_run_batch_processing_task(task_id, request.pdf_folder, request.output_root, request.goal, request.batch_size))
    return PipelineTaskSubmitResponse(task_id=task_id, status=TaskState.queued.value)

