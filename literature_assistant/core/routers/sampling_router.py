from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from literature_assistant.core.llm_defaults import MODEL_MAX_TOKENS, TASK_DEFAULTS
    from literature_assistant.core.model_config_store import (
        CHAT_MODEL_CONTEXT_WINDOW_DEFAULT,
        chat_context_compression_store,
        normalize_chat_context_compression_settings,
    )
    from literature_assistant.core.sampling_storage import load_user_sampling, save_user_sampling
else:
    from llm_defaults import MODEL_MAX_TOKENS, TASK_DEFAULTS
    from model_config_store import (
        CHAT_MODEL_CONTEXT_WINDOW_DEFAULT,
        chat_context_compression_store,
        normalize_chat_context_compression_settings,
    )
    from sampling_storage import load_user_sampling, save_user_sampling

DEFAULTS_VERSION = "2026-07-11"

router = APIRouter(prefix="/sampling", tags=["Sampling"])


class SamplingPayload(BaseModel):
    tasks: dict[str, dict[str, Any]] = Field(default_factory=dict)


def _configured_model_max_tokens() -> int:
    """Return the active frontend/output ceiling from the model context config."""

    settings = normalize_chat_context_compression_settings(
        chat_context_compression_store.get_settings()
    )
    context_window = int(
        settings.get("model_context_window") or CHAT_MODEL_CONTEXT_WINDOW_DEFAULT
    )
    return min(int(MODEL_MAX_TOKENS), context_window)


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
        "model_max_tokens": _configured_model_max_tokens(),
    }


@router.put("")
async def put_sampling(payload: SamplingPayload) -> dict[str, bool]:
    try:
        save_user_sampling(
            payload.tasks,
            max_tokens_limit=_configured_model_max_tokens(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/{task}")
async def delete_sampling(task: str) -> dict[str, bool]:
    tasks = load_user_sampling()
    tasks.pop(task, None)
    save_user_sampling(tasks)
    return {"ok": True}
