# -*- coding: utf-8 -*-
"""Chroma derived dense index for project chunk stores."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from literature_assistant.core.chunk_hashing import compute_chunk_hashes
    from literature_assistant.core.chunk_index_consistency_gate import IndexedChunkRecord
else:
    from chunk_hashing import compute_chunk_hashes
    from chunk_index_consistency_gate import IndexedChunkRecord


CHUNK_CHROMA_INDEX_SCHEMA_VERSION = "scholar-ai-chunk-chroma-index/v1"

ChunkChromaIndexStatus = Literal[
    "valid",
    "missing",
    "stale",
    "contract_mismatch",
    "split_brain",
    "unavailable",
]

_COLLECTION_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class ChunkChromaBuildReport:
    """Summary of a complete Chroma collection rebuild."""

    schema_version: str
    project_id: str
    collection_name: str
    persist_dir: str
    chunk_store_version: str
    contract_hash: str
    indexed_count: int
    skipped_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report payload."""

        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "collection_name": self.collection_name,
            "persist_dir": self.persist_dir,
            "chunk_store_version": self.chunk_store_version,
            "contract_hash": self.contract_hash,
            "indexed_count": self.indexed_count,
            "skipped_count": self.skipped_count,
        }


@dataclass(frozen=True)
class ChunkChromaDiagnostics:
    """Current consistency state of a project Chroma collection."""

    status: ChunkChromaIndexStatus
    project_id: str
    collection_name: str
    chunk_store_version: str
    expected_chunk_store_version: str
    contract_hashes: tuple[str, ...]
    expected_contract_hash: str
    indexed_count: int
    fallback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a machine-readable diagnostics payload."""

        return {
            "status": self.status,
            "project_id": self.project_id,
            "collection_name": self.collection_name,
            "chunk_store_version": self.chunk_store_version,
            "expected_chunk_store_version": self.expected_chunk_store_version,
            "contract_hashes": list(self.contract_hashes),
            "expected_contract_hash": self.expected_contract_hash,
            "indexed_count": self.indexed_count,
            "fallback_reason": self.fallback_reason,
        }


@dataclass(frozen=True)
class ChunkChromaSearchResult:
    """Bounded Chroma query result with collection diagnostics."""

    diagnostics: ChunkChromaDiagnostics
    hits: tuple[IndexedChunkRecord, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable query result."""

        return {
            "diagnostics": self.diagnostics.to_dict(),
            "hits": [hit.to_dict() for hit in self.hits],
        }


def _require_non_empty_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _bounded_text(value: object, *, max_chars: int = 5000) -> str:
    return str(value or "").replace("\x00", " ").strip()[:max_chars]


