"""MCP tool-result formatter (Phase 2 / TASK-202).

Converts the manager's tool-call result (``{"is_error", "content"}``) into
provider-native tool-result messages, plus a generic XML/text fallback.
The formatter never raises on tool-side errors — it embeds them so the
LLM can decide to retry or stop.

Each result block also carries a structured preview record (server_id,
tool_name, tool_call_id, is_error, elapsed_ms, redacted_preview) for the
audit log; the chat router persists those alongside the transcript.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp_runtime.security_policy import redact_text_for_audit


PREVIEW_CHAR_LIMIT = 1200


@dataclass
class ToolResultRecord:
    """Audit-friendly summary of one tool execution."""

    tool_call_id: str
    server_id: str
    server_slug: str
    tool_name: str
    is_error: bool
    elapsed_ms: int
    preview: str
    truncated: bool = False
    raw_content: list[dict[str, Any]] = field(default_factory=list)


def _flatten_content(content: list[dict[str, Any]]) -> str:
    """Collapse MCP content blocks into plain text for the LLM payload."""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        if "text" in block:
            parts.append(str(block["text"]))
        elif "raw" in block:
            parts.append(str(block["raw"]))
        else:
            # Best-effort: keep type marker.
            parts.append(f"<{block.get('type', 'block')}>")
    return "\n".join(p for p in parts if p)


def build_tool_result_record(
    *,
    tool_call_id: str,
    server_id: str,
    server_slug: str,
    tool_name: str,
    raw: dict[str, Any],
    elapsed_ms: int,
) -> ToolResultRecord:
    """Wrap a manager call_tool() result in a record + redacted preview."""
    is_error = bool(raw.get("is_error", False))
    content = raw.get("content") or []
    flat = _flatten_content(content if isinstance(content, list) else [])
    redacted = redact_text_for_audit(flat)
    truncated = False
    if len(redacted) > PREVIEW_CHAR_LIMIT:
        redacted = redacted[:PREVIEW_CHAR_LIMIT] + "...[truncated]"
        truncated = True
    return ToolResultRecord(
        tool_call_id=tool_call_id,
        server_id=server_id,
        server_slug=server_slug,
        tool_name=tool_name,
        is_error=is_error,
        elapsed_ms=elapsed_ms,
        preview=redacted,
        truncated=truncated,
        raw_content=content if isinstance(content, list) else [],
    )


def format_for_claude(record: ToolResultRecord) -> dict[str, Any]:
    """Produce a Claude `tool_result` content block (wrapped in a `user`
    role message at the runner layer).
    """
    return {
        "type": "tool_result",
        "tool_use_id": record.tool_call_id,
        "is_error": record.is_error,
        "content": [{"type": "text", "text": record.preview}],
    }


def format_for_openai(record: ToolResultRecord) -> dict[str, Any]:
    """Produce an OpenAI-compatible `tool` role message."""
    return {
        "role": "tool",
        "tool_call_id": record.tool_call_id,
        "name": record.tool_name,
        "content": record.preview,
    }


def _escape_xml_content(text: str) -> str:
    """Escape characters that could break the tool_result XML envelope."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_generic_xml(record: ToolResultRecord) -> str:
    """Fallback for providers without a tool-result role. Wraps the
    preview in a fenced block annotated with metadata.

    Content is XML-escaped to prevent a malicious tool from injecting
    closing tags or fake XML structure into the LLM context.
    """
    err_tag = "true" if record.is_error else "false"
    escaped = _escape_xml_content(record.preview)
    return (
        f"<tool_result tool=\"{record.tool_name}\" "
        f"server=\"{record.server_slug}\" "
        f"call_id=\"{record.tool_call_id}\" "
        f"is_error=\"{err_tag}\" elapsed_ms=\"{record.elapsed_ms}\" "
        f"source=\"untrusted_mcp_output\">\n"
        f"{escaped}\n"
        f"</tool_result>"
    )


def format_for_provider(provider_key: str, record: ToolResultRecord) -> Any:
    """Dispatch helper. ``provider_key`` is the chat_router-style key
    ("claude" vs "openai"). Other providers fall back to XML.
    """
    if provider_key == "claude":
        return format_for_claude(record)
    if provider_key == "openai":
        return format_for_openai(record)
    return format_generic_xml(record)


__all__ = [
    "PREVIEW_CHAR_LIMIT",
    "ToolResultRecord",
    "build_tool_result_record",
    "format_for_claude",
    "format_for_openai",
    "format_for_provider",
    "format_generic_xml",
]
