"""Echo/math stdio MCP server fixture for Phase 0 preflight (TASK-002).

Minimal MCP server using fastmcp; exposes two tools:
  - echo(text: str) -> str
  - add(a: int, b: int) -> int

Used by tests/fixtures/mcp/test_phase0_smoke.py to exercise the
mcp 1.27.0 stdio client API surface (initialize -> list_tools -> call_tool)
on Python 3.13. Not used in production runtime.

Invocation: ``python -m tests.fixtures.mcp.echo_math_server`` or directly
``python tests/fixtures/mcp/echo_math_server.py``.
"""

from __future__ import annotations

from fastmcp import FastMCP


mcp = FastMCP("echo-math-fixture")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the input text back unchanged."""
    return text


@mcp.tool()
def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


if __name__ == "__main__":
    mcp.run(transport="stdio")
