"""Safe result wrapper for MCP tool outputs."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .redaction import SecretRedactor

MAX_RESULT_PREVIEW: int = 100 * 1024  # 100KB
TRUNCATION_SUFFIX: str = "... [truncated]"


def _json_size(value: Any) -> int:
    """Return UTF-8 JSON byte size for JSON-serializable values."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _truncate_text(value: str, max_bytes: int) -> str:
    """Return text that fits a byte budget while preserving valid UTF-8."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if _json_size(value) <= max_bytes:
        return value
    if _json_size(TRUNCATION_SUFFIX) > max_bytes:
        return "" if _json_size("") <= max_bytes else TRUNCATION_SUFFIX

    low = 0
    high = len(value)
    best = TRUNCATION_SUFFIX
    while low <= high:
        midpoint = (low + high) // 2
        candidate = value[:midpoint] + TRUNCATION_SUFFIX
        if _json_size(candidate) <= max_bytes:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best


def _redact_json_value(value: Any) -> Any:
    """Redact secrets without changing JSON-compatible container shapes."""
    if isinstance(value, str):
        return SecretRedactor.scan(value)
    if isinstance(value, Mapping):
        return {str(key): _redact_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_json_value(item) for item in value]
    return value


def _compact_json_value(value: Any, max_bytes: int) -> tuple[Any, bool]:
    """Bound oversized JSON-compatible values while preserving container types."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    if _json_size(value) <= max_bytes:
        return value, False

    if isinstance(value, str):
        return _truncate_text(value, max_bytes), True

    if isinstance(value, Mapping):
        compacted: dict[str, Any] = {}
        truncated = False
        reserved = _json_size({"truncated": True, "omitted_keys": []}) + 32
        for key, item in value.items():
            key_text = str(key)
            candidate = {**compacted, key_text: item}
            if _json_size(candidate) <= max_bytes:
                compacted[key_text] = item
                continue
            remaining_keys = max(len(value) - len(compacted), 1)
            used_bytes = _json_size(compacted)
            remaining_budget = max(max_bytes - used_bytes - reserved, 256)
            item_budget = max(256, remaining_budget // remaining_keys)
            compacted_item, item_truncated = _compact_json_value(item, item_budget)
            candidate = {**compacted, key_text: compacted_item}
            if _json_size(candidate) > max_bytes:
                truncated = True
                continue
            compacted[key_text] = compacted_item
            truncated = truncated or item_truncated
        if truncated or len(compacted) < len(value):
            compacted.setdefault("_truncated", True)
            omitted = [str(key) for key in value.keys() if str(key) not in compacted]
            if omitted:
                compacted["_omitted_keys"] = omitted[:50]
            while _json_size(compacted) > max_bytes and "_omitted_keys" in compacted:
                omitted_keys = compacted["_omitted_keys"]
                if isinstance(omitted_keys, list) and len(omitted_keys) > 1:
                    compacted["_omitted_keys"] = omitted_keys[: max(1, len(omitted_keys) // 2)]
                else:
                    del compacted["_omitted_keys"]
            while _json_size(compacted) > max_bytes:
                removable_keys = [key for key in compacted if not key.startswith("_")]
                if not removable_keys:
                    return {"_truncated": True}, True
                del compacted[removable_keys[-1]]
        return compacted, True

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        compacted_list: list[Any] = []
        truncated = False
        per_item_budget = max(256, max_bytes // max(len(value), 1))
        for item in value:
            compacted_item, item_truncated = _compact_json_value(item, per_item_budget)
            candidate = [*compacted_list, compacted_item]
            if _json_size(candidate) > max_bytes:
                truncated = True
                break
            compacted_list.append(compacted_item)
            truncated = truncated or item_truncated
        if truncated or len(compacted_list) < len(value):
            compacted_list.append(
                {
                    "_truncated": True,
                    "omitted_items": max(len(value) - len(compacted_list), 0),
                }
            )
            while _json_size(compacted_list) > max_bytes and len(compacted_list) > 1:
                marker = compacted_list[-1]
                compacted_list.pop(-2)
                if isinstance(marker, dict):
                    marker["omitted_items"] = int(marker.get("omitted_items", 0)) + 1
            if _json_size(compacted_list) > max_bytes:
                return [{"_truncated": True}], True
        return compacted_list, True

    return value, True


def safe_result(
    data: Any,
    error: bool = False,
    error_code: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Wrap tool output with safety checks.

    Args:
        data: Tool output (must be JSON-serializable)
        error: Whether this is an error result
        error_code: Optional error code
        message: Optional human-readable message

    Returns:
        Safe, redacted, size-limited result dict
    """
    try:
        json.dumps(data, ensure_ascii=False)
        redacted_data = _redact_json_value(data)
        original_size = _json_size(redacted_data)
        result_data, truncated = _compact_json_value(redacted_data, MAX_RESULT_PREVIEW)

        result = {
            "is_error": error,
            "error_code": error_code,
            "message": message,
            "data": result_data,
            "truncated": truncated,
        }
        if truncated:
            result["truncation"] = {
                "limit_bytes": MAX_RESULT_PREVIEW,
                "original_bytes": original_size,
            }
        return result

    except (TypeError, ValueError) as e:
        # Serialization failure
        return {
            "is_error": True,
            "error_code": "serialization_failed",
            "message": f"Failed to serialize result: {e}",
            "data": None,
            "truncated": False,
        }
