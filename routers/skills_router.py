# -*- coding: utf-8 -*-
"""Skills API Router - Manages writing skills, skill packs, and actions."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from models import (
    SkillDescriptorPayload,
    SkillPackPayload,
    CapabilityPayload,
    WritingActionPayload,
    RunActionRequest,
    RunActionAcceptedPayload,
    SkillRunResultPayload,
)

logger = logging.getLogger("SkillsRouter")
router = APIRouter(tags=["Skills"])


def _skill_payloads(
    ui_mode: str,
    kind: str | None = None,
    source: str | None = None,
) -> list[SkillDescriptorPayload]:
    """Return validated skill payloads from the writing skill service."""
    from skills.service import get_writing_skill_service
    service = get_writing_skill_service()
    return [
        SkillDescriptorPayload(**item)
        for item in service.list_skills(ui_mode=ui_mode, kind=kind, source=source)
    ]


@router.get("/skills", response_model=list[SkillDescriptorPayload])
async def list_skills(
    ui_mode: str = Query(default="skill_assisted"),
    kind: str | None = Query(default=None),
    source: str | None = Query(default=None),
) -> list[SkillDescriptorPayload]:
    """List available skills filtered for the requested UI mode."""
    return _skill_payloads(ui_mode=ui_mode, kind=kind, source=source)


@router.get("/skills/{skill_id}", response_model=SkillDescriptorPayload)
async def get_skill(skill_id: str) -> SkillDescriptorPayload:
    """Return one skill descriptor by ID."""
    from skills.service import get_writing_skill_service
    service = get_writing_skill_service()
    payload = service.get_skill(skill_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return SkillDescriptorPayload(**payload)


@router.get("/skill_packs", response_model=list[SkillPackPayload])
async def list_skill_packs(
    ui_mode: str = Query(default="skill_assisted"),
) -> list[SkillPackPayload]:
    """List available skill packs for the requested UI mode."""
    from skills.service import get_writing_skill_service
    service = get_writing_skill_service()
    return [SkillPackPayload(**item) for item in service.list_skill_packs(ui_mode=ui_mode)]


@router.get("/capabilities", response_model=list[CapabilityPayload])
async def list_capabilities() -> list[CapabilityPayload]:
    """List stable capability metadata exposed to the frontend."""
    from skills.service import get_writing_skill_service
    service = get_writing_skill_service()
    return [CapabilityPayload(**item) for item in service.list_capabilities()]


@router.get("/actions", response_model=list[WritingActionPayload])
async def list_actions() -> list[WritingActionPayload]:
    """List legacy-compatible actions backed by builtin skills."""
    from skills.service import get_writing_skill_service
    service = get_writing_skill_service()
    return [WritingActionPayload(**item) for item in service.list_legacy_actions()]


@router.post("/run_action", response_model=RunActionAcceptedPayload)
async def run_action(request: RunActionRequest) -> RunActionAcceptedPayload:
    """Run a writing action by delegating to the skill runtime."""
    from skills.service import get_writing_skill_service
    service = get_writing_skill_service()
    try:
        result = service.run_legacy_action(
            request.action_id,
            request.input_text,
            scope=request.scope,
            output_mode=request.output_mode,
        )
        return RunActionAcceptedPayload(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/transform_result/{job_id}", response_model=SkillRunResultPayload)
async def get_transform_result(job_id: str) -> SkillRunResultPayload:
    """Retrieve the result of a completed action transformation."""
    from skills.service import get_writing_skill_service
    service = get_writing_skill_service()
    payload = service.get_transform_result(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Job result not found: {job_id}")
    return SkillRunResultPayload(**payload)
