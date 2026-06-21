"""Passive Scholar AI workflow health checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from models import ToolAttempt, ToolNextAction, ToolOutcome
from project_paths import WORKSPACE_OUTPUT_ROOT, WORKSPACE_RUNTIME_STATE_ROOT


HEALTH_CHECK_SCHEMA_VERSION = "scholar-ai-health-check/v1"
HealthStatus = Literal["ok", "degraded", "blocked"]

router = APIRouter(prefix="/api/health", tags=["System"])


class HealthCheckItem(BaseModel):
    """One passive readiness check for the local Scholar AI workflow.

    Args:
        name: Stable check identifier.
        status: Result for this check.
        reason: Short non-secret explanation.
        details: Small JSON-safe diagnostic details.
        next_action: Optional follow-up that can be rendered by UI or agents.
    """

    name: str = Field(min_length=1, max_length=120)
    status: HealthStatus
    reason: str = Field(default="", max_length=500)
    details: dict[str, Any] = Field(default_factory=dict)
    next_action: ToolNextAction | None = None


class HealthCheckResponse(BaseModel):
    """Current local workflow readiness response.

    Args:
        schema_version: Versioned response contract.
        status: Aggregated result across all checks.
        generated_at: UTC timestamp.
        include_live: Whether live probes were requested. This endpoint keeps
            default checks passive and records the flag for explicit live modes.
        checks: Ordered readiness/dependency checks.
        recommendations: Deduplicated next actions from degraded/blocked checks.
        outcome: ToolOutcome envelope for MCP and agent consumers.
    """

    schema_version: Literal["scholar-ai-health-check/v1"] = HEALTH_CHECK_SCHEMA_VERSION
    status: HealthStatus
    generated_at: str
    include_live: bool = False
    checks: list[HealthCheckItem] = Field(default_factory=list)
    recommendations: list[ToolNextAction] = Field(default_factory=list)
    outcome: ToolOutcome


def _now_iso_z() -> str:
    """Return a second-resolution UTC timestamp for diagnostics."""

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _host_label(value: str | None) -> str:
    """Return a host-only label so health output never leaks full endpoints."""

    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    return (parsed.netloc or parsed.path).split("/", 1)[0].lower()


def _read_json_file(path: Path) -> dict[str, Any]:
    """Read a small JSON object, returning an empty mapping on bad local state."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _path_check() -> HealthCheckItem:
    """Check local runtime/output workspace roots without writing files."""

    details = {
        "runtime_state_root": str(WORKSPACE_RUNTIME_STATE_ROOT),
        "output_root": str(WORKSPACE_OUTPUT_ROOT),
        "runtime_state_exists": WORKSPACE_RUNTIME_STATE_ROOT.exists(),
        "output_root_exists": WORKSPACE_OUTPUT_ROOT.exists(),
    }
    if WORKSPACE_RUNTIME_STATE_ROOT.exists() and WORKSPACE_OUTPUT_ROOT.exists():
        return HealthCheckItem(
            name="workspace_paths",
            status="ok",
            reason="Runtime and output roots exist.",
            details=details,
        )
    return HealthCheckItem(
        name="workspace_paths",
        status="degraded",
        reason="Runtime or output root is not initialized yet.",
        details=details,
        next_action=ToolNextAction(
            kind="retry_later",
            message="Run the standard path diagnostic before continuing.",
            command_preview="& .\\.venv-1\\Scripts\\python.exe .\\run_literature_assistant.py paths",
        ),
    )


def _resource_index_check() -> HealthCheckItem:
    """Inspect project/material/chunk readiness without reading full text."""

    try:
        from writing_resources import get_writing_resource_store

        store = get_writing_resource_store()
        projects = store.list_projects()
        material_count = 0
        chunk_count = 0
        for project in projects[:50]:
            project_id = str(getattr(project, "project_id", "") or "")
            if not project_id:
                continue
            materials = store.list_materials(project_id)
            material_count += len(materials)
            try:
                import routers.resources_router as resources_router

                chunk_store = resources_router._load_chunk_store(project_id)
            except (ImportError, AttributeError, OSError, ValueError):
                chunk_store = {}
            if isinstance(chunk_store, dict):
                chunk_count += sum(len(items) for items in chunk_store.values() if isinstance(items, list))
    except Exception as exc:  # pragma: no cover - defensive startup guard
        return HealthCheckItem(
            name="project_index",
            status="blocked",
            reason="Project resource store could not be inspected.",
            details={"error_class": exc.__class__.__name__},
            next_action=ToolNextAction(
                kind="retry_later",
                message="Restart the backend or inspect resource-store initialization errors.",
            ),
        )

    details = {
        "project_count": len(projects),
        "material_count": material_count,
        "chunk_count": chunk_count,
    }
    if chunk_count > 0:
        return HealthCheckItem(
            name="project_index",
            status="ok",
            reason="At least one indexed chunk is available for retrieval.",
            details=details,
        )
    if material_count > 0:
        return HealthCheckItem(
            name="project_index",
            status="degraded",
            reason="Materials exist, but no indexed chunks were found.",
            details=details,
            next_action=ToolNextAction(
                kind="scan_folder",
                message="Scan the project source folder so retrieval and evidence packs can read chunks.",
                tool_name="literature.project_scan_folder",
            ),
        )
    return HealthCheckItem(
        name="project_index",
        status="degraded",
        reason="No project materials are available yet.",
        details=details,
        next_action=ToolNextAction(
            kind="bind_source_folder",
            message="Create or select a project source folder, then scan it.",
            tool_name="literature.project_scan_folder",
        ),
    )


