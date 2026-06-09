# -*- coding: utf-8 -*-
"""Annotation API Router — PDF highlight + note persistence.

L1 (commits 4879b959 / 367aed6e / c5205a63): highlights only.
L2 (Track C): adds notes + last_page (read-progress) + Markdown export.
Both layers share the same on-disk JSON file via tmp+replace atomic
writes; L1 endpoints preserve L2 fields on roundtrip and vice versa.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from literature_assistant.core.project_paths import runtime_state_path

router = APIRouter(prefix="/api/annotations", tags=["Annotations"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File-system helpers
# ---------------------------------------------------------------------------

def _annotations_dir() -> Path:
    p = runtime_state_path() / "annotations"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _annotation_file(material_id: str) -> Path:
    if "/" in material_id or "\\" in material_id or ".." in material_id:
        raise HTTPException(status_code=400, detail="Invalid material_id")
    return _annotations_dir() / f"{material_id}.json"


def _read_annotation_data(material_id: str) -> dict[str, Any]:
    """Read the on-disk annotation file as a tolerant dict.

    Returns the L2 envelope (material_id + highlights + notes + last_page)
    even when the file is L1-only, to keep call sites uniform.
    """
    f = _annotation_file(material_id)
    if not f.exists():
        return {
            "material_id": material_id,
            "highlights": [],
            "notes": [],
            "last_page": None,
        }
    raw: dict[str, Any]
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = {}
    return {
        "material_id": material_id,
        "highlights": raw.get("highlights") or [],
        "notes": raw.get("notes") or [],
        "last_page": raw.get("last_page") if isinstance(raw.get("last_page"), int) else None,
    }


def _write_annotation_file(f: Path, annotation: dict[str, Any]) -> None:
    """Atomic write: tmp file + os.replace."""
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)


def _persist(material_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Atomic write of a sanitised L2 envelope. Removes the file when
    every L2 segment is empty, so L1 callers that DELETE-then-GET still
    see the historical "no annotation" shape.
    """
    highlights = data.get("highlights") or []
    notes = data.get("notes") or []
    last_page = data.get("last_page")
    f = _annotation_file(material_id)
    has_anything = bool(highlights) or bool(notes) or isinstance(last_page, int)
    if not has_anything:
        if f.exists():
            f.unlink()
        return {
            "material_id": material_id,
            "highlights": [],
            "notes": [],
            "last_page": None,
        }
    payload = {
        "material_id": material_id,
        "highlights": highlights,
        "notes": notes,
        "last_page": last_page if isinstance(last_page, int) and last_page >= 1 else None,
    }
    _write_annotation_file(f, payload)
    return payload


# ---------------------------------------------------------------------------
# Schemas (L1 + L2)
# ---------------------------------------------------------------------------

class HighlightRect(BaseModel):
    """Normalized highlight rectangle, relative to the PDF page box.

    All four values are in [0, 1] so the overlay can be drawn correctly
    regardless of the user's current zoom level. (x, y) is the top-left
    of the rect; w/h are the width/height. A single highlight typically
    has 1-N rects (one per visual line of selected text).
    """
    x: float = Field(..., ge=0, le=1)
    y: float = Field(..., ge=0, le=1)
    w: float = Field(..., gt=0, le=1)
    h: float = Field(..., gt=0, le=1)


class Highlight(BaseModel):
    page: int = Field(..., ge=1)
    text: str = Field(..., min_length=1)
    color: str = Field("#FFEB3B", max_length=7)
    # Optional so highlights persisted before 0.1.8.1 (which had no
    # visual overlay at all) still validate. Frontend falls back to a
    # text-only list view when rects is null.
    rects: list[HighlightRect] | None = None


class Note(BaseModel):
    """Selection- or page-anchored free-text note (L2)."""

    model_config = ConfigDict(extra="forbid")
    note_id: str = Field(..., min_length=1, max_length=64)
    page: int = Field(..., ge=1)
    anchor_text: str = Field(default="", max_length=2000)
    body: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=16)
    created_at: str = Field(..., min_length=1)
    updated_at: str = Field(..., min_length=1)


class AnnotationData(BaseModel):
    material_id: str = Field(..., min_length=1)
    highlights: list[Highlight] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)
    last_page: int | None = Field(default=None, ge=1)


class AddHighlightRequest(BaseModel):
    material_id: str = Field(..., min_length=1)
    highlight: Highlight


class ReplaceHighlightsRequest(BaseModel):
    highlights: list[Highlight] = Field(default_factory=list)


