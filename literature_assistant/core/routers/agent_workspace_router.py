# -*- coding: utf-8 -*-
"""Read-only Agent Workspace API for local MCP workflow visibility."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from pdf_backends import public_ocr_status
from project_paths import (
    REPO_ROOT,
    WORKSPACE_ARTIFACTS_ROOT,
    WORKSPACE_OUTPUT_ROOT,
    WORKSPACE_RUNTIME_STATE_ROOT,
    wiki_runtime_db_path,
)
from runtime_env import wiki_enabled
from wiki.source_registry import WikiRegistry


router = APIRouter(prefix="/api/agent-workspace", tags=["Agent Workspace"])

WORKSPACE_DIR_NAME = "agent_mcp_workflows"
AUDIT_DIR_NAME = ".audit"
MAX_ARTIFACTS = 500
MAX_AUDIT_RECORDS = 1000
MAX_PREVIEW_CHARS = 12000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DIRECTORY_STATE_FILES = 1000
MAX_STATE_PATHS = 8
MAX_GOAL_STATE_ACTIONS = 3
MAX_GOAL_STATE_BOUNDARIES = 4
MAX_GOAL_STATE_OPEN_REQUIREMENTS = 5
MAX_GOAL_STATE_AUTH_RECORDS = 8
MAX_GOAL_STATE_MATURE_REFERENCES = 4
MAX_GOAL_STATE_CHANGED_FILES = 8
MAX_GOAL_STATE_VERIFICATION_COMMANDS = 6
MAX_GOAL_LIFECYCLE_BLOCKERS = 5
MAX_GOAL_LIFECYCLE_STATUS_COUNTS = 8
MAX_GOAL_COMPLETION_CHARS = 240
MAX_GOAL_REQUIREMENT_EVIDENCE = 8
MAX_GOAL_REQUIREMENT_TEXT_CHARS = 480
MAX_GOAL_ROLLBACK_CAVEAT_CHARS = 240
MAX_DESKTOP_SMOKE_TEXT_ITEMS = 3
MAX_OCR_RUNTIME_ENGINES = 12
MAX_OCR_RUNTIME_ACTIONS = 5
MAX_OCR_RUNTIME_BLOCKERS = 5
MAX_WIKI_DOCTOR_ACTIONS = 4
MAX_KRT_ACTUAL_LOADING_ACTIONS = 4
MAX_KRT_ACTUAL_LOADING_BLOCKERS = 4
MAX_KRT_ACTUAL_LOADING_MISSING = 4
AGENT_WORKSPACE_DESKTOP_ACCEPTANCE_PATH = "/__desktop_acceptance/agent-workspace"
GIT_STATUS_TIMEOUT_SECONDS = 2.0
OPEN_REQUIREMENT_STATUSES = frozenset(
    {
        "contradicted",
        "incomplete",
        "weak_indirect_evidence",
        "missing_evidence",
        "out_of_scope",
    }
)


class AgentWorkspaceArtifact(BaseModel):
    """One visible workflow artifact."""

    path: str
    name: str
    kind: str
    size_bytes: int = Field(ge=0)
    modified_at: str
    preview: str = ""
    truncated: bool = False


class AgentWorkspaceAuditRecord(BaseModel):
    """One redacted MCP tool audit event."""

    timestamp: str
    tool_name: str
    args_summary: dict[str, Any] = Field(default_factory=dict)
    touched_paths: list[str] = Field(default_factory=list)
    allow_block_reason: str = ""
    result_preview: str = ""
    duration_ms: int = Field(default=0, ge=0)
    error_code: str | None = None


class AgentWorkspaceDirectoryState(BaseModel):
    """Bounded local directory summary for workspace recovery checks."""

    label: str
    path: str
    exists: bool
    file_count: int = Field(default=0, ge=0)
    total_bytes: int = Field(default=0, ge=0)
    truncated: bool = False


class AgentWorkspaceGitState(BaseModel):
    """Read-only git state summary for local recovery decisions."""

    available: bool
    branch: str | None = None
    ahead: int = Field(default=0, ge=0)
    behind: int = Field(default=0, ge=0)
    changed_count: int = Field(default=0, ge=0)
    staged_count: int = Field(default=0, ge=0)
    unstaged_count: int = Field(default=0, ge=0)
    untracked_count: int = Field(default=0, ge=0)
    conflicted_count: int = Field(default=0, ge=0)
    dirty_paths: list[str] = Field(default_factory=list)
    error: str | None = None


class AgentWorkspaceRecoveryProbe(BaseModel):
    """One read-only recovery endpoint a resumed agent can inspect.

    Args:
        label: Stable display label for the recovery surface.
        route: Local route or route pattern. Placeholder routes require an
            identifier supplied from visible runtime state.
        read_only: Whether this probe is diagnostic only.
        requires_identifier: Whether the route pattern needs a job/request id.
        identifier_hint: Identifier name expected by the route pattern.
        purpose: Why this probe should be read before mutating workflow state.
        mcp_tool: Optional MCP tool exposing the same read-only projection.
    """

    label: str = Field(min_length=1, max_length=120)
    route: str = Field(min_length=1, max_length=240)
    read_only: bool = True
    requires_identifier: bool = False
    identifier_hint: str | None = Field(default=None, max_length=80)
    purpose: str = Field(min_length=1, max_length=240)
    mcp_tool: str | None = Field(default=None, max_length=120)


class AgentWorkspaceGoalCompletionClaim(BaseModel):
    """Bounded longrun completion-claim summary for resume decisions.

    Args:
        this_slice: Short local slice completion claim.
        full_goal: Short full-goal completion boundary claim.
        can_mark_goal_complete: Whether a resumed agent may mark the full goal complete.
        why_not_complete: Short reason the full goal remains active.
    """

    this_slice: str | None = Field(default=None, max_length=MAX_GOAL_COMPLETION_CHARS)
    full_goal: str | None = Field(default=None, max_length=MAX_GOAL_COMPLETION_CHARS)
    can_mark_goal_complete: bool | None = None
    why_not_complete: str | None = Field(default=None, max_length=MAX_GOAL_COMPLETION_CHARS)


class AgentWorkspaceGoalRequirementStatus(BaseModel):
    """Bounded requirement-to-evidence status summary for resume decisions.

    Args:
        total: Number of requirement rows in the selected goal-state record.
        proved: Rows backed by concrete implementation, command, artifact, or
            runtime evidence.
        incomplete: Rows that still need stronger local evidence or tooling.
        out_of_scope: Rows explicitly excluded by the current user boundary.
        latest_id: Last row id in the requirement matrix.
    """

    total: int = Field(default=0, ge=0)
    proved: int = Field(default=0, ge=0)
    incomplete: int = Field(default=0, ge=0)
    out_of_scope: int = Field(default=0, ge=0)
    latest_id: str | None = Field(default=None, max_length=160)


class AgentWorkspaceGoalOpenRequirement(BaseModel):
    """Bounded unresolved requirement row for recovery decisions.

    Args:
        id: Requirement matrix id.
        status: Current requirement-to-evidence state.
        requirement: Short redacted requirement text.
        residual_risk: Short redacted residual risk or blocker note.
    """

    id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=80)
    requirement: str | None = Field(default=None, max_length=240)
    residual_risk: str | None = Field(default=None, max_length=240)


class AgentWorkspaceGoalLifecycleBlocker(BaseModel):
    """One bounded goal-level blocker from the longrun lifecycle rollup.

    Args:
        id: Stable blocker id.
        status: Current blocker state.
        requirement_surface: Short product or workflow surface affected.
        missing_evidence: Missing proof needed before completion can be claimed.
        current_boundary: Current authorization, tooling, or evidence boundary.
        evidence: Current bounded evidence explaining why this blocker still applies.
    """

    id: str = Field(min_length=1, max_length=160)
    status: str | None = Field(default=None, max_length=120)
    requirement_surface: str | None = Field(default=None, max_length=240)
    missing_evidence: str | None = Field(default=None, max_length=240)
    current_boundary: str | None = Field(default=None, max_length=240)
    evidence: str | None = Field(default=None, max_length=240)


class AgentWorkspaceGoalLifecycleRollup(BaseModel):
    """Machine-readable longrun goal lifecycle summary for recovery decisions.

    Args:
        schema_version: Source rollup schema identifier.
        updated_at: Timestamp from the rollup.
        status: Goal-level lifecycle status, distinct from requirement rows.
        is_goal_complete: Whether the longrun goal itself is complete.
        can_mark_goal_complete: Whether a resumed agent may mark it complete.
        requirements_total: Total requirement rows recorded by the rollup.
        requirement_status_counts: Bounded requirement row counts by status.
        requirements_all_proved: Whether all rows are currently proved.
        requirements_all_proved_or_out_of_scope: Whether every row is proved or
            explicitly outside scope.
        latest_requirement_id: Latest requirement row id recorded by the rollup.
        latest_slice_id: Latest slice id recorded by the rollup.
        completion_blockers: Bounded unresolved goal-level blockers.
        machine_readable_completion_rule: Compact rule for completion claims.
        why_not_complete: Bounded explanation list when the goal remains active.
    """

    schema_version: str | None = Field(default=None, max_length=120)
    updated_at: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=160)
    is_goal_complete: bool | None = None
    can_mark_goal_complete: bool | None = None
    requirements_total: int | None = Field(default=None, ge=0)
    requirement_status_counts: dict[str, int] = Field(default_factory=dict)
    requirements_all_proved: bool | None = None
    requirements_all_proved_or_out_of_scope: bool | None = None
    latest_requirement_id: str | None = Field(default=None, max_length=160)
    latest_slice_id: str | None = Field(default=None, max_length=160)
    completion_blockers: list[AgentWorkspaceGoalLifecycleBlocker] = Field(default_factory=list)
    machine_readable_completion_rule: str | None = Field(default=None, max_length=240)
    why_not_complete: list[str] = Field(default_factory=list)


class AgentWorkspaceGoalMatureReference(BaseModel):
    """One bounded mature-reference record from the longrun goal state.

    Args:
        topic: Slice-specific reason this reference was checked.
        source: Official or mature reference label.
        url: Reference URL or local reference label.
        status: Reachability or review status recorded by the slice.
        checked_at: Timestamp recorded by the slice.
        use_in_slice: Bounded note explaining the borrowed boundary.
    """

    topic: str | None = Field(default=None, max_length=160)
    source: str | None = Field(default=None, max_length=160)
    url: str | None = Field(default=None, max_length=240)
    status: str | None = Field(default=None, max_length=160)
    checked_at: str | None = Field(default=None, max_length=80)
    use_in_slice: str | None = Field(default=None, max_length=240)


class AgentWorkspaceGoalRequirementEvidenceRef(BaseModel):
    """One bounded evidence reference from the longrun requirement matrix.

    Args:
        label: Short evidence reference label, preserving list order.
        text: Redacted evidence reference text or compact JSON preview.
    """

    label: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=MAX_GOAL_REQUIREMENT_TEXT_CHARS)


class AgentWorkspaceGoalRequirementDrilldown(BaseModel):
    """Read-only requirement-to-evidence drilldown for one longrun row.

    Args:
        schema_version: Stable payload schema for REST, MCP, and UI callers.
        available: Whether the requested requirement was found.
        read_only: Confirms this projection has no mutation authority.
        path: Repository-relative goal-state record label.
        updated_at: Goal-state record timestamp.
        checkpoint_id: Rollback checkpoint id, without local checkpoint path.
        id: Requirement row id.
        status: Requirement row status.
        requirement: Redacted requirement text.
        residual_risk: Redacted residual risk text.
        evidence: Bounded evidence references.
        evidence_count: Total evidence references found before truncation.
        truncated: Whether evidence references were omitted.
        next_safe_local_actions: Bounded next local actions from the goal state.
        stop_boundaries: Bounded stop boundaries from the goal state.
        error: Redacted lookup/read error when unavailable.
    """

    schema_version: str = "scholar_ai_goal_requirement_drilldown_v1"
    available: bool
    read_only: bool = True
    path: str | None = Field(default=None, max_length=240)
    updated_at: str | None = Field(default=None, max_length=80)
    checkpoint_id: str | None = Field(default=None, max_length=120)
    id: str | None = Field(default=None, max_length=160)
    status: str | None = Field(default=None, max_length=80)
    requirement: str | None = Field(default=None, max_length=MAX_GOAL_REQUIREMENT_TEXT_CHARS)
    residual_risk: str | None = Field(default=None, max_length=MAX_GOAL_REQUIREMENT_TEXT_CHARS)
    evidence: list[AgentWorkspaceGoalRequirementEvidenceRef] = Field(default_factory=list)
    evidence_count: int = Field(default=0, ge=0)
    truncated: bool = False
    next_safe_local_actions: list[str] = Field(default_factory=list)
    stop_boundaries: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None, max_length=240)


class AgentWorkspaceGoalState(BaseModel):
    """Bounded longrun goal-state summary for recovery decisions.

    Args:
        available: Whether a local goal-state JSON record was found and parsed.
        path: Repository-relative or redacted label for the selected record.
        updated_at: Timestamp from the selected goal-state record.
        checkpoint_id: Rollback checkpoint id, without local checkpoint path.
        rollback_caveat: Bounded rollback caution text, without local paths or commands.
        requirement_count: Number of requirement-to-evidence rows.
        proved_count: Number of rows currently proved.
        incomplete_count: Number of incomplete rows.
        out_of_scope_count: Number of rows explicitly outside current scope.
        latest_requirement_id: Last requirement id in the matrix.
        requirement_status: Compact requirement-to-evidence status summary.
        open_requirements: Bounded non-proved requirement rows for recovery.
        lifecycle_rollup: Machine-readable goal-level completion boundary.
        completion_claim: Bounded slice/full-goal completion summary.
        next_authorized_local_actions: Bounded action labels from the record.
        stop_boundaries: Bounded stop-boundary labels from the record.
        authoritative_records: Bounded record labels a resumed agent should read first.
        mature_references_checked: Bounded reference records used for latest slices.
        changed_files_for_this_slice: Bounded changed-file labels from the latest slice.
        verification_commands: Bounded verification evidence commands from the latest slice.
        error: Redacted parse/read error when unavailable.
    """

    available: bool
    path: str | None = Field(default=None, max_length=240)
    updated_at: str | None = Field(default=None, max_length=80)
    checkpoint_id: str | None = Field(default=None, max_length=120)
    rollback_caveat: str | None = Field(default=None, max_length=MAX_GOAL_ROLLBACK_CAVEAT_CHARS)
    requirement_count: int = Field(default=0, ge=0)
    proved_count: int = Field(default=0, ge=0)
    incomplete_count: int = Field(default=0, ge=0)
    out_of_scope_count: int = Field(default=0, ge=0)
    latest_requirement_id: str | None = Field(default=None, max_length=160)
    requirement_status: AgentWorkspaceGoalRequirementStatus = Field(default_factory=AgentWorkspaceGoalRequirementStatus)
    open_requirements: list[AgentWorkspaceGoalOpenRequirement] = Field(default_factory=list)
    lifecycle_rollup: AgentWorkspaceGoalLifecycleRollup = Field(default_factory=AgentWorkspaceGoalLifecycleRollup)
    completion_claim: AgentWorkspaceGoalCompletionClaim = Field(default_factory=AgentWorkspaceGoalCompletionClaim)
    next_authorized_local_actions: list[str] = Field(default_factory=list)
    stop_boundaries: list[str] = Field(default_factory=list)
    authoritative_records: list[str] = Field(default_factory=list)
    mature_references_checked: list[AgentWorkspaceGoalMatureReference] = Field(default_factory=list)
    changed_files_for_this_slice: list[str] = Field(default_factory=list)
    verification_commands: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None, max_length=240)


class AgentWorkspaceDesktopSmokeState(BaseModel):
    """Latest local desktop acceptance smoke evidence for recovery decisions.

    Args:
        available: Whether a desktop smoke summary was found and parsed.
        run_id: Stable run directory id under generated desktop smoke artifacts.
        status: Smoke result status from the local summary.
        initial_path: App route used when launching the source desktop window.
        expected_initial_path: App route required for Agent Workspace acceptance evidence.
        candidate_count: Number of desktop smoke summaries inspected.
        ignored_count: Number of summaries ignored because they were not Agent Workspace acceptance runs.
        summary_path: Repository-relative summary artifact label.
        screenshot_path: Repository-relative screenshot artifact label.
        accessibility_tree_path: Repository-relative UIA tree artifact label.
        screenshot_nonblank: Whether the captured desktop image was nonblank.
        accessibility_tree_available: Whether a UIA tree was captured.
        accessibility_tree_root_name: Root accessible object name.
        accessibility_tree_root_control_type: Root accessible object type.
        accessibility_tree_node_count: Total captured UIA node count.
        accessibility_tree_named_node_count: Captured named-node count.
        warnings: Bounded local smoke warnings.
        errors: Bounded local smoke errors.
        error: Redacted read/parse error when unavailable.
    """

    schema_version: str = "scholar_ai_desktop_smoke_state_v1"
    available: bool
    read_only: bool = True
    run_id: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, max_length=80)
    initial_path: str | None = Field(default=None, max_length=240)
    expected_initial_path: str = AGENT_WORKSPACE_DESKTOP_ACCEPTANCE_PATH
    candidate_count: int = Field(default=0, ge=0)
    ignored_count: int = Field(default=0, ge=0)
    summary_path: str | None = Field(default=None, max_length=240)
    screenshot_path: str | None = Field(default=None, max_length=240)
    accessibility_tree_path: str | None = Field(default=None, max_length=240)
    screenshot_nonblank: bool | None = None
    accessibility_tree_available: bool | None = None
    accessibility_tree_root_name: str | None = Field(default=None, max_length=120)
    accessibility_tree_root_control_type: str | None = Field(default=None, max_length=120)
    accessibility_tree_node_count: int | None = Field(default=None, ge=0)
    accessibility_tree_named_node_count: int | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None, max_length=240)


class AgentWorkspaceOcrEngineState(BaseModel):
    """One redacted OCR engine readiness summary for workspace recovery."""

    name: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    engine_type: str = Field(min_length=1, max_length=40)
    available: bool
    requires_network: bool
    readiness_status: str | None = Field(default=None, max_length=80)
    readiness_blockers: list[str] = Field(default_factory=list)
    next_safe_local_actions: list[str] = Field(default_factory=list)
    unavailable_reason: str | None = Field(default=None, max_length=240)


class AgentWorkspaceOcrRuntimeState(BaseModel):
    """Read-only OCR runtime snapshot for local processing recovery."""

    schema_version: str = "scholar_ai_ocr_runtime_state_v1"
    available: bool
    read_only: bool = True
    policy: str | None = Field(default=None, max_length=40)
    configured_engine: str | None = Field(default=None, max_length=80)
    selected_engine: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=40)
    source: str | None = Field(default=None, max_length=80)
    engine_config: dict[str, Any] = Field(default_factory=dict)
    engine_count: int = Field(default=0, ge=0)
    ready_engine_count: int = Field(default=0, ge=0)
    engines: list[AgentWorkspaceOcrEngineState] = Field(default_factory=list)
    readiness_blockers: list[str] = Field(default_factory=list)
    warning: str | None = Field(default=None, max_length=240)
    next_safe_local_actions: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None, max_length=240)


class AgentWorkspaceWikiDoctorSample(BaseModel):
    """One bounded WikiRegistry row that still needs Source Vault mirror review.

    Args:
        record_type: Source or chunk row category from the registry backlog.
        record_id: Registry source_id or chunk_id for locating the row.
        source_id: Parent source id for joining source/chunk evidence.
        status: Persisted Source Vault mirror status.
        error: Redacted mirror error when present.
    """

    record_type: str = Field(min_length=1, max_length=40)
    record_id: str = Field(min_length=1, max_length=160)
    source_id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=80)
    error: str | None = Field(default=None, max_length=240)


class AgentWorkspaceWikiDoctorState(BaseModel):
    """Read-only Wiki Doctor recovery summary for Source Vault mirror backlog."""

    schema_version: str = "scholar_ai_wiki_doctor_state_v1"
    available: bool
    read_only: bool = True
    status: str = Field(default="unknown", max_length=80)
    registry_db_path: str | None = Field(default=None, max_length=240)
    source_count: int = Field(default=0, ge=0)
    chunk_count: int = Field(default=0, ge=0)
    pending_source_count: int = Field(default=0, ge=0)
    pending_chunk_count: int = Field(default=0, ge=0)
    needs_replay: bool = False
    source_status_counts: dict[str, int] = Field(default_factory=dict)
    chunk_status_counts: dict[str, int] = Field(default_factory=dict)
    sample_count: int = Field(default=0, ge=0)
    samples: list[AgentWorkspaceWikiDoctorSample] = Field(default_factory=list)
    action_count: int = Field(default=0, ge=0)
    next_safe_local_actions: list[str] = Field(default_factory=list)
    warning: str | None = Field(default=None, max_length=240)
    error: str | None = Field(default=None, max_length=240)


class AgentWorkspaceKnowledgeActualLoadingGateState(BaseModel):
    """Read-only Knowledge Runtime live actual-loading gate summary.

    Args:
        available: Whether the conformance gate could be read locally.
        status: Gate status from the Knowledge Runtime conformance endpoint.
        verdict: Live smoke artifact verdict when an artifact is present.
        artifact_ref: Repository-relative proof artifact label.
        provider_preflight_status: Provider forced-tool-call preflight status.
        recovery_state: Machine-readable recovery state for resumed agents.
    """

    schema_version: str = "scholar_ai_krt_actual_loading_gate_state_v1"
    available: bool
    read_only: bool = True
    status: str = Field(default="unknown", max_length=80)
    verdict: str | None = Field(default=None, max_length=120)
    artifact_ref: str | None = Field(default=None, max_length=240)
    artifact_path: str | None = Field(default=None, max_length=240)
    artifact_exists: bool = False
    artifact_schema_valid: bool = False
    artifact_contract_valid: bool = False
    provider_preflight_status: str | None = Field(default=None, max_length=80)
    provider_latest_status: str | None = Field(default=None, max_length=80)
    provider_record_count: int = Field(default=0, ge=0)
    auth_required_count: int = Field(default=0, ge=0)
    tool_call_ok_count: int = Field(default=0, ge=0)
    provider_ready_for_authorized_live_smoke: bool = False
    recovery_state: str | None = Field(default=None, max_length=120)
    recovery_blocked_by: list[str] = Field(default_factory=list)
    recovery_ref_count: int = Field(default=0, ge=0)
    authorization_required_ref_count: int = Field(default=0, ge=0)
    completion_requires_authorized_live_smoke: bool = True
    missing: list[str] = Field(default_factory=list)
    next_safe_local_actions: list[str] = Field(default_factory=list)
    claim_boundary: str | None = Field(default=None, max_length=240)
    error: str | None = Field(default=None, max_length=240)


class AgentWorkspaceState(BaseModel):
    """Machine-readable local workspace state for resumable agents."""

    schema_version: str = "scholar_ai_agent_workspace_state_v1"
    generated_at: str
    workspace_ready: bool
    read_only: bool = True
    artifact_root: AgentWorkspaceDirectoryState
    runtime_state_root: AgentWorkspaceDirectoryState
    output_root: AgentWorkspaceDirectoryState
    git: AgentWorkspaceGitState
    goal_state: AgentWorkspaceGoalState
    desktop_smoke: AgentWorkspaceDesktopSmokeState
    ocr_runtime: AgentWorkspaceOcrRuntimeState
    wiki_doctor: AgentWorkspaceWikiDoctorState
    knowledge_actual_loading_gate: AgentWorkspaceKnowledgeActualLoadingGateState
    recovery_probes: list[AgentWorkspaceRecoveryProbe] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    next_safe_local_actions: list[str] = Field(default_factory=list)


class AgentWorkspaceStatus(BaseModel):
    """Aggregated Agent Workspace snapshot."""

    artifact_root: str
    artifact_count: int = Field(ge=0)
    audit_count: int = Field(ge=0)
    total_artifact_bytes: int = Field(ge=0)
    latest_activity_at: str | None = None
    workspace_state: AgentWorkspaceState
    artifacts: list[AgentWorkspaceArtifact] = Field(default_factory=list)
    audit_records: list[AgentWorkspaceAuditRecord] = Field(default_factory=list)


def _workspace_root() -> Path:
    """Return the local MCP workflow artifact root."""

    return (WORKSPACE_ARTIFACTS_ROOT / WORKSPACE_DIR_NAME).resolve()


def _audit_root() -> Path:
    """Return the audit log directory inside the workflow workspace."""

    return (_workspace_root() / AUDIT_DIR_NAME).resolve()


def _iso_from_mtime(path: Path) -> str:
    """Return an ISO timestamp for a filesystem object."""

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _redact_text(value: str) -> str:
    """Redact secret-like substrings before returning local workspace data."""

    try:
        from lit_assistant_mcp.redaction import SecretRedactor

        text = SecretRedactor.scan(value)
    except Exception:
        text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-***REDACTED***", value)
        text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{8,}", "Bearer ***REDACTED***", text)
        text = re.sub(r"(?i)\bAuthorization:\s*(?:Bearer|Basic)\s+\S+", "Authorization: ***REDACTED***", text)
    text = re.sub(r"(?i)\b[A-Z]:[/\\]Users[/\\][^ \t\r\n\"'<>]+", "[redacted-local-path]", text)
    text = re.sub(r"(?i)\b/Users/[^ \t\r\n\"'<>]+", "[redacted-local-path]", text)
    return text


def _safe_relative(path: Path, root: Path) -> str:
    """Return POSIX-style relative path under ``root`` or raise."""

    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="path escapes Agent Workspace") from exc
    return relative.as_posix()


def _safe_repo_relative(path_text: str) -> str:
    """Return a redacted repository-relative path from git porcelain output."""

    if not path_text.strip():
        return ""
    normalized = path_text.strip().replace("\\", "/")
    if normalized.startswith("\"") and normalized.endswith("\""):
        normalized = normalized[1:-1]
    if normalized.startswith("/") or ":" in normalized.split("/", 1)[0]:
        return "[redacted-local-path]"
    return _redact_text(normalized)


def _workspace_state_path(path: Path) -> str:
    """Return a path label that avoids exposing absolute local workspace roots."""

    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT.resolve())
        return _redact_text(relative.as_posix())
    except ValueError:
        return "[redacted-local-path]"


def _artifact_kind(path: Path) -> str:
    """Classify artifact type for UI filters."""

    suffix = path.suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix == ".json":
        return "json"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix in {".txt", ".log"}:
        return "text"
    return "file"


def _read_preview(path: Path, max_chars: int) -> tuple[str, bool]:
    """Read a bounded text preview for supported artifact files."""

    stat = path.stat()
    if stat.st_size > MAX_FILE_BYTES:
        return "", True
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", False
    redacted = _redact_text(text)
    truncated = len(redacted) > max_chars
    return redacted[:max_chars], truncated


def _iter_artifact_files(root: Path) -> list[Path]:
    """List non-audit files under the workflow artifact root."""

    if not root.exists():
        return []
    if not root.is_dir():
        raise HTTPException(status_code=500, detail="Agent Workspace root is not a directory")
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(_audit_root())
            continue
        except ValueError:
            out.append(path)
    return sorted(out, key=lambda item: item.stat().st_mtime, reverse=True)


def _load_artifacts(limit: int, max_preview_chars: int) -> tuple[list[AgentWorkspaceArtifact], int]:
    """Load bounded artifact summaries and total bytes."""

    root = _workspace_root()
    files = _iter_artifact_files(root)
    total_bytes = sum(path.stat().st_size for path in files)
    artifacts: list[AgentWorkspaceArtifact] = []
    for path in files[:limit]:
        preview, truncated = _read_preview(path, max_preview_chars)
        artifacts.append(
            AgentWorkspaceArtifact(
                path=_safe_relative(path, root),
                name=path.name,
                kind=_artifact_kind(path),
                size_bytes=path.stat().st_size,
                modified_at=_iso_from_mtime(path),
                preview=preview,
                truncated=truncated,
            )
        )
    return artifacts, total_bytes


def _coerce_str(value: Any) -> str:
    """Convert JSON scalar-ish values to a safe display string."""

    if value is None:
        return ""
    if isinstance(value, str):
        return _redact_text(value)
    return _redact_text(str(value))


def _coerce_record(value: Any) -> dict[str, Any]:
    """Return a redacted mapping for audit argument previews."""

    if not isinstance(value, dict):
        return {}
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        key_text = _coerce_str(key)
        if isinstance(item, str):
            redacted[key_text] = _redact_text(item)
        elif isinstance(item, (int, float, bool)) or item is None:
            redacted[key_text] = item
        else:
            redacted[key_text] = _redact_text(json.dumps(item, ensure_ascii=False, default=str))
    return redacted


def _parse_audit_line(line: str) -> AgentWorkspaceAuditRecord | None:
    """Parse one JSONL audit line into a redacted API model."""

    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    timestamp = _coerce_str(payload.get("timestamp"))
    tool_name = _coerce_str(payload.get("tool_name"))
    if not timestamp or not tool_name:
        return None
    raw_touched = payload.get("touched_paths")
    touched_paths = [
        _coerce_str(item)
        for item in raw_touched
        if isinstance(item, str)
    ] if isinstance(raw_touched, list) else []
    raw_duration = payload.get("duration_ms")
    duration_ms = int(raw_duration) if isinstance(raw_duration, int) and raw_duration >= 0 else 0
    error_code = payload.get("error_code")
    return AgentWorkspaceAuditRecord(
        timestamp=timestamp,
        tool_name=tool_name,
        args_summary=_coerce_record(payload.get("args_summary")),
        touched_paths=touched_paths,
        allow_block_reason=_coerce_str(payload.get("allow_block_reason")),
        result_preview=_coerce_str(payload.get("result_preview")),
        duration_ms=duration_ms,
        error_code=_coerce_str(error_code) or None,
    )


def _load_audit_records(limit: int) -> list[AgentWorkspaceAuditRecord]:
    """Load the latest audit records from JSONL files."""

    audit = _audit_root()
    if not audit.exists():
        return []
    if not audit.is_dir():
        raise HTTPException(status_code=500, detail="Agent Workspace audit path is not a directory")
    records: list[AgentWorkspaceAuditRecord] = []
    files = sorted(audit.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            record = _parse_audit_line(line)
            if record is not None:
                records.append(record)
            if len(records) >= limit:
                return records
    return records


def _count_directory_state(
    label: str,
    root: Path,
    *,
    excluded_root: Path | None = None,
) -> AgentWorkspaceDirectoryState:
    """Return a bounded directory state without exposing child file paths."""

    resolved = root.resolve()
    resolved_excluded = excluded_root.resolve() if excluded_root is not None else None
    path_label = _workspace_state_path(resolved)
    if not resolved.exists():
        return AgentWorkspaceDirectoryState(label=label, path=path_label, exists=False)
    if not resolved.is_dir():
        return AgentWorkspaceDirectoryState(label=label, path=path_label, exists=True)
    file_count = 0
    total_bytes = 0
    truncated = False
    for path in resolved.rglob("*"):
        if not path.is_file():
            continue
        if resolved_excluded is not None:
            try:
                path.resolve().relative_to(resolved_excluded)
                continue
            except ValueError:
                pass
        try:
            stat = path.stat()
        except OSError:
            continue
        file_count += 1
        total_bytes += max(int(stat.st_size), 0)
        if file_count >= MAX_DIRECTORY_STATE_FILES:
            truncated = True
            break
    return AgentWorkspaceDirectoryState(
        label=label,
        path=path_label,
        exists=True,
        file_count=file_count,
        total_bytes=total_bytes,
        truncated=truncated,
    )


def _parse_branch_header(header: str) -> tuple[str | None, int, int]:
    """Parse ``git status --porcelain=v2 --branch`` header fields."""

    branch: str | None = None
    ahead = 0
    behind = 0
    for line in header.splitlines():
        if line.startswith("# branch.head "):
            value = line.removeprefix("# branch.head ").strip()
            branch = None if value == "(detached)" else value
        elif line.startswith("# branch.ab "):
            parts = line.removeprefix("# branch.ab ").split()
            for part in parts:
                if part.startswith("+") and part[1:].isdigit():
                    ahead = int(part[1:])
                elif part.startswith("-") and part[1:].isdigit():
                    behind = int(part[1:])
    return branch, ahead, behind


def _parse_git_porcelain(stdout: str) -> AgentWorkspaceGitState:
    """Convert porcelain v2 status into a bounded read-only summary."""

    branch, ahead, behind = _parse_branch_header(stdout)
    staged_count = 0
    unstaged_count = 0
    untracked_count = 0
    conflicted_count = 0
    dirty_paths: list[str] = []
    for line in stdout.splitlines():
        if not line or line.startswith("# "):
            continue
        if line.startswith("? "):
            untracked_count += 1
            path_text = _safe_repo_relative(line[2:])
        elif line.startswith("u "):
            conflicted_count += 1
            parts = line.split(maxsplit=10)
            path_text = _safe_repo_relative(parts[-1] if parts else "")
        elif line.startswith("1 ") or line.startswith("2 "):
            parts = line.split(maxsplit=8)
            status = parts[1] if len(parts) > 1 else ".."
            if len(status) >= 2:
                if status[0] != ".":
                    staged_count += 1
                if status[1] != ".":
                    unstaged_count += 1
            path_text = _safe_repo_relative(parts[-1] if parts else "")
        else:
            path_text = ""
        if path_text and len(dirty_paths) < MAX_STATE_PATHS:
            dirty_paths.append(path_text)
    changed_count = staged_count + unstaged_count + untracked_count + conflicted_count
    return AgentWorkspaceGitState(
        available=True,
        branch=branch,
        ahead=ahead,
        behind=behind,
        changed_count=changed_count,
        staged_count=staged_count,
        unstaged_count=unstaged_count,
        untracked_count=untracked_count,
        conflicted_count=conflicted_count,
        dirty_paths=dirty_paths,
    )


def _read_git_workspace_state() -> AgentWorkspaceGitState:
    """Read local git state through a non-mutating porcelain command."""

    repo_root = REPO_ROOT.resolve()
    if not (repo_root / ".git").exists():
        return AgentWorkspaceGitState(available=False, error="git repository metadata is not present")
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain=v2", "--branch"],
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_STATUS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return AgentWorkspaceGitState(available=False, error=_redact_text(str(exc)))
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "git status failed"
        return AgentWorkspaceGitState(available=False, error=_redact_text(message[:240]))
    return _parse_git_porcelain(completed.stdout)


def _latest_goal_state_file() -> Path | None:
    """Return the newest longrun goal-state JSON file under docs/plans."""

    plans_root = (REPO_ROOT / "docs" / "plans").resolve()
    if not plans_root.exists() or not plans_root.is_dir():
        return None
    files = [path for path in plans_root.glob("longrun-goal-state-*.json") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda item: (item.stat().st_mtime, item.name))


def _safe_text_list(value: Any, limit: int) -> list[str]:
    """Return a bounded list of redacted display strings."""

    if limit <= 0 or not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = _redact_text(item).strip()
        if text:
            out.append(text[:240])
        if len(out) >= limit:
            break
    return out


def _safe_text_list_or_string(value: Any, limit: int) -> list[str]:
    """Return bounded display strings from a legacy string or list shape."""

    if limit <= 0:
        return []
    if isinstance(value, str):
        text = _redact_text(value).strip()
        return [text[:240]] if text else []
    return _safe_text_list(value, limit)


def _safe_optional_text(value: Any, *, max_chars: int = 240) -> str | None:
    """Return a bounded redacted string or ``None`` for missing values."""

    if not isinstance(value, str) or not value.strip():
        return None
    return _redact_text(value.strip())[:max_chars]


def _safe_goal_completion_claim(value: Any) -> AgentWorkspaceGoalCompletionClaim:
    """Return bounded completion claims without exposing the full goal record."""

    if not isinstance(value, dict):
        return AgentWorkspaceGoalCompletionClaim()
    this_slice = value.get("this_slice")
    full_goal = value.get("full_goal")
    can_mark_goal_complete = value.get("can_mark_goal_complete")
    why_not_complete = value.get("why_not_complete")
    return AgentWorkspaceGoalCompletionClaim(
        this_slice=_redact_text(this_slice).strip()[:MAX_GOAL_COMPLETION_CHARS]
        if isinstance(this_slice, str) and this_slice.strip()
        else None,
        full_goal=_redact_text(full_goal).strip()[:MAX_GOAL_COMPLETION_CHARS]
        if isinstance(full_goal, str) and full_goal.strip()
        else None,
        can_mark_goal_complete=can_mark_goal_complete if isinstance(can_mark_goal_complete, bool) else None,
        why_not_complete=_redact_text(why_not_complete).strip()[:MAX_GOAL_COMPLETION_CHARS]
        if isinstance(why_not_complete, str) and why_not_complete.strip()
        else None,
    )


def _desktop_smoke_root() -> Path:
    """Return the generated desktop smoke artifact root."""

    return (WORKSPACE_ARTIFACTS_ROOT / "generated" / "desktop_smoke").resolve()


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """Return a JSON object from ``path`` or ``None`` when it is unavailable."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _latest_desktop_smoke_summary_file() -> tuple[Path | None, dict[str, Any] | None, int, int]:
    """Return the newest Agent Workspace desktop smoke summary and scan counts."""

    root = _desktop_smoke_root()
    if not root.exists() or not root.is_dir():
        return None, None, 0, 0
    files = [path for path in root.glob("*/summary.json") if path.is_file()]
    if not files:
        return None, None, 0, 0
    sorted_files = sorted(files, key=lambda item: (item.stat().st_mtime, item.parent.name), reverse=True)
    ignored_count = 0
    for path in sorted_files:
        payload = _read_json_object(path)
        if payload is None:
            ignored_count += 1
            continue
        if payload.get("initial_path") == AGENT_WORKSPACE_DESKTOP_ACCEPTANCE_PATH:
            return path, payload, len(sorted_files), ignored_count
        ignored_count += 1
    return None, None, len(sorted_files), ignored_count


