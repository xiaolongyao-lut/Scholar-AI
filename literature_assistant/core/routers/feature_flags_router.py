"""Feature flags REST API.

Endpoints
---------
- ``GET  /api/feature-flags``         — list every registered flag with its
  current resolved value, default, env-var binding, and source label
  (``override`` / ``env`` / ``default``).
- ``POST /api/feature-flags/{name}``  — persist an override for one flag.
  Writes ``runtime_state/feature_flags_override.json`` atomically and returns
  the post-update entry.

The flag registry lives in ``literature_assistant/core/feature_flags.py`` —
unknown flag names return 404 from POST and are filtered out of GET.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from feature_flags import FEATURE_FLAGS, list_flags, set_flag


router = APIRouter(prefix="/api/feature-flags", tags=["FeatureFlags"])


class FeatureFlagEntry(BaseModel):
    name: str
    label: str
    description: str
    default: bool
    env_var: str | None = None
    current: bool
    source: str  # "override" | "env" | "default"


class FeatureFlagListResponse(BaseModel):
    flags: list[FeatureFlagEntry]


class SetFeatureFlagRequest(BaseModel):
    enabled: bool = Field(..., description="Desired flag state.")


@router.get("", response_model=FeatureFlagListResponse)
async def get_feature_flags() -> FeatureFlagListResponse:
    """Return every registered feature flag with its current resolved value."""
    return FeatureFlagListResponse(
        flags=[FeatureFlagEntry(**entry) for entry in list_flags()]
    )


@router.post("/{name}", response_model=FeatureFlagEntry)
async def set_feature_flag(name: str, req: SetFeatureFlagRequest) -> FeatureFlagEntry:
    """Persist an override for one registered flag."""
    if name not in FEATURE_FLAGS:
        raise HTTPException(status_code=404, detail=f"unknown feature flag: {name}")
    entry = set_flag(name, req.enabled)
    return FeatureFlagEntry(**entry)
