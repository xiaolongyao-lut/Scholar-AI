"""MCP tool-result formatter.

Converts the manager's tool-call result (``{"is_error", "content"}``) into
provider-native tool-result messages, plus a generic XML/text fallback.
The formatter never raises on tool-side errors — it embeds them so the
LLM can decide to retry or stop.

Each result block also carries a structured preview record (server_id,
tool_name, tool_call_id, is_error, elapsed_ms, redacted_preview) for the
audit log; the chat router persists those alongside the transcript.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mcp_runtime.security_policy import redact_text_for_audit


PREVIEW_CHAR_LIMIT = 1200
LLM_PAYLOAD_CHAR_LIMIT = 16000
_REF_SUMMARY_LIMIT = 5
STRUCTURED_STRING_CHAR_LIMIT = 1200
_STRUCTURED_METADATA_DENY_KEY_PARTS = (
    "provider_payload",
    "raw_content",
    "llm_payload",
    "authorization",
    "api_key",
    "token",
    "secret",
)


@dataclass
class ToolResultRecord:
    """Audit and provider-facing envelopes for one tool execution.

    Args:
        preview: Redacted, short audit string safe for logs and UI.
        llm_payload: Redacted, bounded payload sent back to the provider.
        llm_payload_chars: Provider-facing payload size after redaction/truncation.
        estimated_tokens: Conservative character-derived token estimate.
        redacted: Whether the provider payload changed during secret redaction.
        unsupported_block_count: Count of non-text MCP blocks summarized by marker.
        source_provenance: Small source identifiers without raw body text.
        budget_class: Coarse budget bucket: refs, body, error, or context_budget_exceeded.
        structured_content: Redacted JSON-safe MCP structured content, local/API state only.
        structured_metadata: Redacted JSON-safe MCP metadata, local/API state only.
        raw_content: Local-only MCP content blocks, never persisted by audit.
    """

    tool_call_id: str
    server_id: str
    server_slug: str
    tool_name: str
    is_error: bool
    elapsed_ms: int
    preview: str
    truncated: bool = False
    llm_payload: str = ""
    llm_payload_truncated: bool = False
    llm_payload_chars: int = 0
    estimated_tokens: int = 0
    redacted: bool = False
    unsupported_block_count: int = 0
    source_provenance: dict[str, Any] = field(default_factory=dict)
    budget_class: str = "body"
    structured_content: dict[str, Any] | None = None
    structured_metadata: dict[str, Any] = field(default_factory=dict)
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


def _unsupported_block_count(content: list[dict[str, Any]]) -> int:
    """Count MCP blocks that cannot be represented as plain provider text."""

    count = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        if "text" in block or "raw" in block:
            continue
        count += 1
    return count


def _estimate_tokens(text: str) -> int:
    """Return a deterministic rough token estimate for local budgeting."""

    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _bounded_structured_scalar(value: Any) -> str | int | float | bool | None:
    """Return a redacted scalar safe for structured state projections."""

    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = redact_text_for_audit(str(value))
    if len(text) > STRUCTURED_STRING_CHAR_LIMIT:
        return f"{text[: STRUCTURED_STRING_CHAR_LIMIT - 1].rstrip()}…"
    return text


def _structured_json_safe(value: Any, *, depth: int = 0) -> Any:
    """Return redacted JSON-safe structured data without provider payload text.

    Why:
        MCP structured content is application state, but it may still contain
        secret-looking strings or non-JSON objects. Normalize before any API
        projection and keep raw provider payloads out of persistent audit.
    """

    if depth > 8:
        return "<max_depth_exceeded>"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = str(_bounded_structured_scalar(key) or "")
            if not safe_key:
                continue
            out[safe_key] = _structured_json_safe(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_structured_json_safe(item, depth=depth + 1) for item in value[:100]]
    return _bounded_structured_scalar(value)


def _extract_structured_content(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Extract first-class MCP structured content from common key spellings."""

    for key in ("structured_content", "structuredContent"):
        value = raw.get(key)
        if isinstance(value, dict):
            safe = _structured_json_safe(value)
            return safe if isinstance(safe, dict) else None
    return None


