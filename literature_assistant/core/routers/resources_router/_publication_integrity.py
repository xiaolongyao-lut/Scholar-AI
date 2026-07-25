# -*- coding: utf-8 -*-
"""Strict material publication proof over resource-owned persisted state."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acquisition.models import ImportPublicationEvidence
from chunk_fts_index import (
    CHUNK_FTS_INDEX_SCHEMA_VERSION,
    ChunkFtsIntegrityError,
    ChunkFtsIntegrityReport,
    inspect_chunk_fts_index,
)
from chunk_hashing import (
    CHUNK_HASH_VERSION,
    SUPPORTED_CHUNK_HASH_VERSIONS,
    compute_chunk_hashes,
    compute_chunk_store_version,
)
from material_revision import MaterialRevisionStore, MaterialRevisionStoreError
from material_revision_sync import material_revision_db_path

import routers.resources_router as _rr


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_PLAIN_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PREFIXED_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CHUNK_HASH_FIELDS = frozenset(
    {
        "content_hash",
        "locator_hash",
        "chunk_hash",
        "embedding_input_hash",
        "hash_version",
    }
)


class MaterialPublicationIntegrityError(RuntimeError):
    """Bounded resource-layer failure that cannot be treated as publication."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize a stable machine code and safe diagnostic message."""

        safe_message = str(message or "Material publication integrity check failed").replace("\n", " ")[:500]
        super().__init__(safe_message)
        self.code = str(code or "material_publication_unverified")[:80]
        self.safe_message = safe_message


@dataclass(frozen=True)
class _DocumentSnapshot:
    content_sha256: str
    source_fingerprint: str
    source_size_bytes: int


@dataclass(frozen=True)
class _ChunkSnapshot:
    chunk_hash_version: str
    manifest_sha256: str
    material_file_sha256: str
    material_chunk_count: int
    material_chunk_root_sha256: str
    chunk_store_version: str
    fts_report: ChunkFtsIntegrityReport


def _integrity_error(code: str, message: str) -> MaterialPublicationIntegrityError:
    return MaterialPublicationIntegrityError(code, message)


def _validated_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value.strip()):
        raise ValueError(f"{name} has an unsupported identifier shape")
    return value.strip()


