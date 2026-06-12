"""Diagnostics endpoints — read-only window into backend.log for the UI.

Why this exists:
    Users see chat fail (rerank API down, embedding endpoint blocked,
    safety policy reject) but the only place the failure mode is recorded
    is the backend log file. Tailing a file on disk works for engineers
    but is invisible to product users. This router exposes a tightly
    scoped read API the Settings UI can poll.

Scope guards:
    - Only reads files under ``runtime_state_path("logs")``. Any other
      path is rejected with 400 — no traversal.
    - Hard line cap (``MAX_LINES``) so a UI bug can't pull a 50MB tail.
    - Level filter is whitelist-only (``DEBUG/INFO/WARNING/ERROR/CRITICAL``).
    - Search term is treated as a plain substring, not a regex, to avoid
      accidental ReDoS via UI input.
    - Lines pass through ``_redact_sensitive_log_text`` (same redactor the
      file handler uses) so any credential that leaked past the original
      sink still gets masked in the API response.

What this is NOT:
    - Not a remote log forwarder. Loopback only — the existing CORS /
      capability auth on the adapter applies; no extra ACL.
    - Not a log writer. There is no POST.
    - Not a stream / SSE. Frontend polls with a small interval; SSE would
      require more handler plumbing for one debugging surface.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("diagnostics_router")

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics"])

# Hard limits — UI cannot ask for more than this in one round-trip.
MAX_LINES = 2000
DEFAULT_LINES = 200

VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Adapter LOG_FORMAT in practice writes:
#   "2026-06-09 11:05:06,982 - httpx - INFO - HTTP Request: ..."
# i.e. " - " separator between asctime / name / levelname / message.
# The regex is loose enough to also catch "ISO T" style if a logger
# overrides the format. Non-conforming lines (uvicorn startup banner,
# stack frames) are treated as continuations.
_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)"
    r"\s*-\s*"
    r"(?P<logger>[^\s-][^\s][^-]*?)"
    r"\s*-\s*"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)"
    r"\s*-\s*"
    r"(?P<message>.*)$"
)


class LogLineEntry(BaseModel):
    """One parsed log line. Continuation lines (stack traces) carry the
    same ``level`` / ``logger`` as the preceding parsed line so the UI
    can group them under a single entry."""

    timestamp: str = ""
    level: str = ""
    logger_name: str = ""
    message: str
    raw: str
    is_continuation: bool = False


class LogTailResponse(BaseModel):
    file: str
    file_size_bytes: int
    total_returned: int
    truncated: bool = False
    available_files: list[str] = Field(default_factory=list)
    entries: list[LogLineEntry] = Field(default_factory=list)


def _logs_dir() -> Path:
    """Resolve the absolute logs directory, importing project_paths lazily
    so the router stays importable in test environments that don't have
    the production runtime path setup."""
    from project_paths import runtime_state_path  # local import, mirrors adapter

    return runtime_state_path("logs")


def _list_available_files() -> list[str]:
    """List rotating log file basenames (``backend.log``, ``backend.log.1``…)
    in the logs dir. Sorted newest-first by mtime so the UI can default to
    the current file but still let users pick older rolls."""
    base = _logs_dir()
    if not base.is_dir():
        return []
    try:
        items = sorted(
            (p for p in base.iterdir() if p.is_file() and p.name.startswith("backend.log")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [p.name for p in items]
    except OSError:
        return []


def _resolve_file_path(name: str) -> Path:
    """Strictly resolve ``name`` against the logs dir.

    Rejects anything that escapes the logs dir (path traversal) or is not
    a regular file. Empty ``name`` defaults to ``backend.log``.
    """
    base = _logs_dir().resolve()
    candidate = (base / (name or "backend.log")).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="log path escapes logs directory") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"log file not found: {candidate.name}")
    return candidate


def _tail_lines(path: Path, want: int) -> tuple[list[str], bool]:
    """Read up to ``want`` lines from the tail of ``path``.

    Returns (lines, truncated). ``truncated`` means there were more lines
    than ``want`` so the head is missing — UI shows a banner.

    Why not seek-from-end byte scan: rotating logs cap at 10MB so the
    whole file fits in memory cheaply; the simple ``readlines`` path is
    correct for UTF-8 + CRLF and avoids edge-case off-by-ones at the
    file boundary.
    """
    want = max(1, min(want, MAX_LINES))
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"could not read log: {exc}") from exc
    truncated = len(lines) > want
    return lines[-want:], truncated


def _redact(text: str) -> str:
    """Best-effort credential redactor.

    The adapter's ``SensitiveDataFilter`` already runs at log time, so
    most patterns are already masked. We re-run a lightweight pass here
    in case a downstream library wrote to disk before the filter
    attached (early-boot logs).
    """
    if "***REDACTED***" in text:
        return text
    try:
        from python_adapter_server import _redact_sensitive_log_text  # type: ignore[attr-defined]
        return _redact_sensitive_log_text(text)
    except Exception:
        # Conservative inline patterns — never silently let raw secrets
        # reach the API consumer.
        text = re.sub(r"(sk-[A-Za-z0-9_-]{8,})", r"sk-***REDACTED***", text)
        text = re.sub(r"(Bearer\s+)([A-Za-z0-9._-]{8,})", r"\1***REDACTED***", text)
        return text


def _parse_lines(
    lines: Iterable[str],
    *,
    level_filter: set[str] | None,
    search: str,
) -> list[LogLineEntry]:
    """Parse rolling log lines and apply filters in one pass.

    Continuation lines (no leading timestamp, e.g. stack frames) inherit
    the level of the most-recent parsed line and pass the filter as a
    group. This keeps tracebacks intact under a level=ERROR filter.
    """
    out: list[LogLineEntry] = []
    last_parsed: LogLineEntry | None = None
    needle = search.strip().lower()
    for raw in lines:
        line = raw.rstrip("\r\n")
        match = _LINE_RE.match(line)
        if match is not None:
            level = match.group("level")
            if level_filter is not None and level not in level_filter:
                last_parsed = None
                continue
            redacted_msg = _redact(match.group("message"))
            entry = LogLineEntry(
                timestamp=match.group("ts"),
                level=level,
                logger_name=match.group("logger"),
                message=redacted_msg,
                raw=_redact(line),
                is_continuation=False,
            )
            if needle and needle not in redacted_msg.lower() and needle not in entry.logger_name.lower():
                last_parsed = entry  # remember for child lines, but skip emit
                continue
            out.append(entry)
            last_parsed = entry
        else:
            # Continuation (traceback, multiline message). Attach to the
            # most-recent parsed entry IF it passed the level filter.
            if last_parsed is None:
                continue
            redacted_raw = _redact(line)
            if needle and needle not in redacted_raw.lower():
                continue
            out.append(LogLineEntry(
                timestamp=last_parsed.timestamp,
                level=last_parsed.level,
                logger_name=last_parsed.logger_name,
                message=redacted_raw,
                raw=redacted_raw,
                is_continuation=True,
            ))
    return out


@router.get("/logs", response_model=LogTailResponse)
async def get_log_tail(
    name: str = Query("backend.log", description="Log file basename within the logs dir."),
    lines: int = Query(DEFAULT_LINES, ge=1, le=MAX_LINES, description="Tail size."),
    level: str = Query("", description="One of DEBUG/INFO/WARNING/ERROR/CRITICAL, or empty for all."),
    search: str = Query("", description="Substring match against message or logger name."),
) -> LogTailResponse:
    """Return the tail of one rotating backend log.

    Use cases:
      - User sees "rerank failed, falling back to local" and wants to know
        which provider broke. ``level=WARNING&search=rerank``.
      - Setup wizard: confirm the backend received the credential by
        searching for the masked suffix.
      - Pre-bug-report: copy out the last 200 lines.
    """
    path = _resolve_file_path(name)
    file_size = path.stat().st_size

    level = level.strip().upper()
    level_set: set[str] | None = None
    if level:
        if level not in VALID_LEVELS:
            raise HTTPException(
                status_code=400,
                detail=f"invalid level: {level!r}; valid: {VALID_LEVELS}",
            )
        # Threshold semantics: level=WARNING returns WARNING + ERROR + CRITICAL.
        idx = VALID_LEVELS.index(level)
        level_set = set(VALID_LEVELS[idx:])

    raw_lines, truncated = _tail_lines(path, lines)
    entries = _parse_lines(raw_lines, level_filter=level_set, search=search)

    return LogTailResponse(
        file=path.name,
        file_size_bytes=file_size,
        total_returned=len(entries),
        truncated=truncated,
        available_files=_list_available_files(),
        entries=entries,
    )


@router.get("/logs/files")
async def list_log_files() -> dict[str, list[str]]:
    """List rotating log file names available for tail.

    Frontend uses this to populate a "Switch file" dropdown without
    eagerly tailing every file.
    """
    return {"files": _list_available_files()}
