"""Provider tool-schema adapter (Phase 2 / TASK-201).

Converts cached ``McpToolDescriptor`` lists into the schema that each LLM
provider expects on the request side, and parses the namespaced tool name
back into ``(server_id, tool_name)`` on the response side.

Namespace convention: ``mcp__{server_slug}__{tool_name}``. Slug → server_id
mapping is provided by the caller (the runner already has the server config
list when it builds tools).

Provider keys mirror ``chat_router._provider_key`` ("claude" vs anything
else → OpenAI-compatible). "Generic-disabled" means the provider does not
support tool-use natively (no schema emitted; the runner short-circuits).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from models.mcp import McpServerConfig, McpToolDescriptor


NAMESPACE_PREFIX = "mcp__"
NAMESPACE_SEP = "__"


def namespace_tool_name(server_slug: str, tool_name: str) -> str:
    return f"{NAMESPACE_PREFIX}{server_slug}{NAMESPACE_SEP}{tool_name}"


@dataclass(frozen=True)
class NamespacedTool:
    server_id: str
    server_slug: str
    tool_name: str


class ToolNamespaceError(ValueError):
    """Raised when a namespaced tool name cannot be resolved to a server."""


def parse_namespaced_tool(
    namespaced_name: str,
    *,
    slug_to_server_id: dict[str, str],
) -> NamespacedTool:
    """Reverse-lookup a ``mcp__{slug}__{tool}`` name. Raises if the prefix
    is missing or the slug is unknown.
    """
    if not namespaced_name.startswith(NAMESPACE_PREFIX):
        raise ToolNamespaceError(
            f"tool name {namespaced_name!r} missing {NAMESPACE_PREFIX!r} prefix"
        )
    rest = namespaced_name[len(NAMESPACE_PREFIX):]
    sep_idx = rest.find(NAMESPACE_SEP)
    if sep_idx <= 0 or sep_idx >= len(rest) - len(NAMESPACE_SEP):
        raise ToolNamespaceError(
            f"tool name {namespaced_name!r} not in mcp__<slug>__<tool> form"
        )
    slug = rest[:sep_idx]
    tool = rest[sep_idx + len(NAMESPACE_SEP):]
    server_id = slug_to_server_id.get(slug)
    if server_id is None:
        raise ToolNamespaceError(f"unknown server_slug {slug!r}")
    return NamespacedTool(server_id=server_id, server_slug=slug, tool_name=tool)


def _provider_key(provider: str) -> str:
    """Mirror chat_router._provider_key minimal subset."""
    p = (provider or "").strip().lower()
    if p in {"claude", "anthropic"}:
        return "claude"
    return "openai"


def _claude_schema(slug: str, tool: McpToolDescriptor) -> dict[str, Any]:
    schema = tool.input_schema or {"type": "object", "properties": {}}
    return {
        "name": namespace_tool_name(slug, tool.name),
        "description": tool.description or "",
        "input_schema": schema,
    }


def _openai_schema(slug: str, tool: McpToolDescriptor) -> dict[str, Any]:
    parameters = tool.input_schema or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": namespace_tool_name(slug, tool.name),
            "description": tool.description or "",
            "parameters": parameters,
        },
    }


def build_provider_tools(
    provider: str,
    catalog: list[tuple[McpServerConfig, list[McpToolDescriptor]]],
) -> list[dict[str, Any]]:
    """Flatten a multi-server catalog into one provider-native ``tools`` array.

    Args:
      provider: caller-side provider string (e.g. "Claude", "OpenAI").
      catalog: ordered list of (server_config, tool_list) — the runner builds
        this from the cached tool catalog after gating on approval state.

    Returns:
      A list ready to drop into ``payload["tools"]``. Empty list if the
      provider has no native tool-use schema (caller should skip the loop).
    """
    key = _provider_key(provider)
    out: list[dict[str, Any]] = []
    for cfg, tools in catalog:
        slug = cfg.server_slug
        for t in tools:
            if key == "claude":
                out.append(_claude_schema(slug, t))
            else:
                out.append(_openai_schema(slug, t))
    return out


def build_slug_to_server_id(
    catalog: list[tuple[McpServerConfig, list[McpToolDescriptor]]],
) -> dict[str, str]:
    """Helper for the runner: build the reverse-lookup map once per call."""
    return {cfg.server_slug: cfg.server_id for cfg, _ in catalog}


__all__ = [
    "NAMESPACE_PREFIX",
    "NAMESPACE_SEP",
    "NamespacedTool",
    "ToolNamespaceError",
    "build_provider_tools",
    "build_slug_to_server_id",
    "namespace_tool_name",
    "parse_namespaced_tool",
]
