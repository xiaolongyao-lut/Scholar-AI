"""CSL citation-style management endpoints.

Exposes the :mod:`csl_style_store` registry to the frontend: list styles, read
the active style (and its XML for the browser-side citeproc processor), import a
``.csl`` file, switch the active style, and delete an uploaded style. Builtin
styles are read-only.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from csl_style_store import CslValidationError, csl_style_store

router = APIRouter(prefix="/api/csl-styles", tags=["Citation Styles"])


class CslStyleMetaPayload(BaseModel):
    """One citation style row for the settings UI."""

    id: str
    title: str
    source: Literal["builtin", "uploaded"]
    active: bool = False
    can_delete: bool = False
    created_at: str | None = None


class CslStyleListPayload(BaseModel):
    styles: list[CslStyleMetaPayload] = Field(default_factory=list)
    active_style_id: str


class CslActiveStylePayload(BaseModel):
    """Active style with its raw CSL XML for the browser-side processor."""

    id: str
    title: str
    csl_xml: str


class CslStyleImportRequest(BaseModel):
    csl_xml: str = Field(..., min_length=1)
    title: str | None = None


class CslSetActiveRequest(BaseModel):
    style_id: str = Field(..., min_length=1)


def _list_payload() -> CslStyleListPayload:
    styles = [CslStyleMetaPayload(**meta) for meta in csl_style_store.list_styles()]
    active_id = next((style.id for style in styles if style.active), "")
    return CslStyleListPayload(styles=styles, active_style_id=active_id)


@router.get("", response_model=CslStyleListPayload)
async def list_csl_styles() -> CslStyleListPayload:
    """List builtin + uploaded styles and the active selection."""
    return _list_payload()


@router.get("/active", response_model=CslActiveStylePayload)
async def get_active_csl_style() -> CslActiveStylePayload:
    """Return the active style and its CSL XML (single source of truth)."""
    return CslActiveStylePayload(**csl_style_store.get_active())


@router.get("/{style_id}/content", response_model=CslActiveStylePayload)
async def get_csl_style_content(style_id: str) -> CslActiveStylePayload:
    xml = csl_style_store.get_style_xml(style_id)
    if xml is None:
        raise HTTPException(status_code=404, detail=f"style not found: {style_id}")
    title = next(
        (meta["title"] for meta in csl_style_store.list_styles() if meta["id"] == style_id),
        style_id,
    )
    return CslActiveStylePayload(id=style_id, title=title, csl_xml=xml)


@router.post("/import", response_model=CslStyleMetaPayload)
async def import_csl_style(req: CslStyleImportRequest) -> CslStyleMetaPayload:
    """Validate and store an uploaded ``.csl`` style; it becomes active."""
    try:
        meta = csl_style_store.import_style(req.csl_xml, title_override=req.title)
    except CslValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CslStyleMetaPayload(**meta)


@router.put("/active", response_model=CslActiveStylePayload)
async def set_active_csl_style(req: CslSetActiveRequest) -> CslActiveStylePayload:
    try:
        active = csl_style_store.set_active(req.style_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"style not found: {req.style_id}") from exc
    return CslActiveStylePayload(**active)


@router.delete("/{style_id}", response_model=CslStyleListPayload)
async def delete_csl_style(style_id: str) -> CslStyleListPayload:
    try:
        csl_style_store.delete_style(style_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"style not found: {style_id}") from exc
    return _list_payload()


__all__ = ["router"]
