"""MCP local installer HTTP API (S3 / plan 2026-05-20 §A2-A3).

Three endpoints driving the wizard:

  POST /api/mcp/installations/scan      run scanner against local path
  POST /api/mcp/installations/preview   resolve a candidate (read-only)
  POST /api/mcp/installations/install   create server + optionally probe

Separate router instance keeps the registry CRUD in ``mcp_router.py`` lean.
Both are mounted under the ``/api/mcp`` namespace by ``python_adapter_server``.

Errors → HTTP mapping:

- ``InstallScanNotFoundError``        → 404 ``scan_not_found``
- ``InstallScanExpiredError``         → 410 ``scan_expired``
- ``InstallCandidateMismatchError``   → 400 ``candidate_mismatch``
- ``InstallCredentialMissingError``   → 400 ``credential_not_found``
- ``InstallCredentialDisabledError``  → 400 ``credential_disabled``
- ``InstallTransportUnsupportedError``→ 400 ``transport_unsupported``
- ``InstallSlugConflictError``        → 409 ``server_slug_conflict``
- ``McpPackageScanError``             → 400 ``scan_rejected``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from models.mcp_installation import McpPackageScanRequest, McpPackageScanResult
from mcp_runtime.package_scanner import (
    McpPackageScanError,
    McpPackageScanner,
    get_package_scanner,
)
from mcp_runtime.scan_registry import (
    McpScanRegistry,
    get_scan_registry,
)
from mcp_runtime.template_installer import (
    InstallCandidateMismatchError,
    InstallCredentialDisabledError,
    InstallCredentialMissingError,
    InstallError,
    InstallResult,
    InstallScanExpiredError,
    InstallScanNotFoundError,
    InstallSlugConflictError,
    InstallTransportUnsupportedError,
    McpTemplateInstaller,
    get_template_installer,
)


logger = logging.getLogger("McpInstallerRouter")
router = APIRouter(prefix="/api/mcp/installations", tags=["MCP-Installer"])


# ---------------------------------------------------------------------------
# Test-injectable singletons (router-local, so tests can swap one without
# touching the per-module ones in mcp_runtime/* — see test_mcp_installer_router)
# ---------------------------------------------------------------------------


_scanner: McpPackageScanner | None = None
_registry: McpScanRegistry | None = None
_installer: McpTemplateInstaller | None = None


def _get_scanner() -> McpPackageScanner:
    return _scanner if _scanner is not None else get_package_scanner()


def _get_registry() -> McpScanRegistry:
    return _registry if _registry is not None else get_scan_registry()


def _get_installer() -> McpTemplateInstaller:
    return _installer if _installer is not None else get_template_installer()


def set_router_scanner(s: McpPackageScanner | None) -> None:
    global _scanner
    _scanner = s


def set_router_scan_registry(r: McpScanRegistry | None) -> None:
    global _registry
    _registry = r


def set_router_installer(i: McpTemplateInstaller | None) -> None:
    global _installer
    _installer = i


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class InstallationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scan_id: str = Field(min_length=1, max_length=64)
    launch_candidate_sha: str = Field(min_length=1, max_length=64)


class InstallationInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scan_id: str = Field(min_length=1, max_length=64)
    launch_candidate_sha: str = Field(min_length=1, max_length=64)
    server_slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    config_values: dict[str, str] = Field(default_factory=dict)
    """Non-secret env values resolved from McpInstallConfigField inputs."""
    credential_bindings: dict[str, str] = Field(default_factory=dict)
    """Map env_name -> credential_id from McpRequiredCredential picker."""
    trust_to_probe: bool = False
    """Locked Revisions M7: True triggers list_tools probe + spawns process."""
    enable_for_session: bool = False
    """Only honored when trust_to_probe=True AND probe succeeds; advances
    approval from catalog_reviewed to enabled_for_session in one shot."""
    notes: str = Field(default="", max_length=1024)


class InstallationInstallResponse(BaseModel):
    """Public-facing shape; no raw secrets."""

    model_config = ConfigDict(extra="forbid")

    install_id: str
    server_id: str
    server: dict[str, Any]
    """McpServerConfigPublic as dict (env/header values masked)."""
    install_dir: str
    absolute_cwd: str
    approval_state: str
    probe: dict[str, Any]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/scan", response_model=McpPackageScanResult)
async def scan_local_package(
    body: McpPackageScanRequest,
) -> McpPackageScanResult:
    """Run the scanner against a local path. Caches result by scan_id with TTL."""
    scanner = _get_scanner()
    registry = _get_registry()
    try:
        result = scanner.scan(body)
    except McpPackageScanError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "scan_rejected", "message": str(exc)},
        ) from exc
    registry.register(result)
    # Cheap housekeeping; bounds memory in long-running servers.
    registry.purge_expired()
    return result


@router.post("/preview")
async def preview_install(
    body: InstallationPreviewRequest,
) -> dict[str, Any]:
    """Confirm scan_id + candidate sha are still valid; return the candidate."""
    installer = _get_installer()
    try:
        scan, candidate = installer.preview(
            scan_id=body.scan_id,
            launch_candidate_sha=body.launch_candidate_sha,
        )
    except InstallScanExpiredError as exc:
        raise HTTPException(
            status_code=410,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except InstallScanNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except InstallCandidateMismatchError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return {
        "scan_id": scan.scan_id,
        "source_path": scan.source_path,
        "package_id": scan.package_id,
        "display_name": scan.display_name,
        "description": scan.description,
        "version": scan.version,
        "transport": scan.transport,
        "candidate": candidate.model_dump(mode="json"),
        "config_fields": [f.model_dump(mode="json") for f in scan.config_fields],
        "required_credentials": [
            c.model_dump(mode="json") for c in scan.required_credentials
        ],
        "expected_tools": list(scan.expected_tools),
        "warnings": [w.model_dump(mode="json") for w in scan.warnings],
        "expires_at": scan.expires_at,
    }


@router.post("/install", response_model=InstallationInstallResponse)
async def install_package(
    body: InstallationInstallRequest,
) -> InstallationInstallResponse:
    """Create server from scan + bindings; probe + advance approval if trusted."""
    installer = _get_installer()
    try:
        result: InstallResult = await installer.install(
            scan_id=body.scan_id,
            launch_candidate_sha=body.launch_candidate_sha,
            server_slug=body.server_slug,
            display_name=body.display_name,
            config_values=dict(body.config_values),
            credential_bindings=dict(body.credential_bindings),
            trust_to_probe=body.trust_to_probe,
            enable_for_session=body.enable_for_session,
            notes=body.notes,
        )
    except InstallScanExpiredError as exc:
        raise HTTPException(status_code=410, detail={"code": exc.code, "message": str(exc)}) from exc
    except InstallScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc
    except InstallSlugConflictError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    except (
        InstallCandidateMismatchError,
        InstallCredentialMissingError,
        InstallCredentialDisabledError,
        InstallTransportUnsupportedError,
    ) as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from exc
    except InstallError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    return InstallationInstallResponse(
        install_id=result.install_id,
        server_id=result.server.server_id,
        server=result.server.model_dump(mode="json"),
        install_dir=result.install_dir,
        absolute_cwd=result.absolute_cwd,
        approval_state=result.approval_state,
        probe={
            "status": result.probe.status,
            "tool_count": result.probe.tool_count,
            "tools": list(result.probe.tools),
            "reason": result.probe.reason,
        },
    )


__all__ = [
    "InstallationInstallRequest",
    "InstallationInstallResponse",
    "InstallationPreviewRequest",
    "router",
    "set_router_installer",
    "set_router_scan_registry",
    "set_router_scanner",
]
