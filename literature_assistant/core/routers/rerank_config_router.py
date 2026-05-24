"""FastAPI routes for the rerank runtime override.

The override is consulted by ``reranker_client._resolve_rerank_targets``
*before* the env / .env fallback so the Settings UI can switch the
project to a local BGE rerank server, a SiliconFlow account, or any
other OpenAI-/Cohere-compatible rerank endpoint without editing files.

Endpoints:

  GET  /api/rerank/config        — return masked override (no api_key)
  PUT  /api/rerank/config        — update the override fields
  DELETE /api/rerank/config      — clear the override entirely (revert to env)
  POST /api/rerank/test          — probe the configured endpoint with a tiny
                                   payload, returning whether it responded
                                   without 4xx/5xx
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import rerank_runtime_config


logger = logging.getLogger("rerank_config_router")

router = APIRouter(prefix="/api/rerank", tags=["Rerank"])


class RerankConfigPayload(BaseModel):
    """Public view of the runtime override; api_key never leaves the box."""

    provider: str = ""
    base_url: str = ""
    model: str = ""
    has_api_key: bool = False
    api_key_masked: str = ""
    updated_at: str = ""


class RerankConfigUpdate(BaseModel):
    """Update payload. None on api_key preserves the previously stored key."""

    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class RerankProbeResult(BaseModel):
    ok: bool
    status: int = 0
    error: str = ""
    elapsed_ms: int = 0


@router.get("/config", response_model=RerankConfigPayload)
async def get_rerank_config() -> RerankConfigPayload:
    return RerankConfigPayload(**rerank_runtime_config.get_public_config())


@router.put("/config", response_model=RerankConfigPayload)
async def put_rerank_config(payload: RerankConfigUpdate) -> RerankConfigPayload:
    updated = rerank_runtime_config.write_config(
        provider=payload.provider,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
    )
    return RerankConfigPayload(**updated)


@router.delete("/config", response_model=RerankConfigPayload)
async def delete_rerank_config() -> RerankConfigPayload:
    rerank_runtime_config.clear_config()
    return RerankConfigPayload(**rerank_runtime_config.get_public_config())


@router.post("/test", response_model=RerankProbeResult)
async def test_rerank_endpoint(payload: RerankConfigUpdate) -> RerankProbeResult:
    """Send a 2-document rerank probe to verify endpoint + key + model.

    Uses the payload if supplied (so the UI can test before saving);
    otherwise reads from the existing override. Does NOT modify the
    stored config.
    """
    base_url = (payload.base_url or rerank_runtime_config.get_resolved_field("base_url") or "").strip()
    api_key = (payload.api_key or rerank_runtime_config.get_resolved_field("api_key") or "").strip()
    model = (payload.model or rerank_runtime_config.get_resolved_field("model") or "").strip()

    if not base_url:
        raise HTTPException(status_code=400, detail="base_url is required")

    probe_body: dict[str, Any] = {
        "model": model or "bge-reranker-v2-m3",
        "query": "ping",
        "documents": ["doc1", "doc2"],
        "top_n": 2,
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    import time as _t

    start = _t.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.post(base_url, headers=headers, json=probe_body)
    except httpx.RequestError as exc:
        return RerankProbeResult(
            ok=False,
            status=0,
            error=f"connection failed: {exc}",
            elapsed_ms=int((_t.monotonic() - start) * 1000),
        )

    elapsed_ms = int((_t.monotonic() - start) * 1000)
    if resp.status_code < 400:
        return RerankProbeResult(ok=True, status=resp.status_code, elapsed_ms=elapsed_ms)
    body_preview = resp.text[:240] if resp.text else ""
    return RerankProbeResult(
        ok=False,
        status=resp.status_code,
        error=body_preview or f"HTTP {resp.status_code}",
        elapsed_ms=elapsed_ms,
    )


@router.post("/models/discover")
async def discover_rerank_models(payload: RerankConfigUpdate) -> dict[str, Any]:
    """Discover models from a rerank service (api_key in body, not URL)."""
    from routers.model_config_router import discover_models_from_endpoint

    base_url = (payload.base_url or rerank_runtime_config.get_resolved_field("base_url") or "").strip()
    api_key = (payload.api_key or rerank_runtime_config.get_resolved_field("api_key") or "").strip()
    result = await discover_models_from_endpoint(base_url, api_key)
    return result.model_dump()


__all__ = ["router"]