def _provider_capability_check() -> HealthCheckItem:
    """Read provider tool-call capability records without probing the network."""

    try:
        from provider_capabilities import CAPABILITY_STATUS_AUTH_REQUIRED, CAPABILITY_STATUS_TOOL_CALL_OK
        from provider_capabilities import provider_capability_store

        payload = _read_json_file(provider_capability_store.path)
        records = payload.get("records") if isinstance(payload, dict) else {}
        record_values = list(records.values()) if isinstance(records, dict) else []
    except Exception as exc:  # pragma: no cover - defensive startup guard
        return HealthCheckItem(
            name="provider_tool_capability",
            status="blocked",
            reason="Provider capability store could not be inspected.",
            details={"error_class": exc.__class__.__name__},
            next_action=ToolNextAction(
                kind="open_settings",
                message="Open model settings and rerun the provider capability probe.",
                endpoint="/api/chat/tool-capability/test",
            ),
        )

    status_counts: dict[str, int] = {}
    ok_records = 0
    auth_required = 0
    for raw in record_values:
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == CAPABILITY_STATUS_TOOL_CALL_OK and bool(raw.get("forced_tool_choice_ok")):
            ok_records += 1
        if status == CAPABILITY_STATUS_AUTH_REQUIRED:
            auth_required += 1
    details = {
        "record_count": len(record_values),
        "tool_call_ok_count": ok_records,
        "status_counts": status_counts,
    }
    if ok_records > 0:
        return HealthCheckItem(
            name="provider_tool_capability",
            status="ok",
            reason="At least one provider/model endpoint has proven native tool-call support.",
            details=details,
        )
    if auth_required > 0:
        status: HealthStatus = "blocked"
        reason = "Provider capability records require authentication."
    else:
        status = "degraded"
        reason = "No provider tool-call capability record is proven yet."
    return HealthCheckItem(
        name="provider_tool_capability",
        status=status,
        reason=reason,
        details=details,
        next_action=ToolNextAction(
            kind="configure_provider",
            message="Run the model tool-capability probe from settings before relying on provider-selected tools.",
            endpoint="/api/chat/tool-capability/test",
        ),
    )


def _rerank_check() -> HealthCheckItem:
    """Inspect rerank override state without sending credentials to a provider."""

    try:
        import rerank_runtime_config

        public_config = rerank_runtime_config.get_public_config()
    except Exception as exc:  # pragma: no cover - defensive startup guard
        return HealthCheckItem(
            name="rerank_config",
            status="degraded",
            reason="Rerank config could not be inspected.",
            details={"error_class": exc.__class__.__name__},
            next_action=ToolNextAction(
                kind="configure_rerank",
                message="Open rerank settings and save a valid rerank provider configuration.",
            ),
        )
    details = {
        "provider": str(public_config.get("provider") or ""),
        "base_url_host": _host_label(str(public_config.get("base_url") or "")),
        "model": str(public_config.get("model") or ""),
        "has_api_key": bool(public_config.get("has_api_key")),
        "updated_at": str(public_config.get("updated_at") or ""),
    }
    if details["has_api_key"] and details["model"]:
        return HealthCheckItem(
            name="rerank_config",
            status="ok",
            reason="A rerank runtime override is configured.",
            details=details,
        )
    return HealthCheckItem(
        name="rerank_config",
        status="degraded",
        reason="Rerank is not fully configured; retrieval can still fall back to lexical/hybrid paths.",
        details=details,
        next_action=ToolNextAction(
            kind="configure_rerank",
            message="Configure rerank if semantic reranking is required for this workflow.",
        ),
    )


