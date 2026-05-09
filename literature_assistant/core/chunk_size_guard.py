from __future__ import annotations

import os
from typing import Any, TypedDict

from token_utils import count_tokens

DEFAULT_CHUNK_HARD_MAX_CHARS = 5000
DEFAULT_CHUNK_HARD_MAX_TOKENS = 1200


class FilteredEmbeddingChunk(TypedDict):
    index: int
    chunk_id: str
    material_id: str
    char_count: int
    token_count: int
    max_chars: int
    max_tokens: int
    reasons: list[str]


class EmbeddingSafeChunkReport(TypedDict):
    input_count: int
    kept_count: int
    filtered_count: int
    hard_max_chars: int
    hard_max_tokens: int
    chunks: list[dict[str, Any]]
    filtered_chunks: list[FilteredEmbeddingChunk]


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


def filter_embedding_safe_chunks(chunks: list[dict[str, Any]]) -> EmbeddingSafeChunkReport:
    """Return chunks accepted by the embedding hard guard.

    Args:
        chunks: Runtime-order chunk dictionaries. Each item must be a dict so
            downstream cache hashes stay aligned with `ChunkVectorStore.build`.

    Returns:
        A report containing runtime-order kept chunks and non-content metadata
        for chunks rejected by the hard max char/token guard.
    """

    if not isinstance(chunks, list):
        raise TypeError("chunks must be a list of dictionaries")

    kept_chunks: list[dict[str, Any]] = []
    filtered_chunks: list[FilteredEmbeddingChunk] = []
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise TypeError(f"chunk at index {index} must be a dictionary")
        metrics = inspect_chunk(chunk)
        if not bool(metrics["is_oversize"]):
            kept_chunks.append(chunk)
            continue

        reasons: list[str] = []
        if bool(metrics["over_chars"]):
            reasons.append("char_count_exceeds_hard_max")
        if bool(metrics["over_tokens"]):
            reasons.append("token_count_exceeds_hard_max")
        filtered_chunks.append(
            {
                "index": index,
                "chunk_id": str(metrics["chunk_id"]),
                "material_id": str(metrics["material_id"]),
                "char_count": int(metrics["char_count"]),
                "token_count": int(metrics["token_count"]),
                "max_chars": int(metrics["max_chars"]),
                "max_tokens": int(metrics["max_tokens"]),
                "reasons": reasons or ["hard_guard_rejected"],
            }
        )

    return {
        "input_count": len(chunks),
        "kept_count": len(kept_chunks),
        "filtered_count": len(filtered_chunks),
        "hard_max_chars": hard_max_chars(),
        "hard_max_tokens": hard_max_tokens(),
        "chunks": kept_chunks,
        "filtered_chunks": filtered_chunks,
    }
