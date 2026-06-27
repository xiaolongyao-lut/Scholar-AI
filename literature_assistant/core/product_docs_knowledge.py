"""Read-only knowledge projection for Scholar AI product documentation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path used by the running app.
    from literature_assistant.core.project_paths import REPO_ROOT
except ImportError:  # pragma: no cover - flat import path used by legacy tests.
    from project_paths import REPO_ROOT


PRODUCT_DOCS_KNOWLEDGE_SCHEMA_VERSION = "scholar-ai-product-docs-knowledge/v1"
PRODUCT_DOCS_REF_SCHEMA_VERSION = "scholar-ai-product-docs-knowledge-ref/v1"
PRODUCT_DOCS_PACKAGE_ID = "product_docs"
MAX_PRODUCT_DOC_BYTES = 2 * 1024 * 1024
MAX_PRODUCT_DOC_SEARCH_RESULTS = 50
_DOC_SOURCE_PATTERNS = ("README.md", "docs/*.md")
_EXCLUDED_DOC_PARTS = frozenset({"plans"})


@dataclass(frozen=True)
class ProductDocSource:
    """One authoritative product-doc source file loaded into runtime knowledge."""

    relative_path: str
    role: str
    loaded: bool
    content_hash: str
    char_count: int
    byte_count: int
    updated_at: str
    warning: str | None = None


@dataclass(frozen=True)
class ProductDocChunk:
    """One bounded product-doc ref derived from an authoritative Markdown source."""

    chunk_id: str
    title: str
    source_path: str
    source_role: str
    source_hash: str
    content_hash: str
    span_start: int
    span_end: int
    text: str

    @property
    def ref_id(self) -> str:
        """Return the agent-readable resource ref for this product-doc chunk."""

        return build_product_docs_chunk_ref_id(self.chunk_id)

    @property
    def read_endpoint(self) -> str:
        """Return the bounded resource endpoint for this product-doc chunk."""

        return f"/api/agent-bridge/resource/{self.ref_id}"


@dataclass(frozen=True)
class ProductDocsSnapshot:
    """Read-only source/ref/provenance status for repo-local product docs."""

    package_id: str
    source_path: str
    source_hash: str
    content_hash: str
    loaded: bool
    manifest_loaded: bool
    load_status: str
    updated_at: str
    title: str
    description: str
    source_files: list[ProductDocSource] = field(default_factory=list)
    chunks: list[ProductDocChunk] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    runtime_consumers: list[dict[str, str]] = field(default_factory=list)

    def to_status_payload(self, *, include_chunks: bool = False) -> dict[str, Any]:
        """Return a JSON-safe product-doc knowledge status payload."""

        payload: dict[str, Any] = {
            "schema_version": PRODUCT_DOCS_KNOWLEDGE_SCHEMA_VERSION,
            "package_id": self.package_id,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "content_hash": self.content_hash,
            "loaded": self.loaded,
            "manifest_loaded": self.manifest_loaded,
            "load_status": self.load_status,
            "updated_at": self.updated_at,
            "title": self.title,
            "description": self.description,
            "source_files": [asdict(item) for item in self.source_files],
            "chunk_count": len(self.chunks),
            "warnings": list(self.warnings),
            "manifest": dict(self.manifest),
            "runtime_consumers": [dict(item) for item in self.runtime_consumers],
        }
        if include_chunks:
            payload["chunks"] = [
                {
                    "chunk_id": chunk.chunk_id,
                    "ref_id": chunk.ref_id,
                    "read_endpoint": chunk.read_endpoint,
                    "title": chunk.title,
                    "source_path": chunk.source_path,
                    "source_role": chunk.source_role,
                    "source_hash": chunk.source_hash,
                    "content_hash": chunk.content_hash,
                    "span_start": chunk.span_start,
                    "span_end": chunk.span_end,
                    "char_count": len(chunk.text),
                }
                for chunk in self.chunks
            ]
        return payload


def build_product_docs_chunk_ref_id(chunk_id: str) -> str:
    """Return a stable agent resource ref for one product-doc chunk."""

    normalized = _normalize_chunk_id(chunk_id)
    return f"product_docs:chunk:{normalized}"


def load_product_docs_snapshot(repo_root: Path | None = None) -> ProductDocsSnapshot:
    """Load README and top-level docs Markdown as a read-only knowledge package."""

    root = repo_root or REPO_ROOT
    source_paths = _discover_sources(root)
    warnings: list[str] = []
    source_records: list[ProductDocSource] = []
    file_payloads: list[tuple[Path, str, str]] = []

    for source_path in source_paths:
        role = _source_role(root, source_path)
        try:
            text = _read_bounded_source(source_path)
        except OSError as exc:
            warnings.append(f"Could not read {_repo_relative(source_path, root)}: {exc}")
            source_records.append(_source_record(root, source_path, role, text="", warning=str(exc)))
            continue
        file_payloads.append((source_path, role, text))
        source_records.append(_source_record(root, source_path, role, text=text))

    if not source_paths:
        warnings.append("No product documentation sources were found.")
    if not file_payloads:
        return _snapshot(
            source_path="README.md + docs/*.md",
            source_hash="unknown",
            content_hash="unknown",
            loaded=False,
            manifest_loaded=False,
            load_status="missing",
            updated_at="unknown",
            source_files=source_records,
            warnings=warnings,
        )

    chunks = _build_chunks(root, file_payloads)
    source_hash = _combined_source_hash(root, file_payloads)
    content_hash = _combined_runtime_content_hash(chunks)
    loaded = bool(chunks)
    if not loaded:
        warnings.append("Product documentation sources did not produce readable chunks.")
    return _snapshot(
        source_path="README.md + docs/*.md",
        source_hash=source_hash,
        content_hash=content_hash,
        loaded=loaded,
        manifest_loaded=loaded,
        load_status="loaded" if loaded else "missing",
        updated_at=_latest_updated_at([path for path, _role, _text in file_payloads]),
        source_files=source_records,
        chunks=chunks,
        manifest=_manifest(root, source_records, chunks),
        warnings=warnings,
    )


def get_product_docs_status() -> dict[str, Any]:
    """Return source/ref/provenance status for product documentation."""

    return load_product_docs_snapshot().to_status_payload(include_chunks=True)


def read_product_docs() -> dict[str, Any]:
    """Return product-doc chunk metadata and source summaries for bounded callers."""

    snapshot = load_product_docs_snapshot()
    entries = {
        chunk.chunk_id: {
            "title": chunk.title,
            "source_path": chunk.source_path,
            "source_role": chunk.source_role,
            "content": chunk.text,
            "content_hash": chunk.content_hash,
            "span_start": chunk.span_start,
            "span_end": chunk.span_end,
        }
        for chunk in snapshot.chunks
    }
    return {
        **snapshot.to_status_payload(include_chunks=True),
        "entries": entries,
    }


def search_product_docs(query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
    """Search product documentation chunks and return bounded resource refs."""

    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if top_k < 1 or top_k > MAX_PRODUCT_DOC_SEARCH_RESULTS:
        raise ValueError(f"top_k must be between 1 and {MAX_PRODUCT_DOC_SEARCH_RESULTS}")

    snapshot = load_product_docs_snapshot()
    terms = _query_terms(normalized_query)
    hits: list[tuple[int, ProductDocChunk]] = []
    for chunk in snapshot.chunks:
        score = _score_chunk(chunk, terms, normalized_query)
        if score > 0:
            hits.append((score, chunk))
    hits.sort(key=lambda item: (-item[0], item[1].source_path, item[1].span_start))

    return [
        {
            "schema_version": PRODUCT_DOCS_REF_SCHEMA_VERSION,
            "ref_id": chunk.ref_id,
            "kind": "product_docs",
            "resource_kind": "chunk",
            "title": chunk.title,
            "summary": _summary_for_query(chunk.text, terms),
            "score": float(score),
            "rank": index,
            "read_endpoint": chunk.read_endpoint,
            "metadata": _chunk_metadata(chunk, snapshot),
        }
        for index, (score, chunk) in enumerate(hits[:top_k], start=1)
    ]


def read_product_docs_resource(raw_ref: str) -> dict[str, Any]:
    """Resolve one `product_docs:chunk:<chunk_id>` resource ref."""

    chunk_id = _parse_product_docs_raw_ref(raw_ref)
    snapshot = load_product_docs_snapshot()
    for chunk in snapshot.chunks:
        if chunk.chunk_id == chunk_id:
            return {
                "kind": "product_docs",
                "project_id": None,
                "title": chunk.title,
                "content": chunk.text,
                "metadata": _chunk_metadata(chunk, snapshot),
                "ref_id": chunk.ref_id,
            }
    raise KeyError(f"Product docs chunk not found: {chunk_id}")


def _snapshot(
    *,
    source_path: str,
    source_hash: str,
    content_hash: str,
    loaded: bool,
    manifest_loaded: bool,
    load_status: str,
    updated_at: str,
    source_files: list[ProductDocSource],
    chunks: list[ProductDocChunk] | None = None,
    manifest: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> ProductDocsSnapshot:
    return ProductDocsSnapshot(
        package_id=PRODUCT_DOCS_PACKAGE_ID,
        source_path=source_path,
        source_hash=source_hash,
        content_hash=content_hash,
        loaded=loaded,
        manifest_loaded=manifest_loaded,
        load_status=load_status,
        updated_at=updated_at,
        title="Product Documentation",
        description="Repo-local README and product documentation for Scholar AI.",
        source_files=list(source_files),
        chunks=list(chunks or []),
        manifest=dict(manifest or {}),
        warnings=list(warnings or []),
        runtime_consumers=_runtime_consumers(),
    )


def _discover_sources(root: Path) -> list[Path]:
    sources: list[Path] = []
    for pattern in _DOC_SOURCE_PATTERNS:
        for path in sorted(root.glob(pattern), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            relative = _safe_relative(path, root)
            if any(part in _EXCLUDED_DOC_PARTS for part in relative.parts):
                continue
            if path not in sources:
                sources.append(path)
    return sources


def _read_bounded_source(path: Path) -> str:
    size = path.stat().st_size
    if size > MAX_PRODUCT_DOC_BYTES:
        raise OSError(f"file exceeds {MAX_PRODUCT_DOC_BYTES} bytes")
    return path.read_text(encoding="utf-8")


def _source_role(root: Path, path: Path) -> str:
    relative = _repo_relative(path, root)
    if relative == "README.md":
        return "readme"
    return "product_doc"


def _source_record(root: Path, path: Path, role: str, *, text: str, warning: str | None = None) -> ProductDocSource:
    loaded = warning is None and bool(text)
    return ProductDocSource(
        relative_path=_repo_relative(path, root),
        role=role,
        loaded=loaded,
        content_hash=_sha256_text(text) if loaded else "unknown",
        char_count=len(text) if loaded else 0,
        byte_count=len(text.encode("utf-8")) if loaded else 0,
        updated_at=_path_updated_at(path) if path.exists() else "unknown",
        warning=warning,
    )


def _build_chunks(root: Path, file_payloads: list[tuple[Path, str, str]]) -> list[ProductDocChunk]:
    chunks: list[ProductDocChunk] = []
    for path, role, text in file_payloads:
        if not text.strip():
            continue
        relative_path = _repo_relative(path, root)
        source_hash = _sha256_text(text)
        for index, (span_start, span_end, chunk_text) in enumerate(_markdown_chunks(text), start=1):
            if not chunk_text.strip():
                continue
            chunk_id = _chunk_id(relative_path, index, span_start, span_end)
            chunks.append(
                ProductDocChunk(
                    chunk_id=chunk_id,
                    title=_title_from_text(chunk_text, fallback=Path(relative_path).stem),
                    source_path=relative_path,
                    source_role=role,
                    source_hash=source_hash,
                    content_hash=_sha256_text(chunk_text),
                    span_start=span_start,
                    span_end=span_end,
                    text=chunk_text.strip(),
                )
            )
    return chunks


def _markdown_chunks(text: str) -> list[tuple[int, int, str]]:
    stripped = str(text or "")
    if not stripped:
        return []
    starts = [match.start() for match in re.finditer(r"(?m)^#{1,3}\s+\S", stripped)]
    if not starts or starts[0] != 0:
        starts.insert(0, 0)
    chunks: list[tuple[int, int, str]] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(stripped)
        chunk_text = stripped[start:end].strip()
        if chunk_text:
            chunks.append((start, end, chunk_text))
    return chunks


def _chunk_id(relative_path: str, index: int, span_start: int, span_end: int) -> str:
    digest = hashlib.sha256(f"{relative_path}:{index}:{span_start}:{span_end}".encode("utf-8")).hexdigest()
    stem = Path(relative_path).stem.lower().replace("_", "-")
    safe_stem = re.sub(r"[^a-z0-9.-]+", "-", stem).strip("-") or "doc"
    return f"{safe_stem}-{index}-{digest[:16]}"


def _chunk_metadata(chunk: ProductDocChunk, snapshot: ProductDocsSnapshot) -> dict[str, Any]:
    return {
        "knowledge_ref_schema_version": PRODUCT_DOCS_REF_SCHEMA_VERSION,
        "ref_id": chunk.ref_id,
        "package_id": snapshot.package_id,
        "resource_kind": "chunk",
        "source": "product_docs",
        "source_type": "product_markdown",
        "source_path": chunk.source_path,
        "source_role": chunk.source_role,
        "source_hash": chunk.source_hash,
        "content_hash": chunk.content_hash,
        "package_content_hash": snapshot.content_hash,
        "span_start": chunk.span_start,
        "span_end": chunk.span_end,
        "read_endpoint": chunk.read_endpoint,
        "runtime_consumers": [dict(item) for item in snapshot.runtime_consumers],
    }


def _parse_product_docs_raw_ref(raw_ref: str) -> str:
    normalized = str(raw_ref or "").strip()
    parts = normalized.split(":")
    if len(parts) != 2 or parts[0] != "chunk":
        raise ValueError("product_docs refs must use chunk:<chunk_id>")
    return _normalize_chunk_id(parts[1])


def _normalize_chunk_id(chunk_id: str) -> str:
    normalized = str(chunk_id or "").strip()
    if not normalized:
        raise ValueError("chunk_id must not be empty")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError("chunk_id must not contain control characters")
    if "/" in normalized or "\\" in normalized or ".." in normalized:
        raise ValueError("chunk_id must be a stable id, not a path")
    return normalized


def _manifest(
    root: Path,
    source_records: list[ProductDocSource],
    chunks: list[ProductDocChunk],
) -> dict[str, Any]:
    return {
        "source_patterns": list(_DOC_SOURCE_PATTERNS),
        "excluded_parts": sorted(_EXCLUDED_DOC_PARTS),
        "runtime_mutability": "read_only",
        "source_count": len(source_records),
        "loaded_source_count": sum(1 for source in source_records if source.loaded),
        "chunk_count": len(chunks),
        "source_paths": [source.relative_path for source in source_records],
        "repo_root_name": root.name,
    }


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", query.lower())
    return [term for term in terms if term]


def _score_chunk(chunk: ProductDocChunk, terms: list[str], query: str) -> int:
    text = chunk.text.lower()
    title = chunk.title.lower()
    score = 0
    for term in terms:
        score += text.count(term)
        if term in title:
            score += 3
        if term in chunk.source_path.lower():
            score += 2
    if query.lower() in text:
        score += 5
    return score


def _summary_for_query(text: str, terms: list[str], *, max_chars: int = 420) -> str:
    clean_text = " ".join(str(text or "").split())
    if len(clean_text) <= max_chars:
        return clean_text
    lower_text = clean_text.lower()
    first_hit = min((lower_text.find(term) for term in terms if lower_text.find(term) >= 0), default=0)
    start = max(0, first_hit - 80)
    end = min(len(clean_text), start + max_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clean_text) else ""
    return f"{prefix}{clean_text[start:end].strip()}{suffix}"


def _title_from_text(text: str, *, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title[:300]
    return fallback.replace("-", " ").replace("_", " ").strip().title() or "Product Documentation"


def _combined_source_hash(root: Path, file_payloads: list[tuple[Path, str, str]]) -> str:
    payload = [
        {
            "relative_path": _repo_relative(path, root),
            "role": role,
            "content_hash": _sha256_text(text),
        }
        for path, role, text in file_payloads
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _combined_runtime_content_hash(chunks: list[ProductDocChunk]) -> str:
    payload = [
        {
            "chunk_id": chunk.chunk_id,
            "source_path": chunk.source_path,
            "source_hash": chunk.source_hash,
            "content_hash": chunk.content_hash,
            "span_start": chunk.span_start,
            "span_end": chunk.span_end,
        }
        for chunk in chunks
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _latest_updated_at(paths: list[Path]) -> str:
    timestamps = [path.stat().st_mtime for path in paths if path.exists()]
    if not timestamps:
        return "unknown"
    return datetime.fromtimestamp(max(timestamps), tz=timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _path_updated_at(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
    except OSError:
        return "unknown"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _repo_relative(path: Path, root: Path | None = None) -> str:
    base = root or REPO_ROOT
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name
    except OSError:
        return path.as_posix()


def _safe_relative(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return Path(path.name)


def _runtime_consumers() -> list[dict[str, str]]:
    return [
        {
            "consumer": "literature_assistant.core.routers.knowledge_router",
            "use": "read-only package registry and product-doc search",
        },
        {
            "consumer": "literature_assistant.core.routers.agent_bridge_router",
            "use": "bounded resource loading through agent_resource_read",
        },
        {
            "consumer": "agent_mcp_server",
            "use": "MCP status/search/read tools and product-doc refs",
        },
    ]
