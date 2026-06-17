"""Audit logging for MCP tool calls."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import SecretRedactor


class AuditLog:
    """Write append-only audit events."""

    def __init__(self, audit_root: Path) -> None:
        """Initialize audit logger.

        Args:
            audit_root: Root directory for audit logs (e.g., workspace_artifacts/agent_mcp_workflows/.audit)
        """
        self.audit_root = audit_root
        self.audit_root.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        tool_name: str,
        args_summary: dict[str, Any],
        touched_paths: list[Path],
        allow_block_reason: str,
        result_preview: str,
        duration_ms: int,
        error_code: str | None = None,
    ) -> None:
        """Write an audit event.

        Args:
            tool_name: MCP tool name (e.g., "source.read_file")
            args_summary: Redacted argument summary
            touched_paths: Paths accessed during execution
            allow_block_reason: "allowed" or block reason
            result_preview: Redacted output preview (max 500 chars)
            duration_ms: Execution duration
            error_code: Optional error code
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self.audit_root / f"{today}.jsonl"

        # Redact all string fields
        redacted_args = {
            k: SecretRedactor.scan(str(v)) if isinstance(v, str) else v
            for k, v in args_summary.items()
        }
        redacted_preview = SecretRedactor.scan(result_preview[:500])

        record = {
            "timestamp": timestamp,
            "tool_name": tool_name,
            "args_summary": redacted_args,
            "touched_paths": [str(p) for p in touched_paths],
            "allow_block_reason": allow_block_reason,
            "result_preview": redacted_preview,
            "duration_ms": duration_ms,
            "error_code": error_code,
        }

        # Append to JSONL
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
