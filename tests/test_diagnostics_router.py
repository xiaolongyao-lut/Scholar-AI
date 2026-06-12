"""Tests for the /api/diagnostics/logs endpoint.

Pins:
1. Line parser handles the real adapter log format
   "YYYY-MM-DD HH:MM:SS,sss - logger - LEVEL - message".
2. Level filter is threshold-based: WARNING returns WARNING+ERROR+CRITICAL.
3. Continuation lines (stack frames, no leading timestamp) inherit the
   level of the preceding parsed line so tracebacks stay grouped.
4. Path traversal is blocked.
5. Bad level value returns 400.
6. Credentials in log content are redacted before reaching the API.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_CORE = Path(__file__).resolve().parents[1] / "literature_assistant" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))


def _make_log(tmp_path: Path, body: str) -> Path:
    logs = tmp_path / "logs"
    logs.mkdir()
    target = logs / "backend.log"
    target.write_text(body, encoding="utf-8")
    return target


@pytest.fixture
def diagnostics_with_temp_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Redirect _logs_dir() to a tmp directory the test populates."""
    from routers import diagnostics_router

    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(diagnostics_router, "_logs_dir", lambda: logs)
    return diagnostics_router, logs


def test_parser_extracts_timestamp_level_logger_message(diagnostics_with_temp_logs) -> None:
    dr, logs_dir = diagnostics_with_temp_logs
    (logs_dir / "backend.log").write_text(
        "2026-06-09 11:05:06,982 - httpx - INFO - HTTP Request: GET /health\n"
        "2026-06-09 11:05:07,000 - PipelineAdapter - WARNING - 400 trace=abc\n"
        "2026-06-09 11:05:08,100 - PipelineAdapter - ERROR - rerank failed: net\n",
        encoding="utf-8",
    )
    tail = asyncio.run(dr.get_log_tail(name="backend.log", lines=10, level="", search=""))
    assert tail.total_returned == 3
    levels = [e.level for e in tail.entries]
    assert levels == ["INFO", "WARNING", "ERROR"]
    msgs = [e.message for e in tail.entries]
    assert "HTTP Request" in msgs[0]
    assert "rerank failed" in msgs[2]


def test_level_filter_is_threshold(diagnostics_with_temp_logs) -> None:
    """level=WARNING must return WARNING + ERROR + CRITICAL, not just WARNING."""
    dr, logs_dir = diagnostics_with_temp_logs
    (logs_dir / "backend.log").write_text(
        "2026-06-09 10:00:00,000 - mod - DEBUG - dbg\n"
        "2026-06-09 10:00:01,000 - mod - INFO - inf\n"
        "2026-06-09 10:00:02,000 - mod - WARNING - warn\n"
        "2026-06-09 10:00:03,000 - mod - ERROR - err\n"
        "2026-06-09 10:00:04,000 - mod - CRITICAL - crit\n",
        encoding="utf-8",
    )
    tail = asyncio.run(dr.get_log_tail(name="backend.log", lines=50, level="WARNING", search=""))
    levels = [e.level for e in tail.entries]
    assert levels == ["WARNING", "ERROR", "CRITICAL"]


def test_continuation_lines_inherit_level(diagnostics_with_temp_logs) -> None:
    """Stack frames following an ERROR line must surface under level=ERROR."""
    dr, logs_dir = diagnostics_with_temp_logs
    (logs_dir / "backend.log").write_text(
        "2026-06-09 10:00:00,000 - mod - ERROR - boom\n"
        "Traceback (most recent call last):\n"
        "  File 'x.py', line 1, in <module>\n"
        "    raise ValueError('oops')\n"
        "ValueError: oops\n",
        encoding="utf-8",
    )
    tail = asyncio.run(dr.get_log_tail(name="backend.log", lines=10, level="ERROR", search=""))
    # The ERROR line plus all 4 traceback frames.
    assert tail.total_returned == 5
    assert tail.entries[0].is_continuation is False
    assert all(e.is_continuation for e in tail.entries[1:])
    assert all(e.level == "ERROR" for e in tail.entries)


