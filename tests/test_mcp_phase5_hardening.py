"""Phase 5 tests: audit logger + streamable_http URL guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_runtime import audit as mcp_audit
from mcp_runtime.security_policy import (
    McpSecurityPolicyError,
    validate_streamable_http_url,
)
from mcp_runtime.tool_result_formatter import build_tool_result_record


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


@pytest.fixture()
def audit_path(tmp_path: Path, monkeypatch) -> Path:
    target = tmp_path / "audit.jsonl"
    monkeypatch.setattr(mcp_audit, "audit_log_path", lambda: target)
    return target


def _make_record(*, tool: str = "echo", is_error: bool = False):
    return build_tool_result_record(
        tool_call_id="c1",
        server_id="mcp_demo",
        server_slug="demo",
        tool_name=tool,
        raw={"is_error": is_error, "content": [{"type": "text", "text": "ok"}]},
        elapsed_ms=5,
    )


def test_audit_append_creates_jsonl(audit_path: Path) -> None:
    mcp_audit.append(_make_record())
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["tool_name"] == "echo"
    assert "ts" in rec
    assert "raw_content" not in rec


def test_audit_append_multiple_lines(audit_path: Path) -> None:
    for i in range(5):
        mcp_audit.append(_make_record(tool=f"t{i}"))
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5


def test_audit_read_recent_returns_tail(audit_path: Path) -> None:
    for i in range(10):
        mcp_audit.append(_make_record(tool=f"t{i}"))
    out = mcp_audit.read_recent(limit=3)
    assert len(out) == 3
    assert [r["tool_name"] for r in out] == ["t7", "t8", "t9"]


def test_audit_read_recent_returns_empty_when_missing(audit_path: Path) -> None:
    assert mcp_audit.read_recent(limit=10) == []


def test_audit_rotation_drops_oldest(audit_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MCP_AUDIT_MAX_LINES", "100")
    for i in range(120):
        mcp_audit.append(_make_record(tool=f"t{i}"))
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    # cap=100, drop = 120 - 100 + 100/5 = 40 → keep 80
    assert 60 <= len(lines) <= 100


# ---------------------------------------------------------------------------
# streamable_http URL guard
# ---------------------------------------------------------------------------


def test_streamable_http_accepts_public_https() -> None:
    validate_streamable_http_url("https://mcp.example.com/sse")


def test_streamable_http_accepts_public_http() -> None:
    validate_streamable_http_url("http://api.example.com/mcp")


def test_streamable_http_rejects_non_http_scheme() -> None:
    with pytest.raises(McpSecurityPolicyError, match="scheme"):
        validate_streamable_http_url("ftp://example.com")


def test_streamable_http_rejects_empty_host() -> None:
    with pytest.raises(McpSecurityPolicyError, match="host"):
        validate_streamable_http_url("https:///path")


@pytest.mark.parametrize("host", [
    "localhost",
    "127.0.0.1",
    "10.1.2.3",
    "192.168.1.10",
    "172.16.5.5",
    "169.254.1.1",
])
def test_streamable_http_rejects_private_ranges(host: str, monkeypatch) -> None:
    monkeypatch.delenv("LITERATURE_MCP_HTTP_ALLOW_PRIVATE", raising=False)
    with pytest.raises(McpSecurityPolicyError, match="private"):
        validate_streamable_http_url(f"https://{host}:8080/sse")


def test_streamable_http_allows_private_when_env_set(monkeypatch) -> None:
    monkeypatch.setenv("LITERATURE_MCP_HTTP_ALLOW_PRIVATE", "1")
    validate_streamable_http_url("http://localhost:8080/mcp")
    validate_streamable_http_url("https://10.0.0.5/sse")


def test_streamable_http_rejects_ipv6_loopback(monkeypatch) -> None:
    monkeypatch.delenv("LITERATURE_MCP_HTTP_ALLOW_PRIVATE", raising=False)
    with pytest.raises(McpSecurityPolicyError, match="private"):
        validate_streamable_http_url("https://[::1]:8080/")
