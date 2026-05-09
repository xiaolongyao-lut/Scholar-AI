"""MCP audit logger (Phase 5 / TASK-502).

Append-only JSONL of tool-call records (one line per dispatch). The
dispatcher writes here regardless of success / failure so the dashboard
endpoint and offline review can see every invocation, including the
ones blocked by approval / capability gates.

Schema (one JSON object per line):

  {
    "ts": "2026-05-09T01:02:03+00:00",
    "tool_call_id": "call_xyz",
    "server_id": "mcp_demo",
    "server_slug": "demo",
    "tool_name": "echo",
    "is_error": false,
    "elapsed_ms": 12,
    "preview": "...redacted text...",
    "truncated": false
  }

File: ``runtime_state_path("mcp_servers", "audit.jsonl")``. Bounded by
``MCP_AUDIT_MAX_LINES`` (default 5000) — when the cap is reached the
oldest 20% of lines are dropped on the next write.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from project_paths import runtime_state_path

from mcp_runtime.tool_result_formatter import ToolResultRecord


logger = logging.getLogger("McpAuditLogger")


_LOCK = threading.Lock()
_DEFAULT_MAX_LINES = 5000


def audit_log_path() -> Path:
    return runtime_state_path("mcp_servers", "audit.jsonl")


def _max_lines() -> int:
    raw = os.environ.get("MCP_AUDIT_MAX_LINES")
    if not raw:
        return _DEFAULT_MAX_LINES
    try:
        return max(100, int(raw))
    except ValueError:
        return _DEFAULT_MAX_LINES


def _record_to_dict(record: ToolResultRecord) -> dict[str, Any]:
    """Trim raw_content from the audit dump (preview already carries the
    redacted version)."""
    d = asdict(record)
    d.pop("raw_content", None)
    d["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return d


def append(record: ToolResultRecord) -> None:
    """Append one record to the audit JSONL. Best-effort: failures are
    logged, never raised — audit must not break tool dispatch.
    """
    try:
        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(_record_to_dict(record), ensure_ascii=False)
        with _LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            _maybe_rotate(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_audit_append_failed: %s", exc)


def _maybe_rotate(path: Path) -> None:
    cap = _max_lines()
    try:
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    if len(lines) <= cap:
        return
    drop = max(1, len(lines) - cap + (cap // 5))
    keep = lines[drop:]
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.writelines(keep)
    os.replace(tmp, path)


def read_recent(limit: int = 200) -> list[dict[str, Any]]:
    """Return the last ``limit`` records (newest last). Returns [] if the
    file is missing.
    """
    path = audit_log_path()
    if not path.exists():
        return []
    limit = max(1, min(limit, 5000))
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh.readlines()[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.warning("mcp_audit_read_failed: %s", exc)
    return out


def clear() -> None:
    """Test helper: delete the audit file."""
    path = audit_log_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


__all__ = [
    "append",
    "audit_log_path",
    "clear",
    "read_recent",
]
