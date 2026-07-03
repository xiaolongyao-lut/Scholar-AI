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

import asyncio
import hashlib
import json
import logging
import math
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from provider_capabilities import (
    CAPABILITY_STATUS_AUTH_REQUIRED,
    CAPABILITY_STATUS_PROBE_FAILED,
    CAPABILITY_STATUS_TOOL_CALL_OK,
    provider_capability_store,
)
from model_config_store import (
    CHAT_CONTEXT_COMPRESSION_KEEP_RECENT_DEFAULT,
    CHAT_CONTEXT_COMPRESSION_KEEP_RECENT_MAX,
    CHAT_CONTEXT_COMPRESSION_KEEP_RECENT_MIN,
    CHAT_CONTEXT_COMPRESSION_TARGET_DEFAULT,
    CHAT_CONTEXT_COMPRESSION_TARGET_MAX,
    CHAT_CONTEXT_COMPRESSION_TARGET_MIN,
    CHAT_CONTEXT_COMPRESSION_TRIGGER_DEFAULT,
    CHAT_CONTEXT_COMPRESSION_TRIGGER_MAX,
    CHAT_CONTEXT_COMPRESSION_TRIGGER_MIN,
    chat_context_compression_store,
    chat_store,
    discussion_defaults_store,
    embedding_store,
    ModelConfigStore,
    normalize_chat_context_compression_settings,
)
from models.discussion import DISCUSSION_MAX_TURNS_LIMIT
from provider_payload_compat import apply_openai_chat_payload_compat, provider_http_timeout_s

logger = logging.getLogger(__name__)

_EMBEDDING_CONTRACT_SCHEMA_VERSION = "scholar-ai-embedding-contract/v1"
_EMBEDDING_INPUT_BUILDER_VERSION = "runtime_env.build_embedding_request_payload/v1"
_EMBEDDING_NORMALIZATION_VERSION = "observed_l2_norm/v1"
_EMBEDDING_TRUNCATION_VERSION = "probe_sample_no_truncation/v1"


def _probe_error_response(
    *,
    status: int,
    elapsed_ms: int,
    error: str,
    extra: dict[str, Any] | None = None,
) -> ProbeResult:
    return ProbeResult(
        ok=False,
        status=status,
        error=error,
        elapsed_ms=elapsed_ms,
        extra=extra or {},
    )


def _extract_chat_probe_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return ""
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                text_parts = [
                    part.get("text", "").strip()
                    for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                ]
                joined = "".join(text_parts).strip()
                if joined:
                    return joined
        text = choice.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _embedding_vectors_from_payload(payload: Any) -> list[list[float]]:
    try:
        from runtime_env import extract_embedding_vectors
    except (ImportError, AttributeError):
        return []
    raw_vectors = extract_embedding_vectors(payload)
    vectors: list[list[float]] = []
    for raw_vector in raw_vectors:
        if (
            isinstance(raw_vector, list)
            and raw_vector
            and all(isinstance(value, (int, float)) for value in raw_vector)
        ):
            vectors.append([float(value) for value in raw_vector])
    return vectors


def _embedding_response_model_from_payload(payload: Any) -> str | None:
    """Return the provider-reported embedding model when the response exposes it.

    Args:
        payload: JSON-decoded provider response object.

    Returns:
        A non-empty model id string, or None when the provider omits it.
    """
    if not isinstance(payload, dict):
        return None
    top_level_model = payload.get("model")
    if isinstance(top_level_model, str) and top_level_model.strip():
        return top_level_model.strip()
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            item_model = item.get("model")
            if isinstance(item_model, str) and item_model.strip():
                return item_model.strip()
    output = payload.get("output")
    if isinstance(output, dict):
        output_model = output.get("model")
        if isinstance(output_model, str) and output_model.strip():
            return output_model.strip()
    return None


def _embedding_vectors_are_l2_normalized(vectors: list[list[float]]) -> bool | None:
    """Infer whether returned dense vectors are already L2-normalized.

    Args:
        vectors: Dense embedding vectors extracted from a provider response.

    Returns:
        True when every non-zero probe vector has unit L2 norm within tolerance;
        False when at least one vector is clearly not unit-normalized; None when
        no non-zero vector is available.
    """
    if not isinstance(vectors, list) or not vectors:
        return None
    observed = False
    for vector in vectors:
        if not vector:
            continue
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 1e-12:
            continue
        observed = True
        if abs(norm - 1.0) > 1e-3:
            return False
    return True if observed else None