def _coerce_page(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return 0
    try:
        page = int(value)
    except (TypeError, ValueError):
        return 0
    return page if page > 0 else 0


def _collection_name(project_id: str) -> str:
    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    cleaned = _COLLECTION_NAME_RE.sub("_", normalized_project_id).strip("_-")
    digest = hashlib.sha256(normalized_project_id.encode("utf-8")).hexdigest()[:12]
    prefix = (cleaned or "project")[:48].strip("_-") or "project"
    return f"project_{prefix}_{digest}_chunks"


def _import_chromadb() -> Any:
    try:
        import chromadb
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("chromadb is not available") from exc
    return chromadb


def _embedding_from_chunk(
    chunk: Mapping[str, Any],
    *,
    embedding_dim: int,
) -> list[float] | None:
    value = chunk.get("embedding")
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return None
    if len(value) < embedding_dim:
        return None
    vector: list[float] = []
    for raw in value[:embedding_dim]:
        if isinstance(raw, bool):
            return None
        try:
            number = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        vector.append(number)
    if not any(component != 0.0 for component in vector):
        return None
    return vector


def _chunk_document(chunk: Mapping[str, Any]) -> str:
    text = _bounded_text(chunk.get("content")) or _bounded_text(chunk.get("raw_content"))
    if not text:
        raise ValueError("indexed chunk must contain non-empty content or raw_content")
    return text


def _metadata(
    *,
    project_id: str,
    material_id: str,
    chunk_id: str,
    chunk: Mapping[str, Any],
    contract_hash: str,
) -> dict[str, Any]:
    hashes = compute_chunk_hashes(chunk, material_id_hint=material_id)
    return {
        "schema_version": CHUNK_CHROMA_INDEX_SCHEMA_VERSION,
        "project_id": project_id,
        "material_id": material_id,
        "chunk_id": chunk_id,
        "content_hash": hashes["content_hash"],
        "chunk_hash": hashes["chunk_hash"],
        "embedding_input_hash": hashes["embedding_input_hash"],
        "hash_version": hashes["hash_version"],
        "contract_hash": contract_hash,
        "page": _coerce_page(chunk.get("page")),
        "chunk_type": _bounded_text(chunk.get("chunk_type"), max_chars=80) or "unknown",
        "title": _bounded_text(chunk.get("title"), max_chars=500),
        "section_title": _bounded_text(chunk.get("section_title"), max_chars=300),
        "has_image": bool(chunk.get("image_paths") or chunk.get("figure_image_paths")),
        "has_table": bool(_bounded_text(chunk.get("table_csv"))),
        "has_equation": bool(_bounded_text(chunk.get("equation_latex"))),
        "locator_quality": _bounded_text(chunk.get("locator_quality"), max_chars=80),
        "linter_status": _bounded_text(chunk.get("linter_status"), max_chars=80),
    }


def _iter_indexable_rows(
    *,
    project_id: str,
    store: Mapping[str, Sequence[Mapping[str, Any]]],
    contract_hash: str,
    embedding_dim: int,
) -> tuple[list[str], list[list[float]], list[str], list[dict[str, Any]], int]:
    if not isinstance(store, Mapping):
        raise TypeError("store must be a mapping of material ids to chunk sequences")
    if not isinstance(embedding_dim, int) or embedding_dim < 1:
        raise ValueError("embedding_dim must be a positive integer")

    ids: list[str] = []
    embeddings: list[list[float]] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    skipped = 0
    seen: set[str] = set()
    for raw_material_id, chunks in sorted(store.items(), key=lambda item: str(item[0])):
        material_id = _require_non_empty_string(str(raw_material_id), name="material_id")
        if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
            raise TypeError("store material values must be chunk sequences")
        for chunk in chunks:
            if not isinstance(chunk, Mapping):
                skipped += 1
                continue
            chunk_id = _bounded_text(chunk.get("chunk_id"), max_chars=240)
            vector = _embedding_from_chunk(chunk, embedding_dim=embedding_dim)
            if not chunk_id or vector is None:
                skipped += 1
                continue
            row_id = f"{project_id}:{material_id}:{chunk_id}"
            if row_id in seen:
                skipped += 1
                continue
            try:
                document = _chunk_document(chunk)
                metadata = _metadata(
                    project_id=project_id,
                    material_id=material_id,
                    chunk_id=chunk_id,
                    chunk=chunk,
                    contract_hash=contract_hash,
                )
            except (TypeError, ValueError):
                skipped += 1
                continue
            seen.add(row_id)
            ids.append(row_id)
            embeddings.append(vector)
            documents.append(document)
            metadatas.append(metadata)
    return ids, embeddings, documents, metadatas, skipped


def _collection_metadata(
    *,
    project_id: str,
    chunk_store_version: str,
    contract_hash: str,
    embedding_dim: int,
) -> dict[str, Any]:
    return {
        "schema_version": CHUNK_CHROMA_INDEX_SCHEMA_VERSION,
        "project_id": project_id,
        "chunk_store_version": chunk_store_version,
        "contract_hash": contract_hash,
        "embedding_dim": embedding_dim,
    }


def rebuild_chunk_chroma_index(
    *,
    persist_dir: Path,
    project_id: str,
    store: Mapping[str, Sequence[Mapping[str, Any]]],
    chunk_store_version: str,
    contract_hash: str,
    embedding_dim: int = 1024,
    batch_size: int = 500,
) -> ChunkChromaBuildReport:
    """Rebuild a project Chroma collection from chunk-store truth.

    Args:
        persist_dir: Directory where Chroma stores the derived collection.
        project_id: Non-empty project id used to isolate the collection.
        store: Current chunk-store truth. Rows without usable embeddings are skipped.
        chunk_store_version: Content-derived truth-store version.
        contract_hash: Current embedding contract hash for all indexed rows.
        embedding_dim: Expected dense embedding width.
        batch_size: Chroma add batch size, from 1 to 5000.

    Returns:
        Build report for the newly rebuilt collection.
    """

    if not isinstance(persist_dir, Path):
        raise TypeError("persist_dir must be a pathlib.Path")
    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    normalized_version = _require_non_empty_string(chunk_store_version, name="chunk_store_version")
    normalized_contract_hash = _require_non_empty_string(contract_hash, name="contract_hash")
    if not isinstance(batch_size, int) or batch_size < 1 or batch_size > 5000:
        raise ValueError("batch_size must be between 1 and 5000")

    ids, embeddings, documents, metadatas, skipped = _iter_indexable_rows(
        project_id=normalized_project_id,
        store=store,
        contract_hash=normalized_contract_hash,
        embedding_dim=embedding_dim,
    )
    chromadb = _import_chromadb()
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    name = _collection_name(normalized_project_id)
    try:
        client.delete_collection(name=name)
    except Exception:
        pass
    collection = client.create_collection(
        name=name,
        metadata=_collection_metadata(
            project_id=normalized_project_id,
            chunk_store_version=normalized_version,
            contract_hash=normalized_contract_hash,
            embedding_dim=embedding_dim,
        ),
    )
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        collection.add(
            ids=ids[start:end],
            embeddings=embeddings[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )
    return ChunkChromaBuildReport(
        schema_version=CHUNK_CHROMA_INDEX_SCHEMA_VERSION,
        project_id=normalized_project_id,
        collection_name=name,
        persist_dir=str(persist_dir),
        chunk_store_version=normalized_version,
        contract_hash=normalized_contract_hash,
        indexed_count=len(ids),
        skipped_count=skipped,
    )


def _missing_diagnostics(
    *,
    project_id: str,
    collection_name: str,
    expected_chunk_store_version: str,
    expected_contract_hash: str,
    fallback_reason: str,
) -> ChunkChromaDiagnostics:
    return ChunkChromaDiagnostics(
        status="missing",
        project_id=project_id,
        collection_name=collection_name,
        chunk_store_version="",
        expected_chunk_store_version=expected_chunk_store_version,
        contract_hashes=(),
        expected_contract_hash=expected_contract_hash,
        indexed_count=0,
        fallback_reason=fallback_reason,
    )


def inspect_chunk_chroma_index(
    *,
    persist_dir: Path,
    project_id: str,
    expected_chunk_store_version: str,
    expected_contract_hash: str,
    metadata_batch_size: int = 1000,
) -> ChunkChromaDiagnostics:
    """Inspect a Chroma collection before dense recall is allowed."""

    if not isinstance(persist_dir, Path):
        raise TypeError("persist_dir must be a pathlib.Path")
    normalized_project_id = _require_non_empty_string(project_id, name="project_id")
    expected_version = _require_non_empty_string(expected_chunk_store_version, name="expected_chunk_store_version")
    expected_contract = _require_non_empty_string(expected_contract_hash, name="expected_contract_hash")
    if not isinstance(metadata_batch_size, int) or metadata_batch_size < 1:
        raise ValueError("metadata_batch_size must be a positive integer")

    name = _collection_name(normalized_project_id)
    if not persist_dir.exists():
        return _missing_diagnostics(
            project_id=normalized_project_id,
            collection_name=name,
            expected_chunk_store_version=expected_version,
            expected_contract_hash=expected_contract,
            fallback_reason="chroma_index_missing",
        )
    try:
        chromadb = _import_chromadb()
        client = chromadb.PersistentClient(path=str(persist_dir))
        collection = client.get_collection(name=name)
        collection_metadata = collection.metadata or {}
        indexed_count = int(collection.count())
        contract_hashes: set[str] = set()
        for offset in range(0, indexed_count, metadata_batch_size):
            payload = collection.get(include=["metadatas"], limit=metadata_batch_size, offset=offset)
            metadatas = payload.get("metadatas") or []
            for metadata in metadatas:
                if not isinstance(metadata, Mapping):
                    continue
                contract = _bounded_text(metadata.get("contract_hash"), max_chars=120)
                if contract:
                    contract_hashes.add(contract)
        if not contract_hashes:
            collection_contract = _bounded_text(collection_metadata.get("contract_hash"), max_chars=120)
            if collection_contract:
                contract_hashes.add(collection_contract)
    except Exception:
        return ChunkChromaDiagnostics(
            status="unavailable",
            project_id=normalized_project_id,
            collection_name=name,
            chunk_store_version="",
            expected_chunk_store_version=expected_version,
            contract_hashes=(),
            expected_contract_hash=expected_contract,
            indexed_count=0,
            fallback_reason="chroma_index_unavailable",
        )

    actual_version = _bounded_text(collection_metadata.get("chunk_store_version"), max_chars=120)
    sorted_contracts = tuple(sorted(contract_hashes))
    if len(sorted_contracts) > 1:
        return ChunkChromaDiagnostics(
            status="split_brain",
            project_id=normalized_project_id,
            collection_name=name,
            chunk_store_version=actual_version,
            expected_chunk_store_version=expected_version,
            contract_hashes=sorted_contracts,
            expected_contract_hash=expected_contract,
            indexed_count=indexed_count,
            fallback_reason="chroma_index_split_brain",
        )
    if sorted_contracts and sorted_contracts[0] != expected_contract:
        return ChunkChromaDiagnostics(
            status="contract_mismatch",
            project_id=normalized_project_id,
            collection_name=name,
            chunk_store_version=actual_version,
            expected_chunk_store_version=expected_version,
            contract_hashes=sorted_contracts,
            expected_contract_hash=expected_contract,
            indexed_count=indexed_count,
            fallback_reason="chroma_index_contract_mismatch",
        )
    if actual_version != expected_version:
        return ChunkChromaDiagnostics(
            status="stale",
            project_id=normalized_project_id,
            collection_name=name,
            chunk_store_version=actual_version,
            expected_chunk_store_version=expected_version,
            contract_hashes=sorted_contracts,
            expected_contract_hash=expected_contract,
            indexed_count=indexed_count,
            fallback_reason="chroma_index_stale",
        )
    return ChunkChromaDiagnostics(
        status="valid",
        project_id=normalized_project_id,
        collection_name=name,
        chunk_store_version=actual_version,
        expected_chunk_store_version=expected_version,
        contract_hashes=sorted_contracts,
        expected_contract_hash=expected_contract,
        indexed_count=indexed_count,
    )


def _query_embedding(value: Sequence[float], *, embedding_dim: int) -> list[float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("query_embedding must be a numeric sequence")
    if len(value) < embedding_dim:
        raise ValueError("query_embedding is shorter than embedding_dim")
    vector: list[float] = []
    for raw in value[:embedding_dim]:
        if isinstance(raw, bool):
            raise TypeError("query_embedding must not contain booleans")
        try:
            number = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise TypeError("query_embedding must contain finite numbers") from exc
        if not math.isfinite(number):
            raise ValueError("query_embedding must contain finite numbers")
        vector.append(number)
    return vector


def query_chunk_chroma_index(
    *,
    persist_dir: Path,
    project_id: str,
    query_embedding: Sequence[float],
    expected_chunk_store_version: str,
    expected_contract_hash: str,
    limit: int = 10,
    embedding_dim: int = 1024,
) -> ChunkChromaSearchResult:
    """Query Chroma only after collection diagnostics are valid."""

    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    vector = _query_embedding(query_embedding, embedding_dim=embedding_dim)
    diagnostics = inspect_chunk_chroma_index(
        persist_dir=persist_dir,
        project_id=project_id,
        expected_chunk_store_version=expected_chunk_store_version,
        expected_contract_hash=expected_contract_hash,
    )
    if diagnostics.status != "valid" or diagnostics.indexed_count == 0:
        return ChunkChromaSearchResult(diagnostics=diagnostics)
    try:
        chromadb = _import_chromadb()
        client = chromadb.PersistentClient(path=str(persist_dir))
        collection = client.get_collection(name=diagnostics.collection_name)
        payload = collection.query(
            query_embeddings=[vector],
            n_results=min(limit, diagnostics.indexed_count),
            include=["metadatas", "distances"],
        )
    except Exception:
        return ChunkChromaSearchResult(
            diagnostics=ChunkChromaDiagnostics(
                status="unavailable",
                project_id=diagnostics.project_id,
                collection_name=diagnostics.collection_name,
                chunk_store_version=diagnostics.chunk_store_version,
                expected_chunk_store_version=diagnostics.expected_chunk_store_version,
                contract_hashes=diagnostics.contract_hashes,
                expected_contract_hash=diagnostics.expected_contract_hash,
                indexed_count=diagnostics.indexed_count,
                fallback_reason="chroma_index_query_failed",
            )
        )

    metadatas = (payload.get("metadatas") or [[]])[0]
    distances = (payload.get("distances") or [[]])[0]
    hits: list[IndexedChunkRecord] = []
    for index, metadata in enumerate(metadatas):
        if not isinstance(metadata, Mapping):
            continue
        distance = float(distances[index]) if index < len(distances) else None
        score = None if distance is None else 1.0 / (1.0 + max(distance, 0.0))
        try:
            hits.append(
                IndexedChunkRecord(
                    project_id=_require_non_empty_string(metadata.get("project_id"), name="project_id"),
                    material_id=_require_non_empty_string(metadata.get("material_id"), name="material_id"),
                    chunk_id=_require_non_empty_string(metadata.get("chunk_id"), name="chunk_id"),
                    chunk_hash=_require_non_empty_string(metadata.get("chunk_hash"), name="chunk_hash"),
                    embedding_input_hash=_require_non_empty_string(
                        metadata.get("embedding_input_hash"),
                        name="embedding_input_hash",
                    ),
                    contract_hash=_require_non_empty_string(metadata.get("contract_hash"), name="contract_hash"),
                    source="dense",
                    score=score,
                )
            )
        except (TypeError, ValueError):
            continue
    return ChunkChromaSearchResult(diagnostics=diagnostics, hits=tuple(hits))
