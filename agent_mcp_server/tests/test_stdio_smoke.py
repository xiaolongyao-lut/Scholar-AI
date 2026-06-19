"""Stdio MCP handshake smoke test through the distribution wrapper."""

import asyncio
import os
import platform
import socket
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "agent_mcp_server" / "bin" / "lit-assistant-mcp.ps1"


def _unused_loopback_url() -> str:
    """Return a currently unused loopback URL for unreachable-backend assertions."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


def test_stdio_wrapper_initialize_list_and_call() -> None:
    """Wrapper must serve MCP over stdio without protocol noise."""
    if platform.system() != "Windows":
        return

    async def run_smoke() -> None:
        env = os.environ.copy()
        env["LITERATURE_ASSISTANT_REPO_ROOT"] = str(REPO_ROOT)
        env["LITERATURE_ASSISTANT_BASE_URL"] = _unused_loopback_url()
        env["LITASSIST_MCP_SKIP_BACKEND_AUTOSTART"] = "1"
        server_params = StdioServerParameters(
            command="powershell",
            args=[
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(WRAPPER),
            ],
            cwd=REPO_ROOT,
            env=env,
        )
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                result = await session.call_tool("literature.config_status", {})
                workflow_result = await session.call_tool(
                    "workflow.run_json_workflow",
                    {
                        "workflow": {
                            "id": "stdio-artifact-smoke",
                            "steps": [
                                {
                                    "id": "write",
                                    "tool": "artifact.write_markdown",
                                    "args": {
                                        "path": "smoke/stdio-artifact.md",
                                        "content": "stdio artifact smoke",
                                        "overwrite": True,
                                    },
                                }
                            ],
                        }
                    },
                )

        assert initialized.serverInfo.name == "literature-assistant"
        assert "source.list_tree" in tool_names
        assert "source.inspect_routes" in tool_names
        assert "literature.config_status" in tool_names
        assert "literature.agent_request_create" in tool_names
        assert "workflow.run_json_workflow" in tool_names
        assert "artifact.write_markdown" in tool_names
        assert result.structuredContent is not None
        assert result.structuredContent["is_error"] is True
        assert result.structuredContent["error_code"] in {
            "backend_unavailable",
            "backend_timeout",
            "backend_bad_response",
            "backend_unknown_error",
        }
        assert workflow_result.structuredContent is not None
        assert workflow_result.structuredContent["is_error"] is False

    asyncio.run(run_smoke())