def _embedding_representation_mode(base_url: str, model: str, vectors: list[list[float]]) -> str:
    """Classify the observed embedding representation for index-contract gating.

    Args:
        base_url: Configured provider base URL.
        model: Requested embedding model id.
        vectors: Dense vectors extracted from the probe response.

    Returns:
        A stable representation mode string. Current runtime extraction only
        accepts dense vectors; multimodal providers are flagged separately.
    """
    if not vectors:
        raise ValueError("vectors must contain at least one dense vector")
    try:
        from runtime_env import is_dashscope_multimodal_embedding_config

        if is_dashscope_multimodal_embedding_config(base_url, model):
            return "multimodal-dense"
    except (ImportError, AttributeError):
        pass
    lowered_model = model.strip().lower()
    if any(token in lowered_model for token in ("multimodal", "vl-embedding", "vision")):
        return "multimodal-dense"
    return "dense"


def _build_embedding_contract_extra(
    *,
    provider: str,
    base_url: str,
    requested_model: str,
    response_model: str | None,
    vectors: list[list[float]],
) -> dict[str, Any]:
    """Build a redacted, deterministic Phase-0 embedding contract diagnostic.

    Args:
        provider: User-visible provider label.
        base_url: Configured provider base URL. Only a hash id is emitted.
        requested_model: Model id sent in the embedding request.
        response_model: Provider-reported model id when present.
        vectors: Dense vectors extracted from the probe response.

    Returns:
        JSON-safe fields suitable for ``ProbeResult.extra``.

    Raises:
        ValueError: If required inputs are missing or vector dimensions are
        inconsistent.
    """
    normalized_provider = provider.strip() or "Local LLM"
    normalized_model = requested_model.strip()
    if not normalized_model:
        raise ValueError("requested_model must be a non-empty string")
    if not vectors:
        raise ValueError("vectors must contain at least one dense vector")
    dim = len(vectors[0])
    if dim <= 0:
        raise ValueError("embedding dimension must be positive")
    if any(len(vector) != dim for vector in vectors):
        raise ValueError("embedding vectors must have a consistent dimension")

    base_url_id = hashlib.sha256(base_url.strip().rstrip("/").encode("utf-8")).hexdigest()[:16]
    contract: dict[str, Any] = {
        "contract_schema_version": _EMBEDDING_CONTRACT_SCHEMA_VERSION,
        "provider": normalized_provider,
        "base_url_id": base_url_id,
        "requested_model": normalized_model,
        "provider_response_model": response_model,
        "dim": dim,
        "representation_mode": _embedding_representation_mode(base_url, normalized_model, vectors),
        "normalize": _embedding_vectors_are_l2_normalized(vectors),
        "distance_metric": "cosine",
        "instruction_template": "none",
        "max_length": None,
        "truncation_policy": "probe_sample_no_truncation",
        "embedding_input_builder_version": _EMBEDDING_INPUT_BUILDER_VERSION,
        "normalization_version": _EMBEDDING_NORMALIZATION_VERSION,
        "truncation_version": _EMBEDDING_TRUNCATION_VERSION,
    }
    digest_payload = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    contract["contract_hash"] = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
    return contract


# ---------------------------------------------------------------------------
# Shared Pydantic models
# ---------------------------------------------------------------------------

class ConfigPayload(BaseModel):
    """Public view of a subsystem's runtime override with masked credential state."""
    provider: str = ""
    base_url: str = ""
    model: str = ""
    has_api_key: bool = False
    api_key_masked: str = ""
    updated_at: str = ""


class ConfigUpdate(BaseModel):
    """Update payload. None for the credential field preserves the stored value."""
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class CredentialApplyRequest(BaseModel):
    """Apply a saved RuntimeCredential to a subsystem override.

    The request carries only an opaque local credential reference; the backend
    resolves the credential material internally.
    """

    credential_id: str = Field(min_length=1, max_length=128)


class ProbeResult(BaseModel):
    ok: bool
    status: int = 0
    error: str = ""
    elapsed_ms: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class DiscoverRequest(BaseModel):
    """POST body for model discovery; credential material is never sent in URLs."""
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


