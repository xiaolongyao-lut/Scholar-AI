"""Tests for safe_result wrapper."""

import pytest

from lit_assistant_mcp.result import safe_result


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