def _agent_bridge_check() -> HealthCheckItem:
    """Check whether the agent-bridge router can persist runtime jobs."""

    try:
        from writing_runtime import get_writing_runtime

        runtime, _ = get_writing_runtime()
        session_count = len(getattr(runtime, "_sessions", {}) or {})
        job_count = len(getattr(runtime, "_jobs", {}) or {})
    except Exception as exc:  # pragma: no cover - defensive startup guard
        return HealthCheckItem(
            name="agent_bridge_runtime",
            status="blocked",
            reason="Writing runtime could not be inspected.",
            details={"error_class": exc.__class__.__name__},
            next_action=ToolNextAction(
                kind="retry_later",
                message="Restart the backend before creating agent bridge jobs.",
            ),
        )
    return HealthCheckItem(
        name="agent_bridge_runtime",
        status="ok",
        reason="Runtime job store is importable and ready for agent bridge jobs.",
        details={"session_count": session_count, "job_count": job_count},
    )


def _optional_live_check(include_live: bool) -> HealthCheckItem:
    """Record live-probe policy without making network calls by default."""

    if include_live:
        return HealthCheckItem(
            name="live_probe_policy",
            status="degraded",
            reason="Live probing was requested, but this health check currently remains passive.",
            details={"include_live": True},
            next_action=ToolNextAction(
                kind="configure_provider",
                message="Use the dedicated provider capability probe for low-budget live validation.",
                endpoint="/api/chat/tool-capability/test",
            ),
        )
    return HealthCheckItem(
        name="live_probe_policy",
        status="ok",
        reason="No live provider/API calls were made by this health check.",
        details={"include_live": False},
    )


def _overall_status(checks: list[HealthCheckItem]) -> HealthStatus:
    """Return the aggregate workflow status."""

    if any(item.status == "blocked" for item in checks):
        return "blocked"
    if any(item.status == "degraded" for item in checks):
        return "degraded"
    return "ok"


def _recommendations(checks: list[HealthCheckItem]) -> list[ToolNextAction]:
    """Return deduplicated next actions for degraded or blocked checks."""

    seen: set[tuple[str, str, str]] = set()
    actions: list[ToolNextAction] = []
    prioritized_checks = sorted(
        checks,
        key=lambda item: {"blocked": 0, "degraded": 1, "ok": 2}[item.status],
    )
    for item in prioritized_checks:
        if item.status == "ok" or item.next_action is None:
            continue
        key = (item.next_action.kind, item.next_action.tool_name or "", item.next_action.endpoint or "")
        if key in seen:
            continue
        seen.add(key)
        actions.append(item.next_action)
    return actions


def build_health_check_response(include_live: bool = False) -> HealthCheckResponse:
    """Build a passive workflow health response.

    Args:
        include_live: Records explicit live-probe intent. The current
            implementation remains passive and points callers to dedicated
            low-budget probes instead of spending quota here.

    Returns:
        A versioned response with check items, recommendations, and outcome.
    """

    checks = [
        _path_check(),
        _resource_index_check(),
        _provider_capability_check(),
        _rerank_check(),
        _agent_bridge_check(),
        _optional_live_check(include_live),
    ]
    status = _overall_status(checks)
    recommendations = _recommendations(checks)
    attempts = [
        ToolAttempt(
            stage=item.name,
            status="success" if item.status == "ok" else ("blocked" if item.status == "blocked" else "degraded"),
            reason=item.reason,
            metadata=item.details,
        )
        for item in checks
    ]
    next_action = recommendations[0] if recommendations else ToolNextAction(kind="none", message="")
    outcome = ToolOutcome(
        status="success" if status == "ok" else status,
        quality="full" if status == "ok" else "partial",
        reason=(
            "Scholar AI workflow readiness checks passed."
            if status == "ok"
            else "Scholar AI workflow readiness is degraded or blocked; inspect recommendations."
        ),
        next_action=next_action,
        attempts=attempts,
    )
    return HealthCheckResponse(
        status=status,
        generated_at=_now_iso_z(),
        include_live=include_live,
        checks=checks,
        recommendations=recommendations,
        outcome=outcome,
    )


@router.get("/check", response_model=HealthCheckResponse)
async def get_health_check(include_live: bool = Query(default=False)) -> HealthCheckResponse:
    """Return passive Scholar AI workflow readiness."""

    return build_health_check_response(include_live=include_live)


__all__ = [
    "HEALTH_CHECK_SCHEMA_VERSION",
    "HealthCheckItem",
    "HealthCheckResponse",
    "build_health_check_response",
    "router",
]