def _safe_artifact_path_from_summary(value: Any) -> str | None:
    """Return a repository-relative artifact path from a summary path field."""

    if not isinstance(value, str) or not value.strip():
        return None
    return _workspace_state_path(Path(value.strip()))


def _safe_optional_int(value: Any) -> int | None:
    """Return a non-negative integer from arbitrary summary data."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _load_desktop_smoke_state() -> AgentWorkspaceDesktopSmokeState:
    """Load the latest local desktop smoke evidence without exposing raw paths."""

    summary_path, payload, candidate_count, ignored_count = _latest_desktop_smoke_summary_file()
    if summary_path is None:
        return AgentWorkspaceDesktopSmokeState(
            available=False,
            candidate_count=candidate_count,
            ignored_count=ignored_count,
            error="no Agent Workspace desktop smoke summary found",
        )
    path_label = _workspace_state_path(summary_path)
    if payload is None:
        return AgentWorkspaceDesktopSmokeState(
            available=False,
            candidate_count=candidate_count,
            ignored_count=ignored_count,
            summary_path=path_label,
            error="desktop smoke summary could not be parsed",
        )

    return AgentWorkspaceDesktopSmokeState(
        available=True,
        candidate_count=candidate_count,
        ignored_count=ignored_count,
        run_id=_safe_optional_text(payload.get("run_id"), max_chars=120) or _redact_text(summary_path.parent.name)[:120],
        status=_safe_optional_text(payload.get("status"), max_chars=80),
        initial_path=_safe_optional_text(payload.get("initial_path")),
        summary_path=path_label,
        screenshot_path=_safe_artifact_path_from_summary(payload.get("screenshot_png")),
        accessibility_tree_path=_safe_artifact_path_from_summary(payload.get("accessibility_tree_json")),
        screenshot_nonblank=payload.get("screenshot_nonblank") if isinstance(payload.get("screenshot_nonblank"), bool) else None,
        accessibility_tree_available=payload.get("accessibility_tree_available")
        if isinstance(payload.get("accessibility_tree_available"), bool)
        else None,
        accessibility_tree_root_name=_safe_optional_text(payload.get("accessibility_tree_root_name"), max_chars=120),
        accessibility_tree_root_control_type=_safe_optional_text(
            payload.get("accessibility_tree_root_control_type"),
            max_chars=120,
        ),
        accessibility_tree_node_count=_safe_optional_int(payload.get("accessibility_tree_node_count")),
        accessibility_tree_named_node_count=_safe_optional_int(payload.get("accessibility_tree_named_node_count")),
        warnings=_safe_text_list(payload.get("warnings"), MAX_DESKTOP_SMOKE_TEXT_ITEMS),
        errors=_safe_text_list(payload.get("errors"), MAX_DESKTOP_SMOKE_TEXT_ITEMS),
    )


def _safe_ocr_config_record(value: Any) -> dict[str, Any]:
    """Return a bounded, redacted OCR config record for recovery display."""

    if not isinstance(value, dict):
        return {}
    secret_parts = ("api_key", "token", "secret", "password", "authorization", "bearer")
    out: dict[str, Any] = {}
    for raw_key, raw_value in list(value.items())[:12]:
        key = _redact_text(str(raw_key).strip())[:80]
        if not key:
            continue
        if any(part in key.lower() for part in secret_parts):
            out[key] = "***"
        elif isinstance(raw_value, str):
            out[key] = _redact_text(raw_value)[:240]
        elif isinstance(raw_value, (int, float, bool)) or raw_value is None:
            out[key] = raw_value
        else:
            out[key] = str(type(raw_value).__name__)[:80]
    return out


def _safe_ocr_engine_state(value: Any) -> AgentWorkspaceOcrEngineState | None:
    """Return one bounded OCR engine summary from registry metadata."""

    if not isinstance(value, dict):
        return None
    name = _safe_optional_text(value.get("name"), max_chars=80)
    if name is None:
        return None
    display_name = _safe_optional_text(value.get("display_name"), max_chars=120) or name
    engine_type = _safe_optional_text(value.get("engine_type"), max_chars=40) or "unknown"
    return AgentWorkspaceOcrEngineState(
        name=name,
        display_name=display_name,
        engine_type=engine_type,
        available=value.get("available") is True,
        requires_network=value.get("requires_network") is True,
        readiness_status=_safe_optional_text(value.get("readiness_status"), max_chars=80),
        readiness_blockers=_safe_text_list(value.get("readiness_blockers"), MAX_OCR_RUNTIME_BLOCKERS),
        next_safe_local_actions=_safe_text_list(value.get("next_safe_local_actions"), MAX_OCR_RUNTIME_ACTIONS),
        unavailable_reason=_safe_optional_text(value.get("unavailable_reason"), max_chars=240),
    )


def _load_ocr_runtime_state() -> AgentWorkspaceOcrRuntimeState:
    """Load redacted OCR runtime status without executing OCR."""

    try:
        payload = public_ocr_status()
    except Exception as exc:
        return AgentWorkspaceOcrRuntimeState(
            available=False,
            error=_redact_text(str(exc))[:240] or "OCR runtime status could not be loaded",
        )
    if not isinstance(payload, dict):
        return AgentWorkspaceOcrRuntimeState(
            available=False,
            error="OCR runtime status returned an invalid payload",
        )

    engines: list[AgentWorkspaceOcrEngineState] = []
    raw_engines = payload.get("available_engines")
    if isinstance(raw_engines, list):
        for item in raw_engines:
            if len(engines) >= MAX_OCR_RUNTIME_ENGINES:
                break
            engine = _safe_ocr_engine_state(item)
            if engine is not None:
                engines.append(engine)
    blockers: list[str] = []
    for engine in engines:
        if len(blockers) >= MAX_OCR_RUNTIME_BLOCKERS:
            break
        for blocker in engine.readiness_blockers:
            blockers.append(f"{engine.name}: {blocker}"[:240])
            if len(blockers) >= MAX_OCR_RUNTIME_BLOCKERS:
                break
    warning = _safe_optional_text(payload.get("warning"), max_chars=240)
    if warning and len(blockers) < MAX_OCR_RUNTIME_BLOCKERS:
        blockers.insert(0, warning)

    return AgentWorkspaceOcrRuntimeState(
        available=True,
        policy=_safe_optional_text(payload.get("policy"), max_chars=40),
        configured_engine=_safe_optional_text(payload.get("configured_engine"), max_chars=80),
        selected_engine=_safe_optional_text(payload.get("selected_engine"), max_chars=80),
        language=_safe_optional_text(payload.get("language"), max_chars=40),
        source=_safe_optional_text(payload.get("source"), max_chars=80),
        engine_config=_safe_ocr_config_record(payload.get("engine_config")),
        engine_count=len(engines),
        ready_engine_count=sum(1 for engine in engines if engine.available),
        engines=engines,
        readiness_blockers=blockers,
        warning=warning,
        next_safe_local_actions=_safe_text_list(payload.get("next_safe_local_actions"), MAX_OCR_RUNTIME_ACTIONS),
    )


def _load_wiki_doctor_state() -> AgentWorkspaceWikiDoctorState:
    """Load read-only Wiki registry mirror backlog without replaying rows."""

    try:
        if not wiki_enabled():
            return AgentWorkspaceWikiDoctorState(
                available=False,
                status="disabled",
                warning="Wiki runtime is disabled",
                next_safe_local_actions=["Enable wiki runtime before relying on Wiki Doctor recovery state."],
            )
        registry_path = wiki_runtime_db_path()
        path_label = _workspace_state_path(registry_path)
        if not registry_path.exists():
            return AgentWorkspaceWikiDoctorState(
                available=False,
                status="missing_registry",
                registry_db_path=path_label,
                warning="Wiki registry database is missing",
                next_safe_local_actions=["Run /api/wiki/doctor before claiming WikiRegistry Source Vault mirror health."],
            )
        registry = WikiRegistry(registry_path)
        backlog = registry.source_vault_mirror_backlog(sample_limit=MAX_WIKI_DOCTOR_ACTIONS)
        needs_replay = backlog.needs_replay
        samples = [
            AgentWorkspaceWikiDoctorSample(
                record_type=_redact_text(sample.record_type).strip()[:40] or "unknown",
                record_id=_redact_text(sample.record_id).strip()[:160] or "unknown",
                source_id=_redact_text(sample.source_id).strip()[:160] or "unknown",
                status=_redact_text(sample.status).strip()[:80] or "unknown",
                error=(_redact_text(sample.error).strip()[:240] or None),
            )
            for sample in backlog.samples[:MAX_WIKI_DOCTOR_ACTIONS]
        ]
        return AgentWorkspaceWikiDoctorState(
            available=True,
            status="warning" if needs_replay else "ok",
            registry_db_path=path_label,
            source_count=backlog.source_count,
            chunk_count=backlog.chunk_count,
            pending_source_count=backlog.pending_source_count,
            pending_chunk_count=backlog.pending_chunk_count,
            needs_replay=needs_replay,
            source_status_counts=backlog.source_status_counts,
            chunk_status_counts=backlog.chunk_status_counts,
            sample_count=len(backlog.samples),
            samples=samples,
            action_count=1 if needs_replay else 0,
            next_safe_local_actions=(
                [
                    "Read /api/wiki/doctor, then run an explicit local maintenance slice before WikiRegistry.replay_source_vault_mirror()."
                ]
                if needs_replay
                else ["Keep Wiki Doctor and Source Vault Status in the recovery audit before KRT closure."]
            ),
            warning=(
                f"Source Vault mirror backlog has {backlog.pending_source_count} source rows and "
                f"{backlog.pending_chunk_count} chunk rows pending replay."
                if needs_replay
                else None
            ),
        )
    except Exception as exc:
        return AgentWorkspaceWikiDoctorState(
            available=False,
            status="error",
            error=_redact_text(str(exc))[:240] or "Wiki Doctor state could not be loaded",
            next_safe_local_actions=["Run /api/wiki/doctor directly and inspect the bounded error before KRT closure."],
        )


def _read_knowledge_actual_loading_gate() -> Any:
    """Return the Knowledge Runtime actual-loading gate from its owner module."""

    try:
        from routers.knowledge_router import _actual_loading_gate
    except ModuleNotFoundError:
        from literature_assistant.core.routers.knowledge_router import _actual_loading_gate

    return _actual_loading_gate()


def _load_knowledge_actual_loading_gate_state() -> AgentWorkspaceKnowledgeActualLoadingGateState:
    """Load the existing Knowledge Runtime actual-loading proof gate read-only."""

    try:
        gate = _read_knowledge_actual_loading_gate()
        artifact_path = None
        if isinstance(gate.artifact_path, str) and gate.artifact_path.strip():
            artifact_path = _workspace_state_path(Path(gate.artifact_path))
        recovery_refs = list(gate.recovery.recovery_refs)
        return AgentWorkspaceKnowledgeActualLoadingGateState(
            available=True,
            status=_redact_text(gate.status).strip()[:80] or "unknown",
            verdict=_safe_optional_text(gate.verdict, max_chars=120),
            artifact_ref=_safe_optional_text(gate.artifact_ref, max_chars=240),
            artifact_path=artifact_path,
            artifact_exists=gate.artifact_exists,
            artifact_schema_valid=gate.artifact_schema_valid,
            artifact_contract_valid=gate.artifact_contract_valid,
            provider_preflight_status=_safe_optional_text(gate.provider_preflight.status, max_chars=80),
            provider_latest_status=_safe_optional_text(gate.provider_preflight.latest_status, max_chars=80),
            provider_record_count=gate.provider_preflight.record_count,
            auth_required_count=gate.provider_preflight.auth_required_count,
            tool_call_ok_count=gate.provider_preflight.tool_call_ok_count,
            provider_ready_for_authorized_live_smoke=gate.provider_preflight.provider_ready_for_authorized_live_smoke,
            recovery_state=_safe_optional_text(gate.recovery.state, max_chars=120),
            recovery_blocked_by=_safe_text_list(
                gate.recovery.blocked_by,
                MAX_KRT_ACTUAL_LOADING_BLOCKERS,
            ),
            recovery_ref_count=len(recovery_refs),
            authorization_required_ref_count=sum(1 for item in recovery_refs if item.requires_authorization),
            completion_requires_authorized_live_smoke=gate.recovery.completion_requires_authorized_live_smoke,
            missing=_safe_text_list(gate.missing, MAX_KRT_ACTUAL_LOADING_MISSING),
            next_safe_local_actions=_safe_text_list(
                gate.next_safe_local_actions,
                MAX_KRT_ACTUAL_LOADING_ACTIONS,
            ),
            claim_boundary=_safe_optional_text(gate.claim_boundary, max_chars=240),
        )
    except Exception as exc:
        return AgentWorkspaceKnowledgeActualLoadingGateState(
            available=False,
            status="error",
            error=_redact_text(str(exc))[:240] or "Knowledge Runtime actual-loading gate could not be loaded",
            next_safe_local_actions=[
                "Read /api/knowledge/runtime-conformance before claiming live model-context loading proof."
            ],
        )


def _safe_goal_open_requirement(row: dict[str, Any]) -> AgentWorkspaceGoalOpenRequirement | None:
    """Return one bounded open requirement row when it is safe to expose."""

    row_id = row.get("id")
    status = row.get("status")
    if not isinstance(row_id, str) or not row_id.strip():
        return None
    if not isinstance(status, str) or status not in OPEN_REQUIREMENT_STATUSES:
        return None
    requirement = row.get("requirement")
    residual_risk = row.get("residual_risk")
    requirement_text = (
        _redact_text(requirement).strip()[:240]
        if isinstance(requirement, str) and requirement.strip()
        else None
    )
    residual_risk_text = (
        _redact_text(residual_risk).strip()[:240]
        if isinstance(residual_risk, str) and residual_risk.strip()
        else None
    )
    return AgentWorkspaceGoalOpenRequirement(
        id=_redact_text(row_id.strip())[:160],
        status=status,
        requirement=requirement_text,
        residual_risk=residual_risk_text,
    )


def _safe_goal_lifecycle_blocker(value: Any) -> AgentWorkspaceGoalLifecycleBlocker | None:
    """Return one bounded lifecycle blocker without exposing raw local records."""

    if isinstance(value, str):
        raw_id = value.strip()
        if not raw_id:
            return None
        return AgentWorkspaceGoalLifecycleBlocker(id=_redact_text(raw_id)[:160])
    if not isinstance(value, dict):
        return None
    raw_id = value.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return None
    return AgentWorkspaceGoalLifecycleBlocker(
        id=_redact_text(raw_id.strip())[:160],
        status=_safe_optional_text(value.get("status"), max_chars=120),
        requirement_surface=_safe_optional_text(value.get("requirement_surface"), max_chars=240),
        missing_evidence=_safe_optional_text(value.get("missing_evidence"), max_chars=240),
        current_boundary=_safe_optional_text(value.get("current_boundary"), max_chars=240),
        evidence=_safe_optional_text(value.get("evidence"), max_chars=240),
    )


def _safe_goal_lifecycle_status_counts(value: Any) -> dict[str, int]:
    """Return bounded non-negative lifecycle status counts from arbitrary JSON."""

    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, count in value.items():
        if len(counts) >= MAX_GOAL_LIFECYCLE_STATUS_COUNTS:
            break
        if not isinstance(key, str) or not key.strip() or not isinstance(count, int) or count < 0:
            continue
        counts[_redact_text(key.strip())[:80]] = count
    return counts


def _safe_goal_lifecycle_rollup(value: Any) -> AgentWorkspaceGoalLifecycleRollup:
    """Return a bounded lifecycle rollup from arbitrary goal-state data."""

    if not isinstance(value, dict):
        return AgentWorkspaceGoalLifecycleRollup()
    raw_blockers = value.get("completion_blockers")
    completion_blockers: list[AgentWorkspaceGoalLifecycleBlocker] = []
    if isinstance(raw_blockers, list):
        for item in raw_blockers:
            if len(completion_blockers) >= MAX_GOAL_LIFECYCLE_BLOCKERS:
                break
            blocker = _safe_goal_lifecycle_blocker(item)
            if blocker is not None:
                completion_blockers.append(blocker)
    return AgentWorkspaceGoalLifecycleRollup(
        schema_version=_safe_optional_text(value.get("schema_version"), max_chars=120),
        updated_at=_safe_optional_text(value.get("updated_at"), max_chars=80),
        status=_safe_optional_text(value.get("status"), max_chars=160),
        is_goal_complete=value.get("is_goal_complete") if isinstance(value.get("is_goal_complete"), bool) else None,
        can_mark_goal_complete=value.get("can_mark_goal_complete")
        if isinstance(value.get("can_mark_goal_complete"), bool)
        else None,
        requirements_total=value.get("requirements_total")
        if isinstance(value.get("requirements_total"), int) and value.get("requirements_total") >= 0
        else None,
        requirement_status_counts=_safe_goal_lifecycle_status_counts(value.get("requirement_status_counts")),
        requirements_all_proved=value.get("requirements_all_proved")
        if isinstance(value.get("requirements_all_proved"), bool)
        else None,
        requirements_all_proved_or_out_of_scope=value.get("requirements_all_proved_or_out_of_scope")
        if isinstance(value.get("requirements_all_proved_or_out_of_scope"), bool)
        else None,
        latest_requirement_id=_safe_optional_text(value.get("latest_requirement_id"), max_chars=160),
        latest_slice_id=_safe_optional_text(value.get("latest_slice_id"), max_chars=160),
        completion_blockers=completion_blockers,
        machine_readable_completion_rule=_safe_optional_text(
            value.get("machine_readable_completion_rule"),
            max_chars=240,
        ),
        why_not_complete=_safe_text_list_or_string(value.get("why_not_complete"), MAX_GOAL_STATE_BOUNDARIES),
    )


def _safe_requirement_text(value: Any) -> str | None:
    """Return bounded redacted requirement text from arbitrary goal-state data."""

    if not isinstance(value, str) or not value.strip():
        return None
    return _redact_text(value).strip()[:MAX_GOAL_REQUIREMENT_TEXT_CHARS]


def _safe_evidence_preview(value: Any) -> str | None:
    """Return a bounded redacted evidence preview without exposing raw records."""

    if isinstance(value, str):
        text = value.strip()
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = str(value)
    text = _redact_text(text).strip()
    return text[:MAX_GOAL_REQUIREMENT_TEXT_CHARS] if text else None


def _safe_goal_requirement_evidence_refs(value: Any) -> tuple[list[AgentWorkspaceGoalRequirementEvidenceRef], int, bool]:
    """Return bounded evidence refs and total count for a requirement row."""

    if not isinstance(value, list):
        return [], 0, False
    refs: list[AgentWorkspaceGoalRequirementEvidenceRef] = []
    for index, item in enumerate(value):
        if len(refs) >= MAX_GOAL_REQUIREMENT_EVIDENCE:
            break
        preview = _safe_evidence_preview(item)
        if preview is None:
            continue
        label = f"evidence {index + 1}"
        if isinstance(item, dict):
            raw_label = item.get("id") or item.get("ref_id") or item.get("path") or item.get("command")
            if isinstance(raw_label, str) and raw_label.strip():
                label = _redact_text(raw_label.strip())[:80]
        refs.append(AgentWorkspaceGoalRequirementEvidenceRef(label=label, text=preview))
    return refs, len(value), len(value) > MAX_GOAL_REQUIREMENT_EVIDENCE


def _load_goal_state_payload() -> tuple[Path | None, dict[str, Any] | None, str | None]:
    """Load the newest goal-state payload for summary and drilldown projections."""

    path = _latest_goal_state_file()
    if path is None:
        return None, None, "no longrun goal-state record found"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return path, None, _redact_text(str(exc))[:240]
    if not isinstance(payload, dict):
        return path, None, "goal-state record is not an object"
    return path, payload, None


def _goal_state_checkpoint_id(payload: dict[str, Any]) -> str | None:
    """Return the newest rollback checkpoint id without exposing local paths.

    Args:
        payload: Parsed longrun goal-state JSON object.

    Returns:
        Latest recovery checkpoint id, falling back to the historical checkpoint id.
    """

    rollback = payload.get("rollback")
    if not isinstance(rollback, dict):
        return None
    for key in ("latest_goal_state_checkpoint_id", "latest_checkpoint_id", "checkpoint_id"):
        value = rollback.get(key)
        if isinstance(value, str) and value.strip():
            return _redact_text(value.strip())[:120]
    return None


def _goal_state_rollback_caveat(payload: dict[str, Any]) -> str | None:
    """Return bounded rollback caveat text without exposing restore details.

    Args:
        payload: Parsed longrun goal-state JSON object.

    Returns:
        Redacted caution text from rollback metadata, or ``None`` when absent.
    """

    rollback = payload.get("rollback")
    if not isinstance(rollback, dict):
        return None
    value = rollback.get("latest_checkpoint_caveat")
    if not isinstance(value, str) or not value.strip():
        return None
    return _redact_text(value.strip())[:MAX_GOAL_ROLLBACK_CAVEAT_CHARS]


def _safe_goal_mature_references(value: Any) -> list[AgentWorkspaceGoalMatureReference]:
    """Return bounded mature-reference records without exposing full plan history.

    Args:
        value: Raw ``mature_references_checked`` value from the goal-state JSON.

    Returns:
        Up to ``MAX_GOAL_STATE_MATURE_REFERENCES`` redacted reference records.
    """

    if not isinstance(value, list):
        return []
    references: list[AgentWorkspaceGoalMatureReference] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        reference = AgentWorkspaceGoalMatureReference(
            topic=_safe_optional_text(item.get("topic"), max_chars=160),
            source=_safe_optional_text(item.get("source"), max_chars=160),
            url=_safe_optional_text(item.get("url"), max_chars=240),
            status=_safe_optional_text(item.get("status"), max_chars=160),
            checked_at=_safe_optional_text(item.get("checked_at"), max_chars=80),
            use_in_slice=_safe_optional_text(item.get("use_in_slice"), max_chars=240),
        )
        if any(
            (
                reference.topic,
                reference.source,
                reference.url,
                reference.status,
                reference.checked_at,
                reference.use_in_slice,
            )
        ):
            references.append(reference)
        if len(references) >= MAX_GOAL_STATE_MATURE_REFERENCES:
            break
    return references


def _load_goal_state_summary() -> AgentWorkspaceGoalState:
    """Load a bounded local goal-state summary without exposing full records."""

    path, payload, error = _load_goal_state_payload()
    if path is None:
        return AgentWorkspaceGoalState(available=False, error="no longrun goal-state record found")
    path_label = _workspace_state_path(path)
    if payload is None:
        return AgentWorkspaceGoalState(available=False, path=path_label, error=error or "goal-state record unavailable")

    raw_requirements = payload.get("requirements")
    requirements = raw_requirements if isinstance(raw_requirements, list) else []
    statuses: dict[str, int] = {}
    latest_requirement_id: str | None = None
    open_requirements: list[AgentWorkspaceGoalOpenRequirement] = []
    for row in requirements:
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        if isinstance(status, str):
            statuses[status] = statuses.get(status, 0) + 1
        if len(open_requirements) < MAX_GOAL_STATE_OPEN_REQUIREMENTS:
            open_requirement = _safe_goal_open_requirement(row)
            if open_requirement is not None:
                open_requirements.append(open_requirement)
        row_id = row.get("id")
        if isinstance(row_id, str) and row_id.strip():
            latest_requirement_id = _redact_text(row_id.strip())[:160]

    checkpoint_id = _goal_state_checkpoint_id(payload)
    updated_at = payload.get("updated_at")
    return AgentWorkspaceGoalState(
        available=True,
        path=path_label,
        updated_at=_redact_text(updated_at)[:80] if isinstance(updated_at, str) and updated_at.strip() else None,
        checkpoint_id=checkpoint_id,
        rollback_caveat=_goal_state_rollback_caveat(payload),
        requirement_count=len(requirements),
        proved_count=statuses.get("proved", 0),
        incomplete_count=statuses.get("incomplete", 0),
        out_of_scope_count=statuses.get("out_of_scope", 0),
        latest_requirement_id=latest_requirement_id,
        requirement_status=AgentWorkspaceGoalRequirementStatus(
            total=len(requirements),
            proved=statuses.get("proved", 0),
            incomplete=statuses.get("incomplete", 0),
            out_of_scope=statuses.get("out_of_scope", 0),
            latest_id=latest_requirement_id,
        ),
        open_requirements=open_requirements,
        lifecycle_rollup=_safe_goal_lifecycle_rollup(payload.get("goal_lifecycle_rollup")),
        completion_claim=_safe_goal_completion_claim(payload.get("completion_claim")),
        next_authorized_local_actions=_safe_text_list(payload.get("next_authorized_local_actions"), MAX_GOAL_STATE_ACTIONS),
        stop_boundaries=_safe_text_list(payload.get("stop_boundary"), MAX_GOAL_STATE_BOUNDARIES),
        authoritative_records=_safe_text_list(payload.get("authoritative_records"), MAX_GOAL_STATE_AUTH_RECORDS),
        mature_references_checked=_safe_goal_mature_references(payload.get("mature_references_checked")),
        changed_files_for_this_slice=_safe_text_list(
            payload.get("changed_files_for_this_slice"),
            MAX_GOAL_STATE_CHANGED_FILES,
        ),
        verification_commands=_safe_text_list(
            payload.get("verification_commands"),
            MAX_GOAL_STATE_VERIFICATION_COMMANDS,
        ),
    )


def _load_goal_requirement_drilldown(requirement_id: str) -> AgentWorkspaceGoalRequirementDrilldown:
    """Load one bounded goal-state requirement row by id.

    Args:
        requirement_id: Exact requirement matrix id to inspect.

    Returns:
        A read-only, response-model-compatible requirement drilldown.

    Raises:
        HTTPException: If the id is empty or too long.
    """

    if not isinstance(requirement_id, str) or not requirement_id.strip():
        raise HTTPException(status_code=400, detail="requirement_id is required")
    normalized_id = requirement_id.strip()
    if len(normalized_id) > 160:
        raise HTTPException(status_code=400, detail="requirement_id is too long")

    path, payload, error = _load_goal_state_payload()
    if path is None:
        return AgentWorkspaceGoalRequirementDrilldown(
            available=False,
            id=_redact_text(normalized_id)[:160],
            error=error or "no longrun goal-state record found",
        )
    path_label = _workspace_state_path(path)
    if payload is None:
        return AgentWorkspaceGoalRequirementDrilldown(
            available=False,
            path=path_label,
            id=_redact_text(normalized_id)[:160],
            error=error or "goal-state record unavailable",
        )

    requirements = payload.get("requirements")
    rows = requirements if isinstance(requirements, list) else []
    match = next(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and row.get("id", "").strip() == normalized_id
        ),
        None,
    )
    checkpoint_id = _goal_state_checkpoint_id(payload)
    updated_at = payload.get("updated_at")
    base = {
        "path": path_label,
        "updated_at": _redact_text(updated_at)[:80] if isinstance(updated_at, str) and updated_at.strip() else None,
        "checkpoint_id": checkpoint_id,
        "next_safe_local_actions": _safe_text_list(payload.get("next_authorized_local_actions"), MAX_GOAL_STATE_ACTIONS),
        "stop_boundaries": _safe_text_list(payload.get("stop_boundary"), MAX_GOAL_STATE_BOUNDARIES),
    }
    if match is None:
        return AgentWorkspaceGoalRequirementDrilldown(
            available=False,
            id=_redact_text(normalized_id)[:160],
            error="requirement id was not found in the selected goal-state record",
            **base,
        )

    evidence_refs, evidence_count, truncated = _safe_goal_requirement_evidence_refs(match.get("evidence"))
    status = match.get("status")
    row_id = match.get("id")
    return AgentWorkspaceGoalRequirementDrilldown(
        available=True,
        id=_redact_text(row_id.strip())[:160] if isinstance(row_id, str) and row_id.strip() else _redact_text(normalized_id)[:160],
        status=_redact_text(status.strip())[:80] if isinstance(status, str) and status.strip() else None,
        requirement=_safe_requirement_text(match.get("requirement")),
        residual_risk=_safe_requirement_text(match.get("residual_risk")),
        evidence=evidence_refs,
        evidence_count=evidence_count,
        truncated=truncated,
        **base,
    )


def _workspace_recovery_probe(
    label: str,
    route: str,
    purpose: str,
    *,
    mcp_tool: str | None = None,
    requires_identifier: bool = False,
    identifier_hint: str | None = None,
) -> AgentWorkspaceRecoveryProbe:
    """Create a typed read-only recovery probe with boundary validation.

    Args:
        label: Human-readable probe label.
        route: Absolute local route or route pattern.
        purpose: Short recovery reason for resumed agents.
        mcp_tool: Optional MCP tool name for the same projection.
        requires_identifier: Whether route placeholders need runtime context.
        identifier_hint: Identifier expected by the route pattern.

    Returns:
        A response-model validated read-only recovery probe.

    Raises:
        ValueError: If required probe fields are malformed.
    """

    if not isinstance(label, str) or not label.strip():
        raise ValueError("recovery probe label must be non-empty")
    if not isinstance(route, str) or not route.strip() or not route.strip().startswith("/"):
        raise ValueError("recovery probe route must be an absolute local route")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError("recovery probe purpose must be non-empty")
    if requires_identifier and (not isinstance(identifier_hint, str) or not identifier_hint.strip()):
        raise ValueError("identifier_hint is required for identifier-bound recovery probes")
    return AgentWorkspaceRecoveryProbe(
        label=label.strip(),
        route=route.strip(),
        read_only=True,
        requires_identifier=requires_identifier,
        identifier_hint=identifier_hint.strip() if isinstance(identifier_hint, str) and identifier_hint.strip() else None,
        purpose=purpose.strip(),
        mcp_tool=mcp_tool.strip() if isinstance(mcp_tool, str) and mcp_tool.strip() else None,
    )


def _latest_activity(
    artifacts: list[AgentWorkspaceArtifact],
    audit_records: list[AgentWorkspaceAuditRecord],
) -> str | None:
    """Return the newest known activity timestamp."""

    values = [item.modified_at for item in artifacts]
    values.extend(record.timestamp for record in audit_records)
    return max(values) if values else None


def _build_workspace_state() -> AgentWorkspaceState:
    """Build the read-only local workspace recovery state."""

    artifact_state = _count_directory_state("agent_mcp_workflows", _workspace_root(), excluded_root=_audit_root())
    runtime_state = _count_directory_state("runtime_state", WORKSPACE_RUNTIME_STATE_ROOT)
    output_state = _count_directory_state("generated_output", WORKSPACE_OUTPUT_ROOT)
    git_state = _read_git_workspace_state()
    goal_state = _load_goal_state_summary()
    desktop_smoke = _load_desktop_smoke_state()
    ocr_runtime = _load_ocr_runtime_state()
    wiki_doctor = _load_wiki_doctor_state()
    knowledge_actual_loading_gate = _load_knowledge_actual_loading_gate_state()
    boundaries = [
        "Do not execute approvals, import-to-wiki writes, external uploads, push, tag, release, publish, or deploy from this status surface.",
        "Do not mutate Zotero databases or github/ reference repositories from Agent Workspace state.",
        "Create a rollback checkpoint and re-check official or mature references before nontrivial edits.",
    ]
    next_actions = [
        "Read Wiki Doctor, Knowledge Packages, Knowledge Runtime Conformance, Wiki/Product Docs/Academic English/Source Vault search refs, bounded resource reads, Knowledge Context Receipt, MCP Result Envelope, Goal Lifecycle Completion Gate, Workflow Passport, Evidence Integrity Gate, Research Action Lifecycle, Agent Handoff Cards, and Goal Requirement Drilldowns before resuming mutating work or claiming closure.",
        "Inspect git dirty paths and preserve unrelated local work before staging or committing.",
        "Use workspace artifacts and audit records as recovery evidence; treat missing evidence as unresolved.",
    ]
    return AgentWorkspaceState(
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        workspace_ready=artifact_state.exists and runtime_state.exists,
        artifact_root=artifact_state,
        runtime_state_root=runtime_state,
        output_root=output_state,
        git=git_state,
        goal_state=goal_state,
        desktop_smoke=desktop_smoke,
        ocr_runtime=ocr_runtime,
        wiki_doctor=wiki_doctor,
        knowledge_actual_loading_gate=knowledge_actual_loading_gate,
        recovery_probes=[
            _workspace_recovery_probe(
                "Desktop Smoke Evidence",
                "/api/agent-workspace/status",
                "Recover latest source desktop screenshot and accessibility-tree artifact labels before claiming UI acceptance.",
                mcp_tool="literature.agent_workspace_status",
            ),
            _workspace_recovery_probe(
                "OCR Runtime Status",
                "/api/pdf-backend/ocr-status",
                "Recover OCR policy, selected engine, readiness blockers, and redacted runtime config before claiming local processing capability.",
                mcp_tool="literature.ocr_status",
            ),
            _workspace_recovery_probe(
                "Wiki Doctor",
                "/api/wiki/doctor",
                "Recover wiki integrity diagnostics and Source Vault mirror backlog before claiming Knowledge Runtime Pipeline closure.",
                mcp_tool="literature.wiki_doctor",
            ),
            _workspace_recovery_probe(
                "Knowledge Runtime Conformance",
                "/api/knowledge/runtime-conformance",
                "Recover package conformance, actual-loading gate state, and blocked evidence before claiming model-context readiness.",
                mcp_tool="literature.knowledge_runtime_conformance",
            ),
            _workspace_recovery_probe(
                "Knowledge Packages",
                "/api/knowledge/packages",
                "Recover package source paths, hashes, runtime consumers, and load status before selecting refs for bounded context.",
                mcp_tool="literature.knowledge_packages",
            ),
            _workspace_recovery_probe(
                "Wiki Search",
                "/api/wiki/search",
                "Recover wiki refs before bounded resource reads or context receipts.",
                mcp_tool="literature.wiki_search",
                requires_identifier=True,
                identifier_hint="query",
            ),
            _workspace_recovery_probe(
                "Academic English Search",
                "/api/knowledge/academic-english/search?q={query}",
                "Recover academic-English refs before bounded resource reads or context receipts.",
                mcp_tool="literature.academic_english_search",
                requires_identifier=True,
                identifier_hint="query",
            ),
            _workspace_recovery_probe(
                "Product Docs Search",
                "/api/knowledge/product-docs/search?q={query}",
                "Recover product-doc refs before bounded resource reads or context receipts.",
                mcp_tool="literature.product_docs_search",
                requires_identifier=True,
                identifier_hint="query",
            ),
            _workspace_recovery_probe(
                "Source Vault Status",
                "/api/knowledge/source-vault",
                "Recover Source Vault manifest, source counts, refs, and empty-runtime blockers before claiming source-to-context proof.",
                mcp_tool="literature.source_vault_status",
            ),
            _workspace_recovery_probe(
                "Source Vault Search",
                "/api/knowledge/source-vault/search?q={query}",
                "Recover Source Vault search refs before reading bounded resources or assembling context receipts.",
                mcp_tool="literature.source_vault_search",
                requires_identifier=True,
                identifier_hint="query",
            ),
            _workspace_recovery_probe(
                "Source Vault Resource Read",
                "/api/agent-bridge/resource/{ref_id}",
                "Recover bounded Source Vault resource text, cursor, hash, and provenance before using refs as context.",
                mcp_tool="literature.source_vault_read",
                requires_identifier=True,
                identifier_hint="ref_id",
            ),
            _workspace_recovery_probe(
                "Knowledge Context Receipt",
                "/api/knowledge/context-receipt",
                "Recover bounded context receipt proof for selected refs before claiming prompt/context loading.",
                mcp_tool="literature.knowledge_context_receipt",
                requires_identifier=True,
                identifier_hint="ref_id",
            ),
            _workspace_recovery_probe(
                "MCP Result Envelope",
                "/api/agent-workspace/status",
                "Recover safe_result envelope fields, recursive redaction, structured truncation metadata, and serialization_failed boundaries from the source-readable MCP capability map before interpreting large tool outputs.",
                mcp_tool="source.read_file",
            ),
            _workspace_recovery_probe(
                "Goal Lifecycle Completion Gate",
                "/api/agent-workspace/status",
                "Recover can_mark_goal_complete, completion_blockers, completion_claim, and why_not_complete before treating all-proved requirements as long-goal closure.",
                mcp_tool="literature.agent_workspace_status",
            ),
            _workspace_recovery_probe(
                "Workflow Passport",
                "/runtime/workflow-passport",
                "Recover stage, gate, reproducibility, and provenance context before resuming workflow work.",
                mcp_tool="literature.workflow_passport",
            ),
            _workspace_recovery_probe(
                "Evidence Integrity Gate",
                "/runtime/evidence-integrity-gate",
                "Recover blockers, unresolved evidence, and integrity signals before trusting claims.",
                mcp_tool="literature.evidence_integrity_gate",
            ),
            _workspace_recovery_probe(
                "Research Action Lifecycle",
                "/runtime/research-action-lifecycle",
                "Recover action, approval, preflight, effect, and forbidden-action state before mutation.",
                mcp_tool="literature.research_action_lifecycle",
            ),
            _workspace_recovery_probe(
                "Agent Handoff Card",
                "/runtime/job/{job_id}/agent-handoff-card",
                "Recover resumable handoff instructions, resource refs, replay recovery, and boundaries for one job.",
                mcp_tool="literature.agent_handoff_card",
                requires_identifier=True,
                identifier_hint="job_id",
            ),
            _workspace_recovery_probe(
                "Agent Workspace Status",
                "/api/agent-workspace/status",
                "Recover local artifact, audit, git, root, and recovery-probe state.",
                mcp_tool="literature.agent_workspace_status",
            ),
            _workspace_recovery_probe(
                "Goal Requirement Drilldown",
                "/api/agent-workspace/goal-requirements/{requirement_id}",
                "Recover one requirement-to-evidence row by id before claiming closure.",
                mcp_tool="literature.agent_workspace_requirement",
                requires_identifier=True,
                identifier_hint="requirement_id",
            ),
        ],
        boundaries=boundaries,
        next_safe_local_actions=next_actions,
    )


@router.get("/status", response_model=AgentWorkspaceStatus)
async def get_agent_workspace_status(
    artifact_limit: int = Query(200, ge=1, le=MAX_ARTIFACTS),
    audit_limit: int = Query(300, ge=1, le=MAX_AUDIT_RECORDS),
    preview_chars: int = Query(4000, ge=0, le=MAX_PREVIEW_CHARS),
) -> AgentWorkspaceStatus:
    """Return redacted Agent Workspace artifacts and MCP audit events."""

    root = _workspace_root()
    root.mkdir(parents=True, exist_ok=True)
    _audit_root().mkdir(parents=True, exist_ok=True)
    artifacts, total_bytes = _load_artifacts(artifact_limit, preview_chars)
    audit_records = _load_audit_records(audit_limit)
    return AgentWorkspaceStatus(
        artifact_root=str(root),
        artifact_count=len(_iter_artifact_files(root)),
        audit_count=len(audit_records),
        total_artifact_bytes=total_bytes,
        latest_activity_at=_latest_activity(artifacts, audit_records),
        workspace_state=_build_workspace_state(),
        artifacts=artifacts,
        audit_records=audit_records,
    )


@router.get("/goal-requirements/{requirement_id}", response_model=AgentWorkspaceGoalRequirementDrilldown)
async def get_agent_workspace_goal_requirement(
    requirement_id: str,
) -> AgentWorkspaceGoalRequirementDrilldown:
    """Return a bounded read-only requirement-to-evidence drilldown."""

    return _load_goal_requirement_drilldown(requirement_id)
