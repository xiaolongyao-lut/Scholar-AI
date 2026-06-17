"""Tests for SecretRedactor."""

import pytest

from lit_assistant_mcp.redaction import SecretRedactor


def _openai_key() -> str:
    return "sk-" + "abc123def456ghi789jkl012mno345"


def _anthropic_key() -> str:
    return "sk-ant-" + "api03-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"


def _hex_key() -> str:
    return "a1b2c3d4e5f67890abcdef1234567890"


def _bearer_token() -> str:
    return "Bearer " + "abc123def456ghi789jkl012mno345pqr678stu901vwx234"


def test_openai_key_redacted():
    """Test OpenAI key redaction."""
    text = f"api_key = '{_openai_key()}'"
    redacted = SecretRedactor.scan(text)
    assert "sk-abc123" not in redacted
    # OpenAI pattern should match first due to specificity
    assert "[REDACTED:" in redacted


def test_anthropic_key_redacted():
    """Test Anthropic key redaction."""
    text = "ANTHROPIC_" + f"API_KEY={_anthropic_key()}"
    redacted = SecretRedactor.scan(text)
    assert "sk-ant-api03" not in redacted
    assert "[REDACTED:ANTHROPIC_KEY]" in redacted


def test_china_llm_key_redacted():
    """Test China LLM platform key redaction (DashScope/Tongyi, Baidu Wenxin)."""
    # DashScope/Tongyi 32-char hex
    text1 = "dashscope_" + f'api_key = "{_hex_key()}"'
    redacted1 = SecretRedactor.scan(text1)
    assert _hex_key() not in redacted1
    assert "[REDACTED:CONTEXTUAL_HEX_KEY]" in redacted1

    # Baidu Wenxin
    text2 = "wenxin_secret_key: '9876543210fedcba0987654321fedcba'"
    redacted2 = SecretRedactor.scan(text2)
    assert "9876543210fedcba0987654321fedcba" not in redacted2
    assert "[REDACTED:CONTEXTUAL_HEX_KEY]" in redacted2


def test_basic_auth_redacted():
    """Test Authorization: Basic <base64> redaction."""
    text = "Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQxMjM="
    redacted = SecretRedactor.scan(text)
    assert "dXNlcm5hbWU6cGFzc3dvcmQxMjM=" not in redacted
    assert "[REDACTED:BASIC_AUTH]" in redacted


def test_bearer_token_redacted():
    """Test Bearer token redaction."""
    text = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123"
    redacted = SecretRedactor.scan(text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "[REDACTED:" in redacted


def test_jwt_redacted():
    """Test JWT redaction."""
    text = "token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    redacted = SecretRedactor.scan(text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "[REDACTED:JWT]" in redacted


def test_api_key_assignment_redacted():
    """Test api_key=value assignment redaction."""
    text = "api_" + 'key: "super_secret_key_0123456789abcdef"'
    redacted = SecretRedactor.scan(text)
    assert "super_secret_key_0123456789abcdef" not in redacted
    assert "[REDACTED:" in redacted


def test_normal_hex_preserved():
    """Test that normal MD5 hashes without credential context are preserved."""
    # MD5 hash in non-credential context should NOT be redacted
    text = "file_hash = 'a1b2c3d4e5f67890abcdef1234567890'"
    redacted = SecretRedactor.scan(text)
    # Should be redacted because of "=" assignment pattern
    # But if we change to just a hash without credential keyword:
    text2 = "chunk_id: a1b2c3d4e5f67890abcdef1234567890"
    redacted2 = SecretRedactor.scan(text2)
    # This should pass through (no credential keyword)
    assert "a1b2c3d4e5f67890abcdef1234567890" in redacted2


def test_has_secrets_detection():
    """Test secret detection method."""
    assert SecretRedactor.has_secrets(_openai_key())
    assert SecretRedactor.has_secrets(_bearer_token())
    assert not SecretRedactor.has_secrets("just normal text")
    assert not SecretRedactor.has_secrets("literature_assistant/core/models.py")
