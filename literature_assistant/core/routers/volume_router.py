# -*- coding: utf-8 -*-
"""Volume router.

Exposes the legacy batch -> volume bundle -> cross-paper analysis workflow to
frontend clients.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from volume_analysis_service import get_volume_analysis, list_volume_summaries

router = APIRouter(prefix="/volumes", tags=["Volume"])


@router.get("")
async def list_volumes() -> dict[str, object]:
    volumes = list_volume_summaries()
    return {
        "total": len(volumes),
        "volumes": [{key: value for key, value in volume.items() if key != "bundle_path"} for volume in volumes],
    }


@router.get("/{volume_key}/analysis")
async def get_volume_analysis_endpoint(
    volume_key: str,
    refresh: bool = Query(False, description="Force rebuild the cached analysis artifacts"),
) -> dict[str, object]:
    try:
        return await get_volume_analysis(volume_key, refresh=refresh)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Volume not found: {volume_key}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Volume bundle missing: {exc}") from exc