def _extract_structured_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract MCP envelope metadata without merging it into model text."""

    value = raw.get("_meta")
    if value is None:
        value = raw.get("meta")
    if not isinstance(value, dict):
        return {}
    safe = _structured_json_safe(value)
    if not isinstance(safe, dict):
        return {}
    return {
        key: item
        for key, item in safe.items()
        if not any(part in key.lower() for part in _STRUCTURED_METADATA_DENY_KEY_PARTS)
    }


def _bounded_value(value: Any, *, max_chars: int) -> str | int | float | bool | None:
    """Return a scalar value safe for a compact tool-result summary."""

    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    if len(text) > max_chars:
        return f"{text[: max_chars - 1].rstrip()}…"
    return text


def _compact_ref_item(value: Any) -> dict[str, Any] | None:
    """Project an evidence/search ref to identity fields needed by next calls."""

    if not isinstance(value, dict):
        return None
    allowed_fields = (
        "source_type",
        "ref_id",
        "read_endpoint",
        "chunk_id",
        "material_id",
        "page",
        "summary",
        "lexical_score",
        "rerank_score",
        "source_title",
        "source_path",
        "joint_score",
    )
    compact: dict[str, Any] = {}
    for field_name in allowed_fields:
        if field_name not in value:
            continue
        max_chars = 280 if field_name == "summary" else 240
        bounded = _bounded_value(value.get(field_name), max_chars=max_chars)
        if bounded is not None and bounded != "":
            compact[field_name] = bounded
    return compact or None


def _compact_refs_payload(payload: Any) -> dict[str, Any] | None:
    """Return a compact refs summary for long Literature tool results.

    Why:
        Provider-facing tool-result previews are intentionally bounded, but
        agents must still see ref ids/read endpoints early enough to perform
        follow-up bounded resource reads.
    """

    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    raw_refs = data.get("evidence_refs")
    if not isinstance(raw_refs, list):
        raw_refs = data.get("refs")
    if not isinstance(raw_refs, list) or not raw_refs:
        return None
    refs = [
        compact
        for compact in (_compact_ref_item(item) for item in raw_refs[:_REF_SUMMARY_LIMIT])
        if compact is not None
    ]
    if not refs:
        return None
    summary: dict[str, Any] = {"refs": refs}
    for field_name in (
        "evidence_pack_ref",
        "project_id",
        "query",
        "section_id",
        "retrieval_method",
        "rerank_status",
        "total",
        "truncated",
    ):
        if field_name in data:
            bounded = _bounded_value(data.get(field_name), max_chars=280)
            if bounded is not None and bounded != "":
                summary[field_name] = bounded
    return summary


def _compact_audit_payload(payload: Any) -> dict[str, Any] | None:
    """Return a compact writing-audit provenance summary when available."""

    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    audit = data.get("audit")
    if not isinstance(audit, dict):
        return None
    compact: dict[str, Any] = {}
    for field_name in (
        "invocation_surface",
        "agent_mediated",
        "mcp_tool_calls_used",
        "disclosure_required",
        "agent_host",
        "source",
    ):
        if field_name in audit:
            bounded = _bounded_value(audit.get(field_name), max_chars=160)
            if bounded is not None and bounded != "":
                compact[field_name] = bounded
    for field_name in ("tool_chain", "used_mcp_tools"):
        raw_items = audit.get(field_name)
        if isinstance(raw_items, list):
            items: list[str | int | float | bool] = []
            for item in raw_items[:8]:
                bounded = _bounded_value(item, max_chars=160)
                if bounded is not None and bounded != "":
                    items.append(bounded)
            compact[field_name] = items
    for field_name in ("style_profile", "quality_gate", "score"):
        if field_name in data:
            bounded = _bounded_value(data.get(field_name), max_chars=160)
            if bounded is not None and bounded != "":
                compact[field_name] = bounded
    return compact or None


def _tool_prefers_compact_llm_payload(tool_name: str) -> bool:
    """Return True for tools whose contract is ref identity, not body text.

    Why:
        Search/evidence-pack tools intentionally return refs and summaries so
        agents perform a bounded follow-up read before using source text.
    """

    normalized = str(tool_name or "").strip()
    return normalized.endswith(
        (
            ".search_refs",
            ".evidence_pack_build",
            ".citations_sources",
            ".citations_detect_overlap",
            ".figures_candidates",
        )
    )


def _budget_class_for_tool(*, tool_name: str, is_error: bool) -> str:
    """Classify one tool result for context-budget diagnostics."""

    if is_error:
        return "error"
    if _tool_prefers_compact_llm_payload(tool_name):
        return "refs"
    return "body"


def _source_provenance_from_flat(
    *,
    server_id: str,
    server_slug: str,
    tool_name: str,
    flat: str,
) -> dict[str, Any]:
    """Extract source identifiers from a tool result without copying body text."""

    provenance: dict[str, Any] = {
        "server_id": server_id,
        "server_slug": server_slug,
        "tool_name": tool_name,
    }
    try:
        payload = json.loads(flat)
    except json.JSONDecodeError:
        return provenance
    if not isinstance(payload, dict):
        return provenance
    data = payload.get("data")
    if not isinstance(data, dict):
        data = payload
    for field_name in (
        "project_id",
        "material_id",
        "chunk_id",
        "ref_id",
        "source_type",
        "source_path",
        "path",
        "page",
    ):
        if field_name not in data:
            continue
        bounded = _bounded_value(data.get(field_name), max_chars=240)
        if bounded is not None and bounded != "":
            provenance[field_name] = bounded
    return provenance


def _json_text(value: Any) -> str:
    """Serialize provider-facing JSON without ASCII escaping."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _provider_payload_text(record: ToolResultRecord) -> str:
    """Return model-visible tool-result text without using audit preview.

    Why:
        The preview field is an audit-only projection and can omit, reorder, or
        summarize content in ways that are not a provider tool-result contract.
    """

    if not isinstance(record, ToolResultRecord):
        raise TypeError("record must be a ToolResultRecord")
    if record.llm_payload:
        return record.llm_payload
    return _json_text(
        {
            "tool_result_for_llm": {
                "tool_name": record.tool_name,
                "is_error": record.is_error,
                "provider_payload_empty": True,
                "message": (
                    "Tool execution completed, but no provider-visible payload "
                    "was available for this result."
                ),
            }
        }
    )