class ToolCapabilityProbeResult(BaseModel):
    """Public result for a chat provider's native tool-call capability probe."""

    ok: bool
    status: str
    provider: str = ""
    base_url_host: str = ""
    model: str = ""
    stage: str = ""
    error: str = ""
    provider_message: str | None = None
    ordinary_chat_ok: bool = False
    forced_tool_choice_ok: bool = False
    capability: dict[str, Any] = Field(default_factory=dict)


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

    try:
        from routers.chat_router import (
            _build_models_discovery_endpoint,
            _validate_outbound_llm_base_url,
        )

        # B15 (2026-06-13): user is exploring a new provider — let probes hit
        # any HTTPS host without requiring a pre-baked .env allowlist entry.
        # Scheme / userinfo / path checks still run. Real chat traffic uses the
        # strict path (skip_dns=False default) elsewhere.
        _validate_outbound_llm_base_url(trimmed, "Local LLM", skip_dns=True)
        url = _build_models_discovery_endpoint(trimmed)
    except ValueError as exc:
        return DiscoverResult(ok=False, error=str(exc))
    except ImportError as exc:
        return DiscoverResult(ok=False, error=f"Endpoint validator unavailable: {exc}")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
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


def _credential_category_for_store(store: ModelConfigStore) -> str:
    if store.subsystem == "chat":
        return "generation"
    if store.subsystem == "embedding":
        return "embedding"
    return store.subsystem


def _apply_credential_to_store(
    store: ModelConfigStore,
    credential_id: str,
) -> ConfigPayload:
    from credential_store import CredentialNotFoundError
    from routers.credentials_router import get_credential_store

    credential_store = get_credential_store()
    try:
        credential = credential_store.get_internal(credential_id)
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
    expected_category = _credential_category_for_store(store)
    if credential.category.value != expected_category:
        raise HTTPException(
            status_code=400,
            detail=(
                f"credential category mismatch: expected {expected_category}, "
                f"got {credential.category.value}"
            ),
        )

    updated = store.write_config(
        provider=credential.provider,
        base_url=credential.base_url,
        api_key=credential.api_key,
        model=credential.model,
    )
    return ConfigPayload(**updated)


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

    @sub_router.post("/config/apply-credential", response_model=ConfigPayload)
    async def apply_credential(payload: CredentialApplyRequest) -> ConfigPayload:
        return _apply_credential_to_store(store, payload.credential_id)

    @sub_router.delete("/config", response_model=ConfigPayload)
    async def delete_config() -> ConfigPayload:
        store.clear_config()
        return ConfigPayload(**store.get_public_config())

    return sub_router


# ---------------------------------------------------------------------------
# Chat subsystem
# ---------------------------------------------------------------------------

chat_router = _build_config_routes(chat_store, "/api/chat", "Chat Config")


class ChatContextCompressionPayload(BaseModel):
    """SmartRead long-session compression settings."""

    enabled: bool = True
    trigger_tokens: int = Field(
        default=CHAT_CONTEXT_COMPRESSION_TRIGGER_DEFAULT,
        ge=CHAT_CONTEXT_COMPRESSION_TRIGGER_MIN,
        le=CHAT_CONTEXT_COMPRESSION_TRIGGER_MAX,
    )
    target_tokens: int = Field(
        default=CHAT_CONTEXT_COMPRESSION_TARGET_DEFAULT,
        ge=CHAT_CONTEXT_COMPRESSION_TARGET_MIN,
        le=CHAT_CONTEXT_COMPRESSION_TARGET_MAX,
    )
    keep_recent_turns: int = Field(
        default=CHAT_CONTEXT_COMPRESSION_KEEP_RECENT_DEFAULT,
        ge=CHAT_CONTEXT_COMPRESSION_KEEP_RECENT_MIN,
        le=CHAT_CONTEXT_COMPRESSION_KEEP_RECENT_MAX,
    )
    updated_at: str = ""


def _chat_context_compression_payload() -> ChatContextCompressionPayload:
    settings = normalize_chat_context_compression_settings(
        chat_context_compression_store.get_settings()
    )
    return ChatContextCompressionPayload(
        enabled=bool(settings.get("enabled", True)),
        trigger_tokens=int(settings.get("trigger_tokens") or CHAT_CONTEXT_COMPRESSION_TRIGGER_DEFAULT),
        target_tokens=int(settings.get("target_tokens") or CHAT_CONTEXT_COMPRESSION_TARGET_DEFAULT),
        keep_recent_turns=int(
            settings.get("keep_recent_turns") or CHAT_CONTEXT_COMPRESSION_KEEP_RECENT_DEFAULT
        ),
        updated_at=str(settings.get("updated_at") or ""),
    )


