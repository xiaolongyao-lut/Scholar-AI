"""Integration tests for Phase 1B (security_policy + client_manager +
tool_catalog + mcp_router). Uses the Phase 0 echo_math stdio fixture as
a real MCP server target.

Skipped automatically if `mcp` / `fastmcp` are not installed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


def _can_import_mcp() -> bool:
    try:
        import mcp  # noqa: F401
        import fastmcp  # noqa: F401
        return True
    except ImportError:
        return False


HAS_MCP = _can_import_mcp()
SKIP_REASON = "mcp / fastmcp not installed"


_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mcp" / "echo_math_server.py"


def _stdio_create_payload(
    *,
    slug: str = "echo-math-int",
    name: str = "Echo Math Integration",
) -> dict:
    """Body for POST /api/mcp/servers — launches the Phase 0 fixture via the
    same Python interpreter the test runs in.
    """
    return {
        "name": name,
        "server_slug": slug,
        "transport": "stdio",
        "stdio": {
            "command": sys.executable,
            "args": [str(_FIXTURE)],
            "env": {},
        },
        "provenance": "runtime_user_confirmed",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    from mcp_runtime.server_store import RuntimeMcpServerStore
    from routers import mcp_router as r
    s = RuntimeMcpServerStore(path=tmp_path / "runtime_mcp_servers.json")
    r.set_mcp_server_store(s)
    yield s
    r.set_mcp_server_store(None)


@pytest.fixture()
def manager():
    from mcp_runtime.client_manager import McpClientManager, set_mcp_client_manager
    m = McpClientManager()
    set_mcp_client_manager(m)
    yield m
    asyncio.get_event_loop().run_until_complete(m.shutdown_all()) if False else None
    set_mcp_client_manager(None)


@pytest.fixture()
def catalog(manager):
    from mcp_runtime.tool_catalog import McpToolCatalog
    from routers import mcp_router as r
    cat = McpToolCatalog(list_tools_fn=manager.list_tools)
    r.set_mcp_tool_catalog(cat)
    yield cat
    r.set_mcp_tool_catalog(None)


@pytest.fixture()
def client(store, manager, catalog):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import mcp_router as r
    app = FastAPI()
    app.include_router(r.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# CRUD smoke (no network required)
# ---------------------------------------------------------------------------


def test_list_empty(client) -> None:
    resp = client.get("/api/mcp/servers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_then_get(client) -> None:
    body = _stdio_create_payload()
    r = client.post("/api/mcp/servers", json=body)
    assert r.status_code == 200, r.text
    pub = r.json()
    assert pub["server_id"].startswith("mcp_")
    assert pub["server_slug"] == "echo-math-int"
    assert pub["approval_state"] == "registered"
    # Fetch it back
    g = client.get(f"/api/mcp/servers/{pub['server_id']}")
    assert g.status_code == 200
    assert g.json()["server_id"] == pub["server_id"]


def test_create_rejects_duplicate_slug(client) -> None:
    body = _stdio_create_payload(slug="dup")
    assert client.post("/api/mcp/servers", json=body).status_code == 200
    body2 = _stdio_create_payload(slug="dup", name="Other")
    r = client.post("/api/mcp/servers", json=body2)
    assert r.status_code == 400


def test_update_approval_state_forward(client) -> None:
    pub = client.post("/api/mcp/servers", json=_stdio_create_payload()).json()
    r = client.put(
        f"/api/mcp/servers/{pub['server_id']}",
        json={"approval_state": "catalog_reviewed"},
    )
    assert r.status_code == 200
    assert r.json()["approval_state"] == "catalog_reviewed"


def test_update_approval_state_skip_rejected(client) -> None:
    pub = client.post("/api/mcp/servers", json=_stdio_create_payload()).json()
    r = client.put(
        f"/api/mcp/servers/{pub['server_id']}",
        json={"approval_state": "enabled_for_session"},
    )
    assert r.status_code == 400


def test_delete_then_404(client) -> None:
    pub = client.post("/api/mcp/servers", json=_stdio_create_payload()).json()
    r = client.delete(f"/api/mcp/servers/{pub['server_id']}")
    assert r.status_code == 200
    r2 = client.get(f"/api/mcp/servers/{pub['server_id']}")
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# /test endpoint (drives real stdio subprocess via Phase 0 fixture)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_MCP, reason=SKIP_REASON)
def test_endpoint_test_runs_list_tools_and_promotes_approval(client) -> None:
    pub = client.post("/api/mcp/servers", json=_stdio_create_payload()).json()
    sid = pub["server_id"]

    # Initial state: registered.
    assert pub["approval_state"] == "registered"

    r = client.post(f"/api/mcp/servers/{sid}/test")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok", body
    assert body["probed"] is True
    assert body["tool_count"] == 2  # echo + add
    tool_names = {t["name"] for t in body["tools"]}
    assert tool_names == {"echo", "add"}
    assert isinstance(body["fingerprint"], str) and len(body["fingerprint"]) == 16

    # First successful probe auto-promotes approval to catalog_reviewed.
    after = client.get(f"/api/mcp/servers/{sid}").json()
    assert after["approval_state"] == "catalog_reviewed"


@pytest.mark.skipif(not HAS_MCP, reason=SKIP_REASON)
def test_endpoint_tools_uses_cache_after_test(client) -> None:
    pub = client.post("/api/mcp/servers", json=_stdio_create_payload()).json()
    sid = pub["server_id"]
    # Prime the cache via /test
    client.post(f"/api/mcp/servers/{sid}/test")
    # Read cached
    r = client.get(f"/api/mcp/servers/{sid}/tools")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    assert names == {"echo", "add"}


@pytest.mark.skipif(not HAS_MCP, reason=SKIP_REASON)
def test_test_endpoint_404_for_missing(client) -> None:
    r = client.post("/api/mcp/servers/mcp_ghost/test")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# security_policy unit tests (no MCP SDK required)
# ---------------------------------------------------------------------------


def test_validate_stdio_command_rejects_dangerous_basename() -> None:
    from mcp_runtime.security_policy import (
        McpSecurityPolicyError,
        validate_stdio_command,
    )
    from models.mcp import McpStdioConfig
    with pytest.raises(McpSecurityPolicyError, match="dangerous list"):
        validate_stdio_command(McpStdioConfig(command="rm", args=["-rf", "/"]))


def test_validate_stdio_command_rejects_dangerous_arg_pattern() -> None:
    from mcp_runtime.security_policy import (
        McpSecurityPolicyError,
        validate_stdio_command,
    )
    from models.mcp import McpStdioConfig
    with pytest.raises(McpSecurityPolicyError, match="dangerous pattern"):
        validate_stdio_command(
            McpStdioConfig(command="python", args=["-c", "rm -rf /tmp/x"])
        )


def test_validate_stdio_command_accepts_python_runner() -> None:
    from mcp_runtime.security_policy import validate_stdio_command
    from models.mcp import McpStdioConfig
    # Should not raise
    validate_stdio_command(
        McpStdioConfig(command="python", args=["-m", "tests.fixtures.mcp.echo_math_server"])
    )


def test_prepare_subprocess_env_strips_secret_inheritance(monkeypatch) -> None:
    from mcp_runtime.security_policy import prepare_subprocess_env
    monkeypatch.setenv("OPENAI_API_KEY", "test-real-secret-1234")  # pragma: allowlist secret
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = prepare_subprocess_env(
        server_id="mcp_test",
        user_env={"FIXTURE_KEY": "test-user-supplied-1234"},  # pragma: allowlist secret
    )
    # System PATH passes through allowlist; OPENAI_API_KEY does NOT.
    assert env["PATH"] == "/usr/bin:/bin"
    assert "OPENAI_API_KEY" not in env
    # User-explicit env passes.
    assert env["FIXTURE_KEY"] == "test-user-supplied-1234"  # pragma: allowlist secret
    # Tagged for orchestrator detection.
    assert env["LITERATURE_MCP_SERVER_ID"] == "mcp_test"


def test_redact_env_for_audit_masks_secret_keys() -> None:
    from mcp_runtime.security_policy import redact_env_for_audit
    raw = {
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "test-very-long-secret-1234567890",  # pragma: allowlist secret
        "MY_TOKEN": "test-bearer-1234567890",  # pragma: allowlist secret
        "PUBLIC_VAR": "world",
    }
    out = redact_env_for_audit(raw)
    assert out["PATH"] == "/usr/bin"
    assert out["PUBLIC_VAR"] == "world"
    assert out["OPENAI_API_KEY"] != raw["OPENAI_API_KEY"]
    assert out["MY_TOKEN"] != raw["MY_TOKEN"]


def test_prepare_isolated_cwd_rejects_path_traversal() -> None:
    from mcp_runtime.security_policy import (
        McpSecurityPolicyError,
        prepare_isolated_cwd,
    )
    with pytest.raises(McpSecurityPolicyError):
        prepare_isolated_cwd("../escape")
    with pytest.raises(McpSecurityPolicyError):
        prepare_isolated_cwd("a/b")


def test_capped_stream_buffer_truncates() -> None:
    from mcp_runtime.security_policy import CappedStreamBuffer
    b = CappedStreamBuffer(max_chars=10)
    b.write("hello ")
    b.write("world!!!!")  # would exceed
    rendered = b.render()
    assert b.truncated is True
    assert "truncated" in rendered
    assert len(rendered) > 10  # marker added


# ---------------------------------------------------------------------------
# tool_catalog unit tests
# ---------------------------------------------------------------------------


from types import SimpleNamespace


def _stub_config(server_id: str = "s1"):
    """Minimal duck-typed stand-in for McpServerConfig — tool_catalog only
    reads ``.server_id``.
    """
    return SimpleNamespace(server_id=server_id)


@pytest.mark.asyncio
async def test_catalog_caches_until_invalidated() -> None:
    from mcp_runtime.tool_catalog import McpToolCatalog
    from models.mcp import McpToolCapability, McpToolDescriptor

    call_count = {"n": 0}

    async def fake_list(config):
        call_count["n"] += 1
        return [McpToolDescriptor(name="t", capability=McpToolCapability.UNKNOWN)]

    cat = McpToolCatalog(list_tools_fn=fake_list)
    cfg = _stub_config("s1")
    await cat.get_tools(cfg)
    await cat.get_tools(cfg)
    assert call_count["n"] == 1  # cached
    await cat.get_tools(cfg, refresh=True)
    assert call_count["n"] == 2  # forced refresh
    cat.invalidate("s1")
    await cat.get_tools(cfg)
    assert call_count["n"] == 3  # invalidated -> fetch


@pytest.mark.asyncio
async def test_catalog_fingerprint_changes_when_tools_change() -> None:
    from mcp_runtime.tool_catalog import McpToolCatalog
    from models.mcp import McpToolCapability, McpToolDescriptor

    state = {"i": 0}

    async def fake_list(config):
        state["i"] += 1
        if state["i"] == 1:
            return [McpToolDescriptor(name="alpha", capability=McpToolCapability.UNKNOWN)]
        return [
            McpToolDescriptor(name="alpha", capability=McpToolCapability.UNKNOWN),
            McpToolDescriptor(name="beta", capability=McpToolCapability.UNKNOWN),
        ]

    cat = McpToolCatalog(list_tools_fn=fake_list)
    cfg = _stub_config("s1")
    await cat.get_tools(cfg)
    fp1 = cat.fingerprint("s1")
    await cat.get_tools(cfg, refresh=True)
    fp2 = cat.fingerprint("s1")
    assert fp1 != fp2