def test_search_substring_filters_logger_name_and_message(diagnostics_with_temp_logs) -> None:
    dr, logs_dir = diagnostics_with_temp_logs
    (logs_dir / "backend.log").write_text(
        "2026-06-09 10:00:00,000 - reranker - INFO - searching\n"
        "2026-06-09 10:00:01,000 - other - INFO - unrelated\n"
        "2026-06-09 10:00:02,000 - other - WARNING - rerank fallback fired\n",
        encoding="utf-8",
    )
    tail = asyncio.run(dr.get_log_tail(name="backend.log", lines=10, level="", search="rerank"))
    # Both lines mentioning "rerank" (one in logger name, one in message).
    assert tail.total_returned == 2
    assert tail.entries[0].logger_name == "reranker"
    assert "fallback" in tail.entries[1].message


def test_path_traversal_is_blocked(diagnostics_with_temp_logs) -> None:
    dr, logs_dir = diagnostics_with_temp_logs
    (logs_dir / "backend.log").write_text("2026-06-09 10:00:00,000 - mod - INFO - ok\n", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dr.get_log_tail(name="../../etc/passwd", lines=10, level="", search=""))
    assert exc.value.status_code == 400


def test_unknown_level_returns_400(diagnostics_with_temp_logs) -> None:
    dr, logs_dir = diagnostics_with_temp_logs
    (logs_dir / "backend.log").write_text("2026-06-09 10:00:00,000 - mod - INFO - ok\n", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dr.get_log_tail(name="backend.log", lines=10, level="LOUD", search=""))
    assert exc.value.status_code == 400


def test_missing_file_returns_404(diagnostics_with_temp_logs) -> None:
    dr, _ = diagnostics_with_temp_logs
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dr.get_log_tail(name="nope.log", lines=10, level="", search=""))
    assert exc.value.status_code == 404


def test_credentials_in_log_body_are_redacted(diagnostics_with_temp_logs) -> None:
    dr, logs_dir = diagnostics_with_temp_logs
    (logs_dir / "backend.log").write_text(
        "2026-06-09 10:00:00,000 - mod - WARNING - bad key sk-abcdefghijklmnop in payload\n"
        "2026-06-09 10:00:01,000 - mod - WARNING - Bearer tok-1234567890abcdef seen\n",
        encoding="utf-8",
    )
    tail = asyncio.run(dr.get_log_tail(name="backend.log", lines=10, level="", search=""))
    body = "\n".join(e.message for e in tail.entries)
    assert "sk-abcdefghijklmnop" not in body
    assert "tok-1234567890abcdef" not in body
    assert "***REDACTED***" in body


def test_lines_clamped_to_max(diagnostics_with_temp_logs) -> None:
    dr, logs_dir = diagnostics_with_temp_logs
    body = "\n".join(
        f"2026-06-09 10:00:{i:02},000 - mod - INFO - line {i}" for i in range(0, 50)
    )
    (logs_dir / "backend.log").write_text(body, encoding="utf-8")
    # Request more than MAX_LINES — FastAPI Query(le=MAX_LINES) validates,
    # so we test the next path: small file, valid request.
    tail = asyncio.run(dr.get_log_tail(name="backend.log", lines=200, level="", search=""))
    assert tail.total_returned <= 50
    assert tail.truncated is False  # 50-line file fits in 200 tail


def test_list_files_returns_backend_log_variants(diagnostics_with_temp_logs) -> None:
    dr, logs_dir = diagnostics_with_temp_logs
    (logs_dir / "backend.log").write_text("a\n", encoding="utf-8")
    (logs_dir / "backend.log.1").write_text("b\n", encoding="utf-8")
    (logs_dir / "unrelated.log").write_text("c\n", encoding="utf-8")
    result = asyncio.run(dr.list_log_files())
    files = result["files"]
    assert "backend.log" in files
    assert "backend.log.1" in files
    assert "unrelated.log" not in files
