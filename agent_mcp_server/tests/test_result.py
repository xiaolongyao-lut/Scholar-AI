"""Tests for safe_result wrapper."""

import json

from lit_assistant_mcp.result import MAX_RESULT_PREVIEW, safe_result


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _openai_key() -> str:
    return "sk-" + "abc123def456ghi789jkl012mno345"


def test_safe_result_success():
    """Test safe_result with successful data."""
    data = {"status": "ok", "count": 42}
    result = safe_result(data)

    assert result["is_error"] is False
    assert result["error_code"] is None
    assert result["data"]["status"] == "ok"


def test_safe_result_with_secret():
    """Test that safe_result redacts secrets."""
    data = {
        "api_key": _openai_key(),
        "message": "Connected successfully",
    }
    result = safe_result(data)

    assert result["is_error"] is False
    result_str = str(result["data"])
    assert "sk-abc123" not in result_str
    assert "[REDACTED:" in result_str


def test_safe_result_size_limit():
    """Test that safe_result limits output size."""
    # Create data larger than 100KB
    large_data = {"content": "x" * 200000}
    result = safe_result(large_data)

    assert result["is_error"] is False
    assert "truncated" in str(result["data"]).lower()
    assert _json_size(result["data"]) <= MAX_RESULT_PREVIEW


def test_safe_result_preserves_structured_data_when_truncated():
    """Large results must keep machine-readable object shape after truncation."""
    large_data = {
        "status": "ok",
        "content": "x" * 200000,
        "refs": [{"ref_id": "chunk:1", "score": 0.98}],
    }
    result = safe_result(large_data)

    assert result["is_error"] is False
    assert result["truncated"] is True
    assert isinstance(result["data"], dict)
    assert result["data"]["status"] == "ok"
    assert result["data"]["refs"] == [{"ref_id": "chunk:1", "score": 0.98}]
    assert result["data"]["content"].endswith("... [truncated]")
    assert _json_size(result["data"]) <= MAX_RESULT_PREVIEW


def test_safe_result_keeps_small_fields_in_wide_truncated_objects():
    """Wide payloads should spend truncation budget only on oversized fields."""
    large_data = {
        **{f"field_{index}": f"value_{index}" for index in range(80)},
        "large_content": "x" * 200000,
    }
    result = safe_result(large_data)

    assert result["is_error"] is False
    assert result["truncated"] is True
    assert result["data"]["field_0"] == "value_0"
    assert result["data"]["field_79"] == "value_79"
    assert result["data"]["large_content"].endswith("... [truncated]")
    assert _json_size(result["data"]) <= MAX_RESULT_PREVIEW


def test_safe_result_preserves_list_shape_when_truncated():
    """Large result arrays must remain arrays with explicit truncation metadata."""
    large_data = [{"index": index, "content": "x" * 50000} for index in range(10)]
    result = safe_result(large_data)

    assert result["is_error"] is False
    assert result["truncated"] is True
    assert isinstance(result["data"], list)
    assert isinstance(result["data"][-1], dict)
    assert result["data"][-1]["_truncated"] is True
    assert _json_size(result["data"]) <= MAX_RESULT_PREVIEW


def test_safe_result_bounds_json_escaped_string_payloads():
    """Escaped JSON characters must not bypass the byte-size truncation limit."""
    result = safe_result({"content": '"' * 200000})

    assert result["is_error"] is False
    assert result["truncated"] is True
    assert isinstance(result["data"], dict)
    assert result["data"]["content"].endswith("... [truncated]")
    assert _json_size(result["data"]) <= MAX_RESULT_PREVIEW


def test_safe_result_error():
    """Test safe_result with error."""
    result = safe_result(
        data=None,
        error=True,
        error_code="backend_unavailable",
        message="Backend is down",
    )

    assert result["is_error"] is True
    assert result["error_code"] == "backend_unavailable"
    assert result["message"] == "Backend is down"


def test_safe_result_serialization_failure():
    """Test safe_result with non-serializable data."""
    class NonSerializable:
        pass

    result = safe_result(NonSerializable())

    assert result["is_error"] is True
    assert result["error_code"] == "serialization_failed"
