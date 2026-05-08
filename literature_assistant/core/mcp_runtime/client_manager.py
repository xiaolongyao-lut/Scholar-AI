"""MCP client lifecycle manager (Phase 1B / TASK-104).

Per-operation session lifecycle. Each ``list_tools`` / ``call_tool``
opens a fresh stdio (or streamable_http) session, performs the operation,
and closes the session inside the SAME asyncio task. This avoids the
anyio "exit cancel scope in a different task" error that appears when
the mcp SDK's AsyncExitStack is held across HTTP request boundaries.

Phase 2 tool-use loop may add an in-request session pool (open once per
tool-call round, reuse for the bounded loop) but cross-request pooling
is **out of scope for v1** (plan v0.3 §4.4 / §11).

Streamable HTTP transport persists in the store from day 1 but execution
is gated behind ``LITERATURE_ENABLE_MCP_STREAMABLE_HTTP=1``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator

from models.mcp import McpServerConfig, McpToolDescriptor, McpTransport
from mcp_runtime.security_policy import (
    DEFAULT_LAUNCH_POLICY,
    ProcessLaunchPolicy,
    prepare_isolated_cwd,
    prepare_subprocess_env,
    validate_stdio_command,
)


logger = logging.getLogger("McpClientManager")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class McpClientManagerError(RuntimeError):
    pass


class McpStreamableHttpDisabledError(McpClientManagerError):
    """Raised when caller tries to launch streamable_http while feature flag
    is off (plan v0.3 §4.4)."""


class McpServerLaunchError(McpClientManagerError):
    pass


class McpToolCallError(McpClientManagerError):
    pass


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class McpClientManager:
    """Per-operation MCP session manager.

    Stateless across operations; each call opens and closes a session.
    Caching of tool descriptors lives in ``mcp_runtime.tool_catalog`` and
    persistence lives in ``mcp_runtime.server_store`` — this module is
    just a thin wrapper around the mcp SDK to enforce timeouts and
    per-server config plumbing.
    """

    def __init__(
        self,
        *,
        launch_policy: ProcessLaunchPolicy | None = None,
    ) -> None:
        self._policy = launch_policy or DEFAULT_LAUNCH_POLICY

    @staticmethod
    def _streamable_http_enabled() -> bool:
        return os.environ.get(
            "LITERATURE_ENABLE_MCP_STREAMABLE_HTTP", ""
        ).strip().lower() in {"1", "true", "yes", "on"}

    # ------------------------------------------------------------------ open

    @asynccontextmanager
    async def _session_for(
        self, config: McpServerConfig
    ) -> AsyncIterator[Any]:
        """Open a single MCP session for one operation. Yields a
        ``mcp.ClientSession`` already initialized; closes everything on exit.
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if config.transport == McpTransport.STREAMABLE_HTTP:
            if not self._streamable_http_enabled():
                raise McpStreamableHttpDisabledError(
                    "Streamable HTTP execution disabled "
                    "(set LITERATURE_ENABLE_MCP_STREAMABLE_HTTP=1)"
                )
            async with self._open_streamable_http_session(config) as session:
                yield session
            return

        if config.stdio is None:
            raise McpServerLaunchError(
                f"server {config.server_id}: stdio block is None"
            )
        validate_stdio_command(config.stdio)
        cwd = prepare_isolated_cwd(config.server_id)
        env = prepare_subprocess_env(
            server_id=config.server_id,
            user_env=dict(config.stdio.env),
        )
        params = StdioServerParameters(
            command=config.stdio.command,
            args=list(config.stdio.args),
            env=env,
            cwd=str(cwd),
        )

        async with AsyncExitStack() as stack:
            try:
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(
                    ClientSession(read, write)
                )
                await asyncio.wait_for(
                    session.initialize(),
                    timeout=self._policy.startup_timeout_seconds,
                )
            except McpStreamableHttpDisabledError:
                raise
            except Exception as exc:
                raise McpServerLaunchError(
                    f"server {config.server_id} stdio launch failed: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            yield session

    @asynccontextmanager
    async def _open_streamable_http_session(
        self, config: McpServerConfig
    ) -> AsyncIterator[Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        if config.http is None:
            raise McpServerLaunchError(
                f"server {config.server_id}: http block is None"
            )
        async with AsyncExitStack() as stack:
            try:
                read, write, _meta = await stack.enter_async_context(
                    streamablehttp_client(
                        config.http.url, headers=dict(config.http.headers)
                    )
                )
                session = await stack.enter_async_context(
                    ClientSession(read, write)
                )
                await asyncio.wait_for(
                    session.initialize(),
                    timeout=self._policy.startup_timeout_seconds,
                )
            except Exception as exc:
                raise McpServerLaunchError(
                    f"server {config.server_id} streamable_http launch failed: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            yield session

    # -------------------------------------------------------------- queries

    async def list_tools(
        self, config: McpServerConfig
    ) -> list[McpToolDescriptor]:
        """Open a session, list tools, close session."""
        from models.mcp import McpToolCapability

        async with self._session_for(config) as session:
            result = await asyncio.wait_for(
                session.list_tools(),
                timeout=self._policy.startup_timeout_seconds,
            )
            out: list[McpToolDescriptor] = []
            for tool in result.tools:
                schema = getattr(tool, "inputSchema", {}) or {}
                out.append(
                    McpToolDescriptor(
                        name=tool.name,
                        description=getattr(tool, "description", "") or "",
                        input_schema=schema if isinstance(schema, dict) else {},
                        capability=McpToolCapability.UNKNOWN,
                    )
                )
            return out

    async def call_tool(
        self,
        config: McpServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Open a session, invoke a tool, close session.

        Returns ``{"is_error": bool, "content": [...]}`` — provider-native
        formatting happens in Phase 2 ``tool_result_formatter``.
        """
        async with self._session_for(config) as session:
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=arguments),
                    timeout=self._policy.per_call_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise McpToolCallError(
                    f"tool {tool_name!r} on server {config.server_id} timed "
                    f"out after {self._policy.per_call_timeout_seconds}s"
                ) from exc
            except Exception as exc:
                raise McpToolCallError(
                    f"tool {tool_name!r} on server {config.server_id} "
                    f"raised: {type(exc).__name__}"
                ) from exc

            content_parts: list[dict[str, Any]] = []
            for block in result.content:
                block_type = getattr(block, "type", "text")
                if hasattr(block, "text"):
                    content_parts.append({"type": block_type, "text": block.text})
                else:
                    content_parts.append({"type": block_type, "raw": str(block)})
            return {
                "is_error": bool(getattr(result, "isError", False)),
                "content": content_parts,
            }

    async def health(self, config: McpServerConfig) -> bool:
        """Cheap liveness probe: try a list_tools round-trip. Returns
        False on any exception (caller may then choose to retry).
        """
        try:
            await self.list_tools(config)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Module-level singleton (FastAPI registration uses this)
# ---------------------------------------------------------------------------


_singleton: McpClientManager | None = None


def get_mcp_client_manager() -> McpClientManager:
    global _singleton
    if _singleton is None:
        _singleton = McpClientManager()
    return _singleton


def set_mcp_client_manager(manager: McpClientManager | None) -> None:
    """Test hook: inject a custom manager or reset to default."""
    global _singleton
    _singleton = manager


__all__ = [
    "McpClientManager",
    "McpClientManagerError",
    "McpServerLaunchError",
    "McpStreamableHttpDisabledError",
    "McpToolCallError",
    "get_mcp_client_manager",
    "set_mcp_client_manager",
]
