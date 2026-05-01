from __future__ import annotations

import os
from typing import Any

from token_utils import count_tokens

DEFAULT_CHUNK_HARD_MAX_CHARS = 5000
DEFAULT_CHUNK_HARD_MAX_TOKENS = 1200


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def hard_max_chars() -> int:
    return max(1, _env_int("CHUNK_HARD_MAX_CHARS", DEFAULT_CHUNK_HARD_MAX_CHARS))


def hard_max_tokens() -> int:
    return max(1, _env_int("CHUNK_HARD_MAX_TOKENS", DEFAULT_CHUNK_HARD_MAX_TOKENS))


def extract_chunk_text(chunk: dict[str, Any]) -> str:
    return str(
        chunk.get("raw_content")
        or chunk.get("content")
        or chunk.get("claim")
        or chunk.get("text")
        or chunk.get("source_text")
        or ""
    )


def inspect_text(text: str) -> dict[str, Any]:
    value = str(text or "")
    char_count = len(value)
    token_count = count_tokens(value)
    max_chars = hard_max_chars()
    max_tokens = hard_max_tokens()
    over_chars = char_count > max_chars
    over_tokens = token_count > max_tokens
    return {
        "char_count": char_count,
        "token_count": token_count,
        "max_chars": max_chars,
        "max_tokens": max_tokens,
        "over_chars": over_chars,
        "over_tokens": over_tokens,
        "is_oversize": over_chars or over_tokens,
    }


def inspect_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    metrics = inspect_text(extract_chunk_text(chunk))
    metrics["chunk_id"] = str(chunk.get("chunk_id") or "")
    metrics["material_id"] = str(chunk.get("material_id") or "")
    return metrics


def summarize_oversize_chunks(chunks: list[dict[str, Any]]) -> dict[str, int]:
    oversize_count = 0
    max_char_count = 0
    max_token_count = 0
    for chunk in chunks:
        metrics = inspect_chunk(chunk)
        if metrics["is_oversize"]:
            oversize_count += 1
            max_char_count = max(max_char_count, int(metrics["char_count"]))
            max_token_count = max(max_token_count, int(metrics["token_count"]))
    return {
        "oversize_count": oversize_count,
        "max_char_count": max_char_count,
        "max_token_count": max_token_count,
    }