def _prepend_compact_tool_summary(flat: str) -> str:
    """Move follow-up-critical fields ahead of the bounded preview."""

    if not flat:
        return flat
    try:
        payload = json.loads(flat)
    except json.JSONDecodeError:
        return flat
    compact: dict[str, Any] = {}
    refs_summary = _compact_refs_payload(payload)
    if refs_summary is not None:
        compact.update(refs_summary)
    audit_summary = _compact_audit_payload(payload)
    if audit_summary is not None:
        compact["audit"] = audit_summary
    if not compact:
        return flat
    compact_text = json.dumps(
        {"compact_tool_result": compact},
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"{compact_text}\n{flat}"


def _build_llm_payload_text(
    *,
    tool_name: str,
    flat: str,
    is_error: bool,
    max_chars: int = LLM_PAYLOAD_CHAR_LIMIT,
) -> tuple[str, bool, bool]:
    """Return the bounded payload that should be visible to the provider.

    Args:
        tool_name: Internal MCP tool name used for contract-specific shaping.
        flat: Flattened tool content text.
        is_error: Whether the tool result represents an error.
        max_chars: Hard character budget for the provider-facing payload.

    Returns:
        A pair of provider-visible text and whether it was truncated.
    """

    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("tool_name must be a non-empty string")
    if not isinstance(flat, str):
        raise ValueError("flat must be a string")
    if not isinstance(is_error, bool):
        raise ValueError("is_error must be a boolean")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 100:
        raise ValueError("max_chars must be an integer >= 100")

    payload_text = flat
    if not is_error and _tool_prefers_compact_llm_payload(tool_name):
        try:
            parsed = json.loads(flat)
        except json.JSONDecodeError:
            parsed = None
        compact: dict[str, Any] = {}
        refs_summary = _compact_refs_payload(parsed)
        if refs_summary is not None:
            compact.update(refs_summary)
        audit_summary = _compact_audit_payload(parsed)
        if audit_summary is not None:
            compact["audit"] = audit_summary
        if compact:
            payload_text = _json_text(
                {
                    "tool_result_for_llm": {
                        "tool_name": tool_name,
                        "is_error": is_error,
                        "result": compact,
                    }
                }
            )

    redacted = redact_text_for_audit(payload_text)
    was_redacted = redacted != payload_text
    if len(redacted) <= max_chars:
        return redacted, False, was_redacted
    marker = "\n...[llm_payload_truncated]"
    return redacted[: max_chars - len(marker)].rstrip() + marker, True, was_redacted


def build_tool_result_record(
    *,
    tool_call_id: str,
    server_id: str,
    server_slug: str,
    tool_name: str,
    raw: dict[str, Any],
    elapsed_ms: int,
) -> ToolResultRecord:
    """Wrap a manager call_tool() result in audit and LLM envelopes."""
    if not isinstance(raw, dict):
        raise ValueError("raw must be a dictionary")
    is_error = bool(raw.get("is_error", False))
    content = raw.get("content") or []
    flat = _flatten_content(content if isinstance(content, list) else [])
    llm_payload, llm_payload_truncated, redacted_for_llm = _build_llm_payload_text(
        tool_name=tool_name,
        flat=flat,
        is_error=is_error,
    )
    audit_flat = _prepend_compact_tool_summary(flat)
    redacted = redact_text_for_audit(audit_flat)
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
        llm_payload=llm_payload,
        llm_payload_truncated=llm_payload_truncated,
        llm_payload_chars=len(llm_payload),
        estimated_tokens=_estimate_tokens(llm_payload),
        redacted=redacted_for_llm,
        unsupported_block_count=_unsupported_block_count(content if isinstance(content, list) else []),
        source_provenance=_source_provenance_from_flat(
            server_id=server_id,
            server_slug=server_slug,
            tool_name=tool_name,
            flat=flat,
        ),
        budget_class=_budget_class_for_tool(tool_name=tool_name, is_error=is_error),
        structured_content=_extract_structured_content(raw),
        structured_metadata=_extract_structured_metadata(raw),
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
        "content": [{"type": "text", "text": _provider_payload_text(record)}],
    }


def format_for_openai(record: ToolResultRecord) -> dict[str, Any]:
    """Produce an OpenAI-compatible `tool` role message."""
    return {
        "role": "tool",
        "tool_call_id": record.tool_call_id,
        "name": record.tool_name,
        "content": _provider_payload_text(record),
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
    escaped = _escape_xml_content(_provider_payload_text(record))
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
    "LLM_PAYLOAD_CHAR_LIMIT",
    "ToolResultRecord",
    "build_tool_result_record",
    "format_for_claude",
    "format_for_openai",
    "format_for_provider",
    "format_generic_xml",
]