@chat_router.get("/context-compression", response_model=ChatContextCompressionPayload)
async def get_chat_context_compression() -> ChatContextCompressionPayload:
    """Return SmartRead long-session compression settings."""
    return _chat_context_compression_payload()


@chat_router.put("/context-compression", response_model=ChatContextCompressionPayload)
async def put_chat_context_compression(
    payload: ChatContextCompressionPayload,
) -> ChatContextCompressionPayload:
    """Update SmartRead long-session compression settings."""
    if payload.target_tokens >= payload.trigger_tokens:
        raise HTTPException(
            status_code=400,
            detail="target_tokens must be smaller than trigger_tokens",
        )
    settings = normalize_chat_context_compression_settings(
        chat_context_compression_store.write_settings(
            {
                "enabled": payload.enabled,
                "trigger_tokens": payload.trigger_tokens,
                "target_tokens": payload.target_tokens,
                "keep_recent_turns": payload.keep_recent_turns,
            }
        )
    )
    return ChatContextCompressionPayload(
        enabled=bool(settings.get("enabled", True)),
        trigger_tokens=int(settings.get("trigger_tokens") or payload.trigger_tokens),
        target_tokens=int(settings.get("target_tokens") or payload.target_tokens),
        keep_recent_turns=int(settings.get("keep_recent_turns") or payload.keep_recent_turns),
        updated_at=str(settings.get("updated_at") or ""),
    )


@chat_router.delete("/context-compression", response_model=ChatContextCompressionPayload)
async def delete_chat_context_compression() -> ChatContextCompressionPayload:
    """Reset SmartRead long-session compression settings to defaults."""
    chat_context_compression_store.clear_settings()
    return _chat_context_compression_payload()


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
        from routers.chat_router import (
            _build_chat_endpoint,
            _resolve_api_key,
            _validate_outbound_llm_base_url,
        )

        # B20 (2026-06-13): user-initiated probe — skip strict IP classification
        # so freshly-added third-party gateways don't get rejected before the
        # user can even reach "测试连接". Real chat traffic stays strict.
        _validate_outbound_llm_base_url(base_url, provider or "OpenAI", skip_dns=True)
        url = _build_chat_endpoint(base_url, provider or "OpenAI")
        resolved_key = _resolve_api_key(provider or "OpenAI", api_key)
    except ValueError as exc:
        return ProbeResult(ok=False, error=str(exc))
    except ImportError as exc:
        return ProbeResult(ok=False, error=f"Endpoint validator unavailable: {exc}")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"

    probe_body = {
        "model": model or "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    apply_openai_chat_payload_compat(
        probe_body,
        provider=provider,
        base_url=base_url,
        model=str(probe_body["model"]),
        top_k=None,
    )

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=provider_http_timeout_s(
                provider=provider,
                base_url=base_url,
                model=str(probe_body["model"]),
                default_s=15.0,
            ),
            follow_redirects=False,
        ) as client:
            resp = await client.post(url, headers=headers, json=probe_body)
    except httpx.RequestError as exc:
        return ProbeResult(
            ok=False, status=0,
            error=f"连接失败: {exc}",
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )

    elapsed_ms = int((time.monotonic() - start) * 1000)
    if resp.status_code < 400:
        try:
            response_text = _extract_chat_probe_text(resp.json())
        except ValueError:
            response_text = ""
        if not response_text:
            return _probe_error_response(
                status=resp.status_code,
                elapsed_ms=elapsed_ms,
                error="聊天接口返回成功状态，但没有返回可用的回复内容",
            )
        return ProbeResult(
            ok=True,
            status=resp.status_code,
            elapsed_ms=elapsed_ms,
            extra={"response_chars": len(response_text)},
        )
    body_preview = resp.text[:300] if resp.text else ""
    return ProbeResult(
        ok=False, status=resp.status_code,
        error=body_preview or f"HTTP {resp.status_code}",
        elapsed_ms=elapsed_ms,
    )


def _capability_status_from_probe_result(probe_result: Any) -> str:
    """Map a provider probe result to a persisted dispatch-gate status."""

    if bool(getattr(probe_result, "ok", False)) and bool(
        getattr(probe_result, "forced_tool_choice_ok", False)
    ):
        return CAPABILITY_STATUS_TOOL_CALL_OK
    status_code = getattr(probe_result, "status_code", None)
    if status_code in {401, 403}:
        return CAPABILITY_STATUS_AUTH_REQUIRED
    return CAPABILITY_STATUS_PROBE_FAILED


