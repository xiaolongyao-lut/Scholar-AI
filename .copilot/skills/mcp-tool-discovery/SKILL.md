---
name: "mcp-tool-discovery"
description: "Use available MCP tools when present, fall back gracefully when absent"
domain: "tooling"
confidence: "medium"
source: "my-project bootstrap"
---

## Context

Use this skill when a task can benefit from external tools exposed through MCP, such as GitHub, Azure, Trello, or other workspace-configured services.

## Patterns

### Detect first

At task start, inspect available tools for known MCP prefixes or service-specific tool names.

### Prefer capability, not dependency

- If the MCP tool exists, use it when it improves the task.
- If it does not exist, do not block the task.
- Fall back to local files, CLI tools, or a user-facing note when necessary.

### Keep tool usage explicit

When you do use MCP, mention what capability you are relying on in your working notes or result summary.

## Anti-Patterns

- Assuming MCP is always configured
- Failing the whole task because an MCP server is missing
- Hiding a hard dependency on an unavailable external tool