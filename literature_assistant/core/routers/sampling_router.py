from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llm_defaults import MODEL_MAX_TOKENS, TASK_DEFAULTS
from sampling_storage import load_user_sampling, save_user_sampling

DEFAULTS_VERSION = "2026-04-21"

router = APIRouter(prefix="/sampling", tags=["Sampling"])


class SamplingPayload(BaseModel):
    tasks: dict[str, dict[str, Any]] = Field(default_factory=dict)


@router.get("")
async def get_sampling() -> dict[str, Any]:
    """Return sampling defaults + user overrides for the Settings page.

    The response includes saved overrides, versioned defaults, per-task
    default sampling values, and the model context upper bound used by Settings.
    """
    return {
        "tasks": load_user_sampling(),
        "defaults_version": DEFAULTS_VERSION,
        "task_defaults": {task: dict(defaults) for task, defaults in TASK_DEFAULTS.items()},
        "model_max_tokens": MODEL_MAX_TOKENS,
    }


@router.put("")
async def put_sampling(payload: SamplingPayload) -> dict[str, bool]:
    try:
        save_user_sampling(payload.tasks)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/{task}")
async def delete_sampling(task: str) -> dict[str, bool]:
    tasks = load_user_sampling()
    tasks.pop(task, None)
    save_user_sampling(tasks)
    return {"ok": True}
