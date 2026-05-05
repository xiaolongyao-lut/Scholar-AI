# -*- coding: utf-8 -*-
"""Annotation API Router — PDF highlight persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from literature_assistant.core.project_paths import runtime_state_path

router = APIRouter(prefix="/api/annotations", tags=["Annotations"])


def _annotations_dir() -> Path:
    p = runtime_state_path() / "annotations"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _annotation_file(material_id: str) -> Path:
    if "/" in material_id or "\\" in material_id or ".." in material_id:
        raise HTTPException(status_code=400, detail="Invalid material_id")
    return _annotations_dir() / f"{material_id}.json"


class Highlight(BaseModel):
    page: int = Field(..., ge=1)
    text: str = Field(..., min_length=1)
    color: str = Field("#FFEB3B", max_length=7)


class AnnotationData(BaseModel):
    material_id: str = Field(..., min_length=1)
    highlights: list[Highlight] = Field(default_factory=list)


class AddHighlightRequest(BaseModel):
    material_id: str = Field(..., min_length=1)
    highlight: Highlight


@router.get("/{material_id}")
async def get_annotations(material_id: str):
    f = _annotation_file(material_id)
    if not f.exists():
        return {"material_id": material_id, "highlights": []}
    data = json.loads(f.read_text(encoding="utf-8"))
    return data


@router.post("/{material_id}")
async def add_highlight(material_id: str, req: AddHighlightRequest):
    f = _annotation_file(material_id)
    existing: list[dict[str, Any]] = []
    if f.exists():
        existing = json.loads(f.read_text(encoding="utf-8")).get("highlights", [])

    existing.append(req.highlight.model_dump())

    annotation = {"material_id": material_id, "highlights": existing}
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)

    return annotation


@router.delete("/{material_id}")
async def clear_annotations(material_id: str):
    f = _annotation_file(material_id)
    if f.exists():
        f.unlink()
    return {"ok": True, "material_id": material_id}