@chat_router.post("/tool-capability/test", response_model=ToolCapabilityProbeResult)
async def test_chat_tool_capability(payload: ConfigUpdate) -> ToolCapabilityProbeResult:
    """Probe and persist native OpenAI-compatible chat tool-call capability."""

    base_url = (payload.base_url or chat_store.get_resolved_field("base_url") or "").strip()
    api_key = (payload.api_key or chat_store.get_resolved_field("api_key") or "").strip()
    model = (payload.model or chat_store.get_resolved_field("model") or "").strip()
    provider = (payload.provider or chat_store.get_resolved_field("provider") or "OpenAI").strip()

    if not base_url:
        record = provider_capability_store.upsert_record(
            provider=provider,
            base_url=base_url,
            model=model,
            status=CAPABILITY_STATUS_PROBE_FAILED,
            ordinary_chat_ok=False,
            forced_tool_choice_ok=False,
            failure_class="configuration",
            masked_error="base_url is required",
        )
        return ToolCapabilityProbeResult(
            ok=False,
            status=record.status,
            provider=record.provider,
            base_url_host=record.base_url_host,
            model=record.model,
            stage="configuration",
            error="base_url is required",
            ordinary_chat_ok=False,
            forced_tool_choice_ok=False,
            capability=record.to_dict(),
        )
    if not model:
        record = provider_capability_store.upsert_record(
            provider=provider,
            base_url=base_url,
            model=model,
            status=CAPABILITY_STATUS_PROBE_FAILED,
            ordinary_chat_ok=False,
            forced_tool_choice_ok=False,
            failure_class="configuration",
            masked_error="model is required",
        )
        return ToolCapabilityProbeResult(
            ok=False,
            status=record.status,
            provider=record.provider,
            base_url_host=record.base_url_host,
            model=record.model,
            stage="configuration",
            error="model is required",
            ordinary_chat_ok=False,
            forced_tool_choice_ok=False,
            capability=record.to_dict(),
        )

    try:
        from provider_probe import probe_openai_tool_calling_capability
    except ImportError as exc:
        record = provider_capability_store.upsert_record(
            provider=provider,
            base_url=base_url,
            model=model,
            status=CAPABILITY_STATUS_PROBE_FAILED,
            ordinary_chat_ok=False,
            forced_tool_choice_ok=False,
            failure_class="import_error",
            masked_error=str(exc),
        )
        return ToolCapabilityProbeResult(
            ok=False,
            status=record.status,
            provider=record.provider,
            base_url_host=record.base_url_host,
            model=record.model,
            stage="import_error",
            error=str(exc),
            ordinary_chat_ok=False,
            forced_tool_choice_ok=False,
            capability=record.to_dict(),
        )

    probe_result = await asyncio.to_thread(
        probe_openai_tool_calling_capability,
        base_url,
        api_key,
        model,
        provider=provider,
        timeout_s=provider_http_timeout_s(
            provider=provider,
            base_url=base_url,
            model=model,
            default_s=10.0,
        ),
    )
    status = _capability_status_from_probe_result(probe_result)
    record = provider_capability_store.upsert_record(
        provider=provider,
        base_url=base_url,
        model=model,
        status=status,
        ordinary_chat_ok=bool(getattr(probe_result, "chat_ok", False)),
        forced_tool_choice_ok=bool(getattr(probe_result, "forced_tool_choice_ok", False)),
        failure_class=str(getattr(probe_result, "stage", "") or ""),
        masked_error=str(getattr(probe_result, "error", "") or ""),
    )
    return ToolCapabilityProbeResult(
        ok=record.tool_call_ok,
        status=record.status,
        provider=record.provider,
        base_url_host=record.base_url_host,
        model=record.model,
        stage=str(getattr(probe_result, "stage", "") or ""),
        error=str(getattr(probe_result, "error", "") or ""),
        provider_message=getattr(probe_result, "provider_message", None),
        ordinary_chat_ok=record.ordinary_chat_ok,
        forced_tool_choice_ok=record.forced_tool_choice_ok,
        capability=record.to_dict(),
    )


@chat_router.post("/models/discover", response_model=DiscoverResult)
async def discover_chat_models(req: DiscoverRequest) -> DiscoverResult:
    """Discover models from a chat/LLM service without URL credentials."""
    base_url = req.base_url or chat_store.get_resolved_field("base_url") or ""
    api_key = req.api_key or chat_store.get_resolved_field("api_key") or ""
    return await discover_models_from_endpoint(base_url, api_key)


