"""MCP integration subsystem.

Renamed from `core.mcp` to `core.mcp_runtime` so the package does not
shadow the third-party `mcp` SDK at import time. All Phase 1+ MCP work
imports from `mcp_runtime.*` (local) and `mcp.*` (SDK).
"""
