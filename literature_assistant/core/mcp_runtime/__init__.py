"""MCP integration subsystem.

Renamed from `core.mcp` to `core.mcp_runtime` so the package does not
shadow the third-party `mcp` SDK at import time. Product MCP work
imports from `mcp_runtime.*` (local) and `mcp.*` (SDK).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from literature_assistant.core.mcp_runtime.accessors import (
        get_enabled_server,
        has_enabled_server,
    )
else:
    from mcp_runtime.accessors import get_enabled_server, has_enabled_server

__all__ = ["get_enabled_server", "has_enabled_server"]