def _read_json_object(path: Path, *, missing_code: str, invalid_code: str) -> tuple[dict[str, Any], bytes]:
    if not path.is_file():
        raise _integrity_error(missing_code, f"Required publication file is missing: {path.name}")
    try:
        raw_bytes = path.read_bytes()
        decoded = raw_bytes.decode("utf-8")
        payload = json.loads(decoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _integrity_error(invalid_code, f"Required publication file is unreadable: {path.name}") from exc
    if not isinstance(payload, dict):
        raise _integrity_error(invalid_code, f"Required publication file must contain a JSON object: {path.name}")
    return payload, raw_bytes


def _read_document_snapshot(
    project_id: str,
    material_id: str,
    *,
    expected_source_fingerprint: str,
    expected_source_size: int,
) -> _DocumentSnapshot:
    payload, _raw_bytes = _read_json_object(
        _rr._get_doc_store_path(project_id),
        missing_code="material_document_store_missing",
        invalid_code="material_document_store_invalid",
    )
    document = payload.get(material_id)
    if not isinstance(document, Mapping):
        raise _integrity_error(
            "material_document_missing",
            "Target material is absent from the document store",
        )
    if document.get("extraction_status") != "succeeded" or str(document.get("extraction_error") or ""):
        raise _integrity_error(
            "material_document_not_published",
            "Target material does not have a successful extraction state",
        )
    source_fingerprint = document.get("source_fingerprint")
    source_size = document.get("source_size")
    if source_fingerprint != expected_source_fingerprint or source_size != expected_source_size:
        raise _integrity_error(
            "material_source_mismatch",
            "Persisted material source identity differs from the validated artifact",
        )
    if isinstance(source_size, bool) or not isinstance(source_size, int):
        raise _integrity_error("material_source_invalid", "Persisted material source size is invalid")
    content = document.get("content")
    if not isinstance(content, str) or not content:
        raise _integrity_error(
            "material_document_content_missing",
            "Published material must contain non-empty extracted text",
        )
    return _DocumentSnapshot(
        content_sha256="sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
        source_fingerprint=source_fingerprint,
        source_size_bytes=source_size,
    )


def _material_jsonl_path(project_dir: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise _integrity_error(
            "chunk_manifest_material_path_invalid",
            "Chunk manifest material path must be non-empty",
        )
    relative = Path(relative_path.strip())
    if relative.is_absolute() or relative.name != str(relative) or relative.suffix.lower() != ".jsonl":
        raise _integrity_error(
            "chunk_manifest_material_path_invalid",
            "Chunk manifest material path must be one project-local JSONL filename",
        )
    candidate = (project_dir / relative).resolve()
    if candidate.parent != project_dir.resolve():
        raise _integrity_error(
            "chunk_manifest_material_path_invalid",
            "Chunk manifest material path escapes the project chunk directory",
        )
    return candidate


def _read_material_jsonl(
    path: Path,
    material_id: str,
    *,
    require_persisted_hashes: bool,
) -> tuple[list[dict[str, Any]], bytes]:
    if not path.is_file():
        raise _integrity_error("material_chunk_file_missing", "Manifest-bound material chunk file is missing")
    try:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _integrity_error("material_chunk_file_invalid", "Material chunk file is unreadable") from exc
    chunks: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _integrity_error(
                "material_chunk_file_invalid",
                f"Material chunk JSONL contains invalid JSON at line {line_number}",
            ) from exc
        if not isinstance(chunk, dict):
            raise _integrity_error(
                "material_chunk_file_invalid",
                f"Material chunk JSONL line {line_number} must be an object",
            )
        if chunk.get("material_id") != material_id:
            raise _integrity_error(
                "material_chunk_identity_mismatch",
                "Persisted chunk material identity differs from its manifest owner",
            )
        chunk_id = chunk.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            raise _integrity_error("material_chunk_identity_invalid", "Persisted chunk id must be non-empty")
        persisted_hash_fields = _CHUNK_HASH_FIELDS.intersection(chunk)
        if persisted_hash_fields and persisted_hash_fields != _CHUNK_HASH_FIELDS:
            raise _integrity_error(
                "material_chunk_hash_incomplete",
                "Persisted chunk hash fields must be either complete or absent for legacy data",
            )
        if require_persisted_hashes and not persisted_hash_fields:
            raise _integrity_error(
                "material_chunk_hash_missing",
                "Target material chunks must persist the current truth-hash contract",
            )
        persisted_hash_version = str(chunk.get("hash_version") or "").strip()
        if (
            persisted_hash_fields
            and persisted_hash_version not in SUPPORTED_CHUNK_HASH_VERSIONS
        ):
            raise _integrity_error(
                "material_chunk_hash_version_unsupported",
                "Persisted chunk uses an unsupported truth-hash contract",
            )
        validation_hash_version = persisted_hash_version or CHUNK_HASH_VERSION
        try:
            computed_hashes = compute_chunk_hashes(
                chunk,
                material_id_hint=material_id,
                hash_version=validation_hash_version,
            )
        except (TypeError, ValueError) as exc:
            raise _integrity_error(
                "material_chunk_hash_unavailable",
                "Persisted chunk cannot produce deterministic truth hashes",
            ) from exc
        if persisted_hash_fields and any(
            chunk.get(key) != value for key, value in computed_hashes.items()
        ):
            raise _integrity_error(
                "material_chunk_hash_mismatch",
                "Persisted chunk hash fields differ from recomputed truth hashes",
            )
        chunks.append(chunk)
    if not chunks:
        raise _integrity_error("material_chunks_missing", "Published material must contain at least one chunk")
    chunk_ids = [str(chunk["chunk_id"]) for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise _integrity_error("material_chunk_identity_duplicate", "Material chunk ids must be unique")
    return chunks, raw_bytes


def _manifest_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _integrity_error("chunk_manifest_invalid", f"Chunk manifest field {name} is invalid")
    return value


def _read_chunk_snapshot(project_id: str, material_id: str) -> _ChunkSnapshot:
    project_dir = _rr._chunk_store_dir(project_id)
    manifest, manifest_bytes = _read_json_object(
        project_dir / "manifest.json",
        missing_code="chunk_manifest_missing",
        invalid_code="chunk_manifest_invalid",
    )
    if manifest.get("version") != 2:
        raise _integrity_error("chunk_manifest_version_unsupported", "Strict publication requires chunk manifest v2")
    materials = manifest.get("materials")
    if not isinstance(materials, Mapping) or not materials:
        raise _integrity_error("chunk_manifest_invalid", "Chunk manifest materials must be a non-empty object")
    manifest_hash_version = str(manifest.get("chunk_hash_version") or "").strip()
    if manifest_hash_version not in SUPPORTED_CHUNK_HASH_VERSIONS:
        raise _integrity_error("chunk_hash_version_mismatch", "Chunk manifest hash contract is unsupported")

    store: dict[str, list[dict[str, Any]]] = {}
    material_file_bytes: dict[str, bytes] = {}
    used_paths: set[Path] = set()
    for raw_material_id, raw_entry in materials.items():
        try:
            manifest_material_id = _validated_id(raw_material_id, "manifest material_id")
        except ValueError as exc:
            raise _integrity_error("chunk_manifest_invalid", "Chunk manifest contains an invalid material id") from exc
        if not isinstance(raw_entry, Mapping):
            raise _integrity_error("chunk_manifest_invalid", "Chunk manifest material entry must be an object")
        material_path = _material_jsonl_path(project_dir, raw_entry.get("relative_path"))
        if material_path in used_paths:
            raise _integrity_error("chunk_manifest_invalid", "Chunk manifest material paths must be unique")
        used_paths.add(material_path)
        chunks, raw_bytes = _read_material_jsonl(
            material_path,
            manifest_material_id,
            require_persisted_hashes=manifest_material_id == material_id,
        )
        expected_count = _manifest_count(raw_entry.get("total_chunks"), "total_chunks")
        manifest_sha256 = raw_entry.get("sha256")
        computed_manifest_sha256 = hashlib.sha256(
            json.dumps(chunks, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if (
            expected_count != len(chunks)
            or not isinstance(manifest_sha256, str)
            or not _PLAIN_SHA256_RE.fullmatch(manifest_sha256)
            or manifest_sha256 != computed_manifest_sha256
        ):
            raise _integrity_error(
                "chunk_manifest_material_mismatch",
                "Chunk manifest material count or digest differs from its JSONL truth",
            )
        store[manifest_material_id] = chunks
        material_file_bytes[manifest_material_id] = raw_bytes

    target_chunks = store.get(material_id)
    if target_chunks is None:
        raise _integrity_error("material_chunks_missing", "Target material is absent from the chunk manifest")
    target_hash_versions = {
        str(chunk.get("hash_version") or "").strip()
        for chunk in target_chunks
    }
    if (
        len(target_hash_versions) != 1
        or not target_hash_versions.issubset(SUPPORTED_CHUNK_HASH_VERSIONS)
    ):
        raise _integrity_error(
            "material_chunk_hash_version_mismatch",
            "Target material chunks must use one supported hash contract",
        )
    target_hash_version = next(iter(target_hash_versions))
    try:
        chunk_store_version = compute_chunk_store_version(
            store,
            hash_version=manifest_hash_version,
        )
        material_chunk_root = compute_chunk_store_version(
            {material_id: target_chunks},
            hash_version=target_hash_version,
        )
    except (TypeError, ValueError) as exc:
        raise _integrity_error(
            "chunk_store_hash_unavailable",
            "Chunk store cannot produce deterministic publication hashes",
        ) from exc
    if (
        manifest.get("chunk_store_version_status") != "valid"
        or manifest.get("chunk_store_version") != chunk_store_version
    ):
        raise _integrity_error(
            "chunk_store_version_mismatch",
            "Chunk manifest version does not match persisted chunk truth",
        )

    try:
        fts_report = inspect_chunk_fts_index(
            db_path=_rr._chunk_fts_index_path(project_id),
            project_id=project_id,
            material_id=material_id,
            store=store,
            expected_chunk_store_version=chunk_store_version,
            hash_version=manifest_hash_version,
        )
    except (ChunkFtsIntegrityError, TypeError, ValueError) as exc:
        code = getattr(exc, "code", "fts_integrity_error")
        raise _integrity_error(code, "Material FTS publication integrity could not be verified") from exc

    if (
        manifest.get("fts_index_status") != "valid"
        or manifest.get("fts_index_fallback_reason") not in {None, ""}
        or manifest.get("fts_index_schema_version") != CHUNK_FTS_INDEX_SCHEMA_VERSION
        or manifest.get("fts_index_relative_path") != _rr._chunk_fts_index_path(project_id).name
        or manifest.get("fts_index_chunk_store_version") != chunk_store_version
        or _manifest_count(manifest.get("fts_index_indexed_count"), "fts_index_indexed_count")
        != fts_report.indexed_count
        or _manifest_count(manifest.get("fts_index_skipped_count"), "fts_index_skipped_count")
        != fts_report.skipped_count
    ):
        raise _integrity_error(
            "chunk_manifest_fts_mismatch",
            "Chunk manifest FTS evidence differs from the persisted index",
        )

    return _ChunkSnapshot(
        chunk_hash_version=target_hash_version,
        manifest_sha256="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        material_file_sha256="sha256:" + hashlib.sha256(material_file_bytes[material_id]).hexdigest(),
        material_chunk_count=len(target_chunks),
        material_chunk_root_sha256="sha256:" + material_chunk_root,
        chunk_store_version=chunk_store_version,
        fts_report=fts_report,
    )


def _read_revision_head(
    project_id: str,
    material_id: str,
    *,
    document: _DocumentSnapshot,
    chunks: _ChunkSnapshot,
) -> tuple[str, str, Any]:
    revision_path = material_revision_db_path(project_id)
    if not revision_path.is_file():
        raise _integrity_error(
            "material_revision_store_missing",
            "Material revision store is missing",
        )
    try:
        store = MaterialRevisionStore(revision_path, project_id)
        active_receipt = store.get_active_receipt(material_id)
        head = store.get_current_head(material_id)
    except (MaterialRevisionStoreError, TypeError, ValueError) as exc:
        raise _integrity_error(
            "material_revision_store_invalid",
            "Material revision store could not produce a validated applied head",
        ) from exc
    if active_receipt is not None:
        raise _integrity_error(
            "material_revision_pending",
            "Material has an incomplete revision transition",
        )
    if head is None:
        raise _integrity_error("material_revision_head_missing", "Material has no applied revision head")
    identity = head.identity
    if (
        identity.raw_source_sha256 != document.source_fingerprint
        or identity.raw_source_size_bytes != document.source_size_bytes
        or identity.extracted_text_sha256 != document.content_sha256
        or identity.material_chunk_root_sha256 != chunks.material_chunk_root_sha256
        or identity.extractor.output_fingerprint_state != "known"
        or identity.extractor.output_fingerprint != document.content_sha256
        or identity.chunker.output_fingerprint_state != "known"
        or identity.chunker.output_fingerprint != chunks.material_chunk_root_sha256
    ):
        raise _integrity_error(
            "material_revision_head_mismatch",
            "Applied material revision does not match document and chunk publication truth",
        )
    return identity.revision_fingerprint, head.applied_receipt_id, head.applied_at


def verify_material_publication(
    project_id: str,
    material_id: str,
    *,
    expected_source_fingerprint: str,
    expected_source_size: int,
) -> ImportPublicationEvidence:
    """Return strict evidence that one material is durable and retrieval-visible.

    Args:
        project_id: Existing project that owns all publication state.
        material_id: Imported material to verify.
        expected_source_fingerprint: Validated ``sha256:<hex>`` artifact identity.
        expected_source_size: Exact validated source byte count, at least 4096.

    Returns:
        Immutable evidence bound to document, chunk, FTS, and revision facts.

    Raises:
        MaterialPublicationIntegrityError: If any persisted publication fact is
            missing, corrupt, stale, or inconsistent with another store.
        ValueError: If caller-supplied identifiers or source evidence are invalid.
    """

    normalized_project_id = _validated_id(project_id, "project_id")
    normalized_material_id = _validated_id(material_id, "material_id")
    if not isinstance(expected_source_fingerprint, str) or not _PREFIXED_SHA256_RE.fullmatch(
        expected_source_fingerprint
    ):
        raise ValueError("expected_source_fingerprint must use sha256:<64 lowercase hex>")
    if (
        isinstance(expected_source_size, bool)
        or not isinstance(expected_source_size, int)
        or expected_source_size < 4096
        or expected_source_size > 1_099_511_627_776
    ):
        raise ValueError("expected_source_size must be between 4096 bytes and 1 TiB")

    document = _read_document_snapshot(
        normalized_project_id,
        normalized_material_id,
        expected_source_fingerprint=expected_source_fingerprint,
        expected_source_size=expected_source_size,
    )
    with _rr._CHUNK_STORE_LOCK:
        chunks = _read_chunk_snapshot(normalized_project_id, normalized_material_id)
    revision_fingerprint, revision_receipt_id, revision_applied_at = _read_revision_head(
        normalized_project_id,
        normalized_material_id,
        document=document,
        chunks=chunks,
    )
    return ImportPublicationEvidence(
        project_id=normalized_project_id,
        material_id=normalized_material_id,
        source_fingerprint=document.source_fingerprint,
        source_size_bytes=document.source_size_bytes,
        document_content_sha256=document.content_sha256,
        chunk_manifest_sha256=chunks.manifest_sha256,
        chunk_hash_version=chunks.chunk_hash_version,
        material_chunk_file_sha256=chunks.material_file_sha256,
        material_chunk_count=chunks.material_chunk_count,
        material_chunk_root_sha256=chunks.material_chunk_root_sha256,
        chunk_store_version=chunks.chunk_store_version,
        fts_schema_version=chunks.fts_report.schema_version,
        fts_chunk_store_version=chunks.fts_report.chunk_store_version,
        fts_indexed_count=chunks.fts_report.indexed_count,
        fts_skipped_count=chunks.fts_report.skipped_count,
        fts_material_indexed_count=chunks.fts_report.material_indexed_count,
        revision_fingerprint=revision_fingerprint,
        revision_receipt_id=revision_receipt_id,
        revision_applied_at=revision_applied_at,
    )


__all__ = [
    "MaterialPublicationIntegrityError",
    "verify_material_publication",
]
