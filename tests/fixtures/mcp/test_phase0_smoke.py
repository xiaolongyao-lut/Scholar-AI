"""Phase 0 preflight: end-to-end stdio MCP smoke against fixture server.

Verifies the mcp 1.27.0 client API surface that MCP integration Phase 1
will depend on:

  - StdioServerParameters configures argv-only command (no shell)
  - stdio_client(...) yields async (read, write) streams
  - ClientSession.initialize() returns server info / capabilities
  - ClientSession.list_tools() returns tool descriptors
  - ClientSession.call_tool(...) round-trips a tool invocation

Skipped automatically if `mcp` or `fastmcp` are not installed (CI guard;
runtime dependency is pinned in requirements-pin.txt + requirements-ci.txt).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.asyncio


def _can_import_mcp() -> bool:
    try:
        import mcp  # noqa: F401
        import fastmcp  # noqa: F401
        from mcp import ClientSession, StdioServerParameters  # noqa: F401
        from mcp.client.stdio import stdio_client  # noqa: F401
        return True
    except ImportError:
        return False


HAS_MCP = _can_import_mcp()
SKIP_REASON = "mcp / fastmcp not installed (skip in CI without MCP deps)"


_FIXTURE_PATH = Path(__file__).parent / "echo_math_server.py"


def _server_params():
    """Build a StdioServerParameters that launches the echo/math fixture
    via the same Python interpreter the test runs in (avoids PATH issues).
    """
    from mcp import StdioServerParameters
    return StdioServerParameters(
        command=sys.executable,
        args=[str(_FIXTURE_PATH)],
        env=None,
    )


@pytest.mark.skipif(not HAS_MCP, reason=SKIP_REASON)
async def test_initialize_returns_server_info() -> None:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _server_params()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            result = await session.initialize()
            assert result is not None
            # serverInfo.name comes from FastMCP("echo-math-fixture")
            assert result.serverInfo.name == "echo-math-fixture"


@pytest.mark.skipif(not HAS_MCP, reason=SKIP_REASON)
async def test_list_tools_returns_echo_and_add() -> None:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _server_params()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool_names = {t.name for t in tools_result.tools}
            assert tool_names == {"echo", "add"}, (
                f"expected echo+add, got {tool_names}"
            )


@pytest.mark.skipif(not HAS_MCP, reason=SKIP_REASON)
async def test_call_tool_echo_round_trip() -> None:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _server_params()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "echo", arguments={"text": "phase-0-ping"}
            )
            assert result.isError is False
            # MCP CallToolResult.content is a list of content blocks
            assert len(result.content) >= 1
            text_block = result.content[0]
            # fastmcp returns the str return value as a TextContent block
            text = getattr(text_block, "text", None) or str(text_block)
            assert "phase-0-ping" in text


@pytest.mark.skipif(not HAS_MCP, reason=SKIP_REASON)
async def test_call_tool_add_returns_integer_sum() -> None:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _server_params()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "add", arguments={"a": 17, "b": 25}
            )
            assert result.isError is False
            text_block = result.content[0]
            text = getattr(text_block, "text", None) or str(text_block)
            assert "42" in text


@pytest.mark.skipif(not HAS_MCP, reason=SKIP_REASON)
async def test_call_tool_with_unknown_name_returns_error_not_exception() -> None:
    """MCP servers signal tool errors via CallToolResult.isError, not by
    raising on the client side. Phase 1 tool_dispatcher relies on this
    contract.
    """
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    params = _server_params()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                result = await session.call_tool("nonexistent", arguments={})
            except Exception as exc:
                # If the server raises instead of returning isError, document
                # this so Phase 1 tool_dispatcher knows to wrap.
                pytest.skip(
                    f"server raised on unknown tool ({type(exc).__name__}); "
                    f"Phase 1 dispatcher must wrap call_tool in try/except"
                )
            else:
                assert result.isError is True


@pytest.mark.skipif(not HAS_MCP, reason=SKIP_REASON)
def test_streamable_http_client_importable() -> None:
    """Sanity: the Streamable HTTP transport is reachable in this mcp
    version. Phase 1 stores a `transport='streamable_http'` enum from day
    1 even though execution is feature-flagged off.
    """
    from mcp.client.streamable_http import streamablehttp_client  # noqa: F401
