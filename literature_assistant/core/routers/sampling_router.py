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

    Response shape (locked by tests/test_sampling_endpoint_contract.py,
    B8 / 0.1.8.2):
        - tasks: dict[str, dict] — user-saved overrides, {} when none
        - defaults_version: str — bump when TASK_DEFAULTS schema changes
        - task_defaults: dict[task_name, dict[field, value]] — ALWAYS
          carries every registered task (chat, inspiration, extraction,
          summarization, rewrite) with all four fields (temperature,
          top_p, top_k, max_tokens). Frontend FALLBACK_TASK_DEFAULTS is
          a defense-in-depth floor; this endpoint must not rely on it.
        - model_max_tokens: positive int — upper bound for max_tokens
          sliders in the UI.

    Contract regression sentinel: if a future refactor removes a task
    from TASK_DEFAULTS or drops one of the four sampling fields, the
    Settings → 采样策略 panel would silently break (re-introducing the
    2026-05-23 user crash). The contract test pins both invariants.
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
