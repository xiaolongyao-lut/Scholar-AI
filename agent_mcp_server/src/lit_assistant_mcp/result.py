"""Safe result wrapper for MCP tool outputs."""

import json
from typing import Any

from .redaction import SecretRedactor

MAX_RESULT_PREVIEW: int = 100 * 1024  # 100KB


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
        # Serialize to JSON
        serialized = json.dumps(data, ensure_ascii=False, indent=2)

        # Redact secrets
        redacted = SecretRedactor.scan(serialized)

        # Limit size
        if len(redacted) > MAX_RESULT_PREVIEW:
            redacted = redacted[:MAX_RESULT_PREVIEW] + "\n... [truncated]"

        # Parse back to structured data
        try:
            result_data = json.loads(redacted) if not redacted.endswith("... [truncated]") else redacted
        except json.JSONDecodeError:
            result_data = redacted

        return {
            "is_error": error,
            "error_code": error_code,
            "message": message,
            "data": result_data,
        }

    except (TypeError, ValueError) as e:
        # Serialization failure
        return {
            "is_error": True,
            "error_code": "serialization_failed",
            "message": f"Failed to serialize result: {e}",
            "data": None,
        }