# ---------------------------------------------------------------------------
# Embedding subsystem
# ---------------------------------------------------------------------------

embedding_router = _build_config_routes(embedding_store, "/api/embedding", "Embedding Config")


class LocalEmbeddingStatusPayload(BaseModel):
    """Snapshot of in-process local embedding loading for the Settings UI.

    Rendered as a status chip / badge next to the Embedding card. Mirrors
    ``LocalRerankStatusPayload`` field-by-field so the frontend can reuse
    the same chip component for both.

    ``available=true`` means embedding can use a locally cached
    SentenceTransformer (default ``BAAI/bge-m3``) in the backend Python
    process when the upstream API fails; ``available=false`` means an API outage will
    propagate as ``EmbeddingAPIError`` to the caller.
    """

    available: bool
    disabled: bool
    weights_present: bool
    allow_download: bool
    model_name: str
    device: str
    device_source: str  # "auto_detected" | "env_override"
    batch_size: int
    loaded: bool
    hf_cache_dir: str
    unavailable_reason: str = ""


@embedding_router.get("/local-status", response_model=LocalEmbeddingStatusPayload)
async def get_local_embedding_status() -> LocalEmbeddingStatusPayload:
    """Status of in-process local embedding loading (weights / device / availability).

    Used by Settings UI to render a chip telling the user whether
    embedding can use a local SentenceTransformer from the backend process
    when the configured API embedding fails. Does NOT load weights —
    runs in <1 ms on a warm process.
    """
    try:
        from local_embedding_adapter import get_status
    except ImportError as exc:  # adapter module missing — degrade gracefully
        logger.warning("local_embedding_adapter unavailable: %s", exc)
        return LocalEmbeddingStatusPayload(
            available=False,
            disabled=True,
            weights_present=False,
            allow_download=False,
            model_name="",
            device="cpu",
            device_source="auto_detected",
            batch_size=0,
            loaded=False,
            hf_cache_dir="",
            unavailable_reason="local_embedding_adapter 模块不可用。",
        )
    return LocalEmbeddingStatusPayload(**get_status())


@embedding_router.post("/test", response_model=ProbeResult)
async def test_embedding_endpoint(payload: ConfigUpdate) -> ProbeResult:
    """Probe an embedding endpoint using runtime_env helpers for URL construction."""
    base_url = (payload.base_url or embedding_store.get_resolved_field("base_url") or "").strip()
    api_key = (payload.api_key or embedding_store.get_resolved_field("api_key") or "").strip()
    model = (payload.model or embedding_store.get_resolved_field("model") or "").strip()
    provider = (payload.provider or embedding_store.get_resolved_field("provider") or "Local LLM").strip()

    if not base_url:
        return ProbeResult(ok=False, error="base_url is required")

    try:
        from routers.chat_router import _validate_outbound_llm_base_url

        # B20: user-initiated embedding probe — see B20 note above.
        _validate_outbound_llm_base_url(base_url, provider or "Local LLM", skip_dns=True)
    except ValueError as exc:
        return ProbeResult(ok=False, error=str(exc))

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
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
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
        except ValueError:
            resp_data = {}
        vectors = _embedding_vectors_from_payload(resp_data)
        if not vectors:
            return _probe_error_response(
                status=resp.status_code,
                elapsed_ms=elapsed_ms,
                error="向量化接口返回成功状态，但没有返回可用的向量数组",
            )
        extra["dimension"] = len(vectors[0])
        extra["vectors"] = len(vectors)
        response_model = _embedding_response_model_from_payload(resp_data)
        contract_model = str(body.get("model") or model or "").strip()
        if contract_model:
            extra.update(
                _build_embedding_contract_extra(
                    provider=provider,
                    base_url=base_url,
                    requested_model=contract_model,
                    response_model=response_model,
                    vectors=vectors,
                )
            )
        return ProbeResult(ok=True, status=resp.status_code, elapsed_ms=elapsed_ms, extra=extra)

    body_preview = resp.text[:300] if resp.text else ""
    return ProbeResult(
        ok=False, status=resp.status_code,
        error=body_preview or f"HTTP {resp.status_code}",
        elapsed_ms=elapsed_ms,
    )


@embedding_router.post("/models/discover", response_model=DiscoverResult)
async def discover_embedding_models(req: DiscoverRequest) -> DiscoverResult:
    """Discover models from an embedding service without URL credentials."""
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
