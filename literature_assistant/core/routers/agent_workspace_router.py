# -*- coding: utf-8 -*-
"""Read-only Agent Workspace API for local MCP workflow visibility."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from project_paths import WORKSPACE_ARTIFACTS_ROOT


router = APIRouter(prefix="/api/agent-workspace", tags=["Agent Workspace"])

WORKSPACE_DIR_NAME = "agent_mcp_workflows"
AUDIT_DIR_NAME = ".audit"
MAX_ARTIFACTS = 500
MAX_AUDIT_RECORDS = 1000
MAX_PREVIEW_CHARS = 12000
MAX_FILE_BYTES = 2 * 1024 * 1024


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


class AgentWorkspaceStatus(BaseModel):
    """Aggregated Agent Workspace snapshot."""

    artifact_root: str
    artifact_count: int = Field(ge=0)
    audit_count: int = Field(ge=0)
    total_artifact_bytes: int = Field(ge=0)
    latest_activity_at: str | None = None
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

        return SecretRedactor.scan(value)
    except Exception:
        import re

        text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-***REDACTED***", value)
        text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{8,}", "Bearer ***REDACTED***", text)
        text = re.sub(r"(?i)\bAuthorization:\s*(?:Bearer|Basic)\s+\S+", "Authorization: ***REDACTED***", text)
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


def _latest_activity(
    artifacts: list[AgentWorkspaceArtifact],
    audit_records: list[AgentWorkspaceAuditRecord],
) -> str | None:
    """Return the newest known activity timestamp."""

    values = [item.modified_at for item in artifacts]
    values.extend(record.timestamp for record in audit_records)
    return max(values) if values else None


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
        artifacts=artifacts,
        audit_records=audit_records,
    )