class AddNoteRequest(BaseModel):
    """L2 note add. note_id is server-generated; do not trust client value."""

    model_config = ConfigDict(extra="forbid")
    page: int = Field(..., ge=1)
    anchor_text: str = Field(default="", max_length=2000)
    body: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=16)


class UpdateNoteRequest(BaseModel):
    """L2 note replace (body + tags). page + anchor_text immutable."""

    model_config = ConfigDict(extra="forbid")
    body: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=16)


class LastPageRequest(BaseModel):
    """L2 read-progress write. Allow null to clear."""

    model_config = ConfigDict(extra="forbid")
    page: int | None = Field(default=None, ge=1)


def _dump_highlight_for_storage(highlight: Highlight) -> dict[str, Any]:
    """Serialize highlights without null-only overlay fields.

    Older clients compare the L1 highlight shape exactly. Omitting unset
    optional geometry preserves that contract while still allowing rects when
    the PDF overlay sends them.
    """

    return highlight.model_dump(exclude_none=True)


def _utc_now_iso() -> str:
    """ISO-8601 UTC timestamp without microseconds."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _generate_note_id(existing_ids: set[str]) -> str:
    """UUID4-12 hex; pre-flight collision check inside caller's lock."""
    for _ in range(8):
        candidate = secrets.token_hex(6)  # 12 hex chars
        if candidate not in existing_ids:
            return candidate
    # Vanishingly unlikely with 12 hex chars; surface as 500 rather than loop.
    raise HTTPException(status_code=500, detail="Failed to allocate note id")


# ---------------------------------------------------------------------------
# L1 endpoints — preserved + L2-aware
# ---------------------------------------------------------------------------

@router.get("/{material_id}")
async def get_annotations(material_id: str):
    return _read_annotation_data(material_id)


@router.post("/{material_id}")
async def add_highlight(material_id: str, req: AddHighlightRequest):
    data = _read_annotation_data(material_id)
    data["highlights"] = list(data["highlights"]) + [_dump_highlight_for_storage(req.highlight)]
    return _persist(material_id, data)


@router.put("/{material_id}")
async def replace_highlights(material_id: str, req: ReplaceHighlightsRequest):
    """Replace the full highlight list. Preserves notes + last_page."""
    data = _read_annotation_data(material_id)
    data["highlights"] = [_dump_highlight_for_storage(h) for h in req.highlights]
    return _persist(material_id, data)


@router.delete("/{material_id}")
async def clear_annotations(material_id: str):
    """L1 contract: full reset. Removes notes + last_page too — destructive
    by design, matches the "scrap this material's annotations" intent.
    """
    f = _annotation_file(material_id)
    if f.exists():
        f.unlink()
    return {"ok": True, "material_id": material_id}


# ---------------------------------------------------------------------------
# L2 — notes
# ---------------------------------------------------------------------------

NOTES_PER_MATERIAL_LIMIT = 200


@router.post("/{material_id}/notes")
async def add_note(material_id: str, req: AddNoteRequest):
    data = _read_annotation_data(material_id)
    notes = list(data["notes"])
    if len(notes) >= NOTES_PER_MATERIAL_LIMIT:
        raise HTTPException(
            status_code=413,
            detail=f"超过单材料笔记数量上限（{NOTES_PER_MATERIAL_LIMIT}）；请导出后归档。",
        )
    existing_ids = {str(n.get("note_id")) for n in notes if isinstance(n, dict)}
    note_id = _generate_note_id(existing_ids)
    now = _utc_now_iso()
    note = Note(
        note_id=note_id,
        page=req.page,
        anchor_text=req.anchor_text,
        body=req.body,
        tags=list(req.tags),
        created_at=now,
        updated_at=now,
    ).model_dump()
    notes.append(note)
    data["notes"] = notes
    persisted = _persist(material_id, data)
    return {"material_id": material_id, "note": note, "annotation": persisted}


@router.put("/{material_id}/notes/{note_id}")
async def update_note(material_id: str, note_id: str, req: UpdateNoteRequest):
    data = _read_annotation_data(material_id)
    notes = list(data["notes"])
    for i, raw in enumerate(notes):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("note_id")) != note_id:
            continue
        updated = dict(raw)
        updated["body"] = req.body
        updated["tags"] = list(req.tags)
        updated["updated_at"] = _utc_now_iso()
        notes[i] = updated
        data["notes"] = notes
        persisted = _persist(material_id, data)
        return {"material_id": material_id, "note": updated, "annotation": persisted}
    raise HTTPException(status_code=404, detail=f"note 不存在: {note_id}")


