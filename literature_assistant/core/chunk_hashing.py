# -*- coding: utf-8 -*-
"""Deterministic truth-hash helpers for project chunk-store records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict


CHUNK_HASH_VERSION = "scholar-ai-chunk-hash/v1"

ChunkHashTransition = Literal[
    "unchanged",
    "truth_changed",
    "embedding_changed",
    "truth_changed_embedding_unchanged",
    "unknown",
]


class ChunkHashes(TypedDict):
    """Hash fields persisted on each chunk-store record.

    Values are lowercase SHA-256 hex digests. ``hash_version`` identifies the
    canonicalization contract, so future migrations can compare safely.
    """

    content_hash: str
    locator_hash: str
    chunk_hash: str
    embedding_input_hash: str
    hash_version: str


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_canonical(value: Any) -> str:
    payload = _canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalized_text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _normalized_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _normalized_text(value)


def _normalized_sequence(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [_normalized_text(value)]
    if not isinstance(value, Sequence):
        raise TypeError("locator sequence fields must be strings, sequences, or null")
    return [_normalized_scalar(item) for item in value]


def _evidence_text(chunk: Mapping[str, Any]) -> str:
    raw_content = _normalized_text(chunk.get("raw_content"))
    content = _normalized_text(chunk.get("content"))
    text = raw_content or content
    if not text:
        raise ValueError("chunk must contain non-empty raw_content or content")
    return text


def _embedding_input_text(chunk: Mapping[str, Any]) -> str:
    text = _normalized_text(chunk.get("content")) or _evidence_text(chunk)
    if not text:
        raise ValueError("chunk embedding input cannot be empty")
    return text


def _material_id(chunk: Mapping[str, Any], material_id_hint: str | None) -> str:
    value = _normalized_text(chunk.get("material_id")) or _normalized_text(material_id_hint)
    if not value:
        raise ValueError("chunk material_id is required for locator_hash")
    return value


def _locator_payload(chunk: Mapping[str, Any], material_id_hint: str | None) -> dict[str, Any]:
    return {
        "material_id": _material_id(chunk, material_id_hint),
        "page": _normalized_scalar(chunk.get("page")),
        "chunk_index": _normalized_scalar(chunk.get("chunk_index")),
        "bbox": _normalized_sequence(chunk.get("bbox")),
        "image_paths": _normalized_sequence(chunk.get("image_paths")),
        "table_csv": _normalized_text(chunk.get("table_csv")),
        "equation_latex": _normalized_text(chunk.get("equation_latex")),
        "section_path": _normalized_sequence(chunk.get("section_path")),
        "locator": chunk.get("locator") if isinstance(chunk.get("locator"), Mapping) else None,
    }


def compute_chunk_hashes(
    chunk: Mapping[str, Any],
    *,
    material_id_hint: str | None = None,
) -> ChunkHashes:
    """Return deterministic truth and embedding-input hashes for one chunk.

    Args:
        chunk: Mapping with at least ``content`` or ``raw_content`` and a
            resolvable ``material_id``.
        material_id_hint: Fallback material id from the surrounding chunk-store
            key when legacy chunks are missing the field.

    Returns:
        Hash fields safe to persist into the chunk-store record.

    Raises:
        TypeError: If ``chunk`` is not mapping-like or locator sequence fields
            have unsupported shapes.
        ValueError: If evidence text or material identity is missing.
    """

    if not isinstance(chunk, Mapping):
        raise TypeError("chunk must be a mapping")

    content_hash = _sha256_canonical(
        {
            "hash_version": CHUNK_HASH_VERSION,
            "content": _evidence_text(chunk),
        }
    )
    locator_hash = _sha256_canonical(
        {
            "hash_version": CHUNK_HASH_VERSION,
            "locator": _locator_payload(chunk, material_id_hint),
        }
    )
    chunk_hash = _sha256_canonical(
        {
            "hash_version": CHUNK_HASH_VERSION,
            "content_hash": content_hash,
            "locator_hash": locator_hash,
            "chunk_type": _normalized_text(chunk.get("chunk_type")) or "unknown",
        }
    )
    embedding_input_hash = _sha256_canonical(
        {
            "hash_version": CHUNK_HASH_VERSION,
            "embedding_input": _embedding_input_text(chunk),
        }
    )
    return {
        "content_hash": content_hash,
        "locator_hash": locator_hash,
        "chunk_hash": chunk_hash,
        "embedding_input_hash": embedding_input_hash,
        "hash_version": CHUNK_HASH_VERSION,
    }


def with_chunk_hashes(
    chunk: Mapping[str, Any],
    *,
    material_id_hint: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Return a chunk copy with deterministic hash fields populated.

    Args:
        chunk: Mapping chunk record to copy.
        material_id_hint: Fallback material id for legacy chunk-store records.
        overwrite: Recompute existing hash fields when ``True``.

    Returns:
        A new dict preserving all unrelated chunk fields.
    """

    if not isinstance(chunk, Mapping):
        raise TypeError("chunk must be a mapping")

    result = dict(chunk)
    required_keys = {"content_hash", "locator_hash", "chunk_hash", "embedding_input_hash", "hash_version"}
    if not overwrite and required_keys.issubset(result.keys()):
        return result

    result.update(compute_chunk_hashes(result, material_id_hint=material_id_hint))
    if not _normalized_text(result.get("material_id")) and material_id_hint:
        result["material_id"] = _normalized_text(material_id_hint)
    return result


