"""Unified Settings API for runtime API configuration.

This router aggregates the existing subsystem endpoints without replacing
their compatibility contracts. Credential material remains owned by subsystem
stores and is exposed only through masked public fields.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import rerank_runtime_config
from feature_flags import FEATURE_FLAGS, list_flags, set_flag
from model_config_store import chat_store, embedding_store
from routers.credentials_router import get_credential_store


router = APIRouter(prefix="/api/settings", tags=["Settings"])

SettingsSubsystem = Literal["chat", "embedding", "rerank"]


class SettingsApiConfigPayload(BaseModel):
    """Masked runtime API config for one subsystem.

    Shape:
    - provider/base_url/model are public strings.
    - credential material is never returned; masked fields are display-only.
    """

    provider: str = ""
    base_url: str = ""
    model: str = ""
    has_api_key: bool = False
    api_key_masked: str = ""
    updated_at: str = ""


class SettingsApiConfigUpdate(BaseModel):
    """Partial subsystem update.

    Passing None for the credential field preserves the stored value; passing an empty string
    clears it, matching the legacy subsystem endpoint semantics.
    """

    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class SettingsApiBundlePayload(BaseModel):
    """Unified API config bundle returned by GET /api/settings."""

    chat: SettingsApiConfigPayload
    embedding: SettingsApiConfigPayload
    rerank: SettingsApiConfigPayload


class SettingsCredentialsSummaryPayload(BaseModel):
    """Credential center summary; counts are mask-safe and category-scoped."""

    total: int = Field(ge=0)
    enabled: int = Field(ge=0)
    generation: int = Field(ge=0)
    embedding: int = Field(ge=0)
    rerank: int = Field(ge=0)


class SettingsFeatureFlagPayload(BaseModel):
    """Feature flag public state mirrored from /api/feature-flags."""

    name: str
    label: str
    current: bool
    source: str


class UnifiedSettingsPayload(BaseModel):
    """Single Settings document for UI bootstrap and smoke verification."""

    api: SettingsApiBundlePayload
    credentials: SettingsCredentialsSummaryPayload
    feature_flags: list[SettingsFeatureFlagPayload]


class UnifiedSettingsUpdate(BaseModel):
    """Partial unified settings update.

    Supported writes are intentionally limited to already-owned runtime stores
    so /api/settings cannot bypass credential masking or endpoint policies.
    """

    chat: SettingsApiConfigUpdate | None = None
    embedding: SettingsApiConfigUpdate | None = None
    rerank: SettingsApiConfigUpdate | None = None
    feature_flags: dict[str, bool] | None = None


def _public_model_config(subsystem: SettingsSubsystem) -> SettingsApiConfigPayload:
    if subsystem == "chat":
        return SettingsApiConfigPayload(**chat_store.get_public_config())
    if subsystem == "embedding":
        return SettingsApiConfigPayload(**embedding_store.get_public_config())
    if subsystem == "rerank":
        return SettingsApiConfigPayload(**rerank_runtime_config.get_public_config())
    raise HTTPException(status_code=400, detail=f"unknown settings subsystem: {subsystem}")


def _write_model_config(
    subsystem: SettingsSubsystem,
    update: SettingsApiConfigUpdate,
) -> SettingsApiConfigPayload:
    if subsystem == "chat":
        return SettingsApiConfigPayload(**chat_store.write_config(
            provider=update.provider,
            base_url=update.base_url,
            api_key=update.api_key,
            model=update.model,
        ))
    if subsystem == "embedding":
        return SettingsApiConfigPayload(**embedding_store.write_config(
            provider=update.provider,
            base_url=update.base_url,
            api_key=update.api_key,
            model=update.model,
        ))
    if subsystem == "rerank":
        return SettingsApiConfigPayload(**rerank_runtime_config.write_config(
            provider=update.provider,
            base_url=update.base_url,
            api_key=update.api_key,
            model=update.model,
        ))
    raise HTTPException(status_code=400, detail=f"unknown settings subsystem: {subsystem}")


def _clear_model_config(subsystem: SettingsSubsystem) -> SettingsApiConfigPayload:
    if subsystem == "chat":
        chat_store.clear_config()
    elif subsystem == "embedding":
        embedding_store.clear_config()
    elif subsystem == "rerank":
        rerank_runtime_config.clear_config()
    else:
        raise HTTPException(status_code=400, detail=f"unknown settings subsystem: {subsystem}")
    return _public_model_config(subsystem)


def _credentials_summary() -> SettingsCredentialsSummaryPayload:
    credentials = get_credential_store().list_public()
    generation = sum(1 for item in credentials if item.category.value == "generation")
    embedding = sum(1 for item in credentials if item.category.value == "embedding")
    rerank = sum(1 for item in credentials if item.category.value == "rerank")
    enabled = sum(1 for item in credentials if item.enabled)
    return SettingsCredentialsSummaryPayload(
        total=len(credentials),
        enabled=enabled,
        generation=generation,
        embedding=embedding,
        rerank=rerank,
    )


def _feature_flags() -> list[SettingsFeatureFlagPayload]:
    return [SettingsFeatureFlagPayload(**entry) for entry in list_flags()]


def _settings_payload() -> UnifiedSettingsPayload:
    return UnifiedSettingsPayload(
        api=SettingsApiBundlePayload(
            chat=_public_model_config("chat"),
            embedding=_public_model_config("embedding"),
            rerank=_public_model_config("rerank"),
        ),
        credentials=_credentials_summary(),
        feature_flags=_feature_flags(),
    )


@router.get("", response_model=UnifiedSettingsPayload)
async def get_settings() -> UnifiedSettingsPayload:
    """Return the unified Settings document.

    Output never contains credential material and is safe for browser bootstrap.
    """

    return _settings_payload()


@router.put("", response_model=UnifiedSettingsPayload)
async def update_settings(payload: UnifiedSettingsUpdate) -> UnifiedSettingsPayload:
    """Apply a partial unified settings update and return the fresh document."""

    if payload.chat is not None:
        _write_model_config("chat", payload.chat)
    if payload.embedding is not None:
        _write_model_config("embedding", payload.embedding)
    if payload.rerank is not None:
        _write_model_config("rerank", payload.rerank)
    if payload.feature_flags is not None:
        for name, enabled in payload.feature_flags.items():
            if name not in FEATURE_FLAGS:
                raise HTTPException(status_code=404, detail=f"unknown feature flag: {name}")
            set_flag(name, enabled)
    return _settings_payload()


@router.delete("", response_model=UnifiedSettingsPayload)
async def delete_settings(
    subsystem: SettingsSubsystem | None = Query(default=None),
) -> UnifiedSettingsPayload:
    """Clear API overrides.

    When subsystem is omitted, all model API overrides are cleared. Credential
    records are not deleted through this endpoint.
    """

    if subsystem is None:
        _clear_model_config("chat")
        _clear_model_config("embedding")
        _clear_model_config("rerank")
    else:
        _clear_model_config(subsystem)
    return _settings_payload()


__all__ = ["router"]
