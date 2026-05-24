"""Unified config/test/discover endpoints for chat and embedding subsystems.

Follows the same pattern as ``rerank_config_router.py`` but uses the shared
``model_config_store`` module. Rerank keeps its own router for backwards
compatibility; this router handles chat + embedding.

Endpoints:
  GET    /api/chat/config              — masked override
  PUT    /api/chat/config              — update override
  DELETE /api/chat/config              — clear (revert to env)
  POST   /api/chat/test                — probe chat completion endpoint
  POST   /api/chat/models/discover     — list models from /v1/models

  GET    /api/embedding/config         — masked override
  PUT    /api/embedding/config         — update override
  DELETE /api/embedding/config         — clear (revert to env)
  POST   /api/embedding/test           — probe embedding endpoint
  POST   /api/embedding/models/discover — list models from /v1/models
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from model_config_store import chat_store, embedding_store, ModelConfigStore, discussion_defaults_store
from models.discussion import DISCUSSION_MAX_TURNS_LIMIT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared Pydantic models
# ---------------------------------------------------------------------------

class ConfigPayload(BaseModel):
    """Public view of a subsystem's runtime override (api_key masked)."""
    provider: str = ""
    base_url: str = ""
    model: str = ""
    has_api_key: bool = False
    api_key_masked: str = ""
    updated_at: str = ""


class ConfigUpdate(BaseModel):
    """Update payload. None on api_key preserves the previously stored key."""
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class ProbeResult(BaseModel):
    ok: bool
    status: int = 0
    error: str = ""
    elapsed_ms: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class DiscoverRequest(BaseModel):
    """POST body for model discovery (api_key in body, not URL)."""
    base_url: str
    api_key: str = ""


class DiscoveredModel(BaseModel):
    id: str
    name: str = ""
    description: str = ""


class DiscoverResult(BaseModel):
    ok: bool
    models: list[DiscoveredModel] = []
    endpoint: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Shared logic
# ---------------------------------------------------------------------------

async def discover_models_from_endpoint(base_url: str, api_key: str) -> DiscoverResult:
    """Hit /v1/models on any OpenAI-compatible endpoint.

    URL-derivation rules (matching cc-switch's build_models_url):
      - "https://api.x.com" -> "https://api.x.com/v1/models"
      - "https://api.x.com/v1" -> "https://api.x.com/v1/models"
      - "https://api.x.com/v1/chat/completions" -> "https://api.x.com/v1/models"
    """
    trimmed = base_url.strip().rstrip("/")
    if not trimmed:
        return DiscoverResult(ok=False, error="Base URL is empty")

    if "/v1/" in trimmed:
        idx = trimmed.rfind("/v1/")
        url = f"{trimmed[: idx + 3]}/models"
    elif trimmed.endswith("/v1"):
        url = f"{trimmed}/models"
    else:
        url = f"{trimmed}/v1/models"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models_list = data.get("data", []) if isinstance(data, dict) else []
        discovered = [
            DiscoveredModel(
                id=m.get("id", ""),
                name=m.get("id", ""),
                description=str(m.get("owned_by") or ""),
            )
            for m in models_list
            if isinstance(m, dict) and m.get("id")
        ]
        discovered.sort(key=lambda m: m.id)
        return DiscoverResult(ok=True, models=discovered, endpoint=url)
    except httpx.HTTPStatusError as exc:
        return DiscoverResult(ok=False, error=f"HTTP {exc.response.status_code}", endpoint=url)
    except httpx.RequestError as exc:
        return DiscoverResult(ok=False, error=f"连接失败: {exc}", endpoint=url)


def _build_config_routes(store: ModelConfigStore, prefix: str, tag: str) -> APIRouter:
    """Factory: create GET/PUT/DELETE /config routes for a subsystem."""
    sub_router = APIRouter(prefix=prefix, tags=[tag])

    @sub_router.get("/config", response_model=ConfigPayload)
    async def get_config() -> ConfigPayload:
        return ConfigPayload(**store.get_public_config())

    @sub_router.put("/config", response_model=ConfigPayload)
    async def put_config(payload: ConfigUpdate) -> ConfigPayload:
        updated = store.write_config(
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=payload.api_key,
            model=payload.model,
        )
        return ConfigPayload(**updated)

    @sub_router.delete("/config", response_model=ConfigPayload)
    async def delete_config() -> ConfigPayload:
        store.clear_config()
        return ConfigPayload(**store.get_public_config())

    return sub_router


