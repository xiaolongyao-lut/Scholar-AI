# -*- coding: utf-8 -*-
"""Skills API Router - Manages writing skills, skill packs, and actions."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from models import (
    SkillDescriptorPayload,
    SkillSecurityAssessmentPayload,
    SkillPackPayload,
    CapabilityPayload,
    WritingActionPayload,
    RunActionRequest,
    RunActionAcceptedPayload,
    SkillRunResultPayload,
    ImportUserSkillRequest,
    ImportUserSkillResponse,
    SkillToggleResponse,
    SkillTestRunResponse,
    SkillRuntimeSettingsUpdate,
    SkillRuntimeSettingsResponse,
    SkillApprovalRequestCreate,
    SkillApprovalRequestPayload,
    SkillApprovalDecisionCreate,
    SkillApprovalDecisionPayload,
    SkillApprovalDetailPayload,
    SkillUninstallResponse,
    SkillRollbackRequest,
    SkillRollbackResponse,
    SkillExportResponse,
)

logger = logging.getLogger("SkillsRouter")
router = APIRouter(tags=["Skills"])


def get_skill_service():
    """Return the writing skill service used by this router."""
    from skills.service import get_writing_skill_service

    return get_writing_skill_service()


def _skill_payloads(
    ui_mode: str,
    kind: str | None = None,
    source: str | None = None,
) -> list[SkillDescriptorPayload]:
    """Return validated skill payloads from the writing skill service."""
    service = get_skill_service()
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


@router.get("/skills/audit")
async def get_skill_audit(
    skill_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """Get audit events for skill operations."""
    service = get_skill_service()
    return service.list_audit_events(skill_id=skill_id, limit=limit)


@router.post("/skills/approvals/requests", response_model=SkillApprovalRequestPayload)
async def create_skill_approval_request(
    request: SkillApprovalRequestCreate,
) -> SkillApprovalRequestPayload:
    """Create a persistent approval request for a skill capability."""
    service = get_skill_service()
    try:
        payload = service.submit_approval_request(
            capability_id=request.capability_id,
            capability_name=request.capability_name,
            reason=request.reason,
            context=request.context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillApprovalRequestPayload(**payload)


@router.get("/skills/approvals/pending", response_model=list[SkillApprovalRequestPayload])
async def list_pending_skill_approvals() -> list[SkillApprovalRequestPayload]:
    """List approval requests without a final approve or deny decision."""
    service = get_skill_service()
    return [SkillApprovalRequestPayload(**item) for item in service.list_pending_approval_requests()]


@router.get("/skills/approvals/{request_id}", response_model=SkillApprovalDetailPayload)
async def get_skill_approval_detail(request_id: str) -> SkillApprovalDetailPayload:
    """Return one approval request with latest decision and full decision history."""
    service = get_skill_service()
    try:
        payload = service.get_approval_detail(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Approval request not found: {request_id}")
    return SkillApprovalDetailPayload(**payload)


@router.get("/skills/{skill_id}/security", response_model=SkillSecurityAssessmentPayload)
async def get_skill_security_assessment(skill_id: str) -> SkillSecurityAssessmentPayload:
    """Return the current machine-readable runtime safety policy for one Skill."""
    service = get_skill_service()
    try:
        payload = service.get_skill_security_assessment(skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return SkillSecurityAssessmentPayload(**payload)


@router.post("/skills/approvals/{request_id}/decide", response_model=SkillApprovalDecisionPayload)
async def decide_skill_approval_request(
    request_id: str,
    request: SkillApprovalDecisionCreate,
) -> SkillApprovalDecisionPayload:
    """Record a user decision for one approval request."""
    service = get_skill_service()
    try:
        payload = service.decide_approval_request(
            request_id=request_id,
            decision=request.decision,
            user_id=request.user_id,
            reason=request.reason,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return SkillApprovalDecisionPayload(**payload)


@router.get("/skills/{skill_id}", response_model=SkillDescriptorPayload)
async def get_skill(skill_id: str) -> SkillDescriptorPayload:
    """Return one skill descriptor by ID."""
    service = get_skill_service()
    payload = service.get_skill(skill_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return SkillDescriptorPayload(**payload)


@router.put("/skills/{skill_id}/runtime-settings", response_model=SkillRuntimeSettingsResponse)
async def update_skill_runtime_settings(
    skill_id: str,
    request: SkillRuntimeSettingsUpdate,
) -> SkillRuntimeSettingsResponse:
    """Persist manifest-driven Skill settings without storing credential material."""
    service = get_skill_service()
    try:
        payload = service.update_skill_runtime_settings(
            skill_id,
            config_values=dict(request.config_values),
            credential_bindings=dict(request.credential_bindings),
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillRuntimeSettingsResponse(**payload)


@router.get("/skill_packs", response_model=list[SkillPackPayload])
async def list_skill_packs(
    ui_mode: str = Query(default="skill_assisted"),
) -> list[SkillPackPayload]:
    """List available skill packs for the requested UI mode."""
    service = get_skill_service()
    return [SkillPackPayload(**item) for item in service.list_skill_packs(ui_mode=ui_mode)]


@router.get("/capabilities", response_model=list[CapabilityPayload])
async def list_capabilities() -> list[CapabilityPayload]:
    """List stable capability metadata exposed to the frontend."""
    service = get_skill_service()
    return [CapabilityPayload(**item) for item in service.list_capabilities()]


@router.get("/actions", response_model=list[WritingActionPayload])
async def list_actions() -> list[WritingActionPayload]:
    """List legacy-compatible actions backed by builtin skills."""
    service = get_skill_service()
    return [WritingActionPayload(**item) for item in service.list_legacy_actions()]


@router.post("/run_action", response_model=RunActionAcceptedPayload)
async def run_action(request: RunActionRequest) -> RunActionAcceptedPayload:
    """Run a writing action by delegating to the skill runtime."""
    service = get_skill_service()
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
    service = get_skill_service()
    payload = service.get_transform_result(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Job result not found: {job_id}")
    return SkillRunResultPayload(**payload)


# =========================================================================
# User Skill Management
# =========================================================================

@router.post("/skills/import", response_model=ImportUserSkillResponse)
async def import_user_skill_endpoint(request: ImportUserSkillRequest) -> ImportUserSkillResponse:
    """Import a user skill package from a local directory or zip archive."""
    try:
        service = get_skill_service()
        result = service.import_user_skill(
            source_path=request.source_path,
            managed_root=None,  # Server-side fixed root for security
            origin=request.origin,
        )
    except ValueError as exc:
        detail = str(exc)
        error_code = "SOURCE_PATH_NOT_FOUND" if "does not exist" in detail.lower() else "INVALID_SOURCE_PATH"
        raise HTTPException(status_code=400, detail={"error_code": error_code, "errors": [detail]}) from exc
    if not result.get("success", False):
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": result.get("error_code", "IMPORT_VALIDATION_FAILED"),
                "errors": result.get("errors", []),
            },
        )
    return ImportUserSkillResponse(**result)


@router.post("/skills/{skill_id}/enable", response_model=SkillToggleResponse)
async def enable_skill(skill_id: str) -> SkillToggleResponse:
    """Enable a user skill."""
    service = get_skill_service()
    try:
        result = service.enable_skill(skill_id)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")
    return SkillToggleResponse(**result)


@router.post("/skills/{skill_id}/disable", response_model=SkillToggleResponse)
async def disable_skill(
    skill_id: str,
    reason: str = Query(default="Disabled by user"),
) -> SkillToggleResponse:
    """Disable a user skill."""
    service = get_skill_service()
    try:
        result = service.disable_skill(skill_id, reason=reason)
    except ValueError as exc:
        detail = str(exc)
        status_code = 400 if "Builtin skills cannot" in detail else 404
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return SkillToggleResponse(**result)


@router.delete("/skills/{skill_id}", response_model=SkillUninstallResponse)
async def uninstall_skill(
    skill_id: str,
    dry_run: bool = Query(default=False),
) -> SkillUninstallResponse:
    """Uninstall a managed user skill after creating a rollback snapshot."""
    service = get_skill_service()
    try:
        result = service.uninstall_skill(skill_id, dry_run=dry_run)
    except ValueError as exc:
        detail = str(exc)
        if "Builtin skills cannot" in detail:
            status_code = 403
        elif "not found" in detail.lower():
            status_code = 404
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return SkillUninstallResponse(**result)


@router.post("/skills/{skill_id}/rollback", response_model=SkillRollbackResponse)
async def rollback_skill(
    skill_id: str,
    request: SkillRollbackRequest | None = None,
) -> SkillRollbackResponse:
    """Restore a managed user skill from a rollback snapshot."""
    service = get_skill_service()
    try:
        result = service.rollback_skill(
            skill_id,
            backup_path=request.backup_path if request is not None else None,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return SkillRollbackResponse(**result)


@router.post("/skills/{skill_id}/export", response_model=SkillExportResponse)
async def export_skill(
    skill_id: str,
    output_path: str | None = Query(default=None),
) -> SkillExportResponse:
    """Export a user skill to a zip archive.

    J11 (2026-05-26): Export user skill package for backup/sharing.

    Args:
        skill_id: Skill ID to export.
        output_path: Optional output zip filename under workspace_artifacts/skill_exports.

    Returns:
        SkillExportResponse with success/export_path/errors.

    Raises:
        404: Skill not found.
        400: Cannot export builtin skill or skill directory not found.
    """
    service = get_skill_service()
    try:
        result = service.export_user_skill(skill_id, output_path=output_path)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            status_code = 404
        elif "builtin" in detail.lower():
            status_code = 400
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    if not result["success"]:
        raise HTTPException(status_code=500, detail={"errors": result["errors"]})

    return SkillExportResponse(**result)



@router.post("/skills/{skill_id}/test-run", response_model=SkillTestRunResponse)
async def test_run_skill(
    skill_id: str,
    input_text: str = Query(default="This is a test input for skill validation."),
) -> SkillTestRunResponse:
    """Test-run a skill with sample input."""
    service = get_skill_service()
    if not service.has_skill(skill_id):
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_id}")

    result = service.run_skill(skill_id=skill_id, input_text=input_text)
    return SkillTestRunResponse(**result.to_dict())