def classify_chunk_hash_transition(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    material_id_hint: str | None = None,
) -> ChunkHashTransition:
    """Classify whether truth and embedding-input hashes diverged.

    Args:
        previous: Existing chunk record, with or without persisted hash fields.
        current: Replacement chunk record, with or without persisted hash fields.
        material_id_hint: Fallback material id for legacy records.

    Returns:
        A bounded transition label for backfill and quarantine decisions.
    """

    if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
        raise TypeError("previous and current chunks must be mappings")

    try:
        previous_hashes = compute_chunk_hashes(previous, material_id_hint=material_id_hint)
        current_hashes = compute_chunk_hashes(current, material_id_hint=material_id_hint)
    except (TypeError, ValueError):
        return "unknown"

    truth_changed = previous_hashes["chunk_hash"] != current_hashes["chunk_hash"]
    embedding_changed = previous_hashes["embedding_input_hash"] != current_hashes["embedding_input_hash"]
    if truth_changed and not embedding_changed:
        return "truth_changed_embedding_unchanged"
    if truth_changed:
        return "truth_changed"
    if embedding_changed:
        return "embedding_changed"
    return "unchanged"


def compute_chunk_store_version(store: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    """Return a content-derived project chunk-store version.

    Args:
        store: Mapping of ``material_id`` to chunk mappings. Each chunk must be
            hashable under ``CHUNK_HASH_VERSION``.

    Returns:
        A SHA-256 Merkle-style root over sorted ``material_id``, ``chunk_id``,
        and ``chunk_hash`` rows.

    Raises:
        TypeError: If the store shape is not mapping -> sequence -> mapping.
        ValueError: If any chunk cannot produce deterministic hashes.
    """

    if not isinstance(store, Mapping):
        raise TypeError("store must be a mapping of material_id to chunk sequences")

    rows: list[dict[str, str]] = []
    for raw_material_id, chunks in sorted(store.items(), key=lambda item: str(item[0])):
        material_id = _normalized_text(raw_material_id)
        if not material_id:
            raise ValueError("store material_id keys must be non-empty")
        if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
            raise TypeError("store material values must be chunk sequences")
        for chunk in chunks:
            if not isinstance(chunk, Mapping):
                raise TypeError("store chunks must be mappings")
            chunk_id = _normalized_text(chunk.get("chunk_id"))
            hashes = compute_chunk_hashes(chunk, material_id_hint=material_id)
            rows.append(
                {
                    "material_id": material_id,
                    "chunk_id": chunk_id,
                    "chunk_hash": hashes["chunk_hash"],
                    "embedding_input_hash": hashes["embedding_input_hash"],
                }
            )
    rows.sort(key=lambda item: (item["material_id"], item["chunk_id"], item["chunk_hash"]))
    return _sha256_canonical(
        {
            "hash_version": CHUNK_HASH_VERSION,
            "rows": rows,
        }
    )