# ---------------------------------------------------------------------------
# Chat subsystem
# ---------------------------------------------------------------------------

chat_router = _build_config_routes(chat_store, "/api/chat", "Chat Config")


@chat_router.post("/test", response_model=ProbeResult)
async def test_chat_endpoint(payload: ConfigUpdate) -> ProbeResult:
    """Probe a chat completion endpoint with a minimal request.

    Uses the same URL construction as the real chat path via _build_chat_endpoint.
    """
    base_url = (payload.base_url or chat_store.get_resolved_field("base_url") or "").strip()
    api_key = (payload.api_key or chat_store.get_resolved_field("api_key") or "").strip()
    model = (payload.model or chat_store.get_resolved_field("model") or "").strip()
    provider = (payload.provider or chat_store.get_resolved_field("provider") or "").strip()

    if not base_url:
        return ProbeResult(ok=False, error="base_url is required")

    # Reuse the real chat endpoint URL builder
    try:
        from routers.chat_router import _build_chat_endpoint, _resolve_api_key
        url = _build_chat_endpoint(base_url, provider or "OpenAI")
        resolved_key = _resolve_api_key(provider or "OpenAI", api_key)
    except (ImportError, ValueError):
        # Fallback if import fails
        trimmed = base_url.rstrip("/")
        if "/v1/" in trimmed:
            idx = trimmed.rfind("/v1/")
            url = f"{trimmed[: idx + 3]}/chat/completions"
        elif trimmed.endswith("/v1"):
            url = f"{trimmed}/chat/completions"
        else:
            url = f"{trimmed}/v1/chat/completions"
        resolved_key = api_key

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"

    probe_body = {
        "model": model or "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 1,
        "temperature": 0,
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(url, headers=headers, json=probe_body)
    except httpx.RequestError as exc:
        return ProbeResult(
            ok=False, status=0,
            error=f"连接失败: {exc}",
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    if resp.status_code < 400:
        return ProbeResult(ok=True, status=resp.status_code, elapsed_ms=elapsed_ms)
    body_preview = resp.text[:300] if resp.text else ""
    return ProbeResult(
        ok=False, status=resp.status_code,
        error=body_preview or f"HTTP {resp.status_code}",
        elapsed_ms=elapsed_ms,
    )


@chat_router.post("/models/discover", response_model=DiscoverResult)
async def discover_chat_models(req: DiscoverRequest) -> DiscoverResult:
    """Discover models from a chat/LLM service (api_key in body, not URL)."""
    base_url = req.base_url or chat_store.get_resolved_field("base_url") or ""
    api_key = req.api_key or chat_store.get_resolved_field("api_key") or ""
    return await discover_models_from_endpoint(base_url, api_key)


# ---------------------------------------------------------------------------
# Embedding subsystem
# ---------------------------------------------------------------------------

embedding_router = _build_config_routes(embedding_store, "/api/embedding", "Embedding Config")


@embedding_router.post("/test", response_model=ProbeResult)
async def test_embedding_endpoint(payload: ConfigUpdate) -> ProbeResult:
    """Probe an embedding endpoint using runtime_env helpers for URL construction."""
    base_url = (payload.base_url or embedding_store.get_resolved_field("base_url") or "").strip()
    api_key = (payload.api_key or embedding_store.get_resolved_field("api_key") or "").strip()
    model = (payload.model or embedding_store.get_resolved_field("model") or "").strip()

    if not base_url:
        return ProbeResult(ok=False, error="base_url is required")

    # Use runtime_env helpers if available for URL construction (DashScope compat)
    try:
        from runtime_env import resolve_embedding_request_url, build_embedding_request_payload
        url = resolve_embedding_request_url(base_url, model)
        body = build_embedding_request_payload(["test"], base_url=base_url, model=model)
    except (ImportError, AttributeError):
        # Fallback: standard OpenAI-compatible embedding endpoint
        trimmed = base_url.rstrip("/")
        if trimmed.endswith("/embeddings"):
            url = trimmed
        elif "/v1" in trimmed:
            idx = trimmed.rfind("/v1")
            url = f"{trimmed[: idx + 3]}/embeddings"
        else:
            url = f"{trimmed}/v1/embeddings"
        body = {"input": "test", "model": model or "text-embedding-3-small"}

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.RequestError as exc:
        return ProbeResult(
            ok=False, status=0,
            error=f"连接失败: {exc}",
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    extra: dict[str, Any] = {}
    if resp.status_code < 400:
        try:
            resp_data = resp.json()
            # Extract dimension from first embedding if available
            data_list = resp_data.get("data", [])
            if data_list and isinstance(data_list[0], dict):
                embedding = data_list[0].get("embedding", [])
                if isinstance(embedding, list):
                    extra["dimension"] = len(embedding)
        except Exception:
            pass
        return ProbeResult(ok=True, status=resp.status_code, elapsed_ms=elapsed_ms, extra=extra)

    body_preview = resp.text[:300] if resp.text else ""
    return ProbeResult(
        ok=False, status=resp.status_code,
        error=body_preview or f"HTTP {resp.status_code}",
        elapsed_ms=elapsed_ms,
    )


@embedding_router.post("/models/discover", response_model=DiscoverResult)
async def discover_embedding_models(req: DiscoverRequest) -> DiscoverResult:
    """Discover models from an embedding service (api_key in body, not URL)."""
    base_url = req.base_url or embedding_store.get_resolved_field("base_url") or ""
    api_key = req.api_key or embedding_store.get_resolved_field("api_key") or ""
    return await discover_models_from_endpoint(base_url, api_key)


# ---------------------------------------------------------------------------
# Discussion defaults endpoints (C3a carry-over plan)
# ---------------------------------------------------------------------------

discussion_router = APIRouter(prefix="/api/discussion", tags=["Discussion"])


class DiscussionDefaultsPayload(BaseModel):
    """Discussion defaults settings."""
    auto_stop: bool | None = None
    min_turns: int | None = Field(default=None, ge=1, le=DISCUSSION_MAX_TURNS_LIMIT)
    convergence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    convergence_judge_agent_id: str | None = None
    updated_at: str = ""


@discussion_router.get("/defaults", response_model=DiscussionDefaultsPayload)
async def get_discussion_defaults() -> DiscussionDefaultsPayload:
    """Get stored discussion defaults."""
    settings = discussion_defaults_store.get_settings()
    return DiscussionDefaultsPayload(
        auto_stop=settings.get("auto_stop"),
        min_turns=settings.get("min_turns"),
        convergence_threshold=settings.get("convergence_threshold"),
        convergence_judge_agent_id=settings.get("convergence_judge_agent_id"),
        updated_at=settings.get("updated_at", ""),
    )


@discussion_router.put("/defaults", response_model=DiscussionDefaultsPayload)
async def update_discussion_defaults(payload: DiscussionDefaultsPayload) -> DiscussionDefaultsPayload:
    """Update discussion defaults."""
    updates: dict[str, Any] = {}
    if payload.auto_stop is not None:
        updates["auto_stop"] = payload.auto_stop
    if payload.min_turns is not None:
        updates["min_turns"] = payload.min_turns
    if payload.convergence_threshold is not None:
        updates["convergence_threshold"] = payload.convergence_threshold
    if payload.convergence_judge_agent_id is not None:
        updates["convergence_judge_agent_id"] = payload.convergence_judge_agent_id
    settings = discussion_defaults_store.write_settings(updates)
    return DiscussionDefaultsPayload(
        auto_stop=settings.get("auto_stop"),
        min_turns=settings.get("min_turns"),
        convergence_threshold=settings.get("convergence_threshold"),
        convergence_judge_agent_id=settings.get("convergence_judge_agent_id"),
        updated_at=settings.get("updated_at", ""),
    )


# ---------------------------------------------------------------------------
# Combined router for app registration
# ---------------------------------------------------------------------------

router = APIRouter()
router.include_router(chat_router)
router.include_router(embedding_router)
router.include_router(discussion_router)

__all__ = ["router", "discover_models_from_endpoint"]
