"""FastAPI routes for the rerank runtime override.

The override is consulted by ``reranker_client._resolve_rerank_targets``
*before* the env / .env fallback so the Settings UI can switch the
project to a local BGE rerank server, a SiliconFlow account, or any
other OpenAI-/Cohere-compatible rerank endpoint without editing files.

Endpoints:

  GET  /api/rerank/config        — return masked override
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
    """Public view of the runtime override with masked credential state."""

    provider: str = ""
    base_url: str = ""
    model: str = ""
    has_api_key: bool = False
    api_key_masked: str = ""
    updated_at: str = ""


class RerankConfigUpdate(BaseModel):
    """Update payload. None for the credential field preserves the stored value."""

    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class RerankCredentialApplyRequest(BaseModel):
    """Apply a saved rerank RuntimeCredential without returning credential material."""

    credential_id: str = Field(min_length=1, max_length=128)


class RerankProbeResult(BaseModel):
    ok: bool
    status: int = 0
    error: str = ""
    elapsed_ms: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class LocalRerankStatusPayload(BaseModel):
    """Snapshot of the local rerank fallback for the Settings UI.

    Rendered as a status chip / badge. ``available=true`` means the
    local fallback can actually be invoked when the API rerank fails;
    ``available=false`` means rerank will degrade to static
    hybrid_score sorting on API failure.

    Frontend rendering hints (non-binding, just what the UI usually
    needs):
      - green chip when available
      - yellow chip when available=false but weights_present=false and
        allow_download=true ("click to download N MB")
      - red chip when disabled or weights missing and no download
      - secondary line: "GPU (RTX 4060)" / "CPU" — show device + source
      - tertiary line: model_name + "Change in Settings → 高级" link

    The ``loaded`` flag exists for engineers debugging cold-start
    latency; UI does not need to surface it.
    """

    available: bool
    disabled: bool
    weights_present: bool
    allow_download: bool
    model_name: str
    device: str
    device_source: str  # "auto_detected" | "env_override"
    max_length: int
    batch_size: int
    loaded: bool
    hf_cache_dir: str


def _extract_rerank_probe_scores(payload: Any, document_count: int) -> list[float]:
    if not isinstance(payload, dict):
        return []

    output = payload.get("output")
    if isinstance(output, dict):
        raw_results = output.get("results")
    else:
        raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []

    scores: list[float] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("relevance_score")
        if not isinstance(index, int) or not 0 <= index < document_count:
            continue
        if not isinstance(score, (int, float)):
            continue
        scores.append(float(score))
    return scores


@router.get("/config", response_model=RerankConfigPayload)
async def get_rerank_config() -> RerankConfigPayload:
    return RerankConfigPayload(**rerank_runtime_config.get_public_config())


@router.get("/local-status", response_model=LocalRerankStatusPayload)
async def get_local_rerank_status() -> LocalRerankStatusPayload:
    """Status of the local rerank fallback (model weights / device / availability).

    Used by Settings UI to render a chip telling the user whether
    rerank will gracefully fall back to a local model when the
    configured API rerank fails. Does NOT load weights — runs in <1 ms
    on a warm process.

    See ``LocalRerankStatusPayload`` docstring for rendering hints.
    """
    try:
        from local_rerank_adapter import get_status
    except ImportError as exc:  # adapter module missing — degrade gracefully
        logger.warning("local_rerank_adapter unavailable: %s", exc)
        return LocalRerankStatusPayload(
            available=False,
            disabled=True,
            weights_present=False,
            allow_download=False,
            model_name="",
            device="cpu",
            device_source="auto_detected",
            max_length=0,
            batch_size=0,
            loaded=False,
            hf_cache_dir="",
        )
    return LocalRerankStatusPayload(**get_status())


@router.put("/config", response_model=RerankConfigPayload)
async def put_rerank_config(payload: RerankConfigUpdate) -> RerankConfigPayload:
    updated = rerank_runtime_config.write_config(
        provider=payload.provider,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
    )
    return RerankConfigPayload(**updated)


@router.post("/config/apply-credential", response_model=RerankConfigPayload)
async def apply_rerank_credential(
    payload: RerankCredentialApplyRequest,
) -> RerankConfigPayload:
    from credential_store import CredentialNotFoundError
    from routers.credentials_router import get_credential_store

    try:
        credential = get_credential_store().get_internal(payload.credential_id)
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "credential_not_found",
                "message": "凭证不存在或已被删除。",
            },
        ) from exc
    if not credential.enabled:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "credential_disabled",
                "message": "选择的凭证已停用，请更换凭证。",
            },
        )
    if credential.category.value != "rerank":
        raise HTTPException(
            status_code=400,
            detail=(
                "credential category mismatch: expected rerank, "
                f"got {credential.category.value}"
            ),
        )

    updated = rerank_runtime_config.write_config(
        provider=credential.provider,
        base_url=credential.base_url,
        api_key=credential.api_key,
        model=credential.model,
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

    try:
        from routers.chat_router import _validate_outbound_llm_base_url

        _validate_outbound_llm_base_url(base_url, "Local LLM")
    except ValueError as exc:
        return RerankProbeResult(ok=False, error=str(exc))

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
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
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
        try:
            scores = _extract_rerank_probe_scores(resp.json(), len(probe_body["documents"]))
        except ValueError:
            scores = []
        if not scores:
            return RerankProbeResult(
                ok=False,
                status=resp.status_code,
                error="重排序接口返回成功状态，但没有返回可用的排序分数",
                elapsed_ms=elapsed_ms,
            )
        return RerankProbeResult(
            ok=True,
            status=resp.status_code,
            elapsed_ms=elapsed_ms,
            extra={"results": len(scores)},
        )
    body_preview = resp.text[:240] if resp.text else ""
    return RerankProbeResult(
        ok=False,
        status=resp.status_code,
        error=body_preview or f"HTTP {resp.status_code}",
        elapsed_ms=elapsed_ms,
    )


@router.post("/models/discover")
async def discover_rerank_models(payload: RerankConfigUpdate) -> dict[str, Any]:
    """Discover models from a rerank service without URL credentials."""
    from routers.model_config_router import discover_models_from_endpoint

    base_url = (payload.base_url or rerank_runtime_config.get_resolved_field("base_url") or "").strip()
    api_key = (payload.api_key or rerank_runtime_config.get_resolved_field("api_key") or "").strip()
    result = await discover_models_from_endpoint(base_url, api_key)
    return result.model_dump()


__all__ = ["router"]
