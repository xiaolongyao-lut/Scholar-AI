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

from project_paths import REPO_ROOT, WORKSPACE_ARTIFACTS_ROOT, WORKSPACE_OUTPUT_ROOT, WORKSPACE_RUNTIME_STATE_ROOT


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
MAX_GOAL_STATE_BOUNDARIES = 3
MAX_GOAL_COMPLETION_CHARS = 240
GIT_STATUS_TIMEOUT_SECONDS = 2.0


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
    """

    this_slice: str | None = Field(default=None, max_length=MAX_GOAL_COMPLETION_CHARS)
    full_goal: str | None = Field(default=None, max_length=MAX_GOAL_COMPLETION_CHARS)


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


class AgentWorkspaceGoalState(BaseModel):
    """Bounded longrun goal-state summary for recovery decisions.

    Args:
        available: Whether a local goal-state JSON record was found and parsed.
        path: Repository-relative or redacted label for the selected record.
        updated_at: Timestamp from the selected goal-state record.
        checkpoint_id: Rollback checkpoint id, without local checkpoint path.
        requirement_count: Number of requirement-to-evidence rows.
        proved_count: Number of rows currently proved.
        incomplete_count: Number of incomplete rows.
        out_of_scope_count: Number of rows explicitly outside current scope.
        latest_requirement_id: Last requirement id in the matrix.
        requirement_status: Compact requirement-to-evidence status summary.
        completion_claim: Bounded slice/full-goal completion summary.
        next_authorized_local_actions: Bounded action labels from the record.
        stop_boundaries: Bounded stop-boundary labels from the record.
        error: Redacted parse/read error when unavailable.
    """

    available: bool
    path: str | None = Field(default=None, max_length=240)
    updated_at: str | None = Field(default=None, max_length=80)
    checkpoint_id: str | None = Field(default=None, max_length=120)
    requirement_count: int = Field(default=0, ge=0)
    proved_count: int = Field(default=0, ge=0)
    incomplete_count: int = Field(default=0, ge=0)
    out_of_scope_count: int = Field(default=0, ge=0)
    latest_requirement_id: str | None = Field(default=None, max_length=160)
    requirement_status: AgentWorkspaceGoalRequirementStatus = Field(default_factory=AgentWorkspaceGoalRequirementStatus)
    completion_claim: AgentWorkspaceGoalCompletionClaim = Field(default_factory=AgentWorkspaceGoalCompletionClaim)
    next_authorized_local_actions: list[str] = Field(default_factory=list)
    stop_boundaries: list[str] = Field(default_factory=list)
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


def _safe_goal_completion_claim(value: Any) -> AgentWorkspaceGoalCompletionClaim:
    """Return bounded completion claims without exposing the full goal record."""

    if not isinstance(value, dict):
        return AgentWorkspaceGoalCompletionClaim()
    this_slice = value.get("this_slice")
    full_goal = value.get("full_goal")
    return AgentWorkspaceGoalCompletionClaim(
        this_slice=_redact_text(this_slice).strip()[:MAX_GOAL_COMPLETION_CHARS]
        if isinstance(this_slice, str) and this_slice.strip()
        else None,
        full_goal=_redact_text(full_goal).strip()[:MAX_GOAL_COMPLETION_CHARS]
        if isinstance(full_goal, str) and full_goal.strip()
        else None,
    )


def _load_goal_state_summary() -> AgentWorkspaceGoalState:
    """Load a bounded local goal-state summary without exposing full records."""

    path = _latest_goal_state_file()
    if path is None:
        return AgentWorkspaceGoalState(available=False, error="no longrun goal-state record found")
    path_label = _workspace_state_path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return AgentWorkspaceGoalState(available=False, path=path_label, error=_redact_text(str(exc))[:240])
    if not isinstance(payload, dict):
        return AgentWorkspaceGoalState(available=False, path=path_label, error="goal-state record is not an object")

    raw_requirements = payload.get("requirements")
    requirements = raw_requirements if isinstance(raw_requirements, list) else []
    statuses: dict[str, int] = {}
    latest_requirement_id: str | None = None
    for row in requirements:
        if not isinstance(row, dict):
            continue
        status = row.get("status")
        if isinstance(status, str):
            statuses[status] = statuses.get(status, 0) + 1
        row_id = row.get("id")
        if isinstance(row_id, str) and row_id.strip():
            latest_requirement_id = _redact_text(row_id.strip())[:160]

    rollback = payload.get("rollback")
    checkpoint_id = rollback.get("checkpoint_id") if isinstance(rollback, dict) else None
    updated_at = payload.get("updated_at")
    return AgentWorkspaceGoalState(
        available=True,
        path=path_label,
        updated_at=_redact_text(updated_at)[:80] if isinstance(updated_at, str) and updated_at.strip() else None,
        checkpoint_id=_redact_text(checkpoint_id)[:120] if isinstance(checkpoint_id, str) and checkpoint_id.strip() else None,
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
        completion_claim=_safe_goal_completion_claim(payload.get("completion_claim")),
        next_authorized_local_actions=_safe_text_list(payload.get("next_authorized_local_actions"), MAX_GOAL_STATE_ACTIONS),
        stop_boundaries=_safe_text_list(payload.get("stop_boundary"), MAX_GOAL_STATE_BOUNDARIES),
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
    boundaries = [
        "Do not execute approvals, import-to-wiki writes, external uploads, push, tag, release, publish, or deploy from this status surface.",
        "Do not mutate Zotero databases or github/ reference repositories from Agent Workspace state.",
        "Create a rollback checkpoint and re-check official or mature references before nontrivial edits.",
    ]
    next_actions = [
        "Read Workflow Passport, Evidence Integrity Gate, Research Action Lifecycle, and Agent Handoff Cards before resuming mutating work.",
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
        recovery_probes=[
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
