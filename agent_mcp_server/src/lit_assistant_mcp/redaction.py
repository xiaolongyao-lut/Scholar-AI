"""Sensitive information redaction for multi-provider API keys and secrets."""

import re
from typing import Final

# Redaction patterns (ordered by specificity)
PATTERNS: Final[list[tuple[str, re.Pattern[str]]]] = [
    # OpenAI
    ("OPENAI_KEY", re.compile(r'sk-[a-zA-Z0-9]{20,}', re.IGNORECASE)),

    # Anthropic
    ("ANTHROPIC_KEY", re.compile(r'sk-ant-api[a-zA-Z0-9-]{50,}', re.IGNORECASE)),

    # JWT tokens
    ("JWT", re.compile(r'eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]*', re.IGNORECASE)),

    # Bearer tokens (40-80 chars)
    ("BEARER_TOKEN", re.compile(r'Bearer\s+[A-Za-z0-9_-]{40,80}', re.IGNORECASE)),

    # Basic auth
    ("BASIC_AUTH", re.compile(r'Basic\s+[A-Za-z0-9+/=]{20,}', re.IGNORECASE)),

    # Authorization headers
    ("AUTH_HEADER", re.compile(r'Authorization:\s*(?:Bearer|Basic)\s+\S+', re.IGNORECASE)),

    # Context-aware 32-char hex (China LLM platforms: DashScope/Tongyi, Azure, etc.)
    # Only redact when preceded by credential-like context
    ("CONTEXTUAL_HEX_KEY", re.compile(
        r'(?:api_key|apikey|token|secret|secret_key|password|passwd|dashscope|tongyi|qwen|zhipu|glm|baidu|wenxin|azure)'
        r'\s*[=:]\s*["\']?([a-f0-9]{32,64})["\']?',
        re.IGNORECASE
    )),

    # Assignment patterns (must come after more specific patterns)
    ("API_KEY_ASSIGN", re.compile(
        r'(?:api_key|apikey|token|secret|secret_key|password|passwd)\s*[=:]\s*["\']([^"\']{16,})["\']',
        re.IGNORECASE
    )),

    # URL-encoded secrets (lookahead for credential keys)
    ("URL_ENCODED_SECRET", re.compile(
        r'(?:api_key|token|secret|password)=[A-Za-z0-9%+_-]{20,}',
        re.IGNORECASE
    )),

    # Long base64-like strings in credential context
    ("BASE64_SECRET", re.compile(
        r'(?:api_key|token|secret|password|authorization)\s*[=:]\s*["\']?([A-Za-z0-9+/=]{40,})["\']?',
        re.IGNORECASE
    )),
]


class SecretRedactor:
    """Redact sensitive information from text."""

    @staticmethod
    def scan(text: str) -> str:
        """Scan and redact secrets from text.

        Args:
            text: Input text potentially containing secrets

        Returns:
            Text with secrets replaced by [REDACTED:<TYPE>]
        """
        if not text:
            return text

        result = text
        for label, pattern in PATTERNS:
            result = pattern.sub(f"[REDACTED:{label}]", result)

        return result

    @staticmethod
    def has_secrets(text: str) -> bool:
        """Check if text contains detectable secrets."""
        if not text:
            return False

        for _, pattern in PATTERNS:
            if pattern.search(text):
                return True
        return False