@router.delete("/{material_id}/notes/{note_id}")
async def delete_note(material_id: str, note_id: str):
    data = _read_annotation_data(material_id)
    notes = list(data["notes"])
    new_notes = [n for n in notes if not (isinstance(n, dict) and str(n.get("note_id")) == note_id)]
    if len(new_notes) == len(notes):
        raise HTTPException(status_code=404, detail=f"note 不存在: {note_id}")
    data["notes"] = new_notes
    persisted = _persist(material_id, data)
    return {"material_id": material_id, "note_id": note_id, "annotation": persisted}


# ---------------------------------------------------------------------------
# L2 — last-page (read progress)
# ---------------------------------------------------------------------------

@router.put("/{material_id}/last-page")
async def set_last_page(material_id: str, req: LastPageRequest):
    """Update read-progress. PUT shape — pair with the POST alias below
    for `navigator.sendBeacon()` clients (Beacon only sends POST).
    """
    return _set_last_page_inner(material_id, req.page)


@router.post("/{material_id}/last-page")
async def set_last_page_post(material_id: str, req: LastPageRequest):
    """POST alias of PUT /last-page so frontend can use
    `navigator.sendBeacon()` for unload flush. Per amendment §0.1: Beacon
    only supports POST. Identical semantics to the PUT endpoint.
    """
    return _set_last_page_inner(material_id, req.page)


def _set_last_page_inner(material_id: str, page: int | None) -> dict[str, Any]:
    data = _read_annotation_data(material_id)
    current = data.get("last_page")
    if current == page:
        # No-op; do not touch disk.
        return {
            "material_id": material_id,
            "last_page": current,
            "changed": False,
        }
    data["last_page"] = page
    persisted = _persist(material_id, data)
    return {
        "material_id": material_id,
        "last_page": persisted.get("last_page"),
        "changed": True,
    }


# ---------------------------------------------------------------------------
# L2 — Markdown export
# ---------------------------------------------------------------------------

_MD_ESCAPE = re.compile(r"([\\`*_{}\[\]()#+\-.!|>])")


def _escape_markdown(text: str) -> str:
    """Conservative Markdown escape so user-supplied note bodies cannot
    accidentally break the export structure (e.g. a `#` at line start
    becoming a header).
    """
    if not text:
        return ""
    return _MD_ESCAPE.sub(r"\\\1", text)


def _render_markdown(material_id: str, data: dict[str, Any]) -> str:
    """Render the annotation envelope as a Markdown blob."""
    lines: list[str] = []
    lines.append(f"# {material_id}")
    last_page = data.get("last_page")
    lines.append("")
    lines.append(f"> Last page read: {last_page if isinstance(last_page, int) else '—'}")
    lines.append(f"> Generated: {_utc_now_iso()}")
    lines.append("")

    highlights = [h for h in data.get("highlights") or [] if isinstance(h, dict)]
    if highlights:
        lines.append("## Highlights")
        lines.append("")
        by_page: dict[int, list[dict[str, Any]]] = {}
        for h in highlights:
            page = h.get("page") if isinstance(h.get("page"), int) else 0
            by_page.setdefault(int(page), []).append(h)
        for page in sorted(by_page.keys()):
            lines.append(f"### Page {page}")
            lines.append("")
            for h in by_page[page]:
                text = _escape_markdown(str(h.get("text") or ""))
                lines.append(f"- > {text}")
            lines.append("")

    notes = [n for n in data.get("notes") or [] if isinstance(n, dict)]
    if notes:
        lines.append("## Notes")
        lines.append("")
        for n in notes:
            page = n.get("page") if isinstance(n.get("page"), int) else 0
            anchor = _escape_markdown(str(n.get("anchor_text") or "")).strip()
            heading_tail = anchor if anchor else "页面笔记"
            lines.append(f"### Page {page} — {heading_tail}")
            lines.append("")
            body = _escape_markdown(str(n.get("body") or "")).strip()
            if body:
                lines.append(body)
                lines.append("")
            tags = [str(t) for t in (n.get("tags") or []) if isinstance(t, str) and t.strip()]
            if tags:
                lines.append(f"Tags: {', '.join(_escape_markdown(t) for t in tags)}")
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@router.get("/{material_id}/export.md")
async def export_markdown(material_id: str) -> Response:
    """Markdown blob: title + last_page metadata + highlights grouped
    by page + notes inlined under their anchor. User-supplied fields
    Markdown-escaped to avoid structural breakage.
    """
    data = _read_annotation_data(material_id)
    body = _render_markdown(material_id, data)
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{material_id}.md"',
            "Cache-Control": "no-store",
        },
    )
